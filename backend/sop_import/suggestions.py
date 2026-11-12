"""Read-time task suggestions from quote evidence.

Pure. A suggestion never changes a task and nothing here writes anywhere; a person accepts or dismisses it through
the service. Each rule speaks for one catalog row and lists claims in order; the first claim that holds is the
suggestion. A proof claim satisfies the row's completion evidence on its own. An indicator claim correlates with
the row but leaves part of its completion text unobservable, so accepting it needs an explicit confirmation.
"""
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from .catalog import digest
from .domain import Applicability, Lifecycle
from .quote_facts import WON_LABELS, QuoteFacts


class Tier(str, Enum):
    PROOF = 'proof'
    INDICATOR = 'indicator'


@dataclass(frozen=True)
class Claim:
    tier: Tier
    state: Lifecycle
    holds: Callable[[QuoteFacts], bool]


@dataclass(frozen=True)
class Rule:
    meegle_id: int
    facts: tuple[str, ...]
    claims: tuple[Claim, ...]
    revision: int = 1

    @property
    def id(self):
        return f'quote-evidence:A:{self.meegle_id}'

    @property
    def source_row_key(self):
        return f'meegle-v137:A:{self.meegle_id}'


PROOF, INDICATOR = Tier.PROOF, Tier.INDICATOR
DONE, STARTED = Lifecycle.DONE, Lifecycle.IN_PROGRESS
# The one transition that reaches each suggested state, and the states it may start from.
ACTIONS = {DONE: 'complete', STARTED: 'start'}
REACHABLE = {DONE: {Lifecycle.PENDING, Lifecycle.IN_PROGRESS, Lifecycle.BLOCKED}, STARTED: {Lifecycle.PENDING}}


def label(letters):
    allowed = frozenset(letters)
    return lambda f: f.stage_label in allowed


def single(meegle_id, facts, tier, state, holds):
    return Rule(meegle_id, facts, (Claim(tier, state, holds),))


LABEL = ('stage_label',)
RULES = {rule.source_row_key: rule for rule in (
    single(1, ('inquiry_date', 'client', 'project_name'), INDICATOR, DONE,
           lambda f: bool(f.inquiry_date and f.client and f.project_name)),
    Rule(2, ('quote_nos', 'duplicated'), (Claim(PROOF, DONE, lambda f: bool(f.quote_nos) and not f.duplicated),
                                          Claim(INDICATOR, DONE, lambda f: bool(f.quote_nos)))),
    single(3, ('first_contact_date',), INDICATOR, DONE, lambda f: bool(f.first_contact_date)),
    single(8, ('quoted_date', 'pm_handoff_date'), INDICATOR, DONE, lambda f: bool(f.quoted_date and f.pm_handoff_date)),
    Rule(9, ('quoted_date', 'returned_date', 'quote_deadline', 'deadline_passed'),
         (Claim(INDICATOR, DONE, lambda f: bool(f.returned_date)),
          Claim(INDICATOR, STARTED, lambda f: bool(f.quoted_date) and not f.deadline_passed))),
    Rule(12, ('returned_date', 'quote_deadline', 'deadline_passed'),
         (Claim(PROOF, DONE, lambda f: bool(f.returned_date)), Claim(PROOF, DONE, lambda f: f.deadline_passed))),
    Rule(15, ('returned_date', 'price_positive'),
         (Claim(INDICATOR, DONE, lambda f: bool(f.returned_date) and f.price_positive),
          Claim(INDICATOR, STARTED, lambda f: bool(f.returned_date)))),
    # The 回傳本 upload in #16's completion text has no source field, so a valid number stays an indicator.
    single(16, ('engineering_no', 'numbered', 'numbers_consistent'), INDICATOR, DONE,
           lambda f: f.numbered and f.numbers_consistent),
    single(17, ('post_win_contact_date', 'contract_end_date'), INDICATOR, DONE,
           lambda f: bool(f.post_win_contact_date and f.contract_end_date)),
    single(19, ('confirmation_link', 'returned_date', 'confirmation_meeting_date', 'v4_confirmation', 'stage_label'),
           INDICATOR, DONE, lambda f: bool(f.confirmation_link and f.returned_date or f.confirmation_meeting_date
                                           or f.v4_confirmation or f.stage_label in WON_LABELS)),
    single(59, ('field_points', 'stage_label'), INDICATOR, DONE, lambda f: f.field_points or label('BCDEFGH')(f)),
    single(60, ('office_points', 'stage_label'), INDICATOR, DONE, lambda f: f.office_points or label('CDEFGH')(f)),
    single(61, ('admin_points', 'admin_return_date'), INDICATOR, DONE, lambda f: f.admin_points or bool(f.admin_return_date)),
    single(21, ('field_team', 'field_deadline'), INDICATOR, STARTED, lambda f: bool(f.field_team or f.field_deadline)),
    single(24, LABEL, INDICATOR, DONE, label('BCDEFGH')),
    single(25, ('stage_label', 'meegle_daily'), INDICATOR, STARTED,
           lambda f: f.stage_label == 'B' or f.meegle_daily.upper() == 'TRUE'),
    single(26, LABEL, INDICATOR, STARTED, label('B')),
    single(29, LABEL, INDICATOR, DONE, label('CDEFGH')),
    single(32, LABEL, INDICATOR, DONE, label('CDEFGH')),
    single(33, LABEL, INDICATOR, STARTED, label('CD')),
    single(34, LABEL, INDICATOR, STARTED, label('CD')),
    single(35, LABEL, INDICATOR, STARTED, label('CD')),
    single(36, LABEL, INDICATOR, DONE, label('DEFGH')),
    single(37, LABEL, INDICATOR, DONE, label('DEFGH')),
    single(38, LABEL, INDICATOR, DONE, label('EFGH')),
    single(39, LABEL, INDICATOR, DONE, label('EFGH')),
    single(30, ('billable_date', 'stage_label'), INDICATOR, DONE, lambda f: bool(f.billable_date) or label('EFGH')(f)),
    single(41, LABEL, INDICATOR, DONE, label('EFGH')),
    single(43, LABEL, INDICATOR, DONE, label('FG')),
    Rule(44, ('received', 'received_date', 'stage_label'),
         (Claim(PROOF, DONE, lambda f: f.received or bool(f.received_date)), Claim(INDICATOR, DONE, label('G')))),
    single(46, LABEL, INDICATOR, STARTED, label('EF')),
)}


def evaluate(rule: Rule, facts: QuoteFacts):
    claim = next((c for c in rule.claims if c.holds(facts)), None)
    if claim is None:
        return None
    body = {'rule_id': rule.id, 'rule_revision': rule.revision, 'tier': claim.tier.value,
            'suggested_state': claim.state.value, 'facts': facts.plain(rule.facts)}
    return {**body, 'facts_hash': digest(body)}


def current(task, facts: QuoteFacts):
    """The suggestion the evidence makes for this task now, or None when it would not move the task forward."""
    rule = RULES.get(task.source_row_key)
    if rule is None or task.template_family_id == 'manual' or task.applicability != Applicability.APPLICABLE:
        return None
    found = evaluate(rule, facts)
    if found is None or task.state not in REACHABLE[Lifecycle(found['suggested_state'])]:
        return None
    return {'task_id': task.id, **found}
