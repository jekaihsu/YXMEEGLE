# Node assignment and tasks in V4 (2026-10-14)

Per-case node owners, approvals and tasks live in two V4 Lark Base tables. The web app reads and writes them with the company application identity. The workspace JSON, `project['nodes']` and the workspace version are untouched. Node-assignment data is a separate read model keyed by case code and node key, and it reaches the browser only through the routes below.

## Switches

The feature is off unless `NODE_ASSIGNMENT_ENABLED=true`. While off, every route answers 404 with code `disabled` and never contacts Lark.

| Variable | Default | Meaning |
| --- | --- | --- |
| `NODE_ASSIGNMENT_ENABLED` | `false` | Feature flag |
| `NODE_ASSIGNMENT_BASE_TOKEN` | `H7W6b0PFWaVF1BsgqXJj3pQ9pXb` | V4 Base |
| `NODE_ASSIGNMENT_NODE_TABLE_ID` | `tblcPZPmezkyeVb7` | 節點指派 |
| `NODE_ASSIGNMENT_TASK_TABLE_ID` | `tblsoyGcC6K5AipF` | 任務 |
| `NODE_ASSIGNMENT_PEOPLE_TABLE_ID` | `tblfaCO2xPUNptQH` | V4 人員名單, read only |
| `NODE_ASSIGNMENT_CONFIRMATION_TABLE_ID` | `tblmSQrcCs9vPQZx` | 工程確認單, used only to build the link |
| `NODE_ASSIGNMENT_READ_TTL_SECONDS` | `60` (5 to 300) | Case read cache |
| `NODE_ASSIGNMENT_ROSTER_TTL_SECONDS` | `120` (30 to 900) | Roster cache; writes need a roster no older than this |
| `NODE_ASSIGNMENT_STALE_MAX_SECONDS` | `900` (60 to 3600) | Oldest data served as stale after a Lark failure |
| `NODE_ASSIGNMENT_LOCK_TIMEOUT_SECONDS` | `10` (1 to 30) | Wait for another write on the same node |

The feature also needs the existing application settings `LARK_WORKER_IDENTITY=application`, `LARK_APP_ID`, `LARK_APP_SECRET` and `LARK_WORKER_ORGANIZATION`. Lark requests share the live-read rate bucket (`LARK_LIVE_READ_MAX_RPS`). Only the formal workspace `lark-<organization>` with environment `production` can use it. Writes also require the workspace setting `external_enabled`.

The only writable formal tables are listed in `FORMAL_WRITE_ALLOWLIST` in `backend/remote_policy.py`. A table ID set by environment outside that list makes the feature answer 503 `lark_unconfigured`, and the client refuses the write before any request.

## Lark application permissions

Application identity (tenant token) scopes:

- `bitable:app` to create and update records in 節點指派 and 任務. Reads are covered by the same scope.
- `bitable:app:readonly` is already used by live reads and is sufficient for the GET routes alone.

Base access:

- Add the application to the V4 Base with edit permission (Base share menu, add document app, can edit).
- If V4 uses advanced permissions, the application's role needs add and edit on 節點指派 and 任務, and read on 人員名單 for 姓名, 所屬組別, 職級, 在職 and Lark帳號.

A Lark permission failure (codes 99991672, 1254302, 91403, or HTTP 401/403) is answered with code `lark_permission` and `missing_scopes`, and the server log line `node_assignment lark permission denied` names the code, path and missing scopes.

## Routes

All routes sit under `/api/projects/{project_id}/node-assignments`. Mutations need the signed session, pass the same-origin guard, and carry a `request_id` (1 to 120 characters). Bodies are limited to 16 KB.

| Method | Path | Body |
| --- | --- | --- |
| GET | (the prefix itself) | none |
| GET | `/nodes/{key}` | none |
| POST | `/nodes/{key}/claim` | `{request_id, expected_revision}` |
| POST | `/nodes/{key}/assign` | `{request_id, expected_revision, owner_open_ids: [1..20]}` |
| POST | `/nodes/{key}/complete` | `{request_id, expected_revision}` |
| POST | `/nodes/{key}/approve` | `{request_id, expected_revision}` |
| POST | `/nodes/{key}/reject` | `{request_id, expected_revision, reason (1..500)}` |
| POST | `/nodes/{key}/tasks` | `{request_id, title (1..200), detail? (..2000), assignee_open_id?, deadline? YYYY-MM-DD, department?}` |
| PATCH | `/nodes/{key}/tasks/{task_id}` | `{request_id, expected_revision, status?, assignee_open_id?, deadline?, detail?}` |
| GET | `/start-sop` | none |
| POST | `/start-sop` | `{request_id, preview_hash}` |

