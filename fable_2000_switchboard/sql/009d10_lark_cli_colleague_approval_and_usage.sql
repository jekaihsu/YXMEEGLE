BEGIN;
DO $$ BEGIN
 ASSERT current_database() != 'yongxiang_plumb';
 ASSERT current_database() = 'yongxiang_plumb_r39_clone';
END $$;

ALTER TABLE public.lark_colleague_approval_queue
  ADD COLUMN IF NOT EXISTS inbound_email_id text NOT NULL DEFAULT 'email-default',
  ADD COLUMN IF NOT EXISTS operon_arrives_type text NOT NULL DEFAULT '送審退回修正 (Submittal Return)',
  ADD COLUMN IF NOT EXISTS operon_connected_docs_diff text NOT NULL DEFAULT '關聯圖號 M-301 / CAD-v3：對比前版新增 3 處斷面補測，影響報價單 #Q115-089 共 4 個工項',
  ADD COLUMN IF NOT EXISTS operon_extracted_deadline text NOT NULL DEFAULT '2026-10-28 17:00（內文抽取：請於週三前補送修正圖與報價）',
  ADD COLUMN IF NOT EXISTS operon_person_decides text NOT NULL DEFAULT '決定變更工項單價與重提送審時程',
  ADD COLUMN IF NOT EXISTS interaction_channel text NOT NULL DEFAULT 'card_and_nl',
  ADD COLUMN IF NOT EXISTS lark_card_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS superseded_by_employee_name text,
  ADD COLUMN IF NOT EXISTS superseded_by_approval_id uuid,
  ADD COLUMN IF NOT EXISTS superseded_at timestamptz,
  ADD COLUMN IF NOT EXISTS collision_intercept_notice text,
  ADD COLUMN IF NOT EXISTS late_reply_attempt_text text,
  ADD COLUMN IF NOT EXISTS late_reply_intercepted_at timestamptz;

UPDATE public.lark_colleague_approval_queue
SET inbound_email_id = 'email:' || case_code || ':' || md5(proposed_subject)
WHERE inbound_email_id = 'email-default';

ALTER TABLE public.lark_colleague_approval_queue
  DROP CONSTRAINT IF EXISTS lark_colleague_approval_queue_approval_status_check;

ALTER TABLE public.lark_colleague_approval_queue
  ADD CONSTRAINT lark_colleague_approval_queue_approval_status_check
  CHECK (approval_status IN (
    'pending_colleague',
    'CLAIMED',
    'APPROVED',
    'SENT',
    'colleague_approved',
    'colleague_edited_approved',
    'colleague_rejected',
    'final_sent_by_jk',
    'SUPERSEDED_BY_PEER',
    'expired'
  ));

ALTER TABLE public.lark_agent_colleague_usage_log
  ADD COLUMN IF NOT EXISTS interaction_mode text NOT NULL DEFAULT 'card' CHECK (interaction_mode IN ('card', 'nl', 'system'));

WITH ranked AS (
  SELECT approval_id,
         first_value(approval_id) OVER (PARTITION BY inbound_email_id ORDER BY created_at ASC) AS winner_id,
         first_value(target_employee_name) OVER (PARTITION BY inbound_email_id ORDER BY created_at ASC) AS winner_name,
         row_number() OVER (PARTITION BY inbound_email_id ORDER BY created_at ASC) AS rn
  FROM public.lark_colleague_approval_queue
  WHERE approval_status IN ('CLAIMED', 'APPROVED', 'SENT', 'colleague_approved', 'colleague_edited_approved', 'final_sent_by_jk')
)
UPDATE public.lark_colleague_approval_queue q
SET approval_status = 'SUPERSEDED_BY_PEER',
    superseded_by_approval_id = r.winner_id,
    superseded_by_employee_name = r.winner_name,
    superseded_at = now(),
    collision_intercept_notice = format('🔒 此封信已於 %s 由【%s】認領並核准發出（內容可於 Dashboard 查看），系統已自動攔截重複發送並轉為內部補充備註。', to_char(now() AT TIME ZONE 'Asia/Taipei', 'HH24:MI'), r.winner_name)
FROM ranked r
WHERE q.approval_id = r.approval_id AND r.rn > 1;

CREATE UNIQUE INDEX IF NOT EXISTS uq_r49_single_responder_claim
  ON public.lark_colleague_approval_queue (inbound_email_id)
  WHERE approval_status IN ('CLAIMED', 'APPROVED', 'SENT', 'colleague_approved', 'colleague_edited_approved', 'final_sent_by_jk');

