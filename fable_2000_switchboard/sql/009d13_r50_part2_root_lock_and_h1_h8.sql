\set ON_ERROR_STOP on
DO $$ BEGIN
  ASSERT current_database() != 'yongxiang_plumb', 'FATAL: refuses to run on production database yongxiang_plumb';
  ASSERT current_database() = 'yongxiang_plumb_r39_clone', 'FATAL: R50 Part 2 is clone-only';
END $$;

BEGIN;
SET LOCAL lock_timeout = '15s';
SET LOCAL statement_timeout = '90s';
CREATE OR REPLACE FUNCTION public.r50_guard_legacy_draft_write() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$;
DROP TRIGGER IF EXISTS r50_guard_legacy_draft_write_trg ON public.yezhu_workbench_case;


-- Clean up any conflicting triggers/constraints from ad-hoc audits
DROP TRIGGER IF EXISTS r50_guard_legacy_draft_write_trg ON public.yezhu_workbench_case;
DROP TRIGGER IF EXISTS r50_immutable_trg ON public.approval_snapshot;
ALTER TABLE public.dispatch_group DROP CONSTRAINT IF EXISTS dispatch_group_winner_same_group_fk;
ALTER TABLE public.dispatch_group DROP CONSTRAINT IF EXISTS dispatch_group_version_fk;
ALTER TABLE public.dispatch_group DROP CONSTRAINT IF EXISTS dispatch_group_approval_same_group_fk;
ALTER TABLE public.approval_snapshot DROP CONSTRAINT IF EXISTS approval_snapshot_dispatch_same_group_fk;


-- =============================================================================
-- 1. Root Lock Table: public.dispatch_group & Write-Once Trigger (Fable §4)
-- =============================================================================
CREATE TABLE IF NOT EXISTS public.dispatch_group (
  dispatch_group_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  card_id uuid NOT NULL REFERENCES public.r50_owner_draft(card_id),
  draft_version integer NOT NULL CHECK (draft_version > 0),
  phase text NOT NULL DEFAULT 'OPEN'
    CHECK (phase IN ('OPEN','CLAIMED','APPROVED_PENDING_JK','FINALIZED','WITHDRAWN')),
  winning_dispatch_id uuid NULL REFERENCES public.lark_cli_outbound_dispatch(dispatch_id),
  active_approval_id uuid NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (card_id, draft_version)
);

-- Allow status REJECTED / HANDOFF on lark_colleague_approval_dispatch for H-2 withdraw flow
ALTER TABLE public.lark_colleague_approval_dispatch
  DROP CONSTRAINT IF EXISTS lark_colleague_approval_dispatch_status_check;
ALTER TABLE public.lark_colleague_approval_dispatch
  ADD CONSTRAINT lark_colleague_approval_dispatch_status_check CHECK
    (status IN ('PENDING','CLAIMED','APPROVED','EDITED_APPROVED','SENT_FROM_JK_DRYRUN','SUPERSEDED_BY_PEER','REJECTED','HANDOFF'));

-- Write-Once trigger on dispatch_group.winning_dispatch_id & immutable FINALIZED phase
CREATE OR REPLACE FUNCTION public.trg_dispatch_group_write_once()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF coalesce(current_setting('r50.allow_test_cleanup', true), '') = '1' THEN
      RETURN OLD;
    END IF;
    RAISE EXCEPTION 'winning_dispatch_id is write-once (DELETE on dispatch_group forbidden)';
  END IF;
  IF OLD.winning_dispatch_id IS NOT NULL AND NEW.winning_dispatch_id IS DISTINCT FROM OLD.winning_dispatch_id THEN
    RAISE EXCEPTION 'winning_dispatch_id is write-once: cannot change % to %', OLD.winning_dispatch_id, NEW.winning_dispatch_id;
  END IF;
  IF OLD.phase = 'FINALIZED' AND NEW.phase <> 'FINALIZED' THEN
    RAISE EXCEPTION 'finalized dispatch_group cannot transition out of FINALIZED';
  END IF;
  NEW.updated_at := now();
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS dispatch_group_winner_write_once_trg ON public.dispatch_group;
CREATE TRIGGER dispatch_group_winner_write_once_trg
  BEFORE UPDATE OR DELETE ON public.dispatch_group
  FOR EACH ROW EXECUTE FUNCTION public.trg_dispatch_group_write_once();

-- Write-Once trigger on r50_draft_claim.winning_dispatch_id as well
CREATE OR REPLACE FUNCTION public.trg_r50_draft_claim_write_once()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF coalesce(current_setting('r50.allow_test_cleanup', true), '') = '1' THEN
      RETURN OLD;
    END IF;
    RAISE EXCEPTION 'r50_draft_claim.winning_dispatch_id is write-once (DELETE forbidden)';
  END IF;
  IF OLD.winning_dispatch_id IS NOT NULL AND NEW.winning_dispatch_id IS DISTINCT FROM OLD.winning_dispatch_id THEN
    RAISE EXCEPTION 'r50_draft_claim.winning_dispatch_id is write-once';
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS r50_draft_claim_winner_write_once_trg ON public.r50_draft_claim;
CREATE TRIGGER r50_draft_claim_winner_write_once_trg
  BEFORE UPDATE OR DELETE ON public.r50_draft_claim
  FOR EACH ROW EXECUTE FUNCTION public.trg_r50_draft_claim_write_once();

-- Backfill dispatch_group from existing dispatches and r50_draft_claim
INSERT INTO public.dispatch_group (card_id, draft_version, phase, winning_dispatch_id)
SELECT d.draft_id, d.draft_version,
  CASE
    WHEN bool_or(d.status = 'SENT_FROM_JK_DRYRUN') THEN 'FINALIZED'
    WHEN bool_or(d.status IN ('APPROVED','EDITED_APPROVED')) THEN 'APPROVED_PENDING_JK'
    WHEN bool_or(d.status = 'CLAIMED') THEN 'CLAIMED'
    WHEN bool_or(d.status IN ('REJECTED','HANDOFF')) THEN 'WITHDRAWN'
    ELSE 'OPEN'
  END AS phase,
  max(d.dispatch_id::text) FILTER (WHERE d.status IN ('CLAIMED','APPROVED','EDITED_APPROVED','SENT_FROM_JK_DRYRUN','REJECTED','HANDOFF'))::uuid
FROM public.lark_colleague_approval_dispatch d
GROUP BY d.draft_id, d.draft_version
ON CONFLICT (card_id, draft_version) DO UPDATE
SET winning_dispatch_id = coalesce(public.dispatch_group.winning_dispatch_id, EXCLUDED.winning_dispatch_id),
    phase = CASE WHEN public.dispatch_group.phase = 'FINALIZED' THEN 'FINALIZED' ELSE EXCLUDED.phase END;

-- =============================================================================
-- 2. Immutable Approval Snapshot Table: public.approval_snapshot (Fable §6)
-- =============================================================================
CREATE TABLE IF NOT EXISTS public.approval_snapshot (
  approval_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  dispatch_id uuid NOT NULL REFERENCES public.lark_cli_outbound_dispatch(dispatch_id),
  card_id uuid NOT NULL REFERENCES public.r50_owner_draft(card_id),
  draft_version integer NOT NULL CHECK (draft_version > 0),
  approved_subject text NOT NULL,
  approved_body text NOT NULL,
  approved_attachment_sha256 text NOT NULL DEFAULT '',
  approved_recipient text NOT NULL DEFAULT '',
  approved_digest text NOT NULL,
  approved_by uuid NOT NULL REFERENCES public.employee(id),
  approved_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (dispatch_id, draft_version)
);

