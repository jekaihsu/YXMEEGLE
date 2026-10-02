# 加密異地備份：本機實作與啟用條件

2026-09-30 狀態補充：專用 root 的目前 ACL 已由 `.runtime/lark-input-cli/backup-drive-privacy-verification.json` 核實私密（app＋jekai），詳見 `BACKUP_ACTIVATION_RUNBOOK_20260929.md`。一次性 driver 及 upload 前空庫檢查、同一 cfg 還原、早期 offsite 失敗撤销舊綠狀態均已在本機完成，46 項相關測試通過。仍無本輪實際金鑰生成／持久 volume／加密 Drive 往返／排程回執；下文較早的 ACL 待辦為歷史紀錄，不能用本機測試取代真實驗收。

本輪完成本機程式及測試，**沒有開啟雲端定時備份、沒有產生或修改正式金鑰、沒有建立／刪除真實 Drive 檔案**。最後已保存的19鍵雲端設定仍沒有 BACKUP_DIR；該回執是歷史設定證據，不冒充此刻即時讀取。

## 實作

新增 `scripts/backup_offsite.py`，使用成熟的 [cryptography Fernet／MultiFernet](https://cryptography.io/en/stable/fernet/) 作認證加密及金鑰輪替。每8MiB明文備份片段獨立加密，清單也加密；清單包含順序、片段與完整原檔雜湊。解密驗證全部成功才以exclusive原子方式公布ZIP，錯誤不留下看似成功的正式檔。此檔案格式只是分塊與清單包裝，沒有自訂密碼演算法。

雲端僅傳加密資料。Drive保存後逐檔下載比對加密bytes雜湊；持久化 attempted/token checkpoint，丟回應時按精確檔名查回、驗證後沿用，不盲目重送。查不到已attempted檔案時保留結果未知，待核對，不猜測失敗。成功副本最多每小時重驗，避免每分鐘重下載全部備份。

每日30天、每月12月清理由已驗證receipt限定；只移除仍在核定root、名稱及token相符的到期備份，不清理其他Drive檔案。加密片段到期後一併清理本機片段，保留小型receipt。此保留規則不能替代異地root權限或金鑰保管。

`backup_schedule.py` 保留一致快照及引用附件驗證，先確認當日／当月異地副本，再執行retention。遠端失敗即記錄error狀態；其他早期設定／本地故障仍由程序輸出型別與既有status時效顯示異常。`runtime_health` 對只有本機備份回傳local_only，不再顯示備份全部正常。

## 正式啟用前設定

下列設定均需以完整環境map合併，不能只送delta：

- `BACKUP_DIR`：獨立受保護的持久本機掛載，與UPLOAD_DIR分離。程式不自動建立雲端volume。
- `BACKUP_OFFSITE_ENABLED=true`。
- `BACKUP_DRIVE_ROOT_TOKEN`、`BACKUP_DRIVE_ALLOWED_ROOT`：同一個已核定的備份專用資料夾token，不能沿用成果交付資料夾。
- `BACKUP_DRIVE_PRIVATE_ROOT_VERIFIED=true`：由管理員核對資料夾權限後明示；這是部署前置核定，不是程式宣稱已自動檢查所有Drive分享成員。
- `BACKUP_ENCRYPTION_KEYS_JSON`：Fernet key字串陣列，第一把加密，其餘只供輪替期間解密。使用成熟函式 `Fernet.generate_key()`，不得用一般密碼或硬編碼。金鑰另存受控密鑰系統／離線復原保管，不放repo、備份ZIP或同一Drive資料夾。
- 同專用application的Drive讀寫／下載權限與backup root存取授權；本輪未新增外部權限。

新依賴：`cryptography>=46,<51`。本機測試環境現有41.0.3能執行所用穩定API，但正式image需依requirements安裝並跑發版驗證，不將舊本機版本測試視為新image證據。

## 還原

將某次加密manifest與其所有加密片段下載到私密目錄；配置金鑰及獨立空PG演練庫，執行：

```text
python scripts/restore_drill.py --encrypted-manifest --file /private/backup-manifest.fernet --uploads /private/drill-uploads --receipt /private/drill-receipt.json
```

演練腳本沿用正式與演練DB名稱不得相同、目標必須全空等限制，只import備份工具，不import app、不啟worker；解密到私密暫存ZIP後逐列／附件往返驗證。實際演練庫需停web/worker，腳本沒有遠端停服務能力。明文暫存於正常finally清除；程序被強制終止時，私密目錄可能保留，應納入操作清理。

本機針對測試：backup_offsite、backup_safety、runtime_health、runtime及OAuth復原契約共 **42 passed**；其後加密staging再次驗證及retention清理調整，offsite **7 passed**。尚缺真實金鑰備援、資料夾權限、定時執行、加密Drive上傳讀回、獨立PG還原及告警送達驗收。沒有這些回執，不能標為正式災難復原完成。
## Second review and live restore acceptance (2026-09-29)

**Production-snapshot PostgreSQL restore drill verified at 2026-09-29 06:07 UTC.** After deployment `6abb5119ad96bf301ede434a`, all three deployed backup/drill script hashes matched local reviewed files. A fresh read-only backup restored into separately named database `yx_restore_drill_20260929_060714`; re-export comparison confirmed every row in all six tables and the attachment hash. Counts: workspaces 28, receipts 2, source_caches 2, business_records 21,002, company_people 64, action_audit 18; one attachment. Source SHA-256: `3c6f010099a695c98bcd3b11b194804d1fe17fdca2c96b89d6941bbfe28029f5`. Private backup and PostgreSQL receipts: `.runtime/current-cloud-backup-20260929T060614Z-0388f9ff/`. Production database was not modified; no web/worker started and no database dropped. The isolated drill database remains for separately authorized cleanup. This resolves the earlier missing-script preflight blocker below; it does **not** establish that scheduled encrypted offsite Drive backups are enabled.

Latest integration verification: backend full suite 770 passed (96.87s), followed by 22 backup targeted tests including the actual `LARK_DRIVE_ROOT` / `LARK_TEST_DRIVE_ROOT` independent-destination guards. Local and remote monthly retention both preserve future-dated snapshots.

2026-09-29 04:54 UTC fresh deployed backup completed: six tables and one attachment; all rows and attachment bytes restored and compared locally. Private receipt: `.runtime/current-cloud-backup-20260929T045414Z-c3c76c92/receipt.json`. PostgreSQL drill preflight stopped before creating any database because deployed `scripts/restore_drill.py` was absent; both deployed backup helper hashes matched local. No version check was bypassed. After deploying the drill script, create a fresh backup again because the old remote `/tmp` archive may disappear with deployment.

- Uploads record the attempt before network I/O. An uncertain upload is reconciled only by exact name plus downloaded ciphertext hash; a missing or duplicate match stops automatic retries.
- Retention now confirms file absence with a complete Drive listing after DELETE. An asynchronous/pending response or lost reply retains local encrypted files, records the attempted deletion, and never blindly repeats DELETE. A later complete listing may finish reconciliation. Files outside the reviewed root are never deleted.
- Future-dated monthly backups are retained; only months older than the 12-month window expire.
- Encryption verifies the source has not changed between initial hashing and chunk creation. Restore-drill engine initialization failures now clean up the temporary decrypted archive.
- Added an actual encrypted remote-copy restore fixture: all six tables populated, legacy and normalized attachment references, every restored row and both files compared. This is a SQLite test, not evidence of a real PostgreSQL drill.
- Added asynchronous deletion and decrypted-temp cleanup regression tests. Independent private Drive ACLs, deployment encryption keys, and real encrypted upload/download remain pending external acceptance; PostgreSQL restore is now verified as recorded above.