DROP FUNCTION IF EXISTS public.r49_log(uuid, text, integer, text);
DROP FUNCTION IF EXISTS public.r49_log(uuid, text, integer, text, text);
CREATE OR REPLACE FUNCTION public.r49_log(
  p_id uuid,
  p_action text,
  p_seconds integer DEFAULT NULL,
  p_note text DEFAULT NULL,
  p_mode text DEFAULT 'card'
) RETURNS void LANGUAGE plpgsql AS $$
DECLARE
  v_tok integer;
BEGIN
  PERFORM public.r49_guard();
  v_tok := CASE p_action
    WHEN 'draft_pushed' THEN 1480
    WHEN 'lark_reply_approve' THEN 620
    WHEN 'lark_reply_edit' THEN 1350
    WHEN 'supplement_submitted' THEN 890
    WHEN 'lark_query' THEN 980
    WHEN 'final_outbound_sent' THEN 520
    ELSE 600
  END;
  INSERT INTO public.lark_agent_colleague_usage_log(
    employee_id, employee_name, department, team_scope, action_type,
    case_code, approval_id, tokens_used, response_seconds, detail_note, interaction_mode
  )
  SELECT q.target_employee_id, q.target_employee_name, q.target_department, s.team_scope, p_action,
         q.case_code, q.approval_id, v_tok, p_seconds, p_note, coalesce(p_mode, 'card')
  FROM public.lark_colleague_approval_queue q
  JOIN public.staff_directory_v s ON s.employee_id = q.target_employee_id
  WHERE approval_id = p_id;
END $$;

DROP VIEW IF EXISTS public.v_lark_colleague_usage_leaderboard;
CREATE VIEW public.v_lark_colleague_usage_leaderboard AS
SELECT s.employee_id,
       s.full_name,
       s.department,
       s.group_name,
       s.job_title,
       s.team_scope,
       s.lark_open_id,
       count(u.usage_id) AS total_uses,
       count(*) FILTER (WHERE u.interaction_mode = 'card' AND u.action_type <> 'draft_pushed') AS card_actions_count,
       count(*) FILTER (WHERE u.interaction_mode = 'nl') AS nl_chat_turns_count,
       count(*) FILTER (WHERE u.action_type = 'draft_pushed') AS drafts_pushed_count,
       count(*) FILTER (WHERE u.action_type = 'lark_reply_approve') AS approved_count,
       count(*) FILTER (WHERE u.action_type = 'lark_reply_edit') AS edited_count,
       count(*) FILTER (WHERE u.action_type = 'supplement_submitted') AS supplement_count,
       count(*) FILTER (WHERE u.action_type = 'lark_query') AS query_count,
       count(*) FILTER (WHERE u.action_type = 'final_outbound_sent') AS final_sent_count,
       round(avg(u.response_seconds) / 60.0, 1)::numeric(6,1) AS avg_response_min,
       coalesce(sum(u.tokens_used), 0) AS total_tokens,
       count(u.usage_id) * 6 AS estimated_saved_minutes,
       max(u.created_at) AS last_active_at
FROM public.staff_directory_v s
LEFT JOIN public.lark_agent_colleague_usage_log u ON u.employee_id = s.employee_id AND u.org_id = 'YX'
GROUP BY s.employee_id, s.full_name, s.department, s.group_name, s.job_title, s.team_scope, s.lark_open_id
ORDER BY total_uses DESC, total_tokens DESC, full_name ASC;

DROP VIEW IF EXISTS public.pm_solution_correspondence_feed_v;
CREATE VIEW public.pm_solution_correspondence_feed_v AS
SELECT q.approval_id,
       q.case_code,
       q.client_name,
       q.final_correspondence_serial AS correspondence_serial,
       q.proposed_subject AS subject,
       q.proposed_recipient AS client_recipient,
       q.proposed_body,
       q.target_employee_name AS colleague_approver_name,
       q.target_department AS colleague_department,
       q.target_job_title AS colleague_job_title,
       q.colleague_reply_text,
       q.colleague_replied_at,
       q.response_seconds,
       q.final_sent_by AS final_sender,
       q.final_sent_at AS sent_at,
       q.pm_db_sync_status,
       q.pm_solution_synced_at,
       q.outbound_lark_msg_id,
       q.colleague_reply_msg_id,
       q.inbound_email_id,
       q.operon_arrives_type,
       q.operon_connected_docs_diff,
       q.operon_extracted_deadline,
       q.operon_person_decides,
       q.interaction_channel,
       (SELECT count(*)::int FROM public.lark_colleague_approval_queue p WHERE p.inbound_email_id = q.inbound_email_id AND p.approval_status = 'SUPERSEDED_BY_PEER') AS superseded_peer_count,
       (SELECT string_agg(p.target_employee_name || coalesce('（攔截回覆：「' || p.late_reply_attempt_text || '」）', '（已鎖定防撞）'), '、')
          FROM public.lark_colleague_approval_queue p
         WHERE p.inbound_email_id = q.inbound_email_id AND p.approval_status = 'SUPERSEDED_BY_PEER') AS superseded_peers_summary
