# Case detail performance investigation — 2026-10-29

Latest follow-up: [snapshot implementation and verified 04286c2 staging measurements](CASE_DETAIL_SNAPSHOT_PERF_20261029.md). The acceptance target is still not met; that report supersedes the release measurements below.

Worktree: `/Users/vc/Local/YXMEEGLE-worktrees/case-detail-perf`. Only staging app `6abc0821454b8f31a5ef614a` and staging PostgreSQL `6abc081caa61051740e67fbd` were used. Production was not accessed or deployed.

## Root cause

Case reads amplified a small case into workspace-wide JSON work. The generic scoped-read predicate retained records with no `project_id`, which is necessary for some shared policy rows but wrong for formal-case activity. One staging case consequently decoded **15,303 global events** that the later visibility filter discarded. It also materialized **2,875 work schedules** and **534 unmatched daily records**, even though the case response already omitted those feeds. Overview and progress repeated this work concurrently, holding the Python interpreter and delaying the otherwise smaller node/task readers.

The staging profiler measured about 18,800 database JSON decodes and a **3,785 ms warm broad capture**. Scoping formal events in SQL and excluding the unused feeds reduced the equivalent warm capture to **762 ms** (1,447 total JSON loads including compact source rows). These are separate read-only process captures on staging data, not browser measurements. Project-specific events and the shared authority/policy collections remain loaded. Demo/test timelines retain their previous behavior.

Source reads had a second amplification: per-row PostgreSQL JSONB projection over quotation/history documents, repeated for different case/read shapes. `EXPLAIN (ANALYZE, BUFFERS)` showed **1,207 rows**, no disk reads, and **1,429 / 2,259 ms** execution for normal/SOP shapes. The bounded source-only cache now fetches and compacts a workspace version once, shares it across cases and shapes, and gives each request a fresh decoded copy. A staging-data comparison found **zero value mismatches across all 1,207 rows in both shapes**. Quote policy facts across duplicate quote numbers remain intact; full mutation/import paths retain full evidence.

The project list had an independent cold path: `/api/projects?view=portfolio` took **8,777 ms**, mostly waiting for bulk Lark node/task tables. It now returns labeled persisted cards and refreshes the optional overlay in the background, with one bulk refresh at a time.

## Instrumentation and hypothesis checks

Permanent request timers distinguish worker/dependency queue, handler wall time/thread CPU, DB pool acquisition/pre-ping, DB execution/count, source build/copy, storage/upgrade/seal, HTTP/rate-limit/read-slot waits, mutex/single-flight waits, and event-loop lag. `slow_request` covers the entire ASGI response and includes existing phase spans. Successful responses expose durations in Server-Timing; denied response headers remain uniform.

- On instrumented `d3fe237`, a 13,949 ms node read spent only 17 ms in the worker queue. Broad materialization, DB calls, upstream work and single-flight waits explained the rest; spans overlap and cannot be summed.
- Initial authenticated `3d73957` requests measured node assignments 7,384 ms, SOP tasks 7,897 ms and overview 8,046 ms. The supplied earlier page observations were 28 s cold / 13.9 s reload, with requests near 19 s.
- Reports eagerly started a 14-table / 8,782-record build at boot and occupied all three shared Lark read slots. That build took 55,984 ms. Boot warming was removed and bulk report concurrency reduced to one. Reports remain demand-loaded with bounded cold waits and stale reads.
- Removing report startup alone did not fix the page: `57363fd` still measured SOP at 15,177 ms cold / 12,844 ms reload. Process isolation alone and query reduction alone both missed the target. The combined runtime keeps the narrowed reads and moves ordinary live refresh/SOP projection into a supervised process, with report reading/normalization in a spawned worker. Both background processes run at lower CPU priority (nice 10). The existing DB lease/freshness/authority paths are reused; explicit blocking/forced refreshes retain their prior fenced behavior.
- Independent DB checks: 42 ms connection establishment, five idle app connections and no observed DB lock wait. App and DB cgroups exposed no CPU/memory quota or throttling. Later sampling did show scheduling contention: host CPU PSI some avg10 was 71.11%, while the app cgroup CPU PSI full avg10 was 28.73%. A separate CPU-only process later took 112–155 ms wall / 106–119 ms CPU as pressure subsided. These observations show variable scheduling pressure; they do not establish an OOM.
- Some browser requests exceeded both the response timer and full ASGI log by several seconds (for example 8,119 ms browser versus 3,354 ms ASGI). New browser evidence records request queueing, TTFB and transfer time. Such gaps alone do not identify a particular proxy/network component.

