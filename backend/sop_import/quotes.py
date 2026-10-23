"""The merged 報價總表 register: one entry per 報價編號, built from cached source rows and visible cases.

Pure. The caller supplies a state already narrowed to what the viewer may see, plus the local planning cases the
viewer may see under `local_cases`, and decides whether amounts show.
"""
from collections import defaultdict
from dataclasses import asdict

from ..sources import normalized_case, number, text
from .case_stage import Stage, stage
from .quote_facts import case_facts, collect, live

STAGES = frozenset(s.value for s in Stage)


def names(rows, field):
    found = []
    for f in rows:
        value = f.get(field)
        for item in value if isinstance(value, list) else [value]:
            name = (item.get('name') if isinstance(item, dict) else text(item)) or ''
            if name.strip() and name.strip() not in found:
                found.append(name.strip())
    return found


def entry(quote_no, rows, projects, *, today, amounts, detail=False):
    fields = [r.get('fields') or {} for r in rows]
    linked = sorted({pid for r in rows for pid in [r.get('project_id'), *(r.get('project_ids') or [])] if pid in projects},
                    key=lambda pid: (projects[pid].get('case_type') == 'intake', pid))
    records = [rec for pid in linked for rec in projects[pid].get('source_records') or [] if live(rec)]
    facts = collect(fields, today=today, v4_confirmation=any(rec.get('kind') == 'confirmation' for rec in records))
    amount = next((value for f in fields if (value := number(f.get('契約價格(未稅)'))) is not None), None)
    result = {'origin': 'source', 'quote_no': quote_no, 'local_reference': None, 'engineering_no': facts.engineering_no or None,
              'name': facts.project_name or None, 'client': facts.client or None,
              'quoted_on': facts.quoted_date or None, 'quote_deadline': facts.quote_deadline or None,
              'contract_amount': amount if amounts else None, 'amount_restricted': not amounts,
              'quote_owners': names(fields, '報價負責人'), 'pm_names': names(fields, '案件負責人'),
              'pm_id': (projects[linked[0]].get('pm_id') or None) if linked else None,
              'status': next((s for f in fields if (s := text(f.get('狀態')).strip())), None),
              'stage_label': facts.stage_label or None, 'stage': stage(facts).value,
              'project_id': linked[0] if linked else None, 'project_ids': linked,
              'source_rows': len(rows), 'duplicated': facts.duplicated}
    if detail:
        result.update(facts={k: list(v) if isinstance(v, tuple) else v for k, v in asdict(facts).items()},
                      records=[{'id': r.get('id'), 'source_url': r.get('source_url')} for r in rows])
    return result


def local_entry(project, *, today, amounts, detail=False):
    facts = case_facts(project, {}, today)
    result = {'origin': 'local', 'quote_no': project.get('official_quote_no'), 'local_reference': project['local_reference'],
              'engineering_no': None, 'name': project.get('name') or None, 'client': project.get('client') or None,
              'quoted_on': None, 'quote_deadline': None, 'contract_amount': None, 'amount_restricted': not amounts,
              'quote_owners': [], 'pm_names': [], 'pm_id': project.get('pm_id') or None, 'status': None,
              'stage_label': None, 'stage': stage(facts).value, 'project_id': project['id'], 'project_ids': [project['id']],
              'source_rows': 0, 'duplicated': False}
    if detail:
        result.update(facts={k: list(v) if isinstance(v, tuple) else v for k, v in asdict(facts).items()}, records=[])
    return result


def groups(state):
    found = defaultdict(list)
    for row in state.get('source_quotes') or []:
        quote_no = normalized_case((row.get('fields') or {}).get('報價編號'))
        if quote_no and live(row):
            found[quote_no].append(row)
    return {k: sorted(v, key=lambda r: str(r.get('id'))) for k, v in found.items()}


def register(state, *, today, amounts):
    projects = {p['id']: p for p in state.get('projects', [])}
    local = sorted(state.get('local_cases', []), key=lambda p: (p.get('created_at') or '', p['id']), reverse=True)
    entries = [entry(k, rows, projects, today=today, amounts=amounts) for k, rows in groups(state).items()]
    return ([local_entry(p, today=today, amounts=amounts) for p in local]
            + sorted(entries, key=lambda e: e['quote_no'], reverse=True))


def find(state, quote_no, *, today, amounts):
    rows = groups(state).get(quote_no)
    if rows:
        projects = {p['id']: p for p in state.get('projects', [])}
        return entry(quote_no, rows, projects, today=today, amounts=amounts, detail=True)
    project = next((p for p in state.get('local_cases', []) if quote_no in (p.get('local_reference'), p.get('official_quote_no'))), None)
    return local_entry(project, today=today, amounts=amounts, detail=True) if project else None


def matches(item, q):
    return q.casefold() in ' '.join(item.get(k) or '' for k in ('quote_no', 'local_reference', 'name', 'client')).casefold()
