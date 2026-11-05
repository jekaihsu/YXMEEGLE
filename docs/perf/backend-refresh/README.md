# Changed source refresh and company/personal reads — 2026-10-25

Baseline: `f265e5943ec5ad274eae3f3a64456904e8a0639a` (merged redesign HEAD).
Implementation: `a9bab19` (source/storage), `accb7be` (company/My Work reads).
All inputs are fictional; source fetches and assignment sources are fake. The
PostgreSQL runs use a disposable local cluster with a private Unix socket. No
Lark calls, frontend edits, push, deployment, or sibling-worktree edits occurred.

## Source refresh

The fixture has 420 projects, 5,880 daily records and 21,849 normalized business
rows. Each scenario runs five times. `lock_held_ms` measures the complete write
transaction, including commit, as in the existing benchmark. Final paired
baseline-export/current-tree medians, in milliseconds:

- PostgreSQL changed refresh: total **1,713.9 → 1,430.5**; write transaction
  **716.4 → 110.6** (85% shorter).
- SQLite changed refresh: total **1,748.7 → 1,363.4**; write transaction
  **819.7 → 101.9** (88% shorter).
- Unchanged refresh: PostgreSQL **105.3 → 128.0** total / **43.1 → 43.1**
  transaction; SQLite **99.2 → 121.1** total / **37.9 → 37.1** transaction.
  The unchanged path still performs zero full loads/imports/business writes;
  no unchanged-path speedup is claimed. Wall-clock variation includes machine
  load and cache serialization.

The original pre-edit SQLite baseline was 1,774.9 ms total / 834.9 ms transaction
(`sources_initial_before.json`). Final raw medians/minima/maxima are in
`sources_{before,after}.json` (SQLite) and
`sources_{before,after}_postgres.json`. HTTP samples are in
`reads_{before,after}.json`.

A normalized, revision-proven workspace now captures its original rows during
its existing pre-lock read. Importing and preparing the entity delta, project
concurrency versions, changed project/task index rows, and counter values happen
before acquiring the workspace lock. The transaction upserts only changed
business rows in bounded batches, deletes removed rows, appends immutable events,
and publishes the precomputed indexes with the new workspace/cache revision.
Counter upserts are batched too.

Under the lock, both workspace revision and original root must still match.
Every storage write invalidates the persisted projection proof, including a
writer that does not bump the version. A concurrent local write therefore
forces a fresh full load/import/save. Generation, snapshot time, cache and
policy/authorization fences still run inside the transaction. Auto-enrollment,
legacy storage, missing revision proofs and bridge-bearing states retain the
full-save fallback. The unnecessary copy of all project trees is omitted when
SOP auto-enrollment is disabled.

The importer still processes the complete changed source snapshot outside the
lock. This change prepares an incremental persistence delta; it does not make
the source import itself incremental. Cold/fallback refreshes can still pay for
full persistence under the lock. Local SOP tables are untouched. Native tasks,
comments, approvals, case policy and append-only event history remain intact.

## Company dashboard and legacy My Work

The routes omit project comments, daily history, schedules, recurring rows,
unmatched/reviewed daily collections and source work items. Company also omits
event history. My Work retains events for pause/return reasons and unknown job
outcomes. Both retain complete task/review trees, files, evidence, financial
state, authority inputs, all case headers and source identity collections used
by visibility/redaction. Local SOP personal items still use the existing adapter.

Storage continues to mark these views read-only. Only the trusted route declares
that the projection includes every input needed by its read model; source
partial/truncated flags still make company totals incomplete. The ordinary
partial-workspace behavior of the pure read models remains unchanged.

The populated 319-case HTTP fixture has 7,018 native tasks and 9,000 daily reports.
Five warm requests follow one excluded initial request. Initial measured medians:

- Company: 243.34 → 163.95 ms; decoded JSON values 33,590 → 13,248.
- Legacy My Work: 189.96 → 159.96 ms; decoded JSON values 33,591 → 21,165.

Response contents, populated row counts and authority decisions are preserved;
this is a database decode/CPU reduction, not a response-size or cache change.
Wall times are local observations and can vary with other jobs on this machine.

## Reproduce

```sh
/Users/vc/Local/YXMEEGLE/.venv/bin/python -B scripts/benchmark_source_sync.py --db sqlite --projects 420 --repeats 5 --out /tmp/source-refresh.json
/Users/vc/Local/YXMEEGLE/.venv/bin/python -B -m backend.benchmark_case_home --samples 5 --output /tmp/company-my-work.json
/Users/vc/Local/YXMEEGLE/.venv/bin/python -B -m pytest backend/test_source_sync_prepared.py backend/test_storage_prepared.py backend/test_company_my_work_read_cost.py -q
/Users/vc/Local/YXMEEGLE/.venv/bin/python -B scripts/test_action_audit_postgres.py backend/test_source_sync_prepared.py backend/test_source_sync_refresh_cost.py -q
```

For PostgreSQL benchmarking, pass a disposable local admin URL to `--db`; the
benchmark creates and drops its own random database. Baseline replays use a
`git archive` export under `/tmp`, without modifying another worktree.

## Validation

- Full backend suite: **5,114 passed, 35 skipped, 1 xfailed, 9 failed** in
  388.80 seconds. All nine failures match the supplied baseline list:
  historical-date proxy visibility, SOP start evidence overlay, node-item
  progress, three partial-write daily cases, denied SOP read scope, deployment
  staging, and the Home production evidence panel. No new full-suite failures.
- Final new regression modules: **10 passed, 4 PostgreSQL skips**; the PostgreSQL
  source tests were also run separately with PostgreSQL enabled below.
- Source/storage/company/My Work/index suite: 244 passed, 9 PostgreSQL skips.
- Scoped read suite including populated demo/production equivalence: 123 passed.
- Source refresh regressions with disposable PostgreSQL enabled: 27 passed.
- New storage differential test compares 24 sequences of add/delete/reorder,
  owner/status/template/skip mutations with full saves, and reconciles indexes.
- New changed-refresh tests reject full business JSON reads under the lock,
  preserve local state on the prepared path, and force fallback for concurrent
  writes both with and without workspace version increments.
- New route tests compare populated full/projection responses in demo and
  production, verify unknown outcomes and source truncation, and prove the
  stored local state does not change.
