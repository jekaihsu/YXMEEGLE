# I5 — Reports, management overview and sources

Status: implemented and verified; ready for coordinator / independent review. No deployment, integration-branch push, PR, or company-data writes.

Branch: `t3/rd-I5`  
Base: `4da92c78` (`t3/redesign-integration` when the prescribed worktree was created)  
Worktree: `/Users/vc/.t3/worktrees/YXMEEGLE/rd-I5`  
Final head: reported in the worker handoff / branch history (this report is committed with the evidence).

## Delivered

- Reports use shared DataState for loading, denied, stale and partial states. The stale banner identifies the retained timestamp, age at render, whether the report reread failed or the source returned an old snapshot, and links to standalone sources. Explicit reread remains available. No timer, focus, visibility or online fetch was added.
- Home distinguishes V3 report-table rows, V4 projects and quotes. Only the report-table count comes from this page's response. Other populations stay unknown with links to their owning pages; the historical 940 / 398 / 394 comparison is explicitly described as baseline evidence, not current totals. Every report exposes its source/snapshot time; week/date filters retain their existing behavior.
- Unverified contract and PM aggregates read `金額加總待核對`. PM bars use known row counts instead of unexplained percentages or unverified money. Missing finance fields show — with a partial-state explanation; a genuine scalar zero is preserved. The LC backend digit-concatenation fix is unchanged.
- Sales/progress combine case identity into ID/name/subline cells, retain one work-status badge, and put secondary facts in the existing detail surface. Progress only adds the no-work exception when planned days are positive. Group achievement is disclosed. Other reports retain their existing sorting/filter/export behavior and get the same calm surfaces, labels and mobile record treatment.
- Mobile tables use labelled records from the same table DOM; desktop wide tables have a keyboard-focusable region and explicit horizontal-scroll instruction. Tabs scroll with a fade; ResizeObserver keeps the selected tab visible after viewport changes, with no data operation.
- Management H1 is `管理總覽`. Each row is a project ID, never a confirmation version. Loaded names compute `同名 N 列`; blanks show 未填. Initially 25 project rows render, with 25-row local reveal and inline details. Unknown snapshot cards remain — / 尚未載入; known cards retain their drilldown. No fabricated health/review/publish columns.
- Source health consolidates an identical all-stale condition once, hides repeated healthy badges, keeps absolute Taipei success times, and retains differing error/state information. Unknown source diagnostics use Partial rather than a false empty state. Expired roster and shadow-endpoint 403 render typed Stale and Denied states respectively, preserving existing recovery permissions.
- Legacy Sources was extracted from App's internal function into `Sources.tsx`. Its GET uses page owner / requestPageData with initial-open or explicit-refresh intent. An empty definition array without a successful source timestamp stays `— 張資料表 · 尚未讀取`; confirmed empty snapshots may show 0. Source writes/role gates and the existing sync action remain intact. Session epochs remount the legacy page; denied reads clear retained data.
- Standalone sources is linked from 管理設定, Reports' source tab, management's source summary and stale report/source banners. No top-level nav destination was added.

## Data-state defect found and fixed

Most report tabs previously consumed `result.data` only. On an explicit reread failure the shared hook returned the last report solely as `previous`, so the tabs discarded their retained presentation. The hook now exposes that same retained response with `meta.stale` / `meta.refresh_error`, preserving the original fetched_at. Its denied branch still withholds both data and previous. A literal test verifies 940 retained rows after 500, and removal after 403. The existing test that expected `data === undefined` after an offline refresh was updated for this agreed stale presentation.

## Scope / integration notes

Primary edits: `frontend/src/reports/{ReportsPage,HomeTab,ProgressTab,ProgressDetail,ReviewTab,SalesTab,ContactsTab,AssetsTab,SourcesTab,shared,useReport}.tsx/ts`, `reports.css`; `ManagerOverview.tsx`, `managerOverviewView.ts`, `manager-overview.css`; `SourceHealth.tsx`, `sourceHealthView.ts`, `Sources.tsx`, `SourceMappingSummary.tsx`, `Sources.css`, `source-health.css`.

Necessary adapter edits outside those components are deliberately small:

- App.tsx: extraction/import of legacy Sources plus session-epoch key.
- IntegratedPages.tsx: pass the explicit source-health reread callback.
- P2Pages.tsx: pass management reread, shared Loading state and source reachability from retained-read failure.
- SettingsOverview.tsx: one standalone sources link (coordinate this tiny hunk with I6).
- LarkPilotPanel.tsx: typed display of existing roster/403 errors; transport and retry behavior unchanged.

No design foundation/token files, backend files, source schedules, endpoints or permissions were changed. Existing audit fingerprints were updated for six already-inventoried files after checking their unchanged deadlines/debounce/print/history/presentation triggers. No allow-list entry was added. In particular, the pilot timer only updates its local age presentation; report history events remain user query changes, not passive revalidation.

