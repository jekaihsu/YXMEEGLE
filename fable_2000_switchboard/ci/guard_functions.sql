CREATE OR REPLACE FUNCTION public.outbound_guard()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE
  c record;
  combined_body text;
BEGIN
  combined_body := coalesce(NEW.draft_body, '') || E'\n' || coalesce(NEW.final_body, '');
  -- Shared first-hit semantics, applied to subject and both draft/final bodies.
  IF public.guard_hit('internal',coalesce(NEW.subject,'')||E'\n'||combined_body) IS NOT NULL THEN
    RAISE EXCEPTION 'outbound contains internal/forbidden text (%)', public.guard_hit('internal',coalesce(NEW.subject,'')||E'\n'||combined_body);
  END IF;
  IF public.guard_hit('forbidden',coalesce(NEW.subject,'')||E'\n'||combined_body) IS NOT NULL THEN
    RAISE EXCEPTION 'outbound contains internal/forbidden text (%)', public.guard_hit('forbidden',coalesce(NEW.subject,'')||E'\n'||combined_body);
  END IF;
  -- 2. Recipient must belong to case customer when case_id & to_contact_id are present
  IF NEW.to_contact_id IS NOT NULL AND NEW.case_id IS NOT NULL THEN
    IF NOT EXISTS (
      SELECT 1 FROM public.customer_contact ct
      JOIN public."case" cs ON cs.customer_id = ct.customer_id
      WHERE ct.id = NEW.to_contact_id AND cs.id = NEW.case_id
    ) THEN
      RAISE EXCEPTION 'recipient not of this case customer';
    END IF;
  END IF;
  -- Customer restrictions apply even while a draft has no resolved contact.
  IF EXISTS (
    SELECT 1 FROM public.customer cust
    WHERE (cust.id=(SELECT customer_id FROM public.customer_contact WHERE id=NEW.to_contact_id)
        OR cust.id=(SELECT customer_id FROM public."case" WHERE id=NEW.case_id))
      AND coalesce((cust.delivery_constraints->>'no_links')::bool,false)
  ) AND public.guard_hit('url',coalesce(NEW.subject,'')||combined_body||NEW.attachments::text) IS NOT NULL THEN
    RAISE EXCEPTION 'customer forbids links';
  END IF;
  -- 4. Sealed deliverable attachment requires release_gate_checked
  IF NEW.status IN ('approved','sent') OR NEW.final_body IS NOT NULL THEN
    IF EXISTS (
      SELECT 1
      FROM public.outbound_attachment oa
      JOIN public.deliverable_version dv ON dv.id = oa.deliverable_version_id
      WHERE oa.outbound_id = NEW.id AND dv.is_sealed = true
    ) AND NOT coalesce(NEW.release_gate_checked, false) THEN
      RAISE EXCEPTION 'sealed deliverable requires release gate';
    END IF;
  END IF;
  RETURN NEW;
END $function$

;
CREATE OR REPLACE FUNCTION public.switchboard_outbound_guard()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE body text;
BEGIN
  body := translate(public.guard_normalize(coalesce(NEW.subject,'')||E'\n'||coalesce(NEW.draft_body,'')||E'\n'||coalesce(NEW.final_body,'')), U&'\200B\200C\200D\2060\FEFF','');
  IF body ~* '(^|[^a-zA-Z0-9])([a-zA-Z][12][0-9]{8}|09[0-9]{2}[- ]?[0-9]{3}[- ]?[0-9]{3}|0[2-8][- ]?[0-9]{3,4}[- ]?[0-9]{4})([^a-zA-Z0-9]|$)' THEN
    RAISE EXCEPTION '對外草稿含未遮蔽電話或身分證'; END IF;
  IF body ~* '(1[3-9]([ ()-]*[0-9]){9}|\+886[ ()-]*[2-9]([ ()-]*[0-9]){7,8}|(電話|电话|手機|手机|phone|tel)[：: ]*[+]?[0-9][0-9 ()-]{6,}[0-9])' THEN
    RAISE EXCEPTION '對外草稿含未遮蔽國際電話'; END IF;
  IF body ~* '(薪資|薪水|月薪|年薪|salary|payroll)' AND
    regexp_replace(body,'\[MASKED_HR_PRIVATE\]','','g') ~ '[0-9]' THEN
    RAISE EXCEPTION '對外草稿含薪酬數字'; END IF;
  IF NEW.approved_by IS NOT NULL AND (NEW.to_contact_id IS NULL OR NEW.case_id IS NULL) THEN
    RAISE EXCEPTION '核准前須核實收件人與案件'; END IF;
  IF NEW.to_contact_id IS NOT NULL AND NEW.case_id IS NOT NULL AND NOT EXISTS(
    SELECT 1 FROM public.customer_contact t JOIN public."case" c ON c.customer_id=t.customer_id
      WHERE t.id=NEW.to_contact_id AND c.id=NEW.case_id) THEN
    RAISE EXCEPTION '收件人與案件客戶不一致'; END IF;
  RETURN NEW;
