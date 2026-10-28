BEGIN;
DO $$ BEGIN IF current_database() <> 'yongxiang_plumb_r39_clone' THEN RAISE EXCEPTION 'clone only'; END IF; END $$;
CREATE OR REPLACE FUNCTION public.r32_unlinked_org_marker_guard()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE
  v_row jsonb := to_jsonb(NEW);
  v_inbound boolean := TG_TABLE_NAME IN ('email_message', 'switchboard_intake');
  v_mb_org text;
  txt text := lower(coalesce(v_row->>'subject', '') || ' ' ||
              coalesce(v_row->>'body_new_text', '') || ' ' ||
              coalesce(v_row->>'body_text', '') || ' ' ||
              coalesce(v_row->>'draft_body', '') || ' ' ||
              coalesce(v_row->>'final_body', '') || ' ' ||
              coalesce(v_row->>'from_addr', '') || ' ' ||
              coalesce(v_row->>'payload', ''));
  has_yx_hard boolean;
  has_sj_hard boolean;
  has_sj_any  boolean;
  bad text;
BEGIN
  -- Ticket 105: mailbox ownership is the inbound boundary; a mixed-tax-ID
  -- message and an explicit SJ company name must also reach quarantine.
  IF v_inbound THEN
    IF TG_TABLE_NAME = 'email_message' THEN
      SELECT b.org_id INTO v_mb_org FROM public.email_mailbox b WHERE b.id = NEW.mailbox_id;
    ELSE
      SELECT b.org_id INTO v_mb_org FROM public.email_mailbox b WHERE lower(b.address) = lower(NEW.mailbox);
    END IF;
    v_mb_org := coalesce(v_mb_org, v_row->>'org_id');
    IF EXISTS (SELECT 1 FROM public.org_marker m
                WHERE m.org_code <> v_mb_org AND position(lower(m.value) IN txt)>0) THEN
      NEW.org_id := NULL;
      NEW.quarantine_reason := 'R32-ORG-MARKER: cross-org or mixed markers in inbound mailbox';
      RETURN NEW;
    END IF;
  END IF;
  IF v_inbound AND TG_OP = 'INSERT' AND NOT public.org_marker_armed('SJ')
     AND (TG_TABLE_NAME = 'email_message' OR coalesce(v_row->>'channel', '') = 'email') THEN
    IF TG_TABLE_NAME = 'email_message' THEN
      SELECT b.org_id INTO v_mb_org FROM public.email_mailbox b
       WHERE b.id = nullif(v_row->>'mailbox_id', '')::uuid;
      IF v_mb_org IS NULL AND nullif(v_row->>'mailbox_id', '') IS NULL THEN
        SELECT b.org_id INTO v_mb_org FROM public.email_mailbox b
         WHERE lower(b.address) = lower(coalesce(substring(v_row->>'from_addr' FROM '<([^<>]+)>\s*$'),
                                                btrim(coalesce(v_row->>'from_addr', ''))))
           AND coalesce((v_row->>'dkim_pass')::boolean, false)
           AND lower(btrim(coalesce(v_row->>'dkim_domain', ''))) = lower(split_part(b.address, '@', 2));
      END IF;
    ELSE
      SELECT b.org_id INTO v_mb_org FROM public.email_mailbox b
       WHERE lower(b.address) = lower(btrim(coalesce(v_row->>'mailbox', '')));
    END IF;
    NEW.org_id := v_mb_org;
    IF v_mb_org IS NULL THEN
      NEW.quarantine_reason := coalesce(NEW.quarantine_reason, 'ORG-MARKER-NOT-ARMED');
    END IF;
    RETURN NEW;
  END IF;

  has_yx_hard := EXISTS (SELECT 1 FROM public.org_marker m WHERE m.org_code = 'YX' AND m.kind IN ('tax_id', 'domain')
                                                            AND position(lower(m.value) IN txt) > 0);
  has_sj_hard := EXISTS (SELECT 1 FROM public.org_marker m WHERE m.org_code = 'SJ' AND m.kind IN ('tax_id', 'domain')
                                                            AND position(lower(m.value) IN txt) > 0);
  has_sj_any  := EXISTS (SELECT 1 FROM public.org_marker m WHERE m.org_code = 'SJ'
                                                            AND position(lower(m.value) IN txt) > 0);

  IF (v_row->>'case_id') IS NULL THEN
    IF (v_row->>'org_id') = 'YX' AND has_sj_hard AND NOT has_yx_hard THEN
      bad := 'unlinked message carries SJ marker but org_id=YX';
    ELSIF (v_row->>'org_id') = 'SJ' AND has_yx_hard AND NOT has_sj_hard THEN
      bad := 'unlinked message carries YX marker but org_id=SJ';
    ELSIF TG_TABLE_NAME IN ('outbound_message', 'client_communication')
          AND (v_row->>'org_id') = 'SJ' AND (NOT public.org_marker_armed('SJ') OR NOT has_sj_any) THEN
      bad := 'unlinked SJ row requires armed SJ markers and an explicit SJ marker';
    END IF;
  END IF;

  IF bad IS NOT NULL THEN
    IF v_inbound THEN
      NEW.org_id := NULL;
      NEW.quarantine_reason := 'R32-ORG-MARKER:' || bad;
      RETURN NEW;
    END IF;
    RAISE EXCEPTION 'R32-ORG-MARKER: %', bad;
  END IF;

  IF TG_TABLE_NAME IN ('switchboard_intake', 'email_message') THEN
    IF NEW.org_id IS NULL AND NEW.quarantine_reason IS NULL
       AND NOT coalesce((v_row->>'is_synthetic')::boolean, false) THEN
      NEW.quarantine_reason := 'NO-ORG';
    END IF;
  END IF;
  RETURN NEW;
