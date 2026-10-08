# Prototype implementation contract

Root workspace: `C:/Users/asus/Desktop/B4/meegle`. UI Traditional Chinese.

## API
- `GET /api/session`: `{user: User|null, users: User[], mode: "demo"|"lark", auth_configured: boolean}`. Demo-only `POST /api/demo/session` `{user_id}` sets signed session cookie. Initial local demo uses `u-pm`.
- `GET /api/workspace`: Workspace below. Authentication required except local explicitly enabled demo; no source credentials in response.
- `POST /api/actions`: `{action, version, request_id, project_id?, node_id?, task_id?, payload}` -> full updated Workspace. Server enforces version (409), role, stage gates; request_id idempotency. GET fresh Workspace after conflict. All successful actions write event. Errors `{detail: string}`.
- `POST /api/files`: multipart `file, project_id, node_id, direction` with `version` field -> full Workspace. Files stored server-side and authenticated `GET /api/files/{id}/download`.
- `GET /api/health`: health; `GET /api/auth/lark/login` and callback supported when configured.
- `GET /api/sources`: `{configured, last_sync, status, message, tables:[], records:[]}`. Auth required. `POST /api/sources/sync` reads only Lark sources and stores isolated source cache. Does not mutate demonstration projects or Lark.

## Workspace
`{version:number, as_of:string, users:User[], projects:Project[], approvals:Approval[], events:Event[], calendar:{holidays:string[],workdays:string[]}, source_status:{status,last_sync,message}}`

User `{id,name,role,department,avatar}`. Roles pm, manager, member. demo users `u-pm`, `u-field`, `u-control`, `u-map`, `u-report`, `u-manager`, `u-agent`.

Project `{id,code,name,client,pm_id,status,priority,due_date,original_due_date,created_at,started_at,description,contract_amount,estimated_points,source_url,source_kind,revision,nodes:Node[],files:File[],comments:Comment[],daily_reports:DailyReport[]}`. source_kind `demo` initially. Financial/points missing values nullable.

Node `{id,name,key,owner_id,collaborator_ids:[],status,start_date,due_date,original_due_date,started_at,completed_at,tasks:Task[]}`.
Node keys `sales,pm,confirmation,field,control,mapping,report,pricing,settlement`. statuses `pending,in_progress,completed,paused,superseded`.

Task `{id,title,owner_id,status,required,start_date,due_date,original_due_date,started_at,completed_at,points,work_item_id,description,input,output,comments:Comment[],revision}`. task status also `rework`. `input/output` strings; files separate.

Comment `{id,author_id,body,created_at}`. File `{id,name,node_id,direction,version,uploaded_by,created_at,size,url,storage}` direction input/output; storage local/link. DailyReport `{id,date,department,case_code,person,description,points,source_url}`.

Approval `{id,project_id,type,title,status,reason,node_id,task_ids:[],dates:[{task_id,due_date}],owner_confirmed,client_confirmed,lark_status,created_by,created_at,executed_at,reference_url,attachments:[],history:[]}`. type change/extension; status draft/pending/approved/executed/rejected/withdrawn; lark_status draft/pending/approved/rejected. changes only freeze selected work_item_id(s) and downstream same work_item_id; extensions never freeze work. Storing old tasks superseded + new revision tasks on execution. Dates updates strictly through approval execution; direct assignment only initial scheduling.

Event `{id,project_id,node_id?,task_id?,actor_id,action,message,created_at}`.

## Actions and payloads
- task_start / task_complete / task_return `{reason?,output?}`. task_complete requires current task owner or active explicitly seeded proxy; managers cannot bypass owner. required output nonempty; only designated stage inputs enforced, not whole upstream stage complete.
- task_update `{owner_id?,title?,start_date?,due_date?,points?,description?}`. Node owner/PM can assign; once due_date exists changes forbidden without extension. Original due set at initial schedule. task_add `{title,owner_id?,start_date?,due_date?,points?,required?,work_item_id?}` under node. task_update retains history.
- node_complete `{}` node owner only, all required active tasks completed, no relevant pending change; no blanket PM override.
- participants_update `{nodes:[{node_id,owner_id,collaborator_ids}]}` PM/manager; does not overwrite individually reassigned tasks.
- comment_add `{body}` project or node/task scope via ids.
- approval_create `{type,title,reason,node_id,task_ids,dates,reference_url?,attachments?}` creates draft. dates mandatory for extension; change supports dates for replacement tasks.
- approval_submit `{approval_id}` freezes impacted change tasks only; approval rejection leaves change paused until explicit resume.
- approval_confirm `{approval_id,party:"owner"|"client"}` simulation only. party owner means company supervisor, client means client.
- approval_lark `{approval_id,result:"approved"|"rejected"}` simulation only manager. For change approved requires all 3; extension Lark approved sufficient.
- approval_execute `{approval_id}` explicit assigned approver actor manager/PM; revision check, idempotent. Change creates replacement tasks preserving old; extension applies dates preserving originals.
- approval_withdraw `{approval_id}`; change_resume `{approval_id,reason}` explicit after rejection/withdrawal, owner/PM; no auto resume.
- file_link `{name,url,direction,version?}` node/project target, verified http(s).
- calendar_update `{holidays,workdays}` PM/manager. demo_reset `{}` manager only; explicitly confirmed UI, seed only demo workspace.

Backend owns schema implementation and informs frontend immediately if changes necessary. Frontend reads this contract and may show capability errors but must not fake persisted successful operations. All features operate on API-backed data. Bootstrap seed deterministic rich realistic Traditional Chinese scenarios and as_of for reproducible demo only. Production date is real Asia/Taipei.


## Shell and overview reads

