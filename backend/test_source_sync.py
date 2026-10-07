"""Atomic source refresh and scheduler tests against isolated SQLite memory stores."""
from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, Column, String, Integer, JSON
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool
from . import source_sync, storage
from .policy import upgrade
from .seed import seed, USERS
from .sources import import_sources
from .source_sync import SourceSyncService


def records(code='C115001'):
    def r(kind,rid,fields): return dict(base_token='v4',table_id=kind,record_id=rid,kind=kind,fields=fields)
    return [r('confirmation','rec1',{'工程確認單編號':code,'狀態':'執行中'}),r('daily','recD',{'工程編號':code,'日期':'2026-09-27','組別':'控制'})]


def snapshot(clock, rows=None):
    return {'configured':True,'status':'ready','last_sync':clock,'message':'success','tables':[{'table_id':'confirmation','status':'ready'}],'records':records() if rows is None else rows}


@pytest.fixture
def harness(monkeypatch):
    base=declarative_base()
    class W(base):
        __tablename__='workspaces'
        id=Column(String,primary_key=True); version=Column(Integer); data=Column(JSON)
    class A(base):
        __tablename__='auth'
        id=Column(String,primary_key=True); data=Column(JSON)
    class C(base):
        __tablename__='cache'
        id=Column(String,primary_key=True); data=Column(JSON)
    B,P=storage.models(base)
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    base.metadata.create_all(engine); sessions=sessionmaker(engine,expire_on_commit=False)
    clock=['2026-09-27T10:00:00+08:00']; monkeypatch.setattr(source_sync,'now',lambda:clock[0])
    ws=seed(True); ws['users']=deepcopy(USERS); import_sources(ws,records()); upgrade(ws)
    ws['environment']='production'; ws['source_status']={'status':'ready','last_sync':clock[0],'last_attempt_at':clock[0],'message':'last good'}
    next(u for u in ws['users'] if u['id']=='u-manager').update(identity_app_id='app1',bootstrap_admin=True)
    ws['source_connection']={'enabled':True,'actor_id':'u-manager','interval_seconds':300}
    wid='lark-tenant'
    with sessions.begin() as db:
        row=W(id=wid,version=ws['version'],data={}); db.add(row); db.flush(); row.data=storage.save(db,B,wid,ws)
        db.add(C(id=wid,data=snapshot(clock[0])))
        db.add(P(organization_id=wid,person_id='u-manager',data=deepcopy(next(u for u in ws['users'] if u['id']=='u-manager'))))
        db.add(A(id='auth1',data={'organization':wid,'uid':'u-manager','access_token':'fake','expires':datetime.fromisoformat(clock[0]).timestamp()+3600}))
    cfg={'LARK_APP_ID':'app1','LARK_WORKER_IDENTITY':'application','LARK_WORKER_ORGANIZATION':'tenant','LARK_ALLOWED_TENANTS':'tenant'}; fetched=[]
    monkeypatch.setattr(source_sync,'application_adapter',lambda config:SimpleNamespace(token='application-token',client=SimpleNamespace(close=lambda:None)))
    def fetch(token): fetched.append(token); return snapshot(clock[0])
    service=SourceSyncService(sessions,W,B,P,A,C,cfg,fetcher=fetch)
    def read():
        with sessions() as db: return storage.load(db,B,db.get(W,wid)),deepcopy(db.get(C,wid).data)
    yield SimpleNamespace(service=service,sessions=sessions,W=W,B=B,P=P,A=A,C=C,wid=wid,cfg=cfg,clock=clock,fetched=fetched,read=read)
    engine.dispose()


@pytest.mark.parametrize('kind',['partial','partial_table','invalid'])
def test_partial_or_malformed_snapshot_preserves_projects_daily_and_cache(harness,kind):
    h=harness; before,cache=h.read(); h.clock[0]='2026-09-27T10:05:00+08:00'
    payload=snapshot(h.clock[0],[records()[1]])
    if kind=='partial': payload['status']='partial'
    elif kind=='partial_table': payload['tables'][0]['status']='partial'
    else: payload.pop('records')
    h.service.fetcher=lambda token:payload
    with pytest.raises(HTTPException): h.service.sync(h.wid,'u-manager','fake')
    state,after=h.read()
    assert state['projects']==before['projects']
    assert after['records']==cache['records'] and after['tables']==cache['tables']
    assert state['source_status']['last_sync']==after['last_sync']==cache['last_sync']
    assert state['source_status']['last_attempt_at']==h.clock[0] and after['status']=='error'


