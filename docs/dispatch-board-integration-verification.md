# Dispatch board app integration verification

Implemented directly in `/Users/vc/.t3/worktrees/YXMEEGLE/dispatch-int`, branch `t3/dispatch-board`, starting at `844aeaa`.

## Behavior

The home card appears in `todo` (需要處理), because its pending dispatches and overlaps require decisions or follow-up. It is available in all three home views for eligible users. Existing section order and saved layout version 2 remain unchanged. Old layouts append the new card through the existing parser. Users can hide or reorder it within the section.

`dispatchAccess.ts` owns the predicate shared by navigation and home card availability. It preserves all existing navigation restrictions. The flag must be boolean true, the role must be PM or manager, and the session must be a Lark company workspace outside the test/demo prefixes.

The card reuses `Card`, `Button`, `Skeleton`, `useViewData`, and the board's parser, week function, display selector, and request lifecycle. `useDispatchBoardRead` is the existing board request logic extracted for both consumers. Failed reads are isolated from other cards. Cold failures, forbidden responses, and empty windows display dashes. Retained data explicitly identifies counts as the last successful snapshot. Stale data includes age. The source note preserves the last booking date and reported gaps. The board link is `#view=dispatch`.

The drawer matches an exact case code or, when there is no code, a unique name. Conflicting code/name candidates remain unresolved. A name cannot override a different code. It first uses available workspace projects. If the shell lacks a match, the drawer queries the existing `GET /api/projects` overview search with `tab=all`, `q`, `limit=100`, and `offset=0`. Only complete, validated search results qualify. Truncated, malformed, failed, ambiguous, or missing results display plain text `案件連結未能解析`. Record references are never a fallback. Resolved links use the existing `#view=project&project=…&tab=flow` route and `homeHref` helper.

The people attendance route is `#view=people`. `PeopleAttendancePanel` keeps the week and name filters in local React state and reads no person/date route parameters. Person names therefore remain plain text. No deep link was invented.

No case detail panel was added. Before that can work against real data, repair or replace the schedule's dangling 案件 relation to missing table `tbljGNdDxLs8ihuE`, define the mapping to the app's canonical project identifier, expose the resolved code/name, and provide a case-filtered dispatch read or agreed week/filter contract. Permissions, partial joins, stale data, and source gaps must survive that mapping. Live verification needs a real resolved case and a missing-case example.

## Tests and commands

`test-home-dispatch.mjs` was written before the implementation and initially failed because the modules did not exist. Updated literal layout expectations failed before adding the card. A further literal regression failed before rejecting a matching name with a different code.

All 17 commands in `output/dispatch-board/home-test-results.json` pass. The commands are `npm run build`, `npx tsc --noEmit -p tsconfig.json`, `node test-dispatch-board.mjs`, `node test-contrast.mjs`, every `test-home-*.mjs` except the two exclusions below, and `node test-unified-home.mjs`.

The excluded scripts are `test-home-panels.mjs` and `test-home-target-navigation.mjs`, as requested for known baseline failures. No other failing check was ignored. Existing SSR layout-effect warnings remain in the dispatch test logs. `git diff --check` passes.

The new script covers literal permission results, navigation rendering, v2 migration and grouping, case resolution and ambiguous/malformed/truncated results, all source states, all three mounted home views, retained HTTP failure, clearing on HTTP 403, other-card survival, and disabled/member request suppression.

## Browser evidence

The Vite harness ran from this worktree with `DISPATCH_TEST_PORT=5199 node qa/dispatch-board-vite.mjs`. Port 5198 already served `/Users/vc/.t3/worktrees/YXMEEGLE/t3-f824e8ff/frontend`; that process was left alone. The harness now serves synthetic home panels, company summary, attendance state, and project search. Its session uses Lark mode so the existing company-workspace gate can be exercised. It performs no real Lark reads or writes. Report access is explicitly unavailable in this fixture.

T3 collaborative preview captured the real home at 1280 × 1600 and 390 × 2300. All twelve captures have document width equal to viewport width. Card top and height are identical across all six states at each width. Desktop card top is 746.1796875px and height is 471.84375px. Mobile card top is 1044.1171875px and height is 455.84375px. Removing the shared count skeleton's margins fixed the measured 8px loading-height difference.

`output/dispatch-board/home-browser-evidence.json` records states, counts, other cards, bounds, source text, and screenshot paths. Screenshots are:

- `output/dispatch-board/home-loaded-1280.png` and `home-loaded-390.png`.
- `output/dispatch-board/home-loading-1280.png` and `home-loading-390.png`.
- `output/dispatch-board/home-forbidden-1280.png` and `home-forbidden-390.png`.
- `output/dispatch-board/home-read_failed-1280.png` and `home-read_failed-390.png`.
- `output/dispatch-board/home-empty_future_window-1280.png` and `home-empty_future_window-390.png`.
- `output/dispatch-board/home-stale-1280.png` and `home-stale-390.png`.

The read_failed fixture contains last-good slots, so its counts remain 1, 2, 2 with failure and snapshot labels. Cold failures without slots have separate literal tests and show dashes. Forbidden and empty-future captures show dashes. Empty-future text preserves `2026-08-19`.

Browser drawer verification resolved 示例 C001 to `#view=project&project=synthetic-project-c001&tab=flow` through project search. 示例 C002 shares the synthetic name but has a different code. It displays `案件連結未能解析` without a link after the code-mismatch regression fix. Neither drawer rendered raw references. Person rows have no links.

## Decisions and limits

Model the Domain shaped the shared parsed board and access predicate. Test Behavior, Not Implementation shaped literal counts, routes, migration, and mounted-view checks. Prove It Works caught the skeleton geometry and mismatched-code fallback on the running application. Type System Discipline kept project search responses unknown until validation. These leaf skills were read during this implementation.

The throughput checkpoint used contract and pattern reads as the blocking first steps. Independent workstreams were not split because home layout, permissions, and the shared board request hook form one coupled frontend change. Shared mutable state stayed with one implementation owner in the explicitly assigned worktree. The smallest safe decomposition was tests, implementation, real browser verification, and final checks. Architecture and implementation remained in-thread under the requested implementation-subagent role. Independent review remains with the parent task. No PR was opened.

Live backend integration was not exercised. Real case relations still dangle. No push, deploy, new worktree, dependency installation, or Lark write occurred. `frontend/node_modules` remains the original symlink.
