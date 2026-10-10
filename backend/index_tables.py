"""Derived, queryable copies of project cards, tasks and counts (VCC-97).

business_records stays the only source of truth. Rows here are rebuilt from a
workspace state dict, so a from-scratch rebuild and incremental maintenance share
one code path. Core statements only: valid on SQLite and PostgreSQL.
"""
from copy import deepcopy
from sqlalchemy import select, delete, insert

CLOSED_TASK_STATUSES=('completed','approved_skipped')
CHUNK=400


def tables(model):
    t=model.metadata.tables
    return t['project_index'],t['task_index'],t['workspace_counters']


def project_summary_json(state,project):
    """Today's project_summary on a copy (it refreshes derived state in place); None if it cannot be computed."""
    from .operations import project_summary
    try: return project_summary(state,deepcopy(project))
    except Exception: return None


def project_rows(wid,state,project_ids=None,summaries=True):
    """(project rows, task rows) for the selected projects of a full state."""
    wanted=None if project_ids is None else set(project_ids)
    projects,tasks=[],[]
    for i,p in enumerate(state.get('projects',[])):
        if wanted is not None and p['id'] not in wanted: continue
        nodes=p.get('nodes',[]); task_total=task_done=0
        for ni,n in enumerate(nodes):
            for ti,t in enumerate(n.get('tasks',[])):
                task_total+=1; task_done+=t.get('status')=='completed'
                tasks.append(dict(workspace_id=wid,task_id=t['id'],project_id=p['id'],node_id=n['id'],node_key=n.get('key') or '',node_name=n.get('name') or '',
                                  node_ordinal=ni,ordinal=ti,assignee_id=t.get('owner_id') or n.get('owner_id') or '',
                                  status=t.get('status') or '',due_date=t.get('due_date') or '',required=bool(t.get('required',True))))
        projects.append(dict(workspace_id=wid,project_id=p['id'],ordinal=i,code=p.get('code') or '',name=p.get('name') or '',client=p.get('client') or '',
                             pm_id=p.get('pm_id') or '',admin_id=p.get('admin_id') or '',supervisor_id=p.get('supervisor_id') or '',
                             status=p.get('status') or '',execution_status=p.get('execution_status') or '',priority=p.get('priority') or '',
                             case_type=p.get('case_type') or '',case_visibility=p.get('case_visibility') or '',source_kind=p.get('source_kind') or '',
                             source_status=p.get('source_status') or '',execution_system=p.get('execution_system') or '',due_date=p.get('due_date') or '',
                             created_at=p.get('created_at') or '',concurrency_version=p.get('concurrency_version',0),
                             nodes_total=len(nodes),nodes_completed=sum(n.get('status')=='completed' for n in nodes),
                             tasks_total=task_total,tasks_completed=task_done,summary=project_summary_json(state,p) if summaries else None,source_version=state.get('version',0)))
    return projects,tasks


def counter_values(state):
    """{(key, subject_id): value}; time-dependent counts (overdue) are never stored."""
    values={('projects_total',''):len(state.get('projects',[])),
            ('approvals_pending',''):sum(a.get('status')=='pending' for a in state.get('approvals',[])),
            ('daily_unmatched',''):len(state.get('daily_unmatched',[]))}
    for p in state.get('projects',[]):
        for n in p.get('nodes',[]):
            for t in n.get('tasks',[]):
                if t.get('status') not in CLOSED_TASK_STATUSES:
                    owner=t.get('owner_id') or n.get('owner_id') or ''
                    values[('tasks_open',owner)]=values.get(('tasks_open',owner),0)+1
    return values


def _chunks(items):
    items=list(items)
    for i in range(0,len(items),CHUNK): yield items[i:i+CHUNK]


