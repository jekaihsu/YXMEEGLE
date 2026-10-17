"""啟動 SOP: what to seed into 節點指派 and 任務 for one case, decided without I/O.

The plan comes from the case's derived contract plan and quotes. Lark state is
folded in afterwards as `NodeState`, so the preview hash covers only what the
operator reviews and survives a partial run.
"""
import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from ..business_policy import can_manage_roles
from ..contract_links import plan_summary
from ..sources import day
from .domain import FINISHED, NODE_DEPARTMENTS, NodeKey, TaskStatus, derive_chain
from .lark_table import CaseSnapshot
from .operations import facts_of

SOP_RULE_VERSION = 'start-sop-20261017.1'
CHAIN_NOTE = '節點狀態仍依九節點流程推導；啟動 SOP 只建立節點列與一筆種子任務，不會變更任何節點狀態。'
SHOWN_DATES = 5
PLAN_TRUNCATED_MESSAGE = '計畫明細過多已截斷，工項數量可能不完整'


class BlockerCode(StrEnum):
    DISABLED = 'disabled'
    WRITES_DISABLED = 'writes_disabled'
    NO_CONFIRMATION_CODE = 'no_confirmation_code'
    NO_PLANNED_QUANTITY = 'no_planned_quantity'
    FORBIDDEN = 'forbidden'
    LARK_UNAVAILABLE = 'lark_unavailable'


class WarningCode(StrEnum):
    NO_PM = 'no_pm'
    DEADLINE_CONFLICT = 'deadline_conflict'
    AMBIGUOUS_LINKS = 'ambiguous_links'
    NEEDS_REVIEW = 'needs_review'
    DERIVED_LINKS = 'derived_links'
    PLAN_TRUNCATED = 'plan_truncated'


class Outcome(StrEnum):
    CREATED = 'created'
    EXISTING = 'existing'
    FAILED = 'failed'
    SKIPPED = 'skipped'


BLOCKER_MESSAGES = {
    BlockerCode.DISABLED: '節點指派功能尚未啟用',
    BlockerCode.WRITES_DISABLED: '正式外部連線未啟用，節點指派暫不可修改',
    BlockerCode.NO_CONFIRMATION_CODE: '此案件沒有工程確認單編號，無法建立節點指派',
    BlockerCode.NO_PLANNED_QUANTITY: '此案件沒有大於 0 的計畫數量，無法啟動 SOP',
    BlockerCode.FORBIDDEN: '只有系統管理員、案件 PM、案件或節點主管，或本節點所屬組別經理可以啟動 SOP',
    BlockerCode.LARK_UNAVAILABLE: 'Lark 暫時無法讀取，無法確認目前的節點與任務',
}


@dataclass(frozen=True)
class Category:
    label: str
    node: NodeKey
    deadline_field: str


CATEGORIES = (
    Category('外業', NodeKey.FIELD, '外業期限'),
    Category('控制', NodeKey.CONTROL, '內業期限(控)'),
    Category('圖資', NodeKey.MAPPING, '內業期限(圖)'),
    Category('報告', NodeKey.REPORT, '內業期限(報)'),
)
SEED_NODES = tuple(c.node for c in CATEGORIES)


def marker(key: NodeKey) -> str:
    return f'[SOP-START:v1:{key.value}]'


@dataclass(frozen=True)
class Notice:
    code: WarningCode
    message: str
    node: NodeKey | None = None

    def public(self):
        return {'code': self.code.value, 'message': self.message, 'node': self.node.value if self.node else None}


@dataclass(frozen=True)
class ItemBasis:
    native: int
    derived: int
    ambiguous: int
    unlinked: int

    def public(self):
        return {'native': self.native, 'derived': self.derived, 'ambiguous': self.ambiguous, 'unlinked': self.unlinked}


