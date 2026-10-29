# Case-detail container resources — 2026-10-29

Continuation of [wire delivery investigation](CASE_DETAIL_WIRE_PERF_20261029.md). Worktree `case-detail-perf`, starting `a4172c9`; only staging app `6abc0821454b8f31a5ef614a` and DB `6abc081caa61051740e67fbd` are in scope. No plan settings, production changes, service suspension or spending.

## Before

Zeabur service metric, one-hour pre-change window: CPU average 52.67%, maximum 73.57%, minimum 23.46%; memory average 1,564.89 MB, maximum 1,734.42 MB, minimum 1,023.96 MB. These agree with the supplied preceding three-hour measurements (49.8% CPU / 1,566 MB average), but are separate windows.

A ten-second `/proc` sample inside staging, before this change:

| Process | CPU (% of one core) | RSS (KiB) | Anonymous RSS (KiB) |
| --- | ---: | ---: | ---: |
| supervisor | 0.0 | 19,956 | 14,068 |
| one uvicorn web interpreter | 0.2 | 392,420 | 383,844 |
| durable worker | 19.1 | 303,412 | 296,244 |
| live-refresh worker | 35.1 | 957,692 | 949,244 |
| idle report child | 0.0 | 56,084 | 49,428 |

Two multiprocessing trackers use about 13 MB each. Container memory.current was 1,649,278,976 bytes. This identifies background processes, rather than duplicated uvicorn workers or an active report build, as the observed CPU baseline and largest RSS owner. There is one web interpreter. Most RSS is anonymous; the database is PostgreSQL, not an embedded SQLite cache. `ps` is absent. `py-spy` installed under `/tmp`, but attachment and `/proc/*/smaps_rollup` are denied by container process permissions. There is no successful pre-change Python object/allocator trace, so exact retained heap versus freed allocator arenas must not be inferred from RSS alone.

The durable worker enumerated **37 workspaces**, including accumulated demo fixtures. Each call ran native-poll and job paths that loaded full workspace state even when no work existed. Live refresh checked every five seconds and refreshed sources on their roughly one-minute freshness boundary. The source importer can hold the fetched snapshot, database JSON, decoded workspace, prior project copy, candidate import and comparison/save structures simultaneously. Its database source snapshot is persisted, not a permanent process-global snapshot cache.

Read-only SQL sizes in the formal workspace: 15,956 events / 6.34 MB JSON; 9,599 tasks / 6.78 MB; 425 source quotes / 9.46 MB; 691 contract items / 9.54 MB; 422 projects / 4.64 MB; 2,875 schedules / 1.90 MB. The persisted source snapshot is 5.87 MB. Serialized bytes understate decoded Python graphs and transient copies. These figures establish input scale, not a heap census.

A real authenticated Chromium case navigation before this change reproduced a **12,510 ms first-screen request**, including **4,921 ms body delivery**. Session and shell took 307 and 434 ms. Four task rows and the expected current SOP, stuck-node reason and next action rendered. The earlier 61.6 ms app completion versus 4,082.9 ms browser result remains independent evidence of downstream delay.

`cpu.max` is unlimited and quota-throttling counters remain zero. High service CPU and host scheduling pressure do not establish quota throttling or an OOM.

## Changes

- The supervisor now launches one web interpreter and **one scheduled background interpreter**. A lazily started, isolated report-compute child remains under the web process; its measured idle footprint is about 88 MiB and zero CPU. The latter owns live refresh, durable jobs and SOP projection; the separate live-refresh child is no longer launched. Existing DB lease/CAS/advisory-lock fences remain.
- Hosted enumeration is limited to the configured company and its test workspace; accumulated demo workspaces are no longer processed by the hosted company worker. Local/demo operation keeps its existing enumeration.
- Jobs check only queue/delegation records and due scheduled-task existence before loading full state. Native observation similarly checks its small approval collections first. These are preflights only: execution re-reads authoritative state and preserves write/permission fencing. SOP projection checks pending work and its reconciliation age before loading workspace/source data.
- Background bulk refresh is spaced roughly five minutes apart with jitter, pauses without an authenticated reader active in the preceding three minutes, and backs off bulk work when cgroup CPU full-pressure avg10 is at least 25%. Roster freshness checks continue while idle. Public freshness labels and the 900-second admission bound are unchanged; stale data is not relabeled fresh. Force/wait refreshes keep their original behavior. Durable queue checks remain approximately thirty seconds apart, with jitter and interruptible waits.
- Completed live refresh futures are removed rather than retaining exception tracebacks and their temporary workspace graphs. A weak-reference regression proves a failed refresh releases its working set.
- Background cycle completion collects unreachable graphs and returns freed glibc allocations with `malloc_trim`, where supported. The image caps glibc arenas at two and sets its automatic trim threshold. These release freed memory; they do not evict live authorized data.
- Existing source JSON (32 MB / 16 entries), encoded case/list snapshots (8 MB / 32 entries), and report single-flight behavior remain. Consolidation removes a background interpreter's duplicate module/service state; DB-backed source/freshness/weekly snapshots remain shared through PostgreSQL.
- The existing manager-only `/api/admin/runtime-health` now includes per-process RSS, anonymous RSS, cumulative CPU time, thread count, worker queue depth and encoded read-cache bytes/limit/queue depth. It exposes no commands, paths, environment or credentials. Background logs record named stage CPU/wall time and RSS before and after releasing memory. This is cumulative CPU accounting; interval utilization is derived from two samples.

