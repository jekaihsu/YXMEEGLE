"""Compact portfolio with read-only, cached node-assignment status overlays."""
from sqlalchemy import select
from . import index_tables, storage
from .index_reads import visibility
from .shell import card, project_counts
from .sop_import.models import CasePolicy, LocalTask


def portfolio(db, model, row, state, today, *, assignments, data, user):
    pi, ti, _ = index_tables.tables(model)
    rows = db.execute(select(pi).where(pi.c.workspace_id == row.id,
        *visibility(pi, state.get('environment', 'production'))).order_by(pi.c.ordinal)).mappings().all()
    ids = {r['project_id'] for r in rows}
    counts = project_counts(db, ti, row.id, today)
    policies = dict(db.execute(select(CasePolicy.project_id, CasePolicy.policy)
        .where(CasePolicy.workspace_id == row.id)).all())
    imported = set(db.scalars(select(LocalTask.project_id).where(LocalTask.workspace_id == row.id,
        LocalTask.imported_version_id.is_not(None)).distinct()))
    overlay_enabled = bool(ids) and not assignments.assignment_unavailable(state, data)
    headers, nodes, daily = {}, {}, {}
    if row.data.get('storage_schema') == 2:
        records = db.execute(select(model.kind, model.entity_id, model.parent_id, model.data)
            .where(model.workspace_id == row.id, model.kind.in_(('projects', 'nodes', 'project_daily_reports')
                if overlay_enabled else ('projects', 'nodes'))).order_by(model.ordinal))
        for kind, ident, parent, stored in records:
            if kind == 'projects':
                headers[ident] = stored
            elif kind == 'nodes' and parent in ids:
                nodes.setdefault(parent, []).append(stored)
            elif kind == 'project_daily_reports' and parent in ids:
                daily.setdefault(parent, []).append(stored)
    else:
        for p in row.data.get('projects', []):
            headers[p['id']] = p
            if p['id'] in ids:
                nodes[p['id']] = p.get('nodes', [])
                daily[p['id']] = p.get('daily_reports', [])
    statuses = {}
    if overlay_enabled:
        evidence = storage.load_partial(db, model, row,
            collections=('source_confirmations', 'contract_items', 'source_work_items'))
        assignment_state = dict(state, **{key: evidence[key] for key in
            ('source_confirmations', 'contract_items', 'source_work_items')})
        assignment_state['projects'] = [dict(p, nodes=nodes.get(pid, []), daily_reports=daily.get(pid, []))
                                        for pid, p in headers.items()]
        statuses = {pid: chain for pid, chain in assignments.portfolio_statuses(assignment_state, data, user).items() if pid in ids}
    items = []
    for r in rows:
        p = headers.get(r['project_id'], {})
        item = card(r, state, counts)
        item.update({key: p.get(key) for key in ('created_at', 'source_lifecycle', 'parent_code', 'owner_id', 'collaborator_ids')})
        derived = {n['id']: n for n in (r['summary'] or {}).get('nodes', [])}
        chain = statuses.get(r['project_id'], {})
        item['portfolio_nodes'] = [dict(key=n.get('key'), status=chain.get(n.get('key'), derived.get(n.get('id'), n).get('status')),
            status_source='lark_derived' if n.get('key') in chain else 'persisted',
            owner_id=n.get('owner_id'), collaborator_ids=n.get('collaborator_ids', [])) for n in nodes.get(r['project_id'], [])]
        item['sop_summary'] = dict(policy=policies.get(r['project_id']), imported_tasks=r['project_id'] in imported)
        items.append(item)
    return dict(items=items, total=len(items), as_of=today,
                basis='persisted_workspace+lark_derived' if statuses else 'persisted_workspace')
