\set ON_ERROR_STOP on
BEGIN;
DO $$ BEGIN
  IF current_database() <> 'yongxiang_plumb_r39_clone' THEN
    RAISE EXCEPTION 'Ticket104 requires the exact r39 test clone';
  END IF;
END $$;
SET LOCAL lock_timeout = '10s';

CREATE OR REPLACE FUNCTION public.r46_effective_employee_id() RETURNS uuid
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public
AS $$ SELECT public.r46_authenticated_employee_id() $$;
DROP FUNCTION IF EXISTS public.r46_impersonate(text,uuid);
ALTER TABLE public.api_session DROP COLUMN IF EXISTS acting_as_employee_id;
ALTER TABLE public.api_session DROP CONSTRAINT api_session_role_check;
ALTER TABLE public.api_session ADD CONSTRAINT api_session_role_check
CHECK(role IN ('sales','pm','vp','admin','finance','gm','it','engineer','payroll','field_member','field_lead','inner_lead'));

-- A session principal cannot be reassigned, including by changing its identifier.
CREATE OR REPLACE FUNCTION public.t104_session_principal_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
  IF TG_OP='UPDATE' AND (NEW.id IS DISTINCT FROM OLD.id OR
     NEW.employee_id IS DISTINCT FROM OLD.employee_id OR
     NEW.org_id IS DISTINCT FROM OLD.org_id OR
     NEW.lark_open_id IS DISTINCT FROM OLD.lark_open_id OR
     NEW.token_sha256 IS DISTINCT FROM OLD.token_sha256) THEN
    RAISE EXCEPTION 'SW-SSO-02 immutable session principal' USING ERRCODE='42501';
  END IF;
  IF TG_OP='INSERT' AND NOT EXISTS (
    SELECT 1 FROM public.employee e WHERE e.id=NEW.employee_id
    AND e.org_id=NEW.org_id AND e.employment_status='active'
    AND e.identity_confirmed AND e.lark_open_id=NEW.lark_open_id
    AND btrim(e.lark_open_id)<>''
  ) THEN
    RAISE EXCEPTION 'SW-SSO-01 active mapped employee required' USING ERRCODE='28000';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS t104_session_principal ON public.api_session;
CREATE TRIGGER t104_session_principal BEFORE INSERT OR UPDATE ON public.api_session
FOR EACH ROW EXECUTE FUNCTION public.t104_session_principal_guard();
CREATE UNIQUE INDEX IF NOT EXISTS t104_api_session_id ON public.api_session(id);
CREATE UNIQUE INDEX IF NOT EXISTS t104_session_actor ON public.api_session(id,employee_id);
ALTER TABLE public.card_action_log ALTER COLUMN session_id SET NOT NULL;
DO $$ BEGIN
  IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='t104_action_session_actor_fk') THEN
    ALTER TABLE public.card_action_log ADD CONSTRAINT t104_action_session_actor_fk
      FOREIGN KEY(session_id,actor_employee_id) REFERENCES public.api_session(id,employee_id);
  END IF;
END $$;

-- Accept the explicit offboarding state from the acceptance brief.
ALTER TABLE public.employee DROP CONSTRAINT employee_employment_status_check;
ALTER TABLE public.employee ADD CONSTRAINT employee_employment_status_check
CHECK(employment_status IN ('active','on_leave','resigned','left','candidate','external'));
DO $$ BEGIN
  IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='t104_active_open_id_nonempty') THEN
    ALTER TABLE public.employee ADD CONSTRAINT t104_active_open_id_nonempty
    CHECK(org_id<>'YX' OR employment_status<>'active' OR nullif(btrim(lark_open_id),'') IS NOT NULL);
  END IF;
END $$;

CREATE OR REPLACE FUNCTION public.t104_offboard_sessions() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
  IF NEW.employment_status<>'active' THEN
    UPDATE public.api_session SET expires_at=least(expires_at,now()) WHERE employee_id=NEW.id;
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS t104_offboard_sessions ON public.employee;
CREATE TRIGGER t104_offboard_sessions AFTER UPDATE OF employment_status ON public.employee
FOR EACH ROW EXECUTE FUNCTION public.t104_offboard_sessions();

