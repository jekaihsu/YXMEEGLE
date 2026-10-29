# Case-detail wire delivery follow-up — 2026-10-29

Continuation from [snapshot perf](CASE_DETAIL_SNAPSHOT_PERF_20261029.md) and [root-cause investigation](CASE_DETAIL_PERF_ROOT_CAUSE_20261029.md). Worktree `case-detail-perf`, starting `dd97a71`. Only the existing staging app/DB are in scope. No spending, resource-plan changes, production deployment, or service suspension.

## Baseline: payload and delivery

Authenticated shared Chromium, 1280×800, existing runtime `04286c2`. Sequential GET probes, browser default content negotiation; every successful response below used **gzip**, with `Content-Length` matching ResourceTiming encodedBodySize. ResourceTiming transferSize was encodedBodySize + 300 bytes. Numbers are bytes and milliseconds, not estimates.

| Endpoint | Decoded bytes | Gzip bytes | Request total | Wait | Download |
| --- | ---: | ---: | ---: | ---: | ---: |
| session | 31,724 | 5,103 | 366 | 365 | <1 |
| workspace shell | 272,793 | 33,002 | 891 | 887 | 4 |
| first-screen | 174,116 | 30,739 | 200 | 183 | 16 |
| node-assignments | 30,633 | 5,334 | 921 | 918 | 3 |
| sop-tasks | 18,687 | 4,255 | 611 | 608 | 2 |
| start-sop preview | 2,100 | 898 | 489 | 487 | 1 |
| progress | 6,994 | 1,830 | 1,957 | 1,954 | 3 |
| sop-assignees | 9,008 | 2,352 | 214 | 211 | 2 |
| complete portfolio | 859,476 | 48,391 | 134 | 104 | 28 |

This round does **not** reproduce the earlier 4–9 second body-transfer delay. An unchanged-code full navigation rendered detail at 1,183 ms from the first API start (session 489 ms, shell 495 ms, first-screen 181 ms), four task rows and the expected SOP/next-action/stuck-node text. This establishes substantial time variance before the new code; any before/after speedup claim must account for it. The previous report's slow samples remain valid observations, not a constant payload-size effect.

The first-screen has no base64 and no MB-scale JSON. Its project slice contains 37,462 characters of reusable SOP templates, 9,326 of administrative revisions and approximately 35,000 of project data; assignments are about 29,500 characters, tasks 16,000 and progress 6,400. Session and shell both embed 68 roster entries (about 28–30K characters each). The shell also embeds 421 compact project headers (~201K characters). Portfolio contains 385 cards. These roster/header duplication opportunities remain distinct from the small measured compressed bodies.

The browser exposes the authenticated response headers and wire/decoded byte counts directly. Repository tooling has no exported authenticated curl cookie jar; no session was forged or secret extracted. Anonymous curl cannot substitute for these authorized payload measurements.

## Implementation

- Snapshot builds serialize JSON once and precompress gzip at level 1 in the snapshot worker. Immutable raw/compressed bytes and a content digest share the existing bounded, single-flight cache. Responses have an explicit Content-Length and bypass repeated gzip middleware work. There is no new encoder dependency: prior measured JSON encoding was only 3.5 ms, so replacing it with orjson would not explain the historical missing seconds.
- Conditional GET validates the existing fresh viewer/admission/visibility keys before ETag matching. Browser cache policy is `private, max-age=0, must-revalidate`; server-side 15-second freshness / 120-second stale-while-revalidate remains. Positive browser freshness or browser SWR could serve revoked data without reauthorization, so it is deliberately not enabled. Session epochs clear frontend ETags; mutations retain the existing cache invalidation fences.
- SOP status, next action, stuck node and task readers still seed together from the first-screen response. Progress/report construction now starts after that screen mounts through its existing reader. Administrative history and connection diagnostics are removed from the first-screen project slice; normal detail readers retain them. Existing skeletons reserve the deferred progress area.
- The portfolio first response is a 30-card page. Remaining pages load after first render, pinned to the same authority-scoped snapshot digest. Stale/expired/invalidated cursors require a fresh read rather than mixing captures. Counts and search are explicitly partial until completion; complete existing client filters/grouping remain. Both complete legacy reads and paged responses retain cached Lark-derived status overlays.
- Delivery logs report compressed byte count, ASGI body-message count, header-to-first-body gap, full completion time and time blocked in ASGI send. This can distinguish app body production from downstream delivery during an actual recurrence.

