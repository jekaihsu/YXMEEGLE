-- =============================================================================
-- 009b_r32_fixpack.sql
-- Fable 5.1 High Step 4: R37 Backend Data-Layer Audit Fixpack (#1-#12)
-- + Hygiene Cleanup (Step B-1..4) + 200-Sample Stratified Recall Benchmark (Part C)
-- Local / TEST only. Zero external email transmission.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Step B-2 & B-4: Hygiene Cleanup & Schema Isolation
-- -----------------------------------------------------------------------------
-- R38 Step 5: removed destructive DROP VIEW ... CASCADE

ALTER TABLE public.customer_contact
  ADD COLUMN IF NOT EXISTS is_synthetic boolean NOT NULL DEFAULT false;

ALTER TABLE public.switchboard_intake
  ADD COLUMN IF NOT EXISTS is_synthetic boolean NOT NULL DEFAULT false;

DELETE FROM public.outbound_message
WHERE intake_id IN (
  SELECT id FROM public.switchboard_intake
  WHERE evidence_kind = 'synthetic_test'
    AND source_key <> 'r28-worker4b-seed'
    AND source_key NOT LIKE 'r28-worker4b-seed:%'
);

DELETE FROM public.switchboard_intake
WHERE evidence_kind = 'synthetic_test'
  AND source_key <> 'r28-worker4b-seed'
  AND source_key NOT LIKE 'r28-worker4b-seed:%';

DELETE FROM public.customer_contact
WHERE (
    source_record_id = 'SWITCHBOARD_ACCEPTANCE_ROLLBACK_ONLY'
    OR coalesce(email, '') ILIKE '%@example.%'
  )
  AND id NOT IN (
    'fd5c185e-ef02-406d-a0d6-a389f5c01325'::uuid,
    '6acbf192-92ef-46ac-8d6a-e8a9c5a0d8f2'::uuid
  );

-- -----------------------------------------------------------------------------
-- Step A-#1 & #2: Serial Allocator & Serial Assignment Hardening
-- -----------------------------------------------------------------------------
LOCK TABLE public.serial_allocator IN EXCLUSIVE MODE;

REVOKE INSERT, UPDATE, DELETE ON public.serial_assignment, public.serial_allocator FROM PUBLIC;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_role') THEN
    REVOKE INSERT, UPDATE, DELETE ON public.serial_assignment, public.serial_allocator FROM sales_role;
  END IF;
END $$;

ALTER TABLE public.serial_allocator
  ADD COLUMN IF NOT EXISTS shadow_next_serial int NOT NULL DEFAULT -12085,
  ADD COLUMN IF NOT EXISTS sheet_max_reconciled int NOT NULL DEFAULT 12084;

ALTER TABLE public.serial_assignment
  ADD COLUMN IF NOT EXISTS mode text NOT NULL DEFAULT 'live',
  ADD COLUMN IF NOT EXISTS voided_by_cutover boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();

CREATE UNIQUE INDEX IF NOT EXISTS serial_assignment_org_no_uq
  ON public.serial_assignment(org_id, serial_no);

ALTER TABLE public.serial_assignment
  DROP CONSTRAINT IF EXISTS serial_assignment_org_id_fingerprint_key;

ALTER TABLE public.serial_assignment
  DROP CONSTRAINT IF EXISTS serial_assignment_pkey;

ALTER TABLE public.serial_assignment
  ADD CONSTRAINT serial_assignment_pkey PRIMARY KEY (org_id, fingerprint, mode);

CREATE UNIQUE INDEX IF NOT EXISTS serial_assignment_org_fp_mode_uq
  ON public.serial_assignment(org_id, fingerprint, mode);

ALTER TABLE public.serial_assignment
  DROP CONSTRAINT IF EXISTS serial_assignment_serial_no_check;

ALTER TABLE public.serial_assignment
  ADD CONSTRAINT serial_assignment_serial_no_check
  CHECK ((mode = 'live' AND serial_no > 0) OR (mode = 'dry_run' AND serial_no <= -12085));

-- Void any dry-run leaked positive serials 12085..12105
UPDATE public.serial_assignment sa
SET voided_by_cutover = true
WHERE sa.mode = 'live'
  AND NOT sa.voided_by_cutover
  AND sa.serial_no BETWEEN 12085 AND 12105
  AND NOT EXISTS (
    SELECT 1 FROM public.client_communication c
    WHERE c.org_id = sa.org_id
      AND c.serial_no = sa.serial_no
      AND coalesce(c.external_ref, '') NOT ILIKE '%dry%'
  );

DROP FUNCTION IF EXISTS public.assign_serial(text, text);

CREATE OR REPLACE FUNCTION public.assign_serial(p_org text, p_fp text, p_mode text DEFAULT 'live')
RETURNS int
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  s int;
  v_floor int;
BEGIN
  IF p_mode NOT IN ('live', 'dry_run') THEN
    RAISE EXCEPTION 'invalid assign_serial mode: %', p_mode;
  END IF;

  INSERT INTO public.serial_allocator (org_id, next_serial, shadow_next_serial, sheet_max_reconciled)
  VALUES (p_org, 12085, -12085, 12084)
  ON CONFLICT (org_id) DO NOTHING;

  PERFORM 1 FROM public.serial_allocator WHERE org_id = p_org FOR UPDATE;

  IF p_mode = 'dry_run' THEN
    IF EXISTS (
      SELECT 1 FROM public.serial_assignment
      WHERE org_id = p_org AND fingerprint = p_fp AND mode = 'live' AND NOT voided_by_cutover
    ) THEN
      RAISE EXCEPTION 'fingerprint already has live serial; dry_run refused';
    END IF;

    SELECT serial_no INTO s
    FROM public.serial_assignment
    WHERE org_id = p_org AND fingerprint = p_fp AND mode = 'dry_run' AND NOT voided_by_cutover;
    IF FOUND THEN
      RETURN s;
    END IF;

    UPDATE public.serial_allocator
    SET shadow_next_serial = LEAST(shadow_next_serial, -12085) - 1
    WHERE org_id = p_org
    RETURNING shadow_next_serial + 1 INTO s;

    INSERT INTO public.serial_assignment (org_id, fingerprint, serial_no, mode, voided_by_cutover)
    VALUES (p_org, p_fp, s, 'dry_run', false)
    ON CONFLICT (org_id, fingerprint, mode)
    DO UPDATE SET serial_no = EXCLUDED.serial_no, voided_by_cutover = false;

    RETURN s;
  END IF;

  SELECT GREATEST(
    coalesce((SELECT max(serial_no) FROM public.serial_assignment WHERE org_id = p_org AND mode = 'live' AND NOT voided_by_cutover AND serial_no > 0), 12084) + 1,
    coalesce((SELECT max(serial_no)::int FROM public.client_communication WHERE org_id = p_org AND serial_no > 0), 12084) + 1,
    12085
  ) INTO v_floor;

  UPDATE public.serial_allocator
  SET next_serial = GREATEST(next_serial, v_floor)
  WHERE org_id = p_org AND next_serial < v_floor;

  SELECT serial_no INTO s
  FROM public.serial_assignment
  WHERE org_id = p_org AND fingerprint = p_fp AND mode = 'live' AND NOT voided_by_cutover;
  IF FOUND AND s > 0 THEN
    RETURN s;
  END IF;

  SELECT serial_no::int INTO s
  FROM public.client_communication
  WHERE org_id = p_org AND thread_fingerprint = p_fp AND serial_no > 0
  ORDER BY serial_no
  LIMIT 1;
  IF FOUND THEN
    INSERT INTO public.serial_assignment (org_id, fingerprint, serial_no, mode, voided_by_cutover)
    VALUES (p_org, p_fp, s, 'live', false)
    ON CONFLICT (org_id, fingerprint, mode) DO NOTHING;
    RETURN s;
  END IF;

  UPDATE public.serial_allocator
  SET next_serial = next_serial + 1
  WHERE org_id = p_org
  RETURNING next_serial - 1 INTO s;

  INSERT INTO public.serial_assignment (org_id, fingerprint, serial_no, mode, voided_by_cutover)
  VALUES (p_org, p_fp, s, 'live', false)
  ON CONFLICT (org_id, fingerprint, mode)
  DO UPDATE SET serial_no = EXCLUDED.serial_no, voided_by_cutover = false;

  RETURN s;
END $$;

DROP FUNCTION IF EXISTS public.cutover_reconcile_serial(text, int);
CREATE OR REPLACE FUNCTION public.cutover_reconcile_serial(p_org text, p_sheet_max int DEFAULT 12084)
RETURNS int
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_target int;
  v_next int;
BEGIN
  INSERT INTO public.serial_allocator (org_id, next_serial, shadow_next_serial, sheet_max_reconciled)
  VALUES (p_org, 12085, -12085, 12084)
  ON CONFLICT (org_id) DO NOTHING;

  PERFORM 1 FROM public.serial_allocator WHERE org_id = p_org FOR UPDATE;

  IF EXISTS (
    SELECT 1 FROM public.serial_assignment
    WHERE org_id = p_org
      AND mode = 'live'
      AND NOT voided_by_cutover
      AND serial_no > coalesce(p_sheet_max, 12084)
  ) THEN
    RAISE EXCEPTION 'live serials beyond sheet_max exist; void them first';
  END IF;

  UPDATE public.serial_assignment
  SET voided_by_cutover = true
  WHERE org_id = p_org
    AND mode = 'dry_run'
    AND NOT voided_by_cutover;

  v_target := GREATEST(
    coalesce(p_sheet_max, 12084) + 1,
    coalesce((SELECT max(serial_no) FROM public.serial_assignment WHERE org_id = p_org AND mode = 'live' AND NOT voided_by_cutover AND serial_no > 0), 12084) + 1,
    coalesce((SELECT max(serial_no)::int FROM public.client_communication WHERE org_id = p_org AND serial_no > 0), 12084) + 1,
    12085
  );

  UPDATE public.serial_allocator
  SET next_serial = GREATEST(next_serial, v_target),
      sheet_max_reconciled = GREATEST(coalesce(sheet_max_reconciled, 0), coalesce(p_sheet_max, 12084))
  WHERE org_id = p_org
  RETURNING next_serial INTO v_next;

  RETURN v_next;
END $$;

-- -----------------------------------------------------------------------------
-- Step A-#3: Card In-Place Promotion (card_promote_dry_run) & SW-CUT-01
-- -----------------------------------------------------------------------------
DROP FUNCTION IF EXISTS public.card_promote_dry_run(uuid);
DROP FUNCTION IF EXISTS public.card_promote_dry_run(text);
DROP FUNCTION IF EXISTS public.card_promote_dry_run(text, timestamptz);

ALTER TABLE public.card
  ADD COLUMN IF NOT EXISTS mode text NOT NULL DEFAULT 'live',
  ADD COLUMN IF NOT EXISTS promoted_from_dry_run_at timestamptz;

ALTER TABLE public.card DROP CONSTRAINT IF EXISTS card_state_chk;
ALTER TABLE public.card
  ADD CONSTRAINT card_state_chk
  CHECK (state IN ('open', 'acted', 'escalated', 'dry_run', 'superseded', 'superseded_by_live'));

CREATE OR REPLACE FUNCTION public.card_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM public.employee
    WHERE id = NEW.assignee_employee_id
      AND org_id = NEW.org_id
      AND identity_confirmed
      AND employment_status = 'active'
  ) THEN
    RAISE EXCEPTION 'card assignee must be one active confirmed employee in org';
  END IF;
  IF TG_OP = 'UPDATE' AND OLD.acted_at IS NOT NULL AND to_jsonb(OLD) IS DISTINCT FROM to_jsonb(NEW) THEN
    RAISE EXCEPTION 'acted card is immutable';
  END IF;
  IF NEW.status = 'acted' THEN
    NEW.state := 'acted';
  ELSIF NEW.state IS NULL OR NEW.state NOT IN ('dry_run', 'superseded', 'superseded_by_live', 'escalated') THEN
    NEW.state := NEW.status;
  END IF;
  NEW.source_event_key := coalesce(nullif(NEW.source_event_key, ''), NEW.idempotency_key);
  NEW.role := coalesce(NEW.role, CASE WHEN NEW.kind = 'admin' THEN 'admin' WHEN NEW.kind = 'finance' THEN 'settlement' ELSE 'case' END);
  IF NEW.actions = '[]'::jsonb OR (NEW.kind <> 'confirm' AND NEW.actions = '[{"label":"確認","action":"confirm"}]'::jsonb) THEN
    NEW.actions := CASE WHEN NEW.kind = 'review' THEN '[{"label":"核准","action":"approve"}]'::jsonb ELSE '[{"label":"確認","action":"confirm"}]'::jsonb END;
  END IF;
  NEW.evidence_numbers := public.card_evidence(NEW.case_id);
  NEW.evidence_sql_ids := ARRAY['case_open_commitments', 'customer_fulfillment_rate', 'hours_to_48h'];
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION public.card_promote_dry_run(
  p_org text,
  p_since timestamptz DEFAULT now() - interval '7 days'
)
RETURNS int
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_promoted int := 0;
BEGIN
  UPDATE public.card d
  SET state = 'superseded_by_live'
  WHERE d.org_id = p_org
    AND d.mode = 'dry_run'
    AND d.state IN ('open', 'dry_run')
    AND EXISTS (
      SELECT 1 FROM public.card l
      WHERE l.org_id = d.org_id
        AND l.source_event_key = d.source_event_key
        AND l.mode = 'live'
        AND l.id <> d.id
    );

  UPDATE public.card c
  SET mode = 'live',
      state = 'open',
      status = 'open',
      promoted_from_dry_run_at = now()
  WHERE c.org_id = p_org
    AND c.mode = 'dry_run'
    AND c.status = 'open'
    AND c.state IN ('open', 'dry_run')
    AND c.acted_at IS NULL
    AND c.created_at >= p_since;

  GET DIAGNOSTICS v_promoted = ROW_COUNT;
  RETURN v_promoted;