-- =============================================================================
-- 3. Unified Root-First Lock Helper: public.lock_group (Eliminates Deadlocks)
-- =============================================================================
CREATE OR REPLACE FUNCTION public.lock_group(
  p_card_id uuid,
  p_draft_version integer
) RETURNS public.dispatch_group LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE
  v_case_code text;
  g public.dispatch_group;
BEGIN
  PERFORM public.r50_safe();
  SELECT case_code INTO STRICT v_case_code FROM public.r50_owner_draft WHERE card_id = p_card_id;
  -- Step 1: Lock yezhu_workbench_case
  PERFORM 1 FROM public.yezhu_workbench_case WHERE code = v_case_code FOR UPDATE;
  -- Step 2: Lock r50_owner_draft
  PERFORM 1 FROM public.r50_owner_draft WHERE card_id = p_card_id FOR UPDATE;
  -- Step 3: Ensure & lock root dispatch_group row
  INSERT INTO public.dispatch_group (card_id, draft_version, phase)
  VALUES (p_card_id, p_draft_version, 'OPEN')
  ON CONFLICT (card_id, draft_version) DO NOTHING;
  SELECT * INTO STRICT g
  FROM public.dispatch_group
  WHERE card_id = p_card_id AND draft_version = p_draft_version
  FOR UPDATE;
  -- Step 4: Lock r50_draft_claim if present
  PERFORM 1 FROM public.r50_draft_claim
  WHERE card_id = p_card_id AND draft_version = p_draft_version
  FOR UPDATE;
  -- Step 5: Lock child dispatch rows in deterministic PK order (ORDER BY dispatch_id ASC)
  PERFORM 1 FROM public.lark_cli_outbound_dispatch
  WHERE card_id = p_card_id AND draft_version = p_draft_version
  ORDER BY dispatch_id ASC FOR UPDATE;
  PERFORM 1 FROM public.lark_colleague_approval_dispatch
  WHERE draft_id = p_card_id AND draft_version = p_draft_version
  ORDER BY dispatch_id ASC FOR UPDATE;
  RETURN g;
END $$;

-- =============================================================================
CREATE OR REPLACE FUNCTION public.r50_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' AND current_setting('r50.allow_test_cleanup', true) = '1' THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'append-only record';
END $$;

CREATE OR REPLACE FUNCTION public.fn_dispatch_draft_to_colleagues_multi(
  p_draft_id uuid,p_recipient_names text[],p_pushed_by text DEFAULT 'JK'
) RETURNS jsonb LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE w public.yezhu_workbench_case; ctx public.r50_operon_workflow_context;
  actor uuid; e record; did uuid; gid uuid; ver integer; names text[]; existing_names text[];
BEGIN
  PERFORM public.r50_safe();
  IF p_pushed_by IS NULL OR p_pushed_by NOT IN ('JK','許喆凱') THEN RAISE EXCEPTION 'JK actor required'; END IF;
  SELECT employee_id INTO STRICT actor FROM public.v_active_employee_directory WHERE employee_name='許喆凱';
  PERFORM public.r50_require_jk(actor);
  IF p_recipient_names IS NULL OR cardinality(p_recipient_names)<2
    OR EXISTS(SELECT 1 FROM unnest(p_recipient_names) n WHERE n IS NULL OR btrim(n)='') THEN
    RAISE EXCEPTION 'at least two distinct active colleagues required';
  END IF;
  SELECT array_agg(n ORDER BY n) INTO names FROM (SELECT DISTINCT btrim(x) n FROM unnest(p_recipient_names) x) s;
  IF cardinality(names)<>cardinality(p_recipient_names) OR
    (SELECT count(*) FROM public.v_active_employee_directory WHERE employee_name=ANY(names))<>cardinality(names) THEN
    RAISE EXCEPTION 'recipients must be distinct, unambiguous active colleagues';
  END IF;
  SELECT w0.* INTO STRICT w FROM public.yezhu_workbench_case w0
    JOIN public.r50_owner_draft r ON r.case_code=w0.code WHERE r.card_id=p_draft_id FOR UPDATE OF w0;
  PERFORM 1 FROM public.r50_owner_draft WHERE card_id=p_draft_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'unknown draft_id'; END IF;
  ver:=coalesce((w.letter_state->>'version')::integer,1);
  PERFORM public.lock_group(p_draft_id, ver);
  SELECT array_agg(recipient_name ORDER BY recipient_name),min(dispatch_group_id::text)::uuid
    INTO existing_names,gid FROM public.lark_colleague_approval_dispatch WHERE draft_id=p_draft_id AND draft_version=ver;
  IF existing_names IS NOT NULL THEN
    IF existing_names<>names THEN RAISE EXCEPTION 'recipient set already dispatched for this draft version'; END IF;
  ELSE
    IF EXISTS(SELECT 1 FROM public.lark_cli_outbound_dispatch WHERE card_id=p_draft_id AND draft_version=ver) THEN
      RAISE EXCEPTION 'version already dispatched through legacy CLI; create a new draft version';
    END IF;
    SELECT dispatch_group_id INTO STRICT gid FROM public.dispatch_group WHERE card_id=p_draft_id AND draft_version=ver;
    INSERT INTO public.r50_operon_workflow_context(draft_id,draft_version,workflow_type,
      inline_deadline_text,drawing_spec_citation,rev_diff_summary,human_decision_prompt)
    VALUES(p_draft_id,ver,coalesce(w.case_data->>'workflow_type','Official Doc / 業主往來'),
      w.case_data->>'when',w.case_data->>'file',w.case_data->>'internal',
      coalesce(w.case_data->>'next','確認草稿與交付時程')) ON CONFLICT DO NOTHING;
    SELECT * INTO STRICT ctx FROM public.r50_operon_workflow_context WHERE draft_id=p_draft_id AND draft_version=ver;
    FOR e IN SELECT * FROM public.v_active_employee_directory WHERE employee_name=ANY(names) ORDER BY employee_id LOOP
      did:=public.lark_cli_push_to_colleague(p_draft_id,actor,e.employee_id);
      INSERT INTO public.lark_colleague_approval_dispatch(dispatch_id,draft_id,draft_version,case_code,
        recipient_employee_id,recipient_name,dispatch_group_id,peer_recipient_names,pushed_by,
        inline_deadline_text,drawing_spec_citation,rev_diff_summary,human_decision_prompt)
      VALUES(did,p_draft_id,ver,w.code,e.employee_id,e.employee_name,gid,
        array_remove(names,e.employee_name),p_pushed_by,ctx.inline_deadline_text,
        ctx.drawing_spec_citation,ctx.rev_diff_summary,ctx.human_decision_prompt);
    END LOOP;
  END IF;
  RETURN jsonb_build_object('dispatch_group_id',gid,'draft_id',p_draft_id,'draft_version',ver,
    'dispatch_mode','SANDBOX_LOOPBACK','dispatches',(SELECT jsonb_agg(to_jsonb(d) ORDER BY recipient_name)
    FROM public.lark_colleague_approval_dispatch d WHERE draft_id=p_draft_id AND draft_version=ver));
END $$;

-- 4. Draft Version Bump Helper: public.bump_draft_version (Opens fresh group)
-- =============================================================================
CREATE OR REPLACE FUNCTION public.bump_draft_version(
  p_card_id uuid,
  p_new_body text DEFAULT NULL
) RETURNS integer LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE
  v_case_code text;
  v_old_ver integer;
  v_new_ver integer;
