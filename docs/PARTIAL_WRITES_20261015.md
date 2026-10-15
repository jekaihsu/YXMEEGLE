# Partial writes (2026-10-15)

## Why

Every user write went through `persist_mutation`: take the workspace row lock, load and upgrade the whole workspace, run the mutation, then `storage.save` loaded and diffed the whole workspace again, all under the lock. On staging (2 vCPU, 31,934 `business_records`, 420 projects) a load costs 2.1 to 2.8 s and a save diff 10.9 s, so one click on one task held the lock for about 14 s and every other writer waited behind it.

## What a write does now

A write that has a rule in `backend/write_footprint.py` loads, checks and saves only its footprint.

| Part | Rule |
| --- | --- |
| Collections | The rule names the top-level collections the action may read or write (`CASE_RECORDS` for case actions). They are loaded whole. |
| Project trees | One case (nodes, tasks, review cycles and every project child list), resolved from the request. Every other case is an id-only placeholder. |
| Events | Insert only. History is never loaded and cannot be searched. |
| Root | Always present, as in a full load. |

`WorkspaceView` is what the mutation sees. It raises `FootprintViolation` for an undeclared collection, for any field of a case outside the footprint, for walking or copying the whole state, for searching events, and for adding, removing or reordering cases. `FootprintViolation` is a `BaseException`, so the broad `except Exception` clauses in the mutation code cannot swallow it and save a partial view.

`storage.save_partial` writes the same rows a full save of the same change writes: row data, parent and ordinal, the project `concurrency_version` bump (only for cases whose data changed), event ordinals, `project_index` and `task_index` rows for the cases that changed, and `workspace_counters` (version advanced, values moved by the exact delta). A change that would touch a case, a template or a root skip request outside the footprint raises before any row is written, because a full save would have rewritten that case too.

The response is still the full workspace (`API_CONTRACT.md`). It is now read after the lock is released, the way `GET /api/workspace` reads it, instead of being built from the locked state.

## Fallback and switches

| Situation | Behaviour |
| --- | --- |
| Action has no rule, or the request has no case id | Full path, as before. |
| Mutation reaches outside the footprint | The partial attempt is rolled back, a `partial_write_declined` warning is logged, the full path runs. |
| A case in the request is not found in the footprint (404) | The full path decides the answer. |
| Legacy storage layout, a pending upgrade that would write shared records, cases without an execution system | Full path (the first full write heals the data, later writes are partial). |
| `PARTIAL_WRITES_ENABLED=false` | Every write takes the full path. Default is `true`. |
| `PARTIAL_WRITES_STRICT=true` | A `FootprintViolation` is raised instead of falling back. Tests run strict. |

`app.state.partial_writes` counts committed and declined partial writes and `app.state.last_write` records which path the last write took and how long it held the row lock.

## Actions on the partial path

`task_start`, `task_complete`, `task_return`, `task_add`, `task_update`, `comment_add` (mentions add the `jobs` collection), `node_complete`, `review_submit`, `review_vote`, `evidence_submit`, `evidence_approve`, `file_link`, `participants_update`, `document_withdraw`, `project_roles`, `delegation_set`, `node_skip_create`, `node_skip_submit`, `node_skip_vote`, `node_skip_apply`, `node_skip_withdraw`, `delivery_submit`, `delivery_review`, `daily_propose`, `daily_approve`.

`daily_propose` and `daily_approve` look up the case that holds the daily by its primary key (a daily id exists once) and load that case together with the target case.

## Left on the full path, and why

