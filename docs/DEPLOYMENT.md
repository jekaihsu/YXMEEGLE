# 部署、Lark 設定與備份還原

更新日期：2026-09-29。依根目錄 Dockerfile、scripts/run_service.py、scripts/run_worker.py 與目前後端實作撰寫。**9 月 29 日新增功能的上線狀態以 [執行紀錄](EXECUTION_TRACKER_20260929.md) 為準**；本機 build／測試及 Lark 應用發布，不代表工作台服務已更新。

已核實報價總表 2 張、V4 7 張指定來源表的完整讀取，共 2,569 筆，並觀察到連續背景同步；案件歸戶與新案接管仍須實際驗收。四張原生審批定義已建立並讀回 ACTIVE，但尚不能視為真實送審、雙人核准及回存已通過。人員名單已讀取；正常班表仍待同應用員工 ID 權限與排班查詢驗收。Drive 根目錄可讀不代表上傳完成。所有整合分別記錄證據，不由 API 200 類推全系統完成。

## 1. 模式與隔離

| 模式 | 設定 | 身分與資料 |
| --- | --- | --- |
| 本地示範 | APP_ENV=development、DEMO_MODE=true | SQLite 可用；每個新示範 Cookie 建立獨立工作區，角色切換留在同一工作區 |
| 雲端 preview | APP_ENV=production、DEMO_MODE=true、ALLOW_CLOUD_DEMO=true | 必須 PostgreSQL 及強 session 密鑰；僅操作示範工作區，模擬確認明示為示範 |
| 正式工作區 | APP_ENV=production、DEMO_MODE=false | Lark OAuth、tenant 白名單及伺服器角色；同 tenant 共用工作區，初始為空 |

互動式來源讀取、公司資料及既有原生審批查詢需要有效 Lark session；背景來源同步另支援明確綁定公司 tenant 的 application 身分，不能任意跨公司執行。DEMO_MODE 不賦予示範角色讀取來源的權限。若 preview 同時提供 Lark 登入，登入後進入獨立公司工作區，不把示範案件混入。正式變更／展延尚無可用的原生提單及可信案件綁定驗收，不靠模擬核准繼續正式流程。

Lark 公司登入後另有 test／production 工作區。測試區預設 `test_connection_mode=simulation`；`isolated_live` 僅開放 Input 及文件對專用 Base／Drive 做真實測試，詳見第 4 節。示範 Cookie 工作區始終模擬，不能藉切換設定取得真實連線。

preview 建議使用獨立 Zeabur service、PostgreSQL、附件 volume 與 SESSION_SECRET。公開示範服務不放真實資料；展示資料不得被誤認為公司正式紀錄。

## 2. 本地啟動

在專案根目錄，以 Python 3.12 相容環境安裝後端套件，Node.js 22 編譯前端：

```powershell
python -m pip install -r backend/requirements.txt
Set-Location frontend
npm.cmd ci
npm.cmd run build
Set-Location ..
.\scripts\start_local.ps1 -Port 8000
```

入口為 `http://127.0.0.1:8000`。腳本設定 development、demo；沒有 DATABASE_URL 時使用 `sqlite:///./data/prototype.db`，沒有 UPLOAD_DIR 時使用 `./data/uploads`。後端會建立必要資料目錄及表；不會因重啟覆蓋既有工作區。

`start_local.ps1` 只啟動 web。要驗證背景工作，另在相同 DATABASE_URL、UPLOAD_DIR、密鑰及連線設定下啟動 `python scripts/run_worker.py`；單次檢查使用 `python scripts/run_worker.py --once`。需要同時管理 web／worker 生命週期時，先設定完整環境與 PORT，再使用 `python scripts/run_service.py`。

啟動腳本若未取得 SESSION_SECRET，會生成本次使用的密鑰。要驗證同一瀏覽器工作區的重啟持久性，必須先設定固定 SESSION_SECRET 再啟動，或從保存的工作區資料驗證，不把新 Cookie 建立的新示範工作區誤認為資料遺失。

需本地驗證 Lark 工作區時，不用強制 demo 的啟動腳本；先設定以下各項環境變數及 `DEMO_MODE=false`，再直接執行：

