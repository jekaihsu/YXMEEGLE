# Case detail snapshot follow-up — 2026-10-29

Worktree: `/Users/vc/Local/YXMEEGLE-worktrees/case-detail-perf`, starting at `28c62fe`. Only the requested staging app and database are in scope. Production and the bare repository are not modified.

## Before: attribute the browser/ASGI gap

Authenticated Chromium, 1280×800, staging runtime `8a1ac90`:

- Overview: requestStart 2,154 ms, responseStart 6,008 ms, responseEnd 11,078 ms; 3,736 ms Server-Timing total. **3,854 ms wait + 5,070 ms transfer for 19,485 gzip bytes** (115,557 decoded bytes). Node assignments transferred 5,342 bytes in 4,979 ms; SOP tasks transferred 4,255 bytes in 4,651 ms. This reproduces the prior several-second gap after response headers. It cannot be attributed to JSON parsing/rendering, which occurs after responseEnd, or to uncompressed payloads.
- Browser request scheduling was 1–4 ms. Most resources and all measured APIs negotiated HTTP/3; an initial vendor asset used HTTP/2. Multiplexing is already active. A fresh probe connection took approximately 109 ms to establish; this is far smaller than the delivery gap. API responses use gzip, including when the browser negotiates its normal supported encodings. Brotli is not required to explain or fix these tiny payloads.
- Five case APIs start together after session → shell. Progress starts only after the detail renders, at 11,107 ms, and ends at 13,772 ms. Initial document DOMContentLoaded/load were 427/428 ms and cached detail assets finished by 443 ms. The network waterfall dominates; the first meaningful detail render follows the 11,078 ms response by about 29 ms. A buffered long-task observer attached later recorded no long tasks during the endpoint probes and project-list transition; it does not prove there were none before attachment.
- One Uvicorn web process, one durable worker, one live-read process and one report subprocess were observed in `/proc`; there is no configured Uvicorn worker pool. Five concurrent endpoint probes had only 14–36 ms ASGI-to-endpoint queue time. Progress increased from **2,150 ms sequential / 1,963 ms server** to **8,158 ms parallel / 8,093 ms server**; other parallel reads were 1,773–1,940 ms. Application work/contention remains material; there is no evidence that a long thread-pool queue accounts for the multi-second response-transfer gap.
- `zeabur service metric`, preceding hour: CPU average **41.05%**, maximum **117.23%**; memory average **1,174.92 MB**, maximum **1,651.10 MB**. Both `cpu.max` and `memory.max` are unlimited. Container CPU PSI full avg10 was **24.59%**, some **30.00%**. These are scheduling-pressure observations, not a proved configured-plan CPU ceiling or OOM. Both app and DB were RUNNING. No plan, limit or service lifecycle was changed.
- Independent CPU-only process, 20 one-second-spaced samples: median **20.61 ms process CPU / 88.82 ms wall**, maximum **163.46 ms wall**. At completion, host PSI some avg10 was **55.61%**, container full **17.51%**; cgroup `nr_throttled=0`, `throttled_usec=0`, unlimited quota. This demonstrates descheduling independently of the Python web GIL, rather than a measured quota ceiling. The smallest capacity experiment supported by observed peaks is **two guaranteed vCPUs and at least 2 GB RAM** (measured peak 1.65 GB); this is a capacity estimate, not a verified Zeabur SKU or price. Try host placement/proxy diagnosis first. No purchase is authorized or performed.
- Same-document project-list transition: API **5,343 ms**, including **4,989 ms server**, **1,134 ms thread CPU**, **206 ms transfer** for **48,393 gzip / 859,476 decoded bytes**. Five cards were visible; list rendering followed response completion by about 12 ms. The optional bulk Lark-chain projection still spends CPU even though its network reads no longer block.

Raw evidence: ignored `.runtime/case-detail-perf/round3-{before-probes,cpu,memory,processes,scheduling,app-service,db-service}.*`; browser screenshots are under the T3 browser-artifact directory.

## Changes

