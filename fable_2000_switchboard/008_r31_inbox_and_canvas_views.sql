-- 008_r31_inbox_and_canvas_views.sql
-- R31：六角色收件匣 × 六種 Canvas 預篩視圖 × 卡片動作狀態機。
-- 前提：R29/R29-PSTACK 物件已存在（outbound_message, client_commitment, invoice, receipt_allocation, case_settlement, case_task, ...）
-- 設計契約：
--   * card 是正本；Lark 卡片與 Plumb Inbox 都只讀 card、都打 card_act()。
--   * 三個數字只能綁 evidence_sql 登錄表的 sql_id；沒有來源的數字進不了卡（CHECK + trigger）。
--   * 一張卡一個 assignee；副本走 notification_outbox。
--   * 欄位白名單在 canvas_column_whitelist；API 層依 (view_no, actor_role) 裁剪；fact/dim/canvas 視圖定義不得引用 hr_private。
BEGIN;

-- ---------------------------------------------------------------------------
-- 0. 列舉與登錄表
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS inbox_role (role text PRIMARY KEY, description text);
INSERT INTO inbox_role VALUES
  ('attendance','出勤 owner'),('case','案件 owner'),('field','外業 owner'),('settlement','結算 owner'),('admin','行政 owner'),('mine','等本人按的卡')
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS actor_role (role text PRIMARY KEY, rank int NOT NULL);
INSERT INTO actor_role VALUES ('field_member',10),('field_lead',20),('inner_lead',20),('sales',20),('admin',30),('finance',30),('payroll',30),('pm',40),('vp',50),('gm',60),('it',60)
ON CONFLICT DO NOTHING;

-- 證據 SQL 登錄：卡片上的數字只能來自這裡
CREATE TABLE IF NOT EXISTS evidence_sql (
  sql_id text PRIMARY KEY,
  description text NOT NULL,
  sql_text text NOT NULL,                              -- 以 :card_ref / :case_id 等具名參數，只准 SELECT
  returns text NOT NULL CHECK (returns IN ('int','numeric','text','date','bool')),
  CHECK (sql_text ~* '^\s*select\y' AND sql_text !~* '\y(insert|update|delete|drop|alter|grant|truncate|hr_private)\y')
);

-- 卡片狀態機
CREATE TABLE IF NOT EXISTS card_state_transition (
  card_kind text NOT NULL CHECK (card_kind IN ('approve','choose','confirm','fix','inform')),
  from_state text NOT NULL, action text NOT NULL, to_state text NOT NULL,
  min_actor_rank int NOT NULL DEFAULT 10,
  PRIMARY KEY (card_kind, from_state, action)
);
INSERT INTO card_state_transition VALUES
  ('approve','open','approve','acted',20),('approve','open','reject','acted',20),('approve','open','unsure','escalated',10),
  ('choose','open','choose','acted',10),('choose','open','unsure','escalated',10),
  ('confirm','open','confirm','acted',10),('confirm','open','amend','acted',10),('confirm','open','not_this','acted',10),
  ('fix','open','fix','acted',10),('fix','open','unsure','escalated',10),
  ('inform','open','ack','acted',10),
  ('approve','escalated','approve','acted',40),('approve','escalated','reject','acted',40),
  ('choose','escalated','choose','acted',40),('fix','escalated','fix','acted',40)
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- 1. card 正本
-- ---------------------------------------------------------------------------
-- 0a. R31 欄位與視圖相容性補強（Idempotent schema convergence）
ALTER TABLE card ALTER COLUMN case_id DROP NOT NULL;
ALTER TABLE card DROP CONSTRAINT IF EXISTS card_org_id_fkey;
ALTER TABLE card ADD COLUMN IF NOT EXISTS role text REFERENCES inbox_role(role);
ALTER TABLE card ADD COLUMN IF NOT EXISTS owner_agent text NOT NULL DEFAULT 'switchboard';
ALTER TABLE card ADD COLUMN IF NOT EXISTS title text NOT NULL DEFAULT '待辦卡片';
ALTER TABLE card ADD COLUMN IF NOT EXISTS canvas_view smallint;
ALTER TABLE card ADD COLUMN IF NOT EXISTS canvas_ref jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE card ADD COLUMN IF NOT EXISTS actions jsonb NOT NULL DEFAULT '[{"action":"confirm","label":"確認"}]'::jsonb;
ALTER TABLE card ADD COLUMN IF NOT EXISTS source_event_key text NOT NULL DEFAULT '';
ALTER TABLE card ADD COLUMN IF NOT EXISTS priority smallint NOT NULL DEFAULT 50;
ALTER TABLE card ADD COLUMN IF NOT EXISTS state text NOT NULL DEFAULT 'open';
ALTER TABLE card ADD COLUMN IF NOT EXISTS mode text NOT NULL DEFAULT 'live';
ALTER TABLE card ADD COLUMN IF NOT EXISTS expires_at timestamptz;
ALTER TABLE card ADD COLUMN IF NOT EXISTS result jsonb;

