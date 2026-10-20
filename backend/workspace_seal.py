"""Server-owned workspace normalization shared by runtime and inspection tools."""
from copy import deepcopy
from . import storage
from sqlalchemy import select, func, or_
from .models import BusinessRow, PersonRow
from .workflow import require
from .features import resolve_features
from .production_access import test_profile, set_company_admin_authority


def seal(db,row,state,cfg,*,scoped=False):
    """What every load adds to a stored state. A scoped load holds only part of the projects, so it checks the rest in SQL."""
    from .workspace_environment import normalize_environment
    from .case_cutover import initialize_execution_system,SYSTEMS,isolated
    normalize_environment(state,row.id,cfg)
    state['features']=resolve_features(cfg)
    if state.get('environment')=='production':
        if scoped: demo_rows=db.scalar(select(func.count()).select_from(BusinessRow).where(BusinessRow.workspace_id==row.id,BusinessRow.kind=='projects',BusinessRow.data['source_kind'].as_string().in_(('demo','mock','simulation'))))
        else: demo_rows=sum(p.get('source_kind') in ('demo','mock','simulation') for p in state.get('projects',[]))
        require(not demo_rows,'正式工作區包含隔離示範資料，請由管理員核對',409)
    if scoped and not isolated(state):
        # The full load would classify these cases (and record an event); only the full path may.
        unclassified=BusinessRow.data['execution_system'].as_string()
        if db.scalar(select(func.count()).select_from(BusinessRow).where(BusinessRow.workspace_id==row.id,BusinessRow.kind=='projects',or_(unclassified.is_(None),unclassified.notin_(SYSTEMS)))):
            raise storage.PartialUnavailable('cases without an execution system')
    initialize_execution_system(state)
    if row.id.startswith(('lark-','test-lark-')):
        org=row.id.removeprefix('test-')
        profiles={r.person_id:deepcopy(r.data) for r in db.scalars(select(PersonRow).where(PersonRow.organization_id==org))}
        if row.id.startswith('test-'):
            overlays={r.person_id:r.data for r in db.scalars(select(PersonRow).where(PersonRow.organization_id==row.id))}
            profiles={ident:test_profile(person,overlays.get(ident)) for ident,person in profiles.items()}
            profiles.update({ident:deepcopy(person) for ident,person in overlays.items() if ident not in profiles})
        known={u['id'] for u in state['users']}
        state['users']=[profiles.get(u['id'],u) for u in state['users']]+[p for ident,p in profiles.items() if ident not in known]
    state['native_approval_authority']={'app_id':cfg.get('LARK_APP_ID'),'tenant':cfg.get('LARK_WORKER_ORGANIZATION')}
    set_company_admin_authority(state,cfg)
    return state
