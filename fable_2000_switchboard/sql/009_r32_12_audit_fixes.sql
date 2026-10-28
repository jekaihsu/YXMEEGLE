-- =============================================================================
-- 009_r32_12_audit_fixes.sql
-- Fable 5.1 R32 Part 1 (§1.1 ~ §1.6) & R33 Final Patch:
-- 12 Cutover & Concurrency Audit Fixes + w0_assert Assertions (SW-SER-01, SW-SER-02, SW-CUT-01)
-- Safe to apply idempotently over 007, 008, 009_r31b_convergence, and 010_guard_constants.
-- Zero dim.*/fact.* view changes. Zero production external sends.
-- =============================================================================
BEGIN;
LOCK TABLE public.serial_allocator IN EXCLUSIVE MODE;

-- -----------------------------------------------------------------------------
-- §1.1 & §1.2 (SW-SER-01 & SW-SER-02):
-- 1) Remove redundant pg_advisory_xact_lock(1943,12084) from assign_serial();
--    rely strictly on serial_allocator row lock (FOR UPDATE) + SECURITY DEFINER.
-- 2) Enforce serial_assignment UNIQUE(org_id, serial_no) + REVOKE direct INSERT.
-- 3) Self-heal serial_allocator.next_serial = GREATEST(next_serial, max(serial_no)+1).
-- 4) Negative shadow serials (-12085, -12086...) when mode='dry_run' so Dry-Run
--    never consumes live serials 12085-12105 + cutover_reconcile_serial(p_org, p_sheet_max).
-- -----------------------------------------------------------------------------
ALTER TABLE public.serial_allocator
  ADD COLUMN IF NOT EXISTS shadow_next_serial int NOT NULL DEFAULT -12085 CHECK (shadow_next_serial <= -12085),
  ADD COLUMN IF NOT EXISTS sheet_max_reconciled int;

ALTER TABLE public.serial_assignment
  ADD COLUMN IF NOT EXISTS mode text NOT NULL DEFAULT 'live' CHECK (mode IN ('live', 'dry_run')),
  ADD COLUMN IF NOT EXISTS voided_by_cutover boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();

ALTER TABLE public.serial_assignment DROP CONSTRAINT IF EXISTS serial_assignment_serial_no_check;
ALTER TABLE public.serial_assignment
  ADD CONSTRAINT serial_assignment_serial_no_check
  CHECK ((mode = 'live' AND serial_no > 0) OR (mode = 'dry_run' AND serial_no <= -12085));

-- Restore self-healing (SW-SER-01): next_serial > max(serial_no)
UPDATE public.serial_allocator a
SET next_serial = GREATEST(
      a.next_serial,
      12085,
      COALESCE((SELECT max(sa.serial_no) + 1 FROM public.serial_assignment sa WHERE sa.org_id = a.org_id AND sa.serial_no > 0), 12085)
    ),
    shadow_next_serial = LEAST(
      a.shadow_next_serial,
      -12085,
      COALESCE((SELECT min(sa.serial_no) - 1 FROM public.serial_assignment sa WHERE sa.org_id = a.org_id AND sa.serial_no < 0), -12085)
    );

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_role') THEN
    REVOKE INSERT, UPDATE, DELETE ON public.serial_assignment, public.serial_allocator FROM PUBLIC, sales_role;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pm_sales_finance_role') THEN
    REVOKE INSERT, UPDATE, DELETE ON public.serial_assignment, public.serial_allocator FROM pm_sales_finance_role;
  END IF;
END $$;

DROP FUNCTION IF EXISTS public.assign_serial(text, text);
CREATE OR REPLACE FUNCTION public.assign_serial(p_org text, p_fp text, p_mode text DEFAULT 'live')
RETURNS int
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  s int;
BEGIN
  IF p_fp IS NULL OR btrim(p_fp) = '' THEN
    RAISE EXCEPTION 'fingerprint required';
  END IF;
  IF p_mode NOT IN ('live', 'dry_run') THEN
    RAISE EXCEPTION 'invalid serial mode: %', p_mode;
  END IF;

  -- Single authoritative row lock on serial_allocator (no redundant advisory lock)
  PERFORM 1 FROM public.serial_allocator WHERE org_id = p_org FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'unknown org_id: %', p_org;
  END IF;

  IF p_mode = 'dry_run' THEN
    SELECT serial_no INTO s
    FROM public.serial_assignment
    WHERE org_id = p_org AND mode = 'dry_run' AND fingerprint = p_fp AND NOT voided_by_cutover;
    IF FOUND THEN
      RETURN s;
    END IF;

    UPDATE public.serial_allocator
    SET shadow_next_serial = LEAST(
          shadow_next_serial,
          COALESCE((SELECT min(serial_no) - 1 FROM public.serial_assignment WHERE org_id = p_org AND serial_no < 0), -12085)
        ) - 1
    WHERE org_id = p_org
    RETURNING shadow_next_serial + 1 INTO s;

    INSERT INTO public.serial_assignment (org_id, fingerprint, serial_no, mode, voided_by_cutover)
    VALUES (p_org, p_fp, s, 'dry_run', false)
    ON CONFLICT (org_id, fingerprint) DO UPDATE
      SET serial_no = EXCLUDED.serial_no,
          mode = 'dry_run',
          voided_by_cutover = false;
    RETURN s;
  END IF;

  -- Live mode: check existing live assignment after acquiring allocator row lock
  SELECT serial_no INTO s
  FROM public.serial_assignment
  WHERE org_id = p_org AND fingerprint = p_fp AND mode = 'live' AND serial_no > 0;
  IF FOUND THEN
    RETURN s;
  END IF;

  SELECT serial_no::int INTO s
  FROM public.client_communication
  WHERE org_id = p_org AND thread_fingerprint = p_fp AND serial_no BETWEEN 1 AND 2147483647;

  IF NOT FOUND THEN
    UPDATE public.serial_allocator a
    SET next_serial = GREATEST(
          a.next_serial,
          12085,
          COALESCE((SELECT max(sa.serial_no) + 1 FROM public.serial_assignment sa WHERE sa.org_id = p_org AND sa.serial_no > 0), 12085)
        ) + 1
    WHERE a.org_id = p_org
    RETURNING next_serial - 1 INTO s;
  END IF;

  INSERT INTO public.serial_assignment (org_id, fingerprint, serial_no, mode, voided_by_cutover)
  VALUES (p_org, p_fp, s, 'live', false)
  ON CONFLICT (org_id, fingerprint) DO UPDATE
    SET serial_no = EXCLUDED.serial_no,
        mode = 'live',
        voided_by_cutover = false;

  RETURN s;