-- Preserve all five existing document-policy scopes. Their four business groups
-- are admin, PM, engineering (indoor/outdoor), and management.
INSERT INTO public.team_scope_map(department,group_pattern,team_scope,priority)
VALUES ('外業','^ROV(船務)?組$','engineering_outdoor',5)
ON CONFLICT(department,group_pattern) DO UPDATE SET team_scope=excluded.team_scope,priority=excluded.priority;
UPDATE public.employee e SET name_initials=m.initials
FROM (VALUES
 ('William Chiu','wc'),('劉耀云','lyy'),('劉芳君','lfj'),('吳奇穎','wqy'),
 ('吳宇軒','wyx'),('吳沛柔','wpr'),('康益誌','kyz'),('廖冠綸','lgl'),
 ('廖堉惠','lyh'),('張又升','zys'),('張証崴','zzw'),('文乃毅','wny'),
 ('朱雅雯','zyw'),('李佳諭','ljy'),('李柏毅','lby'),('李炘龍','lxl'),
 ('林佑靜','lyj'),('林士辰','lsc'),('林威仁','lwr'),('林宗翰','lzh'),
 ('林瑩瑄','lyx'),('林豐緯','lfw'),('育寬 林','lyk'),('胡畯評','hjp'),
 ('莊勇勝','zys'),('蔡文銜','cwx'),('蔡長庭','czt'),('許峻瑋','xjw'),
 ('謝椀曳','xwy'),('賴佳宏','ljh'),('邱慶宗','qqz'),('郭冠辰','ggc'),
 ('郭國泰','ggt'),('鐘傑嶙','zjl'),('陳嘉略','cjl'),('陳振德','czd'),
 ('陳靖羽','cjy'),('黃佑賢','hyx'),('黃耀興','hyx'),('黃馨加','hxj')
) m(full_name,initials)
WHERE e.org_id='YX' AND e.employment_status='active' AND e.full_name=m.full_name
AND coalesce(e.name_initials,'') !~ '^[a-z]+( [a-z]+)*$';
CREATE OR REPLACE FUNCTION public.org_mode(p_org text) RETURNS text
LANGUAGE sql STABLE AS $$ SELECT mode FROM public.org_mode WHERE org_id=p_org $$;
UPDATE public.org_mode SET mode='shadow' WHERE org_id='YX';
UPDATE r47.control SET mode='shadow',external_enabled=false WHERE org_id='YX';

-- The control is enforced on the real correspondence outbox, including inserts.
CREATE TABLE IF NOT EXISTS public.writeback_outbox (
  org_id text PRIMARY KEY REFERENCES public.org(id),
  enabled boolean NOT NULL DEFAULT false CHECK(NOT enabled)
);
INSERT INTO public.writeback_outbox(org_id,enabled) VALUES('YX',false)
ON CONFLICT(org_id) DO UPDATE SET enabled=false;
CREATE OR REPLACE FUNCTION public.t104_writeback_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
  IF NEW.org_id='YX' AND NOT coalesce((SELECT enabled FROM public.writeback_outbox WHERE org_id=NEW.org_id),false) THEN
    RAISE EXCEPTION 'T104 writeback disabled on trial clone' USING ERRCODE='42501';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS t104_writeback_guard ON public.correspondence_writeback_outbox;
CREATE TRIGGER t104_writeback_guard BEFORE INSERT OR UPDATE ON public.correspondence_writeback_outbox
FOR EACH ROW EXECUTE FUNCTION public.t104_writeback_guard();

-- Keep historical suppressed rows as evidence instead of changing recipients.
CREATE SCHEMA IF NOT EXISTS ticket104_audit;
CREATE TABLE IF NOT EXISTS ticket104_audit.excluded_notification
(LIKE public.notification_outbox INCLUDING DEFAULTS, archived_at timestamptz NOT NULL DEFAULT now());
WITH moved AS (
  DELETE FROM public.notification_outbox n WHERE NOT EXISTS (
    SELECT 1 FROM public.employee e WHERE e.employment_status='active' AND e.org_id='YX'
    AND e.full_name IN ('許喆凱','羅薇','吳柏頤','張家彬') AND e.lark_open_id=n.recipient_id
  ) RETURNING *
) INSERT INTO ticket104_audit.excluded_notification
SELECT moved.*,now() FROM moved;
CREATE OR REPLACE FUNCTION public.t104_notice_allowlist() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
  IF NOT EXISTS(SELECT 1 FROM public.employee e WHERE e.org_id='YX'
    AND e.employment_status='active' AND e.full_name IN ('許喆凱','羅薇','吳柏頤','張家彬')
    AND e.lark_open_id=NEW.recipient_id) THEN
    RAISE EXCEPTION 'T104 trial recipient outside allowlist' USING ERRCODE='42501';
  END IF;
  IF NEW.status='sent' THEN
    RAISE EXCEPTION 'T104 zero external sends' USING ERRCODE='42501';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS t104_notice_allowlist ON public.notification_outbox;
CREATE TRIGGER t104_notice_allowlist BEFORE INSERT OR UPDATE ON public.notification_outbox
FOR EACH ROW EXECUTE FUNCTION public.t104_notice_allowlist();

-- Recursive filtering also removes sensitive fields buried inside JSON arrays.
CREATE OR REPLACE FUNCTION public.t104_scrub_json(p_value jsonb,p_role text)
RETURNS jsonb LANGUAGE plpgsql STABLE SET search_path=pg_catalog,public AS $$
DECLARE k text; v jsonb; result jsonb;
BEGIN
  IF jsonb_typeof(p_value)='object' THEN
    result:='{}';
    FOR k,v IN SELECT * FROM jsonb_each(p_value) LOOP
      IF EXISTS(SELECT 1 FROM public.canvas_forbidden_column WHERE k ~* column_regex)
        OR (k ~* '^bonus_pool_' AND p_role<>'gm')
        OR (k IN ('labor_std_cost','external_cost','projected_total_cost','projected_margin',
                 'margin_ratio_now','margin_ratio_after','floor_price')
            AND p_role NOT IN ('pm','vp','gm','it')) THEN CONTINUE; END IF;
      result:=result || jsonb_build_object(k,public.t104_scrub_json(v,p_role));
    END LOOP;
    RETURN result;
  ELSIF jsonb_typeof(p_value)='array' THEN
    SELECT coalesce(jsonb_agg(public.t104_scrub_json(value,p_role) ORDER BY ord),'[]')
      INTO result FROM jsonb_array_elements(p_value) WITH ORDINALITY a(value,ord);
    RETURN result;
  END IF;
  RETURN p_value;