Validation, deployment and after measurements follow in the final release section.

## Active-load follow-up before final release

The first staging candidate, `f40d747`, passed five continuous minutes of health and the deployed 230-file runtime hash check. It reduced quiet container memory to roughly 350–400 MB, but active refresh exposed another retained footprint: `live_sources` used **17.307 CPU seconds / 42.795 wall seconds**, raised worker RSS to **402 MB**, and left **294 MB** after collection/trim. Allocated Python block counts then remained stable near 624,000 over repeated quiet cycles. This is evidence of a retained/high-water footprint, not proof of an unbounded leak. With web/report data loaded, container memory crossed 600 MB, so this candidate was not the final resource acceptance result.

The raw source cache retained decoded snapshots even for implicit background reads that always use `max_age=-1` and never reuse those snapshots. Implicit source reads now keep single-flight sharing but do not retain the returned graph. Explicit scoped source reads retain at most two entries within an 8 MB serialized-byte budget; an individually oversized entry is returned but not retained. The durable source snapshot remains in PostgreSQL.

If background RSS still exceeds 200 MiB after a completed cycle, heartbeat commit and graph release, the worker closes its readers and exits with a dedicated recycle status. The supervisor replaces **only that worker**, after it has exited; web stays alive and there is at most one background worker. A small container-local deadline preserves refresh spacing across that recycle, preventing repeated cold imports. Real subprocess tests verify web survives and both worker generations stop on requested shutdown. Unexpected exit codes still fail supervision normally.

Passive GET timers for home panels, my work, live status and source health no longer renew the activity marker. Authenticated navigation/domain reads and writes renew it; an unattended polling home page therefore cannot keep bulk source refresh running forever. This does not change authorization or public freshness labels.

First-candidate browser results are retained as intermediate evidence, not final acceptance: cold case render 6,111 ms; warm SOP plus four tasks 1,556 / 942 / 2,173 ms; cold/warm first list cards 2,616 / 1,346 ms. Cold first-screen spends 3,777 ms in upstream reads and 1,231 ms snapshot CPU, with 18 ms body delivery. The third warm progress request took 7,099 ms (3,417 ms DB spans, 394 ms thread CPU); spans overlap. The live list advanced from the earlier 385 to 386 cases, with two in progress and three SOP-in-progress, so this is not an immutable-data benchmark. No interactive business write was performed for QA.

The home-panel client also used a fixed 60-second timer while visible. It now schedules jittered 4.5–5.5-minute refreshes, skips them after three minutes without pointer/keyboard/wheel activity, and refreshes immediately when interaction resumes after idle or when the document becomes visible. Initial reads, query changes, explicit retries, mutations and session-scope invalidation retain their existing paths. A fake-clock component regression advances an unattended visible page ten minutes with zero new reads, then verifies an interaction refreshes the displayed body. Existing open tabs must load the new bundle to get this client change; the server-side passive-poll exclusion also applies to old clients.

Validation before final deploy: actual full pre-push hook **5,511 passed, 39 skipped, 1 xfailed**, with only the documented report-normalization failure. Final affected backend selections passed **261** and **72** tests respectively (overlapping selections), including the real-process recycle regression. The final frontend ran all 23 hook commands: 22 pass, including build/tooling; only the documented shell-mode assertion fails. Additional home-query/loading/panel checks pass, including the inactivity/resume regression. The hook predates the last small activity/gauge and frontend adjustments; those are covered by the affected selections and complete frontend command rerun rather than claimed as a clean full-hook rerun.

## Final release and browser measurements

