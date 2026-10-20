# SOP and flow copy cleanup

Branch t3/sop-copy-cleanup. Base 6ae352962cd008f8e589636b3ca1f456f2be5605. No push.

## Changes

8d1c136 shortens flow task, approval, source footer and next-action copy. It updates both rendered flow test files.

1787c18 removes evidence and readiness captions.

Changed source files are FlowTasks.tsx, ProjectDetail.tsx, ProjectFlow.tsx, FlowEvidence.tsx, FlowSourceDetails.tsx and ProjectReadiness.tsx. SopTasks.tsx, SopImportSheet.tsx, SopTaskInspector.tsx, Quotes.tsx and QuoteCreateSheet.tsx were inspected. Their existing labels, errors and control reasons needed no changes.

## Before and after

| Before | After |
| --- | --- |
| 本地流程任務與 Lark 任務分開，保留原節點完成及審批規則。 | 本地流程任務 |
| 任務來源暫不可用，請重試明細後再確認完整清單。 | 任務來源暫不可用 |
| ${filtered.length} 項已載入，來源未完整 | ${filtered.length} 項 |
| ${filtered.length} 項符合 | ${filtered.length} 項 |
| 沒有符合篩選條件的任務。 | 沒有符合的任務 |
| 尚無可見任務。新增具體工作後即可指派與追蹤。 | 尚無可見任務 |
| 找不到此 Lark 任務，可能已移除或不在可見範圍。 | 找不到此 Lark 任務 |
| 財務與節點跳過保留原核准流程。變更與展延尚未開放。 | 移除 |
| 。來源時間不等於工作台操作時間。 | 移除，保留同步時間及來源狀態 |
| 審批通過後，由負責人明確套用新版本或新期限。 | 移除 |
| 確認成果後核准或退回。 | 待審核 |
| 核對本節點證據，指派具體工作並確認交接。 | 待處理 |
| 先指派或認領節點負責人。 | 待認領 |
| 來源未提供負責組別，未能對應到本組主管 | 主管未設定 |
| 節點說明與背景 | 節點資訊 |
| localNode.guidance 或 localNode.description | 移除節點背景段落 |
| 依來源數量顯示，單位依各工項；不跨單位加總。 | 移除 |
| 來源已直接連結合約工項。 | 移除，保留原生關聯標籤及數量 |
| 以工編對應合約工項，尚非來源直接連結。 | 移除，保留依工編推導標籤及數量 |
| 找到多筆可能的合約工項，需人工確認。 | 移除，保留關聯待確認標籤及數量 |
| 尚無法對應合約工項。 | 移除，保留未關聯標籤及數量 |
| 無此類關聯 | 移除，保留零數量 |
| node.quantity.reason 或 來源尚無可確認的完成量 | 移除，保留實際完成量未知 |
| p.actual.unit_note | 移除，保留實際完成量未知 |
| 不代表尚未施工，也無法計算完成百分比。 | 移除 |
| 怎麼補 · 在 Lark 日報填「所屬案件」與「合約工項」後，下次來源同步會連起來。 | 移除 |
| 僅顯示 ${p.items.length}／${p.items_total} 筆，來源工項未全部列入此清單。 | ${p.items.length}／${p.items_total} 筆 |
| 來源未按內業生產節點拆分，下列週報不代表本節點獨立實績。 | 移除 |
| 週報為工作預排與工作單資料，與上方日報回報量分開呈現。 | 移除 |
| 週報僅列出各部門最近 6 個有活動的週次。 | 最近 6 週 |
| ⚠ v3 案件對應有歧義。以下案件全部列出，未選定或合併任何一筆。 | 案件對應待確認 |
| 怎麼補 · ${gapHint(g.id)} | 移除所有補資料教學，保留缺口狀態 |
| 目前未列出資料缺口。 | 無資料缺口 |
| 尚無已核實的確認單／合約工項關聯，請查看來源同步狀態。 | 尚無確認單／合約工項 |
| 來源唯讀。報價可連到多份工程確認單；跨組任務引用同一合約工項，金額不重複加總。 | 移除 |

Removed gapHint captions also covered these possible strings. The shared dictionary remains for other views.

- 請 PM／行政在 Lark 建立工程確認單並連結案件。
- 請 PM 核對確認單狀態與合約明細。
- 請確認填報工項表的來源同步權限。
- 請確認合約明細與工項表同步完整且權限涵蓋相關資料。
- 請核對來源完整工項，清單超過顯示上限。
- 在 Lark 工項填入對應的合約工項。
- 核對重複工編，指定唯一的合約工項關聯。
- 核對附掛報價，保留正確的案件關聯。
- 在 Lark 日報填「所屬案件」與「合約工項」後，下次來源同步會連起來。
- 核對各 v3 案件的案號／報價單號，修正重複對應後重新同步。
- 核對 v3 案號與此案工編或報價單號。
- 請在對應 v3 案件填寫工作預排或工作單。
- 報表快照正在建立，稍後重新讀取。
- 請管理員檢查報表來源連線後重試。
- 請有報表權限的 PM／主管查看，或向管理員申請權限。
- 請管理員確認報表功能設定。
- 請管理員檢查報表同步，更新後再核對。
- 請有財務權限的人員查看。
- 請在來源報價填寫請款、收款資料並等待同步。
- 請核對來源欄位與案件關聯，修正後等待下次同步。

## Verification

Build passed. All package test scripts were run. Relevant passing scripts include test:sop-tasks, test:quotes, test:project-progress and test:start-sop. test-project-flow-ui.mjs and test-project-flow-round2.mjs passed directly. Assertions check absent explanations and retained labels, counts and actions.

Every frontend test-*.mjs file was run individually. The first run exposed two obsolete assertions in test-project-flow-round2.mjs. Those were updated to require the new manager label and absent background prose while preserving collaborator, elapsed-time and file-action checks.

For baseline comparison, source and test edits were stashed. HEAD was verified as 6ae3529. npm run build was run on base before rerunning every failing test file. The stash was restored. base-results.json and base-*.log contain the results. All nine remaining failures also fail on base.

A browser fixture attempt did not reach the rendered flow page, so browser visual verification is not claimed. Rendered behavior was verified through the real React components in JSDOM.

Laziness Protocol shaped the change. Existing JSX labels were shortened or deleted without new logic, types or abstractions. No PR review was dispatched because this is a mechanical copy change and no PR was requested.

Final full-file run passed 93 of 102 files. These files failed on both final and base, each with exit code 1.

- test-dev-tooling.mjs
- test-home-panels.mjs
- test-home-target-navigation.mjs
- test-ops-sync-panel.mjs
- test-plan-panel.mjs
- test-reports-interactions.mjs
- test-search-input.mjs
- test-shell-mode.mjs
- test-ux-case-detail.mjs
