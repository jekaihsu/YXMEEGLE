# PR #81 independent review fix report

All changes stay in the reports worktree and the permitted paths. No commit, push, stash, source-data edits or raw-data copy into the repository occurred. The pre-existing `.venv` and `frontend/node_modules` symlinks remain untracked. PR https://github.com/jekaihsu/YXMEEGLE/pull/81 is linked to the thread.

## Findings and regression evidence

The initial new regression run produced 10 failures and 28 passes. Failures reproduced the old multi-day denominator, zero-contract fallback, unused-asset exclusion, blank-person identity and all six unknown-query paths. Additional targeted compute tests were also executed against the original HEAD module loaded in memory and failed. The single-flight/LRU and gap-reuse tests likewise failed against HEAD's snapshot implementation. Final validation passes 44 backend tests.

1. Multi-day plans expand inclusive Taipei dates into week indexes. Case totals deduplicate case/date across groups; each group retains its own date set. Leave and C000000 are excluded. Inverted spans count one day and emit a computed gap. Tests `test_multiday_case_dates_group_normalization_unplanned_and_diff` and `test_days_diff_sort_matches_display_and_cross_group_deduplication` cover epoch-ms dates, cross-week spans, multiple cases, duplicate groups, leave and inverted spans. The real dump has nine inverted rows, now disclosed.
2. Both plan and actual groups use `normalize_group`, including filters. The trailing 組 is removed and original work-row group labels remain available. Achievement uses the planned/actual case-date intersection; unplanned days are separate at KPI, case and group levels. Unmatched normalized groups emit gaps. Tests `test_multiday_case_dates_group_normalization_unplanned_and_diff` and `test_unplanned_actual_never_in_achievement_numerator` cover matching, suffix filters and excluded actuals.
3. Days `diff` is actual minus planned days and sorts on the same value shown by the frontend. Points keep their points difference. `test_days_diff_sort_matches_display_and_cross_group_deduplication` asserts the exact order and values.
4. Sales grouped totals use nullable sums. A zero actual contract with positive expected contract uses expected. Gaps disclose fallback counts and outlier case codes. PM progress is weighted over positive contracts with known progress. Negative remaining points stay per case and are excluded from the KPI. `test_sales_null_groups_zero_fallback_weighting_outliers_and_remaining` covers all of these with synthetic cases, including a missing contract bucket. The real dump has 90 zero-contract fallbacks and 33 outliers. Contract total changes from 162559588081.3751 to 162605093438.3251 source units. No source values are silently rescaled.
5. Every endpoint rejects unknown query keys with 422 detail. SnapshotStore also normalizes allowed params before key creation. Results use a 512-entry LRU and a shared Future for concurrent identical misses. Static gaps are precomputed once for endpoint/department and reused, activating the formerly dead precompute path. Tests `test_unknown_query_keys_rejected`, `test_identical_result_misses_single_flight_and_lru`, `test_snapshot_gaps_do_not_rescan_requests` and the existing stale-refresh tests cover this behavior.
6. Assets disclose the two cost-link coverage fractions for the selected window and the count of excluded odometer pairs. A partial km total is labelled 部分里程. Null idle-days assets survive idle filtering and show 期間無使用紀錄. The unused KPI uses that conservative label at all coverage levels. `test_asset_coverage_invalid_mileage_and_never_used_idle_filter` covers these cases. For 2026-01-01 through 2026-10-15, coverage is 168/761 vehicle cost rows and 151/761 instrument cost rows. Four mileage pairs are excluded; valid total remains 140638 km. The KPI no longer implies complete mileage coverage.
7. Person rankings retain one entry per person/group. Display is person · group; identity and click filters include both fields. Blank people show 未填 and use `__blank__`. Select options are deduplicated and BarList has distinct keys. Tests `test_same_person_in_two_groups_has_distinct_ranking_identity` and `test_person_group_identity_blank_filter_stable_options_and_status_order` cover this model.
8. `test_role_gate_all_reports_and_refresh` covers staff denial on every GET and refresh, and PM/manager success. GET returns 200; authorized refresh may return 200 or 202 per contract. Synthetic fixture extensions are in the compute tests and preserve the sanitized fixture's real cell/link shapes. The new tests assert returned behavior rather than intermediate collections.
9. TrendChart uses a named group, an SVG text summary and native selectable-week buttons outside the SVG. Nonselectable bars use role=group. Errors use role=alert. `frontend/test-reports-view.mjs` renders and asserts these semantics, blank metadata timestamps, failed-refresh copy and deduplicated options. The browser confirmed 12 native week buttons, zero focusable descendants inside role=img, and Enter changed the selected week from 2026-10-05 to 2026-07-20. The screenshot is retained locally in T3 browser artifacts.

