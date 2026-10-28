-- Installed transactionally by lark_cli_watcher_agent.ensure_schema(). No transport calls.
DO $$ BEGIN
 ASSERT current_database() != 'yongxiang_plumb';
 IF current_database() <> 'yongxiang_plumb_r39_clone'
    OR current_setting('app.env', true) = 'prod' THEN
  RAISE EXCEPTION 'clone database required';
 END IF;
 PERFORM pg_advisory_xact_lock(508272829);
END $$;

-- Refuse a busy migration atomically, avoiding partial lock acquisition deadlocks
-- with listeners that are already reading this schema.
LOCK TABLE yezhu_workbench_case,r50_owner_draft,lark_cli_outbound_dispatch,
 lark_cli_inbound_reply,colleague_agent_usage_event,r50_collision_interception_log,
 r50_lark_loopback_queue,r50_peer_lock_notification IN ACCESS EXCLUSIVE MODE NOWAIT;

CREATE OR REPLACE FUNCTION r50_safe() RETURNS void LANGUAGE plpgsql AS $$ BEGIN
 ASSERT current_database() != 'yongxiang_plumb';
 IF current_database() <> 'yongxiang_plumb_r39_clone' OR current_setting('app.env',true)='prod' THEN
  RAISE EXCEPTION 'clone database required';
 END IF;
END $$;

ALTER TABLE lark_cli_outbound_dispatch DROP CONSTRAINT lark_cli_outbound_dispatch_reply_status_check;
ALTER TABLE lark_cli_outbound_dispatch ADD CONSTRAINT lark_cli_outbound_dispatch_reply_status_check
 CHECK (reply_status IN ('WAITING_COLLEAGUE','CLAIMED','APPROVED','EDITED_AND_APPROVED','REJECTED','HANDOFF','SUPERSEDED_BY_PEER'));
ALTER TABLE lark_cli_inbound_reply DROP CONSTRAINT lark_cli_inbound_reply_parsed_action_check;
ALTER TABLE lark_cli_inbound_reply ADD CONSTRAINT lark_cli_inbound_reply_parsed_action_check
 CHECK (parsed_action IN ('approve','claim','edit_and_approve','reject','handoff','agent_query','blocked_duplicate_responder'));
ALTER TABLE colleague_agent_usage_event DROP CONSTRAINT colleague_agent_usage_event_event_type_check;
ALTER TABLE colleague_agent_usage_event ADD CONSTRAINT colleague_agent_usage_event_event_type_check
 CHECK (event_type IN ('dispatch','approve','claim','edit_and_approve','reject','handoff','agent_query','blocked_duplicate_responder','COLLISION_BLOCKED'));
ALTER TABLE lark_cli_inbound_reply DROP CONSTRAINT lark_cli_inbound_reply_interaction_mode_check;
ALTER TABLE lark_cli_inbound_reply ADD CONSTRAINT lark_cli_inbound_reply_interaction_mode_check
 CHECK (interaction_mode IN ('card_action','nl_chat','CARD_MODE','NL_CHAT_MODE'));
ALTER TABLE colleague_agent_usage_event DROP CONSTRAINT colleague_agent_usage_event_interaction_mode_check;
ALTER TABLE colleague_agent_usage_event ADD CONSTRAINT colleague_agent_usage_event_interaction_mode_check
 CHECK (interaction_mode IN ('card_action','nl_chat','system_dispatch','CARD_MODE','NL_CHAT_MODE'));
ALTER TABLE r50_collision_interception_log DROP CONSTRAINT r50_collision_interception_log_interaction_mode_check;
ALTER TABLE r50_collision_interception_log ADD CONSTRAINT r50_collision_interception_log_interaction_mode_check
 CHECK (interaction_mode IN ('card_action','nl_chat','CARD_MODE','NL_CHAT_MODE'));
ALTER TABLE r50_collision_interception_log DROP CONSTRAINT r50_collision_interception_log_interception_status_check;
ALTER TABLE r50_collision_interception_log ADD CONSTRAINT r50_collision_interception_log_interception_status_check
 CHECK (interception_status IN ('BLOCKED_DUPLICATE_RESPONDER','COLLISION_BLOCKED_SUPERSEDED_BY_PEER'));
ALTER TABLE r50_lark_loopback_queue DROP CONSTRAINT r50_lark_loopback_queue_status_check;
ALTER TABLE r50_lark_loopback_queue ADD CONSTRAINT r50_lark_loopback_queue_status_check
 CHECK (status IN ('QUEUED','DONE','REJECTED','COLLISION_BLOCKED_SUPERSEDED_BY_PEER'));
