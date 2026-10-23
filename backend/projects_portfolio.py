"""Read-only portfolio projection. No remote reads, task bodies, or financial fields."""
from sqlalchemy import select
from . import index_tables
from .index_reads import visibility
from .shell import card, project_counts
from .sop_import.models import CasePolicy, LocalTask


def portfolio(db, model, row, state, today):
    pi, ti, _ = index_tables.tables(model)
    rows = db.execute(select(pi).where(pi.c.workspace_id == row.id,
        *visibility(pi, state.get('environment', 'production'))).order_by(pi.c.ordinal)).mappings().all()
    ids = {r['project_id'] for r in rows}
    counts = project_counts(db, ti, row.id, today)
    policies = dict(db.execute(select(CasePolicy.project_id, CasePolicy.policy)
        .where(CasePolicy.workspace_id == row.id)).all())
    imported = set(db.scalars(select(LocalTask.project_id).where(LocalTask.workspace_id == row.id,
        LocalTask.imported_version_id.is_not(None)).distinct()))
    headers, nodes = {}, {}
    if row.data.get('storage_schema') == 2:
        records = db.execute(select(model.kind, model.entity_id, model.parent_id, model.data)
            .where(model.workspace_id == row.id, model.kind.in_(('projects', 'nodes'))).order_by(model.ordinal))
        for kind, ident, parent, data in records:
            if kind == 'projects' and ident in ids:
                headers[ident] = data
            elif kind == 'nodes' and parent in ids:
                nodes.setdefault(parent, []).append(data)
    else:
        for p in row.data.get('projects', []):
            if p['id'] in ids:
                headers[p['id']] = p
                nodes[p['id']] = p.get('nodes', [])
    items = []
    for r in rows:
        p = headers.get(r['project_id'], {})
        item = card(r, state, counts)
        item.update({key: p.get(key) for key in ('created_at', 'source_lifecycle', 'parent_code', 'owner_id', 'collaborator_ids')})
        derived = {n['id']: n for n in (r['summary'] or {}).get('nodes', [])}
        item['portfolio_nodes'] = [dict(key=n.get('key'), status=derived.get(n.get('id'), n).get('status'),
            owner_id=n.get('owner_id'), collaborator_ids=n.get('collaborator_ids', [])) for n in nodes.get(r['project_id'], [])]
        item['sop_summary'] = dict(policy=policies.get(r['project_id']), imported_tasks=r['project_id'] in imported)
        items.append(item)
    return dict(items=items, total=len(items), as_of=today, basis='persisted_workspace')
