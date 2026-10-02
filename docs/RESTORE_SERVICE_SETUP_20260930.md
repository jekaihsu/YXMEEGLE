# 獨立 PostgreSQL 還原驗收服務準備（2026-09-30）

工具：`scripts/workbench_restore_setup.py inspect|prepare`。本次僅準備及本地 mock 測試，未執行任何雲端建立。

- 固定 project `6ab61680a4c05a5bcb57ace9`、environment `6ab6168036d2a6cac409f0c6`、service `yongxiang-workbench-restore-drill`。
- 建立前查 exact name；拒絕正式／staging ID、重名及無本地建立回執的既有服務。exclusive marker 在 mutation 前落盤；未知結果不可重建。
- 新獨立 PG database `workbench_restore_drill`，隨機憑證只存 ignored `.runtime/cloud-restore/secrets.json`；不複用正式／staging PG。
- 僅 postgres:17-alpine、私網 TCP、獨立 data volume。禁止 public forwarding，不裝 app/worker。工具不執行 restore、不宣稱 PG 已空或還原已成功。
- manifest/create API 證據：既有 `scripts/workbench_cloud_setup.py` 與 `.runtime/zeabur-inputs.json`。createPrebuiltService 是 project 級 API，沒有臆造 environmentID mutation 參數；建立後以固定 ENV 查 status。未改其它服务配置。

## 私網還原途徑（CLI help 已確認，遠端尚未執行）

本地 `zeabur service exec --help` 確認：

`zeabur service exec --id <服務ID> --env-id <環境ID> -- <command> [args...]`

可以在既有 staging app 容器 `6abc0821454b8f31a5ef614a` 另外啟動還原子進程，透過新 PG 的 dnsName 私網位址連線，且不修改 staging app 的持久 DATABASE_URL、不重啟或停止服務。子進程執行已有 `scripts/restore_drill.py`；其目標檢核強制 PostgreSQL、與 production 不同 database 名稱，restore 本身確認目標空白。

執行前仍須核實：新 PG 已啟動、staging 容器含最新腳本與 psycopg、/tmp 可用空間、備份下載方式，以及子進程如何安全取得私有 DSN／解密金鑰。CLI help 沒有承諾 stdin 檔案傳送；不可把密鑰直接塞進可見命令參數、輸出、app 全域變數。可採後續受保護檔案傳送或專用 one-shot runner，但目前未驗證其 API，不能寫作完成。

公開連線：本地 schema 尚未證實 TLS endpoint／安全 tunnel，故工具輸出 restore_ready=false 與 connection_blocker。不要使用未核實 TLS 的公開 Postgres forwarding。

驗證：`python -m pytest backend/test_workbench_restore_setup.py -q`，10 passed。測試不連外。
