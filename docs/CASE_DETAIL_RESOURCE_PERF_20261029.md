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

- The container now launches one web interpreter and **one background interpreter**. The latter owns live refresh, durable jobs and SOP projection; the separate live-refresh child is no longer launched. Existing DB lease/CAS/advisory-lock fences remain.
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

Validation before final deploy: actual full pre-push hook **5,511 passed, 39 skipped, 1 xfailed**, with only the documented report-normalization failure. Final affected backend selection passed **261 tests**, plus **72** cache/runtime/source tests and the real-process recycle regression. The final frontend ran all 23 hook commands: 22 pass, including build/tooling; only the documented shell-mode assertion fails. Additional home-query/loading/panel checks pass, including the inactivity/resume regression. The hook predates the last small activity/gauge and frontend adjustments; those are covered by the affected selections and complete frontend command rerun rather than claimed as a clean full-hook rerun.
