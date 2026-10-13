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


HANDLERS = {}
TERMINAL = frozenset()


def sweep(node, plan):
    hidden, codes = plan.hidden, plan.hidden_codes
    plan.visited += 1
    if type(node) is dict:
        hit = HANDLERS.keys() & node.keys()
        for key in hit:
            HANDLERS[key](node, key, plan)
        for key in list(node):
            if key in hidden or key in codes or (':' in key and key.split(':', 1)[1] in hidden):
                del node[key]; plan.fallback += 1
        for key, value in node.items():
            kind = type(value)
            if kind is str:
                if value in hidden or value in codes:
                    node[key] = None; plan.fallback += 1
                elif len(value) > 24:
                    if 'record=' in value:
                        match = _URL_REC.search(value)
                        if match and match.group(1) in hidden:
                            node[key] = None; plan.fallback += 1
                    elif '|' in value and any(part in hidden for part in value.split('|')):
                        node[key] = '|'.join(part for part in value.split('|') if part not in hidden)
                        plan.fallback += 1
            elif kind in (dict, list) and key not in TERMINAL:
                sweep(value, plan)
    elif type(node) is list:
        kept = []
        for value in node:
            kind = type(value)
            if kind is str and (value in hidden or value in codes):
                plan.fallback += 1
            else:
                if kind in (dict, list):sweep(value, plan)
                kept.append(value)
        node[:] = kept


def apply(out, plan):
    out.pop('source_case_review', None)
    for collection in ('source_confirmations', 'source_quotes', 'contract_items'):
        for row in out.get(collection, ()):
            row.pop('history', None)
    sweep(out, plan)
    if plan.fallback:
        import logging
        logging.getLogger(__name__).warning('case_redaction unregistered holder: %d hits', plan.fallback)
    return plan


def _unresolved(node, key, plan):
    values = node[key]
    if isinstance(values, list):
        node[key] = [PLACEHOLDER] * len(values)


def _unresolved_records(node, key, plan):
    for row in node[key] if isinstance(node[key], list) else ():
        if isinstance(row, dict) and 'record_id' in row:
            row['record_id'] = PLACEHOLDER


HANDLERS.update(unresolved_confirmation_ids=_unresolved, unresolved_quote_ids=_unresolved,
                unresolved=_unresolved_records)
