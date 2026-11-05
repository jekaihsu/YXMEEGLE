# Frontend loading performance — 2026-10-25

Base: `5c39bb0`. Worktree branch: `t3/frontend-data-loading-performance`.
All HTTP measurements use synthetic local fixtures. No live Lark reads or writes, deployment, push, or edits in sibling worktrees.

## Measurements

Sizes count the complete static manifest import graph, including React and icons; deferred chunks are excluded from initial bytes. Gzip sizes are recomputed with the same Node zlib default level 6 for both builds. Exact values and timing conditions are in `frontend/qa/loading-performance-results.json`.

- Entry JavaScript: **479.80 → 260.86 kB raw**; 155.26 → 87.19 kB gzip.
- All initial JavaScript: **647.02 → 428.08 kB raw** (−33.8%); 205.69 → 137.61 kB gzip.
- Initial CSS: **287.22 → 230.28 kB raw** (−19.8%); 47.68 → 37.90 kB gzip.
- Total JavaScript across every route: 1,200.05 → 1,206.04 kB raw (+0.5% splitting overhead).
- Chrome median DOMContentLoaded: **346.7 → 285.4 ms**; first contentful paint: **404 → 336 ms**.
- Quote next-page interaction: **146.2 → 50.8 ms** median over 28 interactions per build.
- Initial quote-table readiness, 2,000 rows: **1,302 → 1,304 ms**, effectively unchanged. Twenty sequential page requests remain the limiting factor.
- Isolated 10,000-row quote-number sort: **260.7 → 15.3 ms**, median of five warm runs after one warmup.

Browser conditions: seven fresh Chrome contexts per build, `channel: 'chrome'`, headless, 4× CPU slowdown, 40 ms network latency, 1,250,000 bytes/s download/upload, gzip local responses. Pagination duration includes Playwright actionability overhead. These are local diagnostics, not production Lark latency claims. Both builds had zero uncaught browser errors.

## Changes and rationale

- `frontend/src/App.tsx`: lazy-load projects, operations/settings, dispatch, work/source health, people, and Lark diagnostics. Keep the default dashboard eager. A Suspense boundary retains the shell while secondary code loads.
- `frontend/src/IntegratedPages.tsx`: remove the unused dispatch re-export; opening work/source-health no longer downloads the dispatch editor. Existing Vite React/icon vendor chunks already work correctly and remain unchanged.
- `frontend/src/Quotes.tsx` and `quoteApi.ts`: reuse `Intl.Collator` with the original locale/numeric semantics, memoize searchable text and sorted rows, and cancel obsolete page/detail reads. Sorting, filtering, pagination, amount redaction, and all-pages-before-global-sort behavior remain intact.
- `frontend/src/api.ts`: default GET/HEAD deadlines to 30 seconds, retain explicit longer deadlines and `timeoutMs: 0` opt-out, settle cancellation during headers/body even when the transport ignores abort, and skip pre-aborted requests. Mutation deadlines/retries remain caller-owned. No new automatic retries or global TTL cache: existing domain readers already deduplicate/cache with workspace, identity, revision and reload scopes; an unconditional shared TTL could suppress explicit refreshes.
- `backend/app.py`: successful/partial/304 hashed `/assets/*` responses receive `public, max-age=31536000, immutable`. HTML remains `no-cache`, API responses remain `no-store`, and unhashed/missing files never receive immutable headers. Existing gzip level 5 already compresses API/static responses; it is preserved and verified rather than adding another compression layer/dependency.

New/extended verification: `frontend/test-build-loading.mjs`, `test-api-cancellation.mjs`, `test-api-response.mjs`, `test-quotes.mjs`, `test-quotes-ui.mjs`, and `backend/test_frontend_transport.py`. The API response harness now bundles its relative imports, fixing its pre-existing data-URL import failure.

## Verification