@dataclass(frozen=True)
class PlannedNode:
    category: Category
    planned_qty: str
    lines: int
    items: int
    basis: ItemBasis
    deadline: str | None
    notices: tuple[Notice, ...]
    detail: str

    @property
    def key(self) -> NodeKey:
        return self.category.node

    @property
    def title(self) -> str:
        return f'{self.category.label}：依計畫數量完成'

    @property
    def department(self) -> str:
        # Existing task creation requires one of the node's departments; the first is the generic one.
        return NODE_DEPARTMENTS[self.key][0]

    def reviewed(self):
        return {'key': self.key.value, 'planned_qty': self.planned_qty, 'lines': self.lines, 'items': self.items,
                'items_basis': self.basis.public(), 'deadline': self.deadline, 'task_title': self.title,
                'task_detail': self.detail}


@dataclass(frozen=True)
class StartPlan:
    project_id: str
    code: str | None
    nodes: tuple[PlannedNode, ...]
    notices: tuple[Notice, ...]
    plan_rule_version: str

    @property
    def preview_hash(self) -> str:
        reviewed = {'nodes': [n.reviewed() for n in self.nodes], 'plan_rule_version': self.plan_rule_version,
                    'sop_rule_version': SOP_RULE_VERSION}
        return hashlib.sha256(json.dumps(reviewed, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class NodeState:
    """What Lark holds for one seed node right now."""
    node_exists: bool
    seed_task_exists: bool
    open: bool

    @property
    def will_create_node(self) -> bool:
        return not self.node_exists

    @property
    def will_create_task(self) -> bool:
        return self.open and not self.seed_task_exists


def observe(snapshot: CaseSnapshot, skipped, key: NodeKey) -> NodeState:
    seeded = any(t.status is not TaskStatus.CANCELLED and marker(key) in t.detail for t in snapshot.node_tasks(key))
    status = derive_chain(facts_of(snapshot, skipped))[key]
    return NodeState(bool(snapshot.rows.get(key)), seeded, status not in FINISHED)


def may_start(user, project, key: NodeKey, manages_node: bool) -> bool:
    """Project lead (admin, PM, project or node supervisor) or a manager of the node's departments."""
    node = next((n for n in project.get('nodes') or [] if n.get('key') == key.value), {})
    leads = {project.get('pm_id'), project.get('supervisor_id'), node.get('supervisor_id')} - {None, ''}
    return can_manage_roles(user) or user['id'] in leads or manages_node


def project_quotes(state, project):
    """The quotes the case page shows: direct project ids or links through the case's confirmations."""
    pid = project['id']
    confirmations = [c for c in state.get('source_confirmations') or [] if c.get('project_id') == pid]
    linked = [q for q in state.get('source_quotes') or []
              if q.get('project_id') == pid or pid in (q.get('project_ids') or [])
              or any(q.get('id') in (c.get('quote_ids') or []) or c.get('id') in (q.get('confirmation_ids') or [])
                     for c in confirmations)]
    return linked or list(project.get('quotes') or [])


def _valid_day(value) -> str | None:
    iso = day(value)
    try:
        return iso if iso and date(2000, 1, 1) <= date.fromisoformat(iso) <= date(2100, 12, 31) else None
    except ValueError:
        return None


def quote_deadline(quotes, field: str) -> tuple[str | None, tuple[str, ...]]:
    """The one date every dated quote agrees on, else no date and the disagreeing dates."""
    dates = sorted({d for q in quotes if (d := _valid_day((q.get('fields') or {}).get(field)))})
    return (dates[0] if len(dates) == 1 else None), (tuple(dates) if len(dates) > 1 else ())


def _count(counts, name) -> int:
    value = counts.get(name)
    return value if type(value) is int and value > 0 else 0


def _quantity(value) -> Decimal:
    try:
        parsed = Decimal(str(value).strip())
    except InvalidOperation:
        return Decimal(0)
    return parsed if parsed.is_finite() else Decimal(0)


def _detail(category: Category, qty, lines, items, basis: ItemBasis, notices, truncated) -> str:
    rows = [f'依計畫數量完成{category.label}。', f'計畫數量：{qty}', f'合約明細：{lines} 筆；工項：{items} 項',
            f'工項連結：原生 {basis.native}、推導 {basis.derived}、待確認 {basis.ambiguous}、未連結 {basis.unlinked}']
    rows += ['注意：' + n.message for n in notices]
    if truncated:
        rows.append('注意：' + PLAN_TRUNCATED_MESSAGE)
    return '\n'.join(rows + [marker(category.node)])



def plan_start(state, project, code: str | None) -> StartPlan:
    summary = plan_summary(state, project['id']) or {}
    categories = summary.get('categories') or {}
    truncated = summary.get('truncated') is True
    quotes = project_quotes(state, project)
    nodes, notices = [], []
    if not project.get('pm_id'):
        notices.append(Notice(WarningCode.NO_PM, '此案件尚未指定 PM'))
    if truncated:
        notices.append(Notice(WarningCode.PLAN_TRUNCATED, PLAN_TRUNCATED_MESSAGE))
    for category in CATEGORIES:
        counts = categories.get(category.label) or {}
        found = []
        if (review := _count(counts, 'needs_review')):
            found.append(Notice(WarningCode.NEEDS_REVIEW,
                                f'{category.label}有 {review} 筆合約明細因重複待人工核對，未計入計畫數量', category.node))
        if (ambiguous := _count(counts, 'items_ambiguous')):
            found.append(Notice(WarningCode.AMBIGUOUS_LINKS,
                                f'{category.label}有 {ambiguous} 個工項對到多筆合約明細，連結不明確', category.node))
        if (derived := _count(counts, 'items_derived')):
            found.append(Notice(WarningCode.DERIVED_LINKS,
                                f'{category.label}有 {derived} 個工項連結為系統推導，非來源原生關聯', category.node))
        qty = str(counts.get('planned_qty') or '0')
        if _quantity(qty) > 0:
            deadline, disputed = quote_deadline(quotes, category.deadline_field)
            if disputed:
                shown = '、'.join(disputed[:SHOWN_DATES]) + ('…' if len(disputed) > SHOWN_DATES else '')
                found.append(Notice(WarningCode.DEADLINE_CONFLICT,
                                    f'{category.label}期限在報價間不一致（{shown}），未帶入截止日', category.node))
            basis = ItemBasis(_count(counts, 'items_native'), _count(counts, 'items_derived'),
                              _count(counts, 'items_ambiguous'),
                              _count(counts, 'items_unlinked') + _count(counts, 'items_native_unresolved'))
            lines, items = _count(counts, 'lines'), _count(counts, 'items')
            nodes.append(PlannedNode(category, qty, lines, items, basis, deadline, tuple(found),
                                     _detail(category, qty, lines, items, basis, found, truncated)))
        notices += found
    return StartPlan(project['id'], code, tuple(nodes), tuple(notices), str(summary.get('rule_version') or ''))


def preview_body(plan: StartPlan, states: dict[NodeKey, NodeState] | None, blockers) -> dict:
    """The GET contract. `states` is None while Lark cannot be read, so nothing is promised."""
    rows = []
    for node in plan.nodes:
        state = (states or {}).get(node.key)
        rows.append({
            'key': node.key.value, 'label': node.category.label, 'category': node.category.label,
            'planned_qty': node.planned_qty, 'lines': node.lines, 'items': node.items,
            'items_basis': node.basis.public(), 'deadline': node.deadline,
            'node_exists': bool(state and state.node_exists), 'seed_task_exists': bool(state and state.seed_task_exists),
            'will_create_node': bool(state and state.will_create_node),
            'will_create_task': bool(state and state.will_create_task),
            'task_title': node.title, 'task_detail': node.detail})
    pending = any(r['will_create_node'] or r['will_create_task'] for r in rows)
    return {
        'project_id': plan.project_id, 'code': plan.code, 'eligible': not blockers and pending,
        'already_started': states is not None and bool(rows) and not pending,
        'blockers': [{'code': b.value, 'message': m} for b, m in blockers],
        'warnings': [n.public() for n in plan.notices], 'nodes': rows, 'chain_note': CHAIN_NOTE,
        'preview_hash': plan.preview_hash, 'plan_rule_version': plan.plan_rule_version}