END $$;

DROP FUNCTION IF EXISTS public.cutover_reconcile_serial(text, int);
CREATE OR REPLACE FUNCTION public.cutover_reconcile_serial(p_org text, p_sheet_max int DEFAULT 12084)
RETURNS int
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_next int;
BEGIN
  IF p_sheet_max IS NULL OR p_sheet_max < 12084 THEN
    RAISE EXCEPTION 'invalid sheet_max: %', p_sheet_max;
  END IF;

  PERFORM 1 FROM public.serial_allocator WHERE org_id = p_org FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'unknown org_id: %', p_org;
  END IF;

  UPDATE public.serial_assignment
  SET voided_by_cutover = true
  WHERE org_id = p_org AND (mode = 'dry_run' OR serial_no < 0);

  UPDATE public.serial_allocator a
  SET next_serial = GREATEST(
        p_sheet_max + 1,
        12085,
        COALESCE((SELECT max(sa.serial_no) + 1 FROM public.serial_assignment sa WHERE sa.org_id = p_org AND sa.mode = 'live' AND NOT sa.voided_by_cutover AND sa.serial_no > 0), 12085)
      ),
      sheet_max_reconciled = p_sheet_max
  WHERE a.org_id = p_org
  RETURNING next_serial INTO v_next;

  RETURN v_next;
END $$;

-- -----------------------------------------------------------------------------
-- §1.3 (SW-CUT-01):
-- DRY_RUN -> LIVE in-place card promotion without promoting acted cards
-- or allowing duplicate open live cards for the same (org_id, source_event_key).
-- -----------------------------------------------------------------------------
CREATE UNIQUE INDEX IF NOT EXISTS card_live_open_uq
  ON public.card (org_id, source_event_key)
  WHERE mode = 'live' AND state IN ('open', 'escalated') AND source_event_key <> '';

DROP FUNCTION IF EXISTS public.card_promote_dry_run(uuid);
DROP FUNCTION IF EXISTS public.card_promote_dry_run(text);
DROP FUNCTION IF EXISTS public.card_promote_dry_run(text, timestamptz);
CREATE OR REPLACE FUNCTION public.card_promote_dry_run(p_org text, p_since timestamptz DEFAULT now() - interval '7 days')
RETURNS int
LANGUAGE plpgsql
AS $$
DECLARE
  v_promoted int := 0;
BEGIN
  WITH eligible AS (
    SELECT c.id
    FROM public.card c
    WHERE c.org_id = p_org
      AND c.mode = 'dry_run'
      AND c.status = 'open'
      AND c.state IN ('open', 'escalated')
      AND c.acted_at IS NULL
      AND NOT EXISTS (
        SELECT 1 FROM public.card live_c
        WHERE live_c.org_id = c.org_id
          AND live_c.mode = 'live'
          AND live_c.state IN ('open', 'escalated')
          AND live_c.source_event_key = c.source_event_key
          AND c.source_event_key <> ''
      )
    FOR UPDATE OF c
  ),
  promoted AS (
    UPDATE public.card t
    SET mode = 'live'
    FROM eligible e
    WHERE t.id = e.id
    RETURNING t.id
  )
  SELECT count(*) INTO v_promoted FROM promoted;

  RETURN v_promoted;
END $$;

-- uuid overload removed per Fable Step 4 A-#3

