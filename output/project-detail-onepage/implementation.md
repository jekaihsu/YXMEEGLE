# Project detail one-page workbench

Implemented in `t3/project-detail-workbench` from `173fa7e`.
No push or deployment. No real Lark writes.

## Behavior

The overview stepper opens the node workbench inline and keeps `tab=overview`.
Task rows open the same visible editor for Lark, local SOP and legacy tasks.
The editor supports the fields each source authorizes. Existing date and evidence restrictions remain enforced.
Node assignment, complete, approve, reject and legacy direct completion are visible actions with disabled reasons.
Old flow, task, node and task-source deep links remain supported.
The other project tabs remain available.

Unstarted cases show a primary 啟動 SOP action. Formal cases use the native SOP preview. Intake cases use local default import. The existing preview and apply sheets import per-case defaults.
Managers can edit titles, executors, dates and applicability, add tasks, and archive tasks from the workbench.
Report summary opens report-link review inline. Existing work-item and source destinations remain linked.

## Model and design

`nodeWorkbenchModel.ts` owns `NodeWorkbench`, node facts, source adapters and the action registry.
`WorkbenchTask` is a union of `lark`, `local-sop` and `legacy`, retaining each original task and revision.
Each registered action has `visible`, `enabled` and `disabledReason`, derived from server permissions.
Transient read and write activity is distinct from ordinary-write policy blocks. An allowed legacy completion stays available.
`InlineTaskEditor` renders a field permission table. Existing source inspectors retain their mutations, conflicts and task transitions.

A single large replacement inspector would duplicate transition and evidence logic. Shared editor fields with existing source controllers preserve those rules.
Model the Domain selected the task union and registry. Sequence Work into Verifiable Units selected the model, backend, integration and cleanup commit order.
Architecture and implementation ran in-thread because this task explicitly assigned one implementation owner.

## Cases without a confirmation

Intake and blank-code cases use local SOP task data and canonical local node actions.
`POST /api/projects/{id}/sop-nodes/{node_key}` supports assign, complete and reject.
The route uses existing SOP case-management authority, the task-write flag, current authorization under a workspace lock and node revisions.
It saves canonical node changes through existing storage and workflow audit functions, plus action audit rows.
Completion requires all linked applicable work to be done, applicability resolved and required legacy tasks finished.
Financial completion remains unavailable through this path. Lark-managed cases cannot use it.

Private local-planning cases can open a minimal detail through their authorized SOP response when the ordinary detail is unavailable.
Assigned-only readers cannot obtain a whole-case projection through this fallback. Unknown case facts remain unknown.
Official case lists, totals and the original detail authorization remain unchanged.

## Verification

- TypeScript typecheck passed.
- Vite production build passed into `tmp/onepage/final-dist`, outside `frontend/dist`.
- All 13 requested and new frontend test files passed. New model and editor tests cover 10 cases.
- The whole frontend suite has 117 files. 104 passed and 13 failed. All failures also fail at the base commit.
- `test-sop-tasks.mjs` now passes 20 tests. `test-ux-case-detail.mjs` now passes 10 tests, fixing its five stale failures.
- The focused backend matrix has 411 passed, one failed and one skipped. The base has 406 passed, the same failure and the same skip.
- The five added backend tests passed. The unchanged failure expects field status 進行中 but receives 待處理 in the evidence-overlay SOP-start fixture.

`verification.json` lists every remaining frontend failure and all required test files.
`base-backend.txt` and `final-backend.txt` preserve the unchanged backend failure.
`changed-files.txt` lists the code and test files.

## Real browser evidence

The real Vite app used isolated SQLite and the demo API on ports 5827 and 8827.
The formal-case node service used `httpx.MockTransport(FakeBitable)`. All other Lark reads were denied.

Passed the overview stepper, local owner assignment, manual task edits and completion, local node completion, import of 38 SOP defaults, per-case default edits, applicability, archive and inline report-link review.
Passed formal node assignment, task creation and all editor fields, complete, approve, reject with reason and explicit legacy direct completion.
Passed legacy task editing, initial date and notes. A workspace conflict preserved the draft, and reload then save persisted it.
Passed private local-planning detail and keyboard Escape. Layout scroll width matched 1440 and 390 CSS pixels.

Screenshots are `local-overview-1440.png`, `remote-overview-1440.png`, `local-editor-390.png` and `local-start-390.png`.
The primary local start button was visible at 48 CSS pixels from the top after opening the workbench at mobile width.
Native snapshots may downsample large images. Their CSS viewport sizes were measured in the page.

Could not run remote SOP start because the synthetic formal case has no planned quantities.
Could not validate genuine external source and work-item destinations because the synthetic case lacks those links.
Local SOP start, report review, task deep links and the existing report/work-item route tests passed.
Template-level SOP catalog authoring remains outside scope. These changes edit per-case task snapshots.
