-- 006_seed_client_playbook_and_templates.sql
-- 永祥 AI 總機：業主潛規則（client_playbook_rule）、交付限制（customer.delivery_constraints）、
-- 發票規則旗標、OTP 白名單、7 大參數化範本（email_template）。
-- 前提：R29 DDL 已套用（client_playbook_rule / email_template / otp_forward_rule / org / customer）。
-- 冪等：全部 ON CONFLICT；重跑不重複。rule_code 是自然鍵。
-- 規則文字裡的任何數字都是「規則」不是「資料」：發票日、罰金、工作天由這裡查，不由模型記。

BEGIN;

-- ---------------------------------------------------------------------------
-- 0. 組織與結構性旗標
-- ---------------------------------------------------------------------------
-- Existing org IDs and verified legal identities are authoritative; never overwrite them.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM org WHERE id='YX') OR NOT EXISTS (SELECT 1 FROM org WHERE id='SJ')
  THEN RAISE EXCEPTION 'R29 YX/SJ organization seed required'; END IF;
END $$;

ALTER TABLE client_playbook_rule ADD COLUMN IF NOT EXISTS rule_code text;
CREATE UNIQUE INDEX IF NOT EXISTS client_playbook_rule_code_uq ON client_playbook_rule(rule_code);
ALTER TABLE client_playbook_rule ADD COLUMN IF NOT EXISTS sender_domain_regex text;   -- 以寄件網域套用
ALTER TABLE client_playbook_rule ADD COLUMN IF NOT EXISTS enforcement text NOT NULL DEFAULT 'advise'
  CHECK (enforcement IN ('advise','gate','auto_card'));                                -- advise=草稿提示；gate=守門擋；auto_card=生成卡片
ALTER TABLE customer ADD COLUMN IF NOT EXISTS delivery_constraints jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE customer ADD COLUMN IF NOT EXISTS invoice_rules jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE email_template ADD COLUMN IF NOT EXISTS tone text NOT NULL DEFAULT 'formal';

-- ---------------------------------------------------------------------------
-- 1. client_playbook_rule — 以 sender_domain_regex 掛到客戶群，customer_id 於客戶主檔完成後由 UPDATE 回填
-- ---------------------------------------------------------------------------
INSERT INTO client_playbook_rule
  (id, org_id, customer_id, scope, category, rule_code, sender_domain_regex, rule_text, structured, enforcement, confirmed_by, active)
VALUES
-- 台塑集團（@fpg.com.tw / tradevan 電子採購）
 (gen_random_uuid(), 'YX', NULL, 'customer', 'CAT-04', 'FPG_PERMIT_5WD',
  '(fpg\.com\.tw|tradevan\.com\.tw)',
  '台塑出入廠憑單：預定出廠日期只能開在申請日起 5 個工作天內；逾期未繳銷罰 NT$1,000 並須簽切結書。憑單綁人也綁車，D-1 必須提醒繳銷。',
  '{"permit_kind":"fpg_entry","max_workdays":5,"late_penalty_twd":1000,"affidavit_required":true,"remind_days_before":1,"binds":["employee","vehicle"]}',
  'auto_card', NULL, true),
 (gen_random_uuid(), 'YX', NULL, 'customer', 'CAT-02', 'FPG_NO_EXTERNAL_LINKS',
  '(fpg\.com\.tw|tradevan\.com\.tw|nanya\.com\.tw|fpcc\.com\.tw)',
  '台塑／麥電集團廠區電腦禁連外網：成果不得附任何雲端連結；單檔 >10MB 拆檔，或寄光碟；正文不得含 http(s)://。',
  '{"no_links":true,"max_attachment_mb":10,"cd_allowed":true,"split_large_files":true}',
  'gate', NULL, true),
 (gen_random_uuid(), 'YX', NULL, 'customer', 'CAT-06', 'FPG_EPROCUREMENT_BILLING',
  '(fpg\.com\.tw|tradevan\.com\.tw)',
  '台塑電子採購網請款：請款前需進度達標通知（主旨含「進度達標」「請款通知」）；請款單上傳至 tradevan 電子採購網，不以 Email 寄發票。',
  '{"billing_channel":"tradevan_portal","requires_progress_notice":true,"email_invoice_allowed":false}',
  'advise', NULL, true),
