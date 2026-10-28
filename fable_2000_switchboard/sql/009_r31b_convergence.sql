-- R31-B: additive convergence over the installed R29 schema.
BEGIN;
SELECT pg_advisory_xact_lock(1943,12090);
CREATE TABLE IF NOT EXISTS public.backfill_quarantine (
 id bigserial PRIMARY KEY,run_id uuid NOT NULL,kind text NOT NULL,payload jsonb NOT NULL,
 resolved_by uuid,resolved_at timestamptz,UNIQUE(kind,payload));
CREATE UNIQUE INDEX IF NOT EXISTS comm_org_serial_uq ON public.client_communication(org_id,serial_no) WHERE serial_no IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS comm_org_fingerprint_uq ON public.client_communication(org_id,thread_fingerprint) WHERE thread_fingerprint IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS thread_org_root_uq ON public.email_thread(org_id,root_message_id);
CREATE TABLE IF NOT EXISTS public.employee_alias (
 org_id text NOT NULL REFERENCES public.org(id),alias text NOT NULL CHECK(btrim(alias)<>''),
 employee_id uuid NOT NULL REFERENCES public.employee(id),PRIMARY KEY(org_id,alias));
CREATE OR REPLACE FUNCTION public.employee_alias_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM employee WHERE id=NEW.employee_id AND org_id=NEW.org_id AND employment_status='active' AND identity_confirmed)
 THEN RAISE EXCEPTION 'alias employee must be active, confirmed and in same org'; END IF;
 NEW.alias:=btrim(normalize(NEW.alias,NFKC)); RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS employee_alias_guard_trg ON public.employee_alias;
CREATE TRIGGER employee_alias_guard_trg BEFORE INSERT OR UPDATE ON public.employee_alias FOR EACH ROW EXECUTE FUNCTION public.employee_alias_guard();
-- Only unambiguous full names are automatic; nicknames require administrative confirmation.
INSERT INTO public.employee_alias(org_id,alias,employee_id)
 SELECT org_id,btrim(normalize(full_name,NFKC)),(array_agg(id))[1] FROM public.employee
 WHERE identity_confirmed AND employment_status='active' GROUP BY 1,2 HAVING count(*)=1 ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS public.card (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),org_id text NOT NULL REFERENCES public.org(id),case_id uuid,
 assignee_employee_id uuid NOT NULL REFERENCES public.employee(id),kind text NOT NULL CHECK(kind IN ('confirm','review','admin','finance','return_work')),
 idempotency_key text NOT NULL UNIQUE,status text NOT NULL DEFAULT 'open' CHECK(status IN ('open','acted')),
 proposed_fields jsonb NOT NULL DEFAULT '{}',evidence_numbers jsonb NOT NULL DEFAULT '[]',evidence_sql_ids text[] NOT NULL DEFAULT '{}',
 acted_at timestamptz,acted_by uuid REFERENCES public.employee(id),action text,action_key text UNIQUE,
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(case_id,org_id) REFERENCES public."case"(id,org_id),
 CONSTRAINT card_single_assignee CHECK(assignee_employee_id IS NOT NULL),
 CHECK ((status='open' AND acted_at IS NULL AND acted_by IS NULL AND action IS NULL AND action_key IS NULL)
 OR (status='acted' AND acted_at IS NOT NULL AND acted_by IS NOT NULL AND action IS NOT NULL AND action_key IS NOT NULL)));
CREATE UNIQUE INDEX IF NOT EXISTS card_idem ON public.card(idempotency_key);
CREATE TABLE IF NOT EXISTS public.card_transition (
 card_id uuid PRIMARY KEY REFERENCES public.card(id),next_assignee_employee_id uuid NOT NULL REFERENCES public.employee(id),
 next_kind text NOT NULL CHECK(next_kind IN ('review','return_work')),on_action text NOT NULL CHECK(on_action IN ('confirm','approve','return_work')));
-- R31 inbox compatibility: one schema and one evidence registry across both APIs.
CREATE TABLE IF NOT EXISTS public.evidence_sql(sql_id text PRIMARY KEY,description text NOT NULL,sql_text text NOT NULL,returns text NOT NULL);
INSERT INTO public.evidence_sql VALUES
 ('case_open_commitments','案件未結承諾數','SELECT count(*) FROM client_commitment WHERE case_id=:case_id AND status NOT IN (''fulfilled'',''withdrawn'')','int'),
 ('customer_fulfillment_rate','客戶承諾兌現率','SELECT coalesce(100.0*count(*) FILTER(WHERE status=''fulfilled'')/nullif(count(*),0),0) FROM client_commitment WHERE customer_id=:customer_id','numeric'),
 ('hours_to_48h','距48小時剩餘時數','SELECT greatest(0,coalesce(48-extract(epoch FROM(now()-min(occurred_at)))/3600,48)) FROM client_communication WHERE case_id=:case_id','numeric') ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS public.actor_role(role text PRIMARY KEY,rank int NOT NULL);
