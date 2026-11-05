# Project detail UX redesign (PRD v1.0): current-state mapping, gaps, plan

Base commit: `5e33e40` on `feat/project-detail-ux-prd-v1` (= `c16ce48`, which staging served at 2026-10-30, plus one docs file). `c16ce48` is an ancestor of HEAD. `origin/main` is about 1300 commits behind and is not the base.
Spec: `YX_Project_Detail_UX_PRD_v1.0.pdf` (R01-R50, T01-T23). No `AGENTS.md` exists in this repo, so `README.md`, `docs/` and the existing test scripts were read instead.

## 1. Current state (what the code does today)

| Concern | Where | Today |
| --- | --- | --- |
| Route | `projectRoutes.ts`, `ProjectDetail.tsx` | Hash router `#view=project&project=ID&tab=&node=&task=&section=&task_filters=`. Tab `overview` (default) hosts the summary; `flow` hosts the full workspace. Old aliases (`tasks`, `progress`, `daily`, `logs`) map in `projectFlowRoute`. |
| Summary | `ProjectOverview.tsx` + `CaseNextStep.tsx` | "目前 SOP" card: first unfinished node, a reason sentence, one next action from `selectNextAction`. |
| Navigator | `FlowDiagram.tsx` | Chain built from the constant `NODE_ASSIGNMENT_ORDER` (nine keys). `parseNodeAssignments` drops unknown keys and re-sorts to that constant. |
| Selected node | `ProjectFlow.tsx` (`inline` mode inside overview) | Rendered only when the URL has `node`, `task` or `section=all-tasks`, and below a todo card and KPI cards. By default no node card is visible. |
| Task list | `FlowTasks.tsx`, overview "待辦事項" card | Two lists: a todo card (unfinished only) and the node list with a "此節點 / 全部任務" toggle and filters 我的 / 未指派 / 逾期. No collapsed other-stage groups. |
| Assignment | `FlowActions.tsx` `TaskPersonPicker` (inline form), `AssignmentTaskInspector` + `TaskDrawer` (editor drawer) | Inline select form; `update_task` PATCH with `expected_revision`. No dirty-draft guard, no conflict diff, no timeout recovery UI in the inline form. |
| Mutation core | `useNodeAssignments.ts`, `nodeAssignmentApi.ts` | One in-flight mutation lock, `request_id` reused on retry of the same mutation (backend resolves `outcome_unknown` by replaying the same `request_id`), `revision_conflict` reloads and shows a notice. |
| Capabilities | `AssignmentTask.can.{assign,edit_status,cancel,claim,edit_details}`, `NodeAssignmentList.can[nodeKey]`, `writes_enabled` | Server-computed per task and node. Reused unchanged. |
| Status dictionaries | `nodeAssignmentApi.ts` (`NODE_LABELS`, `TASK_STATUS_OPTIONS`), `workflowLabels.ts` (`STATUS`, local tasks) | Node labels map to 未開始/待處理/進行中/待審核/已完成/略過, unknown to 狀態待確認. Task statuses 待處理/進行中/已完成/取消; unknown to 狀態待確認. |
| Progress | `AssignmentNode.tasks {done,total}`, `progress` | Backend-computed, non-cancelled task counts. Used as the authority. |
| Current stage | `summary.current_node` | Single key, the first node in the chain that is neither done nor skipped (`domain.summarize`). |
| Page-open writes | `ProjectDetail.tsx`, `useStartSop`, `EnsureSopStatus` | Reads only (`GET first-screen`, `node-assignments`, `start-sop` preview). Verified again by test T01 below. |

## 2. Contract gaps (reported, not papered over)

