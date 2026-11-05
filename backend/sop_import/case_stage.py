from enum import Enum

from ..source_lifecycle import declared
from .domain import NODE_MAP
from .quote_facts import QuoteFacts

NEXT_NODE = {'sales': 'pm', 'pm': 'confirmation', 'confirmation': 'field', 'field': 'control',
             'control': 'mapping', 'mapping': 'report', 'report': 'pricing', 'pricing': 'settlement',
             'settlement': 'settlement'}
SOURCE_STAGE = {'執行中': 'field', '已完工': 'pricing', '已結案': 'settlement'}


class Stage(str, Enum):
    INQUIRY = 'inquiry'
    QUOTED = 'quoted'
    QUOTE_EXPIRED = 'quote_expired'
    RETURNED = 'returned'
    NUMBERED = 'numbered'
    CONFIRMATION = 'confirmation'
    FIELD = 'field'
    OFFICE = 'office'
    PRICING = 'pricing'
    PAID = 'paid'
    CANCELLED = 'cancelled'


# Most advanced first: a case is at the first stage whose predicate holds.
LADDER = (
    (Stage.PAID, lambda f: f.stage_label == 'G'),
    (Stage.PRICING, lambda f: f.stage_label in {'D', 'E', 'F', 'H'}),
    (Stage.OFFICE, lambda f: f.stage_label == 'C'),
    (Stage.FIELD, lambda f: f.stage_label == 'B'),
    (Stage.CONFIRMATION, lambda f: f.stage_label in {'0', 'A'} or f.v4_confirmation
     or f.won and f.numbered and f.confirmation_evidence),
    (Stage.NUMBERED, lambda f: f.won and f.numbered),
    (Stage.RETURNED, lambda f: f.won),
    (Stage.QUOTE_EXPIRED, lambda f: f.quoted and f.deadline_passed),
    (Stage.QUOTED, lambda f: f.quoted),
    (Stage.INQUIRY, lambda f: True),
)
STAGE_NODE = {Stage.INQUIRY: 'sales', Stage.QUOTED: 'sales', Stage.QUOTE_EXPIRED: 'sales', Stage.RETURNED: 'pm',
              Stage.NUMBERED: 'pm', Stage.CONFIRMATION: 'confirmation', Stage.FIELD: 'field', Stage.OFFICE: 'control',
              Stage.PRICING: 'pricing', Stage.PAID: 'settlement'}


def progress(facts: QuoteFacts) -> Stage:
    """How far the case got, ignoring a cancellation label."""
    return next(stage for stage, holds in LADDER if holds(facts))


def stage(facts: QuoteFacts) -> Stage:
    return Stage.CANCELLED if facts.stage_label == 'I' else progress(facts)


def start_node(project, nodes, facts: QuoteFacts):
    reached = {STAGE_NODE[progress(facts)]}
    source_stage = SOURCE_STAGE.get(declared(project))
    if source_stage:
        reached.add(source_stage)
    for node in nodes:
        key = node.get('key')
        if key not in NEXT_NODE:
            continue
        if node.get('status') in {'in_progress', 'blocked', 'paused', 'in_review'}:
            reached.add(key)
        elif node.get('status') == 'completed':
            reached.add(NEXT_NODE[key])
    return next(key for key in reversed(NODE_MAP.values()) if key in reached)
