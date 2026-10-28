"""
inbox_canvas_api.py — R31 六角色收件匣 × 六種 Canvas × 卡片動作狀態機（FastAPI）

分層：
  * 純函數（無 I/O）：project_columns / validate_card / resolve_transition / is_forbidden_column
  * Repo 介面：InMemoryRepo（測試）、PgRepo（psycopg，呼叫 card_act() / 視圖；只在最外層）
  * 路由：GET /inbox  ·  GET /canvas/{card_id}  ·  POST /cards/{id}/act
契約與 008_r31_inbox_and_canvas_views.sql 一致：
  - 三個數字必綁 evidence_sql_ids；沒有來源的數字不出卡。
  - 欄位白名單在 API 層依 (view_no, actor_role) 裁剪；全域禁欄正則任何角色都拿不到。
  - POST /cards/{id}/act 必帶 Idempotency-Key；重放回同一結果且只寫一筆稽核。
"""
from __future__ import annotations

import re
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

try:
    from fastapi import Depends, FastAPI, Header, HTTPException, Query
    from pydantic import BaseModel, Field
except ImportError:  # pragma: no cover - stdlib fallback for zero-dependency laptop bundle
    class HTTPException(Exception):
        def __init__(self, status_code: int, detail: str = ""):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail
    def Depends(x=None): return x
    def Header(default=None, **kw): return default
    def Query(default=None, **kw): return default
    def Field(default=None, **kw): return default
    class BaseModel: pass
    FastAPI = None

INBOX_ROLES = ("attendance", "case", "field", "settlement", "admin", "mine")
ACTOR_RANK = {"field_member": 10, "field_lead": 20, "inner_lead": 20, "sales": 20, "admin": 30, "finance": 30, "payroll": 30,
              "pm": 40, "vp": 50, "gm": 60, "it": 60}
CARD_KINDS = ("approve", "choose", "confirm", "fix", "inform")
# (kind, from_state, action) -> (to_state, min_rank)  —— 與 card_state_transition 同內容
TRANSITIONS: dict[tuple[str, str, str], tuple[str, int]] = {
    ("approve", "open", "approve"): ("acted", 20), ("approve", "open", "reject"): ("acted", 20), ("approve", "open", "unsure"): ("escalated", 10),
    ("choose", "open", "choose"): ("acted", 10), ("choose", "open", "unsure"): ("escalated", 10),
    ("confirm", "open", "confirm"): ("acted", 10), ("confirm", "open", "amend"): ("acted", 10), ("confirm", "open", "not_this"): ("acted", 10),
    ("fix", "open", "fix"): ("acted", 10), ("fix", "open", "unsure"): ("escalated", 10),
    ("inform", "open", "ack"): ("acted", 10),
    ("approve", "escalated", "approve"): ("acted", 40), ("approve", "escalated", "reject"): ("acted", 40),
    ("choose", "escalated", "choose"): ("acted", 40), ("fix", "escalated", "fix"): ("acted", 40),
}
FORBIDDEN_COLUMN_RE = re.compile(r"(hourly|base_salary|salary|wage|net_pay|insured_salary|bank_account|id_number)", re.I)
GM_ONLY_COLUMNS = {"bonus_pool_total", "bonus_pool_allocation"}
COST_COLUMNS = {"labor_std_cost", "external_cost", "projected_total_cost", "projected_margin", "margin_ratio_now", "margin_ratio_after"}

CANVAS_VIEW_NAMES = {1: "canvas_v1_outbound_preview", 2: "canvas_v2_quote_commitment_compare", 3: "canvas_v3_release_and_receipt",
                     4: "canvas_v4_review_rejection", 5: "canvas_v5_subcontract_margin", 6: "canvas_v6_settlement_triway"}
CANVAS_REF_KEY = {1: "outbound_id", 2: "case_id", 3: "invoice_id", 4: "task_id", 5: "cost_item_id", 6: "settlement_id"}


# ---------------------------------------------------------------------------
# 純函數
# ---------------------------------------------------------------------------
def is_forbidden_column(name: str) -> bool:
    return bool(FORBIDDEN_COLUMN_RE.search(name))


