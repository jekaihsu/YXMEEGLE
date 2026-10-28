-- Ticket 74 compatibility and authorization reconciliation. Clone only.
DO $guard$ BEGIN
  ASSERT current_database() = 'yongxiang_plumb_r39_clone';
  ASSERT current_database() != 'yongxiang_plumb';
END $guard$;
CREATE SCHEMA IF NOT EXISTS switchboard_ops;
GRANT USAGE ON SCHEMA switchboard_ops TO plumb_app;

-- A SET ROLE application connection never inherits the maintenance exception.
CREATE OR REPLACE FUNCTION public.r46_privileged() RETURNS boolean
LANGUAGE sql STABLE AS $$
 SELECT session_user IN ('postgres','box')
 AND current_user IN ('postgres','box');
$$;
CREATE OR REPLACE FUNCTION public.r46_authenticated_employee_id() RETURNS uuid
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
 SELECT e.id FROM public.api_session s JOIN public.employee e ON e.id=s.employee_id
 WHERE s.token_sha256 = nullif(current_setting('app.r47_session_sha256',true),'')
 AND length(s.token_sha256)=64 AND s.expires_at>now()
 AND s.org_id=e.org_id AND e.org_id='YX' AND e.employment_status='active'
 AND e.identity_confirmed AND s.lark_open_id=e.lark_open_id
 LIMIT 1;
$$;
CREATE OR REPLACE FUNCTION public.r46_effective_employee_id() RETURNS uuid
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
 SELECT coalesce(t.id,a.id) FROM public.api_session s
 JOIN public.employee a ON a.id=public.r46_authenticated_employee_id() AND a.id=s.employee_id
 LEFT JOIN public.employee t ON t.id=s.acting_as_employee_id AND t.org_id=a.org_id
   AND t.employment_status='active' AND a.role_code IN ('gm','it')
 WHERE s.token_sha256=current_setting('app.r47_session_sha256',true);