`key` is one of `sales, pm, confirmation, field, control, mapping, report, pricing, settlement`. `expected_revision` is the `revision` from the last read, or `null` for a node that has no Lark row yet.

### Case overview

```json
{
  "project_id": "p1", "code": "A115001-01",
  "summary": {"done": 1, "total": 8, "current_node": "confirmation"},
  "nodes": [{
    "key": "field", "label": "外業", "departments": ["外業", "水深A"],
    "record_id": "rec...", "revision": "3f2a9c0d1b7e4a55",
    "status": "進行中", "derived_status": "進行中",
    "tasks": {"done": 1, "total": 3}, "progress": 0.3333,
    "owners": [{"open_id": "ou_...", "name": "王外業"}], "assignment_method": "主管指派",
    "assigned_by": {"open_id": "ou_...", "name": "林經理"},
    "approver": null, "approved_at": null, "reject_reason": null,
    "started_at": "2026-10-14T09:00:00+08:00", "finished_at": null,
    "deadline": "2026-10-20", "warnings": []
  }],
  "can": {"field": {"claim": false, "assign": true, "complete": true, "approve": false, "reject": false, "create_task": true}},
  "warnings": [], "stale": false, "stale_reason": null, "fetched_at": "2026-10-14T09:00:05+08:00",
  "roster": {"available": true, "stale": false},
  "writes_enabled": true, "writes_disabled_reason": null
}
```

`derived_status` is authoritative. `status` is the value stored in the Lark 狀態 column; the app keeps it in step on every write, and a difference is flagged with the node warning `lark_status_drift`.

### Node detail and mutation responses

