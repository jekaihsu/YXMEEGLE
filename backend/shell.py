"""GET /api/workspace?scope=shell: navigation, badges and project cards, no project trees (VCC-98)."""
import hashlib
import json
from datetime import date, timedelta
from sqlalchemy import select, func, and_, or_, case
from . import index_tables
from .index_reads import visibility, search, _binary
from .business_policy import can_business_override
from .case_cutover import project_execution_view
from .file_categories import categories
from .operations import delegation_valid
from .workspace_projection import filter_private_workspace

CLOSED=('completed','superseded')
ATTENTION_LIMIT=5  # Dashboard shows [...overdue, ...dueToday].slice(0,5)
PENDING_SHOWN=2


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


def etag(wid,user,version,today,users,index_generation=None):
    key=json.dumps([wid,user['id'],user.get('authz_version',0),user.get('role'),sorted(user.get('capabilities',[])),user.get('active',True),can_business_override(user),version,today,users,index_generation],sort_keys=True,default=str)
    return 'W/"shell-'+hashlib.sha256(key.encode()).hexdigest()[:32]+'"'


def open_late(ti,today):
    openq=ti.c.status.notin_(CLOSED)
    return openq,and_(openq,ti.c.due_date!='',ti.c.due_date<today)


def project_counts(db,ti,wid,today,ids=None):
    """{project_id: (open, overdue, blocked tasks)}; ids limits the scan to one page of projects."""
    openq,late=open_late(ti,today); where=[ti.c.workspace_id==wid]
    if ids is not None: where.append(ti.c.project_id.in_(ids))
    return {r.project_id:(r.active,r.late,r.blocked) for r in db.execute(select(ti.c.project_id,func.sum(case((openq,1),else_=0)).label('active'),
        func.sum(case((late,1),else_=0)).label('late'),
        func.sum(case((and_(openq,ti.c.status.in_(('paused','blocked'))),1),else_=0)).label('blocked')).where(*where).group_by(ti.c.project_id))}


def card(r,state,per_project,detail=False):
    """List-row view of one project_index row, shared by the shell and the paged overview."""
    summary=r['summary'] or {}; derived=summary.get('execution_status') or r['execution_status']  # full workspace shows the refreshed value (status mirrors it)
    active,overdue,blocked=per_project.get(r['project_id'],(0,0,0))
    card=dict(id=r['project_id'],code=r['code'],name=r['name'],client=r['client'],pm_id=r['pm_id'],status=derived,execution_status=derived,
              due_date=r['due_date'],case_type=r['case_type'],source_kind=r['source_kind'],
              source_status=r['source_status'],concurrency_version=r['concurrency_version'],
              progress=summary.get('progress') or dict(completed_nodes=r['nodes_completed'],approved_skipped_nodes=0,total_nodes=r['nodes_total']),
              overdue_tasks=overdue or 0,active_tasks=active or 0)
    view=project_execution_view(state,dict(case_visibility=r['case_visibility'],execution_system=r['execution_system']))
    view.pop('execution_system_label')  # the client derives it from execution_system
    card.update({k:v for k,v in view.items() if v is not None})
    if detail:
        facts=r['shell_facts']
        card.update(contract_amount=facts['contract_amount'],current_nodes=facts['current_nodes'],blocked_tasks=blocked or 0)
        if facts['source_lifecycle'] is not None: card['source_lifecycle']=facts['source_lifecycle']
    return card