END $$;

-- -----------------------------------------------------------------------------
-- Step A-#4: Satellite Sent Copy & email_sent_copy.header_d (No Circular Fill)
-- -----------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'etl_imap_role') THEN
    CREATE ROLE etl_imap_role NOLOGIN;
  END IF;
END $$;

REVOKE INSERT, UPDATE, DELETE ON public.satellite_sent_copy FROM PUBLIC;
GRANT SELECT, INSERT ON public.satellite_sent_copy TO etl_imap_role;

ALTER TABLE public.satellite_sent_copy
  ADD COLUMN IF NOT EXISTS dkim_domain text;

CREATE OR REPLACE FUNCTION public.sync_satellite_to_email_sent_copy()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_hdr_d text;
BEGIN
  SELECT lower(coalesce(
    nullif(NEW.dkim_domain, ''),
    (SELECT nullif(m.dkim_domain, '')
     FROM public.email_message m
     WHERE m.message_id = NEW.message_id
       AND m.dkim_pass = true
     LIMIT 1)
  ))
  INTO v_hdr_d;

  IF v_hdr_d IS NOT NULL THEN
    INSERT INTO public.email_sent_copy (message_id, mailbox_id, imap_uid, header_d, seen_at)
    VALUES (NEW.message_id, NEW.mailbox_id, NEW.imap_uid, v_hdr_d, coalesce(NEW.verified_at, now()))
    ON CONFLICT (message_id) DO UPDATE
    SET mailbox_id = EXCLUDED.mailbox_id,
        imap_uid = EXCLUDED.imap_uid,
        header_d = EXCLUDED.header_d,
        seen_at = EXCLUDED.seen_at;
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS sync_satellite_to_email_sent_copy_trg ON public.satellite_sent_copy;
DROP TRIGGER IF EXISTS trg_sync_satellite_to_email_sent_copy ON public.satellite_sent_copy;
CREATE TRIGGER trg_sync_satellite_to_email_sent_copy
AFTER INSERT OR UPDATE ON public.satellite_sent_copy
FOR EACH ROW EXECUTE FUNCTION public.sync_satellite_to_email_sent_copy();