ALTER TABLE lark_cli_inbound_reply ADD COLUMN IF NOT EXISTS received_order bigint GENERATED ALWAYS AS IDENTITY;

-- A separate immutable ownership decision survives a winner's rejection/handoff.
CREATE TABLE IF NOT EXISTS r50_draft_claim (
 card_id uuid NOT NULL REFERENCES r50_owner_draft(card_id),
 draft_version integer NOT NULL CHECK (draft_version > 0),
 winning_dispatch_id uuid NOT NULL REFERENCES lark_cli_outbound_dispatch(dispatch_id),
 claimed_at timestamptz NOT NULL DEFAULT now(),
 mode text NOT NULL DEFAULT 'SANDBOX_LOOPBACK' CHECK (mode='SANDBOX_LOOPBACK'),
 PRIMARY KEY (card_id,draft_version)
);
INSERT INTO r50_draft_claim(card_id,draft_version,winning_dispatch_id)
 SELECT card_id,draft_version,dispatch_id FROM lark_cli_outbound_dispatch
 WHERE reply_status IN ('APPROVED','EDITED_AND_APPROVED') OR comm_id IS NOT NULL
 ON CONFLICT DO NOTHING;
DROP INDEX IF EXISTS r50_single_responder_winner_uq;
CREATE UNIQUE INDEX r50_single_responder_winner_uq ON lark_cli_outbound_dispatch(card_id,draft_version)
 WHERE reply_status IN ('CLAIMED','APPROVED','EDITED_AND_APPROVED');

-- Preserve the view's existing column order (including earlier local upgrades).
DO $view_upgrade$ DECLARE columns text; BEGIN
 SELECT string_agg(quote_ident(column_name),',' ORDER BY ordinal_position) INTO columns
 FROM information_schema.columns WHERE table_schema='public' AND table_name='colleague_agent_usage_summary_v';
 IF NOT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='public'
  AND table_name='colleague_agent_usage_summary_v' AND column_name='nl_chat_count') THEN
  columns:=columns||',nl_chat_count';
 END IF;
 EXECUTE 'CREATE OR REPLACE VIEW colleague_agent_usage_summary_v AS SELECT '||columns||' FROM ('||$view$
 SELECT e.employee_id,e.employee_name,e.department,
 count(u.event_id) FILTER (WHERE event_type='dispatch') AS dispatches_received,
 count(u.event_id) FILTER (WHERE event_type IN ('approve','edit_and_approve')) AS approvals_count,
 count(u.event_id) FILTER (WHERE event_type='edit_and_approve') AS edits_count,
 count(u.event_id) FILTER (WHERE event_type='handoff') AS handoffs_count,
 count(u.event_id) FILTER (WHERE event_type='agent_query') AS agent_queries_count,
 count(u.event_id) FILTER (WHERE event_type<>'dispatch') AS total_interactions,
 round(avg(response_seconds) FILTER (WHERE event_type<>'dispatch'),1) AS avg_response_seconds,
 max(u.created_at) AS last_active_at,
 count(u.event_id) FILTER (WHERE event_type<>'dispatch' AND interaction_mode IN ('card_action','CARD_MODE')) AS card_actions_count,
 count(u.event_id) FILTER (WHERE event_type<>'dispatch' AND interaction_mode IN ('nl_chat','NL_CHAT_MODE')) AS nl_chat_turns_count,
 coalesce(sum(tokens_used) FILTER (WHERE event_type<>'dispatch'),0) AS tokens_used,
 count(u.event_id) FILTER (WHERE event_type<>'dispatch' AND interaction_mode IN ('nl_chat','NL_CHAT_MODE')) AS nl_chat_count,
 count(u.event_id) FILTER (WHERE event_type IN ('blocked_duplicate_responder','COLLISION_BLOCKED')) AS collision_saves_count,
 'SANDBOX_REHEARSAL'::text AS dataset_kind,
 0::bigint AS tokens_measured,
 coalesce(sum(tokens_used) FILTER (WHERE event_type<>'dispatch'),0)::bigint AS tokens_estimated,
 'ESTIMATED_ONLY'::text AS tokens_coverage,
 count(u.event_id) FILTER (WHERE event_type IN ('claim','approve','edit_and_approve')) AS claimed_to_hub_count
 FROM v_active_employee_directory e LEFT JOIN colleague_agent_usage_event u USING(employee_id)
 GROUP BY e.employee_id,e.employee_name,e.department
 $view$||') summary';