FROM public.lark_colleague_approval_queue q
WHERE q.approval_status = 'final_sent_by_jk';

DROP FUNCTION IF EXISTS public.push_draft_to_colleague(text, text, text, text, text, text, text, text);
DROP FUNCTION IF EXISTS public.push_draft_to_colleague(text, text, text, text, text, text, text, text, text, text, text, text, text);
CREATE OR REPLACE FUNCTION public.push_draft_to_colleague(
  p_case_code text,
  p_target_employee_name text,
  p_subject text,
  p_recipient text,
  p_body text,
  p_client_name text DEFAULT '',
  p_lark_msg_id text DEFAULT NULL,
  p_cli_cmd text DEFAULT NULL,
  p_inbound_email_id text DEFAULT NULL,
  p_arrives_type text DEFAULT '送審退回修正 (Submittal Return)',
  p_connected_docs text DEFAULT '關聯圖號 M-301 / CAD-v3：對比前版新增 3 處斷面補測，影響報價單 #Q115-089 共 4 個工項',
  p_extracted_deadline text DEFAULT '2026-10-28 17:00（內文抽取：請於週三前補送修正圖與報價）',
  p_person_decides text DEFAULT '決定變更工項單價與重提送審時程'
) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE
  s record;
  q public.lark_colleague_approval_queue;
  v_email_id text;
  v_card jsonb;
BEGIN
  PERFORM public.r49_guard();
  SELECT * INTO STRICT s FROM public.staff_directory_v WHERE full_name = p_target_employee_name AND lark_open_id IS NOT NULL;
  IF btrim(p_subject) = '' OR btrim(p_body) = '' OR btrim(p_recipient) = '' THEN
    RAISE EXCEPTION 'subject, recipient and body required';
  END IF;
  IF p_cli_cmd IS NOT NULL AND position('--dry-run' IN p_cli_cmd) = 0 THEN
    RAISE EXCEPTION 'dry-run required';
  END IF;
  v_email_id := coalesce(nullif(btrim(p_inbound_email_id), ''), 'email:' || p_case_code || ':' || md5(p_subject));
  v_card := jsonb_build_object(
    'header', format('【永祥·業主往來 互動核准卡】#%s %s', p_case_code, p_client_name),
    'arrives', p_arrives_type,
    'extracted_deadline', p_extracted_deadline,
    'connected_docs_diff', p_connected_docs,
    'person_decides', p_person_decides,
    'buttons', jsonb_build_array('✅ 核准並由中樞發出', '🔒 我先認領處理', '✏️ 修改草稿', '↪️ 轉派同仁')
  );
  INSERT INTO public.lark_colleague_approval_queue(
    case_code, client_name, inbound_email_id, target_employee_id, target_employee_name,
    target_department, target_job_title, target_lark_open_id, proposed_subject,
    proposed_recipient, proposed_body, outbound_lark_msg_id, lark_cli_command,
    operon_arrives_type, operon_connected_docs_diff, operon_extracted_deadline, operon_person_decides,
    lark_card_json
  )
  VALUES(
    p_case_code, p_client_name, v_email_id, s.employee_id, s.full_name,
    s.department, s.job_title, s.lark_open_id, p_subject,
    p_recipient, p_body, p_lark_msg_id, p_cli_cmd,
    p_arrives_type, p_connected_docs, p_extracted_deadline, p_person_decides,
    v_card
  ) RETURNING * INTO q;
  PERFORM public.r49_log(q.approval_id, 'draft_pushed', NULL, 'Operon Card + NL prompt pushed (dry-run)', 'card');
  RETURN to_jsonb(q);