Validation and release measurements follow below. Raw local evidence is ignored under `.runtime/case-detail-perf/round6-*`.

## Local validation

- 34 focused backend tests passed (snapshots, portfolio, timing, transport and server headers); the subsequent final cache-fence/logger guards passed 12 tests. Covers unchanged warm gzip bytes without recompression, gzip-q=0 identity negotiation, empty 304s, changed viewers, first-screen/page compressed-size budgets, complete 65-card pagination pinned across a source revision, cursor expiry and invalidation.
- After `npm ci`, all 22 frontend pre-push commands ran independently: 21 passed; only the documented shell-mode `逾期 1` assertion fails. The overview and tooling checks pass after updating their expected paged URL. The changed detail/list rendered tests and list-model tests pass, including first-page rendering while the remaining page is unresolved and progress starting only after SOP/task render. TypeScript/build passed.
- Full pre-push hook is being run before pushing; its final result is recorded below. No new failure is accepted as baseline.

## Verified staging release

Runtime **`62a4174cbb592052a4693330bb8798a69aba6682`**, deployment **`6ae2fdb3b1b373d6123a7cef`**. Health-200 samples reporting that exact SHA span **307 consecutive seconds**, 08:05:33–08:10:39 UTC. Both requested app and DB services are RUNNING. All **229 deployed backend/script/deployment files** match the checked **532-source-file** package; offline smoke passes. There was a transient browser 502 during replacement before the good window. No resource settings or plans changed and no spending or production action occurred.

Full pre-push hook: **5,501 passed, 39 skipped, 1 xfailed**, with the documented report-normalization failure and one introduced home-panel Cache-Control assertion failure. The latter was fixed by limiting the HTTP caching exception to snapshot responses; **53 affected backend tests pass** on the final runtime source. The final retention/compatibility guards also passed their focused selection. The full eight-minute suite preceded those final small fixes; it is not reported as a clean rerun of the final tree. After actual hook execution and the separate complete frontend command run, push used the documented baseline bypass.

Code commits: `bf4ede8` wire snapshots, conditional clients, deferred progress and paged list; `62a4174` restrict the caching exception to snapshot responses. Later report-only commits do not change deployed source.

## Browser results and acceptance

**Overall SLA: NOT MET.** Warm first-screen and warm first-list-card targets pass in the measured runs; cold case/list generation and intermittent downstream delivery still exceed limits. The fast baseline before this implementation prevents attributing all observed improvement to the code.

Real authenticated Chromium, 1280×800, HTTP/3. Full document navigations go through health and back. Warm runs use cached static assets and an existing application snapshot. Warm 2 was preceded by an explicitly recorded read-only snapshot probe because its previous entry had expired; that probe took 2,799 ms server time and is not hidden inside a cold result.

| Milestone | Prior reported 04286c2 slow runs | This runtime | Target |
| --- | ---: | ---: | ---: |
| Case first post-deploy snapshot | 8,566 ms | **5,237 ms rendered-case mark** | <4,000 ms |
| Warm SOP status + four task rows | 12,494 / 12,862 ms | **1,874 / 960 / 975 ms** | <2,000 ms |
| First portfolio capture, same-document transition | — | **1,897 ms first cards / 8,137 ms complete counts** | <3,000 ms first screen |
| Full-document list reload | 16,917 ms | **760 ms first cards / 3,531 ms complete counts** | <3,000 ms first screen |
| Full-document list after snapshot expiry | — | **8,584 ms first cards / 10,821 ms complete counts** | <3,000 ms first screen |

