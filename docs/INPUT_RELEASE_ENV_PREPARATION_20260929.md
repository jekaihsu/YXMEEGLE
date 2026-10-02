# Input／Drive 完整環境設定待套用

2026-09-29 06:53 UTC 唯讀查詢 Zeabur 最新環境；19 個 unique keys（另有 1 個值相同的重複 entry）。完整保留原 key 與所有未知設定值後，準備為 29 keys：加入正式 Input 三項、隔離測試 Input 三項、Attendance contact 解析、兩個 Drive root、原生審批新提單保持 false。

`validate_environment` 與 `validate_request` 通過。未加入 BACKUP_DIR、未開備份、未執行環境 mutation、未部署。

私密檔：`.runtime/input-release-full-env-request.json`；摘要與 fresh snapshot 指紋：`.runtime/input-release-env-preparation.json`。工具 `scripts/prepare_input_release_env.py` 只產生完整替換請求，不送出。

**等待 companyadmin 精確環境片段再合併，當前 29-key 檔不是最終核定套用版本。** root 與身份 agent 已同步；加入片段時要重新讀最新環境，避免覆蓋其間的設定更新。842 backend tests 是 companyadmin 更新前的程式快照，不應當作新管理員功能已驗收。

## 最終準備更新（07:16 UTC）

再次 fresh read 成功，仍為 19 個原始 keys。加入 B 提供的私密 company-admin-env-fragment，現在完整 30 keys；保留所有未知原值，validate_request 通過。請求 SHA256：24cd4bdb1c8d28b282d95ce2ef4adffb32789ffe0247d3800c2d6c7d86745e14。仍未 apply，沒有備份啟用或 BACKUP_DIR。

已和 B 對齊並核對 jobs.state 重算 company admin authority、jobs.authorize 傳 cfg、env example 空 grant 欄均已存，沒有重複覆寫。B 回報 worker／Input／mention／native／admin 相關 92 tests 與 companyadmin18 tests 通過；本代理未重複執行同一組檢查。
