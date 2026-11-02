# LC logic checks

Scope: `t3/rd-LC`, created from integration commit `e596dd53` in the prescribed worktree. Orders 13–16 read in full, together with gates and F4/F5/F6 review notes. No integration push, deployment, production access, UI restyle, or storage.py edit.

Classification: E = exists in code (including this patch), D = presentation/design work using existing facts, N = needs a new endpoint/data contract. E does not certify source data as true.

## B1 — fixed (E)

`frontend/src/CaseDetail.tsx:140` previously built section IDs from React useId; the chip at line 687 was an anchor with a bare section hash. That hash replaced the application's hash route. The new node regression first failed with `#:r0:-section-overview` instead of `#view=confirmation&ctx=retained`.

Stable `confirmation-section-<key>` IDs and button handlers now scroll/focus within the current component root, leaving the route untouched (`CaseDetail.tsx:687`). Targets have tabindex -1 (`:363`). The Chrome regression exposed two targets nested in closed details; the handler now opens ancestor disclosures before scrolling. All seven sections pass keyboard navigation in Chrome, including reports/documents and history. Existing chip CSS is reused without changes.

Tests: `test-confirmation-section-navigation.mjs` (failing first, then pass); `test-confirmation-navigation-browser.mjs` (real Chrome, isolated synthetic component fixture, no backend/network); case-detail view and plan-panel suites pass.

## L2 — confirmed parsing bug fixed; live total attribution remains unproven (E)

Path: registry registers 實際合約金額 / 預期合約金額 from the v3 案件 table (`backend/reports/registry.py:24`); `normalize` retains raw fields; `contract` selects actual, with expected fallback (`compute.py:91`); `sales` adds each source record exactly once and groups it once by PM (`:207`–`:220`); SalesTab renders these totals with compactMoney (`frontend/src/reports/SalesTab.tsx:11`). No multiplication into 萬 or 億 occurs in the backend. `reportsView.ts:13` correctly divides yuan by 100,000,000 for 億.

Defect: `cell([120000,340000])` produces display text `120000,340000`; the old `number` removed commas and returned **120000340000**, not a scalar source amount. This is digit concatenation, not ordinary summation or a currency unit conversion. For example, `[256730,100000]` would become 256730100000, formatted as NT$ 2,567.3 億. Scalar fields and a source record's PM do not duplicate the row in the sales accumulator. Distinct source records are still distinct; the model does not promise deduplication by case name or code.

`backend/reports/compute.py:37` now unwraps single-valued arrays/objects recursively and rejects multi-valued numeric cells as unknown. It deliberately does not guess whether lookup amounts should be summed, deduplicated, or chosen. The existing missing-field quality gaps explain that sums include only available values (`:416`). If all amounts are unknown, nullable_sum returns None, not zero (`:270`).

The new failing-first test observed 120000340000.0 for the multi-value fixture. It now checks nested wrappers, scalar comma formatting, expected fallback, total 300000 and PM totals 250000/50000, and an unknown lookup row. All 27 compute tests and the focused reports suites pass.

Limitation: the staging baseline contains displayed totals and 50 rendered rows, not the complete raw lookup cells. This proves a capable defect and its correction, **not** that every dollar of the observed staging total came from this defect. Re-read reports on staging after integration and inspect authorized raw outlier cells before treating totals as verified. F5's muted “金額加總待核對” remains D; it should not be removed on this synthetic evidence alone. No arbitrary scaling or guessing of a corrected company total.

## L3 — correct as specified; no threshold/clock change (E)

`frontend/src/sourceHealthView.ts:157` uses backend data_state; it contains no clock or TTL calculation. Backend `source_health.py:77` marks stale if dataset status is stale or age >= TTL. The same dataset freshness is applied to all tables, explaining all nine labels (`:141`). `live_read/status.py:30` computes age using the server's now minus persisted dataset **as_of**, with timezone normalization (`:11`). It is not browser time or a comparison with the source's modified date. TTL defaults: LiveReadConfig 60 seconds; from_env 60 when enabled, legacy 300 when disabled (`live_read/config.py:10,40`). Runtime environment can override them.