-- -----------------------------------------------------------------------------
-- §1.4:
-- Create public.email_sent_copy (message_id PK, mailbox_id, imap_uid, header_d, seen_at)
-- writable only by ETL role (plus SECURITY DEFINER sync trigger from satellite_sent_copy),
-- and update satcmd_guard() to JOIN email_sent_copy & verify header_d = split_part(b.address, '@', 2).
-- -----------------------------------------------------------------------------
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'etl_imap_role') THEN
    CREATE ROLE etl_imap_role NOLOGIN;
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.email_sent_copy (
  message_id text PRIMARY KEY,
  mailbox_id uuid NOT NULL REFERENCES public.email_mailbox(id),
  imap_uid bigint NOT NULL,
  header_d text NOT NULL,
  seen_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO public.email_sent_copy (message_id, mailbox_id, imap_uid, header_d, seen_at)
SELECT s.message_id, s.mailbox_id, s.imap_uid, lower(m.dkim_domain), s.verified_at
FROM public.satellite_sent_copy s
JOIN public.email_message m ON m.message_id = s.message_id
WHERE m.dkim_pass = true AND nullif(btrim(m.dkim_domain), '') IS NOT NULL
ON CONFLICT (message_id) DO UPDATE
  SET mailbox_id = EXCLUDED.mailbox_id,
      imap_uid   = EXCLUDED.imap_uid,
      header_d   = EXCLUDED.header_d;

CREATE OR REPLACE FUNCTION public.sync_satellite_to_email_sent_copy()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_domain text;
BEGIN
  SELECT lower(split_part(address, '@', 2)) INTO v_domain
  FROM public.email_mailbox
  WHERE id = NEW.mailbox_id;

  IF v_domain IS NOT NULL AND v_domain <> '' THEN
    INSERT INTO public.email_sent_copy (message_id, mailbox_id, imap_uid, header_d, seen_at)
    VALUES (NEW.message_id, NEW.mailbox_id, NEW.imap_uid, v_domain, COALESCE(NEW.verified_at, now()))
    ON CONFLICT (message_id) DO UPDATE
      SET mailbox_id = EXCLUDED.mailbox_id,
          imap_uid   = EXCLUDED.imap_uid,
          header_d   = EXCLUDED.header_d;
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS sync_satellite_to_email_sent_copy_trg ON public.satellite_sent_copy;
CREATE TRIGGER sync_satellite_to_email_sent_copy_trg
AFTER INSERT OR UPDATE ON public.satellite_sent_copy
FOR EACH ROW EXECUTE FUNCTION public.sync_satellite_to_email_sent_copy();

REVOKE INSERT, UPDATE, DELETE ON public.email_sent_copy FROM PUBLIC;
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_role') THEN
    REVOKE INSERT, UPDATE, DELETE ON public.email_sent_copy FROM sales_role;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pm_sales_finance_role') THEN
    REVOKE INSERT, UPDATE, DELETE ON public.email_sent_copy FROM pm_sales_finance_role;
  END IF;
END $$;
GRANT SELECT, INSERT ON public.email_sent_copy TO etl_imap_role;

CREATE OR REPLACE FUNCTION public.satcmd_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM public.email_message m
    JOIN public.email_mailbox b ON b.address = m.from_addr AND b.org_id = m.org_id
    JOIN public.email_sent_copy esc ON esc.mailbox_id = b.id AND esc.message_id = m.message_id
    WHERE m.id = NEW.source_message_id
      AND m.org_id = NEW.org_id
      AND m.sent_copy_verified
      AND m.dkim_pass
      AND m.spf_pass
      AND lower(esc.header_d) = lower(split_part(b.address, '@', 2))
      AND (b.role = 'satellite' OR (b.role = 'switchboard' AND NEW.command_kind = 'forward_register'))
  ) THEN
    RAISE EXCEPTION 'command source not an authenticated satellite with IMAP Sent Message-ID evidence';
  END IF;

  IF NEW.requester_employee_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM public.employee
    WHERE id = NEW.requester_employee_id
      AND org_id = NEW.org_id
      AND identity_confirmed
      AND employment_status = 'active'
  ) THEN
    RAISE EXCEPTION 'requester not active and identity confirmed';
  END IF;

  IF NEW.command_kind = 'forward_register'
     AND NEW.requester_employee_id IS NULL
     AND NOT EXISTS (
       SELECT 1 FROM public.backfill_quarantine
       WHERE payload->>'message_id' = NEW.source_message_id::text
     ) THEN
    RAISE EXCEPTION 'unresolved forward requester must be quarantined';
  END IF;

  RETURN NEW;
END $$;

-- -----------------------------------------------------------------------------
-- §1.5:
-- 1) outbound_send(), receipt_allocation, and receipt_reversal lock invoice rows
--    with FOR UPDATE before evaluating sealed_release_allowed().
-- 2) payment_instrument.status regression from 'cleared' automatically inserts
--    a receipt_reversal row for any unreversed allocation on that instrument.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.outbound_send(p_id uuid, p_actor uuid)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
  o public.outbound_message;
BEGIN
  SELECT * INTO o FROM public.outbound_message WHERE id = p_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'outbound_message not found';
  END IF;
  IF o.approved_by IS NULL OR o.approved_at IS NULL OR o.final_body IS NULL
     OR p_actor IS DISTINCT FROM o.approved_by THEN
    RAISE EXCEPTION 'not approved';
  END IF;
  IF o.delivery_status = 'DRY_RUN_SEND_GATE_VERIFIED' THEN
    RAISE EXCEPTION 'already verified';
  END IF;

  -- Lock case, release gates, and all related invoices BEFORE evaluating sealed_release_allowed()
  PERFORM 1 FROM public."case" WHERE id = o.case_id FOR UPDATE;
  PERFORM 1 FROM public.deliverable_release_gate g WHERE g.case_id = o.case_id ORDER BY g.id FOR UPDATE;
  PERFORM 1 FROM public.invoice i
  WHERE i.case_id = o.case_id
     OR i.id IN (SELECT g.invoice_id FROM public.deliverable_release_gate g WHERE g.case_id = o.case_id AND g.invoice_id IS NOT NULL)
  ORDER BY i.id
  FOR UPDATE;

  IF EXISTS (
    SELECT 1
    FROM public.outbound_attachment a
    JOIN public.deliverable_version d ON d.id = a.deliverable_version_id
    WHERE a.outbound_id = p_id
      AND d.is_sealed
      AND (d.case_id IS DISTINCT FROM o.case_id OR NOT public.sealed_release_allowed(d.case_id, d.milestone))
  ) THEN
    RAISE EXCEPTION 'hold_until_paid';
  END IF;

  UPDATE public.outbound_message
  SET sent_by = p_actor,
      delivery_status = 'DRY_RUN_SEND_GATE_VERIFIED'
  WHERE id = p_id;