-- 南亞塑膠（JSA）
 (gen_random_uuid(), 'YX', NULL, 'customer', 'CAT-03', 'NANYA_JSA_REVIEW',
  '(nanya\.com\.tw|fpg\.com\.tw)',
  '南亞 JSA 作業安全分析審查：教育訓練日期必須 ≥ 審查完成日（含當日）；必附彩色現場照片；日期在審查日前即退件。',
  '{"doc":"JSA","training_date_rule":">=review_completed_date","photo_required":true,"photo_color":true}',
  'gate', NULL, true),
-- 台灣高鐵（@thsrc.com.tw）
 (gen_random_uuid(), 'YX', NULL, 'customer', 'CAT-05', 'THSRC_WORK_ORDER_BATCH',
  '(thsrc\.com\.tw)',
  '高鐵開口合約：每張工作指示單（PCDL-YY-NNNN 第N張）＝一個派工批次，掛母案 rate_card；未收到指示單不得排工。',
  '{"work_order_regex":"PCDL-\\\\d{2}-\\\\d{4}","creates":"dispatch_batch","requires_before_plan":true}',
  'auto_card', NULL, true),
 (gen_random_uuid(), 'YX', NULL, 'customer', 'CAT-03', 'THSRC_3D_TRAVERSE_RECHECK',
  '(thsrc\.com\.tw)',
  '高鐵主驗人退件「導線施測成果不符合規範，請重測」：回覆須附 3D 導線共軛點複測成果、閉合差表與儀器校正證明；用語參考上次通過版本。',
  '{"reply_requires":["traverse_closure_table","conjugate_points","instrument_calibration_cert"],"use_last_passed_reply":true}',
  'advise', NULL, true),
 (gen_random_uuid(), 'YX', NULL, 'customer', 'CAT-06', 'THSRC_ACCEPTANCE_THEN_BILLING',
  '(thsrc\.com\.tw)',
  '高鐵計價：驗收核決通知後才可正式發文計價；計價文須附計價憑證列表並蓋公司大小章；未核決前不得開發票。',
  '{"requires_acceptance_notice":true,"official_letter_required":true,"attachments":["payment_voucher_list"],"company_seals":["large","small"]}',
  'gate', NULL, true),
-- 中華工程（@bes.com.tw）
 (gen_random_uuid(), 'YX', NULL, 'customer', 'CAT-06', 'BES_INVOICE_RULES',
  '(bes\.com\.tw)',
  '中華工程計價：估驗單／計價單一式二份，蓋「合約計價」與「領款」大小章；發票日期限每月 10～20 日；發票品名固定＝合約編號＋合約名稱＋第X期計價，錯一字整批退件。',
  '{"copies":2,"seals":["contract_valuation","payment_receipt"],"invoice_day_min":10,"invoice_day_max":20,"item_name_formula":"{contract_no}{contract_name}第{period}期計價"}',
  'gate', NULL, true),
-- 政府機關（水利署、河川分署、地政局、縣市政府、港務公司）
 (gen_random_uuid(), 'YX', NULL, 'industry', 'CAT-02', 'GOV_OFFICIAL_DOC_NUMBER',
  '(gov\.tw|twport\.com\.tw)',
  '機關成果提送必帶正式發文字號「(民國年)詠發字第XXXXXXXXXXX號」，由公文系統依序配號；無文號的成果信不得寄出。',
  '{"doc_number_regex":"\\\\(\\\\d{3}\\\\)詠發字第\\\\d+號","official_doc_number_required":true}',
  'gate', NULL, true),
 (gen_random_uuid(), 'YX', NULL, 'industry', 'CAT-03', 'GOV_BUILDING_LINE_DEADLINE',
  '(gov\.tw)',
  '建築線補正有法定期限（依各縣市通知，通常 15～30 日）；逾期須重新申請。收到補正通知即建承諾列（party=us, kind=document_due）並以通知文號追蹤。',
  '{"commitment_kind":"document_due","party":"us","deadline_source":"notice_body","default_days":15}',
  'auto_card', NULL, true),
