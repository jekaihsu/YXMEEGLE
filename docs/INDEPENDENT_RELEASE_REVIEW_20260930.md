# 獨立交付覆核：Drive 恢復與 HTTP 請求界線

日期：2026-09-30。覆核代理：independent_release_review。對象是公司專案工作台，不是儀器借用系統。

## 結論與範圍

本輪限定範圍的 75 項測試通過。Drive 遠端寫入後若本地回執保存失敗，不會當成普通失敗自動重送；原上傳回執已保存時，後續恢復只驗證原檔。這是本地程式與模擬介面的證據，不代表新版已部署或真實 Lark 全線驗收完成。

覆核檔案：`backend/jobs.py` 的 Drive 分支、`backend/request_limits.py`，以及相應 worker、隔離連線、HTTP、上傳驗證測試。本代理僅補強 `backend/test_independent_input_worker_review.py`，沒有修改其他代理負責的來源、流程、審批或前端檔案。

## 檢查結果

- 建立資料夾或上傳檔案前標記遠端嘗試；遠端成功、回執 checkpoint 失敗時，工作變成 `outcome_unknown`。網路逾時造成回應遺失，也維持未知結果，不判定可以重建或重傳。
- 各層資料夾回執保存 parent、name、destination_root、remote_mode；再次使用前核對目的地，避免跨環境繼續上傳。
- 已保存 upload receipt 後，讀回失敗或最終本地完成 checkpoint 失敗，工作標示 `retry_only=verify_file`。重試使用原 file_token 與 sha256；即使原本地檔案不見，也不觸發第二次上傳。
- 每個遠端步驟前重查權限與環境。未知結果工作的下一次 worker 執行不會再次呼叫原資料夾建立／上傳。
- HTTP middleware 不依賴 Content-Type 判斷一般 API 的大小限制，因此省略或偽裝為 text/plain 不能繞過限制。multipart 整體大小在解析器之前限制；上傳路由本身仍驗證單檔大小、檔名及雜湊。
- 若持續資料庫故障連錯誤 checkpoint 都不能寫入，本輪程式沒有宣稱已保存失敗狀態；原 running lease 過期後的既有保守恢復仍須使用未知結果處理。此種真實基礎設施中斷不在本輪故障注入的證明範圍。

## 可重現測試證據

```powershell
python -m pytest backend/test_independent_input_worker_review.py backend/test_worker_reliability.py backend/test_isolated_live.py backend/test_http_request_limits.py backend/test_upload_policy.py -q --tb=short
```

第一次覆核：73 passed in 17.71s。

加入「建立資料夾回應遺失」與「上傳回應遺失」兩項反例，並確認未知結果下一輪不重送後：**75 passed in 16.14s**。

六種 Drive 故障注入包括：資料夾成功後 checkpoint 失敗、上傳成功後 checkpoint 失敗、資料夾回應遺失、上傳回應遺失、讀回失敗、最終完成 checkpoint 失敗。既有 upload receipt 的兩項恢復案例均確認只上傳一次。

## 仍須取得的外部驗收證據

本輪未呼叫真實 Lark 寫入 API，也未部署。以下不可用上述單測代替：

1. 將凍結的同一版本部署到隔離服務，驗證映像、環境隔離、持久化附件目錄及服務重啟後資料保留。
2. 真實 Lark 測試目錄完成上傳、下載雜湊核對、保存回執；故障後依回執查回，未知結果由受控核實程序解除，不能直接新建檔案。
3. 真實同事 OAuth、名冊身分關聯，以及 PM／主管或行政本人依規則完成原生審批。此項仍由主代理彙整結果。
4. 獨立備份憑證、公司持有的加密金鑰、異地備份與隔離還原，以及正式切換前同版本 24 小時觀測。
5. 全後端／前端／部署包整合驗收由主代理另行記錄；此報告只保證上述 75 項限定測試，不宣稱整個專案已完成。
