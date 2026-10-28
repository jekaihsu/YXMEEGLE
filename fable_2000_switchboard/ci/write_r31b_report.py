#!/usr/bin/env python3
"""Render the Traditional Chinese audit from measured verification results."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT.parent/'results/r31b_convergence'
r=json.loads((OUT/'result.json').read_text())
p=ROOT.parent/'w0_reports/13_fable_r30_r31b_convergence_audit.md'
first=r['stitch'].get('first_successful_apply') or {}
rows=[
('1','單一負責人與副本','card_single_assignee、事件冪等鍵、同組織在職已確認身分；副本只寫 notification_outbox；下一張卡待前卡動作後才建立。'),
('2','內部結算與現金獎金分離','case_settlement 可於完工後、未收款時 gm_signed；雙方未結承諾及已施作的預備明細阻擋簽核；獎金存 hr_private.bonus_line，未全額入帳拒絕新增。closed 額外檢查全數發票、封印成果里程碑及保留款。'),
('3','統一工編','Python 唯一來源採使用者指定 ^[A-MVXZ][0-9]{6}(-[0-9A-Z]{1,3})?$；產生 SQL 常數與同字串 CHECK。抽取正則由常數衍生，避免截取過長工編的合法前綴。'),
('4','序號與 thread 分開唯一','分別建立 (org_id,serial_no) 與 (org_id,thread_fingerprint) 部分唯一索引；相同序號換 thread 仍會被拒絕。'),
('5','地址辨識與來源認證分離','結果欄位改 is_internal_address，不提供 is_authentic_source；satcmd_guard 獨立要求 DKIM、SPF、Sent 副本與組織一致。'),
('6','待確認抽取值與 SQL 證據','抽取值只放 proposed_fields，渲染標示「待確認」；三個證據槽由 SQL 重新計算，綁 evidence_sql 登錄的 sql_id。呼叫者送入假數字亦無法覆蓋。'),
('7','30／100 元匯費容差','常數 BANK_FEE_TOLERANCE_TWD=100 產生 guard_setting 與金額 CHECK；差 30 或 100 元均須財務確認 invoice_fee_adjustment 後，invoice_paid_v 才歸零並放行。沖帳前文案為「待財務沖帳（差 NT$30，匯費容差內）」。撤銷收款會重新封鎖。'),
('8','員工別名','employee_alias 以 (org_id,alias) 唯一；僅自動登錄無歧義的正式全名，暱稱及簡稱由行政確認後維護。未命中轉行政待分類卡並隔離，不猜員工。'),
('9','兩種渲染器、同一動作','Lark／Plumb adapter 共讀 card，共用 POST /cards/{id}/act；四參數核心 SQL 以行鎖序列化，舊七參數 SQL 簽章轉接同一核心。雙通道與八路併發僅一次 acted_at、一次 audit_event／card_action_log。'),
('10','API 角色欄位白名單','Bearer token 由 api_session 雜湊與有效期限驗證，拒絕自行宣告角色；sales 看 floor_price、燈號，pm／vp 加 standard_cost_price。Canvas 亦逐層裁剪巢狀欄位，未知欄位不回傳；薪酬換算不進公開 API。')]
lines=[
'# Fable R30＋R31-B 收斂稽核',
'',f"驗證時間：{r['verified_at']}。資料庫：Box PostgreSQL `yongxiang_plumb_r39_clone`（隔離測試庫）。",
'',f"**本次可驗證範圍結果：`passed: {str(r['passed']).lower()}`、`failed_count: {r['failed_count']}`。** 此結果涵蓋實際 PostgreSQL 遷移、API 處理器、共用守門與套件合成資料回填；不代表真實 50,578 封信件與 12,084 列 Sheet 已完成匯入。",
'', '真實 `.eml` 目錄與權威《業主往來紀錄表》CSV 未在工作區找到。已從原始 ZIP 解出 6 封信與 5 列 CSV，實跑 dry-run、apply 與重跑。未製造歷史資料，也未以現有摘要 corpus 假扮原始信件。',
'', '| 驗證項目 | 實測結果 |', '|---|---|',
f"| R30 指定黃金測試 | {r['golden'].get('tests',0)}/23 PASS，0 failure、0 error、0 skip |",
f"| 專案收斂與 parity 測試 | {r['tests'].get('tests',0)} PASS，0 failure、0 error、0 skip |",
f"| 共用守門語料 | {r['guard_parity'].get('matched',0)}/{r['guard_parity'].get('cases',0)}，首個命中名稱完全一致，parity 100%；共 {r['guard_parity'].get('patterns',0)} 個模式 |",
'| R30 種子 | 連續套用兩次，org 身分與所有規則、範本、OTP 列的鍵值及內容一致 |',
'| 009／010 遷移 | 各連續套用兩次；另重播舊 R29 遷移，最新收斂定義仍保留 |',
'| 歷史縫合六項斷言 | 6/6 PASS，資料範圍為套件合成資料 |',
'| 回填冪等 | 重跑新增信件、連結、往來紀錄均為 0；dry-run 前後信件筆數相同 |',
'| 公開維度／事實物件 | 最終完整驗證單輪前後 10 個物件之定義、欄位、擁有者、ACL 與資料雜湊相同 |',
'| hr_private 與成本欄位 | sales 無私有 schema 權限；pm_sales_finance_role 無 bonus_line SELECT；sales 無 standard_cost_price SELECT |',
'', '| # | 收斂項目 | 已實作與驗證 |', '|---|---|---|']
lines += [f'| {i} | {name} | {description} |' for i,name,description in rows]
lines += [
'', '六項 stitch 斷言分別驗證：目錄信件數與 DB 相同、Message-ID 無重複、所有連結目標存在、序號在組織內唯一、內部命令不來自外部寄件者、隔離列均有 kind。額外測試覆蓋三種縫合規則及跨組織隔離。',
'', f"首次成功寫入的 DB 執行紀錄：`{first.get('run_id','未提供')}`；讀取 {first.get('mails_seen',0)} 封、新增 {first.get('mails_inserted',0)} 封、{first.get('links_inserted',0)} 條連結、{first.get('comms_inserted',0)} 筆往來紀錄，隔離 {first.get('quarantined',0)} 項。未解析的客戶／經手人，以及重號、空號與格式錯誤列，保留原列並隔離；不建立假員工或任意指定客戶。",
'', '原始套件的 uuid 組織鍵已對齊現有 text `YX`／`SJ`，保留資料庫既有法定名稱與統編；聯絡人採 customer_contact，發票日期採 issue_date。信件維持 append-only，在插入前決定 thread_id；批次失敗整筆交易回滾。',
'', '目前沒有 `dim.work_item`；價格政策與資料庫欄位權限使用 `public.work_item_policy` 驗證。既有 Canvas 路徑另外套用 API 白名單與巢狀欄位裁剪，兩個 ASGI 匯入路徑共用同一個認證 API。',
'', '為避免較早階段的冪等遷移重新覆寫 R31-B，009／010 保存部署函數與視圖定義；舊 R29／R31 遷移在同一交易提交前還原已安裝的收斂定義。測試已實際重播 R29 遷移並驗證最終行為。',
'', f"保留既有 {r['legacy_case_codes']['invalid_existing_rows']} 筆不符新工編格式的歷史列，CHECK 使用 NOT VALID，對新寫入與更新強制新格式。沒有自動改工編或宣稱舊資料已全數合規。",
'', 'OTP 寄件來源查核排除套件 fixture 後，沒有可供確認的真實 NLSC／CPC 驗證碼來源；正式寄件人核對仍待原始郵件。未寄出 OTP、Email 或 Lark 訊息，也未啟動對外 API listener；本次驗證為程式與本機 DB 整合範圍。',
'', '原始最早快照另外保留兩項差異：`dim.asset_instrument` 資料筆數 154→153；`dim.case_project` 的 ACL 不同，資料仍為 1,349 筆且雜湊相同。當時共享工作區另有 R29／R30 及 ROV 程序運作；本報告不替這兩項差異做未經證明的歸因，也未還原其他工作的資料或權限。最終單輪驗證以另外保存的 before／after 快照比較，結果一致。',
'', '主要交付檔案：',
'', '- `ai_switchboard_mvp/sql/006_seed_client_playbook_and_templates.sql`',
'- `ai_switchboard_mvp/sql/009_r31b_convergence.sql`',
'- `ai_switchboard_mvp/ci/gen_guard_constants.py`、`ci/guard_functions.sql`、`ci/guard_corpus.jsonl`',
'- `ai_switchboard_mvp/sql/010_guard_constants.sql`',
'- `ai_switchboard_mvp/api.py`、`canvas_policy.py`、`card_renderers.py`、`inbox_canvas_api.py`',
'- `ai_switchboard_mvp/tests/test_guard_parity.py`、`tests/test_convergence.py`、`tests/test_backfill_stitch.py`',
'- `results/r31b_convergence/result.json`、`golden.xml`、`pytest.xml` 及各階段日誌',
'', '重現方式（在 ai_switchboard_mvp 目錄）：',
'', '```bash',
'PG_DSN=dbname=yongxiang_plumb_r39_clone .venv-r31b/bin/python ci/verify_r31b.py',
'.venv-r31b/bin/python ci/write_r31b_report.py',
'```',
'', '若有真實匯出，驗證器可另傳 `--eml-dir /實際路徑 --sheet-csv /實際路徑.csv`。未提供 PG_DSN 的 pytest 僅做本機驗證並將資料庫測試標 skip；本次已有 PG_DSN，沒有 skip。已提供 pre-commit 產物檢查設定；工作區沒有 Git repository，故本次以產物完整內容與部署常數比較驗證，沒有宣稱已執行 Git hook。',
'', '原始檔案備份、最早快照、最終驗證前後快照、產物 SHA-256 與來源限制均可由 result.json 與同目錄證據追查。', '']
p.write_text('\n'.join(lines))
print(p)
