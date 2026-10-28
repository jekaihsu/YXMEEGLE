-- =============================================================================
-- 009d_r32_fixpack.sql
-- Fable 5.1 Step 6 (R39) corrections to 009c. Spec: /workspace/fable/r39/step6_reply.md
--
-- Must-fix (R39 一頁摘要 §2):
--   M1  cc 翻負 / serial_assignment 作廢 only with outbound.delivery_status LIKE 'DRY_RUN%'
--       evidence, one-shot via dry_run_negated_at / dry_run_voided_at markers; restore rows
--       009c negated without evidence.
--   M2  assign_serial: both INSERTs ON CONFLICT (org_id,fingerprint,mode) DO UPDATE clearing
--       void flags; cc old-number lookup back to serial_no > 0.
--   M3  one company, one code: 'yongxiang' merged into 'YX'; all equivalence hacks removed;
--       org_id FK -> org(id) on every table that lacked it.
--   M4  enqueue_card / card_act no longer hard-code evidence; caller passes p_evidence.
-- Other (§3-§4): overtime trigger fix, org_marker table, hygiene guard + mark-not-delete,
--   quarantine index + admin card, gate thresholds back to R37 (+REAL_MAIL_DROPPED),
--   schema_migration run-once table, single non-destructive registry snapshot.
--
-- Idempotent: a second run must produce no data changes.
-- Guard: refuses to run on a non-clone/non-test DB unless app.allow_hygiene=on.
--   (Tightened vs. Fable's regex: 'r23'/'r25' removed because the laptop target DB is
--    named yongxiang_unified_r23 and must NOT pass the guard implicitly.)
-- =============================================================================
\set ON_ERROR_STOP on
BEGIN;

DO $$ BEGIN
  IF current_database() !~ '(clone|test)' AND current_setting('app.allow_hygiene', true) IS DISTINCT FROM 'on' THEN
    RAISE EXCEPTION '009d: hygiene/one-shot blocks need app.allow_hygiene=on on non-clone DB % (PGOPTIONS=''-c app.allow_hygiene=on'')', current_database();
  END IF;
END $$;

-- -----------------------------------------------------------------------------
-- §0 schema_migration (run-once ledger; deploy via run_migration_once.sh)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.schema_migration (
  name        text PRIMARY KEY,
  applied_at  timestamptz NOT NULL DEFAULT now(),
  applied_db  text NOT NULL DEFAULT current_database(),
  checksum    text,
  note        text
);

-- -----------------------------------------------------------------------------
-- §1 (M3) 一家公司一個代碼：merge 'yongxiang' -> 'YX'
--   Fable's SQL lists serial_assignment / serial_allocator / employee. Because
--   card(case_id,org_id) -> case(id,org_id) and every case/customer/quote row is
--   'yongxiang', moving only employees would make every card on a real case fail
--   card_guard once the hacks are removed. So the merge is applied to EVERY
--   public base table with an org_id column, in one transaction, with an
--   explicit orphan check over all org-bearing FKs afterwards.
-- -----------------------------------------------------------------------------
DO $$
DECLARE
  t record; fk record; ck record; n bigint; v_orphans bigint; v_ck jsonb := '[]'::jsonb;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM public.org WHERE id = 'yongxiang') THEN
    RETURN;  -- already merged
  END IF;

  -- allocator: keep the highest counters, then drop the duplicate allocator
  UPDATE public.serial_allocator a
     SET next_serial = GREATEST(a.next_serial, b.next_serial),
         shadow_next_serial = LEAST(a.shadow_next_serial, b.shadow_next_serial),
         sheet_max_reconciled = GREATEST(a.sheet_max_reconciled, b.sheet_max_reconciled)
    FROM public.serial_allocator b
   WHERE a.org_id = 'YX' AND b.org_id = 'yongxiang';
  DELETE FROM public.serial_allocator WHERE org_id = 'yongxiang';

  -- composite (x_id, org_id) FKs + append-only triggers: move all rows together
  PERFORM set_config('session_replication_role', 'replica', true);
  FOR t IN
    SELECT c.table_name
      FROM information_schema.columns c
      JOIN information_schema.tables tb USING (table_schema, table_name)
     WHERE c.table_schema = 'public' AND c.column_name = 'org_id' AND tb.table_type = 'BASE TABLE'
     ORDER BY 1
  LOOP
    -- NOT VALID CHECK constraints (e.g. case_code_format_chk on legacy codes) would be
    -- re-evaluated by the UPDATE; lift them for the org_id-only update and re-add NOT VALID.
    FOR ck IN
      SELECT conname, pg_get_constraintdef(oid) AS def FROM pg_constraint
       WHERE conrelid = format('public.%I', t.table_name)::regclass AND contype = 'c' AND NOT convalidated
    LOOP
      EXECUTE format('ALTER TABLE public.%I DROP CONSTRAINT %I', t.table_name, ck.conname);
      v_ck := v_ck || jsonb_build_object('t', t.table_name, 'n', ck.conname, 'd', regexp_replace(ck.def, '\s+NOT VALID$', ''));
    END LOOP;
    EXECUTE format('UPDATE public.%I SET org_id = %L WHERE org_id = %L', t.table_name, 'YX', 'yongxiang');
    GET DIAGNOSTICS n = ROW_COUNT;
    IF n > 0 THEN RAISE NOTICE '009d org merge: % row(s) yongxiang->YX in %', n, t.table_name; END IF;
  END LOOP;
  FOR ck IN SELECT x->>'t' AS t, x->>'n' AS n, x->>'d' AS d FROM jsonb_array_elements(v_ck) x LOOP
    EXECUTE format('ALTER TABLE public.%I ADD CONSTRAINT %I %s NOT VALID', ck.t, ck.n, ck.d);
  END LOOP;
  PERFORM set_config('session_replication_role', 'origin', true);

  -- orphan check over every FK that involves org_id (replica mode skipped FK triggers)
  FOR fk IN
    SELECT con.conname, con.conrelid::regclass AS child, con.confrelid::regclass AS parent,
           (SELECT string_agg('c.' || quote_ident(a.attname), ',' ORDER BY k.ord)
              FROM unnest(con.conkey) WITH ORDINALITY k(attnum, ord)
              JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum) AS ccols,
           (SELECT string_agg('p.' || quote_ident(a.attname), ',' ORDER BY k.ord)
              FROM unnest(con.confkey) WITH ORDINALITY k(attnum, ord)
              JOIN pg_attribute a ON a.attrelid = con.confrelid AND a.attnum = k.attnum) AS pcols
      FROM pg_constraint con
     WHERE con.contype = 'f' AND con.connamespace = 'public'::regnamespace
       AND EXISTS (SELECT 1 FROM unnest(con.conkey) k
                     JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k
                    WHERE a.attname = 'org_id')
  LOOP
    EXECUTE format('SELECT count(*) FROM %s c WHERE ROW(%s) IS NOT NULL AND NOT EXISTS (SELECT 1 FROM %s p WHERE ROW(%s) = ROW(%s))',
                   fk.child, fk.ccols, fk.parent, fk.pcols, fk.ccols)
      INTO v_orphans;
    IF v_orphans > 0 THEN
      RAISE EXCEPTION '009d org merge: % orphan row(s) for FK % on %', v_orphans, fk.conname, fk.child;
    END IF;
  END LOOP;

  DELETE FROM public.org WHERE id = 'yongxiang';
END $$;

-- column defaults that still say 'yongxiang' -> 'YX' (no-op on rerun)
DO $$
DECLARE c record;
BEGIN
  FOR c IN
    SELECT table_name, column_name FROM information_schema.columns
     WHERE table_schema = 'public' AND column_name = 'org_id' AND column_default ~ '''yongxiang'''
  LOOP
    EXECUTE format('ALTER TABLE public.%I ALTER COLUMN %I SET DEFAULT %L', c.table_name, c.column_name, 'YX');
  END LOOP;
END $$;

-- org_id FK -> org(id) on every base table that lacks one (quarantine copy excluded)
DO $$
DECLARE t record;
BEGIN
  FOR t IN
    SELECT c.table_name
      FROM information_schema.columns c
      JOIN information_schema.tables tb USING (table_schema, table_name)
     WHERE c.table_schema = 'public' AND c.column_name = 'org_id' AND tb.table_type = 'BASE TABLE'
       AND c.table_name NOT IN ('email_rag_chunk_quarantine')
       AND NOT EXISTS (
         SELECT 1 FROM pg_constraint con
          WHERE con.conrelid = format('public.%I', c.table_name)::regclass
            AND con.contype = 'f' AND con.confrelid = 'public.org'::regclass
            AND array_length(con.conkey, 1) = 1)
  LOOP
    EXECUTE format('ALTER TABLE public.%I ADD CONSTRAINT r39_org_fk FOREIGN KEY (org_id) REFERENCES public.org(id) NOT VALID', t.table_name);
    EXECUTE format('ALTER TABLE public.%I VALIDATE CONSTRAINT r39_org_fk', t.table_name);
    RAISE NOTICE '009d: added r39_org_fk on %', t.table_name;
  END LOOP;
