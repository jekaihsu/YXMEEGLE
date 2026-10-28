-- ============================================================================
-- Fable 5.1 R29 + R29-PSTACK 6 Structural Locks (/correct & /statechart)
-- Strictly in `public` schema. Never touches `dim.*` (5) or `fact.*` (5).
-- Standalone R29 migration over the existing R28/MVP public tables.
-- Laptop: psql -X -v ON_ERROR_STOP=1 -d yongxiang_unified_r23 -f r29_hardlocks.sql
-- No database name, filesystem dependency, extension, network call or real send.
-- Existing yongxiang org keys remain for R28 compatibility; new orgs are YX/SJ.
-- ============================================================================
BEGIN;
SELECT pg_advisory_xact_lock(1943, 12089);

-- ----------------------------------------------------------------------------
-- LOCK 4: CAT-09 Organization Isolation (`org`: YX 詠翔測量 / SJ 上準精密)
-- & Composite Foreign Keys (`(case_id, org_id)`) + Row-Locked Idempotent Serial
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.org (
  id text PRIMARY KEY,
  org_uuid uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
  name text NOT NULL UNIQUE,
  tax_id text UNIQUE
);

INSERT INTO public.org (id, org_uuid, name, tax_id) VALUES
  ('YX', '11111111-1111-4111-8111-111111111101', '詠翔測量工程有限公司', NULL),
  ('SJ', '11111111-1111-4111-8111-111111111102', '上準精密有限公司', NULL),
  ('yongxiang', '11111111-1111-4111-8111-111111111103', '詠翔測量(相容代碼)', NULL)
ON CONFLICT (id) DO NOTHING;

ALTER TABLE public.customer ADD COLUMN IF NOT EXISTS delivery_constraints jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE public.expense_line ADD COLUMN IF NOT EXISTS case_id uuid;
ALTER TABLE public.expense_line ADD COLUMN IF NOT EXISTS org_id text NOT NULL DEFAULT 'YX';
ALTER TABLE public.client_communication ADD COLUMN IF NOT EXISTS org_id text NOT NULL DEFAULT 'YX';
ALTER TABLE public.client_communication ADD COLUMN IF NOT EXISTS thread_fingerprint text;
ALTER TABLE public.outbound_message ADD COLUMN IF NOT EXISTS org_id text NOT NULL DEFAULT 'YX';
ALTER TABLE public.outbound_message ADD COLUMN IF NOT EXISTS idempotency_key text UNIQUE;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'public."case"'::regclass AND conname = 'case_id_org_uq') THEN
    ALTER TABLE public."case" ADD CONSTRAINT case_id_org_uq UNIQUE (id, org_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'public.invoice'::regclass AND conname = 'invoice_case_org_fk') THEN
    ALTER TABLE public.invoice ADD CONSTRAINT invoice_case_org_fk FOREIGN KEY (case_id, org_id) REFERENCES public."case"(id, org_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'public.expense_line'::regclass AND conname = 'expense_case_org_fk') THEN
    ALTER TABLE public.expense_line ADD CONSTRAINT expense_case_org_fk FOREIGN KEY (case_id, org_id) REFERENCES public."case"(id, org_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'public.client_communication'::regclass AND conname = 'comm_case_org_fk') THEN
    -- Existing cross-org rows must fail validation; never silently relabel evidence.
    ALTER TABLE public.client_communication ADD CONSTRAINT comm_case_org_fk FOREIGN KEY (case_id, org_id) REFERENCES public."case"(id, org_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'public.client_communication'::regclass AND conname = 'comm_fp_serial_uq') THEN
    ALTER TABLE public.client_communication ADD CONSTRAINT comm_fp_serial_uq UNIQUE (org_id, thread_fingerprint, serial_no);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.serial_allocator (
  org_id text PRIMARY KEY REFERENCES public.org(id),
  next_serial int NOT NULL DEFAULT 12085 CHECK (next_serial >= 12085)
);

INSERT INTO public.serial_allocator (org_id, next_serial) VALUES
  ('YX', 12085),
  ('SJ', 12085),
  ('yongxiang', 12085)
ON CONFLICT (org_id) DO NOTHING;

CREATE OR REPLACE FUNCTION public.assign_serial(p_org text, p_fp text) RETURNS int
LANGUAGE plpgsql AS $$
DECLARE s int;
BEGIN
  IF p_fp IS NULL OR btrim(p_fp)='' THEN RAISE EXCEPTION 'fingerprint required'; END IF;
  PERFORM 1 FROM public.serial_allocator WHERE org_id=p_org FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'unknown org_id: %',p_org; END IF;
  -- Check AFTER acquiring the common lock, including when another transaction just committed.
  SELECT serial_no INTO s FROM public.serial_assignment WHERE org_id=p_org AND fingerprint=p_fp;
  IF FOUND THEN RETURN s; END IF;
  SELECT serial_no::int INTO s FROM public.client_communication
    WHERE org_id=p_org AND thread_fingerprint=p_fp;
  IF NOT FOUND THEN
    UPDATE public.serial_allocator SET next_serial=next_serial+1 WHERE org_id=p_org
      RETURNING next_serial-1 INTO s;
  END IF;
  INSERT INTO public.serial_assignment(org_id,fingerprint,serial_no) VALUES(p_org,p_fp,s);
  RETURN s;
END $$;

-- ----------------------------------------------------------------------------
-- LOCK 1: `satcmd_guard()` (Anti-Prompt-Injection on Satellite Commands)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.email_mailbox (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  address text NOT NULL UNIQUE,
  role text NOT NULL CHECK (role IN ('switchboard','satellite','archive')),
  org_id text REFERENCES public.org(id),
  is_sending_allowed bool NOT NULL DEFAULT false
);

INSERT INTO public.email_mailbox (id, address, role, org_id, is_sending_allowed) VALUES
  ('22222222-2222-4222-8222-222222222201', 'yongxiang.ltd@gmail.com', 'switchboard', 'YX', true),
  ('22222222-2222-4222-8222-222222222202', 'yonginside@gmail.com', 'satellite', 'YX', false),
  ('22222222-2222-4222-8222-222222222203', 'yong.yx1101@gmail.com', 'satellite', 'YX', false),
  ('22222222-2222-4222-8222-222222222204', 'yong.yx1103@gmail.com', 'satellite', 'YX', false),
  ('22222222-2222-4222-8222-222222222205', 'archive@yxsurvey.com.tw', 'archive', 'YX', false)
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS public.email_message (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  mailbox_id uuid REFERENCES public.email_mailbox(id),
  gmail_id text,
  message_id text UNIQUE,
  in_reply_to text,
  "references" text[],
  from_addr text NOT NULL,
  to_addrs text[],
  cc_addrs text[],
  subject text,
  sent_at timestamptz NOT NULL DEFAULT now(),
  raw_mime_path text NOT NULL DEFAULT 'dry-run://unavailable',
  body_new_text text,
  body_hash text,
  quoted_duplicate_of uuid REFERENCES public.email_message(id),
  labels text[],
  is_internal_command bool NOT NULL DEFAULT false,
  sent_copy_verified bool NOT NULL DEFAULT false,
  dkim_pass bool NOT NULL DEFAULT false,
  spf_pass bool NOT NULL DEFAULT false,
  dkim_domain text,
  category text CHECK (category ~ '^CAT-(0[1-9]|10)$'),
  org_id text NOT NULL DEFAULT 'YX' REFERENCES public.org(id),
  customer_id uuid REFERENCES public.customer(id),
  case_id uuid REFERENCES public."case"(id),
  quote_id uuid REFERENCES public.quote(id),
  thread_id uuid,
  ingested_at timestamptz DEFAULT now()
);