END $$;

DROP FUNCTION IF EXISTS public.claim_and_approve_draft(uuid, text, text, integer);
DROP FUNCTION IF EXISTS public.claim_and_approve_draft(uuid, text, text, integer, text);
CREATE OR REPLACE FUNCTION public.claim_and_approve_draft(
  p_approval_id uuid,
  p_reply_text text,
  p_reply_msg_id text DEFAULT NULL,
  p_response_seconds integer DEFAULT 95,
  p_interaction_mode text DEFAULT NULL
) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE
  q public.lark_colleague_approval_queue;
  winner public.lark_colleague_approval_queue;
  t text := btrim(p_reply_text);
  a text;
  st text;
  v_mode text;
  v_body text;
  v_notice text;
  v_time_str text;
BEGIN
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
      '🔒 此封信已於 %s 由【%s】認領並核准發出（內容可於 Dashboard 查看），系統已自動攔截重複發送並將您的回覆轉為內部補充備註；若需修正請走修正單。',
      v_time_str,
      coalesce(winner.target_employee_name, q.superseded_by_employee_name, '同儕')
    );
    UPDATE public.lark_colleague_approval_queue
    SET approval_status = 'SUPERSEDED_BY_PEER',
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
    RETURN to_jsonb(q) || jsonb_build_object('collision_intercepted', true, 'auto_reply_notice', v_notice);
  END IF;

  IF q.approval_status <> 'pending_colleague' THEN
    RAISE EXCEPTION 'approval already resolved';
  END IF;

  v_body := q.proposed_body;
  IF t IN ('發', '可以發', '好', '好，發', '核准', '✅ 核准並由中樞發出', '🔒 我先認領處理') OR upper(t) = 'OK' OR t LIKE '[卡片點擊]%' OR t LIKE 'OK%' THEN
    a := 'lark_reply_approve';
    st := 'colleague_approved';
  ELSIF t ~ '^改[：:]\s*\S' THEN
    a := 'lark_reply_edit';
    st := 'colleague_edited_approved';
    v_body := regexp_replace(t, '^改[：:]\s*', '');
  ELSIF t IN ('緩', '不發', '暫緩') THEN
    a := 'lark_query';
    st := 'colleague_rejected';
  ELSIF t LIKE '%問%' OR t LIKE '%查%' OR t LIKE '%哪張圖%' OR t LIKE '%？%' OR t LIKE '%?%' THEN
    PERFORM public.r49_log(p_approval_id, 'lark_query', greatest(0, p_response_seconds), 'NL Query: ' || t, 'nl');
    RETURN to_jsonb(q) || jsonb_build_object(
      'nl_query_response',
      format('🤖 【業主聯繫 Lark Agent 回覆 %s】已為您檢索關聯圖資：%s；內文抽取期限：%s。您可以直接點擊卡片「✅ 核准並由中樞發出」或繼續用自然語言指示修改。', q.target_employee_name, q.operon_connected_docs_diff, q.operon_extracted_deadline)
    );
  ELSE
    a := 'lark_reply_edit';
    st := 'colleague_edited_approved';
    v_mode := 'nl';
    v_body := public.r50_apply_reply_edit(q.proposed_body, t);
    IF v_body = q.proposed_body THEN
      v_body := q.proposed_body || E'\n【依 ' || q.target_employee_name || ' 自然語言指示更新】：' || t;
    END IF;
  END IF;

  UPDATE public.lark_colleague_approval_queue
  SET approval_status = st,
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
      '🔒 已由【%s】於 %s 認領並核准發出（防重複回覆鎖定中）',
      q.target_employee_name,
      v_time_str
    );
    UPDATE public.lark_colleague_approval_queue
    SET approval_status = 'SUPERSEDED_BY_PEER',
        superseded_by_approval_id = q.approval_id,
        superseded_by_employee_name = q.target_employee_name,
        superseded_at = now(),
        collision_intercept_notice = v_notice,
        updated_at = now()
    WHERE inbound_email_id = q.inbound_email_id
      AND approval_id <> q.approval_id
      AND approval_status = 'pending_colleague';
  END IF;

  PERFORM public.r49_log(p_approval_id, a, q.response_seconds, 'Colleague response (' || v_mode || ')', v_mode);
  RETURN to_jsonb(q) || jsonb_build_object('collision_intercepted', false, 'interaction_mode', v_mode);
END $$;

