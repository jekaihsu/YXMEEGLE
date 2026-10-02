# SOP 來源契約增量實作（本地，尚未部署）

## 本批程式

- `backend/sop_source_contracts.json`：兩模板真實節點、角色、條件與交付定義；52 個子任務各有穩定 lineage identity 及含來源版本的 contract ID。可由 `scripts/build_sop_runtime_catalog.py` 重建。
- `backend/sop_contracts.py`：契約快照、52／58 停用標記、核定 D4／D5 定義、安全套用、條件判定及執行 gate。
- `policy.template` 新版 template ID `sop-contracts-20260929.1`；原 published workspace copies 不被重寫。保留 `partial_inventory`，不宣稱完整版條件引擎完成。
- `operations.sop_apply` 接安全 merge：先完整驗證，再保留原 node/task 物件更新；已完成節點、既有成果、人工 owner／assignment history、confirmations、revision 不變。新任務才繼承大節點負責人並記錄指派事件。
- `workflow_rules.execution_reasons` 同時支援手動開始／完成、批次完成及 scheduler，禁啟已停用考評／薪資工作與未知條件工作。
- `sources.project_nodes` 與正式 `v4_sources.nodes` 都已帶穩定鍵及來源契約元資料。新版候選未發布前，正式來源仍採公司的舊 published SOP。
- `policy.upgrade` 對既有 workspace 僅註冊一次新版 draft 候選並留 system event；不覆寫 published 範本、不移動案件版本。管理員明確 publish 後才供後續新案採用；既有案仍要走 SOP 套用申請，Meegle／pending 案不得套用。
- `operations.missing` 已接條件待核對 gate；未知條件不能利用同名任務、既有 stable key 或完成過的子任務略過。

## 啟用範圍

直接啟用 3 個已核定 PM 預設工作：業主聯繫紀錄與佐證、各組內業進度追蹤、下包需求及工作範圍確認。保留其來源 node key 與責任說明；工作負責人沿用大節點，可明確改派。

前兩項是 `single_occurrence_record`、非開工前必填。既有 recurring 管理每一輪；完成一次紀錄不代表永久完成週期，也不能把執行中的追蹤反過來當作 PM 派工前置條件。下包需求範圍確認為一次性必做工作。

6 個條件式下包定義（報價收件、四組出工、成果驗收）放在 `deferred_task_definitions`。既有產品尚未有核定適用性的入口，不能一律必填或因未知就當不適用。本批預設不啟用它們，避免製造使用者無法解除的完成阻擋。條件 helper 與測試可供下一批接入口使用。

52 個來源任務保留的是完整契約，**不是在每個案件複製 52 個必填任務**。來源 `required`、visibility、pass_mode 不會被一概當作 unconditional true；最新核定規則仍優先。

## 本地驗證

- 新增測試涵蓋：52 個穩定鍵、真實交付、條件未知／false／true、停止未知工作、只有指定組的下包任務建立、多人改派保留、已完成成果與版本歷史保留、正式 pending／Meegle 不允許改版、晚發現錯誤的原子性、已停用工作不產生或啟動、無入口的条件定義不製造新案卡關。
- 回歸：SOP／工作流自動化／案件分流／期限合計 107 通過；來源 projection／identity／entities 29 通過；operations 31 通過。最終新增來源契約與正式 V4 整合測試共 29 通過，包含 stable／legacy × completed／pending 的新條件防繞過。
- 獨立代理第二眼指出既有任務匹配分支會略過新 applicability；已修正為先解析新條件。未完成任務的契約 metadata 遷移記入 `sop_contract_history`，保留成果、負責人、狀態與 revision；completed 任務保持原內容，活動節點由 pending 條件 gate 阻止新版本錯誤完成。明確 false 只取消未完成工作之必做性，不偽造完成，並保留前後 metadata 記錄。
- 來源 refs 建構改為輕量投影，避免每次 workspace upgrade 深拷貝整份表單／條件树；原始契約內容仍完整保存且不执行其中字串。
- 最終穩定程式整批重跑：`test_sop_contract_integration`、`test_sop_contracts`、`test_source_projection`、`test_source_identity`、`test_source_entities`、`test_workflow_automation`、`test_operations`，**139 passed in 21.57s**。此為針對本批的回歸，不等同全 backend suite。

## 仍未宣稱完成的範圍

1. 未來開放 6 個 conditional defaults 時，仍需核定適用性入口。本批只具安全 helper 與完成 gate，沒有冒稱已建成核准入口。
2. 71 條來源連線的完整條件、並行、回圈執行等價仍是後續引擎工作。
3. 全公司切換基準仍須使用者核定；新發現來源案繼續 pending，不用 first-seen 時間猜新舊案。
4. 本批未部署；root 目前發布使用先前封存的 861 測試版本。本地測試不代表正式 Lark 送審／Drive／Input 全流程端到端驗收。

本文件狀態隨 root 接入與測試結果補記；不代表已部署或已實現全部 SOP 拓樸。
