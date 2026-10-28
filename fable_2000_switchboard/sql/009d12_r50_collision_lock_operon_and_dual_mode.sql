\set ON_ERROR_STOP on
-- This migration has no live transport and may run only on the named clone.
DO $$ BEGIN
  ASSERT current_database() != 'yongxiang_plumb';
  ASSERT current_database() = 'yongxiang_plumb_r39_clone';
  IF current_database() <> 'yongxiang_plumb_r39_clone' THEN
    RAISE EXCEPTION 'R50 collision migration is clone-only';
  END IF;
END $$;
BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '90s';
CREATE OR REPLACE FUNCTION public.r50_guard_legacy_draft_write() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$;
DROP TRIGGER IF EXISTS r50_guard_legacy_draft_write_trg ON public.yezhu_workbench_case;

CREATE OR REPLACE FUNCTION public.r50_safe() RETURNS void LANGUAGE plpgsql AS $$ BEGIN
  ASSERT current_database() != 'yongxiang_plumb';
  ASSERT current_database() = 'yongxiang_plumb_r39_clone';
  IF current_database() <> 'yongxiang_plumb_r39_clone' THEN RAISE EXCEPTION 'R50 is clone-only'; END IF;
END $$;

-- 009d10 uses r50_owner_draft.card_id, not a separate draft table. Keep that
-- identity and the existing CLI dispatch IDs, PM log, and JK dry-run sender.
-- The requested colleague dispatch relation does not exist in the R50 baseline.
CREATE TABLE IF NOT EXISTS public.lark_colleague_approval_dispatch (
  dispatch_id uuid PRIMARY KEY REFERENCES public.lark_cli_outbound_dispatch(dispatch_id),
  draft_id uuid NOT NULL REFERENCES public.r50_owner_draft(card_id),
  draft_version integer NOT NULL CHECK (draft_version > 0),
  case_code text NOT NULL REFERENCES public.yezhu_workbench_case(code),
  recipient_employee_id uuid NOT NULL REFERENCES public.employee(id),
  recipient_name text NOT NULL,
  status text NOT NULL DEFAULT 'PENDING',
  dispatch_mode text NOT NULL DEFAULT 'SANDBOX_LOOPBACK' CHECK (dispatch_mode = 'SANDBOX_LOOPBACK'),
  pushed_by text NOT NULL DEFAULT 'JK',
  reply_text text,
  edited_body text,
  decision_status text,
  approved_at timestamptz,
  comm_id uuid UNIQUE REFERENCES public.client_communication(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.lark_colleague_approval_dispatch
  ADD COLUMN IF NOT EXISTS dispatch_group_id uuid,
  ADD COLUMN IF NOT EXISTS peer_recipient_names text[] DEFAULT '{}'::text[],
  ADD COLUMN IF NOT EXISTS superseded_by_employee_id uuid REFERENCES public.employee(id),
  ADD COLUMN IF NOT EXISTS superseded_by_name text,
  ADD COLUMN IF NOT EXISTS superseded_at timestamptz,
  ADD COLUMN IF NOT EXISTS peer_notification_status text DEFAULT 'NONE',
  ADD COLUMN IF NOT EXISTS peer_notification_text text,
  ADD COLUMN IF NOT EXISTS interaction_mode text DEFAULT 'CARD_MODE',
  ADD COLUMN IF NOT EXISTS inline_deadline_text text,
  ADD COLUMN IF NOT EXISTS drawing_spec_citation text,
  ADD COLUMN IF NOT EXISTS rev_diff_summary text,
  ADD COLUMN IF NOT EXISTS human_decision_prompt text;
ALTER TABLE public.lark_colleague_approval_dispatch
  DROP CONSTRAINT IF EXISTS lark_colleague_approval_dispatch_status_check,
  DROP CONSTRAINT IF EXISTS lark_colleague_approval_dispatch_interaction_mode_check;
ALTER TABLE public.lark_colleague_approval_dispatch
  ADD CONSTRAINT lark_colleague_approval_dispatch_status_check CHECK
    (status IN ('PENDING','CLAIMED','APPROVED','EDITED_APPROVED','REJECTED','SENT_FROM_JK_DRYRUN','SUPERSEDED_BY_PEER')),
  ADD CONSTRAINT lark_colleague_approval_dispatch_interaction_mode_check CHECK
    (interaction_mode IN ('CARD_MODE','NL_CHAT_MODE'));

-- Remove old uniqueness on the pair itself, including a partial PENDING index;
-- retain identity/per-recipient uniqueness and install the precise winner rule.
DO $$ DECLARE r record; BEGIN
  FOR r IN
    SELECT i.indexrelid::regclass AS idx, c.conname
    FROM pg_index i JOIN pg_class t ON t.oid=i.indrelid
    LEFT JOIN pg_constraint c ON c.conindid=i.indexrelid
    WHERE i.indrelid='public.lark_colleague_approval_dispatch'::regclass
      AND i.indisunique AND NOT i.indisprimary AND i.indnkeyatts=2
      AND (SELECT array_agg(a.attname::text ORDER BY a.attname)
           FROM unnest(i.indkey::smallint[]) WITH ORDINALITY k(attnum,n)
           JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=k.attnum
           WHERE k.n<=i.indnkeyatts) = ARRAY['draft_id','draft_version']::text[]
      AND i.indexrelid <> coalesce(to_regclass('public.idx_r50_single_winner_per_draft_version'),0::oid)
  LOOP
    IF r.conname IS NOT NULL THEN
      EXECUTE format('ALTER TABLE public.lark_colleague_approval_dispatch DROP CONSTRAINT %I',r.conname);
    ELSE EXECUTE format('DROP INDEX %s',r.idx); END IF;
  END LOOP;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS idx_r50_dispatch_version_recipient
  ON public.lark_colleague_approval_dispatch(draft_id,draft_version,recipient_employee_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_r50_single_winner_per_draft_version
  ON public.lark_colleague_approval_dispatch(draft_id,draft_version)
  WHERE status IN ('CLAIMED','APPROVED','EDITED_APPROVED','SENT_FROM_JK_DRYRUN');
CREATE INDEX IF NOT EXISTS idx_r50_dispatch_group
  ON public.lark_colleague_approval_dispatch(dispatch_group_id);
-- Newer CLI builds also consult this compact claim registry. Use the same
-- winner there so either baseline's JK sender can safely finalize a CAS result.
CREATE TABLE IF NOT EXISTS public.r50_draft_claim (
  card_id uuid NOT NULL REFERENCES public.r50_owner_draft(card_id),
  draft_version integer NOT NULL CHECK(draft_version>0),
  winning_dispatch_id uuid NOT NULL REFERENCES public.lark_cli_outbound_dispatch(dispatch_id),
  claimed_at timestamptz NOT NULL DEFAULT now(),
  mode text NOT NULL DEFAULT 'SANDBOX_LOOPBACK' CHECK(mode='SANDBOX_LOOPBACK'),
  PRIMARY KEY(card_id,draft_version)
);
INSERT INTO public.r50_draft_claim(card_id,draft_version,winning_dispatch_id)
SELECT draft_id,draft_version,dispatch_id FROM public.lark_colleague_approval_dispatch
WHERE status IN ('CLAIMED','APPROVED','EDITED_APPROVED','SENT_FROM_JK_DRYRUN') ON CONFLICT DO NOTHING;
DO $$ BEGIN ASSERT NOT EXISTS(SELECT 1 FROM public.lark_colleague_approval_dispatch d
  JOIN public.r50_draft_claim c ON c.card_id=d.draft_id AND c.draft_version=d.draft_version
  WHERE d.status IN ('CLAIMED','APPROVED','EDITED_APPROVED','SENT_FROM_JK_DRYRUN')
    AND d.dispatch_id<>c.winning_dispatch_id),'legacy and colleague claim winners disagree'; END $$;

CREATE TABLE IF NOT EXISTS public.r50_operon_workflow_context (
  draft_id uuid NOT NULL REFERENCES public.r50_owner_draft(card_id),
  draft_version integer NOT NULL,
  workflow_type text NOT NULL,
  arrived_at timestamptz,
  logged_at timestamptz NOT NULL DEFAULT now(),
  deadline_at timestamptz,
  inline_deadline_text text,
  drawing_spec_citation text,
  rev_diff_summary text,
  changes_count integer CHECK (changes_count >= 0),
  confidence_score numeric(3,2) CHECK (confidence_score BETWEEN 0 AND 1),
  human_decision_prompt text NOT NULL,
  is_sandbox_demo boolean NOT NULL DEFAULT false,
  PRIMARY KEY(draft_id,draft_version),
  CHECK (arrived_at IS NULL OR logged_at >= arrived_at)
);

-- Preserve immutable historical events and the legacy CLI's lowercase modes.
-- New CAS events use the public CARD_MODE / NL_CHAT_MODE vocabulary.
ALTER TABLE public.colleague_agent_usage_event
  ADD COLUMN IF NOT EXISTS interaction_mode text DEFAULT 'CARD_MODE',
  ADD COLUMN IF NOT EXISTS event_detail jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE public.colleague_agent_usage_event ALTER COLUMN interaction_mode SET DEFAULT 'CARD_MODE';
ALTER TABLE public.colleague_agent_usage_event
  DROP CONSTRAINT IF EXISTS colleague_agent_usage_event_interaction_mode_check,
  DROP CONSTRAINT IF EXISTS colleague_agent_usage_event_event_type_check;
ALTER TABLE public.colleague_agent_usage_event
  ADD CONSTRAINT colleague_agent_usage_event_interaction_mode_check CHECK
    (interaction_mode IN ('CARD_MODE','NL_CHAT_MODE','card_action','nl_chat','system_dispatch')),
  ADD CONSTRAINT colleague_agent_usage_event_event_type_check CHECK
    (event_type IN ('dispatch','claim','approve','edit_and_approve','reject','handoff','agent_query',
                   'blocked_duplicate_responder','COLLISION_BLOCKED'));
ALTER TABLE public.colleague_agent_usage_event ADD COLUMN IF NOT EXISTS tokens_source text NOT NULL DEFAULT 'ESTIMATED';
CREATE OR REPLACE VIEW public.r50_colleague_agent_usage_rollup_v AS
SELECT e.employee_id,e.employee_name,e.department,
  count(u.event_id) FILTER (WHERE event_type='dispatch') dispatches_received,
  count(u.event_id) FILTER (WHERE event_type IN ('approve','edit_and_approve')) approvals_count,
  count(u.event_id) FILTER (WHERE event_type='edit_and_approve') edits_count,
  count(u.event_id) FILTER (WHERE event_type='handoff') handoffs_count,
  count(u.event_id) FILTER (WHERE event_type='agent_query') agent_queries_count,
  count(u.event_id) FILTER (WHERE event_type<>'dispatch') total_interactions,
  round(avg(u.response_seconds) FILTER (WHERE event_type<>'dispatch'),1) avg_response_seconds,
  max(u.created_at) last_active_at,
  count(u.event_id) FILTER (WHERE event_type<>'dispatch' AND u.interaction_mode IN ('CARD_MODE','card_action')) card_actions_count,
  count(u.event_id) FILTER (WHERE event_type<>'dispatch' AND u.interaction_mode IN ('NL_CHAT_MODE','nl_chat')) nl_chat_turns_count,
  coalesce(sum(u.tokens_used) FILTER (WHERE event_type<>'dispatch'),0) tokens_used,
  count(u.event_id) FILTER (WHERE event_type<>'dispatch' AND u.interaction_mode IN ('NL_CHAT_MODE','nl_chat')) nl_chat_count,
  count(u.event_id) FILTER (WHERE event_type IN ('COLLISION_BLOCKED','blocked_duplicate_responder')) collision_saves_count,
  'SANDBOX_OBSERVED'::text AS dataset_kind,
  coalesce(sum(u.tokens_used) FILTER (WHERE event_type<>'dispatch' AND u.tokens_source='MEASURED_MODEL_USAGE'),0)::bigint AS tokens_measured,
  coalesce(sum(u.tokens_used) FILTER (WHERE event_type<>'dispatch' AND u.tokens_source<>'MEASURED_MODEL_USAGE'),0)::bigint AS tokens_estimated,
  CASE WHEN count(u.event_id) FILTER (WHERE event_type<>'dispatch' AND u.tokens_used>0)>0 THEN 'SANDBOX_OBSERVED' ELSE 'NONE' END AS tokens_coverage,
  count(u.event_id) FILTER (WHERE event_type IN ('claim','approve','edit_and_approve')) AS claimed_to_hub_count
FROM public.v_active_employee_directory e
LEFT JOIN public.colleague_agent_usage_event u USING(employee_id)
GROUP BY e.employee_id,e.employee_name,e.department;
-- Preserve each existing view's column order for dependent UI/API consumers.
-- Earlier incremental R50 builds put nl_chat_count on either side of tokens_used.
DO $$ DECLARE view_name text; columns_sql text; BEGIN
  FOREACH view_name IN ARRAY ARRAY['colleague_agent_usage_summary_v','lark_agent_usage_stats'] LOOP
    SELECT string_agg(format('%I',a.attname),',' ORDER BY
      coalesce(old.attnum::integer,1000+a.attnum)) INTO columns_sql
    FROM pg_attribute a LEFT JOIN pg_attribute old ON old.attrelid=to_regclass('public.'||view_name)
      AND old.attname=a.attname AND old.attnum>0 AND NOT old.attisdropped
    WHERE a.attrelid='public.r50_colleague_agent_usage_rollup_v'::regclass AND a.attnum>0 AND NOT a.attisdropped;
    EXECUTE format('CREATE OR REPLACE VIEW public.%I AS SELECT %s FROM public.r50_colleague_agent_usage_rollup_v',view_name,columns_sql);
  END LOOP;
END $$;

-- All entry points must lock workbench -> draft -> dispatch. Taking individual
-- peer rows before the group lock can deadlock two simultaneous responders.
-- Apply only these small ordering changes to the existing 009d10 functions.
DO $$ DECLARE definition text; old text; replacement text; signature text; BEGIN
  replacement:=$new$SELECT * INTO STRICT d FROM public.lark_cli_outbound_dispatch WHERE dispatch_id=p_dispatch_id;
 -- R50 CAS lock order: case then group then peer.
 PERFORM 1 FROM public.yezhu_workbench_case WHERE code=d.case_code FOR UPDATE;
 PERFORM 1 FROM public.r50_owner_draft WHERE card_id=d.card_id FOR UPDATE;
 SELECT * INTO STRICT d FROM public.lark_cli_outbound_dispatch WHERE dispatch_id=p_dispatch_id FOR UPDATE;$new$;
  FOREACH signature IN ARRAY ARRAY['public.lark_cli_ingest_reply(text,uuid,uuid,text)',
    'public.jk_final_send_and_sync_pm_db(uuid,uuid)'] LOOP
    definition:=pg_get_functiondef(signature::regprocedure);
    IF position('R50 CAS lock order: case then group then peer.' IN definition)=0 THEN
      old:=substring(definition FROM 'SELECT \* INTO STRICT d FROM (?:public\.)?lark_cli_outbound_dispatch WHERE dispatch_id=p_dispatch_id(?: FOR UPDATE)?;');
      IF old IS NOT NULL THEN
        -- Replace only the initial read, preserving later validation and audit code.
        definition:=overlay(definition PLACING replacement FROM position(old IN definition) FOR length(old));
        EXECUTE definition;
      END IF;
    END IF;
  END LOOP;
  definition:=pg_get_functiondef('public.lark_cli_ingest_reply(text,uuid,uuid,text)'::regprocedure);
  IF position('grouped colleague dispatch requires CAS' IN definition)=0 THEN
    old:='SELECT * INTO STRICT d FROM public.lark_cli_outbound_dispatch WHERE dispatch_id=p_dispatch_id FOR UPDATE;';
    IF position(old IN definition)>0 THEN
      definition:=overlay(definition PLACING old||E'\n IF EXISTS(SELECT 1 FROM public.lark_colleague_approval_dispatch WHERE dispatch_id=p_dispatch_id) THEN\n  RAISE EXCEPTION ''grouped colleague dispatch requires CAS'';\n END IF;' FROM position(old IN definition) FOR length(old));
      EXECUTE definition;
    END IF;
  END IF;
  -- Raw ingress and CAS share the same lock order and draft claim state.
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
  SELECT array_agg(recipient_name ORDER BY recipient_name),min(dispatch_group_id::text)::uuid
    INTO existing_names,gid FROM public.lark_colleague_approval_dispatch WHERE draft_id=p_draft_id AND draft_version=ver;
  IF existing_names IS NOT NULL THEN
    IF existing_names<>names THEN RAISE EXCEPTION 'recipient set already dispatched for this draft version'; END IF;
  ELSE
    IF EXISTS(SELECT 1 FROM public.lark_cli_outbound_dispatch WHERE card_id=p_draft_id AND draft_version=ver) THEN
      RAISE EXCEPTION 'version already dispatched through legacy CLI; create a new draft version';
    END IF;
    gid:=gen_random_uuid();
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

CREATE OR REPLACE FUNCTION public.fn_claim_or_approve_lark_dispatch_cas(
  p_dispatch_id uuid,p_actor_name text,p_action text,p_interaction_mode text DEFAULT 'CARD_MODE',
  p_reply_text text DEFAULT NULL,p_edited_body text DEFAULT NULL
) RETURNS jsonb LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE d public.lark_colleague_approval_dispatch; winner public.lark_colleague_approval_dispatch;
  cli public.lark_cli_outbound_dispatch; ctx public.r50_operon_workflow_context;
  a text:=upper(btrim(p_action)); notice text; body text; decision text; rid uuid; cid uuid;
  jk uuid; ver integer; secs integer; amt numeric; days_text text; delay_days integer;
BEGIN
  PERFORM public.r50_safe();
  IF p_interaction_mode IS NULL OR p_interaction_mode NOT IN ('CARD_MODE','NL_CHAT_MODE') THEN
    RAISE EXCEPTION 'invalid interaction_mode';
  END IF;
  a:=CASE a WHEN 'EDITED_APPROVED' THEN 'EDIT_AND_APPROVE' WHEN 'EDIT_APPROVE' THEN 'EDIT_AND_APPROVE'
       WHEN 'APPROVED' THEN 'APPROVE' WHEN 'CLAIMED' THEN 'CLAIM' WHEN 'CHAT' THEN 'QUERY' ELSE a END;
  IF a IS NULL OR a NOT IN ('CLAIM','APPROVE','EDIT_AND_APPROVE','QUERY') THEN RAISE EXCEPTION 'invalid action'; END IF;
  -- Initial read identifies the lock group only; every decision uses reread rows.
  SELECT * INTO STRICT d FROM public.lark_colleague_approval_dispatch WHERE dispatch_id=p_dispatch_id;
  SELECT coalesce((letter_state->>'version')::integer,1) INTO STRICT ver
    FROM public.yezhu_workbench_case WHERE code=d.case_code FOR UPDATE;
  PERFORM 1 FROM public.r50_owner_draft WHERE card_id=d.draft_id FOR UPDATE;
  PERFORM 1 FROM public.lark_cli_outbound_dispatch WHERE card_id=d.draft_id AND draft_version=d.draft_version
    ORDER BY dispatch_id FOR UPDATE;
  PERFORM 1 FROM public.lark_colleague_approval_dispatch WHERE draft_id=d.draft_id AND draft_version=d.draft_version
    ORDER BY dispatch_id FOR UPDATE;
  SELECT * INTO STRICT d FROM public.lark_colleague_approval_dispatch WHERE dispatch_id=p_dispatch_id;
  IF p_actor_name IS DISTINCT FROM d.recipient_name THEN RAISE EXCEPTION 'wrong sender'; END IF;
  IF NOT EXISTS(SELECT 1 FROM public.v_active_employee_directory
    WHERE employee_id=d.recipient_employee_id AND employee_name=p_actor_name) THEN RAISE EXCEPTION 'inactive sender'; END IF;
  SELECT * INTO winner FROM public.lark_colleague_approval_dispatch
    WHERE draft_id=d.draft_id AND draft_version=d.draft_version AND dispatch_id<>p_dispatch_id
      AND status IN ('CLAIMED','APPROVED','EDITED_APPROVED','SENT_FROM_JK_DRYRUN');
  IF NOT FOUND THEN
    SELECT g.* INTO winner FROM public.r50_draft_claim c
      JOIN public.lark_colleague_approval_dispatch g ON g.dispatch_id=c.winning_dispatch_id
      WHERE c.card_id=d.draft_id AND c.draft_version=d.draft_version AND c.winning_dispatch_id<>p_dispatch_id;
  END IF;
  IF winner.dispatch_id IS NOT NULL OR d.status='SUPERSEDED_BY_PEER' THEN
    notice:=coalesce(d.peer_notification_text,
      format('🔒 此信件已由 %s 核准發出，系統已鎖定防重複回覆，您無須重複回覆。',coalesce(winner.recipient_name,d.superseded_by_name)));
    IF d.status='PENDING' AND winner.dispatch_id IS NOT NULL THEN
      UPDATE public.lark_colleague_approval_dispatch SET status='SUPERSEDED_BY_PEER',
        superseded_by_employee_id=winner.recipient_employee_id,superseded_by_name=winner.recipient_name,
        superseded_at=now(),peer_notification_status='SANDBOX_NOTIFIED',peer_notification_text=notice,updated_at=now()
        WHERE dispatch_id=p_dispatch_id;
    END IF;
    INSERT INTO public.colleague_agent_usage_event(employee_id,dispatch_id,event_key,event_type,
      interaction_mode,response_seconds,event_detail)
    VALUES(d.recipient_employee_id,p_dispatch_id,'cas:collision:'||gen_random_uuid(),'COLLISION_BLOCKED',
      p_interaction_mode,greatest(0,extract(epoch FROM clock_timestamp()-d.created_at)::integer),
      jsonb_build_object('actor_name',p_actor_name,'action',a,'reply_text',p_reply_text,
        'winner_name',coalesce(winner.recipient_name,d.superseded_by_name),'notice',notice));
    RETURN jsonb_build_object('status','COLLISION_BLOCKED_SUPERSEDED_BY_PEER','dispatch_id',p_dispatch_id,
      'peer_notification_text',notice,'comm_id',NULL,'external_messages_sent',0);
  END IF;
  IF ver<>d.draft_version THEN RAISE EXCEPTION 'stale draft_version'; END IF;
  SELECT * INTO STRICT cli FROM public.lark_cli_outbound_dispatch WHERE dispatch_id=p_dispatch_id;
  IF d.status='SENT_FROM_JK_DRYRUN' THEN
    IF a IN ('APPROVE','EDIT_AND_APPROVE') AND
      (p_reply_text IS NULL OR p_reply_text IS NOT DISTINCT FROM d.reply_text) AND
      (p_edited_body IS NULL OR p_edited_body IS NOT DISTINCT FROM d.edited_body) THEN
      RETURN to_jsonb(d)||jsonb_build_object('idempotent',true,'external_messages_sent',0);
    END IF;
    RAISE EXCEPTION 'dispatch already finalized';
  END IF;
  IF a='QUERY' THEN
    INSERT INTO public.colleague_agent_usage_event(employee_id,dispatch_id,event_key,event_type,interaction_mode,event_detail)
    VALUES(d.recipient_employee_id,p_dispatch_id,'cas:query:'||gen_random_uuid(),'agent_query',p_interaction_mode,
      jsonb_build_object('reply_text',p_reply_text));
    RETURN to_jsonb(d)||jsonb_build_object('external_messages_sent',0);
  END IF;
  IF a='CLAIM' AND d.status='CLAIMED' THEN RETURN to_jsonb(d)||jsonb_build_object('idempotent',true); END IF;
  body:=nullif(btrim(p_edited_body),'');
  -- Supported NL instructions are converted to concrete client-facing text using r50_parse_zh_amount.
  -- Other edit instructions require an explicit reviewed p_edited_body.
  IF body IS NULL AND p_interaction_mode='NL_CHAT_MODE' AND coalesce(p_reply_text,'') ~ '(改|延後)' AND a<>'CLAIM' THEN
    amt:=public.r50_parse_zh_amount(p_reply_text);
    days_text:=substring(p_reply_text FROM '交期延後\s*([0-9]+|一|二|兩|三|四|五|六|七|八|九|十)\s*天');
    IF amt IS NULL AND days_text IS NULL THEN
      RAISE EXCEPTION 'p_edited_body required for this NL edit';
    END IF;
    IF days_text IS NOT NULL AND amt IS NULL AND p_reply_text !~ '再發[。！! ]*$' THEN
      RAISE EXCEPTION 'p_edited_body required for this NL edit';
    END IF;
    body:=cli.message_preview;
    IF amt IS NOT NULL THEN
      IF body ~ '單價[：:\s]*(?:NT\$|TWD|\$)?\s*[0-9,]+(?:\.[0-9]+)?(?:\s*(?:千萬|百萬|十萬|億|萬|千|百|十))?(?:\s*元)?' THEN
        body:=regexp_replace(
          body,
          '單價[：:\s]*(?:NT\$|TWD|\$)?\s*[0-9,]+(?:\.[0-9]+)?(?:\s*(?:千萬|百萬|十萬|億|萬|千|百|十))?(?:\s*元)?',
          '單價 NT$'||to_char(amt,'FM999,999,999,990'),
          'g'
        );
      ELSIF body ~ '單價[^\n，；;。]*' THEN
        body:=regexp_replace(
          body,
          '單價[^\n，；;。]*',
          '單價 NT$'||to_char(amt,'FM999,999,999,990'),
          'g'
        );
      ELSE
        body:=body||E'\n追加工項單價 NT$'||to_char(amt,'FM999,999,999,990')||'。';
      END IF;
    END IF;
    IF days_text IS NOT NULL THEN
      SELECT * INTO STRICT ctx FROM public.r50_operon_workflow_context WHERE draft_id=d.draft_id AND draft_version=d.draft_version;
      IF ctx.deadline_at IS NULL THEN RAISE EXCEPTION 'reviewed delivery date required for NL deadline edit'; END IF;
      delay_days:=CASE days_text WHEN '一' THEN 1 WHEN '二' THEN 2 WHEN '兩' THEN 2 WHEN '三' THEN 3 WHEN '四' THEN 4 WHEN '五' THEN 5
        WHEN '六' THEN 6 WHEN '七' THEN 7 WHEN '八' THEN 8 WHEN '九' THEN 9 WHEN '十' THEN 10 ELSE days_text::integer END;
      IF body ~ '交期[^\n，,；;。]*' THEN
        body:=regexp_replace(body,'交期[^\n，,；;。]*','交期 '||
          to_char((ctx.deadline_at AT TIME ZONE 'Asia/Taipei')::date+delay_days,'YYYY-MM-DD')||'（順延 '||delay_days||' 天）','g');
      ELSE
        body:=body||E'\n交期 '||to_char((ctx.deadline_at AT TIME ZONE 'Asia/Taipei')::date+delay_days,'YYYY-MM-DD')||'（順延 '||delay_days||' 天）。';
      END IF;
    END IF;
    a:='EDIT_AND_APPROVE';
  END IF;
  IF a='EDIT_AND_APPROVE' AND body IS NULL THEN RAISE EXCEPTION 'nonempty p_edited_body required'; END IF;
  IF a='CLAIM' AND p_edited_body IS NOT NULL THEN RAISE EXCEPTION 'CLAIM cannot edit the draft'; END IF;
  IF a='APPROVE' AND body IS NOT NULL THEN a:='EDIT_AND_APPROVE'; END IF;
  INSERT INTO public.r50_draft_claim(card_id,draft_version,winning_dispatch_id)
    VALUES(d.draft_id,d.draft_version,p_dispatch_id) ON CONFLICT DO NOTHING;
  IF (SELECT winning_dispatch_id FROM public.r50_draft_claim WHERE card_id=d.draft_id AND draft_version=d.draft_version)
      IS DISTINCT FROM p_dispatch_id THEN RAISE EXCEPTION 'first-claim CAS invariant violated'; END IF;
  decision:=CASE a WHEN 'CLAIM' THEN 'CLAIMED' WHEN 'APPROVE' THEN 'APPROVED' ELSE 'EDITED_APPROVED' END;
  UPDATE public.lark_colleague_approval_dispatch SET status=decision,decision_status=decision,
    interaction_mode=p_interaction_mode,reply_text=p_reply_text,edited_body=body,
    approved_at=CASE WHEN a<>'CLAIM' THEN now() ELSE NULL END,updated_at=now() WHERE dispatch_id=p_dispatch_id;
  notice:=format('🔒 此信件已由 %s 核准發出，系統已鎖定防重複回覆，您無須重複回覆。',p_actor_name);
  UPDATE public.lark_colleague_approval_dispatch SET status='SUPERSEDED_BY_PEER',
    superseded_by_employee_id=d.recipient_employee_id,superseded_by_name=p_actor_name,superseded_at=now(),
    peer_notification_status='SANDBOX_NOTIFIED',peer_notification_text=notice,updated_at=now()
    WHERE draft_id=d.draft_id AND draft_version=d.draft_version AND dispatch_id<>p_dispatch_id AND status='PENDING';
  -- Mirror the lock into the existing CLI workflow, so its sender cannot bypass it.
  UPDATE public.lark_cli_outbound_dispatch SET reply_status='SUPERSEDED_BY_PEER',
    jk_final_send_status='SUPERSEDED_BY_PEER',superseded_by_dispatch_id=p_dispatch_id,
    superseded_by_employee_name=p_actor_name,peer_lock_notice=notice,updated_at=now()
    WHERE card_id=d.draft_id AND draft_version=d.draft_version AND dispatch_id<>p_dispatch_id
      AND reply_status='WAITING_COLLEAGUE';
  INSERT INTO public.r50_peer_lock_notification(card_id,case_code,draft_version,winning_dispatch_id,
    winning_employee_id,winning_employee_name,superseded_dispatch_id,target_employee_id,target_employee_name,
    notice_text,lark_cli_dryrun_cmd)
  SELECT d.draft_id,d.case_code,d.draft_version,p_dispatch_id,d.recipient_employee_id,p_actor_name,
    p.dispatch_id,p.recipient_employee_id,p.recipient_name,notice,
    format('lark-cli im +messages-send --user-id %s --text %L --dry-run',p.recipient_employee_id,notice)
  FROM public.lark_colleague_approval_dispatch p WHERE p.draft_id=d.draft_id AND p.draft_version=d.draft_version
    AND p.status='SUPERSEDED_BY_PEER' ON CONFLICT(winning_dispatch_id,superseded_dispatch_id) DO UPDATE
    SET notice_text=excluded.notice_text,lark_cli_dryrun_cmd=excluded.lark_cli_dryrun_cmd;
  secs:=greatest(0,extract(epoch FROM clock_timestamp()-d.created_at)::integer);
  IF a<>'CLAIM' THEN
    INSERT INTO public.lark_cli_inbound_reply(lark_message_id,dispatch_id,sender_employee_id,sender_name,
      raw_reply_text,parsed_action,edited_body,verified_assignee,draft_version_matched,response_seconds,interaction_mode)
    VALUES('r50-cas:approval:'||p_dispatch_id,p_dispatch_id,d.recipient_employee_id,p_actor_name,
      coalesce(p_reply_text,CASE a WHEN 'APPROVE' THEN '核准' ELSE '修改後核准' END),
      CASE a WHEN 'APPROVE' THEN 'approve' ELSE 'edit_and_approve' END,body,true,true,secs,
      CASE p_interaction_mode WHEN 'CARD_MODE' THEN 'card_action' ELSE 'nl_chat' END) RETURNING reply_id INTO rid;
    UPDATE public.lark_cli_outbound_dispatch SET
      reply_status=CASE a WHEN 'APPROVE' THEN 'APPROVED' ELSE 'EDITED_AND_APPROVED' END,
      jk_final_send_status='READY_FOR_JK_SEND',updated_at=now() WHERE dispatch_id=p_dispatch_id;
  END IF;
  INSERT INTO public.colleague_agent_usage_event(employee_id,dispatch_id,reply_id,event_key,event_type,
    interaction_mode,response_seconds,tokens_used,event_detail)
  VALUES(d.recipient_employee_id,p_dispatch_id,rid,'cas:'||lower(decision)||':'||p_dispatch_id,
    CASE a WHEN 'CLAIM' THEN 'claim' WHEN 'APPROVE' THEN 'approve' ELSE 'edit_and_approve' END,
    p_interaction_mode,secs,CASE p_interaction_mode WHEN 'CARD_MODE' THEN 60 ELSE greatest(120,length(coalesce(p_reply_text,''))*8) END,
    jsonb_build_object('reply_text',p_reply_text,'edited_body',body,'decision_status',decision));
  IF a<>'CLAIM' THEN
    SELECT employee_id INTO STRICT jk FROM public.v_active_employee_directory WHERE employee_name='許喆凱';
    cid:=public.jk_final_send_and_sync_pm_db(p_dispatch_id,jk);
    UPDATE public.lark_colleague_approval_dispatch SET status='SENT_FROM_JK_DRYRUN',comm_id=cid,updated_at=now()
      WHERE dispatch_id=p_dispatch_id;
  END IF;
  SELECT * INTO STRICT d FROM public.lark_colleague_approval_dispatch WHERE dispatch_id=p_dispatch_id;
  RETURN to_jsonb(d)||jsonb_build_object('external_messages_sent',0);
END $$;

CREATE OR REPLACE VIEW public.operon_inbox_workflow_matrix_v AS
SELECT d.case_code,coalesce(w.letter_state->>'subj',w.case_data->>'subj') AS subject,
  ctx.workflow_type AS arrives_workflow_type,ctx.inline_deadline_text AS arrives_inline_deadline,
  ctx.drawing_spec_citation AS draft_drawing_citation,ctx.rev_diff_summary AS draft_rev_diff_badge,
  ctx.changes_count AS draft_changes_count,ctx.confidence_score AS draft_confidence_score,
  ctx.human_decision_prompt AS person_decides_prompt,
  array_agg(d.recipient_name ORDER BY d.recipient_name) AS multi_assignees,
  max(d.recipient_name) FILTER(WHERE d.status IN ('CLAIMED','APPROVED','EDITED_APPROVED','SENT_FROM_JK_DRYRUN')) AS lock_winner_name,
  coalesce(array_agg(d.recipient_name ORDER BY d.recipient_name) FILTER(WHERE d.status='SUPERSEDED_BY_PEER'),'{}'::text[]) AS superseded_peers,
  CASE WHEN bool_or(d.status IN ('CLAIMED','APPROVED','EDITED_APPROVED','SENT_FROM_JK_DRYRUN')) THEN
    '🔒 已由 '||max(d.recipient_name) FILTER(WHERE d.status IN ('CLAIMED','APPROVED','EDITED_APPROVED','SENT_FROM_JK_DRYRUN'))||' 認領 · 同儕防重複回覆已鎖定'
    ELSE '待同事認領 · First-Claim CAS' END AS lock_status_badge,
  coalesce(max(d.interaction_mode) FILTER(WHERE d.status IN ('CLAIMED','APPROVED','EDITED_APPROVED','SENT_FROM_JK_DRYRUN')),'PENDING') AS interaction_mode_used
FROM public.lark_colleague_approval_dispatch d
JOIN public.yezhu_workbench_case w ON w.code=d.case_code
JOIN public.r50_operon_workflow_context ctx ON ctx.draft_id=d.draft_id AND ctx.draft_version=d.draft_version
GROUP BY d.draft_id,d.draft_version,d.case_code,w.letter_state,w.case_data,ctx.workflow_type,
  ctx.inline_deadline_text,ctx.drawing_spec_citation,ctx.rev_diff_summary,ctx.changes_count,
  ctx.confidence_score,ctx.human_decision_prompt;

CREATE OR REPLACE VIEW public.operon_workflow_kpis_v AS
WITH workflow AS (
  SELECT ctx.*,win.final_sent_at FROM public.r50_operon_workflow_context ctx
  LEFT JOIN LATERAL (SELECT c.final_sent_at FROM public.lark_colleague_approval_dispatch d
    JOIN public.lark_cli_outbound_dispatch c USING(dispatch_id)
    WHERE d.draft_id=ctx.draft_id AND d.draft_version=ctx.draft_version AND d.status='SENT_FROM_JK_DRYRUN') win ON true
)
SELECT round(avg(extract(epoch FROM logged_at-arrived_at)),2) AS time_from_arrival_to_logging_sec,
  count(*) FILTER(WHERE deadline_at IS NOT NULL AND coalesce(final_sent_at,now())>deadline_at) AS deadlines_missed_count,
  round(avg(extract(epoch FROM final_sent_at-arrived_at)/60)
    FILTER(WHERE workflow_type ~ '(Submittal|Pricing)'),2) AS submittal_pricing_turnaround_min,
  -- Count actual blocked attempts once, rather than all notification recipients.
  (SELECT count(*) FROM public.colleague_agent_usage_event
    WHERE event_type IN ('COLLISION_BLOCKED','blocked_duplicate_responder')) AS multi_assignee_collisions_prevented
FROM workflow;
COMMENT ON VIEW public.operon_workflow_kpis_v IS
  'Clone sandbox telemetry. Durations average known arrival timestamps only; missed deadlines count workflows; collisions count blocked attempts, not notifications.';

-- Realistic sandbox examples use the existing real case identities, with
-- isolated versions. Do not overwrite a person's current working draft/body.
DO $$ DECLARE r record; draft uuid; ver integer; grp jsonb; a uuid; b uuid; res jsonb; BEGIN
  FOR r IN SELECT * FROM (VALUES
    ('C115211-01A','Request for Pricing / 變更計價','NL_CHAT_MODE',22,0.99::numeric),
    ('C115042','Submittal Return / 送審退回','CARD_MODE',4,0.97::numeric)
  ) v(code,workflow_type,imode,changes,confidence) LOOP
    SELECT card_id INTO STRICT draft FROM public.r50_owner_draft WHERE case_code=r.code;
    SELECT coalesce((letter_state->>'version')::integer,1) INTO STRICT ver FROM public.yezhu_workbench_case WHERE code=r.code;
    IF EXISTS(SELECT 1 FROM public.lark_colleague_approval_dispatch WHERE draft_id=draft AND draft_version=ver) THEN CONTINUE; END IF;
    -- Reserve a fresh current version only when the baseline already dispatched it.
    IF EXISTS(SELECT 1 FROM public.lark_cli_outbound_dispatch WHERE card_id=draft AND draft_version=ver) THEN
      SELECT greatest(ver,coalesce(max(draft_version),0))+1 INTO ver FROM public.lark_cli_outbound_dispatch WHERE card_id=draft;
      UPDATE public.yezhu_workbench_case SET letter_state=jsonb_set(coalesce(letter_state,'{}'),'{version}',to_jsonb(ver)) WHERE code=r.code;
    END IF;
    INSERT INTO public.r50_operon_workflow_context(draft_id,draft_version,workflow_type,arrived_at,logged_at,
      deadline_at,inline_deadline_text,drawing_spec_citation,rev_diff_summary,changes_count,confidence_score,
      human_decision_prompt,is_sandbox_demo)
    VALUES(draft,ver,r.workflow_type,now()-interval '16 minutes',now()-interval '15 minutes 42 seconds',
      '2026-10-28 17:00:00+08','⏰ 10/28 17:00（來信內文：請於週三 17:00 前確認）',
      'Sheet 114 · P&ID · Rev D / Quote #115471-01A',
      CASE WHEN r.changes=22 THEN 'Rev C → Rev D · 22 changes' ELSE 'Rev B → Rev C · 4 changes' END,
      r.changes,r.confidence,'決定追加單價與交付日期',true) ON CONFLICT DO NOTHING;
    grp:=public.fn_dispatch_draft_to_colleagues_multi(draft,ARRAY['吳柏頤','涂振邦']);
    SELECT dispatch_id INTO STRICT a FROM public.lark_colleague_approval_dispatch WHERE draft_id=draft AND draft_version=ver AND recipient_name='吳柏頤';
    SELECT dispatch_id INTO STRICT b FROM public.lark_colleague_approval_dispatch WHERE draft_id=draft AND draft_version=ver AND recipient_name='涂振邦';
    res:=public.fn_claim_or_approve_lark_dispatch_cas(a,'吳柏頤','APPROVE',r.imode,
      CASE r.imode WHEN 'NL_CHAT_MODE' THEN '把單價改 18 萬、交期延後三天再發' ELSE '核准' END);
    ASSERT res->>'status'='SENT_FROM_JK_DRYRUN';
    res:=public.fn_claim_or_approve_lark_dispatch_cas(b,'涂振邦','APPROVE','CARD_MODE','核准');
    ASSERT res->>'status'='COLLISION_BLOCKED_SUPERSEDED_BY_PEER';
  END LOOP;
END $$;

-- Restore the baseline's missing legacy links conservatively: every missing
-- quote already has an unmerged case_id; leave quote selection to a human.
-- This is the same pending_human repair used by 009d11, not an assertion change.
INSERT INTO public.quote_case_link(quote_id,case_id,link_role,decided_by)
SELECT q.id,k.id,'pending_human','r50:missing-legacy-link-backfill'
FROM public.quote q JOIN public."case" k ON k.id=q.case_id AND k.merged_into IS NULL
WHERE NOT EXISTS(SELECT 1 FROM public.quote_case_link l WHERE l.quote_id=q.id)
  AND NOT EXISTS(SELECT 1 FROM public.quote_case_link rl JOIN public.quote rq ON rq.id=rl.quote_id JOIN public.r48_quote_source src ON src.record_id=rq.lark_record_id WHERE rl.case_id=k.id);
DO $$ DECLARE r record; assignee uuid; BEGIN
  SELECT employee_id INTO STRICT assignee FROM public.v_active_employee_directory WHERE employee_name='羅薇';
  FOR r IN SELECT DISTINCT k.id,k.org_id FROM public.quote_case_link l JOIN public."case" k ON k.id=l.case_id
    WHERE l.link_role='pending_human' AND NOT EXISTS(SELECT 1 FROM public.card c
      WHERE c.case_id=l.case_id AND c.kind='choose' AND c.state IN ('open','escalated','acted')) LOOP
    PERFORM public.enqueue_card(r.org_id,r.id,assignee,'choose','r50:choose-quote:'||r.id,'[]'::jsonb,
      jsonb_build_object('label','請選擇案件的正式報價','reason','legacy quote linkage requires human decision'));
  END LOOP;
END $$;

-- Retain the previous assertion function for inspection. Run the eight
-- original closed-loop checks explicitly, plus the three requested new checks.
DO $$ BEGIN
  IF to_regprocedure('public.r50_assert_all_before_collision()') IS NULL THEN
    ALTER FUNCTION public.r50_assert_all() RENAME TO r50_assert_all_before_collision;
  END IF;
END $$;
CREATE OR REPLACE FUNCTION public.r50_assert_legacy_eight() RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE actor uuid; cardid uuid; did uuid; rid uuid; rid2 uuid; cid uuid; emp uuid; other uuid;
  ver integer; result jsonb:='{}'; caught boolean;
BEGIN
  PERFORM public.r50_safe();
  SELECT employee_id INTO STRICT actor FROM public.v_active_employee_directory WHERE employee_name='許喆凱';
  BEGIN
    SELECT card_id INTO STRICT cardid FROM public.r50_owner_draft WHERE case_code='C114109';
    UPDATE public.yezhu_workbench_case SET letter_state=jsonb_set(letter_state,'{version}',
      to_jsonb(coalesce((letter_state->>'version')::integer,1)+10000)) WHERE code='C114109';
    did:=public.lark_cli_push_to_colleague(cardid,actor);
    SELECT target_employee_id,draft_version INTO STRICT emp,ver FROM public.lark_cli_outbound_dispatch WHERE dispatch_id=did;
    ASSERT EXISTS(SELECT 1 FROM public.colleague_agent_usage_event WHERE dispatch_id=did AND event_type='dispatch');
    result:=result||jsonb_build_object('SW-LARK-01','PASS');
    rid:=public.lark_cli_ingest_reply('r50-assert:'||did,did,emp,'[v'||ver||'] [CARD:approve] 核准');
    rid2:=public.lark_cli_ingest_reply('r50-assert:'||did,did,emp,'[v'||ver||'] [CARD:approve] 核准');
    ASSERT rid=rid2;
    ASSERT (SELECT count(*)=1 FROM public.colleague_agent_usage_event WHERE reply_id=rid);
    result:=result||jsonb_build_object('SW-LARK-02','PASS');
    SELECT employee_id INTO other FROM public.v_active_employee_directory WHERE employee_id<>emp LIMIT 1;
    caught:=false;
    BEGIN PERFORM public.lark_cli_ingest_reply('wrong:'||did,did,other,'[v'||ver||'] 核准');
    EXCEPTION WHEN OTHERS THEN caught:=SQLERRM='wrong sender'; END;
    ASSERT caught; result:=result||jsonb_build_object('SW-LARK-03','PASS');
    caught:=false;
    BEGIN PERFORM public.lark_cli_ingest_reply('stale:'||did,did,emp,'[v'||(ver-1)||'] 核准');
    EXCEPTION WHEN OTHERS THEN caught:=SQLERRM='missing or stale reply draft_version'; END;
    ASSERT caught;
    UPDATE public.yezhu_workbench_case SET letter_state=jsonb_set(letter_state,'{version}',to_jsonb(ver+1)) WHERE code='C114109';
    caught:=false;
    BEGIN PERFORM public.jk_final_send_and_sync_pm_db(did,actor);
    EXCEPTION WHEN OTHERS THEN caught:=SQLERRM='stale draft_version'; END;
    ASSERT caught;
    UPDATE public.yezhu_workbench_case SET letter_state=jsonb_set(letter_state,'{version}',to_jsonb(ver)) WHERE code='C114109';
    result:=result||jsonb_build_object('SW-LARK-04','PASS');
    cid:=public.jk_final_send_and_sync_pm_db(did,actor);
    ASSERT cid=public.jk_final_send_and_sync_pm_db(did,actor);
    ASSERT EXISTS(SELECT 1 FROM public.client_communication WHERE id=cid AND is_synthetic AND our_employee_id=actor);
    result:=result||jsonb_build_object('SW-LARK-05','PASS');
    ASSERT EXISTS(SELECT 1 FROM public.pm_solution_owner_comm_v WHERE dispatch_id=did
      AND serial_no LIKE '業主往來%' AND colleague_approver_name='吳柏頤');
    result:=result||jsonb_build_object('SW-LARK-06','PASS');
    ASSERT (SELECT count(*) FROM public.colleague_agent_usage_summary_v)=67;
    ASSERT (SELECT count(*) FROM public.lark_agent_usage_stats)=67;
    ASSERT NOT EXISTS(SELECT 1 FROM public.colleague_agent_usage_summary_v WHERE employee_name=chr(23459)||chr(33993));
    ASSERT NOT EXISTS(SELECT 1 FROM public.colleague_agent_usage_summary_v v JOIN public.employee e ON e.id=v.employee_id WHERE e.employment_status<>'active');
    result:=result||jsonb_build_object('SW-LARK-07','PASS');
    ASSERT NOT EXISTS(SELECT 1 FROM public.lark_cli_outbound_dispatch
      WHERE dispatch_mode<>'SANDBOX_LOOPBACK' OR jk_final_send_status='SENT_FROM_JK_LIVE');
    result:=result||jsonb_build_object('SW-LARK-08','PASS');
    RAISE EXCEPTION USING ERRCODE='ZX051',MESSAGE='rollback original eight R50 assertion fixtures';
  EXCEPTION WHEN SQLSTATE 'ZX051' THEN NULL; END;
  RETURN result;
END $$;
CREATE OR REPLACE FUNCTION public.r50_assert_all() RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE old_result jsonb; result jsonb; draft uuid; ver integer; grp jsonb; a uuid; b uuid;
  res jsonb; cid uuid; n bigint; caught boolean; card_before bigint; nl_before bigint;
BEGIN
  PERFORM public.r50_safe();
  old_result:=public.r50_assert_legacy_eight();
  ASSERT NOT EXISTS(SELECT 1 FROM jsonb_each_text(old_result) WHERE value<>'PASS');
  SELECT jsonb_object_agg(key,value) INTO result FROM jsonb_each(old_result)
    WHERE key IN ('SW-LARK-01','SW-LARK-02','SW-LARK-03','SW-LARK-04','SW-LARK-05','SW-LARK-06','SW-LARK-07','SW-LARK-08');
  ASSERT (SELECT count(*)=8 FROM jsonb_each(result));
  BEGIN
    SELECT card_id INTO STRICT draft FROM public.r50_owner_draft WHERE case_code='C115211-01A';
    SELECT coalesce((letter_state->>'version')::integer,1)+20000 INTO STRICT ver
      FROM public.yezhu_workbench_case WHERE code='C115211-01A';
    UPDATE public.yezhu_workbench_case SET letter_state=jsonb_set(coalesce(letter_state,'{}'),'{version}',to_jsonb(ver))
      WHERE code='C115211-01A';
    INSERT INTO public.r50_operon_workflow_context(draft_id,draft_version,workflow_type,arrived_at,logged_at,
      deadline_at,inline_deadline_text,drawing_spec_citation,rev_diff_summary,changes_count,confidence_score,human_decision_prompt)
    VALUES(draft,ver,'Request for Pricing / 變更計價',now()-interval '16 minutes',now()-interval '15 minutes 42 seconds',
      '2026-10-28 17:00+08','⏰ 10/28 17:00','Sheet 114 · P&ID · Rev D / Quote #115471-01A',
      'Rev C → Rev D · 22 changes',22,0.99,'決定追加單價與交付日期');
    grp:=public.fn_dispatch_draft_to_colleagues_multi(draft,ARRAY['吳柏頤','涂振邦']);
    ASSERT grp=public.fn_dispatch_draft_to_colleagues_multi(draft,ARRAY['涂振邦','吳柏頤']);
    ASSERT (SELECT count(*)=2 AND bool_and(status='PENDING') AND count(DISTINCT dispatch_group_id)=1
      FROM public.lark_colleague_approval_dispatch WHERE draft_id=draft AND draft_version=ver);
    SELECT dispatch_id INTO STRICT a FROM public.lark_colleague_approval_dispatch
      WHERE draft_id=draft AND draft_version=ver AND recipient_name='吳柏頤';
    SELECT dispatch_id INTO STRICT b FROM public.lark_colleague_approval_dispatch
      WHERE draft_id=draft AND draft_version=ver AND recipient_name='涂振邦';
    caught:=false;
    BEGIN PERFORM public.fn_claim_or_approve_lark_dispatch_cas(a,'涂振邦','CLAIM');
    EXCEPTION WHEN OTHERS THEN caught:=SQLERRM='wrong sender'; END;
    ASSERT caught;
    SELECT card_actions_count,nl_chat_count INTO card_before,nl_before FROM public.colleague_agent_usage_summary_v
      WHERE employee_name='吳柏頤';
    res:=public.fn_claim_or_approve_lark_dispatch_cas(a,'吳柏頤','CLAIM','CARD_MODE');
    ASSERT res->>'status'='CLAIMED';
    ASSERT NOT EXISTS(SELECT 1 FROM public.lark_cli_outbound_dispatch WHERE dispatch_id=a AND comm_id IS NOT NULL);
    ASSERT EXISTS(SELECT 1 FROM public.lark_colleague_approval_dispatch WHERE dispatch_id=b AND status='SUPERSEDED_BY_PEER'
      AND superseded_by_name='吳柏頤' AND superseded_by_employee_id IS NOT NULL AND superseded_at IS NOT NULL
      AND peer_notification_status='SANDBOX_NOTIFIED'
      AND peer_notification_text='🔒 此信件已由 吳柏頤 核准發出，系統已鎖定防重複回覆，您無須重複回覆。');
    ASSERT public.r50_parse_zh_amount('把單價改 18 萬') = 180000;
    ASSERT public.r50_parse_zh_amount('改 5 千') = 5000;
    ASSERT public.r50_parse_zh_amount('改 120 萬') = 1200000;
    ASSERT public.r50_parse_zh_amount('改 1.5 億') = 150000000;
    res:=public.fn_claim_or_approve_lark_dispatch_cas(b,'涂振邦','APPROVE','NL_CHAT_MODE','我也核准');
    ASSERT res->>'status'='COLLISION_BLOCKED_SUPERSEDED_BY_PEER';
    ASSERT EXISTS(SELECT 1 FROM public.colleague_agent_usage_event WHERE dispatch_id=b AND event_type='COLLISION_BLOCKED');
    caught:=false;
    BEGIN UPDATE public.lark_colleague_approval_dispatch SET status='CLAIMED' WHERE dispatch_id=b;
    EXCEPTION WHEN unique_violation THEN caught:=true; END;
    ASSERT caught,'partial unique index must reject a second winner';
    res:=public.fn_claim_or_approve_lark_dispatch_cas(a,'吳柏頤','APPROVE','NL_CHAT_MODE','把單價改 18 萬、交期延後三天再發');
    ASSERT res->>'status'='SENT_FROM_JK_DRYRUN' AND res->>'decision_status'='EDITED_APPROVED';
    cid:=(res->>'comm_id')::uuid;
    ASSERT EXISTS(SELECT 1 FROM public.client_communication WHERE id=cid AND is_synthetic
      AND body_text LIKE '%NT$180,000%' AND body_text NOT LIKE '%180,000,000%' AND body_text LIKE '%2026-10-31%');
    res:=public.fn_claim_or_approve_lark_dispatch_cas(a,'吳柏頤','APPROVE','NL_CHAT_MODE','把單價改 18 萬、交期延後三天再發');
    ASSERT (res->>'comm_id')::uuid=cid AND (res->>'idempotent')::boolean;
    ASSERT (SELECT count(*)=1 FROM public.lark_cli_outbound_dispatch WHERE card_id=draft AND draft_version=ver AND comm_id IS NOT NULL);
    caught:=false;
    BEGIN PERFORM public.jk_final_send_and_sync_pm_db(b,(SELECT employee_id FROM public.v_active_employee_directory WHERE employee_name='許喆凱'));
    EXCEPTION WHEN OTHERS THEN caught:=SQLERRM LIKE '%superseded by peer responder%'; END;
    ASSERT caught;
    result:=result||jsonb_build_object('SW-LARK-COLLISION-01','PASS');
    ASSERT EXISTS(SELECT 1 FROM public.colleague_agent_usage_summary_v WHERE employee_name='吳柏頤'
      AND card_actions_count=card_before+1 AND nl_chat_count=nl_before+1 AND approvals_count>0 AND edits_count>0);
    ASSERT NOT EXISTS(SELECT 1 FROM public.colleague_agent_usage_summary_v
      WHERE total_interactions<>card_actions_count+nl_chat_count OR collision_saves_count IS NULL);
    ASSERT (SELECT count(*) FROM public.colleague_agent_usage_summary_v)=(SELECT count(*) FROM public.v_active_employee_directory);
    result:=result||jsonb_build_object('SW-LARK-DUALMODE-01','PASS');
    ASSERT EXISTS(SELECT 1 FROM public.operon_inbox_workflow_matrix_v WHERE case_code='C115211-01A'
      AND arrives_workflow_type LIKE '%Pricing%' AND arrives_inline_deadline LIKE '%10/28%'
      AND draft_drawing_citation LIKE '%Sheet 114 · P&ID%' AND draft_rev_diff_badge='Rev C → Rev D · 22 changes'
      AND draft_changes_count=22 AND draft_confidence_score=0.99
      AND person_decides_prompt='決定追加單價與交付日期' AND multi_assignees @> ARRAY['吳柏頤','涂振邦']
      AND lock_winner_name='吳柏頤' AND superseded_peers=ARRAY['涂振邦'] AND interaction_mode_used='NL_CHAT_MODE');
    ASSERT EXISTS(SELECT 1 FROM public.operon_workflow_kpis_v WHERE time_from_arrival_to_logging_sec>=0
      AND deadlines_missed_count>=0 AND submittal_pricing_turnaround_min>=0 AND multi_assignee_collisions_prevented>0);
    result:=result||jsonb_build_object('SW-OPERON-WORKFLOW-01','PASS');
    RAISE EXCEPTION USING ERRCODE='ZX052',MESSAGE='rollback R50 collision assertion fixtures';
  EXCEPTION WHEN SQLSTATE 'ZX052' THEN NULL;
  END;
  IF to_regprocedure('public.r50_part2_assert_all()') IS NOT NULL AND position('r50_assert_all' IN pg_get_functiondef('public.r50_part2_assert_all'::regproc)) = 0 THEN
    result := result || public.r50_part2_assert_all();
  END IF;
  ASSERT (SELECT count(*)>=11 AND bool_and(value='PASS') FROM jsonb_each_text(result));
  RETURN result;
END $$;

UPDATE public.r50_peer_lock_notification
SET lark_cli_dryrun_cmd=format('lark-cli im +messages-send --user-id %s --text %L --dry-run',target_employee_id,notice_text)
WHERE lark_cli_dryrun_cmd IS DISTINCT FROM format('lark-cli im +messages-send --user-id %s --text %L --dry-run',target_employee_id,notice_text);

DO $$ BEGIN
  ASSERT (SELECT count(*)>=11 AND bool_and(value='PASS') FROM jsonb_each_text(public.r50_assert_all()));
  ASSERT (SELECT count(*)=19 AND bool_and(pass) FROM public.master_pre_tuesday_assert_all()),'master gate failed';
END $$;

REVOKE ALL ON public.switchboard_gold_label FROM PUBLIC, plumb_app;
COMMIT;
