# FLOW fix round 1

Implemented F1–F8 on `t3/case-simplify-fix-flow`. No task-sheet implementation or data/people/items tab region was edited. No push.

- Flow overflow uses DetailsMenu, a 44px marker-free trigger, secondary menu actions, close-on-select, empty-menu suppression, and inline permission/completion reasons. Existing write guards and mutation recovery remain.
- Next-step execution blocks have explicit cause kinds (pause, Meegle, ownership, execution restriction, source verification); titles no longer infer cause from prose. Common pending-task blockers appear once; unique reasons stay under their task. Overview pause/execution reasons are not repeated in the task list.
- Removed selected-node heading/state duplication, duplicate node facts, redundant stepper context, zero approval bar, and duplicate delivery heading. Retained delivery controls, accessible section label, actual approver and legacy completion evidence. SOP tools are setup-gated and closed by default.
- Sidebar lists executors under one label. Linked task filters remain active and visible on short lists.
- Removed unused FlowTasks props, expanded-stage state, HelpTip/help data, obsolete TaskPersonPicker and CSS, unused blockerSummary and stageNextStep userId argument, shell onPeople prop, and unused ProjectDetail imports. Executor and default-checklist helpers still have callers and remain.

Validation passed:

- `npx tsc -b`
- `npm run build` (existing large-chunk warning only)
- `npm run test:project-flow`: model, UI and round2 tests; round2 now has 22 checks, including overflow role reasons, close-on-select, empty-menu suppression, and blocker deduplication.
- `npm run test:stage-model`: complete wired suite, including updated stage-workspace assertions.
- `node test-stage-model.mjs`: 24 tests, including five execution-block causes and shared/unique blocker cases.
- `node test-stage-workspace.mjs`
- `node test-work-nonempty.mjs`: assigned/delegated/local save and reload paths.
- `node test-task-sheet.mjs`: 9 checks.
- `node test-ux-case-detail.mjs`: 10 tests.
- `node test-task-list-context.mjs`
- `git diff --check`

The three formerly orphaned tests now have package scripts (`test:project-flow`, `test:work-nonempty`). Tests now open lazy menus/editors, use the actual assignee picker, exercise filter thresholds/deep links, and retain dispatch, source-failure, assignment readback, mutation payload and route coverage. The UI suite's progress request count now reflects retained cached evidence after dispatch publication.

Intentionally retired subtests: opening overview's removed work-item preview table, overview empty-document/item-preview cards, and the removed KPI strip. Replaced their surrounding overview assertions with summary/task-list/loading/error checks. Removed-node background/facts, source timestamps, template accordion and metadata-prefix assertions were converted to absence assertions; canonical item navigation remains covered from flow evidence. Stage-workspace now asserts the accessible stage label and the single overview pause reason rather than removed panels. No task-sheet behavior tests were dropped.

Browser: production Vite build served from this worktree at port 5411 with /api proxied to localhost:8000. Shared Chrome preview checked p1/p3/p5/p6/p7 × overview/flow × 1280×800 and 390×844 (20 states), plus opened overflow and a short-list `task_filters=mine` deep link. All checked pages had no document horizontal overflow; flow had one delivery heading and one primary, 44×44px overflow with list-style none; p3 blocker appeared once. Menu items were secondary; mine filtering remained visible with zero matching tasks. No write actions clicked.

Screenshots and browser results: `/Users/vc/Local/review-artifacts/cd-simplify/fix1-flow/` (p3 overview/flow at both widths, mobile overflow and mine deep link). Browser validation used the shared preview tools required by this runtime.

Limits: live demo API returned only `in_progress` and `engineering_complete`, with zero `closed` cases. No `closed` mapping was invented. Paused/completed and non-demo execution causes were verified using fixtures. No F1–F8 work skipped; SHEET-owned items remain outside this branch.
