# 2026-09-27 UI 整合補齊

依本對話核定決策及實際後端契約補齊以下入口，未執行任何正式外部寫入。

- 案件合併待核對提示、衝突明細、案件主管／管理員的 `migration_review {reason}`。另列財務重新提案及雙方核准阻擋，主管核對不表示財務通過。
- 正式工作區交接管理者可讀取或更新請假審批來源；畫面顯示實際狀態、期間及核實時間。一般人員只顯示本人涉及的來源紀錄。
- 教育訓練分別顯示訓練紀錄與正式能力的遠端儲存狀態及錯誤。補上訓練成果退回原因、紀錄儲存重試及原能力認定者重試入口。
- 能力地圖分頁增加正式訓練資料表映射設定；逐欄填實際名稱，由後端驗證十種欄位契約。僅正式工作區的來源管理者可操作。
- 背景工作列表補上訓練紀錄與正式能力儲存名稱。

契約：`POST /api/delegations/verify-approval` 使用 `version, instance_code`；`POST /api/learning/mappings/verify` 使用 `version, mapping`；`learning_retry` 使用 `id, target: record|capability`；`training_return` 使用 `id, reason`。

驗證：`npm.cmd run build` 通過 TypeScript 與 Vite。尚未由本次補齊工作執行瀏覽器互動或正式 Lark 驗收；完整整合驗證及 Apple Design 獨立覆核由主代理安排。