`GET /nodes/{key}` and every successful mutation return the same envelope with `node` (one node object as above), `can` (that node's actions), `summary`, `tasks` and `assignable_people`. A mutation response also carries `record_id` of the row it wrote. A replayed mutation returns the stored body with the header `Idempotent-Replayed: true`.

```json
{
  "tasks": [{
    "id": "rec...", "revision": "9b0c1d2e3f405162", "title": "控制點佈設", "detail": "北側 12 點",
    "assignee": {"open_id": "ou_...", "name": "陳水深"}, "assigned_by": {"open_id": "ou_...", "name": "林經理"},
    "department": "水深B", "deadline": "2026-10-20", "status": "進行中",
    "done_at": null, "created_at": "2026-10-14T09:10:00+08:00",
    "can": {"edit_status": true, "cancel": false, "assign": false, "claim": false, "edit_details": false}
  }],
  "assignable_people": [{"open_id": "ou_...", "name": "陳水深", "departments": ["水深B"]}]
}
```

`assignable_people` is filled only for someone who manages the node.

### Errors

Errors are `{detail, code, ...}` with `detail` in Traditional Chinese.

| Code | HTTP | Meaning |
| --- | --- | --- |
| `disabled` | 404 | Flag off, or not the formal production workspace |
| `not_found` | 404 | Unknown node, task, or a case without a confirmation code |
| `forbidden` | 403 | Role does not allow the action; audited as denied |
| `writes_disabled` | 403 | `external_enabled` is off, or a table outside the write allowlist |
| `invalid` | 422 | Body failed validation |
| `payload_too_large` | 413 | Body over 16 KB |
| `rate_limited` | 429 | More than 30 Lark writes per person or 300 per company in a minute. Every outbound create or update counts once; replays, no-op presses and denied attempts cost nothing |
| `illegal_transition` | 409 | Not allowed from the current status |
| `revision_conflict` | 409 | Someone changed the row since `expected_revision`; `current_revision` included |
| `duplicate_assignment_key` | 409 | More than one row for one 指派鍵; `record_ids` included, nothing is picked |
| `idempotency_conflict` | 409 | The `request_id` was used with a different body |
| `readback_mismatch` | 409 | The written values did not read back; replay the same `request_id` to reconcile |
| `busy` | 409 | Another write on the same node did not finish in time |
| `preview_stale` | 409 | 啟動 SOP: the plan or a quote deadline changed since the preview |
| `nothing_to_start` | 409 | 啟動 SOP: no confirmation code or no planned quantity; `blockers` included |
| `outcome_unknown` | 502 | Lark did not confirm a write; replay the same `request_id` to reconcile |
| `lark_permission` | 502 | Lark scope or Base permission missing; `lark_code`, `missing_scopes` included |
| `lark_error` | 502 | Lark rejected a request or returned incomplete pages |
| `lark_unavailable` | 503 | Lark down, rate limited or timed out |
| `lark_unconfigured` | 503 | Application identity or table configuration missing |
| `roster_unavailable` | 503 | Writes paused because the roster cannot be refreshed |

## Status model

The nine nodes form one chain, 業務 to 結算. Status is derived per node in this order.

1. 略過 when the app's existing approved skip (`approved_skipped` with a valid waiver) applies. Never written here.
2. 已完成 when Lark holds 狀態 已完成 with 核准人 and 核准時間.
3. 未開始 when the previous node is neither 已完成 nor 略過.
4. 進行中 while a rejection (退回原因) is active.
5. 待審核 when at least one task is not cancelled and every such task is 已完成.
6. 進行中 when any task is 進行中 or 已完成.
7. 待處理 otherwise.

Task counts are done tasks over tasks that are not cancelled. The case summary counts 已完成 nodes over nine, with 略過 nodes removed from both sides.

Rejecting a 待審核 or 已完成 node sets 退回原因 and clears 核准人, 核准時間 and 完成時間. The rejection holds the node at 進行中 until a task on it is completed again, which clears 退回原因. Reopening never writes to later nodes; the response warns `later_nodes_started` when a later node is 進行中, 待審核 or 已完成.

Read caches use stale-while-revalidate: first reads load synchronously, with roster and case requests running concurrently through the shared rate bucket. Within the soft TTL reads are fresh; beyond it, entries up to `NODE_ASSIGNMENT_STALE_MAX_SECONDS` return immediately with `stale: true, stale_reason: "refreshing"` while one daemon refresh per key runs. Refresh failures are logged and do not fail that read. Older entries must load synchronously. Roster soft TTL remains 120 seconds; successful roster schema checks are cached for 10 minutes, failures are never cached. Writes still require a fresh case and a roster within its soft TTL, verify read-back, and replace the case cache after success.

The overview adds `node_details`, keyed by all nine node keys, each containing `tasks` and `assignable_people` exactly as the node detail endpoint does (empty lists where applicable). People are visible only to actors who manage that node. Existing overview fields and the node detail endpoint remain unchanged.

Read duration logs use `node_assignment read overview ms=<total> cache=<hit|stale|miss> lark_calls=<n>` (or `read detail`), without identities or tokens; calls count Bitable attempts, excluding token minting. Session responses expose `features.node_assignment: true` only when the deployment flag is enabled and application identity, organization, credentials and approved table targets are configured, independently of `workspace_shell`.

## Who may act

| Action | Allowed for | From status |
| --- | --- | --- |
| claim | Employed member of the node's departments, node has no owner | any open |
| create_task | Members (for themselves) and managers (any eligible assignee) | any open |
| assign | Manager | any open |
| complete | Manager | 待處理, 進行中, 待審核 |
| approve | Manager | 待審核 |
| reject | Manager | 待審核, 已完成 |

A manager is an employed 經理 whose 所屬組別 meets the node's departments, any employed 副總 or 老闆, or a person with the server company-admin business grant (`can_business_override`). For ordinary node work, server-session system administrators (`manager` role or `can_manage_roles`) also manage every node as an explicit exception to independent business authority; this never substitutes financial/native approval seats. Assignees must be employed members of the node's departments. Open means any status except 已完成 and 略過; tasks are frozen once the node is 已完成 or 略過.

## Write safety

Each write runs under a lock for its 指派鍵, re-checks the session and a fresh roster inside the lock, and plans against a fresh Lark read. A missing node row is created with the workflow's 指派鍵 by search, create once, search again; a second row is reported as `duplicate_assignment_key`. A pending receipt is stored before the first remote write. Every write is read back and compared. An uncertain create or update stays pending, and a replay of the same `request_id` reconciles it by reading instead of sending it again. Each success, denial and failure writes an audit row with actor, request ID, and before and after values, without tokens.

## Case detail links and projection additions

The canonical home target uses the existing hash route.

```text
#view=project&project=<stable-project-id>&tab=flow&node=<node-key>&task=<lark-task-record-id>
```

Encode every value with `encodeURIComponent`. `project` is the authorized workspace project ID. It is not a case code or confirmation record ID. `node` is one of the nine keys listed in Routes. `task` is optional and is the task's Lark `rec...` record ID. `tab=tasks` opens the task list with the same target contract.

The case page expands the selected Lark node, scrolls its detail into view, and gives keyboard focus to that detail. When `task` is present, it scrolls to the task, focuses its row, and expands its source details. Reduced motion uses immediate scrolling. A task-only hash can discover the node from the overview's authorized `node_details`. Send both identifiers from home so that older overview payloads also locate the node.

Legacy `node=<workspace-node-id>&task=<workspace-task-id>` links retain the local task inspector. A Lark node key selects the assignment panel and does not open the local completion dialog. A missing remote task shows a scoped error. A disabled assignment feature shows an unavailable message and labels the remaining local workflow separately. Neither case visibility nor mutation authorization changes.

The top-level router still reads the hash. This change does not add `assignment_node` or `assignment_task` aliases and does not add query-only routing. Link creators must use the hash contract above.

Node responses add `assignment_key`, `origin=lark`, `deadline_basis=related_tasks_max`, and `next_due`. `deadline` keeps the latest deadline among non-cancelled related tasks, including completed tasks. `next_due` is the earliest deadline among tasks that are neither completed nor cancelled. Both values are null when the relevant set has no date. Nodes have no native 截止日 field.

Task details sort all authorized tasks before rendering. Open overdue tasks come first using the Taipei calendar date. Deadline ascending follows, with null dates last. Status priority is 進行中, 待處理, 已完成, 取消. Record ID is the stable final tie-breaker. The client uses the same ordering for the combined task tab.

The client preserves `fetched_at` and `stale_reason`. Panels identify `fetched_at` as the workbench read time, not the Lark modification time. The nine-node summary and each node's task counts remain the existing Lark read model. Local SOP templates appear in an expandable section and do not change those counts.

Assignment reads start when flow, tasks, or assignment participants become visible. Hover or keyboard focus can prefetch after 150 ms. Save Data and slow 2G connections disable extra prefetch. Overview responses still contain the existing embedded `node_details`. This stream does not change the service to omit those fields. Successful writes still use version checks, idempotent request IDs, remote readback, and the existing server permissions.

## 啟動 SOP

A project lead previews, then confirms, and the app seeds one 節點指派 row and ONE 任務 row for each production category with a planned quantity. Categories map to nodes 外業 `field`, 控制 `control`, 圖資 `mapping`, 報告 `report`. Each node costs at most three Lark writes: the node row create, the task create, and the same node sync every task create runs (進度, and 開始時間 once work has started), so one press writes at most 12 times. Node status stays derived from the nine-node chain: the operation never forces a status, and the sync only mirrors the derived one onto the row.

**Source.** Quantities, line and item counts and link-basis counts come from `state['derived_plan'][project_id]` (`plan_summary`). A category with a planned quantity of 0 is absent. Deadlines come from the project's quotes (direct `project_id`/`project_ids`, or through the case's confirmations, as `frontend/src/sourceQuotes.ts projectQuotes` does) using 外業期限, 內業期限(控), 內業期限(圖), 內業期限(報), normalized with `sources.day()`. If dated quotes disagree on a node's date, the deadline is null and the warning `deadline_conflict` names the dates. Nothing is picked.