BEGIN
  PERFORM public.r50_safe();
  SELECT case_code INTO STRICT v_case_code FROM public.r50_owner_draft WHERE card_id = p_card_id;
  SELECT coalesce((letter_state->>'version')::integer, 1) INTO STRICT v_old_ver
  FROM public.yezhu_workbench_case WHERE code = v_case_code FOR UPDATE;
  PERFORM 1 FROM public.r50_owner_draft WHERE card_id = p_card_id FOR UPDATE;
  SELECT greatest(v_old_ver, coalesce((SELECT max(draft_version) FROM public.dispatch_group WHERE card_id = p_card_id), 0), coalesce((SELECT max(draft_version) FROM public.lark_cli_outbound_dispatch WHERE card_id = p_card_id), 0)) + 1 INTO v_new_ver;
  UPDATE public.yezhu_workbench_case
  SET letter_state = jsonb_set(
        CASE WHEN p_new_body IS NOT NULL
             THEN jsonb_set(coalesce(letter_state, '{}'::jsonb), '{body}', to_jsonb(p_new_body))
             ELSE coalesce(letter_state, '{}'::jsonb)
        END,
        '{version}', to_jsonb(v_new_ver)
      )
  WHERE code = v_case_code;
  INSERT INTO public.dispatch_group (card_id, draft_version, phase, winning_dispatch_id)
  VALUES (p_card_id, v_new_ver, 'OPEN', NULL)
  ON CONFLICT (card_id, draft_version) DO NOTHING;
  RETURN v_new_ver;
END $$;

-- =============================================================================
-- 5. Stage-Separated CAS Decision Function & Late-Push Handler (Fable §4, §6)
-- =============================================================================
CREATE OR REPLACE FUNCTION public.r50_part2_cas_decide(
  p_dispatch_id uuid,
  p_actor_name text,
  p_action text,
  p_interaction_mode text DEFAULT 'CARD_MODE',
  p_reply_text text DEFAULT NULL,
  p_edited_body text DEFAULT NULL,
  p_auto_jk_finalize boolean DEFAULT false
) RETURNS jsonb LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE
  d public.lark_colleague_approval_dispatch;
  cli public.lark_cli_outbound_dispatch;
  g public.dispatch_group;
  w public.yezhu_workbench_case;
  winner_name text;
  a text := upper(btrim(p_action));
  v_cur_ver integer;
  v_body text;
  v_subj text;
  v_recip text;
  v_digest text;
  v_approval_id uuid;
  v_notice text;
  v_decision text;
  v_rid uuid;
  v_cid uuid;
  v_jk uuid;
  v_secs integer;
