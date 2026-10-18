# Dispatch board frontend verification

Implemented in `/Users/vc/.t3/worktrees/YXMEEGLE/t3-f824e8ff` on `t3/dispatch-board-page`.
The authoritative contract is `/Users/vc/Local/YXMEEGLE/docs/SOP_R1_SLICE1_DISPATCH_BOARD_20261018.md`.

## Implementation

`frontend/src/dispatchBoardModel.ts` owns the parsed envelope, enum degradation, date validation, queue, KPI, day and group selectors, person-day grid, display rules, and Chinese reason labels. External values enter as `unknown`. Unknown enum values become `unknown`. Malformed or duplicate slot identities are excluded and mark the source partial. Missing dates stay unresolved and do not enter day cells. Unsupported envelope versions or invalid windows produce a local read error.

KPI and queue values are recomputed from the parsed slots. Wire aggregates cannot disagree with the displayed list. People without bookings show unknown attendance. The UI never infers that an unbooked person is available.

`frontend/src/DispatchBoard.tsx` and `DispatchBoard.css` provide the week controls, summary, queue, daily groups, person-day view, source age, gaps, and detail drawer. The drawer reuses the existing focus trap. Date-only overlaps retain their unknown status. Inactive people and instruments with repair reasons are unavailable. Qualification and leave checks remain unknown.

`api`, `useViewData`, `Button`, `Badge`, `Skeleton`, `Eyebrow`, `useDialogFocus`, and the existing glass and color tokens are reused. No dependency was added. The feature makes only GET requests. Refresh failures keep the last successful response for the current week. A 403 replaces it with a sanitized forbidden response. Session epochs and week keys prevent prior identities or weeks from appearing during a new read. A stale response or pending joins trigger up to three additional reads, 1.5 seconds apart. Manual refresh remains available.

The app uses `/#view=dispatch`, its existing hash-route equivalent of `/dispatch`. `Session.features.dispatch_board` must mirror backend `DISPATCH_BOARD_ENABLED`, just as `node_assignment` mirrors its backend flag. Navigation and direct route rendering require the boolean `true`. An absent or false flag shows the disabled landing page and makes no dispatch request. Dispatch renders its frame after session discovery without waiting for the workspace response.

Changed integration files are `frontend/src/App.tsx`, `AppShell.tsx`, `IntegratedPages.tsx`, `api.ts`, `appCommon.tsx`, and `types.ts`. `frontend/package.json` adds `test:dispatch-board`.

## Fixture and mock

`frontend/fixtures/dispatchBoardSample.json` labels all records as synthetic. Each object under `variants` is a contract-shaped response. Variants are `loaded`, `stale`, `read_failed`, `forbidden`, `empty_future_window`, and `partial_joins`. The loaded response includes one unassigned slot, two overlapping timed slots, two date-only overlaps, an inactive person, and a repair-state instrument. The empty response preserves the real contract's last-booking date of `2026-08-19`.

Run the real Vite application with the isolated memory mock.

```sh
cd /Users/vc/.t3/worktrees/YXMEEGLE/t3-f824e8ff/frontend
node qa/dispatch-board-vite.mjs
```

Open `http://127.0.0.1:5198/#view=dispatch`. `DISPATCH_TEST_PORT` selects another port. The mock serves synthetic session and shell responses plus `GET /api/v2/dispatch/board`. It shifts synthetic booking dates and capacity days into the requested week. For nonempty synthetic responses it advances the last-booking date to cover that week. The empty variant retains `2026-08-19`. Production imports neither this mock nor its fixture.

Change the mock's memory state by posting JSON to `/__dispatch-test/state`.

```json
{"state":"loaded","delay":0}
```

The other states are `stale`, `read_failed`, `http_failed`, `forbidden`, `http_forbidden`, `empty_future_window`, `partial_joins`, and `flag_off`. `delay` is milliseconds. Reload the page for a cold read. Use the page's refresh button to verify retained data. Browser screenshots use a 60-second delay to capture the cold loading state.

## Commands and results