- `/api/projects/{id}/first-screen` returns project detail, assignments, SOP tasks, start status and progress in one response. Its builder seals one scoped case capture, gives each existing projection a private copy, and retains the existing visibility/permission checks and normal-versus-SOP quote-field projection. Responses are encoded once, compressed by the existing gzip middleware, bounded to 8 MB / 32 entries, single-flight, fresh for 15 seconds and stale-while-revalidate for up to 120 seconds.
- Cache keys include authenticated identity/admission and SOP checklist/identity/policy revisions. A changed workspace version marks the last-good snapshot stale and starts revalidation instead of discarding the first screen; it still expires after 120 seconds. A new roster verification timestamp alone does not change the identity key: admission is checked against that fresh timestamp before cache lookup. All other viewer fields remain in the key. Identity is rechecked on every HTTP read and background case refresh. Write attempts (including ambiguous failures) invalidate snapshots; invalidated in-flight work cannot repopulate the cache. Existing mutation paths still reauthorize writes and obtain fresh read-backs.
- The frontend seeds its existing validated readers before mounting the case view. Status and tasks render together, without the four separate heavy reads or the progress waterfall. Assignee choices load after the first payload. Existing skeletons reserve space during reads; legacy/document routes retain their prior behavior.
- Portfolio reads keep persisted index cards and the existing last-good Lark-derived overlay when available. Upstream table refreshes remain nonblocking; the bounded encoded-response cache removes repeated bulk projection work from warm requests. Per-group display limits already bound rendered rows; all cards remain available for complete counts and filters. Assignment detail is checked in the case view.

## Validation / staging acceptance

Release measurements and exact served SHA will be recorded after staging deployment and five minutes of health 200 on that SHA. The prior runtime's SLA failure remains the baseline until that verification completes.

Pre-release checks: 72 focused backend tests pass, including reader parity, failed/oversized cache entries, stale single-flight, post-write fencing, viewer isolation, and persisted portfolio behavior. All 23 frontend hook commands ran; 22 pass, with only the documented baseline `test:shell-mode` assertion failure. The rendered first-screen regression verifies status and task rows together and no separate heavy API reads. Full backend hook result is recorded with release evidence below.


### First rollout and revision correction

Runtime `95b6ddb`, deployment `6ae2d30cea16512cf7419564`, passed 307 seconds of health 200 from 05:03:55–05:09:02 UTC. All 229 backend/script/deployment files in the running container matched the package. Both services were RUNNING.

The first full document navigation rendered status and four tasks at **40,325 ms**, with 4 APIs rather than 8. Shell delivery alone consumed **14,411 ms for 33,006 gzip bytes** despite 708 ms server time. First-screen miss took 7,535 ms server / 14,005 ms browser, including 6,375 ms transfer for 30,747 bytes. No observed long tasks or runtime errors accompanied this. This is a failed acceptance run, not a latency improvement.

Subsequent warm full navigations took 12,289 / 17,198 / 8,881 / 10,611 / 10,686 / 5,706 ms. All rebuilt the snapshot. The source workspace is revised by ordinary background source/roster work; treating each global revision as a different cache entry prevented useful revalidation across navigations. The final revision makes these changes expire freshness while retaining the last-good bytes for bounded stale-while-revalidate. HTTP writes and changed SOP/identity/policy revisions still invalidate immediately, and stale node data is labeled with the existing last-successful-data text.

Separate same-page snapshot probes proved the delivery gap even when caching worked: **134 ms server / 5,047 ms browser** and **60 ms server / 7,470 ms browser**. The latter spent **7,348 ms receiving 30,748 gzip bytes**, with 3 ms queue and zero event-loop lag. These are isolated endpoint probes, not full-page acceptance. The cold builder remains measurable (1.4–1.6 s CPU, 3.2–8.5 s wall, including DB/upstream work) and is not claimed optimal. Final rollout acceptance is recorded below.