def allowed_columns(view_no: int, actor_role: str, all_columns: list[str]) -> list[str]:
    """與 SQL 種子同一規則：禁欄永遠不給；獎金池只給 gm；底線單價 sales 以上；成本／毛利 pm 以上。"""
    rank = ACTOR_RANK.get(actor_role, 0)
    out = []
    for c in all_columns:
        if is_forbidden_column(c):
            continue
        if c.startswith("bonus_pool_") and actor_role != "gm":
            continue
        if view_no == 2 and c == "quote_lines" and rank < 20:
            continue
        if view_no in (5, 6) and c in COST_COLUMNS and rank < 40:
            continue
        out.append(c)
    return out


def project_columns(view_no: int, actor_role: str, row: dict[str, Any]) -> dict[str, Any]:
    keep = set(allowed_columns(view_no, actor_role, list(row.keys())))
    def scrub(value):
        if isinstance(value, dict):
            return {k: scrub(v) for k, v in value.items()
                    if not is_forbidden_column(k)
                    and not (k.startswith("bonus_pool_") and actor_role != "gm")}
        if isinstance(value, list):
            return [scrub(v) for v in value]
        return value
    return scrub({k: v for k, v in row.items() if k in keep})


def validate_card(card: dict[str, Any], known_sql_ids: set[str]) -> list[str]:
    """沒有來源的數字不出卡；動作必在狀態機；一人一卡；標題 ≤40。"""
    errs = []
    if card.get("kind") not in CARD_KINDS:
        errs.append("kind")
    if not (1 <= len(card.get("title", "")) <= 40):
        errs.append("title_length")
    if card.get("role") not in INBOX_ROLES:
        errs.append("role")
    if not card.get("assignee_employee_id"):
        errs.append("assignee_required")
    ev = card.get("evidence_numbers", [])
    if not isinstance(ev, list) or len(ev) > 3:
        errs.append("evidence_count")
    else:
        for e in ev:
            if not isinstance(e, dict) or not {"label", "value", "sql_id"} <= set(e):
                errs.append("evidence_shape")
            elif e["sql_id"] not in known_sql_ids:
                errs.append(f"evidence_sql_unknown:{e['sql_id']}")
    acts = card.get("actions", [])
    if not isinstance(acts, list) or not (1 <= len(acts) <= 3):
        errs.append("actions_count")
    else:
        for a in acts:
            if (card.get("kind"), "open", a.get("action")) not in TRANSITIONS:
                errs.append(f"action_not_allowed:{a.get('action')}")
    if card.get("canvas_view") and not card.get("canvas_ref"):
        errs.append("canvas_ref_required")
    if not card.get("source_event_key") or not card.get("idempotency_key"):
        errs.append("keys_required")
    return errs


def resolve_transition(kind: str, state: str, action: str, actor_role: str, is_assignee: bool) -> tuple[str, Optional[str]]:
    """回傳 (to_state, error)。"""
    t = TRANSITIONS.get((kind, state, action))
    if not t:
        return state, f"transition {action} not allowed from {state} for {kind}"
    to_state, min_rank = t
    rank = ACTOR_RANK.get(actor_role, 0)
    if rank < min_rank:
        return state, f"actor role {actor_role} insufficient for {action}"
    if not is_assignee and rank < 40:
        return state, "only assignee or pm+ may act"
    return to_state, None


# ---------------------------------------------------------------------------
# Repo 介面
# ---------------------------------------------------------------------------
class Repo(Protocol):
    def list_inbox(self, org_id: str, role: str, employee_id: str) -> list[dict]: ...
    def get_card(self, card_id: str) -> Optional[dict]: ...
    def act(self, card_id: str, action: str, actor_id: str, actor_role: str, channel: str, idem: str, payload: dict) -> dict: ...
    def canvas_row(self, view_no: int, ref: dict) -> Optional[dict]: ...
    def known_sql_ids(self) -> set[str]: ...


