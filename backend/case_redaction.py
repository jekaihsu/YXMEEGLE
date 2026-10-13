"""One response-only redaction plan for confirmation and quote identities."""
from dataclasses import dataclass, field
import re
from .source_entities import entity_id
from .source_case_policy import identity, CODE_FIELDS
from .sources import source_id, text

CASE_COLLECTIONS = ('source_confirmations', 'source_quotes')
PLACEHOLDER = '［不開放檢視］'
_URL_REC = re.compile(r'[?&]record=([^&#]+)')


def forms(row):
    ident = row.get('source_identity') or {}
    result = {x for x in (ident.get('record_id'), row.get('id'), row.get('review_quote_id')) if x}
    if all(ident.get(k) for k in ('base_token', 'table_id', 'record_id')):
        result.update((entity_id(ident), identity(ident), source_id(ident)))
    for key in ('source_url', 'url'):
        match = _URL_REC.search(row.get(key) or '')
        if match:
            result.add(match.group(1))
    return {x for x in result if isinstance(x, str) and len(x) >= 8}


def codes_of(row):
    values = [row.get(k) for k in ('code', 'quote_code', 'engineering_code', 'parent_code')]
    values += row.get('code_history', [])
    values += [text((row.get('fields') or {}).get(k)) for k in CODE_FIELDS]
    return {x for x in values if isinstance(x, str) and x}


@dataclass
class Plan:
    admitted: frozenset
    hidden: frozenset
    hidden_codes: frozenset
    labels: dict = field(default_factory=dict)
    fallback: int = 0
    visited: int = 0


def snapshot(state):
    return {c: list(state.get(c, ())) for c in CASE_COLLECTIONS + ('contract_items', 'projects')}


def make_plan(before, after):
    admitted, prior, allowed_codes, prior_codes = set(), set(), set(), set()
    for collection in CASE_COLLECTIONS:
        for row in after.get(collection, ()):
            admitted.update(forms(row)); allowed_codes.update(codes_of(row))
        for row in before.get(collection, ()):
            prior.update(forms(row)); prior_codes.update(codes_of(row))
    visible = {p['id'] for p in after.get('projects', ())}
    for p in after.get('projects', ()):
        admitted.update(forms(p)); allowed_codes.update(codes_of(p))
    for p in before.get('projects', ()):
        if p['id'] not in visible:
            prior.update(forms(p)); prior_codes.update(codes_of(p))
    plan = Plan(frozenset(admitted), frozenset(prior-admitted), frozenset(prior_codes-allowed_codes))
    plan.labels = {p['id']: [label for q in p.get('quotes', ()) if q.get('id') in plan.hidden
        for label in (q.get('quote_code'), q.get('id')) if label and label not in allowed_codes]
        for p in before.get('projects', ())}
    return plan
