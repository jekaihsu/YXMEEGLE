"""Repair the explicitly identified lossy handoff sections; no runtime changes."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
tracker = ROOT / 'docs/EXECUTION_TRACKER_20260930.md'
text = tracker.read_text(encoding='utf-8-sig')
marker = '\n## 9/30 ?'
if marker not in text:
    raise SystemExit('Expected damaged section not found; no change made')
tracker.write_text(text.split(marker, 1)[0].rstrip() + '''

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
''', encoding='utf-8')
custodian = ROOT / 'docs/BACKUP_CUSTODIAN_20260930.md'
custodian.write_text('''# 備份還原金鑰保管決策（2026-09-30）

使用者指定 jeaki；依本對話已驗證的公司帳號，記錄為 jekai。

- 責任為保管備份還原金鑰及協調復原，不新增日常管理或必要業務簽核席位。
- 金鑰已在本機產生；加密上傳、下載與獨立 PostgreSQL 還原驗收已完成，詳見 EXECUTION_TRACKER_20260930.md。
- 使用者回覆「尚未另存，先繼續技術驗收」，因此 custody_confirmed=false；公司受控位置的分離保管尚未完成。
- 常態備份排程仍未啟用；不以此阻擋其他獨立的修正與技術驗收。
- 金鑰不得寫入文件、版本庫、對話或與加密備份放在同一位置。本機金鑰檔不移除、不重新產生。
''', encoding='utf-8')
print('Repaired tracker and custodian UTF-8 text; no secrets read or runtime changed.')