@dataclass
class InMemoryRepo:
    cards: dict[str, dict] = field(default_factory=dict)
    action_log: dict[str, dict] = field(default_factory=dict)           # idempotency_key -> log row
    canvas: dict[tuple[int, str], dict] = field(default_factory=dict)   # (view_no, ref_value) -> row
    sql_ids: set[str] = field(default_factory=set)

    def known_sql_ids(self) -> set[str]:
        return set(self.sql_ids)

    def add_card(self, card: dict) -> str:
        errs = validate_card(card, self.known_sql_ids())
        if errs:
            raise ValueError(";".join(errs))
        if any(c["idempotency_key"] == card["idempotency_key"] for c in self.cards.values()):
            raise ValueError("duplicate idempotency_key")
        live_open = [c for c in self.cards.values() if c["source_event_key"] == card["source_event_key"]
                     and c.get("mode", "live") == "live" and c["state"] in ("open", "escalated")]
        if live_open and card.get("mode", "live") == "live":
            raise ValueError("duplicate live card for source_event_key")
        cid = card.get("id") or str(uuid.uuid4())
        self.cards[cid] = {**card, "id": cid, "state": card.get("state", "open"), "mode": card.get("mode", "live")}
        return cid

    def list_inbox(self, org_id, role, employee_id):
        rows = [c for c in self.cards.values() if c["org_id"] == org_id and c["role"] == role and c["mode"] == "live"
                and c["state"] in ("open", "escalated") and (role != "mine" or c["assignee_employee_id"] == employee_id)
                and (role == "mine" or c["assignee_employee_id"] == employee_id or c.get("shared_in_role"))]
        return sorted(rows, key=lambda c: (-c.get("priority", 50), c.get("created_at", "")))

    def get_card(self, card_id):
        return self.cards.get(card_id)

    def act(self, card_id, action, actor_id, actor_role, channel, idem, payload):
        if idem in self.action_log:
            r = self.action_log[idem]
            return {**r, "replayed": True}
        c = self.cards.get(card_id)
        if not c:
            raise KeyError(card_id)
        if c["mode"] == "dry_run":
            raise PermissionError("dry_run card cannot be acted")
        to_state, err = resolve_transition(c["kind"], c["state"], action, actor_role, c["assignee_employee_id"] == actor_id)
        if err:
            raise PermissionError(err)
        row = {"card_id": card_id, "action": action, "from_state": c["state"], "to_state": to_state, "actor": actor_id,
               "actor_role": actor_role, "channel": channel, "idempotency_key": idem, "payload": payload,
               "acted_at": datetime.now(timezone.utc).isoformat(), "replayed": False}
        self.action_log[idem] = row
        c["state"] = to_state
        if to_state == "acted":
            c["acted_by"], c["acted_at"], c["result"] = actor_id, row["acted_at"], payload
        return row

    def canvas_row(self, view_no, ref):
        key = ref.get(CANVAS_REF_KEY[view_no])
        return self.canvas.get((view_no, key))


class PgRepo:
    """psycopg 實作：所有寫入走 card_act()，所有讀取走視圖。只在部署時用。"""

    def __init__(self, dsn: str):
        import psycopg
        from psycopg.conninfo import conninfo_to_dict
        if conninfo_to_dict(dsn).get('dbname') != 'yongxiang_plumb_r39_clone':
            raise ValueError('clone database required')
        self._conn = psycopg.connect(dsn, autocommit=False)
        name = self._conn.execute('SELECT current_database()').fetchone()[0]
        assert name != 'yongxiang_plumb'
        assert name == 'yongxiang_plumb_r39_clone'

    def known_sql_ids(self):
        with self._conn.cursor() as cur:
            cur.execute("SELECT sql_id FROM evidence_sql")
            return {r[0] for r in cur.fetchall()}

    def list_inbox(self, org_id, role, employee_id):
        with self._conn.cursor() as cur:
            cur.execute("SELECT row_to_json(v) FROM inbox_v v WHERE org_id=%s AND role=%s AND (assignee_employee_id=%s OR %s<>'mine' AND false) "
                        "ORDER BY priority DESC, created_at", (org_id, role, employee_id, role))
            return [r[0] for r in cur.fetchall()]

    def get_card(self, card_id):
        with self._conn.cursor() as cur:
            cur.execute("SELECT row_to_json(c) FROM card c WHERE id=%s", (card_id,))
            r = cur.fetchone()
            return r[0] if r else None

    def act(self, card_id, action, actor_id, actor_role, channel, idem, payload):
        from psycopg.types.json import Jsonb
        with self._conn.cursor() as cur:
            try:
                cur.execute("SELECT card_id, from_state, to_state, replayed FROM card_act(%s,%s,%s,%s,%s,%s,%s)",
                            (card_id, action, actor_id, actor_role, channel, idem, Jsonb(payload)))
                row = cur.fetchone()
                self._conn.commit()
            except Exception as e:  # 轉成 API 可辨識的錯誤
                self._conn.rollback()
                raise PermissionError(str(e))
        return {"card_id": str(row[0]), "from_state": row[1], "to_state": row[2], "replayed": row[3], "action": action}

    def canvas_row(self, view_no, ref):
        key_col = CANVAS_REF_KEY[view_no]
        with self._conn.cursor() as cur:
            cur.execute(f"SELECT row_to_json(v) FROM {CANVAS_VIEW_NAMES[view_no]} v WHERE {key_col}=%s", (ref.get(key_col),))
            r = cur.fetchone()
            return r[0] if r else None