END $$;

-- -----------------------------------------------------------------------------
-- §2 (M1) Dry-Run serial negation / voiding: evidence-based + one-shot markers
-- -----------------------------------------------------------------------------
ALTER TABLE public.client_communication ADD COLUMN IF NOT EXISTS dry_run_negated_at timestamptz;
ALTER TABLE public.serial_assignment    ADD COLUMN IF NOT EXISTS dry_run_voided_at timestamptz;

-- Dry-Run evidence for a thread: some cc row of that (org, fingerprint) is linked
-- (by comm_id or intake_id) to an outbound_message whose delivery_status LIKE 'DRY_RUN%'.
-- (outbound_message has no thread_fingerprint column; cc is unique per (org, fingerprint).)
CREATE OR REPLACE FUNCTION public.r39_thread_has_dry_run(p_org text, p_fp text)
RETURNS boolean
LANGUAGE sql STABLE
AS $$
  SELECT p_fp IS NOT NULL AND EXISTS (
    SELECT 1
      FROM public.client_communication c2
      JOIN public.outbound_message o
        ON o.org_id = c2.org_id
       AND (o.comm_id = c2.id OR (c2.intake_id IS NOT NULL AND o.intake_id = c2.intake_id))
     WHERE c2.org_id = p_org
       AND c2.thread_fingerprint = p_fp
       AND o.delivery_status LIKE 'DRY_RUN%')
$$;

CREATE OR REPLACE FUNCTION public.r39_dry_run_serial_repair()
RETURNS jsonb
LANGUAGE plpgsql
AS $$
DECLARE
  v_restore int := 0; v_negate int := 0; v_unvoid int := 0; v_keep int := 0;
  v_void int := 0; v_alloc int := 0; v_skip int := 0;
BEGIN
  -- (a) restore rows 009c negated without Dry-Run evidence
  CREATE TEMP TABLE IF NOT EXISTS r39_cc_restore (id uuid PRIMARY KEY) ON COMMIT DROP;
  CREATE TEMP TABLE IF NOT EXISTS r39_cc_negate  (id uuid PRIMARY KEY) ON COMMIT DROP;
  TRUNCATE r39_cc_restore, r39_cc_negate;

  INSERT INTO r39_cc_restore
  SELECT c.id FROM public.client_communication c
   WHERE c.serial_no BETWEEN -12105 AND -12085
     AND c.dry_run_negated_at IS NULL
     AND NOT public.r39_thread_has_dry_run(c.org_id, c.thread_fingerprint)
     -- genuine shadow serials issued by assign_serial(...,'dry_run') are not 009c damage
     AND NOT EXISTS (SELECT 1 FROM public.serial_assignment sa
                      WHERE sa.org_id = c.org_id AND sa.mode = 'dry_run' AND sa.serial_no = c.serial_no)
     AND NOT EXISTS (SELECT 1 FROM public.client_communication c3
                      WHERE c3.org_id = c.org_id AND c3.serial_no = abs(c.serial_no));
  SELECT count(*) INTO v_skip FROM public.client_communication c
   WHERE c.serial_no BETWEEN -12105 AND -12085 AND c.dry_run_negated_at IS NULL
     AND NOT public.r39_thread_has_dry_run(c.org_id, c.thread_fingerprint)
     AND EXISTS (SELECT 1 FROM public.client_communication c3
                  WHERE c3.org_id = c.org_id AND c3.serial_no = abs(c.serial_no));
  IF v_skip > 0 THEN
    RAISE WARNING '009d: % negated cc row(s) not restored because abs(serial) is already taken - manual review', v_skip;
  END IF;

  -- (b) negate positive 12085..12105 only with Dry-Run evidence, once
  INSERT INTO r39_cc_negate
  SELECT c.id FROM public.client_communication c
   WHERE c.serial_no BETWEEN 12085 AND 12105
     AND c.dry_run_negated_at IS NULL
     AND public.r39_thread_has_dry_run(c.org_id, c.thread_fingerprint)
     AND NOT EXISTS (SELECT 1 FROM public.client_communication c3
                      WHERE c3.org_id = c.org_id AND c3.serial_no = -c.serial_no);

  IF EXISTS (SELECT 1 FROM r39_cc_restore) OR EXISTS (SELECT 1 FROM r39_cc_negate) THEN
    -- only the two append-only triggers are bypassed; org-marker guard stays on
    ALTER TABLE public.client_communication DISABLE TRIGGER r28_comm_append_only;
    ALTER TABLE public.client_communication DISABLE TRIGGER switchboard_communication_immutable;

    UPDATE public.client_communication c SET serial_no = abs(c.serial_no)
      FROM r39_cc_restore r WHERE r.id = c.id;
    GET DIAGNOSTICS v_restore = ROW_COUNT;

    UPDATE public.client_communication c SET serial_no = -abs(c.serial_no), dry_run_negated_at = now()
      FROM r39_cc_negate r WHERE r.id = c.id;
    GET DIAGNOSTICS v_negate = ROW_COUNT;

    ALTER TABLE public.client_communication ENABLE TRIGGER r28_comm_append_only;
    ALTER TABLE public.client_communication ENABLE TRIGGER switchboard_communication_immutable;
  END IF;

  -- (c) serial_assignment voided by 009c without evidence -> un-void
  UPDATE public.serial_assignment sa
     SET voided_by_cutover = false, voided_at = NULL, void_reason = NULL
   WHERE sa.void_reason = 'R38_DRYRUN_NEGATED'
     AND sa.dry_run_voided_at IS NULL
     AND NOT EXISTS (SELECT 1 FROM public.client_communication c
                      WHERE c.org_id = sa.org_id AND c.serial_no = -sa.serial_no)
     AND NOT public.r39_thread_has_dry_run(sa.org_id, sa.fingerprint)
     AND NOT EXISTS (SELECT 1 FROM public.serial_assignment o
                      WHERE o.org_id = sa.org_id AND o.serial_no = sa.serial_no
                        AND NOT o.voided_by_cutover AND (o.fingerprint, o.mode) <> (sa.fingerprint, sa.mode));
  GET DIAGNOSTICS v_unvoid = ROW_COUNT;

  -- 009c voids that DO have evidence: keep, but stamp the one-shot marker
  UPDATE public.serial_assignment sa SET dry_run_voided_at = coalesce(sa.voided_at, now())
   WHERE sa.void_reason = 'R38_DRYRUN_NEGATED' AND sa.voided_by_cutover AND sa.dry_run_voided_at IS NULL;
  GET DIAGNOSTICS v_keep = ROW_COUNT;

  -- (d) void live 12085..12105 only with Dry-Run evidence, once (marker survives reuse)
  UPDATE public.serial_assignment sa
     SET voided_by_cutover = true, voided_at = now(), void_reason = 'R39_DRYRUN_NEGATED', dry_run_voided_at = now()
   WHERE sa.mode = 'live' AND NOT sa.voided_by_cutover
     AND sa.serial_no BETWEEN 12085 AND 12105
     AND sa.dry_run_voided_at IS NULL
     AND public.r39_thread_has_dry_run(sa.org_id, sa.fingerprint);
  GET DIAGNOSTICS v_void = ROW_COUNT;

  -- (e) allocator must stay above every active live serial (only ever increases)
  UPDATE public.serial_allocator a SET next_serial = m.mx + 1
    FROM (SELECT org_id, max(serial_no) AS mx FROM public.serial_assignment
           WHERE mode = 'live' AND NOT voided_by_cutover AND serial_no > 0 GROUP BY org_id) m
   WHERE m.org_id = a.org_id AND a.next_serial <= m.mx;
  GET DIAGNOSTICS v_alloc = ROW_COUNT;

  RETURN jsonb_build_object('cc_restored', v_restore, 'cc_negated', v_negate, 'cc_restore_skipped', v_skip,
                            'sa_unvoided', v_unvoid, 'sa_r38_kept_marked', v_keep,
                            'sa_voided', v_void, 'allocator_bumped', v_alloc);
END $$;

DO $$ DECLARE r jsonb; BEGIN
  r := public.r39_dry_run_serial_repair();
  RAISE NOTICE '009d serial repair: %', r;
END $$;

-- -----------------------------------------------------------------------------
-- §3 (M2) assign_serial: ON CONFLICT reuse of voided rows; cc lookup > 0
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.assign_serial(
  p_org text,
  p_fp text,
  p_mode text DEFAULT 'live'
)
RETURNS int
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  s int;
  v_floor int;
