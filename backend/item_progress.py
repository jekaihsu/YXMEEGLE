"""Progress of a fill item (合約填報工項) and of a production node, from Lark's own revenue points.

`對應營業額` is the item's planned revenue points and `本工項剩餘營業額` is what Lark says is left after the linked daily
and work-order rows consumed part of it. Both are the same unit, so a node percentage is legitimate. A remaining equal to
the plan is ambiguous (nothing done, or nothing linked) and is never read as 0% done.
"""
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from .sources import REMAINING_POINTS_FIELD, text  # noqa: F401  (re-exported)

PLANNED_POINTS_FIELD = '對應營業額'
MAX_POINTS = Decimal(10) ** 9
DONE, PARTIAL, NO_SIGNAL = 'done', 'partial', 'no_signal'
NUMBER = re.compile(r'(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?')
# A comma is only a thousands separator: groups of exactly three digits, so "0,0" and "1,2" are malformed, not 0 and 12.
GROUPED = re.compile(r'\d{1,3}(?:,\d{3})+(?:\.\d*)?')
HUNDRED, ONE_DECIMAL = Decimal(100), Decimal('0.1')
CAPPED_UNTIL_DONE = Decimal('99.9')


def parse_points(value) -> Decimal | None:
    """A non-negative, bounded decimal, or None for anything else (blank, negative, NaN, huge, text)."""
    if value is None or isinstance(value, bool):
        return None
    raw = (text(value) if isinstance(value, (list, dict)) else str(value)).strip()
    if len(raw) > 100:
        return None
    if GROUPED.fullmatch(raw):
        raw = raw.replace(',', '')
    elif not NUMBER.fullmatch(raw):
        return None
    try:
        number = Decimal(raw)
    except InvalidOperation:
        return None
    # A vanishing exponent would make fmt() build a gigantic string, so only 12 decimal places are meaningful.
    return number if number.is_finite() and number <= MAX_POINTS and (number == 0 or number.adjusted() >= -12) else None


def fmt(number: Decimal | None) -> str | None:
    return None if number is None else format(number.normalize(), 'f')


def item_status(planned: Decimal | None, remaining: Decimal | None) -> str:
    if planned is None or remaining is None or planned <= 0 or remaining > planned:
        return NO_SIGNAL
    if remaining <= 0:
        return DONE
    return PARTIAL if remaining < planned else NO_SIGNAL


@dataclass(frozen=True)
class NodeProgress:
    items_total: int
    items_done: int
    earned: Decimal
    planned: Decimal
    known: bool
    all_done: bool
    known_items: int = 0

    @property
    def percent(self) -> Decimal | None:
        if not self.known or self.planned <= 0:
            return None
        value = min(HUNDRED, max(Decimal(0), (self.earned / self.planned * HUNDRED).quantize(ONE_DECIMAL, ROUND_HALF_UP)))
        return value if self.all_done else min(value, CAPPED_UNTIL_DONE)

    def public(self, points: bool = True) -> dict | None:
        """None until some item has real progress. Without the points gate only the item counts remain."""
        if not self.known:
            return None
        return {'percent': fmt(self.percent) if points else None, 'earned_points': fmt(self.earned) if points else None,
                'planned_points': fmt(self.planned) if points else None, 'items_done': self.items_done,
                'items_total': self.items_total, 'known_items': self.known_items,
                'unknown_items': self.items_total - self.known_items}


def node_progress(pairs, complete: bool = True) -> NodeProgress:
    """`pairs` are (planned, remaining) decimals or None, one per planned item of the node.

    Earned and planned points only count items whose remaining is a valid number not above the plan.
    An incomplete list (truncated plan) can never be all done.
    """
    pairs = list(pairs)
    statuses = [item_status(p, r) for p, r in pairs]
    valid = [(p, r) for p, r in pairs if p is not None and r is not None and p > 0 and r <= p]
    return NodeProgress(len(pairs), statuses.count(DONE), sum((p - r for p, r in valid), Decimal(0)),
                        sum((p for p, _ in valid), Decimal(0)), any(s != NO_SIGNAL for s in statuses),
                        complete and bool(pairs) and all(s == DONE for s in statuses),
                        sum(s != NO_SIGNAL for s in statuses))
