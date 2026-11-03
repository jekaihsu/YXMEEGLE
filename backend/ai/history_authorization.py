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


def referenced_visibility(sessions, workspace_id, cfg, actor_id=None, extra=()):
    from .ledger import required_case_ids
    wanted = required_case_ids(sessions, workspace_id, actor_id) | set(extra)
    if not wanted:
        return set()
    with sessions() as db:
        root = db.get(WorkspaceRow, workspace_id)
        if root is None:
            raise HistoryDenied()
        state = storage.load_partial(db, BusinessRow, root, collections=('projects',), project_ids=wanted, project_details=False)
        normalize_environment(state, workspace_id, cfg)
        return {p['id'] for p in state['projects'] if visible_project(state,p)}


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
        if not rows:
            root = db.get(WorkspaceRow, workspace_id)
            if root is not None and root.data.get('storage_schema') != 2:
                state = storage.load_partial(db, BusinessRow, root, collections=('projects',), project_ids=wanted, project_details=False)
                normalize_environment(state, workspace_id, cfg)
                if wanted.issubset({p['id'] for p in state['projects'] if visible_project(state,p)}):
                    return
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
    values = [user.get('permission_version', user.get('authz_version', 0)), user.get('role'), sorted(user.get('capabilities', [])),
              user.get('active', True), user.get('company_admin_authorization')]
    return hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()