def replace_projects(db,model,wid,state,project_ids):
    """Drop and rewrite index rows of the given projects (absent ones are just removed)."""
    ids=list(project_ids)
    if not ids: return
    pi,ti,_=tables(model)
    for part in _chunks(ids):
        db.execute(delete(ti).where(ti.c.workspace_id==wid,ti.c.project_id.in_(part)))
        db.execute(delete(pi).where(pi.c.workspace_id==wid,pi.c.project_id.in_(part)))
    projects,tasks=project_rows(wid,state,ids)
    if projects: db.execute(insert(pi),projects)
    if tasks: db.execute(insert(ti),tasks)


def replace_counters(db,model,wid,state):
    """Write only counters whose value or version differs; delete vanished ones."""
    *_,ci=tables(model)
    desired=counter_values(state); version=state.get('version',0)
    existing={(r.key,r.subject_id):r for r in db.execute(select(ci).where(ci.c.workspace_id==wid))}
    for key,row in existing.items():
        if key not in desired:
            db.execute(delete(ci).where(ci.c.workspace_id==wid,ci.c.key==key[0],ci.c.subject_id==key[1]))
        elif row.value!=desired[key] or row.source_version!=version:
            db.execute(ci.update().where(ci.c.workspace_id==wid,ci.c.key==key[0],ci.c.subject_id==key[1]).values(value=desired[key],source_version=version))
    fresh=[dict(workspace_id=wid,key=k,subject_id=s,value=v,source_version=version) for (k,s),v in desired.items() if (k,s) not in existing]
    if fresh: db.execute(insert(ci),fresh)


def _mismatch(rows,expected,key,ignore=('source_version',)):
    """Compare actual vs expected row dicts keyed by `key`: (missing, extra, stale) key lists."""
    strip=lambda row:{k:v for k,v in row.items() if k not in ignore}
    missing=sorted(k for k in expected if k not in rows)
    extra=sorted(k for k in rows if k not in expected)
    stale=sorted(k for k in expected if k in rows and strip(rows[k])!=strip(expected[k]))
    return missing,extra,stale


def reconcile(db,model,wid,state):
    """Diff the index tables against a rebuild from `state` (a full upgraded load)."""
    pi,ti,ci=tables(model)
    projects,tasks=project_rows(wid,state)
    expected_p={r['project_id']:r for r in projects}; expected_t={r['task_id']:r for r in tasks}
    actual_p={r['project_id']:dict(r) for r in db.execute(select(pi).where(pi.c.workspace_id==wid)).mappings()}
    actual_t={r['task_id']:dict(r) for r in db.execute(select(ti).where(ti.c.workspace_id==wid)).mappings()}
    mp,ep,sp=_mismatch(actual_p,expected_p,'project_id')
    mt,et,st=_mismatch(actual_t,expected_t,'task_id')
    desired=counter_values(state)
    actual_c={(r.key,r.subject_id):r.value for r in db.execute(select(ci).where(ci.c.workspace_id==wid))}
    drift=sorted((k,s,actual_c.get((k,s)),desired.get((k,s))) for k,s in actual_c.keys()|desired.keys() if actual_c.get((k,s))!=desired.get((k,s)))
    report={'projects':{'expected':len(expected_p),'actual':len(actual_p),'missing':mp,'extra':ep,'stale':sp},
            'tasks':{'expected':len(expected_t),'actual':len(actual_t),'missing':mt,'extra':et,'stale':st},
            'counters':{'expected':len(desired),'actual':len(actual_c),'drift':[{'key':k,'subject_id':s,'stored':a,'expected':e} for k,s,a,e in drift]}}
    task_projects={t['project_id'] for t in tasks if t['task_id'] in set(mt)|set(st)}|{actual_t[t]['project_id'] for t in et}
    report['dirty_projects']=sorted(set(mp)|set(ep)|set(sp)|task_projects)
    report['healthy']=not (report['dirty_projects'] or drift)
    return report


def repair(db,model,wid,state,report):
    """Rewrite only the projects and counters a report flagged."""
    replace_projects(db,model,wid,state,report['dirty_projects'])
    replace_counters(db,model,wid,state)