ALTER TABLE public.client_communication ADD COLUMN IF NOT EXISTS email_message_id uuid REFERENCES public.email_message(id);

CREATE TABLE IF NOT EXISTS public.email_thread (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  root_message_id uuid REFERENCES public.email_message(id),
  subject_norm text,
  customer_id uuid REFERENCES public.customer(id),
  case_id uuid REFERENCES public."case"(id),
  org_id text REFERENCES public.org(id)
);

CREATE TABLE IF NOT EXISTS public.email_link (
  message_id uuid REFERENCES public.email_message(id),
  original_message_id uuid REFERENCES public.email_message(id),
  link_rule text CHECK (link_rule IN ('references','serial_no','quoted_hash')),
  confidence numeric(3,2),
  PRIMARY KEY (message_id, original_message_id)
);

CREATE TABLE IF NOT EXISTS public.email_attachment (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  message_id uuid REFERENCES public.email_message(id),
  filename text,
  mime text,
  sha256 text NOT NULL,
  bytes int,
  stored_path text,
  text_extracted text,
  is_sealed_deliverable bool NOT NULL DEFAULT false,
  UNIQUE (message_id, sha256)
);

CREATE TABLE IF NOT EXISTS public.email_switchboard_command (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_message_id uuid NOT NULL UNIQUE REFERENCES public.email_message(id),
  requester_employee_id uuid REFERENCES public.employee(id),
  parsed_to_contact_id uuid REFERENCES public.customer_contact(id),
  parsed_template_code text,
  instruction_block text NOT NULL,
  body_after_strip text NOT NULL,
  parse_confidence numeric(3,2),
  outbound_message_id uuid REFERENCES public.outbound_message(id),
  status text NOT NULL DEFAULT 'parsed' CHECK (status IN ('parsed','needs_contact','drafted','sent','rejected')),
  CONSTRAINT satcmd_source_chk CHECK (true)
);

CREATE OR REPLACE FUNCTION public.satcmd_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM public.email_message m
    JOIN public.email_mailbox b ON b.address=m.from_addr AND b.role='satellite' AND b.org_id=m.org_id
    JOIN public.satellite_sent_copy s ON s.mailbox_id=b.id AND s.message_id=m.message_id
    WHERE m.id=NEW.source_message_id AND m.dkim_spf_passed AND m.sent_copy_verified
  ) THEN RAISE EXCEPTION 'command source not an authenticated satellite with IMAP Sent Message-ID evidence'; END IF;
  IF NEW.requester_employee_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM public.employee WHERE id=NEW.requester_employee_id
      AND org_id=NEW.org_id AND identity_confirmed AND employment_status='active'
  ) THEN RAISE EXCEPTION 'requester not active and identity confirmed'; END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS satcmd_guard_trg ON public.email_switchboard_command;
CREATE TRIGGER satcmd_guard_trg
BEFORE INSERT OR UPDATE ON public.email_switchboard_command
FOR EACH ROW EXECUTE FUNCTION public.satcmd_guard();

-- ----------------------------------------------------------------------------
-- LOCK 3: `invoice_paid_v` + `bank_notice` + `receipt_allocation` + `receipt_reversal`
-- + `payment_instrument` (Uncleared checks do NOT unlock sealed deliverables!)
-- ----------------------------------------------------------------------------
ALTER TABLE public.invoice ADD COLUMN IF NOT EXISTS amount_due numeric(14,2);
UPDATE public.invoice SET amount_due = coalesce(total_amount, 0) WHERE amount_due IS NULL;
ALTER TABLE public.invoice ADD COLUMN IF NOT EXISTS bes_rules bool NOT NULL DEFAULT false;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'public.invoice'::regclass AND conname = 'invoice_bes_window_chk') THEN
    ALTER TABLE public.invoice ADD CONSTRAINT invoice_bes_window_chk
      CHECK (NOT bes_rules OR EXTRACT(day FROM issue_date) BETWEEN 10 AND 20);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.payment_instrument (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id text NOT NULL DEFAULT 'YX' REFERENCES public.org(id),
  customer_id uuid REFERENCES public.customer(id),
  instrument_type text NOT NULL CHECK (instrument_type IN ('wire','check','cash')),
  amount numeric(14,2) NOT NULL CHECK (amount > 0),
  status text NOT NULL DEFAULT 'received_uncleared' CHECK (status IN ('received_uncleared','cleared','bounced')),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.receipt_allocation (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  invoice_id uuid NOT NULL REFERENCES public.invoice(id),
  instrument_id uuid REFERENCES public.payment_instrument(id),
  amount numeric(14,2) NOT NULL CHECK (amount > 0),
  allocated_by uuid REFERENCES public.employee(id),
  allocated_at timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION public.receipt_allocation_cleared_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.instrument_id IS NOT NULL AND EXISTS (
    SELECT 1 FROM public.payment_instrument p
    WHERE p.id = NEW.instrument_id AND p.status <> 'cleared'
  ) THEN
    RAISE EXCEPTION 'payment_instrument status must be cleared (received_uncleared check cannot allocate/unlock)';
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS receipt_allocation_cleared_trg ON public.receipt_allocation;
CREATE TRIGGER receipt_allocation_cleared_trg
BEFORE INSERT OR UPDATE ON public.receipt_allocation
FOR EACH ROW EXECUTE FUNCTION public.receipt_allocation_cleared_guard();

CREATE TABLE IF NOT EXISTS public.receipt_reversal (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  allocation_id uuid NOT NULL REFERENCES public.receipt_allocation(id),
  amount numeric(14,2) NOT NULL CHECK (amount > 0),
  reason text NOT NULL DEFAULT 'check_bounce_or_reversal',
  reversed_at timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE VIEW public.invoice_paid_v AS
SELECT i.id, i.case_id, i.org_id,
       coalesce(i.amount_due, i.total_amount, 0) AS amount_due,
       coalesce(i.amount_due, i.total_amount, 0) - a.total + r.total AS unpaid_amount,
       (coalesce(i.amount_due, i.total_amount, 0) - a.total + r.total = 0) AS paid
FROM public.invoice i
CROSS JOIN LATERAL (
  SELECT coalesce(sum(a.amount),0) AS total
  FROM public.receipt_allocation a
  LEFT JOIN public.payment_instrument p ON p.id=a.instrument_id
  WHERE a.invoice_id=i.id AND (a.instrument_id IS NULL OR p.status='cleared')
) a
CROSS JOIN LATERAL (
  SELECT coalesce(sum(r.amount),0) AS total
  FROM public.receipt_reversal r JOIN public.receipt_allocation a ON a.id=r.allocation_id
  WHERE a.invoice_id=i.id
) r;

CREATE TABLE IF NOT EXISTS public.bank_notice (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email_message_id uuid REFERENCES public.email_message(id),
  bank text,
  amount numeric(14,2),
  masked_tax_id text,
  value_date date,
  matched_customer_id uuid REFERENCES public.customer(id),
  candidate_invoice_ids uuid[],
  status text NOT NULL DEFAULT 'candidate' CHECK (status IN ('candidate','allocated','rejected')),
  allocated_receipt_id uuid REFERENCES public.receipt_allocation(id)
);

CREATE TABLE IF NOT EXISTS public.deliverable_release_gate (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id uuid NOT NULL REFERENCES public."case"(id),
  milestone text NOT NULL,
  deliverable_class text NOT NULL CHECK (deliverable_class IN ('preview','sealed')),
  invoice_id uuid REFERENCES public.invoice(id),
  override_by uuid REFERENCES public.employee(id),
  override_reason text,
  override_expires_at timestamptz,
  CHECK (
    deliverable_class = 'preview'
    OR invoice_id IS NOT NULL
    OR (override_by IS NOT NULL AND override_reason IS NOT NULL AND override_expires_at IS NOT NULL)
  )
);

CREATE OR REPLACE FUNCTION public.sealed_release_allowed(p_case uuid, p_milestone text) RETURNS bool
LANGUAGE sql VOLATILE AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.deliverable_release_gate g
    LEFT JOIN public.invoice_paid_v iv ON iv.id = g.invoice_id AND iv.case_id = g.case_id
    WHERE g.case_id = p_case
      AND g.milestone = p_milestone
      AND g.deliverable_class = 'sealed'
      AND (
        coalesce(iv.paid, false) = true
        OR (g.override_by IS NOT NULL AND g.override_expires_at > now())
      )
  )
$$;

-- ----------------------------------------------------------------------------
-- LOCK 2: `outbound_guard()` + `outbound_send()` + `deliverable_version` / `quote_version` FKs
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.deliverable_version (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id uuid NOT NULL REFERENCES public."case"(id),
  milestone text NOT NULL DEFAULT 'FINAL',
  version_no int NOT NULL DEFAULT 1,
  status text NOT NULL CHECK (status IN ('草稿','審核中','核定','已交付','退回')),
  is_sealed bool NOT NULL DEFAULT true,
  sha256 text NOT NULL,
  UNIQUE (id, status)
);

ALTER TABLE public.quote_version ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'approved';
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'public.quote_version'::regclass AND conname = 'quote_version_id_status_uq') THEN
    ALTER TABLE public.quote_version ADD CONSTRAINT quote_version_id_status_uq UNIQUE (id, status);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'public.customer_contact'::regclass AND conname = 'contact_id_customer_uq') THEN
    ALTER TABLE public.customer_contact ADD CONSTRAINT contact_id_customer_uq UNIQUE (id, customer_id);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.outbound_recipient (
  outbound_id uuid NOT NULL REFERENCES public.outbound_message(id) ON DELETE CASCADE,
  contact_id uuid NOT NULL REFERENCES public.customer_contact(id),
  case_id uuid REFERENCES public."case"(id),
  customer_id uuid NOT NULL REFERENCES public.customer(id),
  PRIMARY KEY (outbound_id, contact_id),
  FOREIGN KEY (contact_id, customer_id) REFERENCES public.customer_contact(id, customer_id)
);