- `npm ci`; `npm run build`: passed. No dependency/lockfile changes.
- Every `frontend/test-*.mjs`, run independently with `node`: baseline **96/112 scripts passed**; changed tree **100/114 passed**. No new failures. Two new scripts pass; API-response and tooling/bundle-budget scripts now pass. The symlinked dependency baseline and an archived base source tree using the installed npm dependencies produced the same failed-script set.
- Final targeted reruns of API response/cancellation, ETag/view-data/StrictMode races, performance instrumentation, quote contracts/UI, and production split budgets: passed. Quote tests cover all sort keys/directions/nulls/ties, no input mutation, no resorting on pagination/parent updates, and obsolete network cancellation.
- `/Users/vc/Local/YXMEEGLE/.venv/bin/python -B -m pytest backend/test_frontend_transport.py backend/test_server_timing.py backend/test_backend.py -q`: **29 passed**. Includes gzip/identity access preservation, HTML/assets/API cache contracts, range requests and 304s.
- `git diff --check`: passed.

The following 14 frontend scripts fail on both base and changed source and remain outside this implementation:

- `test-dispatch-board.mjs`, `test-dispatch-fixes.mjs`
- `test-home-panels.mjs`, `test-home-target-navigation.mjs`
- `test-ops-sync-panel.mjs`, `test-search-input.mjs` (module-resolution setup)
- `test-p2-routes.mjs`, `test-plan-panel.mjs`
- `test-read-loading.mjs`, `test-reload-generation.mjs`
- `test-reports-interactions.mjs`, `test-shell-mode.mjs`
- `test-sop-tasks.mjs`, `test-ux-case-detail.mjs`

## Reproduce browser measurements

Keep the base build before editing, or build an archived copy of base source using the same dependencies. From `frontend/`:

```sh
npm run build
node qa/loading-performance.mjs /path/to/base/dist /tmp/yx-before.json
node qa/loading-performance.mjs dist /tmp/yx-after.json
```

The benchmark defaults to the provided `/private/tmp/yxr/pwi/node_modules/playwright-core/index.mjs`; set `PLAYWRIGHT_MODULE` to another Playwright core module path when needed. Chrome must be installed. The harness serves fixture APIs itself, binds only to loopback, and blocks every external browser request.

Remaining opportunities: quote acquisition still fetches every 100-row page before sorting, and the main CSS bundle is still substantial. Changing server-side sorting/paging or dividing shared global CSS warrants separate coordination with the owning agents. The default dashboard's model/data logic and all explicitly excluded files were left untouched.

## Follow-up: bounded bulk quote pages — 2026-10-25

Measured again from merged `t3/ui-clean-redesign` HEAD using the same fictional
2,000-row Chrome workload and throttling above. Seven fresh contexts per build:
quote-table readiness median **1,296.6 → 294.9 ms** (−77.3%); sequential
requests **20 → 1**. All seven after runs issued exactly one request; neither
build had browser errors. These fixture responses exclude backend/Lark latency.
Samples and conditions: `frontend/qa/quote-bulk-results.json`.

The existing `/api/quotes` route now accepts a bounded limit of **2,000**
(previously 100); its default remains 30. The register requests 2,000 rows per
page, following the actual returned row count until all pages arrive. This
keeps global client sorting, filtering, page resets, cancellation and explicit
reload behavior. Larger registers still paginate (2,001 rows need two reads).
There is no unbounded bulk endpoint or source refresh. The same visibility
projection, search including 工程編號, amount redaction and SOP counts apply.
The backend already constructs the entire visible register before slicing;
larger pages also avoid repeating that work twenty times.

Reproduce with `npm run build` and the existing
`node qa/loading-performance.mjs dist /tmp/quotes.json`. Its fictional server
now honors the requested `limit` and records quote request counts. The UI tests
cover 2,000/2,001 rows, cross-page global ordering and engineering-number search;
existing sort-key/direction/null/tie and obsolete-request tests remain intact.
The real-app backend test covers 2,003 visible entries in two pages, hidden
source exclusion, redaction, counts and engineering-number search.

Follow-up targeted verification: both quote scripts pass (contracts/sorts and
13 UI cases), TypeScript/Vite production build passes, and the combined
reports/quotes/transport backend run passes **185 tests, 1 skipped**.