```powershell
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

回呼網址仍須符合 Lark 應用後台允許的精確網址。若後台不接受本地回呼，使用已設定的 HTTPS 測試網域；不能以開發 Cookie 假裝通過 OAuth。

`.env.example` 不會被程式自動載入。PowerShell 使用 `$env:變數名稱 = '值'`；容器及 Zeabur 使用各自的環境設定。密鑰不可寫入前端變數、瀏覽器、原始碼或 README。

## 3. Zeabur 容器

1. 以此專案根目錄為 Docker build context，使用根 Dockerfile。不要以 `frontend` 或 `backend` 子目錄作 context，否則多階段 COPY 路徑不完整。
2. 在同一專案提供 PostgreSQL，將連線字串設為應用的 DATABASE_URL。程式接受 `postgresql://`、`postgres://` 或 `postgresql+psycopg://`，內部使用 psycopg；production 拒絕 SQLite。
3. 為附件掛載持久 volume 到 `/data/uploads`，並確認 PostgreSQL 自身資料也持久化。兩者是不同儲存範圍，不能只備份其中一個。
4. 設定下表環境變數，容器以 `${PORT:-8080}` 對外監聽。健康檢查為 `/api/health`，會實際查詢資料庫；健康不等同 OAuth、來源及備份均已驗收。
5. 配置 Zeabur 預設 HTTPS 網域，前後端在同一網域交付。取得實際網域後更新 PUBLIC_ORIGIN、LARK_REDIRECT_URI 及 Lark 後台回呼白名單。
6. Docker 預設入口為 `python scripts/run_service.py`：先啟動 web，待 `/api/health` 的 DB 檢查成功後啟動持久 worker；任一子程序意外結束時，監督程序停止另一程序並以失敗碼退出，交平台重啟整組。不要在同一服務另外再啟動第二個 worker。
7. 先驗證啟動、頁面、角色和持久化，再做正式 Lark 登入、來源與工作排程驗收。維持單實例部署；未宣告多副本或高可用已完成。