END $view_upgrade$;

CREATE OR REPLACE FUNCTION public.r50_parse_zh_amount(p_text text)
RETURNS numeric LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
  m text[];
  num_val numeric;
  unit text;
  mult numeric := 1;
BEGIN
  IF p_text IS NULL OR btrim(p_text) = '' THEN
    RETURN NULL;
  END IF;
  IF p_text ~ '單價' THEN
    m := regexp_match(p_text, '單價\s*(?:改(?:成|為)?|[：:])?\s*(?:NT\$|TWD|\$)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(千萬|百萬|十萬|億|萬|千|百|十)?(?:\s*元)?');
  ELSE
    m := regexp_match(p_text, '(?:改(?:成|為)?\s*)?(?:NT\$|TWD|\$)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(千萬|百萬|十萬|億|萬|千|百|十)(?:\s*元)?');
    IF m IS NULL THEN
      m := regexp_match(p_text, '(?:改(?:成|為)?\s*)(?:NT\$|TWD|\$)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(千萬|百萬|十萬|億|萬|千|百|十)?(?:\s*元)?(?!\s*[天日週周月年號])');
    END IF;
  END IF;
  IF m IS NULL OR m[1] IS NULL THEN
    RETURN NULL;
  END IF;
  num_val := replace(m[1], ',', '')::numeric;
  unit := coalesce(m[2], '');
  mult := CASE unit
    WHEN '億' THEN 100000000
    WHEN '千萬' THEN 10000000
    WHEN '百萬' THEN 1000000
    WHEN '十萬' THEN 100000
    WHEN '萬' THEN 10000
    WHEN '千' THEN 1000
    WHEN '百' THEN 100
    WHEN '十' THEN 10
    ELSE 1
  END;
  RETURN round(num_val * mult, 0);
END $$;

CREATE OR REPLACE FUNCTION r50_parse_interaction(p_text text)
 RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE txt text; a text; imode text; ca text;
BEGIN
 txt:=btrim(regexp_replace(p_text,'^\[v[0-9]+\]\s*',''));
 IF txt ~ '^\[CARD(:[a-z_]+)?\]' THEN
  imode:='CARD_MODE'; ca:=substring(txt FROM '^\[CARD:([a-z_]+)\]');
  txt:=btrim(regexp_replace(txt,'^\[CARD(:[a-z_]+)?\]\s*',''));
 ELSE imode:='NL_CHAT_MODE'; END IF;
 txt:=btrim(regexp_replace(txt,'^@業主聯繫(\s*Lark\s*總機)?\s*',''));
 IF ca IS NOT NULL THEN
  IF ca NOT IN ('approve','claim','edit_approve','edit_and_approve') THEN RAISE EXCEPTION 'unsupported card action'; END IF;
  a:=CASE WHEN ca='edit_approve' THEN 'edit_and_approve' ELSE ca END;
 ELSIF txt IN ('拒絕','不核准','reject','緩發') THEN a:='reject';
 ELSIF txt ~ '不要|不准|勿|先別|暫不|尚未|未核准|不核准|不發|不能|不可|是否|[?？]' THEN a:='agent_query';
 ELSIF txt ~ '^改[：:]\s*\S' THEN a:='edit_and_approve';
 ELSIF txt ~ '^轉交\s+@\S' THEN a:='handoff';
 ELSIF txt IN ('認領','我先認領處理','claim') THEN a:='claim';
 ELSIF txt IN ('核准','OK','ok','認領並核准','可以發','照這樣發','核准發出','approve') THEN a:='approve';
 ELSIF (txt ~ '再發|發出|核准' AND txt ~ '改|補上|延後') OR (txt ~ '改' AND public.r50_parse_zh_amount(txt) IS NOT NULL) THEN a:='edit_and_approve';
 ELSE a:='agent_query'; END IF;
 IF a='edit_and_approve' AND txt='' THEN RAISE EXCEPTION 'edit_approve requires edited_body or edit instructions'; END IF;
 RETURN jsonb_build_object('action',a,'interaction_mode',imode,'text',txt);
END $$;