-- 公司級（global）
 (gen_random_uuid(), 'YX', NULL, 'global', 'CAT-02', 'HOLD_UNTIL_PAID_SEALED',
  '.',
  '官章版成果（.dwg/.dxf/用印 PDF）在該里程碑發票未收 = 0 前不得寄出；預覽版（浮水印、無章）不受限；特批需副總以上並有到期日。',
  '{"sealed_ext":[".dwg",".dxf"],"preview_allowed":true,"override_min_role":"vp"}',
  'gate', NULL, true),
 (gen_random_uuid(), 'YX', NULL, 'global', 'CAT-06', 'BANK_NOTICE_NEVER_AUTO_UNLOCK',
  '(tcb-bank\.com\.tw|mufg\.jp|ctbcbank\.com)',
  '銀行入帳通知只生成 bank_notice 候選列；配對（遮罩統編前後三碼＋金額±匯費容差）後由財務按卡確認沖帳，才算入帳。',
  '{"fee_tolerance_twd":100,"tax_id_mask_regex":"\\\\d{3}\\\\*\\\\*\\\\d{3}"}',
  'gate', NULL, true),
 (gen_random_uuid(), 'YX', NULL, 'global', 'CAT-01', 'VERBAL_PROMISE_48H',
  '.',
  '任何電話／LINE 口頭承諾（追加、折扣、交期）必須在 48 小時內以書面確認稿發出；未發出的承諾結算時不計。',
  '{"written_confirm_hours":48,"blocks_settlement":true}',
  'auto_card', NULL, true)
ON CONFLICT (rule_code) DO UPDATE SET
  rule_text = EXCLUDED.rule_text, structured = EXCLUDED.structured, enforcement = EXCLUDED.enforcement,
  sender_domain_regex = EXCLUDED.sender_domain_regex, active = EXCLUDED.active;

-- 1b. 把結構化交付限制與發票規則寫回客戶主檔（依網域匹配既有客戶 Email）
UPDATE customer c SET delivery_constraints = c.delivery_constraints || '{"no_links":true,"max_attachment_mb":10,"cd_allowed":true}'::jsonb
 WHERE EXISTS (SELECT 1 FROM customer_contact ct WHERE ct.customer_id = c.id AND ct.email ~* '@(fpg|nanya|fpcc)\.com\.tw$');
UPDATE customer c SET invoice_rules = c.invoice_rules || '{"bes_rules":true,"invoice_day_min":10,"invoice_day_max":20}'::jsonb
 WHERE EXISTS (SELECT 1 FROM customer_contact ct WHERE ct.customer_id = c.id AND ct.email ~* '@bes\.com\.tw$');
UPDATE customer c SET delivery_constraints = c.delivery_constraints || '{"official_doc_number_required":true}'::jsonb
 WHERE EXISTS (SELECT 1 FROM customer_contact ct WHERE ct.customer_id = c.id AND ct.email ~* '\.gov\.tw$');

-- 1c. 中華工程旗標 → invoice 的 CHECK 由此欄驅動（R29 §3）
ALTER TABLE invoice ADD COLUMN IF NOT EXISTS bes_rules boolean NOT NULL DEFAULT false;
ALTER TABLE invoice DROP CONSTRAINT IF EXISTS invoice_bes_day_chk;
ALTER TABLE invoice ADD CONSTRAINT invoice_bes_day_chk
  CHECK (NOT bes_rules OR issue_date IS NULL OR EXTRACT(day FROM issue_date) BETWEEN 10 AND 20) NOT VALID;

