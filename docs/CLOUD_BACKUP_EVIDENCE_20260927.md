# 正式舊版在線備份與本機還原驗證

最新備份於 **21:29:03（Asia/Taipei）** 完成：`.runtime/legacy-cloud-backup-20260927T132858Z-c41e80dd/`，16 工作區／1 回執／1 快取／1 附件，ZIP 249,673 bytes；SHA-256 `71695290c9eba4b9ac23c030c85d90216d656441e887ba7665a61adfc9735ed6`。已核對該目錄 `receipt.json`，逐列還原與附件雜湊比對皆通過，未停機、未修改正式 DB。下文較早時間保留作歷史紀錄；自動備份排程仍未啟用。

最新備份於 **17:03:19** 再次完成：`.runtime/legacy-cloud-backup-20260927T090311Z-c9603e1e/`，15 工作區／1 回執／1 快取／1 附件，ZIP 245,179 bytes；SHA-256 `152d6f587b3861dc770454f1c23507af79b6264e43943681d0957cac94af02fb`。逐列還原與附件雜湊比對皆通過，未停機或修改正式 DB。以下保留較早備份及遷移演練的完整紀錄。

完成時間：2026-09-27 16:08:24（Asia/Taipei）。本次獲授權僅備份與本機還原，不部署、不停機、不修改正式資料庫。

## 實際結果

| 項目 | 結果 |
| --- | --- |
| 來源 | Zeabur app service `6ab61834a4c05a5bcb57ad69`，environment `6ab6168036d2a6cac409f0c6` |
| 正式 DB 存取 | PostgreSQL 同一 `REPEATABLE READ`、`READ ONLY` 交易 |
| workspaces | 15 筆 |
| receipts | 1 筆 |
| source_caches | 1 筆 |
| 快照引用的 local 附件 | 1 個 |
| ZIP 大小 | 245,180 bytes |
| ZIP SHA-256 | `384e682374b94b30069c93c978f48841236a841db4ab2738243d35b4fa0edd2e` |
| 本機空白 SQLite 還原 | 成功；三表每筆完整內容與快照逐筆相等 |
| 還原附件 | 每個附件 SHA-256 與 manifest 相等 |
| 新版額外兩表 | business_records、company_people 各 0 筆，符合舊版 v1 還原轉換 |
| 登入 sessions | 不備份、不還原 |

完整 ZIP、還原資料庫、還原附件與 aggregate receipt 保存於工作區忽略的私有目錄：`.runtime/legacy-cloud-backup-20260927T080819Z-24207edc/`。其中 `receipt.json` 可供後續核對；不得把 ZIP、DB、附件、傳輸內容或業務資料提交原始碼／部署包。正式容器僅新增 `/tmp/yx-legacy-snapshot-20260927T080819Z-24207edc.zip` 備份檔，該處是暫存，不能代替已取回的本機副本。

## 一致性依據與實作

已唯讀檢視舊容器完整備份腳本、附件建立／刪改程式及程序列表。PID 1 是單一 uvicorn。舊附件在獨立 id 路徑以 `open('xb')` 完整写完並關閉檔案，才提交 workspace 引用；沒有一般附件覆寫或刪除 API，上傳例外 cleanup 會刪除該次 target。

新增獨立 `scripts/backup_live_legacy.py`，不改既有停寫備份工具。新工具只接受已稽核舊 schema，先取三表一致快照，再複製其中引用的 local 附件。驗證 id、size、路徑範圍、非 symlink、讀取前後 inode／size／mtime，缺檔或不符即失敗並移除本次不完整 ZIP；新上傳但不在快照中的孤兒檔不納入。正式 DB 交易明確設為唯讀，未使用 SIGSTOP 或服務維護模式。

執行的 source SHA-256：`d99be09f2a8fcf247874c678e0633cb02e74f4cd8a2dcce41399f309a13acd74`。

一次性傳輸腳本 `.runtime/run_legacy_cloud_backup.py` 將受審查程式壓縮後透過已授權 `zeabur service exec` 執行，捕獲傳輸資料到本機程序記憶體，驗證 ZIP 大小與 SHA-256 後保存檔案。沒有將 base64、業務列或 credentials 印到工具輸出。首次過長命令沒有取得有效回執；改用壓縮傳輸後成功，未接受第一次結果。

## 測試與限制

`python -B -m pytest backend/test_backup_live_legacy.py -q`：**9 passed**。包含快照引用附件與空白 DB 還原、排除進行中孤兒檔、缺檔／大小／路徑／symlink 拒絕、既有目標檔保護、新 schema 拒絕，以及 PostgreSQL 交易隔離與唯讀設定。

本次實測證明「正式 PostgreSQL 應用快照與引用附件已取回，並在本機空白 SQLite 使用新版還原工具成功還原」。不等同 PostgreSQL 全叢集、角色或設定備份，不等同已完成另一個雲端 PostgreSQL 的災難復原或 RPO／RTO 驗收。未部署新版程式，也未開啟每日備份排程。此在線方法只適用本次稽核的舊附件不可變規則，不能未經核對直接套用至未來版本。

## 部署前新版遷移演練

2026-09-27 16:12（Asia/Taipei），另拷還原 DB 與附件至 `.runtime/legacy-migration-rehearsal-f5e53ee5/`，以最新版 backend 啟動遷移。APP_ENV=development、DEMO_MODE=false，移除該程序 Lark 外部設定；未啟動 worker 或來源同步。原始 `restore.sqlite` 的前後 SHA-256 相同，原還原證據未變更。

| 項目 | 保留／重組結果 |
| --- | --- |
| workspaces | 15 |
| projects | 378（含 280 個有 source_identity 的來源案件） |
| nodes／tasks | 3,402／8,218 |
| daily_reports／events | 183／18 |
| files／comments | 1／1 |
| BusinessRows | 12,318 |
| PersonRows | 0，舊版沒有此表的人員資料；首次驗證身份時才建立 |

每個 `storage.load` 重組結果均與 `upgrade(原始 JSON)` 嚴格相等，因此原有來源欄位、人工欄位與歷史內容全數保留；migration_archive 完全等於原 JSON，workspace version 不變，source_caches／receipts 及附件 bytes 不變。重啟最新 backend 後再次核對一致且無重複資料，`/api/health` 回 200。演練 receipt 保存於上述目錄。這是資料結構遷移驗證，不是來源重新匯入完成的證據；原快照沒有 `manual_updated=true` 的任務，不能拿此實測取代人工修改衝突的專項測試。

正式 Lark 工作區 aggregate：1 個，包含 1 位 active manager；`source_connection` 欄位不存在，啟用數為 0。新版定時同步會跳過此狀態，部署後需先經合法同步建立來源連線狀態，不能僅憑 worker 啟動宣告已每五分鐘同步。紀錄未包含 tenant／person ID 或業務列。