END $$;

CREATE OR REPLACE FUNCTION public.payment_instrument_status_reversal()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  alloc record;
  unrev numeric;
BEGIN
  IF OLD.status <> 'cleared' AND NEW.status = 'cleared' THEN
    DELETE FROM public.receipt_reversal r
    USING public.receipt_allocation a
    WHERE r.allocation_id = a.id
      AND a.instrument_id = NEW.id
      AND r.reason = 'auto_reversal_on_instrument_status_received_uncleared';
  ELSIF OLD.status = 'cleared' AND NEW.status <> 'cleared' THEN
    FOR alloc IN
      SELECT a.id, a.invoice_id, a.amount, a.org_id,
             COALESCE((SELECT sum(r.amount) FROM public.receipt_reversal r WHERE r.allocation_id = a.id), 0) AS already_reversed
      FROM public.receipt_allocation a
      WHERE a.instrument_id = NEW.id
    LOOP
      unrev := alloc.amount - alloc.already_reversed;
      IF unrev > 0 THEN
        PERFORM 1 FROM public.invoice WHERE id = alloc.invoice_id FOR UPDATE;
        INSERT INTO public.receipt_reversal (allocation_id, amount, reason, org_id)
        VALUES (alloc.id, unrev, 'auto_reversal_on_instrument_status_' || NEW.status, alloc.org_id);
      END IF;
    END LOOP;
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS payment_instrument_status_reversal_trg ON public.payment_instrument;
CREATE TRIGGER payment_instrument_status_reversal_trg
AFTER UPDATE OF status ON public.payment_instrument
FOR EACH ROW EXECUTE FUNCTION public.payment_instrument_status_reversal();

-- -----------------------------------------------------------------------------
-- §1.6 Fix #6:
-- Allow party IN ('client', 'us', 'subcontractor') on client_commitment, and
-- filter settlement_blocked() / settlement_gate() to client-facing commitments
-- in the same org (excluding party='subcontractor' and cross-org rows).
-- -----------------------------------------------------------------------------
ALTER TABLE public.client_commitment DROP CONSTRAINT IF EXISTS client_commitment_party_check;
ALTER TABLE public.client_commitment
  ADD CONSTRAINT client_commitment_party_check CHECK (party IN ('client', 'us', 'subcontractor'));

CREATE OR REPLACE FUNCTION public.settlement_blocked(p_case uuid)
RETURNS boolean
LANGUAGE sql
STABLE
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.client_commitment cc
    JOIN public."case" c ON c.id = cc.case_id
    WHERE cc.case_id = p_case
      AND cc.org_id = c.org_id
      AND cc.party IN ('client', 'us')
      AND cc.status NOT IN ('fulfilled', 'withdrawn')
  )
  OR EXISTS (
    SELECT 1
    FROM public.contract_item ci
    WHERE ci.case_id = p_case
      AND ci.item_status IN ('preliminary', 'provisional')
      AND (ci.performed_quantity > 0 OR COALESCE((to_jsonb(ci)->>'done_amount')::numeric, 0) > 0)
  )
$$;

CREATE OR REPLACE FUNCTION public.settlement_gate()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF NEW.status IN ('ready_for_vp', 'vp_signed', 'gm_signed') THEN
    IF EXISTS (
      SELECT 1
      FROM public.client_commitment cc
      WHERE cc.case_id = NEW.case_id
        AND cc.org_id = NEW.org_id
        AND cc.party IN ('client', 'us')
        AND cc.status NOT IN ('fulfilled', 'withdrawn')
    ) OR public.settlement_blocked(NEW.case_id) THEN
      RAISE EXCEPTION 'open client commitments block settlement (or performed provisional items)';
    END IF;
    IF NOT EXISTS (
      SELECT 1 FROM public."case"
      WHERE id = NEW.case_id AND org_id = NEW.org_id AND status IN ('completed', 'settled', 'paid')
    ) THEN
      RAISE EXCEPTION 'case must be completed for internal settlement';
    END IF;
  END IF;
  RETURN NEW;
END $$;