These authenticated reads are enabled by `WORKSPACE_SHELL_ENABLED` and require `INDEX_TABLES_ENABLED` for indexed responses. `GET /api/session` advertises `features: {workspace_shell: true}` when shell mode is enabled; the flag-off response omits `features`.

### Shell workspace

`GET /api/workspace?scope=shell` returns `scope: "shell"`, `version`, `as_of`, `workspace_id`, `environment`, `users`, `calendar`, `source_status`, `file_categories`, `approval_connection`, `freshness`, and the following dashboard fields. `approvals` and `events` are empty arrays; read the full workspace on demand for their records.

- `projects`: slim visible case cards in workspace order, containing `id`, `code`, `name`, `client`, `pm_id`, `status`, `execution_status`, `due_date`, `case_type`, `source_kind`, `source_status`, `concurrency_version`, `progress: {completed_nodes, approved_skipped_nodes, total_nodes}`, `overdue_tasks`, `active_tasks`, and execution admission fields. No project trees (`nodes`, `files`, `comments`, `daily_reports`) or overview-only facts (`contract_amount`, `source_lifecycle`, `current_nodes`, `blocked_tasks`) are included.
- `counts`: integer `approvals_pending`, `daily_unmatched`, `my_overdue_tasks`, `my_active_tasks`, `active_tasks`, `overdue_tasks`, `due_today_tasks`, `blocked_tasks`. Task totals cover visible cases; `my_*` follows the user's execution authority, including valid delegation and business override. Open tasks exclude `completed` and `superseded`.
- `attention`: at most five open overdue or due-today tasks, overdue first, then workspace project/node/task order (task ID breaks ties).
- `blocked`: a separate list of at most five open tasks with status `paused` or `blocked`, including undated and future-dated tasks, in project/node/task order with task ID as tie-breaker. `counts.blocked_tasks` counts the entire visible set, not just these five. Unmet input dependencies alone do not qualify. `attention` keeps its existing meaning; the two lists may overlap.
- Both task lists use exactly `{task_id, project_id, node_id, node_key, node_name, assignee_id, status, due_date, project_code, project_name, title}`. An undated task has `due_date: ""`.
- `pending_approvals`: at most two visible pending applications as `{id, title, type, project_id}`; `counts.approvals_pending` covers all visible pending applications.

A shell response carries a weak `ETag`. A matching `If-None-Match` returns an empty 304 response with the same ETag; validators vary with workspace, identity/authority, version, date and users. Responses use `Cache-Control: no-store`; clients may retain the body and explicitly revalidate. When the flag is off or the index is missing/stale/not backfilled, this endpoint falls back to the full workspace (without `scope: "shell"`). Clients must inspect the returned scope. A write while index maintenance is disabled leaves the index unavailable across later unrelated saves until a complete backfill or reconcile/repair restores the generation; re-enabling the flag alone is insufficient.

### Paged case overview

`GET /api/projects?view=overview&tab=all|formal|intake|active|overdue|completed&sort=due|name|progress&dir=asc|desc&q=&status=&owner=&offset=0&limit=30` returns `{total, offset, limit, facets: {all, formal, intake}, items: ProjectCard[]}`. Defaults are `tab=formal`, `sort=due`, `dir=asc`, `offset=0`, `limit=30`; offset must be nonnegative and limit is 1–100. Invalid queries or a disabled shell feature return 422; an index that is not ready returns 503 with no full-workspace fallback.

Search matches code/name/client (literal wildcard characters); `owner` filters PM and `status` filters indexed case status. The `overdue` tab selects cases with overdue tasks, not every paused/blocked case. Facets count all visible cases independent of search and filters. Due and progress sorting use case ID to break ties; direction applies to ties too.

Each overview item contains all shared shell-card fields with identical values, plus:

| Field | Type | Presence and meaning |
|---|---|---|
| `contract_amount` | number or null | Always present; null means unset. Same amount as the full workspace for every user who can see the case, including members; no extra finance-role read gate. |
| `source_lifecycle` | `{relationship: string, state: "mapped" or "needs_verification", canonical: string or null, reasons: string[]}` | Omitted when the project has no lifecycle (including non-governed demo cases), never substituted with null. Compact projection excludes source IDs, `lifecycle_sources`, `blank_sources` and `quote_workflow`. |
| `current_nodes` | `{key: string, name: string, status: "in_progress" or "paused"}[]` | Always present; current refreshed stages in node order, empty when none. |
| `blocked_tasks` | integer ≥ 0 | Always present; this visible case's open tasks whose status is paused/blocked, regardless of due date. Does not inspect input dependencies. |

Visibility filters apply before listing and aggregation: excluded/history and source-review cases are not exposed in production overview cards, shell lists or blocked totals. Facts are maintained on workspace writes; finance approval, stage transitions and pauses update subsequent overview reads without a manual backfill. Older servers can omit these additive fields; clients retain missing-field fallbacks.

### Single case detail

`GET /api/projects/{id}` returns `{scope: "project", version, as_of, project, ...caseRecords}`: one full visible project tree plus its case records and global templates/catalogues, projected with the same privacy rules as the full workspace. Shared shell metadata is not repeated. A missing/invisible project, or a disabled shell feature, returns 404. Full lifecycle details remain available in the project tree. Shared quotes, confirmations and contract items are included when related to the requested case and every related case is workspace-visible; authorization uses authoritative workspace-wide project headers, independently of the one loaded tree.

Contract evidence: `backend/test_projects_overview.py` covers shared-card parity, nullable amount/lifecycle omission, current stages, status-blocked counts, member/manager parity, visibility, write maintenance, paging/filter/sort validation and fixed query count at page sizes 10/100. `backend/test_shell.py` covers feature gating, fallback, ETag/304, counts/visibility, undated/future blocked tasks, exact task-list keys and the five-item ordering/limit.
