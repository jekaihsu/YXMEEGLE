# Unified project flow verification

Implemented in the isolated worktree `/Users/vc/.t3/worktrees/YXMEEGLE/t3-9dacab7b` on branch `t3/project-detail-flow-restructure`, based on local commit `531f864`. Only `frontend/` and `output/` changed. No backend edit, push, deployment, or PR.

## Result

The project tabs are 流程, 日報, 案件資料, 檔案, 紀錄. The four old flow-related hashes remain valid. `overview` scrolls to the workspace top, `progress` to the selected evidence block, `flow` to the selected node, and `tasks` to the all-task list. The view adapter preserves node, task, completion, focus, comment, and return-context parameters. Existing API normalization remains intact. `route-callers.txt` contains the source caller inventory, including home, reports, completion, notifications, and assignment links.

`flowModel.ts` builds on `joinProgressStages`. It joins authoritative node state, owners, deadlines, source quantities, gaps, and one normalized task list. Cancelled and superseded tasks are excluded. All task counts and displayed task rows use that model. Overall progress uses non-cancelled task completion when tasks exist. Otherwise it uses node handoff completion. The label states that basis. Physical production quantities are never inferred from task completion. Missing quantities and missing units remain unknown.

The nine-node diagram uses status icons and text, per-node progress, avatars, task counts, next deadlines, and overdue marks. Arrow keys, Home, and End change the selected node and URL. It is horizontal at 1280px and vertical at 390px. The transition uses available content width, at 750px, so it also accommodates a narrow desktop workspace with a sidebar.

The selected panel reuses production evidence and existing assignment forms. Tasks support current-node and all-task views, composed filters, the shared TaskInspector entry point, roster assignment, creation, and the original revision-checked mutation paths. The roster endpoint already returns employed, group-authorized people. No workspace-wide user list grants assignment authority.

Scheduling uses `canWriteDispatch`, the existing publish dialog, and existing dispatch work records to resolve the parent obligation and confirmation. A unique matching obligation prefills the dialog. Multiple matches require selection. No match explains how to establish an obligation. The project identity, group, and node position must match, including the shared mapping/report department groups. Case codes and display names do not select a parent obligation. Case, project, department, package, and parent references come from that obligation. Drafts use the same local storage key as the dispatch workspace. Publishing refreshes node tasks and evidence. A rendered integration test publishes a fixture command and verifies that the newly returned V4 task appears.

The old CaseOverview, ProgressOverview, ProjectProgress page body, StageButton, second assignment diagram, and second node/task list were removed. ProductionCard and the forms moved into focused modules. The original local workflow remains available when node assignment is disabled. Local completion and local TaskInspector behavior are preserved. The existing inspector entry point also accepts Lark assignment tasks, whose details and state controls use the assignment API.

The six requested secondary sections start collapsed. SOP help, readiness, and legacy operational review also stay available in collapsed sections. Shared dialogs opened inside the CSS container use body portals. Browser inspection caught the fixed-position containment issue and verified the fix.

## Commands and results

- `node test-project-flow-model.mjs` passed. Tests were written before the model existed. They assert literal model numbers, alias focus, cancellation, filters, unknown actual quantities, and dispatch references.
- `node test-project-flow-ui.mjs` passed. The first run failed against the old eight-tab UI. The suite checks the rendered workspace, keyboard navigation, composed filters, permission reasons, PATCH payloads, retained assignment errors, task creation, publish refresh, aliases, source failure isolation, independent loading, legacy mode, old-server detail caching, and recovery from detail failure.
- `node test-node-assignments.mjs` passed. The retired UI-selector tests were replaced with hook/API lifecycle checks. These cover shared prefetch, StrictMode, revision envelopes, uncertain-result request reuse, double-submit prevention, field errors, conflict refresh, unmount, and session separation. The unified UI suite now owns the visible assignment behavior.
- `node test-node-evidence.mjs` passed. Parser and pure evidence tests remain. Item sheets, unknown quantities, item status, and keyboard dismissal now test the reused NodeWorkItems component directly instead of the removed second diagram.
- `node test-start-sop.mjs` passed. Its 41 tests exercise SopControls, UsageMap, PlanLine, and useStartSop directly.
- Every `frontend/test-*.mjs` was run with Node before and after the change. The baseline had 96 scripts. The implementation has 98 scripts, with 89 passing and the same nine failures. `verification/results.json`, `verification/summary.json`, and the per-script logs contain the results. There are no additional failures. Result manifests are committed. Per-script logs remain local under the repository log ignore rule; build, typecheck, and unified-flow UI logs are explicitly retained in the commit.
- The required case-detail-view, case-navigation, dispatch-board, dispatch-publish, dispatch-publish-ui, dispatch-round2, and contrast scripts passed.
- `npm run build` passed. Its full output is `verification/build.log`.
- `npx tsc --noEmit -p tsconfig.json` passed. Its output is `verification/typecheck.log`.
- `git diff --check` passed.