-- Deterministic sandbox edits; unknown instructions need an explicit replacement body.
CREATE OR REPLACE FUNCTION r50_apply_reply_edit(p_body text,p_instruction text) RETURNS text LANGUAGE plpgsql AS $$
DECLARE body text:=p_body; amt numeric; price_fmt text; days text; sheet text; n int; old_date text; remaining text:=p_instruction; handled bool:=false;
BEGIN
 IF p_instruction ~ '^改[：:]\s*\S' THEN RETURN btrim(regexp_replace(p_instruction,'^改[：:]\s*','')); END IF;
 amt:=public.r50_parse_zh_amount(p_instruction);
 IF amt IS NOT NULL THEN
  price_fmt:='NT$'||to_char(amt,'FM999,999,999,990');
  IF body ~ '單價[：:\s]*(?:NT\$|TWD|\$)?\s*[0-9,]+(?:\.[0-9]+)?(?:\s*(?:千萬|百萬|十萬|億|萬|千|百|十))?(?:\s*元)?' THEN
   body:=regexp_replace(body,'單價[：:\s]*(?:NT\$|TWD|\$)?\s*[0-9,]+(?:\.[0-9]+)?(?:\s*(?:千萬|百萬|十萬|億|萬|千|百|十))?(?:\s*元)?','單價 '||price_fmt,'g');
  ELSIF body ~ '單價[^
，；;。]*' THEN
   body:=regexp_replace(body,'單價[^
，；;。]*','單價 '||price_fmt,'g');
  ELSE body:=body||E'
追加工項單價 '||price_fmt||'。'; END IF;
  handled:=true;
  remaining:=regexp_replace(remaining,'(?:單價\s*)?(?:改(?:成|為)?|[：:])?\s*(?:NT\$|TWD|\$)?\s*[0-9][0-9,]*(?:\.[0-9]+)?\s*(?:千萬|百萬|十萬|億|萬|千|百|十)?(?:\s*元)?','','g');
 END IF;
 days:=substring(p_instruction FROM '交期延後\s*([0-9]+|[一二兩三四五六七八九十])\s*天');
 IF days IS NOT NULL THEN
  n:=CASE days WHEN '一' THEN 1 WHEN '二' THEN 2 WHEN '兩' THEN 2 WHEN '三' THEN 3 WHEN '四' THEN 4
   WHEN '五' THEN 5 WHEN '六' THEN 6 WHEN '七' THEN 7 WHEN '八' THEN 8 WHEN '九' THEN 9 WHEN '十' THEN 10 ELSE days::int END;
  old_date:=substring(body FROM '交期[：:\s]*([0-9]{4}-[0-9]{2}-[0-9]{2})');
  IF old_date IS NOT NULL THEN
   body:=regexp_replace(body,'交期[：:\s]*[0-9]{4}-[0-9]{2}-[0-9]{2}(?:（順延\s*[0-9]+\s*天）)?','交期 '||((old_date::date+n)::text)||'（順延 '||n||' 天）','g');
  ELSE body:=body||E'
交期延後'||days||'天。'; END IF;
  handled:=true;
  remaining:=regexp_replace(remaining,'交期延後\s*([0-9]+|[一二兩三四五六七八九十])\s*天','','g');
 END IF;
 sheet:=substring(p_instruction FROM '(?i)補上\s*(Sheet\s*[0-9]+)\s*圖號');
 IF sheet IS NOT NULL THEN
  body:=body||E'
圖號：'||sheet||'。'; handled:=true;
  remaining:=regexp_replace(remaining,'補上\s*Sheet\s*[0-9]+\s*圖號','','gi');
 END IF;
 remaining:=regexp_replace(remaining,'核准發出|核准|再發|發出|然後|幫我|[把並再、，,。；;「」『』[:space:]]','','g');
 IF NOT handled OR remaining<>'' THEN RAISE EXCEPTION 'unsupported edit instructions; provide edited_body'; END IF;
 RETURN body;
END $$;