| 變數 | 正式值或規則 |
| --- | --- |
| APP_ENV | production |
| DEMO_MODE | false；只有 preview 明確改 true |
| ALLOW_CLOUD_DEMO | 正式為 false；preview 同時設 true 才允許雲端 demo |
| DATABASE_URL | Zeabur PostgreSQL 私有連線設定，勿在日誌輸出 |
| SESSION_SECRET | 隨機且至少 32 字元，部署與重啟保持一致 |
| UPLOAD_DIR | /data/uploads，對應持久 volume |
| PORT | 8080 或平台指定埠 |
| PUBLIC_ORIGIN | 實際 HTTPS 網域的 origin，不含路徑及尾斜線 |
| LARK_APP_ID | 公司授權的應用 ID |
| LARK_APP_SECRET | 應用密鑰，僅後端可用 |
| LARK_REDIRECT_URI | 實際 origin＋/api/auth/lark/callback，與後台白名單完全一致 |
| LARK_ALLOWED_TENANTS | 允許的 tenant_key，以逗號分隔、避免多餘空白 |
| LARK_ROLE_MAP_JSON | open_id 對 pm／manager／member 的 JSON；未列入者預設 member |
| LARK_OAUTH_SCOPES | 使用者登入要求的 scopes，以空白分隔；範例為 bitable:app:readonly approval:approval:readonly。與 application scopes、Base 資源角色分開查核；發布新 app 版本不代表舊 user token 自動取得新權限 |
| LARK_SOURCE_TABLES_JSON | 必須填完整 9 張來源表 JSON，參照 deployment/source-tables.json；單純將檔案放進 image 不會自動載入，範例值 [] 不可作正式設定 |
| LARK_SOURCE_MAX_PAGES | 預設 50，每頁 200；來源上限限制為 1 至 100 頁 |
| LARK_WORKER_IDENTITY | 需要公司背景真實連線時設 application；不能以本機 CLI 憑證替代 |
| LARK_WORKER_ORGANIZATION | 精確的公司 tenant_key；背景程序只服務相符公司工作區 |
| LARK_LIVE_READ_ENABLED | 預設 false；僅字串 true（不分大小寫）開啟按需即時讀取（需 LARK_WORKER_IDENTITY=application）。關閉時 worker 沿用舊的 300 秒計時。回滾＝改回 false 並重啟 |
| LARK_LIVE_READ_SOURCE_TTL_SECONDS／LARK_LIVE_READ_ROSTER_TTL_SECONDS | 來源／名冊軟 TTL；預設旗標開 60、旗標關 300；下限 30，無上限。旗標關閉時同時是舊 worker 的最短間隔 |
| LARK_LIVE_READ_ATTENDANCE_TTL_SECONDS | 班表軟 TTL；預設 300；下限 60 |
| LARK_LIVE_READ_MAX_RPS | 每進程 Lark 請求速率；預設 5；範圍 0.01–10 |
| LARK_LIVE_READ_BLOCKING_TIMEOUT_SECONDS | 准入與手動等待的最長秒數；預設 10；下限 0.01 |
| LARK_LIVE_READ_LEASE_SECONDS | 刷新租約秒數；預設 120；下限 60 |
| LARK_BITABLE_RECORDS_API | list（預設，每頁 200）或 search（每頁 500）；其他值退回 list。須先於 staging 驗證再切換 |
| LARK_TEST_BASE_TOKEN | 選用，隔離真實 Input 測試專用 Base，須與測試工作區 test_base 一致且不得為正式來源 Base |
| LARK_INPUT_BASE_TOKEN | 正式 Input 專用登錄 Base，须与工作區 settings.input_base 相同；不得為 V4、報價或薪資 Base |
| LARK_INPUT_TABLE_ID | 正式 Input 專用登錄表，须与工作區 settings.input_table 相同；缺少或不符時阻擋查證與寫入 |
| LARK_TEST_DRIVE_ROOT | 選用，隔離真實文件測試專用根目錄，須與 test_drive_root 一致且不同於正式根目錄 |
| BACKUP_DIR | 備份排程使用的獨立受保護持久儲存位置，不能置於 UPLOAD_DIR 內；設定後 run_service 啟動 backup 子程序，仍須驗證排程及異地副本 |
| LARK_INPUT_REGISTRATION_FIELDS_JSON | 九項 Input 登錄語意欄位對應的 field_id／field_name，見 backend/input_registration.py 的 FIELD_NAMES；專用表不得沿用來源表 |
| LARK_ATTENDANCE_IDENTITY_RESOLUTION | 權限驗證後才設 contact；依同一應用 open_id 查 user_id，不能以姓名推測 |
| LARK_NATIVE_APPROVAL_MAPPINGS_JSON | 四種原生審批的定義、表單欄位、節點及席次；設定不等於實測通過 |
| LARK_NATIVE_APPROVAL_SUBMIT_ENABLED | 預設 false；真實角色驗收期間受控開啟，且 DEMO_MODE 必須 false 才能首次送審。關閉後仍允許查回已送出的未知結果與申請人撤回 |
| BACKUP_OFFSITE_ENABLED | 私密備份目錄與密鑰就緒後設 true；未設定時僅為本地備份，不算異地備份完成 |
| BACKUP_DRIVE_ROOT_TOKEN／BACKUP_DRIVE_ALLOWED_ROOT | 必須相等的專用私密 Drive 根目錄，不能使用一般文件或測試根目錄 |
| BACKUP_DRIVE_PRIVATE_ROOT_VERIFIED | 真正查核根目錄權限後才設 true |
| BACKUP_ENCRYPTION_KEYS_JSON | Fernet 密鑰陣列，新密鑰在前；僅設於後端密鑰儲存，由公司另外保管復原副本，切勿填進文件或 Git |
| LARK_CHANGE_APPROVAL_CODE | 選用，限制讀取的設計變更審批定義 |
| LARK_EXTENSION_APPROVAL_CODE | 選用，限制讀取的期限調整審批定義 |

容器內前端位置為 `/app/frontend/dist`，由 FastAPI 提供。Dockerfile 中預設 APP_ENV=production、DEMO_MODE=false、UPLOAD_DIR=/data/uploads。不需要另外啟動 Vite 開發伺服器。

## 4. Lark 實際設定及限制

OAuth 使用瀏覽器綁定 state 與一次性 nonce；tenant 與 open_id 取自 Lark 使用者資訊。手動來源同步使用目前登入者 access token，不讀取本機 lark-cli 憑證。登入失效後需重新登入，目前未實作 user token refresh。

來源清單以 `deployment/source-tables.json` 為準，共 9 張：