Code commits are `f40d747` (process consolidation/preflights/gauges), `5fe97ca` (source retention and worker recycling), and `50b7af4` (activity-aware home polling). Final served application SHA is **`50b7af453c89a7a88fdd530cbbb5b84c73b8aa05`**, deployment **`6ae316edb1b373d6123a7f6d`**. The 534-file package passed offline smoke; all 533 source files match the commit, and all 230 deployed backend/script/deployment files match the staged hashes. Health reporting this exact SHA began at **09:53:10 UTC**, with more than five consecutive healthy minutes before browser loading began. One non-JSON response occurred during replacement before that good window.

Authenticated shared Chromium, 1280×800, HTTP/3. Full navigations go through health. Cold case is the first first-screen request on the new interpreter (`X-Read-Snapshot: miss`); warm runs use retained stale-while-revalidate snapshots, still with fresh authorization. Times below are **milliseconds from navigation origin**, not just API latency. Observers were installed before SOP/task/list mounting; the permanent render marks independently agree. Four task rows and the expected SOP/next-action/stuck-node text were present in every completed case run. No observed page errors, unhandled rejections, alerts or long tasks in these captures.

| Milestone | Final runtime | Target/result |
| --- | ---: | --- |
| Cold SOP status plus four tasks | 6,733 | <4,000: fail |
| Warm SOP status plus four tasks | 1,039 / 1,563 / 769 | <2,000: all three pass |
| Cold list first cards | 4,935 | Cold first screen still slow |
| Warm list first cards | 1,404 | <2,000: pass |
| Complete list/counts, cold / warm | 8,599 / 4,842 | Deferred pagination, not first render |

Final list shows 386 cases, two in progress and three SOP-in-progress. The source changed during this work, so this is a live-data comparison, not an immutable benchmark. No interactive business writes were used for QA. Earlier wire/snapshot reports contain fast and slow baseline runs; this release must not be credited with eliminating all natural latency variance.

The final cold first-screen API takes **5,145 ms browser / 5,059 ms server**, with **4.3 ms body transfer**. Server spans include **2,892 ms upstream**, **1,232 ms snapshot CPU**, **608 ms DB execution** and **1.2 ms gzip**. Spans overlap and are not additive. Its navigation additionally spends 597 ms on session and 693 ms on shell. This cold miss is chiefly upstream and application construction; it is not the earlier multi-second tiny-body download floor. Warm first-screen APIs take 127 / 193 / 170 ms. Progress remains deferred and takes 2,270 / 5,424 / 5,004 / 2,448 ms across cold and warm runs, with up to 2,609 ms DB spans, source-cache lock waits and loop lag. These are still application/storage opportunities.

Cold list page 1 takes **3,913 ms browser / 3,857 ms server**, **3.4 ms body transfer**, **1,182 ms snapshot CPU**, **817 ms DB spans** and **711 ms loop lag**. It still builds the whole portfolio before returning its first page. Warm page 1 takes 150 ms. The current final navigations do not reproduce the previous four-second downstream body delay; they do not disprove those earlier measurements.

A separate idle CPU-only process sampled 45 one-second-spaced jobs: **11.2 ms median CPU / 13.0 ms median wall**, maximum **34.7 ms wall / 14.8 ms CPU**. At that maximum the host CPU PSI some avg10 is 33.26%, app full avg10 1.11%; cgroup CPU quota remains unlimited. Residual scheduling variation exists, but no CPU-quota throttle or OOM is established.

The final runtime proves safe recycling in the real container: a source batch uses **18.106 CPU seconds / 47.5 wall seconds**, records **403,398,656 RSS bytes** in the worker at source-stage completion, retains zero raw source-cache entries, then drops to **289,968,128 bytes** after collection/trim. At 09:59:59 UTC it requests recycle; at 10:00:00 the supervisor starts worker PID 136. The replacement settles near **98 MB RSS**; web remains PID 7 and health stays 200 with the same SHA. The remaining post-trim footprint despite zero source entries demonstrates why allocator/process lifetime matters in addition to cache entry limits. It does not identify every allocation class; a successful heap trace is still absent.

Quiet resource acceptance and the final open-item summary are recorded after the observation window below.

Final memory-map diagnosis succeeded after running the read as UID 10001, matching the application: web RSS 360,384 KiB, anonymous/Pss_Anon 333,752 KiB; worker RSS 106,028 KiB, anonymous/Pss_Anon 81,988 KiB; swap zero for both. File-backed proportional memory is only about 10 MB web / 8 MB worker. Thus the remaining footprint is predominantly anonymous process allocation, not SQLite or mapped-file cache. `py-spy` attachment remains denied even as the application UID; these maps are not a Python heap census. Diagnostic installation is confined to `/tmp`; no dependency/image change was made for it.