CREATE OR REPLACE FUNCTION r50_supersede_peers(p_winner uuid) RETURNS void LANGUAGE plpgsql AS $$
DECLARE winner lark_cli_outbound_dispatch; peer lark_cli_outbound_dispatch; notice text; cas_notice text;
BEGIN
 PERFORM r50_safe();
 SELECT * INTO STRICT winner FROM lark_cli_outbound_dispatch WHERE dispatch_id=p_winner;
 notice:=CASE WHEN winner.reply_status IN ('APPROVED','EDITED_AND_APPROVED')
  THEN format('🔒 此信件已由 %s 核准發出，系統已鎖定防重複回覆，您無須重複回覆。',winner.target_employee_name)
  ELSE format('🔒 此信件已由 %s 認領處理，系統已鎖定防重複回覆，您無須重複回覆。',winner.target_employee_name) END;
 cas_notice:=format('🔒 此信件已由 %s 核准發出，系統已鎖定防重複回覆，您無須重複回覆。',winner.target_employee_name);
 FOR peer IN SELECT * FROM lark_cli_outbound_dispatch
  WHERE card_id=winner.card_id AND draft_version=winner.draft_version AND dispatch_id<>p_winner
  ORDER BY dispatch_id FOR UPDATE
 LOOP
  UPDATE lark_cli_outbound_dispatch SET reply_status='SUPERSEDED_BY_PEER',
   jk_final_send_status=CASE WHEN jk_final_send_status='BLOCKED_DUPLICATE_RESPONDER' THEN jk_final_send_status ELSE 'SUPERSEDED_BY_PEER' END,
   superseded_by_dispatch_id=p_winner,superseded_by_employee_name=winner.target_employee_name,
   peer_lock_notice=notice,updated_at=now() WHERE dispatch_id=peer.dispatch_id;
  INSERT INTO r50_peer_lock_notification(card_id,case_code,draft_version,winning_dispatch_id,
   winning_employee_id,winning_employee_name,superseded_dispatch_id,target_employee_id,target_employee_name,
   notice_text,lark_cli_dryrun_cmd)
  VALUES(winner.card_id,winner.case_code,winner.draft_version,p_winner,winner.target_employee_id,
   winner.target_employee_name,peer.dispatch_id,peer.target_employee_id,peer.target_employee_name,notice,
   format('lark-cli im +messages-send --user-id %s --text %L --dry-run',peer.target_employee_id,notice))
  ON CONFLICT(winning_dispatch_id,superseded_dispatch_id) DO UPDATE
   SET notice_text=excluded.notice_text,lark_cli_dryrun_cmd=excluded.lark_cli_dryrun_cmd;
 END LOOP;
 IF to_regclass('public.lark_colleague_approval_dispatch') IS NOT NULL THEN
  UPDATE public.lark_colleague_approval_dispatch
  SET status='SUPERSEDED_BY_PEER',
      superseded_by_employee_id=winner.target_employee_id,
      superseded_by_name=winner.target_employee_name,
      superseded_at=now(),
      peer_notification_status='SANDBOX_NOTIFIED',
      peer_notification_text=cas_notice,
      updated_at=now()
  WHERE draft_id=winner.card_id AND draft_version=winner.draft_version AND dispatch_id<>p_winner AND status='PENDING';
 END IF;
END $$;

CREATE OR REPLACE FUNCTION lark_cli_ingest_reply(p_lark_msg_id text,p_dispatch_id uuid,p_sender_emp_id uuid,p_raw_text text)
 RETURNS uuid LANGUAGE plpgsql AS $$
DECLARE d lark_cli_outbound_dispatch; previous lark_cli_inbound_reply; winner lark_cli_outbound_dispatch;
 rid uuid; claimed uuid; v int; secs int; toks int; a text; imode text; txt text; notice text; body text; parsed jsonb;
