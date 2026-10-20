"""The merged 報價總表 register: one entry per 報價編號, built from cached source rows and visible cases.

Pure. The caller supplies a state already narrowed to what the viewer may see and decides whether amounts show.
"""
from collections import defaultdict
from dataclasses import asdict

from ..sources import normalized_case, number, text
from .case_stage import Stage, stage
from .quote_facts import collect, live

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
    result = {'origin': 'source', 'quote_no': quote_no, 'engineering_no': facts.engineering_no or None,
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


def groups(state):
    found = defaultdict(list)
    for row in state.get('source_quotes') or []:
        quote_no = normalized_case((row.get('fields') or {}).get('報價編號'))
        if quote_no and live(row):
            found[quote_no].append(row)
    return {k: sorted(v, key=lambda r: str(r.get('id'))) for k, v in found.items()}


def register(state, *, today, amounts):
    projects = {p['id']: p for p in state.get('projects', [])}
    entries = [entry(k, rows, projects, today=today, amounts=amounts) for k, rows in groups(state).items()]
    return sorted(entries, key=lambda e: e['quote_no'], reverse=True)


def matches(item, q):
    return q.casefold() in ' '.join(item.get(k) or '' for k in ('quote_no', 'name', 'client')).casefold()