## Batched nits

Search offset resets in the same React update as the debounced query. `frontend/test-reports-requests.mjs` observes `:50` during typing and `new:0` after debounce. Every table calls `nextSortOrder`; tests cover first text ascending, first number descending and repeat toggles. Review status order is passed, returned, pending, unset. `test_filter_options_survive_empty_filtered_results` and the review identity test check stable options despite filters. UI selectors consume those options. MetaNotice handles blank timestamps and shows 更新失敗，顯示舊資料 via additive refresh_error. The existing refresh-failure test asserts that flag. The prior polish report now states screenshots are local and uncommitted.

## Real dump before and after

Before values were read from the unchanged original code before edits. After values came through FastAPI TestClient over the same local dump with scope=week.

| Week | Department | Old planned days | New planned days | Actual days | New matched days | New unplanned days | Old achievement | New achievement |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 2026-09-28 | field | 24 | 29 | 36 | 14 | 22 | 150% | 48.275862% |
| 2026-09-28 | office | 30 | 43 | 49 | 26 | 23 | 163.333333% | 60.465116% |
| 2026-10-05 | field | 8 | 10 | 30 | 7 | 23 | 375% | 70% |
| 2026-10-05 | office | 14 | 24 | 52 | 20 | 32 | 371.428571% | 83.333333% |

For 9/28, field groups were 地形C, 地形E, 外業, 奇穎組, 水深A, 水深A組, 水深B, 水深B組, 水深C, 水深C組, 點工B. They now are 地形C, 地形E, 外業, 奇穎, 水深A, 水深B, 水深C, 點工B. For 10/5, field groups now are 地形C, 地形E, 奇穎, 水深A, 水深C, 點工B; 水深A組 and 水深C組 were previously separate. Both office weeks collapse 控制組 and 控制 into 控制, alongside 圖報A and 圖報B.

Previously `?data=x` raised duplicate-argument TypeError on five report endpoints and was accepted by sources. All six now return 422 with a string detail against the real-data app.

## Validation

The following commands pass in the specified worktree.

```sh
/Users/vincent/Local/YXMEEGLE/.venv/bin/python -m pytest backend/test_reports_*.py -q
# 44 passed, one existing Starlette TestClient deprecation warning.
```

From frontend, `npx tsc -b`, `npm run test:reports`, `npm run build` and `npm run test:overview` all pass. `git diff --check` passes. Five real-dump benchmark runs yield zero errors across 45,000 timed requests. Median miss p95 in ms is review 0.733, rows 0.511, sales 2.867, assets 2.079 and progress 0.490. All pass the 100 ms aggregate and 80 ms row limits. Measurement scope, ranges, profile evidence and the benchmark query adapter are in `REPORTS_BACKEND_20261015.md`.

## Remaining limits

All requested findings and nits are addressed. The benchmark file still sends obsolete week keys to sales/assets. It is outside the allowed edit paths, so measurement uses the documented in-memory adapter. The local dump lacks contract details and financial formula values. TAF, self-calibration and monthly inspection sources remain absent. No live upstream refresh was requested or performed. UI keyboard verification uses synthetic data; real data was verified through the endpoints. The coordinating agent owns the next independent fix-diff review. This report does not claim that review has run.

Model the Domain shaped the case/date and per-group set model. Test Behavior, Not Implementation shaped the returned KPI, HTTP and rendered-markup assertions. Type System Discipline preserved nullable financial totals in frontend types. Implementation and verification ran in-thread as the assigned implementation sub-agent; no child delegation ran.

## Round 2

Implementation is confined to `/Users/vincent/Local/YXMEEGLE-wt-reports-pr`. No commit, push, stash, live refresh, or other checkout edits were performed. The real dump remains under `/tmp/lark-docs/data`; no source records were copied into fixtures or docs.

### Findings and changes