## Commands and results

Executed in the worktree frontend unless noted:

- `npm ci`: PASS.
- `node test-i5-redesign.mjs`: PASS — unknown legacy table count vs confirmed zero; stale source/time/age/action; three populations; Loading; 436 stable project IDs, loaded same-name count 28, 25-to-50 reveal, selection and Denied; one shared stale source label.
- `npm run test:reports`: PASS — view, requests, mocks and filters; includes literal retained failure / denied checks and seven interaction scenarios. Filter browser checks cover 1440, 1024, 768 and 390 with touch on/off.
- `npm run test:reports-progress`: PASS — existing detail/hash/focus/cancellation, status filter, points/day views, page identity, 202 and 429 and no passive polling. Updated presentation expectations for combined identity and reduced columns.
- `node test-manager-overview-view.mjs`: PASS — 33 tests / 163 checks, including mutation guards. Added Taipei formatter to mutation fixture dependencies.
- `node test-source-health-view.mjs`, `node test-source-health-ui.mjs`: PASS.
- `node test-lark-pilot.mjs`: PASS; added exact DataState kind/title assertions for shadow 403 and expired roster.
- `node test-source-lifecycle.mjs`, `node test-source-build-visibility.mjs`, `node test-home-reports.mjs`, `node test-reports-stale-notice.mjs`: PASS.
- All `test-fetch-intent*.mjs`: PASS. Core/React/audit via `npm run test:fetch-intent`; browser synthetic contract has zero idle requests. Built-app guard also passes Home, Case and Dispatch with zero idle requests and errors using the isolated API with `DISPATCH_BOARD_ENABLED=true` on port 8796. An initial guard run correctly rejected the normal demo's disabled Dispatch fixture; rerun used that enabled isolated fixture without application changes.
- `npx tsc -b`: PASS.
- `npm run build`: PASS. Existing >500 kB Assistant chunk warning remains.
- `git diff --check`: PASS.

Relevant command output is copied beside this report. Known unrelated base failures were not broadened into this unit's work. No claim that every frontend/backend test ran.

## Real browser QA

T3 preview against isolated demo API `127.0.0.1:8795`, Vite `localhost:5295`, SQLite/uploads under `/tmp/I5-demo`. A second isolated backend on 8796 enabled Dispatch only for the mandated built-app fetch guard. Default localhost profile had an older incompatible session, so full-app checks used preview's incognito profile without cookie handling or login automation. Initial preview open failed with connection refused before Vite started; it worked after server startup. Browser plugin skill was not installed; T3 preview was used under the task's explicit browser requirement, with no browser fallback.

Flows checked:

1. Real demo management route -> open details -> inline project facts -> close, preserving selection URL / focus behavior. Demo has 7 authorized project rows and unknown cards, not the company fixture's 436.
2. Real source-health route -> explicit reread, unknown/denied source facts; legacy route -> company data remains unexposed in demo. Legacy empty/no-read count is separately tested because demo's metadata cannot establish a real company source read.
3. Full shell reports using the existing explicit `?mock=1&mockState=stale` path -> all five data tabs -> mobile selected-tab visibility -> progress labelled table. No source/company writes. These are synthetic report fixtures, not staging totals.
4. Isolated production-component fixtures -> Home stale (37 / 940 / 12), 436 management rows / 28 matching names, nine stale sources, progress Loading, shadow Denied and roster Stale. These fixtures exist because demo does not expose the company source states. Fixture files are archived beside this report; restore them as frontend/.i5-qa.html and .tsx to reproduce.
5. 390px, 200% CSS zoom stress on management: no document horizontal overflow; detailed unknown fields remain readable. This is a zoom stress check, not native browser zoom automation.

Identity/nonblank/overlay/overflow checks passed. Captured states have no framework error overlay. Intentional synthetic HTTP 403s are expected errors; ordinary demo and mock-report captures had no relevant runtime error. `browser-checks.json` records the final mobile tab offsets, no horizontal overflow/overlay, and typed pilot states.

Screenshots are in this directory: `home-*`, `health-*`, `overview-*`, `loading-*` (production components with stated synthetic fixtures); `reports-{sales,progress,review,assets,contacts}-*` (full shell mock fixtures); `demo-{overview,health,legacy}-*` (real demo responses); `pilot-{denied,roster}-key-*`, `demo-overview-selected-*`, `overview-200percent-390.png`, and table/detail captures. Sizes in filenames are CSS viewports, 1440×900 and 390×844; preview PNG pixel dimensions reflect its scale. Light/dark captures were allowed to settle; transitional captures were replaced.

## Design comparison ledger

Viewed all 16 F5 exports and the reports/home, management/table and sources/health real baseline pairs. LC decisions override older F5 annotations.

Accepted differences:

