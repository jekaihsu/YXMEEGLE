# Import published local SOP tasks

This package implements the backend of M1. It stores local checklists independently of operational tasks and makes no outbound calls. Startup adds nine tables through the shared SQLAlchemy metadata. No import or publication runs during workspace upgrade.

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

The latest published revision of the active default family is the default selection. Publication does not import any case. Existing task snapshots remain unchanged when a later revision is imported.

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

[api-examples.json](api-examples.json) contains complete, actual preview, apply, and list response shapes for one quotation task in an intake case, including a full 21-field snapshot. IDs and timestamps are examples. `expires_at` is UTC epoch seconds. Node IDs come from persisted `business_records`, never titles or array positions.

`start_node` appears in preview, apply, and task-list responses. It derives from persisted case and node data. An unprogressed intake starts at `sales`. Quote status `成案` or a populated `回傳單日期` advances it to `pm`; a confirmation relationship advances it to `confirmation`. Verified engineering lifecycle and persisted node progress can advance it further. Unverified lifecycle values do not advance it. This field does not change task or business node state. Newly imported tasks under every selected node start `pending`.

Display fields return values and codes. Preview outcomes contain `reason_code` and an optional recorded `exclusion_reason`, without catalog helper prose. Catalog interpretation notes reside under `provenance`; immutable task source content resides under the optional `source_snapshot`.

For an explicit participant binding, add `participant_bindings` keyed by source row key, with `executor`, `checker`, or `confirmer` user IDs. A binding requires one active user with `sop_task_work` and case participation. It never selects the importer or node owner automatically.

Subcontract rows #7, #20, #49, #54, #55, and #56 start unselected. Selecting one requires an `applicability_decisions` entry with `value=applicable` and a reason. #18 and #22 start unresolved. Reference, review, routine, and disabled rows cannot be selected. No baseline row is configured mandatory. Optional deselection may include an `exclusion_reasons` map. #31 and #47 remain in related billing task snapshots.

Create a manual task with `POST /api/projects/{id}/sop-tasks` and `{"title":"Review plans","node_keys":["pm"]}`. Imported and manual origins never merge by title. Patch local title, instructions, participants, or due date with `expected_revision`. Due dates are ISO dates and require a reason. Source snapshots are immutable.

Transition with `POST /api/projects/{id}/sop-tasks/{task_id}/transition` and `{"expected_revision":1,"action":"start"}`. Actions are `start`, `block`, `resume`, `reset`, `complete`, `reopen`, `archive`, `restore`, and `set_applicability`. Block, resume, reset, reopen, archive, restore, and applicability decisions require a reason. `set_applicability` also requires `applicability` and management authority. Assignment changes clear local attestations. Completed work must reopen before edits.

## Completion and deferred work

Imported completion rules remain unresolved until reviewed typed evidence obligations are available. All imported tasks currently reject `complete` with `completion_evidence_missing`. Unresolved applicability rejects completion first. Manual tasks have no typed obligations and can complete. No note or URL can manufacture an approval. This backend slice does not yet satisfy the full M1 user demonstration.

Deferred work includes attachments, reviewed completion evidence and checker/confirmation commands, M2 local case creation, date calculation, source identity remapping, and the frontend. Raw dates, role text, TODOs, and source procedures remain inert snapshots. There is no dependency engine or remote approval adapter.

Canonical identity merge/remap must remain disabled for cases with checklist history until a preservation adapter is verified. This slice does not intercept the existing reconciliation paths. Keep canonical IDs stable. Ordinary source refresh and `storage.save` cannot delete feature tables. Missing canonical nodes block further import and retain historical links.

Back up the application database, including all `sop_*` tables. Workspace JSON export does not include them. Restore verification must include templates, tasks, links, previews, runs, and events alongside canonical cases. This slice does not supply a backup or identity migration adapter. Roll back by disabling writes and retaining the tables.

Run verification from the repository root.

```sh
python3 -m pytest backend/test_sop_import_catalog.py backend/test_sop_import.py -q
python3 -m pytest backend -q
```