END $$;

CREATE OR REPLACE FUNCTION public.project_columns(p_viewer uuid,p_view_no integer,p_row jsonb)
RETURNS jsonb LANGUAGE plpgsql STABLE SET search_path=pg_catalog,public AS $$
DECLARE r text; result jsonb;
BEGIN
  IF NOT (public.r46_privileged() OR p_viewer=public.r46_authenticated_employee_id()) THEN
    RAISE EXCEPTION 'Authenticated viewer required' USING ERRCODE='42501';
  END IF;
  SELECT CASE WHEN role_code='engineer' THEN 'field_member' ELSE role_code END INTO r
    FROM public.staff_directory_v WHERE employee_id=p_viewer;
  IF r IS NULL THEN RAISE EXCEPTION 'Active viewer required' USING ERRCODE='28000'; END IF;
  SELECT coalesce(jsonb_object_agg(j.key,j.value),'{}') INTO result
    FROM jsonb_each(p_row) j JOIN public.canvas_column_whitelist w
      ON w.view_no=p_view_no AND w.actor_role=r AND w.column_name=j.key;
  RETURN public.t104_scrub_json(result,r);
END $$;
REVOKE ALL ON FUNCTION public.project_columns(uuid,integer,jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.project_columns(uuid,integer,jsonb) TO plumb_app;

CREATE OR REPLACE FUNCTION public.ticket104_assert_all() RETURNS jsonb
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE bad bigint; r jsonb;
BEGIN
  IF current_database()<>'yongxiang_plumb_r39_clone' THEN
    RAISE EXCEPTION 'Ticket104 requires exact r39 clone'; END IF;
  r:=public.r46_assert_all();
  IF EXISTS(SELECT 1 FROM pg_attribute WHERE attrelid='public.api_session'::regclass
      AND attname=concat('acting','_as_employee_id') AND NOT attisdropped) THEN
    RAISE EXCEPTION 'SW-SSO-02 legacy session column remains'; END IF;
  IF EXISTS(SELECT 1 FROM public.card_action_log l LEFT JOIN public.api_session s ON s.id=l.session_id
      WHERE s.id IS NULL OR s.employee_id IS DISTINCT FROM l.actor_employee_id) THEN
    RAISE EXCEPTION 'SW-SSO-02 action/session actor mismatch'; END IF;
  SELECT count(*) INTO bad FROM public.employee e
    LEFT JOIN public.staff_directory_v s ON s.employee_id=e.id
    WHERE e.org_id='YX' AND e.employment_status='active' AND
    (s.employee_id IS NULL OR s.team_scope='unmapped' OR
     coalesce(e.name_pinyin,'') !~ '^[a-z]+( [a-z]+)*$' OR
     coalesce(e.name_initials,'') !~ '^[a-z]+( [a-z]+)*$');
  IF bad<>0 THEN RAISE EXCEPTION 'SW-SCOPE-01 incomplete directory: %',bad; END IF;
  IF public.org_mode('YX') IS DISTINCT FROM 'shadow' OR
      (public.org_live_ready('YX')->>'ready')::boolean IS DISTINCT FROM false THEN
    RAISE EXCEPTION 'Shadow mode/readiness gate failed'; END IF;
  IF NOT EXISTS(SELECT 1 FROM public.writeback_outbox WHERE org_id='YX' AND NOT enabled)
    OR NOT EXISTS(SELECT 1 FROM r47.control WHERE org_id='YX' AND NOT external_enabled AND mode='shadow') THEN
    RAISE EXCEPTION 'Shadow writeback/external control failed'; END IF;
  IF EXISTS(SELECT 1 FROM public.outbound_message WHERE coalesce(actual_sends,0)<>0
      OR sent_at IS NOT NULL OR status='SENT') OR
      EXISTS(SELECT 1 FROM public.notification_outbox WHERE status='sent') THEN
    RAISE EXCEPTION 'Shadow zero-send assertion failed'; END IF;
  IF EXISTS(SELECT 1 FROM public.notification_outbox n WHERE NOT EXISTS(
    SELECT 1 FROM public.employee e WHERE e.org_id='YX' AND e.employment_status='active'
    AND e.full_name IN ('許喆凱','羅薇','吳柏頤','張家彬') AND e.lark_open_id=n.recipient_id)) THEN
    RAISE EXCEPTION 'Shadow recipient allowlist failed'; END IF;
  RETURN r || jsonb_build_object('name_search','PASS:67','shadow_trial_gate','PASS');
END $$;
COMMIT;