INSERT INTO public.actor_role VALUES('field_member',10),('sales',20),('admin',30),('finance',30),('pm',40),('vp',50) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS public.card_state_transition(card_kind text NOT NULL,from_state text NOT NULL,action text NOT NULL,to_state text NOT NULL,min_actor_rank int NOT NULL DEFAULT 10,PRIMARY KEY(card_kind,from_state,action));
ALTER TABLE public.card_state_transition DROP CONSTRAINT IF EXISTS card_state_transition_card_kind_check;
INSERT INTO public.card_state_transition(card_kind,from_state,action,to_state) VALUES
 ('confirm','open','confirm','acted'),('confirm','open','return_work','acted'),('review','open','approve','acted'),('review','open','reject','acted'),('admin','open','confirm','acted'),('finance','open','confirm','acted'),('return_work','open','confirm','acted') ON CONFLICT DO NOTHING;
ALTER TABLE public.card ADD COLUMN IF NOT EXISTS state text NOT NULL DEFAULT 'open';
ALTER TABLE public.card ADD COLUMN IF NOT EXISTS mode text NOT NULL DEFAULT 'live';
ALTER TABLE public.card ADD COLUMN IF NOT EXISTS actions jsonb NOT NULL DEFAULT '[]';
ALTER TABLE public.card ADD COLUMN IF NOT EXISTS source_event_key text NOT NULL DEFAULT '';
ALTER TABLE public.card ADD COLUMN IF NOT EXISTS role text;
ALTER TABLE public.card ADD COLUMN IF NOT EXISTS canvas_view smallint;
ALTER TABLE public.card ADD COLUMN IF NOT EXISTS canvas_ref jsonb NOT NULL DEFAULT '{}';
CREATE TABLE IF NOT EXISTS public.card_action_log(id bigserial PRIMARY KEY,card_id uuid NOT NULL REFERENCES public.card(id),action text NOT NULL,from_state text NOT NULL,to_state text NOT NULL,actor_employee_id uuid NOT NULL,actor_role text NOT NULL REFERENCES public.actor_role(role),channel text NOT NULL,idempotency_key text NOT NULL UNIQUE,payload jsonb NOT NULL DEFAULT '{}',acted_at timestamptz NOT NULL DEFAULT now());
CREATE OR REPLACE FUNCTION public.card_evidence(p_case uuid) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT jsonb_build_array(
 jsonb_build_object('label','未結承諾數','sql_id','case_open_commitments','value',(SELECT count(*) FROM client_commitment WHERE case_id=p_case AND status NOT IN ('fulfilled','withdrawn'))),
 jsonb_build_object('label','客戶承諾兌現率','sql_id','customer_fulfillment_rate','value',(SELECT coalesce(round(100.0*count(*) FILTER(WHERE k.status='fulfilled')/nullif(count(*),0),2),0) FROM client_commitment k JOIN "case" c ON c.customer_id=k.customer_id WHERE c.id=p_case)),
 jsonb_build_object('label','距48小時剩餘時數','sql_id','hours_to_48h','value',(SELECT greatest(0,coalesce(48-extract(epoch FROM(now()-min(c.occurred_at)))/3600,48)) FROM client_commitment k JOIN client_communication c ON c.id=k.source_comm_id WHERE k.case_id=p_case AND k.status NOT IN ('fulfilled','withdrawn'))))