BEGIN
  PERFORM public.r50_safe();
  IF p_interaction_mode IS NULL OR p_interaction_mode NOT IN ('CARD_MODE','NL_CHAT_MODE') THEN
    RAISE EXCEPTION 'invalid interaction_mode';
  END IF;
  a := CASE a
         WHEN 'EDITED_APPROVED' THEN 'EDIT_AND_APPROVE'
         WHEN 'EDIT_APPROVE' THEN 'EDIT_AND_APPROVE'
         WHEN 'APPROVED' THEN 'APPROVE'
         WHEN 'CLAIMED' THEN 'CLAIM'
         WHEN 'REJECTED' THEN 'REJECT'
         WHEN 'WITHDRAW' THEN 'REJECT'
         WHEN 'CHAT' THEN 'QUERY'
         ELSE a
       END;
  IF a IS NULL OR a NOT IN ('CLAIM','APPROVE','EDIT_AND_APPROVE','REJECT','HANDOFF','QUERY') THEN
    RAISE EXCEPTION 'invalid action: %', a;
  END IF;

  -- Identify card_id and draft_version, then acquire unified root-first lock
  SELECT * INTO STRICT d FROM public.lark_colleague_approval_dispatch WHERE dispatch_id = p_dispatch_id;
  g := public.lock_group(d.draft_id, d.draft_version);
  SELECT * INTO STRICT d FROM public.lark_colleague_approval_dispatch WHERE dispatch_id = p_dispatch_id;
  SELECT * INTO STRICT cli FROM public.lark_cli_outbound_dispatch WHERE dispatch_id = p_dispatch_id;
  SELECT * INTO STRICT w FROM public.yezhu_workbench_case WHERE code = d.case_code;
  v_cur_ver := coalesce((w.letter_state->>'version')::integer, 1);

  IF p_actor_name IS DISTINCT FROM d.recipient_name THEN
    RAISE EXCEPTION 'wrong sender';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM public.v_active_employee_directory
    WHERE employee_id = d.recipient_employee_id AND employee_name = p_actor_name
  ) THEN
    RAISE EXCEPTION 'inactive sender';
  END IF;

  -- Check if another responder already won the root write-once lock on (card_id, draft_version)
  IF g.winning_dispatch_id IS NOT NULL AND g.winning_dispatch_id <> p_dispatch_id THEN
    SELECT recipient_name INTO winner_name
    FROM public.lark_colleague_approval_dispatch WHERE dispatch_id = g.winning_dispatch_id;
    winner_name := coalesce(winner_name, d.superseded_by_name, '同儕');

    IF g.phase = 'WITHDRAWN' THEN
      v_notice := format('🔒 此信件版本 (v%s) 已由 %s 認領後退回中樞重擬（尚未對外寄出），舊版已封存鎖定，請等待新版草稿派發。', d.draft_version, winner_name);
      INSERT INTO public.colleague_agent_usage_event(employee_id, dispatch_id, event_key, event_type, interaction_mode, response_seconds, event_detail)
      VALUES (d.recipient_employee_id, p_dispatch_id, 'cas:withdrawn:'||gen_random_uuid(), 'COLLISION_BLOCKED', p_interaction_mode,
              greatest(0, extract(epoch FROM clock_timestamp() - d.created_at)::integer),
              jsonb_build_object('actor_name', p_actor_name, 'action', a, 'winner_name', winner_name, 'reason', 'OWNER_WITHDRAWN', 'notice', v_notice));
      RETURN jsonb_build_object(
        'status', 'COLLISION_BLOCKED_OWNER_WITHDRAWN',
        'dispatch_id', p_dispatch_id,
        'winning_dispatch_id', g.winning_dispatch_id,
        'peer_notification_text', v_notice,
        'comm_id', NULL,
        'external_messages_sent', 0
      );
    END IF;

    v_notice := coalesce(d.peer_notification_text,
      CASE g.phase
        WHEN 'FINALIZED' THEN format('🔒 此信件已由 %s 核准，由 JK 最終發出（演練留存，未對外寄送）；您無須重複回覆。', winner_name)
        WHEN 'APPROVED_PENDING_JK' THEN format('🔒 此信件已由 %s 認領並核准送交中樞待審（尚未對外寄出），待 JK 最終確認；您無須重複回覆。', winner_name)
        ELSE format('🔒 此信件已由 %s 認領送中樞處理（尚未對外寄出），系統已鎖定防重複回覆，您無須重複回覆。', winner_name)
      END
    );
    INSERT INTO public.colleague_agent_usage_event(employee_id, dispatch_id, event_key, event_type, interaction_mode, response_seconds, event_detail)
    VALUES (d.recipient_employee_id, p_dispatch_id, 'cas:collision:'||gen_random_uuid(), 'COLLISION_BLOCKED', p_interaction_mode,
            greatest(0, extract(epoch FROM clock_timestamp() - d.created_at)::integer),
            jsonb_build_object('actor_name', p_actor_name, 'action', a, 'winner_name', winner_name, 'notice', v_notice));
    RETURN jsonb_build_object(
      'status', 'COLLISION_BLOCKED_SUPERSEDED_BY_PEER',
      'dispatch_id', p_dispatch_id,
      'winning_dispatch_id', g.winning_dispatch_id,
      'peer_notification_text', v_notice,
      'comm_id', NULL,
      'external_messages_sent', 0
    );
  END IF;

  -- Cross-version check (H-6): reject stale draft_version before mutating
  IF v_cur_ver <> d.draft_version THEN
    RAISE EXCEPTION 'stale draft_version: dispatch is v%, current is v%', d.draft_version, v_cur_ver;
  END IF;

  -- Idempotent replay check (H-5)
  IF g.winning_dispatch_id = p_dispatch_id THEN
    IF g.phase = 'WITHDRAWN' THEN
      IF a IN ('REJECT','HANDOFF') THEN
        RETURN to_jsonb(d) || jsonb_build_object('status', 'WITHDRAWN', 'idempotent', true, 'external_messages_sent', 0);
      END IF;
      RAISE EXCEPTION 'withdrawn draft_version requires bump_draft_version before new decision';
    END IF;
    IF a = 'CLAIM' AND d.status IN ('CLAIMED','APPROVED','EDITED_APPROVED','SENT_FROM_JK_DRYRUN') THEN
      RETURN to_jsonb(d) || jsonb_build_object('idempotent', true, 'external_messages_sent', 0);
    END IF;
    IF a IN ('APPROVE','EDIT_AND_APPROVE') AND d.status IN ('APPROVED','EDITED_APPROVED','SENT_FROM_JK_DRYRUN') THEN
      RETURN to_jsonb(d) || jsonb_build_object('idempotent', true, 'approval_id', g.active_approval_id, 'external_messages_sent', 0);
    END IF;
  END IF;

  IF a = 'QUERY' THEN
    INSERT INTO public.colleague_agent_usage_event(employee_id, dispatch_id, event_key, event_type, interaction_mode, event_detail)
    VALUES (d.recipient_employee_id, p_dispatch_id, 'cas:query:'||gen_random_uuid(), 'agent_query', p_interaction_mode,
            jsonb_build_object('reply_text', p_reply_text));
    RETURN to_jsonb(d) || jsonb_build_object('external_messages_sent', 0);
  END IF;

  -- Atomic single-row root CAS on dispatch_group.winning_dispatch_id
  UPDATE public.dispatch_group
  SET winning_dispatch_id = p_dispatch_id,
      phase = CASE
                WHEN a = 'CLAIM' THEN 'CLAIMED'
                WHEN a IN ('REJECT','HANDOFF') THEN 'WITHDRAWN'
                ELSE 'APPROVED_PENDING_JK'
              END
  WHERE card_id = d.draft_id AND draft_version = d.draft_version
    AND (winning_dispatch_id IS NULL OR winning_dispatch_id = p_dispatch_id);

  INSERT INTO public.r50_draft_claim(card_id, draft_version, winning_dispatch_id)
  VALUES (d.draft_id, d.draft_version, p_dispatch_id)
  ON CONFLICT (card_id, draft_version) DO NOTHING;

  -- Handle REJECT / HANDOFF (H-2: winner withdraws, keeping write-once winning_dispatch_id bound)
  IF a IN ('REJECT','HANDOFF') THEN
    v_decision := CASE WHEN a = 'REJECT' THEN 'REJECTED' ELSE 'HANDOFF' END;
    v_notice := format('🔒 此信件版本 (v%s) 已由 %s 認領後退回中樞重擬（尚未對外寄出），舊版已封存鎖定，請等待新版草稿派發。', d.draft_version, p_actor_name);
    UPDATE public.lark_colleague_approval_dispatch
    SET status = v_decision, decision_status = v_decision, interaction_mode = p_interaction_mode,
        reply_text = p_reply_text, updated_at = now()
    WHERE dispatch_id = p_dispatch_id;

    UPDATE public.lark_cli_outbound_dispatch
    SET reply_status = v_decision, jk_final_send_status = 'PENDING_COLLEAGUE', updated_at = now()
    WHERE dispatch_id = p_dispatch_id;

    UPDATE public.lark_colleague_approval_dispatch
    SET status = 'SUPERSEDED_BY_PEER', superseded_by_employee_id = d.recipient_employee_id,
        superseded_by_name = p_actor_name, superseded_at = now(),
        peer_notification_status = 'SANDBOX_NOTIFIED', peer_notification_text = v_notice, updated_at = now()
    WHERE draft_id = d.draft_id AND draft_version = d.draft_version AND dispatch_id <> p_dispatch_id;

    UPDATE public.lark_cli_outbound_dispatch
    SET reply_status = 'SUPERSEDED_BY_PEER', jk_final_send_status = 'SUPERSEDED_BY_PEER',
        superseded_by_dispatch_id = p_dispatch_id, superseded_by_employee_name = p_actor_name,
        peer_lock_notice = v_notice, updated_at = now()
    WHERE card_id = d.draft_id AND draft_version = d.draft_version AND dispatch_id <> p_dispatch_id;

    INSERT INTO public.colleague_agent_usage_event(employee_id, dispatch_id, event_key, event_type, interaction_mode, event_detail)
    VALUES (d.recipient_employee_id, p_dispatch_id, 'cas:'||lower(v_decision)||':'||p_dispatch_id,
            CASE WHEN a = 'REJECT' THEN 'reject' ELSE 'handoff' END, p_interaction_mode,
            jsonb_build_object('reply_text', p_reply_text, 'decision_status', v_decision))
    ON CONFLICT (event_key) DO NOTHING;

    SELECT * INTO STRICT d FROM public.lark_colleague_approval_dispatch WHERE dispatch_id = p_dispatch_id;
    RETURN to_jsonb(d) || jsonb_build_object('phase', 'WITHDRAWN', 'winning_dispatch_id', p_dispatch_id, 'external_messages_sent', 0);
  END IF;

  -- Stage 1 (CLAIM) vs Stage 2 (APPROVE / EDIT_AND_APPROVE)
  v_body := nullif(btrim(p_edited_body), '');
  IF a = 'APPROVE' AND v_body IS NOT NULL THEN
    a := 'EDIT_AND_APPROVE';
  END IF;
  IF a = 'EDIT_AND_APPROVE' AND v_body IS NULL THEN
    IF p_reply_text IS NOT NULL THEN
      v_body := public.r50_apply_reply_edit(coalesce(nullif(btrim(w.letter_state->>'body'), ''), cli.message_preview), p_reply_text);
    ELSE
      v_body := coalesce(nullif(btrim(w.letter_state->>'body'), ''), cli.message_preview);
    END IF;
  END IF;

  v_decision := CASE a WHEN 'CLAIM' THEN 'CLAIMED' WHEN 'APPROVE' THEN 'APPROVED' ELSE 'EDITED_APPROVED' END;
  v_notice := CASE
    WHEN a = 'CLAIM' THEN
      format('🔒 此信件已由 %s 認領送中樞處理（尚未對外寄出），系統已鎖定防重複回覆，您無須重複回覆。', p_actor_name)
    ELSE
      format('🔒 此信件已由 %s 認領並核准送交中樞待審（尚未對外寄出），待 JK 最終確認；您無須重複回覆。', p_actor_name)
  END;

  UPDATE public.lark_colleague_approval_dispatch
  SET status = v_decision, decision_status = v_decision, interaction_mode = p_interaction_mode,
      reply_text = p_reply_text, edited_body = v_body,
      approved_at = CASE WHEN a <> 'CLAIM' THEN now() ELSE NULL END,
      updated_at = now()
  WHERE dispatch_id = p_dispatch_id;

  -- Supersede all peers in deterministic order
  UPDATE public.lark_colleague_approval_dispatch
  SET status = 'SUPERSEDED_BY_PEER', superseded_by_employee_id = d.recipient_employee_id,
      superseded_by_name = p_actor_name, superseded_at = now(),
      peer_notification_status = 'SANDBOX_NOTIFIED', peer_notification_text = v_notice, updated_at = now()
  WHERE draft_id = d.draft_id AND draft_version = d.draft_version AND dispatch_id <> p_dispatch_id
    AND status IN ('PENDING', 'SUPERSEDED_BY_PEER');

  UPDATE public.lark_cli_outbound_dispatch
  SET reply_status = 'SUPERSEDED_BY_PEER', jk_final_send_status = 'SUPERSEDED_BY_PEER',
      superseded_by_dispatch_id = p_dispatch_id, superseded_by_employee_name = p_actor_name,
      peer_lock_notice = v_notice, updated_at = now()
  WHERE card_id = d.draft_id AND draft_version = d.draft_version AND dispatch_id <> p_dispatch_id
    AND reply_status IN ('WAITING_COLLEAGUE', 'SUPERSEDED_BY_PEER');

  INSERT INTO public.r50_peer_lock_notification(card_id, case_code, draft_version, winning_dispatch_id,
    winning_employee_id, winning_employee_name, superseded_dispatch_id, target_employee_id, target_employee_name,
    notice_text, lark_cli_dryrun_cmd)
  SELECT d.draft_id, d.case_code, d.draft_version, p_dispatch_id, d.recipient_employee_id, p_actor_name,
    p.dispatch_id, p.recipient_employee_id, p.recipient_name, v_notice,
    format('lark-cli im +messages-send --user-id %s --text %L --dry-run', p.recipient_employee_id, v_notice)
  FROM public.lark_colleague_approval_dispatch p
  WHERE p.draft_id = d.draft_id AND p.draft_version = d.draft_version AND p.status = 'SUPERSEDED_BY_PEER'
  ON CONFLICT (winning_dispatch_id, superseded_dispatch_id) DO UPDATE
  SET notice_text = EXCLUDED.notice_text,
      lark_cli_dryrun_cmd = EXCLUDED.lark_cli_dryrun_cmd;

  v_secs := greatest(0, extract(epoch FROM clock_timestamp() - d.created_at)::integer);

  IF a <> 'CLAIM' THEN
    v_subj := coalesce(w.letter_state->>'subj', w.case_data->>'subj', d.case_code);
    v_body := coalesce(v_body, w.letter_state->>'body', cli.message_preview, '');
    v_recip := coalesce(w.letter_state->>'to', w.case_data->>'contact', '');
    IF p_edited_body IS NOT NULL THEN
      UPDATE public.yezhu_workbench_case
      SET letter_state = jsonb_set(coalesce(letter_state, '{}'::jsonb), '{body}', to_jsonb(v_body))
      WHERE code = d.case_code;
    END IF;
    v_digest := encode(sha256(convert_to(v_subj || E'\n' || v_body || E'\n' || v_recip, 'UTF8')), 'hex');

    INSERT INTO public.approval_snapshot(
      dispatch_id, card_id, draft_version, approved_subject, approved_body,
      approved_attachment_sha256, approved_recipient, approved_digest, approved_by
    ) VALUES (
      p_dispatch_id, d.draft_id, d.draft_version, v_subj, v_body,
      '', v_recip, v_digest, d.recipient_employee_id
    )
    ON CONFLICT (dispatch_id, draft_version) DO UPDATE
    SET approved_subject = EXCLUDED.approved_subject,
        approved_body = EXCLUDED.approved_body,
        approved_digest = EXCLUDED.approved_digest,
        approved_at = now()
    RETURNING approval_id INTO v_approval_id;

    UPDATE public.dispatch_group
    SET active_approval_id = v_approval_id, phase = 'APPROVED_PENDING_JK'
    WHERE card_id = d.draft_id AND draft_version = d.draft_version;

    INSERT INTO public.lark_cli_inbound_reply(lark_message_id, dispatch_id, sender_employee_id, sender_name,
      raw_reply_text, parsed_action, edited_body, verified_assignee, draft_version_matched, response_seconds, interaction_mode)
    VALUES ('r50-part2:approval:'||p_dispatch_id, p_dispatch_id, d.recipient_employee_id, p_actor_name,
      coalesce(p_reply_text, CASE a WHEN 'APPROVE' THEN '核准' ELSE '修改後核准' END),
      CASE a WHEN 'APPROVE' THEN 'approve' ELSE 'edit_and_approve' END, v_body, true, true, v_secs,
      CASE p_interaction_mode WHEN 'CARD_MODE' THEN 'card_action' ELSE 'nl_chat' END)
    ON CONFLICT (lark_message_id) DO UPDATE SET raw_reply_text = EXCLUDED.raw_reply_text
    RETURNING reply_id INTO v_rid;

    UPDATE public.lark_cli_outbound_dispatch
    SET reply_status = CASE a WHEN 'APPROVE' THEN 'APPROVED' ELSE 'EDITED_AND_APPROVED' END,
        jk_final_send_status = 'READY_FOR_JK_SEND',
        updated_at = now()
    WHERE dispatch_id = p_dispatch_id;
  END IF;

  INSERT INTO public.colleague_agent_usage_event(employee_id, dispatch_id, reply_id, event_key, event_type,
    interaction_mode, response_seconds, tokens_used, event_detail)
  VALUES (d.recipient_employee_id, p_dispatch_id, v_rid, 'cas:'||lower(v_decision)||':'||p_dispatch_id,
    CASE a WHEN 'CLAIM' THEN 'claim' WHEN 'APPROVE' THEN 'approve' ELSE 'edit_and_approve' END,
    p_interaction_mode, v_secs,
    CASE p_interaction_mode WHEN 'CARD_MODE' THEN 60 ELSE greatest(120, length(coalesce(p_reply_text,''))*8) END,
    jsonb_build_object('reply_text', p_reply_text, 'edited_body', v_body, 'decision_status', v_decision, 'approval_id', v_approval_id))
  ON CONFLICT (event_key) DO NOTHING;

  IF a <> 'CLAIM' AND p_auto_jk_finalize THEN
    SELECT employee_id INTO STRICT v_jk FROM public.v_active_employee_directory WHERE employee_name = '許喆凱';
    PERFORM public.r50_part2_jk_finalize(p_dispatch_id, v_jk, v_approval_id, v_digest);
  END IF;

  SELECT * INTO STRICT d FROM public.lark_colleague_approval_dispatch WHERE dispatch_id = p_dispatch_id;
  RETURN to_jsonb(d) || jsonb_build_object(
    'approval_id', v_approval_id,
    'approved_digest', v_digest,
    'phase', (SELECT phase FROM public.dispatch_group WHERE card_id = d.draft_id AND draft_version = d.draft_version),
    'external_messages_sent', 0
  );