-- ---------------------------------------------------------------------------
-- 2. OTP 白名單（拉取制；寄件人完全比對＋主旨正則＋DKIM 網域＝寄件網域）
-- ---------------------------------------------------------------------------
ALTER TABLE otp_forward_rule DROP CONSTRAINT IF EXISTS otp_forward_rule_sender_exact_key;
CREATE UNIQUE INDEX IF NOT EXISTS otp_forward_rule_sender_org_uq ON otp_forward_rule(sender_exact, org_id);
INSERT INTO otp_forward_rule (account_label, sender_exact, subject_regex, code_regex, ttl_minutes, org_id) VALUES
  ('e-GNSS yx.ltd',   'egnss@mail.nlsc.gov.tw', '(驗證碼|Verification)', '\b(\d{4,8})\b', 5, 'YX'),
  ('e-GNSS sjsurvey', 'egnss@mail.nlsc.gov.tw', '(驗證碼|Verification)', '\b(\d{4,8})\b', 5, 'SJ'),
  ('CPC EBCS',        'ebcsAdmin@cpc.com.tw',   '(驗證碼|登入|OTP)',      '\b(\d{4,8})\b', 5, 'YX')
ON CONFLICT (sender_exact, org_id) DO UPDATE SET subject_regex = EXCLUDED.subject_regex, code_regex = EXCLUDED.code_regex, ttl_minutes = EXCLUDED.ttl_minutes;