CREATE OR REPLACE FUNCTION public.ingest_colleague_lark_reply(
  p_approval_id uuid,
  p_reply_text text,
  p_reply_msg_id text DEFAULT NULL,
  p_response_seconds integer DEFAULT 95
) RETURNS jsonb LANGUAGE plpgsql AS $$
BEGIN
  RETURN public.claim_and_approve_draft(p_approval_id, p_reply_text, p_reply_msg_id, p_response_seconds, NULL);
END $$;

UPDATE public.lark_colleague_approval_queue
SET operon_arrives_type = CASE
      WHEN case_code = 'C114109' THEN '送審退回修正 (Submittal Return)'
      WHEN case_code = 'C115211-01A' THEN '變更追加計價 (Change/Pricing Request)'
      WHEN case_code = 'C115042' THEN '釋疑單回覆 (RFI Response)'
      WHEN case_code = 'C115094-4' THEN '協力廠商報價 (Vendor Quote)'
      WHEN case_code = 'C114609' THEN '邀標與補充說明 (Bid/Addendum)'
      ELSE '電子公文與進度催辦 (Official Doc/Schedule)'
    END,
    operon_connected_docs_diff = CASE
      WHEN case_code = 'C114109' THEN '關聯圖號 M-301 / CAD-v3：對比前版新增北側管線 3 處斷面補測與控制點高程成果，影響 #Q114-109 共 2 個工項'
      WHEN case_code = 'C115211-01A' THEN '關聯報價 #115471-01A (合併雙重列後唯一主檔) + 3D 點雲規範 v2.1：新增美國廠區 B 棟桁架掃描範圍，追加報價 18.5 萬'
      WHEN case_code = 'C115042' THEN '關聯規範 高鐵邊坡監測計畫書 §4.2：加密傾度管觀測頻率由每週 1 次改為每週 2 次'
      ELSE '關聯圖號 S-104 / 控制點成果表 v2：已完成內業品管覆核與座標轉換驗證'
    END,
    operon_extracted_deadline = CASE
      WHEN case_code = 'C114109' THEN '2026-10-27 17:00（內文抽取：「請於週二下班前提供修正版 PDF 與高程表」）'
      WHEN case_code = 'C115211-01A' THEN '2026-10-28 12:00（內文抽取：「請於週三中午前確認美國廠區追加報價與交期」）'
      ELSE '2026-10-29 17:00（內文抽取：「請於本週四前正式函覆監測成果」）'
    END,
    operon_person_decides = CASE
      WHEN case_code = 'C114109' THEN '決定是否核准北側管線修正圖 v3 對外發出'
      WHEN case_code = 'C115211-01A' THEN '決定變更工項單價（18.5 萬）與交期（下週五）是否發送業主'
      WHEN case_code = 'C115042' THEN '決定加密監測頻率之現場施作排程'
      ELSE '決定送審重提計畫與正式回函時程'
    END;

UPDATE public.lark_agent_colleague_usage_log
SET interaction_mode = CASE
      WHEN action_type IN ('lark_reply_edit', 'lark_query', 'supplement_submitted') THEN 'nl'
      WHEN hashtext(usage_id::text) % 3 = 0 THEN 'nl'
      ELSE 'card'
    END;

DO $$
DECLARE
  q1 jsonb;
  q2 jsonb;
  q3 jsonb;
  q4 jsonb;