def test_connection_error_preserves_last_success_and_records_attempt(harness):
    h=harness; before,cache=h.read(); h.clock[0]='2026-09-27T10:05:00+08:00'
    def fail(token): raise OSError('temporary failure')
    h.service.fetcher=fail
    with pytest.raises(HTTPException) as exc: h.service.sync(h.wid,'u-manager','fake')
    assert exc.value.status_code==502
    state,after=h.read()
    assert state['projects']==before['projects'] and after['last_sync']==cache['last_sync']
    assert after['last_attempt_at']==h.clock[0] and after['records']==cache['records']


def test_complete_snapshot_without_baseline_imports_all_and_preserves_execution(harness):
    from .source_case_policy import visible_project
    h=harness
    with h.sessions.begin() as db:
        row=db.get(h.W,h.wid);state=storage.load(db,h.B,row)
        state['projects'][0].update(execution_system='meegle',case_visibility='excluded_history')
        row.data=storage.save(db,h.B,h.wid,state)
    before,_=h.read();rows=records()
    rows[0]['created_time']=1790460000000
    rows[0]['fields']['狀態']='已結案'
    h.service.fetcher=lambda _:snapshot(h.clock[0],deepcopy(rows))
    result=h.service.sync(h.wid,'u-manager');state,cache=h.read()
    p=state['projects'][0]
    assert visible_project(state,p) and p['case_visibility']=='source_reference'
    assert p['execution_system']=='meegle'
    assert p['source_status']=='已結案'
    assert p['id']==before['projects'][0]['id']
    assert [n['tasks'] for n in p['nodes']]==[n['tasks'] for n in before['projects'][0]['nodes']]
    assert cache['records']==rows
    assert result['mapping']['projects']==1 and result['mapping']['daily_imported']==1
    assert result['mapping_status']!='baseline_required'
    assert state['source_status']['sync_revision']==1
    h.service.sync(h.wid,'u-manager');again,_=h.read()
    assert len(again['projects'])==1
    assert again['projects'][0]['execution_system']=='meegle'


def test_first_connection_error_is_visible_without_existing_cache(harness):
    h=harness
    with h.sessions.begin() as db: db.delete(db.get(h.C,h.wid))
    h.service.fetcher=lambda token:None
    with pytest.raises(HTTPException): h.service.sync(h.wid,'u-manager','fake')
    state,cache=h.read()
    assert cache['status']=='error' and cache['records']==[] and cache['last_attempt_at']==h.clock[0]


def test_scheduler_reserves_configured_slot_and_skips_test_workspaces(harness):
    h=harness; h.cfg['LARK_LIVE_READ_SOURCE_TTL_SECONDS']='120'; h.clock[0]='2026-09-27T10:01:59+08:00'
    assert h.service.run_due(h.wid) is None and not h.fetched
    h.clock[0]='2026-09-27T10:02:00+08:00'
    h.service.run_due(h.wid); assert h.fetched==['application-token']
    h.clock[0]='2026-09-27T10:02:30+08:00'
    assert h.service.run_due(h.wid) is None
    h.clock[0]='2026-09-27T10:10:00+08:00'
    h.service.run_due(h.wid); assert h.fetched==['application-token','application-token']
    assert h.service.run_due('test-'+h.wid) is None


def test_scheduler_claim_prevents_second_worker_during_fetch(harness):
    h=harness; h.clock[0]='2026-09-27T10:05:00+08:00'; calls=[]
    def fetch(token):
        calls.append(token)
        assert h.service.run_due(h.wid) is None
        return snapshot(h.clock[0])
    h.service.fetcher=fetch; h.service.run_due(h.wid)
    assert calls==['application-token']


def test_expired_user_auth_does_not_stop_company_application_sync(harness):
    h=harness; h.clock[0]='2026-09-27T12:00:00+08:00'; before,cache=h.read()
    assert h.service.run_due(h.wid)['status']=='ready' and h.fetched==['application-token']
    state,after=h.read()
    assert after['status']=='ready' and after['last_sync']==h.clock[0]
    version=state['version']; h.clock[0]='2026-09-27T12:00:30+08:00'
    assert h.service.run_due(h.wid) is None
    assert h.read()[0]['version']==version