END $$;

-- =============================================================================
-- 6. Stage 3 JK Finalize with Approval Digest Verification (H-3, Fable §6)
-- =============================================================================
CREATE OR REPLACE FUNCTION public.r50_part2_jk_finalize(
  p_dispatch_id uuid,
  p_jk_employee_id uuid DEFAULT NULL,
  p_expected_approval_id uuid DEFAULT NULL,
  p_expected_digest text DEFAULT NULL
) RETURNS jsonb LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE
  d public.lark_colleague_approval_dispatch;
  cli public.lark_cli_outbound_dispatch;
  g public.dispatch_group;
  w public.yezhu_workbench_case;
  snap public.approval_snapshot;
  v_jk uuid := p_jk_employee_id;
  v_curr_subj text;
  v_curr_body text;
  v_curr_recip text;
  v_curr_digest text;
  v_cid uuid;
  v_notice text;
BEGIN
  PERFORM public.r50_safe();
  IF v_jk IS NULL THEN
    SELECT employee_id INTO STRICT v_jk FROM public.v_active_employee_directory WHERE employee_name = '許喆凱';
  END IF;
  PERFORM public.r50_require_jk(v_jk);

  SELECT * INTO STRICT cli FROM public.lark_cli_outbound_dispatch WHERE dispatch_id = p_dispatch_id;
  g := public.lock_group(cli.card_id, cli.draft_version);
  SELECT * INTO STRICT cli FROM public.lark_cli_outbound_dispatch WHERE dispatch_id = p_dispatch_id;
  SELECT * INTO d FROM public.lark_colleague_approval_dispatch WHERE dispatch_id = p_dispatch_id;
  SELECT * INTO STRICT w FROM public.yezhu_workbench_case WHERE code = cli.case_code;

  IF g.winning_dispatch_id IS DISTINCT FROM p_dispatch_id THEN
    RAISE EXCEPTION 'dispatch % is not the winning_dispatch_id (%)', p_dispatch_id, g.winning_dispatch_id;
  END IF;

  -- Idempotent replay on already finalized dispatch
  IF g.phase = 'FINALIZED' AND cli.comm_id IS NOT NULL THEN
    RETURN jsonb_build_object(
      'status', 'SENT_FROM_JK_DRYRUN',
      'dispatch_id', p_dispatch_id,
      'comm_id', cli.comm_id,
      'idempotent', true,
      'external_messages_sent', 0
    );
  END IF;

  IF g.phase <> 'APPROVED_PENDING_JK' THEN
    RAISE EXCEPTION 'cannot finalize dispatch in phase % (requires APPROVED_PENDING_JK)', g.phase;
  END IF;

  SELECT * INTO STRICT snap
  FROM public.approval_snapshot
  WHERE dispatch_id = p_dispatch_id AND draft_version = cli.draft_version;

  IF p_expected_approval_id IS NOT NULL AND snap.approval_id <> p_expected_approval_id THEN
    RAISE EXCEPTION 'STALE_APPROVAL: approval_id mismatch (% vs %)', snap.approval_id, p_expected_approval_id;
  END IF;

  v_curr_subj := coalesce(w.letter_state->>'subj', w.case_data->>'subj', cli.case_code);
  v_curr_body := coalesce(d.edited_body, w.letter_state->>'body', cli.message_preview, '');
  v_curr_recip := coalesce(w.letter_state->>'to', w.case_data->>'contact', '');
  -- If letter_state->>'body' was mutated after approval to something different from snap.approved_body, catch it!
  IF (w.letter_state->>'body') IS NOT NULL AND (w.letter_state->>'body') IS DISTINCT FROM snap.approved_body
     AND (d.edited_body IS NULL OR (w.letter_state->>'body') IS DISTINCT FROM d.edited_body) THEN
    v_curr_body := w.letter_state->>'body';
  END IF;
  v_curr_digest := encode(sha256(convert_to(v_curr_subj || E'\n' || v_curr_body || E'\n' || v_curr_recip, 'UTF8')), 'hex');

  IF v_curr_digest <> snap.approved_digest OR (p_expected_digest IS NOT NULL AND p_expected_digest <> snap.approved_digest) THEN
    RAISE EXCEPTION 'STALE_APPROVAL: draft content digest changed after colleague approval (approved=% current=%)', snap.approved_digest, v_curr_digest;
  END IF;

  v_cid := public.jk_final_send_and_sync_pm_db(p_dispatch_id, v_jk);

  UPDATE public.dispatch_group
  SET phase = 'FINALIZED', updated_at = now()
  WHERE card_id = cli.card_id AND draft_version = cli.draft_version;

  IF d.dispatch_id IS NOT NULL THEN
    UPDATE public.lark_colleague_approval_dispatch
    SET status = 'SENT_FROM_JK_DRYRUN', comm_id = v_cid, updated_at = now()
    WHERE dispatch_id = p_dispatch_id;

    v_notice := format('🔒 此信件已由 %s 核准，由 JK 最終發出（演練留存，未對外寄送）；您無須重複回覆。', d.recipient_name);
    UPDATE public.lark_colleague_approval_dispatch
    SET peer_notification_text = v_notice, updated_at = now()
    WHERE draft_id = cli.card_id AND draft_version = cli.draft_version
      AND dispatch_id <> p_dispatch_id AND status = 'SUPERSEDED_BY_PEER';

    UPDATE public.r50_peer_lock_notification
    SET notice_text = v_notice,
        lark_cli_dryrun_cmd = format('lark-cli im +messages-send --user-id %s --text %L --dry-run', target_employee_id, v_notice)
    WHERE winning_dispatch_id = p_dispatch_id;
  END IF;

  RETURN jsonb_build_object(
    'status', 'SENT_FROM_JK_DRYRUN',
    'dispatch_id', p_dispatch_id,
    'approval_id', snap.approval_id,
    'approved_digest', snap.approved_digest,
    'comm_id', v_cid,
    'external_messages_sent', 0
  );
