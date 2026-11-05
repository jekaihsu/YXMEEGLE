"""Open the existing default checklist under the importer's case lock."""
from sqlalchemy import select
from ..models import BusinessRow
from .catalog import digest
from .domain import NODE_MAP, require
from .enrollment_policy import ambiguous
from .service import authorize
from .authority import require_nodes
from .models import CasePolicy


def startable_nodes(service, db, ctx):
    policy = db.get(CasePolicy, (ctx.wid, ctx.project['id']))
    if not policy or policy.policy != 'managed':
        return list(NODE_MAP.values())
    blocked = {node.data.get('key') for node in db.scalars(select(BusinessRow).where(
        BusinessRow.workspace_id == ctx.wid, BusinessRow.kind == 'nodes',
        BusinessRow.parent_id == ctx.project['id'])) if not service.node_enrollable(node.data)}
    return [key for key in NODE_MAP.values() if key in policy.node_keys and key not in blocked]


def ensure_local(service, ctx):
    authorize(ctx, True)
    with service.sessions.begin() as db:
        ctx, state = service.lock(db, ctx)
        require_nodes(ctx, NODE_MAP.values())
        if any(t.template_family_id != 'manual' for t in service.tasks(db, ctx)):
            return {'state': 'already_started'}
        keys = startable_nodes(service, db, ctx)
        if not keys:
            return {'state': 'not_ready', 'reason': 'no_startable_nodes'}
        service.writable()
        require(not ambiguous(ctx.project), 'case_identity_unresolved', 409)
        require(service.position(db, ctx, service.facts(ctx))['stage'] != 'cancelled', 'no_stage', 409)
        version = service.default_version(db, ctx.wid)
        # The former case start sheet opened at sales and selected its default rows.
        normalized = service.normalize(ctx, {'template_version_id': version.id,
                                            'node_keys': keys}, service.rows(db, version))
        service._enroll_case(db, ctx, state, version, normalized, 'ensure-sop',
                             digest({'action': 'ensure-sop', 'template': version.id}))
        return {'state': 'started'}
