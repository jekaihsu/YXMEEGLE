"""Node authority shared by local node actions and imported task mutations."""
from ..business_policy import can_business_override
from ..node_assignment.domain import Actor, CHAIN, NodeKey
from .domain import require


def assistant_manages_node(ctx, key):
    # No authoritative assistant relationship exists in the roster yet.
    return False


def global_manager(ctx):
    user = ctx.user
    return user.get('active', True) and (user.get('role') == 'admin' or can_business_override(user)
        or (user.get('role') == 'manager' and not getattr(ctx, 'roster_required', False)
            and getattr(ctx, 'roster', None) is None)
        or user['id'] == ctx.project.get('pm_id')
        or user['id'] in ctx.project.get('sop_task_delegate_ids', [])
        or (ctx.project.get('case_type') == 'intake' and not ctx.project.get('pm_id')
            and 'sop_task_import' in user.get('capabilities', [])))


def can_manage_nodes(ctx, keys):
    if not ctx.user.get('active', True) or getattr(ctx, 'assigned_only', False):
        return False
    if global_manager(ctx):
        return True
    roster = getattr(ctx, 'roster', None)
    actor = Actor(roster.person(ctx.user['id']) if roster else None, ctx.user['id'])
    keys = tuple(keys)
    return bool(keys) and all(actor.manages(NodeKey(key)) or assistant_manages_node(ctx, key) for key in keys)


def require_nodes(ctx, keys):
    require(can_manage_nodes(ctx, keys), 'sop_import_forbidden', 403)


def manages_any_node(ctx):
    return global_manager(ctx) or any(can_manage_nodes(ctx, [key]) for key in CHAIN)