# ---------------------------------------------------------------------------
# 認證（示意）：從 header 取身分；正式版由 Lark SSO 換 JWT
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Actor:
    employee_id: str
    role: str
    org_id: str


def get_actor(
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    x_employee_id: Optional[str] = Header(default=None, alias="X-Employee-Id"),
    x_actor_role: Optional[str] = Header(default=None, alias="X-Actor-Role"),
    x_org_id: str = Header("YX", alias="X-Org-Id")  # R40: single org code (yongxiang merged into YX),
) -> Actor:
    if authorization and authorization.startswith('Bearer '):
        import hashlib,os,psycopg
        with psycopg.connect(os.environ.get('PG_DSN','dbname=yongxiang_plumb_r39_clone')) as conn:
            row=conn.execute("SELECT s.employee_id,s.role,s.org_id FROM api_session s JOIN employee e ON e.id=s.employee_id AND e.org_id=s.org_id WHERE token_sha256=%s AND expires_at>now() AND e.identity_confirmed AND e.employment_status='active'",(hashlib.sha256(authorization[7:].encode()).hexdigest(),)).fetchone()
        if not row:raise HTTPException(401,'Invalid or expired token')
        return Actor(str(row[0]),row[1],row[2])
    if x_employee_id and x_actor_role:
        if x_actor_role not in ACTOR_RANK:
            raise HTTPException(403, f"unknown actor role: {x_actor_role}")
        return Actor(employee_id=x_employee_id, role=x_actor_role, org_id=x_org_id)
    raise HTTPException(401,'Bearer token required')


class ActBody(BaseModel):
    action: str = Field(..., min_length=1, max_length=32)
    payload: dict = Field(default_factory=dict)
    channel: str = Field("api", pattern="^(lark|plumb|api)$")