CREATE TABLE IF NOT EXISTS public.outbound_attachment (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  outbound_id uuid NOT NULL REFERENCES public.outbound_message(id) ON DELETE CASCADE,
  deliverable_version_id uuid REFERENCES public.deliverable_version(id),
  quote_version_id uuid REFERENCES public.quote_version(id),
  deliverable_status text,
  quote_status text,
  CHECK ((deliverable_version_id IS NULL) <> (quote_version_id IS NULL)),
  FOREIGN KEY (deliverable_version_id, deliverable_status) REFERENCES public.deliverable_version(id, status),
  FOREIGN KEY (quote_version_id, quote_status) REFERENCES public.quote_version(id, status),
  CHECK (deliverable_status IS NULL OR deliverable_status IN ('核定','已交付')),
  CHECK (quote_status IS NULL OR quote_status = 'approved')
);

ALTER TABLE public.outbound_message ADD COLUMN IF NOT EXISTS mailbox_id uuid REFERENCES public.email_mailbox(id);
ALTER TABLE public.outbound_message ADD COLUMN IF NOT EXISTS second_approver_id uuid REFERENCES public.employee(id);
ALTER TABLE public.outbound_message ADD COLUMN IF NOT EXISTS release_gate_checked bool NOT NULL DEFAULT false;
ALTER TABLE public.outbound_message ADD COLUMN IF NOT EXISTS sent_by uuid REFERENCES public.employee(id);
ALTER TABLE public.outbound_message ADD COLUMN IF NOT EXISTS delivery_status text DEFAULT 'DRY_RUN';

CREATE OR REPLACE FUNCTION public.outbound_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  c record;
  combined_body text;
BEGIN
  combined_body := coalesce(NEW.draft_body, '') || E'\n' || coalesce(NEW.final_body, '');
  -- 1. First-line satellite command header leak & internal cost/margin forbidden words
  IF coalesce(NEW.final_body, '') ~ '(寄件人[:：]|收件人[:：]|麻煩幫我|請寄給|收到請登記|業主往來\d+|報編\d+|#\d+行政|給.+[，,]|成本|毛利|底價|A[ /-]*B[ /-]*C)' THEN
    RAISE EXCEPTION 'outbound contains internal/forbidden text';
  END IF;
  -- 2. Recipient must belong to case customer when case_id & to_contact_id are present
  IF NEW.to_contact_id IS NOT NULL AND NEW.case_id IS NOT NULL THEN
    IF NOT EXISTS (
      SELECT 1 FROM public.customer_contact ct
      JOIN public."case" cs ON cs.customer_id = ct.customer_id
      WHERE ct.id = NEW.to_contact_id AND cs.id = NEW.case_id
    ) THEN
      RAISE EXCEPTION 'recipient not of this case customer';
    END IF;
  END IF;
  -- Customer restrictions apply even while a draft has no resolved contact.
  IF EXISTS (
    SELECT 1 FROM public.customer cust
    WHERE (cust.id=(SELECT customer_id FROM public.customer_contact WHERE id=NEW.to_contact_id)
        OR cust.id=(SELECT customer_id FROM public."case" WHERE id=NEW.case_id))
      AND coalesce((cust.delivery_constraints->>'no_links')::bool,false)
  ) AND combined_body ~* '(https?://|www[.]|href[[:space:]]*=|[a-z][a-z0-9+.-]*://)' THEN
    RAISE EXCEPTION 'customer forbids links';
  END IF;
  -- 4. Sealed deliverable attachment requires release_gate_checked
  IF NEW.status IN ('approved','sent') OR NEW.final_body IS NOT NULL THEN
    IF EXISTS (
      SELECT 1
      FROM public.outbound_attachment oa
      JOIN public.deliverable_version dv ON dv.id = oa.deliverable_version_id
      WHERE oa.outbound_id = NEW.id AND dv.is_sealed = true
    ) AND NOT coalesce(NEW.release_gate_checked, false) THEN
      RAISE EXCEPTION 'sealed deliverable requires release gate';
    END IF;
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS outbound_guard_trg ON public.outbound_message;
CREATE TRIGGER outbound_guard_trg
BEFORE INSERT OR UPDATE ON public.outbound_message
FOR EACH ROW EXECUTE FUNCTION public.outbound_guard();