`queue` begins at ASGI entry and ends at synchronous endpoint entry; it cannot measure a proxy queue before the app receives the request. `dbpool` includes connection creation/pre-ping. CPU covers the synchronous endpoint thread, not other threads. The historical 2,587,000 ms simultaneous completion / LeaseLost incident was not reproduced; its exact cause is not established by the old logs.

## Other changes

DB initialization retries OperationalError with 1/2/4/8/16/30-second backoff. The supervisor no longer restarts a still-initializing web process at its old 60-second deadline. Connection establishment has a five-second bound; health performs SELECT 1 and returns 503 on a DB operational failure.

The source cache retains its 32 MB / 16-entry bounds, expires after five minutes, and invalidates on committed writes. Workspace version changes force a new key immediately. Authority-bearing people, grants, approvals and delegations are loaded fresh.

## Validation and final staging measurements

The target is **not met** on staging. The changes remove measured application amplification, but the observed host scheduling and HTTP delivery delays prevent a reliable sub-two-second page result. Do not treat this PR as a verified performance acceptance pass.

Served runtime SHA: `8a1ac90ecd90a521c6c1607aa5a6857a3bf1095f`, deployment `6ae2cbe2b1b373d6123a7883`. All 532 staged runtime files were checked against that commit. Health returned 200 with this exact SHA continuously for **308 seconds**, 04:33:03–04:38:11 UTC. Both app and the separate DB service were RUNNING. No production service was touched.

Authenticated real Chromium browser, 1280×800; milliseconds from navigation start:

| Run | SOP status | Four task rows rendered | Settled | Requests / API | Slowest request |
| --- | ---: | ---: | ---: | --- | --- |
| First case navigation after health observation | 13,821 | 13,821 | 16,104 | 31 / 8 | node assignments 8,276 |
| Warm reload 1 | 6,945 | 6,945 | 11,845 | 31 / 8 | progress 4,892 |
| Warm reload 2 | 16,420 | 16,420 | 19,675 | 31 / 8 | overview 10,962 |
| Warm reload 3, after report snapshot ready | 14,771 | 14,771 | 17,217 | 31 / 8 | shell 10,038 |

Reloads navigated away to health and back to force document loading; each case run waited for all eight APIs before the next. SOP/task visibility uses rendered element dimensions and CSS visibility; the task section is below the initial viewport. Separate screenshots capture the status and task rows. There were four task rows and no alert in each completed case run.

Project list rendered all 385 matching cases without a timeout: **8,174 ms first / 18,620 ms reload**. The portfolio API took **6,733 / 13,161 ms**, of which response transfer took **5,001 / 7,515 ms**. Its second Server-Timing total was 5,443 ms (934 ms thread CPU); the bulk Lark overlay no longer blocks it. The reload's resource count was captured later during separate endpoint probes and is not a clean page-only count; first navigation had 13 resources / 3 APIs.

Three sequential authenticated fetch rounds, browser end-to-end milliseconds:

| Endpoint | Round 1 | Round 2 | Round 3 |
| --- | ---: | ---: | ---: |
| node-assignments | 2,323 | 404 | 363 |
| sop-tasks | 989 | 281 | 486 |
| start-sop | 842 | 244 | 456 |
| sop-assignees | 219 | 396 | 4,631 |
| overview | 791 | 1,230 | 1,872 |
| progress | 1,288 | 1,122 | 1,205 |