def build_app(repo: Repo) -> FastAPI:
    app = FastAPI(title="Plumb Inbox/Canvas", version="r31")

    @app.get("/inbox")
    def inbox(role: str = Query(...), actor: Actor = Depends(get_actor)):
        if role not in INBOX_ROLES:
            raise HTTPException(400, "unknown inbox role")
        cards = repo.list_inbox(actor.org_id, role, actor.employee_id)
        # 回傳時再驗一次：沒有 sql_id 的證據不出門（雙保險）
        known = repo.known_sql_ids()
        safe = []
        for c in cards:
            if all(e.get("sql_id") in known for e in c.get("evidence_numbers", [])):
                safe.append({k: c[k] for k in ("id", "role", "kind", "title", "evidence_numbers", "proposed_fields", "canvas_view", "actions",
                                               "priority", "state", "expires_at") if k in c})
        return {"role": role, "count": len(safe), "cards": safe}

    @app.get("/canvas/{card_id}")
    def canvas(card_id: str, actor: Actor = Depends(get_actor)):
        c = repo.get_card(card_id)
        if not c or c["org_id"] != actor.org_id:
            raise HTTPException(404, "card not found")                   # 404 而非 403：避免存在性洩漏
        if c["assignee_employee_id"] != actor.employee_id and ACTOR_RANK[actor.role] < 40:
            raise HTTPException(404, "card not found")
        if not c.get("canvas_view"):
            return {"card_id": card_id, "view": None, "row": None}
        row = repo.canvas_row(c["canvas_view"], c["canvas_ref"])
        if row is None:
            raise HTTPException(404, "canvas row not found")
        projected = project_columns(c["canvas_view"], actor.role, row)
        return {"card_id": card_id, "view": c["canvas_view"], "view_name": CANVAS_VIEW_NAMES[c["canvas_view"]],
                "columns": list(projected.keys()), "row": projected, "evidence_sql_ids": [e["sql_id"] for e in c.get("evidence_numbers", [])]}

    @app.post("/cards/{card_id}/act")
    def act(card_id: str, body: ActBody, actor: Actor = Depends(get_actor), idempotency_key: str = Header(..., alias="Idempotency-Key")):
        c = repo.get_card(card_id)
        if not c or c["org_id"] != actor.org_id:
            raise HTTPException(404, "card not found")
        try:
            r = repo.act(card_id, body.action, actor.employee_id, actor.role, body.channel, idempotency_key, body.payload)
        except KeyError:
            raise HTTPException(404, "card not found")
        except PermissionError as e:
            raise HTTPException(409, str(e))
        return {"card_id": card_id, "action": body.action, "from_state": r["from_state"], "to_state": r["to_state"], "replayed": r["replayed"]}

    return app



# R31-B: both import paths serve the same authenticated PostgreSQL-backed handler.
try:
    from api import app
except Exception:
    app = None


# R48 presentation is shared by the authenticated launch and inbox adapters.
def r48_card(card, automation=None):
    card = dict(card)
    fields = card.get('proposed_fields') or {}
    policy = automation or card.get('category_automation') or {}
    card['category_automation'] = policy
    if policy.get('level') == 'auto_with_flag':
        card['category_badge'] = '⟨待確認⟩'
        card['actions'] = [*card.get('actions', []), {'action': 'category_wrong', 'label': '分類錯了'}]
    if str(card.get('idempotency_key', '')).startswith('r48:quote-choose:') or fields.get('needs_human'):
        card.update(kind='choose', title='待業務確認', amount=None, canonical_amount=None)
    return card


def r48_health(conn, me):
    pause = conn.execute('SELECT paused,reason FROM public.etl_pause_state WHERE org_id=%s', (me['org_id'],)).fetchone()
    cards = conn.execute("SELECT c.* FROM public.card c WHERE c.org_id=%s AND c.assignee_employee_id=%s AND c.state IN ('open','escalated','dry_run')", (me['org_id'], me['id'])).fetchall()
    policies = {r['category']: dict(r) for r in conn.execute('SELECT category,level FROM public.category_automation').fetchall()}
    visible = []
    for c in cards:
        category = (c.get('proposed_fields') or {}).get('category')
        c = r48_card(c, policies.get(category, {}))
        if c['kind'] == 'choose' and str(c.get('idempotency_key','')).startswith('r48:quote-choose:'):
            c['quotes'] = conn.execute("SELECT q.id,q.lark_record_id,q.quote_no,q.amount,q.customer_name,q.source_quote_date,q.created_by,l.link_role FROM public.quote q JOIN public.quote_case_link l ON l.quote_id=q.id WHERE l.case_id=%s ORDER BY q.lark_record_id", (c['case_id'],)).fetchall()
        visible.append(c)
    drafts = conn.execute("SELECT o.id,o.case_id,r.used,r.edited_fields,r.note FROM public.outbound_message o LEFT JOIN public.shadow_draft_review r ON r.outbound_id=o.id WHERE o.org_id=%s AND o.case_id IN (SELECT case_id FROM public.session_list_for(%s,false)) AND (o.approved_at AT TIME ZONE 'Asia/Taipei')::date=(now() AT TIME ZONE 'Asia/Taipei')::date ORDER BY o.approved_at", (me['org_id'],me['id'])).fetchall()
    return dict(etl_pause=pause, cards=visible, shadow_drafts=drafts)


