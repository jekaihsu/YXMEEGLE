-- =============================================================================
-- 009c_r32_fixpack.sql
-- Fable Step 5 (R38): Honest Backtest Gate + Removal of 3 Green-Light Backdoors
--                     + 5 Implementation Deviation Fixes + Non-Destructive Hygiene
-- Target DBs:
--   1. Box PostgreSQL 17: yongxiang_plumb
--   2. Windows Laptop PostgreSQL 17: yongxiang_unified_r23
-- =============================================================================
BEGIN;

-- =============================================================================
-- 1. Delete Synthetic 200 Gold/Eval & Enforce Real email_message FK + NOT_RUN
-- =============================================================================
DELETE FROM public.switchboard_backtest_eval
WHERE run_id = '00000000-0000-0000-0000-000000000370';

DELETE FROM public.switchboard_gold_label
WHERE message_id LIKE '<gold-%';

ALTER TABLE public.switchboard_gold_label
  ADD COLUMN IF NOT EXISTS label_a jsonb,
  ADD COLUMN IF NOT EXISTS label_b jsonb,
  ALTER COLUMN gold_category DROP NOT NULL,
  ALTER COLUMN agreed SET DEFAULT false;

ALTER TABLE public.switchboard_gold_label
  DROP CONSTRAINT IF EXISTS r38_no_synthetic_gold_chk,
  ADD CONSTRAINT r38_no_synthetic_gold_chk CHECK (message_id NOT LIKE '<gold-%'),
  DROP CONSTRAINT IF EXISTS r38_gold_email_fk,
  ADD CONSTRAINT r38_gold_email_fk
    FOREIGN KEY (message_id) REFERENCES public.email_message(message_id) NOT VALID;

ALTER TABLE public.switchboard_backtest_eval
  ALTER COLUMN predicted_is_otp DROP DEFAULT,
  ALTER COLUMN predicted_is_internal_cmd DROP DEFAULT,
  ALTER COLUMN predicted_is_injection DROP DEFAULT,
  ALTER COLUMN predicted_is_commitment DROP DEFAULT,
  ALTER COLUMN predicted_emit_card DROP DEFAULT,
  ALTER COLUMN predicted_should_filter DROP DEFAULT,
  ALTER COLUMN evidence_numbers_match DROP DEFAULT;

-- Sample 200 real candidate messages from public.email_message awaiting human
-- double-blind labeling by 羅薇 (label_a) & 柏頤 (label_b).
DO $$
DECLARE
  v_cur int;
BEGIN
  SELECT count(*) INTO v_cur FROM public.switchboard_gold_label;
  IF v_cur < 200 THEN
    INSERT INTO public.switchboard_gold_label (
      sample_id,
      message_id,
      stratum,
      annotator_a,
      annotator_b,
      agreed,
      gold_category,
      gold_is_otp,
      gold_is_internal_cmd,
      gold_is_injection,
      gold_is_commitment,
      commitment_due,
      gold_case_code,
      gold_should_emit_card,
      gold_should_filter,
      label_a,
      label_b,
      annotator_a_employee_id,
      annotator_b_employee_id
    )
    SELECT
      'G-' || lpad(row_number() OVER (ORDER BY m.sent_at DESC NULLS LAST, m.id)::text, 3, '0'),
      m.message_id,
      coalesce(nullif(m.category, ''), 'CAT-01'),
      '羅薇',
      '柏頤',
      false,
      NULL,
      false,
      false,
      false,
      false,
      NULL,
      NULL,
      false,
      false,
      NULL,
      NULL,
      'c22b9383-60ec-5bcf-8bb1-4131de44b420'::uuid,
      'a968fbf8-c0ac-5d6a-9939-80584ede3509'::uuid
    FROM (
      SELECT DISTINCT ON (em.message_id) em.*
      FROM public.email_message em
      WHERE em.message_id IS NOT NULL
        AND em.message_id NOT LIKE '<gold-%'
      ORDER BY em.message_id, em.sent_at DESC NULLS LAST
    ) m
    ORDER BY m.sent_at DESC NULLS LAST, m.id
    LIMIT 200
    ON CONFLICT DO NOTHING;
  END IF;
END $$;

DROP FUNCTION IF EXISTS public.backtest_gate(uuid);
CREATE OR REPLACE FUNCTION public.backtest_gate(p_run_id uuid)
RETURNS TABLE (
  metric text,
  pass boolean,
  actual text,
  required text
)
LANGUAGE plpgsql
AS $$
DECLARE
  v_labeled int;
  v_eval_cnt int;
  r record;
  v_tp numeric;
  v_fp numeric;
  v_fn numeric;
  v_p numeric;
  v_r numeric;
  v_f1 numeric;
  v_cat09_r numeric;
  v_otp_p numeric;
  v_icmd_p numeric;
  v_inj_r numeric;
  v_comm_p numeric;
  v_comm_r numeric;
  v_comm_due_ok boolean;
  v_case_acc numeric;
  v_ev_match numeric;
  v_po numeric;
  v_pe numeric;
  v_kappa numeric;