BEGIN
 PERFORM r50_safe();
 PERFORM pg_advisory_xact_lock(hashtextextended(p_lark_msg_id,50));
 SELECT * INTO previous FROM lark_cli_inbound_reply WHERE lark_message_id=p_lark_msg_id;
 IF FOUND THEN
  IF previous.dispatch_id<>p_dispatch_id OR previous.sender_employee_id<>p_sender_emp_id OR previous.raw_reply_text<>p_raw_text
   THEN RAISE EXCEPTION 'idempotency payload mismatch'; END IF;
  RETURN previous.reply_id;
 END IF;
 SELECT * INTO STRICT d FROM lark_cli_outbound_dispatch WHERE dispatch_id=p_dispatch_id;
 -- R50 CAS lock order: case then group then peer.
 SELECT coalesce((letter_state->>'version')::int,1) INTO STRICT v
  FROM yezhu_workbench_case WHERE code=d.case_code FOR UPDATE;
 PERFORM 1 FROM r50_owner_draft WHERE card_id=d.card_id FOR UPDATE;
 PERFORM 1 FROM lark_cli_outbound_dispatch WHERE card_id=d.card_id AND draft_version=d.draft_version ORDER BY dispatch_id FOR UPDATE;
 IF to_regclass('public.lark_colleague_approval_dispatch') IS NOT NULL THEN
  PERFORM 1 FROM public.lark_colleague_approval_dispatch WHERE draft_id=d.card_id AND draft_version=d.draft_version ORDER BY dispatch_id FOR UPDATE;
 END IF;
 SELECT * INTO STRICT d FROM lark_cli_outbound_dispatch WHERE dispatch_id=p_dispatch_id FOR UPDATE;
 IF p_sender_emp_id IS DISTINCT FROM d.target_employee_id THEN RAISE EXCEPTION 'wrong sender'; END IF;
 IF NOT EXISTS(SELECT 1 FROM v_active_employee_directory WHERE employee_id=p_sender_emp_id) THEN RAISE EXCEPTION 'inactive sender'; END IF;
 parsed:=r50_parse_interaction(p_raw_text); a:=parsed->>'action'; imode:=parsed->>'interaction_mode'; txt:=parsed->>'text';
 secs:=greatest(0,extract(epoch FROM (clock_timestamp()-d.created_at))::int);
 toks:=CASE WHEN imode='CARD_MODE' THEN 60 ELSE greatest(120,length(p_raw_text)*8) END;
 SELECT w.* INTO winner FROM r50_draft_claim c JOIN lark_cli_outbound_dispatch w ON w.dispatch_id=c.winning_dispatch_id
  WHERE c.card_id=d.card_id AND c.draft_version=d.draft_version;
 IF (FOUND AND winner.dispatch_id<>p_dispatch_id) OR d.reply_status='SUPERSEDED_BY_PEER' THEN
  IF winner.dispatch_id IS NULL THEN SELECT * INTO STRICT winner FROM lark_cli_outbound_dispatch WHERE dispatch_id=d.superseded_by_dispatch_id; END IF;
  notice:=coalesce(d.peer_lock_notice,format('🔒 此信件已由 %s 認領處理，系統已鎖定防重複回覆，您無須重複回覆。',winner.target_employee_name));
  a:='blocked_duplicate_responder';
 ELSE
  IF v<>d.draft_version THEN RAISE EXCEPTION 'stale draft_version'; END IF;
  IF substring(p_raw_text FROM '^\[v([0-9]+)\]') IS NULL
     OR substring(p_raw_text FROM '^\[v([0-9]+)\]')::int<>v THEN RAISE EXCEPTION 'missing or stale reply draft_version'; END IF;
  IF d.pm_solution_synced THEN RAISE EXCEPTION 'dispatch already finalized'; END IF;
  IF a='edit_and_approve' THEN
   SELECT edited_body INTO body FROM lark_cli_inbound_reply
    WHERE dispatch_id=p_dispatch_id AND edited_body IS NOT NULL ORDER BY received_order DESC LIMIT 1;
   body:=r50_apply_reply_edit(coalesce(body,d.message_preview),txt);
  END IF;
  IF a<>'agent_query' THEN
   -- First-claim compare-and-set. Queries do not claim ownership.
   INSERT INTO r50_draft_claim(card_id,draft_version,winning_dispatch_id)
    VALUES(d.card_id,d.draft_version,p_dispatch_id) ON CONFLICT DO NOTHING;
   SELECT winning_dispatch_id INTO STRICT claimed FROM r50_draft_claim WHERE card_id=d.card_id AND draft_version=d.draft_version;
   IF claimed<>p_dispatch_id THEN RAISE EXCEPTION 'first-claim CAS invariant violated'; END IF;
  END IF;
 END IF;
 INSERT INTO lark_cli_inbound_reply(lark_message_id,dispatch_id,sender_employee_id,sender_name,
  raw_reply_text,parsed_action,edited_body,verified_assignee,draft_version_matched,response_seconds,interaction_mode)
 VALUES(p_lark_msg_id,p_dispatch_id,p_sender_emp_id,d.target_employee_name,p_raw_text,a,body,true,
  coalesce(substring(p_raw_text FROM '^\[v([0-9]+)\]')::int=v,false),secs,imode) RETURNING reply_id INTO rid;
 INSERT INTO colleague_agent_usage_event(employee_id,dispatch_id,reply_id,event_key,event_type,response_seconds,interaction_mode,tokens_used)
 VALUES(p_sender_emp_id,p_dispatch_id,rid,'reply:'||p_lark_msg_id,a,secs,imode,toks);
 IF a='blocked_duplicate_responder' THEN
  UPDATE lark_cli_outbound_dispatch SET reply_status='SUPERSEDED_BY_PEER',jk_final_send_status='BLOCKED_DUPLICATE_RESPONDER',
   superseded_by_dispatch_id=winner.dispatch_id,superseded_by_employee_name=winner.target_employee_name,
   peer_lock_notice=notice,updated_at=now() WHERE dispatch_id=p_dispatch_id;
  IF to_regclass('public.lark_colleague_approval_dispatch') IS NOT NULL THEN
   UPDATE public.lark_colleague_approval_dispatch SET status='SUPERSEDED_BY_PEER',
    superseded_by_employee_id=winner.target_employee_id,superseded_by_name=winner.target_employee_name,
    superseded_at=coalesce(superseded_at,now()),peer_notification_status='SANDBOX_NOTIFIED',
    peer_notification_text=coalesce(peer_notification_text,notice),updated_at=now() WHERE dispatch_id=p_dispatch_id;
  END IF;
  INSERT INTO r50_collision_interception_log(card_id,case_code,draft_version,winning_dispatch_id,winning_employee_name,
   blocked_dispatch_id,blocked_employee_id,blocked_employee_name,blocked_lark_message_id,blocked_reply_text,
   interaction_mode,lock_notice_text,interception_status)
  VALUES(d.card_id,d.case_code,d.draft_version,winner.dispatch_id,winner.target_employee_name,
   p_dispatch_id,p_sender_emp_id,d.target_employee_name,p_lark_msg_id,p_raw_text,imode,notice,'COLLISION_BLOCKED_SUPERSEDED_BY_PEER');
 ELSIF a<>'agent_query' THEN
  UPDATE lark_cli_outbound_dispatch SET reply_status=CASE a
   WHEN 'approve' THEN 'APPROVED' WHEN 'edit_and_approve' THEN 'EDITED_AND_APPROVED'
   WHEN 'reject' THEN 'REJECTED' WHEN 'handoff' THEN 'HANDOFF'
   ELSE CASE WHEN d.reply_status IN ('APPROVED','EDITED_AND_APPROVED') THEN d.reply_status ELSE 'CLAIMED' END END,
   jk_final_send_status=CASE WHEN a IN ('approve','edit_and_approve') THEN 'READY_FOR_JK_SEND'
    WHEN a IN ('reject','handoff') THEN 'PENDING_COLLEAGUE' ELSE d.jk_final_send_status END,
   updated_at=now() WHERE dispatch_id=p_dispatch_id;
  IF to_regclass('public.lark_colleague_approval_dispatch') IS NOT NULL AND a IN ('claim','approve','edit_and_approve') THEN
   UPDATE public.lark_colleague_approval_dispatch SET
    status=CASE a WHEN 'claim' THEN 'CLAIMED' WHEN 'approve' THEN 'APPROVED' ELSE 'EDITED_APPROVED' END,
    decision_status=CASE a WHEN 'claim' THEN 'CLAIMED' WHEN 'approve' THEN 'APPROVED' ELSE 'EDITED_APPROVED' END,
    interaction_mode=imode,reply_text=p_raw_text,edited_body=coalesce(body,edited_body),
    approved_at=CASE WHEN a<>'claim' THEN now() ELSE approved_at END,updated_at=now()
   WHERE dispatch_id=p_dispatch_id;
  END IF;
  PERFORM r50_supersede_peers(p_dispatch_id);
 END IF;
 RETURN rid;
