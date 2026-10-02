# 真實加密異地備份驗收準備

## 已確認

- `scripts/backup_offsite_acceptance.py` 預設只做本機 preflight；加 `--execute` 才會接觸遠端。
- execute 先確認還原 PostgreSQL 為空，再上傳加密分片、下載遠端密文、解密還原、逐表比對資料與附件 hash。它不建立資料庫，不啟動 app/worker，不跑 retention。
- 現有 `.runtime/current-cloud-backup-20260929T060614Z-0388f9ff/workspace.zip` 2026-09-30 本機 `validate_archive` 成功：1,333,591 bytes，解壓合計 23,306,743 bytes，1 個附件。這是 9/29 歷史快照，不能證明最新正式版備份。
- 獨立備份 app `cli_aa361fea3678de13` 的實際 UI 已配置 upload-only 與 Drive readonly，發布／ACL／真實 API 驗收由主線接續。見最小權限核查文件。

## 尚缺的配置或證據

1. 獨立 app 發布生效、專用備份資料夾新 app 身分 ACL 驗證。舊 app 的 ACL 成功不代表新 app 也可存取。
2. 秘密配置：`BACKUP_LARK_APP_ID`、`BACKUP_LARK_APP_SECRET`、`BACKUP_LARK_ORGANIZATION`。不得回退正式工作台 app。
3. `BACKUP_ENCRYPTION_KEYS_JSON` 的有效 Fernet key，以及公司另處保存／取回密鑰的證據。runner 不自動產生或代稱已託管。
4. `BACKUP_DRIVE_ROOT_TOKEN` 與 `BACKUP_DRIVE_ALLOWED_ROOT` 必須一致且不同於成果目錄；只有完成當前 ACL 核查才設 `BACKUP_DRIVE_PRIVATE_ROOT_VERIFIED=true`。
5. `RESTORE_DRILL_DATABASE_URL`：獨立且空的 PostgreSQL，資料庫名稱不同正式 DB，也不能是 postgres/template0/template1。現有 staging app DB 已有資料，不可用。本機至目標的連線方式亦需核實。
6. 最新正式快照、足夠磁碟空間與備份目錄掛載持久性。一次 roundtrip 成功不等於常態排程／持久 volume 已完成。

只讀檢查在 `.runtime/*env*.json` 找到 `DATABASE_URL` 配置證據，沒有輸出值。沒有在已檢查的頂層 JSON 找到上述完整 BACKUP／RESTORE 配置；不代表其他秘密儲存不存在。相關私有路徑：`.runtime/admin-release-current-env.json`、`.runtime/native-release-env-readback.json`、`.runtime/lark-input-cli/backup-drive-privacy-verification.json`。使用時須重新確認新鮮度，不能直接拿舊整份環境覆蓋线上。

## 最短執行順序

1. 主線完成 app 發布與新身分 ACL，提供當前精確白名單目錄；配置公司持有密鑰。
2. 建立獨立空 PG 目標並保持 app/worker 未啟動；以安全方式把上述設定載入執行程序環境，不把值貼入命令或紀錄。
3. 選最新有效 snapshot、全新驗收目錄，先跑不外寫的本機 preflight：

```powershell
python scripts/backup_offsite_acceptance.py --file <snapshot.zip> --directory <全新驗收目錄>
```

4. 確認配置及目標後，使用相同路徑加 `--execute`，這步會上傳密文並寫入獨立還原 DB：

```powershell
python scripts/backup_offsite_acceptance.py --file <snapshot.zip> --directory <全新驗收目錄> --execute
```

5. 留存 `acceptance-receipt.json`、`restore-receipt.json` 與加密上傳 receipt；檢查 `encrypted_offsite`、`downloaded_ciphertext_only`、`postgresql_rows_equal`、`attachments_equal` 全部 true，且 `source_sha256` 對得上選定快照。還原 DB 不接正式 app。

若已部分 execute，原目錄不再符合「全新」条件。保留原 receipt，先查明遠端 token／還原狀態；不能為了重試任意换目录重複上傳或清空 DB。小快照足以驗流程，但最終還是需當前正式快照驗收。



## 9/30 最新技術驗收（取代損壞的問號文字）

- 正式公司入口已停用 Demo；9/30 程式目前僅部署 staging，正式仍是 9/29 映像。正式最新入口核對時間 14:07 UTC，匿名受保護 API 拒絕存取，OAuth 指向公司應用。
- 獨立備份應用 cli_aa361fea3678de13 已發布 1.0.0，只開 drive:file:upload 與 drive:drive:readonly。完整資料夾協作者 UI 與應用讀取均已驗證，不使用不支援的資料夾 members API 作成功證據。
- 正式唯讀快照完成於 13:22:11 UTC，1,683,523 bytes；SHA256：ef6e2f8ffd1c248156ce75e2d2435aa7cb26ade32da450f90dda4d26ddf5907b。
- 快照含 workspaces 37、receipts 5、source_caches 2、business_records 25,494、company_people 128、action_audit 32，以及 2 份附件。登入 sessions 不還原；2 份歷史附件缺原始資料庫 SHA，不能宣稱歷史原始雜湊已核實。
- 已由獨立 Lark 應用上傳加密備份、下載遠端密文、解密核對快照雜湊，再還原至獨立空 PostgreSQL 6abce665454b8f31a5efc37e。資料列與附件逐一比對成功：postgresql_rows_equal=true、attachments_equal=true、downloaded_ciphertext_only=true。
- 未修改正式資料庫或 staging DATABASE_URL；還原服務僅私網可用。單次傳輸 RSA 私鑰已移除，備份還原金鑰仍保留。沒有執行遠端保留期刪除。
- 回執位於 .runtime/workbench-snapshot/receipt.json、.runtime/workbench-backup-roundtrip/roundtrip-receipt.json、.runtime/cloud-restore/restore-verified.json 與 transport-cleanup.json；回執不代表常態排程已啟用。
- 使用者已明確回覆「尚未另存，先繼續技術驗收」。保管人 jekai；custody_confirmed=false。常態備份排程保持關閉，其他技術工作繼續，不重問已回答事項。
- QA 定義 E1DEFC43-3E29-4238-AD9D-91ACF8E29091 已發布並核實 ACTIVE；測試使用同應用名冊解析出的兩個不同在職帳號，不新增正式業務角色。
- QA run qa-joint-20260930，instance 2D9E52F7-298A-4FE2-A1CF-C9403B5B551E 已成功送出；最後成功查回 PENDING 且 binding_verified=true。14:07 UTC 最新 poll 回報 remote_operation_unverified，不能以本機舊 pending 當作最新遠端結果；禁止重送或代真人核准，正在診斷。
- 正式發布仍需核對持久卷權限、來源切換 baseline、同事真人 OAuth 與共同審批。常態維運另需金鑰分離保管及同正式版本 24 小時觀測；不將這些未完成事項標成已完成。
- C 槽僅清理可再生 pip/npm 快取，保留程式、瀏覽器工作階段、公司資料與金鑰；詳見 DISK_RECOVERY_20260930.md。

以上依已有技術回執重建，非重新執行驗收。舊章節記錄的是當時狀態，判斷目前進度以本節及後續紀錄為準。