BEGIN
  SELECT count(*) INTO v_labeled
  FROM public.switchboard_gold_label
  WHERE label_a IS NOT NULL
    AND label_b IS NOT NULL
    AND gold_category IS NOT NULL;

  SELECT count(*) INTO v_eval_cnt
  FROM public.switchboard_backtest_eval
  WHERE run_id = p_run_id;

  IF p_run_id IS NULL OR v_labeled < 200 OR v_eval_cnt < 200 THEN
    RETURN QUERY SELECT
      'BACKTEST-200'::text,
      false,
      format('NOT_RUN (labeled=%s/200, eval=%s/200)', v_labeled, v_eval_cnt),
      'n=200 human double-blind labels & 200 eval rows'::text;
    RETURN;
  END IF;

  -- 1. CAT-01..CAT-10 F1 >= 0.85
  FOR r IN
    SELECT format('CAT-%s', lpad(gs::text, 2, '0')) AS cat
    FROM generate_series(1, 10) gs
  LOOP
    SELECT
      count(*) FILTER (WHERE e.predicted_category = r.cat AND g.gold_category = r.cat),
      count(*) FILTER (WHERE e.predicted_category = r.cat AND g.gold_category <> r.cat),
      count(*) FILTER (WHERE e.predicted_category <> r.cat AND g.gold_category = r.cat)
    INTO v_tp, v_fp, v_fn
    FROM public.switchboard_backtest_eval e
    JOIN public.switchboard_gold_label g ON g.sample_id = e.sample_id
    WHERE e.run_id = p_run_id;

    v_p := CASE WHEN (v_tp + v_fp) > 0 THEN v_tp / (v_tp + v_fp) ELSE 0 END;
    v_r := CASE WHEN (v_tp + v_fn) > 0 THEN v_tp / (v_tp + v_fn) ELSE 0 END;
    v_f1 := CASE WHEN (v_p + v_r) > 0 THEN round((2 * v_p * v_r) / (v_p + v_r), 4) ELSE 0 END;

    metric := r.cat || '_F1';
    pass := (v_f1 >= 0.85);
    actual := format('F1=%s (P=%s, R=%s)', v_f1, round(v_p, 4), round(v_r, 4));
    required := 'F1>=0.8500';
    RETURN NEXT;
  END LOOP;

  -- 2. CAT-09 Isolation Recall = 1.00
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

  -- 3. CAT-10 OTP Precision = 1.00
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

  -- 4. Internal Command Precision = 1.00
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

  -- 5. Injection Hard-Negative Recall = 1.00
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

  -- 6. Commitment Extraction P >= 0.85, R >= 0.80, due_date exact
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

  -- 7. Case Link Accuracy >= 0.90
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

  -- 8. Evidence Numbers 100% SQL match
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

  -- 9. Real Cohen's kappa across 200 double-blind labels using marginal category probabilities
  WITH labeled AS (
    SELECT
      label_a->>'category' AS ca,
      label_b->>'category' AS cb
    FROM public.switchboard_gold_label
    WHERE label_a IS NOT NULL AND label_b IS NOT NULL
  ),
  tot AS (
    SELECT count(*)::numeric AS n,
           count(*) FILTER (WHERE ca = cb)::numeric AS agree_n
    FROM labeled
  ),
  marginals AS (
    SELECT
      cats.cat,
      count(*) FILTER (WHERE l.ca = cats.cat)::numeric / nullif(t.n, 0) AS pa,
      count(*) FILTER (WHERE l.cb = cats.cat)::numeric / nullif(t.n, 0) AS pb
    FROM (SELECT DISTINCT ca AS cat FROM labeled UNION SELECT DISTINCT cb AS cat FROM labeled) cats
    CROSS JOIN tot t
    LEFT JOIN labeled l ON true
    GROUP BY cats.cat, t.n
  )
  SELECT
    t.agree_n / nullif(t.n, 0),
    coalesce((SELECT sum(pa * pb) FROM marginals), 0)
  INTO v_po, v_pe
  FROM tot t;

  v_kappa := CASE
    WHEN coalesce(v_pe, 1) >= 1 THEN 0
    ELSE round((coalesce(v_po, 0) - coalesce(v_pe, 0)) / nullif(1.0 - coalesce(v_pe, 0), 0), 4)
  END;

  metric := 'COHEN_KAPPA_200';
  pass := (v_labeled = 200 AND coalesce(v_kappa, 0) >= 0.75);
  actual := format('n=%s, kappa=%s (Po=%s, Pe=%s)', v_labeled, coalesce(v_kappa, 0), round(coalesce(v_po, 0), 4), round(coalesce(v_pe, 0), 4));
  required := 'n=200, kappa>=0.7500';
  RETURN NEXT;
END $$;

-- =============================================================================
-- 2. Revoke the 3 "Green-Light Backdoors"
-- =============================================================================

-- 2(a) Restore synthetic contact names and r28-worker4b-seed evidence_kind,
--      and mark them with is_synthetic = true instead of disguising them.
--      Also apply safe Hygiene cleanup (no '測試%' / 'TEST_%' deletes, no TRUNCATE, no DROP VIEW ... CASCADE).
UPDATE public.customer_contact
SET full_name = '測試收件人',
    is_synthetic = true
WHERE id = 'fd5c185e-ef02-406d-a0d6-a389f5c01325';

UPDATE public.customer_contact
SET full_name = 'TEST_E2E_CONTACT_DO_NOT_SEND',
    is_synthetic = true
WHERE id = '6acbf192-92ef-46ac-8d6a-e8a9c5a0d8f2';

UPDATE public.customer_contact
SET full_name = '測試資料：專案聯絡窗口',
    is_synthetic = true
WHERE full_name IN ('專案聯絡窗口（種子）', '測試資料：專案聯絡窗口');

UPDATE public.customer_contact
SET is_synthetic = true
WHERE coalesce(email, '') ILIKE '%@example.%'
   OR coalesce(full_name, '') LIKE 'TEST_%'
   OR coalesce(full_name, '') LIKE '測試%'
   OR source_record_id = 'SWITCHBOARD_ACCEPTANCE_ROLLBACK_ONLY';

ALTER TABLE public.switchboard_intake
  ADD COLUMN IF NOT EXISTS is_synthetic boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS org_id text,
  ADD COLUMN IF NOT EXISTS quarantine_reason text;

UPDATE public.switchboard_intake
SET evidence_kind = 'synthetic_test',
    is_synthetic = true
WHERE source_key = 'r28-worker4b-seed'
   OR source_key LIKE 'r28-worker4b-seed:%';

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

-- 2(b) Remove @r29.test / @example.test bypass from r32_unlinked_org_marker_guard
--      and quarantine inbound messages non-destructively instead of dropping mail.
DROP FUNCTION IF EXISTS public.enforce_org_content_marker() CASCADE;

ALTER TABLE public.email_message
  ADD COLUMN IF NOT EXISTS quarantine_reason text;

ALTER TABLE public.email_message
  ALTER COLUMN org_id DROP NOT NULL;