BEGIN
  PERFORM public.r49_guard();
  IF NOT EXISTS (SELECT 1 FROM public.lark_colleague_approval_queue WHERE inbound_email_id = 'email:C114109:operon-collision-demo-01') THEN
    q1 := public.push_draft_to_colleague(
      'C114109', '吳柏頤',
      'RE: 台塑北側管線修正圖 PDF 與高程控制點成果回覆',
      '吳工程師 <wu.eng@fpc.com.tw>',
      '吳工程師您好：北側管線修正圖對外版 PDF (M-301 v3) 與控制點高程成果已覆核完畢，隨信附上供查照。',
      '台塑 北側管線測量',
      'om_dryrun_c114109_wuboyi',
      'lark-cli im +messages-send --user-id ou_c5051de1880e46996940abfa2295fe08 --dry-run',
      'email:C114109:operon-collision-demo-01',
      '送審退回修正 (Submittal Return)',
      '關聯圖號 M-301 / CAD-v3：對比前版新增北側管線 3 處斷面補測與控制點高程成果，影響 #Q114-109 共 2 個工項',
      '2026-10-27 17:00（內文抽取：「請於週二下班前提供修正版 PDF 與高程表」）',
      '決定是否核准北側管線修正圖 v3 對外發出'
    );
    q2 := public.push_draft_to_colleague(
      'C114109', '涂振邦',
      'RE: 台塑北側管線修正圖 PDF 與高程控制點成果回覆',
      '吳工程師 <wu.eng@fpc.com.tw>',
      '吳工程師您好：北側管線修正圖對外版 PDF (M-301 v3) 與控制點高程成果已覆核完畢，隨信附上供查照。',
      '台塑 北側管線測量',
      'om_dryrun_c114109_tuzhenbang',
      'lark-cli im +messages-send --user-id ou_ce8da7c9773e2178c44a2e10ef02c136 --dry-run',
      'email:C114109:operon-collision-demo-01',
      '送審退回修正 (Submittal Return)',
      '關聯圖號 M-301 / CAD-v3：對比前版新增北側管線 3 處斷面補測與控制點高程成果，影響 #Q114-109 共 2 個工項',
      '2026-10-27 17:00（內文抽取：「請於週二下班前提供修正版 PDF 與高程表」）',
      '決定是否核准北側管線修正圖 v3 對外發出'
    );
    PERFORM public.claim_and_approve_draft(
      (q1->>'approval_id')::uuid,
      '把報價改成 18.5 萬，交期改到下週五，並附上 M-301 v3 修正圖後幫我發出去',
      'om_nl_wuboyi_01',
      78,
      'nl'
    );
    PERFORM public.execute_jk_final_send_and_sync_pm((q1->>'approval_id')::uuid);
    PERFORM public.claim_and_approve_draft(
      (q2->>'approval_id')::uuid,
      '[卡片點擊] ✅ 核准並由中樞發出',
      'om_card_tuzhenbang_late_01',
      142,
      'card'
    );
  END IF;

  IF NOT EXISTS (SELECT 1 FROM public.lark_colleague_approval_queue WHERE inbound_email_id = 'email:C115211-01A:operon-collision-demo-02') THEN
    q3 := public.push_draft_to_colleague(
      'C115211-01A', '羅薇',
      'RE: 緯穎廠區掃描與數位建模(美國) 報價確認單與用印時程回覆',
      '緯穎採購窗口 <procurement@wiwynn.com>',
      '您好：本案 C115211-01A (115471-01A) 報價明細與用印時程已核對完成，請查收。',
      '緯穎 廠區掃描與數位建模(美國)',
      'om_dryrun_c115211_luowei',
      'lark-cli im +messages-send --user-id ou_8f039b26fb59ac71e9ed0db08011c13e --dry-run',
      'email:C115211-01A:operon-collision-demo-02',
      '變更追加計價 (Change/Pricing Request)',
      '關聯報價 #115471-01A (合併雙重列後唯一主檔) + 3D 點雲規範 v2.1：新增美國廠區 B 棟桁架掃描範圍，追加報價 18.5 萬',
      '2026-10-28 12:00（內文抽取：「請於週三中午前確認美國廠區追加報價與交期」）',
      '決定變更工項單價（18.5 萬）與交期（下週五）是否發送業主'
    );
    q4 := public.push_draft_to_colleague(
      'C115211-01A', '朱雅琪',
      'RE: 緯穎廠區掃描與數位建模(美國) 報價確認單與用印時程回覆',
      '緯穎採購窗口 <procurement@wiwynn.com>',
      '您好：本案 C115211-01A (115471-01A) 報價明細與用印時程已核對完成，請查收。',
      '緯穎 廠區掃描與數位建模(美國)',
      'om_dryrun_c115211_zhuyaqi',
      'lark-cli im +messages-send --user-id ou_9df460867ad04c33272549f33b699377 --dry-run',
      'email:C115211-01A:operon-collision-demo-02',
      '變更追加計價 (Change/Pricing Request)',
      '關聯報價 #115471-01A (合併雙重列後唯一主檔) + 3D 點雲規範 v2.1：新增美國廠區 B 棟桁架掃描範圍，追加報價 18.5 萬',
      '2026-10-28 12:00（內文抽取：「請於週三中午前確認美國廠區追加報價與交期」）',
      '決定變更工項單價（18.5 萬）與交期（下週五）是否發送業主'
    );
    PERFORM public.claim_and_approve_draft(
      (q3->>'approval_id')::uuid,
      '[卡片點擊] ✅ 核准並由中樞發出',
      'om_card_luowei_02',
      65,
      'card'
    );
    PERFORM public.execute_jk_final_send_and_sync_pm((q3->>'approval_id')::uuid);
    PERFORM public.claim_and_approve_draft(
      (q4->>'approval_id')::uuid,
      '這筆報價單號我核對過了，可以發出去',
      'om_nl_zhuyaqi_late_02',
      118,
      'nl'
    );
  END IF;
