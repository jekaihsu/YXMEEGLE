"""Keep relationship class, quote workflow and engineering lifecycle separate.

Per docs/COMPANY_COCKPIT_RELEASE_20261001.md the quote register's `狀態` (quote
workflow) and `案件狀態` (engineering lifecycle) are distinct fields with no
priority between them, and `待確認單` is only a relationship classification.
Raw values are preserved; only documented lifecycle options map to a canonical
value. Blank, unknown and conflicting values are flagged for verification, and
closure is never inferred from dates, payments or the quote's `成案`.
"""
import re
from .sources import text, source_id

LIFECYCLE = ('報價中', '執行中', '已完工', '已結案', '中止', '內部')
DATE_OPTION = re.compile(r'^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}$|^\d{1,2}[-/.]\d{1,2}$')


def declared(p):
    """The only lifecycle value workflow behavior may depend on; raw source_status never counts.

    Returns a canonical option only when the summary is fully verified: state is
    mapped, no review reasons remain and the value is a documented option.
    Anything else (missing, blank, unknown, conflicting, malformed) is None.
    """
    lifecycle = p.get('source_lifecycle')
    if not isinstance(lifecycle, dict) or lifecycle.get('state') != 'mapped' or lifecycle.get('reasons'):
        return None
    canonical = lifecycle.get('canonical')
    return canonical if canonical in LIFECYCLE else None


def governed(p):
    """Lark-sourced cases (or any carrying a lifecycle summary) are governed by source lifecycle."""
    return p.get('source_kind') == 'lark' or 'source_lifecycle' in p


def needs_review(p):
    """Governed cases without a verified canonical lifecycle fail closed (待核對)."""
    return governed(p) and declared(p) is None


def quote_workflow_kind(raw):
    if not raw:
        return 'blank'
    if raw == '成案':
        return 'won'
    return 'date' if DATE_OPTION.match(raw) else 'other'


def lifecycle_entry(source, ident, field, raw):
    raw = text(raw).strip()
    state = 'blank' if not raw else 'mapped' if raw in LIFECYCLE else 'unknown'
    return {'source': source, 'source_id': ident, 'field': field, 'raw': raw,
            'canonical': raw if state == 'mapped' else None, 'state': state}


def summarize(confirmations, quotes):
    lifecycle = [lifecycle_entry('confirmation', source_id(r), '狀態', r['fields'].get('狀態')) for r in confirmations]
    lifecycle += [lifecycle_entry('quote', source_id(q), '案件狀態', q['fields'].get('案件狀態')) for q in quotes]
    workflow = []
    for q in quotes:
        raw = text(q['fields'].get('狀態')).strip()
        workflow.append({'source_id': source_id(q), 'field': '狀態', 'raw': raw, 'kind': quote_workflow_kind(raw)})
    values = {e['canonical'] for e in lifecycle if e['state'] == 'mapped'}
    reasons = []
    if any(e['state'] == 'unknown' for e in lifecycle):
        reasons.append('unknown_option')
    if len(values) > 1:
        reasons.append('conflict')
    if not lifecycle or any(e['state'] == 'blank' for e in lifecycle):
        reasons.append('blank')
    canonical = next(iter(values)) if len(values) == 1 and not reasons else None
    return {
        'relationship': '已關聯確認單' if confirmations else '待確認單',
        'quote_workflow': workflow,
        'lifecycle_sources': lifecycle,
        'canonical': canonical,
        'state': 'mapped' if canonical else 'needs_verification',
        'reasons': reasons,
        'blank_sources': [e['source_id'] for e in lifecycle if e['state'] == 'blank'],
    }
