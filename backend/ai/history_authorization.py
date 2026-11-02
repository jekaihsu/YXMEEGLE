"""Fresh case visibility for retained answers; never a context-cache lookup."""
from fastapi import HTTPException
from .. import storage
from ..models import BusinessRow, WorkspaceRow
from ..source_case_policy import visible_project
from ..workspace_environment import normalize_environment


class HistoryDenied(HTTPException):
    def __init__(self):
        super().__init__(403, '找不到或沒有權限查看這個案件')


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


def require_case(sessions, workspace_id, project_id, cfg):
    if project_id not in visible_cases(sessions, workspace_id, cfg):
        raise HistoryDenied()