CREATE OR REPLACE VIEW contact AS
SELECT id, customer_id, full_name AS name, email, org_id FROM customer_contact;

ALTER TABLE customer ADD COLUMN IF NOT EXISTS customer_name text;
UPDATE customer SET customer_name = name WHERE customer_name IS NULL AND name IS NOT NULL;

ALTER TABLE deliverable_version ADD COLUMN IF NOT EXISTS filename text;
ALTER TABLE quote_version ADD COLUMN IF NOT EXISTS filename text;

ALTER TABLE "case" ADD COLUMN IF NOT EXISTS stage text;
ALTER TABLE "case" ADD COLUMN IF NOT EXISTS contract_status text;
ALTER TABLE "case" ADD COLUMN IF NOT EXISTS master_cap numeric;
ALTER TABLE "case" ADD COLUMN IF NOT EXISTS case_kind text;

CREATE TABLE IF NOT EXISTS work_item (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text,
  floor_price numeric
);
ALTER TABLE quote_line ADD COLUMN IF NOT EXISTS quote_id uuid;
ALTER TABLE quote_line ADD COLUMN IF NOT EXISTS work_item_id uuid;
ALTER TABLE quote_line ADD COLUMN IF NOT EXISTS qty numeric;

ALTER TABLE contract_item ADD COLUMN IF NOT EXISTS done_amount numeric NOT NULL DEFAULT 0;

ALTER TABLE invoice ADD COLUMN IF NOT EXISTS period_no int;
ALTER TABLE invoice ADD COLUMN IF NOT EXISTS invoice_date date;
ALTER TABLE invoice ADD COLUMN IF NOT EXISTS retention_amount numeric NOT NULL DEFAULT 0;
ALTER TABLE invoice ADD COLUMN IF NOT EXISTS retention_status text NOT NULL DEFAULT 'pending';

ALTER TABLE receipt_allocation ADD COLUMN IF NOT EXISTS diff_amount numeric NOT NULL DEFAULT 0;
ALTER TABLE receipt_allocation ADD COLUMN IF NOT EXISTS diff_kind text;

CREATE TABLE IF NOT EXISTS node_template (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  node_name text,
  exec_sla_days int
);
CREATE TABLE IF NOT EXISTS task_event (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id uuid,
  event text,
  created_at timestamptz DEFAULT now()
);
ALTER TABLE case_task ADD COLUMN IF NOT EXISTS node_template_id uuid;
ALTER TABLE case_task ADD COLUMN IF NOT EXISTS executor_id uuid;
ALTER TABLE case_task ADD COLUMN IF NOT EXISTS started_at timestamptz;
ALTER TABLE case_task ADD COLUMN IF NOT EXISTS exec_done_at timestamptz;

ALTER TABLE client_playbook_rule ADD COLUMN IF NOT EXISTS enforcement text NOT NULL DEFAULT 'hard';
ALTER TABLE client_commitment ADD COLUMN IF NOT EXISTS stated_at timestamptz DEFAULT now();

CREATE TABLE IF NOT EXISTS supplier (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text,
  license_status text
);
CREATE TABLE IF NOT EXISTS cost_item (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id uuid,
  supplier_id uuid,
  kind text,
  nature text,
  status text,
  amount numeric NOT NULL DEFAULT 0
);
CREATE OR REPLACE VIEW case_cost_projection_v AS
SELECT id AS case_id,
       0::numeric AS labor_std_cost,
       0::numeric AS external_cost,
       0::numeric AS misc_cost,
       0::numeric AS projected_total_cost
FROM "case";

ALTER TABLE case_settlement ADD COLUMN IF NOT EXISTS vp_signed_by uuid;
ALTER TABLE case_settlement ADD COLUMN IF NOT EXISTS vp_signed_at timestamptz;
ALTER TABLE case_settlement ADD COLUMN IF NOT EXISTS gm_signed_by uuid;
ALTER TABLE case_settlement ADD COLUMN IF NOT EXISTS gm_signed_at timestamptz;
ALTER TABLE case_settlement ADD COLUMN IF NOT EXISTS bonus_pool_total numeric NOT NULL DEFAULT 0;
ALTER TABLE case_settlement ADD COLUMN IF NOT EXISTS bonus_pool_allocation jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE work_entry ADD COLUMN IF NOT EXISTS case_id uuid;