CREATE OR REPLACE FUNCTION public.outbound_send(p_id uuid,p_actor uuid) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE o public.outbound_message;
BEGIN
  SELECT * INTO o FROM public.outbound_message WHERE id=p_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'outbound_message not found'; END IF;
  IF o.approved_by IS NULL OR o.approved_at IS NULL OR o.final_body IS NULL
     OR p_actor IS DISTINCT FROM o.approved_by THEN RAISE EXCEPTION 'not approved'; END IF;
  IF o.delivery_status='DRY_RUN_SEND_GATE_VERIFIED' THEN RAISE EXCEPTION 'already verified'; END IF;
  -- The same invoice rows are locked by allocation, reversal and instrument triggers.
  PERFORM 1 FROM public."case" WHERE id=o.case_id FOR UPDATE;
  PERFORM 1 FROM public.deliverable_release_gate g WHERE g.case_id=o.case_id ORDER BY g.id FOR UPDATE;
  PERFORM 1 FROM public.invoice i WHERE i.case_id=o.case_id ORDER BY i.id FOR UPDATE;
  IF EXISTS (
    SELECT 1 FROM public.outbound_attachment a
    JOIN public.deliverable_version d ON d.id=a.deliverable_version_id
    WHERE a.outbound_id=p_id AND d.is_sealed
      AND (d.case_id IS DISTINCT FROM o.case_id OR NOT public.sealed_release_allowed(d.case_id,d.milestone))
  ) THEN RAISE EXCEPTION 'hold_until_paid'; END IF;
  -- Existing MVP CHECKs enforce actual_sends=0, status=DRY_RUN and sent_at IS NULL.
  UPDATE public.outbound_message SET sent_by=p_actor,delivery_status='DRY_RUN_SEND_GATE_VERIFIED'
    WHERE id=p_id;
END $$;

-- ----------------------------------------------------------------------------
-- LOCK 5: CAT-10 e-GNSS / EBCS OTP Pull-Only (`otp_forward_rule` + `otp_request` + `otp_deliver()`)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.otp_forward_rule (
  id serial PRIMARY KEY,
  account_label text,
  sender_exact text NOT NULL,
  subject_regex text NOT NULL,
  code_regex text NOT NULL,
  ttl_minutes int NOT NULL DEFAULT 5,
  org_id text NOT NULL DEFAULT 'YX' REFERENCES public.org(id)
);

-- The same service sender may serve YX and SJ accounts independently.
ALTER TABLE public.otp_forward_rule DROP CONSTRAINT IF EXISTS otp_forward_rule_sender_exact_key;
CREATE UNIQUE INDEX IF NOT EXISTS otp_forward_rule_sender_org_uq
  ON public.otp_forward_rule(sender_exact,org_id);
INSERT INTO public.otp_forward_rule (account_label, sender_exact, subject_regex, code_regex, ttl_minutes, org_id) VALUES
  ('國土測繪中心 e-GNSS', 'egnss@mail.nlsc.gov.tw', '(驗證碼|verification|e-GNSS)', '[0-9]{6}', 5, 'YX'),
  ('台灣中油 EBCS', 'ebcsAdmin@cpc.com.tw', '(驗證碼|EBCS|登入)', '[0-9]{6}', 5, 'YX')
