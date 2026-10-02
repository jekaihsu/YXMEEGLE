# 正式部署準備與備份驗收（2026-09-28）

本文件依 `APPROVED_PRODUCTION_PLAN_20260928.md` 核定決策及目前程式審查，優先於舊 `DEPLOYMENT.md` 的過時敘述。此次 deployment review agent **沒有部署、沒有改遠端設定、沒有連線寫入 PostgreSQL**。本機測試通過不等於正式可用。

## 已核實及已修正

- `run_service.py` 啟動 web，等 DB health 通過再啟 worker；子程序死亡會停止整組並讓平台重啟。設定 `BACKUP_DIR` 時也啟備份程序。應維持單實例，不額外啟第二套 worker。
- `run_worker.py` 分別處理原生審批、名冊、Attendance、來源同步及持久 jobs；`source_caches` 的 `runtime:worker` 留有狀態／最後成功。單一外部來源失敗不直接略過其他種類工作。
- 新版可攜備份格式 `/3` 包含 workspaces、receipts、source_caches、business_records、company_people、action_audit，以及這份資料快照引用的本機附件。來源引擎為 PostgreSQL 時以 REPEATABLE READ／READ ONLY 一致快照取得資料。登入 session 不還原。
- 備份只包含已提交附件，不收孤兒／寫到一半檔案。先寫唯一 `.partial-*`、fsync、校驗再以 exclusive hard link 公布正式 ZIP；既有備份不能被覆蓋，失敗不留下看似成功的最終檔案。
- 修正部署打包缺少 `scripts/backup_live_legacy.py`：新版 `backup_restore.py` 依賴其中的安全附件讀取函式，之前 staging 白名單漏檔會使雲端備份 ImportError。
- 修正 restore 空資料庫檢查：不僅檢查業務表，也拒絕含登入 session 或其他非空表的目標。仍要求目標 web／worker 停止，不能用此檢查取代停寫。
- 排程現在也校驗已有月備份；損壞檔案改名保留調查並重建。`status.json.last_success_at` 保持真正快照時間，另以 `last_checked_at` 表示本次校驗；不再每分鐘把舊備份冒充新備份。
- 新增 `scripts/restore_drill.py`，只連獨立命名的空白 PostgreSQL 演練庫；還原後重新匯出，逐列 canonical JSON 比較及逐附件 SHA-256 比對。明確拒絕正式同名資料庫（含 DNS alias）、postgres/template 預設庫及 SQLite；不建立／刪除任何資料庫或雲端服務。

本次驗證：`python -B -m pytest backend/test_backup_safety.py backend/test_runtime.py -q` → **18 passed in 4.10s**。涵蓋失敗不發布半成品、不可覆蓋、排除未提交附件、audit／附件還原、僅含 session 目標拒絕、月備份修復、備份真實年齡、PG 演練目標防呆，以及 runtime／staging 既有測試。這些是本機測試，尚未執行真正 PostgreSQL 還原。

### 管理員維護狀態 API

新增獨立模組 `backend/runtime_health.py`，由主協調者以 `register(app, identity, sessions, CacheRow, cfg)` 註冊 `GET /api/admin/runtime-health`。只允許相符公司正式 Lark 工作區、有效 manager；demo、測試工作區、不同 tenant 及 member 均拒絕。只讀 worker cache 與備份 status，不額外載入整個工作區。

回應包含真正 UTC 成功時間／年齡及 missing、not_configured、stale、degraded 等狀態；worker 心跳超過 5 分鐘或完整成功超過 15 分鐘、備份快照超過 36 小時或校驗超過 15 分鐘即顯示過期。門檻是維護偵測設定，不是承諾的 RPO。缺少時區、未來時間、損壞或過大的 status 檔不能冒充成功。