| Base | 資料表 | kind | table_id |
| --- | --- | --- | --- |
| 報價總表 | 報價總表 | quote | tblENZvYAya93Twa |
| 報價總表 | 工程確認單 | quote_confirmation | tblvV4X1kNVQisVj |
| V4 | 工程確認單 | confirmation | tblmSQrcCs9vPQZx |
| V4 | 合約明細工項 | contract | tblobs4qPy2w9MZ6 |
| V4 | 合約填報工項 | reporting | tblwQPYk3c9RvCU7 |
| V4 | 外業成本單 | cost | tbl8wRYCUCvbSoJG |
| V4 | 內業成本單 | cost | tblKwSDRg6WaGHYr |
| V4 | 外業工作單 | daily | tbl5zPLS0ExWNEty |
| V4 | 內業工作單 | daily | tblrCo8KeZiuJUNh |

上述表的 Base／table_id／kind 為明確白名單；日報會使用指定成本表與既有檢核欄位。核心識別欄位缺少時拒絕匯入，不以猜測或表名相似替代映射。

V3 僅供對照研究，不在匯入清單；Meegle 舊案件不匯入。來源欄位先核對 schema，再完整分頁讀取；partial、缺頁、重複游標或來源錯誤均不能提交成功快照。只有完整快照才原子更新來源快取與工作區。失敗保留最後成功資料、記錄嘗試時間及錯誤，不能把空結果當成新成功。

真實來源同步會在同公司正式工作區建立／更新來源案件與工項；已開始或手動調整的任務遇來源差異會標記 source_change_pending，避免覆蓋其人工安排。此為應用內保存，不是寫回 Lark Base。

同確認單的多筆報價集中在同案；尚無可信確認單關聯的報價保留待確認接案。正式與暫存分開計數，母子案保持獨立，衝突進入核對流程。須以完整來源重放及重跑不重複開案的證據驗收，不能由「9 張欄位 API 200」推定通過。

### 背景同步及持久工作

worker 每 30 秒輪詢各工作區。**旗標 `LARK_LIVE_READ_ENABLED` 關閉（預設）時**，公司來源保存 `source_connection.enabled`；背景按 300 秒（每五分鐘）間隔保留執行槽，名冊與班表同為 300 秒。**旗標開啟時**，來源、名冊、班表三個資料集不再由 worker 計時同步，改由 web 服務在使用者開頁時按需讀取（來源與名冊 TTL 預設 60 秒、班表 300 秒，見 `docs/LIVE_READ_20261007.md`），每個回應附 `freshness`；worker 仍須運行，負責通知、Input、Drive、原生審批輪詢與請假代理刷新。旗標關閉即回到舊計時，詳見該文件的回滾章節。唯讀同步以明確的公司 application／tenant 授權執行，不依賴最後按同步的人員登入。缺少可用身分時顯示需設定背景連線並保留最後成功資料，不假裝已執行。員工操作另受 15 分鐘人員資料新鮮度限制；指定維運主管於名單過期時僅能使用維修入口，不能讀公司業務內容。

來源同步與其他工作各自處理錯誤，來源失敗不應阻斷其他持久工作。Input 只向專用登錄表追加不可變修訂，不改來源儲存格；文件上傳在本地交易內自動排入 Drive 工作。未知遠端結果先讀回核實，不能盲目重送。能力與訓練存回一律禁止，薪資 Base 全域禁止寫入。外部通知與確認單發出另受工作區、角色、tenant、收件人及連線條件限制。

正式案件必須明確分類為 pending／meegle／workbench。未分類及 Meegle 舊案僅供檢視，API 與 worker 同樣阻擋工作台執行；僅明確指定 workbench 才接管。來源第一次出現不代表它是新案，不以日期猜測。分類由主管操作並留下紀錄。

### 隔離真實測試

需同時滿足：Lark test 工作區、`test_connection_mode=isolated_live`、`external_enabled=true`、application worker 正確 tenant，以及後端環境的專用目的地與工作區一致。Input 只能寫專用 test Base，文件只能存專用 test Drive；正式來源 Base／正式 Drive 目的地拒絕使用。測試通知、確認單訊息、能力與訓練存回仍為模擬。`simulated` 不能視為真實資料更新完成。

### 班表、訓練與能力

預排截止依負責人當日正常班表。已知 Attendance 表只有實際打卡，尚未接通正常排班來源；不能使用最後打卡時間或固定 17:00 代替。可由有權限者輸入帶日期的正常班表；缺少／矛盾時顯示待補班表／班表衝突，不能自行判逾期。

依最新核定，訓練、能力認定及考評停用。薪資／能力 Base 全域禁止寫入，既有相關工作不得恢復執行。僅唯讀取得核定的人員欄位，禁止載入薪資金額。班表與接案報價認定管理功能保留，不能因停用訓練而一併關閉。