`live_read/coordinator.py:219` deliberately sets as_of to **read start**, fetched_at to completion; its explicit contract test is `test_live_read_coordinator.py:84`. A successful GET of retained database data is not a successful new Lark read. Also, a read lasting at least its configured TTL can be stale immediately after completion; the timestamp conservatively describes the earliest sampled data. Refreshing a retained read is explicitly stale (`source_health.py:63`), not verified fresh. These are intentional semantics, not proof of a broken clock. Existing source-health tests cover ages 59/60/61 seconds (`test_source_health.py:331`), and fresh reads plus read-start/completion semantics pass in coordinator tests.

The GET path calls ensure without waiting (`backend/app.py:1257`; coordinator `:291,318,385`), so a successful HTTP read may return retained data while the server worker handles the refresh. In background-process mode ensure only reports the persisted dataset. With the default active-user worker cadence of 285–315 seconds (`scripts/run_worker.py:81`) and a 60-second source TTL, stale intervals are expected. A no-poll browser keeps that honest snapshot until the next authorized read.

No live service configuration or raw freshness response was changed/read here. Thus the precise deployed reason among expired snapshot / active refresh / long read is not attributable from the screenshot alone. Follow-up: capture as_of, fetched_at, server_time and TTL on an authorized staging read if the product wants a different freshness policy. Changing that policy is D/contract work; it must not relabel old data as newly verified.

## L4 — misleading automatic-update claim removed (E)

`reports/shared.tsx:8` used “舊資料 · 背景更新中” whenever meta.stale was true; stale does not prove an active refresh. The new failing-first render test caught that unsupported claim. It now reads “舊資料 · 資料待更新”, retaining the timestamp and failure-specific text.

`reports/useReport.ts:53`–`:71` loads on mount/query/retry/identity change; there is no interval, focus, visibility, online or TTL-expiry event that re-fetches an already-open report. The 30s timer aborts a request; the 250ms timers apply user input. The cache TTL is checked only when the effect runs, not an autonomous trigger. Existing report request tests verify ten minutes without passive retries and explicit retry = one request.

Server `backend/reports/snapshot.py:94` starts nonblocking revalidation on a stale **request**; it may also complete independently after the user has read retained data. This is backend work retained by order 16. Source/roster/attendance/outbox workers also remain: `scripts/run_worker.py:128` ticks every 28–32 seconds; its live dataset refresh path runs on an active-user cadence of 285–315 seconds (`:81`), skips sources/attendance while inactive or busy, and still uses TTL checks; source run_due checks configured source TTL before I/O (`source_sync.py:358`), and the live coordinator obeys dataset budgets/rate limits. These are bounded server jobs, not browser polling. Exact remote call cost depends on pages/tables and is recorded by the live-read metrics; no cost was measured here.

## L5 — row-grain correction and capability inventory

The F5 claim “each displayed management row is a confirmation version” is **not supported by current code**. `backend/manager_overview.py:165` keys authorized projects by stable project id; `:190`–`:204` emits one unfinished **project** row per id. `:119` attaches its confirmation row_keys separately. `:206` counts confirmation versions for a separate card. `frontend/src/ManagerOverview.tsx:34` defines the case columns, and the table renders snapshot.cases. Same names are insufficient evidence of duplicate identities or version grain. Source-import history may produce distinct project ids with the same name; this unit does not merge them.

The 436 rows / 297 names / 218 owner blanks are saved baseline observations, not invariants and not proof of grain. The **confirmation-list** endpoint does have one source record/version per row (`backend/confirmation_list.py:8,193`), but it is a different population. Correct F5's annotation before implementation. The 同名 N 列 label is D if explicitly name-only, never a version count. Missing PM labels stay unknown (`manager_overview.py:104`).

F6 challenge 2 also concerns **SettingsOverview**, a different screen. Its existing summary schema is `frontend/src/SettingsOverview.tsx:11` and backend construction is `backend/settings_overview.py:17`.

