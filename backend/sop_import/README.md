# Import published local SOP tasks

This package implements the backend of M1. It stores local checklists independently of operational tasks and makes no outbound calls. Startup adds ten tables through the shared SQLAlchemy metadata. No import or publication runs during workspace upgrade.

## Publish a catalog

1. Use Python 3.12 and install `backend/requirements.txt`.
2. Obtain the original `Plumb-playbook-v0.2.xlsx`. The JSON catalog alone cannot verify the workbook.
3. Run the controlled database operator command from the repository root.

```sh
python3 -m backend.sop_import \
  --database-url sqlite:///backend/local.db \
  --workspace company-workspace \
  --actor authorized-publisher \
  --revision plumb-v0.2-1 \
  --workbook /absolute/path/Plumb-playbook-v0.2.xlsx
```

The command checks the workbook SHA-256, validates all 62 rows and 21 raw fields, recomputes the content hash, and publishes atomically. Repeating the same revision and content returns the existing version. Changed content requires a new revision. After the strict baseline publication, reviewed successor catalogs may add stable origins with reconciled disposition counts, up to 62 task definitions per catalog. Database operator access is the authorization boundary for this command. The HTTP publish endpoint requires the separate `sop_template_publish` grant and publishes only an already staged, source-verified draft. There is no HTTP catalog upload.

The latest published revision of the active default family is the default selection. The family display name, `案件 SOP 預設任務`, comes from the catalog's `proposed_template_family_name`; staging any revision applies it, which also renames a family staged earlier under the English name. Adding the field changes the catalog content hash, so a database that already published the old catalog under some revision must stage the new one under a new revision. Publication does not import any case. Existing task snapshots remain unchanged when a later revision is imported.

## Grant access and enable writes

Grant capabilities explicitly through the existing capability administration system. None is included in automatic manager defaults.

- `sop_task_read` permits local checklist reads.
- `sop_task_read_source` permits full source procedures and snapshots. Without it, task `instructions` and `source_snapshot` are null with a restriction reason. Manual instructions remain readable.
- `sop_task_import` permits import and management for the case PM, a manager, or a user named in the case's `sop_task_delegate_ids`. For an intake case without a PM, the explicit grant and current case visibility permit local planning.
- `sop_task_work` permits an explicitly assigned executor to transition their task. It does not permit import, applicability decisions, or archive.
- `sop_template_publish` permits publication and does not inherit `publish_sop`.

Set `SOP_TASK_WRITES_ENABLED=true` in server configuration. The default is false. Disabling it stops new previews, imports, publication, edits, transitions, and manual task creation. Authorized reads, receipts, and exact committed replays remain available. Existing case visibility and session admission always apply. An import grant is the explicit local planning grant for source-reference cases.

## Import and edit a case

Read `GET /api/sop-templates`, then preview a published version. Omit `node_keys` for all nine nodes in canonical order, beginning with `sales`. Node selection uses exactly the same planner. Intake cases need no formal case number or confirmation to import.

```json
{
  "template_version_id": "version-id",
  "node_keys": ["confirmation"],
  "row_keys": ["meegle-v137:A:19", "meegle-v137:A:59", "meegle-v137:A:60", "meegle-v137:A:61", "meegle-v137:A:22"]
}
```

Send this body to `POST /api/projects/{id}/sop-import/preview`. Preview tokens expire after 900 seconds and belong to the actor, workspace, and case. Selection changes require a fresh preview.

```json
{"preview_id":"preview-id","request_id":"client-operation-id"}
```

Send this body to `POST /api/projects/{id}/sop-import/apply`. Recover ambiguous outcomes with `GET /api/projects/{id}/sop-import/runs/{request_id}`. Keep the original preview and request IDs for retries. A request ID is scoped to the workspace and case and binds to the exact preview ID and actor. Another preview with that request ID returns `idempotency_mismatch`, even when its selection is equivalent. Replays check current authorization before expiry or revision checks.