### 原生審批與代理限制

原生審批由伺服器建立不可變案件／範圍／申請人／席次綁定，具 prepare、submit、poll、cancel 流程。首次送審須開啟專用旗標且關閉公開 demo；未知結果保留原綁定、只查回。撤回限定原申請人，確認 Lark CANCELED 後才顯示撤回成功。PM＋主管或 PM＋行政各席必须不同人；設計變更另需業主佐證及主管本人確認。設定 approval code、取得查詢權或讀到 APPROVED 不等於可信核准，必須核對定義、表單、範圍、各席及回存。

請假代理另有 `POST /api/delegations/verify-approval`，以登入者身分查詢 `/approval/v4/instances/detail`，核對已知請假定義、申請人、代理人、期間及撤銷狀態後保存可信快取。案件內仍須設定代理席位、範圍、期間與資格；不能只憑手填審批編號或勾選 qualified 取得代理權。

Lark 應用需要具備所查資料的權限，且登入使用者也能存取對應 Base。應以實際錯誤及查詢結果驗證，不把本機 CLI「已授權」等同此 Web 應用具備相同權限。業務錯誤 1254302 表示 Base 資源權限問題。

## 5. 備份與還原

使用 `scripts/backup_restore.py` 做可攜式應用備份，支持 SQLite 與 PostgreSQL。它保存 workspaces、receipts、source_caches、business_records、company_people、action_audit 六表及已引用附件，產生包含 SHA-256 檢查值的 ZIP；不備份 auth_sessions，還原後重新登入。這是應用資料匯出，不是 PostgreSQL 全叢集／角色／設定備份。

針對升級前的舊服務，`scripts/backup_live_legacy.py` 使用 PostgreSQL REPEATABLE READ／READ ONLY 取得三表一致快照，只複製快照引用的附件並驗大小、路徑及雜湊。舊版正式備份及本機空白 SQLite 還原逐列／逐檔比對見 [備份證據](CLOUD_BACKUP_EVIDENCE_20260927.md)。此工具限定舊 schema；新版必須使用六表 `backup_restore.py`，其一致性前提如下。

`backup_schedule.py` 提供每日／每月留存排程（30 日／12 月）。設定 BACKUP_DIR 後 `run_service.py` 監督 web、worker、backup 三個子程序。異地模式以 8 MiB 加密分塊及加密 manifest 寫入專用私密 Drive，逐檔讀回比對雜湊；未知上傳／刪除結果先查證。日常本地備份成功不代表異地備份或 PostgreSQL 還原演練已通過。

新版備份以 PostgreSQL REPEATABLE READ／READ ONLY 取得六張資料表的一致快照，只複製快照已引用的不可變附件並驗證大小及雜湊；登入 session 不備份。若未來增加附件覆寫／實體刪除流程，須先重新設計快照一致性或改採停寫維護程序。`backup_live_legacy.py` 仍只供舊 schema 使用，不能取代新版六表工具。

異地備份另需 `BACKUP_OFFSITE_ENABLED=true`、相同的 `BACKUP_DRIVE_ROOT_TOKEN` 與 `BACKUP_DRIVE_ALLOWED_ROOT`、經人工核實後的 `BACKUP_DRIVE_PRIVATE_ROOT_VERIFIED=true`，以及非空 `BACKUP_ENCRYPTION_KEYS_JSON`。私密備份根目錄不可等於正式或測試交付目錄；設定旗標本身不會修改 Drive 權限。保留舊解密金鑰直到相應備份到期，將復原金鑰另外安全保管。未啟用異地時，維運健康狀態顯示 `local_only`。

刪除過期異地副本前核對回執歸屬；DELETE 回應後仍須完整列目錄確認檔案消失，才清除本機加密分塊。不明結果不直接重送；未查證前保留本機副本。排程每分鐘檢查，遠端成功副本最多使用一小時內的核實回執；每日及每月副本不是連續時間點復原。

環境先提供 DATABASE_URL、UPLOAD_DIR；命令不把連線字串放在參數或輸出。備份檔不能放在 uploads 目錄內，目標檔不得已存在。

本地 PowerShell 範例：

```powershell
$env:DATABASE_URL = 'sqlite:///./data/prototype.db'
$env:UPLOAD_DIR = './data/uploads'
python scripts/backup_restore.py backup --file output/backups/workspace-20260925.zip
```