BEGIN
  IF p_org IS NULL OR btrim(p_org) = '' THEN
    RAISE EXCEPTION 'assign_serial requires non-empty p_org';
  END IF;
  IF p_fp IS NULL OR btrim(p_fp) = '' THEN
    RAISE EXCEPTION 'assign_serial requires non-empty p_fp';
  END IF;
  IF p_mode NOT IN ('live', 'dry_run') THEN
    RAISE EXCEPTION 'assign_serial invalid p_mode=% (must be live or dry_run)', p_mode;
  END IF;

  PERFORM 1 FROM public.serial_allocator WHERE org_id = p_org FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'unknown org %', p_org;
  END IF;

  IF p_mode = 'dry_run' THEN
    IF EXISTS (SELECT 1 FROM public.serial_assignment
                WHERE org_id = p_org AND fingerprint = p_fp AND mode = 'live' AND NOT voided_by_cutover) THEN
      RAISE EXCEPTION 'fingerprint already has live serial; dry_run refused';
    END IF;

    SELECT serial_no INTO s FROM public.serial_assignment
     WHERE org_id = p_org AND fingerprint = p_fp AND mode = 'dry_run' AND NOT voided_by_cutover;
    IF FOUND THEN
      RETURN s;
    END IF;

    UPDATE public.serial_allocator
       SET shadow_next_serial = LEAST(
             coalesce(shadow_next_serial, -12085),
             coalesce((SELECT min(serial_no) - 1 FROM public.serial_assignment WHERE org_id = p_org AND serial_no < 0), -12085),
             -12085) - 1
     WHERE org_id = p_org
     RETURNING shadow_next_serial + 1 INTO s;

    INSERT INTO public.serial_assignment AS sa (org_id, fingerprint, serial_no, mode, voided_by_cutover)
    VALUES (p_org, p_fp, s, 'dry_run', false)
    ON CONFLICT (org_id, fingerprint, mode) DO UPDATE
       SET serial_no = EXCLUDED.serial_no, voided_by_cutover = false, voided_at = NULL, void_reason = NULL
     WHERE sa.voided_by_cutover;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'assign_serial: active dry_run row appeared concurrently for %/%', p_org, p_fp;
    END IF;
    RETURN s;
  END IF;

  SELECT serial_no INTO s FROM public.serial_assignment
   WHERE org_id = p_org AND fingerprint = p_fp AND mode = 'live' AND NOT voided_by_cutover;
  IF FOUND THEN
    RETURN s;
  END IF;

  -- R39 3④: any positive historical number for this thread is reused (not only >= 12085)
  SELECT serial_no INTO s FROM public.client_communication
   WHERE org_id = p_org AND thread_fingerprint = p_fp AND serial_no > 0
   ORDER BY serial_no
   LIMIT 1;

  IF s IS NULL THEN
    SELECT GREATEST(
      12085,
      coalesce((SELECT sheet_max_reconciled + 1 FROM public.serial_allocator WHERE org_id = p_org), 12085),
      coalesce((SELECT max(serial_no) + 1 FROM public.client_communication WHERE org_id = p_org AND serial_no > 0), 12085),
      coalesce((SELECT max(serial_no) + 1 FROM public.serial_assignment
                 WHERE org_id = p_org AND mode = 'live' AND NOT voided_by_cutover AND serial_no > 0), 12085)
    ) INTO v_floor;

    UPDATE public.serial_allocator
       SET next_serial = GREATEST(next_serial, v_floor) + 1
     WHERE org_id = p_org
     RETURNING next_serial - 1 INTO s;
  END IF;

  INSERT INTO public.serial_assignment AS sa (org_id, fingerprint, serial_no, mode, voided_by_cutover)
  VALUES (p_org, p_fp, s, 'live', false)
  ON CONFLICT (org_id, fingerprint, mode) DO UPDATE
     SET serial_no = EXCLUDED.serial_no, voided_by_cutover = false, voided_at = NULL, void_reason = NULL
   WHERE sa.voided_by_cutover;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'assign_serial: active live row appeared concurrently for %/%', p_org, p_fp;
  END IF;
  RETURN s;
END $$;

-- -----------------------------------------------------------------------------
-- §4 (M4) evidence is supplied by the caller; no hard-coded sql_ids in functions
-- -----------------------------------------------------------------------------
INSERT INTO public.evidence_sql (sql_id, description, sql_text, returns) VALUES
 ('otp.pending_requests', '同帳號 TTL 內 pending OTP 請求數',
  'SELECT count(*) FROM otp_request WHERE rule_id=:rule_id AND fulfilled_message_id IS NULL AND requested_at > now()-interval ''5 minutes''', 'int'),
 ('quarantine.reason', '隔離信的隔離原因',
  'SELECT quarantine_reason FROM email_message WHERE message_id=:message_id', 'text'),
 ('alias.unresolved_count', '同一封信未解析的員工別名數',
  'SELECT count(*) FROM backfill_quarantine WHERE kind=''unresolved_employee_alias'' AND payload->>''message_id''=:message_id', 'int')
ON CONFLICT (sql_id) DO NOTHING;

ALTER TABLE public.card_transition ADD COLUMN IF NOT EXISTS next_evidence_sql text[];

CREATE OR REPLACE FUNCTION public.card_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  v_elem jsonb;
  v_sql_id text;
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
  NEW.role := coalesce(NEW.role, CASE WHEN NEW.kind = 'admin' THEN 'admin'
                                      WHEN NEW.kind = 'finance' THEN 'settlement'
                                      ELSE 'case' END);

  IF NEW.actions = '[]'::jsonb OR (NEW.kind <> 'confirm' AND NEW.actions = '[{"label":"確認","action":"confirm"}]'::jsonb) THEN
    NEW.actions := CASE WHEN NEW.kind = 'review' THEN '[{"label":"核准","action":"approve"}]'::jsonb
                        ELSE '[{"label":"確認","action":"confirm"}]'::jsonb END;
  END IF;

  IF NEW.evidence_numbers IS NULL
     OR jsonb_typeof(NEW.evidence_numbers) <> 'array'
     OR jsonb_array_length(NEW.evidence_numbers) > 3 THEN
    RAISE EXCEPTION 'evidence must bind evidence_sql';
  END IF;

  FOR v_elem IN SELECT * FROM jsonb_array_elements(NEW.evidence_numbers) LOOP
    IF NOT (v_elem ? 'label' AND v_elem ? 'value' AND v_elem ? 'sql_id')
       OR NOT EXISTS (SELECT 1 FROM public.evidence_sql s WHERE s.sql_id = v_elem->>'sql_id') THEN
      RAISE EXCEPTION 'evidence must bind evidence_sql';
    END IF;
  END LOOP;

  IF coalesce(array_length(NEW.evidence_sql_ids, 1), 0) > 0 THEN
    FOREACH v_sql_id IN ARRAY NEW.evidence_sql_ids LOOP
      IF NOT EXISTS (SELECT 1 FROM public.evidence_sql s WHERE s.sql_id = v_sql_id) THEN
        RAISE EXCEPTION 'evidence must bind evidence_sql';
      END IF;
    END LOOP;
  ELSIF jsonb_array_length(NEW.evidence_numbers) > 0 THEN
    SELECT coalesce(array_agg(e->>'sql_id'), '{}'::text[]) INTO NEW.evidence_sql_ids
      FROM jsonb_array_elements(NEW.evidence_numbers) e;
  END IF;

  RETURN NEW;
END $$;

DROP FUNCTION IF EXISTS public.enqueue_card(text, uuid, uuid, text, text, jsonb, uuid);
CREATE OR REPLACE FUNCTION public.enqueue_card(
  p_org text,
  p_case uuid,
  p_assignee uuid,
  p_kind text,
  p_key text,
  p_evidence jsonb,
  p_proposed jsonb DEFAULT '{}'::jsonb,
  p_cc uuid DEFAULT NULL
)
RETURNS uuid
LANGUAGE plpgsql
AS $$
DECLARE
  cid uuid;
  v_ev jsonb := p_evidence;
