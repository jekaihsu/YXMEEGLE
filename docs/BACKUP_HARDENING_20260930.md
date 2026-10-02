# 備份與部署依賴補強（2026-09-30）

此文件更新 9/29 啟用手冊。程式與本機測試已改，尚未操作遠端環境、金鑰、volume 或備份。實際部署與公司災難復原驗收仍須另外完成。

## 審查項目處理

- #203：新增 `backup_reconcile.py --receipt PATH`，只讀完整 Drive 目錄與檔案 hash；`--apply-receipt` 只回填本機已核實 token。找不到已 attempted 的項目仍保持 unknown，不自動清除、重送或刪除；需要調查遠端請求結果，不能用不存在的一次讀取證明當初沒有成功。當天本機 archive 已完整驗證後，即使異地失敗仍執行本機 30 天／12 月清理，保留今天與近期副本。未知 bundle 不擅刪；容量不足則停止新增 snapshot 並記錄 error。
- #204：成功後同日只比對 snapshot 的大小及 mtime 與配置指紋；每分鐘僅更新 scheduler 心跳，不開 DB、不重 hash、不取得 token。日期／檔案／配置變動或滿 24 小時才完整驗證。遠端 verified 快取從 1 小時改 24 小時。失敗重試至少間隔 15 分鐘，配置變更可立即重試。心跳不更新遠端 verified_at，不冒充新備份成功。
- #205：整包遠端驗證成功後刪除本機加密片段及加密 manifest，保留 receipt。後續完整驗證只讀遠端，不需要重建加密 bytes。未知分塊保留核對；`BACKUP_MAX_LOCAL_BYTES`（預設 20 GiB）與 `BACKUP_MIN_FREE_BYTES`（預設 512 MiB）在新增 daily snapshot 前停止超限增長。單次 snapshot 仍可能超過估計空間，需依實際資料量設定餘裕並監控。
- #206：強制獨立 `BACKUP_LARK_APP_ID`、`BACKUP_LARK_APP_SECRET`、`BACKUP_LARK_ORGANIZATION`。缺任何值或 app ID 等於工作台 app 即拒絕，沒有 fallback。遠端刪除預設關閉；只有明確設定 `BACKUP_REMOTE_PRUNE_ENABLED=true` 才執行原先 receipt 限定清理。建議日常備份身分不授予刪除能力，清理使用分開的核定程序。**這仍不等於 object lock，也不能保證有刪除權限的獨立 app 遭入侵後副本不被刪。** 強制不可變需求仍需獨立 WORM/object-lock 儲存。
- #207：`backup_publish.py` 優先 hard link；不支援時 Windows 使用拒絕覆寫的原生 rename，Linux 使用 `renameat2(RENAME_NOREPLACE)`。不採有競態的 exists＋replace，也不把未寫完的 O_EXCL 檔案公開成正式備份。不支援兩者時 fail closed；須在實際掛載卷驗證。
- #171：新增 Linux Python 3.12 的 36 包完整 hash lock，Docker 改 `pip install --require-hashes`。解析命令用 uv，經核准網路執行；主機只有 Python 3.11，並無 Docker，因此**尚未驗證 Linux 3.12 image 安裝／整合測試**。鎖檔固定 FastAPI 0.142.0、SQLAlchemy 2.1.1、Starlette 1.7.0、cryptography 50.0.1 等實際解析版本，不能把舊本機環境測試冒充鎖版測試。

## 上線前新增條件

1. 新增独立 backup app、授予僅備份目的地的最小讀写權限、重新核實目的地 ACL。既有 app＋jekai 的 ACL 證據不代表新 app 已可存取。
2. 公司金鑰分離保管、私密 volume、全新空 PG 演練庫依原 runbook 執行。禁止將備份 key 放同一 Drive。
3. Docker 現以 UID/GID **10001:10001** 執行。新 image 的目錄 chown 不會覆蓋既有掛載卷 ownership；部署前必須核實 uploads 與 backups 實際掛載根及既有檔案可由 10001 存取。不要因權限失敗改回 root 冒充完成。
4. 白名單加入 `scripts/backup_publish.py`、`scripts/backup_reconcile.py`、`scripts/backup_offsite_acceptance.py`、`backend/requirements.lock`。與全部備份 scripts 一起部署，先跑獨立 staging。
5. 在相同 locked Linux image 執行測試、記錄 Python／套件版本、測試卷 atomic 發布、真實加密 Drive 往返與下載解密 PG 還原，再啟排程與觀察。

獨立 app 設定取代舊手冊「同專用工作台 app」的要求；其他六個 BACKUP 設定仍要完整 env map 合併。`RESTORE_DRILL_DATABASE_URL` 只注入單次演練。

沒有遠端刪除權限時，遠端 30 天／12 月 retention 尚未自動達成。需另外核定獨立 retention 作業或選定具生命週期＋不可變保護的儲存；不能將關閉 DELETE 稱為 retention 已完成。
