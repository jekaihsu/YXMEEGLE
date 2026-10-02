# Drive 真實端到端最小驗收方案（待執行）

本文件是程式檢視後的準備方案，沒有上傳任何文件。正式 root 已由主代理透過正常設定接入，但不能把設定成功當成檔案驗收。

## 建議路徑：隔離工作區＋專用測試 Drive

使用既有 `test-lark-<organization>` 工作區與其中的测试案件；不將測試檔案加入正式案件。檔案測試不需要設定測試 Base，`connection_policy(..., kind='file')` 分支只檢查測試 Drive。

前置條件：

1. 建立／核實不同於正式 root 的專用測試資料夾，例如「詠翔專案工作台整合驗收」。建議放在應用根目錄下作為正式成果目錄的平行目錄。
2. 伺服器 `LARK_TEST_DRIVE_ROOT` 與測試工作區 `settings.test_drive_root` 完全一致，且不等於任何正式 root。
3. 測試工作區設定 `test_connection_mode=isolated_live`、`external_enabled=true`；worker 必須是專用 application 身分且 organization 相符。這些設定由主代理正常管理流程處理，本代理未變更。
4. 確認目標工作區與目標測試案件，保存前置快照中的案件版本、節點／任務狀態、交付證據及既有檔案 ID。

## 正常工作台路徑

1. 建立唯一檔名 `WORKBENCH_DRIVE_ACCEPTANCE_<UTC時間>.txt`；UTF-8 內容明確標示「連線驗收測試文件，不是工程成果／交付佐證」，附唯一測試識別。保存預期 bytes、size、SHA-256。
2. 透過已登入的工作台 POST `/api/files` multipart：指定測試案件、`node_id=''`、`direction=input`、`category_id=other`、`file_key=''`，帶目前 `version` 及案件 `project_version`。不要更新任何既有 file_key。
3. 回傳工作區找出唯一新 file ID，確認未綁節點、分類／用途／檔名正確。GET `/api/files/{id}/download`，比對下載 bytes 的 SHA-256 與預期值。
4. 取得最新工作區版本，POST `/api/files/{id}/store-lark`，僅首次排隊，不重複送出。等待正常 worker 處理。
5. 輪詢原 file／job，預期 `remote_status=verified`、job succeeded、`simulated=false`、`remote_mode=isolated_live`、receipt.destination_root 等於核實測試 root。queued、blocked、unknown、simulated 均不算通過。
6. 以同專用應用透過官方 Drive `/drive/v1/files/{receipt.file_token}/download` 再下載一次，獨立比對 SHA-256 及 size；不能只看 URL／metadata／verified 字樣。
7. 驗證工作台新檔案、檔案保存 job 與稽核紀錄存在；原節點狀態、任务成果、交付證據沒有改變。檔案與回執保留為验收紀錄，不刪除遠端文件、不補作正式成果。

失敗或結果未知時停止重送，保存 request／file／job ID 和錯誤類型，由既有工作回執查證；不得另建立第二個同名測試檔來掩蓋問題。

## 正式工作區未綁節點文件是否可行

技術上可行：`upload` 允許 `node_id=''`，管理員或案件 PM 可操作；未被交付證據引用的檔案不進入節點 review_hash。但仍需 `project_id`，會新增正式案件檔案、稽核與案件版本，並在正式成果根目錄下產生案件／Input 路徑。因此不符合本輪「不代入真實案件文件」限制，不採用此路徑。

程式依據：`backend/app.py` upload/download、`backend/integration_routes.py` store-lark、`backend/remote_policy.py` isolated_live、`backend/jobs.py` file worker。這是待執行方案，不宣稱真實上傳已通過。