**Seed task.** Unassigned, status 待處理, 指派人 is the person who pressed start. Title `<外業|控制|圖資|報告>：依計畫數量完成`. Detail lists the planned quantity, contract lines and items, link-basis counts and the node's warnings, and ends with the marker `[SOP-START:v1:<node key>]`. Department is the first of the node's departments (外業, 控制, 圖報A, 圖報A) because existing task creation requires one of them. A node counts as seeded when any non-cancelled task of that node carries its marker. A manually created task without the marker does not count, and a 已完成 or 略過 node gets its row but no task (`task: "skipped"`).

**Who.** The system administrator (`can_manage_roles`), the project's PM or supervisor, the node's supervisor, or a manager of the node's departments (the same rule as `Actor.manages`). A project lead who is not an employed person in the roster is refused unless they hold the system-admin or business override (the rule of `plan_patch_task`), and the pressing account must be a Lark open id because it is written as 指派人. Authority is checked per node. Everyone else gets 403 `forbidden` with a Chinese reason, audited as `node_assignment.start_sop` with result `denied`.

**Blockers** (`eligible` is true only with none and at least one row to write): `disabled`, `writes_disabled` (workspace `external_enabled` off), `no_confirmation_code`, `no_planned_quantity`, `forbidden`, `lark_unavailable`. The flag-off case answers 404 `disabled` like every route, so `disabled` is not sent as a blocker. `can_start` is true only when the caller may start at least one node, so the frontend gates the button on it instead of re-implementing authority (it is also false while the case cannot be read). **Warnings** never block: `no_pm`, `deadline_conflict`, `ambiguous_links`, `needs_review`, `derived_links`, `plan_truncated`. `items_basis.unlinked` also counts native links that could not be resolved.