- `npm ci --no-audit --no-fund` installed the existing lockfile dependencies.
- `npx tsc -b` passed.
- `npm run build` passed, including TypeScript and Vite production compilation.
- `npm run test:dispatch-board` passed 64 literal parser, selector, rendering, feature gate, request, failure-retention, 403-clearing, and session-isolation assertions.
- Twenty of twenty-one relevant Node scripts passed. All results and individual local logs are under `output/dispatch-board/`. `test-results.json` records the complete list.
- Passing scripts include `test-data-state.mjs`, `test-contrast.mjs`, all three node-assignment scripts, `test-project-progress.mjs`, `test-ux-disabled.mjs`, `test-integration-routes.mjs`, the home layout/counts/unified tests, all three home-report scripts, `test-home-review-regressions.mjs`, `test-p2-routes.mjs`, `test-company-route.mjs`, `test-api-response.mjs`, and `test-session-epoch.mjs`.
- `test-shell-mode.mjs` fails its existing table-header assertion at line 72. It expects `來源 · 工作台 · 關注` and `執行歸屬 · 專案經理`; the page renders `案件狀態` and `歸屬與負責人`. The same failure was reproduced from a clean `git archive HEAD frontend`, using the same dependencies. The scratch baseline was removed. `baseline-shell-mode.log` preserves the result.
- The two home tests explicitly excluded by the task, `test-home-panels.mjs` and `test-home-target-navigation.mjs`, were not run.
- `git diff --check` passed.

Existing jsdom tests emit their `window.scrollTo` warning. The new dispatch script runs without those warnings. No browser application exception was observed.

## Real browser evidence

T3 collaborative preview drove the real application and saved the screenshots. Desktop viewport is 1280 × 1800. Mobile viewport is 390 × 2000. The taller mobile capture shows the queue followed by the per-day list. Day containers scroll internally so their reserved geometry stays stable.

All six scenarios have document scroll width equal to viewport width. The loading-state skeleton initially exposed a horizontal overflow at 390px. Setting the grid children and queue flex container to `min-width: 0` fixed it. All captures listed below contain the fix.

At 1280px, loading and loaded queue tops are both 655.30px and grid tops are both 1037.30px. At 390px, queue tops are both 878.09px. Mobile grid tops differ by less than 0.05 CSS pixels due to subpixel layout. Stale and failed notices retain the loaded frame geometry. `browser-evidence.json` contains all measured positions, sizes, displayed counts, and document widths.

Keyboard verification passed on both group and person views. ArrowRight moved from Monday to Tuesday. The first Tuesday slot received visible focus with a 2px solid outline. Enter opened `示例 C002`. Esc closed the drawer and restored focus to its trigger. The timed-overlap explanation appeared in Chinese. The inactive-person and repair-instrument drawer showed both unavailable badges and Chinese reasons. It fit the 390px viewport.

The partial-join response first displayed `姓名待確認` for `示例 C002`. After the mock switched to the joined response, the automatic reread filled in `示例 林安娜`. Neither state rendered a raw record ID. Flag-off browser verification showed the disabled landing page, no dispatch navigation button, and zero requests to `/api/v2/dispatch/board`.

The failure screenshots use a successful board followed by a contract `read_failed` response. They retain KPI values `6, 1, 2, 2` and display inline retry. Forbidden screenshots use HTTP 403 and show only dashes. Empty screenshots show the `2026-08-19` notice and dashes instead of healthy zeroes.

Screenshots are saved in `output/dispatch-board/`.

- `loading-1280.png` and `loading-390.png`.
- `loaded-1280.png` and `loaded-390.png`.
- `stale-1280.png` and `stale-390.png`.
- `failed-1280.png` and `failed-390.png`.
- `forbidden-1280.png` and `forbidden-390.png`.
- `empty-1280.png` and `empty-390.png`.
- `detail-390.png`.

`prefers-reduced-motion` removes skeleton animation, transitions, transforms, and smooth scrolling in the board and drawer. This is covered by the stylesheet, rather than a browser media-emulation measurement. The existing light/dark contrast test passed with the reused tokens and Badge/Button colors.

## Limits and delivery

There are no intentional wire-contract deviations. The internal model accepts missing optional values conservatively and adds `unknown` to enum domains. The root fixture wrapper carries its synthetic label and named variants; each response under it follows the contract. The hash route is the app's equivalent of `/dispatch`.

The backend is not part of this change. Its endpoint, feature payload, permissions, coalescing, and live source behavior still need integration verification after the parallel backend work lands. This run used contract-shaped synthetic responses. No backend files were changed. Nothing was pushed or deployed, and no PR was opened.

Model the Domain shaped the single typed envelope and selectors. Type System Discipline shaped the unknown-input parser and enum fallback. Prove It Works caught and verified the mobile skeleton fix on the running application. Test Behavior, Not Implementation shaped the literal test expectations. Their leaf skills were read in this session.

The throughput checkpoint ran contract and existing-pattern reads first, then model, UI, integration, and verification. One implementation owner held the coupled frontend files. The isolated worktree avoided shared mutable writes. Implementation stayed in-thread under the requested implementation-subagent role. Independent review belongs to the parent task. No nested agents were dispatched.