- Projects, not confirmation versions, are management table grain (LC L5). Confirmation versions stay separate snapshot facts. Name-only counts are computed from loaded names and never merge identities.
- Home's V4/quote figures are — until their own page is read, instead of hardcoding the design's 398 / 394 as current data. Historic 940/398/394 is labelled baseline evidence. No extra endpoint reads were added just to populate a comparison card.
- Unverified total/PM amounts are muted `金額加總待核對`, superseding the earlier export's giant amount plus warning. Actual scalar row zero remains 0 rather than guessing it means missing (F5 Q2 had no source contract establishing that).
- Shared I1 control treatment/shell surfaces remain. No competing foundation styling was introduced.
- Progress keeps the existing 50-row server pagination / existing detail drawer. Management gets the local 25-row reveal because its complete response is already loaded. No invented grouped endpoint or new page counts.
- Mobile uses labelled table records, preserving the same semantic data and sort/pagination instead of maintaining a duplicated ul view. Review/assets/contacts retain full supported fields and clear desktop horizontal-scroll affordances; undrawn tabs use the shared card/row/state language.
- Sources' new rule explanation names retained snapshot freshness conservatively; it does not claim a successful GET proved a successful new Lark read or promise a background update. Absolute per-source success times remain because different rows may differ.
- Report status/options/chart categories remain the server's actual values; no hardcoded stage-fixture buckets or unsupported per-source coverage indicator is invented.

Fixed/rejected differences: repeated health badges/relative ages; arbitrary giant financial headlines; unknown-as-zero; unsupported background-refresh copy; confirmation-version row wording; blank owners; overly wide progress/sales rows; selected tab hidden after desktop-to-mobile resize; lost stale report on refresh failure.

## N-items and follow-ups

- Independent management health/review/publish columns need new per-project contracts: NOT implemented. Top-level source link remains.
- Management pending-decision/overdue/weekly-activity facts remain unknown where the backend supplies no verified measure; no inference from execution status or source health.
- No new global V4/quote count/time contract was added to report Home. Those pages remain the authority for their populations.
- Finance aggregates need an authorized live raw-cell/outlier check after integration before removing `金額加總待核對`. LC's numeric parsing fix remains intact; synthetic tests do not certify a corrected company total.
- Progress per-source partial coverage and the single-case plan outlier claim need complete source evidence; no arbitrary warning or fabricated contributing-case count was added from one paginated screen.
- Coordinator must obtain the independent cross-family implementation review and reconcile the tiny SettingsOverview / P2 adapter hunks with their owners. No independent approval is claimed here.


## Integration follow-up — 2026/11/03

Status: integration merge resolved and verified; original screenshots are retained unchanged. No new view design, backend change, deployment or company-data access.

Merged integration commit `a4398e0089e631b3e2db5a44b36458a862d4117d` into I5 commit `393e23d0f18ae54519df17e885ebbe28b257a9e1`. Merge commit: `97239bad179e0e2bf74b390b41cc5dec15e2f841`. Final evidence-commit head is reported in the worker handoff.

Manual conflict resolutions only:

- `frontend/src/P2Pages.tsx`: retain I4 confirmation refresh callback and ConfirmationList binding; retain contract/work-item forbidden/unlocated rendering, confirmation breadcrumb ownership and removal of the confirmation IntersectionObserver prefetch. Retain I5 manager-overview refresh callback, shared Loading DataState and source-health link. The auto-merged IntegratedPages source reread callback is intact. No confirmation/contract/work-item code was replaced with the older I5 version.
- `frontend/test-fetch-intent-audit.mjs`: preserve all nonconflicting unit changes and recompute only the existing P2Pages whole-file fingerprint for the resolved file. Both parents and the resolved audit contain 38 entries; no entries or blanket exemptions were added. Neither parent deleted a key relative to their merge base. I4's actual automatic-prefetch code deletion remains applied.

Verification (all executed against the merged worktree):

- PASS `node test-i5-redesign.mjs`.
- PASS `npm run test:reports` and `npm run test:reports-progress`.
- PASS `node test-reports-stale-notice.mjs`.
- PASS `node test-manager-overview-view.mjs` (33 tests, 163 checks).
- PASS `node test-source-health-view.mjs`, `node test-source-health-ui.mjs`, `node test-lark-pilot.mjs`, `node test-source-lifecycle.mjs`, `node test-source-build-visibility.mjs`, `node test-home-reports.mjs`.
- PASS I4-focused compatibility checks `node test-i4-work-confirmations.mjs` and `node test-confirmations-loading.mjs`.
- PASS all four `test-fetch-intent*.mjs`: `npm run test:fetch-intent` covers core, React and audit; `YX_FETCH_INTENT_API_URL=http://127.0.0.1:8796 node test-fetch-intent-browser.mjs` covers synthetic browser and the built app against an isolated demo backend with Dispatch enabled. Home, Case and Dispatch render with no runtime errors and zero idle requests.
- PASS `npx tsc -b`, `npm run build`, `git diff --check`. Existing Assistant chunk-size warning remains.
- Additional diagnostic `node test-p2-routes.mjs`: FAIL on the pre-existing assertion that navigation must not contain `{view:'work',label:`. Both this test and AppShell.tsx are byte-identical to integration (verified against the merge parent); integration now deliberately includes the work destination. No unrelated file or assertion was changed. This diagnostic failure does not affect the passing I4-focused checks above.