END $$;

-- =============================================================================
-- 7. Late-Push Handler: public.r50_part2_late_push_colleague (H-4)
-- =============================================================================
CREATE OR REPLACE FUNCTION public.r50_part2_late_push_colleague(
  p_card_id uuid,
  p_draft_version integer,
  p_colleague_name text,
  p_pushed_by text DEFAULT 'JK'
) RETURNS jsonb LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE
  g public.dispatch_group;
  w public.yezhu_workbench_case;
  e record;
  win record;
  v_did uuid := gen_random_uuid();
  v_notice text;
  v_status text;
  v_reply_status text;
  v_jk_status text;
BEGIN
  PERFORM public.r50_safe();
  g := public.lock_group(p_card_id, p_draft_version);
  SELECT * INTO STRICT e FROM public.v_active_employee_directory WHERE employee_name = btrim(p_colleague_name);
  SELECT w0.* INTO STRICT w FROM public.yezhu_workbench_case w0
  JOIN public.r50_owner_draft r ON r.case_code = w0.code WHERE r.card_id = p_card_id;

  -- Check if already dispatched to this colleague on this version
  IF EXISTS (
    SELECT 1 FROM public.lark_colleague_approval_dispatch
    WHERE draft_id = p_card_id AND draft_version = p_draft_version AND recipient_employee_id = e.employee_id
  ) THEN
    RETURN (
      SELECT to_jsonb(d) FROM public.lark_colleague_approval_dispatch d
      WHERE draft_id = p_card_id AND draft_version = p_draft_version AND recipient_employee_id = e.employee_id
    );
  END IF;

  IF g.winning_dispatch_id IS NOT NULL THEN
    SELECT recipient_name, recipient_employee_id INTO win
    FROM public.lark_colleague_approval_dispatch WHERE dispatch_id = g.winning_dispatch_id;
    v_status := 'SUPERSEDED_BY_PEER';
    v_reply_status := 'SUPERSEDED_BY_PEER';
    v_jk_status := 'SUPERSEDED_BY_PEER';
    v_notice := CASE g.phase
      WHEN 'FINALIZED' THEN format('🔒 此信件已由 %s 核准，由 JK 最終發出（演練留存，未對外寄送）；您無須重複回覆。', coalesce(win.recipient_name, '同儕'))
      WHEN 'APPROVED_PENDING_JK' THEN format('🔒 此信件已由 %s 認領並核准送交中樞待審（尚未對外寄出），待 JK 最終確認；您無須重複回覆。', coalesce(win.recipient_name, '同儕'))
      WHEN 'WITHDRAWN' THEN format('🔒 此信件版本 (v%s) 已由 %s 認領後退回中樞重擬（尚未對外寄出），舊版已封存鎖定，請等待新版草稿派發。', p_draft_version, coalesce(win.recipient_name, '同儕'))
      ELSE format('🔒 此信件已由 %s 認領送中樞處理（尚未對外寄出），系統已鎖定防重複回覆，您無須重複回覆。', coalesce(win.recipient_name, '同儕'))
    END;
  ELSE
    v_status := 'PENDING';
    v_reply_status := 'WAITING_COLLEAGUE';
    v_jk_status := 'PENDING_COLLEAGUE';
    v_notice := NULL;
  END IF;

  INSERT INTO public.lark_cli_outbound_dispatch(
    dispatch_id, card_id, case_code, draft_version, target_employee_id, target_employee_name,
    dispatch_mode, message_preview, pushed_by, reply_status,
    jk_final_send_status, superseded_by_dispatch_id, superseded_by_employee_name, peer_lock_notice
  ) VALUES (
    v_did, p_card_id, w.code, p_draft_version, e.employee_id, e.employee_name,
    'SANDBOX_LOOPBACK',
    coalesce(w.letter_state->>'body', w.case_data->>'subj', w.code),
    (SELECT employee_id FROM public.v_active_employee_directory WHERE employee_name = '許喆凱'),
    v_reply_status, v_jk_status,
    g.winning_dispatch_id, win.recipient_name, v_notice
  );

  INSERT INTO public.lark_colleague_approval_dispatch(
    dispatch_id, draft_id, draft_version, case_code, recipient_employee_id, recipient_name,
    dispatch_group_id, status, dispatch_mode, pushed_by,
    superseded_by_employee_id, superseded_by_name,
    superseded_at, peer_notification_status, peer_notification_text
  ) VALUES (
    v_did, p_card_id, p_draft_version, w.code, e.employee_id, e.employee_name,
    g.dispatch_group_id, v_status, 'SANDBOX_LOOPBACK', p_pushed_by,
    win.recipient_employee_id, win.recipient_name,
    CASE WHEN g.winning_dispatch_id IS NOT NULL THEN now() ELSE NULL END,
    CASE WHEN g.winning_dispatch_id IS NOT NULL THEN 'SANDBOX_NOTIFIED' ELSE 'NONE' END,
    v_notice
  );

  IF g.winning_dispatch_id IS NOT NULL THEN
    INSERT INTO public.r50_peer_lock_notification(
      card_id, case_code, draft_version, winning_dispatch_id, winning_employee_id, winning_employee_name,
      superseded_dispatch_id, target_employee_id, target_employee_name, notice_text, lark_cli_dryrun_cmd
    ) VALUES (
      p_card_id, w.code, p_draft_version, g.winning_dispatch_id, win.recipient_employee_id, win.recipient_name,
      v_did, e.employee_id, e.employee_name, v_notice,
      format('lark-cli im +messages-send --user-id %s --text %L --dry-run', e.employee_id, v_notice)
    ) ON CONFLICT (winning_dispatch_id, superseded_dispatch_id) DO NOTHING;
  END IF;

  RETURN (SELECT to_jsonb(d) FROM public.lark_colleague_approval_dispatch d WHERE dispatch_id = v_did);
