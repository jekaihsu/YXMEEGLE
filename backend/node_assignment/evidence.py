"""Early nodes the case's own data already proves done, so nobody has to tick them in Lark.

Pure and read-only: the result is overlaid on the derived chain and never written to Lark. Later nodes
(外業 to 結算) are never inferred. Edit RULES to change what counts as evidence.
"""
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from ..case_evidence import live_confirmation_fields, live_contract_lines, proves_sales_by_code
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