The `I5-followup-*.txt` transcripts are included alongside this report. A temporary demo backend on port 8796 was used only for the required browser fetch-intent test and stopped afterward. No additional application files were edited beyond the two conflict resolutions. This entire evidence directory, including screenshots and REPORT.md, is copied to `/Users/vc/.local/state/t3-pstack/orchestrate/yx-redesign/impl-evidence/I5/` for coordinator review.


## Claude review follow-up — 2026/11/03

Scope: the three small items explicitly requested from IMPL-batch1-review.md, I5 P3-17/18 and P3-19's report-week date. Integration merged FIRST and fast-forwarded cleanly to `aeee3a24`; no conflicts or audit fingerprint edits were needed. Code commit: `be00c28943c612266aec8b8c3c4af51f5e094867`. Final evidence commit head is in the worker handoff.

Changes:

1. Unknown responsible cells now display 待核對. A verifiably empty source string (including whitespace-only) with a valid nonblocking state is projected as known / 未填. Null, not-loaded, unavailable and withheld labels remain unknown. The current backend's missing-authorized-label reason therefore produces 待核對; no backend data or inference was changed.
2. Summary cards share the enclosing snapshot time once at section level. Unknown cards contain only — and 尚未載入, never a fabricated per-card data time. Known cards with the common timestamp also avoid repetition; a known card carrying a genuinely different data time retains that distinct provenance.
3. Reports Home formats its seven-day report interval as `2026/10/26–11/01`. The pure UTC calendar helper rejects invalid dates, handles leap days and shows the full end year across a year boundary (`2026/12/28–2027/01/03`). No query, week selection or fetch behavior changed.

Files: ManagerOverview.tsx, managerOverviewView.ts, reports/HomeTab.tsx, reports/reportsView.ts, test-i5-redesign.mjs and test-manager-overview-view.mjs. No other review items or application files were changed.

Tests/results:

- PASS `node test-i5-redesign.mjs`: literal unknown/blank owner cells, one summary timestamp, no unknown-card timestamp, shared vs distinct known-card time, exact formatted week, invalid date and leap/year boundaries, plus existing I5 state/population/reveal tests.
- PASS the same suite with `TZ=America/Los_Angeles`.
- PASS `node test-manager-overview-view.mjs`: 34 tests, 173 checks, including explicit empty-string/whitespace source values and unknown/not-loaded/withheld reasons.
- PASS `npm run test:reports`, `npm run test:reports-progress`, `node test-reports-stale-notice.mjs`.
- PASS source-health view/UI, Lark pilot, source lifecycle/build visibility and Home report suites.
- PASS all four `test-fetch-intent*.mjs`: core/React/audit via `npm run test:fetch-intent`; browser test run with `YX_FETCH_INTENT_API_URL=http://127.0.0.1:8796` against an isolated demo with Dispatch enabled. Built Home, Case and Dispatch have zero idle requests and no runtime errors. No audit exemptions were added or changed.
- PASS `npx tsc -b`, `npm run build`, `git diff --check`. Existing Assistant chunk-size warning only.

Visual verification: T3 preview on isolated demo API 8796 and Vite 5295, incognito localhost profile. The temporary `review-shell-fixture.html` archives a reproduction harness based on the real index bootstrap and real App/AppShell: it supplies a synthetic dated report response, and changes two isolated demo owner fields to explicit unknown / explicit blank. It does not bypass the view model, write data or contact staging/production. The app renders PM 週報 / 管理總覽 H1s, full shell, real filters and reread controls. Browser checks confirm owner cells `待核對`, `未填`, then the actual demo owner; exactly one 資料時間 in the summary section; and `報告週 2026/10/26–11/01`. No document overflow or framework overlay at 390px. Screenshots at CSS 1440×900 and 390×844, light/dark: `review-home-shell-*`, `review-overview-summary-*`, `review-overview-owners-*`. These supplement the older component-only evidence and address the review's shell-evidence clarification. All captures were taken after theme transitions settled. The temporary frontend entrypoint and local services were removed/stopped after verification.

The remaining optional I5 P3 observations (KPI links/units, zero-quality-reminder copy, money typography, rail scroll behavior and tab semantics) are outside these three requested fixes and remain coordinator follow-ups. No new source contract or capability was introduced.