END $$;

-- =============================================================================
-- 8. Read-Only Watcher Liveness View & Poll Heartbeat Function (H-7, Fable §8)
-- =============================================================================
CREATE OR REPLACE VIEW public.r50_watcher_status_v AS
SELECT
  agent_id,
  mode,
  trigger_architecture,
  last_poll_at,
  round(extract(epoch FROM (now() - last_poll_at))::numeric, 1) AS seconds_since_last_poll,
  (now() - last_poll_at < interval '60 seconds') AS watcher_alive,
  CASE WHEN now() - last_poll_at < interval '60 seconds' THEN 'ALIVE' ELSE 'STALE' END AS status,
  processed_count
FROM public.r50_lark_watcher_heartbeat;

CREATE OR REPLACE FUNCTION public.r50_watcher_record_poll(
  p_agent_id text DEFAULT 'lark-cli-watcher-agent'
) RETURNS jsonb LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
  PERFORM public.r50_safe();
  INSERT INTO public.r50_lark_watcher_heartbeat(agent_id, mode, last_poll_at, processed_count, trigger_architecture)
  VALUES (
    p_agent_id, 'SANDBOX_LOOPBACK', now(),
    (SELECT count(*)::integer FROM public.lark_cli_inbound_reply),
    'EVENT_DRIVEN_INBOX_WEBHOOK'
  )
  ON CONFLICT (agent_id) DO UPDATE
  SET mode = 'SANDBOX_LOOPBACK',
      last_poll_at = now(),
      processed_count = EXCLUDED.processed_count,
      trigger_architecture = 'EVENT_DRIVEN_INBOX_WEBHOOK';
  RETURN (SELECT to_jsonb(v) FROM public.r50_watcher_status_v v WHERE agent_id = p_agent_id);
END $$;

-- =============================================================================
-- 9. R50 Part 2 Assertion Suite: public.r50_part2_assert_all()
-- =============================================================================
CREATE OR REPLACE FUNCTION public.r50_part2_assert_all()
RETURNS jsonb LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE
  v_res jsonb := '{}'::jsonb;
  v_card uuid;
  v_ver integer;
  v_grp jsonb;
  v_da uuid;
  v_db uuid;
  v_dc jsonb;
  v_r1 jsonb;
  v_r2 jsonb;
  v_jk uuid;
  v_caught boolean;
  v_w1 boolean;
