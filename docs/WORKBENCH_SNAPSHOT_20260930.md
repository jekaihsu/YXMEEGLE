# 正式工作台唯讀快照工具

## 原 attempt 的受控 helper 修復

主線首次 capture 因正式容器兩個備份模組與本機已審查版本不同而停止；真實診斷確認原遠端 attempt 目錄、archive、metadata 全不存在，UPLOAD_DIR 存在且無 symlink，資料庫為 PostgreSQL。原 attempt marker 保留。

新增命令（由主線執行，開發 Agent 未外呼）：

```powershell
python scripts/workbench_snapshot.py diagnose
python scripts/workbench_snapshot.py repair-preflight
python scripts/workbench_snapshot.py repair-reviewed-helper
```

新版 diagnose 保存對應原 ID 的 diagnostic.json。preflight 完全離線，檢查一小時內且三項遠端資源皆不存在的診斷，核對本機三份 helper SHA 仍與原 marker 相同，列出完整命令字元長度；32,000 字元以上不執行。

repair 使用同個 ID、新增獨立 repair-attempt.json，傳送僅含公開程式碼的壓縮 bundle。遠端再次檢查原目錄／檔案不存在，exclusive mkdir；將三份程式與空 scripts/__init__.py 存入該目錄 reviewed-helpers，不修改 /app。Python 必須尚未載入 scripts package；將私有 helper 放 sys.path 第一位，import 後再次核對三模組 __file__ 都位於私有目錄。之後執行相同現代備份流程、同 archive 路徑。

修復發生未知結果後不可再送 repair；只能 recover 同一 archive。9 項本機測試通過，包含實際隔離套件 import、舊 attempt 不變、二次 repair 拒絕及資料未通過驗證不發布。

`scripts/workbench_snapshot.py` 固定服務 `6ab61834a4c05a5bcb57ad69` 與環境 `6ab6168036d2a6cac409f0c6`，不接受任意服務、DB URL、遠端指令或輸出路徑。本次只寫工具及本機測試，尚未執行外部命令。

```powershell
python scripts/workbench_snapshot.py capture
python scripts/workbench_snapshot.py status
python scripts/workbench_snapshot.py recover
```

首次 capture 在任何外部請求前獨占建立 `.runtime/workbench-snapshot/attempt.json` 並 fsync。遠端使用獨占 `/tmp/yx-workbench-snapshot-<固定attempt ID>`，執行正式容器既有 `scripts.backup_restore.backup()`；不是 legacy backup。先比對備份本體、檔案讀取 helper、exclusive publish 三份程式 SHA，部署版本不同即停止。

資料庫僅 PostgreSQL，備份實作用 REPEATABLE READ＋READ ONLY 交易取得六張表。附件以該資料庫快照的引用為準；讀取時核對大小、inode、mtime，排除未提交檔案，ZIP 逐項 SHA 驗證與獨占發布。本工具另檢查 UPLOAD_DIR 不含 symlink，並以資料庫附件既有 sha256 核對 ZIP 內容。舊附件若尚無 DB sha256，只能證明讀取競態與 archive checksum 核對，會列入 `legacy_file_references_without_hash`，不冒稱全部具備 DB hash 證據。

線上讀取成立的前提是工作台正常上傳採不可變 file ID；不支援在快照期間由外部工具原地修改舊附件。`backup_restore.py` 開頭仍有舊版「暫停寫入」文字，實作已採上述快照與引用讀取；若需要比此更強的檔案系統一致性保證，應採儲存快照或維護窗口，不能只改文字宣稱通過。

建立與取回為兩次固定 service exec。遠端 base64 只由 subprocess 捕獲，從不回印 stdout/stderr 或保存 raw logs；本機核對 bytes／SHA／archive manifest 後才獨占保存私有 `snapshot.zip` 及 `receipt.json`。單檔上限 128 MiB，超過停止，不能截斷當成功。回執含 archive_path、sha256、source_service_id、observed_at、table/file aggregate。

未知結果、逾時或重啟後只可 recover 同個遠端 zip；不重新建立或換 ID。若遠端沒有完整 snapshot.json／zip，recover 停止待查。不要刪 attempt.json 來重試。既有 receipt 的 status/recover 只驗證本機相同 archive；不外連、不重送。

驗證：5 項合成測試通過，包含完整私有落檔、未知後不重建、錯誤傳輸不發布、固定唯讀備份路徑與 stdout/stderr 不外洩。尚未證明真實服務備份、遠端檔案取回或空 PostgreSQL 還原成功；由主線審查工具後執行。