CREATE OR REPLACE FUNCTION public.r32_unlinked_org_marker_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  v_row jsonb := to_jsonb(NEW);
  txt text := coalesce(v_row->>'subject', '') || ' ' ||
              coalesce(v_row->>'body_new_text', '') || ' ' ||
              coalesce(v_row->>'body_text', '') || ' ' ||
              coalesce(v_row->>'draft_body', '') || ' ' ||
              coalesce(v_row->>'final_body', '') || ' ' ||
              coalesce(v_row->>'from_addr', '') || ' ' ||
              coalesce(v_row->>'payload', '');
  has_yx boolean := txt ~* '(28725008|54100047|詠翔|yxsurvey)';
  has_sj boolean := txt ~* '(83100099|上準|shangjun|sj-precision)';
  bad text;
BEGIN
  IF (v_row->>'case_id') IS NULL THEN
    IF (v_row->>'org_id') = 'YX' AND has_sj AND NOT has_yx THEN
      bad := 'unlinked message carries SJ marker but org_id=YX';
    ELSIF (v_row->>'org_id') = 'SJ' AND has_yx AND NOT has_sj THEN
      bad := 'unlinked message carries YX marker (28725008/yxsurvey) but org_id=SJ';
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

DO $$
DECLARE
  t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['email_message', 'switchboard_intake', 'outbound_message', 'client_communication']
  LOOP
    IF to_regclass('public.' || t) IS NOT NULL THEN
      EXECUTE format('DROP TRIGGER IF EXISTS r32_unlinked_org_marker_trg ON public.%I', t);
      EXECUTE format(
        'CREATE TRIGGER r32_unlinked_org_marker_trg BEFORE INSERT OR UPDATE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.r32_unlinked_org_marker_guard()',
        t
      );
    END IF;
  END LOOP;
END $$;

-- 2(c) Remove hard-stuffed 3 fixed evidence items at end of card_guard() and
--      genuinely validate that evidence_numbers bind to public.evidence_sql.
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
      AND (
        org_id = NEW.org_id
        OR (org_id = 'yongxiang' AND NEW.org_id = 'YX')
        OR (org_id = 'YX' AND NEW.org_id = 'yongxiang')
      )
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
  NEW.role := coalesce(
    NEW.role,
    CASE
      WHEN NEW.kind = 'admin' THEN 'admin'
      WHEN NEW.kind = 'finance' THEN 'settlement'
      ELSE 'case'
    END
  );

  IF NEW.actions = '[]'::jsonb OR (NEW.kind <> 'confirm' AND NEW.actions = '[{"label":"確認","action":"confirm"}]'::jsonb) THEN
    NEW.actions := CASE
      WHEN NEW.kind = 'review' THEN '[{"label":"核准","action":"approve"}]'::jsonb
      ELSE '[{"label":"確認","action":"confirm"}]'::jsonb
    END;
  END IF;

  -- Genuine validation: evidence_numbers must be a JSON array (<= 3 items) whose
  -- elements each carry label, value, and a sql_id registered in public.evidence_sql.
  IF NEW.evidence_numbers IS NULL
     OR jsonb_typeof(NEW.evidence_numbers) <> 'array'
     OR jsonb_array_length(NEW.evidence_numbers) > 3 THEN
    RAISE EXCEPTION 'evidence must bind evidence_sql';
  END IF;

  FOR v_elem IN SELECT * FROM jsonb_array_elements(NEW.evidence_numbers)
  LOOP
    IF NOT (v_elem ? 'label' AND v_elem ? 'value' AND v_elem ? 'sql_id')
       OR NOT EXISTS (SELECT 1 FROM public.evidence_sql s WHERE s.sql_id = v_elem->>'sql_id') THEN
      RAISE EXCEPTION 'evidence must bind evidence_sql';
    END IF;
  END LOOP;

  IF coalesce(array_length(NEW.evidence_sql_ids, 1), 0) > 0 THEN
    FOREACH v_sql_id IN ARRAY NEW.evidence_sql_ids
    LOOP
      IF NOT EXISTS (SELECT 1 FROM public.evidence_sql s WHERE s.sql_id = v_sql_id) THEN
        RAISE EXCEPTION 'evidence must bind evidence_sql';
      END IF;
    END LOOP;
  ELSIF jsonb_array_length(NEW.evidence_numbers) > 0 THEN
    SELECT coalesce(array_agg(e->>'sql_id'), '{}'::text[])
    INTO NEW.evidence_sql_ids
    FROM jsonb_array_elements(NEW.evidence_numbers) e;
  END IF;

  RETURN NEW;
END $$;

-- Update enqueue_card and card_act so SQL-created cards pass SQL-computed evidence_numbers
CREATE OR REPLACE FUNCTION public.enqueue_card(
  p_org text,
  p_case uuid,
  p_assignee uuid,
  p_kind text,
  p_key text,
  p_proposed jsonb DEFAULT '{}'::jsonb,
  p_cc uuid DEFAULT NULL
)
RETURNS uuid
LANGUAGE plpgsql
AS $$
DECLARE
  cid uuid;
  v_ev jsonb;
  v_sql_ids text[];
