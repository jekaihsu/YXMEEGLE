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