$$;
CREATE OR REPLACE FUNCTION public.r46_scope_code(p_scope text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$ SELECT CASE p_scope
 WHEN 'admin_finance' THEN 'ADMIN_SCOPE' WHEN 'pm_sales' THEN 'PM_SCOPE'
 WHEN 'management' THEN 'EXEC_SCOPE'
 WHEN 'engineering_indoor' THEN 'ENG_SCOPE' WHEN 'engineering_outdoor' THEN 'ENG_SCOPE'
 ELSE NULL END $$;
CREATE OR REPLACE FUNCTION public.r46_impersonate(p_token text,p_target uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE a uuid; sid uuid; role_name text;
BEGIN
 PERFORM set_config('app.r47_session_sha256',p_token,true);
 a:=public.r46_authenticated_employee_id();
 IF a IS NULL THEN RAISE EXCEPTION 'Authenticated session required' USING ERRCODE='28000'; END IF;
 SELECT role_code INTO role_name FROM public.employee WHERE id=a;
 IF role_name NOT IN ('gm','it') THEN RAISE EXCEPTION 'Impersonation requires IT or management' USING ERRCODE='42501'; END IF;
 IF p_target=a THEN p_target:=NULL; END IF;
 IF p_target IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.employee
 WHERE id=p_target AND org_id='YX' AND employment_status='active') THEN
 RAISE EXCEPTION 'Invalid impersonation target' USING ERRCODE='42501'; END IF;
 SELECT id INTO sid FROM public.api_session WHERE token_sha256=p_token FOR UPDATE;
 UPDATE public.impersonation_log SET ended_at=now() WHERE session_id=sid AND ended_at IS NULL;
 UPDATE public.api_session SET acting_as_employee_id=p_target,last_seen_at=now() WHERE token_sha256=p_token;
 IF p_target IS NOT NULL THEN
 INSERT INTO public.impersonation_log(session_id,actor_employee_id,target_employee_id)
 VALUES(sid,a,p_target); END IF;
 RETURN jsonb_build_object('ok',true,'actor_employee_id',a,'acting_as_employee_id',p_target);
END $$;
REVOKE ALL ON FUNCTION public.r46_impersonate(text,uuid) FROM PUBLIC;

-- Reconcile fields missing from the authoritative 67-person roster restored
-- by ticket 77. Do not reactivate the four retired placeholder identities.
UPDATE public.employee SET
 department=CASE department_name WHEN '行政' THEN '行政與財務組' WHEN 'PM' THEN '業務與PM組' ELSE '經營層' END,
 group_name=coalesce(team_code,department_name),
 role_code=CASE department_name WHEN '行政' THEN 'admin' WHEN 'PM' THEN 'pm' ELSE 'it' END,
 lark_open_id=coalesce(lark_open_id,'ou_sandbox_unconfirmed_'||replace(id::text,'-',''))
 WHERE org_id='YX' AND employment_status='active' AND department IS NULL;
INSERT INTO public.team_scope_map(department,group_pattern,team_scope,priority)
 SELECT '外業','^ROV船務組$','engineering_outdoor',10
 WHERE NOT EXISTS(SELECT 1 FROM public.team_scope_map
 WHERE department='外業' AND group_pattern='^ROV船務組$' AND team_scope='engineering_outdoor');
-- Correct only the mapped ROV team; retain the authoritative 67-person roster.
UPDATE public.employee SET group_name='ROV船務組'
 WHERE org_id='YX' AND employment_status='active' AND full_name IN ('張爲斌','劉允中');
UPDATE public.api_session s SET lark_open_id=e.lark_open_id,
 expires_at=least(s.expires_at,now()),acting_as_employee_id=NULL
 FROM public.employee e WHERE e.id=s.employee_id AND length(s.token_sha256)<>64;
REVOKE ALL ON public.api_session FROM plumb_app;
-- Transitions go through the guarded routines. Blanket grants in older R50
-- upgrades must not permit direct mutation of these authorization controls.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
 ON public.card, public.serial_cutover_log, public.prod_guard_state,
    public.email_message_disposition FROM PUBLIC, plumb_app;

CREATE OR REPLACE FUNCTION public.r46_document_access(p_viewer uuid,p_doc uuid)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
 SELECT EXISTS(SELECT 1 FROM public.case_document d
 JOIN public.staff_directory_v v ON v.employee_id=p_viewer
 WHERE d.id=p_doc AND NOT d.is_hr_private
 AND (v.team_scope NOT IN ('engineering_indoor','engineering_outdoor')
      OR d.doc_kind NOT IN ('invoice','billing','contract'))
 AND (NOT d.is_sealed_unpaid OR v.team_scope='admin_finance'));
$$;
REVOKE ALL ON FUNCTION public.r46_document_access(uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.r46_document_access(uuid,uuid) TO plumb_app;
CREATE OR REPLACE FUNCTION public.doc_permitted(p_viewer uuid,p_doc_id uuid)
RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT (public.r46_privileged() OR p_viewer=public.r46_effective_employee_id())
 AND public.r46_document_access(p_viewer,p_doc_id);
$$;

ALTER TABLE public.employee ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.card ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."case" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.case_document ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS r46_employee_read ON public.employee;
CREATE POLICY r46_employee_read ON public.employee FOR SELECT TO plumb_app
 USING (public.r46_authenticated_employee_id() IS NOT NULL AND org_id='YX' AND employment_status='active');
DROP POLICY IF EXISTS r46_case_read ON public."case";
CREATE POLICY r46_case_read ON public."case" FOR SELECT TO plumb_app
 USING (org_id='YX' AND public.r46_authenticated_employee_id() IS NOT NULL);
DROP POLICY IF EXISTS r46_card_read ON public.card;
CREATE POLICY r46_card_read ON public.card FOR SELECT TO plumb_app
 USING (org_id='YX' AND public.r46_authenticated_employee_id() IS NOT NULL);
DROP POLICY IF EXISTS r46_document_read ON public.case_document;
CREATE POLICY r46_document_read ON public.case_document FOR SELECT TO plumb_app
 USING (public.r46_authenticated_employee_id() IS NOT NULL
 AND public.r46_document_access(public.r46_effective_employee_id(),id));

-- Approval covers the reviewed content. Editing that content requires reapproval.
CREATE OR REPLACE FUNCTION public.r46_invalidate_approval() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
 IF NEW.final_body IS DISTINCT FROM OLD.final_body OR NEW.subject IS DISTINCT FROM OLD.subject
 OR NEW.to_contact_id IS DISTINCT FROM OLD.to_contact_id OR NEW.case_id IS DISTINCT FROM OLD.case_id THEN
   NEW.draft_body:=coalesce(NEW.final_body,NEW.draft_body); NEW.final_body:=NULL;
   NEW.approved_at:=NULL; NEW.approved_by:=NULL;
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS r46_invalidate_approval ON public.outbound_message;
CREATE TRIGGER r46_invalidate_approval BEFORE UPDATE ON public.outbound_message
 FOR EACH ROW EXECUTE FUNCTION public.r46_invalidate_approval();

ALTER TABLE public.card_action_log ADD COLUMN IF NOT EXISTS session_id uuid;
CREATE OR REPLACE FUNCTION public.r46_bind_action_actor() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE a uuid; s uuid;
BEGIN
 a:=public.r46_authenticated_employee_id();
 IF a IS NULL THEN RAISE EXCEPTION 'Authenticated action session required' USING ERRCODE='28000'; END IF;
 SELECT id INTO s FROM public.api_session WHERE token_sha256=current_setting('app.r47_session_sha256',true);
 IF NEW.actor_employee_id IS DISTINCT FROM a THEN
   RAISE EXCEPTION 'Action actor must match authenticated principal' USING ERRCODE='42501';
 END IF;
 NEW.session_id:=s; RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS r46_bind_action_actor ON public.card_action_log;
CREATE TRIGGER r46_bind_action_actor BEFORE INSERT OR UPDATE ON public.card_action_log
 FOR EACH ROW EXECUTE FUNCTION public.r46_bind_action_actor();

-- Retire legacy audit rows whose original session was never recorded; preserve
-- them as history rather than inventing an authenticated origin.
CREATE TABLE IF NOT EXISTS switchboard_ops.legacy_impersonation_log
 (LIKE public.impersonation_log INCLUDING DEFAULTS);
INSERT INTO switchboard_ops.legacy_impersonation_log
 SELECT l.* FROM public.impersonation_log l WHERE l.session_id IS NULL
 AND NOT EXISTS(SELECT 1 FROM switchboard_ops.legacy_impersonation_log a WHERE a.id=l.id);
DELETE FROM public.impersonation_log WHERE session_id IS NULL;

-- Real inbound keys are optional for imported history; new watcher events use
-- the reply Message-ID. UUID primary keys alone do not provide replay safety.
ALTER TABLE public.lark_agent_colleague_usage_log ADD COLUMN IF NOT EXISTS inbound_message_id text;
CREATE UNIQUE INDEX IF NOT EXISTS r46_usage_inbound_once
 ON public.lark_agent_colleague_usage_log(employee_id,inbound_message_id,action_type)
 WHERE inbound_message_id IS NOT NULL;
ALTER TABLE public.colleague_agent_usage_event ADD COLUMN IF NOT EXISTS tokens_source text NOT NULL DEFAULT 'ESTIMATED';
-- Imported sandbox history contains two finalized replays of one inbound key.
-- Preserve both final records; enforce one pending claim and forbid any new
-- claim or finalization once that key has a completed correspondence.
DROP INDEX IF EXISTS public.uq_r49_single_responder_claim;
CREATE UNIQUE INDEX uq_r49_single_responder_claim ON public.lark_colleague_approval_queue(inbound_email_id)
 WHERE final_correspondence_serial IS NULL AND approval_status IN
 ('CLAIMED','APPROVED','SENT','colleague_approved','colleague_edited_approved','final_sent_by_jk');
UPDATE public.lark_colleague_approval_queue q SET approval_status='final_sent_by_jk'
 WHERE q.final_correspondence_serial IS NOT NULL AND q.approval_status='SUPERSEDED_BY_PEER'
 AND EXISTS(SELECT 1 FROM public.lark_agent_colleague_usage_log u
 WHERE u.approval_id=q.approval_id AND u.action_type='final_outbound_sent');
CREATE OR REPLACE FUNCTION public.r46_preserve_final_approval() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
 IF TG_OP='UPDATE' AND OLD.final_correspondence_serial IS NOT NULL
 AND (NEW.final_correspondence_serial IS DISTINCT FROM OLD.final_correspondence_serial
 OR NEW.approval_status IS DISTINCT FROM 'final_sent_by_jk') THEN
 RAISE EXCEPTION 'Finalized approval cannot be superseded' USING ERRCODE='42501';
 END IF;
 IF (TG_OP='INSERT' OR OLD.final_correspondence_serial IS NULL)
 AND (NEW.final_correspondence_serial IS NOT NULL OR NEW.approval_status IN
 ('CLAIMED','APPROVED','SENT','colleague_approved','colleague_edited_approved','final_sent_by_jk'))
 AND EXISTS(SELECT 1 FROM public.lark_colleague_approval_queue q
 WHERE q.inbound_email_id=NEW.inbound_email_id AND q.approval_id<>NEW.approval_id
 AND q.final_correspondence_serial IS NOT NULL) THEN
 RAISE EXCEPTION 'Inbound correspondence already finalized' USING ERRCODE='42501';
 END IF;
 RETURN NEW; END $$;
DROP TRIGGER IF EXISTS r46_preserve_final_approval ON public.lark_colleague_approval_queue;
CREATE TRIGGER r46_preserve_final_approval BEFORE INSERT OR UPDATE ON public.lark_colleague_approval_queue
 FOR EACH ROW EXECUTE FUNCTION public.r46_preserve_final_approval();

-- Reconcile existing contracts without dropping their dependent views.
CREATE OR REPLACE FUNCTION public.session_list_for(p_viewer uuid, p_show_all boolean DEFAULT false)
 RETURNS TABLE(case_id uuid, case_code text, title text, ball text, line2 text, due_at timestamp with time zone, sort_key integer)
 LANGUAGE sql
 STABLE
AS $function$
  WITH v AS (
    SELECT team_scope FROM public.staff_directory_v WHERE employee_id = p_viewer
  ),
  mine AS (
    SELECT c.case_id, min(c.expires_at) AS due, max(c.priority) AS pri
      FROM public.card c
     WHERE c.assignee_employee_id = p_viewer
       AND c.state IN ('open','escalated','dry_run')
       AND c.case_id IS NOT NULL
     GROUP BY c.case_id
  ),
  in_scope AS (
    SELECT DISTINCT c.case_id
      FROM public.card c
      JOIN public.inbox_role_scope r ON r.inbox_role = c.role
      JOIN v ON v.team_scope = r.team_scope
     WHERE c.state IN ('open','escalated','dry_run')
       AND c.case_id IS NOT NULL
  )
  SELECT
    k.id AS case_id,
    k.case_code,
    k.title,
    CASE
      WHEN m.case_id IS NOT NULL THEN 'mine'
      WHEN EXISTS (SELECT 1 FROM public.card c WHERE c.case_id = k.id AND c.state IN ('open','escalated','dry_run')) THEN 'someone'
      ELSE 'client'
    END AS ball,
    public.case_line2(k.id, p_viewer) AS line2,
    m.due AS due_at,
    CASE
      WHEN m.due < now() THEN 1
      WHEN m.case_id IS NOT NULL THEN 2
      WHEN s.case_id IS NOT NULL THEN 3
      ELSE 4
    END AS sort_key
  FROM public."case" k
  LEFT JOIN mine m ON m.case_id = k.id
  LEFT JOIN in_scope s ON s.case_id = k.id
  WHERE EXISTS(SELECT 1 FROM v)
 AND (public.r46_privileged() OR p_viewer=public.r46_effective_employee_id())
 AND (m.case_id IS NOT NULL OR s.case_id IS NOT NULL OR p_show_all OR (SELECT team_scope FROM v)='management')
  ORDER BY sort_key ASC, m.pri DESC NULLS LAST, k.last_activity_at DESC NULLS LAST;
$function$
;
CREATE OR REPLACE FUNCTION public.r46_assert_all()
 RETURNS jsonb
 LANGUAGE plpgsql
AS $function$
DECLARE
  v_bad bigint;
  v_cnt bigint;
  v_sample_case uuid;
  v_admin_emp uuid := 'c22b9383-60ec-5bcf-8bb1-4131de44b420'::uuid; -- 羅薇
  v_eng_emp   uuid := '13394342-2826-5d5d-a26f-44e259279870'::uuid; -- 張家彬
BEGIN
  -- SW-SSO-01: every active YX employee has non-empty unique lark_open_id; every api_session.employee_id is active
  SELECT count(*) INTO v_bad
    FROM public.employee
   WHERE org_id = 'YX' AND employment_status = 'active'
     AND (lark_open_id IS NULL OR btrim(lark_open_id) = '');
  IF v_bad > 0 THEN
    RAISE EXCEPTION 'SW-SSO-01 FAILED: % active employee(s) missing lark_open_id', v_bad;
  END IF;

  SELECT count(*) - count(DISTINCT lark_open_id) INTO v_bad
    FROM public.employee
   WHERE org_id = 'YX' AND employment_status = 'active';
  IF v_bad > 0 THEN
    RAISE EXCEPTION 'SW-SSO-01 FAILED: % duplicate lark_open_id among active employees', v_bad;
  END IF;

  SELECT count(*) INTO v_bad
    FROM public.api_session s
    JOIN public.employee e ON e.id = s.employee_id
   WHERE e.employment_status <> 'active';
  IF v_bad > 0 THEN
    RAISE EXCEPTION 'SW-SSO-01 FAILED: % api_session row(s) point to non-active employee', v_bad;
  END IF;

  -- SW-SSO-02: every action is bound to its authenticated session principal.
  SELECT count(*) INTO v_bad FROM public.card_action_log l
  LEFT JOIN public.api_session s ON s.id=l.session_id
  WHERE s.id IS NULL OR l.actor_employee_id IS DISTINCT FROM s.employee_id;
  IF v_bad>0 THEN RAISE EXCEPTION 'SW-SSO-02: action/session mismatch'; END IF;
  -- SW-SCOPE-01: staff_directory_v has 0 unmapped rows and 67 active YX staff
  SELECT count(*) INTO v_bad FROM public.staff_directory_v WHERE team_scope = 'unmapped';
  IF v_bad > 0 THEN
    RAISE EXCEPTION 'SW-SCOPE-01 FAILED: % staff_directory_v row(s) are unmapped', v_bad;
  END IF;
  SELECT count(*) INTO v_cnt FROM public.staff_directory_v;
  IF v_cnt <> 67 THEN
    RAISE EXCEPTION 'SW-SCOPE-01 FAILED: expected 67 active staff in staff_directory_v, got %', v_cnt;
  END IF;

  -- SW-SCOPE-02: doc_scope_visibility covers all 13 doc_kind x 5 team_scope = 65 explicit rows
  SELECT count(*) INTO v_cnt FROM public.doc_scope_visibility;
  IF v_cnt < 65 THEN
    RAISE EXCEPTION 'SW-SCOPE-02 FAILED: expected 65 explicit rows in doc_scope_visibility, got %', v_cnt;
  END IF;

  -- SW-SCOPE-03: for every active employee X holding open/escalated/dry_run cards, session_list_for(X, false) includes 100% of their ball cases
  SELECT count(*) INTO v_bad
    FROM (
      SELECT DISTINCT c.assignee_employee_id AS emp_id, c.case_id
        FROM public.card c
        JOIN public.staff_directory_v v ON v.employee_id = c.assignee_employee_id
       WHERE c.state IN ('open','escalated','dry_run')
         AND c.case_id IS NOT NULL
    ) held
   WHERE NOT EXISTS (
     SELECT 1 FROM public.session_list_for(held.emp_id, false) sl
      WHERE sl.case_id = held.case_id AND sl.ball = 'mine'
   );
  IF v_bad > 0 THEN
    RAISE EXCEPTION 'SW-SCOPE-03 FAILED: % held case(s) hidden by team_scope filter', v_bad;
  END IF;

  -- SW-SCOPE-04: case_docs_for(engineer, case) even when expanded returns 0 hr_private or forbidden financial/contract docs
  SELECT id INTO v_sample_case FROM public."case" WHERE org_id = 'YX' AND case_code = 'C114109' LIMIT 1;
  IF v_sample_case IS NULL THEN
    SELECT case_id INTO v_sample_case FROM public.case_document LIMIT 1;
  END IF;

  SELECT count(*) INTO v_bad
    FROM public.case_docs_for(v_eng_emp, v_sample_case) d
    JOIN public.case_document raw ON raw.id = d.doc_id
   WHERE raw.is_hr_private OR d.doc_kind IN ('invoice', 'billing', 'contract');
  IF v_bad > 0 THEN
    RAISE EXCEPTION 'SW-SCOPE-04 FAILED: engineer case_docs_for leaked % restricted doc(s)', v_bad;
  END IF;

  -- SW-SCOPE-05: admin default visible docs are strictly in the 6 admin categories; engineer default visible docs are strictly in the 6 engineering categories
  SELECT count(*) INTO v_bad
    FROM public.case_docs_for(v_admin_emp, v_sample_case)
   WHERE visible_by_default
     AND doc_kind NOT IN ('contract','quote','billing','invoice','official_doc','client_letter');
  IF v_bad > 0 THEN
    RAISE EXCEPTION 'SW-SCOPE-05 FAILED: admin visible_by_default leaked % non-admin doc(s)', v_bad;
  END IF;

  SELECT count(*) INTO v_bad
    FROM public.case_docs_for(v_eng_emp, v_sample_case)
   WHERE visible_by_default
     AND doc_kind NOT IN ('cad','pointcloud','control_report','fix_pdf','site_photo','work_order');
  IF v_bad > 0 THEN
    RAISE EXCEPTION 'SW-SCOPE-05 FAILED: engineer visible_by_default leaked % non-engineering doc(s)', v_bad;
  END IF;

  RETURN jsonb_build_object(
    'SW-SSO-01', 'PASS',
    'SW-SSO-02', 'PASS',
    'SW-SCOPE-01', 'PASS:67',
    'SW-SCOPE-02', 'PASS:65',
    'SW-SCOPE-03', 'PASS',
    'SW-SCOPE-04', 'PASS',
    'SW-SCOPE-05', 'PASS'
  );
END;
$function$
;
CREATE OR REPLACE VIEW public.v_yezhu_team_scoped_docs AS  SELECT w.code AS case_code,
    d.doc_id,
    d.doc_scope,
    d.doc_type_label,
    d.file_name,
    d.status_tag,
    d.updated_label
   FROM yezhu_workbench_case w
     CROSS JOIN LATERAL ( VALUES (w.code || '-adm-1'::text,'admin'::text,'合約與用印歸檔'::text,w.code || '_工程承攬合約書_正本掃描.pdf'::text,'已用印歸檔'::text,'10/12 羅薇'::text), (w.code || '-adm-2'::text,'admin'::text,'請款單與發票憑證'::text,w.code || '_估驗計價請款單與發票明細.pdf'::text,
                CASE
                    WHEN w.code = 'C114609'::text THEN '尾款待入帳'::text
                    ELSE '已核對入帳'::text
                END,'10/18 孟君'::text), (w.code || '-adm-3'::text,'admin'::text,'業主往來函文與公文'::text,w.code || '_業主往來收發文紀錄表.pdf'::text,'流水號已同步'::text,'10/24 羅薇'::text), (w.code || '-pm-1'::text,'pm'::text,'工程確認單與排程'::text,w.code || '_工程確認單與里程碑排程表.pdf'::text,'PM 管控中'::text,'10/20 柏頤'::text), (w.code || '-pm-2'::text,'pm'::text,'報價單與變更追加'::text,w.code || '_報價單明細與工期承諾紀錄.pdf'::text,'業主已確認'::text,'10/22 振邦'::text), (w.code || '-pm-3'::text,'pm'::text,'成果交付對外摘要'::text,COALESCE(w.case_data ->> 'file'::text, w.code || '_對外交付成果摘要.pdf'::text),'對外版 PDF'::text,'10/24 柏頤'::text), (w.code || '-eng-1'::text,'eng'::text,'CAD 修正圖與對外版 PDF'::text,COALESCE(w.case_data ->> 'file'::text, w.code || '_修正圖面_對外版.pdf'::text),'圖資組已檢核'::text,'10/24 文澤'::text), (w.code || '-eng-2'::text,'eng'::text,'測量控制點與高程成果'::text,w.code || '_TWD97控制點座標與高程計算表.pdf'::text,'控制組已平差'::text,'10/23 重樺'::text), (w.code || '-eng-3'::text,'eng'::text,'外業現場照片與進場 JSA'::text,w.code || '_外業現場踏勘照片與工安紀錄.pdf'::text,'外業已上傳'::text,'10/23 恆安'::text)) d(doc_id, doc_scope, doc_type_label, file_name, status_tag, updated_label) WHERE public.r46_privileged() OR (public.r46_authenticated_employee_id() IS NOT NULL
 AND (d.doc_scope='eng' OR EXISTS(SELECT 1 FROM public.staff_directory_v s
 WHERE s.employee_id=public.r46_effective_employee_id() AND s.team_scope NOT IN ('engineering_indoor','engineering_outdoor'))));
CREATE OR REPLACE VIEW public.r50_colleague_agent_usage_rollup_v AS  SELECT e.employee_id,
    e.employee_name,
    e.department,
    count(u.event_id) FILTER (WHERE u.event_type = 'dispatch'::text) AS dispatches_received,
    count(u.event_id) FILTER (WHERE u.event_type = ANY (ARRAY['approve'::text, 'edit_and_approve'::text])) AS approvals_count,
    count(u.event_id) FILTER (WHERE u.event_type = 'edit_and_approve'::text) AS edits_count,
    count(u.event_id) FILTER (WHERE u.event_type = 'handoff'::text) AS handoffs_count,
    count(u.event_id) FILTER (WHERE u.event_type = 'agent_query'::text) AS agent_queries_count,
    count(u.event_id) FILTER (WHERE u.event_type <> 'dispatch'::text) AS total_interactions,
    round(avg(u.response_seconds) FILTER (WHERE u.event_type <> 'dispatch'::text), 1) AS avg_response_seconds,
    max(u.created_at) AS last_active_at,
    count(u.event_id) FILTER (WHERE u.event_type <> 'dispatch'::text AND (u.interaction_mode = ANY (ARRAY['CARD_MODE'::text, 'card_action'::text]))) AS card_actions_count,
    count(u.event_id) FILTER (WHERE u.event_type <> 'dispatch'::text AND (u.interaction_mode = ANY (ARRAY['NL_CHAT_MODE'::text, 'nl_chat'::text]))) AS nl_chat_turns_count,
    COALESCE(sum(u.tokens_used) FILTER (WHERE u.event_type <> 'dispatch'::text), 0::bigint) AS tokens_used,
    count(u.event_id) FILTER (WHERE u.event_type <> 'dispatch'::text AND (u.interaction_mode = ANY (ARRAY['NL_CHAT_MODE'::text, 'nl_chat'::text]))) AS nl_chat_count,
    count(u.event_id) FILTER (WHERE u.event_type = ANY (ARRAY['COLLISION_BLOCKED'::text, 'blocked_duplicate_responder'::text])) AS collision_saves_count,
    'SANDBOX_OBSERVED'::text AS dataset_kind,
    COALESCE(sum(u.tokens_used) FILTER (WHERE u.event_type <> 'dispatch'::text AND u.tokens_source='MEASURED_MODEL_USAGE'), 0::bigint) AS tokens_measured,
    COALESCE(sum(u.tokens_used) FILTER (WHERE u.event_type <> 'dispatch'::text AND u.tokens_source<>'MEASURED_MODEL_USAGE'), 0::bigint) AS tokens_estimated,
        CASE
            WHEN count(u.event_id) FILTER (WHERE u.event_type <> 'dispatch'::text AND u.tokens_used > 0) > 0 THEN 'SANDBOX_OBSERVED'::text
            ELSE 'NONE'::text
        END AS tokens_coverage,
    count(u.event_id) FILTER (WHERE u.event_type = ANY (ARRAY['claim'::text, 'approve'::text, 'edit_and_approve'::text])) AS claimed_to_hub_count
   FROM v_active_employee_directory e
     LEFT JOIN colleague_agent_usage_event u USING (employee_id)
  GROUP BY e.employee_id, e.employee_name, e.department;
CREATE OR REPLACE VIEW public.v_lark_colleague_usage_leaderboard AS  SELECT s.employee_id,
    s.full_name,
    s.department,
    s.group_name,
    s.job_title,
    s.team_scope,
    s.lark_open_id,
    count(u.usage_id) AS total_uses,
    count(*) FILTER (WHERE u.interaction_mode = 'card'::text AND u.action_type <> 'draft_pushed'::text) AS card_actions_count,
    count(*) FILTER (WHERE u.interaction_mode = 'nl'::text) AS nl_chat_turns_count,
    count(*) FILTER (WHERE u.action_type = 'draft_pushed'::text) AS drafts_pushed_count,
    count(*) FILTER (WHERE u.action_type = 'lark_reply_approve'::text) AS approved_count,
    count(*) FILTER (WHERE u.action_type = 'lark_reply_edit'::text) AS edited_count,
    count(*) FILTER (WHERE u.action_type = 'supplement_submitted'::text) AS supplement_count,
    count(*) FILTER (WHERE u.action_type = 'lark_query'::text) AS query_count,
    count(*) FILTER (WHERE u.action_type = 'final_outbound_sent'::text) AS final_sent_count,
    round(avg(u.response_seconds) / 60.0, 1)::numeric(6,1) AS avg_response_min,
    COALESCE(sum(u.tokens_used), 0::bigint) AS total_tokens,
    count(u.usage_id) * 6 AS estimated_saved_minutes,
    max(u.created_at) AS last_active_at,
    COALESCE(sum(u.tokens_used) FILTER (WHERE u.tokens_source = 'MEASURED_MODEL_USAGE'::text), 0::bigint) AS tokens_measured,
    COALESCE(sum(u.tokens_used) FILTER (WHERE u.tokens_source = 'ESTIMATED'::text), 0::bigint) AS tokens_estimated,
        CASE
            WHEN count(u.usage_id) FILTER (WHERE u.tokens_source = 'MEASURED_MODEL_USAGE'::text) > 0 AND count(u.usage_id) FILTER (WHERE u.tokens_source = 'ESTIMATED'::text) > 0 THEN 'MIXED'::text
            WHEN count(u.usage_id) FILTER (WHERE u.tokens_source = 'MEASURED_MODEL_USAGE'::text) > 0 THEN 'MEASURED'::text
            WHEN count(u.usage_id) FILTER (WHERE u.tokens_source = 'ESTIMATED'::text) > 0 THEN 'ESTIMATED_ONLY'::text
            ELSE 'NONE'::text
        END AS tokens_coverage,
    'SANDBOX_OBSERVED'::text AS dataset_kind,
    count(*) FILTER (WHERE u.action_type = ANY (ARRAY['lark_reply_approve'::text, 'lark_reply_edit'::text])) AS claimed_to_hub_count,
    count(*) FILTER (WHERE u.detail_note ~~ 'COLLISION_INTERCEPTED%'::text) AS collision_interceptions_count
   FROM staff_directory_v s
     LEFT JOIN lark_agent_colleague_usage_log u ON u.employee_id = s.employee_id AND u.org_id = 'YX'::text AND u.action_type IN ('lark_reply_approve','lark_reply_edit','lark_query','supplement_submitted')
  GROUP BY s.employee_id, s.full_name, s.department, s.group_name, s.job_title, s.team_scope, s.lark_open_id
  ORDER BY (count(u.usage_id)) DESC, (COALESCE(sum(u.tokens_used), 0::bigint)) DESC, s.full_name;
-- The legacy source never recorded an interaction mode. Preserve its original
-- totals and expose compatible metric names without inventing card/NL history.
CREATE OR REPLACE VIEW public.colleague_usage_leaderboard_v AS
 SELECT d.employee_id,d.full_name AS employee_name,d.department_group AS department,
 d.sub_group,d.job_title_display AS job_title,d.role_scope AS team_scope,d.lark_open_id,
 count(u.usage_id)::integer AS total_interactions,
 count(u.usage_id) FILTER(WHERE u.action_type='approve_send')::integer AS approved_sends,
 count(u.usage_id) FILTER(WHERE u.action_type IN ('edit_draft','supplement_file'))::integer AS edits_and_supplements,
 count(u.usage_id) FILTER(WHERE u.action_type IN ('query_bot','triage_assign'))::integer AS queries_and_triage,
 count(u.usage_id) FILTER(WHERE u.action_type='reject_draft')::integer AS rejected_drafts,
 coalesce(round(avg(u.response_seconds)/60.0,1),0.0)::numeric(10,1) AS avg_response_min,
 coalesce(sum(u.tokens_used),0::bigint) AS total_tokens,max(u.created_at) AS last_active_at,
 0::bigint AS card_actions_count,0::bigint AS nl_chat_turns_count,
 count(u.usage_id) AS unclassified_interactions_count,
 CASE WHEN count(u.usage_id)=0 THEN 'NO_EVENTS' ELSE 'UNRECORDED_LEGACY' END AS interaction_mode_coverage
 FROM public.v_yezhu_lark_directory d
 LEFT JOIN public.colleague_lark_agent_usage u ON u.employee_id::text=d.employee_id AND u.org_id='YX'
 GROUP BY d.employee_id,d.full_name,d.department_group,d.sub_group,d.job_title_display,d.role_scope,d.lark_open_id
 ORDER BY count(u.usage_id) DESC,coalesce(sum(u.tokens_used),0::bigint) DESC,d.full_name;
CREATE OR REPLACE VIEW public.r46_team_scope_directory AS
 SELECT s.*,public.r46_scope_code(team_scope) AS scope_code FROM public.staff_directory_v s;
CREATE OR REPLACE VIEW switchboard_ops.staff_directory_v WITH (security_invoker=true) AS SELECT * FROM public.staff_directory_v;
GRANT SELECT ON switchboard_ops.staff_directory_v TO plumb_app;
CREATE OR REPLACE VIEW switchboard_ops.v_yezhu_lark_directory WITH (security_invoker=true) AS SELECT * FROM public.v_yezhu_lark_directory;
GRANT SELECT ON switchboard_ops.v_yezhu_lark_directory TO plumb_app;
CREATE OR REPLACE VIEW switchboard_ops.v_yezhu_team_scoped_docs WITH (security_invoker=true) AS SELECT * FROM public.v_yezhu_team_scoped_docs;
GRANT SELECT ON switchboard_ops.v_yezhu_team_scoped_docs TO plumb_app;
CREATE OR REPLACE VIEW switchboard_ops.v_yezhu_team_scoped_cases WITH (security_invoker=true) AS SELECT * FROM public.v_yezhu_team_scoped_cases;
GRANT SELECT ON switchboard_ops.v_yezhu_team_scoped_cases TO plumb_app;
CREATE OR REPLACE VIEW switchboard_ops.v_active_employee_directory WITH (security_invoker=true) AS SELECT * FROM public.v_active_employee_directory;
GRANT SELECT ON switchboard_ops.v_active_employee_directory TO plumb_app;
CREATE OR REPLACE VIEW switchboard_ops.v_lark_colleague_usage_leaderboard WITH (security_invoker=true) AS SELECT * FROM public.v_lark_colleague_usage_leaderboard;
GRANT SELECT ON switchboard_ops.v_lark_colleague_usage_leaderboard TO plumb_app;
CREATE OR REPLACE VIEW switchboard_ops.colleague_usage_leaderboard_v WITH (security_invoker=true) AS SELECT * FROM public.colleague_usage_leaderboard_v;
GRANT SELECT ON switchboard_ops.colleague_usage_leaderboard_v TO plumb_app;
CREATE OR REPLACE VIEW switchboard_ops.colleague_agent_usage_summary_v WITH (security_invoker=true) AS SELECT * FROM public.colleague_agent_usage_summary_v;
GRANT SELECT ON switchboard_ops.colleague_agent_usage_summary_v TO plumb_app;
CREATE OR REPLACE VIEW switchboard_ops.r50_colleague_agent_usage_rollup_v WITH (security_invoker=true) AS SELECT * FROM public.r50_colleague_agent_usage_rollup_v;
GRANT SELECT ON switchboard_ops.r50_colleague_agent_usage_rollup_v TO plumb_app;
CREATE OR REPLACE VIEW switchboard_ops.r46_team_scope_directory WITH (security_invoker=true) AS SELECT * FROM public.r46_team_scope_directory;
GRANT SELECT ON switchboard_ops.r46_team_scope_directory TO plumb_app;
CREATE OR REPLACE VIEW switchboard_ops.team_scope_map WITH (security_invoker=true) AS SELECT * FROM public.team_scope_map;
GRANT SELECT ON switchboard_ops.team_scope_map TO plumb_app;
CREATE OR REPLACE VIEW switchboard_ops.doc_scope_visibility WITH (security_invoker=true) AS SELECT * FROM public.doc_scope_visibility;
GRANT SELECT ON switchboard_ops.doc_scope_visibility TO plumb_app;
CREATE OR REPLACE FUNCTION switchboard_ops.case_docs_for(p_viewer uuid, p_case uuid) RETURNS TABLE(doc_id uuid, doc_kind text, title text, version text, created_at timestamp with time zone, visible_by_default boolean) LANGUAGE sql STABLE AS $$ SELECT  * FROM public.case_docs_for($1,$2) $$;
CREATE OR REPLACE FUNCTION switchboard_ops.doc_permitted(p_viewer uuid, p_doc_id uuid) RETURNS boolean LANGUAGE sql STABLE AS $$ SELECT public.doc_permitted($1,$2) $$;
CREATE OR REPLACE FUNCTION switchboard_ops.people_picker(p_actor uuid, p_context text, p_case uuid DEFAULT NULL::uuid, p_q text DEFAULT NULL::text) RETURNS TABLE(employee_id uuid, full_name text, department text, group_name text, job_title text, avatar_url text, tier integer, tier_label text, badges text[], score real, team_scope text) LANGUAGE sql STABLE AS $$ SELECT  * FROM public.people_picker($1,$2,$3,$4) $$;
CREATE OR REPLACE FUNCTION switchboard_ops.r46_assert_all() RETURNS jsonb LANGUAGE sql STABLE AS $$ SELECT public.r46_assert_all() $$;
CREATE OR REPLACE FUNCTION switchboard_ops.session_list_for(p_viewer uuid, p_show_all boolean DEFAULT false) RETURNS TABLE(case_id uuid, case_code text, title text, ball text, line2 text, due_at timestamp with time zone, sort_key integer) LANGUAGE sql STABLE AS $$ SELECT  * FROM public.session_list_for($1,$2) $$;
CREATE OR REPLACE FUNCTION switchboard_ops.r46_authenticated_employee_id() RETURNS uuid LANGUAGE sql STABLE AS $$ SELECT public.r46_authenticated_employee_id() $$;
CREATE OR REPLACE FUNCTION switchboard_ops.r46_effective_employee_id() RETURNS uuid LANGUAGE sql STABLE AS $$ SELECT public.r46_effective_employee_id() $$;
CREATE OR REPLACE FUNCTION switchboard_ops.r46_privileged() RETURNS boolean LANGUAGE sql STABLE AS $$ SELECT public.r46_privileged() $$;
CREATE OR REPLACE FUNCTION switchboard_ops.r46_scope_code(p_scope text) RETURNS text LANGUAGE sql STABLE AS $$ SELECT public.r46_scope_code($1) $$;
DO $$ BEGIN
 ASSERT (SELECT count(*) FROM public.staff_directory_v)=67;
 ASSERT (SELECT count(DISTINCT scope_code) FROM public.r46_team_scope_directory)=4;
 ASSERT NOT EXISTS(SELECT 1 FROM public.staff_directory_v WHERE full_name LIKE '%宣蓉%');
 ASSERT (SELECT count(*) FROM public.v_lark_colleague_usage_leaderboard)=67;
END $$;

CREATE OR REPLACE FUNCTION public.r49_log(p_id uuid, p_action text, p_seconds integer DEFAULT NULL::integer, p_note text DEFAULT NULL::text, p_mode text DEFAULT 'card'::text)
 RETURNS void
 LANGUAGE plpgsql
AS $function$
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
    case_code, approval_id, tokens_used, response_seconds, detail_note, interaction_mode, inbound_message_id
  )
  SELECT q.target_employee_id, q.target_employee_name, q.target_department, s.team_scope, p_action,
         q.case_code, q.approval_id, v_tok, p_seconds, p_note, coalesce(p_mode, 'card'), q.colleague_reply_msg_id
  FROM public.lark_colleague_approval_queue q
  JOIN public.staff_directory_v s ON s.employee_id = q.target_employee_id
  WHERE approval_id = p_id ON CONFLICT DO NOTHING;
END $function$
;
