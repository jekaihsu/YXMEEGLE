# Project detail: one 流程 workspace instead of four overlapping tabs

Owner direction 2026-10-18: 案件概覽 / 工程進度 / 流程與交付 / 任務 show near-duplicate data. Combine them, draw the SOP diagram with progress and per-section progress, link each node and task to its detail, and let the PM assign jobs or attach existing tasks to people right in the project view.

## What the code shows today (ProjectDetail.tsx, ProjectProgress.tsx, NodeAssignments.tsx)

- 案件概覽: NextAction + the nine-stage progress strip (ProgressOverview, same data as 工程進度) + top-4 待處理任務 (same rows as 任務) + local flow completion % + facts + readiness + activity + data links.
- 工程進度: nine-stage chain (joinProgressStages already merges SOP node rows with source evidence) + production cards (計畫/實際/週報) + identity + finance + data gaps.
- 流程與交付: NodeAssignments (node list with inline people and tasks, x/y counts) + the legacy node section and TaskTable.
- 任務: NodeAssignments with tasksOnly, i.e. all tasks of all nodes flat.

The same three facts (stage state, task list, progress) are rendered three or four times with different chrome.

## Judgment

Agree, and go further than merging by name. One tab is the case's working surface; the other three become views inside it, not tabs.

New tab set (5 instead of 8): **流程** (default, absorbs 概覽, 工程進度, 流程與交付, 任務) | 日報 | 案件資料 | 檔案 | 紀錄. Old routes (`tab=overview|progress|flow|tasks`) keep working as aliases that open 流程 with the matching focus, because home cards, reports, notifications and shared links use them.

## 流程 layout (top to bottom, each block has one job)

1. **Header strip.** Case code/name, PM, due date, amount (existing facts, once), source freshness. One line of 「下一步」 (existing NextAction) and 「需要我處理」 chips.
2. **SOP diagram.** The nine nodes in order 業務, PM, 確認單, 外業, 控制, 圖資, 報告, 計價, 結算, as a horizontal chain (390px: vertical stepper). Each node shows: state (未開始/待處理/進行中/待審核/已完成/略過), owner avatar, tasks done/total (non-cancelled), a progress ring or bar, deadline and a warning mark when overdue. A node with source evidence (外業/控制/圖資/報告) shows planned vs done quantity under the same bar, with unit, and 「來源未連結」 when the daily-report link is missing (0/187 and 0/348 in real data today). Never invent a percentage: unknown shows as unknown. Overall case progress is the one number at the left of the diagram, computed from the same node rows and labelled with its basis.
3. **Selected node panel** (click a node, keyboard arrows move between nodes, URL carries `node=`): node facts, responsible group and manager, the node's evidence block (what 工程進度 shows today for that node: planned items, actual, 週報 rows, gaps and how to fix them), and its task list.
4. **Task list** (the 任務 tab becomes this): rows with title, person, status, deadline, source. Toggle 「此節點 / 全部任務」 and filters (我的, 未指派, 逾期). Clicking a row opens the existing TaskInspector.
5. **Assign inline** (see below).
6. **Secondary, collapsed by default:** 審批與歷史, 資料缺口, 連結與身分, 財務, 案件討論, 案件活動. They keep their content but stop competing with the diagram.

No block may repeat another block's data: stage state and counts come from one joined model (`joinProgressStages` extended), tasks from one list.

## Assign in the project view

- Per node and per task, an 「指派」/「改派」 control for users the existing node authority allows (node manager or above, PM of the case; reuse node_assignment rules, do not add new permissions).
- **Attach an existing task to a person**: on any unassigned or mis-assigned task row, a person picker (roster, group-filtered, employed only) that updates 負責人 through the existing node-assignment task edit path (deadline optional). Shows pending and error states inline.
- **Create a task** under the selected node with title, content, person, deadline (existing add-task path).
- **Schedule work** (people + time + instruments + vehicles) for execution nodes opens the dispatch assignment dialog (DispatchPublishDialog) prefilled with project_ref, case, department (the node's group) and parent obligation, only when `features.dispatch_write` and role pm/manager. It uses the same preview/approval/publish flow; after publish the new V4 task appears in this list. When dispatch is off, only the simple assign controls show.
- Every control states why it is disabled (existing DisabledActionReasons pattern).

## Data honesty and loading

- Skeleton with final geometry for diagram, panel and list. Each source loads independently: the diagram renders from node rows first, evidence fills in; a failing source degrades only its block with a retry.
- Reuse the existing caches/prefetch (prefetchNodeAssignments, useProjectProgress); one request per source per case, shared by all blocks.
- Real data caveat to show plainly: of 16 real cases none has linked daily reports, so actual units are unknown; the diagram shows 「實際完成量來源未連結」 with the existing gap explanation, not 0%.

## Out of scope

Changing node status rules, approval rules, Lark schemas, the dispatch backend, 日報/案件資料/檔案/紀錄 tabs.
