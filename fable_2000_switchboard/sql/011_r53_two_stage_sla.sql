-- R53 two-stage SLA state machine.
--
-- Scope: a NEW, self-contained feature. It reuses public.case / public.employee /
-- public.notification_outbox but adds its own tracker table and functions so it does
-- not collide with the existing card lifecycle state model (public.card.state).
--
-- 7-stage status model (r53_sla_status):
--   UNCLAIMED            -- case landed, nobody has taken the ball
--   CLAIMED              -- someone owns it but has not sent the client reply yet
--   WAITING_UPSTREAM_DATA-- legitimate snooze/hold; SLA clocks are PAUSED
--   SENT                 -- reply sent to client, still awaiting resolution
--   ESCALATED_L1         -- first escalation fired
--   ESCALATED_L2         -- second escalation fired
--   RESOLVED             -- terminal; case closed, no more SLA
--
-- Two escalation tracks (business/elapsed time minus paused time = "live" age):
--   Unclaimed track  : UNCLAIMED, L1 at +2h, L2 at +4h.
--   Claimed-unsent   : CLAIMED,   L1 at +24h, L2 at +28h (+4h after L1).
-- WAITING_UPSTREAM_DATA pauses both clocks by accumulating paused_seconds.
--
-- Radar sweeps: twice daily at 09:00 and 16:30 Asia/Taipei, selecting all
-- non-terminal, non-paused trackers whose live age has crossed a threshold.

BEGIN;

CREATE TABLE IF NOT EXISTS public.r53_sla_tracker (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id            text NOT NULL,
  case_id           uuid NOT NULL REFERENCES public.case(id),
  status            text NOT NULL DEFAULT 'UNCLAIMED',
  assignee_employee_id uuid REFERENCES public.employee(id),
  -- Clock anchors. clock_started_at is when the *current* track started
  -- (ingest for UNCLAIMED, claim time for CLAIMED). It is reset on CLAIM.
  arrived_at        timestamptz NOT NULL DEFAULT now(),
  clock_started_at  timestamptz NOT NULL DEFAULT now(),
  claimed_at        timestamptz,
  sent_at           timestamptz,
  resolved_at       timestamptz,
  -- Snooze bookkeeping.
  paused_at         timestamptz,                 -- non-null iff currently WAITING_UPSTREAM_DATA
  paused_seconds    bigint NOT NULL DEFAULT 0,   -- total accumulated pause
  escalation_level  smallint NOT NULL DEFAULT 0, -- 0, 1, 2
  last_escalated_at timestamptz,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT r53_sla_status_check CHECK (status = ANY (ARRAY[
    'UNCLAIMED','CLAIMED','WAITING_UPSTREAM_DATA','SENT',
    'ESCALATED_L1','ESCALATED_L2','RESOLVED'])),
  CONSTRAINT r53_sla_level_check CHECK (escalation_level BETWEEN 0 AND 2),
  CONSTRAINT r53_sla_paused_iff CHECK (
    (status = 'WAITING_UPSTREAM_DATA') = (paused_at IS NOT NULL))
);

-- One active tracker per case (RESOLVED trackers are archival, allow many).
CREATE UNIQUE INDEX IF NOT EXISTS r53_sla_one_live_per_case
  ON public.r53_sla_tracker(case_id) WHERE status <> 'RESOLVED';

-- ------------------------------------------------------------------------- --
-- Live age: wall elapsed since clock_started_at, minus all paused time,
-- minus any in-flight pause currently open. Deterministic given p_now.
-- ------------------------------------------------------------------------- --
CREATE OR REPLACE FUNCTION public.r53_live_age_seconds(
  t public.r53_sla_tracker, p_now timestamptz)
RETURNS bigint LANGUAGE sql IMMUTABLE AS $$
  SELECT GREATEST(0,
    EXTRACT(EPOCH FROM (p_now - t.clock_started_at))::bigint
    - t.paused_seconds
    - CASE WHEN t.paused_at IS NOT NULL
           THEN EXTRACT(EPOCH FROM (p_now - t.paused_at))::bigint
           ELSE 0 END);
$$;

-- Which escalation level *should* apply right now for a given tracker.
-- Returns 0/1/2. Paused and terminal trackers never escalate.
CREATE OR REPLACE FUNCTION public.r53_due_level(
  t public.r53_sla_tracker, p_now timestamptz)
