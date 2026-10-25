# Case list and home loading performance — 2026-10-25

Baseline: `5c39bb0`. All measurements use fictional local data, SQLite and mocked assignment reads; no live Lark, deployment or persistent external data was used. Raw cold/warm samples, byte counts, query counts and JSON decode counts are in [receipt.json](receipt.json).

## Measured results

HTTP fixture: 319 cases, 7,018 native tasks, 9,000 daily reports, 7,915 events and 65 users. The assignment profile supplies nine mocked assignment rows per case; its member has 1,914 open assignments, with 100 returned on the first page. HTTP numbers below are medians of seven warm requests after one excluded initial request. CPU contention from concurrent local workers makes latency less stable than query and decode counts.

- Default assigned panel, assignments disabled: **237.85 → 11.50 ms**; JSON values decoded **33,590 → 451**. SQL **8 → 9**: the extra small header query replaces decoding the workspace.
- Assigned panel with mocked assignments: **402.33 → 183.87 ms**, SQL **327 → 12**, JSON values decoded **33,590 → 14,114**. The same 100 assignments remain in the response.
- Portfolio with mocked assignments: **246.06 → 161.68 ms**, SQL **333 → 15**. Legacy completion audits now use one workspace read instead of 319 case reads.
- Confirmation panel, assignments disabled: **213.27 → 145.34 ms**, JSON values decoded **33,590 → 21,548**.
- Confirmation panel with mocked assignments: **342.71 → 267.13 ms**, SQL **327 → 12**.
- Portfolio without assignments: **55.99 → 67.01 ms** in the recorded runs; query/decode counts unchanged. Paired interleaved probes also caught and removed an intermediate SQLite query-plan regression: keeping an outer `kind IN (...)` predicate preserves the `(workspace_id, kind, entity_id)` access path while filtering invisible project children. These noisy timings do not establish a no-assignment portfolio speedup.
- Daily refresh replay: **5,251.71 → 630.76 ms** (five runs, 319 confirmations and 8,932 daily rows). This replay creates source-native cases without operational SOP tasks; it is an importer CPU benchmark, not an entire source-sync or lock-duration measurement. Profiling reduced normalized-code calls from about 2.88 million to 46 thousand.
- Frontend 319-case filter/sort CPU: **29.04 → 2.95 ms**, after excluding two warm-up samples. Unchanged inputs also reuse the modeled case rows on pin, view and expansion changes.
- After its workspace loads, default Home now makes **one request instead of three**: hidden confirmation/attendance cards no longer fetch. A manual workspace refresh triggers one subsequent panel read, rather than a read during the workspace update followed by another local refresh read.

Response schemas and populated payloads remain unchanged. Portfolio responses are about 530 KB decoded / 22 KB gzip without assignment overlays, and 541 KB / 21 KB gzip with overlays. The populated assigned preview is about 92 KB / 3.2 KB gzip. This change does not claim a payload reduction; it removes redundant reads, full-row decoding and a redundant FastAPI JSON conversion for the portfolio.

## Changes and behavior safeguards

- `backend/home_panels.py`: header-only reads for disabled assignment / SOP-only panels; omit unrelated history and schedules from other reads; avoid building native local-task details that panel selectors discard. Applied skip requests retain the full native task/evidence path.
- `backend/storage.py`, `backend/app.py`: opt-in omitted-kind reads, tagged `_partial` so they cannot be saved. Ordinary readers retain their original calling convention. Portfolio uses `JSONResponse`, matching the existing workspace response path, to encode already-JSON-compatible values once.
- `backend/projects_portfolio.py`: bound counts and child reads to visible case IDs, retaining all project headers where ambiguity checks need them.
- `backend/node_assignment/{bulk,service}.py`: batch legacy-completion audit reads while retaining ordering, workspace isolation, native record/approver/timestamp checks and the existing single-case reader.
- `backend/v4_sources.py`: remove fetched daily IDs from existing collections once; index exact full codes, reviewed aliases, native project IDs and daily reviews for a replay. The existing resolver still decides attribution and ambiguity. Native/text conflicts, suffixes, manual reviews, duplicate input last-row-wins behavior and unfetched history remain covered.
- `frontend/src/{ProjectsList.tsx,projectsListModel.ts}`: memoize case modeling and compute sort dates/attention once per row, preserving urgency, unknown-date and tie ordering.
- `frontend/src/{UnifiedHome.tsx,useHomePanels.ts,useHomeCompany.ts}`: request visible home data only; use the existing reload generation instead of separately reacting to both generation and workspace version; hold the panel generation until manual refresh finishes.

New checks compare projected panels against full reads in demo and production, compare indexed daily decisions against the original complete resolver, assert one audit query for hundreds of cases, verify audit bindings/order/isolation, preserve unfetched/duplicate daily behavior, reject saves of omitted reads and count actual frontend requests during refresh.

## Reproduce

From the worktree root, using the supplied environment:

```sh
/Users/vc/Local/YXMEEGLE/.venv/bin/python -B -m backend.benchmark_case_home --samples 7 --output /tmp/case-home.json
/Users/vc/Local/YXMEEGLE/.venv/bin/python -B -m backend.benchmark_v4_refresh --samples 5
/Users/vc/Local/YXMEEGLE/.venv/bin/python -B -m pytest backend/test_home_read_performance.py backend/test_v4_read_performance.py backend/test_projects_portfolio.py -q
```

From `frontend/`:

```sh
node benchmark-projects-list.mjs
node test-unified-home.mjs
node test-home-query-refresh.mjs
node test-projects-list-model.mjs
node test-projects-list-ui.mjs
npm run build
```

Before measurements were recorded before implementation. A second populated-assignment baseline used the original backend implementations loaded from `git show 5c39bb0:<path>` into an isolated Python process, with the unchanged benchmark fixture; no worktree checkout was changed. Frontend baseline failures were checked by temporarily restoring only the changed frontend source files in this worktree, then restoring their exact current contents in `finally`.

## Validation

- New backend logic plus portfolio / partial-write / timing checks: **45 passed**.
- Import, relationship, review-version, provenance and daily-shape checks: **154 passed, 1 skipped**.
- Broader case/home/index/storage/company/my-work selection: **139 passed** before adding the six production-equivalence cases; those cases subsequently passed too.
- Thirteen related frontend scripts passed: home counts, executable work, layout, query refresh, people, people cards, reports, unified home, portfolio model, portfolio DOM, company routes, table sorting and view-data. TypeScript / Vite production build passed.
- Two additional frontend scripts fail identically with original sources: `test-home-panels.mjs` (fixture source date is beyond its cache-retention window) and `test-shell-mode.mjs` (existing sidebar overdue expectation).
- Full backend final result: **5,071 passed, 9 pre-existing failures, 23 skipped, 1 xfailed** (335.90 s). The nine pre-existing failures were independently reproduced against original `5c39bb0` implementations; their exact node IDs are in the receipt. An initial new compatibility failure in `test_partial_response_uses_one_snapshot_when_a_writer_commits_after_the_header` was fixed and its complete regression module passes.

## Remaining bottlenecks

Company dashboard and legacy `/api/my-work` still decode the full workspace: about 33,590 JSON values, with roughly 250–300 ms local request times in this fixture. Their authority/redaction and review calculations remain intact; a further narrow projection needs its own equivalence work. Larger assignment-backed views still read linked daily evidence and recompute per-case source evidence. Cold Lark / roster latency, PostgreSQL network latency, source-sync write/index rebuilds and browser wall-clock first paint were not measured here. The importer replay does not measure contract/reporting task-reassignment scans. No shared response cache or new staleness policy was introduced.