The persisted-card list on the first rollout rendered in **2,414 ms first / 17,410 ms reload**. Portfolio server time fell to **1,289 ms cold / 85 ms cached**, versus the prior same-document 4,989 ms server measurement. Its reload spent 6,558 ms transferring 48,216 gzip bytes, while the preceding shell spent 9,962 ms in transfer despite 341 ms server time. Five was a prior grouping result; the new rendered grouping contains three first-visible cards, while the complete data set remains available for counts and filtering. No virtualization was added because grouped display already limits mounted cards.


Final cache safeguards: indexed case visibility and case-owner/delegate fields are checked before cache lookup, independently of background workspace freshness. A newly hidden case cannot return its previous snapshot. Unindexed/legacy storage retains strict workspace-version invalidation. A queued build also rechecks the same viewer authority before publication, preventing it from being cached under a different permission state. The authority-change and hidden-case regressions pass.

Final pre-push rerun: **5,499 passed, 39 skipped, 1 xfailed**, with only the documented report-normalization baseline failure. The obsolete portfolio expectation (one legacy audit read) was corrected to assert the new persisted behavior and zero reads; it is not classified as a baseline failure. The latest affected cache/portfolio/home/timing selection passes **45 tests**. Frontend hook commands: 22/23 pass, with only the documented shell-mode failure. The full suite preceded the final visibility-key patch; the affected 45-test selection covers that patch.


### Final-runtime measurements before portfolio status correction

`f20aa1c`, deployment `6ae2dcf9ea16512cf741962b`, passed 306 seconds of health 200, 05:46:10–05:51:16 UTC; both services were RUNNING and all 229 runtime files matched.

| Full document run | SOP status + four task rows | First-screen cache | API browser / server | Transfer |
| --- | ---: | --- | ---: | ---: |
| Cold snapshot | 17,315 ms | miss | 15,558 / 9,903 ms | 5,600 ms |
| Warm 1 | 12,013 ms | stale | 8,241 / 311 ms | 7,880 ms |
| Warm 2 | 9,069 ms | hit | 7,689 / 109 ms | 7,536 ms |
| Warm 3 | 9,347 ms | stale | 3,251 / 204 ms | 2,989 ms |

First-screen JSON was 174 KB decoded / 30.7–30.8 KB gzip. Complete cold ASGI time was 9,907 ms, independently confirming a 5,651 ms gap to browser completion. Snapshot encoding took 6 ms; the cold builder used 1,903 ms CPU and 9,746 ms wall, including 2,295 ms upstream and 1,721 ms DB spans (overlap; do not sum). Warm revalidation now returns last-good bytes immediately despite changing source workspace revisions. All measured page content had four task rows, no alerts, runtime errors or observed long tasks. Warm 1/2 resource captures were taken before the secondary assignee request completed; cold and warm 3 complete captures contain four APIs. The first-screen portion has no four-request fan-out.

Portfolio rendered at 6,597 / 14,892 ms, with API server time 1,724 / 109 ms. The warm portfolio spent **9,237 ms transferring 48,214 gzip bytes**. Its preceding session spent 3,161 ms transferring 5,103 bytes. These exceed the acceptance limits independently of the cached handler.

Screenshot QA caught a correctness regression in the persisted-only variant: it labeled all 385 cases unstarted because Lark-derived statuses were never overlaid. That variant is rejected. The final correction restores the existing nonblocking, cached-source overlay and retains encoded response caching. The legacy audit-query expectation is restored, and **94 affected tests pass**. No frontend runtime code changed in this correction.

Read-only interaction: clicking an overview SOP task opens its matching visible detail dialog with source evidence and existing denied-write controls; no alerts or errors. An additional all-tasks navigation check changed URL and pressed state but did not expose the fifth confirmation-node SOP row in its default field-node scope. This scope behavior was not changed here and its baseline was not established.

Latest one-hour Zeabur metrics: CPU average 50.12%, maximum 93.62%; memory average 1,438 MB, maximum 1,774 MB. Two GB remains the minimum measured RAM estimate with limited headroom; two guaranteed vCPUs are a capacity experiment, not a verified SKU or price. No plan or limit changes were made.
