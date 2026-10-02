# SOP runtime 覆蓋檢查

本批完成的是執行時的唯讀覆蓋診斷，**不是 62 節點完整流程引擎已上線**。

## 已接入

- `backend/sop_runtime.py` 從正式封裝的 `sop_source_contracts.json` 載入 334662 / v137 的 62 節點、71 邊，呼叫現有 `Topology` 核對圖形並產生診斷。
- 既有 `project_summary` 回傳精簡 `sop_topology`，包含來源數、停用數、精確版本來源引用覆蓋、未引用數、適用條件未決數、無效引用數。全工作區回應不附完整 62 節點明細；函式明細模式可供單案後續 UI 使用。
- 相同名稱、不同模板或版本不混同。重複引用去重，不同本地任務保留。已封存舊版任務不作當前覆蓋證據。
- 本地任務完成與來源流程節點完成分開呈現；refs 只是來源關聯，不能證明完整流程狀態。來源執行仍回傳 `execution_mapping_pending` / `source_execution_verified=false`。
- 52／58 的考評停用及 45→75／76／77 的平行來源邊完整保留。沒有添加假回邊或串行關係。

## 不變的權限與資料

診斷不修改任務、負責人、成果、歷史、適用性決定、審批、結案或任何外部資料。沒有設定新的審批人或透過假案件開啟流程。既有完成的彙整任務不被拆成假造的來源完成紀錄。

## 驗證

`python -m pytest backend/test_sop_runtime.py backend/test_sop_topology.py backend/test_sop_contracts.py backend/test_sop_contract_integration.py backend/test_workflow_automation.py -q`

結果：**115 passed**。新增 8 項驗證涵蓋封裝來源、回應大小、歷史不改寫、完成不冒充、版本差異、跨模板隔離、條件 unknown、平行／停用以及實際 summary 路徑。

此檔記錄本機實作及測試；部署與正式環境驗收由主協調者另記。

## 仍待完成

來源全節點與工作台執行單位的版本化映射、條件決定入口與公司既有主管確認程序、正式分支與匯合 gate、確認單正式發出交接、新輪次範圍失效。`SOP_TOPOLOGY_NEXT_BATCH_20260929.md` 的六批不能因本診斷存在就宣告完成。