def test_suspended_actor_is_blocked_before_fetch(harness):
    h=harness
    with h.sessions.begin() as db:
        row=db.get(h.P,(h.wid,'u-manager')); row.data={**row.data,'active':False}
    with pytest.raises(HTTPException) as exc: h.service.sync(h.wid,'u-manager','fake')
    assert exc.value.status_code==403 and not h.fetched


def test_permissions_revoked_during_fetch_prevent_commit(harness):
    h=harness; before,cache=h.read()
    def fetch(token):
        with h.sessions.begin() as db:
            row=db.get(h.P,(h.wid,'u-manager')); row.data={**row.data,'active':False}
        return snapshot(h.clock[0],records('C999999'))
    h.service.fetcher=fetch
    with pytest.raises(HTTPException) as exc: h.service.sync(h.wid,'u-manager','fake')
    assert exc.value.status_code==403
    state,after=h.read(); assert state['projects']==before['projects'] and after['records']==cache['records']


def test_default_fetcher_receives_app_cfg_without_environment_dependency(harness,monkeypatch):
    h=harness; cfg=dict(h.cfg,LARK_SOURCE_TABLES_JSON='isolated-app-config'); seen=[]
    def fetch(token,cfg=None,client=None): seen.append((token,cfg)); assert client is not None; return snapshot(h.clock[0])
    monkeypatch.setattr(source_sync,'fetch_sources',fetch)
    service=SourceSyncService(h.sessions,h.W,h.B,h.P,h.A,h.C,cfg)
    service.sync(h.wid,'u-manager','fake')
    assert seen==[('application-token',cfg)]


def test_application_auth_failure_updates_attempt_and_retains_snapshot(harness,monkeypatch):
    h=harness; h.cfg.update(LARK_WORKER_IDENTITY='application',LARK_WORKER_ORGANIZATION='tenant'); h.clock[0]='2026-09-27T12:00:00+08:00'
    before,cache=h.read()
    def fail(cfg): raise RuntimeError('token endpoint down')
    monkeypatch.setattr(source_sync,'application_adapter',fail)
    with pytest.raises(HTTPException): h.service.run_due(h.wid)
    state,after=h.read()
    assert not h.fetched and state['projects']==before['projects']
    assert after['status']=='error' and after['last_sync']==cache['last_sync'] and after['last_attempt_at']==h.clock[0]


def test_direct_sync_cannot_import_production_records_into_test_namespace(harness):
    h=harness
    with pytest.raises(HTTPException) as exc: h.service.sync('test-'+h.wid,'u-manager','fake')
    assert exc.value.status_code==403 and not h.fetched


def test_complete_daily_table_deletion_is_persisted_as_inactive_history(harness):
    h=harness; before,_=h.read()
    ident=before['projects'][0]['daily_reports'][0]['id']
    payload=snapshot(h.clock[0],records()[:1])
    payload['tables'] += [{'base_token':'v4','table_id':'daily','kind':'daily','status':'ready','count':0}]
    payload['records'][0]['created_time']='2026-09-27T09:00:00+08:00'
    with h.sessions.begin() as db:
        row=db.get(h.W,h.wid);state=storage.load(db,h.B,row)
        state['source_case_baseline']={'version':1,'cutover_at':'2026-09-26T00:00:00+08:00',
            'source_tables':[['','confirmation'],['v4','daily']], 'record_ids':[], 'case_codes':[]}
        for project in state['projects']:project['case_visibility']='new_case'
        row.data=storage.save(db,h.B,h.wid,state)
    h.service.fetcher=lambda _:deepcopy(payload)
    h.service.sync(h.wid,'u-manager','fake')
    state,cache=h.read()
    assert not state['projects'][0]['daily_reports']
    assert state['daily_unmatched'][0]['id']==ident and state['daily_unmatched'][0]['source_missing']
    assert state['source_status']['mapping']['daily_source_missing']==1
    assert cache['mapping']['daily_total']==0
    assert state['source_status']['mapping_status']=='review_required'