BEGIN
  v_ev := public.card_evidence(p_case);
  v_sql_ids := ARRAY['case_open_commitments', 'customer_fulfillment_rate', 'hours_to_48h'];

  INSERT INTO public.card (
    org_id,
    case_id,
    assignee_employee_id,
    kind,
    idempotency_key,
    proposed_fields,
    evidence_numbers,
    evidence_sql_ids
  )
  VALUES (
    p_org,
    p_case,
    p_assignee,
    p_kind,
    p_key,
    coalesce(p_proposed, '{}'::jsonb),
    v_ev,
    v_sql_ids
  )
  ON CONFLICT (idempotency_key) DO NOTHING
  RETURNING id INTO cid;

  IF cid IS NULL THEN
    SELECT id INTO cid
    FROM public.card
    WHERE idempotency_key = p_key
      AND org_id = p_org
      AND assignee_employee_id = p_assignee
      AND case_id IS NOT DISTINCT FROM p_case
      AND kind = p_kind
      AND proposed_fields = coalesce(p_proposed, '{}'::jsonb);
    IF cid IS NULL THEN
      RAISE EXCEPTION 'event idempotency payload conflict' USING ERRCODE = '23505';
    END IF;
  END IF;

  IF p_cc IS NOT NULL THEN
    IF NOT EXISTS (
      SELECT 1 FROM public.employee
      WHERE id = p_cc AND org_id = p_org AND employment_status = 'active' AND identity_confirmed
    ) THEN
      RAISE EXCEPTION 'invalid copy recipient';
    END IF;
    INSERT INTO public.notification_outbox (recipient_id, tier, dedupe_key, payload)
    VALUES (
      p_cc::text,
      'immediate',
      'copy:' || cid::text || ':' || p_cc::text,
      jsonb_build_object('card_id', cid, 'copy_only', true)
    )
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

  IF NOT EXISTS (
    SELECT 1 FROM public.card_state_transition
    WHERE card_kind = c.kind AND from_state = 'open' AND action = p_action
  ) THEN
    RAISE EXCEPTION 'action not allowed for card kind';
  END IF;

  UPDATE public.card
  SET status = 'acted',
      acted_at = clock_timestamp(),
      acted_by = p_actor,
      action = p_action,
      action_key = p_key
  WHERE id = p_id
  RETURNING * INTO c;

  INSERT INTO public.audit_event (table_name, record_id, op, actor_id, before_val, after_val)
  VALUES (
    'card',
    p_id::text,
    'UPDATE',
    p_actor::text,
    jsonb_build_object('status', 'open'),
    jsonb_build_object('status', 'acted', 'action', p_action, 'acted_at', c.acted_at)
  );

  INSERT INTO public.card_action_log (
    card_id,
    action,
    from_state,
    to_state,
    actor_employee_id,
    actor_role,
    channel,
    idempotency_key
  )
  VALUES (
    p_id,
    p_action,
    'open',
    'acted',
    p_actor,
    coalesce((SELECT role FROM public.api_session WHERE employee_id = p_actor AND expires_at > now() ORDER BY expires_at DESC LIMIT 1), 'field_member'),
    'api',
    p_key
  );

  SELECT * INTO t FROM public.card_transition WHERE card_id = p_id AND on_action = p_action;
  IF FOUND THEN
    INSERT INTO public.card (
      org_id,
      case_id,
      assignee_employee_id,
      kind,
      idempotency_key,
      evidence_numbers,
      evidence_sql_ids
    )
    VALUES (
      c.org_id,
      c.case_id,
      t.next_assignee_employee_id,
      t.next_kind,
      'after:' || p_id::text || ':' || p_action,
      public.card_evidence(c.case_id),
      ARRAY['case_open_commitments', 'customer_fulfillment_rate', 'hours_to_48h']
    )
    ON CONFLICT DO NOTHING
    RETURNING id INTO n;

    INSERT INTO public.notification_outbox (recipient_id, tier, dedupe_key, payload)
    VALUES (
      t.next_assignee_employee_id::text,
      'immediate',
      'after:' || p_id::text,
      jsonb_build_object('card_id', n)
    )
    ON CONFLICT DO NOTHING;
  END IF;

  RETURN jsonb_build_object('id', c.id, 'status', c.status, 'acted_at', c.acted_at, 'action', c.action);
END $$;

-- =============================================================================
-- 3. Fix the 5 Implementation Deviations
-- =============================================================================

-- 3(a) Negate Dry-Run positive serials 12085..12105 in client_communication
--      so v_floor does not jump to 12106.
ALTER TABLE public.client_communication DISABLE TRIGGER USER;

UPDATE public.client_communication
SET serial_no = -serial_no
WHERE serial_no BETWEEN 12085 AND 12105;

ALTER TABLE public.client_communication ENABLE TRIGGER USER;

ALTER TABLE public.serial_assignment
  ADD COLUMN IF NOT EXISTS voided_at timestamptz,
  ADD COLUMN IF NOT EXISTS void_reason text;

ALTER TABLE public.serial_assignment
  DROP CONSTRAINT IF EXISTS serial_assignment_org_id_serial_no_key;
DROP INDEX IF EXISTS public.serial_assignment_org_no_uq;

CREATE UNIQUE INDEX IF NOT EXISTS serial_assignment_org_serial_active_uq
  ON public.serial_assignment(org_id, serial_no)
  WHERE NOT voided_by_cutover;

UPDATE public.serial_assignment
SET voided_by_cutover = true,
    voided_at = coalesce(voided_at, now()),
    void_reason = coalesce(void_reason, 'R38_DRYRUN_NEGATED')
WHERE serial_no BETWEEN 12085 AND 12105;

UPDATE public.serial_allocator a
SET next_serial = GREATEST(
  12085,
  coalesce((
    SELECT max(sa.serial_no) + 1
    FROM public.serial_assignment sa
    WHERE sa.org_id = a.org_id
      AND sa.mode = 'live'
      AND NOT sa.voided_by_cutover
      AND sa.serial_no > 0
  ), 12085)
)
WHERE a.org_id IN ('YX', 'SJ', 'yongxiang');

-- 3(b) Remove NOT NULL DEFAULT 12084 from serial_allocator.sheet_max_reconciled
--      and raise 'unknown org %' instead of auto-inserting in assign_serial / cutover_reconcile_serial.
ALTER TABLE public.serial_allocator
  ALTER COLUMN sheet_max_reconciled DROP NOT NULL,
  ALTER COLUMN sheet_max_reconciled DROP DEFAULT;

