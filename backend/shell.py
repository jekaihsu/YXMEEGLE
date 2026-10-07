"""GET /api/workspace?scope=shell: navigation, badges and project cards, no project trees (VCC-98)."""
import hashlib
import json
from datetime import date, timedelta
from sqlalchemy import select, func, and_, or_, case
from . import index_tables
from .index_reads import visibility
from .business_policy import can_business_override
from .case_cutover import project_execution_view
from .file_categories import categories
from .operations import delegation_valid
from .workspace_projection import filter_private_workspace

CLOSED=('completed','superseded')
ATTENTION_LIMIT=10


def delegated_task_ids(state,user,today):
    """Task ids user may act on through an active owner delegation (mirrors workflow.is_owner)."""
    active={u['id'] for u in state['users'] if u.get('active',True)}
    return {t for d in state.get('delegations',[]) if d['delegate_id']==user['id'] and d['principal_id'] in active and d['seat']=='owner'
            and d.get('scope')=='tasks' and d['start_date']<=today<=d['end_date'] and d['status']=='active' and delegation_valid(state,d,at_use=True)
            for t in d.get('task_ids',[])}


def prepare(state,user,today):
    """Authority facts needed by build(), taken before the privacy projection trims delegations; then project users."""
    facts=dict(active=[u['id'] for u in state['users'] if u.get('active',True)],delegated=delegated_task_ids(state,user,today),override=can_business_override(user))
    filter_private_workspace(state,user)
    return facts


def mine(ti,user,facts):
    """Condition selecting tasks whose can_execute is true for user (owner, valid delegate, or business override)."""
    if facts['override']: return ti.c.assignee_id.in_(facts['active'])
    return or_(and_(ti.c.assignee_id==user['id'],ti.c.assignee_id.in_(facts['active'])),ti.c.task_id.in_(sorted(facts['delegated']) or ['']))


def etag(wid,user,version,today,users):
    key=json.dumps([wid,user['id'],user.get('authz_version',0),user.get('role'),sorted(user.get('capabilities',[])),user.get('active',True),can_business_override(user),version,today,users],sort_keys=True,default=str)
    return 'W/"shell-'+hashlib.sha256(key.encode()).hexdigest()[:32]+'"'


def build(db,model,row,state,user,facts,today,approval_connection):
    wid=row.id; pi,ti,ci=index_tables.tables(model); env=state.get('environment','production')
    vis=visibility(pi,env)
    counters={r.key:r.value for r in db.execute(select(ci.c.key,ci.c.value).where(ci.c.workspace_id==wid,ci.c.subject_id==''))}
    hidden=db.scalar(select(func.count()).select_from(pi).where(pi.c.workspace_id==wid,~and_(*vis))) if vis else 0
    pending=counters.get('approvals_pending',0)
    if hidden:  # approvals of hidden cases must not be counted: recount exactly from the visible set
        from . import storage
        visible={r for r in db.scalars(select(pi.c.project_id).where(pi.c.workspace_id==wid,*vis))}
        pending=sum(a.get('status')=='pending' and a.get('project_id') in visible for a in storage.load_partial(db,model,row,collections=('approvals',))['approvals'])
    openq=ti.c.status.notin_(CLOSED); late=and_(openq,ti.c.due_date!='',ti.c.due_date<today)
    per_project={r.project_id:(r.active,r.late) for r in db.execute(select(ti.c.project_id,func.sum(case((openq,1),else_=0)).label('active'),
        func.sum(case((late,1),else_=0)).label('late')).where(ti.c.workspace_id==wid).group_by(ti.c.project_id))}
    joined=ti.join(pi,and_(pi.c.workspace_id==ti.c.workspace_id,pi.c.project_id==ti.c.project_id))
    owned=mine(ti,user,facts)
    my_active,my_late=db.execute(select(func.coalesce(func.sum(case((openq,1),else_=0)),0),func.coalesce(func.sum(case((late,1),else_=0)),0))
        .select_from(joined).where(ti.c.workspace_id==wid,owned,*vis)).one()
    tomorrow=(date.fromisoformat(today)+timedelta(days=1)).isoformat()
    attention=[dict(r._mapping) for r in db.execute(select(ti.c.task_id,ti.c.project_id,ti.c.node_key,ti.c.status,ti.c.due_date,pi.c.code.label('project_code'),pi.c.name.label('project_name'))
        .select_from(joined).where(ti.c.workspace_id==wid,owned,openq,ti.c.due_date!='',ti.c.due_date<tomorrow,*vis)
        .order_by(ti.c.due_date,ti.c.task_id).limit(ATTENTION_LIMIT))]
    if attention:
        titles={r.entity_id:(r.data or {}).get('title') for r in db.execute(select(model.entity_id,model.data).where(model.workspace_id==wid,model.kind=='tasks',model.entity_id.in_([a['task_id'] for a in attention])))}
        for a in attention: a['title']=titles.get(a['task_id'],'')
    cards=[]
    for r in db.execute(select(pi).where(pi.c.workspace_id==wid,*vis).order_by(pi.c.ordinal,pi.c.project_id)).mappings():
        summary=r['summary'] or {}; derived=summary.get('execution_status') or r['execution_status']  # full workspace shows the refreshed value (status mirrors it)
        active,overdue=per_project.get(r['project_id'],(0,0))
        card=dict(id=r['project_id'],code=r['code'],name=r['name'],client=r['client'],pm_id=r['pm_id'],status=derived,execution_status=derived,
                  due_date=r['due_date'],case_type=r['case_type'],source_kind=r['source_kind'],
                  source_status=r['source_status'],concurrency_version=r['concurrency_version'],
                  progress=summary.get('progress') or dict(completed_nodes=r['nodes_completed'],approved_skipped_nodes=0,total_nodes=r['nodes_total']),
                  overdue_tasks=overdue or 0,active_tasks=active or 0)
        view=project_execution_view(state,dict(case_visibility=r['case_visibility'],execution_system=r['execution_system']))
        view.pop('execution_system_label')  # the client derives it from execution_system
        card.update({k:v for k,v in view.items() if v is not None})
        cards.append(card)
    lark=any(c['source_kind']=='lark' for c in cards)
    return dict(scope='shell',version=row.version,as_of=today if not cards or lark else state.get('as_of',today),workspace_id=wid,environment=env,users=state['users'],
                calendar=state.get('calendar'),source_status=state.get('source_status'),file_categories=categories(state),approval_connection=approval_connection,
                counts=dict(approvals_pending=pending,daily_unmatched=counters.get('daily_unmatched',0),my_overdue_tasks=int(my_late),my_active_tasks=int(my_active)),
                projects=cards,attention=attention,approvals=[],events=[])