END $function$

;
CREATE OR REPLACE FUNCTION public.otp_deliver(p_msg uuid)
 RETURNS uuid
 LANGUAGE plpgsql
AS $function$
DECLARE m public.email_message; r public.otp_forward_rule; req public.otp_request; t timestamptz; pending_cnt int; admin_emp uuid;
BEGIN
  -- One message cannot fulfill concurrent requests or be replayed to a second employee.
  SELECT * INTO m FROM public.email_message WHERE id=p_msg FOR UPDATE;
  IF NOT FOUND THEN RETURN NULL; END IF;
  t:=clock_timestamp();
  IF public.guard_hit('otp_forbidden',coalesce(m.subject,'')||E'\n'||coalesce(m.body_new_text,'')) IS NOT NULL THEN RETURN NULL; END IF;
  SELECT * INTO r FROM public.otp_forward_rule
    WHERE lower(sender_exact)=lower(m.from_addr) AND org_id=m.org_id AND public.guard_normalize(m.subject) ~* subject_regex
      AND public.guard_normalize(m.body_new_text) ~ code_regex AND m.dkim_spf_passed
      AND lower(m.dkim_domain)=lower(split_part(sender_exact,'@',2)) ORDER BY id LIMIT 1;
  IF NOT FOUND OR m.sent_at>t OR m.sent_at<=t-interval '5 minutes'
     OR EXISTS(SELECT 1 FROM public.otp_request WHERE fulfilled_message_id=p_msg) THEN RETURN NULL; END IF;
  SELECT count(*) INTO pending_cnt FROM public.otp_request q JOIN public.employee e ON e.id=q.requester_employee_id
    WHERE q.rule_id=r.id AND q.org_id=m.org_id AND q.fulfilled_message_id IS NULL
      AND q.requested_at>t-interval '5 minutes' AND q.requested_at<=t AND m.sent_at>=q.requested_at
      AND e.employment_status='active' AND e.identity_confirmed AND e.org_id=q.org_id;
  IF pending_cnt > 1 THEN
    SELECT e.id INTO admin_emp FROM public.employee e
     WHERE e.org_id = m.org_id AND e.employment_status = 'active' AND e.identity_confirmed AND e.role_code = 'admin'
     ORDER BY e.id LIMIT 1;
    IF admin_emp IS NULL THEN
      RAISE EXCEPTION 'no active confirmed admin employee for org %', m.org_id;
    END IF;
    PERFORM public.enqueue_card(
      m.org_id, m.case_id, admin_emp, 'admin', 'otp-conflict:' || m.id::text,
      jsonb_build_array(jsonb_build_object('label', '同帳號 pending 請求', 'value', pending_cnt, 'sql_id', 'otp.pending_requests')),
      jsonb_build_object('label', 'OTP 衝突', 'rule_id', r.id));
    RETURN NULL;
  END IF;
  SELECT q.* INTO req FROM public.otp_request q JOIN public.employee e ON e.id=q.requester_employee_id
    WHERE q.rule_id=r.id AND q.org_id=m.org_id AND q.fulfilled_message_id IS NULL
      AND q.requested_at>t-interval '5 minutes' AND q.requested_at<=t AND m.sent_at>=q.requested_at
      AND e.employment_status='active' AND e.identity_confirmed AND e.org_id=q.org_id
    ORDER BY q.requested_at,q.id LIMIT 1 FOR UPDATE OF q;
  IF NOT FOUND THEN RETURN NULL; END IF;
  t:=clock_timestamp();
  IF t>=req.requested_at+interval '5 minutes' THEN RETURN NULL; END IF;
  UPDATE public.otp_request SET fulfilled_message_id=p_msg,delivered_at=t WHERE id=req.id;
  -- A private outbox row is the complete dry-run delivery contract; no group target exists.
  INSERT INTO public.otp_private_delivery(request_id,message_id,recipient_employee_id,org_id)
    VALUES(req.id,p_msg,req.requester_employee_id,req.org_id);
  RETURN req.requester_employee_id;
END $function$

;
-- Earlier keyword-only trigger is subsumed by outbound_guard (draft and final).
DROP TRIGGER IF EXISTS r28_outbound_keyword_guard ON public.outbound_message;
