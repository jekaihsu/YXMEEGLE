# 加密異地備份：最小啟用與一次性復原驗收

本文件是已核定備份工作的執行準備；本次只審查程式、增加本機 driver／測試，沒有產生正式金鑰、上傳備份、建立 volume、修改雲端環境或操作資料庫。專用 Drive 的目前 ACL 已另行驗證，不能因此宣稱加密異地備份已啟用。

## 精確設定

| Key | 正式值／要求 |
| --- | --- |
| `BACKUP_DIR` | 建議 `/data/backups`，獨立持久 volume，不能在 `UPLOAD_DIR` 內；**完成一次性驗收後才加入服務環境** |
| `BACKUP_OFFSITE_ENABLED` | `true`，啟用每日／每月異地複本 |
| `BACKUP_DRIVE_ROOT_TOKEN` | `S6lqfyItLlr42OdCidWjgkLEpic` |
| `BACKUP_DRIVE_ALLOWED_ROOT` | 同上，必須完全相等 |
| `BACKUP_DRIVE_PRIVATE_ROOT_VERIFIED` | `true`，依本次有日期的 ACL 回執；此 flag 本身不會向 Drive 重新查權限 |
| `BACKUP_ENCRYPTION_KEYS_JSON` | JSON 字串陣列；第一把 Fernet key 加密，其餘供舊備份解密；實際值只能走受控 secret 交付 |

既有必要值必須保留：`DATABASE_URL`、`UPLOAD_DIR=/data/uploads`、`LARK_APP_ID=cli_aa3cab98b2789e17`、`LARK_APP_SECRET`、`LARK_WORKER_IDENTITY=application`、`LARK_WORKER_ORGANIZATION`。備份 application adapter 不使用個人 OAuth token；授權 app 仍須具備目標資料夾存取、列目錄、上傳及下載權限。

僅演練程序另外注入 `RESTORE_DRILL_DATABASE_URL`：已另外建立、名稱異於正式庫、全部表均空且沒有 web／worker 的 PostgreSQL 演練庫。不要把此設定留在正式 web／worker 環境。`DATABASE_URL` 在 snapshot 階段讀正式庫，在 restore drill 階段只供名稱安全比對，不會連正式庫。

所有正式環境更新必須從**最新完整環境 map**合併這六個 key，再跑 `release_env_guard`。`prepare_release_settings.py` 目前只準備來源／worker delta，沒有備份 key 的新增邏輯；勿以它的成功訊息當成備份設定已齊。不得直接提交六鍵 delta 取代整份環境。

## Volume 與啟動順序

`run_service.py` 只要看見非空 `BACKUP_DIR` 就啟動 `backup_schedule.py`；`BACKUP_OFFSITE_ENABLED=false` 不會停止本機備份。先掛載 volume、核對持久性與存取權，再做一次性验收，最後才加入 `BACKUP_DIR` 並啟動排程。

建議專用 volume 掛載 `/data/backups`，既有 uploads volume 仍為 `/data/uploads`。不要把備份寫到未掛載的 container 目錄或 `/tmp` 後宣稱持久。程序需要建立檔案、fsync、同檔案系統 hard link、rename／replace；部署身份需能使用這些操作。只允許服務及核定維運身份讀取，Linux 可用 owner-only 目錄權限；程式本身不會建立雲端 volume，也不會自動收緊 filesystem ACL。

本機 volume 會存**明文 ZIP**、加密分塊、checkpoint 及 `status.json`。30 個 daily＋12 個 monthly 並非小量固定空間：按實際保留 ZIP 總量計算，再加 Fernet/base64 約 1.34 倍的異地 staging、驗收下載／還原和暫存餘量；正常穩態約為保留 ZIP 總量的 2.34 倍，未含失敗残留。異常 `.invalid-*`、中斷的 acceptance 目錄不由 daily retention 自動清理。

## 一次性最小命令

先由核定 secret 系統向**單次程序**注入上列備份設定、既有 app 設定、DB 設定與演練 DSN；不要在指令、shell history 或 chat 寫入秘密值。此階段不需設定 `BACKUP_DIR` 或啟動 worker。以下示範使用已掛載私密 volume 的唯一 run 目錄，實際執行前換成此次唯一名稱。

```sh
python scripts/backup_restore.py backup --uploads /data/uploads --file /data/backups/acceptance-20260929TXXXXXXZ.zip
python scripts/backup_offsite_acceptance.py --file /data/backups/acceptance-20260929TXXXXXXZ.zip --directory /data/backups/acceptance-20260929TXXXXXXZ
python scripts/backup_offsite_acceptance.py --file /data/backups/acceptance-20260929TXXXXXXZ.zip --directory /data/backups/acceptance-20260929TXXXXXXZ --execute
```

第一步讀正式 PostgreSQL 一致快照及引用附件，產生全新 ZIP；第二步只有本機設定、archive 及不同 DB 名稱檢查，不連網、不查演練庫是否空。執行第三步前，操作者須已確認演練庫無服務連線。第三步現在會先唯讀檢查所有既有資料表（含非工作台備份表，如 auth_sessions），拒絕非空庫後才取得 Drive credentials；最後還原前再次檢查。這不是資料庫鎖，演練期間仍必須停用該庫的 web／worker。