The last list run is a genuine encoded-snapshot cache miss after its 120-second retention elapsed, without manual invalidation or source writes. Its first page starts at 3,712 ms and takes **4,860 ms browser / 4,748 ms server**, with only **3 ms download**. The snapshot uses **990 ms CPU**, 4,155 ms snapshot wall, 1,002 ms DB spans and 509 ms maximum event-loop lag. It does not pass the list cold target; pagination currently cuts first-response bytes while still building the complete portfolio capture. More selective page construction remains an application opportunity.

The cold observer was installed late after a tool parameter rejection. Its first visible-element observation is 5,955 ms; the existing first-render performance mark plus the first session's start time yields the 5,237 ms case-render milestone. The first-screen body finishes at 5,222 ms, and screenshot/DOM verify four task rows and correct SOP, stuck-node and next-action content. Cold acceptance fails even without relying on the render proxy: its API alone takes 4,268 ms. Warm visibility observers were installed before initial APIs and measure SOP and task rows together directly. All completed case/list runs have no application alerts, runtime errors or observed long tasks. Two transient connection/navigation errors occurred between cold and warm 1; the final warm 1 navigation committed normally with its own clean resource/visibility capture. Alternative automation inventory had no browser; the recovered shared browser supplied the remaining evidence.

| Active API/run | Browser total | Header Server-Timing | Download | Encoded / decoded bytes |
| --- | ---: | ---: | ---: | ---: |
| first-screen cold | 4,268 ms | 4,181 ms | **10 ms** | **26,301 / 154,163** |
| first-screen warm 1 | 203 ms | 118 ms | 3 ms | 26,301 / 154,163 cached; **300 transfer bytes** |
| first-screen warm 2 | 108 ms | 55 ms | 10 ms | 26,314 / 154,163 |
| first-screen warm 3 | 90 ms | 45 ms | 1 ms | cached; **300 transfer bytes** |
| first list page, first capture | 1,883 ms | 1,803 ms | 2 ms | **5,075 / 69,711** |
| first list page, reload | 147 ms | see raw capture | <1 ms | cached; **300 transfer bytes** |
| list page 10, first capture | **4,083 ms** | **59 ms** | **3,953 ms** | **5,443 / 63,371** |

Browser-managed 304 revalidation exposes a merged 200 response and the cached representation's encoded/decoded sizes; transferSize=300 identifies the empty network body. Server logs independently confirm actual 304 and zero body bytes. Explicit `cache:no-store` + If-None-Match probes also return **304, zero bytes** for first-screen and page 1. Full first-screen compressed size is comfortably below 100 KB. At gzip level 1 the complete legacy portfolio is 56,283 bytes; new UI pages are about 3–6 KB each. Pagination trades some compression efficiency and extra round trips for a small first response.

### Definitive body-production versus downstream evidence

At **08:13:24 UTC**, the app's matching 5,443-byte page response logs:

```
response_delivery path=/api/projects status=200 bytes=5443 chunks=2
headers_ms=59.4 first_body_ms=1.1 complete_ms=61.6 send_ms=0.1
```

The browser sees 129.7 ms wait and 3,953.2 ms download for that request. Thus the app completes the entire body in **61.6 ms**, while Chromium completes at **4,082.9 ms**. This is a reproduced **>4-second floor outside application body generation on a 5.4 KB precompressed response**. The ASGI messages are the complete payload plus final empty body, not a slow stream. It rules out per-request JSON encoding, lazy projection, gzip CPU cost and an application chunk loop as the source of these missing seconds. It does not identify whether the remaining delay is kernel/host, proxy, transport path or browser network stack. No particular Zeabur component is proven responsible.

The cold first-screen similarly sends 26,301 bytes in two body messages, completes at 4,184.3 ms versus 4,181.1 ms headers, and spends 0.1 ms in ASGI send. Its **2,872 ms upstream span**, **1,214 ms snapshot CPU**, **1,243 ms storage wall**, and 5.1 ms final encode/compress explain its construction delay; spans overlap and must not be summed. Gzip compression itself is 1.6 ms. Payload delivery is no longer the cold bottleneck in this run.