$$;
CREATE OR REPLACE FUNCTION public.card_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM employee WHERE id=NEW.assignee_employee_id AND org_id=NEW.org_id AND identity_confirmed AND employment_status='active')
 THEN RAISE EXCEPTION 'card assignee must be one active confirmed employee in org'; END IF;
 IF TG_OP='UPDATE' AND OLD.acted_at IS NOT NULL AND to_jsonb(OLD) IS DISTINCT FROM to_jsonb(NEW)
 THEN RAISE EXCEPTION 'acted card is immutable'; END IF;
 -- Evidence slots are generated from SQL, never from proposed extraction fields.
 NEW.state:=NEW.status;
 NEW.source_event_key:=coalesce(nullif(NEW.source_event_key,''),NEW.idempotency_key);
 NEW.role:=coalesce(NEW.role,CASE WHEN NEW.kind='admin' THEN 'admin' WHEN NEW.kind='finance' THEN 'settlement' ELSE 'case' END);
 IF NEW.actions='[]'::jsonb OR (NEW.kind<>'confirm' AND NEW.actions='[{"label":"確認","action":"confirm"}]'::jsonb) THEN
 NEW.actions:=CASE WHEN NEW.kind='review' THEN '[{"label":"核准","action":"approve"}]'::jsonb ELSE '[{"label":"確認","action":"confirm"}]'::jsonb END;
 END IF;
 NEW.evidence_numbers:=public.card_evidence(NEW.case_id);
 NEW.evidence_sql_ids:=ARRAY['case_open_commitments','customer_fulfillment_rate','hours_to_48h'];
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS card_guard_trg ON public.card;
CREATE TRIGGER card_guard_trg BEFORE INSERT OR UPDATE ON public.card FOR EACH ROW EXECUTE FUNCTION public.card_guard();
CREATE OR REPLACE FUNCTION public.card_act(p_id uuid,p_actor uuid,p_action text,p_key text) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE c public.card; t public.card_transition; n uuid; result jsonb;
BEGIN
 IF p_key IS NULL OR btrim(p_key)='' OR p_action NOT IN ('confirm','approve','return_work','reject') OR p_action IS NULL THEN RAISE EXCEPTION 'invalid action or idempotency key'; END IF;
 SELECT * INTO c FROM public.card WHERE id=p_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'card not found'; END IF;
 IF c.assignee_employee_id IS DISTINCT FROM p_actor OR NOT EXISTS(SELECT 1 FROM employee WHERE id=p_actor AND org_id=c.org_id AND employment_status='active' AND identity_confirmed)
 THEN RAISE EXCEPTION 'actor is not the active assignee' USING ERRCODE='42501'; END IF;
 IF c.mode<>'live' THEN RAISE EXCEPTION 'dry_run card cannot be acted'; END IF;
 IF c.acted_at IS NOT NULL THEN
   IF c.action<>p_action THEN RAISE EXCEPTION 'card already acted with different action' USING ERRCODE='23505'; END IF;
   RETURN jsonb_build_object('id',c.id,'status',c.status,'acted_at',c.acted_at,'action',c.action);
 END IF;
 IF NOT EXISTS(SELECT 1 FROM public.card_state_transition WHERE card_kind=c.kind AND from_state='open' AND action=p_action) THEN RAISE EXCEPTION 'action not allowed for card kind'; END IF;
 UPDATE public.card SET status='acted',acted_at=clock_timestamp(),acted_by=p_actor,action=p_action,action_key=p_key WHERE id=p_id RETURNING * INTO c;
 INSERT INTO public.audit_event(table_name,record_id,op,actor_id,before_val,after_val)
 VALUES('card',p_id::text,'UPDATE',p_actor::text,jsonb_build_object('status','open'),jsonb_build_object('status','acted','action',p_action,'acted_at',c.acted_at));
 INSERT INTO public.card_action_log(card_id,action,from_state,to_state,actor_employee_id,actor_role,channel,idempotency_key)
 VALUES(p_id,p_action,'open','acted',p_actor,coalesce((SELECT role FROM public.api_session WHERE employee_id=p_actor AND expires_at>now() ORDER BY expires_at DESC LIMIT 1),'field_member'),'api',p_key);
 SELECT * INTO t FROM public.card_transition WHERE card_id=p_id AND on_action=p_action;
 IF FOUND THEN
   INSERT INTO public.card(org_id,case_id,assignee_employee_id,kind,idempotency_key)
   VALUES(c.org_id,c.case_id,t.next_assignee_employee_id,t.next_kind,'after:'||p_id::text||':'||p_action) ON CONFLICT DO NOTHING RETURNING id INTO n;
   INSERT INTO public.notification_outbox(recipient_id,tier,dedupe_key,payload)
   VALUES(t.next_assignee_employee_id::text,'immediate','after:'||p_id::text,jsonb_build_object('card_id',n)) ON CONFLICT DO NOTHING;
 END IF;
 RETURN jsonb_build_object('id',c.id,'status',c.status,'acted_at',c.acted_at,'action',c.action);
END $$;
CREATE OR REPLACE FUNCTION public.card_act(p_card uuid,p_action text,p_actor uuid,p_actor_role text,p_channel text,p_idem text,p_payload jsonb DEFAULT '{}')
 RETURNS TABLE(card_id uuid,from_state text,to_state text,replayed bool) LANGUAGE plpgsql AS $$