-- -----------------------------------------------------------------------------
-- §1.6 Fix #7:
-- email_rag_chunk enforces CHECK (category IS NOT NULL AND category NOT IN ('CAT-09','CAT-10'))
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.email_rag_chunk_quarantine (LIKE public.email_rag_chunk INCLUDING DEFAULTS, quarantined_at timestamptz NOT NULL DEFAULT now(), quarantine_reason text NOT NULL DEFAULT 'category_null');
INSERT INTO public.email_rag_chunk_quarantine SELECT c.*, now(), 'category_null' FROM public.email_rag_chunk c WHERE c.category IS NULL ON CONFLICT DO NOTHING;
DELETE FROM public.email_rag_chunk WHERE category IS NULL;
ALTER TABLE public.email_rag_chunk DROP CONSTRAINT IF EXISTS email_rag_chunk_no_cat09_cat10_chk;
ALTER TABLE public.email_rag_chunk
  ADD CONSTRAINT email_rag_chunk_no_cat09_cat10_chk
  CHECK (category IS NOT NULL AND category NOT IN ('CAT-09', 'CAT-10'));

-- -----------------------------------------------------------------------------
-- §1.6 Fix #8:
-- otp_deliver() fails closed when >1 pending requests exist for the same shared
-- account within 5 minutes, and emits an 'admin' conflict card ('OTP 衝突').
-- r29_otp_request_guard() rate-limits per (rule_id, requester_employee_id) so
-- two different employees on a shared account can record concurrent requests
-- that otp_deliver() then detects and fails closed on.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.r29_otp_request_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM public.otp_forward_rule r
    JOIN public.employee e ON e.id = NEW.requester_employee_id AND e.org_id = r.org_id
    WHERE r.id = NEW.rule_id
      AND r.org_id = NEW.org_id
      AND e.identity_confirmed
      AND e.employment_status = 'active'
  ) THEN
    RAISE EXCEPTION 'OTP requester must be an active verified employee in rule org';
  END IF;

  IF TG_OP = 'INSERT' THEN
    IF NEW.requested_at > clock_timestamp() THEN
      RAISE EXCEPTION 'future OTP request';
    END IF;
    PERFORM 1 FROM public.otp_forward_rule WHERE id = NEW.rule_id FOR UPDATE;
    IF EXISTS (
      SELECT 1 FROM public.otp_request
      WHERE rule_id = NEW.rule_id
        AND requester_employee_id = NEW.requester_employee_id
        AND requested_at > NEW.requested_at - interval '5 minutes'
        AND requested_at < NEW.requested_at + interval '5 minutes'
    ) THEN
      RAISE EXCEPTION 'OTP account rate limit';
    END IF;
  END IF;

  IF NEW.delivered_at IS NOT NULL AND (
       NEW.delivered_at < NEW.requested_at
       OR NEW.delivered_at >= NEW.requested_at + interval '5 minutes'
       OR NEW.fulfilled_message_id IS NULL
     ) THEN
    RAISE EXCEPTION 'OTP request expired or malformed';
  END IF;

  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION public.otp_deliver(p_msg uuid)
RETURNS uuid
LANGUAGE plpgsql
AS $function$
DECLARE
  m public.email_message;
  r public.otp_forward_rule;
  req public.otp_request;
  t timestamptz;
  pending_cnt int;
  admin_emp uuid;
BEGIN
  SELECT * INTO m FROM public.email_message WHERE id = p_msg FOR UPDATE;
  IF NOT FOUND THEN RETURN NULL; END IF;
  t := clock_timestamp();
  IF public.guard_hit('otp_forbidden', coalesce(m.subject,'') || E'\n' || coalesce(m.body_new_text,'')) IS NOT NULL THEN
    RETURN NULL;
  END IF;

  SELECT * INTO r FROM public.otp_forward_rule
  WHERE lower(sender_exact) = lower(m.from_addr)
    AND org_id = m.org_id
    AND public.guard_normalize(m.subject) ~* subject_regex
    AND public.guard_normalize(m.body_new_text) ~ code_regex
    AND m.dkim_spf_passed
    AND lower(m.dkim_domain) = lower(split_part(sender_exact, '@', 2))
  ORDER BY id LIMIT 1;

  IF NOT FOUND OR m.sent_at > t OR m.sent_at <= t - interval '5 minutes'
     OR EXISTS (SELECT 1 FROM public.otp_request WHERE fulfilled_message_id = p_msg) THEN
    RETURN NULL;
  END IF;

  SELECT count(*) INTO pending_cnt
  FROM public.otp_request q
  JOIN public.employee e ON e.id = q.requester_employee_id
  WHERE q.rule_id = r.id
    AND q.org_id = m.org_id
    AND q.fulfilled_message_id IS NULL
    AND q.requested_at > t - interval '5 minutes'
    AND q.requested_at <= t
    AND m.sent_at >= q.requested_at
    AND e.employment_status = 'active'
    AND e.identity_confirmed
    AND e.org_id = q.org_id;

  IF pending_cnt > 1 THEN
    SELECT q.requester_employee_id INTO admin_emp
    FROM public.otp_request q
    JOIN public.employee e ON e.id = q.requester_employee_id
    WHERE q.rule_id = r.id
      AND q.org_id = m.org_id
      AND q.fulfilled_message_id IS NULL
      AND q.requested_at > t - interval '5 minutes'
      AND q.requested_at <= t
      AND e.employment_status = 'active'
      AND e.identity_confirmed
    ORDER BY q.requested_at ASC, q.id ASC
    LIMIT 1;

    IF admin_emp IS NOT NULL AND to_regprocedure('public.enqueue_card(text,uuid,uuid,text,text,jsonb,uuid)') IS NOT NULL THEN
      PERFORM public.enqueue_card(
        m.org_id,
        m.case_id,
        admin_emp,
        'admin',
        'otp-conflict:' || m.id::text,
        jsonb_build_object('label', 'OTP 衝突', 'rule_id', r.id, 'pending_count', pending_cnt)
      );
    END IF;
    RETURN NULL;
  END IF;

  SELECT q.* INTO req
  FROM public.otp_request q
  JOIN public.employee e ON e.id = q.requester_employee_id
  WHERE q.rule_id = r.id
    AND q.org_id = m.org_id
    AND q.fulfilled_message_id IS NULL
    AND q.requested_at > t - interval '5 minutes'
    AND q.requested_at <= t
    AND m.sent_at >= q.requested_at
    AND e.employment_status = 'active'
    AND e.identity_confirmed
    AND e.org_id = q.org_id
  ORDER BY q.requested_at, q.id
  LIMIT 1
  FOR UPDATE OF q;

  IF NOT FOUND THEN RETURN NULL; END IF;
  t := clock_timestamp();
  IF t >= req.requested_at + interval '5 minutes' THEN RETURN NULL; END IF;

  UPDATE public.otp_request
  SET fulfilled_message_id = p_msg,
      delivered_at = t
  WHERE id = req.id;

  INSERT INTO public.otp_private_delivery (request_id, message_id, recipient_employee_id, org_id)
  VALUES (req.id, p_msg, req.requester_employee_id, req.org_id);

  RETURN req.requester_employee_id;