| Route or action | Reason |
| --- | --- |
| `task_batch_complete` | Spans several cases chosen by the payload. |
| `approval_*`, `change_resume`, `sop_*`, `recurring_*`, `handover_*`, `finance_*`, `payment_*`, `input_*`, `confirmation_*`, `delegation_revoke`, `job_retry`, `admin_*`, `migration_review`, `financial_finalize`, `calendar_update`, `case_execution_assign`, `file_category_save`, `demo_reset` and the learning actions | Not yet audited line by line, or they touch every case. Add them one rule at a time with an equivalence test. |
| `POST /api/files` | Queues a job by key, which needs the whole `jobs` collection, and runs a full load before the lock for its pre-check. |
| `integration_routes`, `native_routes`, `/api/approvals/{id}/refresh`, `/api/learning/sync`, `/api/delegations/verify-approval` | Lark calls and several collections per request. |
| Node assignment (`backend/node_assignment`) | Writes to Lark, not through `persist_mutation`. Untouched. |

## Sources sync

| Step | Before | Now |
| --- | --- | --- |
| `failure()` and the scheduled attempt in `run_due` | Load the workspace, change `source_status`, diff and save everything under the lock | Load users and templates, write the root with `save_collections`. Falls back to the full path if the upgrade would write rows. |
| `sync()` reading `sync_revision` | Loaded and upgraded the whole workspace | Reads the root. |
| `apply_snapshot` | Load, fingerprint, import and save under the lock | Load, fingerprint and import before the lock. Under the lock the version is compared with the one read; if equal the prepared state is used, if not the old locked path runs. The save is still the full diff. |

Every content write bumps the workspace version in the same transaction, which is what makes "same version" mean "same state". The live-read coordinator's generation fence, policy fence, stale-snapshot check and complete-table checks run under the lock exactly as before.

`apply_snapshot` legitimately rewrites many cases when the sources change (the import walks every project), so its save stays a full diff. What moved out of the lock is the load, the fingerprint and the import.

## Cheaper full save

`storage.save` copied every task about four times (whole state, project, node, task). It copies each record once now. The stored rows and the returned root are unchanged and are checked against a plain deep copy and pop in `test_storage_save_rows.py`. This speeds up every write that is still on the full path.

## Equivalence evidence

| Test file | What it proves |
| --- | --- |
| `test_partial_writes.py` | Each converted action runs on one world through both paths; the answer and `business_records`, `workspaces`, `receipts`, `action_audit`, `company_people`, `project_index`, `task_index` and `workspace_counters` are equal. Also replay with the same `request_id`, a different payload with the same `request_id`, a stale workspace version, per-case versions, rejected requests, the index staying ready, the company workspace, unclassified cases, and node skip, delivery, mention and daily flows. A registry test fails when a rule has no equivalence test. |
| `test_write_footprint.py` | The guard: undeclared collections, other cases, whole-state walks, events, structure, and `except Exception` not swallowing a violation. Strict mode raises and saves nothing, lenient mode falls back with identical results, a switch turns the partial path off, and a write that changes another case is refused before any row moves. |
| `test_partial_write_concurrency.py` | Threads against one database (PostgreSQL for the row-lock cases): writers on different cases all commit with their own versions, two writers on one case conflict, a partial writer queues behind a full-path writer. |
| `test_source_sync_partial.py` | Failure, scheduled attempt, unchanged and changed syncs store identical rows with the partial paths on and off; the import runs before the lock unless the version moved. |
| `test_storage_save_rows.py` | The cheaper `storage.save` stores the rows of the reference flattening and does not alias the caller's state. |

Run them against PostgreSQL with `scripts/test_action_audit_postgres.py backend/test_partial_writes.py backend/test_partial_write_concurrency.py -q`.

## Adding an action

1. Read the action line by line. List the collections it reads or writes and how it finds its case.
2. Add `RULES['action'] = Rule(collections, project=..., extra=...)` in `write_footprint.py`.
3. Add a scenario in `write_world.scenarios` (or a flow test) and run `test_partial_writes.py`. Strict mode names the first thing the action reaches outside the footprint.

## Measurements

See `docs/perf/write_paths/` for the raw JSON and `scripts/benchmark_write_paths.py`, `scripts/benchmark_source_sync.py` to reproduce.