CREATE TABLE IF NOT EXISTS card (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL,
  role text NOT NULL REFERENCES inbox_role(role),
  assignee_employee_id uuid NOT NULL,                  -- 一張卡一個人（紅隊 #1）
  owner_agent text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('approve','choose','confirm','fix','inform')),
  title text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 40),
  evidence_numbers jsonb NOT NULL DEFAULT '[]'::jsonb,  -- [{label,value,sql_id}] ≤3，sql_id 必在 evidence_sql
  proposed_fields jsonb NOT NULL DEFAULT '{}'::jsonb,   -- Agent 抽取值，UI 標「待確認」，永不當證據（紅隊 #6）
  canvas_view smallint CHECK (canvas_view BETWEEN 1 AND 6),
  canvas_ref jsonb NOT NULL DEFAULT '{}'::jsonb,        -- {case_id|outbound_id|invoice_id|...}
  actions jsonb NOT NULL,                               -- [{action,label}] ≤3，action 必在 card_state_transition
  source_event_key text NOT NULL,                       -- 決定性：事件來源＋規則，DRY_RUN→LIVE 不重建（審計 #2）
  idempotency_key text NOT NULL UNIQUE,
  priority smallint NOT NULL DEFAULT 50,
  state text NOT NULL DEFAULT 'open' CHECK (state IN ('open','escalated','acted','expired','superseded','dry_run')),
  mode text NOT NULL DEFAULT 'live' CHECK (mode IN ('live','dry_run')),
  expires_at timestamptz,
  acted_by uuid, acted_at timestamptz, result jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (jsonb_typeof(evidence_numbers)='array' AND jsonb_array_length(evidence_numbers) <= 3),
  CHECK (jsonb_typeof(actions)='array' AND jsonb_array_length(actions) BETWEEN 1 AND 3),
  CHECK ((mode='dry_run') = (state='dry_run') OR state IN ('superseded'))
);
CREATE UNIQUE INDEX IF NOT EXISTS card_source_live_uq ON card(source_event_key) WHERE mode='live' AND state IN ('open','escalated');
CREATE INDEX IF NOT EXISTS card_inbox_idx ON card(role, assignee_employee_id, state, priority DESC);

-- 證據與動作的參照完整性（jsonb 無法用 FK，用 trigger）
CREATE OR REPLACE FUNCTION card_validate() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE e jsonb; a jsonb;
BEGIN
  FOR e IN SELECT * FROM jsonb_array_elements(NEW.evidence_numbers) LOOP
    IF NOT (e ? 'label' AND e ? 'value' AND e ? 'sql_id') THEN RAISE EXCEPTION 'evidence needs label/value/sql_id: %', e; END IF;
    IF NOT EXISTS (SELECT 1 FROM evidence_sql WHERE sql_id = e->>'sql_id') THEN RAISE EXCEPTION 'unknown evidence sql_id %', e->>'sql_id'; END IF;
  END LOOP;
  FOR a IN SELECT * FROM jsonb_array_elements(NEW.actions) LOOP
    IF NOT EXISTS (SELECT 1 FROM card_state_transition t WHERE t.card_kind = NEW.kind AND t.from_state = 'open' AND t.action = a->>'action')
    THEN RAISE EXCEPTION 'action % not allowed for kind %', a->>'action', NEW.kind; END IF;
  END LOOP;
  IF NEW.canvas_view IS NOT NULL AND NEW.canvas_ref = '{}'::jsonb THEN RAISE EXCEPTION 'canvas_view set but canvas_ref empty'; END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS card_validate_trg ON card;
CREATE TRIGGER card_validate_trg BEFORE INSERT OR UPDATE ON card FOR EACH ROW EXECUTE FUNCTION card_validate();

-- 動作稽核（append-only）
CREATE TABLE IF NOT EXISTS card_action_log (
  id bigserial PRIMARY KEY,
  card_id uuid NOT NULL REFERENCES card(id),
  action text NOT NULL, from_state text NOT NULL, to_state text NOT NULL,
  actor_employee_id uuid NOT NULL, actor_role text NOT NULL REFERENCES actor_role(role),
  channel text NOT NULL CHECK (channel IN ('lark','plumb','api')),
  idempotency_key text NOT NULL UNIQUE,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  acted_at timestamptz NOT NULL DEFAULT now()
);
REVOKE UPDATE, DELETE ON card_action_log FROM PUBLIC;

-- ---------------------------------------------------------------------------
-- 2. card_act：唯一的狀態轉移入口（冪等、角色門檻、稽核）
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION card_act(p_card uuid, p_action text, p_actor uuid, p_actor_role text, p_channel text,
                                    p_idem text, p_payload jsonb DEFAULT '{}'::jsonb)
