# Isolated native approval transport acceptance runner

Implemented as `scripts/native_qa_runner.py` with `backend/native_qa.py`.
This is a repository-local operator tool, not a production API exception.
It has no workspace DB connection, source import, business apply, impersonated
vote, approve, reject, auto-pass or cancellation operation.

## Manifest and credentials

Put a non-secret manifest in `.runtime/native-qa/config.json`. Actual identities
and definition IDs must be copied from the separately authorized QA setup.

```json
{
  "schema_version": 1,
  "purpose": "native_qa_transport_only",
  "app_id": "<same application ID>",
  "tenant": "<authorized company tenant>",
  "definition_name": "<exact dedicated QA definition name containing QA or 驗收>",
  "mapping": {
    "kind": "extension",
    "approval_code": "<dedicated QA approval code>",
    "fields": {
      "binding": {"id": "<actual control ID>", "name": "<exact name>", "type": "input"},
      "content": {"id": "<actual control ID>", "name": "<exact name>", "type": "textarea"}
    },
    "nodes": [{"id": "<actual approval node ID>", "seats": ["supervisor"]}],
    "boundary_nodes": {
      "start": {"id": "<actual Submit ID>", "name": "Submit"},
      "end": {"id": "<actual End ID>", "name": "End"}
    }
  },
  "participants": {
    "applicant": "<authorized applicant open_id>",
    "approvers": {"supervisor": "<selected real test employee open_id>"},
    "allowlist": ["<applicant open_id>", "<test employee open_id>"]
  },
  "authorization": {
    "decision_ref": "<actual user authorization reference>",
    "authorized_by": "<authorizing person>",
    "reason": "Dedicated QA transport acceptance; no business role change",
    "expires_at": "<explicit expiry in timezone-aware ISO format>"
  }
}
```

If applicant and the single extension supervisor are the same authorized person,
the allowlist contains that ID once. This does not permit automatic approval:
an actual human PASS timeline remains mandatory. Other kinds retain exact
existing two-person rules: financial PM/admin, change and node-skip PM/supervisor.

Credentials come from standard `LARK_*` environment variables, optionally seeded
by `--saved-config <existing local server config JSON>`. Environment overrides
file values. Files may be flat dictionaries or existing `variables.data` exports.
Never put tokens on CLI flags. Required server configuration is the application
ID/secret, worker company, application identity, allowed tenants, and the complete
four-kind production mapping inventory. The runner refuses a QA approval code
matching any configured production code. It also requires the remote exact
definition name to match the QA manifest. It never creates/edits a definition.

## Operator commands

All commands emit a stable JSON envelope: `{ "ok": true, "result": {...} }` or
`{ "ok": false, "error": {"code": "safe_code"}, "business_apply_allowed": false }`.
Outputs contain only local run/UUID/instance receipt status, never credentials,
participant IDs, raw forms, or remote exception text.

```powershell
python scripts/native_qa_runner.py --config .runtime/native-qa/config.json --saved-config <server-config.json> doctor
python scripts/native_qa_runner.py --config .runtime/native-qa/config.json --saved-config <server-config.json> prepare --run-id qa-extension-20260929
```

`doctor` has no network I/O. `prepare` only reads the definition and persists a
QA binding and immutable UUID in `.runtime/native-qa/attempts.sqlite`. It does
not create a business request or remote instance. Inspect the authorized QA
setup before explicitly invoking the real write:

```powershell
python scripts/native_qa_runner.py --config .runtime/native-qa/config.json --saved-config <server-config.json> create --run-id qa-extension-20260929 --allow-create
python scripts/native_qa_runner.py --config .runtime/native-qa/config.json --saved-config <server-config.json> poll --run-id qa-extension-20260929
python scripts/native_qa_runner.py --config .runtime/native-qa/config.json --saved-config <server-config.json> status --run-id qa-extension-20260929
```

These are usage examples, not commands run during implementation. Only the
selected real employee may personally act in Lark; the runner cannot vote.

The optional `--db` must resolve to a `.sqlite` file under this workspace's
`.runtime`. A dedicated SQLite application ID rejects existing application DBs.
SQLite transactions use `BEGIN IMMEDIATE` to claim an attempt, FULL synchronous
durability, and CAS versions for receipts. The attempt/UUID is committed before
POST. Two create callers cannot both claim it. A crash/timeout/unknown result
leaves the attempted marker; subsequent create calls only perform GET polling of
the same UUID, even if Lark returns not-found. Never use a new run ID to work
around an unknown outcome. Repeated prepare preserves the original UUID.

Every create reads/verifies the remote definition again, and every HTTP boundary
reloads exact manifest/participant/company policy. Policy or definition drift
blocks use. Keep the original manifest and authorization available for the full
acceptance window; editing it changes its hash and does not silently reauthorize
an old binding. Any necessary policy change/recovery requires deliberate review.

## Isolation and evidence interpretation

QA identity uses `qa_workspace_id` and `qa_run_id`, lacks production `workspace_id`
and `project_id`, and has its own schema/purpose and binding hash. Production
`prepare_binding` rejects it. Production native routes, DEMO_MODE restrictions,
submit enablement and business gates were not modified.

A receipt can report real `approved=true` only after exact definition/form/UUID/
applicant/node/approver/PASS verification. It always reports
`business_apply_allowed=false`. Failed or malformed polling clears the previous
verified receipt. A QA transport success does not prove the production case UI,
role assignment, business apply, finance or source-sync flow.

Implementation validation uses only synthetic adapters and temporary SQLite.
No real remote POST or human approval was performed by this workstream.

Validation evidence:

- QA + existing native approval/service suites: **74 passed in 5.39 seconds**.
- After adding offline CLI/credential-redaction coverage, the entire QA suite:
  **25 passed in 4.93 seconds**.
- CLI `--help` exits successfully without external access.
- Tests cover crash/timeout/unavailable reconciliation, at-most-once POST across
  restarts, atomic parallel claim, stale receipt CAS, failed pre-POST checkpoint,
  revoked participant policy, definition drift, namespace separation, refusal to
  open an existing non-QA database, and rejection of auto-pass/malformed receipts.