RETURNS smallint LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE
    WHEN t.status IN ('WAITING_UPSTREAM_DATA','RESOLVED','SENT') THEN 0::smallint
    WHEN t.status = 'UNCLAIMED' OR (t.status LIKE 'ESCALATED%' AND t.claimed_at IS NULL) THEN
      CASE
        WHEN public.r53_live_age_seconds(t, p_now) >= 4*3600 THEN 2::smallint
        WHEN public.r53_live_age_seconds(t, p_now) >= 2*3600 THEN 1::smallint
        ELSE 0::smallint END
    WHEN t.status = 'CLAIMED' OR (t.status LIKE 'ESCALATED%' AND t.claimed_at IS NOT NULL) THEN
      CASE
        WHEN public.r53_live_age_seconds(t, p_now) >= 28*3600 THEN 2::smallint
        WHEN public.r53_live_age_seconds(t, p_now) >= 24*3600 THEN 1::smallint
        ELSE 0::smallint END
    ELSE 0::smallint END;
$$;

-- ------------------------------------------------------------------------- --
-- Transitions. Each returns the updated tracker row.
-- ------------------------------------------------------------------------- --
CREATE OR REPLACE FUNCTION public.r53_claim(
  p_tracker uuid, p_assignee uuid, p_now timestamptz DEFAULT now())
RETURNS public.r53_sla_tracker LANGUAGE plpgsql AS $$
DECLARE r public.r53_sla_tracker;
BEGIN
  SELECT * INTO r FROM public.r53_sla_tracker WHERE id = p_tracker FOR UPDATE;
  IF r.status NOT IN ('UNCLAIMED','ESCALATED_L1','ESCALATED_L2') OR r.claimed_at IS NOT NULL THEN
    RAISE EXCEPTION 'r53_claim: cannot claim from status % (claimed_at=%)', r.status, r.claimed_at;
  END IF;
  UPDATE public.r53_sla_tracker SET
    status='CLAIMED', assignee_employee_id=p_assignee, claimed_at=p_now,
    clock_started_at=p_now,          -- claimed-unsent clock starts fresh at claim
    escalation_level=0, last_escalated_at=NULL,
    paused_seconds=0, updated_at=p_now
  WHERE id=p_tracker RETURNING * INTO r;
  RETURN r;
END; $$;

CREATE OR REPLACE FUNCTION public.r53_snooze(
  p_tracker uuid, p_now timestamptz DEFAULT now())
RETURNS public.r53_sla_tracker LANGUAGE plpgsql AS $$
DECLARE r public.r53_sla_tracker;
BEGIN
  SELECT * INTO r FROM public.r53_sla_tracker WHERE id=p_tracker FOR UPDATE;
  IF r.status IN ('WAITING_UPSTREAM_DATA','RESOLVED') THEN
    RAISE EXCEPTION 'r53_snooze: invalid from %', r.status;
  END IF;
  UPDATE public.r53_sla_tracker SET
    status='WAITING_UPSTREAM_DATA',
    paused_at=p_now, updated_at=p_now
  WHERE id=p_tracker RETURNING * INTO r;
  RETURN r;
END; $$;

-- Resume from snooze back to its pre-pause track. We infer the track from
-- whether the case was claimed: CLAIMED if claimed_at set, else UNCLAIMED.
CREATE OR REPLACE FUNCTION public.r53_resume(
  p_tracker uuid, p_now timestamptz DEFAULT now())
RETURNS public.r53_sla_tracker LANGUAGE plpgsql AS $$
DECLARE r public.r53_sla_tracker;
BEGIN
  SELECT * INTO r FROM public.r53_sla_tracker WHERE id=p_tracker FOR UPDATE;
  IF r.status <> 'WAITING_UPSTREAM_DATA' THEN
    RAISE EXCEPTION 'r53_resume: not paused (status=%)', r.status;
  END IF;
  UPDATE public.r53_sla_tracker SET
    status = CASE
      WHEN escalation_level = 2 THEN 'ESCALATED_L2'
      WHEN escalation_level = 1 THEN 'ESCALATED_L1'
      WHEN claimed_at IS NOT NULL THEN 'CLAIMED'
      ELSE 'UNCLAIMED' END,
    paused_seconds = paused_seconds + EXTRACT(EPOCH FROM (p_now - paused_at))::bigint,
    paused_at = NULL, updated_at = p_now
  WHERE id=p_tracker RETURNING * INTO r;
  RETURN r;
END; $$;

CREATE OR REPLACE FUNCTION public.r53_mark_sent(
  p_tracker uuid, p_now timestamptz DEFAULT now())