RETURNS TABLE (card_id uuid, from_state text, to_state text, replayed bool) LANGUAGE plpgsql AS $$
DECLARE c card; t card_state_transition; r actor_role; existing card_action_log;
BEGIN
  SELECT * INTO existing FROM card_action_log WHERE idempotency_key = p_idem;
  IF FOUND THEN RETURN QUERY SELECT existing.card_id, existing.from_state, existing.to_state, true; RETURN; END IF;  -- 冪等重放
  SELECT * INTO c FROM card WHERE id = p_card FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'card % not found', p_card; END IF;
  IF c.mode = 'dry_run' THEN RAISE EXCEPTION 'dry_run card cannot be acted'; END IF;
  SELECT * INTO t FROM card_state_transition WHERE card_kind = c.kind AND card_state_transition.from_state = c.state AND action = p_action;
  IF NOT FOUND THEN RAISE EXCEPTION 'transition % not allowed from state % for kind %', p_action, c.state, c.kind; END IF;
  SELECT * INTO r FROM actor_role WHERE role = p_actor_role;
  IF NOT FOUND OR r.rank < t.min_actor_rank THEN RAISE EXCEPTION 'actor role % insufficient for %', p_actor_role, p_action; END IF;
  IF c.assignee_employee_id <> p_actor AND r.rank < 40 THEN RAISE EXCEPTION 'only assignee or pm+ may act'; END IF;
  INSERT INTO card_action_log (card_id, action, from_state, to_state, actor_employee_id, actor_role, channel, idempotency_key, payload)
  VALUES (c.id, p_action, c.state, t.to_state, p_actor, p_actor_role, p_channel, p_idem, p_payload);
  UPDATE card SET state = t.to_state, acted_by = CASE WHEN t.to_state='acted' THEN p_actor END,
                  acted_at = CASE WHEN t.to_state='acted' THEN now() END, result = p_payload
   WHERE id = c.id;
  RETURN QUERY SELECT c.id, c.state, t.to_state, false;
END $$;

-- DRY_RUN → LIVE：不重建，只翻模式；同 source_event_key 的 live 卡已存在時標 superseded（審計 #2）
CREATE OR REPLACE FUNCTION card_promote_dry_run(p_org uuid) RETURNS int LANGUAGE plpgsql AS $$
DECLARE n int;
BEGIN
  UPDATE card d SET state='superseded' WHERE d.org_id::text=p_org::text AND d.mode='dry_run' AND EXISTS
    (SELECT 1 FROM card l WHERE l.org_id=p_org AND l.mode='live' AND l.source_event_key=d.source_event_key);
  UPDATE card SET mode='live', state='open' WHERE org_id::text=p_org::text AND mode='dry_run' AND state='dry_run';
  GET DIAGNOSTICS n = ROW_COUNT; RETURN n;
END $$;

-- ---------------------------------------------------------------------------
-- 3. 收件匣視圖（六角色共用，API 以 role/assignee 篩）
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW inbox_v AS
SELECT c.id AS card_id, c.org_id, c.role, c.assignee_employee_id, c.owner_agent, c.kind, c.title,
       c.evidence_numbers, c.proposed_fields, c.canvas_view, c.actions, c.priority, c.state, c.expires_at, c.created_at,
       (c.expires_at IS NOT NULL AND c.expires_at < now()) AS is_overdue
FROM card c WHERE c.mode='live' AND c.state IN ('open','escalated');

-- ---------------------------------------------------------------------------
-- 4. 六種 Canvas 預篩視圖（都只讀 public；絕不 JOIN hr_private）
-- ---------------------------------------------------------------------------
-- ① 對外發信預覽與守門檢查單
CREATE OR REPLACE VIEW canvas_v1_outbound_preview AS
SELECT o.id AS outbound_id, o.status, o.channel, o.case_id, o.quote_id, o.invoice_id,
       ct.name AS recipient_name, ct.email AS recipient_email, cu.customer_name,
       o.final_body, left(o.final_body, 200) AS first_lines,
       (SELECT jsonb_agg(jsonb_build_object('filename', coalesce(dv.filename, qv.filename), 'sealed', coalesce(dv.is_sealed,false),
                                            'version_status', coalesce(dv.status, qv.status)))
          FROM outbound_attachment oa LEFT JOIN deliverable_version dv ON dv.id=oa.deliverable_version_id
                                      LEFT JOIN quote_version qv ON qv.id=oa.quote_version_id WHERE oa.outbound_id=o.id) AS attachments,
       jsonb_build_object(
         'internal_text', guard_hit('internal', coalesce(o.subject,'')||E'\n'||o.final_body) IS NULL,
         'forbidden_word', guard_hit('forbidden', coalesce(o.subject,'')||E'\n'||o.final_body) IS NULL,
         'recipient_of_case', (o.case_id IS NULL OR EXISTS (SELECT 1 FROM "case" cs WHERE cs.id=o.case_id AND cs.customer_id=ct.customer_id)),
         'no_links_ok', NOT coalesce((cu.delivery_constraints->>'no_links')::bool,false) OR o.final_body !~* 'https?://',
         'attachments_whitelisted', NOT EXISTS (SELECT 1 FROM outbound_attachment oa WHERE oa.outbound_id=o.id AND oa.deliverable_version_id IS NULL AND oa.quote_version_id IS NULL),
         'release_gate', o.release_gate_checked OR NOT EXISTS (SELECT 1 FROM outbound_attachment oa JOIN deliverable_version dv ON dv.id=oa.deliverable_version_id WHERE oa.outbound_id=o.id AND dv.is_sealed)
       ) AS gate_checks,
       em.body_new_text AS source_command_body_stripped
