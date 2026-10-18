# Project flow decisions

The data shape is FlowNode with separate task progress and production quantity. An unknown actual quantity stays null even when all tasks are done. Overall completion uses non-cancelled task counts when present, otherwise workflow node handoff counts, with its basis displayed.

The implementation stays in-thread under the requested implementation-subagent role. The parent owns delegation and independent review. No PR is being opened.

Throughput checkpoint. The merge removes the four competing tab bodies. Reusable production evidence, assignment forms, and the existing task inspector keep existing writes and node authority. The joined pure model and route-focus tests run first. Browser checks and the full frontend script census follow the implementation.

An alternative was to put new wrappers around each of the four existing bodies. Rejected because it retains duplicate requests, numbers, and task lists. A second alternative was to make progress data own all state. Rejected because source evidence does not grant SOP completion or write authority.

Runtime review found that CSS containment trapped fixed dialogs. Body portals corrected the schedule, assignment-task, SOP, report, and work-item sheets. Browser measurements verified viewport positioning. Regression checks also corrected stale recovered-detail errors and repeated detail reads after a manual refresh.


## Round 2 decisions

One selectedFlowNode result in ProjectDetail drives all flow sections and local operations. The assignment hook is shared by props instead of duplicated state.

Node completion overrides task counts. Skipped nodes have no bar and are excluded from overall progress. Unknown counted nodes keep the overall percentage unknown. Production quantity remains separate.

Keyboard selection replaces URL history and preserves the existing tab. Real browser verification found that changing the default tab to flow also triggered AppShell's scroll reset. Keeping the tab prevents that reset without changing shell behavior for other pages.

Local tasks retain their original inspector and authority inside a collapsed local-workflow section. Assignment tasks use their existing standalone inspector module directly. No new inspector abstraction is needed.

A successful mutation's readback owns the visible task row. Forced detail reads supersede pending reads. Obsolete reads cannot replace or clear the newer cache.

Group-manager fallback describes an unresolved match. The loaded assignment roster has no rank field. The page resolves active managers from matching workspace departments when possible and makes no new source claim.

母案 remains in the existing 案件資料 → 母子案 section. The background panel does not duplicate it.