API 不回傳路徑、檔名、原始錯誤、凭證或工作內容，使用 `Cache-Control: no-store`。`scope=runtime_only`，並明示本次沒有驗外部整合或 ZIP 本體；排程留下的成功訊號不能代替獨立還原演練。專項 `python -B -m pytest backend/test_runtime_health.py -q` → **14 passed in 0.90s**；正式註冊及雲端回應另由部署驗收確認。

## 尚未取得正式證據的必要條件

### 最新部署前完整備份（2026-09-28 台灣 22:49）

使用雲端已部署 `scripts/backup_restore.py`，以 PostgreSQL REPEATABLE READ／READ ONLY 取得格式 `/3` 六表與引用附件：workspaces 26、receipts 1、source_caches 2、business_records 18,864、company_people 64、action_audit 15，附件 1 個。ZIP 1,140,368 bytes，SHA-256 `285d13e1cb1d5f20d88f14f9c594df89c210068f98c7d487b4c405b7035fe0cf`。

傳輸雜湊、ZIP 每項雜湊、隔離本機 SQLite 還原後逐列及逐附件比對全部相同；雲端與本機備份腳本雜湊相符。正式資料庫未修改、服務未暫停、不還原登入 session。私密回執：`.runtime/current-cloud-backup-20260928T144917Z-8b70c171/receipt.json`。這是部署前完整備份與 SQLite 還原證據，**尚非 PostgreSQL 災難還原驗收**。

| 項目 | 必須取得的證據／目前界線 |
| --- | --- |
| 新版本上線 | Zeabur 新部署 ID、RUNNING、asset 清單一致、後端版本與環境；舊 2026-09-25 回執不能沿用成新版成功 |
| 正式設定 | APP_ENV=production、DEMO_MODE=false、ALLOW_CLOUD_DEMO=false、固定強 SESSION_SECRET、正確 HTTPS origin／callback、名冊 bootstrap 管理員及 application tenant |
| 外部能力 | 真實 OAuth、動態名冊、九表同步、Drive 上傳讀回、四類專用原生審批及回執、正常班表；缺一不能靠 mock 宣告完成 |
| 備份儲存 | 獨立受保護持久目的地，容量／權限／加密／異地保存可驗證；單純設 BACKUP_DIR 或放同一容器不可算災難備份 |
| PostgreSQL 還原 | 獨立空白 PG 庫及空附件目錄，執行下述演練；現有本機 SQLite 還原回執不足以替代 |
| 排程與警示 | 檢查真實 backup 快照時間及 worker 最後成功；失敗目前寫結構化 stdout，尚缺實際有人會收到的失敗／超齡告警驗收 |
| 財務／權限 | 不同人 PM＋行政／PM＋主管、離職停權、測試正式隔離、財務來源與 SOP 完成分離、薪水 Base 全域禁止 mutation |

`prepare_release_settings.py` 現在準備完整環境 map：驗證已保存設定完整，保留原值，再合併九表清單與 application 身分／tenant 三項變更；沒有自動完成其他生產設定。Zeabur 的 `updateEnvironmentVariable` 會完整替換，禁止只送差異（見 `ENVIRONMENT_REPLACEMENT_INCIDENT_20260928.md`）。不可直接執行 `deploy_prepare.py settings` 當作正式遷移：其歷史用途是初次 preview 設定，應核對並保留現有密鑰／資源配置。

## 可執行的部署步驟（由主協調者執行）

1. 凍結這次 release 的程式、記錄測試與資產雜湊，完成原生串接及角色驗收。不得從整個工作區直接上傳，`.runtime` 可能含私密憑證及正式備份。
2. 以當前服務 schema 適用的腳本取得部署前 DB＋附件備份、驗證校驗值。新版 `backup_restore.py` 支援舊三表輸入；`backup_live_legacy.py` 則僅適用已核實舊 schema。確認可回復資料與舊部署 ID，保存現有設定於私密位置。
3. 完成下節 PostgreSQL 還原演練。完成獨立備份目的地配置，正式部署前核對 BACKUP_DIR 確為持久／受保護掛載，不是暫存容器目錄。
4. 在根目錄執行 `python scripts/deploy_prepare.py staging`，取得白名單 staging_directory。檢查 manifest 包含 backup_restore、backup_live_legacy、backup_schedule、run_service、run_worker；不含憑證、DB、附件。
5. 主協調者確認正式環境設定後，從該 staging_directory 執行以下已以本機 CLI `--help` 核對的命令：

