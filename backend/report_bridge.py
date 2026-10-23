"""Local V4 to v3 case decisions. Snapshot candidates do not constitute owner review."""
from copy import deepcopy
from sqlalchemy import select
from .models import ReportCaseBridge
from .sources import normalized_case
from .workflow import now


def bridge_candidates(project, reports):
    found = {}
    refs = [(project.get('code'), 'code')] + [(q.get('quote_code'), 'quote_number') for q in project.get('quotes', [])]
    for raw, match in refs:
        code = normalized_case(raw)
        cases=reports.case_candidates(code) if code and hasattr(reports,'case_candidates') else [reports.case(code)] if code else []
        for case in cases:
            if case: found.setdefault(case['case_key'], {**case, 'match': match})
    return list(found.values())


def reconcile_bridges(state, reports):
    bridges = state.setdefault('report_case_bridges', {})
    if reports.data is None: return bridges
    for p in state.get('projects', []):
        candidates = bridge_candidates(p, reports)
        current = bridges.get(p['id'])
        if current and current['status'] in ('reviewed', 'rejected'): continue
        codes = [c['case_code'] for c in candidates]
        if current and current.get('candidates') == candidates: continue
        bridges[p['id']] = dict(project_id=p['id'], status='auto_exact' if len(candidates) == 1 else 'pending',
                               codes=codes if len(candidates) == 1 else [], actor_id='system:exact_rule',
                               reason='唯一完整案號或明確報價編號' if len(candidates) == 1 else '候選不唯一，需人工核對',
                               decided_at=now(), candidates=candidates, history=(current or {}).get('history', []))
    return bridges


def accepted_cases(project, reports, bridge=None):
    if not bridge or bridge.get('status') not in ('auto_exact', 'reviewed'): return []
    result = []
    for code in bridge.get('codes', []):
        case = reports.case(code)
        if case: result.append({**case, 'match': next((c['match'] for c in bridge.get('candidates', []) if c['case_code'] == code), 'code'),
                                'bridge_status': bridge['status']})
    return result


def load_bridges(db, wid):
    return {r.project_id: {k: deepcopy(getattr(r, k)) for k in ('project_id', 'status', 'codes', 'actor_id', 'reason', 'decided_at', 'candidates', 'history')}
            for r in db.scalars(select(ReportCaseBridge).where(ReportCaseBridge.workspace_id == wid))}


def save_bridges(db, wid, state):
    dialect=db.get_bind().dialect.name
    if dialect=='sqlite':
        from sqlalchemy.dialects.sqlite import insert
    else:
        from sqlalchemy.dialects.postgresql import insert
    for pid, data in state.get('report_case_bridges', {}).items():
        values={k:deepcopy(data[k]) for k in ('status','codes','actor_id','reason','decided_at','candidates','history')}
        db.execute(insert(ReportCaseBridge).values(workspace_id=wid,project_id=pid,**values).on_conflict_do_nothing(index_elements=['workspace_id','project_id']))
        row=db.get(ReportCaseBridge,(wid,pid),populate_existing=True,with_for_update=True)
        if data['status'] in ('auto_exact','pending') and row.status in ('reviewed','rejected'): continue
        for key,value in values.items():
            if getattr(row,key)!=value: setattr(row,key,value)
