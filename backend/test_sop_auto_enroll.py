"""Local-only enrollment acceptance. The h fixture forbids outbound HTTP."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from .models import BusinessRow
from .sop_import.catalog import load_catalog, stage, publish
from .sop_import.domain import NODE_MAP
from .sop_import.enrollment_policy import decide_policy, SYSTEM_ACTOR
from .sop_import.models import CasePolicy, SourceAdmission, Enrollment, LocalTask, TaskNodeLink, TaskEvent, Version, Family
from .test_sop_import import h, URL, post, preview, apply, overview

CUTOFF = '2026-10-20T00:00:00+08:00'
NOW = datetime.fromisoformat('2026-10-23T10:00:00+08:00').timestamp()


@pytest.mark.parametrize('facts,enabled,since,expected', [
    ({'identity_verified':True,'first_seen_at':'2026-10-20T00:00:00+08:00'},True,CUTOFF,'managed'),
    ({'identity_verified':True,'first_seen_at':'2026-10-19T23:59:59+08:00'},True,CUTOFF,'legacy'),
    ({'identity_verified':True,'first_seen_at':'2026-10-23T10:00:00+08:00'},False,CUTOFF,'legacy'),
    ({'identity_verified':True,'first_seen_at':'2026-10-23T10:00:00+08:00'},True,None,'legacy'),
    ({'identity_verified':True,'first_seen_at':'2026-10-23T10:00:00+08:00'},True,'invalid','legacy'),
    ({'identity_verified':True,'first_seen_at':'2026-10-23T10:00:00'},True,CUTOFF,'legacy'),
    ({'identity_verified':False},True,CUTOFF,'needs_review'),
    ({'identity_verified':True,'ambiguous':True,'local_quote_creation':True},True,CUTOFF,'needs_review'),
    ({'identity_verified':True,'known_existing':True},True,CUTOFF,'legacy'),
    ({'identity_verified':True,'source_baseline':True,'first_seen_at':'2026-10-23T00:00:00Z'},True,CUTOFF,'legacy'),
    ({'identity_verified':True,'local_quote_creation':True},False,None,'managed'),
    ({'status':'in_progress','nodes':[{}],'created_at':'2026-10-23T00:00:00Z'},True,CUTOFF,'needs_review'),
])
def test_pure_policy(facts, enabled, since, expected):
    original = deepcopy(facts)
    assert decide_policy(facts, enabled=enabled, since=since)[0] == expected
    assert facts == original


def configure(h):
    h.cfg.update(SOP_AUTO_ENROLL_ENABLED='true', SOP_AUTO_ENROLL_SINCE=CUTOFF)
    h.service.clock = lambda: NOW
    with h.sessions.begin() as db:
        for pid in ('p1','p2'):
            row = db.get(BusinessRow, ('w','projects',pid))
            row.data = {**row.data, 'code':pid,'name':pid,'source_kind':'lark','source_identity':{
                'base_token':'fixture-base','table_id':'confirmation','record_id':'rec-'+pid}}
            for node in db.scalars(select(BusinessRow).where(BusinessRow.workspace_id=='w',BusinessRow.parent_id==pid)):
                node.data = {**node.data, 'name':node.data['key'], 'status':'pending','owner_id':'keep-owner','tasks':[]}


def project(h, pid='p1'):
    with h.sessions() as db:
        row = db.get(BusinessRow, ('w','projects',pid))
        return {**deepcopy(row.data), 'nodes':[deepcopy(n.data) for n in db.scalars(select(BusinessRow).where(
            BusinessRow.workspace_id=='w',BusinessRow.kind=='nodes',BusinessRow.parent_id==pid))]}


def admit(h, previous=None, pid='p1'):
    if h.cfg.get('SOP_AUTO_ENROLL_ENABLED') != 'true':
        configure(h)
    p = project(h,pid)
    record = {**p['source_identity'],'kind':'confirmation','fields':{'工程確認單編號':pid}}
    state = {'projects':[p]}
    with h.sessions.begin() as db:
        h.service.admit_snapshot(db,'w',state,previous or [],{'records':[record],'last_sync':'2026-10-23T10:00:00+08:00'})
        row = db.scalar(select(Enrollment).where(Enrollment.project_id==pid))
        return row.id if row else None


def test_new_case_nine_nodes_unassigned_and_concurrent_replay(h):
    ident = admit(h)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _:h.service.enroll_case('w',ident),range(4)))
    assert all(r['status']=='succeeded' for r in results)
    assert len({tuple(r['receipt']['created_task_ids']) for r in results})==1
    assert len(results[0]['receipt']['created_task_ids'])==38
    with h.sessions() as db:
        assert len(list(db.scalars(select(LocalTask))))==38
        assert len(list(db.scalars(select(TaskNodeLink))))==42
        assert set(db.scalars(select(TaskNodeLink.node_key)))==set(NODE_MAP.values())
        assert all(t.participants=={} for t in db.scalars(select(LocalTask)))
        assert {e.actor_id for e in db.scalars(select(TaskEvent))}=={SYSTEM_ACTOR}
        assert db.get(Enrollment,('w',ident)).attempts==1
    assert overview(h)['sop_enrollment']['enrollment']['status']=='succeeded'


@pytest.mark.parametrize('missing',['template','writes'])
def test_pending_then_manual_retry(h,missing):
    configure(h)
    if missing=='template':
        with h.sessions.begin() as db:
            db.get(Version,('w',h.vid)).status='retired'
    else:
        h.cfg['SOP_TASK_WRITES_ENABLED']='false'
    ident = admit(h)
    result = h.service.enroll_case('w',ident)
    assert result['status']=='pending' and result['attempts']==1
    assert result['last_error']==('template_unavailable' if missing=='template' else 'import_unavailable')
    if missing=='template':
        with h.sessions.begin() as db:
            v=stage(db,'w','r2',load_catalog(),source_verified=True);publish(db,v,'publisher',NOW)
    h.cfg['SOP_TASK_WRITES_ENABLED']='true'
    h.who[0]='manager'
    result=post(h,URL+'/sop-import/retry',{'enrollment_id':ident})
    assert result['status']=='succeeded' and result['attempts']==2
    assert len(result['receipt']['created_task_ids'])==38
    with h.sessions.begin() as db:
        policy=db.get(CasePolicy,('w','p1'))
        assert h.service.queue_enrollment(db,'w',project(h),policy,SYSTEM_ACTOR,'repeat after publication').id==ident
        assert len(list(db.scalars(select(Enrollment))))==1


def test_legacy_untouched_on_repeat_admission_and_manual_import_refused(h):
    configure(h);old=project(h)
    for _ in range(2):
        assert admit(h,[old]) is None
    assert project(h)==old
    with h.sessions() as db:
        assert list(db.scalars(select(LocalTask)))==[]
        assert db.get(CasePolicy,('w','p1')).policy=='legacy'
    assert post(h,URL+'/sop-import/preview',{'template_version_id':h.vid},409)['code']=='legacy_case_requires_opt_in'


@pytest.mark.parametrize('who,status',[('pm',200),('manager',200),('admin',200),('member',403),('other',403)])
def test_opt_in_authority_and_only_chosen_unstarted_nodes(h,who,status):
    h.users['admin']={'id':'admin','name':'管理員','role':'admin','active':True,'capabilities':[]}
    configure(h)
    with h.sessions.begin() as db:
        row = db.get(BusinessRow,('w','nodes','real-p1-0'));row.data={**row.data,'status':'completed'}
        row = db.get(BusinessRow,('w','nodes','real-p1-1'));row.data={**row.data,'status':'in_progress'}
        row = db.get(BusinessRow,('w','projects','p1'))
        row.data={**row.data,'nodes':[deepcopy(n.data) for n in db.scalars(select(BusinessRow).where(BusinessRow.workspace_id=='w',BusinessRow.parent_id=='p1'))]}
    old=project(h);admit(h,[old]);h.who[0]=who
    result=post(h,URL+'/sop-import/opt-in',{'node_keys':['field'],'confirmed':True},status)
    assert project(h)==old
    with h.sessions() as db:
        links=list(db.scalars(select(TaskNodeLink)))
        assert {l.node_key for l in links}==({'field'} if status==200 else set())
        if status==200:
            assert db.get(CasePolicy,('w','p1')).decided_by==who
            assert result['status']=='succeeded'


@pytest.mark.parametrize('key',['sales','pm'])
def test_finished_or_running_opt_in_refused_and_confirmation_required(h,key):
    configure(h)
    with h.sessions.begin() as db:
        node = db.get(BusinessRow,('w','nodes','real-p1-'+('0' if key=='sales' else '1')))
        node.data={**node.data,'status':'completed' if key=='sales' else 'in_progress'}
        p=db.get(BusinessRow,('w','projects','p1'));p.data={**p.data,'nodes':[deepcopy(n.data) for n in db.scalars(select(BusinessRow).where(BusinessRow.workspace_id=='w',BusinessRow.parent_id=='p1'))]}
    old=project(h);admit(h,[old])
    post(h,URL+'/sop-import/opt-in',{'node_keys':['field']},422)
    assert post(h,URL+'/sop-import/opt-in',{'node_keys':[key],'confirmed':True},409)['code']=='node_already_started_or_finished'
    assert project(h)==old


def test_template_revision_does_not_duplicate_or_overwrite_result(h):
    ident=admit(h);first=h.service.enroll_case('w',ident)
    with h.sessions.begin() as db:
        task=db.get(LocalTask,('w',first['receipt']['created_task_ids'][0]))
        task.local={**task.local,'result':{'note':'保留結果','actor_id':'pm','at':NOW}};task.revision+=1
        task_id=task.id;original=deepcopy(task.local)
        db.get(Version,('w',h.vid)).status='retired'
        v=stage(db,'w','r2',load_catalog(),source_verified=True);publish(db,v,'publisher',NOW+1)
    p=project(h)
    with h.sessions.begin() as db:
        policy=db.get(CasePolicy,('w','p1'))
        job=h.service.queue_enrollment(db,'w',p,policy,SYSTEM_ACTOR,'新版本')
        next_id=job.id
    result=h.service.enroll_case('w',next_id)
    assert result['receipt']['created_task_ids']==[]
    assert len(result['receipt']['existing_task_ids'])==38
    with h.sessions() as db:
        assert db.get(LocalTask,('w',task_id)).local==original
        assert len(list(db.scalars(select(LocalTask))))==38


def test_failed_attempt_is_inspectable_and_bounded(h,monkeypatch):
    ident=admit(h)
    monkeypatch.setattr(h.service,'commit_import',lambda *a,**k:(_ for _ in ()).throw(RuntimeError('fixture failure')))
    h.service.run_enrollments('w')
    h.service.run_enrollments('w')
    with h.sessions() as db:
        row=db.get(Enrollment,('w',ident));assert (row.status,row.last_error,row.attempts)==('failed','RuntimeError',1)
        assert list(db.scalars(select(LocalTask)))==[]
    h.who[0]='member';assert h.client.get('/api/sop-import/readiness').status_code==403
    post(h,URL+'/sop-import/retry',{'enrollment_id':ident},403)
    h.who[0]='manager'
    data=h.client.get('/api/sop-import/readiness').json()
    assert next(c for c in data['items'] if c['project_id']=='p1')['enrollments'][0]['status']=='failed'


def test_real_source_commit_survives_enrollment_failure_and_repeat_is_stable(tmp_path, monkeypatch):
    import httpx
    from . import storage
    from .models import WorkspaceRow
    from .test_sop_quotes import harness, WID
    monkeypatch.setattr(httpx.HTTPTransport,'handle_request',lambda *a,**k:(_ for _ in ()).throw(AssertionError('network forbidden')))
    app, client, _, _ = harness(tmp_path,SOP_AUTO_ENROLL_ENABLED='true',SOP_AUTO_ENROLL_SINCE=CUTOFF)
    sync=app.state.source_sync;sync.sop_enrollment.clock=lambda:NOW
    monkeypatch.setattr(sync,'_policy',lambda wid:('fixture-only',))
    monkeypatch.setattr(sync,'_actor',lambda *a:{'id':'u-manager','role':'manager'})
    with app.state.sessions() as db:
        before=storage.load(db,BusinessRow,db.get(WorkspaceRow,WID))
        old=deepcopy(before['projects'])
    rows=[{'base_token':'local-fixture','table_id':'confirmation','record_id':rid,'kind':'confirmation',
           'created_time':created,'fields':{'工程確認單編號':code,'工程名稱':name}}
          for rid,code,name,created in [('new-case','CNEW','新案','2026-10-22T00:00:00+08:00'),('old-case','COLD','舊案','2026-09-01T00:00:00+08:00')]]
    snapshot={'configured':True,'status':'ready','last_sync':'2026-10-23T10:00:00+08:00','message':'local fixture',
              'records':rows,'tables':[{'base_token':'local-fixture','table_id':'confirmation','status':'ready'}]}
    original=sync.sop_enrollment.commit_import
    monkeypatch.setattr(sync.sop_enrollment,'commit_import',lambda *a,**k:(_ for _ in ()).throw(RuntimeError('fixture failure')))
    result=sync.apply_snapshot(WID,deepcopy(snapshot),'u-manager',expected_policy=('fixture-only',),expected_generation=0)
    assert result['status']=='ready'
    with app.state.sessions() as db:
        state=storage.load(db,BusinessRow,db.get(WorkspaceRow,WID))
        new=next(p for p in state['projects'] if p['code']=='CNEW')
        legacy=next(p for p in state['projects'] if p['code']=='COLD')
        assert db.get(CasePolicy,(WID,new['id'])).policy=='managed'
        assert db.get(CasePolicy,(WID,legacy['id'])).policy=='legacy'
        job=db.scalar(select(Enrollment).where(Enrollment.workspace_id==WID,Enrollment.project_id==new['id']))
        ident=job.id;assert job.status=='failed'
        for prior in old:
            assert next(p for p in state['projects'] if p['id']==prior['id'])['nodes']==prior['nodes']
        legacy_nodes=deepcopy(legacy['nodes'])
    monkeypatch.setattr(sync.sop_enrollment,'commit_import',original)
    sync.sop_enrollment.clock=lambda:NOW+121
    result=sync.apply_snapshot(WID,deepcopy(snapshot),'u-manager',expected_policy=('fixture-only',),expected_generation=1,skip_unchanged=True)
    with app.state.sessions() as db:
        retried=db.get(Enrollment,(WID,ident))
        assert retried.status=='succeeded' and len(retried.receipt['created_task_ids'])==38
        assert db.get(WorkspaceRow,WID).data['source_status']['sync_revision']==1
    result=sync.apply_snapshot(WID,deepcopy(snapshot),'u-manager',expected_policy=('fixture-only',),expected_generation=1)
    with app.state.sessions() as db:
        state=storage.load(db,BusinessRow,db.get(WorkspaceRow,WID))
        assert next(p for p in state['projects'] if p['id']==legacy['id'])['nodes']==legacy_nodes
        assert len(list(db.scalars(select(LocalTask).where(LocalTask.workspace_id==WID))))==38
        assert len(list(db.scalars(select(Enrollment).where(Enrollment.workspace_id==WID))))==1
    client.close();app.state.engine.dispose()


def test_local_quote_creation_without_template_stays_pending(tmp_path,monkeypatch):
    import httpx
    from .test_sop_quotes import harness, WID
    monkeypatch.setattr(httpx.HTTPTransport,'handle_request',lambda *a,**k:(_ for _ in ()).throw(AssertionError('network forbidden')))
    app,client,signin,_=harness(tmp_path,LOCAL_CASE_CREATION_ENABLED='true')
    signin('u-manager')
    with app.state.sessions.begin() as db:
        for v in db.scalars(select(Version).where(Version.workspace_id==WID)):
            v.status='retired'
    draft=client.post('/api/quotes/preview',json={'name':'等待範本的新案','pm_id':'u-pm'}).json()
    response=client.post('/api/quotes',json={'draft_id':draft['draft_id'],'request_id':'pending-local'})
    assert response.status_code==200,response.text
    with app.state.sessions() as db:
        job=db.scalar(select(Enrollment).where(Enrollment.project_id==response.json()['project_id']))
        assert (job.status,job.last_error)==('pending','template_unavailable')
        assert db.get(CasePolicy,(WID,job.project_id)).policy=='managed'
    client.close();app.state.engine.dispose()


def test_protected_nodes_require_explicit_scope_and_preserve_result(h):
    from .sop_import.enrollment_policy import protected_node_changes
    from types import SimpleNamespace
    before=[{'id':'case','nodes':[{'id':'done','key':'sales','status':'completed','tasks':[{'id':'old','result':'保留'}]},
                                 {'id':'future','key':'field','status':'pending','tasks':[]}]}]
    policies={'case':SimpleNamespace(policy='legacy',node_keys=[])}
    changed=deepcopy(before);changed[0]['nodes'][0]['tasks']=[]
    assert protected_node_changes(policies,before,changed)==['done']
    policies['case']=SimpleNamespace(policy='managed',node_keys=['field'])
    changed=deepcopy(before);changed[0]['nodes'][1]['tasks']=[{'id':'new'}]
    assert protected_node_changes(policies,before,changed)==[]
    changed[0]['nodes'][0]['status']='pending'
    assert protected_node_changes(policies,before,changed)==['done']
