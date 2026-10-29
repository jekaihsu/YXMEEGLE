# Case detail staging follow-up, 2026-10-29

All work was done in `/Users/vc/Local/YXMEEGLE-worktrees/case-detail-perf`, starting at `425c192`. Production and the bare repository were not modified.

## Findings and changes

### A. Slow case reads

The overview request had a 10-second client timeout followed by an automatic retry. This explains the duplicate overview request and its exact 10-second cutoff. The request now has one 20-second budget and an explicit user retry after failure. Pending readers still coalesce. It does **not** establish why the first server response took 10 seconds.

Inspection confirmed that node assignment already runs roster and case reads in parallel, shares both through per-service single-flight caches, and serves last-good data with background revalidation. The caches are shared by SOP permission reads through the same node-assignment service. Adding another roster cache would duplicate the existing mechanism. Existing fake-upstream cache/concurrency tests were run again.

The application token mint had an independent 15-second HTTP timeout that could exceed the remaining upstream operation budget. It now uses the smaller of the configured request timeout and remaining budget. A regression test verifies a 0.5-second remaining budget reaches the HTTP transport as 0.5 seconds.

The shared database source cache previously retained a single entry even when it exceeded its 160-million-character limit, had no entry-count limit, and left failed fetch locks registered. It now rejects entries over 32 MB of UTF-8 payload, retains at most 16 entries within that total byte budget, removes expired entries, and removes failed flights. This bounds retained raw source payload; it does not bound all process memory or transient JSON decoding.

A latency-injecting JSDOM reproduction uses the real ProjectDetailGate and API timeout code, with a 10.1-second first response and a 5.1-second second response. Warm responses take 10 ms. It uses the files route to isolate the shared case-snapshot reader from unrelated workflow requests. One run per condition, baseline `425c192` versus the changed code:

| Condition | Before settled | After settled | Before/after requests |
|---|---:|---:|---:|
| Cold simulated upstream | 15,157 ms | 10,129 ms | 2 / 1 |
| Warm simulated upstream | 58 ms | 57 ms | 1 / 1 |

Run from `frontend`: `node scripts/measure-case-read-latency.mjs`. It writes `.runtime/case-detail-perf/latency-reproduction.json`. These are controlled client-path results, not staging browser timings or evidence of faster upstream service. The cause of simultaneous ~10-second server reads remains unverified while the cluster is unreachable.

### B. Staging outage

The deployment list reports `6ae2980aea16512cf741910d` as RUNNING. That metadata does not establish health. Fresh diagnostics on October 29:

- Service status: `CLUSTER_UNREACHABLE`, trace `2ecec18813ff2e9289911cb729ea3d6f`.
- Pod status/events interface: `CLUSTER_UNREACHABLE`, trace `3e13fb2af11de8012cd781c8dd6d561d`. Restart counts and OOM/health-check events could not be retrieved.
- Runtime logs for that exact deployment: `INTERNAL`, cluster log endpoint timed out awaiting headers, trace `240f47ca36287a9c8be5b3958f48c183`.
- CPU and memory metrics, with a valid current end time: `INTERNAL_SERVER_ERROR`, trace `51ea5cfd6e224ef846656b39c8fe0fa1`.
- Service `resourceLimit` and `maxResourceLimit`: CPU and memory are both null. No explicit limit is exposed; host capacity and actual consumption remain unknown.
- Public `/api/health`: connection timeout after 12.061 s at `2026-10-29T01:18:54Z`.
- The exact case URL was opened in real Chrome. It showed `ERR_TIMED_OUT`. Screenshot: `.runtime/case-detail-perf/staging-outage-20261029.png`.

Two T3 browser opens also timed out after 15 s; native Chrome was used for independent browser evidence. The temporary case tab was closed afterward.

Boot inspection: schema creation and workspace migration run before Uvicorn starts. Live roster, attendance and source warmups use `ensure(..., wait=False)`; weekly attendance queues its refresher; the web supervisor waits for DB-aware health before starting the durable worker. Health performs a database `SELECT 1`, not Lark reads. No new eager warmup was added. The available evidence establishes an unreachable Zeabur cluster/control path, but cannot rule out an app failure preceding that outage. It does not justify claiming an OOM, crash loop, or CPU cause.

### C. Missing assignment controls

A cold-roster account that had only assigned-task access skipped roster recovery when already participating in a task. Such an account could also be a node manager, but the server returned the participant view without manager edit actions. The cold read now recovers roster authority for that case too. A regression test creates this precise participant + node-manager combination and verifies `edit` is present.

Server SOP task responses now carry an assignment-blocked reason distinguishing unavailable roster, missing node authority, SOP enrollment policy, disabled writes and completed/archived tasks. Denied overview rows show a disabled assignment button and a visible reason. Client controls still use server permissions; no new grant is inferred from role labels or roster loading alone. The reviewer's actual live account cannot be classified until staging can serve its authenticated response.

### D. Task and recommendation noise

Real unfinished task rows now precede a closed native disclosure containing recommendations and their count. The navigation label explicitly identifies the number as pending tasks, while the text explains that full lists include completed, archived and cancelled tasks. The secondary node list identifies itself as Lark/local-flow tasks and explains that SOP tasks are in the separate section. Its empty message no longer claims the node has no tasks of any source. Thus the four pending tasks and a separate five-task full list can be understood without presenting two unlabeled totals.

## Validation and release

Validation, push and staging deployment results are appended below after execution. No five-minute health success or authenticated cold/warm browser measurement is claimed while staging remains unreachable.
