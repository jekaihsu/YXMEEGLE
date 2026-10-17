"""Early nodes the case's own data already proves done, so nobody has to tick them in Lark.

Pure and read-only: the result is overlaid on the derived chain and never written to Lark. Later nodes
(外業 to 結算) are never inferred. Edit RULES to change what counts as evidence.
"""
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from ..sources import normalized_case
from .domain import NodeKey

C_CODE = re.compile(r'[Cc]\d+')


@dataclass(frozen=True)
class AutoDone:
    rule: str
    reason_zh: str

    def public(self) -> dict:
        return {'rule': self.rule, 'reason': self.reason_zh}


@dataclass(frozen=True)
class Basis:
    code: str
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
         lambda b: '工編以 C 開頭，業務階段已完成' if C_CODE.match(b.code) else None),
    Rule('confirmation_lines', (NodeKey.SALES, NodeKey.PM, NodeKey.CONFIRMATION),
         lambda b: f'已建立工程確認單（{b.contract_lines} 筆合約工項）' if b.has_confirmation and b.contract_lines else None),
)


def basis_of(project, state) -> Basis:
    pid = project.get('id')
    confirmed = any(isinstance(r, dict) and r.get('kind') == 'confirmation' for r in project.get('source_records') or []) \
        or any(c.get('project_id') == pid and c.get('source_kind') == 'confirmation'
               for c in state.get('source_confirmations') or [])
    lines = sum(1 for c in state.get('contract_items') or [] if c.get('project_id') == pid)
    return Basis(normalized_case(project.get('code')), confirmed, lines)


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