The unchanged baseline failures are `test-dev-tooling.mjs`, `test-home-panels.mjs`, `test-home-target-navigation.mjs`, `test-ops-sync-panel.mjs`, `test-plan-panel.mjs`, `test-reports-interactions.mjs`, `test-search-input.mjs`, `test-shell-mode.mjs`, and `test-ux-case-detail.mjs`. They were not fixed.

## Browser evidence

The actual application ran through `frontend/qa/project-flow-vite.mjs` at port 5208. This uses the repository's Vite fixture-server approach. It renders App and ProjectDetail with contract-shaped synthetic node, task, production, unknown, error, and dispatch responses. It does not connect to or write Lark.

The T3 collaborative browser verified 1280 x 900 and 390 x 844 CSS-pixel viewports. Both had no horizontal document overflow. A cold initial case load made one node-assignment request and one progress request, with zero detail requests when embedded node details were supplied. Browser keyboard checks changed field to control and back, synchronized the URL, and retained the selected-step focus. A task row opened the body-portalled inspector. Escape closed it. Actual fixture UI actions attached a person and created a task, then confirmed successful readback.

`browser-evidence.json` records viewport measurements, request counts, alias destinations, and scenario paths. The stable alias captures have their target blocks below the fixed application header. Schedule field captures show the verified project, confirmation, department, and parent values.

Screenshots are all under this directory.

- `alias-flow-1280.png`
- `alias-flow-390.png`
- `alias-overview-1280.png`
- `alias-overview-390.png`
- `alias-progress-1280.png`
- `alias-progress-390.png`
- `alias-tasks-1280.png`
- `alias-tasks-390.png`
- `attach-person-1280.png`
- `attach-person-390.png`
- `create-task-1280.png`
- `create-task-390.png`
- `default-1280.png`
- `default-390.png`
- `evidence-error-1280.png`
- `evidence-error-390.png`
- `evidence-unknown-1280.png`
- `evidence-unknown-390.png`
- `legacy-1280.png`
- `legacy-390.png`
- `loading-1280.png`
- `loading-390.png`
- `schedule-fields-1280.png`
- `schedule-fields-390.png`
- `schedule-prefilled-1280.png`
- `schedule-prefilled-390.png`
- `task-filters-1280.png`
- `task-filters-390.png`
- `task-inspector-390.png`

## Decisions and limits

No feature from the requested flow is intentionally omitted. Unknown source quantities remain unknown in both the model and UI. The API supplies actual quantity unit notes rather than a guaranteed common planned unit, so the UI preserves the source note and warns against summing unlike units. It never assigns a guessed unit or divides unlike quantities.

The browser run uses synthetic responses, as allowed by the requested verification method. Live Lark writes and live production credentials were not exercised. Dispatch backend approval rules and source schemas were unchanged. Independent design/review delegation and PR work remain with the parent orchestration role. This implementation delegate did not launch child agents or open a PR.

Model the Domain shaped the joined FlowNode and FlowTask model. Type System Discipline shaped the progress union and explicit task source variants. Test Behavior, Not Implementation shaped the literal model and rendered-behavior assertions. Prove It Works shaped the running-app checks, screenshots, and request census. These leaf skills were read during the session. Deslop and technical-writing guidance were applied to the final change and report.

