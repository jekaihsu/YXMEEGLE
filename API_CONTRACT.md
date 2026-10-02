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