`GET /api/projects/{id}/sop-tasks?node_key=confirmation` returns a node scope. Omit the query for a deduplicated case list. `counts` describes the selected scope. `case_counts` always deduplicates the whole case. `node_counts` includes all nine nodes. Numerator and denominator include only applicable, non-archived tasks. Unresolved and not-applicable counts remain separate.

[api-examples.json](api-examples.json) contains complete, actual preview, apply, and list response shapes for one quotation task in an intake case, including a full 21-field snapshot. IDs and timestamps are examples. `expires_at` is UTC epoch seconds as the decimal number the server returns, such as `1792496832.94495`. Node IDs come from persisted `business_records`, never titles or array positions. `python3 scripts/sop_import_examples.py` also adds later fields to the original entries through the same backend code, and replaces every other entry from real calls against a throwaway demo app: `sop_tasks_with_suggestions`, `accept_suggestion`, `accept_suggestion_stale`, `dismiss_suggestion`, `accept_suggestions`, `templates`, `sop_assignees`, `task_edit`, `task_transition`, `manual_task`, `preview_error_node_mapping_invalid`, `preview_error_row_not_importable`, `preview_error_applicability_unresolved`, `quotes`, `quote`, `quote_preview`, `quote_create`, `quote_create_replay`, `quote_request`, `quote_number_taken`, and `quotes_with_local`.

`start_node` and `stage` appear in preview, apply, and task-list responses. Neither changes task or business node state. Newly imported tasks under every selected node start `pending`.

`stage` is the quote lifecycle derived from the case's 報價總表 rows. Rows are merged first: every live source row carrying one of the case's 報價編號 counts, including duplicated rows that belong to other intake records. `quote_facts.py` reads the rows and `case_stage.py` holds the ordered predicate table. The first stage that holds wins.

| `stage` | Holds when | `start_node` |
| --- | --- | --- |
| `paid` | `狀態 (1)` is G | `settlement` |
| `pricing` | `狀態 (1)` is D, E, F or H | `pricing` |
| `office` | `狀態 (1)` is C | `control` |
| `field` | `狀態 (1)` is B | `field` |
| `confirmation` | `狀態 (1)` is 0 or A, a V4 confirmation record exists, or the case is won and numbered with `確認單回傳開會日期`, `提供行政回傳確認單時間`, or a confirmation link plus `回傳單日期` | `confirmation` |
| `numbered` | won, and `工程編號` or `編號` is C, A, B, K or X followed by digits that are not all zero | `pm` |
| `returned` | won without such a number; `報編` placeholders do not count | `pm` |
| `quote_expired` | `報價日期` or `提供給PM日期` is set and `報價期限` is before today in Asia/Taipei | `sales` |
| `quoted` | `報價日期` or `提供給PM日期` is set | `sales` |
| `inquiry` | otherwise | `sales` |
| `cancelled` | the merged `狀態 (1)` is I; a live letter on another row wins | as if not cancelled |

Won means `回傳單日期` is set, or the case is numbered and `狀態` is `成案` or `舊案`, or `狀態 (1)` is A to H. `成案` alone does not win a case. A `此案確認單` link or a quote-base `工程確認單` alone is a quote-time costing sheet and advances nothing. Merged `狀態 (1)` is the furthest live letter. I counts only when every row says I.

`start_node` is the furthest of the stage's node, the verified engineering lifecycle, and persisted node progress. Unverified lifecycle values do not advance it.

The source fetch reads these quote fields: `詢價日期`, `第一次聯繫日期`, `報價日期`, `提供給PM日期`, `回傳單日期`, `編號`, `狀態 (1)`, `確認單回傳開會日期`, `提供行政回傳確認單時間`, `成案後聯繫日期`, `契約價格(含稅)`, the five `確認單營業額` fields, `外業負責組別`, `內業負責組別`, `MEEGLE日報填報情形`, `PM告知可請款日期`, `連絡人`, and `報價負責人`. `契約價格(含稅)` and the `確認單營業額` fields are server only and never leave in public source views.