-- ---------------------------------------------------------------------------
-- 3. 7 大參數化範本（{{param}} 由後端以白名單替換；未提供的必填參數 → 草稿不得核准）
--    禁詞檢查（outbound_guard）同樣套在範本本身；CI 會掃 body_tpl。
-- ---------------------------------------------------------------------------
INSERT INTO email_template (code, name, subject_tpl, body_tpl, required_params, category, version, active, tone) VALUES
 ('inquiry_reply', '詢價回覆',
  '詠翔測量｜{{project_title}} 詢價回覆',
  E'{{contact_title}}您好：\n\n感謝您的詢價。{{project_title}}一案，我們已收到需求資料，將於{{reply_by_date}}前提供報價。\n若有現場勘查需求或圖資可先提供，請回覆本信。\n\n詠翔測量有限公司\n{{pm_name}}（{{pm_title}}）\n電話：{{company_phone}}',
  ARRAY['contact_title','project_title','reply_by_date','pm_name','pm_title','company_phone'], 'CAT-01', 1, true, 'formal'),
 ('company_profile', '基本資料',
  '詠翔測量有限公司 基本資料',
  E'{{contact_title}}您好：\n\n隨信附上本公司基本資料（登記證明、技師證照、ISO 證書、保險證明）供貴單位建檔。\n如需補充文件，請告知項目與格式。\n\n詠翔測量有限公司\n{{sender_name}}\n電話：{{company_phone}}',
  ARRAY['contact_title','sender_name','company_phone'], 'CAT-01', 1, true, 'formal'),
 ('quote_return_reply', '報價回傳回覆（帶 pm 參數）',
  '詠翔測量｜{{project_title}} 報價回傳確認（報價編號 {{quote_no}}）',
  E'{{contact_title}}您好：\n\n已收到貴單位回傳之報價簽認單（報價編號 {{quote_no}}），本案由專案經理 {{pm_name}} 負責，聯絡電話 {{pm_phone}}。\n後續將由 {{pm_name}} 與您確認進場時間與所需資料。\n\n詠翔測量有限公司\n{{pm_name}}（專案經理）',
  ARRAY['contact_title','project_title','quote_no','pm_name','pm_phone'], 'CAT-01', 2, true, 'formal'),
 ('deliverable_submit', '成果提送標準信',
  '(成果提供) {{case_code}} {{project_title}}{{doc_number_suffix}}',
  E'{{contact_title}}您好：\n\n{{case_code}} {{project_title}}之{{milestone_name}}成果如附件（{{attachment_list}}）。{{official_doc_line}}\n如對成果內容有任何意見，請於 {{review_days}} 個工作日內回覆，以利後續作業。\n\n詠翔測量有限公司\n{{pm_name}}（專案經理）',
  ARRAY['contact_title','case_code','project_title','milestone_name','attachment_list','review_days','pm_name'], 'CAT-02', 1, true, 'formal'),
 ('billing_reply', '計價請款通知回覆',
  '{{case_code}} 第{{period}}期計價請款（{{contract_no}}）',
  E'{{contact_title}}您好：\n\n依貴單位{{acceptance_notice_ref}}，{{case_code}} {{project_title}}第{{period}}期計價文件如附件：計價單{{copies}}份（已用印）、發票（品名：{{invoice_item_name}}）、計價憑證列表。\n請協助查收並惠予撥款，謝謝。\n\n詠翔測量有限公司\n{{finance_name}}（財務）\n電話：{{company_phone}}',
  ARRAY['contact_title','case_code','project_title','period','contract_no','acceptance_notice_ref','copies','invoice_item_name','finance_name','company_phone'], 'CAT-06', 1, true, 'formal'),
 ('review_fix_reply', '審查意見修正回覆',
  'Re: {{case_code}} 審查意見回覆（第{{round}}次）',
  E'{{contact_title}}您好：\n\n針對貴單位{{review_ref}}所提意見，修正說明如下：\n{{response_table}}\n修正後成果如附件（{{attachment_list}}），請再次審閱。\n\n詠翔測量有限公司\n{{pm_name}}（專案經理）',
  ARRAY['contact_title','case_code','round','review_ref','response_table','attachment_list','pm_name'], 'CAT-03', 1, true, 'formal'),
 ('verbal_confirm_48h', '48h 口頭承諾書面確認函',
  '{{case_code}} 電話確認事項（{{call_date}}）',
  E'{{contact_title}}您好：\n\n依{{call_date}}電話討論，確認如下：\n{{commitment_lines}}\n如上述內容與您的理解不符，請於 2 個工作日內回覆更正；逾期未回覆，本公司將依上述內容辦理。\n\n詠翔測量有限公司\n{{pm_name}}（專案經理）\n電話：{{pm_phone}}',
  ARRAY['contact_title','case_code','call_date','commitment_lines','pm_name','pm_phone'], 'CAT-01', 1, true, 'formal')
ON CONFLICT (code) DO UPDATE SET
  name = EXCLUDED.name, subject_tpl = EXCLUDED.subject_tpl, body_tpl = EXCLUDED.body_tpl,
  required_params = EXCLUDED.required_params, category = EXCLUDED.category, version = EXCLUDED.version,
  active = EXCLUDED.active, tone = EXCLUDED.tone;

-- 舊範本退役：兩個「報價回傳回覆(專案經理：X)」合併為帶參數的 quote_return_reply
UPDATE email_template SET active = false WHERE code IN ('quote_return_reply_zhong','quote_return_reply_wu');

-- ---------------------------------------------------------------------------
-- 4. 自檢：範本不得含內部字串或禁詞（與 outbound_guard 同一份正則）
-- ---------------------------------------------------------------------------
DO $$
DECLARE bad int;
BEGIN
  SELECT count(*) INTO bad FROM email_template
   WHERE active AND (subject_tpl || E'\n' || body_tpl) ~
     '(寄件人\s*[:：]|收件人\s*[:：]|麻煩幫我|請寄給|收到請登記|業主往來\s*\d+|報編\s*\d+|#\d+\s*行政|成本|毛利|底價|A/B/C|點數單價)';
  IF bad > 0 THEN RAISE EXCEPTION '% active template(s) contain internal/forbidden text', bad; END IF;
END $$;

COMMIT;
