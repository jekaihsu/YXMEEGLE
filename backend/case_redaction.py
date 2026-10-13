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


def _refs(node, key, plan):
    if isinstance(node[key], list):
        node[key] = [value for value in node[key] if value in plan.admitted]


def _entity_ids(node, key, plan):
    values = node[key]
    if isinstance(values, dict):
        for collection in CASE_COLLECTIONS:
            if collection in values:
                _refs(values, collection, plan)


HANDLERS.update(confirmation_ids=_refs, quote_ids=_refs, source_record_ids=_refs,
                source_entity_ids=_entity_ids)


def _names_hidden(row, plan):
    for key in ('id','quote_id','source_url','url','record_ids','link_record_ids','text','code','quote_code','engineering_code'):
        value = row.get(key)
        if type(value) is str:
            if value in plan.hidden or value in plan.hidden_codes:return True
            match = _URL_REC.search(value) if 'record=' in value else None
            if match and match.group(1) in plan.hidden:return True
        elif type(value) is list and any(type(x) is str and x in plan.hidden for x in value):
            return True
    return False


def _record_list(node, key, plan):
    if not isinstance(node[key], list):return
    kept = []
    for row in node[key]:
        if isinstance(row, dict) and _names_hidden(row, plan):
            if key != 'quotes' or not row.get('source_missing'):continue
            # A process-secret HMAC preserves a stable row key without exposing identity.
            opaque = hmac.new(_OPAQUE_KEY, str(row.get('id')).encode(), hashlib.sha256).hexdigest()
            row = {k: row.get(k) for k in ('amount', 'source_missing')}
            row.update(id='removed-'+opaque,
                quote_code=None,engineering_code=None,source_url=None,url=None,fields=None,review_available=False)
        sweep(row, plan);kept.append(row)
    node[key] = kept


def _fields(node, key, plan):
    if not isinstance(node[key], dict):return
    for name, value in node[key].items():
        if isinstance(value, list):
            node[key][name] = [x for x in value if not (type(x) is str and (x in plan.hidden or x in plan.hidden_codes)
                or isinstance(x, dict) and _names_hidden(x, plan))]


def _conflicts(node, key, plan):
    if not isinstance(node[key], dict):return
    for name in list(node[key]):
        if ':' in name and name.split(':', 1)[1] in plan.hidden:
            del node[key][name]
        elif isinstance(node[key][name], list):
            node[key][name] = [x for x in node[key][name] if not (type(x) is str and (x in plan.hidden or x in plan.hidden_codes))]


def _scrub_text(messages, labels):
    for i, message in enumerate(messages):
        for label in labels:message = message.replace('報價 '+label+'：', '報價 '+PLACEHOLDER+'：')
        messages[i] = message


def _policy_summary(node, key, plan):
    for row in node[key]:
        labels = plan.labels.get(row.get('project_id'))
        if not labels:continue
        closure = row.get('closure', {})
        financial = closure.get('financial', {})
        incoming = financial.get('incoming', {})
        for section in [closure, financial, incoming, *row.get('nodes', [])]:
            _scrub_text(section.get('missing', []), labels)


import hashlib, hmac, secrets
_OPAQUE_KEY = secrets.token_bytes(32)
HANDLERS.update(quotes=_record_list, source_record_history=_record_list, fields=_fields,
                source_conflicts=_conflicts, policy_summary=_policy_summary)
TERMINAL = frozenset(('quotes', 'source_record_history'))


def _source_urls(node, key, plan):
    node[key] = [value for value in node[key] if not (
        isinstance(value, str) and (match := _URL_REC.search(value)) and match.group(1) in plan.hidden)]


HANDLERS['source_urls'] = _source_urls


def _provenance(node, key, plan):
    node.pop(key, None)


HANDLERS['source_provenance'] = _provenance


def _case_scalar(node, key, plan):
    if isinstance(node[key], str) and node[key] in plan.hidden:
        node[key] = None


# Lifecycle status/raw values remain intact; only diagnostic identities change.
HANDLERS.update(source_id=_case_scalar, blank_sources=_refs)