容器內，DATABASE_URL 延用已設定的密鑰變數：

```sh
python scripts/backup_restore.py backup --uploads /data/uploads --file /tmp/workspace-backup.zip
```

將完成的 ZIP 取回到受控儲存，不把容器 `/tmp` 當永久備份。備份包含案件及來源快取，依公司資料權限保護；另行安全保存部署版本及必要環境設定，勿把密鑰直接放入備份說明文件。

**還原僅允許空的目標資料庫與空的附件目錄。** 不在現有正式工作區上覆蓋還原；先使用獨立DB與volume驗證。工具會檢查格式、檔案雜湊、路徑及目標是否已有資料，檢查失敗即拒絕。

```powershell
$env:DATABASE_URL = 'sqlite:///./data/restore-check.db'
$env:UPLOAD_DIR = './data/restore-uploads'
python scripts/backup_restore.py restore --file output/backups/workspace-20260925.zip
```

首次還原前確保 `data` 父目錄存在；勿先啟動會建立示範資料的應用。PostgreSQL 還原改用新的空資料庫連線字串，UPLOAD_DIR 指向新的空 volume，命令相同。恢復完成後用相同程式版本啟動，應用會建立登入相關 schema；登入 session 不恢復。

專用 PostgreSQL 演練工具 `scripts/restore_drill.py` 使用 `DATABASE_URL` 僅比較正式資料庫名稱，實際還原只連線至私密設定的 `RESTORE_DRILL_DATABASE_URL`。目標必須為另一個名稱的空 PostgreSQL 資料庫；工具不啟動 web／worker、不建立或刪除資料庫。先核對部署內工具版本，再用獨立暫存目錄執行：

```sh
python scripts/restore_drill.py --file /private/workspace.zip --uploads /private/drill-uploads --receipt /private/drill-receipt.json
# 從異地下載完整 manifest 與所有分塊後：
python scripts/restore_drill.py --encrypted-manifest --file /private/backup-manifest.fernet --uploads /private/encrypted-drill-uploads --receipt /private/encrypted-drill-receipt.json
```

工具重新備份還原結果，逐列比較六表並核對全部附件雜湊。SQLite 測試通過不代表 PostgreSQL 演練通過；部署替換後 `/tmp` 快照可能消失，須重新建立並取回完整備份。最新備份及演練阻擋證據見 [備份實作與驗收紀錄](BACKUP_OFFSITE_IMPLEMENTATION_20260929.md)。

正式啟用前完成一次恢復演練：比對工作區／事件／審批數量，核對任務狀態與版本，抽取附件驗證大小及下載，確認新的公司登入、權限和來源狀態。記錄備份時間、應用版本、來源環境與驗證結果；未實做不得標示通過。保留週期與管理責任依公司部署政策設定。

## 6. 啟用及重啟驗收

- build 通過，`/api/health` 回 ok 且雲端 database=postgresql；沒有把健康檢查當成全部外部整合成功。
- 本地／preview 能完成示範操作，頁面重載仍保留；同一 session secret 重啟後工作區與附件可取回。
- 未登入正式服務時拿不到工作區；demo 不能讀／同步來源、查原生審批或切換成真實身分。
- Lark 回呼精確匹配，允許 tenant 成功、其他 tenant 拒絕；角色來源符合後台設定。
- 唯讀來源可追溯來源、更新時間及 partial／失敗狀態，沒有遠端寫入。
- 全量 9 表讀取、案件歸戶及第二次同步不重複建立案件逐項驗收；現有 2,569 筆讀取證據不代表所有案件分類已經完成。
- web 及 worker 都由監督程序運行；手動成功後的背景同步（旗標關閉：每五分鐘；旗標開啟：按需讀取與 `freshness`）、失敗保留資料、登入過期與 application fallback 分別驗證。
- test 的全模擬與隔離真實 Input／文件模式各自驗證；沒有對正式來源表或正式 Drive 試寫。
- 正常班表來源、請假代理可信查詢各自驗收；能力與訓練停用及薪資 Base 不回寫須測試。打卡、欄位可讀與本機模擬不是完成證據。
- 變更及展延的示範操作有明確標記；未配置真實提交 adapter 時正式送審被阻擋，不能顯示已成功送出。
- 還原演練完成後記錄結果；目前文件本身不承諾雲端重啟或備份恢復已通過。