BEGIN
  IF v_ev IS NULL THEN
    -- case-level default only for case/review/settlement kinds (R39 2c)
    IF p_kind IN ('case', 'review', 'settlement') THEN
      v_ev := public.card_evidence(p_case);
    ELSE
      RAISE EXCEPTION 'enqueue_card: p_evidence is required for kind %', p_kind;
    END IF;
  END IF;

  INSERT INTO public.card (org_id, case_id, assignee_employee_id, kind, idempotency_key,
                           proposed_fields, evidence_numbers, evidence_sql_ids)
  VALUES (p_org, p_case, p_assignee, p_kind, p_key,
          coalesce(p_proposed, '{}'::jsonb), v_ev, '{}'::text[])   -- sql_ids derived by card_guard
  ON CONFLICT (idempotency_key) DO NOTHING
  RETURNING id INTO cid;

  IF cid IS NULL THEN
    SELECT id INTO cid FROM public.card
     WHERE idempotency_key = p_key AND org_id = p_org AND assignee_employee_id = p_assignee
       AND case_id IS NOT DISTINCT FROM p_case AND kind = p_kind
       AND proposed_fields = coalesce(p_proposed, '{}'::jsonb);
    IF cid IS NULL THEN
      RAISE EXCEPTION 'event idempotency payload conflict' USING ERRCODE = '23505';
    END IF;
  END IF;

  IF p_cc IS NOT NULL THEN
    IF NOT EXISTS (SELECT 1 FROM public.employee
                    WHERE id = p_cc AND org_id = p_org AND employment_status = 'active' AND identity_confirmed) THEN
      RAISE EXCEPTION 'invalid copy recipient';
    END IF;
    INSERT INTO public.notification_outbox (recipient_id, tier, dedupe_key, payload)
    VALUES (p_cc::text, 'immediate', 'copy:' || cid::text || ':' || p_cc::text,
            jsonb_build_object('card_id', cid, 'copy_only', true))
    ON CONFLICT DO NOTHING;
  END IF;

  RETURN cid;
END $$;

CREATE OR REPLACE FUNCTION public.card_act(
  p_id uuid,
  p_actor uuid,
  p_action text,
  p_key text
)
RETURNS jsonb
LANGUAGE plpgsql
AS $$
DECLARE
  c public.card;
  t public.card_transition;
  n uuid;
  v_ev jsonb;
BEGIN
  IF p_key IS NULL OR btrim(p_key) = '' OR p_action NOT IN ('confirm', 'approve', 'return_work', 'reject') OR p_action IS NULL THEN
    RAISE EXCEPTION 'invalid action or idempotency key';
  END IF;

  SELECT * INTO c FROM public.card WHERE id = p_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'card not found';
  END IF;

  IF c.assignee_employee_id IS DISTINCT FROM p_actor OR NOT EXISTS (
    SELECT 1 FROM public.employee
     WHERE id = p_actor AND org_id = c.org_id AND employment_status = 'active' AND identity_confirmed
  ) THEN
    RAISE EXCEPTION 'actor is not the active assignee' USING ERRCODE = '42501';
  END IF;

  IF c.mode <> 'live' THEN
    RAISE EXCEPTION 'dry_run card cannot be acted';
  END IF;

  IF c.acted_at IS NOT NULL THEN
    IF c.action <> p_action THEN
      RAISE EXCEPTION 'card already acted with different action' USING ERRCODE = '23505';
    END IF;
    RETURN jsonb_build_object('id', c.id, 'status', c.status, 'acted_at', c.acted_at, 'action', c.action);
  END IF;

  IF NOT EXISTS (SELECT 1 FROM public.card_state_transition
                  WHERE card_kind = c.kind AND from_state = 'open' AND action = p_action) THEN
    RAISE EXCEPTION 'action not allowed for card kind';
  END IF;

  UPDATE public.card
     SET status = 'acted', acted_at = clock_timestamp(), acted_by = p_actor, action = p_action, action_key = p_key
   WHERE id = p_id
  RETURNING * INTO c;

  INSERT INTO public.audit_event (table_name, record_id, op, actor_id, before_val, after_val)
  VALUES ('card', p_id::text, 'UPDATE', p_actor::text,
          jsonb_build_object('status', 'open'),
          jsonb_build_object('status', 'acted', 'action', p_action, 'acted_at', c.acted_at));

  INSERT INTO public.card_action_log (card_id, action, from_state, to_state, actor_employee_id, actor_role, channel, idempotency_key)
  VALUES (p_id, p_action, 'open', 'acted', p_actor,
          coalesce((SELECT role FROM public.api_session WHERE employee_id = p_actor AND expires_at > now()
                     ORDER BY expires_at DESC LIMIT 1), 'field_member'),
          'api', p_key);

  SELECT * INTO t FROM public.card_transition WHERE card_id = p_id AND on_action = p_action;
  IF FOUND THEN
    -- R39 2c: follow-up evidence recomputed from the transition's declared sql_ids;
    -- without a declaration only the case-level default (review kind) is allowed.
    IF t.next_evidence_sql IS NOT NULL THEN
      SELECT coalesce(jsonb_agg(e), '[]'::jsonb) INTO v_ev
        FROM jsonb_array_elements(public.card_evidence(c.case_id)) e
       WHERE e->>'sql_id' = ANY (t.next_evidence_sql);
    ELSE
      v_ev := NULL;
    END IF;

    IF v_ev IS NULL AND t.next_kind NOT IN ('case', 'review', 'settlement') THEN
      v_ev := '[]'::jsonb;
    END IF;

    n := public.enqueue_card(c.org_id, c.case_id, t.next_assignee_employee_id, t.next_kind,
                             'after:' || p_id::text || ':' || p_action, v_ev);

    INSERT INTO public.notification_outbox (recipient_id, tier, dedupe_key, payload)
    VALUES (t.next_assignee_employee_id::text, 'immediate', 'after:' || p_id::text, jsonb_build_object('card_id', n))
    ON CONFLICT DO NOTHING;
  END IF;

  RETURN jsonb_build_object('id', c.id, 'status', c.status, 'acted_at', c.acted_at, 'action', c.action);
END $$;

-- callers updated to the new signature (and to carry their own evidence)
CREATE OR REPLACE FUNCTION public.forward_register_card(p_message uuid, p_alias text, p_admin uuid)
RETURNS uuid
LANGUAGE plpgsql
AS $$
DECLARE m public.email_message; eid uuid; v_cnt int;
BEGIN
  SELECT * INTO STRICT m FROM public.email_message WHERE id = p_message;
  SELECT a.employee_id INTO eid
    FROM public.employee_alias a JOIN public.employee e ON e.id = a.employee_id
   WHERE a.org_id = m.org_id AND a.alias = btrim(normalize(p_alias, NFKC))
     AND e.identity_confirmed AND e.employment_status = 'active' AND e.org_id = m.org_id;
  IF eid IS NULL THEN
    INSERT INTO public.backfill_quarantine (run_id, kind, payload)
    VALUES (gen_random_uuid(), 'unresolved_employee_alias', jsonb_build_object('message_id', m.id::text, 'alias', p_alias))
    ON CONFLICT DO NOTHING;
    SELECT count(*) INTO v_cnt FROM public.backfill_quarantine
     WHERE kind = 'unresolved_employee_alias' AND payload->>'message_id' = m.id::text;
    RETURN public.enqueue_card(m.org_id, m.case_id, p_admin, 'admin', 'alias:' || m.id::text,
             jsonb_build_array(jsonb_build_object('label', '未解析別名數', 'value', v_cnt, 'sql_id', 'alias.unresolved_count')),
             jsonb_build_object('alias', p_alias, 'label', '待分類'));
  END IF;
  RETURN public.enqueue_card(m.org_id, m.case_id, eid, 'review', 'forward:' || m.id::text, NULL);
END $$;

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
  v_sig constant text := 'public.enqueue_card(text,uuid,uuid,text,text,jsonb,jsonb,uuid)';
