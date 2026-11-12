# Case detail loading — 2026-10-25

Implementation: `facc307` (backend), `faac73a` (frontend). Baseline: `5c39bb0`.
All fixtures are fictional. No live Lark calls, source writes, pushes or deployments.

## Measurements

The checked-in [JSON results](case-detail-20261025.json) contain 11 sequential
TestClient requests per endpoint, with identity encoding, temporary SQLite and
setup excluded. Baseline code ran from an isolated temporary archive of
`5c39bb0`; the same new benchmark/fixtures ran against both versions. These are
local application timings, not staging network measurements. Other test
processes shared this machine, so small differences are noisy.

Company fixture: 319 cases, 7,018 tasks, 7,915 events and 9,000 daily reports.
Median before → after:

- `/api/projects/p001`: **31.01 → 26.67 ms**, 63,592 bytes unchanged.
- `/api/projects/p001/navigation`: **40.96 → 23.88 ms**, output unchanged.
- `/api/case-detail/p001`: **739.35 → 24.68 ms**, 20,826 bytes unchanged.
- `/api/projects/p001/progress`: **38.20 → 27.47 ms**, 4,665 bytes unchanged.

The same company in synthetic Lark identity mode with an additional 8,565-row
source cache (external readers disabled):

- Project: **34.49 → 31.10 ms**, 65,254 bytes unchanged.
- Navigation: **39.29 → 26.71 ms**, 279 bytes unchanged.
- Case detail: **864.75 → 49.29 ms**, 21,736 bytes unchanged.
- Progress: **94.73 → 48.41 ms**, 4,829 bytes unchanged.

An oversized single case with 400 contract lines and 800 tasks/evidence links
reduced tree construction from **272.80 → 7.63 ms**. A separate comparison
asserted exact old/new read-model equality on this fixture. The first baseline
before any edits measured 491 ms for the company case-detail endpoint; the
11-request baseline above was slower under shared CPU load. Both identify the
same dominant work: projecting every company's task for one case.

Profiling the 8,565-row workload after scoping exposed another cost: source
health copied and redacted all raw fields even though only status was consumed.
The metadata-only change alone reduced case detail **99.40 → 58.86 ms** and
progress **103.54 → 61.68 ms** in that measurement round.

## Changes and preserved behavior

- Case detail uses the existing scoped P2 capture instead of loading all case
  trees. Generation fences, visibility, privacy, redaction, selection and source
  timestamps remain in force. Scoped/full response equality is tested.
- Source health on scoped case reads counts the same admitted record identities
  and keeps table metadata. It skips raw-field copying and redaction. The small
  metadata result still passes through redaction. Ready, partial, failed,
  forbidden and loading health results match the full source-health path.
- Navigation copies only relevant inputs, preserving input purity. Contract and
  parent/child indexes replace repeated full scans; order and contested edges
  remain unchanged. The unused copy of workspace state for health was removed.
- JSON-native project and case-detail models are encoded directly, avoiding an
  extra recursive FastAPI conversion. Added timing coverage distinguishes
  capture, projection and encoding; case 404s retain indistinguishable headers.
- Progress computes automatic bridge candidates in memory, using persisted
  owner decisions from its captured read. It no longer writes/locks the
  workspace during GET. Link-review routes still persist their own decisions.
  Weekly aggregates use the captured reports snapshot, never `store.get()`;
  candidate lookup is indexed once per request.
- Frontend overview starts detail, assignments and progress together: **6 → 3
  initial requests**. Document entry makes **6 → 1**. SOP tasks, eligibility and
  assignees start on flow entry without waiting for detail. Pending detail reads
  remain shared across tab changes, with existing session/generation fences.
  `CaseDetail.tsx` is presentational and has no fetch waterfall to change.

## Validation

- Final affected backend suite: **309 passed, 1 skipped**. Covers project detail,
  case detail/navigation, progress, P2 integration, report links, public HTTP
  boundaries and both redaction suites. Four real-coordinator tests prove
  responses finish while mocked source/roster/report refreshers are stalled.
  Warm progress is checked for zero DML/row locks and zero blocking reports reads.
- Full backend checkpoint: **5,059 passed, 23 skipped, 1 xfailed, 9 failed**,
  412.79 seconds. This checkpoint preceded the final metadata-only optimization;
  the final affected suite above covers that change. All nine failures were
  reproduced against the untouched `5c39bb0` archive: historical proxy assignment,
  start-SOP evidence overlay, node item progress, three partial daily-write cases,
  denied SOP reads, missing deployment vocabulary JSON, and home evidence state.
- All `frontend/test-*.mjs`: **98 scripts passed, 15 failed**; all 15 failures also
  reproduced against `5c39bb0`. No timeouts. Failed scripts: api-response,
  dev-tooling, dispatch-board, dispatch-fixes, home-panels, home-target-navigation,
  ops-sync-panel, p2-routes, plan-panel, read-loading, reports-interactions,
  search-input, shell-mode, sop-tasks and ux-case-detail.
- New rendered React regression, reload-generation, project progress and related
  frontend scripts passed. `npm run build` passed. `git diff --check` passed.

Reproduce the benchmarks from the worktree root:

```sh
/Users/vc/Local/YXMEEGLE/.venv/bin/python -B -m backend.benchmark_case_detail --rounds 11
/Users/vc/Local/YXMEEGLE/.venv/bin/python -B -m backend.benchmark_case_detail --rounds 11 --source-records 8565
# Add --profile for synchronous handler cProfile output.
```

## Remaining costs

Single-case SQL still decodes root metadata, shared catalogues/source identity
rows and, for P2 reads, the complete source cache once. SQLite's generation-fence
JSON extracts also parse that cache. Company-wide tables, report snapshot build
CPU/GIL contention and per-week aggregate cache misses remain outside these
changes. No staging latency or PostgreSQL query-plan claim is made. In the local
fixtures the main project endpoint was already fast; its small measured change
should not be treated as a guaranteed end-to-end speedup.