Dispatch ledger. Implementation and verification stayed in-thread under the requested implementation-subagent role. The parent owns delegated design and independent review.

## Frontend file inventory

Changed and removed tracked files follow.

```text
M	frontend/src/NodeAssignments.css
D	frontend/src/NodeAssignments.tsx
M	frontend/src/NodeWorkItems.tsx
M	frontend/src/ProjectDetail.css
M	frontend/src/ProjectDetail.tsx
M	frontend/src/ProjectProgress.css
D	frontend/src/ProjectProgress.tsx
M	frontend/src/StartSopControls.tsx
M	frontend/src/useNodeAssignments.ts
M	frontend/test-node-assignments.mjs
M	frontend/test-node-evidence.mjs
M	frontend/test-start-sop.mjs
```

Added frontend files follow.

```text
frontend/qa/project-flow-vite.mjs
frontend/src/AssignmentTaskInspector.tsx
frontend/src/FlowActions.tsx
frontend/src/FlowDiagram.tsx
frontend/src/FlowEvidence.tsx
frontend/src/FlowSchedule.tsx
frontend/src/FlowSourceDetails.tsx
frontend/src/FlowTasks.tsx
frontend/src/NodeAssignmentForms.tsx
frontend/src/ProjectFlow.css
frontend/src/ProjectFlow.tsx
frontend/src/flowModel.ts
frontend/src/useFlowDetails.ts
frontend/test-project-flow-model.mjs
frontend/test-project-flow-ui.mjs
```

## Round 2

This frontend-only bug-fix round works directly in `/Users/vc/.t3/worktrees/YXMEEGLE/t3-9dacab7b`, branch `t3/project-detail-flow-restructure`, from `2085edc`. The commit changes only `frontend/` and `output/`. There is no push, deployment, backend change, or PR. The final response records the commit hash.

### Defects and regression evidence

Every behavioral fix has literal expectations. Component regressions mount the actual React components. `test-project-flow-round2.mjs` has 14 mounted checks, `test-project-flow-model.mjs` has 9 model tests, and `test-node-assignments.mjs` has 13 hook and cache tests. All pass. `round2/red-original-*.txt` records these regression suites against the original tracked source. `round2/red-shell.txt`, `round2/red-local-inspector.txt`, and `round2/red-overall-unknown.txt` record additional failing checks before their fixes. The original source was restored temporarily for the backtest and the fixed source was restored in a `finally` block. These backtests are separate from the final all-script census.