def test_late_concurrent_snapshot_cannot_overwrite_newer_success_or_status(harness):
    h=harness;older=snapshot(h.clock[0],records('C111111'));original=h.service.fetcher
    def delayed(token):
        h.service.fetcher=lambda _:snapshot('2026-09-27T10:01:00+08:00',records('C222222'))
        h.service.sync(h.wid,'u-manager','must-not-be-used')
        h.service.fetcher=original
        return older
    h.service.fetcher=delayed
    with pytest.raises(HTTPException) as exc:h.service.sync(h.wid,'u-manager')
    assert exc.value.status_code==409
    state,cache=h.read()
    assert cache['records'][0]['fields']['工程確認單編號']=='C222222'
    assert state['source_status']['status']=='ready' and cache['status']=='ready'
    assert not any(p['code']=='C111111' for p in state['projects'])


def test_older_snapshot_and_configuration_swap_fail_closed(harness):
    h=harness;before,cache=h.read()
    h.service.fetcher=lambda _:snapshot('2026-09-26T10:00:00+08:00',records('C111111'))
    with pytest.raises(HTTPException):h.service.sync(h.wid,'u-manager')
    assert h.read()[0]['projects']==before['projects']
    def swap(_):
        h.cfg['LARK_WORKER_ORGANIZATION']='another'
        return snapshot(h.clock[0],records('C111111'))
    h.service.fetcher=swap
    with pytest.raises(HTTPException):h.service.sync(h.wid,'u-manager')
    assert h.read()[1]['records']==cache['records']


def test_split_fetch_then_apply_preserves_projection_and_replay_ids(harness):
    h=harness
    raw=h.service.fetch(h.wid,'u-manager')
    before=h.read()[0]
    result=h.service.apply_snapshot(h.wid,raw,'u-manager')
    state=h.read()[0]
    assert result['mapping']==state['source_status']['mapping']
    assert [p['id'] for p in state['projects']]==[p['id'] for p in before['projects']]
    ids=[(p['id'],[t['id'] for n in p['nodes'] for t in n['tasks']]) for p in state['projects']]
    h.service.apply_snapshot(h.wid,h.service.fetch(h.wid,'u-manager'),'u-manager')
    assert [(p['id'],[t['id'] for n in p['nodes'] for t in n['tasks']]) for p in h.read()[0]['projects']]==ids


@pytest.mark.parametrize('actor_id',['u-manager',None])
def test_environment_changed_during_source_read_is_conflict(harness,actor_id):
    h=harness
    def fetch(token):
        with h.sessions.begin() as db:
            row=db.get(h.W,h.wid);state=storage.load(db,h.B,row)
            state['environment']='test';row.data=storage.save(db,h.B,h.wid,state)
        return snapshot(h.clock[0])
    h.service.fetcher=fetch
    with pytest.raises(HTTPException) as exc:h.service.sync(h.wid,actor_id,skip_unchanged=True)
    assert exc.value.status_code==409


def test_source_timer_disabled_by_live_read(harness):
    h=harness;h.cfg['LARK_LIVE_READ_ENABLED']='true';h.clock[0]='2026-09-27T12:00:00+08:00'
    before=h.read()
    assert h.service.run_due(h.wid) is None and not h.fetched
    assert h.read()==before


def test_older_read_cannot_overwrite_as_of_after_unchanged_refresh(harness):
    h=harness;h.clock[0]='2026-09-27T10:02:00+08:00'
    h.service.sync(h.wid,'u-manager',skip_unchanged=True)
    assert h.read()[1]['last_sync']==h.clock[0]
    h.service.fetcher=lambda token:snapshot('2026-09-27T10:01:00+08:00',records('C111111'))
    with pytest.raises(HTTPException) as exc:h.service.sync(h.wid,'u-manager',skip_unchanged=True)
    assert exc.value.status_code==409
    assert h.read()[1]['last_sync']==h.clock[0]
    assert not any(p['code']=='C111111' for p in h.read()[0]['projects'])


@pytest.mark.parametrize('flag', [None, 'false'])
def test_legacy_source_timer_defaults_to_300_seconds(harness, flag):
    h = harness
    if flag is not None:
        h.cfg['LARK_LIVE_READ_ENABLED'] = flag
    h.clock[0] = '2026-09-27T10:04:59+08:00'
    assert h.service.run_due(h.wid) is None and not h.fetched
    h.clock[0] = '2026-09-27T10:05:00+08:00'
    assert h.service.run_due(h.wid)['status'] == 'ready'
    assert len(h.fetched) == 1
