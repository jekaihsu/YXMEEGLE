"""What the case's own data says about its nodes, so nobody keeps a second copy in Lark.

Pure and read-only: the result is overlaid on the derived chain and never written to Lark. Two kinds:
`AutoDone` proves an early node done (edit RULES to change that); `Signal` reports a production node's source
evidence (外業/控制/圖資/報告), which may start the node but never finishes or submits it.
"""
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal

from ..case_evidence import live_confirmation_fields, live_contract_lines, proves_sales_by_code
from ..contract_links import plan_summary
from ..project_progress import PRODUCTION, NO_DAILY, actual_of, parse_decimal, planned_items, v3_field_total, work_orders_of
from .domain import NodeKey


@dataclass(frozen=True)
class AutoDone:
    rule: str
    reason_zh: str

    def public(self) -> dict:
        return {'rule': self.rule, 'reason': self.reason_zh}


@dataclass(frozen=True)
class Basis:
    c_code: bool
    has_confirmation: bool
    contract_lines: int


@dataclass(frozen=True)
class Rule:
    id: str
    nodes: tuple[NodeKey, ...]
    reason: Callable[[Basis], str | None]


# The first rule that claims a node wins. A rule's reason is None when it does not apply.
RULES = (
    Rule('c_code', (NodeKey.SALES,),
         lambda b: '工編以 C 開頭，業務階段已完成' if b.c_code else None),
    Rule('confirmation_lines', (NodeKey.SALES, NodeKey.PM, NodeKey.CONFIRMATION),
         lambda b: f'已建立工程確認單（{b.contract_lines} 筆合約工項）' if b.has_confirmation and b.contract_lines else None),
)


def basis_of(project, state) -> Basis:
    return Basis(proves_sales_by_code(project), bool(live_confirmation_fields(state, project)),
                 len(live_contract_lines(state, project)))


def evidence_for(project, state) -> dict[NodeKey, AutoDone]:
    """`state` is the workspace state that holds the case's confirmations and contract lines."""
    basis = basis_of(project, state or {})
    found: dict[NodeKey, AutoDone] = {}
    for rule in RULES:
        reason = rule.reason(basis)
        if reason:
            for key in rule.nodes:
                found.setdefault(key, AutoDone(rule.id, reason))
    return found


def applicable(evidence: Mapping[NodeKey, AutoDone], skipped) -> dict[NodeKey, AutoDone]:
    """An explicit 略過 always wins, so a skipped node carries no auto-done mark."""
    return {key: auto for key, auto in evidence.items() if key not in skipped}


# The progress read model names stages 'field'..'report'; they are the same keys as the production nodes.
PRODUCTION_NODES = tuple(NodeKey(key) for key in PRODUCTION)


# Daily and v3 actuals are revenue points; a plan quantity is in contract units, so they must not be compared.
# Only an actual measured in contract units may drive the 可送審 hint through the quantity guard, and no source provides one yet.
QUANTITY_SOURCE = 'quantity'
# The fill items' own planned and remaining revenue points are the same unit, so every item done is a legitimate basis.
ITEM_POINTS_SOURCE = 'item_points'


@dataclass(frozen=True)
class Signal:
    """One production node's source evidence. Counts are None while the plan or the daily links are unavailable."""
    planned_qty: str | None
    lines: int | None
    items: int | None
    work_orders: int
    latest_date: str | None
    actual_known: bool
    actual_value: str | None
    actual_source: str | None
    started: bool
    reason_zh: str
    progress: dict | None = None
    item_rows: tuple = ()
    items_total: int = 0
    items_truncated: bool = False
    items_all_done: bool = False

    @property
    def complete_by(self) -> str | None:
        planned, actual = parse_decimal(self.planned_qty), parse_decimal(self.actual_value)
        if (self.actual_source == QUANTITY_SOURCE and self.actual_known and planned is not None
                and actual is not None and planned > Decimal(0) and actual >= planned):
            return QUANTITY_SOURCE
        return ITEM_POINTS_SOURCE if self.items_all_done else None

    @property
    def can_submit(self) -> bool:
        return self.complete_by is not None

    def public(self) -> dict:
        return {'planned_qty': self.planned_qty, 'lines': self.lines, 'items': self.items,
                'work_orders': self.work_orders, 'latest_date': self.latest_date,
                'actual_known': self.actual_known, 'actual_value': self.actual_value, 'reason': self.reason_zh,
                'actual_source': self.actual_source, 'progress': self.progress,
                'items_total': self.items_total, 'items_truncated': self.items_truncated,
                'work_items': [{k: v for k, v in row.items() if k != 'item_id'} for row in self.item_rows]}


def production_signal(project, state, reports=None) -> dict[NodeKey, Signal]:
    """Per production node, from the case's contract plan, linked daily rows, the fill items' own points and (外業 only) the v3 register.

    `reports` is an already-built ReportsView, or None; this never reads Lark and never waits for the register.
    """
    summary = plan_summary(state or {}, project['id'])
    from copy import deepcopy
    from ..report_bridge import reconcile_bridges
    bridge_state={'projects':[project],'report_case_bridges':deepcopy((state or {}).get('report_case_bridges',{}))}
    if reports is not None and getattr(reports,'data',None) is not None: reconcile_bridges(bridge_state,reports)
    total = v3_field_total(project,reports,bridge_state['report_case_bridges'].get(project['id'])) if reports is not None else None
    found = {}
    for node in PRODUCTION_NODES:
        key = node.value
        planned, rows, items_total, truncated, progress = planned_items(state or {}, project, summary, key)
        orders = work_orders_of(project, key)
        actual = actual_of(project, key, total)
        count = orders['count'] or 0
        by_items = bool(progress and progress.known)
        started = bool(count) or actual['source'] == 'v3_reports' or by_items
        if count:
            reason = f'已有 {count} 筆日報連結到此案件'
        elif actual['source'] == 'v3_reports':
            reason = '週報登記冊顯示此案件外業累計大於 0'
        elif by_items:
            reason = '合約填報工項已有進度（來源剩餘營業額小於對應營業額）'
        else:
            reason = actual['reason'] or NO_DAILY
        found[node] = Signal(
            planned['qty'] if planned else None, planned['lines'] if planned else None,
            planned['items'] if planned else None, count, orders['latest_date'], actual['known'], actual['value'],
            actual['source'], started, reason, progress.public() if by_items else None, tuple(rows), items_total,
            truncated, bool(progress and progress.all_done))
    return found


def evidence_of(project, state, reports=None) -> dict[NodeKey, 'AutoDone | Signal']:
    """Everything the overlay uses: the early nodes proven done and every production node's signal."""
    return {**production_signal(project, state, reports), **evidence_for(project, state)}


def auto_done(evidence: Mapping) -> dict[NodeKey, AutoDone]:
    return {key: found for key, found in evidence.items() if isinstance(found, AutoDone)}


def signals(evidence: Mapping) -> dict[NodeKey, Signal]:
    return {key: found for key, found in evidence.items() if isinstance(found, Signal)}