## Quiet resource result and acceptance

The final **21-minute** quiet observation is **2026-10-29T10:06:00+00:00–2026-10-29T10:27:00.010263+00:00**, after browser QA and the activity grace period. It contains **22 one-minute Zeabur CPU and memory points**, plus independent `/proc` CPU-time/RSS samples. Health is 200 with the exact served SHA throughout the entire 1,262-second sampled quiet health window. App and DB service metadata both report RUNNING. No resource/plan settings, production services or spending changed.

| Resource | 20-minute pre-change window | Final 21-minute quiet window |
| --- | ---: | ---: |
| Mean service CPU | 50.69% | **4.66%** |
| Minimum / maximum CPU point | 31.54% / 67.23% | 2.80% / 10.87% |
| Mean container memory | 1,695.68 MiB | **559.08 MiB** |
| Minimum / maximum memory point | 1,605.56 / 1,761.04 MiB | 517.65 / **589.98 MiB** |

Mean idle CPU and sampled quiet container memory meet the requested 5% / 600 target in this window. CPU falls about 90.8% and mean memory about 67.0% relative to the measured pre-change window. These are separate live-service windows, not a controlled immutable-data experiment. Quiet means no test browser navigation; other clients' home-panel reads continue. One minute includes the extra `py-spy` installation/denied-attachment experiment, so it is retained in the series rather than discarded; its 10.87% CPU point is not a pure-idle sample. Per-process accounting distinguishes that diagnostic interpreter from the app.

Zeabur memory values are reported here in MiB (the CLI labels them MB). Container memory and individual-process RSS are different quantities; summing RSS double-counts shared mapped pages. The table is not a claim that summed RSS or every active-work peak stays below 600 MiB.

The separate 21-minute window including browser QA and source work, 09:58:10–10:19:10 UTC, averages **7.49% CPU / 535.71 MiB**, with sampled maxima **36.18% / 725.20 MiB**. Thus an absolute 600-MiB ceiling during source imports is **not met**. Worker recycling fixes persistent retention after a batch; it does not bound transient import copies.

Final stable process CPU/RSS accounting over 1243 seconds:

| PID / role | Mean CPU (% of one core) | Last RSS (MiB) |
| --- | ---: | ---: |
| 1 / supervisor | 0.06% | 26.4 |
| 7 / web | 2.71% | 374.5 |
| 8 / web resource tracker | 0.00% | 16.6 |
| 112 / report compute helper | 0.00% | 88.2 |
| 136 / consolidated worker | 1.22% | 134.6 |
| 137 / worker resource tracker | 0.00% | 16.5 |

The isolated report-compute helper remains at about 88 MiB and zero idle CPU. There is one scheduled durable/live worker, rather than a claim that only one non-web Python process exists. Fully consolidating that helper is an open item if the requirement is a literal one-background-process limit.

The exact post-deploy range comes from Zeabur's read-only `service.metrics` API. `zeabur service metric CPU/MEMORY -H 1` was also collected; its hour includes earlier deployments and is not presented as an all-new-SHA result. Raw metrics, health records, process samples, stage logs, browser captures and tests are retained under ignored `.runtime/case-detail-perf/resource-*`.

## Open items / capacity experiment

- **Overall latency acceptance is still not met.** Cold case is 6.73 seconds and cold list 4.93 seconds. Upstream node/table waits, cold snapshot CPU and DB/materialization remain measurable application work. Deferred progress and complete-list pagination also remain slow in some samples. Do not attribute these entirely to Zeabur or claim the application is optimal.
- Quiet resource targets pass, but source imports still require 18 CPU-seconds and transiently exceed 600 MiB. Smaller/streamed import plans, reduced snapshot copies and demand batching are useful next application work. A successful Python heap census remains unmeasured because process attachment is denied.
- If the user chooses a hosting-capacity experiment, try **2 vCPU and 2 GB RAM** on staging, with the provider confirming CPU guarantee/host placement. This gives room for the observed active source-import/report footprint. It is an experiment, not a verified plan/price or proven fix for the cold Lark/DB path; more RAM alone will not remove those waits. The CLI was not used to change size, and no plan change was made.
- Existing open browser tabs need to load the new bundle for the client polling change. The server's passive-poll exclusion already applies to old clients. Longer soak, all write workflows and a literal single-background-process architecture remain unverified/unimplemented.