FROM outbound_message o
JOIN contact ct ON ct.id=o.to_contact_id
JOIN customer cu ON cu.id=ct.customer_id
LEFT JOIN email_switchboard_command sc ON sc.outbound_message_id=o.id
LEFT JOIN email_message em ON em.id=sc.source_message_id;

-- ② 報價／指示單／承諾比對表 ＋ 往來時間軸
CREATE OR REPLACE VIEW canvas_v2_quote_commitment_compare AS
SELECT cs.id AS case_id, cs.case_code, cs.stage, cs.contract_status, cs.customer_id, cu.customer_name,
       q.id AS quote_id, q.quote_no, q.status AS quote_status, q.quoted_total,
       (SELECT jsonb_agg(jsonb_build_object('work_item', wi.name, 'qty', ql.qty, 'unit_price', ql.unit_price, 'floor_price', wi.floor_price,
                                            'below_floor', ql.unit_price < wi.floor_price) ORDER BY ql.line_no)
          FROM quote_line ql JOIN work_item wi ON wi.id=ql.work_item_id WHERE ql.quote_id=q.id) AS quote_lines,
       (SELECT jsonb_agg(jsonb_build_object('item', ci.item_name, 'status', ci.item_status, 'amount', ci.amount, 'done', ci.done_amount, 'remaining', ci.amount-ci.done_amount))
          FROM contract_item ci WHERE ci.case_id=cs.id) AS contract_items,
       (SELECT jsonb_agg(jsonb_build_object('kind', k.kind, 'party', k.party, 'description', k.description, 'due', k.due_date, 'status', k.status,
                                            'written', k.written_confirm_comm_id IS NOT NULL) ORDER BY k.due_date NULLS LAST)
          FROM client_commitment k WHERE k.case_id=cs.id AND k.status NOT IN ('withdrawn')) AS commitments,
       (SELECT jsonb_agg(jsonb_build_object('at', cm.occurred_at, 'dir', cm.direction, 'channel', cm.channel, 'serial', cm.serial_no, 'summary', cm.summary_120) ORDER BY cm.occurred_at DESC)
          FROM (SELECT * FROM client_communication x WHERE x.case_id=cs.id ORDER BY x.occurred_at DESC LIMIT 50) cm) AS timeline,
       mc.master_cap, mc.dispatched_total, mc.remaining_cap, mc.cap_ratio
FROM "case" cs
JOIN customer cu ON cu.id=cs.customer_id
LEFT JOIN quote q ON q.id::text=cs.source_quote_id::text
LEFT JOIN LATERAL (SELECT p.master_cap, sum(ch.contract_total) AS dispatched_total, p.master_cap - coalesce(sum(ch.contract_total),0) AS remaining_cap,
                          CASE WHEN p.master_cap>0 THEN coalesce(sum(ch.contract_total),0)/p.master_cap END AS cap_ratio
                     FROM "case" p LEFT JOIN "case" ch ON ch.parent_case_id=p.id WHERE p.id=coalesce(cs.parent_case_id, cs.id) AND p.case_kind='open_contract'
                    GROUP BY p.master_cap) mc ON true;

-- ③ 成果放行與入帳沖銷單
CREATE OR REPLACE VIEW canvas_v3_release_and_receipt AS
SELECT i.id AS invoice_id, i.case_id, i.period_no, i.invoice_no, i.invoice_date, i.due_date, i.amount_due, i.retention_amount,
       coalesce(pa.allocated,0) AS allocated, coalesce(pr.reversed,0) AS reversed, coalesce(pd.recognized_diff,0) AS recognized_diff,
       i.amount_due - coalesce(pa.allocated,0) + coalesce(pr.reversed,0) - coalesce(pd.recognized_diff,0) AS unpaid,
       (SELECT jsonb_agg(jsonb_build_object('bank', b.bank, 'amount', b.amount, 'value_date', b.value_date, 'masked_tax_id', b.masked_tax_id, 'status', b.status))
          FROM bank_notice b WHERE i.id = ANY(b.candidate_invoice_ids) AND b.status='candidate') AS candidate_notices,
       (SELECT jsonb_agg(jsonb_build_object('milestone', g.milestone, 'class', g.deliverable_class, 'override_by', g.override_by, 'override_expires', g.override_expires_at,
                                            'allowed', sealed_release_allowed(g.case_id, g.milestone)))
          FROM deliverable_release_gate g WHERE g.case_id=i.case_id) AS release_gates
