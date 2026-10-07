"""Route contracts use real leases and a mock-only Lark HTTP boundary."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .app import create_app, CacheRow, PersonRow, WorkspaceRow
from .live_read.client import LiveLarkClient
from .live_read.coordinator import RefreshCoordinator
from .live_read.routes import register
from .live_read.token_cache import TenantTokenCache
from .models import Base
from .test_live_read_coordinator import SynchronousExecutor
from .test_production_access import company


@pytest.fixture
def harness(tmp_path):
    engine=create_engine(f'sqlite:///{tmp_path}/routes.db',connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine)
    sessions=sessionmaker(engine,expire_on_commit=False)
    cfg={'LARK_LIVE_READ_ENABLED':'true','LARK_WORKER_IDENTITY':'application',
         'LARK_APP_ID':'route-test','LARK_APP_SECRET':'synthetic','LARK_WORKER_ORGANIZATION':'company'}
    calls=[]
    def transport(request):
        calls.append(request)
        if request.url.path.endswith('/tenant_access_token/internal'):
            return httpx.Response(200,json={'code':0,'tenant_access_token':'synthetic','expire':7200})
        return httpx.Response(200,json={'code':0,'data':{'items':[]}})
    def read(wid):
        with LiveLarkClient(cfg,transport=httpx.MockTransport(transport),token_cache=TenantTokenCache()) as client:
            client.request('GET','/bitable/v1/apps/fake/tables/fake/records')
            return {'fingerprint':'synthetic','lark':client.metrics}
    readers={d:read for d in ('sources','roster','attendance')}
    coordinator=RefreshCoordinator(sessions,CacheRow,readers,cfg,executor=SynchronousExecutor())
    identity={'mode':'lark','wid':'lark-company'}
    user={'id':'manager','role':'manager'}
    def authorize(wid,dataset,actor):
        if actor['role']!='manager': raise HTTPException(403,'denied')
    app=FastAPI()
    register(app,lambda request:(identity,user),coordinator,authorize=authorize)
    yield TestClient(app),coordinator,calls,identity,user
    engine.dispose()


def test_status_is_read_only_and_waited_refresh_returns_freshness(harness):
    client,c,calls,_,_=harness
    result=client.get('/api/live/status')
    assert result.status_code==200 and result.json()['freshness']['enabled']
    assert calls==[]
    assert result.headers['cache-control']=='no-store'
    result=client.post('/api/live/refresh',json={'datasets':['sources'],'wait':True})
    assert result.status_code==200,result.text
    assert result.json()['freshness']['datasets']['sources']['lark']['calls']==2
    assert len(calls)==2
    assert client.post('/api/live/refresh',json={'datasets':['sources']}).status_code==200
    assert len(calls)==2


@pytest.mark.parametrize('payload',[{'datasets':['sources'],'force':True},{'datasets':['roster']}])
def test_privileged_refresh_denied_before_transport(harness,payload):
    client,_,calls,_,user=harness;user['role']='member'
    assert client.post('/api/live/refresh',json=payload).status_code==403
    assert calls==[]


def test_member_can_request_display_refresh(harness):
    client,_,calls,_,user=harness;user['role']='member'
    assert client.post('/api/live/refresh',json={'datasets':['sources','attendance'],'wait':True}).status_code==200
    assert len(calls)==4


@pytest.mark.parametrize('wid,mode',[('demo-one','demo'),('test-lark-company','lark')])
def test_isolated_workspaces_have_disabled_status_and_zero_transport(harness,wid,mode):
    client,_,calls,identity,_=harness;identity.update(wid=wid,mode=mode)
    freshness=client.get('/api/live/status').json()['freshness']
    assert freshness['enabled'] is False
    assert all(d['status']=='unconfigured' for d in freshness['datasets'].values())
    assert client.post('/api/live/refresh',json={'datasets':['sources']}).status_code==403
    assert calls==[]


def test_waited_failure_has_502_with_sanitized_freshness(harness):
    client,c,_,_,_=harness
    def fail(wid): raise RuntimeError('private-token')
    c.refreshers['sources']=fail
    result=client.post('/api/live/refresh',json={'datasets':['sources'],'wait':True})
    assert result.status_code==502
    assert result.json()['freshness']['datasets']['sources']['status']=='error'
    assert 'private-token' not in result.text


def test_running_refresh_returns_202_coalesces_and_force_conflicts(harness):
    client,c,calls,_,_=harness;started=Event();release=Event()
    def read(wid):
        started.set(); assert release.wait(5)
        return {'fingerprint':'done'}
    c.refreshers['sources']=read
    with ThreadPoolExecutor(max_workers=2) as executor:
        c.executor=executor
        try:
            assert client.post('/api/live/refresh',json={'datasets':['sources']}).status_code==202
            assert started.wait(2)
            assert client.post('/api/live/refresh',json={'datasets':['sources']}).status_code==202
            assert client.post('/api/live/refresh',json={'datasets':['sources'],'force':True}).status_code==409
        finally: release.set()
    assert calls==[]


@pytest.mark.parametrize('payload',[{'datasets':[]},{'datasets':['unknown']},{'datasets':'sources'}])
def test_invalid_request_is_422_without_transport(harness,payload):
    client,_,calls,_,_=harness
    assert client.post('/api/live/refresh',json=payload).status_code==422
    assert calls==[]


def test_demo_app_pages_include_disabled_freshness_without_network(tmp_path):
    app=create_app({'DATABASE_URL':f'sqlite:///{tmp_path}/demo.db','UPLOAD_DIR':str(tmp_path/'uploads'),
                    'DEMO_MODE':'true','LARK_LIVE_READ_ENABLED':'true',
                    'LARK_WORKER_IDENTITY':'application','LARK_LIVE_READ_TRANSPORT':'deny'})
    def forbidden(wid): raise AssertionError('demo must never reach a refresher')
    app.state.live_read.refreshers={d:forbidden for d in ('sources','roster','attendance')}
    client=TestClient(app); assert client.get('/api/session').status_code==200
    for path in ('/api/workspace','/api/sources','/api/live/status'):
        response=client.get(path);assert response.status_code==200,response.text
        assert response.json()['freshness']['enabled'] is False
    assert client.post('/api/live/refresh',json={'datasets':['sources']}).status_code==403


def production_client(tmp_path, *, enabled=True):
    # F1 snapshots validated settings at coordinator creation, as production does.
    app,client=company(tmp_path, {'LARK_LIVE_READ_ENABLED':str(enabled).lower(),
        'LARK_WORKER_IDENTITY':'application','LARK_LIVE_READ_TRANSPORT':'deny'})
    assert client.post('/api/workspace/switch',json={'environment':'production'}).status_code==200
    app.state.live_read.close()
    app.state.live_read.executor=SynchronousExecutor()
    app.state.live_read.roster_executor=app.state.live_read.executor
    return app,client


def test_app_workspace_demand_read_and_header(tmp_path):
    app,client=production_client(tmp_path);calls=[]
    def read(wid):calls.append(wid);return {'fingerprint':'new'}
    app.state.live_read.refreshers={d:read for d in ('sources','roster','attendance')}
    response=client.get('/api/workspace');assert response.status_code==200,response.text
    assert response.headers['x-data-as-of']==response.json()['freshness']['datasets']['sources']['as_of']
    assert len(calls)==2  # The person's roster proof is still below its soft TTL.
    calls.clear()
    assert client.get('/api/live/status').status_code==200
    assert calls==[]


def test_admission_reloads_refreshed_person_before_access_check(tmp_path):
    app,client=production_client(tmp_path)
    with app.state.sessions.begin() as db:
        person=db.get(PersonRow,('lark-company','u-manager'))
        person.data={**person.data,'directory_last_seen_at':(datetime.now(timezone.utc)-timedelta(seconds=901)).isoformat()}
    calls=[]
    def roster(wid):
        calls.append(wid)
        with app.state.sessions.begin() as db:
            person=db.get(PersonRow,(wid,'u-manager'))
            person.data={**person.data,'directory_last_seen_at':datetime.now(timezone.utc).isoformat()}
        return {'fingerprint':'verified'}
    app.state.live_read.refreshers={'roster':roster,'sources':lambda wid:{'fingerprint':'s'},'attendance':lambda wid:{'fingerprint':'a'}}
    response=client.get('/api/workspace');assert response.status_code==200,response.text
    assert calls==['lark-company']


def test_status_never_triggers_stale_admission_read(tmp_path):
    app,client=production_client(tmp_path)
    with app.state.sessions.begin() as db:
        person=db.get(PersonRow,('lark-company','u-manager'))
        person.data={**person.data,'directory_last_seen_at':(datetime.now(timezone.utc)-timedelta(seconds=90)).isoformat()}
    def forbidden(wid):raise AssertionError('status must not read Lark')
    app.state.live_read.refreshers['roster']=forbidden
    assert client.get('/api/live/status').status_code==200
    assert app.state.live_read.status('lark-company')['datasets']['roster']['status']=='never'


@pytest.mark.parametrize('dataset,path,status_key',[
    ('roster','/api/people/sync','people_directory_status'),
    ('attendance','/api/attendance/sync','attendance_schedule_status'),
    ('sources','/api/sources/sync',None),
])
def test_manual_sync_delegates_with_same_permissions_and_returns_cached_response(tmp_path,dataset,path,status_key):
    from .app import AuditRow
    from sqlalchemy import select
    app,client=production_client(tmp_path);calls=[]
    def reader(wid):
        calls.append(wid)
        with app.state.sessions.begin() as db:
            if status_key:
                row=db.get(WorkspaceRow,wid)
                row.data={**row.data,status_key:{'status':'ready','last_success_at':datetime.now(timezone.utc).isoformat()}}
            else:
                db.add(CacheRow(id=wid,data={'configured':True,'last_sync':datetime.now(timezone.utc).isoformat(),
                    'status':'ready','tables':[],'records':[]}))
        return {'fingerprint':'manual'}
    app.state.live_read.refreshers[dataset]=reader
    response=client.post(path,json={})
    assert response.status_code==200,response.text
    assert response.json()['status']=='ready'
    assert response.json()['freshness']['datasets'][dataset]['status']=='fresh'
    assert calls==['lark-company']
    with app.state.sessions() as db:
        audits=list(db.scalars(select(AuditRow).where(AuditRow.actor_id=='u-manager')))
    assert any(row.data.get('live_read') for row in audits)


def test_test_session_never_calls_roster_even_when_person_is_stale(tmp_path):
    app,client=company(tmp_path, {'LARK_LIVE_READ_ENABLED':'true',
        'LARK_WORKER_IDENTITY':'application','LARK_LIVE_READ_TRANSPORT':'deny'})
    with app.state.sessions.begin() as db:
        p=db.get(PersonRow,('lark-company','u-manager'))
        p.data={**p.data,'directory_last_seen_at':(datetime.now(timezone.utc)-timedelta(seconds=90)).isoformat()}
    def forbidden(wid): raise AssertionError('test sessions must not read Lark')
    app.state.live_read.refreshers={d:forbidden for d in ('sources','roster','attendance')}
    response=client.get('/api/workspace')
    assert response.status_code==200,response.text
    assert response.json()['freshness']['enabled'] is False
    assert app.state.live_read.queue_depth==0


@pytest.mark.parametrize('kind,expected', [('bootstrap', 'recovery'), ('grant', 'normal'), ('member', 'denied'), ('fresh_member', 'normal')])
def test_oauth_failed_roster_preserves_access_policy(tmp_path,monkeypatch,kind,expected):
    from urllib.parse import parse_qs,urlparse
    from sqlalchemy import select
    from .app import AuthRow
    app,client=production_client(tmp_path)
    with app.state.sessions.begin() as db:
        p=db.get(PersonRow,('lark-company','u-manager'))
        p.data={**p.data,'role':'member' if kind in ('member', 'fresh_member') else 'manager', 'bootstrap_admin':kind=='bootstrap',
                'authz_version':1, 'directory_last_seen_at':(datetime.now(timezone.utc)-timedelta(seconds=90 if kind=='fresh_member' else 901)).isoformat()}
    if kind=='grant':
        import json
        app.state.cfg['LARK_COMPANY_ADMIN_GRANTS_JSON']=json.dumps([{'open_id':'u-manager', 'app_id':app.state.cfg['LARK_APP_ID'], 'tenant':'company', 'authorized_at':datetime.now(timezone.utc).isoformat(), 'enabled':True, 'role':'manager', 'grant_id':'test-grant', 'reason':'test', 'authorized_by':'owner', 'decision_ref':'test'}])
    class OAuth:
        def __init__(self,**kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def post(self,url,**kwargs):
            return httpx.Response(200,json={'access_token':'synthetic','expires_in':3600},request=httpx.Request('POST',url))
        def get(self,url,**kwargs):
            return httpx.Response(200,json={'data':{'open_id':'u-manager','name':'Manager','tenant_key':'company'}},request=httpx.Request('GET',url))
    monkeypatch.setattr('backend.app.httpx.Client',OAuth)
    calls=[]
    def roster(wid):
        calls.append(wid)
        raise RuntimeError('private-token')
    app.state.live_read.refreshers['roster']=roster
    login=client.get('/api/auth/lark/login',follow_redirects=False)
    state=parse_qs(urlparse(login.headers['location']).query)['state'][0]
    with app.state.sessions() as db: before=set(db.scalars(select(AuthRow.id)))
    response=client.get('/api/auth/lark/callback',params={'state':state,'code':'synthetic'},follow_redirects=False)
    assert response.status_code==(403 if expected=='denied' else 307),response.text
    assert calls==['lark-company']
    if expected=='denied':
        assert '名冊' in response.json()['detail'] and 'private-token' not in response.text
        with app.state.sessions() as db: assert set(db.scalars(select(AuthRow.id)))<=before
    else:
        assert client.get('/api/session').json()['access_mode']==expected


@pytest.mark.parametrize('bootstrap',[True,False])
def test_failed_hard_roster_read_keeps_denial_or_bootstrap_recovery(tmp_path,bootstrap):
    app,client=production_client(tmp_path)
    with app.state.sessions.begin() as db:
        p=db.get(PersonRow,('lark-company','u-manager'))
        p.data={**p.data,'bootstrap_admin':bootstrap,
                'directory_last_seen_at':(datetime.now(timezone.utc)-timedelta(seconds=901)).isoformat()}
    def failed(wid): raise RuntimeError('private-token')
    app.state.live_read.refreshers['roster']=failed
    response=client.get('/api/workspace')
    assert response.status_code==403 and 'private-token' not in response.text
    session=client.get('/api/session').json()
    if bootstrap: assert session['access_mode']=='recovery'
    else: assert session['user'] is None


def test_enabled_attendance_rejects_custom_dates_before_refresh(tmp_path):
    app,client=production_client(tmp_path);calls=[]
    app.state.live_read.refreshers['attendance']=lambda wid:calls.append(wid) or {'fingerprint':'a'}
    response=client.post('/api/attendance/sync',json={'date_from':'2020-01-01','date_to':'2020-01-14'})
    assert response.status_code==422 and '14天' in response.json()['detail']
    assert calls==[]


def test_disabled_attendance_preserves_custom_date_arguments(tmp_path):
    app,client=production_client(tmp_path,enabled=False)
    calls=[]
    def sync(wid,actor,date_from,date_to):
        calls.append((wid,actor,date_from,date_to))
        return {'status':'ready','date_from':date_from,'date_to':date_to}
    app.state.attendance_schedule.sync=sync
    response=client.post('/api/attendance/sync',json={'date_from':'2020-01-01','date_to':'2020-01-14'})
    assert response.status_code==200,response.text
    assert calls==[('lark-company','u-manager','2020-01-01','2020-01-14')]
    assert response.json()['freshness']['enabled'] is False


def test_nonblocking_new_read_returns_202_even_if_it_completes_immediately(harness):
    client,_,calls,_,_=harness
    response=client.post('/api/live/refresh',json={'datasets':['sources']})
    assert response.status_code==202,response.text
    assert response.json()['freshness']['datasets']['sources']['status']=='fresh'
    assert len(calls)==2
    assert client.post('/api/live/refresh',json={'datasets':['sources']}).status_code==200
    assert len(calls)==2


@pytest.mark.parametrize('wait', [False, True])
def test_force_race_maps_coordinator_already_running_to_409(harness, monkeypatch, wait):
    client, coordinator, calls, _, _ = harness
    # Another caller starts between the route precheck and coordinator.ensure.
    monkeypatch.setattr(coordinator, 'ensure', lambda *args, **kwargs: {'status': 'already_running'})
    response = client.post('/api/live/refresh', json={
        'datasets': ['sources'], 'force': True, 'wait': wait})
    assert response.status_code == 409, response.text
    assert 'freshness' in response.json()
    assert calls == []


def test_app_shutdown_closes_both_coordinator_executors(tmp_path):
    app = create_app({'DATABASE_URL': f'sqlite:///{tmp_path}/shutdown.db',
                      'UPLOAD_DIR': str(tmp_path/'uploads'), 'DEMO_MODE': 'true'})
    coordinator = app.state.live_read
    with TestClient(app) as client:
        assert client.get('/api/health').status_code == 200
        assert coordinator.executor.submit(lambda: True).result()
        assert coordinator.roster_executor.submit(lambda: True).result()
    for executor in (coordinator.executor, coordinator.roster_executor):
        with pytest.raises(RuntimeError, match='shutdown'):
            executor.submit(lambda: None)


def test_public_freshness_omits_snapshot_and_exception_internals(harness):
    client, coordinator, _, _, _ = harness
    coordinator.ensure('lark-company', 'sources', wait=True)
    def failed(wid):
        raise OSError('private details')
    coordinator.refreshers['roster'] = failed
    client.post('/api/live/refresh', json={'datasets': ['roster'], 'wait': True})
    response = client.get('/api/live/status')
    for dataset in response.json()['freshness']['datasets'].values():
        assert not {'error_code', 'fingerprint', 'changed_at'} & dataset.keys()
    assert 'OSError' not in response.text


def test_forced_refresh_records_actor_and_datasets(tmp_path):
    from .app import AuditRow
    from sqlalchemy import select
    app, client = production_client(tmp_path)
    app.state.live_read.refreshers['roster'] = lambda wid: {'fingerprint': 'audit'}
    response = client.post('/api/live/refresh', json={'datasets': ['roster', 'roster'], 'force': True, 'wait': True})
    assert response.status_code == 200, response.text
    with app.state.sessions() as db:
        rows = list(db.scalars(select(AuditRow).where(AuditRow.actor_id == 'u-manager')))
    forced = [row for row in rows if row.data.get('force')]
    assert len(forced) == 1
    assert forced[0].data['datasets'] == ['roster']


@pytest.mark.parametrize('path', ['/api/workspace', '/api/sources'])
def test_display_cache_read_failure_returns_cached_content(tmp_path, path):
    app, client = production_client(tmp_path)
    def failed(key):
        raise OSError('private database details')
    app.state.live_read._read = failed
    response = client.get(path)
    assert response.status_code == 200, response.text
    assert response.json()['freshness']['datasets']['sources']['status'] == 'error'
    assert 'private database details' not in response.text
