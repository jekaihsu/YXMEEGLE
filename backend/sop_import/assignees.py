"""Small, privacy-preserving pages for assignment pickers."""
from ..node_assignment.domain import NODE_DEPARTMENTS, NodeKey
from .domain import require
from .authority import global_manager


def page(ctx, people_visible, *, node_key=None, scope=None, q=None, limit=None, cursor=None):
    from .service import authorize, can_manage, case_roles, CASE_ROLES
    authorize(ctx)
    if all(value is None for value in (node_key, scope, q, limit, cursor)):
        people = [(case_roles(u, ctx.project), u) for u in ctx.state.get('users', []) if u.get('active', True)]
        restricted = ctx.assigned_only or not (can_manage(ctx) or people_visible(ctx.user))
        if restricted:
            people = [(roles, u) for roles, u in people if u['id'] == ctx.user['id']]
        people.sort(key=lambda p: (CASE_ROLES.index(p[0][0]) if p[0] else len(CASE_ROLES), p[1].get('name') or '', p[1]['id']))
        return {'project_id': ctx.project['id'], 'restricted': restricted,
                'people': [{'id': u['id'], 'name': u.get('name'), 'case_roles': roles,
                            'department': u.get('department')} for roles, u in people]}
    scope = 'team' if scope is None else scope
    q = '' if q is None else q
    limit = 20 if limit is None else limit
    require(scope in {'team', 'all'} and isinstance(q, str) and len(q) <= 200, 'invalid_request')
    require(type(limit) is int and 1 <= limit <= 50, 'invalid_request')
    require(node_key is None or node_key in NODE_DEPARTMENTS, 'node_mapping_invalid')
    require(cursor is None or isinstance(cursor, str) and cursor.isascii() and cursor.isdigit() and len(cursor) <= 10,
            'invalid_request')
    offset = int(cursor or 0)
    roster = ctx.roster

    def teams(user):
        person = roster.person(user['id']) if roster else None
        return sorted(person.departments) if person else [user['department']] if user.get('department') else []

    target = set(NODE_DEPARTMENTS[NodeKey(node_key)]) if node_key else set(teams(ctx.user))
    restricted = ctx.assigned_only or not (global_manager(ctx) or people_visible(ctx.user))
    people = []
    for user in ctx.state.get('users', []):
        if not user.get('active', True) or restricted and user['id'] != ctx.user['id']:
            continue
        person = roster.person(user['id']) if roster else None
        if person and not person.employed:
            continue
        groups = teams(user)
        same_team = bool(target.intersection(groups))
        # A self-only reader keeps their existing self entry even outside the requested node's team.
        if not restricted and scope == 'team' and target and not same_team:
            continue
        if q.casefold().strip() not in (user.get('name') or '').casefold():
            continue
        roles = case_roles(user, ctx.project)
        people.append((not same_team, CASE_ROLES.index(roles[0]) if roles else len(CASE_ROLES),
                       user.get('name') or '', user['id'],
                       {'id': user['id'], 'name': user.get('name'), 'case_roles': roles,
                        'department': user.get('department'), 'teams': groups}))
    people.sort(key=lambda item: item[:4])
    return {'project_id': ctx.project['id'], 'restricted': restricted,
            'people': [item[4] for item in people[offset:offset + limit]],
            'next_cursor': str(offset + limit) if offset + limit < len(people) else None}