FROM invoice i
LEFT JOIN (SELECT invoice_id, sum(amount) allocated FROM receipt_allocation GROUP BY 1) pa ON pa.invoice_id=i.id
LEFT JOIN (SELECT a.invoice_id, sum(r.amount) reversed FROM receipt_reversal r JOIN receipt_allocation a ON a.id=r.allocation_id GROUP BY 1) pr ON pr.invoice_id=i.id
LEFT JOIN (SELECT invoice_id, sum(diff_amount) recognized_diff FROM receipt_allocation WHERE diff_kind IN ('bank_fee','discount','client_deduction') GROUP BY 1) pd ON pd.invoice_id=i.id;

-- ④ 審查退件與 Playbook 對照
CREATE OR REPLACE VIEW canvas_v4_review_rejection AS
SELECT t.id AS task_id, t.case_id, cs.case_code, cs.customer_id, nt.node_name, t.status, t.executor_id, t.checker_id,
       t.started_at, t.exec_done_at, date_part('day', now() - coalesce(t.started_at, t.created_at)) AS dwell_days, nt.exec_sla_days,
       (SELECT count(*) FROM task_event e WHERE e.task_id=t.id AND e.event='rejected') AS rejection_count,
       (SELECT jsonb_agg(jsonb_build_object('rule', r.rule_code, 'text', r.rule_text, 'enforcement', r.enforcement))
          FROM client_playbook_rule r WHERE r.active AND (r.customer_id=cs.customer_id OR r.scope='global')) AS playbook_rules,
       (SELECT jsonb_build_object('message_id', em.id, 'subject', em.subject, 'sent_at', em.sent_at, 'body', em.body_new_text)
          FROM email_message em WHERE em.case_id=cs.id AND em.category='CAT-03' ORDER BY em.sent_at DESC LIMIT 1) AS latest_rejection_mail,
       (SELECT jsonb_build_object('outbound_id', o.id, 'sent_at', o.sent_at, 'body', o.final_body)
          FROM outbound_message o WHERE o.case_id=cs.id AND o.status='sent' AND o.template_code='review_fix_reply' ORDER BY o.sent_at DESC LIMIT 1) AS last_passed_reply
FROM case_task t JOIN "case" cs ON cs.id=t.case_id JOIN node_template nt ON nt.id=t.node_template_id;

-- ⑤ 下包請款與毛利影響（只有標準成本與外部成本，無個人薪資）
CREATE OR REPLACE VIEW canvas_v5_subcontract_margin AS
SELECT ci.id AS cost_item_id, ci.case_id, cs.case_code, ci.kind, ci.nature, ci.status, ci.amount, s.name AS supplier_name, s.license_status AS supplier_license_status,
       est.estimated, act.actual, CASE WHEN est.estimated>0 THEN (act.actual-est.estimated)/est.estimated END AS overrun_ratio,
       cs.contract_total, cp.labor_std_cost, cp.external_cost, cp.misc_cost, cp.projected_total_cost,
       CASE WHEN cs.contract_total>0 THEN (cs.contract_total-cp.projected_total_cost)/cs.contract_total END AS margin_ratio_now,
       CASE WHEN cs.contract_total>0 THEN (cs.contract_total-cp.projected_total_cost-ci.amount)/cs.contract_total END AS margin_ratio_after
FROM cost_item ci JOIN "case" cs ON cs.id=ci.case_id
LEFT JOIN supplier s ON s.id=ci.supplier_id
LEFT JOIN LATERAL (SELECT sum(amount) estimated FROM cost_item e WHERE e.case_id=ci.case_id AND e.nature='estimate' AND e.status='estimate') est ON true
LEFT JOIN LATERAL (SELECT sum(amount) actual FROM cost_item a WHERE a.case_id=ci.case_id AND a.nature='actual' AND a.status<>'void') act ON true
LEFT JOIN case_cost_projection_v cp ON cp.case_id=ci.case_id;

