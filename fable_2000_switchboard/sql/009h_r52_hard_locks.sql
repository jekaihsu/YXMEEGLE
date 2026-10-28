SET plpgsql.check_asserts = on;

DO $$
BEGIN
  ASSERT current_database() != 'yongxiang_plumb', 'FATAL: refusing to touch production database yongxiang_plumb';
  ASSERT current_database() = 'yongxiang_plumb_r39_clone', 'FATAL: must run on yongxiang_plumb_r39_clone';
END $$;

-- ============================================================================
-- Hard Lock #2: Programmatic & DB Test Recipient Allowlist Guard
-- ALLOWED_TEST_RECIPIENT = 'jekai@yxsurvey.com.tw'
-- ============================================================================
CREATE OR REPLACE FUNCTION public.r52_enforce_test_recipient(p_recipient text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
AS $function$
DECLARE
  v_norm text := lower(btrim(coalesce(p_recipient, '')));
BEGIN
  IF v_norm = '' OR v_norm LIKE '%@gmail.com%' OR v_norm <> 'jekai@yxsurvey.com.tw' THEN
    RAISE EXCEPTION 'BLOCKED_NON_WHITELIST_RECIPIENT: recipient "%" is forbidden in test/sandbox mode; only jekai@yxsurvey.com.tw is allowed', coalesce(p_recipient, '<NULL>')
      USING ERRCODE = 'P0001';
  END IF;
  RETURN 'jekai@yxsurvey.com.tw';
END $function$;

ALTER TABLE public.lark_cli_outbound_dispatch
  ADD COLUMN IF NOT EXISTS test_recipient_email text NOT NULL DEFAULT 'jekai@yxsurvey.com.tw';

ALTER TABLE public.lark_cli_outbound_dispatch
  DROP CONSTRAINT IF EXISTS chk_r52_dispatch_allowed_test_recipient;

ALTER TABLE public.lark_cli_outbound_dispatch
  ADD CONSTRAINT chk_r52_dispatch_allowed_test_recipient
  CHECK (test_recipient_email = 'jekai@yxsurvey.com.tw');

ALTER TABLE public.lark_colleague_approval_queue
  ADD COLUMN IF NOT EXISTS test_recipient_email text NOT NULL DEFAULT 'jekai@yxsurvey.com.tw',
  ADD COLUMN IF NOT EXISTS jk_final_send_status text NOT NULL DEFAULT 'PENDING_COLLEAGUE';

ALTER TABLE public.lark_colleague_approval_queue
  DROP CONSTRAINT IF EXISTS chk_r52_queue_allowed_test_recipient;

ALTER TABLE public.lark_colleague_approval_queue
  ADD CONSTRAINT chk_r52_queue_allowed_test_recipient
  CHECK (test_recipient_email = 'jekai@yxsurvey.com.tw');

ALTER TABLE public.finalization
  ADD COLUMN IF NOT EXISTS test_recipient_email text NOT NULL DEFAULT 'jekai@yxsurvey.com.tw';

ALTER TABLE public.finalization
  DROP CONSTRAINT IF EXISTS chk_r52_finalization_allowed_test_recipient;

ALTER TABLE public.finalization
  ADD CONSTRAINT chk_r52_finalization_allowed_test_recipient
  CHECK (test_recipient_email = 'jekai@yxsurvey.com.tw');

-- ============================================================================
-- Hard Lock #3: Operon Workflow Card Builder with Explicit Recipient Badge
-- ============================================================================
CREATE OR REPLACE FUNCTION public.operon_workflow_card_build(
  p_case_code text,
  p_subject text,
  p_client_recipient text,
  p_draft_version integer DEFAULT 1,
  p_test_mode boolean DEFAULT true
)
RETURNS jsonb
LANGUAGE plpgsql
IMMUTABLE
AS $function$
DECLARE
  v_rec text := coalesce(nullif(btrim(p_client_recipient), ''), '台灣世曦 · 林工程師 <lin.ceci@example.com>');
  v_badge text := format('🎯 按下後實際收件人：%s', v_rec);
  v_test_badge text := '🎯 測試保護中：按下只會寄至 jekai@yxsurvey.com.tw（許竣凱），不會外發業主';
BEGIN
  RETURN jsonb_build_object(
    'schema_version', 'r52.hardlock.v1',
    'case_code', coalesce(p_case_code, 'C114109'),
    'subject', coalesce(p_subject, ''),
    'draft_version', coalesce(p_draft_version, 1),
    'intended_client_recipient', v_rec,
    'allowed_test_recipient', 'jekai@yxsurvey.com.tw',
    'jk_final_lock_policy', 'PENDING_JK_FINAL_APPROVAL',
    'recipient_badge', v_badge,
    'test_guard_badge', CASE WHEN p_test_mode THEN v_test_badge ELSE v_badge END,
    'action_buttons', jsonb_build_array(
      jsonb_build_object(
        'action', 'approve',
        'label', '✅ 核准（送交 JK 最終審核放行）',
        'adjacent_recipient_label', v_badge,
        'adjacent_test_guard_label', v_test_badge,
        'transitions_to', 'PENDING_JK_FINAL_APPROVAL',
        'auto_send', false
      ),
      jsonb_build_object(
        'action', 'edit_and_approve',
        'label', '✏️ 修改後送交 JK 審核',
        'adjacent_recipient_label', v_badge,
        'adjacent_test_guard_label', v_test_badge,
        'transitions_to', 'PENDING_JK_FINAL_APPROVAL',
        'auto_send', false
      )
    )
  );
END $function$;

-- ============================================================================
-- Hard Lock #1: PENDING_JK_FINAL_APPROVAL Check Constraints & State Machine
-- ============================================================================
ALTER TABLE public.lark_cli_outbound_dispatch
  DROP CONSTRAINT IF EXISTS lark_cli_outbound_dispatch_jk_final_send_status_check;

ALTER TABLE public.lark_cli_outbound_dispatch
  ADD CONSTRAINT lark_cli_outbound_dispatch_jk_final_send_status_check
  CHECK (
    jk_final_send_status = ANY (ARRAY[
      'PENDING_COLLEAGUE'::text,
      'PENDING_JK_FINAL_APPROVAL'::text,
      'READY_FOR_JK_SEND'::text,
      'SENT_FROM_JK_DRYRUN'::text,
      'SUPERSEDED_BY_PEER'::text,
      'BLOCKED_DUPLICATE_RESPONDER'::text,
      'BLOCKED_NON_WHITELIST_RECIPIENT'::text,
      'SENT_FROM_JK_LIVE'::text
    ])
    AND jk_final_send_status <> 'SENT_FROM_JK_LIVE'::text
  );

ALTER TABLE public.dispatch_group
  DROP CONSTRAINT IF EXISTS dispatch_group_phase_check;

ALTER TABLE public.dispatch_group
  ADD CONSTRAINT dispatch_group_phase_check
  CHECK (
    phase = ANY (ARRAY[
      'OPEN'::text,
      'CLAIMED'::text,
      'HELD'::text,
      'APPROVED_PENDING_JK'::text,
      'PENDING_JK_FINAL_APPROVAL'::text,
      'READY_FOR_JK'::text,
      'FINALIZED'::text,
      'WITHDRAWN'::text,
      'CLOSED_BY_NEW_VERSION'::text
    ])
  );

CREATE OR REPLACE FUNCTION public.r50_sync_legacy(p_group uuid)
RETURNS void
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
BEGIN
  ASSERT current_database() != 'yongxiang_plumb';
  UPDATE public.lark_cli_outbound_dispatch c SET
    reply_status = CASE d.status
      WHEN 'OPEN' THEN 'WAITING_COLLEAGUE'
      WHEN 'EDITED_APPROVED' THEN 'EDITED_AND_APPROVED'
      WHEN 'REJECTED_BY_OWNER' THEN 'REJECTED'
      WHEN 'HANDOFF_SUGGESTED' THEN 'HANDOFF'
      WHEN 'CLOSED_BY_NEW_VERSION' THEN 'SUPERSEDED_BY_PEER'
      ELSE d.status
    END,
    jk_final_send_status = CASE
      WHEN d.status IN ('SUPERSEDED_BY_PEER','CLOSED_BY_NEW_VERSION') THEN 'SUPERSEDED_BY_PEER'
      WHEN f.communication_id IS NOT NULL AND d.dispatch_id = g.winning_dispatch_id THEN 'SENT_FROM_JK_DRYRUN'
      WHEN d.status IN ('APPROVED','EDITED_APPROVED') THEN 'PENDING_JK_FINAL_APPROVAL'
      ELSE 'PENDING_COLLEAGUE'
    END,
    comm_id = CASE WHEN d.dispatch_id = g.winning_dispatch_id THEN f.communication_id ELSE NULL END,
    pm_solution_synced = (f.communication_id IS NOT NULL AND d.dispatch_id = g.winning_dispatch_id),
    superseded_by_dispatch_id = d.superseded_by_dispatch_id,
    test_recipient_email = 'jekai@yxsurvey.com.tw',
    operon_workflow_card = COALESCE(
      c.operon_workflow_card,
      public.operon_workflow_card_build(
        c.case_code,
        coalesce(c.subject, c.case_code),
        coalesce(c.client_sender, '業主窗口'),
        c.draft_version,
        true
      )
    ),
    updated_at = clock_timestamp()
  FROM public.dispatch d
  JOIN public.dispatch_group g ON g.dispatch_group_id = d.group_id
  LEFT JOIN public.finalization f ON f.group_id = g.dispatch_group_id
  WHERE c.dispatch_id = d.dispatch_id AND d.group_id = p_group;

  UPDATE public.lark_colleague_approval_dispatch c SET
    status = CASE d.status
      WHEN 'OPEN' THEN 'PENDING'
      WHEN 'CLOSED_BY_NEW_VERSION' THEN 'SUPERSEDED_BY_PEER'
      WHEN 'REJECTED_BY_OWNER' THEN 'REJECTED'
      WHEN 'HANDOFF_SUGGESTED' THEN 'REJECTED'
      ELSE d.status
    END,
    dispatch_group_id = d.group_id,
    peer_notification_status = CASE
      WHEN n.status = 'SANDBOX_NOTIFIED' THEN 'SANDBOX_NOTIFIED'
      WHEN n.notice_id IS NOT NULL THEN 'QUEUED'
      ELSE 'NONE'
    END,
    peer_notification_text = n.text,
    updated_at = clock_timestamp()
  FROM public.dispatch d
  LEFT JOIN LATERAL (
    SELECT * FROM public.notification_outbox_r50 n
    WHERE n.dispatch_id = d.dispatch_id
    ORDER BY n.created_at DESC LIMIT 1
  ) n ON true
  WHERE c.dispatch_id = d.dispatch_id AND d.group_id = p_group;
END $function$;


CREATE OR REPLACE FUNCTION public.lark_cli_ingest_reply(
  p_lark_msg_id text,
  p_dispatch_id uuid,
  p_sender_emp_id uuid,
  p_raw_text text
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $function$
DECLARE
  d public.lark_cli_outbound_dispatch;
  g public.dispatch_group;
  h public.draft_head;
  v_intent text := 'APPROVE';
  v_mode text := 'NL_CHAT_MODE';
  v_res jsonb;
  v_reply_id uuid := gen_random_uuid();
BEGIN
  ASSERT current_database() != 'yongxiang_plumb';
  PERFORM public.r50_safe();
  IF current_setting('r50.allow_canonical_ingest', true) IS DISTINCT FROM 'on' THEN
    RAISE EXCEPTION 'CANONICAL_ENVELOPE_REQUIRED: ingest via verified channel adapter';
  END IF;
  SELECT * INTO STRICT d FROM public.lark_cli_outbound_dispatch WHERE dispatch_id = p_dispatch_id;
  SELECT x.* INTO STRICT g FROM public.dispatch_group x JOIN public.dispatch dp ON dp.group_id = x.dispatch_group_id WHERE dp.dispatch_id = p_dispatch_id;
  SELECT * INTO STRICT h FROM public.draft_head WHERE card_id = g.card_id;
  IF p_raw_text LIKE '%[CARD:%' THEN
    v_mode := 'CARD_MODE';
  END IF;
  IF p_raw_text LIKE '%改：%' OR p_raw_text LIKE '%改:%' THEN
    v_intent := 'EDIT_APPROVE';
  ELSIF p_raw_text LIKE '%退回%' OR p_raw_text LIKE '%緩%' THEN
    v_intent := 'REJECT';
  END IF;
  v_res := public.handle_action(
    'lark_cli:verified',
    coalesce(nullif(btrim(p_lark_msg_id), ''), v_reply_id::text),
    p_dispatch_id,
    p_sender_emp_id,
    v_mode,
    v_intent,
    g.draft_version,
    h.current_digest,
    jsonb_build_object('body', p_raw_text, 'raw_text', p_raw_text)
  );
  UPDATE public.lark_cli_outbound_dispatch
  SET jk_final_send_status = CASE
        WHEN reply_status IN ('APPROVED', 'EDITED_AND_APPROVED') THEN 'PENDING_JK_FINAL_APPROVAL'
        ELSE jk_final_send_status
      END,
      test_recipient_email = 'jekai@yxsurvey.com.tw',
      updated_at = clock_timestamp()
  WHERE dispatch_id = p_dispatch_id;
  RETURN v_reply_id;
END $function$;

CREATE OR REPLACE FUNCTION public.r50_part2_cas_decide(
  p_dispatch_id uuid,
  p_actor_name text,
  p_action text,
  p_interaction_mode text DEFAULT 'CARD_MODE',
  p_reply_text text DEFAULT NULL,
  p_edited_body text DEFAULT NULL,
  p_auto_jk_finalize boolean DEFAULT false
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $function$
DECLARE
  actor uuid;
  h public.draft_head;
  g public.dispatch_group;
  r jsonb;
  a_norm text := upper(btrim(coalesce(p_action, '')));
BEGIN
  ASSERT current_database() != 'yongxiang_plumb';
  PERFORM public.r50_safe();
  IF p_auto_jk_finalize THEN
    RAISE EXCEPTION 'JK_FINAL_CONFIRMATION_REQUIRED: auto-send is forbidden by Hard Lock #1 (PENDING_JK_FINAL_APPROVAL)';
  END IF;
  SELECT id INTO actor FROM public.employee WHERE full_name = p_actor_name AND employment_status = 'active' AND org_id = 'YX';
  SELECT x.* INTO STRICT g FROM public.dispatch_group x JOIN public.dispatch d ON d.group_id = x.dispatch_group_id WHERE d.dispatch_id = p_dispatch_id;
  SELECT * INTO STRICT h FROM public.draft_head WHERE card_id = g.card_id;
  r := public.handle_action(
    'legacy:explicit',
    gen_random_uuid()::text,
    p_dispatch_id,
    actor,
    p_interaction_mode,
    p_action,
    g.draft_version,
    h.current_digest,
    jsonb_build_object('body', p_edited_body, 'raw_text', p_reply_text)
  );
  RETURN r || jsonb_build_object(
    'status', r->>'outcome',
    'phase', (SELECT phase FROM public.dispatch_group WHERE dispatch_group_id = g.dispatch_group_id),
    'jk_final_send_status', CASE WHEN a_norm IN ('APPROVE', 'EDIT_AND_APPROVE', 'EDIT_APPROVE') THEN 'PENDING_JK_FINAL_APPROVAL' ELSE 'PENDING_COLLEAGUE' END,
    'external_messages_sent', 0
  );
END $function$;

CREATE OR REPLACE FUNCTION public.jk_finalize(
  p_group uuid,
  p_actor uuid,
  p_approval uuid,
  p_digest text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $function$
DECLARE
  g public.dispatch_group;
  s public.approval_snapshot;
  v public.draft_version;
  f public.finalization;
  h public.draft_head;
  c public."case";
  cid uuid;
  sn bigint;
  v_test_rec text;
BEGIN
  ASSERT current_database() != 'yongxiang_plumb';
  PERFORM public.r50_require_jk(p_actor);
  v_test_rec := public.r52_enforce_test_recipient('jekai@yxsurvey.com.tw');
  SELECT * INTO STRICT g FROM public.dispatch_group WHERE dispatch_group_id = p_group;
  g := public.lock_group(g.card_id, g.draft_version);
  SELECT * INTO f FROM public.finalization WHERE org_id = g.org_id AND card_id = g.card_id;
  IF FOUND THEN
    RETURN jsonb_build_object(
      'outcome', 'SENT_FROM_JK_DRYRUN',
      'communication_id', f.communication_id,
      'replay', true,
      'test_recipient_email', v_test_rec,
      'external_messages_sent', 0
    );
  END IF;
  SELECT * INTO STRICT h FROM public.draft_head WHERE card_id = g.card_id;
  IF g.phase NOT IN ('READY_FOR_JK', 'APPROVED_PENDING_JK', 'PENDING_JK_FINAL_APPROVAL')
     OR h.current_version <> g.draft_version
     OR p_approval IS DISTINCT FROM g.active_approval_id
     OR p_digest IS NULL THEN
    RETURN jsonb_build_object('outcome', 'STALE_APPROVAL');
  END IF;
  SELECT * INTO STRICT s FROM public.approval_snapshot WHERE approval_id = g.active_approval_id AND group_id = p_group;
  SELECT * INTO STRICT v FROM public.draft_version WHERE card_id = g.card_id AND version = g.draft_version;
  IF s.approved_digest <> p_digest
     OR s.dispatch_id <> g.winning_dispatch_id
     OR s.approved_digest <> public.r50_content_digest(s.approved_body, s.to_json, s.cc_json, s.attachments_manifest)
     OR s.to_json <> v.to_json
     OR s.cc_json <> v.cc_json
     OR s.attachments_manifest <> v.attachments_manifest
     OR v.digest <> h.current_digest THEN
    RETURN jsonb_build_object('outcome', 'STALE_APPROVAL');
  END IF;
  PERFORM pg_advisory_xact_lock(50, 12085);
  SELECT i INTO sn FROM generate_series(12085, 200000) i
  WHERE NOT EXISTS (SELECT FROM public.client_communication WHERE org_id = g.org_id AND serial_no = i)
    AND NOT EXISTS (SELECT FROM public.serial_assignment WHERE org_id = g.org_id AND serial_no = i)
  ORDER BY i LIMIT 1;
  SELECT k.* INTO c FROM public."case" k JOIN public.r50_work_item w ON k.case_code = w.case_code
  WHERE w.card_id = g.card_id AND k.org_id = g.org_id LIMIT 1;
  INSERT INTO public.client_communication(
    serial_no, direction, channel, occurred_at, customer_id, case_id,
    our_employee_id, external_ref, body_text, summary_120, extracted_by, human_confirmed_by, is_synthetic, org_id
  )
  VALUES(
    sn, 'outbound', 'email', clock_timestamp(),
    coalesce(c.customer_id, '50505050-5050-5050-5050-505050505050'::uuid),
    c.id, p_actor, 'r50-part2-sandbox:' || p_group, s.approved_body,
    'JK 演練留存（未對外寄送）', 'human', p_actor, true, g.org_id
  ) RETURNING id INTO cid;
  INSERT INTO public.finalization(group_id, org_id, card_id, approval_id, final_digest, communication_id, finalized_by, send_mode, test_recipient_email)
  VALUES(p_group, g.org_id, g.card_id, s.approval_id, s.approved_digest, cid, p_actor, 'SENT_FROM_JK_DRYRUN', v_test_rec);
  UPDATE public.dispatch_group SET phase = 'FINALIZED' WHERE dispatch_group_id = p_group;
  PERFORM public.r50_sync_legacy(p_group);
  RETURN jsonb_build_object(
    'outcome', 'SENT_FROM_JK_DRYRUN',
    'communication_id', cid,
    'approved_digest', s.approved_digest,
    'test_recipient_email', v_test_rec,
    'external_messages_sent', 0
  );
END $function$;

-- Update push_draft_to_colleague and claim_and_approve_draft for R49 queue table
CREATE OR REPLACE FUNCTION public.push_draft_to_colleague(
  p_case_code text,
  p_target_employee_name text,
  p_subject text,
  p_recipient text,
  p_body text,
  p_client_name text DEFAULT ''::text,
  p_lark_msg_id text DEFAULT NULL::text,
  p_cli_cmd text DEFAULT NULL::text,
  p_inbound_email_id text DEFAULT NULL::text,
  p_arrives_type text DEFAULT '送審退回修正 (Submittal Return)'::text,
  p_connected_docs text DEFAULT '關聯圖號 M-301 / CAD-v3：對比前版新增 3 處斷面補測，影響報價單 #Q115-089 共 4 個工項'::text,
  p_extracted_deadline text DEFAULT '2026-10-28 17:00（內文抽取：請於週三前補送修正圖與報價）'::text,
  p_person_decides text DEFAULT '決定變更工項單價與重提送審時程'::text
)
RETURNS jsonb
LANGUAGE plpgsql
AS $function$
DECLARE
  s record;
  q public.lark_colleague_approval_queue;
  v_email_id text;
  v_card jsonb;
BEGIN
  ASSERT current_database() != 'yongxiang_plumb';
  PERFORM public.r49_guard();
  SELECT * INTO s FROM public.staff_directory_v WHERE full_name = p_target_employee_name LIMIT 1;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Unknown active employee: %', p_target_employee_name;
  END IF;
  v_email_id := coalesce(nullif(btrim(p_inbound_email_id), ''), 'email:' || p_case_code || ':' || md5(p_subject));
  v_card := public.operon_workflow_card_build(p_case_code, p_subject, p_recipient, 1, true);

  INSERT INTO public.lark_colleague_approval_queue(
    case_code, client_name, inbound_email_id, target_employee_id, target_employee_name,
    target_department, target_job_title, target_lark_open_id, proposed_subject,
    proposed_recipient, proposed_body, outbound_lark_msg_id, lark_cli_command,
    operon_arrives_type, operon_connected_docs_diff, operon_extracted_deadline, operon_person_decides,
    lark_card_json, jk_final_send_status, test_recipient_email
  )
  VALUES(
    p_case_code, p_client_name, v_email_id, s.employee_id, s.full_name,
    s.department, s.job_title, s.lark_open_id, p_subject,
    p_recipient, p_body, p_lark_msg_id, p_cli_cmd,
    p_arrives_type, p_connected_docs, p_extracted_deadline, p_person_decides,
    v_card, 'PENDING_COLLEAGUE', 'jekai@yxsurvey.com.tw'
  ) RETURNING * INTO q;
  PERFORM public.r49_log(q.approval_id, 'draft_pushed', NULL, 'Operon Card + NL prompt pushed (dry-run)', 'card');
  RETURN to_jsonb(q);
END $function$;

CREATE OR REPLACE FUNCTION public.claim_and_approve_draft(
  p_approval_id uuid,
  p_reply_text text,
  p_reply_msg_id text DEFAULT NULL::text,
  p_response_seconds integer DEFAULT 95,
  p_interaction_mode text DEFAULT NULL::text
)
RETURNS jsonb
LANGUAGE plpgsql
AS $function$
DECLARE
  q public.lark_colleague_approval_queue;
  winner public.lark_colleague_approval_queue;
  t text := btrim(p_reply_text);
  a text;
  st text;
  v_jk_st text;
  v_mode text;
  v_body text;
  v_notice text;
  v_time_str text;
BEGIN
  ASSERT current_database() != 'yongxiang_plumb';
  PERFORM public.r49_guard();
  SELECT * INTO STRICT q FROM public.lark_colleague_approval_queue WHERE approval_id = p_approval_id;
  PERFORM pg_advisory_xact_lock(hashtextextended(q.inbound_email_id, 49));
  SELECT * INTO STRICT q FROM public.lark_colleague_approval_queue WHERE approval_id = p_approval_id FOR UPDATE;

  IF p_reply_msg_id IS NOT NULL AND q.colleague_reply_msg_id = p_reply_msg_id THEN
    IF q.colleague_reply_text IS DISTINCT FROM p_reply_text THEN
      RAISE EXCEPTION 'reply payload mismatch';
    END IF;
    RETURN to_jsonb(q);
  END IF;

  v_mode := coalesce(
    p_interaction_mode,
    CASE
      WHEN t LIKE '[卡片點擊]%' OR t IN ('發', '可以發', 'OK', 'ok', '核准', '✅ 核准並由中樞發出', '🔒 我先認領處理') THEN 'card'
      ELSE 'nl'
    END
  );

  SELECT * INTO winner
  FROM public.lark_colleague_approval_queue
  WHERE inbound_email_id = q.inbound_email_id
    AND approval_id <> p_approval_id
    AND approval_status IN ('CLAIMED', 'APPROVED', 'SENT', 'colleague_approved', 'colleague_edited_approved', 'final_sent_by_jk')
  ORDER BY coalesce(colleague_replied_at, updated_at) ASC
  LIMIT 1;

  IF FOUND OR q.approval_status = 'SUPERSEDED_BY_PEER' THEN
    v_time_str := to_char(coalesce(winner.colleague_replied_at, q.superseded_at, now()) AT TIME ZONE 'Asia/Taipei', 'HH24:MI');
    v_notice := format(
      '🔒 此封信已於 %s 由【%s】認領並送交 JK 最終審核（內容可於 Dashboard 查看），系統已自動攔截重複發送並將您的回覆轉為內部補充備註；若需修正請走修正單。',
      v_time_str,
      coalesce(winner.target_employee_name, q.superseded_by_employee_name, '同儕')
    );
    UPDATE public.lark_colleague_approval_queue
    SET approval_status = 'SUPERSEDED_BY_PEER',
        jk_final_send_status = 'SUPERSEDED_BY_PEER',
        superseded_by_approval_id = coalesce(winner.approval_id, superseded_by_approval_id),
        superseded_by_employee_name = coalesce(winner.target_employee_name, superseded_by_employee_name),
        superseded_at = coalesce(superseded_at, now()),
        late_reply_attempt_text = p_reply_text,
        late_reply_intercepted_at = now(),
        collision_intercept_notice = v_notice,
        interaction_channel = v_mode,
        updated_at = now()
    WHERE approval_id = p_approval_id
    RETURNING * INTO q;

    PERFORM public.r49_log(p_approval_id, 'supplement_submitted', greatest(0, p_response_seconds), 'COLLISION_INTERCEPTED -> converted to internal supplement: ' || v_notice, v_mode);
    INSERT INTO public.audit_event(table_name, record_id, op, actor_id, after_val)
    VALUES('lark_colleague_approval_queue', p_approval_id::text, 'UPDATE', q.target_employee_name, to_jsonb(q));
    RETURN to_jsonb(q) || jsonb_build_object('collision_intercepted', true, 'auto_reply_notice', v_notice, 'jk_final_send_status', 'SUPERSEDED_BY_PEER');
  END IF;

  IF q.approval_status <> 'pending_colleague' THEN
    RAISE EXCEPTION 'approval already resolved';
  END IF;

  v_body := q.proposed_body;
  IF t IN ('發', '可以發', '好', '好，發', '核准', '✅ 核准並由中樞發出', '🔒 我先認領處理') OR upper(t) = 'OK' OR t LIKE '[卡片點擊]%' OR t LIKE 'OK%' THEN
    a := 'lark_reply_approve';
    st := 'colleague_approved';
    v_jk_st := 'PENDING_JK_FINAL_APPROVAL';
  ELSIF t ~ '^改[：:]\s*\S' THEN
    a := 'lark_reply_edit';
    st := 'colleague_edited_approved';
    v_jk_st := 'PENDING_JK_FINAL_APPROVAL';
    v_body := regexp_replace(t, '^改[：:]\s*', '');
  ELSIF t IN ('緩', '不發', '暫緩') THEN
    a := 'lark_query';
    st := 'colleague_rejected';
    v_jk_st := 'PENDING_COLLEAGUE';
  ELSIF t LIKE '%問%' OR t LIKE '%查%' OR t LIKE '%哪張圖%' OR t LIKE '%？%' OR t LIKE '%?%' THEN
    PERFORM public.r49_log(p_approval_id, 'lark_query', greatest(0, p_response_seconds), 'NL Query: ' || t, 'nl');
    RETURN to_jsonb(q) || jsonb_build_object(
      'nl_query_response',
      format('🤖 【業主聯繫 Lark Agent 回覆 %s】已為您檢索關聯圖資：%s；內文抽取期限：%s。您可以直接點擊卡片「✅ 核准（送交 JK 審核）」或繼續用自然語言指示修改。', q.target_employee_name, q.operon_connected_docs_diff, q.operon_extracted_deadline)
    );
  ELSE
    a := 'lark_reply_edit';
    st := 'colleague_edited_approved';
    v_jk_st := 'PENDING_JK_FINAL_APPROVAL';
    v_mode := 'nl';
    v_body := q.proposed_body || E'\n【依 ' || q.target_employee_name || ' 自然語言指示更新】：' || t;
  END IF;

  UPDATE public.lark_colleague_approval_queue
  SET approval_status = st,
      jk_final_send_status = v_jk_st,
      colleague_reply_text = p_reply_text,
      colleague_reply_msg_id = p_reply_msg_id,
      colleague_replied_at = now(),
      response_seconds = greatest(0, p_response_seconds),
      proposed_body = v_body,
      interaction_channel = v_mode,
      updated_at = now()
  WHERE approval_id = p_approval_id AND approval_status = 'pending_colleague'
  RETURNING * INTO q;

  IF st IN ('colleague_approved', 'colleague_edited_approved') THEN
    v_time_str := to_char(now() AT TIME ZONE 'Asia/Taipei', 'HH24:MI');
    v_notice := format(
      '🔒 已由【%s】於 %s 認領並送交 JK 最終審核（防重複回覆鎖定中）',
      q.target_employee_name,
      v_time_str
    );
    UPDATE public.lark_colleague_approval_queue
    SET approval_status = 'SUPERSEDED_BY_PEER',
        jk_final_send_status = 'SUPERSEDED_BY_PEER',
        superseded_by_approval_id = q.approval_id,
        superseded_by_employee_name = q.target_employee_name,
        superseded_at = now(),
        collision_intercept_notice = v_notice,
        updated_at = now()
    WHERE inbound_email_id = q.inbound_email_id
      AND approval_id <> q.approval_id
      AND approval_status = 'pending_colleague';
  END IF;

  PERFORM public.r49_log(p_approval_id, a, q.response_seconds, 'Colleague response (' || v_mode || ') -> PENDING_JK_FINAL_APPROVAL', v_mode);
  RETURN to_jsonb(q) || jsonb_build_object(
    'collision_intercepted', false,
    'interaction_mode', v_mode,
    'jk_final_send_status', v_jk_st,
    'auto_send_blocked_by_hard_lock_1', true
  );
END $function$;

-- Backfill existing rows to comply with Hard Locks #1, #2, #3
UPDATE public.lark_cli_outbound_dispatch
SET jk_final_send_status = 'PENDING_JK_FINAL_APPROVAL',
    updated_at = now()
WHERE jk_final_send_status = 'READY_FOR_JK_SEND';

UPDATE public.lark_cli_outbound_dispatch
SET test_recipient_email = 'jekai@yxsurvey.com.tw',
    operon_workflow_card = COALESCE(operon_workflow_card, '{}'::jsonb) || jsonb_build_object(
      'recipient_badge', format('🎯 按下後實際收件人：%s', coalesce(client_sender, '業主窗口')),
      'test_guard_badge', '🎯 測試保護中：按下只會寄至 jekai@yxsurvey.com.tw（許竣凱），不會外發業主',
      'allowed_test_recipient', 'jekai@yxsurvey.com.tw',
      'jk_final_lock_policy', 'PENDING_JK_FINAL_APPROVAL'
    );

UPDATE public.lark_colleague_approval_queue
SET jk_final_send_status = CASE
      WHEN approval_status = 'final_sent_by_jk' THEN 'SENT_FROM_JK_DRYRUN'
      WHEN approval_status IN ('colleague_approved', 'colleague_edited_approved') THEN 'PENDING_JK_FINAL_APPROVAL'
      WHEN approval_status = 'SUPERSEDED_BY_PEER' THEN 'SUPERSEDED_BY_PEER'
      ELSE 'PENDING_COLLEAGUE'
    END,
    test_recipient_email = 'jekai@yxsurvey.com.tw',
    lark_card_json = COALESCE(lark_card_json, '{}'::jsonb) || jsonb_build_object(
      'recipient_badge', format('🎯 按下後實際收件人：%s', coalesce(proposed_recipient, '業主窗口')),
      'test_guard_badge', '🎯 測試保護中：按下只會寄至 jekai@yxsurvey.com.tw（許竣凱），不會外發業主',
      'allowed_test_recipient', 'jekai@yxsurvey.com.tw',
      'jk_final_lock_policy', 'PENDING_JK_FINAL_APPROVAL'
    );

-- ============================================================================
-- R52 Hard Lock Assertion Proof Function (SW-LARK-HARDLOCK-01 ~ 03)
-- ============================================================================
CREATE OR REPLACE FUNCTION public.r52_hard_lock_assert_all()
RETURNS jsonb
LANGUAGE plpgsql
AS $function$
DECLARE
  v_card jsonb;
  v_blocked_gmail boolean := false;
  v_blocked_ext boolean := false;
  v_blocked_autofin boolean := false;
BEGIN
  ASSERT current_database() != 'yongxiang_plumb', 'FATAL: refusing production DB';
  ASSERT current_database() = 'yongxiang_plumb_r39_clone', 'FATAL: must run on clone DB';

  -- SW-LARK-HARDLOCK-01: Colleague replies transition to PENDING_JK_FINAL_APPROVAL, never auto-send
  IF EXISTS (
    SELECT 1 FROM public.lark_cli_outbound_dispatch
    WHERE jk_final_send_status IN ('READY_FOR_JK_SEND', 'SENT_FROM_JK_LIVE')
  ) THEN
    RAISE EXCEPTION 'SW-LARK-HARDLOCK-01 failed: found unheld READY_FOR_JK_SEND or SENT_FROM_JK_LIVE row';
  END IF;

  IF EXISTS (
    SELECT 1 FROM public.lark_cli_outbound_dispatch
    WHERE reply_status IN ('APPROVED', 'EDITED_AND_APPROVED')
      AND pm_solution_synced = false
      AND jk_final_send_status <> 'PENDING_JK_FINAL_APPROVAL'
  ) THEN
    RAISE EXCEPTION 'SW-LARK-HARDLOCK-01 failed: colleague-approved unfinalized row not in PENDING_JK_FINAL_APPROVAL';
  END IF;

  BEGIN
    PERFORM public.r50_part2_cas_decide(
      gen_random_uuid(), '吳柏頤', 'APPROVE', 'CARD_MODE', '核准', NULL, true
    );
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM LIKE '%JK_FINAL_CONFIRMATION_REQUIRED%' THEN
      v_blocked_autofin := true;
    END IF;
  END;
  IF NOT v_blocked_autofin THEN
    RAISE EXCEPTION 'SW-LARK-HARDLOCK-01 failed: p_auto_jk_finalize=true was not blocked';
  END IF;

  -- SW-LARK-HARDLOCK-02: Test recipient strictly locked to jekai@yxsurvey.com.tw
  IF public.r52_enforce_test_recipient('jekai@yxsurvey.com.tw') <> 'jekai@yxsurvey.com.tw' THEN
    RAISE EXCEPTION 'SW-LARK-HARDLOCK-02 failed: allowlisted jekai@yxsurvey.com.tw rejected';
  END IF;

  BEGIN
    PERFORM public.r52_enforce_test_recipient('test.user@gmail.com');
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM LIKE '%BLOCKED_NON_WHITELIST_RECIPIENT%' THEN
      v_blocked_gmail := true;
    END IF;
  END;
  IF NOT v_blocked_gmail THEN
    RAISE EXCEPTION 'SW-LARK-HARDLOCK-02 failed: @gmail.com recipient was not blocked';
  END IF;

  BEGIN
    PERFORM public.r52_enforce_test_recipient('lin.ceci@example.com');
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM LIKE '%BLOCKED_NON_WHITELIST_RECIPIENT%' THEN
      v_blocked_ext := true;
    END IF;
  END;
  IF NOT v_blocked_ext THEN
    RAISE EXCEPTION 'SW-LARK-HARDLOCK-02 failed: external client recipient was not blocked in test mode';
  END IF;

  IF EXISTS (
    SELECT 1 FROM public.lark_cli_outbound_dispatch WHERE test_recipient_email <> 'jekai@yxsurvey.com.tw'
  ) OR EXISTS (
    SELECT 1 FROM public.lark_colleague_approval_queue WHERE test_recipient_email <> 'jekai@yxsurvey.com.tw'
  ) THEN
    RAISE EXCEPTION 'SW-LARK-HARDLOCK-02 failed: non-whitelist test_recipient_email in DB tables';
  END IF;

  -- SW-LARK-HARDLOCK-03: Explicit recipient badge on all cards & dispatches
  v_card := public.operon_workflow_card_build('C115055-1', '測試主旨', '陳俊宏主任 <jh.chen@fpc.com.tw>', 1, true);
  IF (v_card->>'recipient_badge') NOT LIKE '🎯 按下後實際收件人：%<jh.chen@fpc.com.tw>%'
     OR (v_card->>'test_guard_badge') NOT LIKE '%jekai@yxsurvey.com.tw%' THEN
    RAISE EXCEPTION 'SW-LARK-HARDLOCK-03 failed: operon_workflow_card_build missing recipient badge';
  END IF;

  IF EXISTS (
    SELECT 1 FROM public.lark_cli_outbound_dispatch
    WHERE coalesce(operon_workflow_card->>'recipient_badge', '') NOT LIKE '🎯 按下後實際收件人：%'
  ) THEN
    RAISE EXCEPTION 'SW-LARK-HARDLOCK-03 failed: lark_cli_outbound_dispatch missing recipient_badge';
  END IF;

  RETURN jsonb_build_object(
    'SW-LARK-HARDLOCK-01', 'PASS',
    'SW-LARK-HARDLOCK-02', 'PASS',
    'SW-LARK-HARDLOCK-03', 'PASS',
    'pending_jk_final_approval_rows', (
      SELECT count(*) FROM public.lark_cli_outbound_dispatch WHERE jk_final_send_status = 'PENDING_JK_FINAL_APPROVAL'
    ),
    'allowed_test_recipient', 'jekai@yxsurvey.com.tw',
    'verified_db', current_database()
  );
END $function$;

-- Preserve canonical plumb_app REVOKE/GRANT surface
DO $$ DECLARE f record; BEGIN
  FOR f IN SELECT oid::regprocedure AS sig FROM pg_proc WHERE pronamespace='public'::regnamespace
  AND (proname LIKE 'r50%' OR proname IN ('lock_group','bump_draft_version','push_dispatch','handle_action','jk_finalize',
  'fn_claim_or_approve_lark_dispatch_cas','fn_dispatch_draft_to_colleagues_multi','lark_cli_push_to_colleague',
  'lark_cli_ingest_reply','jk_final_send_and_sync_pm_db','r49_process_colleague_reply')) LOOP
    EXECUTE format('REVOKE EXECUTE ON FUNCTION %s FROM PUBLIC,plumb_app',f.sig);
  END LOOP;
END $$;
GRANT EXECUTE ON FUNCTION public.handle_action(text,text,uuid,uuid,text,text,int,text,jsonb),
  public.push_dispatch(uuid,int,uuid,uuid),public.jk_finalize(uuid,uuid,uuid,text),
  public.bump_draft_version(uuid,text) TO plumb_app;