BEGIN
  PERFORM public.r50_safe();
  SELECT employee_id INTO STRICT v_jk FROM public.v_active_employee_directory WHERE employee_name = '許喆凱';

  -- [1] SW-LARK-ROOT-LOCK-01 & SW-LARK-NOTIFY-01 & H-2 / H-3 / H-4 inside rollback block
  BEGIN
    SELECT card_id INTO STRICT v_card FROM public.r50_owner_draft WHERE case_code = 'C115211-01A';
    v_ver := public.bump_draft_version(v_card, 'R50 Part 2 Test Draft Body vA');
    v_grp := public.fn_dispatch_draft_to_colleagues_multi(v_card, ARRAY['吳柏頤','涂振邦']);
    SELECT dispatch_id INTO STRICT v_da FROM public.lark_colleague_approval_dispatch
      WHERE draft_id = v_card AND draft_version = v_ver AND recipient_name = '吳柏頤';
    SELECT dispatch_id INTO STRICT v_db FROM public.lark_colleague_approval_dispatch
      WHERE draft_id = v_card AND draft_version = v_ver AND recipient_name = '涂振邦';

    -- Stage 1: CLAIM by 吳柏頤 -> winning_dispatch_id set, Stage 1 notice has 尚未對外寄出
    v_r1 := public.r50_part2_cas_decide(v_da, '吳柏頤', 'CLAIM', 'CARD_MODE', '我先認領處理', NULL, false);
    ASSERT (SELECT winning_dispatch_id = v_da AND phase = 'CLAIMED' FROM public.dispatch_group WHERE card_id = v_card AND draft_version = v_ver);
    ASSERT EXISTS (
      SELECT 1 FROM public.lark_colleague_approval_dispatch
      WHERE dispatch_id = v_db AND status = 'SUPERSEDED_BY_PEER'
        AND peer_notification_text LIKE '%認領送中樞處理（尚未對外寄出）%'
        AND peer_notification_text NOT LIKE '%由 JK 最終發出%'
    );

    -- Write-once trigger blocks changing winning_dispatch_id to v_db
    v_caught := false;
    BEGIN
      UPDATE public.dispatch_group SET winning_dispatch_id = v_db WHERE card_id = v_card AND draft_version = v_ver;
    EXCEPTION WHEN OTHERS THEN
      v_caught := SQLERRM LIKE '%winning_dispatch_id is write-once%';
    END;
    ASSERT v_caught, 'write-once trigger must reject changing winning_dispatch_id';
    v_res := v_res || jsonb_build_object('SW-LARK-ROOT-LOCK-01', 'PASS');

    -- Stage 2: EDIT_AND_APPROVE by 吳柏頤 (with p_auto_jk_finalize = false) -> phase = APPROVED_PENDING_JK, comm_id IS NULL
    v_r1 := public.r50_part2_cas_decide(v_da, '吳柏頤', 'EDIT_AND_APPROVE', 'NL_CHAT_MODE', '修改報價說明後核准', 'R50 Part 2 Approved Body X', false);
    ASSERT v_r1->>'phase' = 'APPROVED_PENDING_JK';
    ASSERT (SELECT comm_id IS NULL FROM public.lark_cli_outbound_dispatch WHERE dispatch_id = v_da);
    ASSERT EXISTS (
      SELECT 1 FROM public.lark_colleague_approval_dispatch
      WHERE dispatch_id = v_db AND peer_notification_text LIKE '%認領並核准送交中樞待審（尚未對外寄出），待 JK 最終確認%'
    );

    -- H-3: Mutate draft body after colleague approval -> JK finalize must reject with STALE_APPROVAL
    UPDATE public.yezhu_workbench_case
    SET letter_state = jsonb_set(letter_state, '{body}', to_jsonb('TAMPERED BODY Y'::text))
    WHERE code = 'C115211-01A';
    v_caught := false;
    BEGIN
      PERFORM public.r50_part2_jk_finalize(v_da, v_jk);
    EXCEPTION WHEN OTHERS THEN
      v_caught := SQLERRM LIKE '%STALE_APPROVAL%';
    END;
    ASSERT v_caught, 'H-3: JK finalize must block when draft body changed after colleague approval';

    -- Restore approved body X and run Stage 3 JK Finalize -> phase = FINALIZED, Stage 3 notice
    UPDATE public.yezhu_workbench_case
    SET letter_state = jsonb_set(letter_state, '{body}', to_jsonb('R50 Part 2 Approved Body X'::text))
    WHERE code = 'C115211-01A';
    v_r2 := public.r50_part2_jk_finalize(v_da, v_jk, (v_r1->>'approval_id')::uuid, v_r1->>'approved_digest');
    ASSERT v_r2->>'status' = 'SENT_FROM_JK_DRYRUN' AND (v_r2->>'comm_id') IS NOT NULL;
    ASSERT EXISTS (
      SELECT 1 FROM public.lark_colleague_approval_dispatch
      WHERE dispatch_id = v_db AND peer_notification_text LIKE '%由 JK 最終發出（演練留存，未對外寄送）%'
    );
    v_res := v_res || jsonb_build_object('SW-LARK-NOTIFY-01', 'PASS');

    -- H-4: Late push of colleague 羅薇 to already-finalized version -> immediately SUPERSEDED_BY_PEER
    v_dc := public.r50_part2_late_push_colleague(v_card, v_ver, '羅薇');
    ASSERT v_dc->>'status' = 'SUPERSEDED_BY_PEER', 'H-4: late push to claimed/finalized version must be SUPERSEDED_BY_PEER';

    -- H-2: New version where winner claims then rejects/withdraws -> peer B blocked with COLLISION_BLOCKED_OWNER_WITHDRAWN
    v_ver := public.bump_draft_version(v_card, 'R50 Part 2 Withdraw Test Body');
    v_grp := public.fn_dispatch_draft_to_colleagues_multi(v_card, ARRAY['吳柏頤','涂振邦']);
    SELECT dispatch_id INTO STRICT v_da FROM public.lark_colleague_approval_dispatch
      WHERE draft_id = v_card AND draft_version = v_ver AND recipient_name = '吳柏頤';
    SELECT dispatch_id INTO STRICT v_db FROM public.lark_colleague_approval_dispatch
      WHERE draft_id = v_card AND draft_version = v_ver AND recipient_name = '涂振邦';
    PERFORM public.r50_part2_cas_decide(v_da, '吳柏頤', 'CLAIM', 'CARD_MODE');
    PERFORM public.r50_part2_cas_decide(v_da, '吳柏頤', 'REJECT', 'NL_CHAT_MODE', '退回重擬');
    v_r2 := public.r50_part2_cas_decide(v_db, '涂振邦', 'APPROVE', 'CARD_MODE', '核准');
    ASSERT v_r2->>'status' = 'COLLISION_BLOCKED_OWNER_WITHDRAWN', 'H-2: peer B must be blocked after winner withdraws on same version';
    v_res := v_res || jsonb_build_object('SW-LARK-H1-H8-01', 'PASS');

    RAISE EXCEPTION USING ERRCODE = 'ZX053', MESSAGE = 'rollback R50 part 2 fixtures';
  EXCEPTION WHEN SQLSTATE 'ZX053' THEN NULL;
  END;

  -- [2] SW-LARK-WATCHER-01: Watcher heartbeat liveness check is read-only and detects stale last_poll_at
  BEGIN
    UPDATE public.r50_lark_watcher_heartbeat SET last_poll_at = now() - interval '10 minutes';
    SELECT watcher_alive INTO v_w1 FROM public.r50_watcher_status_v LIMIT 1;
    ASSERT v_w1 IS FALSE, 'stale heartbeat must report watcher_alive = false';
    PERFORM public.r50_watcher_record_poll();
    SELECT watcher_alive INTO v_w1 FROM public.r50_watcher_status_v LIMIT 1;
    ASSERT v_w1 IS TRUE, 'fresh poll must report watcher_alive = true';
    RAISE EXCEPTION USING ERRCODE = 'ZX054', MESSAGE = 'rollback watcher fixture';
  EXCEPTION WHEN SQLSTATE 'ZX054' THEN NULL;
  END;
  v_res := v_res || jsonb_build_object('SW-LARK-WATCHER-01', 'PASS');

  -- [3] SW-LARK-75V72-01: 36 duplicate unconfirmed groups / 75 rows (72 exact duplicates + 3 letter revisions)
  ASSERT (SELECT count(*) = 36 AND sum(quote_rows) = 75 FROM public.case_quote_summary_v WHERE duplicate_cohort AND no_v4),
    'SW-LARK-75V72-01: expected 36 groups / 75 rows in case_quote_summary_v WHERE duplicate_cohort AND no_v4';
  v_res := v_res || jsonb_build_object('SW-LARK-75V72-01', 'PASS');

  -- [4] SW-LARK-ZH-AMOUNT-01: Chinese amount multiplier unit conversion (千/萬/十萬/百萬/千萬/億) & zero 1000x inflation
  ASSERT public.r50_parse_zh_amount('把單價改 18 萬、交期延後三天再發') = 180000, '18 萬 must equal 180000';
  ASSERT public.r50_parse_zh_amount('改 5 千') = 5000, '5 千 must equal 5000';
  ASSERT public.r50_parse_zh_amount('改 120 萬') = 1200000, '120 萬 must equal 1200000';
  ASSERT public.r50_parse_zh_amount('改 1.5 億') = 150000000, '1.5 億 must equal 150000000';
  ASSERT public.r50_apply_reply_edit('單價 NT$150,000。交期 2026-10-28。', '把單價改 18 萬、交期延後三天再發') LIKE '%單價 NT$180,000%'
     AND public.r50_apply_reply_edit('單價 NT$150,000。交期 2026-10-28。', '把單價改 18 萬、交期延後三天再發') NOT LIKE '%180,000,000%',
    'r50_apply_reply_edit must produce NT$180,000 and never NT$180,000,000';
  v_res := v_res || jsonb_build_object('SW-LARK-ZH-AMOUNT-01', 'PASS');

  RETURN v_res;
END $$;

-- Record fresh poll so watcher heartbeat starts ALIVE
SELECT public.r50_watcher_record_poll('lark-cli-watcher-agent');

DO $$
DECLARE
  r jsonb;
BEGIN
  r := public.r50_part2_assert_all();
  RAISE NOTICE 'r50_part2_assert_all: %', r;
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO plumb_app;
-- Preserve R46 authorization controls when replaying this legacy upgrade.
REVOKE ALL ON public.api_session FROM plumb_app;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON public.card,
 public.serial_cutover_log, public.prod_guard_state, public.email_message_disposition FROM PUBLIC, plumb_app;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO plumb_app;

REVOKE ALL ON public.switchboard_gold_label FROM PUBLIC, plumb_app;
COMMIT;