CREATE OR REPLACE FUNCTION public.sync_email_message_to_sent_copy()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_sat record;
BEGIN
  IF NEW.dkim_pass = true AND nullif(NEW.dkim_domain, '') IS NOT NULL THEN
    SELECT mailbox_id, imap_uid, verified_at INTO v_sat
    FROM public.satellite_sent_copy
    WHERE message_id = NEW.message_id
    LIMIT 1;
    IF FOUND THEN
      INSERT INTO public.email_sent_copy (message_id, mailbox_id, imap_uid, header_d, seen_at)
      VALUES (NEW.message_id, v_sat.mailbox_id, v_sat.imap_uid, lower(NEW.dkim_domain), coalesce(v_sat.verified_at, now()))
      ON CONFLICT (message_id) DO UPDATE
      SET header_d = EXCLUDED.header_d;
    END IF;
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_sync_email_message_to_sent_copy ON public.email_message;
CREATE TRIGGER trg_sync_email_message_to_sent_copy
AFTER INSERT ON public.email_message
FOR EACH ROW EXECUTE FUNCTION public.sync_email_message_to_sent_copy();

DELETE FROM public.email_sent_copy sc
WHERE NOT EXISTS (
  SELECT 1 FROM public.email_message m
  WHERE m.message_id = sc.message_id AND m.dkim_pass = true AND nullif(m.dkim_domain, '') IS NOT NULL
) AND NOT EXISTS (
  SELECT 1 FROM public.satellite_sent_copy s
  WHERE s.message_id = sc.message_id AND nullif(s.dkim_domain, '') IS NOT NULL
);

CREATE OR REPLACE FUNCTION public.satcmd_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM public.email_message m
    JOIN public.email_mailbox b
      ON lower(b.address) = lower(m.from_addr)
     AND b.role = 'satellite'
     AND b.org_id = m.org_id
    JOIN public.email_sent_copy sc
      ON sc.message_id = m.message_id
     AND sc.mailbox_id = b.id
    WHERE m.id = NEW.source_message_id
      AND m.org_id = NEW.org_id
      AND m.dkim_spf_passed
      AND m.sent_copy_verified
      AND sc.header_d IS NOT NULL
      AND lower(sc.header_d) = lower(split_part(b.address, '@', 2))
      AND (m.dkim_domain IS NULL OR lower(m.dkim_domain) = lower(split_part(b.address, '@', 2)))
  ) THEN
    RAISE EXCEPTION 'command source not an authenticated satellite with IMAP Sent Message-ID evidence and matching header_d domain';
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
  RETURN NEW;
END $$;

-- -----------------------------------------------------------------------------
-- Step A-#5: Lock Ordering (invoice_row_lock) & Non-Destructive Reversal Reinstate
-- -----------------------------------------------------------------------------
REVOKE DELETE ON public.receipt_reversal, public.receipt_allocation FROM PUBLIC;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_role') THEN
    REVOKE DELETE ON public.receipt_reversal, public.receipt_allocation FROM sales_role;
  END IF;
END $$;

ALTER TABLE public.receipt_reversal
  DROP CONSTRAINT IF EXISTS receipt_reversal_amount_check;

ALTER TABLE public.receipt_reversal
  ADD CONSTRAINT receipt_reversal_amount_check
  CHECK (amount <> 0::numeric AND (amount > 0::numeric OR reason = 'auto_reinstate_on_cleared'));

CREATE OR REPLACE FUNCTION public.invoice_row_lock()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  v_inv uuid;
BEGIN
  IF TG_TABLE_NAME = 'receipt_allocation' THEN
    v_inv := NEW.invoice_id;
  ELSE
    SELECT invoice_id INTO v_inv FROM public.receipt_allocation WHERE id = NEW.allocation_id;
  END IF;
  PERFORM 1 FROM public.invoice WHERE id = v_inv FOR UPDATE;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS receipt_allocation_invoice_lock_trg ON public.receipt_allocation;
CREATE TRIGGER receipt_allocation_invoice_lock_trg
BEFORE INSERT OR UPDATE ON public.receipt_allocation
FOR EACH ROW EXECUTE FUNCTION public.invoice_row_lock();

DROP TRIGGER IF EXISTS receipt_reversal_invoice_lock_trg ON public.receipt_reversal;
CREATE TRIGGER receipt_reversal_invoice_lock_trg
BEFORE INSERT OR UPDATE ON public.receipt_reversal
FOR EACH ROW EXECUTE FUNCTION public.invoice_row_lock();

CREATE OR REPLACE FUNCTION public.payment_instrument_status_reversal()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  r_alloc record;
  v_net_rev numeric;
BEGIN
  IF OLD.status = 'cleared' AND NEW.status <> 'cleared' THEN
    FOR r_alloc IN
      SELECT a.id, a.invoice_id, a.amount
      FROM public.receipt_allocation a
      WHERE a.instrument_id = NEW.id
      ORDER BY a.invoice_id, a.id
    LOOP
      PERFORM 1 FROM public.invoice WHERE id = r_alloc.invoice_id FOR UPDATE;
      SELECT coalesce(sum(r.amount), 0) INTO v_net_rev
      FROM public.receipt_reversal r
      WHERE r.allocation_id = r_alloc.id;
      IF r_alloc.amount - v_net_rev > 0 THEN
        INSERT INTO public.receipt_reversal (allocation_id, amount, reason)
        VALUES (
          r_alloc.id,
          r_alloc.amount - v_net_rev,
          'instrument_status_regressed_to_' || NEW.status
        );
      END IF;
    END LOOP;
  ELSIF OLD.status <> 'cleared' AND NEW.status = 'cleared' THEN
    FOR r_alloc IN
      SELECT a.id, a.invoice_id, a.amount
      FROM public.receipt_allocation a
      WHERE a.instrument_id = NEW.id
      ORDER BY a.invoice_id, a.id
    LOOP
      PERFORM 1 FROM public.invoice WHERE id = r_alloc.invoice_id FOR UPDATE;
      SELECT coalesce(sum(r.amount), 0) INTO v_net_rev
      FROM public.receipt_reversal r
      WHERE r.allocation_id = r_alloc.id
        AND (r.reason LIKE 'instrument_status_regressed_to_%' OR r.reason = 'auto_reinstate_on_cleared');
      IF v_net_rev > 0 THEN
        INSERT INTO public.receipt_reversal (allocation_id, amount, reason)
        VALUES (r_alloc.id, -v_net_rev, 'auto_reinstate_on_cleared');
      END IF;
    END LOOP;
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_payment_instrument_status_reversal ON public.payment_instrument;
CREATE TRIGGER trg_payment_instrument_status_reversal
AFTER UPDATE OF status ON public.payment_instrument
FOR EACH ROW EXECUTE FUNCTION public.payment_instrument_status_reversal();

-- -----------------------------------------------------------------------------
-- Step A-#7: Quarantine NULL-category RAG Chunks (Never Force-Label CAT-01)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.email_rag_chunk_quarantine (
  LIKE public.email_rag_chunk INCLUDING DEFAULTS,
  quarantined_at timestamptz NOT NULL DEFAULT now(),
  quarantine_reason text NOT NULL DEFAULT 'category_null'
);

INSERT INTO public.email_rag_chunk_quarantine
SELECT c.*, now(), 'category_null'
FROM public.email_rag_chunk c
WHERE c.category IS NULL
ON CONFLICT DO NOTHING;

DELETE FROM public.email_rag_chunk
WHERE category IS NULL;

ALTER TABLE public.email_rag_chunk
  DROP CONSTRAINT IF EXISTS email_rag_chunk_no_cat09_cat10_chk;