DECLARE done bool;
BEGIN
 SELECT acted_at IS NOT NULL INTO done FROM public.card WHERE id=p_card;
 PERFORM public.card_act(p_card,p_actor,p_action,p_idem);
 RETURN QUERY SELECT p_card,'open'::text,'acted'::text,coalesce(done,false);
END $$;
CREATE OR REPLACE FUNCTION public.enqueue_card(p_org text,p_case uuid,p_assignee uuid,p_kind text,p_key text,p_proposed jsonb DEFAULT '{}',p_cc uuid DEFAULT NULL) RETURNS uuid LANGUAGE plpgsql AS $$
DECLARE cid uuid;
BEGIN
 INSERT INTO public.card(org_id,case_id,assignee_employee_id,kind,idempotency_key,proposed_fields)
 VALUES(p_org,p_case,p_assignee,p_kind,p_key,p_proposed) ON CONFLICT(idempotency_key) DO NOTHING RETURNING id INTO cid;
 IF cid IS NULL THEN
 SELECT id INTO cid FROM public.card WHERE idempotency_key=p_key AND org_id=p_org AND assignee_employee_id=p_assignee AND case_id IS NOT DISTINCT FROM p_case AND kind=p_kind AND proposed_fields=p_proposed;
 IF cid IS NULL THEN RAISE EXCEPTION 'event idempotency payload conflict' USING ERRCODE='23505'; END IF;
 END IF;
 IF p_cc IS NOT NULL THEN
 IF NOT EXISTS(SELECT 1 FROM employee WHERE id=p_cc AND org_id=p_org AND employment_status='active' AND identity_confirmed) THEN RAISE EXCEPTION 'invalid copy recipient'; END IF;
 INSERT INTO public.notification_outbox(recipient_id,tier,dedupe_key,payload)
 VALUES(p_cc::text,'immediate','copy:'||cid::text||':'||p_cc::text,jsonb_build_object('card_id',cid,'copy_only',true)) ON CONFLICT DO NOTHING;
 END IF;
 RETURN cid;
END $$;
CREATE OR REPLACE FUNCTION public.forward_register_card(p_message uuid,p_alias text,p_admin uuid) RETURNS uuid LANGUAGE plpgsql AS $$
DECLARE m public.email_message; eid uuid;
BEGIN
 SELECT * INTO STRICT m FROM public.email_message WHERE id=p_message;
 SELECT a.employee_id INTO eid FROM employee_alias a JOIN employee e ON e.id=a.employee_id WHERE a.org_id=m.org_id AND a.alias=btrim(normalize(p_alias,NFKC)) AND e.identity_confirmed AND e.employment_status='active' AND e.org_id=m.org_id;
 IF eid IS NULL THEN
 INSERT INTO public.backfill_quarantine(run_id,kind,payload) VALUES(gen_random_uuid(),'unresolved_employee_alias',jsonb_build_object('message_id',m.id::text,'alias',p_alias)) ON CONFLICT DO NOTHING;
 RETURN enqueue_card(m.org_id,m.case_id,p_admin,'admin','alias:'||m.id::text,jsonb_build_object('alias',p_alias,'label','待分類'));
 END IF;
 RETURN enqueue_card(m.org_id,m.case_id,eid,'review','forward:'||m.id::text);
END $$;
ALTER TABLE public.email_switchboard_command ADD COLUMN IF NOT EXISTS command_kind text NOT NULL DEFAULT 'send_external' CHECK(command_kind IN ('send_external','forward_register'));
CREATE OR REPLACE FUNCTION public.satcmd_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM email_message m JOIN email_mailbox b ON b.address=m.from_addr AND b.org_id=m.org_id
 JOIN satellite_sent_copy s ON s.mailbox_id=b.id AND s.message_id=m.message_id
 WHERE m.id=NEW.source_message_id AND m.org_id=NEW.org_id AND m.sent_copy_verified AND m.dkim_pass AND m.spf_pass
 AND (b.role='satellite' OR (b.role='switchboard' AND NEW.command_kind='forward_register')))
 THEN RAISE EXCEPTION 'command source not an authenticated satellite with IMAP Sent Message-ID evidence'; END IF;
 IF NEW.requester_employee_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM employee WHERE id=NEW.requester_employee_id AND org_id=NEW.org_id AND identity_confirmed AND employment_status='active') THEN RAISE EXCEPTION 'requester not active and identity confirmed'; END IF;
 IF NEW.command_kind='forward_register' AND NEW.requester_employee_id IS NULL AND NOT EXISTS(SELECT 1 FROM backfill_quarantine WHERE payload->>'message_id'=NEW.source_message_id::text) THEN RAISE EXCEPTION 'unresolved forward requester must be quarantined'; END IF;
 RETURN NEW;
