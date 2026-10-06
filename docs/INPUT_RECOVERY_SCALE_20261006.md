# Input 未知結果恢復、提交鎖定與大量資料查回（#11）

自動化（合成資料，無實際 Lark／憑證／.env／正式資料）：

- `backend/test_input_recovery.py`、`backend/test_input_registration_worker.py`：403／422／429／5xx／逾時對應狀態；新增前一律先以識別碼查詢；未知只用唯讀查回；欄位與記錄分頁、分頁上限與重複 token、限流（Retry-After、5 次上限）、同 `client_token`／登錄識別防重。
- 未知結果的唯一「確認未建立」出口：`POST /api/input-revisions/{id}/dispose-not-created`。需明確確認、原因，且當次唯讀查詢完整分頁後確實查無；查得、讀取失敗或逾時一律不處置。只有成功處置才寫入稽核（`input_registration_disposed_not_created`）。
- `frontend/test-input-recovery.mjs`（`npm run test:input-recovery`）：實際 InputRegistration 元件於 5xx／網路逾時保持鎖定並沿用同一 request_id 與內容；403／422 解除鎖定並保留識別與內容；409 不換識別；成功後才換新識別。
- 本地回執保存失敗、或 POST 發出後的非遠端錯誤，改記為 `outcome_unknown`（可唯讀查回），不再變成不可查回的 `blocked`。

僅能在正式環境驗收（本次未執行、未宣稱通過）：

1. 正式 Input Base 的欄位 ID／型別與實際 Lark 回應形狀（含空表缺 `items`）與設定一致。
2. Lark 實際限流額度與 `Retry-After`；`client_token` 的實際去重行為與保留期間。
3. 大表（數千列以上）上 `records/search` 的篩選延遲、分頁一致性與寫後讀回延遲（處置前查無是否可能因索引延遲）。
4. 逾時／5xx 的真實發生率，以及處置「確認未建立」的人工核對 SOP 與稽核檢視。
5. 正式目的地端到端登錄驗收須另行記錄。