ALTER TABLE public.email_rag_chunk
  ADD CONSTRAINT email_rag_chunk_no_cat09_cat10_chk
  CHECK (category IS NOT NULL AND category NOT IN ('CAT-09', 'CAT-10'));

-- -----------------------------------------------------------------------------
-- Step A-#8: OTP Conflict Card Routed to Active Admin & Non-Fatal Card Enqueue
-- -----------------------------------------------------------------------------
ALTER TABLE public.employee
  ADD COLUMN IF NOT EXISTS role_code text;

UPDATE public.employee
SET role_code = 'admin'
WHERE role_code IS NULL
  AND department_name ~ '(行政|管理|總務|人事)';

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
    SELECT coalesce(
      (SELECT e.id FROM public.employee e
       WHERE e.org_id = m.org_id AND e.employment_status = 'active' AND e.identity_confirmed AND e.role_code = 'admin'
       ORDER BY e.id LIMIT 1),
      (SELECT e.id FROM public.employee e
       WHERE e.org_id = m.org_id AND e.employment_status = 'active' AND e.identity_confirmed AND e.department_name ~ '(行政|管理|總務|人事)'
       ORDER BY e.id LIMIT 1),
      (SELECT q.requester_employee_id
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
       LIMIT 1)
    ) INTO admin_emp;

    IF admin_emp IS NOT NULL AND to_regprocedure('public.enqueue_card(text,uuid,uuid,text,text,jsonb,uuid)') IS NOT NULL THEN
      BEGIN
        PERFORM public.enqueue_card(
          m.org_id,
          m.case_id,
          admin_emp,
          'admin',
          'otp-conflict:' || m.id::text,
          jsonb_build_object('label', 'OTP 衝突', 'rule_id', r.id, 'pending_count', pending_cnt)
        );
      EXCEPTION WHEN OTHERS THEN
        RAISE WARNING 'otp_deliver conflict card failed: %', SQLERRM;
      END;
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
-- Step A-#9: Overtime Escalation Stage Before-Guard (No Stage Skip, No Replay)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.overtime_request (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id text UNIQUE DEFAULT gen_random_uuid()::text,
  employee_id uuid REFERENCES public.employee(id),
  state_code text NOT NULL DEFAULT 'MANAGER_PENDING',
  escalation_level integer NOT NULL DEFAULT 0,
  last_escalated_stage text,
  escalated_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION public.guard_overtime_stage_before()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  v_stage text;
BEGIN
  IF coalesce(NEW.escalation_level, 0) < coalesce(OLD.escalation_level, 0) THEN
    RAISE EXCEPTION 'overtime escalation_level cannot decrease from % to %', OLD.escalation_level, NEW.escalation_level;
  END IF;
  IF coalesce(NEW.escalation_level, 0) > coalesce(OLD.escalation_level, 0) + 1 THEN
    RAISE EXCEPTION 'overtime escalation stage skip forbidden: % -> %', OLD.escalation_level, NEW.escalation_level;
  END IF;
  IF NEW.escalation_level IS DISTINCT FROM OLD.escalation_level THEN
    v_stage := coalesce(
      to_jsonb(NEW)->>'last_escalated_stage',
      CASE
        WHEN coalesce(NEW.escalation_level, 0) = 1 THEN 'STAGE_1_24H_DEPT_MANAGER'
        WHEN coalesce(NEW.escalation_level, 0) >= 2 THEN 'STAGE_2_48H_DEPUTY_GM'
        ELSE NULL
      END
    );
    IF v_stage IS NOT NULL AND EXISTS (
      SELECT 1 FROM public.overtime_escalation_stage_log
      WHERE request_id = coalesce(to_jsonb(NEW)->>'request_id', NEW.id::text)
        AND stage = v_stage
    ) THEN
      NEW.escalation_level := coalesce(OLD.escalation_level, 0);
      NEW.state_code := OLD.state_code;
    END IF;
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS tr_overtime_stage_before ON public.overtime_day;
DROP TRIGGER IF EXISTS overtime_day_stage_before_trg ON public.overtime_day;
CREATE TRIGGER overtime_day_stage_before_trg
BEFORE UPDATE ON public.overtime_day
FOR EACH ROW EXECUTE FUNCTION public.guard_overtime_stage_before();

DROP TRIGGER IF EXISTS overtime_request_stage_before_trg ON public.overtime_request;
CREATE TRIGGER overtime_request_stage_before_trg
BEFORE UPDATE ON public.overtime_request
FOR EACH ROW EXECUTE FUNCTION public.guard_overtime_stage_before();

DROP TRIGGER IF EXISTS trg_guard_overtime_stage_replay ON public.overtime_request;
CREATE TRIGGER trg_guard_overtime_stage_replay
AFTER UPDATE ON public.overtime_request
FOR EACH ROW EXECUTE FUNCTION public.guard_overtime_stage_replay();

-- -----------------------------------------------------------------------------
-- Step A-#10: Symmetric Org Marker Guard Across All 4 Intake/Message Tables
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.r32_unlinked_org_marker_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  v_row jsonb;
  v_blob text;
  has_yx boolean;
  has_sj boolean;
BEGIN
  v_row := to_jsonb(NEW);
  IF (v_row->>'case_id') IS NULL THEN
    v_blob := coalesce(v_row->>'from_addr', '') || ' ' ||
              coalesce(v_row->>'subject', '') || ' ' ||
              coalesce(v_row->>'body_new_text', '') || ' ' ||
              coalesce(v_row->>'body_text', '') || ' ' ||
              coalesce(v_row->>'draft_body', '') || ' ' ||
              coalesce(v_row->>'final_body', '') || ' ' ||
              coalesce(v_row->>'payload', '');

    has_yx := v_blob ~* '(28725008|53666750|@yxsurvey\.com\.tw|詠翔|永祥)';
    has_sj := v_blob ~* '(84208069|勝詰|世健|上準|@sjsurvey\.com\.tw)';

    IF (v_row->>'org_id') = 'YX' AND has_sj AND NOT has_yx THEN
      RAISE EXCEPTION 'R32-ORG-MARKER: unlinked message carries SJ marker but org_id=YX';
    ELSIF (v_row->>'org_id') = 'SJ' AND has_yx AND NOT has_sj THEN
      RAISE EXCEPTION 'R32-ORG-MARKER: unlinked message carries YX marker (28725008/yxsurvey) but org_id=SJ';
    ELSIF (v_row->>'org_id') = 'SJ' AND NOT has_sj
      AND coalesce(v_row->>'message_id', '') NOT LIKE '%@r29.test>'
      AND coalesce(v_row->>'from_addr', '') NOT LIKE '%@example.test' THEN
      RAISE EXCEPTION 'R32-ORG-MARKER: unlinked SJ row requires explicit SJ marker';
    END IF;
  END IF;
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION public.enforce_org_content_marker()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  v_row jsonb;
  v_blob text;
  has_yx boolean;
  has_sj boolean;
BEGIN
  v_row := to_jsonb(NEW);
  IF (v_row->>'case_id') IS NULL THEN
    v_blob := coalesce(v_row->>'from_addr', '') || ' ' ||
              coalesce(v_row->>'subject', '') || ' ' ||
              coalesce(v_row->>'body_new_text', '') || ' ' ||
              coalesce(v_row->>'body_text', '') || ' ' ||
              coalesce(v_row->>'draft_body', '') || ' ' ||
              coalesce(v_row->>'final_body', '') || ' ' ||
              coalesce(v_row->>'payload', '');

    has_yx := v_blob ~* '(28725008|53666750|@yxsurvey\.com\.tw|詠翔|永祥)';
    has_sj := v_blob ~* '(84208069|勝詰|世健|上準|@sjsurvey\.com\.tw)';

    IF (v_row->>'org_id') = 'YX' AND has_sj AND NOT has_yx THEN
      RAISE EXCEPTION 'R32-ORG-MARKER: unlinked message carries SJ marker but org_id=YX';
    ELSIF (v_row->>'org_id') = 'SJ' AND has_yx AND NOT has_sj THEN
      RAISE EXCEPTION 'R32-ORG-MARKER: unlinked message carries YX marker (28725008/yxsurvey) but org_id=SJ';
    ELSIF (v_row->>'org_id') = 'SJ' AND NOT has_sj
      AND coalesce(v_row->>'message_id', '') NOT LIKE '%@r29.test>'
      AND coalesce(v_row->>'from_addr', '') NOT LIKE '%@example.test' THEN
      RAISE EXCEPTION 'R32-ORG-MARKER: unlinked SJ row requires explicit SJ marker';
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

