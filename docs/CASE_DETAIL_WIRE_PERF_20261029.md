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

Validation and release measurements are appended after deployment. Raw local evidence is ignored under `.runtime/case-detail-perf/round6-*`.

## Local validation

- 34 focused backend tests passed (snapshots, portfolio, timing, transport and server headers); the subsequent final cache-fence/logger guards passed 12 tests. Covers unchanged warm gzip bytes without recompression, gzip-q=0 identity negotiation, empty 304s, changed viewers, first-screen/page compressed-size budgets, complete 65-card pagination pinned across a source revision, cursor expiry and invalidation.
- After `npm ci`, all 22 frontend pre-push commands ran independently: 21 passed; only the documented shell-mode `逾期 1` assertion fails. The overview and tooling checks pass after updating their expected paged URL. The changed detail/list rendered tests and list-model tests pass, including first-page rendering while the remaining page is unresolved and progress starting only after SOP/task render. TypeScript/build passed.
- Full pre-push hook is being run before pushing; its final result is recorded below. No new failure is accepted as baseline.
