# PM reports loading measurements

Measured locally on 2026-10-25 against base commit `5c39bb0`. All data and
requests were offline; no Lark reads or writes, database changes, push or deploy.

Reproduce from the worktree root:

```sh
/Users/vc/Local/YXMEEGLE/.venv/bin/python -B -m backend.reports.benchmark
/Users/vc/Local/YXMEEGLE/.venv/bin/python -B -m pytest backend/reports/test_performance.py backend/test_reports_compute.py backend/test_reports_routes.py backend/test_reports_home.py backend/test_project_progress.py backend/test_report_links.py -q
cd frontend
node src/reports/test-loading.mjs
node test-reports-requests.mjs
npm run build
```

`benchmark.py` generates a temporary fictional export with 8,565 rows:
3,000 field work orders, 1,500 office work orders, 1,500 field costs, 300 office
costs, 319 cases, 573 contracts, 1,200 plans, 30 vehicles, 45 instruments, 65
people, 30 monthly rows and 3 issues. It exercises rich-text/formula values,
linked costs, 105 work dates and plans spanning 1–14 days. These are assumed
volumes, not production counts. `--data /path/to/export` instead replays an
existing numeric-date Lark export through `backend.benchmark_reports`.

Before/after, on the same machine and workload:

- Five cold fixture builds, median: **73.65 → 68.21 ms**. The staging 30-second
  source read was not reproduced by offline CPU work.
- While 48 report requests await a single blocked cold build, a separate
  synchronous detail endpoint: **864.27 → 0.57 ms**. This deliberately uses a
  **1-second cold wait budget**, shortened from the production default 20 seconds.
  The delayed reader is released only after the detail request completes.
  Before: some report requests time out with 503; after: all 48 return 200.
  Both versions perform exactly one source read/build.
- Two simultaneous identical frontend readers: **2 → 1 HTTP requests**,
  measured with the actual React hook (base source loaded from `5c39bb0`).

HTTP timings from the existing benchmark: three rounds of 30 cached requests
and 300 forced cache misses per endpoint. Values below are p50 / p95 in ms.
They include TestClient routing, response copy and serialization overhead.

- `review`: hit 1.057 / 1.193 → 0.832 / 0.888;
  miss 0.975 / 1.859 → 1.009 / 2.258.
- `review/rows`: hit 0.419 / 0.624 → 0.453 / 0.523;
  miss 0.374 / 0.934 → 0.349 / 0.790.
- `sales`: hit 0.547 / 0.827 → 0.602 / 0.675;
  miss 1.732 / 2.380 → 1.589 / 2.029.
- `assets`: hit 0.347 / 0.490 → 0.378 / 0.395;
  miss **4.813 / 6.609 → 1.240 / 1.969**.
- `progress`: hit 0.484 / 0.704 → 0.697 / 0.786;
  miss 2.321 / 3.020 → 1.802 / 2.247.

The extra async dispatch adds a small scheduling cost to some cheap hot paths.
The material improvements are worker availability during cold builds and
uncached asset query CPU cost, rather than sub-millisecond hot-path timings.

cProfile findings:

- Cold build: normalize 134 → 113 ms inclusive; `cell()` 204,396 → 182,556
  calls, 80 → 66 ms inclusive. A multi-day plan's group is normalized once
  before date expansion; a review filter's group is normalized once per query.
- 100 uncached asset queries over the full synthetic date range: **1.389 →
  0.403 seconds** inclusive. Before, `day()` ran **450,000 times**, accounting
  for 0.871 seconds. After, asset queries reuse dates parsed during snapshot
  construction and make zero `day()` calls. Remaining CPU is date-to-week
  grouping, mileage parsing and aggregation. cProfile timings include profiler
  overhead and are separate from the unprofiled HTTP timings above.
- An offline comparison loaded the base compute module from git and checked
  **237 identical outputs**: 36 parameter variants for each of six reports,
  plus all 21 endpoint/department gap combinations. Independent status totals
  also match all 3,000 field rows across 16 weeks.

Implementation:

- Keep the dedicated build executor, five-minute TTL, stale reads, warm-up,
  retry cooldown, response LRU and result single-flight. Await cold readiness
  asynchronously so waiters do not consume Starlette's shared 40 worker tokens.
  Authorization and query/JSON work still run in workers. Cancellation and
  timeout of one request cannot cancel the shared build; a later build failure
  is consumed even when its reader has disconnected.
- Keep existing lazy tabs. Coalesce in-flight frontend requests by session
  epoch, mock/live mode, endpoint and canonical query. Cancel transport only
  when its last reader leaves. Preserve bounded warming retries and stale
  response/session guards.

Verification:

- Full backend suite: **5,059 passed, 9 failed, 23 skipped, 1 xfailed**.
  Failures are the existing home/proxy, node evidence/item shape, partial daily
  writes, denied SOP read and deployment packaging cases; none is a reports
  regression. The deployment failure is the missing staged
  `backend/report_link_vocabulary.json` source. All nine were rerun with the
  three base reports modules restored from `5c39bb0` and failed identically.
- Focused reports/progress/links backend checks: **174 passed, 1 skipped**.
  The seven new backend cases cover cold worker availability for both `home`
  and individual reports, cancellation, timeout, stale refresh, failure, cached
  dates and equivalent group filters.
- Existing report/home frontend scripts: **8 passed**; the known standalone
  `test-reports-interactions.mjs` failure remains (`root` is undefined without
  a `REPORT_CASE`). Its seven parameterized scenarios pass through
  `test-reports-requests.mjs`.
- All 112 root frontend test scripts: **96 passed, 16 failed**, both with the
  new hook and with the base hook restored. Besides the supplied known failures,
  existing failures include API response, dev tooling, dispatch, home panels,
  ops sync, P2 routes, plan panel, search input, shell and SOP checks. The shared
  pnpm dependency directory lacks the nested esbuild path expected by one
  tooling check and lacks `playwright-core` required by the search-input script.
- New frontend request and lazy-tab checks pass, including overlapping readers,
  one/last-reader cancellation, retries, warming retries, session isolation and
  expired-session signaling after the initiating reader leaves.
- TypeScript and Vite production build pass. Browser verification of
  `src/reports/preview.html?mock=1`: only ReviewTab loads initially; SalesTab
  and ProgressTab load on selection; zero `/api/reports` network requests.

Remaining limits: live Lark fetch latency and staging hardware were not
measured. Snapshots are per process and not persisted across restarts; a new
process still waits for its first source read, while other HTTP routes can
continue. Python normalization remains in a thread and shares the GIL; this
fixture's CPU build is under 0.1 seconds, not 30 seconds. Much longer plan
spans or much larger datasets may warrant a separate process or persistent
snapshot. Warm-up and stale-while-revalidate already existed and are retained.
