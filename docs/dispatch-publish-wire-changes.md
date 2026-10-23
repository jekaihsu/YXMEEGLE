# Dispatch publish wire changes, review round 1

Date: 2026-10-18. Compared with `docs/dispatch-publish-api-examples.json` at commit `1be34e5`. The regenerated file holds the new shapes. Most changes add fields. The two value changes that need frontend work come first.

## Breaking value changes

1. **`command_id` must be a lowercase UUIDv4.** `POST /api/v2/dispatch/commits` answers 422 `{"code": "invalid", "field": "command_id"}` for anything else, before any Lark request. Use `crypto.randomUUID()`. Lark rejects any other `client_token` with error 1254037, and the id is sent unchanged. Draft ids keep the old rule (8 to 64 of `A-Z a-z 0-9 _ -`).
2. **`required_seats[].holders` now lists person_refs, not open_ids.** It stays a `string[]`. A holder the roster cannot map, such as a session PM without a 人員名單 row, appears in `names` and `people` but not in `holders`. Use `configured` to decide whether a seat has holders, not `holders.length`.

## Added fields

| Where | Field | Meaning |
| --- | --- | --- |
| preview `required_seats[]` | `names: string[]` | Holder display names, in the same order as `people` |
| preview `required_seats[]` | `people: {person_ref: string \| null, name: string \| null}[]` | Who may decide the seat |
| preview `required_seats[]` | `configured: boolean` | At least one holder exists |
| preview `required_seats[]` | `source: "env" \| "roster" \| "session"` | Where the holders came from |
| `/options` `seats[]` | `holders: {person_ref, name}[]`, `source` | Holders for any department |
| `/options` `seats[]` | `by_department: {[所屬組別]: {person_ref, name}[]}` | Only on `group_leader_confirmed` and `manager_review` when derived from the roster |
| `/work` | `gaps: {code: "invalid_draft", draft_id, field}[]` | Stored drafts that failed type checks and were skipped. Always present, usually `[]` |
| board `source` | `accounts: "ok" \| "unavailable"` | Next to `v4_tasks`, only when dispatch writes are on. Either one unavailable makes `quality.states` `["partial"]` |

`/options` `seats[].configured` now means "a holder resolves" instead of "an env list is set".

## New codes and states

| Code or key | Where | Meaning |
| --- | --- | --- |
| `approval_not_configured:<seat>` | `blockers` | Follows the existing `approval_not_configured` and names each seat with no holder |
| `seats: string[]` | 422 `approval_not_configured` body | The seats with no holder |
| 409 `stale_revision` | commit | Another command already committed this or a later revision of the task, or the row changed after it was assessed. Re-preview. May carry `command_id` and `revision` |
| 409 `preview_stale` | commit | Unchanged code. It now also fires when the target row's written fields or a person's Lark帳號 changed after the preview |
| `receipt.duplicates` | commit 202 `reconciliation_required` | Several rows carry the 命令編號, now also found right after a normal write |
| `receipt.error: "search_missing"` or `"search_<code>"` | commit or reconcile 202 `outcome_unknown` | The read-back matched but the 命令編號 search found no row or failed |
| `receipt.changed_since_commit: string[]` | reconcile 202 `reconciliation_required` | V4 fields someone edited after the command opened. The row is not overwritten |
| `feasibility: "unknown"`, `reasons: ["same_day_other_slot"]` | preview `resources[]` | A date-only booking shares the day. Instruments and vehicles now block like people until `verifications["instrument:recX"]` is set |
| 422 `invalid` with `field` | `PUT /drafts/{id}` | Draft fields are type-checked, for example `crew: 1` returns `field: "crew"`. Missing required fields are still accepted |
| 403 `forbidden` or `writes_disabled` | commit, reconcile | The session, role or `external_enabled` is checked again just before the Lark write |

## Unchanged

Routes, status codes of existing outcomes, `command`, `reservations`, `next_action`, work-queue rows, and the task form. A landed create whose response was lost now shows as one `v4_task` row carrying the command. It used to show as two rows.

# Review round 2

Date: 2026-10-18. Compared with `docs/dispatch-publish-api-examples.json` at commit `899091e`. Routes and existing status codes are unchanged. The regenerated file has one example per new shape, at its end, plus `preview again of the published create`.

## Value changes the frontend must handle

1. **`receipt.error: "search_missing"` is now `"search_lag"`.** Same case: the row read back as written, but the 命令編號 search still found nothing after one retry a second later. The command stays `outcome_unknown` (202). Reconcile resolves it by reading the known record id and searching again. It never re-sends the create. `"search_<code>"` for a failed search is unchanged.
2. **Seat holders exclude the proposer.** Whoever created a preview of the hash is not among `required_seats[].holders`, `names` or `people` for `group_leader_confirmed` and `manager_review`, nor in `my_seats`. When the proposer was the only holder, the seat reports `configured: false` and `approval_not_configured:<seat>`. `pm_final` is unaffected.
3. **A committed create's content cannot be published or approved again.** A new preview of the same content carries the blocker `already_published`, `can_commit: false`, and seat decisions `null` because the earlier decisions are not reused. Decisions and commits on it answer 409 `duplicate_command` with the create's `command_id`. A committed update still stops blocking once a later revision supersedes it.

## New codes, reasons and blockers

| Code or key | Where | Meaning |
| --- | --- | --- |
| 422 `invalid`, `field: "department"`, `reason: "unknown_department"` | `POST /previews` | `department` is neither a 任務 部門 value nor a roster 所屬組別, the same sets `/options` returns as `departments` and the `by_department` keys |
| 422 `invalid`, `field: "department"`, `reason: "department_not_node_group"` | `POST /previews` | The target task, or else its parent obligation, is assigned to a node whose 所屬組別 do not include `department` |
| `unknown_department`, `department_not_node_group` | preview `blockers`, 422 `blocked` on commit | The same checks against the commit's fresh sources |
| 409 `seat_conflict`, `reason: "own_preview"` | `POST /previews/{id}/decisions` | The actor proposed this hash and may not decide `group_leader_confirmed` or `manager_review` |
| `decision_holder_changed:<seat>` | preview `blockers` | An acceptance on this seat was made by someone who no longer holds it (left, demoted, inactive, or the proposer). The seat shows `decision: null`. A current holder may decide it, which replaces the lapsed decision |
| 409 `decision_holder_changed`, `seats: string[]`, `blockers` | commit | Takes precedence over 422 `approval_not_configured` when a lapsed decision exists, even when the seat now has no holder |
| `already_published` | preview `blockers` | See value change 3 |
| 503 `recheck_unavailable`, `retryable: true` | commit of an update | The re-read of the task under the workspace lock (one attempt, at most 5 seconds) failed. Nothing was persisted or sent. Retry with the same `command_id`. Replaces the earlier 503 `sources_unavailable` with `source: "tasks"` at this step |
| `receipt.reason: "no_base_snapshot"` | reconcile 202 `reconciliation_required` | The command was opened before pre-command snapshots were recorded and the row differs from the payload, so whether someone edited it cannot be told. The row is not overwritten |

## Behaviour without a new shape

The session, role and `external_enabled` are now re-read after the workspace lock and the in-lock re-read, right before the Lark write. A refusal there answers the same 403 `forbidden` or `writes_disabled` as before and leaves no command and no reservations behind, so the same `command_id` may be retried. A draft whose preview was committed hides its earlier previews from `/work` even after a later revision supersedes that commit.