**Preview** (`GET`, same authorization and caches as the other reads, never writes):

```json
{"project_id": "p1", "code": "A115001-01", "eligible": true, "can_start": true, "already_started": false,
 "blockers": [{"code": "forbidden", "message": "..."}],
 "warnings": [{"code": "deadline_conflict", "message": "...", "node": "field"}],
 "nodes": [{"key": "field", "label": "外業", "category": "外業", "planned_qty": "123.45", "lines": 2, "items": 5,
   "items_basis": {"native": 5, "derived": 0, "ambiguous": 0, "unlinked": 0}, "deadline": "2026-10-30",
   "node_exists": false, "seed_task_exists": false, "will_create_node": true, "will_create_task": true,
   "task_title": "外業：依計畫數量完成", "task_detail": "..."}],
 "chain_note": "...", "preview_hash": "<sha256>", "plan_rule_version": "contract-links-20261017.1"}
```

`preview_hash` is the sha256 of the canonical JSON of the project id, the confirmation code and each node's quantity, counts, deadline, task title and detail plus both rule versions. It does not include Lark state, so it stays the same while a run progresses and a changed plan or quote makes it stale.

**Run** (`POST`, body `{request_id, preview_hash}`) answers `{"started", "complete", "results": [{"key", "node": "created|existing|failed", "task": "created|existing|failed|skipped", "error"}], "overview": <case overview>}`. `started` is true when this call created a row. Before writing it checks, in order, `writes_disabled` (403), a stored result for the `request_id` (replayed with `Idempotent-Replayed`, or `idempotency_conflict` for a different body), `nothing_to_start` (409), `forbidden` (403) and `preview_stale` (409).

Each node runs as its own write under that node's lock with the request id `start-sop:<request_id>:<key>`, so it gets the fresh read, duplicate protection, read-back and pending-receipt reconcile of the other writes, and each Lark write it makes counts against the rate limit (a full press of four new nodes is 12 writes, so a person can fully press about two projects a minute). Each result is read from what actually reached Lark, so a node row that landed while its task failed reports `node: created` (or `existing`), `task: failed` and the task's `error`. A partial failure answers 200 with `complete: false`; an HTTP error is returned only when nothing at all was created. Repeating the same `request_id` resumes: finished nodes replay their stored result and an uncertain write is reconciled by reading. A new press re-plans from Lark and finds the markers. A Lark failure on every node answers with that failure (`lark_permission`, `lark_error`, `outcome_unknown`, `busy`, `rate_limited`, ...). `lark_permission`, `lark_unavailable`, `rate_limited` and similar stop the run, and the remaining nodes report the same `error`.