Every response was 200. The 4,631 ms assignee outlier had **72 ms Server-Timing total**, 55 ms thread CPU, no HTTP upstream span and no >3-second ASGI slow log. Three additional rounds fetching the four original problem endpoints concurrently all returned 200 in **841–2,342 ms**, with server totals 758–2,258 ms. These endpoint results are distinct from full-page acceptance, which still fails.

Reports were absent at boot, started on demand during page use, failed one upstream read after 22,693 ms, then completed a 14-table / 8,782-record snapshot in 77,854 ms in the background process. Idle warm navigation after completion still failed, so reports alone do not explain the remaining browser delay.

### Remaining external evidence and limits

An independent Python process in the app container sampled 45 tiny CPU-only jobs once per second while warm page runs were active. Median thread-independent process CPU was **10.8 ms**; wall time was **41.7 ms median / 120.3 ms maximum**. The maximum sample used only 10.9 ms CPU. At that instant host CPU PSI some avg10 was **74.39%**, app cgroup PSI full avg10 **42.18%**, and `cpu.max` was unlimited. This process shares no web interpreter/GIL. It demonstrates container scheduling delays independently of request code. It does not identify the other host workload or prove every slow span is external.

HTTP delivery is independently material: warm case 2 overview took 10,962 ms in the browser while its complete ASGI response log was **3,605 ms**; browser transfer alone was **7,273 ms** for a 19,778-byte compressed response. Warm case 3 shell took 10,038 ms versus 2,702 ms Server-Timing, including **7,241 ms transfer** for 33,301 bytes. Browser request queueing was 0–4 ms, so browser connection scheduling does not explain this. The precise proxy/network component is unverified. A cold assignee HTTP call also took 2,999 ms upstream.

These measurements establish external bottlenecks large enough to exceed the requested SLA even after small application responses. They do not certify all remaining application code optimal. Host placement/capacity and network delivery investigation are the next useful experiments; no production changes or hosting-plan changes were attempted.

### Tests and commits

- Actual pre-push hook on combined runtime `e795cd2`: **5,493 passed, 39 skipped, 1 xfailed**, one known baseline failure: `backend/reports/test_performance.py::test_spawn_normalization_experiment_roundtrips_snapshot_data_and_gaps` (experimental helper lacks contacts gaps). Its existing failure is documented in the staging memory note. Two focused spawned-process/priority tests passed after the final nice-10 adjustment.
- Combined affected backend selection: **232 passed**. PostgreSQL projection/quote-facts tests were also run against a local PostgreSQL instance, rather than relying solely on SQLite. Live staging source projections matched all 1,207 rows in both read shapes.
- Frontend build and 22 of 23 hook commands passed. The existing `test:shell-mode` navigation `逾期 1` assertion remains the second documented baseline failure. No frontend source changed. Push used the documented baseline bypass after actually running the hook.
- Runtime package/offline smoke passed; staging services remained running throughout final validation.
- Principal commits: `d3fe237` request instrumentation; `154c952` demand reports/DB startup resilience; `67d5e77` shared source projection; `d6fbead` nonblocking portfolio overlay; `4f2dd9c` scoped formal event/feed reads; `e795cd2` combined background isolation; `8a1ac90` background CPU priority. Intermediate experiments remain in history; final runtime behavior is described above.

Unverified: historical 43-minute LeaseLost incident; an actual staging DB outage/recovery (retry/backoff covered with controlled tests); exact infrastructure source of delivery/scheduling pressure; strict cold/warm SLA under stable hosting; long-duration cache/freshness behavior. No deliberate staging DB outage was induced.

Raw release/test/profiler/browser evidence and screenshots are in ignored `.runtime/case-detail-perf/`: `perf-priority-health.jsonl`, `perf-priority-{cold,warm1,warm2,warm3}.json`, `perf-priority-list-{cold,warm-complete}.json`, `perf-priority-{sequential,parallel}.json`, `perf-priority-scheduling.log`, `perf-priority-runtime-last.log`, `perf-combined-hook.log`, `perf-frontend-results.txt`, and `perf-priority-{case,tasks,list}.png`. They are local review artifacts; the summary above is committed for PR reviewers.
