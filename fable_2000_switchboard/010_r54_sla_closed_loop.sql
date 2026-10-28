-- =====================================================================
-- R54 · 7-stage zero-drop state machine + two-stage SLA closed-loop
-- Target DB: yongxiang_plumb_r39_clone ONLY (guarded at top).
-- Re-runnable (idempotent). No external side effects — pure data model.
-- =====================================================================
DO $guard$
BEGIN
  ASSERT current_database() <> 'yongxiang_plumb',
    'FATAL: R54 migration forbidden on production yongxiang_plumb';
  ASSERT current_database() = 'yongxiang_plumb_r39_clone',
    format('FATAL: R54 migration only runs on the clone (got %s)', current_database());
END
$guard$;

-- ---------------------------------------------------------------------
-- 1. The 7 canonical stages (zero-drop: a case can only advance through
--    adjacent allowed transitions, never skip / silently fall off).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.r54_loop_stage (
  stage        text PRIMARY KEY,
  ordinal      int  NOT NULL,
  is_terminal  boolean NOT NULL DEFAULT false,
  label_zh     text NOT NULL
);

INSERT INTO public.r54_loop_stage(stage, ordinal, is_terminal, label_zh) VALUES
  ('RECEIVED',  1, false, '來信進線（未認領）'),
  ('DRAFTED',   2, false, 'AI 草稿已備妥（待確認）'),
  ('CLAIMED',   3, false, '已認領處理中'),
  ('APPROVED',  4, false, '已核准（待寄出）'),
  ('SENT',      5, false, '已寄出（沙盒）'),
  ('ARCHIVED',  6, false, '已歸檔業主往來紀錄'),
  ('CLOSED',    7, true,  '結案'),
  ('SNOOZED',   0, false, '合法擱置中'),
  ('DECLINED',  0, true,  '婉拒 / 不承接')
ON CONFLICT (stage) DO UPDATE
  SET ordinal = EXCLUDED.ordinal, is_terminal = EXCLUDED.is_terminal, label_zh = EXCLUDED.label_zh;

-- Allowed transitions. Anything not listed here is REJECTED (zero-drop).
CREATE TABLE IF NOT EXISTS public.r54_loop_transition (
  from_state text NOT NULL REFERENCES public.r54_loop_stage(stage),
  action     text NOT NULL,
  to_state   text NOT NULL REFERENCES public.r54_loop_stage(stage),
  PRIMARY KEY (from_state, action)
);

INSERT INTO public.r54_loop_transition(from_state, action, to_state) VALUES
  ('RECEIVED', 'draft',     'DRAFTED'),
  ('RECEIVED', 'claim',     'CLAIMED'),     -- a human may grab it before AI drafts
  ('DRAFTED',  'claim',     'CLAIMED'),
  ('DRAFTED',  'approve',   'APPROVED'),    -- fast-path: approve the AI draft as-is
  ('DRAFTED',  'decline',   'DECLINED'),
  ('CLAIMED',  'approve',   'APPROVED'),
  ('CLAIMED',  'decline',   'DECLINED'),
  ('CLAIMED',  'snooze',    'SNOOZED'),
  ('DRAFTED',  'snooze',    'SNOOZED'),
  ('RECEIVED', 'snooze',    'SNOOZED'),
  ('SNOOZED',  'resume',    'CLAIMED'),     -- resume lands back in the actionable lane
  ('SNOOZED',  'resume_received', 'RECEIVED'),
  ('APPROVED', 'send',      'SENT'),
  ('SENT',     'archive',   'ARCHIVED'),
  ('ARCHIVED', 'close',     'CLOSED')
ON CONFLICT (from_state, action) DO UPDATE SET to_state = EXCLUDED.to_state;