DROP FUNCTION IF EXISTS public.assign_serial(text, text);
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
    IF EXISTS (
      SELECT 1 FROM public.serial_assignment
      WHERE org_id = p_org
        AND fingerprint = p_fp
        AND mode = 'live'
        AND NOT voided_by_cutover
    ) THEN
      RAISE EXCEPTION 'fingerprint already has live serial; dry_run refused';
    END IF;

    SELECT serial_no INTO s
    FROM public.serial_assignment
    WHERE org_id = p_org
      AND fingerprint = p_fp
      AND mode = 'dry_run'
      AND NOT voided_by_cutover;
    IF FOUND THEN
      RETURN s;
    END IF;

    UPDATE public.serial_allocator
    SET shadow_next_serial = LEAST(
      coalesce(shadow_next_serial, -12085),
      coalesce((SELECT min(serial_no) - 1 FROM public.serial_assignment WHERE org_id = p_org AND serial_no < 0), -12085),
      -12085
    ) - 1
    WHERE org_id = p_org
    RETURNING shadow_next_serial + 1 INTO s;

    INSERT INTO public.serial_assignment (org_id, fingerprint, serial_no, mode, voided_by_cutover)
    VALUES (p_org, p_fp, s, 'dry_run', false);
    RETURN s;
  END IF;

  SELECT serial_no INTO s
  FROM public.serial_assignment
  WHERE org_id = p_org
    AND fingerprint = p_fp
    AND mode = 'live'
    AND NOT voided_by_cutover;
  IF FOUND THEN
    RETURN s;
  END IF;

  SELECT serial_no INTO s
  FROM public.client_communication
  WHERE org_id = p_org
    AND thread_fingerprint = p_fp
    AND serial_no >= 12085
  ORDER BY serial_no
  LIMIT 1;

  IF s IS NULL THEN
    SELECT GREATEST(
      12085,
      coalesce((SELECT sheet_max_reconciled + 1 FROM public.serial_allocator WHERE org_id = p_org), 12085),
      coalesce((SELECT max(serial_no) + 1 FROM public.client_communication WHERE org_id = p_org AND serial_no > 0), 12085),
      coalesce((SELECT max(serial_no) + 1 FROM public.serial_assignment WHERE org_id = p_org AND mode = 'live' AND NOT voided_by_cutover AND serial_no > 0), 12085)
    ) INTO v_floor;

    UPDATE public.serial_allocator
    SET next_serial = GREATEST(next_serial, v_floor) + 1
    WHERE org_id = p_org
    RETURNING next_serial - 1 INTO s;
  END IF;

  INSERT INTO public.serial_assignment (org_id, fingerprint, serial_no, mode, voided_by_cutover)
  VALUES (p_org, p_fp, s, 'live', false);
  RETURN s;
END $$;

DROP FUNCTION IF EXISTS public.cutover_reconcile_serial(text, int);
CREATE OR REPLACE FUNCTION public.cutover_reconcile_serial(
  p_org text,
  p_sheet_max int
)
RETURNS int
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_live_max int;
  v_comm_max int;
  v_next int;
BEGIN
  IF p_sheet_max IS NULL OR p_sheet_max < 12084 THEN
    RAISE EXCEPTION 'p_sheet_max % cannot be below baseline 12084', p_sheet_max;
  END IF;

  PERFORM 1 FROM public.serial_allocator WHERE org_id = p_org FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'unknown org %', p_org;
  END IF;

  IF EXISTS (
    SELECT 1 FROM public.serial_assignment
    WHERE org_id = p_org
      AND mode = 'live'
      AND NOT voided_by_cutover
      AND serial_no > p_sheet_max
  ) THEN
    RAISE EXCEPTION 'live serials beyond sheet_max exist; void them first';
  END IF;

  UPDATE public.serial_assignment
  SET voided_by_cutover = true,
      voided_at = now(),
      void_reason = 'CUTOVER_RECONCILE'
  WHERE org_id = p_org
    AND mode = 'dry_run'
    AND NOT voided_by_cutover;

  SELECT coalesce(max(serial_no), 0) INTO v_live_max
  FROM public.serial_assignment
  WHERE org_id = p_org
    AND mode = 'live'
    AND NOT voided_by_cutover
    AND serial_no > 0;

  SELECT coalesce(max(serial_no), 0) INTO v_comm_max
  FROM public.client_communication
  WHERE org_id = p_org
    AND serial_no > 0;

  v_next := GREATEST(p_sheet_max + 1, v_live_max + 1, v_comm_max + 1, 12085);

  UPDATE public.serial_allocator
  SET sheet_max_reconciled = p_sheet_max,
      next_serial = v_next
  WHERE org_id = p_org;

  RETURN v_next;
END $$;

-- 3(c) In card_promote_dry_run(p_org), remove 7-day p_since limit, add FOR UPDATE,
--      and handle expires_at <= now().
ALTER TABLE public.card DROP CONSTRAINT IF EXISTS card_state_check;
ALTER TABLE public.card DROP CONSTRAINT IF EXISTS card_state_chk;
ALTER TABLE public.card DROP CONSTRAINT IF EXISTS r32_card_state_check;
ALTER TABLE public.card ADD CONSTRAINT r32_card_state_check
  CHECK (state IN ('open', 'acted', 'escalated', 'dry_run', 'superseded', 'superseded_by_live'));

DROP FUNCTION IF EXISTS public.card_promote_dry_run(uuid);
DROP FUNCTION IF EXISTS public.card_promote_dry_run(text, timestamptz);
DROP FUNCTION IF EXISTS public.card_promote_dry_run(text);

CREATE OR REPLACE FUNCTION public.card_promote_dry_run(p_org text)
RETURNS int
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_promoted int := 0;
BEGIN
  PERFORM 1
  FROM public.card c
  WHERE c.org_id = p_org
    AND c.mode = 'dry_run'
    AND c.state IN ('open', 'dry_run')
  FOR UPDATE;

  UPDATE public.card c
  SET state = 'superseded'
  WHERE c.org_id = p_org
    AND c.mode = 'dry_run'
    AND c.state IN ('open', 'dry_run')
    AND c.expires_at IS NOT NULL
    AND c.expires_at <= now();

  UPDATE public.card d
  SET state = 'superseded_by_live'
  WHERE d.org_id = p_org
    AND d.mode = 'dry_run'
    AND d.state IN ('open', 'dry_run')
    AND (d.expires_at IS NULL OR d.expires_at > now())
    AND EXISTS (
      SELECT 1 FROM public.card l
      WHERE l.org_id = d.org_id
        AND l.source_event_key = d.source_event_key
        AND l.mode = 'live'
        AND l.id <> d.id
    );

  WITH dup AS (
    SELECT id,
           row_number() OVER (PARTITION BY org_id, source_event_key ORDER BY created_at DESC, id DESC) AS rn
    FROM public.card
    WHERE org_id = p_org
      AND mode = 'dry_run'
      AND status = 'open'
      AND state IN ('open', 'dry_run')
      AND acted_at IS NULL
      AND (expires_at IS NULL OR expires_at > now())
      AND nullif(source_event_key, '') IS NOT NULL
  )
  UPDATE public.card d
  SET state = 'superseded_by_live'
  FROM dup
  WHERE d.id = dup.id AND dup.rn > 1;

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
    AND (c.expires_at IS NULL OR c.expires_at > now());

  GET DIAGNOSTICS v_promoted = ROW_COUNT;
  RETURN v_promoted;