END $function$;

CREATE OR REPLACE FUNCTION public.assign_serial(p_org text, p_fp text, p_mode text DEFAULT 'live'::text)
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
DECLARE
  s int;
  v_floor int;
  v_eff_fp text;
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

  SELECT a.canonical_fp INTO v_eff_fp
    FROM public.serial_fingerprint_alias a
   WHERE a.org_id = p_org AND a.alias_fp = p_fp
   LIMIT 1;
  v_eff_fp := coalesce(v_eff_fp, p_fp);

  -- Existing live identity is safe to read in shadow. Allocation remains gated.
  IF p_mode = 'live' THEN
    SELECT serial_no INTO s FROM public.serial_assignment
     WHERE org_id=p_org AND fingerprint=v_eff_fp AND mode='live' AND NOT voided_by_cutover;
    IF FOUND THEN RETURN s; END IF;
  END IF;

  -- R43-7 entry 1: a live number only for a LIVE-ready org
  IF p_mode = 'live' AND NOT coalesce((public.org_live_ready(p_org)->>'ready')::boolean, false) THEN
    RAISE EXCEPTION 'SW-ORG-02: assign_serial(live) refused, org % is not LIVE-ready %', p_org, public.org_live_ready(p_org)
      USING ERRCODE = '42501', HINT = 'use mode dry_run until org_live_ready().ready';
  END IF;

  PERFORM 1 FROM public.serial_allocator WHERE org_id = p_org FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'unknown org %', p_org;
  END IF;

  IF p_mode = 'dry_run' THEN
    IF EXISTS (SELECT 1 FROM public.serial_assignment
                WHERE org_id = p_org AND fingerprint = v_eff_fp AND mode = 'live' AND NOT voided_by_cutover) THEN
      RAISE EXCEPTION 'fingerprint already has live serial; dry_run refused';
    END IF;

    SELECT serial_no INTO s FROM public.serial_assignment
     WHERE org_id = p_org AND fingerprint = v_eff_fp AND mode = 'dry_run' AND NOT voided_by_cutover;
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
    VALUES (p_org, v_eff_fp, s, 'dry_run', false)
    ON CONFLICT (org_id, fingerprint, mode) DO UPDATE
       SET serial_no = EXCLUDED.serial_no, voided_by_cutover = false, voided_at = NULL, void_reason = NULL
     WHERE sa.voided_by_cutover;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'assign_serial: active dry_run row appeared concurrently for %/%', p_org, v_eff_fp;
    END IF;
    RETURN s;
  END IF;

  SELECT serial_no INTO s FROM public.serial_assignment
   WHERE org_id = p_org AND fingerprint = v_eff_fp AND mode = 'live' AND NOT voided_by_cutover;
  IF FOUND THEN
    RETURN s;
  END IF;

  -- R39 3④: any positive historical number for this thread is reused (not only >= 12085)
  SELECT serial_no INTO s FROM public.client_communication
   WHERE org_id = p_org AND thread_fingerprint = v_eff_fp AND serial_no > 0 AND NOT is_synthetic
   ORDER BY serial_no
   LIMIT 1;

  IF s IS NULL THEN
    SELECT GREATEST(
      12085,
      coalesce((SELECT sheet_max_reconciled + 1 FROM public.serial_allocator WHERE org_id = p_org), 12085),
      coalesce((SELECT max(serial_no) + 1 FROM public.client_communication WHERE org_id = p_org AND serial_no > 0 AND NOT is_synthetic), 12085),
      coalesce((SELECT max(serial_no) + 1 FROM public.serial_assignment
                 WHERE org_id = p_org AND mode = 'live' AND NOT voided_by_cutover AND serial_no > 0), 12085)
    ) INTO v_floor;

    UPDATE public.serial_allocator
       SET next_serial = GREATEST(next_serial, v_floor) + 1
     WHERE org_id = p_org
     RETURNING next_serial - 1 INTO s;
    WHILE EXISTS (SELECT 1 FROM public.serial_assignment WHERE org_id = p_org AND serial_no = s) LOOP
      UPDATE public.serial_allocator SET next_serial = next_serial + 1
       WHERE org_id = p_org RETURNING next_serial - 1 INTO s;
    END LOOP;
  END IF;

  INSERT INTO public.serial_assignment AS sa (org_id, fingerprint, serial_no, mode, voided_by_cutover)
  VALUES (p_org, v_eff_fp, s, 'live', false)
  ON CONFLICT (org_id, fingerprint, mode) DO UPDATE
     SET serial_no = EXCLUDED.serial_no, voided_by_cutover = false, voided_at = NULL, void_reason = NULL
   WHERE sa.voided_by_cutover;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'assign_serial: active live row appeared concurrently for %/%', p_org, v_eff_fp;
  END IF;
  RETURN s;