BEGIN
  IF TG_TABLE_NAME = 'payment_instrument' THEN
    IF NEW.status = 'cleared' AND OLD.status IS DISTINCT FROM 'cleared' THEN
      FOR r_alloc IN SELECT id, invoice_id, allocated_by FROM public.receipt_allocation WHERE instrument_id = NEW.id LOOP
        SELECT * INTO v_inv FROM public.invoice WHERE id = r_alloc.invoice_id;
        SELECT coalesce((c.invoice_rules->>'short_pay_tolerance')::numeric, 0) INTO v_tol
          FROM public.customer c WHERE c.id = v_inv.customer_id;
        IF v_tol > 0 THEN
          SELECT unpaid_amount INTO v_unpaid FROM public.invoice_paid_v WHERE id = r_alloc.invoice_id;
          IF v_unpaid > 0 AND v_unpaid <= v_tol THEN
            SELECT coalesce(r_alloc.allocated_by, (
              SELECT e.id FROM public.employee e
               WHERE e.org_id = v_inv.org_id AND e.employment_status = 'active' AND e.identity_confirmed
               ORDER BY (e.department_name ~ '(財務|會計)')::int DESC, e.id LIMIT 1)) INTO v_fin_emp;
            IF v_fin_emp IS NOT NULL AND to_regprocedure(v_sig) IS NOT NULL THEN
              BEGIN
                PERFORM public.enqueue_card(v_inv.org_id, v_inv.case_id, v_fin_emp, 'finance',
                  'short-pay:' || r_alloc.invoice_id::text || ':' || r_alloc.id::text,
                  jsonb_build_array(jsonb_build_object('label', '未收金額', 'value', v_unpaid, 'sql_id', 'invoice.unpaid')),
                  jsonb_build_object('invoice_id', r_alloc.invoice_id, 'tolerance', v_tol, 'label', '短收差額待沖帳'));
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
      SELECT coalesce(NEW.allocated_by, (
        SELECT e.id FROM public.employee e
         WHERE e.org_id = v_inv.org_id AND e.employment_status = 'active' AND e.identity_confirmed
         ORDER BY (e.department_name ~ '(財務|會計)')::int DESC, e.id LIMIT 1)) INTO v_fin_emp;
      IF v_fin_emp IS NOT NULL AND to_regprocedure(v_sig) IS NOT NULL THEN
        BEGIN
          PERFORM public.enqueue_card(v_inv.org_id, v_inv.case_id, v_fin_emp, 'finance',
            'short-pay:' || NEW.invoice_id::text || ':' || NEW.id::text,
            jsonb_build_array(jsonb_build_object('label', '未收金額', 'value', v_unpaid, 'sql_id', 'invoice.unpaid')),
            jsonb_build_object('invoice_id', NEW.invoice_id, 'tolerance', v_tol, 'label', '短收差額待沖帳'));
        EXCEPTION WHEN OTHERS THEN
          RAISE WARNING 'short-pay finance card failed: %', SQLERRM;
        END;
      END IF;
    END IF;
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
    FROM public.otp_request q JOIN public.employee e ON e.id = q.requester_employee_id
   WHERE q.rule_id = r.id AND q.org_id = m.org_id AND q.fulfilled_message_id IS NULL
     AND q.requested_at > t - interval '5 minutes' AND q.requested_at <= t
     AND m.sent_at >= q.requested_at
     AND e.employment_status = 'active' AND e.identity_confirmed AND e.org_id = q.org_id;

  IF pending_cnt > 1 THEN
    SELECT e.id INTO admin_emp FROM public.employee e
     WHERE e.org_id = m.org_id AND e.employment_status = 'active' AND e.identity_confirmed AND e.role_code = 'admin'
     ORDER BY e.id LIMIT 1;
    IF admin_emp IS NULL THEN
      RAISE EXCEPTION 'no active confirmed admin employee for org %', m.org_id;
    END IF;
    PERFORM public.enqueue_card(
      m.org_id, m.case_id, admin_emp, 'admin', 'otp-conflict:' || m.id::text,
      jsonb_build_array(jsonb_build_object('label', '同帳號 pending 請求', 'value', pending_cnt, 'sql_id', 'otp.pending_requests')),
      jsonb_build_object('label', 'OTP 衝突', 'rule_id', r.id));
    RETURN NULL;
  END IF;

  SELECT q.* INTO req
    FROM public.otp_request q JOIN public.employee e ON e.id = q.requester_employee_id
   WHERE q.rule_id = r.id AND q.org_id = m.org_id AND q.fulfilled_message_id IS NULL
     AND q.requested_at > t - interval '5 minutes' AND q.requested_at <= t
     AND m.sent_at >= q.requested_at
     AND e.employment_status = 'active' AND e.identity_confirmed AND e.org_id = q.org_id
   ORDER BY q.requested_at, q.id
   LIMIT 1
   FOR UPDATE OF q;

  IF NOT FOUND THEN RETURN NULL; END IF;
  t := clock_timestamp();
  IF t >= req.requested_at + interval '5 minutes' THEN RETURN NULL; END IF;

  UPDATE public.otp_request SET fulfilled_message_id = p_msg, delivered_at = t WHERE id = req.id;
  INSERT INTO public.otp_private_delivery (request_id, message_id, recipient_employee_id, org_id)
  VALUES (req.id, p_msg, req.requester_employee_id, req.org_id);
  RETURN req.requester_employee_id;
END $function$;

-- -----------------------------------------------------------------------------
-- §5 統編／網域單一來源：org_marker (filled by 行政 from 營業登記; NOT seeded here)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.org_marker (
  org_code    text NOT NULL REFERENCES public.org(id),
  kind        text NOT NULL CHECK (kind IN ('tax_id', 'domain', 'name')),
  value       text NOT NULL CHECK (btrim(value) <> ''),
  verified_by text NOT NULL CHECK (btrim(verified_by) <> ''),
  verified_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (org_code, kind, value)
);

CREATE OR REPLACE FUNCTION public.r32_unlinked_org_marker_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  v_row jsonb := to_jsonb(NEW);
  txt text := lower(coalesce(v_row->>'subject', '') || ' ' ||
              coalesce(v_row->>'body_new_text', '') || ' ' ||
              coalesce(v_row->>'body_text', '') || ' ' ||
              coalesce(v_row->>'draft_body', '') || ' ' ||
              coalesce(v_row->>'final_body', '') || ' ' ||
              coalesce(v_row->>'from_addr', '') || ' ' ||
              coalesce(v_row->>'payload', ''));
  has_yx boolean := EXISTS (SELECT 1 FROM public.org_marker m WHERE m.org_code = 'YX' AND position(lower(m.value) IN txt) > 0);
  has_sj boolean := EXISTS (SELECT 1 FROM public.org_marker m WHERE m.org_code = 'SJ' AND position(lower(m.value) IN txt) > 0);
  bad text;
BEGIN
  IF (v_row->>'case_id') IS NULL THEN
    IF (v_row->>'org_id') = 'YX' AND has_sj AND NOT has_yx THEN
      bad := 'unlinked message carries SJ marker but org_id=YX';
    ELSIF (v_row->>'org_id') = 'SJ' AND has_yx AND NOT has_sj THEN
      bad := 'unlinked message carries YX marker but org_id=SJ';
    ELSIF TG_TABLE_NAME IN ('outbound_message', 'client_communication')
          AND (v_row->>'org_id') = 'SJ' AND NOT has_sj THEN
      bad := 'unlinked SJ row requires explicit SJ marker';
    END IF;
  END IF;

  IF bad IS NOT NULL THEN
    IF TG_TABLE_NAME IN ('email_message', 'switchboard_intake') THEN
      NEW.org_id := NULL;
      NEW.quarantine_reason := 'R32-ORG-MARKER:' || bad;
      RETURN NEW;
    END IF;
    RAISE EXCEPTION 'R32-ORG-MARKER: %', bad;
  END IF;
  RETURN NEW;
END $$;

-- -----------------------------------------------------------------------------
-- §6 加班 trigger: never reference columns that may not exist; same-level no-op
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.guard_overtime_stage_before()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  v_new jsonb := to_jsonb(NEW);
  v_old jsonb := CASE WHEN TG_OP = 'UPDATE' THEN to_jsonb(OLD) ELSE '{}'::jsonb END;
  v_new_lvl int := coalesce((v_new->>'escalation_level')::int, 0);
  v_old_lvl int := coalesce((v_old->>'escalation_level')::int, 0);
  v_stage text;
  v_restore jsonb;
BEGIN
  IF TG_OP = 'UPDATE' THEN
    IF v_new_lvl < v_old_lvl THEN
      RAISE EXCEPTION 'overtime escalation_level cannot decrease from % to %', v_old_lvl, v_new_lvl;
    END IF;
    IF v_new_lvl > v_old_lvl + 1 THEN
      RAISE EXCEPTION 'overtime escalation stage skip forbidden: % -> %', v_old_lvl, v_new_lvl;
    END IF;
    IF v_new_lvl = v_old_lvl THEN
      RETURN NEW;  -- same level (incl. ETL touching only updated_at): no-op, never RAISE
    END IF;
    v_stage := coalesce(v_new->>'last_escalated_stage',
                        CASE WHEN v_new_lvl = 1 THEN 'STAGE_1_24H_DEPT_MANAGER'
                             WHEN v_new_lvl >= 2 THEN 'STAGE_2_48H_DEPUTY_GM' END);
    IF v_stage IS NOT NULL AND EXISTS (
      SELECT 1 FROM public.overtime_escalation_stage_log
       WHERE request_id = coalesce(v_new->>'request_id', v_new->>'id') AND stage = v_stage
    ) THEN
      -- stage already logged: keep the old level and whichever state column the table has
      SELECT jsonb_build_object('escalation_level', v_old_lvl)
             || coalesce(jsonb_object_agg(k, v_old->k), '{}'::jsonb)
        INTO v_restore
        FROM unnest(ARRAY['state', 'status', 'state_code']) k
       WHERE v_new ? k;
      NEW := jsonb_populate_record(NEW, v_restore);
    END IF;
  END IF;
  RETURN NEW;