| Defect | Fix and test | Result |
| --- | --- | --- |
| 1 | `round2 local workflow stays available with assignments` mounts ProjectDetail with both sources. The collapsed `範本與本地流程` section contains the original add-task, node completion, batch-completion component and local TaskTable. Its node picker reaches each local node. Clicking a local task opens its existing inspector without an erroneous missing-Lark-task warning. | PASS |
| 2 | `round2 node state overrides task ratio and skipped nodes have no bar`, `round2 completed and skipped node mounted progress`, and `round2 overall stays unknown when a counted node has unknown progress`. Completed nodes display 100% with either 0/0 or 1/3 tasks. Skipped nodes display `略過` without a bar and are excluded from overall progress. Other nodes use their task ratio or unknown. Overall uses those same node values and stays unknown if a counted node is unknown, rather than inventing a zero. | PASS |
| 3 | `round2 keyboard replaces history and never scrolls the selected panel` mounts ProjectDetail inside the real AppShell. It asserts unchanged history length, no scrollIntoView call, no extra shell scrollTo call, and focus on the selected step. The scroll spy records calls; it does not suppress the scroll effect from running. Keyboard moves retain the current tab so the first move from the default route cannot trigger AppShell's tab-change scroll reset. The browser also wraps and calls the native scrollIntoView implementation. | PASS |
| 4 | `round2 one selected node for panel and local operations` deliberately makes local in-progress control differ from assignment current-node field. The panel, ProjectOperations heading, and opened local add-task dialog all use field. The assignment hook and selectedFlowNode now belong to ProjectDetail and are passed down. | PASS |
| 5 | `round2 browsing refreshes while an assignment edit input defers refresh` and `round2 sixty-second refresh runs while browsing and waits for an edit input` exercise visibility and the actual registered 60000ms callback. Browsing buttons allow refresh; focused assignment edit inputs defer it. The page-wide class guard is removed. | PASS |
| 6 | `round2 failed evidence retains node and offers retry in item sheet` and the existing work-item-sheet test in `test-node-evidence.mjs`. `查看此節點證據` retains `node=`, closes the item sheet, and the failed-source item sheet has `重試工程證據`. Following the link in the browser preserves field and exposes its retry block. | PASS |
| 7 | `round2 local flow list translates both pending and in-progress task statuses` mounts legacy FlowTasks and expects `尚未開始` and `進行中`. Local model rows use the shared STATUS labels. | PASS |
| 8 | `round2 dispatch independent of node writes` disables assignment writes and create-task authority while retaining dispatch access. The schedule dialog still opens with its verified parent obligation. Existing UI tests retain role restrictions and the unresolved-parent explanation. Node mutation controls retain their own disabled reasons. | PASS |
| 9 | `round2 forced detail replaces a pending read and keeps newest cached result` and `round2 assignment readback wins over an in-flight stale detail and avoids refetch`. The mounted row shows 林安娜 after the old detail read finishes. There is one initial list read, one deliberately pending detail read, and no redundant read after the successful mutation. Forced reads replace the pending cache request; obsolete success and failure handlers cannot change the newer cache. | PASS |
| 10 | `round2 source timestamp and honest manager fallback` expects `Lark 節點與任務` and `2026/10/18 08:00:00 (台北時間)` from a UTC input. The strip uses taipeiTime. | PASS |
| 11 | `round2 manager resolved from loaded users and absent source distinguished` resolves the manager when loaded active users match the node group. An unmatched group says `未能對應到本組主管`. Missing source departments are identified explicitly as missing departments, rather than claiming the source omitted its manager. | PASS |
| 12 | `round2 overview goes to page header` targets `project-page-top`. Browser measurements put the case heading at 195.20px on desktop and 179.20px on mobile with scrollY 0. Other alias targets are about 120px below the viewport top. All flow scroll targets, including secondary sections and the diagram, have a 120px scroll margin. | PASS |
| 13 | The two `round2 attention ...` tests exclude manager-wide complete permission and unowned not-started work, and include actual pending task assignment, approval, unassigned assignable work and owned not-started work. | PASS |
| 14 | `round2 background and file shortcut restored collapsed` asserts node description, collaborators, elapsed days and `開啟 作業資料與成果` inside the collapsed `節點說明與背景` section. The 母案 fact is already present in 案件資料 → 母子案 through FamilyPanel, so it is not duplicated. | PASS |
| 15 | Shared NODE_ASSIGNMENT_ORDER, PRODUCTION_NODE_KEYS, FINISHED_NODE_STATES and NODE_NAMES replace repeated flow vocabulary. STATUS and NODE_NAMES live in a pure module and remain re-exported by appCommon. FlowTasks imports the existing standalone AssignmentTaskInspector directly; ProjectDetail owns only the local inspector. This removes the FlowTasks → ProjectDetail → ProjectFlow → FlowTasks cycle. buildFlowModel uses named pure functions for state, task rows, sorting, quantity, node progress and overall progress. The complete model suite and TypeScript build pass. | PASS |

### Commands

All commands run in the worktree's `frontend/` directory. `round2/results.json` records each exact command and exit code. `round2/summary.json` verifies the failure set against the nine requested baseline names. Each command has a matching `.txt` log in `round2/`.

```sh
npm run build
npx tsc --noEmit -p tsconfig.json
node test-project-flow-model.mjs
node test-project-flow-ui.mjs
node test-project-flow-round2.mjs
node test-node-assignments.mjs
node test-node-evidence.mjs
node test-start-sop.mjs
node test-case-detail-view.mjs
node test-case-navigation.mjs
node test-dispatch-board.mjs
node test-dispatch-publish.mjs
node test-dispatch-publish-ui.mjs
node test-dispatch-round2.mjs
node test-contrast.mjs
for test in test-*.mjs; do node "$test"; done
```