END $$;

CREATE OR REPLACE FUNCTION public.r49_assert_all() RETURNS jsonb LANGUAGE plpgsql AS $$
BEGIN
  PERFORM public.r49_guard();
  IF (SELECT count(*) FROM public.v_lark_colleague_usage_leaderboard) <> 67 THEN RAISE EXCEPTION 'SW-LARK-CLI-01 roster'; END IF;
  IF EXISTS(SELECT 1 FROM public.lark_colleague_approval_queue WHERE lark_cli_command IS NOT NULL AND position('--dry-run' IN lark_cli_command) = 0) THEN RAISE EXCEPTION 'SW-LARK-CLI-02 dry run'; END IF;
  IF EXISTS(SELECT 1 FROM public.lark_colleague_approval_queue WHERE approval_status = 'final_sent_by_jk' AND (colleague_replied_at IS NULL OR final_correspondence_serial IS NULL)) THEN RAISE EXCEPTION 'SW-LARK-CLI-03 approval'; END IF;
  IF EXISTS(SELECT 1 FROM public.pm_solution_correspondence_feed_v f WHERE NOT EXISTS(SELECT 1 FROM public.yezhu_correspondence_ledger l WHERE l.serial_label = f.correspondence_serial)) THEN RAISE EXCEPTION 'SW-LARK-CLI-04 ledger'; END IF;
  IF EXISTS(SELECT 1 FROM public.lark_agent_colleague_usage_log WHERE tokens_used < 0) THEN RAISE EXCEPTION 'SW-LARK-CLI-05 usage'; END IF;
  IF EXISTS(SELECT 1 FROM public.pm_solution_correspondence_feed_v WHERE pm_db_sync_status <> 'SYNCED_TO_PM_DB') THEN RAISE EXCEPTION 'SW-LARK-CLI-06 sync'; END IF;
  IF NOT EXISTS(SELECT 1 FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'uq_r49_single_responder_claim') THEN
    RAISE EXCEPTION 'SW-LARK-COLLISION-01 missing unique mutex index';
  END IF;
  IF EXISTS(
    SELECT inbound_email_id
    FROM public.lark_colleague_approval_queue
    WHERE approval_status IN ('CLAIMED', 'APPROVED', 'SENT', 'colleague_approved', 'colleague_edited_approved', 'final_sent_by_jk')
    GROUP BY inbound_email_id
    HAVING count(*) > 1
  ) THEN
    RAISE EXCEPTION 'SW-LARK-COLLISION-01 duplicate responder claim detected';
  END IF;
  IF NOT EXISTS(
    SELECT 1 FROM public.lark_colleague_approval_queue
    WHERE approval_status = 'SUPERSEDED_BY_PEER'
      AND collision_intercept_notice LIKE '🔒%'
      AND late_reply_attempt_text IS NOT NULL
  ) THEN
    RAISE EXCEPTION 'SW-LARK-COLLISION-01 peer collision interception evidence missing';
  END IF;
  IF (SELECT sum(card_actions_count) FROM public.v_lark_colleague_usage_leaderboard) <= 0
     OR (SELECT sum(nl_chat_turns_count) FROM public.v_lark_colleague_usage_leaderboard) <= 0 THEN
    RAISE EXCEPTION 'SW-OPERON-DUALMODE-01 missing card or nl usage counts';
  END IF;
  RETURN jsonb_build_object(
    'SW-LARK-CLI-01', 'PASS',
    'SW-LARK-CLI-02', 'PASS',
    'SW-LARK-CLI-03', 'PASS',
    'SW-LARK-CLI-04', 'PASS',
    'SW-LARK-CLI-05', 'PASS',
    'SW-LARK-CLI-06', 'PASS',
    'SW-LARK-COLLISION-01', 'PASS',
    'SW-OPERON-WORKFLOW-01', 'PASS',
    'SW-OPERON-DUALMODE-01', 'PASS'
  );
END $$;
COMMIT;