def build(db,model,row,state,user,facts,today,approval_connection):
    wid=row.id; pi,ti,ci=index_tables.tables(model); env=state.get('environment','production')
    vis=visibility(pi,env)
    counters={r.key:r.value for r in db.execute(select(ci.c.key,ci.c.value).where(ci.c.workspace_id==wid,ci.c.subject_id==''))}
    rows=db.execute(select(pi).where(pi.c.workspace_id==wid,*vis).order_by(pi.c.ordinal,pi.c.project_id)).mappings().all()
    hidden=counters.get('projects_total',0)-len(rows) if vis else 0  # ready() has verified projects_total against the index
    pending=counters.get('approvals_pending',0); pending_items=[]
    if pending:  # one partial load serves the exact recount over visible cases (hidden ones must not count) and the rows the dashboard lists
        from . import storage
        visible={r for r in db.scalars(select(pi.c.project_id).where(pi.c.workspace_id==wid,*vis))} if hidden else None
        shown=[a for a in storage.load_partial(db,model,row,collections=('approvals',))['approvals'] if a.get('status')=='pending' and (visible is None or a.get('project_id') in visible)]
        pending=len(shown) if hidden else pending
        pending_items=[dict(id=a['id'],title=a.get('title',''),type=a.get('type',''),project_id=a['project_id']) for a in shown[:PENDING_SHOWN]]
    as_of=today if not rows or any(r['source_kind']=='lark' for r in rows) else state.get('as_of',today)  # the date the legacy dashboard measures lateness against
    openq,late=open_late(ti,as_of)
    per_project=project_counts(db,ti,wid,as_of)
    cards=[card(r,state,per_project) for r in rows]
    joined=ti.join(pi,and_(pi.c.workspace_id==ti.c.workspace_id,pi.c.project_id==ti.c.project_id))
    today_q=and_(openq,func.substr(ti.c.due_date,1,10)==as_of[:10])
    blocked_q=and_(openq,ti.c.status.in_(('paused','blocked')))
    # Legacy Dashboard: every open task of every visible case (not only the user's own); the 'my' numbers stay the nav badge.
    owned=mine(ti,user,facts); one=lambda cond:func.coalesce(func.sum(case((cond,1),else_=0)),0)
    allc=db.execute(select(one(openq),one(late),one(today_q),one(and_(openq,owned)),one(and_(late,owned)),one(blocked_q)).select_from(joined).where(ti.c.workspace_id==wid,*vis)).one()
    my_active,my_late=allc[3],allc[4]
    # [...overdue, ...dueToday] in workspace order: project, node, task ordinal
    task_rows=select(ti.c.task_id,ti.c.project_id,ti.c.node_id,ti.c.node_key,ti.c.node_name,ti.c.assignee_id,ti.c.status,ti.c.due_date,pi.c.code.label('project_code'),pi.c.name.label('project_name')).select_from(joined).where(ti.c.workspace_id==wid,*vis)
    attention=[dict(r._mapping) for r in db.execute(task_rows.where(or_(late,today_q))
        .order_by(case((late,0),else_=1),pi.c.ordinal,ti.c.node_ordinal,ti.c.ordinal,ti.c.task_id).limit(ATTENTION_LIMIT))]
    blocked=[dict(r._mapping) for r in db.execute(task_rows.where(blocked_q)
        .order_by(pi.c.ordinal,ti.c.node_ordinal,ti.c.ordinal,ti.c.task_id).limit(ATTENTION_LIMIT))] if allc[5] else []
    if attention or blocked:
        titles={r.entity_id:(r.data or {}).get('title') for r in db.execute(select(model.entity_id,model.data).where(model.workspace_id==wid,model.kind=='tasks',model.entity_id.in_(sorted({a['task_id'] for a in attention+blocked}))))}
        for a in attention+blocked: a['title']=titles.get(a['task_id'],'')
    return dict(scope='shell',version=row.version,as_of=as_of,workspace_id=wid,environment=env,users=state['users'],
                calendar=state.get('calendar'),source_status=state.get('source_status'),file_categories=categories(state),approval_connection=approval_connection,
                counts=dict(approvals_pending=pending,daily_unmatched=counters.get('daily_unmatched',0),my_overdue_tasks=int(my_late),my_active_tasks=int(my_active),
                            active_tasks=int(allc[0]),overdue_tasks=int(allc[1]),due_today_tasks=int(allc[2]),blocked_tasks=int(allc[5])),
                projects=cards,attention=attention,blocked=blocked,pending_approvals=pending_items,approvals=[],events=[])


TABS=('all','formal','intake','active','overdue','completed')
SORTS=('due','name','progress')


def overview_page(db,model,row,state,today,*,q='',status='',owner='',tab='formal',sort='due',desc=False,offset=0,limit=10):
    """One page of project cards for the case overview: filter, sort, count and slice in SQL.

    facets count the whole visible set so the tab badges do not move with the search box.
    """
    wid=row.id; pi,ti,_=index_tables.tables(model); vis=visibility(pi,state.get('environment','production'))
    base=[pi.c.workspace_id==wid,*vis]
    formal=pi.c.case_type!='intake'
    f=db.execute(select(func.count(),func.coalesce(func.sum(case((formal,1),else_=0)),0)).where(*base)).one()
    facets=dict(all=f[0],formal=int(f[1]),intake=f[0]-int(f[1]))
    _,late=open_late(ti,today)
    over=select(ti.c.project_id.label('pid')).where(ti.c.workspace_id==wid,late).group_by(ti.c.project_id).subquery()
    where=list(base)
    if status: where.append(pi.c.status==status)
    if owner: where.append(pi.c.pm_id==owner)
    if q: where.append(search(pi,q))
    where+={'formal':[formal],'intake':[~formal],'active':[pi.c.execution_status!='completed'],'completed':[pi.c.execution_status=='completed'],
            'overdue':[pi.c.project_id.in_(select(over.c.pid))]}.get(tab,[])
    total=db.scalar(select(func.count()).select_from(pi).where(*where))
    key={'name':pi.c.name,'progress':case((pi.c.nodes_total>0,pi.c.nodes_completed*1.0/pi.c.nodes_total),else_=0.0)}.get(sort)
    if key is None: key=_binary(case((pi.c.due_date=='','9999'),else_=pi.c.due_date),db)
    elif sort=='name': key=_binary(key,db)
    order=[(o.desc() if desc else o.asc()) for o in (key,_binary(pi.c.project_id,db))]
    rows=db.execute(select(pi).where(*where).order_by(*order).limit(limit).offset(offset)).mappings().all()
    counts=project_counts(db,ti,wid,today,[r['project_id'] for r in rows])
    return dict(total=total,offset=offset,limit=limit,facets=facets,items=[card(r,state,counts,detail=True) for r in rows])