Build and typecheck pass. The final census runs every one of the 99 test scripts once on the fixed source, with 90 passing and exactly nine baseline failures. Required scripts are included in that census. The failures remain `test-dev-tooling`, `test-home-panels`, `test-home-target-navigation`, `test-ops-sync-panel`, `test-plan-panel`, `test-reports-interactions`, `test-search-input`, `test-shell-mode`, and `test-ux-case-detail`. There are no additional failures. `git diff --check` passes.

### Real browser

Ran `node qa/project-flow-vite.mjs` on port 5208 and used the T3 collaborative browser against the actual App at 1280×900 and 390×844. The fixture server adds completed and skipped node cases and failed-source work items. No external Lark request or write occurs.

The keyboard run starts at scrollY 400 with history length 4. After ArrowRight, both numbers remain unchanged, the selected step retains focus, and native scrollIntoView has zero calls. `round2/browser-evidence.json` records this, the successful assignee readback, viewport measurements and stable alias positions after two animation frames. All measured scenarios have zero horizontal document overflow. Item evidence links preserve node and close their sheet. Actual fixture UI assignment and task creation succeed. Dispatch dialogs resolve and prefill the expected project, confirmation and parent obligation. Loading, legacy, unknown evidence, task filters and task inspector scenarios were rerun. Dispatch publish behavior is covered by the passing rendered integration test; this browser round opens and verifies its prefilled dialog.

All screenshots below are relative to `output/project-flow/round2/`.

- `alias-flow-1280.png`
- `alias-flow-390.png`
- `alias-overview-1280.png`
- `alias-overview-390.png`
- `alias-progress-1280.png`
- `alias-progress-390.png`
- `alias-tasks-1280.png`
- `alias-tasks-390.png`
- `assign-success-1280.png`
- `assign-success-390.png`
- `completed-node-progress-1280.png`
- `completed-node-progress-390.png`
- `create-task-1280.png`
- `create-task-390.png`
- `default-1280.png`
- `default-390.png`
- `evidence-failed-link-1280.png`
- `evidence-failed-link-390.png`
- `keyboard-navigation-1280.png`
- `legacy-1280.png`
- `legacy-390.png`
- `loading-1280.png`
- `loading-390.png`
- `local-workflow-1280.png`
- `local-workflow-390.png`
- `schedule-prefilled-1280.png`
- `schedule-prefilled-390.png`
- `task-filters-1280.png`
- `task-filters-390.png`
- `task-inspector-390.png`

### Decisions and deviations

Progress uses backend DONE precedence and keeps physical quantities separate. A counted node with unknown task progress makes the overall percentage unknown. This avoids treating unavailable task data as zero progress. Skipped nodes do not enter the denominator.

The already-loaded assignment roster exposes availability and assignable people, but no manager rank. The workspace users can resolve a group manager when their active manager role and department match. This round does not invent roster ranks or add a backend API. An unresolved match is labelled as an unresolved client-side match.

The task-inspector cycle was removed by using the assignment inspector's existing independent module directly, rather than moving the large local inspector and its comments into another module. The user-facing behavior remains covered by both inspector tests. The original local SOP workflow keeps its own authority and completion rules even when the Lark node has a different state.

Independent review and delegation remain with the parent coordinator. This implementation sub-agent launched no children and opened no PR. Browser tests use synthetic contract-shaped sources. Live Lark writes are not exercised.

Model the Domain shaped the single selected-node source and shared progress rules. Fix Root Causes led to correcting the AppShell tab trigger after browser evidence caught the first-key scroll reset. Test Behavior, Not Implementation led to literal mounted assertions for labels, history, focus, assignee and retries. Type System Discipline kept skipped and unknown progress explicit. Prove It Works led to native browser scroll measurements and screenshot inspection. Deslop and technical-writing guidance were applied to the diff and this report. The referenced leaf skills were read in this session.

Dispatch ledger. Implementation, tests and browser verification stayed in-thread under the requested implementation-subagent role. The parent owns independent review.