Independent CPU-only process, 45 one-second-spaced samples: **10.9 ms median CPU / 28.6 ms median wall**, maximum **60.1 ms wall for 10.9 ms CPU**. At that maximum, host CPU PSI some avg10 is 57.12%, app full avg10 21.11%. The pre-release cgroup has unlimited cpu.max and zero throttling. This demonstrates descheduling independent of the web interpreter, but does not attribute every DB or handler wait to hosting.

### Complete post-release endpoint size probe

Sequential authenticated reads with browser HTTP cache bypassed; every 200 below uses gzip. TransferSize is encoded+300 bytes. Explicit conditional validations are additional zero-byte 304s. These probes are distinct from navigation timings.

| Endpoint | Decoded bytes | Encoded bytes | Total | Wait | Download |
| --- | ---: | ---: | ---: | ---: | ---: |
| session | 31,724 | 5,103 | 354 ms | 351 ms | 3 ms |
| shell | 272,830 | 32,995 | 969 ms | 953 ms | 15 ms |
| first-screen | 154,163 | 26,302 | 289 ms | 286 ms | 1 ms |
| legacy overview | 115,557 | 19,484 | 3,062 ms | 3,054 ms | 6 ms |
| node assignments | 30,640 | 5,342 | 2,658 ms | 2,654 ms | 3 ms |
| SOP tasks | 18,687 | 4,255 | 1,643 ms | 1,640 ms | 2 ms |
| start SOP preview | 2,100 | 898 | 1,676 ms | 1,674 ms | 1 ms |
| progress | 6,994 | 1,831 | 3,413 ms | 3,411 ms | 1 ms |
| SOP assignees | 9,008 | 2,352 | 524 ms | 522 ms | 1 ms |
| legacy complete portfolio | 859,476 | 56,283 | 3,168 ms | 3,142 ms | 25 ms |
| portfolio page 1 | 69,711 | 5,074 | 220 ms | 216 ms | 3 ms |

### Open items and stopping condition

- The no-API-over-three-seconds requirement cannot pass reliably while a 5.4 KB precompressed body sent by the app in 61.6 ms takes >4 seconds to arrive. This independent downstream floor is the evidence-based stopping condition for further speculative application transfer changes. Provider/path diagnosis requires no paid plan change; none was attempted.
- Cold case construction still misses four seconds: upstream reads plus roughly 1.2 seconds of local snapshot CPU remain measurable work. Smaller domain captures and overlapping/precomputed upstream reads are possible next application work; this report does **not** certify the builder optimal or claim all residual time external.
- Deferred progress remains a separate performance opportunity: full navigation runs take 1.53 / 4.83 / 1.96 / 3.57 seconds. Its 4.74-second ASGI slow log includes 404 ms handler CPU and 2,616 ms DB spans across 24 queries. A later 3.31-second read uses 507 ms CPU / 1,633 ms DB. Further capture/query/cache work may help; moving it after render meets the first-screen dependency goal but does not satisfy the per-API SLA.
- Full list statistics/search completeness takes 8.14 seconds on the first transition with the delayed page, and 3.53 seconds on reload; first cards render promptly. Serial background pagination adds round trips. The additional full-document run after expiry takes 8.58 seconds for first cards and 10.82 seconds for counts; the whole-portfolio cold builder still runs before page 1. Complete counts are 385 cases / 2 active / 3 SOP-in-progress; no stale-all-unstarted overlay regression recurs.
- No source write workflow was exercised. Screenshots and DOM checks verify read-only status/tasks, list counts and existing permission-disabled controls. Longer cache/cursor soak and every write interaction remain unverified.

Evidence: `.runtime/case-detail-perf/round6-{before,before-case,cold,warm1,warm2,warm3,list-first-transition,list-reload,list-expired-full-navigation,after-sizes}.json`, `round6-{health,runtime-package,runtime-list,runtime-final,scheduling,hook,post-hook-fix,frontend-final}.log`, and `round6-{cold-case,warm-case,tasks,list}.png`. Raw evidence is ignored local review material; this report is the durable PR record.