-- ---------------------------------------------------------------------
-- 2. Per-case loop tracker. One row per client-letter case in the loop.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.r54_case_loop (
  case_code      text PRIMARY KEY,
  case_id        uuid,
  stage          text NOT NULL DEFAULT 'RECEIVED' REFERENCES public.r54_loop_stage(stage),
  received_at    timestamptz NOT NULL DEFAULT clock_timestamp(),
  drafted_at     timestamptz,
  claimed_at     timestamptz,
  claimed_by     uuid,              -- public.employee.id
  approved_at    timestamptz,
  sent_at        timestamptz,
  archived_at    timestamptz,
  closed_at      timestamptz,
  snooze_until   timestamptz,       -- legitimate hold; SLA clock paused until this
  snooze_reason  text,
  pre_snooze_stage text,
  created_at     timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at     timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- Full audit trail of every transition (who / when / from→to).
CREATE TABLE IF NOT EXISTS public.r54_loop_event (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  case_code  text NOT NULL,
  from_state text,
  action     text NOT NULL,
  to_state   text NOT NULL,
  actor_id   uuid,
  note       text,
  at         timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- ---------------------------------------------------------------------
-- 3. SLA policy (two-stage), tunable in one place.
--    Stage A — unclaimed  : warn T+2h, escalate T+4h (from received_at)
--    Stage B — claimed/unsent: warn T+24h, escalate T+24h+4h (from claimed_at)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.r54_sla_policy (
  id                     int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  stage_a_warn           interval NOT NULL DEFAULT interval '2 hours',
  stage_a_escalate       interval NOT NULL DEFAULT interval '4 hours',
  stage_b_warn           interval NOT NULL DEFAULT interval '24 hours',
  stage_b_escalate_after interval NOT NULL DEFAULT interval '4 hours',
  business_only          boolean NOT NULL DEFAULT false
);
INSERT INTO public.r54_sla_policy(id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------------
-- 4. Zero-drop transition function. Rejects any illegal jump, stamps the
--    right timestamp column, records an audit event. Returns new stage.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.r54_apply_transition(
  p_case_code text,
  p_action    text,
  p_actor_id  uuid DEFAULT NULL,
  p_at        timestamptz DEFAULT NULL,
  p_snooze_until timestamptz DEFAULT NULL,
  p_note      text DEFAULT NULL
) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE
  v_from text;
  v_to   text;
  v_at   timestamptz := COALESCE(p_at, clock_timestamp());
BEGIN
  SELECT stage INTO v_from FROM public.r54_case_loop WHERE case_code = p_case_code FOR UPDATE;
  IF v_from IS NULL THEN
    RAISE EXCEPTION 'R54_UNKNOWN_CASE: % is not in the loop', p_case_code;
  END IF;

  SELECT to_state INTO v_to FROM public.r54_loop_transition
   WHERE from_state = v_from AND action = p_action;
  IF v_to IS NULL THEN
    RAISE EXCEPTION 'R54_ILLEGAL_TRANSITION: cannot % from % (case %)', p_action, v_from, p_case_code;
  END IF;

  UPDATE public.r54_case_loop SET
    stage         = v_to,
    drafted_at    = CASE WHEN v_to='DRAFTED'  AND drafted_at  IS NULL THEN v_at ELSE drafted_at  END,
    claimed_at    = CASE WHEN v_to='CLAIMED'  AND claimed_at  IS NULL THEN v_at ELSE claimed_at  END,
    claimed_by    = CASE WHEN v_to='CLAIMED'  THEN COALESCE(p_actor_id, claimed_by) ELSE claimed_by END,
    approved_at   = CASE WHEN v_to='APPROVED' THEN v_at ELSE approved_at END,
    sent_at       = CASE WHEN v_to='SENT'     THEN v_at ELSE sent_at     END,
    archived_at   = CASE WHEN v_to='ARCHIVED' THEN v_at ELSE archived_at END,
    closed_at     = CASE WHEN v_to='CLOSED'   THEN v_at ELSE closed_at   END,
    pre_snooze_stage = CASE WHEN v_to='SNOOZED' THEN v_from ELSE pre_snooze_stage END,
    snooze_until  = CASE WHEN v_to='SNOOZED' THEN p_snooze_until
                         WHEN p_action IN ('resume','resume_received') THEN NULL
                         ELSE snooze_until END,
    snooze_reason = CASE WHEN v_to='SNOOZED' THEN p_note
                         WHEN p_action IN ('resume','resume_received') THEN NULL
                         ELSE snooze_reason END,
    updated_at    = v_at
  WHERE case_code = p_case_code;

  INSERT INTO public.r54_loop_event(case_code, from_state, action, to_state, actor_id, note, at)
  VALUES (p_case_code, v_from, p_action, v_to, p_actor_id, p_note, v_at);

  RETURN v_to;
END
$$;

-- Helper to enrol a case into the loop (idempotent).
CREATE OR REPLACE FUNCTION public.r54_enroll_case(
  p_case_code text, p_case_id uuid DEFAULT NULL, p_received_at timestamptz DEFAULT NULL
) RETURNS void LANGUAGE sql AS $$
  INSERT INTO public.r54_case_loop(case_code, case_id, received_at, created_at, updated_at)
  VALUES (p_case_code, p_case_id, COALESCE(p_received_at, clock_timestamp()),
          COALESCE(p_received_at, clock_timestamp()), COALESCE(p_received_at, clock_timestamp()))
  ON CONFLICT (case_code) DO NOTHING;
$$;

-- ---------------------------------------------------------------------
-- 5. SLA radar view — two-stage logic + legitimate-snooze pause.
--    Call public.r54_sla_radar(as_of) to evaluate at any instant.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.r54_sla_radar(p_as_of timestamptz DEFAULT clock_timestamp())
RETURNS TABLE (
  case_code     text,
  stage         text,
  sla_track     text,     -- 'A_UNCLAIMED' | 'B_UNSENT' | 'NONE'
  sla_status    text,     -- 'OK' | 'WARN' | 'ESCALATE' | 'SNOOZED' | 'DONE'
  anchor_at     timestamptz,
  warn_at       timestamptz,
  escalate_at   timestamptz,
  effective_due timestamptz,
  overdue       interval,
  claimed_by    uuid,
  snooze_until  timestamptz
)
LANGUAGE sql STABLE AS $$
  WITH p AS (SELECT * FROM public.r54_sla_policy WHERE id = 1)
  SELECT
    cl.case_code,
    cl.stage,
    tr.sla_track,
    tr.sla_status,
    tr.anchor_at,
    tr.warn_at,
    tr.escalate_at,
    tr.effective_due,
    CASE WHEN tr.sla_status = 'ESCALATE'
         THEN p_as_of - tr.escalate_at ELSE NULL END AS overdue,
    cl.claimed_by,
    cl.snooze_until
  FROM public.r54_case_loop cl
  CROSS JOIN p
  CROSS JOIN LATERAL (
    SELECT
      -- which SLA track is this case on right now?
      CASE
        WHEN cl.stage IN ('RECEIVED','DRAFTED') THEN 'A_UNCLAIMED'
        WHEN cl.stage IN ('CLAIMED','APPROVED') THEN 'B_UNSENT'
        ELSE 'NONE'
      END AS sla_track,
      -- clock anchor
      CASE
        WHEN cl.stage IN ('RECEIVED','DRAFTED') THEN cl.received_at
        WHEN cl.stage IN ('CLAIMED','APPROVED') THEN cl.claimed_at
        ELSE NULL
      END AS anchor_at
  ) base
  CROSS JOIN LATERAL (
    SELECT
      base.sla_track,
      base.anchor_at,
      w.warn_at, w.escalate_at, w.effective_due,
      CASE
        WHEN cl.stage IN ('SENT','ARCHIVED','CLOSED') THEN 'DONE'
        WHEN cl.stage = 'DECLINED' THEN 'DONE'
        -- legitimate snooze: paused until snooze_until
        WHEN cl.stage = 'SNOOZED' OR (cl.snooze_until IS NOT NULL AND cl.snooze_until > p_as_of)
             THEN 'SNOOZED'
        WHEN base.sla_track = 'NONE' THEN 'OK'
        WHEN p_as_of >= w.escalate_at THEN 'ESCALATE'
        WHEN p_as_of >= w.warn_at     THEN 'WARN'
        ELSE 'OK'
      END AS sla_status
    FROM (
      SELECT
        CASE WHEN base.sla_track='A_UNCLAIMED'
             THEN base.anchor_at + (SELECT stage_a_warn FROM p)
             WHEN base.sla_track='B_UNSENT'
             THEN base.anchor_at + (SELECT stage_b_warn FROM p) END AS warn_at,
        CASE WHEN base.sla_track='A_UNCLAIMED'
             THEN base.anchor_at + (SELECT stage_a_escalate FROM p)
             WHEN base.sla_track='B_UNSENT'
             THEN base.anchor_at + (SELECT stage_b_warn FROM p) + (SELECT stage_b_escalate_after FROM p) END AS escalate_at,
        -- when snoozed, the effective due never fires before snooze_until
        GREATEST(
          CASE WHEN base.sla_track='A_UNCLAIMED'
               THEN base.anchor_at + (SELECT stage_a_escalate FROM p)
               WHEN base.sla_track='B_UNSENT'
               THEN base.anchor_at + (SELECT stage_b_warn FROM p) + (SELECT stage_b_escalate_after FROM p) END,
          COALESCE(cl.snooze_until, '-infinity'::timestamptz)
        ) AS effective_due
    ) w
  ) tr
$$;

-- Twice-daily radar sweep (09:00 / 16:30). Returns only the actionable rows.
-- Operationally scheduled by cron; this function performs NO external send.
CREATE OR REPLACE FUNCTION public.r54_radar_sweep(p_as_of timestamptz DEFAULT clock_timestamp())
RETURNS TABLE (
  case_code text, stage text, sla_track text, sla_status text,
  effective_due timestamptz, overdue interval, claimed_by uuid
)
LANGUAGE sql STABLE AS $$
  SELECT case_code, stage, sla_track, sla_status, effective_due, overdue, claimed_by
  FROM public.r54_sla_radar(p_as_of)
  WHERE sla_status IN ('WARN','ESCALATE')
  ORDER BY (sla_status='ESCALATE') DESC, effective_due ASC;
$$;