END $$;

CREATE OR REPLACE FUNCTION jk_final_send_and_sync_pm_db(p_dispatch_id uuid,p_actor_id uuid)
 RETURNS uuid LANGUAGE plpgsql AS $$
DECLARE d lark_cli_outbound_dispatch; c public."case"; rid uuid; v int; msg text; n bigint; claimed uuid;
BEGIN
 PERFORM r50_require_jk(p_actor_id);
 SELECT * INTO STRICT d FROM lark_cli_outbound_dispatch WHERE dispatch_id=p_dispatch_id;
 -- R50 CAS lock order: case then group then peer.
 SELECT coalesce((letter_state->>'version')::int,1) INTO STRICT v FROM yezhu_workbench_case WHERE code=d.case_code FOR UPDATE;
 PERFORM 1 FROM r50_owner_draft WHERE card_id=d.card_id FOR UPDATE;
 SELECT * INTO STRICT d FROM lark_cli_outbound_dispatch WHERE dispatch_id=p_dispatch_id FOR UPDATE;
 SELECT winning_dispatch_id INTO claimed FROM r50_draft_claim WHERE card_id=d.card_id AND draft_version=d.draft_version;
 IF claimed IS DISTINCT FROM p_dispatch_id OR d.reply_status='SUPERSEDED_BY_PEER' THEN RAISE EXCEPTION 'colleague approval required or superseded by peer responder'; END IF;
 IF d.pm_solution_synced THEN RETURN d.comm_id; END IF;
 IF v<>d.draft_version THEN RAISE EXCEPTION 'stale draft_version'; END IF;
 IF d.jk_final_send_status<>'READY_FOR_JK_SEND' OR d.reply_status NOT IN ('APPROVED','EDITED_AND_APPROVED') THEN RAISE EXCEPTION 'colleague approval required'; END IF;
 SELECT * INTO c FROM public."case" WHERE case_code=d.case_code AND org_id='YX' LIMIT 1;
 -- A later plain approval retains an earlier approved edit.
 SELECT edited_body INTO msg FROM lark_cli_inbound_reply WHERE dispatch_id=p_dispatch_id AND edited_body IS NOT NULL
  ORDER BY received_order DESC LIMIT 1;
 msg:=coalesce(msg,d.message_preview);
 LOCK TABLE client_communication IN SHARE ROW EXCLUSIVE MODE;
 SELECT i INTO n FROM generate_series(12085,200000) i
  WHERE NOT EXISTS(SELECT 1 FROM client_communication WHERE org_id='YX' AND serial_no=i)
   AND NOT EXISTS(SELECT 1 FROM serial_assignment WHERE org_id='YX' AND serial_no=i) ORDER BY i LIMIT 1;
 INSERT INTO client_communication(serial_no,direction,channel,occurred_at,customer_id,case_id,our_employee_id,
  external_ref,body_text,summary_120,extracted_by,human_confirmed_by,is_synthetic)
 VALUES(n,'outbound','email',now(),coalesce(c.customer_id,'50505050-5050-5050-5050-505050505050'::uuid),c.id,
  p_actor_id,'r50-sandbox:'||p_dispatch_id,msg,'JK 最終發送・SANDBOX_LOOPBACK','human',p_actor_id,true) RETURNING id INTO rid;
 UPDATE lark_cli_outbound_dispatch SET jk_final_send_status='SENT_FROM_JK_DRYRUN',pm_solution_synced=true,comm_id=rid,
  final_actor_id=p_actor_id,final_sent_at=now(),canonical_quote_no=(SELECT canonical_quote_no::text FROM case_quote_summary_v
   WHERE case_id=c.id AND NOT needs_human LIMIT 1),updated_at=now() WHERE dispatch_id=p_dispatch_id;
 IF to_regclass('public.lark_colleague_approval_dispatch') IS NOT NULL THEN
  UPDATE public.lark_colleague_approval_dispatch SET status='SENT_FROM_JK_DRYRUN',comm_id=rid,updated_at=now() WHERE dispatch_id=p_dispatch_id;
 END IF;
 RETURN rid;