第三步只做一次 `replicate`，不呼叫 `backup_schedule.tick` 或 `prune`：加密 manifest／chunks → 專用 Drive 上傳 → 遠端讀回 hash 驗證 → **再次將遠端 bytes 下載至新的 downloaded 目錄** → 解密該下載 manifest → 空白 PostgreSQL 還原 → 再匯出並逐列／附件比對。它不使用本機加密 staging 冒充下載證據，不啟動 web／worker，不刪遠端檔案，不產生金鑰。

新腳本 `scripts/backup_offsite_acceptance.py` 必須加入下一個 stage 的明確 scripts 清單，或在已有受控執行環境運行同一份已核對 hash 的腳本。不可假設已在目前容器內。2026-09-30 複核：driver、加密備份、安全限制與 runtime health 合計 **46 passed**，其中 driver 6 項；沒有使用真實金鑰或外部服務。

成功需同時保存 `encrypted/*/receipt.json`、`restore-receipt.json`、`acceptance-receipt.json` 及此次 source hash。失敗時保留原目錄與 receipt，不換新目錄盲目重送；upload checkpoint 的 attempted/token 要用原 receipt 與完整 Drive 列表核對。新 driver 故意拒絕已存在的驗收目錄，恢復未完成工作需按既有 `backup_offsite.replicate` checkpoint 流程處理，不抹除記錄。

通過後才以完整環境 map 啟用 `BACKUP_DIR`／`BACKUP_OFFSITE_ENABLED=true` 並重啟既有單實例服務。確認 supervisor 只有一個 backup 子程序、`status.json.offsite.status=verified`、實際 snapshot 時間及下一次排程進展。`backup_schedule.py --once` 會執行 daily/monthly retention；排程已在運作時不要並行手動跑它。現有程式沒有跨程序 lock。

## 公司金鑰交付與保管文件

建立一份**不含 key 值**的公司維運交付記錄，存公司受限維運文件區，由 jekai 管理，包含：

1. Secret 系統名稱、完整 record 路徑／ID、key ID（人類標籤）、建立日期、用途及目前加密 key 的順序。key 值本身存 secret vault，不放文件、Git、備份 ZIP、這個備份 Drive 或 screenshot。
2. 核定保管人 jekai、可執行緊急復原的人員及替代取得程序；新增保管人須另外授權，不因寫這份文件自行授權他人。
3. 分離的災難取回方式：在 Zeabur／app／Drive 均不可用時，如何由公司持有的 vault 或另行核定離線保管取得 key。只放 Zeabur env 不是金鑰備援。
4. 交付確認：jekai 已能從公司保管處取回，並用同一受控 key 解密此次從 Drive 下載的 manifest；記錄驗收回執 ID、日期和成功狀態，不附原始 key。
5. 輪替規則：新 key 放陣列第一位，仍保留所有尚在 daily/monthly 保留期間的旧 key；只有舊 ciphertext 全部到期或完成已驗證重新加密後才移除。離線保管同步更新並保留 key ID → 備份批次對應。

金鑰建立／交付目前仍由 root 依既有授權執行，本次沒有生成任何正式 key，也沒有證據能代替公司保管人取回確認。

## 已知界線與 root 下一步

ACL 回執 `.runtime/lark-input-cli/backup-drive-privacy-verification.json` 已確認此空白專用資料夾只有 app owner＋jekai，對外／連結分享關閉，管理協作者與複製下載限 full access。這解决舊 `BACKUP_OFFSITE_IMPLEMENTATION_20260929.md` 的 ACL 待辦，沒有解决 key custody、持久 volume、實際加密異地往返、排程或告警。

最短下一步是：核定公司 key 保管交付 → 掛載受保護 backup volume → 準備全新空演練庫及私密單次 env → 跑一次上述 driver → 取得回執 → 完整 map 啟排程。2026-09-29 06:07 UTC 的既有 PostgreSQL drill 是先前明文備份復原證據，不能取代本次加密 Drive 往返。

2026-09-30 補正：`backup_schedule` 的 key/settings 與 adapter 取得已移入 offsite 錯誤處理；任何上述失敗都將舊綠 status 改為 error，且停止 retention，不把私密錯誤細節写入 status。此補正尚需隨下一版部署。更早的 snapshot／filesystem 失敗仍需配合程序 error_type 和 status 時效監測。`verify_file` 只下載並驗 hash，不會保存本地復原檔；新 driver 的獨立 downloaded 步驟才提供可還原 bytes。

同次補正：`restore_drill.run` 明確接受 driver 的同一份 cfg，production／drill DSN 安全檢查與解密 key 不再意外讀到另一份 ambient environment。CLI 不變，單獨執行 restore_drill 時仍預設讀程序環境。測試刻意將 ambient drill 指向正式庫、ambient key 設空，確認只有傳入的核定 cfg 被用於演練；SQLite 替身證據不能宣稱真實 PostgreSQL 驗收。