END $function$;

CREATE OR REPLACE FUNCTION public.sealed_release_allowed(p_case uuid, p_milestone text)
 RETURNS boolean
 LANGUAGE sql
AS $function$
  SELECT EXISTS (
    SELECT 1
    FROM public.deliverable_release_gate g
    LEFT JOIN public.invoice_paid_v iv ON iv.id = g.invoice_id AND iv.case_id = g.case_id
    WHERE g.case_id = p_case
      AND g.milestone = p_milestone
      AND g.deliverable_class = 'sealed'
      AND (
        coalesce(iv.paid, false) = true AND iv.unpaid_amount <= 0
        OR (g.override_by IS NOT NULL AND g.override_expires_at > now())
      )
  )
$function$;

CREATE OR REPLACE FUNCTION public.satcmd_guard()
RETURNS trigger LANGUAGE plpgsql AS $function$
DECLARE v_org text;
BEGIN
  SELECT b.org_id INTO v_org
  FROM public.email_message m
  JOIN public.email_mailbox b ON lower(b.address)=lower(coalesce(substring(m.from_addr FROM '<([^<>]+)>\s*$'),btrim(m.from_addr)))
  JOIN public.satellite_sent_copy sc ON sc.mailbox_id=b.id AND sc.message_id=m.message_id
  JOIN public.email_sent_copy es ON es.mailbox_id=b.id AND es.message_id=m.message_id
  WHERE m.id=NEW.source_message_id AND m.org_id=b.org_id AND m.org_id=NEW.org_id
    AND (b.role='satellite' OR (b.role='switchboard' AND NEW.command_kind='forward_register'))
    AND m.sent_copy_verified AND m.dkim_pass AND m.spf_pass
    AND lower(m.dkim_domain)=lower(split_part(b.address,'@',2))
    AND lower(es.header_d)=lower(m.dkim_domain)
    AND lower(coalesce(sc.dkim_domain,m.dkim_domain))=lower(es.header_d)
  LIMIT 1;
  IF v_org IS NULL THEN
    RAISE EXCEPTION 'R32-SAT-AUTH: command source not an authenticated satellite with observed aligned DKIM and IMAP Sent Message-ID evidence';
  END IF;
  IF NEW.requester_employee_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM public.employee WHERE id=NEW.requester_employee_id AND org_id=v_org
      AND identity_confirmed AND employment_status='active') THEN
    RAISE EXCEPTION 'requester not active and identity confirmed';
  END IF;
  IF NEW.command_kind='forward_register' AND NEW.requester_employee_id IS NULL
    AND NOT EXISTS (SELECT 1 FROM public.backfill_quarantine WHERE payload->>'message_id'=NEW.source_message_id::text) THEN
    RAISE EXCEPTION 'unresolved forward requester must be quarantined';
  END IF;
  RETURN NEW;
END $function$;

CREATE OR REPLACE FUNCTION public.emit_quarantine_cards()
 RETURNS integer
 LANGUAGE plpgsql
AS $function$
DECLARE
  q record; v_admin uuid; v_n int := 0; v_skipped int := 0; v_org text; v_unknown boolean; cid uuid;