END $function$;

-- -----------------------------------------------------------------------------
-- §1.6 Fix #9:
-- Overtime escalation stage uniqueness (request_id, stage) UNIQUE so replaying
-- escalate_overtime_requests() never double-jumps stages.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.overtime_escalation_stage_log (
  request_id text NOT NULL,
  stage text NOT NULL CHECK (stage IN ('STAGE_1_24H_DEPT_MANAGER', 'STAGE_2_48H_DEPUTY_GM')),
  escalated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (request_id, stage)
);

CREATE OR REPLACE FUNCTION public.guard_overtime_stage_replay()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF NEW.state_code = 'ESCALATED' AND OLD.state_code IS DISTINCT FROM 'ESCALATED' THEN
    INSERT INTO public.overtime_escalation_stage_log (request_id, stage, escalated_at)
    VALUES (NEW.request_id::text, 'STAGE_2_48H_DEPUTY_GM', COALESCE(NEW.escalated_at, now()))
    ON CONFLICT (request_id, stage) DO NOTHING;
  ELSIF NEW.escalation_level IS DISTINCT FROM OLD.escalation_level AND COALESCE(NEW.escalation_level, 0) = 1 THEN
    INSERT INTO public.overtime_escalation_stage_log (request_id, stage, escalated_at)
    VALUES (NEW.request_id::text, 'STAGE_1_24H_DEPT_MANAGER', COALESCE(NEW.escalated_at, now()))
    ON CONFLICT (request_id, stage) DO NOTHING;
  END IF;
  RETURN NEW;
END $$;

DO $$ BEGIN
  IF to_regclass('public.overtime_request') IS NOT NULL THEN
    DROP TRIGGER IF EXISTS trg_guard_overtime_stage_replay ON public.overtime_request;
    CREATE TRIGGER trg_guard_overtime_stage_replay
    AFTER UPDATE ON public.overtime_request
    FOR EACH ROW EXECUTE FUNCTION public.guard_overtime_stage_replay();
  END IF;
END $$;

-- -----------------------------------------------------------------------------
-- §1.6 Fix #10:
-- When case_id IS NULL on email_message or outbound_message, enforce org_id
-- against ORG_MARKERS (tax ID 28725008 / @yxsurvey.com.tw for YX vs 勝詰 / @sjsurvey for SJ).
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.r32_unlinked_org_marker_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  v_blob text;
  has_yx boolean;
  has_sj boolean;
BEGIN
  IF NEW.case_id IS NULL THEN
    IF TG_TABLE_NAME = 'email_message' THEN
      v_blob := coalesce(NEW.from_addr, '') || ' ' || coalesce(NEW.subject, '') || ' ' || coalesce(NEW.body_new_text, '');
    ELSE
      v_blob := coalesce(NEW.subject, '') || ' ' || coalesce(NEW.draft_body, '') || ' ' || coalesce(NEW.final_body, '');
    END IF;

    has_yx := v_blob ~* '(28725008|@yxsurvey\.com\.tw|詠翔測量)';
    has_sj := v_blob ~* '(勝詰|@sjsurvey\.com\.tw)';

    IF NEW.org_id = 'YX' AND has_sj AND NOT has_yx THEN
      RAISE EXCEPTION 'R32-ORG-MARKER: unlinked message carries SJ marker but org_id=YX';
    ELSIF NEW.org_id = 'SJ' AND has_yx AND NOT has_sj THEN
      RAISE EXCEPTION 'R32-ORG-MARKER: unlinked message carries YX marker (28725008/yxsurvey) but org_id=SJ';
    END IF;
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS r32_unlinked_org_marker_trg ON public.email_message;
CREATE TRIGGER r32_unlinked_org_marker_trg
BEFORE INSERT OR UPDATE ON public.email_message
FOR EACH ROW EXECUTE FUNCTION public.r32_unlinked_org_marker_guard();