1. Sales had 18 records with empty 案件編號, 案件名稱, 業主, 狀態, and 🔴重複編號. Only 實際合約金額, 累計內業營業額點數, and 累計外業營業額點數 were populated. The dump therefore does not support treating them as duplicate cases or filtering them by status. All 735 cases remain. Previously the 18 empty codes appeared first in ascending order and rendered blank. They now sort last in both directions, with record id as the stable tie breaker. The table displays 「（未填編號）」 plus the final six id characters and muted 「未填」 for name and client. All 18 retain unique ids and working HTTPS source-link targets. The new gap reads 「18 件案件未填編號」.
2. Progress bars previously displayed all actual days beside a percentage whose numerator was matched days. Bars now show 「對應 matched / 預排 planned 天」, with a separate visible muted unplanned-days line. The achievement KPI has the same explanation, and matched/unplanned KPI tiles are present. Case columns display and sort planned, matched, and unplanned days. Group payloads add planned_days and matched_days without removing fields. On 2026-10-05 field data, planned 10, actual 30, matched 7, unplanned 23, and achievement 0.7 remain unchanged. Rendered regression data verifies 66.7% shows 4/6 rather than the misleading 5/6.
3. Normalization previously changed 未分組 to 未分, while blank plans used 未分組. It now preserves one internal 未分組 value through repeated normalization, including route and compute boundaries. The missing-group gaps changed from absent to field 9/813 and office 3/1233. Field missing-group rows comprise five dated work rows and four undated rows; office has three undated rows. Real endpoint `group=未分組` returns actual case-days 2 on 2026-07-20, 1 on 2026-08-03, and 1 on 2026-08-10. On 2026-10-05 both departments correctly return zero missing-group rows. The real blank-group plan is on 2026-09-07 but has no usable case code, so it remains excluded by the existing unspecified-case rule. A synthetic blank-group plan with a usable case code proves that filtering includes both plan and actual days.
4. Asset owner/category/status options encode blanks as __blank__, with 「未填」 as the Select label. Progress missing-group options use the same transport sentinel; query normalization maps it to 未分組. Empty string retains its 全部 meaning. Assets owner is now a Select using its options payload. Real `owner=__blank__` changed from no matches to 2 vehicles, both with empty owner. HTTP tests cover all three asset Selects and both progress missing-group spellings. Vehicle status and category retain their existing enabled/disabled and 車輛 fallbacks.
5. Trend week buttons omit error-rate text when the field is undefined and expose aria-current for the chosen week. Each tab declares its sortable-column defaults, including descending date and last_used. Clear filters and item ranking apply search and query together. Request tests observe exactly one request with the new query and no delayed stale-query request. Bar detail text is now visible and muted, rather than only appearing in SVG accessibility text.

### Verification

The initial added backend regression tests failed with missing sales id and 未分組 becoming 未分. The initial chart assertion failed because a total-only week button announced 「失誤率 無法計算」. These assertions pass after the fixes. Added rendered-table assertions cover the sales fallback, muted blanks, source link, matched-day text, separate unplanned text, blank-option label, selected week, and tab sort defaults. Added request assertions cover clear and ranking updates. Added compute and HTTP assertions cover blank options, missing-group normalization, both group query spellings, and matched/unplanned sort keys.

Final commands run in the specified worktree and frontend directory.

- `.venv/bin/python -m pytest backend/test_reports_*.py -q` passes 47 tests. The existing Starlette/httpx deprecation warning remains.
- `npx tsc -b`, `npm run test:reports`, `npm run build`, and `npm run test:overview` pass.
- `git diff --check` passes.
- `.venv/bin/python -m backend.benchmark_reports --data /tmp/lark-docs/data --requests 30 --rounds 1 2>/dev/null` completes with zero errors. This is one acceptance run, not a speedup comparison. Each endpoint has 30 cache-hit requests and 300 forced-cache-miss requests. The harness times synchronous TestClient responses, validates status and snapshot presence, and independently checks field review totals against the dump. Miss p95 in ms is review 0.743, review/rows 0.500, sales 2.903, assets 2.074, progress 0.504. Each aggregate is below 100 ms and rows below 80 ms. Host load before the run was 1.56/1.59/2.00 on 10 CPUs. The measurement includes in-process request handling and excludes live Lark latency. No comparative performance claim is made.

Model the Domain shaped the explicit search/query state and per-tab sort maps. Implementation and verification ran in-thread as the assigned implementation sub-agent. No independent review or browser verification was performed; the coordinator owns both. The data limitations above remain intentional. No requested implementation finding is left open.