END $$;
-- Internal points settlement is independent of the cash-basis bonus ledger.
ALTER TABLE public.contract_item ADD COLUMN IF NOT EXISTS performed_quantity numeric NOT NULL DEFAULT 0 CHECK(performed_quantity>=0);
ALTER TABLE public."case" ADD COLUMN IF NOT EXISTS retention_released boolean NOT NULL DEFAULT false;
CREATE OR REPLACE FUNCTION public.settlement_blocked(p_case uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM client_commitment WHERE case_id=p_case AND status NOT IN ('fulfilled','withdrawn'))
 OR EXISTS(SELECT 1 FROM contract_item WHERE case_id=p_case AND item_status IN ('preliminary','provisional') AND (performed_quantity>0 OR coalesce((to_jsonb(contract_item)->>'done_amount')::numeric,0)>0))
$$;
CREATE OR REPLACE FUNCTION public.settlement_gate() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.status IN ('ready_for_vp','vp_signed','gm_signed') THEN
 IF settlement_blocked(NEW.case_id) THEN RAISE EXCEPTION 'open client commitments block settlement (or performed provisional items)'; END IF;
 IF NOT EXISTS(SELECT 1 FROM "case" WHERE id=NEW.case_id AND org_id=NEW.org_id AND status IN ('completed','settled','paid')) THEN RAISE EXCEPTION 'case must be completed for internal settlement'; END IF;
 END IF; RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION public.case_closed(p_case uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM "case" c JOIN case_settlement s ON s.case_id=c.id WHERE c.id=p_case AND s.status='gm_signed' AND c.retention_released)
 AND EXISTS(SELECT 1 FROM invoice_paid_v WHERE case_id=p_case)
 AND NOT EXISTS(SELECT 1 FROM invoice_paid_v WHERE case_id=p_case AND NOT paid)
 AND NOT EXISTS(SELECT 1 FROM deliverable_release_gate g LEFT JOIN invoice_paid_v v ON v.id=g.invoice_id AND v.case_id=g.case_id WHERE g.case_id=p_case AND g.deliverable_class='sealed' AND NOT coalesce(v.paid,false))
 AND NOT settlement_blocked(p_case)
$$;
CREATE TABLE IF NOT EXISTS hr_private.bonus_line (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),invoice_id uuid NOT NULL REFERENCES public.invoice(id),
 employee_id uuid NOT NULL REFERENCES public.employee(id),points numeric NOT NULL CHECK(points>=0),amount_twd numeric NOT NULL CHECK(amount_twd>=0),
 idempotency_key text NOT NULL UNIQUE,created_at timestamptz NOT NULL DEFAULT now());
CREATE OR REPLACE FUNCTION hr_private.bonus_line_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
 PERFORM 1 FROM public.invoice WHERE id=NEW.invoice_id FOR UPDATE;
 IF NOT EXISTS(SELECT 1 FROM public.invoice_paid_v v JOIN public.employee e ON e.org_id=v.org_id WHERE v.id=NEW.invoice_id AND v.paid AND e.id=NEW.employee_id)
 THEN RAISE EXCEPTION 'bonus requires fully paid invoice in employee organization'; END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS bonus_line_guard_trg ON hr_private.bonus_line;
CREATE TRIGGER bonus_line_guard_trg BEFORE INSERT OR UPDATE ON hr_private.bonus_line FOR EACH ROW EXECUTE FUNCTION hr_private.bonus_line_guard();
DROP TRIGGER IF EXISTS bonus_line_audit ON hr_private.bonus_line;
DO $$ BEGIN
  IF to_regprocedure('hr_private.audit_row()') IS NOT NULL THEN
    CREATE TRIGGER bonus_line_audit AFTER INSERT OR UPDATE OR DELETE ON hr_private.bonus_line FOR EACH ROW EXECUTE FUNCTION hr_private.audit_row();
  ELSIF to_regprocedure('public.audit_row()') IS NOT NULL THEN
    CREATE TRIGGER bonus_line_audit AFTER INSERT OR UPDATE OR DELETE ON hr_private.bonus_line FOR EACH ROW EXECUTE FUNCTION public.audit_row();
  END IF;
END $$;
REVOKE ALL ON hr_private.bonus_line FROM PUBLIC,pm_sales_finance_role;
GRANT SELECT,INSERT,UPDATE,DELETE ON hr_private.bonus_line TO payroll_admin_role;
CREATE TABLE IF NOT EXISTS public.invoice_fee_adjustment (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),invoice_id uuid NOT NULL REFERENCES public.invoice(id),
 allocation_id uuid NOT NULL UNIQUE REFERENCES public.receipt_allocation(id),amount numeric NOT NULL CHECK(amount>0 AND amount<=100),
 confirmed_by uuid NOT NULL REFERENCES public.employee(id),confirmed_at timestamptz NOT NULL DEFAULT now(),idempotency_key text NOT NULL UNIQUE);