END $$;

-- -----------------------------------------------------------------------------
-- §7 衛生：mark, never delete (outbound_message gets is_synthetic too)
-- -----------------------------------------------------------------------------
ALTER TABLE public.outbound_message ADD COLUMN IF NOT EXISTS is_synthetic boolean NOT NULL DEFAULT false;

UPDATE public.switchboard_intake SET is_synthetic = true
 WHERE evidence_kind = 'synthetic_test' AND NOT is_synthetic;

UPDATE public.outbound_message o SET is_synthetic = true
 WHERE NOT o.is_synthetic
   AND EXISTS (SELECT 1 FROM public.switchboard_intake i
                WHERE i.id = o.intake_id AND (i.is_synthetic OR i.evidence_kind = 'synthetic_test'));

UPDATE public.customer_contact SET is_synthetic = true
 WHERE NOT coalesce(is_synthetic, false)
   AND (coalesce(email, '') ILIKE '%@example.%'
        OR coalesce(full_name, '') LIKE 'TEST\_%'
        OR coalesce(full_name, '') LIKE '測試%'
        OR source_record_id = 'SWITCHBOARD_ACCEPTANCE_ROLLBACK_ONLY');

-- -----------------------------------------------------------------------------
-- §8 隔離可見：partial index + 行政 card per quarantined message
--   (email_message has no received_at column; ingested_at is the arrival time)
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS email_message_quarantine_idx
  ON public.email_message (ingested_at)
  WHERE org_id IS NULL AND quarantine_reason IS NOT NULL;

CREATE OR REPLACE FUNCTION public.emit_quarantine_cards()
RETURNS int
LANGUAGE plpgsql
AS $$
DECLARE
  q record; v_admin uuid; v_n int := 0; v_skipped int := 0;
BEGIN
  FOR q IN
    SELECT m.id, m.message_id, m.quarantine_reason, b.org_id AS mailbox_org
      FROM public.email_message m
      LEFT JOIN public.email_mailbox b ON b.id = m.mailbox_id
     WHERE m.org_id IS NULL AND m.quarantine_reason IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM public.card c
                        WHERE c.idempotency_key = 'quarantine:' || coalesce(m.message_id, m.id::text))
     ORDER BY m.ingested_at, m.id
  LOOP
    SELECT e.id INTO v_admin FROM public.employee e
     WHERE e.org_id = q.mailbox_org AND e.role_code = 'admin'
       AND e.employment_status = 'active' AND e.identity_confirmed
     ORDER BY e.id LIMIT 1;
    IF q.mailbox_org IS NULL OR v_admin IS NULL THEN
      v_skipped := v_skipped + 1;
      CONTINUE;
    END IF;
    PERFORM public.enqueue_card(
      q.mailbox_org, NULL, v_admin, 'admin', 'quarantine:' || coalesce(q.message_id, q.id::text),
      jsonb_build_array(jsonb_build_object('label', '隔離原因', 'value', q.quarantine_reason, 'sql_id', 'quarantine.reason')),
      jsonb_build_object('label', '隔離信待分派', 'email_message_id', q.id));
    v_n := v_n + 1;
  END LOOP;
  IF v_skipped > 0 THEN
    RAISE WARNING 'emit_quarantine_cards: % quarantined message(s) without mailbox org/admin', v_skipped;
  END IF;
  RETURN v_n;
END $$;

DO $$ DECLARE n int; BEGIN
  n := public.emit_quarantine_cards();
  IF n > 0 THEN RAISE NOTICE '009d: % quarantine card(s) emitted', n; END IF;
END $$;

-- -----------------------------------------------------------------------------
-- §9 backtest_gate: thresholds back to R37 (read from backtest_threshold),
--     zero-tolerance four, REAL_MAIL_DROPPED = 0, honest NOT_RUN
-- -----------------------------------------------------------------------------
DROP FUNCTION IF EXISTS public.backtest_gate(uuid);
CREATE OR REPLACE FUNCTION public.backtest_gate(p_run_id uuid)
RETURNS TABLE (metric text, pass boolean, actual text, required text)
LANGUAGE plpgsql
AS $$
DECLARE
  c_gate_min_n constant int := 10;   -- R39 1(b): n<10 => report only, not gated
  v_labeled int; v_eval_cnt int;
  r record;
  v_tp numeric; v_fp numeric; v_fn numeric; v_n int; v_p numeric; v_r numeric;
  v_min_p numeric; v_min_r numeric;
  v_cat09_r numeric; v_otp_p numeric; v_icmd_p numeric; v_inj_r numeric;
  v_comm_p numeric; v_comm_r numeric; v_comm_due_ok boolean;
  v_case_acc numeric; v_ev_match numeric; v_dropped int;
  v_po numeric; v_pe numeric; v_kappa numeric;