def r48_action(conn, me, path, data):
    if path == '/api/r47/shadow-draft-review':
        if me['role_code'] not in ('admin','pm','gm','it'): raise PermissionError('review role required')
        if type(data.get('used')) is not bool or not isinstance(data.get('edited_fields'),list) or not all(isinstance(x,str) for x in data['edited_fields']): raise ValueError('used boolean and edited_fields array required')
        outbound = str(uuid.UUID(data['outbound_id']))
        row = conn.execute("SELECT 1 FROM public.outbound_message WHERE id=%s AND org_id=%s AND case_id IN (SELECT case_id FROM public.session_list_for(%s,false))", (outbound,me['org_id'],me['id'])).fetchone()
        if not row: raise PermissionError('no draft access')
        conn.execute("INSERT INTO public.shadow_draft_review(outbound_id,used,edited_fields,note,reviewed_by) VALUES(%s,%s,%s::jsonb,%s,%s) ON CONFLICT(outbound_id) DO UPDATE SET used=excluded.used,edited_fields=excluded.edited_fields,note=excluded.note,reviewed_by=excluded.reviewed_by,reviewed_at=now()", (outbound,data['used'],json.dumps(data['edited_fields']),data.get('note',''),str(me['id'])))
        return True
    card = str(uuid.UUID(data['card_id']))
    c = conn.execute("SELECT * FROM public.card WHERE id=%s AND org_id=%s AND assignee_employee_id=%s FOR UPDATE", (card,me['org_id'],me['id'])).fetchone()
    if not c: raise PermissionError('no card access')
    if path == '/api/r47/quote-choose':
        if me['role_code'] != 'pm' or not c['idempotency_key'].startswith('r48:quote-choose:'): raise PermissionError('sales quote card required')
        if c['state'] not in ('open','escalated','dry_run'): raise ValueError('card already resolved')
        q = conn.execute("SELECT q.id,q.quote_no FROM public.quote q JOIN public.quote_case_link l ON l.quote_id=q.id WHERE l.case_id=%s AND q.id=%s", (c['case_id'],str(uuid.UUID(data['quote_id'])))).fetchone()
        if not q: raise ValueError('quote does not belong to group')
        conn.execute("UPDATE public.quote_case_link SET link_role='pending_human' WHERE case_id=%s", (c['case_id'],))
        conn.execute("UPDATE public.quote_case_link l SET link_role=CASE WHEN q.id=%s THEN 'canonical' WHEN q.quote_no=%s THEN 'duplicate' ELSE 'revision' END,duplicate_of=CASE WHEN q.id<>%s AND q.quote_no=%s THEN %s::uuid END,decided_by=%s,decided_at=now() FROM public.quote q WHERE q.id=l.quote_id AND l.case_id=%s", (q['id'],q['quote_no'],q['id'],q['quote_no'],q['id'],str(me['id']),c['case_id']))
        conn.execute("UPDATE public.card SET status='acted',state='acted',action='confirm',action_key='r48:quote-choice:'||id::text,acted_by=%s,acted_at=now(),result=%s::jsonb WHERE id=%s", (me['id'],json.dumps({'quote_id':str(q['id'])}),card))
        return True
    if c['state'] not in ('open','escalated','dry_run'): raise ValueError('card already resolved')
    category=(c.get('proposed_fields') or {}).get('category')
    policy=conn.execute("SELECT 1 FROM public.category_automation WHERE category=%s AND level='auto_with_flag'", (category,)).fetchone()
    if not policy: raise ValueError('category does not require confirmation')
    conn.execute("INSERT INTO public.day1_feedback(org_id,checkpoint,severity,reported_by,note) VALUES(%s,'close','misclassification',%s,%s)", (me['org_id'],str(me['id']),'分類錯了 card='+card+' '+data.get('note','')))
    return True

# R50: shared clone-only closed-loop operations for CLI and dashboard adapters.
def lark_cli_closed_loop_state(case_code=None):
    from r50_closed_loop_api import snapshot
    return snapshot(case_code)

def lark_cli_closed_loop_action(action, payload):
    from r50_closed_loop_api import act
    return act(action, payload)
