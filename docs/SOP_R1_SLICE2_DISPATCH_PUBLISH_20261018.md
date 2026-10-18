# SOP R1 slice 2: dispatch draft, preview, approval and publish (C04-C06 minimal)

Builds on `docs/SOP_R1_SLICE1_DISPATCH_BOARD_20261018.md`. Source handoff: `YX_SOP_R1_Implementation_Handoff_v1.0.md` sections 2.2 steps 3-7, 4, 4.1.
Scope: a dispatcher can turn one execution task into a published V4 任務 row with a crew, one interval and resources, through preview, approval seats and a command that survives timeouts and restarts. Everything is behind `DISPATCH_WRITE_ENABLED` (default off) and the existing workspace gate `settings.external_enabled`. Real writes are never run by tests.

## Authority (handoff 4.1)

- V4 任務 owns the published task and schedule facts (the 21 fields created 2026-10-18, spec `scripts/v4/task_extension_fields.json`).
- The workbench DB owns commands, reservations, previews and approval decisions. It holds no second editable copy of the task or schedule. Read models stay projections.
- Success is reported only after a read-back of the task row matches the command. A 202, a timeout or a mismatching read-back never shows `confirmed`.

## Data shapes (name these first)

```
Proposal      {project_ref, case_ref?, title, kind="execution", parent_task_ref?, group,
               primary_owner (person_ref), crew [person_ref] (owner included once),
               start, end (datetime, [start,end) exclusive end), est_person_hours,
               instruments [ref], vehicles [ref], note}
Preview       {preview_id, preview_hash, expires_at, proposal, source_vector (schedule fetched_at,
               tasks fetched_at, schema version), feasibility per crew/resource using slice-1 enums,
               conflicts [{kind, ref, other_slot_or_task, interval}], warnings, required_seats,
               can_commit, blockers [code]}
ApprovalSeat  group_leader_confirmed (B04) | manager_review (B05) | pm_final (B05)
Decision      {preview_hash, seat, actor, decision accepted|returned, reason, at}   append-only
Command       {command_id (client idempotency key), preview_hash, actor, state, task_record_id?,
               revision, receipt?, created_at, updated_at}
command_result  pending | committed | failed | outcome_unknown | reconciliation_required | rejected
planning_status unassigned | draft | pending_approval | publishing | confirmed | conflict | cancelled
Reservation   {resource_kind person|instrument|vehicle, ref, start, end, command_id, state held|released}
```

## Rules

1. **Interval and crew.** One continuous [start,end) per execution task. The primary owner belongs to the crew and counts once. Booked person-hours = crew size x hours; a person is counted once.
2. **Feasibility.** Reuse slice-1 rules. Unknown qualification or leave stays `unknown`. A crew member or required resource with `conflict` or `unavailable` blocks commit. `unknown` blocks commit unless the policy value `DISPATCH_ALLOW_UNKNOWN=true` (default false); the dispatcher must then record a manual verification reason per unknown item in the preview request, which is stored with the decision. Capability has no source, so by default every commit is blocked until a verification is recorded or the policy is relaxed. This is intentional.
3. **Occupancy.** Published 任務 rows with 預定開始/預定結束 and 排程狀態 in {已確認, 發布中} and live reservations count as bookings, in addition to 工作預排 rows. Overlap of two real timed intervals is `conflict`; date-only legacy rows stay `unknown`.
4. **Approval.** Handoff 4/B04/B05: group leader confirmation, then required manager review and PM final confirmation, all on the same `preview_hash`. Seats are configured per workspace by role name; the default requires all three and the dispatcher cannot satisfy two seats. A returned decision blocks that hash. Changing any proposal field changes the hash and voids prior decisions. Direct publish is only available when `DISPATCH_APPROVAL_POLICY=direct` is explicitly set. Seat holders are named in settings; no seat holder means commit returns `approval_not_configured`.
5. **Commit.** `POST /api/v2/dispatch/commits {command_id, preview_id}`. Steps in one local transaction: verify the stored preview (hash, not expired, source vector still current, required seats accepted), take reservations atomically (exclusive overlap check across processes; a loser gets 409 and keeps its draft), insert the command as `pending` BEFORE any remote effect. Then call Lark once with `client_token = command_id` to create (or update when `task_record_id` exists) the 任務 row, then read it back and compare every written field. Match => `committed`, planning_status 已確認, reservations stay `held` as the live record. Remote error with no evidence of landing => `failed`, reservations released. Timeout or ambiguous response => `outcome_unknown` and reservations stay held. Read-back mismatch or partial multi-record result => `reconciliation_required`.
6. **Idempotency.** Same `command_id` returns the same command and result. A different `command_id` with the same `preview_hash` while one is live returns 409. Retrying after `outcome_unknown` reuses the same `client_token`; a reconcile pass reads the row by `命令編號` and resolves the state. Never create a second task row for one command.
7. **No invented concurrency.** No remote compare-and-swap is claimed. A later direct edit of the Lark row is detected at read-back/reconcile and shown as a conflict with history; it is not silently overwritten.
8. **Writes limited** to the 任務 fields in the manifest plus 標題, 內容, 負責人, 指派人, 截止日, 部門, 狀態. The table is resolved server-side from config, never from the request. No write to any business master table. `工程確認單` link only when the case ref resolves to a V4 confirmation row.
9. **Status mapping.** 任務.狀態 on create = 待處理; 排程狀態 = 已確認; 命令編號 = command_id; 讀回時間 = now; 排程版本 = revision. HTTP 202 / `pending` is displayed as 處理中, never as confirmed.
10. **Audit.** Every preview, decision and command transition writes an audit row with actor, hashes and ids, no personal data beyond person_ref.