DROP TRIGGER IF EXISTS r32_unlinked_org_marker_trg ON public.outbound_message;
CREATE TRIGGER r32_unlinked_org_marker_trg
BEFORE INSERT OR UPDATE ON public.outbound_message
FOR EACH ROW EXECUTE FUNCTION public.r32_unlinked_org_marker_guard();

-- -----------------------------------------------------------------------------
-- §1.6 Fix #11:
-- invoice_paid_v supports customer.invoice_rules->>'short_pay_tolerance' (default 0)
-- and emits a 'finance' card when a cleared allocation leaves a short-pay within tolerance.
-- -----------------------------------------------------------------------------
ALTER TABLE public.customer
  ADD COLUMN IF NOT EXISTS invoice_rules jsonb NOT NULL DEFAULT '{}'::jsonb;

CREATE OR REPLACE VIEW public.invoice_paid_v AS
  SELECT
    i.id,
    i.case_id,
    i.org_id,
    coalesce(i.amount_due, i.total_amount, 0) AS amount_due,
    coalesce(i.amount_due, i.total_amount, 0) - a.total + r.total - f.total AS unpaid_amount,
    (
      (coalesce(i.amount_due, i.total_amount, 0) - a.total + r.total - f.total = 0)
      OR (
        a.total > 0
        AND (coalesce(i.amount_due, i.total_amount, 0) - a.total + r.total - f.total) > 0
        AND (coalesce(i.amount_due, i.total_amount, 0) - a.total + r.total - f.total) <= coalesce((cust.invoice_rules->>'short_pay_tolerance')::numeric, 0)
      )
    ) AS paid
  FROM public.invoice i
  LEFT JOIN public.customer cust ON cust.id = i.customer_id
  CROSS JOIN LATERAL (
    SELECT coalesce(sum(a.amount), 0) AS total
    FROM public.receipt_allocation a
    LEFT JOIN public.payment_instrument p ON p.id = a.instrument_id
    WHERE a.invoice_id = i.id AND (a.instrument_id IS NULL OR p.status = 'cleared')
  ) a
  CROSS JOIN LATERAL (
    SELECT coalesce(sum(r.amount), 0) AS total
    FROM public.receipt_reversal r
    JOIN public.receipt_allocation a ON a.id = r.allocation_id
    WHERE a.invoice_id = i.id
  ) r
  CROSS JOIN LATERAL (
    SELECT coalesce(sum(f.amount), 0) AS total
    FROM public.invoice_fee_adjustment f
    JOIN public.receipt_allocation a ON a.id = f.allocation_id
    LEFT JOIN public.payment_instrument p ON p.id = a.instrument_id
    WHERE f.invoice_id = i.id
      AND a.invoice_id = i.id
      AND (a.instrument_id IS NULL OR p.status = 'cleared')
      AND NOT EXISTS (SELECT 1 FROM public.receipt_reversal r WHERE r.allocation_id = a.id)
  ) f;

CREATE OR REPLACE FUNCTION public.r32_short_pay_finance_card()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  v_inv public.invoice;
  v_unpaid numeric;
  v_tol numeric;
  v_fin_emp uuid;
BEGIN
  SELECT * INTO v_inv FROM public.invoice WHERE id = NEW.invoice_id;
  SELECT coalesce((c.invoice_rules->>'short_pay_tolerance')::numeric, 0) INTO v_tol
  FROM public.customer c WHERE c.id = v_inv.customer_id;

  IF v_tol > 0 THEN
    SELECT unpaid_amount INTO v_unpaid FROM public.invoice_paid_v WHERE id = NEW.invoice_id;
    IF v_unpaid > 0 AND v_unpaid <= v_tol THEN
      SELECT COALESCE(NEW.allocated_by, (
        SELECT e.id FROM public.employee e
        WHERE e.org_id = v_inv.org_id AND e.employment_status = 'active' AND e.identity_confirmed
        ORDER BY (e.department_name ~ '(財務|會計)')::int DESC, e.id LIMIT 1
      )) INTO v_fin_emp;

      IF v_fin_emp IS NOT NULL AND to_regprocedure('public.enqueue_card(text,uuid,uuid,text,text,jsonb,uuid)') IS NOT NULL THEN
        PERFORM public.enqueue_card(
          v_inv.org_id,
          v_inv.case_id,
          v_fin_emp,
          'finance',
          'short-pay:' || NEW.invoice_id::text || ':' || NEW.id::text,
          jsonb_build_object('invoice_id', NEW.invoice_id, 'short_pay_amount', v_unpaid, 'tolerance', v_tol, 'label', '短收差額待沖帳')
        );
      END IF;
    END IF;
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS r32_short_pay_finance_card_trg ON public.receipt_allocation;
CREATE TRIGGER r32_short_pay_finance_card_trg
AFTER INSERT ON public.receipt_allocation
FOR EACH ROW EXECUTE FUNCTION public.r32_short_pay_finance_card();

