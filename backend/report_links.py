"""Exact report identities. Candidates are evidence and never a fallback assignment."""
from dataclasses import dataclass, asdict
from enum import Enum
import json
from pathlib import Path

VOCABULARY=json.loads(Path(__file__).with_name("report_link_vocabulary.json").read_text(encoding="utf-8"))
from .sources import normalized_case, PROVISIONAL_CASE_FIELD


class LinkBasis(str, Enum):
    SOURCE = VOCABULARY['SOURCE']['value']
    CODE = VOCABULARY['CODE']['value']
    MANUAL = VOCABULARY['MANUAL']['value']


RULES = (
    ('native', 'One complete base/table/record identity; conflicting exact text refuses attribution'),
    ('code', 'One nonblank exact full normalized code or explicitly reviewed alias'),
    ('item', 'One native reporting item or reviewed unique item inside the linked case'),
    ('unresolved', 'Candidates are evidence only; never fuzzy, truncate, split or cross bases'),
)
REASONS = ('missing_reference', 'unresolved_reference', 'ambiguous_reference')
BASIS_LABELS = {VOCABULARY[k]['value']:VOCABULARY[k]['label'] for k in ('SOURCE','CODE','MANUAL')}


@dataclass(frozen=True)
class LinkDecision:
    project_id: str | None
    basis: str | None
    reason: str | None
    candidates: tuple[dict, ...]
    work_item_id: str | None = None

    def public(self):
        return asdict(self)


def identity(value):
    parts = tuple(value.get(k) for k in ('base_token', 'table_id', 'record_id'))
    return parts if all(isinstance(p, str) and p for p in parts) else None


def daily_code(row):
    f = row.get('fields', row.get('source_fields', {}))
    return normalized_case(f.get('案件編號') or f.get('工程編號') or f.get('案號') or
                           f.get(PROVISIONAL_CASE_FIELD) or f.get('可能確認單工作編號') or row.get('source_case_code'))


def native_references(row):
    if 'native_references' in row: return row['native_references']
    refs=[]
    base=row.get('base_token') or row.get('source_identity',{}).get('base_token')
    fields=row.get('fields',row.get('source_fields',{}))
    def visit(value,base,table):
        if isinstance(value,list):
            for item in value: visit(item,base,table)
        elif isinstance(value,dict):
            base=value.get('base_token') or base;table=value.get('table_id') or table
            for key in ('id','record_id','record_ids','link_record_ids'):
                if key in value: visit(value[key],base,table)
        elif isinstance(value,str) and value.startswith('rec'):
            refs.append(dict(base_token=base,table_id=table,record_id=value))
    for field in ('所屬案件','內業工項','合約工項'):
        visit(fields.get(field),base,row.get('linked_tables',{}).get(field))
    return refs


def resolve_daily(row, projects, *, native_targets=None, unresolved_native=False):
    """native_targets are resolved typed identities, including the reporting item's parent case."""
    code = daily_code(row)
    evidence = {}
    def add(pid, why, rank):
        if pid not in evidence: evidence[pid] = dict(project_id=pid, reasons=[], rank=rank)
        evidence[pid]['reasons'].append(why)
        evidence[pid]['rank'] = min(evidence[pid]['rank'], rank)
    exact = set()
    for p in projects:
        if code and code == normalized_case(p.get('code')):
            exact.add(p['id']); add(p['id'], 'exact_full_case_code', 1)
        for alias in p.get('report_link_aliases', []):
            if alias.get('status') == 'reviewed' and code and code == normalized_case(alias.get('code')):
                exact.add(p['id']); add(p['id'], 'reviewed_alias:' + code, 2)
    if native_targets is None:
        native_targets = []
        refs = native_references(row)
        for ref in refs:
            key = identity(ref)
            found = [(p, r) for p in projects for r in [p.get('source_identity', {})] + p.get('source_records', [])
                     if key and (identity(r) == key or r.get('id') == '|'.join(key))]
            ids = {p['id'] for p, _ in found}
            if len(ids) != 1: unresolved_native = True
            else: native_targets.append(dict(identity=ref, project_id=next(iter(ids))))
    native = set()
    items = set()
    for target in native_targets:
        if not identity(target.get('identity', {})) or not any(p['id'] == target.get('project_id') for p in projects):
            unresolved_native = True; continue
        native.add(target['project_id']); add(target['project_id'], 'typed_native_identity', 0)
        if target.get('work_item_id'): items.add((target['project_id'], target['work_item_id']))
    candidates = tuple(sorted(evidence.values(), key=lambda c: (c['rank'], c['project_id'])))
    combined = native | exact
    if len(combined) > 1:
        return LinkDecision(None, None, 'ambiguous_reference', candidates)
    if unresolved_native:
        return LinkDecision(None, None, 'unresolved_reference', candidates)
    if len(combined) == 1:
        pid = next(iter(combined))
        item_ids = {item for parent, item in items if parent == pid}
        return LinkDecision(pid, LinkBasis.SOURCE.value if native else LinkBasis.CODE.value, None, candidates,
                            next(iter(item_ids)) if len(item_ids) == 1 else None)
    return LinkDecision(None, None, 'unresolved_reference' if code or native_targets or native_references(row) else 'missing_reference', candidates)


def can_review_links(user, project=None):
    from .business_policy import can_business_override
    return bool(user and user.get('active', True) and not user.get('manager_revoked') and
                (user.get('role') == 'manager' or can_business_override(user) or
                 project and user.get('id') == project.get('pm_id')))


def case_items(state, project_id):
    return [i for i in state.get('source_work_items', []) if i.get('project_id') == project_id and not i.get('source_missing')]


def reviewed_item(state, project_id, item_id):
    if not item_id: return None
    found = [i for i in case_items(state, project_id) if item_id in (i.get('id'), i.get('reviewed_item_key'))]
    return found[0]['id'] if len(found) == 1 else None


def linked_daily(row):
    return not row.get('source_missing') and row.get('case_mapping_status') == 'matched' and row.get('match_basis') in BASIS_LABELS


def link_summary(state, project_id=None):
    linked = [d for p in state.get('projects', []) if not project_id or p['id'] == project_id
              for d in p.get('daily_reports', []) if linked_daily(d)]
    unmatched = [d for d in state.get('daily_unmatched', []) if not d.get('source_missing')]
    unknown = [d for p in state.get('projects', []) if not project_id or p['id'] == project_id
               for d in p.get('daily_reports', []) if not linked_daily(d) and not d.get('source_missing')]
    departments = sorted({d.get('department') or '未知' for d in linked + unmatched + unknown})
    def count(rows, pending):
        dates = sorted(d['date'] for d in rows if d.get('date'))
        return dict(linked=len(rows), unlinked=len(pending), latest_date=dates[-1] if dates else None,
                    basis={b: sum(d.get('match_basis') == b for d in rows) for b in BASIS_LABELS})
    return dict(**count(linked, unmatched + unknown), total=len(linked + unmatched + unknown),
                unlinked_scope='workspace' if not project_id else 'visible_queue_not_attributed_to_case',
                reasons={r: sum(d.get('case_mapping_status', 'missing_reference') == r for d in unmatched) + (len(unknown) if r=='missing_reference' else 0) for r in REASONS},
                departments={dept: count([d for d in linked if (d.get('department') or '未知') == dept],
                                        [d for d in unmatched + unknown if (d.get('department') or '未知') == dept]) for dept in departments})
