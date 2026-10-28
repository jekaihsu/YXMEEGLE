"""Open the existing default checklist under the importer's case lock."""
from .catalog import digest
from .domain import NODE_MAP, require
from .enrollment_policy import ambiguous
from .service import authorize


def ensure_local(service, ctx):
    authorize(ctx, True)
    with service.sessions.begin() as db:
        ctx, state = service.lock(db, ctx)
        if any(t.template_family_id != 'manual' for t in service.tasks(db, ctx)):
            return {'state': 'already_started'}
        service.writable()
        require(not ambiguous(ctx.project), 'case_identity_unresolved', 409)
        require(service.position(db, ctx, service.facts(ctx))['stage'] != 'cancelled', 'no_stage', 409)
        version = service.default_version(db, ctx.wid)
        # The former case start sheet opened at sales and selected its default rows.
        normalized = service.normalize(ctx, {'template_version_id': version.id,
                                            'node_keys': list(NODE_MAP.values())}, service.rows(db, version))
        service._enroll_case(db, ctx, state, version, normalized, 'ensure-sop',
                             digest({'action': 'ensure-sop', 'template': version.id}))
        return {'state': 'started'}