BEGIN
  SELECT count(*) INTO v_labeled FROM public.switchboard_gold_label
   WHERE label_a IS NOT NULL AND label_b IS NOT NULL AND gold_category IS NOT NULL;
  SELECT count(*) INTO v_eval_cnt FROM public.switchboard_backtest_eval WHERE run_id = p_run_id;

  IF p_run_id IS NULL OR v_labeled < 200 OR v_eval_cnt < 200 THEN
    RETURN QUERY SELECT 'BACKTEST-200'::text, false,
      format('NOT_RUN (labeled=%s/200, eval=%s/200)', v_labeled, v_eval_cnt),
      'n=200 human double-blind labels & 200 eval rows'::text;
    RETURN;
  END IF;

  -- 1. CAT-01..CAT-08: P >= min_precision AND R >= min_recall (backtest_threshold), n >= 10
  FOR r IN SELECT format('CAT-%s', lpad(gs::text, 2, '0')) AS cat FROM generate_series(1, 8) gs LOOP
    SELECT coalesce(t.min_precision, 0.90), coalesce(t.min_recall, 0.85) INTO v_min_p, v_min_r
      FROM (SELECT 1) d LEFT JOIN public.backtest_threshold t ON t.metric = r.cat AND t.stratum = r.cat;
    SELECT count(*) FILTER (WHERE e.predicted_category = r.cat AND g.gold_category = r.cat),
           count(*) FILTER (WHERE e.predicted_category = r.cat AND g.gold_category IS DISTINCT FROM r.cat),
           count(*) FILTER (WHERE e.predicted_category IS DISTINCT FROM r.cat AND g.gold_category = r.cat),
           count(*) FILTER (WHERE g.gold_category = r.cat)
      INTO v_tp, v_fp, v_fn, v_n
      FROM public.switchboard_backtest_eval e
      JOIN public.switchboard_gold_label g ON g.sample_id = e.sample_id
     WHERE e.run_id = p_run_id;
    v_p := CASE WHEN (v_tp + v_fp) > 0 THEN round(v_tp / (v_tp + v_fp), 4) ELSE 0 END;
    v_r := CASE WHEN (v_tp + v_fn) > 0 THEN round(v_tp / (v_tp + v_fn), 4) ELSE 0 END;
    metric := r.cat || '_PR';
    pass := CASE WHEN v_n < c_gate_min_n THEN NULL ELSE (v_p >= v_min_p AND v_r >= v_min_r) END;
    actual := format('P=%s, R=%s, n=%s%s', v_p, v_r, v_n, CASE WHEN v_n < c_gate_min_n THEN ' (REPORT_ONLY n<10)' ELSE '' END);
    required := format('P>=%s, R>=%s, n>=%s', v_min_p, v_min_r, c_gate_min_n);
    RETURN NEXT;
  END LOOP;

  -- 2. zero-tolerance: CAT-09 isolation recall = 1
  SELECT round(count(*) FILTER (WHERE e.predicted_category = 'CAT-09' AND e.predicted_should_filter AND NOT e.predicted_emit_card)::numeric
               / nullif(count(*), 0), 4) INTO v_cat09_r
    FROM public.switchboard_backtest_eval e JOIN public.switchboard_gold_label g ON g.sample_id = e.sample_id
   WHERE e.run_id = p_run_id AND g.gold_category = 'CAT-09';
  metric := 'CAT_09_ISOLATION_RECALL'; pass := (coalesce(v_cat09_r, 0) = 1.0000);
  actual := format('R=%s', coalesce(v_cat09_r, 0)); required := 'R=1.0000'; RETURN NEXT;

  -- 3. zero-tolerance: CAT-10 OTP precision = 1
  SELECT round(count(*) FILTER (WHERE e.predicted_is_otp AND g.gold_is_otp)::numeric
               / nullif(count(*) FILTER (WHERE e.predicted_is_otp), 0), 4) INTO v_otp_p
    FROM public.switchboard_backtest_eval e JOIN public.switchboard_gold_label g ON g.sample_id = e.sample_id
   WHERE e.run_id = p_run_id;
  metric := 'CAT_10_OTP_PRECISION'; pass := (coalesce(v_otp_p, 0) = 1.0000);
  actual := format('P=%s', coalesce(v_otp_p, 0)); required := 'P=1.0000'; RETURN NEXT;

  -- 4. zero-tolerance: internal command precision = 1
  SELECT round(count(*) FILTER (WHERE e.predicted_is_internal_cmd AND g.gold_is_internal_cmd)::numeric
               / nullif(count(*) FILTER (WHERE e.predicted_is_internal_cmd), 0), 4) INTO v_icmd_p
    FROM public.switchboard_backtest_eval e JOIN public.switchboard_gold_label g ON g.sample_id = e.sample_id
   WHERE e.run_id = p_run_id;
  metric := 'INTERNAL_CMD_PRECISION'; pass := (coalesce(v_icmd_p, 0) = 1.0000);
  actual := format('P=%s', coalesce(v_icmd_p, 0)); required := 'P=1.0000'; RETURN NEXT;

  -- 5. zero-tolerance: injection hard-negative recall = 1
  SELECT round(count(*) FILTER (WHERE e.predicted_is_injection AND NOT e.predicted_is_internal_cmd)::numeric
               / nullif(count(*), 0), 4) INTO v_inj_r
    FROM public.switchboard_backtest_eval e JOIN public.switchboard_gold_label g ON g.sample_id = e.sample_id
   WHERE e.run_id = p_run_id AND g.gold_is_injection;
  metric := 'INJECTION_HARD_NEG_RECALL'; pass := (coalesce(v_inj_r, 0) = 1.0000);
  actual := format('R=%s', coalesce(v_inj_r, 0)); required := 'R=1.0000'; RETURN NEXT;

  -- 6. 真信被丟 = 0
  SELECT count(*) INTO v_dropped
    FROM public.switchboard_backtest_eval e JOIN public.switchboard_gold_label g ON g.sample_id = e.sample_id
   WHERE e.run_id = p_run_id AND g.gold_should_filter = false AND e.predicted_should_filter = true;
  metric := 'REAL_MAIL_DROPPED'; pass := (v_dropped = 0);
  actual := format('dropped=%s', v_dropped); required := 'dropped=0'; RETURN NEXT;

  -- 7. commitment extraction
  SELECT round(count(*) FILTER (WHERE e.predicted_is_commitment AND g.gold_is_commitment)::numeric
               / nullif(count(*) FILTER (WHERE e.predicted_is_commitment), 0), 4),
         round(count(*) FILTER (WHERE e.predicted_is_commitment AND g.gold_is_commitment)::numeric
               / nullif(count(*) FILTER (WHERE g.gold_is_commitment), 0), 4),
         bool_and(NOT g.gold_is_commitment OR e.predicted_commitment_due = g.commitment_due)
    INTO v_comm_p, v_comm_r, v_comm_due_ok
    FROM public.switchboard_backtest_eval e JOIN public.switchboard_gold_label g ON g.sample_id = e.sample_id
   WHERE e.run_id = p_run_id;
  metric := 'COMMITMENT_EXTRACTION';
  pass := (coalesce(v_comm_p, 0) >= 0.85 AND coalesce(v_comm_r, 0) >= 0.80 AND coalesce(v_comm_due_ok, false));
  actual := format('P=%s, R=%s, due_exact=%s', coalesce(v_comm_p, 0), coalesce(v_comm_r, 0), coalesce(v_comm_due_ok, false));
  required := 'P>=0.8500, R>=0.8000, due_exact=true'; RETURN NEXT;

  -- 8. case link accuracy
  SELECT round(count(*) FILTER (WHERE e.predicted_case_code = g.gold_case_code)::numeric / nullif(count(*), 0), 4) INTO v_case_acc
    FROM public.switchboard_backtest_eval e JOIN public.switchboard_gold_label g ON g.sample_id = e.sample_id
   WHERE e.run_id = p_run_id AND g.gold_case_code IS NOT NULL;
  metric := 'CASE_LINK_ACCURACY'; pass := (coalesce(v_case_acc, 0) >= 0.90);
  actual := format('acc=%s', coalesce(v_case_acc, 0)); required := 'acc>=0.9000'; RETURN NEXT;

  -- 9. evidence numbers match
  SELECT round(count(*) FILTER (WHERE e.evidence_numbers_match)::numeric / nullif(count(*), 0), 4) INTO v_ev_match
    FROM public.switchboard_backtest_eval e JOIN public.switchboard_gold_label g ON g.sample_id = e.sample_id
   WHERE e.run_id = p_run_id AND g.gold_should_emit_card;
  metric := 'EVIDENCE_NUMBERS_MATCH'; pass := (coalesce(v_ev_match, 0) = 1.0000);
  actual := format('match=%s', coalesce(v_ev_match, 0)); required := 'match=1.0000'; RETURN NEXT;

  -- 10. Cohen's kappa (two annotators, marginal distributions)
  WITH labeled AS (
    SELECT label_a->>'category' AS ca, label_b->>'category' AS cb
      FROM public.switchboard_gold_label WHERE label_a IS NOT NULL AND label_b IS NOT NULL
  ), tot AS (
    SELECT count(*)::numeric AS n, count(*) FILTER (WHERE ca = cb)::numeric AS agree_n FROM labeled
  ), cats AS (
    SELECT ca AS cat FROM labeled UNION SELECT cb FROM labeled
  ), marginals AS (
    SELECT (SELECT count(*) FROM labeled l WHERE l.ca = cats.cat)::numeric / nullif(t.n, 0) AS pa,
           (SELECT count(*) FROM labeled l WHERE l.cb = cats.cat)::numeric / nullif(t.n, 0) AS pb
      FROM cats CROSS JOIN tot t
  )
  SELECT t.agree_n / nullif(t.n, 0), coalesce((SELECT sum(pa * pb) FROM marginals), 0) INTO v_po, v_pe FROM tot t;
  v_kappa := CASE WHEN coalesce(v_pe, 1) >= 1 THEN 0
                  ELSE round((coalesce(v_po, 0) - coalesce(v_pe, 0)) / nullif(1.0 - coalesce(v_pe, 0), 0), 4) END;
  metric := 'COHEN_KAPPA_200'; pass := (v_labeled >= 200 AND coalesce(v_kappa, 0) >= 0.75);
  actual := format('n=%s, kappa=%s (Po=%s, Pe=%s)', v_labeled, coalesce(v_kappa, 0), round(coalesce(v_po, 0), 4), round(coalesce(v_pe, 0), 4));
  required := 'n=200, kappa>=0.7500'; RETURN NEXT;
END $$;

-- -----------------------------------------------------------------------------
-- §10 r32_assert_all: + SW-ORG-01, SW-SER-03/04, SW-EVD-01; HYG covers outbound
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.r32_assert_all()
RETURNS jsonb
LANGUAGE plpgsql
AS $$
DECLARE
  v_bad bigint; v_t record; v_n bigint;
  v_bt_not_run boolean := false; v_bt_bad int := 0; v_bt_status text;