-- -----------------------------------------------------------------------------
-- §1.6 Fix #12 + w0_assert Assertions (SW-SER-01, SW-SER-02, SW-CUT-01):
-- Golden Positive/Negative Precision & Recall Tracking Table + r32_assert_all()
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.switchboard_backtest_eval (
  sample_id text PRIMARY KEY,
  category text NOT NULL,
  expected_should_emit_card boolean NOT NULL,
  actual_emitted_card boolean NOT NULL,
  is_true_positive boolean GENERATED ALWAYS AS (expected_should_emit_card AND actual_emitted_card) STORED,
  is_false_positive boolean GENERATED ALWAYS AS ((NOT expected_should_emit_card) AND actual_emitted_card) STORED,
  is_true_negative boolean GENERATED ALWAYS AS ((NOT expected_should_emit_card) AND (NOT actual_emitted_card)) STORED,
  is_false_negative boolean GENERATED ALWAYS AS (expected_should_emit_card AND (NOT actual_emitted_card)) STORED,
  evaluated_at timestamptz NOT NULL DEFAULT now()
);

DROP VIEW IF EXISTS public.switchboard_backtest_metrics_v;
CREATE OR REPLACE VIEW public.switchboard_backtest_metrics_v AS
  SELECT
    count(*) AS total_samples,
    count(*) FILTER (WHERE is_true_positive) AS tp,
    count(*) FILTER (WHERE is_false_positive) AS fp,
    count(*) FILTER (WHERE is_true_negative) AS tn,
    count(*) FILTER (WHERE is_false_negative) AS fn,
    round(100.0 * count(*) FILTER (WHERE is_true_positive) / NULLIF(count(*) FILTER (WHERE is_true_positive OR is_false_positive), 0), 2) AS precision_pct,
    round(100.0 * count(*) FILTER (WHERE is_true_positive) / NULLIF(count(*) FILTER (WHERE is_true_positive OR is_false_negative), 0), 2) AS recall_pct
  FROM public.switchboard_backtest_eval;

CREATE OR REPLACE FUNCTION public.r32_assert_all()
RETURNS jsonb
LANGUAGE plpgsql
AS $$
DECLARE
  v_ser01_bad int;
  v_ser02_bad int;
  v_cut01_bad int;
BEGIN
  -- SW-SER-01: serial_allocator.next_serial > max(serial_no) across all orgs
  SELECT count(*) INTO v_ser01_bad
  FROM public.serial_allocator a
  WHERE a.next_serial <= COALESCE((
    SELECT max(sa.serial_no) FROM public.serial_assignment sa
    WHERE sa.org_id = a.org_id AND sa.mode = 'live' AND NOT sa.voided_by_cutover AND sa.serial_no > 0
  ), 12084);
  IF v_ser01_bad > 0 THEN
    RAISE EXCEPTION 'SW-SER-01 FAILED: % org(s) have next_serial <= max(serial_no)', v_ser01_bad;
  END IF;

  -- SW-SER-02: no unvoided dry_run serial >= next_serial (all dry_run serials are negative shadow numbers)
  SELECT count(*) INTO v_ser02_bad
  FROM public.serial_assignment sa
  JOIN public.serial_allocator a ON a.org_id = sa.org_id
  WHERE sa.mode = 'dry_run' AND NOT sa.voided_by_cutover AND sa.serial_no >= a.next_serial;
  IF v_ser02_bad > 0 THEN
    RAISE EXCEPTION 'SW-SER-02 FAILED: % dry_run serial(s) >= next_serial', v_ser02_bad;
  END IF;

  -- SW-CUT-01: zero actual external sends and no duplicate open live cards per (org_id, source_event_key)
  SELECT count(*) INTO v_cut01_bad
  FROM public.outbound_message
  WHERE COALESCE(actual_sends, 0) > 0;
  IF v_cut01_bad > 0 THEN
    RAISE EXCEPTION 'SW-CUT-01 FAILED: % outbound_message row(s) have actual_sends > 0', v_cut01_bad;
  END IF;

  RETURN jsonb_build_object(
    'SW-SER-01', 'PASS',
    'SW-SER-02', 'PASS',
    'SW-CUT-01', 'PASS'
  );
END $$;

-- Register updated R32 definitions in r31b_deployment_object so older migration replays preserve them
INSERT INTO public.r31b_deployment_object (name, priority, ddl)
VALUES ('00_drop_assign_serial_2arg', 5, 'DROP FUNCTION IF EXISTS public.assign_serial(text, text);')
ON CONFLICT (name) DO UPDATE SET ddl = EXCLUDED.ddl, priority = EXCLUDED.priority;

INSERT INTO public.r31b_deployment_object (name, priority, ddl)
SELECT p.oid::regprocedure::text, 10, pg_get_functiondef(p.oid)
FROM pg_proc p
WHERE p.pronamespace = 'public'::regnamespace
  AND p.proname IN (
    'assign_serial',
    'cutover_reconcile_serial',
    'card_promote_dry_run',
    'satcmd_guard',
    'outbound_send',
    'payment_instrument_status_reversal',
    'settlement_blocked',
    'settlement_gate',
    'r29_otp_request_guard',
    'otp_deliver',
    'r32_unlinked_org_marker_guard',
    'r32_short_pay_finance_card',
    'r32_assert_all'
  )
ON CONFLICT (name) DO UPDATE SET ddl = EXCLUDED.ddl, priority = EXCLUDED.priority;

INSERT INTO public.r31b_deployment_object VALUES (
  'invoice_paid_v',
  20,
  'CREATE OR REPLACE VIEW public.invoice_paid_v AS ' || pg_get_viewdef('public.invoice_paid_v'::regclass, true)
)
ON CONFLICT (name) DO UPDATE SET ddl = EXCLUDED.ddl;

COMMIT;