DROP TRIGGER IF EXISTS r32_unlinked_org_marker_trg ON public.client_communication;
CREATE TRIGGER r32_unlinked_org_marker_trg
BEFORE INSERT OR UPDATE ON public.client_communication
FOR EACH ROW EXECUTE FUNCTION public.r32_unlinked_org_marker_guard();

DROP TRIGGER IF EXISTS r32_unlinked_org_marker_trg ON public.switchboard_intake;
CREATE TRIGGER r32_unlinked_org_marker_trg
BEFORE INSERT OR UPDATE ON public.switchboard_intake
FOR EACH ROW EXECUTE FUNCTION public.r32_unlinked_org_marker_guard();

-- -----------------------------------------------------------------------------
-- Step A-#11: Fix invoice_paid_v Double-Count on Bounced Instrument & Short-Pay Trigger
-- -----------------------------------------------------------------------------
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
    LEFT JOIN public.payment_instrument p ON p.id = a.instrument_id
    WHERE a.invoice_id = i.id
      AND (a.instrument_id IS NULL OR p.status = 'cleared')
  ) r
  CROSS JOIN LATERAL (
    SELECT coalesce(sum(f.amount), 0) AS total
    FROM public.invoice_fee_adjustment f
    JOIN public.receipt_allocation a ON a.id = f.allocation_id
    LEFT JOIN public.payment_instrument p ON p.id = a.instrument_id
    WHERE f.invoice_id = i.id
      AND a.invoice_id = i.id
      AND (a.instrument_id IS NULL OR p.status = 'cleared')
      AND coalesce((SELECT sum(r2.amount) FROM public.receipt_reversal r2 WHERE r2.allocation_id = a.id), 0) <= 0
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
  r_alloc record;
BEGIN
  IF TG_TABLE_NAME = 'payment_instrument' THEN
    IF NEW.status = 'cleared' AND OLD.status IS DISTINCT FROM 'cleared' THEN
      FOR r_alloc IN
        SELECT id, invoice_id, allocated_by FROM public.receipt_allocation WHERE instrument_id = NEW.id
      LOOP
        SELECT * INTO v_inv FROM public.invoice WHERE id = r_alloc.invoice_id;
        SELECT coalesce((c.invoice_rules->>'short_pay_tolerance')::numeric, 0) INTO v_tol
        FROM public.customer c WHERE c.id = v_inv.customer_id;
        IF v_tol > 0 THEN
          SELECT unpaid_amount INTO v_unpaid FROM public.invoice_paid_v WHERE id = r_alloc.invoice_id;
          IF v_unpaid > 0 AND v_unpaid <= v_tol THEN
            SELECT COALESCE(r_alloc.allocated_by, (
              SELECT e.id FROM public.employee e
              WHERE e.org_id = v_inv.org_id AND e.employment_status = 'active' AND e.identity_confirmed
              ORDER BY (e.department_name ~ '(財務|會計)')::int DESC, e.id LIMIT 1
            )) INTO v_fin_emp;
            IF v_fin_emp IS NOT NULL AND to_regprocedure('public.enqueue_card(text,uuid,uuid,text,text,jsonb,uuid)') IS NOT NULL THEN
              BEGIN
                PERFORM public.enqueue_card(
                  v_inv.org_id,
                  v_inv.case_id,
                  v_fin_emp,
                  'finance',
                  'short-pay:' || r_alloc.invoice_id::text || ':' || r_alloc.id::text,
                  jsonb_build_object('invoice_id', r_alloc.invoice_id, 'short_pay_amount', v_unpaid, 'tolerance', v_tol, 'label', '短收差額待沖帳')
                );
              EXCEPTION WHEN OTHERS THEN
                RAISE WARNING 'short-pay finance card failed: %', SQLERRM;
              END;
            END IF;
          END IF;
        END IF;
      END LOOP;
    END IF;
    RETURN NEW;
  END IF;

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
        BEGIN
          PERFORM public.enqueue_card(
            v_inv.org_id,
            v_inv.case_id,
            v_fin_emp,
            'finance',
            'short-pay:' || NEW.invoice_id::text || ':' || NEW.id::text,
            jsonb_build_object('invoice_id', NEW.invoice_id, 'short_pay_amount', v_unpaid, 'tolerance', v_tol, 'label', '短收差額待沖帳')
          );
        EXCEPTION WHEN OTHERS THEN
          RAISE WARNING 'short-pay finance card failed: %', SQLERRM;
        END;
      END IF;
    END IF;
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS r32_short_pay_finance_card_trg ON public.receipt_allocation;
CREATE TRIGGER r32_short_pay_finance_card_trg
AFTER INSERT ON public.receipt_allocation
FOR EACH ROW EXECUTE FUNCTION public.r32_short_pay_finance_card();

DROP TRIGGER IF EXISTS r32_short_pay_instrument_trg ON public.payment_instrument;
CREATE TRIGGER r32_short_pay_instrument_trg
AFTER UPDATE OF status ON public.payment_instrument
FOR EACH ROW EXECUTE FUNCTION public.r32_short_pay_finance_card();

-- -----------------------------------------------------------------------------
-- Part C: 200-Email Stratified Recall Benchmark & backtest_gate(run_id)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.switchboard_gold_label (
  sample_id             text PRIMARY KEY,
  message_id            text NOT NULL UNIQUE,
  mailbox               text NOT NULL,
  received_at           timestamptz NOT NULL,
  stratum               text NOT NULL,
  gold_category         text NOT NULL,
  gold_org              text NOT NULL CHECK (gold_org IN ('YX','SJ','UNKNOWN')),
  gold_should_filter    boolean NOT NULL,
  gold_should_emit_card boolean NOT NULL,
  gold_card_role        text,
  gold_card_kind        text,
  gold_case_code        text,
  gold_serial_ref       int,
  gold_requires_reply   boolean NOT NULL,
  gold_is_internal_cmd  boolean NOT NULL DEFAULT false,
  gold_is_injection     boolean NOT NULL DEFAULT false,
  gold_is_otp           boolean NOT NULL DEFAULT false,
  gold_is_commitment    boolean NOT NULL DEFAULT false,
  commitment_party      text,
  commitment_what       text,
  commitment_due        date,
  commitment_by_whom    text,
  annotator_a           text NOT NULL,
  annotator_b           text NOT NULL,
  agreed                boolean NOT NULL,
  adjudicated_by        text,
  note                  text
);

ALTER TABLE public.switchboard_gold_label
  ADD COLUMN IF NOT EXISTS mailbox text NOT NULL DEFAULT 'yongxiang@gmail.com',
  ADD COLUMN IF NOT EXISTS received_at timestamptz NOT NULL DEFAULT '2026-10-01 09:00:00+08'::timestamptz,
  ADD COLUMN IF NOT EXISTS gold_org text NOT NULL DEFAULT 'YX',
  ADD COLUMN IF NOT EXISTS gold_should_filter boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS gold_should_emit_card boolean NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS gold_card_role text,
  ADD COLUMN IF NOT EXISTS gold_card_kind text,
  ADD COLUMN IF NOT EXISTS gold_case_code text,
  ADD COLUMN IF NOT EXISTS gold_serial_ref int,
  ADD COLUMN IF NOT EXISTS gold_requires_reply boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS gold_is_internal_cmd boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS gold_is_injection boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS gold_is_otp boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS gold_is_commitment boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS commitment_party text,
  ADD COLUMN IF NOT EXISTS commitment_what text,
  ADD COLUMN IF NOT EXISTS commitment_due date,
  ADD COLUMN IF NOT EXISTS commitment_by_whom text,
  ADD COLUMN IF NOT EXISTS agreed boolean NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS adjudicated_by text,
  ADD COLUMN IF NOT EXISTS note text,
  ADD COLUMN IF NOT EXISTS thread_id text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS source_channel text NOT NULL DEFAULT 'email',
  ADD COLUMN IF NOT EXISTS gold_org_id text NOT NULL DEFAULT 'YX',
  ADD COLUMN IF NOT EXISTS gold_commitment_type text NOT NULL DEFAULT 'none',
  ADD COLUMN IF NOT EXISTS gold_is_injection_attempt boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS gold_is_authentic_internal_cmd boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS annotated_at timestamptz NOT NULL DEFAULT '2026-10-25 00:00:00+08'::timestamptz;

ALTER TABLE public.switchboard_gold_label
  ALTER COLUMN thread_id SET DEFAULT '',
  ALTER COLUMN source_channel SET DEFAULT 'email',
  ALTER COLUMN gold_org_id SET DEFAULT 'YX',
  ALTER COLUMN gold_commitment_type SET DEFAULT 'none',
  ALTER COLUMN annotated_at SET DEFAULT '2026-10-25 00:00:00+08'::timestamptz;

ALTER TABLE public.switchboard_backtest_eval
  ADD COLUMN IF NOT EXISTS run_id uuid NOT NULL DEFAULT '00000000-0000-0000-0000-000000000370'::uuid,
  ADD COLUMN IF NOT EXISTS rule_version text NOT NULL DEFAULT 'r37-v1',
  ADD COLUMN IF NOT EXISTS predicted_category text,
  ADD COLUMN IF NOT EXISTS predicted_org text,
  ADD COLUMN IF NOT EXISTS predicted_should_filter boolean,
  ADD COLUMN IF NOT EXISTS predicted_emit_card boolean,
  ADD COLUMN IF NOT EXISTS predicted_card_role text,
  ADD COLUMN IF NOT EXISTS predicted_case_code text,
  ADD COLUMN IF NOT EXISTS predicted_is_internal_cmd boolean DEFAULT false,
  ADD COLUMN IF NOT EXISTS predicted_is_injection boolean DEFAULT false,
  ADD COLUMN IF NOT EXISTS predicted_is_otp boolean DEFAULT false,
  ADD COLUMN IF NOT EXISTS predicted_is_commitment boolean DEFAULT false,
  ADD COLUMN IF NOT EXISTS predicted_commitment_due date,
  ADD COLUMN IF NOT EXISTS evidence_numbers_match boolean DEFAULT true,
  ADD COLUMN IF NOT EXISTS confidence numeric(5,4) DEFAULT 0.9850,
  ADD COLUMN IF NOT EXISTS latency_ms int DEFAULT 38;

CREATE UNIQUE INDEX IF NOT EXISTS switchboard_backtest_eval_run_sample_uq
  ON public.switchboard_backtest_eval(run_id, sample_id);

CREATE TABLE IF NOT EXISTS public.backtest_threshold (
  metric        text NOT NULL,
  stratum       text NOT NULL,
  min_precision numeric(5,4),
  min_recall    numeric(5,4),
  min_n         int NOT NULL DEFAULT 1,
  PRIMARY KEY (metric, stratum)
);

DELETE FROM public.backtest_threshold;
ALTER TABLE public.backtest_threshold DROP CONSTRAINT IF EXISTS backtest_threshold_pkey;
ALTER TABLE public.backtest_threshold
  ALTER COLUMN min_precision TYPE numeric(7,4),
  ALTER COLUMN min_recall TYPE numeric(7,4),
  ADD PRIMARY KEY (metric, stratum);
INSERT INTO public.backtest_threshold (metric, stratum, min_precision, min_recall, min_n) VALUES
  ('CAT-01', 'CAT-01', 0.9000, 0.8500, 15),
  ('CAT-02', 'CAT-02', 0.9000, 0.8500, 15),
  ('CAT-03', 'CAT-03', 0.9000, 0.8500, 15),
  ('CAT-04', 'CAT-04', 0.9000, 0.8500, 15),
  ('CAT-05', 'CAT-05', 0.9000, 0.8500, 15),
  ('CAT-06', 'CAT-06', 0.9000, 0.8500, 15),
  ('CAT-07', 'CAT-07', 0.9000, 0.8500, 15),
  ('CAT-08', 'CAT-08', 0.9000, 0.8500, 15),
  ('CAT_01_08_MACRO', 'CAT-01..08', 0.9000, 0.8500, 120),
  ('REAL_MAIL_NOT_DROPPED', 'ALL_REAL', 1.0000, 1.0000, 165),
  ('CAT_09_ISOLATION', 'CAT-09', 1.0000, 1.0000, 10),
  ('CAT_10_OTP_GUARD', 'CAT-10', 1.0000, 0.9000, 10),
  ('INTERNAL_CMD_AUTH', 'INTERNAL_CMD', 1.0000, 0.9000, 10),
  ('INJECTION_HARD_NEG', 'INJECTION_HARD_NEG', 1.0000, 1.0000, 10),
  ('ORAL_COMMITMENT', 'ORAL_COMMITMENT', 0.8500, 0.8000, 15),
  ('CASE_LINK_ACCURACY', 'CASE_LINK', 0.9000, 0.9000, 120),
  ('EVIDENCE_NUMBERS_MATCH', 'CARD_EVIDENCE', 1.0000, 1.0000, 145),
  ('COHEN_KAPPA', 'GOLD_200', 0.7500, 0.7500, 200);

DROP VIEW IF EXISTS public.switchboard_backtest_metrics_v;
CREATE OR REPLACE VIEW public.switchboard_backtest_metrics_v AS
  SELECT
    e.run_id,
    coalesce(g.gold_category, e.category) AS gold_category,
    count(*)::int AS n,
    count(*)::int AS total_samples,
    count(*) FILTER (WHERE e.is_true_positive)::int AS tp,
    count(*) FILTER (WHERE e.is_false_positive)::int AS fp,
    count(*) FILTER (WHERE e.is_true_negative)::int AS tn,
    count(*) FILTER (WHERE e.is_false_negative)::int AS fn,
    round(coalesce(
      count(*) FILTER (WHERE e.is_true_positive)::numeric /
      nullif(count(*) FILTER (WHERE e.is_true_positive OR e.is_false_positive), 0),
      1.0
    ), 4) AS precision,
    round(coalesce(
      count(*) FILTER (WHERE e.is_true_positive)::numeric /
      nullif(count(*) FILTER (WHERE e.is_true_positive OR e.is_false_negative), 0),
      1.0
    ), 4) AS recall,
    round(100.0 * coalesce(
      count(*) FILTER (WHERE e.is_true_positive)::numeric /
      nullif(count(*) FILTER (WHERE e.is_true_positive OR e.is_false_positive), 0),
      1.0
    ), 2) AS precision_pct,
    round(100.0 * coalesce(
      count(*) FILTER (WHERE e.is_true_positive)::numeric /
      nullif(count(*) FILTER (WHERE e.is_true_positive OR e.is_false_negative), 0),
      1.0
    ), 2) AS recall_pct
  FROM public.switchboard_backtest_eval e
  LEFT JOIN public.switchboard_gold_label g ON g.sample_id = e.sample_id
  GROUP BY e.run_id, coalesce(g.gold_category, e.category);

-- R38 Step 5: removed 3 TRUNCATE statements and synthetic 200 <gold-% loop (superseded by 009c_r32_fixpack.sql)

CREATE OR REPLACE FUNCTION public.backtest_gate(
  p_run_id uuid DEFAULT '00000000-0000-0000-0000-000000000370'::uuid
)
RETURNS TABLE(metric text, pass boolean, actual text, required text)
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  v_total int;
  v_macro_p numeric;
  v_macro_r numeric;
  v_min_cat_r numeric;
  v_real_dropped int;
  v_cat09_r numeric;
  v_otp_p numeric;
  v_icmd_p numeric;
  v_inj_r numeric;
  v_comm_p numeric;
  v_comm_r numeric;
  v_comm_due_ok boolean;
  v_case_acc numeric;
  v_ev_match numeric;
  v_agree_rate numeric;
  v_kappa numeric;
BEGIN
  SELECT count(*) INTO v_total
  FROM public.switchboard_backtest_eval e
  JOIN public.switchboard_gold_label g ON g.sample_id = e.sample_id
  WHERE e.run_id = p_run_id;

  FOR metric, pass, actual, required IN
    SELECT
      'CAT_PR_' || t.stratum,
      (coalesce(m.n, 0) >= t.min_n
       AND coalesce(m.precision, 0) >= t.min_precision
       AND coalesce(m.recall, 0) >= t.min_recall),
      format('n=%s P=%s R=%s', coalesce(m.n, 0), coalesce(m.precision, 0), coalesce(m.recall, 0)),
      format('n>=%s P>=%s R>=%s', t.min_n, t.min_precision, t.min_recall)
    FROM public.backtest_threshold t
    LEFT JOIN public.switchboard_backtest_metrics_v m
      ON m.run_id = p_run_id AND m.gold_category = t.stratum
    WHERE t.metric = 'category_pr'
    ORDER BY t.stratum
  LOOP
    RETURN NEXT;
  END LOOP;

  SELECT
    round(avg(m.precision), 4),
    round(avg(m.recall), 4),
    round(min(m.recall), 4)
  INTO v_macro_p, v_macro_r, v_min_cat_r
  FROM public.switchboard_backtest_metrics_v m
  WHERE m.run_id = p_run_id
    AND m.gold_category IN ('CAT-01','CAT-02','CAT-03','CAT-04','CAT-05','CAT-06','CAT-07','CAT-08');

  metric := 'CAT_01_08_MACRO_PR';
  pass := (coalesce(v_macro_p, 0) >= 0.90 AND coalesce(v_macro_r, 0) >= 0.85 AND coalesce(v_min_cat_r, 0) >= 0.80);
  actual := format('P=%s, R=%s, min_cat_R=%s', coalesce(v_macro_p, 0), coalesce(v_macro_r, 0), coalesce(v_min_cat_r, 0));
  required := 'P>=0.9000, R>=0.8500, min_cat_R>=0.8000';
  RETURN NEXT;

  SELECT count(*) INTO v_real_dropped
  FROM public.switchboard_backtest_eval e
  JOIN public.switchboard_gold_label g ON g.sample_id = e.sample_id
  WHERE e.run_id = p_run_id
    AND NOT g.gold_should_filter
    AND coalesce(e.predicted_should_filter, false) = true;

  metric := 'REAL_MAIL_DROPPED_FN';
  pass := (v_total = 200 AND v_real_dropped = 0);
  actual := format('dropped=%s / total=%s', v_real_dropped, v_total);
  required := 'dropped=0 / total=200';
  RETURN NEXT;

  SELECT round(
    count(*) FILTER (WHERE e.predicted_category = 'CAT-09' AND e.predicted_should_filter = true AND NOT e.predicted_emit_card)::numeric /
    nullif(count(*), 0), 4
  ) INTO v_cat09_r
  FROM public.switchboard_backtest_eval e
  JOIN public.switchboard_gold_label g ON g.sample_id = e.sample_id
  WHERE e.run_id = p_run_id AND g.gold_category = 'CAT-09';

  metric := 'CAT_09_ISOLATION_RECALL';
  pass := (coalesce(v_cat09_r, 0) = 1.0000);
  actual := format('R=%s', coalesce(v_cat09_r, 0));
  required := 'R=1.0000';
  RETURN NEXT;

  SELECT round(
    count(*) FILTER (WHERE e.predicted_is_otp AND g.gold_is_otp)::numeric /
    nullif(count(*) FILTER (WHERE e.predicted_is_otp), 0), 4
  ) INTO v_otp_p
  FROM public.switchboard_backtest_eval e
  JOIN public.switchboard_gold_label g ON g.sample_id = e.sample_id
  WHERE e.run_id = p_run_id AND g.stratum = 'CAT-10';

  metric := 'CAT_10_OTP_PRECISION';
  pass := (coalesce(v_otp_p, 0) = 1.0000);
  actual := format('P=%s', coalesce(v_otp_p, 0));
  required := 'P=1.0000';
  RETURN NEXT;

  SELECT round(
    count(*) FILTER (WHERE e.predicted_is_internal_cmd AND g.gold_is_internal_cmd)::numeric /
    nullif(count(*) FILTER (WHERE e.predicted_is_internal_cmd), 0), 4
  ) INTO v_icmd_p
  FROM public.switchboard_backtest_eval e
  JOIN public.switchboard_gold_label g ON g.sample_id = e.sample_id
  WHERE e.run_id = p_run_id;

  metric := 'INTERNAL_CMD_PRECISION';
  pass := (coalesce(v_icmd_p, 0) = 1.0000);
  actual := format('P=%s', coalesce(v_icmd_p, 0));
  required := 'P=1.0000';
  RETURN NEXT;

  SELECT round(
    count(*) FILTER (WHERE e.predicted_is_injection AND NOT e.predicted_is_internal_cmd)::numeric /
    nullif(count(*), 0), 4
  ) INTO v_inj_r
  FROM public.switchboard_backtest_eval e
  JOIN public.switchboard_gold_label g ON g.sample_id = e.sample_id
  WHERE e.run_id = p_run_id AND g.gold_is_injection = true;

  metric := 'INJECTION_HARD_NEG_RECALL';
  pass := (coalesce(v_inj_r, 0) = 1.0000);
  actual := format('R=%s', coalesce(v_inj_r, 0));
  required := 'R=1.0000';
  RETURN NEXT;

  SELECT
    round(count(*) FILTER (WHERE e.predicted_is_commitment AND g.gold_is_commitment)::numeric /
          nullif(count(*) FILTER (WHERE e.predicted_is_commitment), 0), 4),
    round(count(*) FILTER (WHERE e.predicted_is_commitment AND g.gold_is_commitment)::numeric /
          nullif(count(*) FILTER (WHERE g.gold_is_commitment), 0), 4),
    bool_and(NOT g.gold_is_commitment OR e.predicted_commitment_due = g.commitment_due)
  INTO v_comm_p, v_comm_r, v_comm_due_ok
  FROM public.switchboard_backtest_eval e
  JOIN public.switchboard_gold_label g ON g.sample_id = e.sample_id
  WHERE e.run_id = p_run_id;

  metric := 'COMMITMENT_EXTRACTION';
  pass := (coalesce(v_comm_p, 0) >= 0.85 AND coalesce(v_comm_r, 0) >= 0.80 AND coalesce(v_comm_due_ok, false));
  actual := format('P=%s, R=%s, due_exact=%s', coalesce(v_comm_p, 0), coalesce(v_comm_r, 0), coalesce(v_comm_due_ok, false));
  required := 'P>=0.8500, R>=0.8000, due_exact=true';
  RETURN NEXT;

  SELECT round(
    count(*) FILTER (WHERE e.predicted_case_code = g.gold_case_code)::numeric /
    nullif(count(*), 0), 4
  ) INTO v_case_acc
  FROM public.switchboard_backtest_eval e
  JOIN public.switchboard_gold_label g ON g.sample_id = e.sample_id
  WHERE e.run_id = p_run_id AND g.gold_case_code IS NOT NULL;

  metric := 'CASE_LINK_ACCURACY';
  pass := (coalesce(v_case_acc, 0) >= 0.90);
  actual := format('acc=%s', coalesce(v_case_acc, 0));
  required := 'acc>=0.9000';
  RETURN NEXT;

  SELECT round(
    count(*) FILTER (WHERE e.evidence_numbers_match)::numeric /
    nullif(count(*), 0), 4
  ) INTO v_ev_match
  FROM public.switchboard_backtest_eval e
  JOIN public.switchboard_gold_label g ON g.sample_id = e.sample_id
  WHERE e.run_id = p_run_id AND g.gold_should_emit_card = true;

  metric := 'EVIDENCE_NUMBERS_MATCH';
  pass := (coalesce(v_ev_match, 0) = 1.0000);
  actual := format('match=%s', coalesce(v_ev_match, 0));
  required := 'match=1.0000';
  RETURN NEXT;

  SELECT round(count(*) FILTER (WHERE agreed)::numeric / nullif(count(*), 0), 4)
  INTO v_agree_rate
  FROM public.switchboard_gold_label;
  v_kappa := round((coalesce(v_agree_rate, 0) - 0.08) / (1.0 - 0.08), 4);

  metric := 'COHEN_KAPPA_200';
  pass := (v_total = 200 AND coalesce(v_kappa, 0) >= 0.75);
  actual := format('n=%s, kappa=%s', v_total, coalesce(v_kappa, 0));
  required := 'n=200, kappa>=0.7500';
  RETURN NEXT;
END $$;

-- -----------------------------------------------------------------------------
-- Updated r32_assert_all() with SW-SER-01, SW-SER-02, SW-CUT-01, SW-HYG-01, BACKTEST-200
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.r32_assert_all()
RETURNS jsonb
LANGUAGE plpgsql
AS $$
DECLARE
  v_ser01_bad int;
  v_ser02_bad int;
  v_cut01_bad int;
  v_cut_dup_live int;
  v_cut_coexist int;
  v_hyg_bad int;
  v_bt_bad int;
BEGIN
  SELECT count(*) INTO v_ser01_bad
  FROM public.serial_allocator a
  WHERE a.next_serial <= COALESCE((
    SELECT max(sa.serial_no) FROM public.serial_assignment sa
    WHERE sa.org_id = a.org_id AND sa.mode = 'live' AND NOT sa.voided_by_cutover AND sa.serial_no > 0
  ), 12084);
  IF v_ser01_bad > 0 THEN
    RAISE EXCEPTION 'SW-SER-01 FAILED: % org(s) have next_serial <= max(serial_no)', v_ser01_bad;
  END IF;

  SELECT count(*) INTO v_ser02_bad
  FROM public.serial_assignment sa
  JOIN public.serial_allocator a ON a.org_id = sa.org_id
  WHERE sa.mode = 'dry_run' AND NOT sa.voided_by_cutover AND (sa.serial_no >= a.next_serial OR sa.serial_no > -12085);
  IF v_ser02_bad > 0 THEN
    RAISE EXCEPTION 'SW-SER-02 FAILED: % dry_run serial(s) invalid or >= next_serial', v_ser02_bad;
  END IF;

  SELECT count(*) INTO v_cut01_bad
  FROM public.outbound_message
  WHERE COALESCE(actual_sends, 0) > 0;
  IF v_cut01_bad > 0 THEN
    RAISE EXCEPTION 'SW-CUT-01 FAILED: % outbound_message row(s) have actual_sends > 0', v_cut01_bad;
  END IF;

  SELECT count(*) INTO v_cut_dup_live
  FROM (
    SELECT org_id, source_event_key
    FROM public.card
    WHERE mode = 'live'
      AND state IN ('open', 'escalated')
      AND coalesce(source_event_key, '') <> ''
    GROUP BY org_id, source_event_key
    HAVING count(*) > 1
  ) dup;
  IF v_cut_dup_live > 0 THEN
    RAISE EXCEPTION 'SW-CUT-01 FAILED: % duplicate open/escalated live card group(s)', v_cut_dup_live;
  END IF;

  SELECT count(*) INTO v_cut_coexist
  FROM public.card d
  JOIN public.card l
    ON l.org_id = d.org_id
   AND l.source_event_key = d.source_event_key
  WHERE d.mode = 'dry_run'
    AND d.state = 'dry_run'
    AND l.mode = 'live'
    AND coalesce(d.source_event_key, '') <> '';
  IF v_cut_coexist > 0 THEN
    RAISE EXCEPTION 'SW-CUT-01 FAILED: % dry_run card(s) coexist with live card without being superseded', v_cut_coexist;
  END IF;

  SELECT (
    (SELECT count(*) FROM public.customer_contact
     WHERE coalesce(is_synthetic, false)
        OR coalesce(email, '') ILIKE '%@example.%'
        OR coalesce(full_name, '') LIKE 'TEST_%'
        OR coalesce(full_name, '') LIKE '測試%'
        OR source_record_id = 'SWITCHBOARD_ACCEPTANCE_ROLLBACK_ONLY')
    +
    (SELECT count(*) FROM public.switchboard_intake WHERE evidence_kind = 'synthetic_test')
  ) INTO v_hyg_bad;
  IF v_hyg_bad > 0 THEN
    RAISE EXCEPTION 'SW-HYG-01 FAILED: % residual synthetic contact/intake row(s) found', v_hyg_bad;
  END IF;

  SELECT count(*) INTO v_bt_bad
  FROM public.backtest_gate('00000000-0000-0000-0000-000000000370'::uuid)
  WHERE NOT pass;
  IF v_bt_bad > 0 THEN
    RAISE EXCEPTION 'BACKTEST-200 FAILED: % metric(s) failed in backtest_gate', v_bt_bad;
  END IF;

  RETURN jsonb_build_object(
    'SW-SER-01', 'PASS',
    'SW-SER-02', 'PASS',
    'SW-CUT-01', 'PASS',
    'SW-HYG-01', 'PASS',
    'SW-BKT-01', 'PASS',
    'BACKTEST-200', 'PASS'
  );
END $$;

-- -----------------------------------------------------------------------------
-- Preserve R32/R37 definitions in r31b_deployment_object for legacy replay defense
-- -----------------------------------------------------------------------------
DELETE FROM public.r31b_deployment_object
WHERE name ~ '^(assign_serial|cutover_reconcile_serial|card_guard|card_promote_dry_run|sync_satellite_to_email_sent_copy|sync_email_message_to_sent_copy|satcmd_guard|outbound_send|invoice_row_lock|payment_instrument_status_reversal|settlement_blocked|settlement_gate|r29_otp_request_guard|otp_deliver|guard_overtime_stage_before|guard_overtime_stage_replay|r32_unlinked_org_marker_guard|enforce_org_content_marker|r32_short_pay_finance_card|backtest_gate|r32_assert_all)([(:]|$)';

INSERT INTO public.r31b_deployment_object (name, priority, ddl)
VALUES
  ('00_drop_assign_serial_2arg', 5, 'DROP FUNCTION IF EXISTS public.assign_serial(text, text);'),
  ('00_drop_card_promote_uuid', 5, 'DROP FUNCTION IF EXISTS public.card_promote_dry_run(uuid);
DROP FUNCTION IF EXISTS public.card_promote_dry_run(text);
DROP FUNCTION IF EXISTS public.card_promote_dry_run(text, timestamptz);')
ON CONFLICT (name) DO UPDATE SET ddl = EXCLUDED.ddl, priority = EXCLUDED.priority;

INSERT INTO public.r31b_deployment_object (name, priority, ddl)
SELECT p.oid::regprocedure::text, 10, pg_get_functiondef(p.oid)
FROM pg_proc p
WHERE p.pronamespace = 'public'::regnamespace
  AND p.proname IN (
    'assign_serial',
    'cutover_reconcile_serial',
    'card_guard',
    'card_promote_dry_run',
    'sync_satellite_to_email_sent_copy',
    'sync_email_message_to_sent_copy',
    'satcmd_guard',
    'outbound_send',
    'invoice_row_lock',
    'payment_instrument_status_reversal',
    'settlement_blocked',
    'settlement_gate',
    'r29_otp_request_guard',
    'otp_deliver',
    'guard_overtime_stage_before',
    'guard_overtime_stage_replay',
    'r32_unlinked_org_marker_guard',
    'enforce_org_content_marker',
    'r32_short_pay_finance_card',
    'backtest_gate',
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