## API (all behind `DISPATCH_WRITE_ENABLED`, role pm or manager unless stated)

- `POST /api/v2/dispatch/previews` body Proposal, returns Preview. Idempotent on identical Proposal content within TTL (15 min).
- `GET /api/v2/dispatch/previews/{preview_id}`.
- `POST /api/v2/dispatch/previews/{preview_id}/decisions` body {seat, decision, reason?}; the actor must hold the seat; returns the updated preview.
- `POST /api/v2/dispatch/commits` body {command_id, preview_id}. 200 committed, 202 pending/outcome_unknown (body carries command), 409 conflict or duplicate, 422 blocked with `blockers`, 403.
- `GET /api/v2/commands/{command_id}` returns command, receipt, next allowed action (`reconcile`, `none`).
- `POST /api/v2/commands/{command_id}/reconcile` (manager) resolves `outcome_unknown` by reading the row by 命令編號.
- Existing `GET /api/v2/dispatch/board` additionally includes published 任務 rows as slots with `provenance: "v4_task"`, and `kind` execution.

## UI (frontend)

Dispatch board gets a 「排班」 flow per unassigned slot or a new task: step 1 proposal form (crew picker with feasibility chips, interval picker with 15-minute steps, instruments and vehicles), step 2 preview (per-person and per-resource feasibility, conflicts, hours: 8 person-hours example, required approval seats with who and status), step 3 approvals (seat holders act on the same hash), step 4 publish with a visible command timeline (pending, committed, outcome unknown with 重新對帳). Honest states: 202 shows 處理中, outcome_unknown shows what is known and what is not, conflicts name the other task and interval. Draft proposals persist in the browser per preview_id and survive reload. 390px usable, keyboard operable. Write controls are absent when the flag is off or the role is not allowed.

## Verification gates

- Tests with fakes: two workers racing on one person or instrument (one 409, draft kept); timeout after remote success then reconcile => committed with one task row; read-back mismatch => reconciliation_required; restart mid-command; unchanged proposal hash reuse; changed field voids decisions; seat holder cannot approve two seats; flag off => 404; `unknown` blocks by default.
- No real Lark write in tests. A separately approved single test write to a row marked `[測試-可刪]` is a manual step run by the parent and cleaned up afterwards.
- Frontend: node tests plus screenshots at 1280 and 390 for every state above.

## Out of scope

Capability and equipment verification records (C01-C03), replanning and cancel (C08), external calendar and Lark messages, SOP default task templates, delivery and review flows.