-- ⑥ 結算三方對帳與未結承諾（獎金池欄位只有 gm 白名單可見，由 API 裁剪）
CREATE OR REPLACE VIEW canvas_v6_settlement_triway AS
SELECT st.id AS settlement_id, st.case_id, cs.case_code, st.status AS settlement_status, st.vp_signed_by, st.vp_signed_at, st.gm_signed_by, st.gm_signed_at,
       cs.contract_total, inv.billed_total, inv.received_total, inv.retention_outstanding,
       pts.total_points, cp.labor_std_cost, cp.external_cost, cp.projected_total_cost, cs.contract_total - cp.projected_total_cost AS projected_margin,
       (SELECT jsonb_agg(jsonb_build_object('kind', k.kind, 'party', k.party, 'status', k.status, 'due', k.due_date))
          FROM client_commitment k WHERE k.case_id=cs.id AND k.party='client' AND k.status IN ('stated','written_sent','pending_confirm','confirmed_unlinked')) AS open_commitments,
       (SELECT jsonb_agg(jsonb_build_object('item', ci.item_name, 'amount', ci.amount, 'done', ci.done_amount))
          FROM contract_item ci WHERE ci.case_id=cs.id AND ci.item_status='provisional' AND ci.done_amount>0) AS provisional_items_with_work,
       st.bonus_pool_total, st.bonus_pool_allocation                       -- ← 只給 gm；API 白名單裁剪
FROM case_settlement st JOIN "case" cs ON cs.id=st.case_id
LEFT JOIN LATERAL (SELECT sum(i.amount_due) billed_total, sum(coalesce(a.allocated,0)) received_total, sum(i.retention_amount) FILTER (WHERE i.retention_status<>'received') retention_outstanding
                     FROM invoice i LEFT JOIN (SELECT invoice_id, sum(amount) allocated FROM receipt_allocation GROUP BY 1) a ON a.invoice_id=i.id WHERE i.case_id=cs.id) inv ON true
LEFT JOIN LATERAL (SELECT sum(allocated_points) total_points FROM work_entry WHERE case_id=cs.id) pts ON true
LEFT JOIN case_cost_projection_v cp ON cp.case_id=cs.id;

-- ---------------------------------------------------------------------------
-- 5. 欄位白名單（API 層讀；view_no × actor_role → 可見欄位）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS canvas_column_whitelist (
  view_no smallint NOT NULL CHECK (view_no BETWEEN 1 AND 6),
  actor_role text NOT NULL REFERENCES actor_role(role),
  column_name text NOT NULL,
  PRIMARY KEY (view_no, actor_role, column_name)
);
-- 全域禁欄：任何視圖、任何角色（防時薪反推）
CREATE TABLE IF NOT EXISTS canvas_forbidden_column (column_regex text PRIMARY KEY);
INSERT INTO canvas_forbidden_column VALUES ('(hourly|base_salary|salary|wage|net_pay|insured_salary|bank_account|id_number)') ON CONFLICT DO NOTHING;

-- 白名單種子（簡化：以角色等級累加；gm 另加 bonus 欄）
INSERT INTO canvas_column_whitelist (view_no, actor_role, column_name)
SELECT v.view_no, r.role, c.column_name
FROM (VALUES (1),(2),(3),(4),(5),(6)) v(view_no)
CROSS JOIN actor_role r
CROSS JOIN LATERAL (
  SELECT a.attname AS column_name FROM pg_attribute a
   WHERE a.attrelid = ('canvas_v'||v.view_no||'_'||CASE v.view_no WHEN 1 THEN 'outbound_preview' WHEN 2 THEN 'quote_commitment_compare' WHEN 3 THEN 'release_and_receipt'
                                                     WHEN 4 THEN 'review_rejection' WHEN 5 THEN 'subcontract_margin' ELSE 'settlement_triway' END)::regclass
     AND a.attnum > 0 AND NOT a.attisdropped) c
WHERE NOT (c.column_name IN ('bonus_pool_total','bonus_pool_allocation') AND r.role <> 'gm')            -- 獎金池只給 gm
  AND NOT (v.view_no = 2 AND c.column_name = 'quote_lines' AND r.rank < 20)                               -- 底線單價：sales 以上
  AND NOT (v.view_no IN (5,6) AND c.column_name IN ('labor_std_cost','external_cost','projected_total_cost','projected_margin','margin_ratio_now','margin_ratio_after') AND r.rank < 40) -- 成本與毛利：pm 以上
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- 6. 結構自檢：canvas/fact/dim 視圖不得引用 hr_private；禁欄不得出現
-- ---------------------------------------------------------------------------
DO $$
DECLARE bad int;
BEGIN
  SELECT count(*) INTO bad FROM pg_views WHERE (schemaname='public' AND viewname LIKE 'canvas_v%' OR schemaname IN ('fact','dim')) AND replace(definition, '[MASKED_HR_PRIVATE]', '') ILIKE '%hr_private%';
  IF bad > 0 THEN RAISE EXCEPTION '% canvas/fact/dim views reference hr_private', bad; END IF;
  SELECT count(*) INTO bad FROM canvas_column_whitelist w JOIN canvas_forbidden_column f ON w.column_name ~* f.column_regex;
  IF bad > 0 THEN RAISE EXCEPTION '% whitelisted columns match forbidden regex', bad; END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 7. 證據 SQL 種子（R31 映射表用到的數字）