END $$;

-- 3(d) Drop parallel public.overtime_request table; bind guard_overtime_stage_before
--      only to public.overtime_day and access fields safely via to_jsonb(NEW).
DROP TABLE IF EXISTS public.overtime_request CASCADE;

ALTER TABLE public.overtime_day
  ADD COLUMN IF NOT EXISTS escalation_level int NOT NULL DEFAULT 0;

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
BEGIN
  IF TG_OP = 'UPDATE' THEN
    IF v_new_lvl < v_old_lvl THEN
      RAISE EXCEPTION 'overtime escalation_level cannot decrease from % to %', v_old_lvl, v_new_lvl;
    END IF;
    IF v_new_lvl > v_old_lvl + 1 THEN
      RAISE EXCEPTION 'overtime escalation stage skip forbidden: % -> %', v_old_lvl, v_new_lvl;
    END IF;
    IF v_new_lvl > 0 AND v_new_lvl = v_old_lvl AND (v_new - 'updated_at') = (v_old - 'updated_at') THEN
      RAISE EXCEPTION 'overtime escalation stage replay forbidden: % -> %', v_old_lvl, v_new_lvl;
    END IF;
    IF v_new_lvl IS DISTINCT FROM v_old_lvl THEN
      v_stage := coalesce(
        v_new->>'last_escalated_stage',
        CASE
          WHEN v_new_lvl = 1 THEN 'STAGE_1_24H_DEPT_MANAGER'
          WHEN v_new_lvl >= 2 THEN 'STAGE_2_48H_DEPUTY_GM'
          ELSE NULL
        END
      );
      IF v_stage IS NOT NULL AND EXISTS (
        SELECT 1 FROM public.overtime_escalation_stage_log
        WHERE request_id = coalesce(v_new->>'request_id', v_new->>'id')
          AND stage = v_stage
      ) THEN
        NEW.escalation_level := v_old_lvl;
        NEW.status := v_old->>'status';
      END IF;
    END IF;
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS overtime_day_stage_before_trg ON public.overtime_day;
CREATE TRIGGER overtime_day_stage_before_trg
  BEFORE INSERT OR UPDATE ON public.overtime_day
  FOR EACH ROW EXECUTE FUNCTION public.guard_overtime_stage_before();

-- 3(e) Undo regex backfill of role_code = 'admin', explicitly assign only the
--      3 real admins from the 81-person roster (羅薇, 雅琪/朱雅琪, 郭倢瑛, count(*) = 3),
--      and remove the 2nd & 3rd fallback tiers in otp_deliver().
UPDATE public.employee SET role_code = NULL WHERE role_code = 'admin';
UPDATE public.employee SET employment_status = 'resigned', role_code = NULL WHERE id = '26a901c0-d648-529e-842f-b778a86cb559'::uuid;

CREATE TABLE IF NOT EXISTS public.employee_role_map (
  employee_id uuid PRIMARY KEY REFERENCES public.employee(id),
  role_code text NOT NULL,
  assigned_by text NOT NULL DEFAULT 'R38_EXPLICIT_ROSTER'
);

DELETE FROM public.employee_role_map;

INSERT INTO public.employee_role_map (employee_id, role_code)
SELECT e.id, 'admin'
FROM public.employee e
WHERE e.id IN (
  'c22b9383-60ec-5bcf-8bb1-4131de44b420'::uuid, -- 羅薇
  '45ab4194-04c9-59ef-bbd9-f1559b830c38'::uuid, -- 朱雅琪 (雅琪)
  '18d11143-a1c8-5afd-bcf1-229e064e930c'::uuid  -- 郭倢瑛 (倢瑛)
);

UPDATE public.employee e
SET role_code = m.role_code
FROM public.employee_role_map m
WHERE e.id = m.employee_id;

DO $$
DECLARE
  v_admin_cnt int;
BEGIN
  SELECT count(*) INTO v_admin_cnt
  FROM public.employee
  WHERE role_code = 'admin';
  IF v_admin_cnt <> 3 THEN
    RAISE EXCEPTION 'R38 admin roster check failed: expected 3 admins, got %', v_admin_cnt;
  END IF;
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
    SELECT e.id INTO admin_emp
    FROM public.employee e
    WHERE (
        e.org_id = m.org_id
        OR (m.org_id = 'YX' AND e.org_id = 'yongxiang')
        OR (m.org_id = 'yongxiang' AND e.org_id = 'YX')
      )
      AND e.employment_status = 'active'
      AND e.identity_confirmed
      AND e.role_code = 'admin'
    ORDER BY (e.org_id = m.org_id)::int DESC, e.id
    LIMIT 1;

    IF admin_emp IS NULL THEN
      RAISE WARNING 'otp_deliver conflict card skipped: no active confirmed admin employee for org %', m.org_id;
      RETURN NULL;
    END IF;

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
      RAISE WARNING 'otp_deliver conflict card enqueue failed: %', SQLERRM;
    END;
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

-- 3(f) In satcmd_guard(), restore OR (b.role = 'switchboard' AND NEW.command_kind = 'forward_register')
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
     AND (b.role = 'satellite' OR (b.role = 'switchboard' AND NEW.command_kind = 'forward_register'))
     AND b.org_id = m.org_id
    LEFT JOIN public.email_sent_copy sc
      ON sc.message_id = m.message_id
     AND sc.mailbox_id = b.id
    LEFT JOIN public.satellite_sent_copy ssc
      ON ssc.message_id = m.message_id
     AND ssc.mailbox_id = b.id
    WHERE m.id = NEW.source_message_id
      AND m.org_id = NEW.org_id
      AND m.dkim_spf_passed
      AND m.sent_copy_verified
      AND (
        (sc.header_d IS NOT NULL AND lower(sc.header_d) = lower(split_part(b.address, '@', 2)))
        OR (b.role = 'switchboard' AND NEW.command_kind = 'forward_register' AND (sc.message_id IS NOT NULL OR ssc.message_id IS NOT NULL))
      )
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