ON CONFLICT (sender_exact,org_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS public.otp_request (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  rule_id int NOT NULL REFERENCES public.otp_forward_rule(id),
  requester_employee_id uuid NOT NULL REFERENCES public.employee(id),
  requested_at timestamptz NOT NULL DEFAULT now(),
  fulfilled_message_id uuid REFERENCES public.email_message(id),
  delivered_at timestamptz,
  CHECK (delivered_at IS NULL OR delivered_at < requested_at + interval '5 minutes')
);

CREATE OR REPLACE FUNCTION public.otp_deliver(p_msg uuid) RETURNS uuid
LANGUAGE plpgsql AS $$
DECLARE m public.email_message; r public.otp_forward_rule; req public.otp_request; t timestamptz;
BEGIN
  -- One message cannot fulfill concurrent requests or be replayed to a second employee.
  SELECT * INTO m FROM public.email_message WHERE id=p_msg FOR UPDATE;
  IF NOT FOUND THEN RETURN NULL; END IF;
  t:=clock_timestamp();
  IF coalesce(m.subject,'')||E'\n'||coalesce(m.body_new_text,'') ~*
       '(password|reset|密碼|重設|銀行|轉帳|google|apple|tcb|mufg)' THEN RETURN NULL; END IF;
  SELECT * INTO r FROM public.otp_forward_rule
    WHERE sender_exact=m.from_addr AND org_id=m.org_id AND m.subject ~ subject_regex
      AND m.body_new_text ~ code_regex AND m.dkim_spf_passed
      AND m.dkim_domain=split_part(sender_exact,'@',2) ORDER BY id LIMIT 1;
  IF NOT FOUND OR m.sent_at>t OR m.sent_at<=t-interval '5 minutes'
     OR EXISTS(SELECT 1 FROM public.otp_request WHERE fulfilled_message_id=p_msg) THEN RETURN NULL; END IF;
  SELECT q.* INTO req FROM public.otp_request q JOIN public.employee e ON e.id=q.requester_employee_id
    WHERE q.rule_id=r.id AND q.org_id=m.org_id AND q.fulfilled_message_id IS NULL
      AND q.requested_at>t-interval '5 minutes' AND q.requested_at<=t AND m.sent_at>=q.requested_at
      AND e.employment_status='active' AND e.identity_confirmed AND e.org_id=q.org_id
    ORDER BY q.requested_at,q.id LIMIT 1 FOR UPDATE OF q;
  IF NOT FOUND THEN RETURN NULL; END IF;
  t:=clock_timestamp();
  IF t>=req.requested_at+interval '5 minutes' THEN RETURN NULL; END IF;
  UPDATE public.otp_request SET fulfilled_message_id=p_msg,delivered_at=t WHERE id=req.id;
  -- A private outbox row is the complete dry-run delivery contract; no group target exists.
  INSERT INTO public.otp_private_delivery(request_id,message_id,recipient_employee_id,org_id)
    VALUES(req.id,p_msg,req.requester_employee_id,req.org_id);
  RETURN req.requester_employee_id;
END $$;

-- ----------------------------------------------------------------------------
-- LOCK 6: `email_rag_chunk` (CAT-09 & CAT-10 Strictly Excluded) + `case_settlement` Gate
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.email_template (
  code text PRIMARY KEY,
  name text NOT NULL,
  subject_tpl text NOT NULL,
  body_tpl text NOT NULL,
  required_params text[] NOT NULL DEFAULT '{}',
  category text NOT NULL CHECK (category ~ '^CAT-(0[1-9]|10)$'),
  version int NOT NULL DEFAULT 1,
  active bool NOT NULL DEFAULT true
);

INSERT INTO public.email_template (code, name, subject_tpl, body_tpl, required_params, category) VALUES
  ('TPL_RFQ_REPLY', '詢價回覆-修', 'Re: {{case_code}} 測量詢價回覆（報編：{{quote_no}}）', '{{client_name}}您好，感謝詢價，檢附報價單 {{quote_no}} 請查照。', ARRAY['client_name','case_code','quote_no'], 'CAT-01'),
  ('TPL_BASIC_INFO', '基本資料', '詠翔測量工程有限公司 基本資料與匯款帳戶', '{{client_name}}您好，檢附本公司基本資料與國泰世華匯款帳戶影本。', ARRAY['client_name'], 'CAT-01'),
  ('TPL_QUOTE_RETURN_PM', '報價回傳回覆(專案經理：{{pm_name}})', 'Re: 【業主回傳】{{quote_no}} 報價確認與派工安排（專案經理：{{pm_name}}）', '{{client_name}}您好，已收到 {{quote_no}} 回傳確認單，本案由專案經理 {{pm_name}} 負責接洽。', ARRAY['client_name','quote_no','pm_name'], 'CAT-01'),
  ('TPL_DELIVERABLE_RELEASE', '測量成果提送', '({{deliverable_stage}}成果提供) {{case_code}} {{project_title}}', '{{client_name}}您好，檢附 {{case_code}} 核定版測量成果 {{approved_version}}。', ARRAY['client_name','case_code','deliverable_stage','project_title','approved_version'], 'CAT-02'),
  ('TPL_REVIEW_REPLY', '審查意見逐條回覆', 'Re: {{case_code}} 審查意見回覆與修正版提送', '{{client_name}}您好，針對 {{case_code}} 審查意見逐條回覆如下：\n{{review_rows}}', ARRAY['client_name','case_code','review_rows'], 'CAT-03'),
  ('TPL_PERMIT_APPLY', '出入廠與作業申請', '{{case_code}} 出入廠/作業核准申請資料提送', '{{client_name}}您好，檢附 {{case_code}} 入廠與職安申請明細 {{permit_details}}。', ARRAY['client_name','case_code','permit_details'], 'CAT-04'),
  ('TPL_BILLING_INVOICE', '計價請款與電子發票通知', '{{case_code}} 第{{period}}期計價請款與發票通知（{{invoice_no}}）', '{{client_name}}您好，檢附 {{case_code}} {{invoice_item}} 計價單與發票 {{invoice_no}}。', ARRAY['client_name','case_code','period','invoice_no','invoice_item'], 'CAT-06')
ON CONFLICT (code) DO NOTHING;

CREATE TABLE IF NOT EXISTS public.permit (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id text NOT NULL DEFAULT 'YX' REFERENCES public.org(id),
  kind text NOT NULL CHECK (kind IN ('fpg_entry','thsrc_work','uav_airspace','safety_card')),
  ref_no text,
  holder_employee_id uuid REFERENCES public.employee(id),
  vehicle_asset_id uuid,
  case_id uuid REFERENCES public."case"(id),
  issued_at date,
  valid_until date,
  workdays_limit int,
  email_message_id uuid REFERENCES public.email_message(id),
  status text NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS public.client_playbook_rule (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id text NOT NULL DEFAULT 'YX' REFERENCES public.org(id),
  customer_id uuid REFERENCES public.customer(id),
  scope text NOT NULL CHECK (scope IN ('customer','industry','global')),
  category text NOT NULL CHECK (category ~ '^CAT-(0[1-9]|10)$'),
  rule_text text NOT NULL,
  structured jsonb NOT NULL DEFAULT '{}'::jsonb,
  evidence_message_ids uuid[] NOT NULL DEFAULT '{}',
  confirmed_by uuid REFERENCES public.employee(id),
  active bool NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS public.email_rag_chunk (
  id bigserial PRIMARY KEY,
  message_id uuid REFERENCES public.email_message(id),
  attachment_id uuid REFERENCES public.email_attachment(id),
  org_id text NOT NULL DEFAULT 'YX' REFERENCES public.org(id),
  customer_id uuid REFERENCES public.customer(id),
  case_id uuid REFERENCES public."case"(id),
  quote_id uuid REFERENCES public.quote(id),
  category text NOT NULL CHECK (category ~ '^CAT-(0[1-9]|10)$'),
  direction text CHECK (direction IN ('inbound','outbound')),
  occurred_at timestamptz,
  chunk_no int NOT NULL,
  chunk_text text NOT NULL,
  content_hash text NOT NULL,
  embedding real[],
  UNIQUE (message_id, attachment_id, chunk_no),
  CONSTRAINT email_rag_chunk_no_cat09_cat10_chk CHECK (category NOT IN ('CAT-09','CAT-10'))
);

CREATE INDEX IF NOT EXISTS email_rag_chunk_meta ON public.email_rag_chunk (org_id, customer_id, category, occurred_at);

CREATE TABLE IF NOT EXISTS public.case_settlement (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id uuid NOT NULL UNIQUE REFERENCES public."case"(id),
  org_id text NOT NULL DEFAULT 'YX' REFERENCES public.org(id),
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','ready_for_vp','vp_signed','gm_signed')),
  updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.client_commitment DROP CONSTRAINT IF EXISTS client_commitment_status_check;
ALTER TABLE public.client_commitment ADD CONSTRAINT client_commitment_status_check
  CHECK (status IN ('stated','written_confirm_sent','written_sent','pending_confirm','confirmed','confirmed_by_client','confirmed_unlinked','confirmed_silent','disputed','fulfilled','breached','withdrawn'));

CREATE OR REPLACE FUNCTION public.settlement_gate() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.status IN ('ready_for_vp','vp_signed','gm_signed') AND EXISTS (
    SELECT 1
    FROM public.client_commitment k
    WHERE k.case_id = NEW.case_id
      AND k.party = 'client'
      AND k.status IN ('stated','written_confirm_sent','written_sent','pending_confirm','confirmed_unlinked')
  ) THEN
    RAISE EXCEPTION 'open client commitments block settlement';
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS settlement_gate_trg ON public.case_settlement;
CREATE TRIGGER settlement_gate_trg
BEFORE INSERT OR UPDATE OF status ON public.case_settlement
FOR EACH ROW EXECUTE FUNCTION public.settlement_gate();

CREATE OR REPLACE FUNCTION public.commitment_lock_on_settled_fn() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_settlement_status text;
BEGIN
  IF NEW.case_id IS NULL THEN
    RETURN NEW;
  END IF;
  SELECT status INTO v_settlement_status
  FROM public.case_settlement
  WHERE case_id = NEW.case_id
  FOR UPDATE;

  IF v_settlement_status IN ('vp_signed', 'gm_signed') THEN
    RAISE EXCEPTION 'cannot add or reopen client_commitment after settlement is signed';
  END IF;

  IF v_settlement_status = 'ready_for_vp'
     AND NEW.party = 'client'
     AND NEW.status NOT IN ('fulfilled', 'waived_by_jk', 'linked_to_change_order', 'withdrawn') THEN
    UPDATE public.case_settlement
    SET status = 'open', updated_at = now()
    WHERE case_id = NEW.case_id AND status = 'ready_for_vp';
  END IF;

  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS commitment_lock_on_settled_trg ON public.client_commitment;
CREATE TRIGGER commitment_lock_on_settled_trg
BEFORE INSERT OR UPDATE OF status, party, case_id ON public.client_commitment
FOR EACH ROW EXECUTE FUNCTION public.commitment_lock_on_settled_fn();



-- R29-PSTACK hardening of evidence, concurrency and privacy.
ALTER TABLE public.email_message ADD COLUMN IF NOT EXISTS dkim_spf_passed boolean
  GENERATED ALWAYS AS (dkim_pass AND spf_pass) STORED;
CREATE TABLE IF NOT EXISTS public.satellite_sent_copy (
  mailbox_id uuid NOT NULL REFERENCES public.email_mailbox(id),
  message_id text NOT NULL CHECK(btrim(message_id)<>''),
  imap_folder text NOT NULL CHECK(imap_folder IN ('Sent','[Gmail]/Sent Mail','INBOX.Sent')),
  uidvalidity bigint NOT NULL CHECK(uidvalidity>0),
  imap_uid bigint NOT NULL CHECK(imap_uid>0),
  verified_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY(mailbox_id,message_id)
);
COMMENT ON TABLE public.satellite_sent_copy IS
  'Trusted IMAP ingestor evidence only: exact Message-ID observed in the satellite Sent folder. No email-text or model writes.';
REVOKE ALL ON public.satellite_sent_copy FROM PUBLIC;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='app_rw') THEN
   REVOKE INSERT,UPDATE,DELETE ON public.satellite_sent_copy FROM app_rw;
 END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.serial_assignment (
  org_id text NOT NULL REFERENCES public.org(id), fingerprint text NOT NULL,
  serial_no int NOT NULL CHECK(serial_no>=12085),
  PRIMARY KEY(org_id,fingerprint), UNIQUE(org_id,serial_no)
);
ALTER TABLE public.client_communication DROP CONSTRAINT IF EXISTS client_communication_serial_no_key;
CREATE UNIQUE INDEX IF NOT EXISTS r29_comm_org_serial_uq ON public.client_communication(org_id,serial_no);
CREATE UNIQUE INDEX IF NOT EXISTS r29_comm_org_fp_uq ON public.client_communication(org_id,thread_fingerprint)
  WHERE thread_fingerprint IS NOT NULL;
UPDATE public.serial_allocator s SET next_serial=greatest(s.next_serial,12085,
  coalesce((SELECT max(serial_no)+1 FROM public.client_communication c WHERE c.org_id=s.org_id AND c.serial_no<=12084),12085),
  coalesce((SELECT max(serial_no)+1 FROM public.serial_assignment a WHERE a.org_id=s.org_id AND a.serial_no<=12084),12085))
WHERE s.next_serial < greatest(12085,
  coalesce((SELECT max(serial_no)+1 FROM public.client_communication c WHERE c.org_id=s.org_id AND c.serial_no<=12084),12085),
  coalesce((SELECT max(serial_no)+1 FROM public.serial_assignment a WHERE a.org_id=s.org_id AND a.serial_no<=12084),12085));

-- Every case-bearing R29 table carries org_id and a validated composite FK.
DO $$ DECLARE tab text; BEGIN
 FOREACH tab IN ARRAY ARRAY['outbound_message','email_message','email_thread','email_rag_chunk',
   'deliverable_release_gate','deliverable_version','permit','case_settlement','outbound_recipient','client_commitment'] LOOP
   EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS org_id text',tab);
   EXECUTE format('UPDATE public.%I t SET org_id=c.org_id FROM public."case" c WHERE t.case_id=c.id AND t.org_id IS NULL',tab);
   EXECUTE format('UPDATE public.%I SET org_id=''YX'' WHERE org_id IS NULL',tab);
   EXECUTE format('ALTER TABLE public.%I ALTER COLUMN org_id SET NOT NULL',tab);
   EXECUTE format('ALTER TABLE public.%I ALTER COLUMN org_id SET DEFAULT ''YX''',tab);
   IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid=format('public.%I',tab)::regclass AND conname='r29_case_org_fk') THEN
     EXECUTE format('ALTER TABLE public.%I ADD CONSTRAINT r29_case_org_fk FOREIGN KEY(case_id,org_id) REFERENCES public."case"(id,org_id)',tab);
   END IF;
 END LOOP;
END $$;
-- A release gate cannot use another case's paid invoice.
CREATE UNIQUE INDEX IF NOT EXISTS r29_invoice_id_case_uq ON public.invoice(id,case_id);
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='public.deliverable_release_gate'::regclass AND conname='r29_gate_invoice_case_fk') THEN
   ALTER TABLE public.deliverable_release_gate ADD CONSTRAINT r29_gate_invoice_case_fk
     FOREIGN KEY(invoice_id,case_id) REFERENCES public.invoice(id,case_id);
 END IF;
END $$;

CREATE OR REPLACE FUNCTION public.r29_receipt_lock() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE ids uuid[]:='{}'; a uuid;
BEGIN
 IF TG_TABLE_NAME='receipt_allocation' THEN
   IF TG_OP<>'DELETE' THEN ids:=array_append(ids,NEW.invoice_id); END IF;
   IF TG_OP<>'INSERT' THEN ids:=array_append(ids,OLD.invoice_id); END IF;
 ELSE
   IF TG_OP<>'DELETE' THEN
     SELECT invoice_id INTO a FROM public.receipt_allocation WHERE id=NEW.allocation_id;
     ids:=array_append(ids,a);
   END IF;
   IF TG_OP<>'INSERT' THEN
     SELECT invoice_id INTO a FROM public.receipt_allocation WHERE id=OLD.allocation_id;
     ids:=array_append(ids,a);
   END IF;
 END IF;
 PERFORM 1 FROM public.invoice WHERE id=ANY(ids) ORDER BY id FOR UPDATE;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS a_r29_receipt_lock ON public.receipt_allocation;
CREATE TRIGGER a_r29_receipt_lock BEFORE INSERT OR UPDATE OR DELETE ON public.receipt_allocation
 FOR EACH ROW EXECUTE FUNCTION public.r29_receipt_lock();
DROP TRIGGER IF EXISTS a_r29_receipt_lock ON public.receipt_reversal;
CREATE TRIGGER a_r29_receipt_lock BEFORE INSERT OR UPDATE OR DELETE ON public.receipt_reversal
 FOR EACH ROW EXECUTE FUNCTION public.r29_receipt_lock();
CREATE OR REPLACE FUNCTION public.r29_instrument_lock() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 PERFORM 1 FROM public.invoice i WHERE EXISTS(
   SELECT 1 FROM public.receipt_allocation a WHERE a.invoice_id=i.id AND a.instrument_id=OLD.id)
   ORDER BY i.id FOR UPDATE;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS a_r29_instrument_lock ON public.payment_instrument;
CREATE TRIGGER a_r29_instrument_lock BEFORE UPDATE ON public.payment_instrument
 FOR EACH ROW EXECUTE FUNCTION public.r29_instrument_lock();

ALTER TABLE public.otp_request ADD COLUMN IF NOT EXISTS org_id text;
UPDATE public.otp_request q SET org_id=r.org_id FROM public.otp_forward_rule r
 WHERE r.id=q.rule_id AND q.org_id IS NULL;
ALTER TABLE public.otp_request ALTER COLUMN org_id SET NOT NULL;
ALTER TABLE public.otp_request ALTER COLUMN org_id SET DEFAULT 'YX';
CREATE UNIQUE INDEX IF NOT EXISTS r29_otp_msg_once ON public.otp_request(fulfilled_message_id)
 WHERE fulfilled_message_id IS NOT NULL;
CREATE OR REPLACE FUNCTION public.r29_otp_request_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM public.otp_forward_rule r JOIN public.employee e
   ON e.id=NEW.requester_employee_id AND e.org_id=r.org_id
   WHERE r.id=NEW.rule_id AND r.org_id=NEW.org_id AND e.identity_confirmed AND e.employment_status='active')
 THEN RAISE EXCEPTION 'OTP requester must be an active verified employee in rule org'; END IF;
 IF TG_OP='INSERT' THEN
   IF NEW.requested_at>clock_timestamp() THEN RAISE EXCEPTION 'future OTP request'; END IF;
   -- Serialize the account's five-minute request window.
   PERFORM 1 FROM public.otp_forward_rule WHERE id=NEW.rule_id FOR UPDATE;
   IF EXISTS(SELECT 1 FROM public.otp_request WHERE rule_id=NEW.rule_id
       AND requested_at>NEW.requested_at-interval '5 minutes'
       AND requested_at<NEW.requested_at+interval '5 minutes')
   THEN RAISE EXCEPTION 'OTP account rate limit'; END IF;
 END IF;
 IF NEW.delivered_at IS NOT NULL AND (NEW.delivered_at<NEW.requested_at
   OR NEW.delivered_at>=NEW.requested_at+interval '5 minutes' OR NEW.fulfilled_message_id IS NULL)
 THEN RAISE EXCEPTION 'OTP request expired or malformed'; END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS r29_otp_request_guard ON public.otp_request;