| Proposed column/element | Existing facts | E/D/N answer |
| --- | --- | --- |
| Management 來源健康 | Top-level source_health.state/route only (`manager_overview.py:127`); not a per-case source-health field | E summary/link; D summary presentation; N for independent per-case health |
| Management 審核進度 | pending_decision deliberately unknown (`:117`); no manager-level pending-decision predicate | N for per-case review progress; cannot derive from local unfinished or source health |
| Management 發布 | No publish field in CaseRow or its backend case payload | N; cannot infer from source readiness or execution state |
| Settings 來源健康 | sources[].readState, last_attempt_at, last_success_at, loaded_count, complete, last_error_code; datasets[].status; node_connection[].status (`settings_overview.py:26`–`:58`) | E facts; D column layout |
| Settings 審核進度 | No generic per-source approval progress in /api/settings/overview. Separate SOP proposals have status and confirmations (`SopApplicability.tsx:9`) | N for a unified row contract; D only for correctly scoped existing SOP facts |
| Settings 發布 | No generic per-source publish field in /api/settings/overview. SOP published/version facts are separate workspace facts; dispatch publishes have command state | N for a unified row contract; D for presentation of explicitly scoped existing facts |

F6 challenge 4: `DispatchPublishDialog.tsx:22` retains command id; `:26` locks editing/publishing once an id exists. Step 4 (`:111`, long JSX line) **does offer the GET action**, but the actual label is **查詢命令進度**, not 查詢原命令結果. A manager can 重新對帳 when next_action is reconcile. The dialog also offers **重試同一命令** for unknown/no response; that POST reuses the same command UUID (`:64`–`:71`). `backend/dispatch_publish/service.py:243` returns an existing command when the preview matches, avoiding a second create. Failed/rejected terminal states alone unlock a new preview; uncertain outcomes do not.

Thus E = same-command lookup, reconcile and prevention of a **new** publish command while uncertain. D = proposed wording, one primary query, visible disabled 重新發布. The design's literal “only query, no enabled retry control” is **not current UI**. It can be implemented with existing endpoints (no N), but do not describe an enabled idempotent retry as a fresh republish. Existing dispatch tests cover UUID retention, 409/503, reconcile and recovery. No dispatch logic change needed in this unit.

## L6 — correct arithmetic; naming/populations differ (E)

`frontend/src/projectsListModel.ts:36` defines SOP membership from managed policy or imported tasks. `:51`–`:54` counts all non-completed SOP cases for the KPI, regardless of which exclusive section displays them. `:39`–`:46` assigns each row to pinned, done, notStarted, mine, sop, other in that order. Therefore owned/pinned/unstarted SOP cases can contribute to the KPI while appearing outside the SOP section. `ProjectsList.tsx:119` binds the KPI and `:136` renders exclusive section counts.

An explicit fixture now asserts SOP KPI 3, SOP section 1, with the three rows grouped mine/sop/pinned. No arithmetic fix. More precise KPI copy or a tooltip is D; the current KPI includes non-completed unstarted SOP cases too, so “進行中” should not be read as the section's exact definition. No N.

## Verification and follow-ups

Failing-first defects: B1 hash mutation, L2 lookup digit concatenation, L4 unsupported refresh claim. Each reproduced before its fix. The browser additionally failed on collapsed targets before that fix.

Passed: `npm run test:logic-checks`; `node test-case-detail-view.mjs`; `npm run test:plan-panel`; `npm run test:reports`; `npm run test:source-health-view`; `node test-projects-list-model.mjs`; `npm run test:dispatch-publish`; `npx tsc -b`; `npm run build`. Build retains the existing large assistant chunk warning; report SSR tests emit existing useLayoutEffect warnings.

Focused backend command: `/Users/vc/Local/YXMEEGLE/.venv/bin/python -m pytest backend/test_reports_compute.py backend/test_reports_routes.py backend/test_reports_home.py backend/test_source_health.py backend/test_live_read_coordinator.py -q` — 213 passed.

Full backend (one run): `/Users/vc/Local/YXMEEGLE/.venv/bin/python -m pytest backend -q` — **5955 passed, 272 skipped, 1 xfailed, 4 warnings in 579.65s**. Warnings are existing unknown perf markers. Log `/tmp/rd-LC-backend-full.log`.

`backend/storage.py` is unchanged from integration and remains 28,599 characters (under 32,000). `git diff --check` passed.

Follow-ups for coordinator: preserve F5's unverified-money presentation until live raw outliers are checked; correct overview row-grain annotation; choose product copy for SOP KPI; implement F6 presentation with scoped facts only. No source sync scheduling was removed.