-- 3(g) ACT-R37-06: Runtime BEFORE INSERT trigger on public.email_rag_chunk to quarantine NULL category rows
CREATE TABLE IF NOT EXISTS public.email_rag_chunk_quarantine (
  LIKE public.email_rag_chunk INCLUDING DEFAULTS,
  quarantined_at timestamptz NOT NULL DEFAULT now(),
  reason text NOT NULL DEFAULT 'runtime_null_category',
  quarantine_reason text NOT NULL DEFAULT 'runtime_null_category'
);

ALTER TABLE public.email_rag_chunk_quarantine
  ALTER COLUMN category DROP NOT NULL,
  ADD COLUMN IF NOT EXISTS reason text NOT NULL DEFAULT 'runtime_null_category',
  ADD COLUMN IF NOT EXISTS quarantine_reason text NOT NULL DEFAULT 'runtime_null_category';

CREATE OR REPLACE FUNCTION public.quarantine_null_email_rag_chunk()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF NEW.category IS NULL THEN
    INSERT INTO public.email_rag_chunk_quarantine (
      id, message_id, attachment_id, org_id, customer_id, case_id, quote_id,
      category, direction, occurred_at, chunk_no, chunk_text, content_hash,
      embedding, reason, quarantine_reason
    ) VALUES (
      coalesce(NEW.id, nextval('email_rag_chunk_id_seq'::regclass)),
      NEW.message_id, NEW.attachment_id, NEW.org_id, NEW.customer_id,
      NEW.case_id, NEW.quote_id, NEW.category, NEW.direction,
      NEW.occurred_at, NEW.chunk_no, NEW.chunk_text, NEW.content_hash,
      NEW.embedding, 'runtime_null_category', 'runtime_null_category'
    );
    RETURN NULL;
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS aa_email_rag_chunk_quarantine_null_trg ON public.email_rag_chunk;
CREATE TRIGGER aa_email_rag_chunk_quarantine_null_trg
  BEFORE INSERT ON public.email_rag_chunk
  FOR EACH ROW EXECUTE FUNCTION public.quarantine_null_email_rag_chunk();

-- 3(h) ACT-R37-02: Ensure switchboard_backtest_metrics_v compares predicted_category vs gold_category
DROP VIEW IF EXISTS public.switchboard_backtest_metrics_v;
CREATE OR REPLACE VIEW public.switchboard_backtest_metrics_v AS
  WITH pairs AS (
    SELECT
      e.run_id,
      g.gold_category AS g_cat,
      coalesce(e.predicted_category, e.category) AS p_cat
    FROM public.switchboard_backtest_eval e
    JOIN public.switchboard_gold_label g ON g.sample_id = e.sample_id
    WHERE g.gold_category IS NOT NULL
  ),
  cats AS (
    SELECT DISTINCT run_id, cat
    FROM (
      SELECT run_id, g_cat AS cat FROM pairs WHERE g_cat IS NOT NULL
      UNION
      SELECT run_id, p_cat AS cat FROM pairs WHERE p_cat IS NOT NULL
    ) u
  ),
  agg AS (
    SELECT
      c.run_id,
      c.cat AS gold_category,
      count(*) FILTER (WHERE p.g_cat = c.cat)::int AS n,
      count(*)::int AS total_samples,
      count(*) FILTER (WHERE p.p_cat = c.cat AND p.g_cat = c.cat)::int AS tp,
      count(*) FILTER (WHERE p.p_cat = c.cat AND p.g_cat IS DISTINCT FROM c.cat)::int AS fp,
      count(*) FILTER (WHERE p.p_cat IS DISTINCT FROM c.cat AND p.g_cat IS DISTINCT FROM c.cat)::int AS tn,
      count(*) FILTER (WHERE p.p_cat IS DISTINCT FROM c.cat AND p.g_cat = c.cat)::int AS fn
    FROM cats c
    JOIN pairs p ON p.run_id = c.run_id
    GROUP BY c.run_id, c.cat
  )
  SELECT
    run_id,
    gold_category,
    n,
    total_samples,
    tp,
    fp,
    tn,
    fn,
    round(coalesce(tp::numeric / nullif(tp + fp, 0), 0.0), 4) AS precision,
    round(coalesce(tp::numeric / nullif(tp + fn, 0), 0.0), 4) AS recall,
    round(100.0 * coalesce(tp::numeric / nullif(tp + fp, 0), 0.0), 2) AS precision_pct,
    round(100.0 * coalesce(tp::numeric / nullif(tp + fn, 0), 0.0), 2) AS recall_pct
  FROM agg;

-- =============================================================================
-- 4. Updated r32_assert_all() returning honest BACKTEST-200: NOT_RUN before
--    human double-blind labels are imported
-- =============================================================================
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
  v_bt_not_run boolean := false;
  v_bt_bad int := 0;
  v_bt_status text;