```powershell
zeabur.cmd deploy --project-id 6ab61680a4c05a5bcb57ace9 --environment-id 6ab6168036d2a6cac409f0c6 --service-id 6ab61834a4c05a5bcb57ad69 --interactive=false
```

6. 取得新部署 ID 與 RUNNING，核對 `/api/health`、實際 assets、真實登入資格、名冊／來源最後成功、審批與 Drive 的實際回執、worker heartbeat、備份快照時間。重啟後再查保存結果。驗收時不得把正式同事訊息或財務核准當測試假資料送出。
7. 寫新部署回執，明確區分本機驗證、隔離 live 測試、正式驗收，以及尚待設定項。

`scripts/deploy_verify.py before/after` 是舊 demo 持久化測試，會假定 p1 並建立留言／附件；正式 DEMO_MODE=false 後不能拿它當完整驗收，也不要為了讓它通過重新開 demo。`assets` 可作資產核對；`config` 只驗 OAuth redirect，不能代替完成登入。

## 無破壞 PostgreSQL 還原演練

選擇同一 PostgreSQL instance 上**不同名稱**的空白演練 DB，或隔離 PostgreSQL 服務；只有已獲權限的主協調者建立資源。不要共用正式 schema，不開正式 DB 外網連接埠。不同 DB 使用現有私網連線即可，不必導出 DB 密碼到桌面。

在能接通該私网 PG 的受控主機，預先以私密環境配置兩個 URL：`DATABASE_URL` 為正式來源識別（腳本只做安全比較，不連此 URL），`RESTORE_DRILL_DATABASE_URL` 為獨立空白演練 DB。演練 uploads 也使用新空目錄，不能掛正式 `/data/uploads`。

```text
python scripts/restore_drill.py --file /private-backups/pre-release.zip --uploads /private-drill/uploads --receipt /private-drill/restore-receipt.json
```

腳本不印連線字串，回執只含表筆數、附件數、來源 ZIP 雜湊及是否逐列／逐檔一致。目標非空即中止；失敗時不自動刪庫，保留隔離目標供調查。若要重新演練，使用另一空白 DB／目錄。人工清理只能針對核實的演練資源，不能套用模糊名稱刪除。

通過後還須用同版應用在**無外部寫入能力**的隔離設定檢查遷移與資料可讀；不得把帶正式 tenant 的還原 DB 直接接 production worker，避免重送真實外部工作。此應用級測試與 DB bytes 還原是不同證據。

## 回復與維護界線

- 新版啟動會遷移資料；單純將 image 退回舊版不保證舊程式可讀新 schema。失敗應先停止寫入／worker，保留故障狀態，再還原部署前備份到獨立空白 DB／附件位置，核對後切換舊版設定。不要用備份覆蓋正在運行的 DB。
- 可攜備份不是 PG 全叢集／角色／設定備份，也不包含外部 Lark Base／Drive 檔案本體；外部附件索引可恢復，但遠端資料須另依 Lark 的保存策略保護。
- 常態備份依賴本機附件的不可變性；若未來加入原地覆寫或刪除附件，必須同步改備份保留策略／停寫或 snapshot 機制，不能沿用目前線上快照假設。
- `/api/health` 的 DB 成功只代表服務基本可用。worker degraded、備份過期、來源不同步需分別告警；現有程式的 heartbeat／status 是可觀測資料，不代表已有人接收告警。
- 30 日／12 月保留按排程執行，不等於已驗證的 RPO／RTO。以完整 PG＋附件演練耗時及真實排程結果建立可承諾數值。