RETURNS public.r53_sla_tracker LANGUAGE plpgsql AS $$
DECLARE r public.r53_sla_tracker;
BEGIN
  SELECT * INTO r FROM public.r53_sla_tracker WHERE id=p_tracker FOR UPDATE;
  IF r.claimed_at IS NULL THEN
    RAISE EXCEPTION 'r53_mark_sent: cannot send an unclaimed case';
  END IF;
  UPDATE public.r53_sla_tracker SET
    status='SENT', sent_at=p_now, paused_at=NULL, updated_at=p_now
  WHERE id=p_tracker RETURNING * INTO r;
  RETURN r;
END; $$;

CREATE OR REPLACE FUNCTION public.r53_resolve(
  p_tracker uuid, p_now timestamptz DEFAULT now())
RETURNS public.r53_sla_tracker LANGUAGE plpgsql AS $$
DECLARE r public.r53_sla_tracker;
BEGIN
  UPDATE public.r53_sla_tracker SET
    status='RESOLVED', resolved_at=p_now, paused_at=NULL, updated_at=p_now
  WHERE id=p_tracker RETURNING * INTO r;
  RETURN r;
END; $$;

-- ------------------------------------------------------------------------- --
-- Escalation runner: fire any due escalations as of p_now. Advances
-- escalation_level by at most one per call toward the due level, sets status to
-- ESCALATED_L1/L2, and enqueues a (mock, local) notification_outbox doorbell
-- with an idempotent dedupe_key. Returns the number of trackers escalated.
-- ------------------------------------------------------------------------- --
CREATE OR REPLACE FUNCTION public.r53_run_escalations(p_now timestamptz DEFAULT now())
RETURNS integer LANGUAGE plpgsql AS $$
DECLARE r public.r53_sla_tracker; due smallint; n integer := 0; dk text;
BEGIN
  FOR r IN SELECT * FROM public.r53_sla_tracker
           WHERE status NOT IN ('RESOLVED','SENT','WAITING_UPSTREAM_DATA') FOR UPDATE
  LOOP
    due := public.r53_due_level(r, p_now);
    IF due > r.escalation_level THEN
      UPDATE public.r53_sla_tracker SET
        escalation_level = r.escalation_level + 1,
        status = CASE WHEN r.escalation_level + 1 = 2 THEN 'ESCALATED_L2' ELSE 'ESCALATED_L1' END,
        last_escalated_at = p_now, updated_at = p_now
      WHERE id = r.id;
      dk := 'r53-esc:' || r.id || ':' || (r.escalation_level + 1)::text;
      INSERT INTO public.notification_outbox(channel, recipient_id, tier, dedupe_key, payload, status)
        VALUES ('mock', coalesce(r.assignee_employee_id::text,'UNCLAIMED'), 'immediate', dk,
                jsonb_build_object('kind','r53_escalation','tracker',r.id,'level',r.escalation_level+1,
                                   'track', CASE WHEN r.claimed_at IS NULL THEN 'unclaimed' ELSE 'claimed_unsent' END),
                'queued')
        ON CONFLICT (dedupe_key) DO NOTHING;
      n := n + 1;
    END IF;
  END LOOP;
  RETURN n;
END; $$;

-- notification_outbox needs a unique dedupe_key for the ON CONFLICT above.
CREATE UNIQUE INDEX IF NOT EXISTS notification_outbox_dedupe_uq
  ON public.notification_outbox(dedupe_key);

-- ------------------------------------------------------------------------- --
-- Radar sweep. Returns the set of trackers that a sweep at p_now would surface.
-- A sweep runs only at 09:00 or 16:30 Asia/Taipei; r53_is_sweep_time guards that.
-- ------------------------------------------------------------------------- --
CREATE OR REPLACE FUNCTION public.r53_is_sweep_time(p_now timestamptz)
RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
  SELECT to_char(p_now AT TIME ZONE 'Asia/Taipei', 'HH24:MI') IN ('09:00','16:30');
$$;

CREATE OR REPLACE FUNCTION public.r53_radar_sweep(p_now timestamptz DEFAULT now())
RETURNS TABLE(tracker_id uuid, case_id uuid, status text,
              escalation_level smallint, live_age_seconds bigint, due_level smallint)
LANGUAGE sql STABLE AS $$
  SELECT t.id, t.case_id, t.status, t.escalation_level,
         public.r53_live_age_seconds(t, p_now),
         public.r53_due_level(t, p_now)
  FROM public.r53_sla_tracker t
  WHERE public.r53_is_sweep_time(p_now)
    AND t.status NOT IN ('RESOLVED','SENT','WAITING_UPSTREAM_DATA')
    AND public.r53_due_level(t, p_now) > 0
  ORDER BY public.r53_due_level(t, p_now) DESC, public.r53_live_age_seconds(t, p_now) DESC;
$$;

COMMIT;