BEGIN
  -- (1) quarantined mail (effective view: a human disposition ends visibility)
  FOR q IN
    SELECT m.id, m.message_id, m.quarantine_reason, b.org_id AS mailbox_org
      FROM public.email_message_effective_v m
      LEFT JOIN public.email_mailbox b ON b.id = m.mailbox_id
     WHERE m.still_quarantined AND m.quarantine_reason IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM public.card c
                        WHERE c.idempotency_key = 'quarantine:' || coalesce(m.message_id, m.id::text))
     ORDER BY m.ingested_at, m.id
  LOOP
    v_unknown := q.mailbox_org IS NULL;
    v_org := coalesce(q.mailbox_org, 'YX');
    SELECT e.id INTO v_admin FROM public.employee e
     WHERE e.org_id = v_org
       AND EXISTS (SELECT 1 FROM public.employee_role_map rm WHERE rm.employee_id = e.id AND rm.role_code = 'admin')
       AND e.employment_status = 'active' AND e.identity_confirmed
     ORDER BY (e.full_name = '羅薇')::int DESC, e.id LIMIT 1;
    IF v_admin IS NULL THEN
      v_skipped := v_skipped + 1;
      CONTINUE;
    END IF;
    cid := public.enqueue_card(
      p_org => v_org, p_case => NULL, p_assignee => v_admin, p_kind => 'admin',
      p_key => 'quarantine:' || coalesce(q.message_id, q.id::text),
      p_evidence => jsonb_build_array(jsonb_build_object('label', '隔離原因', 'value', q.quarantine_reason, 'sql_id', 'quarantine.reason')),
      p_proposed => jsonb_build_object(
        'label', CASE WHEN v_unknown THEN '歸屬不明：隔離信待分派' ELSE '隔離信待分派' END,
        'email_message_id', q.id, 'message_id', q.message_id,
        'card_org_is_mail_org', NOT v_unknown));
    UPDATE public.card SET title = CASE WHEN v_unknown THEN '歸屬不明：隔離信待分派' ELSE '隔離信待分派' END
     WHERE id = cid AND acted_at IS NULL
       AND title IS DISTINCT FROM CASE WHEN v_unknown THEN '歸屬不明：隔離信待分派' ELSE '隔離信待分派' END;
    v_n := v_n + 1;
  END LOOP;

  -- (2) quarantined switchboard_intake rows (Fable Step 8 #3)
  FOR q IN
    SELECT i.id, i.quarantine_reason, b.org_id AS mailbox_org
      FROM public.switchboard_intake i
      LEFT JOIN public.email_mailbox b ON lower(b.address) = lower(btrim(coalesce(i.mailbox, '')))
     WHERE i.org_id IS NULL AND i.quarantine_reason IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM public.card c WHERE c.idempotency_key = 'quarantine:intake:' || i.id::text)
     ORDER BY i.created_at, i.id
  LOOP
    v_unknown := q.mailbox_org IS NULL;
    v_org := coalesce(q.mailbox_org, 'YX');
    SELECT e.id INTO v_admin FROM public.employee e
     WHERE e.org_id = v_org
       AND EXISTS (SELECT 1 FROM public.employee_role_map rm WHERE rm.employee_id = e.id AND rm.role_code = 'admin')
       AND e.employment_status = 'active' AND e.identity_confirmed
     ORDER BY (e.full_name = '羅薇')::int DESC, e.id LIMIT 1;
    IF v_admin IS NULL THEN
      v_skipped := v_skipped + 1;
      CONTINUE;
    END IF;
    cid := public.enqueue_card(
      p_org => v_org, p_case => NULL, p_assignee => v_admin, p_kind => 'admin',
      p_key => 'quarantine:intake:' || q.id::text,
      p_evidence => jsonb_build_array(jsonb_build_object('label', '隔離原因', 'value', q.quarantine_reason, 'sql_id', 'quarantine.intake_reason')),
      p_proposed => jsonb_build_object(
        'label', CASE WHEN v_unknown THEN '歸屬不明：隔離來件待分派' ELSE '隔離來件待分派' END,
        'intake_id', q.id, 'card_org_is_mail_org', NOT v_unknown));
    UPDATE public.card SET title = CASE WHEN v_unknown THEN '歸屬不明：隔離來件待分派' ELSE '隔離來件待分派' END
     WHERE id = cid AND acted_at IS NULL
       AND title IS DISTINCT FROM CASE WHEN v_unknown THEN '歸屬不明：隔離來件待分派' ELSE '隔離來件待分派' END;
    v_n := v_n + 1;
  END LOOP;

  IF v_skipped > 0 THEN
    RAISE WARNING 'emit_quarantine_cards: % quarantined row(s) without an active admin', v_skipped;
  END IF;
  RETURN v_n;
END $function$
;
COMMIT;
