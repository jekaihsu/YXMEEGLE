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

`storage.save_partial` writes the same rows a full save of the same change writes. That covers row data, parent and ordinal, the project `concurrency_version` bump (only for cases whose data changed), event ordinals, `project_index` and `task_index` rows for the cases that changed, and `workspace_counters` (version advanced, values moved by the exact delta). A change that would touch a case, a template or a root skip request outside the footprint raises before any row is written, because a full save would have rewritten that case too.

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
| `test_write_footprint.py` | The guard refuses undeclared collections, other cases, whole-state walks, events, structure, and `except Exception` not swallowing a violation. Strict mode raises and saves nothing, lenient mode falls back with identical results, a switch turns the partial path off, and a write that changes another case is refused before any row moves. |
| `test_partial_write_concurrency.py` | Threads against one database, PostgreSQL for the row-lock cases. Writers on different cases all commit with their own versions, two writers on one case conflict, and a partial writer queues behind a full-path writer. |
| `test_source_sync_partial.py` | Failure, scheduled attempt, unchanged and changed syncs store identical rows with the partial paths on and off; the import runs before the lock unless the version moved. |
| `test_storage_save_rows.py` | The cheaper `storage.save` stores the rows of the reference flattening and does not alias the caller's state. |

Run them against PostgreSQL with `python scripts/test_action_audit_postgres.py backend/test_partial_writes.py backend/test_partial_write_concurrency.py -q`, or set `PARTIAL_WRITES_TEST_POSTGRES_URL` to a server where databases may be created.

## Adding an action

1. Read the action line by line. List the collections it reads or writes and how it finds its case.
2. Add `RULES['action'] = Rule(collections, project=..., extra=...)` in `write_footprint.py`.
3. Add a scenario in `write_world.scenarios` (or a flow test) and run `test_partial_writes.py`. Strict mode names the first thing the action reaches outside the footprint.

## Measurements

All local numbers are medians over 7 runs (5 for sources) on one machine with 12 cores, a 420 project workspace of 44.5k `business_records` (staging has 31.9k), real `/api/actions` requests through the test client, and `INDEX_TABLES_ENABLED`. This machine loads the workspace in 0.15 s where staging needs 1.6 to 2.8 s, so read the ratios, not the seconds. Raw runs are in `docs/perf/write_paths/`.

### One write on the common actions

"Row lock held" is the length of the write transaction, which takes the workspace row lock first.

| Action | Database | Row lock held before | Row lock held after | Whole request before | Whole request after |
| --- | --- | --- | --- | --- | --- |
| `task_start` | SQLite | 1875 ms | 23 ms | 2354 ms | 1275 ms |
| `comment_add` | SQLite | 1885 ms | 23 ms | 2362 ms | 1278 ms |
| `evidence_submit` | SQLite | 1896 ms | 23 ms | 2347 ms | 1287 ms |
| `node_complete` | SQLite | 1879 ms | 36 ms | 2381 ms | 1286 ms |
| `daily_propose` | SQLite | 1887 ms | 29 ms | 2378 ms | 1292 ms |
| `task_start` | PostgreSQL | 1988 ms | 20 ms | 2476 ms | 1276 ms |
| `comment_add` | PostgreSQL | 1997 ms | 20 ms | 2478 ms | 1312 ms |
| `node_complete` | PostgreSQL | 1953 ms | 21 ms | 2469 ms | 1298 ms |
| `daily_propose` | PostgreSQL | 1994 ms | 25 ms | 2482 ms | 1307 ms |

The other converted actions measure the same as `task_start` (all 17 scenarios in `after_*.json`).

### What limits the after number

The write itself is now a one case load (7 ms), a partial save (10 ms) and a commit. The remaining 1.27 s of the request is the response, which the API contract still defines as the full workspace. A profile of one request shows `public_ws` (the projection of every case for the caller) is about 85 percent of the time spent inside `persist_mutation`; the rest of the request is the full read it needs (0.15 s) and encoding an 18 MB body. None of it holds the lock. Cutting it needs a different response (for example the shell scope the frontend already accepts from `/api/actions`), which is a contract and frontend change.

### Staging, read only (rolled back transaction, 2026-10-15)

Staging runs exactly the files of 57ea79a (identical md5 for the files this change touches). The check loaded the real workspace (420 projects) and never committed.

| Measure | Result |
| --- | --- |
| Index ready (`projects_total.source_version` equals the workspace version) | yes |
| Cases without an execution system, cases of demo kind | 0 and 0, so the partial path is available |
| Rows the upgrade would change (users, projects, templates added) | 0, so the first write does not fall back |
| Full load plus upgrade | median 1.64 s (1.46 to 2.35 s) |
| Scoped load of the common collections and one case | median 27 ms (23 to 36 ms) |
| `save_partial` of one task change including index rows and counters, rolled back | median 0.21 s (0.19, 0.21 after a cold 1.6 s first run) |

So the locked part of a task write on staging is about 0.25 s against about 14 s, before the response is read.

### Sources sync (21.8k rows, 420 projects)

| Step | Database | Row lock held before | Row lock held after |
| --- | --- | --- | --- |
| Failed attempt (`failure`) | SQLite | 1367 ms | 19 ms |
| Failed attempt (`failure`) | PostgreSQL | 1400 ms | 24 ms |
| Unchanged snapshot (`apply_snapshot`, skip) | SQLite | 334 ms | 38 ms |
| Unchanged snapshot (`apply_snapshot`, skip) | PostgreSQL | 344 ms | 44 ms |
| Changed snapshot (`apply_snapshot`) | SQLite | 2675 ms | 714 ms |
| Changed snapshot (`apply_snapshot`) | PostgreSQL | 2797 ms | 754 ms |

The changed snapshot still holds the lock for the full diff save (0.62 s of the 0.71 s) and the fingerprint stamped after it.

Reproduce with `scripts/benchmark_write_paths.py` and `scripts/benchmark_source_sync.py` (`--db sqlite` or a PostgreSQL URL where databases can be created).