-- ---------------------------------------------------------------------------
INSERT INTO evidence_sql (sql_id, description, sql_text, returns) VALUES
 ('case.open_commitments', '該案未結業主承諾數', 'SELECT count(*) FROM client_commitment WHERE case_id=:case_id AND party=''client'' AND status IN (''stated'',''written_sent'',''pending_confirm'',''confirmed_unlinked'')', 'int'),
 ('customer.commitment_fulfil_rate', '客戶承諾兌現率', 'SELECT round(100.0*count(*) FILTER (WHERE status=''fulfilled'')/nullif(count(*),0),0) FROM client_commitment WHERE customer_id=:customer_id AND party=''client''', 'numeric'),
 ('commitment.hours_to_48h', '距 48h 書面期限剩餘小時', 'SELECT round(extract(epoch FROM (c.stated_at + interval ''48 hours'' - now()))/3600) FROM client_commitment c WHERE c.id=:commitment_id', 'numeric'),
 ('invoice.unpaid', '發票未收（含已認列差異）', 'SELECT unpaid FROM canvas_v3_release_and_receipt WHERE invoice_id=:invoice_id', 'numeric'),
 ('invoice.retention', '保留款', 'SELECT retention_amount FROM invoice WHERE id=:invoice_id', 'numeric'),
 ('invoice.aging_days', '帳齡天數', 'SELECT date_part(''day'', now()-invoice_date) FROM invoice WHERE id=:invoice_id', 'int'),
 ('outbound.gate_violations', '守門違規數', 'SELECT (SELECT count(*) FROM jsonb_each(gate_checks) WHERE value::text=''false'') FROM canvas_v1_outbound_preview WHERE outbound_id=:outbound_id', 'int'),
 ('outbound.attachment_count', '附件數', 'SELECT count(*) FROM outbound_attachment WHERE outbound_id=:outbound_id', 'int'),
 ('outbound.template', '範本代碼與版本', 'SELECT template_code||'' v''||template_version FROM outbound_message WHERE id=:outbound_id', 'text'),
 ('case.master_remaining_cap', '母約剩餘額度', 'SELECT remaining_cap FROM canvas_v2_quote_commitment_compare WHERE case_id=:case_id', 'numeric'),
 ('case.cap_ratio', '額度水位', 'SELECT cap_ratio FROM canvas_v2_quote_commitment_compare WHERE case_id=:case_id', 'numeric'),
 ('task.dwell_days', '工序停留天數', 'SELECT dwell_days FROM canvas_v4_review_rejection WHERE task_id=:task_id', 'int'),
 ('task.rejection_count', '退件次數', 'SELECT rejection_count FROM canvas_v4_review_rejection WHERE task_id=:task_id', 'int'),
 ('cost.overrun_ratio', '下包超支比率', 'SELECT overrun_ratio FROM canvas_v5_subcontract_margin WHERE cost_item_id=:cost_item_id', 'numeric'),
 ('settlement.margin', '預計毛利', 'SELECT projected_margin FROM canvas_v6_settlement_triway WHERE settlement_id=:settlement_id', 'numeric'),
 ('settlement.open_commitments', '結算未結承諾數', 'SELECT coalesce(jsonb_array_length(open_commitments),0) FROM canvas_v6_settlement_triway WHERE settlement_id=:settlement_id', 'int'),
 ('settlement.unpaid', '結算未收', 'SELECT billed_total-received_total FROM canvas_v6_settlement_triway WHERE settlement_id=:settlement_id', 'numeric'),
 ('otp.seconds_left', 'OTP 剩餘秒數', 'SELECT greatest(0, round(extract(epoch FROM (requested_at + interval ''5 minutes'' - now())))) FROM otp_request WHERE id=:otp_request_id', 'int'),
 ('permit.days_left', '憑單剩餘天', 'SELECT valid_until - current_date FROM permit WHERE id=:permit_id', 'int'),
 ('serial.same_thread_count', '同串往來封數', 'SELECT count(*) FROM client_communication WHERE org_id=:org_id AND serial_no=:serial_no', 'int')
ON CONFLICT (sql_id) DO UPDATE SET description=EXCLUDED.description, sql_text=EXCLUDED.sql_text, returns=EXCLUDED.returns;

-- Preserve installed R31-B convergence when this older migration is replayed.
DO $$ BEGIN
 IF to_regprocedure('public.restore_r31b_guards()') IS NOT NULL THEN
   PERFORM public.restore_r31b_guards();
 END IF;
END $$;
COMMIT;
