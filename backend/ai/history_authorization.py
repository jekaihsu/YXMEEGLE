"""Fresh case visibility for retained answers; never a context-cache lookup."""
from fastapi import HTTPException
from .. import storage
from ..models import BusinessRow, WorkspaceRow
from ..source_case_policy import visible_project
from ..workspace_environment import normalize_environment


class HistoryDenied(HTTPException):
    def __init__(self, *, conversation_only=False):
        self.conversation_only = conversation_only
        super().__init__(403, '找不到或沒有權限查看這個案件')


def stream_error(exc):
    code = 'session_expired' if exc.status_code == 401 else 'ai_forbidden' if exc.status_code in (403, 404) else 'ai_upstream'
    return dict(type='error', code=code, **({'denial_scope':'conversation'}
        if code == 'ai_forbidden' and getattr(exc, 'conversation_only', False) else {}))


def visible_cases(sessions, workspace_id, cfg):
    # Only headers and policy metadata are needed. Load once for the entire page,
    # before the ledger's bounded, single-statement history query.
    with sessions() as db:
        row = db.get(WorkspaceRow, workspace_id)
        if row is None:
            raise HistoryDenied()
        state = storage.load_partial(db, BusinessRow, row, collections=('projects',), project_details=False)
        normalize_environment(state, workspace_id, cfg)
        return {p['id'] for p in state.get('projects', []) if visible_project(state, p)}


def require_cases(sessions, workspace_id, project_ids, cfg):
    """One authoritative, indexed header lookup; no whole-workspace decoding.

    BusinessRow's composite primary key is current even when the derived project
    index is disabled or behind. Only the requested cases are read.
    """
    from sqlalchemy import select
    wanted = set(project_ids)
    if not wanted:
        return
    with sessions() as db:
        rows = db.execute(select(BusinessRow.data, WorkspaceRow.data['environment'].as_string()).join(
            WorkspaceRow, WorkspaceRow.id == BusinessRow.workspace_id).where(
            BusinessRow.workspace_id == workspace_id, BusinessRow.kind == 'projects',
            BusinessRow.entity_id.in_(wanted))).all()
        visible = set()
        for project, environment in rows:
            state = normalize_environment({'environment': environment}, workspace_id, cfg)
            if visible_project(state, project):
                visible.add(project['id'])
        if not wanted.issubset(visible):
            raise HistoryDenied()


def require_case(sessions, workspace_id, project_id, cfg):
    require_cases(sessions, workspace_id, {project_id}, cfg)


def permission_key(user):
    import hashlib
    import json
    values = [user.get('authz_version', 0), user.get('role'), sorted(user.get('capabilities', [])),
              user.get('active', True), user.get('company_admin_authorization')]
    return hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()


def permission_keys(sessions, workspace_id):
    from ..models import PersonRow
    from sqlalchemy import select
    with sessions() as db:
        root = db.get(WorkspaceRow, workspace_id)
        state = storage.load_partial(db, BusinessRow, root, collections=('users',), project_details=False)
        users = {u['id']:u for u in state['users']}
        if workspace_id.startswith(('lark-', 'test-lark-')):
            org = workspace_id.removeprefix('test-')
            users.update({p.person_id:p.data for p in db.scalars(select(PersonRow).where(PersonRow.organization_id == org))})
        return {ident:permission_key(u) for ident, u in users.items() if u.get('active', True)}


def resolve_case_codes(sessions, workspace_id, codes):
    """Resolve trusted report-row codes against server records; ambiguity is conservative."""
    from ..sources import normalized_case
    from sqlalchemy import select
    wanted = {normalized_case(code) for code in codes}
    found = set()
    projects = set()
    with sessions() as db:
        headers = db.scalars(select(BusinessRow.data).where(BusinessRow.workspace_id == workspace_id,
            BusinessRow.kind == 'projects'))
        for project in headers:
            matches = wanted & {normalized_case(code) for code in
                [project.get('code'), *project.get('code_history', [])] if code}
            if matches:
                found.update(matches)
                projects.add(project['id'])
    return projects, found == wanted