1. **Fixed nine-node chain in the backend.** `backend/node_assignment/domain.py` `CHAIN` is the nine `NodeKey` values and the list/detail API always emits all nine. The UI can still be dynamic (R09/R50): it will render exactly the nodes and the order the server returns, keep unknown keys, and never use array position for permissions. Making the chain configurable is a backend change and is out of scope (R02).
2. **Single current stage.** The API gives one `current_node`. The view model keeps a set (`currentStageIds`) so a future multi-stage response renders without a rewrite; today the set has at most one element. PRD default (R21): first by workflow order, disclose the rest.
3. **No blocker or dependency field on Lark tasks.** `AssignmentTask` has no `blocked` status, blocker reason or dependency list. Local tasks expose `execution_blockers` / `activation_blockers` / `paused`. The UI shows the 受阻 flag only where such data exists and otherwise renders "阻礙資訊來源未提供", and the 受阻 filter says how many tasks have a known blocker. Lark tasks are never guessed as blocked. T15 is covered for the data that exists (local tasks).
4. **No approval configuration per node in the list.** Node `approver` is present only when set; the card shows 核准人 only then, and never adds an approval gate (R13, T18).
5. **No server-side "recommended action" and no cross-stage permission rule.** Next step is computed in the browser from the same snapshot, scoped to the current stage, from capabilities the server already returned. Cross-stage candidates are never produced because no explicit allow-rule exists (R36). T17 is UNTESTED end to end for the allow path (no data source), and is covered at unit level with an injected rule.
6. **No batch/atomicity statement for PATCH.** `update_task` writes assignee and deadline in one PATCH with one `expected_revision` and a read-back check (`readback_mismatch` returns the wrong fields). So partial success is reported field by field when the server names fields in `readback_mismatch`; otherwise the drawer re-reads and compares each field with the saved values (T23).
7. **Task-state revision fence at the API.** `expected_revision` is enforced server side (`revision_conflict` 409). Used as the concurrency control (R31).
8. **Case status vs. node/task status sources differ** (list `source_status` vs node derived status vs task status). They are labelled as three levels and never merged (R15). The 案件庫 list shows a different column and is not changed here; the level explanation text is shown on the detail page.

## 3. Decisions (PRD defaults unless noted)

| Decision | Choice |
| --- | --- |
| Where the redesign lives | The `overview` tab (default landing), with `flow` kept intact as the full workspace; links in both resolve to the same selected-node model. |
| Order of blocks | Title and status, tabs, case summary, navigator, selected node card, node tasks, other-stage groups (collapsed), then the existing KPI / items / activity / documents blocks. |
| Selection source | URL `node` / `task` if valid, otherwise first current stage, otherwise first node with a loud fallback notice. Selecting writes `node` into the URL with `replace` for keyboard moves and `push` for clicks. |
| Multi current stages | Set kept, first by workflow order is the default selection, the others are listed. |
| Progress | Server `tasks.done/total`; zero total shows "無適用任務", never 100%. Unknown denominators show "數據待確認". |
| Task filter set | 全部 / 待處理 / 未指派 / 受阻 / 我的, composable, AND, shown as applied chips, one-click clear. 待處理 means status 待處理 or 進行中 (not done, not cancelled) so it overlaps with 未指派 and 受阻 by design. `task_filters` URL param is extended compatibly (`pending`, `blocked` added; `overdue` kept). |
| Drawer | New `AssignDrawer` built on `TaskDrawer` (right overlay, full width under 640 px). Existing inline picker is removed from the list and the old inspector editor stays as the detail view. |
| Drafts | In memory only. |
| Fixtures | `frontend/fixtures/node-assignments.mjs` and `frontend/qa/project-flow-vite.mjs` (synthetic, no Lark). Staging data is never written. |

## 4. Minimal change plan (one focused commit each)

1. This document.
2. Server-ordered nodes: `parseNodeAssignments`, `buildFlowModel`, `selectedFlowNode`, `assignmentTarget` stop hard-coding the nine keys.
3. `stageModel.ts`: pure view model (labels, flags, filters, groups, node stats, stage-scoped next action) with tests T02-T06, T14-T18, T21 data rules.
4. UI: `CaseSummary`, `NodeCard`, unified list with filters and collapsed groups, deep-link expansion, back-to-current, request-generation guard (T19, T20).
5. `AssignDrawer` state machine with cancel / validation / success refresh / conflict / timeout / revoked capability (T07-T13, T23).
6. Responsive and a11y CSS, 1440 / 1024 / 768 / 390.
7. Real-browser verification, fixes, staging deploy.