CREATE OR REPLACE FUNCTION public.invoice_fee_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE unpaid numeric; a public.receipt_allocation;
BEGIN
 IF NEW.amount>(SELECT value_numeric FROM public.guard_setting WHERE name='bank_fee_tolerance_twd') THEN RAISE EXCEPTION 'bank fee tolerance exceeded'; END IF;
 IF TG_OP='UPDATE' THEN RAISE EXCEPTION 'fee adjustments are immutable; reverse allocations instead'; END IF;
 PERFORM 1 FROM invoice WHERE id=NEW.invoice_id FOR UPDATE;
 SELECT * INTO a FROM receipt_allocation WHERE id=NEW.allocation_id;
 IF a.invoice_id IS DISTINCT FROM NEW.invoice_id OR a.allocated_by IS DISTINCT FROM NEW.confirmed_by THEN RAISE EXCEPTION 'finance allocation confirmation required'; END IF;
 IF NOT EXISTS(SELECT 1 FROM employee e JOIN invoice i ON i.org_id=e.org_id WHERE i.id=NEW.invoice_id AND e.id=NEW.confirmed_by AND e.employment_status='active' AND e.identity_confirmed AND (e.department_name ~ '(財務|會計)' OR e.job_title ~ '(財務|會計)')) THEN RAISE EXCEPTION 'active confirmed finance employee required'; END IF;
 SELECT unpaid_amount INTO unpaid FROM invoice_paid_v WHERE id=NEW.invoice_id;
 IF unpaid IS DISTINCT FROM NEW.amount THEN RAISE EXCEPTION 'fee must equal remaining unpaid amount'; END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS invoice_fee_guard_trg ON public.invoice_fee_adjustment;
CREATE TRIGGER invoice_fee_guard_trg BEFORE INSERT OR UPDATE ON public.invoice_fee_adjustment FOR EACH ROW EXECUTE FUNCTION public.invoice_fee_guard();
CREATE OR REPLACE VIEW public.invoice_paid_v AS
 SELECT i.id,i.case_id,i.org_id,coalesce(i.amount_due,i.total_amount,0) AS amount_due,
 coalesce(i.amount_due,i.total_amount,0)-a.total+r.total-f.total AS unpaid_amount,
 (coalesce(i.amount_due,i.total_amount,0)-a.total+r.total-f.total=0) AS paid
 FROM public.invoice i
 CROSS JOIN LATERAL(SELECT coalesce(sum(a.amount),0) total FROM receipt_allocation a LEFT JOIN payment_instrument p ON p.id=a.instrument_id WHERE a.invoice_id=i.id AND (a.instrument_id IS NULL OR p.status='cleared')) a
 CROSS JOIN LATERAL(SELECT coalesce(sum(r.amount),0) total FROM receipt_reversal r JOIN receipt_allocation a ON a.id=r.allocation_id WHERE a.invoice_id=i.id) r
 CROSS JOIN LATERAL(SELECT coalesce(sum(f.amount),0) total FROM invoice_fee_adjustment f JOIN receipt_allocation a ON a.id=f.allocation_id LEFT JOIN payment_instrument p ON p.id=a.instrument_id WHERE f.invoice_id=i.id AND a.invoice_id=i.id AND (a.instrument_id IS NULL OR p.status='cleared') AND NOT EXISTS(SELECT 1 FROM receipt_reversal r WHERE r.allocation_id=a.id)) f;
-- No existing dim/fact views are changed. Work-item policy is new public data.
CREATE TABLE IF NOT EXISTS public.work_item_policy (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),org_id text NOT NULL REFERENCES public.org(id),name text NOT NULL,
 floor_price numeric NOT NULL CHECK(floor_price>=0),standard_cost_price numeric NOT NULL CHECK(standard_cost_price>=0),traffic_light text NOT NULL CHECK(traffic_light IN ('green','amber','red')));
DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='sales_role') THEN CREATE ROLE sales_role NOLOGIN; END IF; END $$;
REVOKE ALL ON public.work_item_policy FROM PUBLIC,sales_role;
GRANT USAGE ON SCHEMA public TO sales_role;
GRANT SELECT(id,org_id,name,floor_price,traffic_light) ON public.work_item_policy TO sales_role;
REVOKE ALL ON SCHEMA hr_private FROM PUBLIC,sales_role,pm_sales_finance_role;
REVOKE ALL ON ALL TABLES IN SCHEMA hr_private FROM PUBLIC,sales_role,pm_sales_finance_role;
CREATE TABLE IF NOT EXISTS public.api_session (
 token_sha256 text PRIMARY KEY,employee_id uuid NOT NULL REFERENCES employee(id),org_id text NOT NULL REFERENCES org(id),
 role text NOT NULL CHECK(role IN ('sales','pm','vp','admin','finance')),expires_at timestamptz NOT NULL);
REVOKE ALL ON public.api_session FROM PUBLIC,sales_role,pm_sales_finance_role;
REVOKE ALL ON public.card,public.card_transition,public.employee_alias,public.invoice_fee_adjustment FROM PUBLIC,sales_role;
CREATE TABLE IF NOT EXISTS public.email_template_version (
 code text NOT NULL REFERENCES email_template(code),version integer NOT NULL,subject_tpl text NOT NULL,body_tpl text NOT NULL,required_params text[] NOT NULL,
 PRIMARY KEY(code,version));
INSERT INTO public.email_template_version SELECT code,version,subject_tpl,body_tpl,required_params FROM public.email_template ON CONFLICT DO NOTHING;
ALTER TABLE public.outbound_message ADD COLUMN IF NOT EXISTS template_code text;
ALTER TABLE public.outbound_message ADD COLUMN IF NOT EXISTS template_version integer;
ALTER TABLE public.outbound_message ADD COLUMN IF NOT EXISTS template_params jsonb;
DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='public.outbound_message'::regclass AND conname='outbound_template_version_fk') THEN
 ALTER TABLE public.outbound_message ADD CONSTRAINT outbound_template_version_fk FOREIGN KEY(template_code,template_version) REFERENCES public.email_template_version(code,version);
END IF; END $$;
CREATE OR REPLACE FUNCTION public.pin_template_draft(p_out uuid,p_code text,p_params jsonb,p_selected_pm uuid DEFAULT NULL) RETURNS void LANGUAGE plpgsql AS $$
DECLARE o public.outbound_message;t public.email_template;pm public.employee;pm_id uuid;param text;sub text;body text;
BEGIN
 SELECT * INTO STRICT o FROM public.outbound_message WHERE id=p_out FOR UPDATE;
 IF o.approved_at IS NOT NULL THEN RAISE EXCEPTION 'approved draft is immutable'; END IF;
 SELECT * INTO STRICT t FROM public.email_template WHERE code=p_code AND active;
 IF o.case_id IS NOT NULL THEN SELECT pm_employee_id INTO pm_id FROM public."case" WHERE id=o.case_id;
 ELSE pm_id:=p_selected_pm; END IF;
 IF p_code='quote_return_reply' THEN
 SELECT * INTO pm FROM employee WHERE id=pm_id AND org_id=o.org_id AND identity_confirmed AND employment_status='active';
 IF NOT FOUND THEN RAISE EXCEPTION 'select an active confirmed PM before drafting'; END IF;
 p_params:=coalesce(p_params,'{}')||jsonb_build_object('pm_name',pm.full_name,'pm_phone',coalesce(pm.work_phone,''));
 END IF;
 sub:=t.subject_tpl;body:=t.body_tpl;
 FOREACH param IN ARRAY t.required_params LOOP
 IF coalesce(p_params->>param,'')='' THEN RAISE EXCEPTION 'required template parameter missing: %',param; END IF;
 END LOOP;
 FOR param IN SELECT jsonb_object_keys(p_params) LOOP
 sub:=replace(sub,'{{'||param||'}}',p_params->>param);body:=replace(body,'{{'||param||'}}',p_params->>param);
 END LOOP;
 IF sub ~ '\{\{' OR body ~ '\{\{' THEN RAISE EXCEPTION 'unresolved template parameter'; END IF;
 INSERT INTO email_template_version VALUES(t.code,t.version,t.subject_tpl,t.body_tpl,t.required_params) ON CONFLICT DO NOTHING;
 IF NOT EXISTS(SELECT 1 FROM email_template_version WHERE code=t.code AND version=t.version AND subject_tpl=t.subject_tpl AND body_tpl=t.body_tpl AND required_params=t.required_params) THEN RAISE EXCEPTION 'template content changed without version bump'; END IF;
 UPDATE outbound_message SET subject=sub,draft_body=body,template_code=t.code,template_version=t.version,template_params=p_params WHERE id=p_out;