CREATE TRIGGER r29_otp_request_guard BEFORE INSERT OR UPDATE ON public.otp_request
 FOR EACH ROW EXECUTE FUNCTION public.r29_otp_request_guard();
CREATE TABLE IF NOT EXISTS public.otp_private_delivery (
 request_id uuid PRIMARY KEY REFERENCES public.otp_request(id),
 message_id uuid NOT NULL UNIQUE REFERENCES public.email_message(id),
 recipient_employee_id uuid NOT NULL REFERENCES public.employee(id),
 org_id text NOT NULL REFERENCES public.org(id),
 channel text NOT NULL DEFAULT 'private_dm' CHECK(channel='private_dm'),
 is_group boolean NOT NULL DEFAULT false CHECK(NOT is_group),
 transport_status text NOT NULL DEFAULT 'DRY_RUN' CHECK(transport_status='DRY_RUN'),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE OR REPLACE FUNCTION public.r29_private_target_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM public.otp_request q WHERE q.id=NEW.request_id
   AND q.fulfilled_message_id=NEW.message_id AND q.requester_employee_id=NEW.recipient_employee_id
   AND q.org_id=NEW.org_id AND q.delivered_at IS NOT NULL)
 THEN RAISE EXCEPTION 'OTP delivery must target its requesting employee'; END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS r29_private_target_guard ON public.otp_private_delivery;
