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

## Follow-up: normalization process experiment — 2026-10-25

**Decision: retain the existing thread executor in `snapshot.py`.** No runtime
process pool or configuration switch was added. Single-flight, stale reads,
fingerprint reuse, retries and shutdown behavior remain unchanged.

The new offline experiment compares the actual `compute.normalize` plus all
21 snapshot gap calculations in one thread against one **spawned** process.
Both return identical data/gaps. Source reads, canonical JSON hashing, source
network latency and final snapshot publication are excluded; serialization of
raw input and normalized output is included in process wall time. A real
FastAPI synchronous detail route is sampled concurrently via ASGITransport;
only requests overlapping normalization count toward latency. Five thread
runs, one cold process run and five subsequent warm process runs use the same
8,565-row fictional export. Worker duration uses a monotonic wall clock around normalization/gaps; it is
not a CPU-time counter. No CPU or memory limits were imposed locally.

- Thread: normalization/gaps worker duration median **37.6 ms**, wall median **39.1 ms**;
  competing detail p50/p95 **37.80 / 59.54 ms** (only five overlapping samples,
  because the GIL delays the sampler itself).
- Spawn, cold: worker duration **47.2 ms**, wall **210.1 ms**;
  detail p50/p95 **0.194 / 0.272 ms** (32 overlapping samples).
- Spawn, warm: worker duration **41.7 ms**, wall median **88.1 ms**;
  detail p50/p95 **0.204 / 0.319 ms** (139 overlapping samples).
- Raw input pickle: **1,414,167 bytes**; result pickle: **3,483,024 bytes**.
  The child high-water RSS reaches **99.7 MiB** after repeated jobs (cold
  83.4 MiB); the parent also retains its application, raw input and snapshot.
  RSS is a process high-water measurement, not incremental container memory.

The process clearly isolates GIL contention, but makes this representative
normalization workload **2.25× slower warm / 5.37× slower cold** in wall time.
A safe server would use spawn rather than fork its active threads/connections,
keep at most one worker, and handle child failure/shutdown. During refresh the
parent retains the old snapshot while serialized input, new data and child
memory coexist. The repository does not establish the container's memory
headroom, and this was not run under Zeabur's memory/CPU limits. Consequently
we cannot establish that the extra process is safe for the memory-limited
single container. The small CPU workload and unchanged-fingerprint reuse do
not justify adding that operational cost here. Much larger live workloads or
measured service latency objectives could warrant revisiting the decision
under the actual container quota. Chunked yielding was not introduced: it
would change normalization throughout compute code without eliminating CPU
cost or providing process isolation.

Reproduce without network or credentials:

```sh
/Users/vc/Local/YXMEEGLE/.venv/bin/python -B -m backend.reports.benchmark_normalization --output /tmp/report-cpu.json
```

Raw samples: `backend/reports/normalization-process-results.json`. The new
spawn roundtrip test checks normalization and every gap result against a real
`SnapshotStore` build. Existing cold-wait, cancellation, stale refresh, failure
and single-flight tests continue to validate the retained implementation.

Follow-up verification: reports/quotes/transport targeted checks pass **185
with 1 skipped**; a second run including the spawned-worker roundtrip and
quote creation/publish/reassignment checks passes **51 tests**. The complete
frontend run passes **101/115 scripts**; the 14 failures are in the previously
recorded baseline set (including dependency-layout/tooling failures).

Complete follow-up backend run: **5,112 passed, 32 skipped, 1 xfailed,
9 failed** (397.37 seconds). The nine failures exactly match the supplied
baseline: `test_home_executable_tasks`, `test_node_assignment_start_sop`,
`test_node_item_progress`, three cases in `test_partial_writes`,
`test_read_scopes`, `test_runtime` deployment staging, and
`test_ux_home_panels`. No new failures. `git diff --check` passes.