The quote-base `合約明細工項` table is not read. On the 2026-10-20 dump, 19 of 333 quote groups have contract lines without a quote date, so they derive `inquiry` here where the evidence dive counted them as quoted. All other stage counts match the dive.

Display fields return values and codes. Preview outcomes contain `reason_code`, an optional recorded `exclusion_reason`, and `node_keys`, the selected nodes the row maps to (empty for node-less rows), without catalog helper prose. The node-less routine and disabled rows (#27, #28, #57, #58) appear only in a case-wide preview of all nine nodes. Errors name what failed beside `code`: `node_mapping_invalid` carries the unknown or unmapped `node_key` (none for an empty selection), `row_not_importable` and `applicability_unresolved` carry `source_row_key`, and `template_mapping_conflict` carries `source_row_key`. Catalog interpretation notes reside under `provenance`; immutable task source content resides under the optional `source_snapshot`.

For an explicit participant binding, add `participant_bindings` keyed by source row key, with `executor`, `checker`, or `confirmer` user IDs. A binding requires one active user with `sop_task_work` and case participation. It never selects the importer or node owner automatically.

`GET /api/projects/{id}/sop-assignees` lists exactly the people a binding accepts: `{"project_id":"…","restricted":false,"people":[{"id":"u-pm","name":"林育寬","case_roles":["pm"]}]}`. `case_roles` holds every case role that makes the person eligible, ordered `pm`, `admin`, `supervisor`, `delegate`, `collaborator`, `manager`. It needs a local checklist read grant and case visibility. A viewer who is neither a case manager nor admitted by `HR_VIEWERS` gets only their own entry with `restricted: true`. A rejected binding names the offending `role` and, during import, the `source_row_key`.

Subcontract rows #7, #20, #49, #54, #55, and #56 start unselected. Selecting one requires an `applicability_decisions` entry with `value=applicable` and a reason. #18 and #22 start unresolved. Reference, review, routine, and disabled rows cannot be selected. No baseline row is configured mandatory. Optional deselection may include an `exclusion_reasons` map. #31 and #47 remain in related billing task snapshots.

Create a manual task with `POST /api/projects/{id}/sop-tasks` and `{"title":"Review plans","node_keys":["pm"]}`. Imported and manual origins never merge by title. Patch local title, instructions, participants, or due date with `expected_revision`. Due dates are ISO dates and require a reason. Source snapshots are immutable.

Transition with `POST /api/projects/{id}/sop-tasks/{task_id}/transition` and `{"expected_revision":1,"action":"start"}`. Actions are `start`, `block`, `resume`, `reset`, `complete`, `reopen`, `archive`, `restore`, and `set_applicability`. Block, resume, reset, reopen, archive, restore, and applicability decisions require a reason. `set_applicability` also requires `applicability` and management authority. Assignment changes clear local attestations. Completed work must reopen before edits.

Manual creation, edits, transitions, and suggestion decisions return the updated `task` exactly as the list shows it, beside `checklist_revision`.

Every listed task carries fields that need no `sop_task_read_source` grant. `node_keys` lists its linked node keys in canonical order. `instance_scope` is `case` or `office_shared`. `is_shared` is true for an `office_shared` task or one linked to several nodes. `is_conditional` is true for catalog rows #7, #18, #20, #22, #49, and #54 to #56, and it stays true after the applicability decision. `allowed_actions` lists what this actor may do to this task now, in this order: the transitions from the table above whose origin state matches, then `restore`, `set_applicability`, `edit`, `accept_suggestion`, and `dismiss_suggestion`. A case manager gets every applicable one. The assigned executor with `sop_task_work` gets the transitions except `archive`. `start`, `resume`, and `reopen` need an applicable task. `complete` also needs completion evidence, so imported tasks never list it; an accepted suggestion completes them. `restore` of a completed task needs the same. With writes disabled the list is empty.

## Evidence suggestions

`GET /api/projects/{id}/sop-tasks` adds `suggestion` to every task. It is null unless quote evidence would move that task forward. Suggestions are computed on each read from the merged quote facts and are never stored. They never change a task by themselves and never write to Lark.

```json
{"task_id":"…","rule_id":"quote-evidence:A:12","rule_revision":1,"tier":"proof","suggested_state":"done",
 "facts":{"returned_date":"2026-09-17","quote_deadline":"2026-08-24","deadline_passed":true},"facts_hash":"…"}
```

`suggestions.py` holds the rule table. Each rule speaks for one catalog row and lists ordered claims, each with a tier, a suggested state, and a predicate over the facts. The first claim that holds is the suggestion. A suggestion appears only for an applicable, non-archived imported task whose state the suggested transition can leave: `done` from pending, in progress, or blocked through `complete`, and `in_progress` from pending through `start`. `facts_hash` covers the rule ID, revision, tier, suggested state, and facts. `facts` hold plain values. Money and revenue points appear only as booleans.

| Rule rows | Tier and state |
| --- | --- |
| #2 unique 報價編號, #12 `回傳單日期` or `報價期限` passed, #44 `案件已入帳` or `入帳日期` | proof, `done` |
| #2 duplicated 報價編號, #44 `狀態 (1)` G, and #1, #3, #8, #15, #16, #17, #19, #24, #29, #30, #32, #36 to #39, #41, #43, #59 to #61 | indicator, `done` |
| #9 open quote, #15 returned without a price, #21, #25, #26, #33 to #35, #46 | indicator, `in_progress` |

Rows #4, #7, #10, #18, #20, #22, #23, #49, #51, #52, and #54 to #56 have no rule because the source holds no evidence for them or only an applicability hint. Three rules differ from the evidence dive on purpose. #16 is an indicator because its 回傳本 upload has no field. #19 ignores a confirmation link without `回傳單日期`. #46 follows its predicate text, E or F, so a G case does not stay in tracking.

Decide one suggestion with `POST /api/projects/{id}/sop-tasks/{task_id}/suggestion`.

```json
{"action":"accept_suggestion","facts_hash":"…","expected_revision":1,"confirm":true,"reason":"回簽附件已上傳"}
{"action":"dismiss_suggestion","facts_hash":"…","reason":"待補佐證"}
```

Accept several in one case with `POST /api/projects/{id}/sop-tasks/suggestions/accept` and `{"tasks":[{"task_id":"…","facts_hash":"…","expected_revision":1}],"confirm":true,"reason":"…"}`. The batch is all or nothing. A failure names the offending `task_id` beside `code`.

Both commands require case task management, the same authority as import, and the write flag. Each command recomputes the current suggestion and rejects a different `facts_hash` with `suggestion_stale` (409). Accept also checks `expected_revision`. A proof claim satisfies that row's completion evidence. An indicator claim needs `confirm: true` and a reason, otherwise `suggestion_confirmation_required` (422). Bulk indicator adoption also requires `confirmed_task_ids` covering each indicator task. One reason applies to those explicit IDs. The state change runs through the transition table. The command records `local.evidence_basis` and appends a `suggestion_accepted` event with the rule ID, revision, tier, facts, hash, transition, and actor. Restoring an archived task that was completed this way reuses that basis.

Repeating an accept whose hash already moved the task to its state replays the stored outcome without a new event, even with writes disabled. A dismissal appends a `suggestion_dismissed` event and hides that exact hash for good. Changed facts produce a new hash, and the suggestion returns. Repeating a dismissal replays. Accepting a dismissed hash returns `suggestion_dismissed` (409).

## Quote register

`GET /api/quotes` lists one entry per 報價編號, newest number first. Query parameters are `stage` (one `stage` code), `q` (case-insensitive match on 報價編號, 工程名稱, or 行號單位, at most 240 characters), `offset`, and `limit` (1 to 100, default 30). `GET /api/quotes/{quote_no}` returns one entry plus `facts`, the merged quote facts, and `records`, the source row IDs and links. An unknown or hidden number returns `quote_not_found` (404).

The register reads the cached `source_quotes` collection and the stored cases. It never reads Lark during a request. The same `filter_visible_cases` policy as the case list decides which rows and cases appear; no extra capability is needed. Rows deleted at the source and rows without a 報價編號 are left out. Rows sharing a 報價編號 merge, and `stage` uses the same predicate table as `sop-tasks`, with a V4 confirmation on any linked case counting.

| Field | Source |
| --- | --- |
| `quote_no` | `報價編號` |
| `engineering_no` | first `工程編號` or `編號` with a valid engineering letter, else the first code present |
| `name`, `client` | `工程名稱`, `行號單位` (`業主` and `合約金額` are empty in the register) |
| `quoted_on`, `quote_deadline` | latest `報價日期`, `報價期限` |
| `contract_amount` | first `契約價格(未稅)`; null with `amount_restricted: true` unless the viewer passes the `/progress` amounts gate (normal access and PM, manager, or `manage_sources`) |
| `quote_owners`, `pm_names` | display names in `報價負責人`, `案件負責人` |
| `pm_id` | the linked case's PM |
| `status`, `stage_label` | first `狀態` text, merged `狀態 (1)` letter |
| `project_id`, `project_ids` | linked visible cases, formal first |
| `source_rows`, `duplicated` | merged row count, whether one 報價編號 repeats |
| `sop_counts` | local checklist counts summed over the linked cases, or null without tasks |

The register stage is per 報價編號. The `sop-tasks` stage merges every 報價編號 of a case, so a formal case with several quotes can differ from one register entry. The case-level `sop-tasks` merge counts only sibling rows in the last admitted source snapshot.

## Local planning quotes

A local planning quote is a case created in this app only. Nothing is written to the 報價總表: the Base runs automations this app cannot read, 報價編號 is typed by hand with no uniqueness check, and the source boundary has no outbound writes.

Set `LOCAL_CASE_CREATION_ENABLED=true` to allow creation. The default is false, and turning it off leaves every read, receipt, and replay working. Creating needs the explicit `create_local_case` grant. Importing tasks at creation also needs `sop_task_import` and `SOP_TASK_WRITES_ENABLED`. Neither grant is a manager default.

Preview with `POST /api/quotes/preview`.

```json
{"name":"新竹科學園區地形測量","pm_id":"u-pm","client":"竹科管理局","description":"初步詢價","official_quote_no":"115950"}
```

`name` and the `pm_id` key are required. `pm_id` is an active PM or manager, or `null` for an explicitly unassigned case. `client`, `description`, and `official_quote_no` are optional. Tasks import by default from the latest published default template, all nine nodes starting with `sales`. The same selection fields as an import preview narrow it: `template_version_id`, `node_keys`, `row_keys`, `participant_bindings`, `applicability_decisions`, `exclusion_reasons`. `"import_tasks": false` creates the case without tasks and allows no selection fields.

The preview allocates the canonical project ID and returns `draft_id`, `expires_at` (900 seconds), `case` with the nine node IDs, and `import`, the same plan an import preview returns, or null. The draft belongs to its actor and holds the normalized form; any change needs a new preview. Preview writes purge expired drafts and retain at most 20 drafts per actor in a workspace.

Create with `POST /api/quotes` and `{"draft_id":"…","request_id":"client-operation-id"}`. One transaction locks the workspace, appends the case through the full workspace save, imports the tasks, writes an audit row, stores the receipt, and consumes the draft. Any failure rolls all of it back. Replaying the request ID returns the stored receipt with `replayed: true`, after the current grant and case visibility are rechecked. The same request ID with another draft returns `idempotency_mismatch` (409). Recover an ambiguous outcome with `GET /api/quotes/requests/{request_id}`.

The case is `case_type=intake` with `planning_origin=local`, `case_visibility=local_planning`, `execution_system=pending`, and nine canonical nodes whose operational task arrays are empty. `v4_sources.blank_nodes` builds them without the old task seeding. `local_reference` is `LOCAL-` and eight characters of the project ID, so it never reads as an official 報價編號 or 工程編號. `official_quote_no` is a display field. NFKC normalization and uppercase conversion precede the ASCII number check. Source keys use the same normalization for uniqueness. It must look like `115950`, `115950-01`, or `115950-01A`, and must not already exist in the merged source register or on another local case, checked at preview and again under the creation lock. Otherwise the codes are `quote_number_invalid` (422) or `quote_number_taken` (409).

Only the creator, the selected PM, collaborators, and managers see the case: in `GET /api/quotes` as an `origin: local` entry, in `GET /api/quotes/{local_reference}`, and through the `sop-tasks` routes. `visible_project`, `filter_visible_cases`, and the index visibility clause leave it out of every official view, including the case list, case detail, workspace payload, company dashboard, and manager overview, in every environment, so it never enters engineering or finance totals. Operational execution is refused for it in every environment. Source refresh never matches it to a Lark row.

`quote_publish.py` is a prepared, disabled adapter for a later step that would publish a local quote to the 報價總表. No route, job, or command calls it. It would write `報價編號`, `工程名稱`, `行號單位`, `備註`, `案件負責人`, and `詢價日期` (the local creation day) and never the lifecycle evidence fields, links, money, or Lark-computed fields. It refuses to run unless `QUOTE_PUBLISH_ENABLED=true`, the actor is an active manager holding `publish_local_quote`, the case has an official 報價編號 the register does not hold, `LARK_QUOTE_BASE_TOKEN` is set, and a client is injected. It builds no Lark client of its own.

## Completion and deferred work

Imported completion rules remain unresolved until reviewed typed evidence obligations are available. Imported tasks reject `complete` with `completion_evidence_missing`; an accepted evidence suggestion is the only path to `done`. Unresolved applicability rejects completion first. Manual tasks have no typed obligations and can complete. No note or URL can manufacture an approval. This backend slice does not yet satisfy the full M1 user demonstration.

Deferred work includes attachments, reviewed typed completion evidence and checker/confirmation commands, date calculation, source identity remapping, local planning cases in the case list and case detail routes, publishing a local quote to the 報價總表, and the frontend. Raw dates, role text, TODOs, and source procedures remain inert snapshots. There is no dependency engine or remote approval adapter.

Canonical identity merge/remap must remain disabled for cases with checklist history until a preservation adapter is verified. This slice does not intercept the existing reconciliation paths. Keep canonical IDs stable. Ordinary source refresh and `storage.save` cannot delete feature tables. Missing canonical nodes block further import and retain historical links.

Back up the application database, including all `sop_*` tables. Workspace JSON export does not include them. Restore verification must include templates, tasks, links, previews, import and local case runs, and events alongside canonical cases. The portable backup includes all SOP tables and restores older archives with empty SOP tables. Identity migration remains deferred. Roll back by disabling writes and retaining the tables.

Run verification from the repository root.

```sh
python3 -m pytest backend/test_sop_import_catalog.py backend/test_sop_import.py backend/test_sop_case_stage.py \
  backend/test_sop_suggestions.py backend/test_sop_quotes.py backend/test_sop_local_case.py backend/test_sop_quote_publish.py -q
python3 -m pytest backend -q
```

Local intake creators with `sop_task_import` can manage the checklist while no PM is assigned. After PM assignment, management requires that PM, a manager, or an explicit SOP delegate.

`quote_number_taken` checks even hidden source numbers. The existence disclosure is an accepted trade-off for official number uniqueness.