CREATE TRIGGER r29_private_target_guard BEFORE INSERT OR UPDATE ON public.otp_private_delivery
 FOR EACH ROW EXECUTE FUNCTION public.r29_private_target_guard();

-- The category CHECK also applies to updates. Source metadata cannot be relabelled to bypass it.
CREATE OR REPLACE FUNCTION public.r29_rag_source_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.message_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.email_message m
   WHERE m.id=NEW.message_id AND m.org_id=NEW.org_id AND m.category=NEW.category
     AND m.category NOT IN ('CAT-06','CAT-09','CAT-10'))
 THEN RAISE EXCEPTION 'RAG source is private or category/org mismatched'; END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS r29_rag_source_guard ON public.email_rag_chunk;
CREATE TRIGGER r29_rag_source_guard BEFORE INSERT OR UPDATE ON public.email_rag_chunk
 FOR EACH ROW EXECUTE FUNCTION public.r29_rag_source_guard();
CREATE OR REPLACE FUNCTION public.r29_email_evidence_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'email_message is append-only; verified evidence cannot be relabelled';
END $$;
DROP TRIGGER IF EXISTS r29_email_evidence_immutable ON public.email_message;
CREATE TRIGGER r29_email_evidence_immutable BEFORE UPDATE OR DELETE ON public.email_message
 FOR EACH ROW EXECUTE FUNCTION public.r29_email_evidence_immutable();

INSERT INTO public.email_mailbox(address,role,org_id) VALUES ('yong.yx1101@gmail.com','satellite','YX'),('yong.yx1103@gmail.com','satellite','YX') ON CONFLICT(address) DO NOTHING;

-- Receipt and attachment relationships must not bridge organizations indirectly.
DO $$ DECLARE child text; parent text; col text; BEGIN
 FOR child,parent,col IN VALUES
   ('receipt_allocation','invoice','invoice_id'),
   ('receipt_reversal','receipt_allocation','allocation_id'),
   ('email_switchboard_command','email_message','source_message_id'),
   ('email_attachment','email_message','message_id'),
   ('outbound_attachment','outbound_message','outbound_id') LOOP
   EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS org_id text',child);
   EXECUTE format('UPDATE public.%I c SET org_id=p.org_id FROM public.%I p WHERE c.%I=p.id AND c.org_id IS NULL',child,parent,col);
   EXECUTE format('ALTER TABLE public.%I ALTER COLUMN org_id SET NOT NULL',child);
   EXECUTE format('CREATE UNIQUE INDEX IF NOT EXISTS %I ON public.%I(id,org_id)','r29_'||parent||'_id_org_uq',parent);
   IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid=format('public.%I',child)::regclass AND conname='r29_parent_org_fk') THEN
     EXECUTE format('ALTER TABLE public.%I ADD CONSTRAINT r29_parent_org_fk FOREIGN KEY(%I,org_id) REFERENCES public.%I(id,org_id)',child,col,parent);
   END IF;
 END LOOP;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS r29_instrument_id_org_uq ON public.payment_instrument(id,org_id);
CREATE UNIQUE INDEX IF NOT EXISTS r29_deliverable_id_org_uq ON public.deliverable_version(id,org_id);
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='public.receipt_allocation'::regclass AND conname='r29_instrument_org_fk') THEN
   ALTER TABLE public.receipt_allocation ADD CONSTRAINT r29_instrument_org_fk
     FOREIGN KEY(instrument_id,org_id) REFERENCES public.payment_instrument(id,org_id);
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='public.outbound_attachment'::regclass AND conname='r29_deliverable_org_fk') THEN
   ALTER TABLE public.outbound_attachment ADD CONSTRAINT r29_deliverable_org_fk
     FOREIGN KEY(deliverable_version_id,org_id) REFERENCES public.deliverable_version(id,org_id);
 END IF;
