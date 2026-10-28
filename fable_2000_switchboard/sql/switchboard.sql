-- 詠翔 AI 往來總機 MVP；僅 public，永遠 DRY_RUN。可重複執行。
BEGIN;
SELECT pg_advisory_xact_lock(1943,12084);
CREATE TABLE IF NOT EXISTS public.switchboard_serial (
  singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
  last_serial bigint NOT NULL CHECK(last_serial>=12084),
  basis text NOT NULL DEFAULT '權威稽核觀察到12084；不是已匯入12084筆'
);
INSERT INTO public.switchboard_serial(singleton,last_serial) VALUES(true,12084)
ON CONFLICT(singleton) DO NOTHING;

CREATE TABLE IF NOT EXISTS public.switchboard_intake (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_key text NOT NULL UNIQUE,
  serial_no bigint NOT NULL UNIQUE,
  serial_label text GENERATED ALWAYS AS ('業主往來'||serial_no::text) STORED,
  channel text NOT NULL CHECK(channel IN ('email','staff_request','phone_memo','sheet_import')),
  mailbox text,
  occurred_at timestamptz NOT NULL,
  evidence_kind text NOT NULL CHECK(evidence_kind IN ('real_thread','real_sheet','staff_request','synthetic_test')),
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION public.switchboard_register(
  p_key text,p_channel text,p_mailbox text,p_at timestamptz,p_kind text,p_payload jsonb,
  p_existing_serial bigint DEFAULT NULL) RETURNS public.switchboard_intake
LANGUAGE plpgsql AS $$
DECLARE item public.switchboard_intake; next_serial bigint;
BEGIN
  PERFORM pg_advisory_xact_lock(1943,12084);
  SELECT * INTO item FROM public.switchboard_intake WHERE source_key=p_key;
  IF FOUND THEN RETURN item; END IF;
  IF p_existing_serial IS NOT NULL AND (p_kind<>'real_sheet' OR p_existing_serial<1) THEN
    RAISE EXCEPTION '既有流水號僅可來自真實試算表列';
  END IF;
  SELECT greatest(last_serial,coalesce((SELECT max(serial_no) FROM public.switchboard_intake),0),
    coalesce((SELECT max(serial_no) FROM public.client_communication),0))
    INTO next_serial FROM public.switchboard_serial WHERE singleton FOR UPDATE;
  next_serial := coalesce(p_existing_serial,next_serial+1);
  UPDATE public.switchboard_serial SET last_serial=greatest(last_serial,next_serial) WHERE singleton;
  INSERT INTO public.switchboard_intake(source_key,serial_no,channel,mailbox,occurred_at,evidence_kind,payload)
    VALUES(p_key,next_serial,p_channel,p_mailbox,p_at,p_kind,p_payload) RETURNING * INTO item;
  RETURN item;
END $$;

CREATE TABLE IF NOT EXISTS public.client_communication (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  intake_id uuid UNIQUE REFERENCES public.switchboard_intake(id),
  serial_no bigint NOT NULL UNIQUE,
  direction text NOT NULL CHECK(direction IN ('inbound','outbound')),
  channel text NOT NULL CHECK(channel IN ('email','line_group','line_oa','phone_memo','official_doc','meeting','staff_request')),
  occurred_at timestamptz NOT NULL,
  customer_id uuid NOT NULL REFERENCES public.customer(id),
  contact_id uuid REFERENCES public.customer_contact(id),
  case_id uuid REFERENCES public."case"(id),
  quote_id uuid REFERENCES public.quote(id),
  invoice_id uuid REFERENCES public.invoice(id),
  our_employee_id uuid NOT NULL REFERENCES public.employee(id),
  external_ref text UNIQUE,
  thread_key text,
  body_text text NOT NULL,
  attachments jsonb NOT NULL DEFAULT '[]',
  summary_120 text CHECK(length(summary_120)<=120),
  extracted_by text NOT NULL DEFAULT 'agent' CHECK(extracted_by IN ('agent','human')),
  human_confirmed_by uuid REFERENCES public.employee(id),
  CHECK(channel<>'phone_memo' OR human_confirmed_by IS NOT NULL)
);
CREATE OR REPLACE FUNCTION public.switchboard_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION '往來事件不可修改或刪除；更正請新增事件'; END $$;
DROP TRIGGER IF EXISTS switchboard_communication_immutable ON public.client_communication;
CREATE TRIGGER switchboard_communication_immutable BEFORE UPDATE OR DELETE ON public.client_communication
FOR EACH ROW EXECUTE FUNCTION public.switchboard_append_only();
DO $$ BEGIN
  IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='app_rw') THEN
    REVOKE UPDATE,DELETE ON public.client_communication FROM app_rw;
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.client_commitment (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_comm_id uuid NOT NULL REFERENCES public.client_communication(id),
  case_id uuid REFERENCES public."case"(id), quote_id uuid REFERENCES public.quote(id),
  customer_id uuid NOT NULL REFERENCES public.customer(id),
  contact_id uuid REFERENCES public.customer_contact(id),
  party text NOT NULL CHECK(party IN ('client','us')),
  kind text NOT NULL CHECK(kind IN ('scope_add','scope_cut','deadline','document_due','price_discount','payment','change_order','site_access','other')),
  description text NOT NULL, quantity numeric, unit text, amount_twd numeric(14,2),
  due_date date, fulfilled_at timestamptz,
  discount_percent numeric CHECK(discount_percent BETWEEN 0 AND 100),
  status text NOT NULL DEFAULT 'stated' CHECK(status IN ('stated','written_confirm_sent','confirmed_by_client','disputed','fulfilled','breached','withdrawn')),
  written_confirm_comm_id uuid REFERENCES public.client_communication(id),
  linked_contract_item_id uuid REFERENCES public.contract_item(id),
  owner_employee_id uuid NOT NULL REFERENCES public.employee(id),
  UNIQUE(source_comm_id,kind),
  CHECK(kind NOT IN ('scope_add','price_discount','change_order') OR case_id IS NOT NULL OR quote_id IS NOT NULL),
  CHECK(status<>'written_confirm_sent' OR written_confirm_comm_id IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS public.email_playbook_rag (
  category_id text PRIMARY KEY CHECK(category_id ~ '^CAT-(0[1-9]|10)$'),
  name_zh text NOT NULL, reply_template text NOT NULL,
  keywords jsonb NOT NULL, rules jsonb NOT NULL, source_refs jsonb NOT NULL,
  legacy_playbook_refs jsonb NOT NULL, grounded_thread_ids jsonb NOT NULL DEFAULT '[]',
  example_status text NOT NULL CHECK(example_status IN ('GROUNDED','NO_EXAMPLE')),
  sla_hours integer NOT NULL CHECK(sla_hours>0),
  requires_human boolean NOT NULL DEFAULT true CHECK(requires_human)
);

CREATE TABLE IF NOT EXISTS public.outbound_message (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  intake_id uuid NOT NULL UNIQUE REFERENCES public.switchboard_intake(id),
  channel text NOT NULL DEFAULT 'email',
  to_contact_id uuid REFERENCES public.customer_contact(id),
  case_id uuid REFERENCES public."case"(id), quote_id uuid REFERENCES public.quote(id),
  invoice_id uuid REFERENCES public.invoice(id),
  draft_body text NOT NULL, final_body text,
  attachments jsonb NOT NULL DEFAULT '[]', drafted_by text NOT NULL DEFAULT 'agent',
  approved_by uuid REFERENCES public.employee(id), approved_at timestamptz,
  sent_at timestamptz CHECK(sent_at IS NULL),
  actual_sends integer NOT NULL DEFAULT 0 CHECK(actual_sends=0),
  status text NOT NULL DEFAULT 'DRY_RUN' CHECK(status='DRY_RUN'),
  scheduled_for timestamptz,
  comm_id uuid REFERENCES public.client_communication(id),
  gate_results jsonb NOT NULL, action_card jsonb NOT NULL,
  prompt_version text NOT NULL DEFAULT 'switchboard-1.0',
  CHECK(approved_by IS NULL OR approved_at IS NOT NULL),
  CHECK(final_body IS NULL OR approved_by IS NOT NULL)
);
DO $$ BEGIN
  IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='public.outbound_message'::regclass
                AND conname='switchboard_final_requires_approval') THEN
    ALTER TABLE public.outbound_message ADD CONSTRAINT switchboard_final_requires_approval
      CHECK(final_body IS NULL OR approved_by IS NOT NULL);
  END IF;
END $$;

CREATE OR REPLACE FUNCTION public.switchboard_outbound_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE body text;
BEGIN
  body := coalesce(NEW.draft_body,'')||E'\n'||coalesce(NEW.final_body,'');
  IF body ~* '(底價|成本|毛利|A[ /-]*B[ /-]*C[ ]*預算|內部|點數單價)' THEN
    RAISE EXCEPTION '對外草稿含禁詞'; END IF;
  IF body ~* '(^|[^a-zA-Z0-9])([a-zA-Z][12][0-9]{8}|09[0-9]{2}[- ]?[0-9]{3}[- ]?[0-9]{3}|0[2-8][- ]?[0-9]{3,4}[- ]?[0-9]{4})([^a-zA-Z0-9]|$)' THEN
    RAISE EXCEPTION '對外草稿含未遮蔽電話或身分證'; END IF;
  IF body ~* '(1[3-9]([ ()-]*[0-9]){9}|\+886[ ()-]*[2-9]([ ()-]*[0-9]){7,8}|(電話|电话|手機|手机|phone|tel)[：: ]*[+]?[0-9][0-9 ()-]{6,}[0-9])' THEN
    RAISE EXCEPTION '對外草稿含未遮蔽國際電話'; END IF;
  IF body ~* '(薪資|薪水|月薪|年薪|salary|payroll)' AND
    regexp_replace(body,'\[MASKED_HR_PRIVATE\]','','g') ~ '[0-9]' THEN
    RAISE EXCEPTION '對外草稿含薪酬數字'; END IF;
  IF NEW.approved_by IS NOT NULL AND (NEW.to_contact_id IS NULL OR NEW.case_id IS NULL) THEN
    RAISE EXCEPTION '核准前須核實收件人與案件'; END IF;
  IF NEW.to_contact_id IS NOT NULL AND NEW.case_id IS NOT NULL AND NOT EXISTS(
    SELECT 1 FROM public.customer_contact t JOIN public."case" c ON c.customer_id=t.customer_id
      WHERE t.id=NEW.to_contact_id AND c.id=NEW.case_id) THEN
    RAISE EXCEPTION '收件人與案件客戶不一致'; END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS switchboard_no_leak ON public.outbound_message;
CREATE TRIGGER switchboard_no_leak BEFORE INSERT OR UPDATE ON public.outbound_message
FOR EACH ROW EXECUTE FUNCTION public.switchboard_outbound_guard();

-- 相容既有組織隔離欄位；不變更既有預設值、外鍵或資料。
ALTER TABLE public.client_communication ADD COLUMN IF NOT EXISTS org_id text NOT NULL DEFAULT 'YX';
ALTER TABLE public.client_commitment ADD COLUMN IF NOT EXISTS org_id text NOT NULL DEFAULT 'YX';
ALTER TABLE public.outbound_message ADD COLUMN IF NOT EXISTS org_id text NOT NULL DEFAULT 'YX';

CREATE OR REPLACE VIEW public.customer_behavior_v AS
WITH stats AS (
 SELECT customer_id,count(*) FILTER(WHERE kind='price_discount') AS discount_count,
 avg(discount_percent) FILTER(WHERE kind='price_discount') AS avg_discount_percent,
 avg(greatest(0,fulfilled_at::date-due_date)) FILTER(WHERE kind='document_due' AND fulfilled_at IS NOT NULL) AS avg_document_delay_days,
 count(*) FILTER(WHERE kind IN ('scope_add','change_order')) AS scope_count,
 count(*) FILTER(WHERE kind IN ('scope_add','change_order') AND status NOT IN ('confirmed_by_client','fulfilled','withdrawn')) AS unsigned_scope_count
 FROM public.client_commitment GROUP BY customer_id
), payments AS (
 SELECT customer_id,avg(greatest(0,CURRENT_DATE-due_date)) FILTER(WHERE paid_amount<total_amount) AS avg_unpaid_overdue_days
 FROM public.invoice GROUP BY customer_id
), paid_delays AS (
 SELECT i.customer_id,avg(greatest(0,p.last_received_date-i.due_date)) AS avg_payment_delay_days
 FROM public.invoice i JOIN (
   SELECT invoice_id,max(received_date) AS last_received_date,sum(amount_twd) AS received_total
   FROM public.payment_receipt GROUP BY invoice_id
 ) p ON p.invoice_id=i.id WHERE p.received_total>=i.total_amount GROUP BY i.customer_id
)
SELECT c.id AS customer_id,c.name,coalesce(s.discount_count,0) AS discount_count,
 s.avg_discount_percent,s.avg_document_delay_days,
 s.unsigned_scope_count::numeric/nullif(s.scope_count,0) AS unsigned_scope_rate,
 p.avg_unpaid_overdue_days,d.avg_payment_delay_days
FROM public.customer c LEFT JOIN stats s ON s.customer_id=c.id LEFT JOIN payments p ON p.customer_id=c.id
 LEFT JOIN paid_delays d ON d.customer_id=c.id;

-- 其他遷移可能已擴充時間線；重跑不得刪除其新增欄位。
DO $$ BEGIN
IF (SELECT count(*) FROM information_schema.columns
    WHERE table_schema='public' AND table_name='case_timeline_v') <= 9 THEN
EXECUTE $view$CREATE OR REPLACE VIEW public.case_timeline_v AS
SELECT c.case_id,c.customer_id,c.occurred_at,'communication'::text AS event_type,c.id AS event_id,
 c.body_text AS description,NULL::text AS status,c.thread_key,c.serial_no
FROM public.client_communication c
UNION ALL
SELECT k.case_id,k.customer_id,c.occurred_at,'commitment',k.id,k.description,k.status,c.thread_key,c.serial_no
FROM public.client_commitment k JOIN public.client_communication c ON c.id=k.source_comm_id$view$;
END IF;
END $$;

CREATE OR REPLACE VIEW public.settlement_commitment_v AS
SELECT k.id,k.source_comm_id,k.case_id,k.quote_id,k.customer_id,k.contact_id,k.party,k.kind,
 k.description,k.quantity,k.unit,k.amount_twd,k.due_date,k.fulfilled_at,k.discount_percent,k.status,
 k.written_confirm_comm_id,k.linked_contract_item_id,k.owner_employee_id,
 c.channel AS source_channel,c.serial_no,
 (k.written_confirm_comm_id IS NOT NULL) AS has_written_shadow,
 (k.status='confirmed_by_client') AS client_confirmed,
 (k.status IN ('stated','written_confirm_sent') AND c.occurred_at<now()-interval '48 hours') AS needs_48h_followup,
 (k.kind IN ('scope_add','change_order') AND k.linked_contract_item_id IS NULL) AS needs_provisional_contract_item
FROM public.client_commitment k JOIN public.client_communication c ON c.id=k.source_comm_id
WHERE k.party='client' AND k.kind IN ('scope_add','change_order') AND k.status<>'withdrawn';
-- GENERATED_PLAYBOOKS
INSERT INTO public.email_playbook_rag(category_id,name_zh,reply_template,keywords,rules,source_refs,legacy_playbook_refs,grounded_thread_ids,example_status,sla_hours,requires_human) VALUES('CAT-01','詢價、招標、議價與報價單往來 (RFQ, Tendering, Price Negotiation & Quote Confirmation)','{{client_name}}您好，已收到 {{case_code}} 詢價。報價編號 {{quote_no}}，請確認範圍及規格；核准版 {{approved_version}} 將由經辦查核。
{{pm_name}}','["詢價", "报价", "報價", "報編", "議價", "招標", "rfq", "quotation"]'::jsonb,'["詢價/報價回傳須核實quote與核版文件；基本資料、詢價回覆-修、PM報價回傳回覆僅知範本名稱，未取得Gmail範本原文"]'::jsonb,'["/workspace/yongxiang_arch/w0_reports/08_email_3to5yr_taxonomy_audit.json", "/workspace/yongxiang_arch/w0_reports/08_email_3to5yr_taxonomy_audit.md", "/workspace/yongxiang_arch/PLUMB_V2_CLIENT_COMM_HARMONY_SPEC_R28.md"]'::jsonb,'[{"path": "/workspace/yongxiang_arch/email_harmony_rag/playbooks.json", "intent_code": "QUOTE", "reply_template_sha256": "cbb25e7b7a6a1ddc9d974c37b4e3ab5bb6bcd033592c908a9f751de2ad24c979"}]'::jsonb,'["QUhEMUJzRGtJNUpLOGdyZytJRVBkNytTRFlBPQ=="]'::jsonb,'GROUNDED',24,true) ON CONFLICT(category_id) DO UPDATE SET name_zh=excluded.name_zh,reply_template=excluded.reply_template,keywords=excluded.keywords,rules=excluded.rules,source_refs=excluded.source_refs,legacy_playbook_refs=excluded.legacy_playbook_refs,grounded_thread_ids=excluded.grounded_thread_ids,example_status=excluded.example_status,sla_hours=excluded.sla_hours,requires_human=excluded.requires_human;
INSERT INTO public.email_playbook_rag(category_id,name_zh,reply_template,keywords,rules,source_refs,legacy_playbook_refs,grounded_thread_ids,example_status,sla_hours,requires_human) VALUES('CAT-02','測量成果提送、階段報告與施工日報繳交 (Survey Deliverables, Interim/Final Reports & Daily Logs)','{{client_name}}您好，附件提供 {{case_code}} 核准成果 {{approved_version}}。交付清單：{{deliverable_list}}。如需修正請標示圖號、頁次。
{{pm_name}}','["成果提供", "成果資料", "成果交付", "成果圖", "成果图", "成果提送", "日報提供", "期中成果", "期末成果", "舊成果"]'::jsonb,'["⛔入帳後再寄出：未核實付款不得交付", "台塑/麥電禁止外網連結；核准檔案依業主上限拆檔或紙本/光碟", "成果PDF/DWG/照片清單由核版資料確認"]'::jsonb,'["/workspace/yongxiang_arch/w0_reports/08_email_3to5yr_taxonomy_audit.json", "/workspace/yongxiang_arch/w0_reports/08_email_3to5yr_taxonomy_audit.md", "/workspace/yongxiang_arch/PLUMB_V2_CLIENT_COMM_HARMONY_SPEC_R28.md"]'::jsonb,'[{"path": "/workspace/yongxiang_arch/email_harmony_rag/playbooks.json", "intent_code": "DELIVERABLE", "reply_template_sha256": "89e6a63c39fc7b0bb2691cc0ab6c3e6589110b4307776ad6370385657c67462d"}]'::jsonb,'[]'::jsonb,'NO_EXAMPLE',24,true) ON CONFLICT(category_id) DO UPDATE SET name_zh=excluded.name_zh,reply_template=excluded.reply_template,keywords=excluded.keywords,rules=excluded.rules,source_refs=excluded.source_refs,legacy_playbook_refs=excluded.legacy_playbook_refs,grounded_thread_ids=excluded.grounded_thread_ids,example_status=excluded.example_status,sla_hours=excluded.sla_hours,requires_human=excluded.requires_human;
INSERT INTO public.email_playbook_rag(category_id,name_zh,reply_template,keywords,rules,source_refs,legacy_playbook_refs,grounded_thread_ids,example_status,sla_hours,requires_human) VALUES('CAT-03','審查意見回覆、成果修正、建築線補正與施測異常重測 (Review Comments, Deliverable Revisions, Building Line Corrections & Re-survey)','{{client_name}}您好，關於 {{case_code}}，逐條審查意見回覆如下：
{{review_rows}}
修正版 {{approved_version}} 待查核。
{{pm_name}}','["審查", "修正", "補正", "退件", "不符合規範", "重測", "jsa"]'::jsonb,'["高鐵逐條意見/回覆/頁碼/圖號；未有複測證據不可宣稱完成", "台塑/南亞JSA教育訓練日期不得早於審查完成日並附彩色照片"]'::jsonb,'["/workspace/yongxiang_arch/w0_reports/08_email_3to5yr_taxonomy_audit.json", "/workspace/yongxiang_arch/w0_reports/08_email_3to5yr_taxonomy_audit.md", "/workspace/yongxiang_arch/PLUMB_V2_CLIENT_COMM_HARMONY_SPEC_R28.md"]'::jsonb,'[{"path": "/workspace/yongxiang_arch/email_harmony_rag/playbooks.json", "intent_code": "DELIVERABLE", "reply_template_sha256": "89e6a63c39fc7b0bb2691cc0ab6c3e6589110b4307776ad6370385657c67462d"}, {"path": "/workspace/yongxiang_arch/email_harmony_rag/playbooks.json", "intent_code": "COMPLIANCE", "reply_template_sha256": "f9c8781404e8a8e34fa142af07575228d66d37a323da323d333011c58c696a59"}]'::jsonb,'[]'::jsonb,'NO_EXAMPLE',24,true) ON CONFLICT(category_id) DO UPDATE SET name_zh=excluded.name_zh,reply_template=excluded.reply_template,keywords=excluded.keywords,rules=excluded.rules,source_refs=excluded.source_refs,legacy_playbook_refs=excluded.legacy_playbook_refs,grounded_thread_ids=excluded.grounded_thread_ids,example_status=excluded.example_status,sla_hours=excluded.sla_hours,requires_human=excluded.requires_human;
INSERT INTO public.email_playbook_rag(category_id,name_zh,reply_template,keywords,rules,source_refs,legacy_playbook_refs,grounded_thread_ids,example_status,sla_hours,requires_human) VALUES('CAT-04','工務行政：出入廠申請、高鐵夜間違規/軌道作業核准、無人機空域與職安教育訓練 (Site Access Permits, Track/Airspace Approvals, EHS Training & Daily Headcount)','{{client_name}}您好，關於 {{case_code}} 入廠/作業申請，請查核 {{permit_details}}，進場條件須待核准。
{{pm_name}}','["出入廠", "入廠", "入厂", "作業申請", "職安", "空域", "hsror", "進場", "进场", "核准通知"]'::jsonb,'["台塑出廠日期原則5工作天內；效期、保險與訓練須查核", "高鐵HSROR/作業核准及無人機空域許可須綁案件日期；不自動寫預排"]'::jsonb,'["/workspace/yongxiang_arch/w0_reports/08_email_3to5yr_taxonomy_audit.json", "/workspace/yongxiang_arch/w0_reports/08_email_3to5yr_taxonomy_audit.md", "/workspace/yongxiang_arch/PLUMB_V2_CLIENT_COMM_HARMONY_SPEC_R28.md"]'::jsonb,'[{"path": "/workspace/yongxiang_arch/email_harmony_rag/playbooks.json", "intent_code": "FIELD", "reply_template_sha256": "8751132bf544f43e591cd9da2c34df86a264105f70d6415506491b4b14c0c7a4"}, {"path": "/workspace/yongxiang_arch/email_harmony_rag/playbooks.json", "intent_code": "COMPLIANCE", "reply_template_sha256": "f9c8781404e8a8e34fa142af07575228d66d37a323da323d333011c58c696a59"}]'::jsonb,'[]'::jsonb,'NO_EXAMPLE',24,true) ON CONFLICT(category_id) DO UPDATE SET name_zh=excluded.name_zh,reply_template=excluded.reply_template,keywords=excluded.keywords,rules=excluded.rules,source_refs=excluded.source_refs,legacy_playbook_refs=excluded.legacy_playbook_refs,grounded_thread_ids=excluded.grounded_thread_ids,example_status=excluded.example_status,sla_hours=excluded.sla_hours,requires_human=excluded.requires_human;
INSERT INTO public.email_playbook_rag(category_id,name_zh,reply_template,keywords,rules,source_refs,legacy_playbook_refs,grounded_thread_ids,example_status,sla_hours,requires_human) VALUES('CAT-05','契約工作指示單、決標通知、開工/會勘通知與電子公文催收 (Contract Work Orders, Award Notices, Site Inspections & Official e-Documents)','{{client_name}}您好，關於 {{case_code}} 合約 {{contract_no}} 工單 {{work_order_no}} 已收悉。待確認事項：{{pending_items}}；範圍與期限請雙方核實。
{{pm_name}}','["契約工作指示單", "決標", "開工", "會勘", "公文", "合約", "合同", "用印", "簽回", "contract", "加測", "追加", "口頭承諾"]'::jsonb,'["高鐵PCDL-25-0376/0089開口合約核對母案、工單、子案、餘額及期限", "契約/追加/折扣/變更由PM以上核准，不自動成案或改契約"]'::jsonb,'["/workspace/yongxiang_arch/w0_reports/08_email_3to5yr_taxonomy_audit.json", "/workspace/yongxiang_arch/w0_reports/08_email_3to5yr_taxonomy_audit.md", "/workspace/yongxiang_arch/PLUMB_V2_CLIENT_COMM_HARMONY_SPEC_R28.md"]'::jsonb,'[{"path": "/workspace/yongxiang_arch/email_harmony_rag/playbooks.json", "intent_code": "CONTRACT", "reply_template_sha256": "1afe4aab8903eefcc0a0bb62e13dd04ddeac043688b2aae754eb326f4ac7c2c7"}]'::jsonb,'["Ym9JOFJqOW1RRVY0Rm1XU2RTU1kvWkN5K1VnPQ=="]'::jsonb,'GROUNDED',24,true) ON CONFLICT(category_id) DO UPDATE SET name_zh=excluded.name_zh,reply_template=excluded.reply_template,keywords=excluded.keywords,rules=excluded.rules,source_refs=excluded.source_refs,legacy_playbook_refs=excluded.legacy_playbook_refs,grounded_thread_ids=excluded.grounded_thread_ids,example_status=excluded.example_status,sla_hours=excluded.sla_hours,requires_human=excluded.requires_human;
INSERT INTO public.email_playbook_rag(category_id,name_zh,reply_template,keywords,rules,source_refs,legacy_playbook_refs,grounded_thread_ids,example_status,sla_hours,requires_human) VALUES('CAT-06','驗收核決、計價數量確認、請款通知與銀行入帳/電子發票 (Acceptance, Billing Quantity Confirmation, Invoicing & Payment Remittance)','{{client_name}}您好，關於 {{case_code}} 帳務文件 {{invoice_no}}，品名 {{invoice_item}}，請確認收件與處理狀態，核准版 {{approved_version}} 由財務查核。
{{pm_name}}','["驗收", "計價", "請款", "發票", "发票", "invoice", "payment", "入帳", "付款", "收款", "帳款"]'::jsonb,'["中華工程發票10–20日；品名嚴格為合約編號+合約名稱+第X期計價", "估驗單、計價單一式二份；蓋合約計價及領款章（大小章）", "台塑依工程編號至電子採購網請款；金額須核報價/發票"]'::jsonb,'["/workspace/yongxiang_arch/w0_reports/08_email_3to5yr_taxonomy_audit.json", "/workspace/yongxiang_arch/w0_reports/08_email_3to5yr_taxonomy_audit.md", "/workspace/yongxiang_arch/PLUMB_V2_CLIENT_COMM_HARMONY_SPEC_R28.md"]'::jsonb,'[{"path": "/workspace/yongxiang_arch/email_harmony_rag/playbooks.json", "intent_code": "BILLING", "reply_template_sha256": "c4bbed10e53f9970a3b359d8720ca51220ead7b5b634873abe2ada2e3b69ee92"}]'::jsonb,'["WDNoZmxzdFgxNzhqK3o4STd6UmhpTThCcjl3PQ==", "ZEVOM1ZuRGE2NzVkcWdFT0JIVm9hOVdQbU1JPQ==", "aG1VTWFDNG5kR0V0N2l0MVJaVEtKc3g2NkJjPQ=="]'::jsonb,'GROUNDED',24,true) ON CONFLICT(category_id) DO UPDATE SET name_zh=excluded.name_zh,reply_template=excluded.reply_template,keywords=excluded.keywords,rules=excluded.rules,source_refs=excluded.source_refs,legacy_playbook_refs=excluded.legacy_playbook_refs,grounded_thread_ids=excluded.grounded_thread_ids,example_status=excluded.example_status,sla_hours=excluded.sla_hours,requires_human=excluded.requires_human;
INSERT INTO public.email_playbook_rag(category_id,name_zh,reply_template,keywords,rules,source_refs,legacy_playbook_refs,grounded_thread_ids,example_status,sla_hours,requires_human) VALUES('CAT-07','下包廠商/地政士請款、代墊規費與外包詢報價 (Subcontractor Billing, Land Scrivener Fees & Vendor Quotes)','{{client_name}}您好，已收到 {{case_code}} 下包/代墊資料，請協助補齊 {{pending_items}}；交易與金額由財務查核。
{{pm_name}}','["下包", "地政士", "代墊", "小柯", "展洲", "世和"]'::jsonb,'["先區分應收與應付；下包/地政士代墊須核交易與單據，不輸出我方成本"]'::jsonb,'["/workspace/yongxiang_arch/w0_reports/08_email_3to5yr_taxonomy_audit.json", "/workspace/yongxiang_arch/w0_reports/08_email_3to5yr_taxonomy_audit.md", "/workspace/yongxiang_arch/PLUMB_V2_CLIENT_COMM_HARMONY_SPEC_R28.md"]'::jsonb,'[{"path": "/workspace/yongxiang_arch/email_harmony_rag/playbooks.json", "intent_code": "BILLING", "reply_template_sha256": "c4bbed10e53f9970a3b359d8720ca51220ead7b5b634873abe2ada2e3b69ee92"}, {"path": "/workspace/yongxiang_arch/email_harmony_rag/playbooks.json", "intent_code": "QUOTE", "reply_template_sha256": "cbb25e7b7a6a1ddc9d974c37b4e3ab5bb6bcd033592c908a9f751de2ad24c979"}]'::jsonb,'[]'::jsonb,'NO_EXAMPLE',24,true) ON CONFLICT(category_id) DO UPDATE SET name_zh=excluded.name_zh,reply_template=excluded.reply_template,keywords=excluded.keywords,rules=excluded.rules,source_refs=excluded.source_refs,legacy_playbook_refs=excluded.legacy_playbook_refs,grounded_thread_ids=excluded.grounded_thread_ids,example_status=excluded.example_status,sla_hours=excluded.sla_hours,requires_human=excluded.requires_human;
INSERT INTO public.email_playbook_rag(category_id,name_zh,reply_template,keywords,rules,source_refs,legacy_playbook_refs,grounded_thread_ids,example_status,sla_hours,requires_human) VALUES('CAT-08','海事工程、離岸風電、無人船/水下設備跨國採購與報關物流 (Offshore Wind, Marine Survey, USV/ROV International Procurement & DHL Customs)','{{client_name}}您好，關於 {{case_code}} 海事設備與物流，請確認 {{pending_items}}。費用及責任條款待主管核實。
{{pm_name}}','["海事", "離岸", "rov", "usv", "dhl", "報關", "报关", "订单发货", "訂單出貨", "裝箱"]'::jsonb,'["海事/離岸/USV/ROV/報關與採購責任、費用人工查核；不採信未核對銀行帳號"]'::jsonb,'["/workspace/yongxiang_arch/w0_reports/08_email_3to5yr_taxonomy_audit.json", "/workspace/yongxiang_arch/w0_reports/08_email_3to5yr_taxonomy_audit.md", "/workspace/yongxiang_arch/PLUMB_V2_CLIENT_COMM_HARMONY_SPEC_R28.md"]'::jsonb,'[{"path": "/workspace/yongxiang_arch/email_harmony_rag/playbooks.json", "intent_code": "PROCUREMENT_LOGISTICS", "reply_template_sha256": "b99d3391a52af017211a27fed6eaa0fe6bcab49e752aaaa101f409d48a0dd58f"}, {"path": "/workspace/yongxiang_arch/email_harmony_rag/playbooks.json", "intent_code": "QUOTE", "reply_template_sha256": "cbb25e7b7a6a1ddc9d974c37b4e3ab5bb6bcd033592c908a9f751de2ad24c979"}]'::jsonb,'["eVN5djdpcGxobnZsSHp0YXBROTYxakJQUUNRPQ=="]'::jsonb,'GROUNDED',24,true) ON CONFLICT(category_id) DO UPDATE SET name_zh=excluded.name_zh,reply_template=excluded.reply_template,keywords=excluded.keywords,rules=excluded.rules,source_refs=excluded.source_refs,legacy_playbook_refs=excluded.legacy_playbook_refs,grounded_thread_ids=excluded.grounded_thread_ids,example_status=excluded.example_status,sla_hours=excluded.sla_hours,requires_human=excluded.requires_human;
INSERT INTO public.email_playbook_rag(category_id,name_zh,reply_template,keywords,rules,source_refs,legacy_playbook_refs,grounded_thread_ids,example_status,sla_hours,requires_human) VALUES('CAT-09','人力資源：104/1111 應徵履歷、配對推薦、勞健保帳單與培訓機構 (HR Recruitment, Job Bank Resumes, Labor/Health Insurance & Training Centers)','[MASKED_HR_PRIVATE]；僅限授權人資人工處理，禁止對外放行。','["104", "1111", "履歷", "履历", "應徵", "招聘", "招募", "薪資", "salary", "勞保", "健保"]'::jsonb,'["人資/履歷與薪酬隔離；[MASKED_HR_PRIVATE]，不自動外發"]'::jsonb,'["/workspace/yongxiang_arch/w0_reports/08_email_3to5yr_taxonomy_audit.json", "/workspace/yongxiang_arch/w0_reports/08_email_3to5yr_taxonomy_audit.md", "/workspace/yongxiang_arch/PLUMB_V2_CLIENT_COMM_HARMONY_SPEC_R28.md"]'::jsonb,'[{"path": "/workspace/yongxiang_arch/email_harmony_rag/playbooks.json", "intent_code": "HR_ADMIN", "reply_template_sha256": "986281fc9165a07a5a27e92a7ae3c107f5f9e5e26815a89803d38bab0c67039b"}]'::jsonb,'["OThkYjg1N2MtMDkwYS00OTZkLThjNTItMzc2MTAyNTQ4NmRl", "cWE3SmtnZ1BzZzN1dXVMY3paSkhoMUVvcVlBPQ=="]'::jsonb,'GROUNDED',48,true) ON CONFLICT(category_id) DO UPDATE SET name_zh=excluded.name_zh,reply_template=excluded.reply_template,keywords=excluded.keywords,rules=excluded.rules,source_refs=excluded.source_refs,legacy_playbook_refs=excluded.legacy_playbook_refs,grounded_thread_ids=excluded.grounded_thread_ids,example_status=excluded.example_status,sla_hours=excluded.sla_hours,requires_human=excluded.requires_human;
INSERT INTO public.email_playbook_rag(category_id,name_zh,reply_template,keywords,rules,source_refs,legacy_playbook_refs,grounded_thread_ids,example_status,sla_hours,requires_human) VALUES('CAT-10','系統驗證碼 (OTP)、氣象警報、公協會活動與行銷電子報 (System OTPs, Weather Alerts, Association Newsletters & Marketing Noise)','系統通知待管理員查核；e-GNSS 驗證碼不對外回覆。','["驗證碼", "confirmation code", "verification code", "password", "登入", "login", "氣象", "警報", "newsletter", "welcome", "secure link"]'::jsonb,'["e-GNSS/EBCS驗證碼為敏感系統事件；本MVP遮蔽且不推播、不回覆", "氣象/行銷/無法分類只入待確認佇列"]'::jsonb,'["/workspace/yongxiang_arch/w0_reports/08_email_3to5yr_taxonomy_audit.json", "/workspace/yongxiang_arch/w0_reports/08_email_3to5yr_taxonomy_audit.md", "/workspace/yongxiang_arch/PLUMB_V2_CLIENT_COMM_HARMONY_SPEC_R28.md"]'::jsonb,'[{"path": "/workspace/yongxiang_arch/email_harmony_rag/playbooks.json", "intent_code": "HR_ADMIN", "reply_template_sha256": "986281fc9165a07a5a27e92a7ae3c107f5f9e5e26815a89803d38bab0c67039b"}, {"path": "/workspace/yongxiang_arch/email_harmony_rag/playbooks.json", "intent_code": "OTHER", "reply_template_sha256": "41948a21a4f697256a2055d75b48ce08a662c31e325e58a0c4299dd31a0a8a8a"}]'::jsonb,'["K2gvRU0wcWt3NlhKMTZBS1RRQVpuSnpDVnF3PQ==", "MDhCMHVZdnRlcHBiMGNPelFkM1dialBFTDFFPQ==", "MWhoQzJteVZvdzQxellPOFJCN1c0ZCtqQ3NzPQ=="]'::jsonb,'GROUNDED',48,true) ON CONFLICT(category_id) DO UPDATE SET name_zh=excluded.name_zh,reply_template=excluded.reply_template,keywords=excluded.keywords,rules=excluded.rules,source_refs=excluded.source_refs,legacy_playbook_refs=excluded.legacy_playbook_refs,grounded_thread_ids=excluded.grounded_thread_ids,example_status=excluded.example_status,sla_hours=excluded.sla_hours,requires_human=excluded.requires_human;
COMMIT;