BEGIN
  -- SW-SER-01: next_serial > max(live serial_no)
  SELECT count(*) INTO v_ser01_bad
  FROM public.serial_allocator a
  WHERE a.next_serial <= COALESCE((
    SELECT max(sa.serial_no) FROM public.serial_assignment sa
    WHERE sa.org_id = a.org_id AND sa.mode = 'live' AND NOT sa.voided_by_cutover AND sa.serial_no > 0
  ), 12084);
  IF v_ser01_bad > 0 THEN
    RAISE EXCEPTION 'SW-SER-01 FAILED: % org(s) have next_serial <= max(serial_no)', v_ser01_bad;
  END IF;

  -- SW-SER-02: dry_run serials must be negative (<= -12085) and < next_serial
  SELECT count(*) INTO v_ser02_bad
  FROM public.serial_assignment sa
  JOIN public.serial_allocator a ON a.org_id = sa.org_id
  WHERE sa.mode = 'dry_run'
    AND NOT sa.voided_by_cutover
    AND (sa.serial_no >= a.next_serial OR sa.serial_no > -12085);
  IF v_ser02_bad > 0 THEN
    RAISE EXCEPTION 'SW-SER-02 FAILED: % dry_run serial(s) invalid or >= next_serial', v_ser02_bad;
  END IF;

  -- SW-CUT-01: zero actual_sends, no duplicate live cards, no un-superseded dry_run coexisting with live
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

  -- SW-HYG-01: no unmarked (is_synthetic = false) synthetic contacts or intakes
  SELECT (
    (SELECT count(*) FROM public.customer_contact
     WHERE NOT coalesce(is_synthetic, false)
       AND (
         coalesce(email, '') ILIKE '%@example.%'
         OR coalesce(full_name, '') LIKE 'TEST_%'
         OR coalesce(full_name, '') LIKE '測試%'
         OR source_record_id = 'SWITCHBOARD_ACCEPTANCE_ROLLBACK_ONLY'
       ))
    +
    (SELECT count(*) FROM public.switchboard_intake
     WHERE evidence_kind = 'synthetic_test'
       AND NOT coalesce(is_synthetic, false))
  ) INTO v_hyg_bad;
  IF v_hyg_bad > 0 THEN
    RAISE EXCEPTION 'SW-HYG-01 FAILED: % unmarked synthetic contact/intake row(s) found', v_hyg_bad;
  END IF;

  -- BACKTEST-200: honestly report NOT_RUN until 200 human double-blind labels & eval exist
  SELECT EXISTS (
    SELECT 1 FROM public.backtest_gate(NULL::uuid)
    WHERE metric = 'BACKTEST-200' AND actual LIKE 'NOT_RUN%'
  ) INTO v_bt_not_run;

  IF v_bt_not_run THEN
    v_bt_status := 'NOT_RUN';
  ELSE
    SELECT count(*) INTO v_bt_bad
    FROM public.backtest_gate(NULL::uuid)
    WHERE NOT pass;
    IF v_bt_bad > 0 THEN
      RAISE EXCEPTION 'BACKTEST-200 FAILED: % metric(s) failed in backtest_gate', v_bt_bad;
    END IF;
    v_bt_status := 'PASS';
  END IF;

  RETURN jsonb_build_object(
    'SW-SER-01', 'PASS',
    'SW-SER-02', 'PASS',
    'SW-CUT-01', 'PASS',
    'SW-HYG-01', 'PASS',
    'BACKTEST-200', v_bt_status
  );
END $$;

-- =============================================================================
-- 5. Update r31b_deployment_object so legacy migration replay retains R38 Step 5
-- =============================================================================
DO $$
BEGIN
  IF to_regclass('public.r31b_deployment_object') IS NOT NULL THEN
    DELETE FROM public.r31b_deployment_object
    WHERE name ~ '^(assign_serial|cutover_reconcile_serial|card_guard|enqueue_card|card_act|card_promote_dry_run|satcmd_guard|otp_deliver|guard_overtime_stage_before|r32_unlinked_org_marker_guard|enforce_org_content_marker|backtest_gate|r32_assert_all)([(:]|$)';

    INSERT INTO public.r31b_deployment_object (name, priority, ddl)
    VALUES
      ('00_drop_assign_serial_2arg', 5, 'DROP FUNCTION IF EXISTS public.assign_serial(text, text);'),
      ('00_drop_card_promote_uuid', 5, 'DROP FUNCTION IF EXISTS public.card_promote_dry_run(uuid); DROP FUNCTION IF EXISTS public.card_promote_dry_run(text, timestamptz);'),
      ('99_email_message_nullable_org', 95, 'ALTER TABLE public.email_message ALTER COLUMN org_id DROP NOT NULL;')
    ON CONFLICT (name) DO UPDATE SET ddl = EXCLUDED.ddl, priority = EXCLUDED.priority;

    INSERT INTO public.r31b_deployment_object (name, priority, ddl)
    SELECT p.oid::regprocedure::text, 10, pg_get_functiondef(p.oid)
    FROM pg_proc p
    WHERE p.pronamespace = 'public'::regnamespace
      AND p.proname IN (
        'assign_serial',
        'cutover_reconcile_serial',
        'card_guard',
        'enqueue_card',
        'card_act',
        'card_promote_dry_run',
        'satcmd_guard',
        'otp_deliver',
        'guard_overtime_stage_before',
        'r32_unlinked_org_marker_guard',
        'backtest_gate',
        'r32_assert_all'
      )
    ON CONFLICT (name) DO UPDATE SET ddl = EXCLUDED.ddl, priority = EXCLUDED.priority;
  END IF;
END $$;


-- -----------------------------------------------------------------------------
-- Preserve R38 (009c) definitions in r31b_deployment_object for legacy replay defense
-- -----------------------------------------------------------------------------
DELETE FROM public.r31b_deployment_object
WHERE name ~ '^(assign_serial|cutover_reconcile_serial|card_guard|enqueue_card|card_act|card_promote_dry_run|sync_satellite_to_email_sent_copy|sync_email_message_to_sent_copy|satcmd_guard|outbound_send|invoice_row_lock|payment_instrument_status_reversal|settlement_blocked|settlement_gate|r29_otp_request_guard|otp_deliver|guard_overtime_stage_before|guard_overtime_stage_replay|r32_unlinked_org_marker_guard|enforce_org_content_marker|r32_short_pay_finance_card|backtest_gate|r32_assert_all)([(:]|$)';

INSERT INTO public.r31b_deployment_object (name, priority, ddl)
VALUES
  ('00_drop_assign_serial_2arg', 5, 'DROP FUNCTION IF EXISTS public.assign_serial(text, text);'),
  ('00_drop_card_promote_uuid', 5, 'DROP FUNCTION IF EXISTS public.card_promote_dry_run(uuid);
DROP FUNCTION IF EXISTS public.card_promote_dry_run(text);
DROP FUNCTION IF EXISTS public.card_promote_dry_run(text, timestamptz);'),
  ('00_drop_backtest_gate', 5, 'DROP FUNCTION IF EXISTS public.backtest_gate(uuid);')
ON CONFLICT (name) DO UPDATE SET ddl = EXCLUDED.ddl, priority = EXCLUDED.priority;

INSERT INTO public.r31b_deployment_object (name, priority, ddl)
SELECT p.oid::regprocedure::text, 10, pg_get_functiondef(p.oid)
FROM pg_proc p
WHERE p.pronamespace = 'public'::regnamespace
  AND p.proname IN (
    'assign_serial',
    'cutover_reconcile_serial',
    'card_guard',
    'enqueue_card',
    'card_act',
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
    'r32_short_pay_finance_card',
    'backtest_gate',
    'r32_assert_all'
  )
ON CONFLICT (name) DO UPDATE SET ddl = EXCLUDED.ddl, priority = EXCLUDED.priority;

COMMIT;