END $$;
CREATE OR REPLACE FUNCTION public.r29_derive_parent_org() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE parent_org text;
BEGIN
 IF TG_TABLE_NAME='receipt_allocation' THEN SELECT org_id INTO parent_org FROM public.invoice WHERE id=NEW.invoice_id;
 ELSIF TG_TABLE_NAME='receipt_reversal' THEN SELECT org_id INTO parent_org FROM public.receipt_allocation WHERE id=NEW.allocation_id;
 ELSIF TG_TABLE_NAME='email_switchboard_command' THEN SELECT org_id INTO parent_org FROM public.email_message WHERE id=NEW.source_message_id;
 ELSIF TG_TABLE_NAME='email_attachment' THEN SELECT org_id INTO parent_org FROM public.email_message WHERE id=NEW.message_id;
 ELSIF TG_TABLE_NAME='outbound_attachment' THEN SELECT org_id INTO parent_org FROM public.outbound_message WHERE id=NEW.outbound_id;
 END IF;
 IF NEW.org_id IS NULL THEN NEW.org_id:=parent_org; END IF;
 RETURN NEW;
END $$;
DO $$ DECLARE tab text; BEGIN
 FOREACH tab IN ARRAY ARRAY['receipt_allocation','receipt_reversal','email_switchboard_command','email_attachment','outbound_attachment'] LOOP
   EXECUTE format('DROP TRIGGER IF EXISTS a0_r29_derive_parent_org ON public.%I',tab);
   EXECUTE format('CREATE TRIGGER a0_r29_derive_parent_org BEFORE INSERT OR UPDATE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.r29_derive_parent_org()',tab);
 END LOOP;
END $$;
-- Complete org scope for R29 business tables and their supporting R28 parents.
-- Derive newly introduced keys from authoritative parents; never rewrite existing keys.
CREATE OR REPLACE FUNCTION public.r29_scope_org() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE parent_org text;
BEGIN
  EXECUTE format('SELECT org_id FROM public.%I WHERE %I=$1',TG_ARGV[0],TG_ARGV[2])
    INTO parent_org USING (to_jsonb(NEW)->>TG_ARGV[1])::uuid;
  IF TG_TABLE_NAME='quote' AND parent_org IS NULL THEN
    SELECT org_id INTO parent_org FROM public.customer WHERE id=NEW.customer_id;
  END IF;
  IF NEW.org_id IS NULL THEN NEW.org_id:=parent_org; END IF;
  RETURN NEW;
END $$;
DO $$ DECLARE child text; parent text; col text; BEGIN
 FOR child,parent,col IN VALUES
   ('quote','case','case_id'), ('quote_version','quote','quote_id'),
   ('customer_contact','customer','customer_id'), ('email_link','email_message','message_id'),
   ('satellite_sent_copy','email_mailbox','mailbox_id'), ('bank_notice','email_message','email_message_id') LOOP
   EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS org_id text',child);
   EXECUTE format('UPDATE public.%I c SET org_id=p.org_id FROM public.%I p WHERE c.%I=p.id AND c.org_id IS NULL',child,parent,col);
   -- Quotes without a case still belong to their recorded customer.
   IF child='quote' THEN
     UPDATE public.quote q SET org_id=c.org_id FROM public.customer c
       WHERE q.customer_id=c.id AND q.org_id IS NULL;
     -- Pre-R29 CRM quotes without case/customer links came from the legacy
     -- single-org import. Preserve that namespace, rather than invent YX links.
     UPDATE public.quote SET org_id='yongxiang' WHERE org_id IS NULL;
   END IF;
   -- Notices with no resolved source are candidate-only records in YX's intake.
   IF child='bank_notice' THEN UPDATE public.bank_notice SET org_id='YX' WHERE org_id IS NULL; END IF;
   EXECUTE format('ALTER TABLE public.%I ALTER COLUMN org_id SET NOT NULL',child);
   EXECUTE format('CREATE UNIQUE INDEX IF NOT EXISTS %I ON public.%I(id,org_id)','r29_'||parent||'_id_org_uq',parent);
   IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid=format('public.%I',child)::regclass AND conname='r29_scope_parent_org_fk') THEN
     EXECUTE format('ALTER TABLE public.%I ADD CONSTRAINT r29_scope_parent_org_fk FOREIGN KEY(%I,org_id) REFERENCES public.%I(id,org_id)',child,col,parent);
   END IF;
   EXECUTE format('DROP TRIGGER IF EXISTS a0_r29_scope_org ON public.%I',child);
   EXECUTE format('CREATE TRIGGER a0_r29_scope_org BEFORE INSERT OR UPDATE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.r29_scope_org(%L,%L,%L)',child,parent,col,'id');
 END LOOP;
END $$;
ALTER TABLE public.bank_notice ALTER COLUMN org_id SET DEFAULT 'YX';
ALTER TABLE public.email_template ADD COLUMN IF NOT EXISTS org_id text NOT NULL DEFAULT 'YX';
-- Both ends of a stitched link and every case-bearing entity stay in the same org.
DO $$ DECLARE tab text; BEGIN
 FOREACH tab IN ARRAY ARRAY['quote','customer','case','employee','invoice','expense_line',
   'client_communication','client_commitment','outbound_message','email_mailbox','email_message',
   'email_thread','email_link','email_attachment','email_switchboard_command','email_template',
   'email_rag_chunk','bank_notice','deliverable_release_gate','deliverable_version',
   'outbound_recipient','outbound_attachment','payment_instrument','receipt_allocation',
   'receipt_reversal','permit','client_playbook_rule','case_settlement','otp_forward_rule',
   'otp_request','otp_private_delivery','satellite_sent_copy','serial_allocator','serial_assignment',
   'quote_version','customer_contact'] LOOP
   EXECUTE format('ALTER TABLE public.%I ALTER COLUMN org_id SET NOT NULL',tab);
   IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid=format('public.%I',tab)::regclass AND conname='r29_org_fk') THEN
     EXECUTE format('ALTER TABLE public.%I ADD CONSTRAINT r29_org_fk FOREIGN KEY(org_id) REFERENCES public.org(id)',tab);
   END IF;
   IF EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name=tab AND column_name='case_id')
      AND tab<>'case' AND NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid=format('public.%I',tab)::regclass AND conname='r29_case_org_fk') THEN
     EXECUTE format('ALTER TABLE public.%I ADD CONSTRAINT r29_case_org_fk FOREIGN KEY(case_id,org_id) REFERENCES public."case"(id,org_id)',tab);
   END IF;
 END LOOP;
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='public.email_link'::regclass AND conname='r29_link_original_org_fk') THEN
   ALTER TABLE public.email_link ADD CONSTRAINT r29_link_original_org_fk
     FOREIGN KEY(original_message_id,org_id) REFERENCES public.email_message(id,org_id);
 END IF;
END $$;
CREATE OR REPLACE FUNCTION public.r29_bank_candidate_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.status<>'candidate' OR NEW.allocated_receipt_id IS NOT NULL THEN
   RAISE EXCEPTION 'bank_notice only creates a candidate; finance must allocate separately';
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS r29_bank_candidate_guard ON public.bank_notice;
CREATE TRIGGER r29_bank_candidate_guard BEFORE INSERT ON public.bank_notice
 FOR EACH ROW EXECUTE FUNCTION public.r29_bank_candidate_guard();
-- Preserve installed R31-B convergence when this older migration is replayed.
DO $$ BEGIN
 IF to_regprocedure('public.restore_r31b_guards()') IS NOT NULL THEN
   PERFORM public.restore_r31b_guards();
 END IF;
END $$;
COMMIT;