END $$;

-- Created last: this signature is also the atomic installation/version marker.
CREATE OR REPLACE FUNCTION r50_multi_dispatch_v1(p_card uuid,p_actor uuid,p_targets jsonb)
 RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE target jsonb; employee_id uuid; did uuid; winner uuid; v int; result jsonb:='[]'; case_code text;
BEGIN
 PERFORM r50_require_jk(p_actor);
 IF jsonb_typeof(p_targets)<>'array' OR jsonb_array_length(p_targets)=0 THEN RAISE EXCEPTION 'recipients required'; END IF;
 SELECT r.case_code INTO STRICT case_code FROM r50_owner_draft r WHERE r.card_id=p_card;
 SELECT coalesce((letter_state->>'version')::int,1) INTO STRICT v FROM yezhu_workbench_case w WHERE w.code=case_code FOR UPDATE;
 PERFORM 1 FROM r50_owner_draft WHERE card_id=p_card FOR UPDATE;
 FOR target IN SELECT value FROM jsonb_array_elements(p_targets) LOOP
  employee_id:=CASE WHEN target='null'::jsonb THEN NULL ELSE (target#>>'{}')::uuid END;
  did:=lark_cli_push_to_colleague(p_card,p_actor,employee_id);
  result:=result||jsonb_build_array(did);
 END LOOP;
 SELECT winning_dispatch_id INTO winner FROM r50_draft_claim WHERE card_id=p_card AND draft_version=v;
 IF FOUND THEN PERFORM r50_supersede_peers(winner); END IF;
 RETURN result;
END $$;