BEGIN
  -- SW-SER-01
  SELECT count(*) INTO v_bad FROM public.serial_allocator a
   WHERE a.next_serial <= coalesce((SELECT max(sa.serial_no) FROM public.serial_assignment sa
                                     WHERE sa.org_id = a.org_id AND sa.mode = 'live' AND NOT sa.voided_by_cutover AND sa.serial_no > 0), 12084);
  IF v_bad > 0 THEN RAISE EXCEPTION 'SW-SER-01 FAILED: % org(s) have next_serial <= max(serial_no)', v_bad; END IF;

  -- SW-SER-02
  SELECT count(*) INTO v_bad FROM public.serial_assignment sa JOIN public.serial_allocator a ON a.org_id = sa.org_id
   WHERE sa.mode = 'dry_run' AND NOT sa.voided_by_cutover AND (sa.serial_no >= a.next_serial OR sa.serial_no > -12085);
  IF v_bad > 0 THEN RAISE EXCEPTION 'SW-SER-02 FAILED: % dry_run serial(s) invalid or >= next_serial', v_bad; END IF;

  -- SW-SER-03: no cc serial negated without Dry-Run evidence (009c damage fully restored)
  SELECT count(*) INTO v_bad FROM public.client_communication c
   WHERE c.serial_no BETWEEN -12105 AND -12085
     AND NOT public.r39_thread_has_dry_run(c.org_id, c.thread_fingerprint)
     AND NOT EXISTS (SELECT 1 FROM public.serial_assignment sa
                      WHERE sa.org_id = c.org_id AND sa.mode = 'dry_run' AND sa.serial_no = c.serial_no);
  IF v_bad > 0 THEN RAISE EXCEPTION 'SW-SER-03 FAILED: % cc serial(s) negated without DRY_RUN evidence', v_bad; END IF;

  -- SW-SER-04: no live serial voided as Dry-Run without evidence
  SELECT count(*) INTO v_bad FROM public.serial_assignment sa
   WHERE sa.voided_by_cutover AND sa.void_reason IN ('R38_DRYRUN_NEGATED', 'R39_DRYRUN_NEGATED')
     AND NOT public.r39_thread_has_dry_run(sa.org_id, sa.fingerprint)
     AND NOT EXISTS (SELECT 1 FROM public.client_communication c WHERE c.org_id = sa.org_id AND c.serial_no = -sa.serial_no);
  IF v_bad > 0 THEN RAISE EXCEPTION 'SW-SER-04 FAILED: % serial_assignment row(s) voided without DRY_RUN evidence', v_bad; END IF;

  -- SW-CUT-01
  SELECT count(*) INTO v_bad FROM public.outbound_message WHERE coalesce(actual_sends, 0) > 0;
  IF v_bad > 0 THEN RAISE EXCEPTION 'SW-CUT-01 FAILED: % outbound_message row(s) have actual_sends > 0', v_bad; END IF;
  SELECT count(*) INTO v_bad FROM (
    SELECT org_id, source_event_key FROM public.card
     WHERE mode = 'live' AND state IN ('open', 'escalated') AND coalesce(source_event_key, '') <> ''
     GROUP BY org_id, source_event_key HAVING count(*) > 1) d;
  IF v_bad > 0 THEN RAISE EXCEPTION 'SW-CUT-01 FAILED: % duplicate open/escalated live card group(s)', v_bad; END IF;
  SELECT count(*) INTO v_bad FROM public.card d JOIN public.card l
    ON l.org_id = d.org_id AND l.source_event_key = d.source_event_key
   WHERE d.mode = 'dry_run' AND d.state = 'dry_run' AND l.mode = 'live' AND coalesce(d.source_event_key, '') <> '';
  IF v_bad > 0 THEN RAISE EXCEPTION 'SW-CUT-01 FAILED: % dry_run card(s) coexist with live card', v_bad; END IF;

  -- SW-HYG-01
  SELECT (SELECT count(*) FROM public.customer_contact
           WHERE NOT coalesce(is_synthetic, false)
             AND (coalesce(email, '') ILIKE '%@example.%' OR coalesce(full_name, '') LIKE 'TEST\_%'
                  OR coalesce(full_name, '') LIKE '測試%' OR source_record_id = 'SWITCHBOARD_ACCEPTANCE_ROLLBACK_ONLY'))
       + (SELECT count(*) FROM public.switchboard_intake WHERE evidence_kind = 'synthetic_test' AND NOT coalesce(is_synthetic, false))
       + (SELECT count(*) FROM public.outbound_message o JOIN public.switchboard_intake i ON i.id = o.intake_id
           WHERE i.is_synthetic AND NOT o.is_synthetic)
    INTO v_bad;
  IF v_bad > 0 THEN RAISE EXCEPTION 'SW-HYG-01 FAILED: % unmarked synthetic row(s)', v_bad; END IF;

  -- SW-ORG-01: one company, one code
  IF EXISTS (SELECT 1 FROM public.org WHERE id = 'yongxiang') THEN
    RAISE EXCEPTION 'SW-ORG-01 FAILED: legacy org code yongxiang still present';
  END IF;
  FOR v_t IN SELECT c.table_name FROM information_schema.columns c
               JOIN information_schema.tables tb USING (table_schema, table_name)
              WHERE c.table_schema = 'public' AND c.column_name = 'org_id' AND tb.table_type = 'BASE TABLE' LOOP
    EXECUTE format('SELECT count(*) FROM public.%I WHERE org_id = %L', v_t.table_name, 'yongxiang') INTO v_n;
    IF v_n > 0 THEN RAISE EXCEPTION 'SW-ORG-01 FAILED: % yongxiang row(s) in %', v_n, v_t.table_name; END IF;
  END LOOP;
  SELECT count(*) INTO v_bad FROM pg_proc p
   WHERE p.pronamespace = 'public'::regnamespace
     AND p.proname IN ('card_guard', 'otp_deliver', 'enqueue_card', 'card_act', 'assign_serial', 'forward_register_card')
     AND p.prosrc ~ '''yongxiang''';
  IF v_bad > 0 THEN RAISE EXCEPTION 'SW-ORG-01 FAILED: % function(s) still carry yongxiang equivalence hack', v_bad; END IF;

  -- SW-EVD-01: evidence never hard-coded by enqueue_card/card_act; old signature gone
  SELECT count(*) INTO v_bad FROM pg_proc p
   WHERE p.pronamespace = 'public'::regnamespace AND p.proname IN ('enqueue_card', 'card_act')
     AND p.prosrc ~ 'ARRAY\[''case_open_commitments''';
  IF v_bad > 0 OR to_regprocedure('public.enqueue_card(text,uuid,uuid,text,text,jsonb,uuid)') IS NOT NULL THEN
    RAISE EXCEPTION 'SW-EVD-01 FAILED: hard-coded evidence or old enqueue_card signature present';
  END IF;

  -- BACKTEST-200
  SELECT EXISTS (SELECT 1 FROM public.backtest_gate(NULL::uuid) WHERE metric = 'BACKTEST-200' AND actual LIKE 'NOT_RUN%')
    INTO v_bt_not_run;
  IF v_bt_not_run THEN
    v_bt_status := 'NOT_RUN';
  ELSE
    SELECT count(*) INTO v_bt_bad FROM public.backtest_gate(NULL::uuid) WHERE pass IS FALSE;
    IF v_bt_bad > 0 THEN RAISE EXCEPTION 'BACKTEST-200 FAILED: % metric(s) failed', v_bt_bad; END IF;
    v_bt_status := 'PASS';
  END IF;

  RETURN jsonb_build_object(
    'SW-SER-01', 'PASS', 'SW-SER-02', 'PASS', 'SW-SER-03', 'PASS', 'SW-SER-04', 'PASS',
    'SW-CUT-01', 'PASS', 'SW-HYG-01', 'PASS', 'SW-ORG-01', 'PASS', 'SW-EVD-01', 'PASS',
    'BACKTEST-200', v_bt_status);
END $$;

-- -----------------------------------------------------------------------------
-- §11 registry snapshot (single block; replaces 009c's duplicated DELETE+INSERT)
--   * functions defined in THIS file are authoritative -> upsert only if changed
--   * any other registered function whose live definition drifted -> WARNING only
-- -----------------------------------------------------------------------------
DELETE FROM public.r31b_deployment_object WHERE name = 'enqueue_card(text,uuid,uuid,text,text,jsonb,uuid)';

INSERT INTO public.r31b_deployment_object (name, priority, ddl) VALUES
  ('00_drop_enqueue_card_7arg', 5, 'DROP FUNCTION IF EXISTS public.enqueue_card(text, uuid, uuid, text, text, jsonb, uuid);')
ON CONFLICT (name) DO NOTHING;

INSERT INTO public.r31b_deployment_object AS d (name, priority, ddl)
SELECT p.oid::regprocedure::text, 10, pg_get_functiondef(p.oid)
  FROM pg_proc p
 WHERE p.pronamespace = 'public'::regnamespace
   AND p.proname IN ('r39_thread_has_dry_run', 'r39_dry_run_serial_repair', 'assign_serial', 'card_guard',
                     'enqueue_card', 'card_act', 'forward_register_card', 'r32_short_pay_finance_card',
                     'otp_deliver', 'r32_unlinked_org_marker_guard', 'guard_overtime_stage_before',
                     'emit_quarantine_cards', 'backtest_gate', 'r32_assert_all')
ON CONFLICT (name) DO UPDATE SET ddl = EXCLUDED.ddl, priority = EXCLUDED.priority
 WHERE d.ddl IS DISTINCT FROM EXCLUDED.ddl OR d.priority IS DISTINCT FROM EXCLUDED.priority;

DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT d.name FROM public.r31b_deployment_object d
      JOIN pg_proc p ON p.oid = to_regprocedure('public.' || d.name)
     WHERE md5(d.ddl) IS DISTINCT FROM md5(pg_get_functiondef(p.oid))
  LOOP
    RAISE WARNING '009d registry drift: % differs from live pg_proc (not overwritten; review manually)', r.name;
  END LOOP;
END $$;

-- -----------------------------------------------------------------------------
-- §12 ledger
-- -----------------------------------------------------------------------------
INSERT INTO public.schema_migration (name, note)
VALUES ('009d_r32_fixpack', 'Fable R39 Step 6 corrections')
ON CONFLICT (name) DO NOTHING;

COMMIT;
