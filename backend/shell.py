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


def etag(wid,user,version,today,users):
    key=json.dumps([wid,user['id'],user.get('authz_version',0),user.get('role'),sorted(user.get('capabilities',[])),user.get('active',True),can_business_override(user),version,today,users],sort_keys=True,default=str)
    return 'W/"shell-'+hashlib.sha256(key.encode()).hexdigest()[:32]+'"'


def home_population(db,model,row,state,user,facts,cards,as_of):
    """Compute personal counts and preview details from canonical source facts."""
    from . import storage
    from .home_details import build_home_task
    visible={p['id']:p for p in cards}
    empty=dict(active=0,overdue=0,due_today=0,attention=[],waiting=[],waiting_counts={})
    if not visible:return empty
    _,ti,_=index_tables.tables(model)
    selected=list(db.scalars(select(ti.c.project_id).where(ti.c.workspace_id==row.id,ti.c.project_id.in_(list(visible)),
        or_(ti.c.assignee_id==user['id'],ti.c.task_id.in_(sorted(facts['delegated']) or ['']))).distinct()))
    if not selected:return empty
    loaded=storage.load_partial(db,model,row,project_ids=selected,project_children=('evidence','delivery_batches'))
    # Batch authority collections and scoped task audit events in one read.
    # Events never leave the server; only canonical assigned-task facts do.
    collections=('users','delegations','approved_leave_delegations','approvals')
    authority={key:[] for key in (*collections,'events')}
    if row.data.get('storage_schema')==2:
        scoped_events=and_(model.kind=='events',model.data['project_id'].as_string().in_(selected),
                          model.data['action'].as_string().in_(['task_pause_for_change','task_return']))
        records=db.execute(select(model.kind,model.data).where(model.workspace_id==row.id,
            or_(and_(model.kind.in_(collections),model.parent_id==''),scoped_events)).order_by(model.ordinal))
        for kind,data in records:authority[kind].append(data)
    else:
        authority.update({key:row.data.get(key,[]) for key in collections})
        authority['events']=[event for event in row.data.get('events',[]) if event.get('project_id') in selected
                             and event.get('action') in ('task_pause_for_change','task_return')]
    full={**state,**authority,'projects':loaded['projects']}
    actor=next((person for person in full['users'] if person.get('id')==user['id'] and person.get('active',True)),None)
    active=overdue=due_today=0; attention=[]; waiting=[]; waiting_counts={}; per_kind={}
    for p in loaded['projects']:
        p['execution_status']=visible[p['id']]['execution_status']
        for n in p.get('nodes',[]):
            for t in n.get('tasks',[]):
                if t['status'] in CLOSED:continue
                home=build_home_task(full,p,n,t,actor,as_of)
                if not home['assigned']:continue
                detail=home['detail']
                if detail['actionable']:
                    active+=1; due=str(t.get('due_date') or '')[:10]
                    if due and due<as_of[:10]:overdue+=1
                    if due==as_of[:10]:due_today+=1
                    if due and due<=as_of[:10]:attention.append(dict(task_id=t['id'],project_id=p['id'],node_id=n['id'],node_key=n.get('key') or '',
                        node_name=n.get('name') or '',assignee_id=t.get('owner_id') or '',status=t['status'],due_date=t.get('due_date') or '',
                        project_code=p['code'],project_name=p.get('name') or '',title=t.get('title') or '',detail=preview_facts(detail)))
                kind=detail['kind']
                if kind:
                    waiting_counts[kind]=waiting_counts.get(kind,0)+1
                    if per_kind.get(kind,0)<5:
                        per_kind[kind]=per_kind.get(kind,0)+1
                        waiting.append(dict(task_id=t['id'],project_id=p['id'],project_code=p['code'],node_id=n['id'],title=t.get('title') or '未命名任務',
                            kind=kind,reason=detail['reason'],detail=preview_facts(detail)))
    attention.sort(key=lambda t:0 if t['due_date'][:10]<as_of[:10] else 1)
    return dict(active=active,overdue=overdue,due_today=due_today,attention=attention[:ATTENTION_LIMIT],waiting=waiting,waiting_counts=waiting_counts)


def preview_facts(detail):
    """Identity/title live once in the preview row; null optional facts are absent."""
    return {key:value for key,value in detail.items() if key not in
            ('task_id','project_id','project_code','node_id','title') and value is not None}


def open_late(ti,today):
    openq=ti.c.status.notin_(CLOSED)
    return openq,and_(openq,ti.c.due_date!='',ti.c.due_date<today)


def project_counts(db,ti,wid,today,ids=None):
    """{project_id: (open tasks, overdue tasks)}; ids limits the scan to one page of projects."""
    openq,late=open_late(ti,today); where=[ti.c.workspace_id==wid]
    if ids is not None: where.append(ti.c.project_id.in_(ids))
    return {r.project_id:(r.active,r.late) for r in db.execute(select(ti.c.project_id,func.sum(case((openq,1),else_=0)).label('active'),
        func.sum(case((late,1),else_=0)).label('late')).where(*where).group_by(ti.c.project_id))}


def card(r,state,per_project):
    """List-row view of one project_index row, shared by the shell and the paged overview."""
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
    openq,_=open_late(ti,as_of)
    per_project=project_counts(db,ti,wid,as_of)
    cards=[card(r,state,per_project) for r in rows]
    joined=ti.join(pi,and_(pi.c.workspace_id==ti.c.workspace_id,pi.c.project_id==ti.c.project_id))
    one=lambda cond:func.coalesce(func.sum(case((cond,1),else_=0)),0)
    # All-case active total remains a portfolio measure. Personal counts use the
    # full readiness facts needed to distinguish assigned from actionable now.
    allc=db.execute(select(one(openq)).select_from(joined).where(ti.c.workspace_id==wid,*vis)).one()
    home=home_population(db,model,row,state,user,facts,cards,as_of)
    return dict(scope='shell',version=row.version,as_of=as_of,workspace_id=wid,environment=env,users=state['users'],
                calendar=state.get('calendar'),source_status=state.get('source_status'),file_categories=categories(state),approval_connection=approval_connection,
                counts=dict(approvals_pending=pending,daily_unmatched=counters.get('daily_unmatched',0),my_overdue_tasks=home['overdue'],my_active_tasks=home['active'],
                            active_tasks=int(allc[0]),overdue_tasks=home['overdue'],due_today_tasks=home['due_today']),
                projects=[{k:v for k,v in card.items() if k!='execution_status'} for card in cards],attention=home['attention'],home_waiting=home['waiting'],home_waiting_counts=home['waiting_counts'],pending_approvals=pending_items,approvals=[],events=[])


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
    return dict(total=total,offset=offset,limit=limit,facets=facets,items=[card(r,state,counts) for r in rows])