END $$;
-- Existing generic transition trigger reads status, but contract_item uses item_status.
CREATE OR REPLACE FUNCTION public.contract_item_state_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.item_status=NEW.item_status THEN RETURN NEW; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.state_transition WHERE entity='contract_item' AND from_state=OLD.item_status AND to_state=NEW.item_status)
 THEN RAISE EXCEPTION 'Illegal state transition on contract_item: % -> %',OLD.item_status,NEW.item_status; END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_contract_item_state ON public.contract_item;
CREATE TRIGGER trg_contract_item_state BEFORE UPDATE OF item_status ON public.contract_item FOR EACH ROW EXECUTE FUNCTION public.contract_item_state_guard();
DO $do$ BEGIN
IF to_regclass('public.canvas_v3_release_and_receipt') IS NOT NULL THEN
 EXECUTE $view$ CREATE OR REPLACE VIEW public.canvas_v3_release_and_receipt AS
 SELECT i.id invoice_id,i.case_id,i.period_no,i.invoice_no,i.issue_date invoice_date,i.due_date,v.amount_due::numeric(14,2) AS amount_due,i.retention_amount,
 a.allocated,r.reversed,(v.amount_due-a.allocated+r.reversed-v.unpaid_amount) recognized_diff,v.unpaid_amount unpaid,
 (SELECT jsonb_agg(jsonb_build_object('bank',b.bank,'amount',b.amount,'value_date',b.value_date,'masked_tax_id',b.masked_tax_id,'status',b.status)) FROM bank_notice b WHERE i.id=ANY(b.candidate_invoice_ids) AND b.status='candidate') candidate_notices,
 (SELECT jsonb_agg(jsonb_build_object('milestone',g.milestone,'class',g.deliverable_class,'allowed',sealed_release_allowed(g.case_id,g.milestone))) FROM deliverable_release_gate g WHERE g.case_id=i.case_id) release_gates
 FROM public.invoice i JOIN public.invoice_paid_v v ON v.id=i.id
 CROSS JOIN LATERAL(SELECT coalesce(sum(a.amount),0) allocated FROM receipt_allocation a LEFT JOIN payment_instrument p ON p.id=a.instrument_id WHERE a.invoice_id=i.id AND (a.instrument_id IS NULL OR p.status='cleared')) a
 CROSS JOIN LATERAL(SELECT coalesce(sum(r.amount),0) reversed FROM receipt_reversal r JOIN receipt_allocation a ON a.id=r.allocation_id WHERE a.invoice_id=i.id) r
 $view$;
END IF;
END $do$;
-- Retain the deployed convergence definitions when older idempotent migrations run again.
CREATE TABLE IF NOT EXISTS public.r31b_deployment_object(name text PRIMARY KEY,priority int NOT NULL,ddl text NOT NULL);
REVOKE ALL ON public.r31b_deployment_object FROM PUBLIC,sales_role,pm_sales_finance_role;
CREATE OR REPLACE FUNCTION public.restore_r31b_guards() RETURNS void LANGUAGE plpgsql AS $$
DECLARE obj record;
BEGIN
 FOR obj IN SELECT ddl FROM public.r31b_deployment_object ORDER BY priority,name LOOP EXECUTE obj.ddl; END LOOP;
 DROP TRIGGER IF EXISTS r28_outbound_keyword_guard ON public.outbound_message;
END $$;
REVOKE ALL ON FUNCTION public.restore_r31b_guards() FROM PUBLIC;
INSERT INTO public.r31b_deployment_object(name,priority,ddl)
 SELECT p.oid::regprocedure::text,10,pg_get_functiondef(p.oid) FROM pg_proc p
 WHERE p.pronamespace='public'::regnamespace AND p.proname IN ('settlement_gate','settlement_blocked','case_closed','satcmd_guard','card_act','card_guard','invoice_fee_guard','contract_item_state_guard')
 ON CONFLICT(name) DO UPDATE SET ddl=EXCLUDED.ddl,priority=EXCLUDED.priority;
INSERT INTO public.r31b_deployment_object VALUES('invoice_paid_v',20,'CREATE OR REPLACE VIEW public.invoice_paid_v AS '||pg_get_viewdef('public.invoice_paid_v'::regclass,true))
 ON CONFLICT(name) DO UPDATE SET ddl=EXCLUDED.ddl;
INSERT INTO public.r31b_deployment_object
 SELECT 'canvas_v3_release_and_receipt',30,'CREATE OR REPLACE VIEW public.canvas_v3_release_and_receipt AS '||pg_get_viewdef(c.oid,true)
 FROM pg_class c WHERE c.oid=to_regclass('public.canvas_v3_release_and_receipt')
 ON CONFLICT(name) DO UPDATE SET ddl=EXCLUDED.ddl;
COMMIT;
