"""Demand refreshers exercise fake HTTP only and the real projection services."""
from copy import deepcopy
from datetime import datetime, timedelta

import httpx
import pytest
from fastapi import HTTPException

from . import source_sync, storage
from .live_read.client import LiveLarkClient, ReadBlocked
from .live_read.coordinator import RefreshCoordinator
from .live_read.datasets import build_refreshers
from .live_read.datasets.sources import SourcesRefresher
from .live_read.datasets.roster import RosterRefresher
from .live_read.datasets.attendance import AttendanceRefresher
from .live_read.token_cache import TenantTokenCache
from .people_directory import PeopleDirectoryService
from .test_people_directory import snapshot as roster_snapshot
from .test_source_sync import harness, records, snapshot
from .test_attendance_service import make


class Bucket:
    def acquire(self, deadline): pass


def factory(h, handler=None):
    h.cfg['LARK_APP_SECRET']='synthetic-secret'
    requests=[]
    def transport(request):
        requests.append(request)
        if request.url.path.endswith('/tenant_access_token/internal'):
            return httpx.Response(200,json={'tenant_access_token':'synthetic-token','expire':7200})
        return httpx.Response(200,json={'code':0,'data':handler(request) if handler else {}})
    cache=TenantTokenCache()
    def create(cfg,**kwargs):
        return LiveLarkClient(cfg,transport=httpx.MockTransport(transport),
                              token_cache=cache,bucket=Bucket(),**kwargs)
    return create,requests


def test_equal_sources_advance_metadata_without_reprojecting_entities(harness):
    h=harness;h.cfg['LARK_LIVE_READ_ENABLED']='true';create,_=factory(h)
    refresh=SourcesRefresher(h.service,create)
    clock=[datetime.fromisoformat(h.clock[0])]
    coordinator=RefreshCoordinator(h.sessions,h.C,{'sources':refresh},h.cfg,clock=lambda:clock[0])
    try:
        first=coordinator.ensure(h.wid,'sources',wait=True)
        before,_=h.read()
        h.clock[0]='2026-09-27T10:01:00+08:00';clock[0]+=timedelta(seconds=60)
        second=coordinator.ensure(h.wid,'sources',wait=True)
        after,cache=h.read()
        assert after['version']==before['version']+1
        assert after['projects']==before['projects'] and after['events']==before['events']
        assert after['source_status']['sync_revision']==before['source_status']['sync_revision']
        assert after['source_status']['last_sync']==cache['last_sync']==h.clock[0]
        assert after['source_status']['last_attempt_at']==cache['last_attempt_at']==h.clock[0]
        assert second['as_of']!=first['as_of'] and cache['as_of']==h.clock[0]
        assert second['changed_at']==first['changed_at']
        assert second['fingerprint']==first['fingerprint']
    finally:coordinator.executor.shutdown()


def test_changed_sources_apply_existing_projection_and_preserve_ids(harness):
    h=harness;create,_=factory(h);refresh=SourcesRefresher(h.service,create)
    first=refresh(h.wid);before,_=h.read()
    changed=records();changed[0]['fields']['備註']='synthetic changed note'
    h.clock[0]='2026-09-27T10:01:00+08:00'
    h.service.fetcher=lambda token:snapshot(h.clock[0],deepcopy(changed))
    second=refresh(h.wid);after,cache=h.read()
    assert second['fingerprint']!=first['fingerprint']
    assert after['source_status']['sync_revision']==before['source_status'].get('sync_revision',0)+1
    assert [p['id'] for p in after['projects']]==[p['id'] for p in before['projects']]
    assert cache['mapping']==after['source_status']['mapping']
    # Reapply the same read through manual sync: its projection is identical.
    h.service.sync(h.wid,'u-manager')
    assert h.read()[0]['projects']==after['projects']


def test_sources_live_http_is_permission_wrapped_on_every_call(harness,monkeypatch):
    h=harness;create,requests=factory(h);h.service.fetcher=None
    def fetch(token,*,cfg,client):
        client.request('GET','/bitable/v1/apps/test/tables')
        with h.sessions.begin() as db:
            row=db.get(h.W,h.wid);state=storage.load(db,h.B,row)
            state['source_connection']['enabled']=False;row.data=storage.save(db,h.B,h.wid,state)
        client.request('GET','/bitable/v1/apps/test/tables/fields')
        return snapshot(h.clock[0])
    monkeypatch.setattr(source_sync,'fetch_sources',fetch)
    with pytest.raises(HTTPException):SourcesRefresher(h.service,create)(h.wid)
    assert len(requests)==2  # token mint and first data read; revoked call never sends
    assert h.read()[0]['source_status'].get('sync_revision',0)==0


def test_partial_equal_sources_are_rejected_before_skip(harness):
    h=harness;create,_=factory(h);refresh=SourcesRefresher(h.service,create);refresh(h.wid)
    prior=h.read()[0]['source_status'].get('sync_revision',0)
    partial=snapshot(h.clock[0]);partial['tables'][0]['status']='partial'
    h.service.fetcher=lambda token:partial
    with pytest.raises(HTTPException) as exc:refresh(h.wid)
    assert exc.value.status_code==409
    assert h.read()[0]['source_status'].get('sync_revision',0)==prior


def test_roster_equal_content_still_renews_admission_timestamps(harness):
    h=harness;create,requests=factory(h);clock=[h.clock[0]]
    def fetch(adapter,app_id):
        adapter.request('GET','/bitable/v1/apps/roster/tables')
        result=roster_snapshot();result['fetched_at']=clock[0];return result
    service=PeopleDirectoryService(h.sessions,h.W,h.B,h.P,h.cfg,fetcher=fetch)
    with h.sessions.begin() as db:
        row=db.get(h.W,h.wid);state=storage.load(db,h.B,row)
        state['people_directory_connection']=deepcopy(state['source_connection'])
        row.data=storage.save(db,h.B,h.wid,state)
    refresh=RosterRefresher(service,create)
    first=refresh(h.wid);clock[0]='2026-09-27T10:01:00+08:00';second=refresh(h.wid)
    assert first['fingerprint']==second['fingerprint'] and second['lark']['calls']==1
    with h.sessions() as db:person=db.get(h.P,(h.wid,'ou_new')).data
    assert person['directory_last_seen_at']==clock[0]
    assert h.read()[0]['people_directory_status']['sync_revision']==2
    assert len(requests)==3


def test_attendance_scoped_query_uses_live_client_and_retains_manual_override(harness):
    h=harness;service,_=make(h)
    def response(request):
        if request.method=='POST':return {'user_daily_shifts':[]}
        return {}
    create,requests=factory(h,response)
    with h.sessions.begin() as db:
        row=db.get(h.W,h.wid);state=storage.load(db,h.B,row)
        state['attendance_schedule_connection']=deepcopy(state['source_connection'])
        today=datetime.now().date().isoformat()
        state['work_schedules'].append({'id':'manual','user_id':'u-manager','day':today,
            'basis':'company_schedule','end_time':'17:00','active':True,'version':1})
        row.data=storage.save(db,h.B,h.wid,state)
    refresh=AttendanceRefresher(service,create);first=refresh(h.wid);second=refresh(h.wid)
    assert first['fingerprint']==second['fingerprint']
    assert next(r for r in h.read()[0]['work_schedules'] if r['id']=='manual')['end_time']=='17:00'
    assert second['lark']['calls']==1
    assert [r.method for r in requests]==['POST','POST','POST']
    client=create(h.cfg,allowed_posts=refresh.allowed_posts)
    try:
        with pytest.raises(ReadBlocked):client.request('POST','/attendance/v1/shifts/create')
    finally:client.close()


@pytest.mark.parametrize('wid',['demo-one','test-lark-tenant'])
def test_isolated_workspace_never_creates_live_transport(harness,wid):
    h=harness;h.cfg['LARK_LIVE_READ_ENABLED']='true'
    def deny(*args,**kwargs):raise AssertionError('isolated workspace called Lark')
    refreshers=build_refreshers(h.service,None,None,client_factory=deny)
    coordinator=RefreshCoordinator(h.sessions,h.C,refreshers,h.cfg)
    try:
        for dataset in refreshers:
            assert coordinator.ensure(wid,dataset,wait=True)['status']=='unconfigured'
    finally:coordinator.executor.shutdown()


def test_real_source_service_cannot_commit_an_expired_refresh_owner(harness):
    from concurrent.futures import ThreadPoolExecutor
    from .live_read.coordinator import LeaseLost
    h = harness
    h.cfg['LARK_LIVE_READ_ENABLED'] = 'true'
    create, _ = factory(h)
    clock = [datetime.fromisoformat(h.clock[0])]
    coordinator = RefreshCoordinator(h.sessions, h.C, {'sources': SourcesRefresher(h.service, create)},
                                     h.cfg, clock=lambda: clock[0])
    before, cached = h.read()
    def fetch(token):
        clock[0] += timedelta(seconds=120)
        h.clock[0] = clock[0].isoformat()
        with ThreadPoolExecutor(max_workers=1) as other:
            assert other.submit(coordinator._claim, coordinator._key(h.wid, 'sources'),
                                clock[0], 'sources', True).result()
        changed = records()
        changed[0]['fields']['備註'] = 'stale fetched value'
        return snapshot(h.clock[0], changed)
    h.service.fetcher = fetch
    try:
        with pytest.raises(LeaseLost):
            coordinator.ensure(h.wid, 'sources', wait=True)
        after, current = h.read()
        assert after == before
        assert current == cached
    finally:
        coordinator.close()


def test_equal_sources_reproject_after_workspace_diverges_from_cache(harness):
    h = harness
    create, _ = factory(h)
    refresh = SourcesRefresher(h.service, create)
    first = refresh(h.wid)
    original, _ = h.read()
    with h.sessions.begin() as db:
        row = db.get(h.W, h.wid)
        state = storage.load(db, h.B, row)
        state['projects'] = []
        row.data = storage.save(db, h.B, h.wid, state)
    assert h.read()[0]['projects'] == []
    h.clock[0] = '2026-09-27T10:01:00+08:00'
    second = refresh(h.wid)
    restored, cache = h.read()
    assert second['fingerprint'] == first['fingerprint']
    assert len(restored['projects']) == len(original['projects']) > 0
    assert restored['source_status']['sync_revision'] == original['source_status']['sync_revision'] + 1
    assert restored['source_status']['last_sync'] == cache['last_sync'] == h.clock[0]


def test_equal_sources_reproject_after_import_version_changes(harness, monkeypatch):
    h = harness
    create, _ = factory(h)
    refresh = SourcesRefresher(h.service, create)
    refresh(h.wid)
    original, _ = h.read()
    monkeypatch.setattr(source_sync, 'SOURCE_PROJECTION_VERSION', 'next-import-version')
    h.clock[0] = '2026-09-27T10:01:00+08:00'
    refresh(h.wid)
    state, _ = h.read()
    assert state['source_status']['sync_revision'] == original['source_status']['sync_revision'] + 1


def test_equal_sources_reproject_after_policy_decision_changes(harness):
    h = harness
    create, _ = factory(h)
    refresh = SourcesRefresher(h.service, create)
    refresh(h.wid)
    original, _ = h.read()
    with h.sessions.begin() as db:
        row = db.get(h.W, h.wid)
        state = storage.load(db, h.B, row)
        state['projects'][0]['case_visibility'] = 'excluded_history'
        row.data = storage.save(db, h.B, h.wid, state)
    h.clock[0] = '2026-09-27T10:01:00+08:00'
    refresh(h.wid)
    state, _ = h.read()
    assert state['source_status']['sync_revision'] == original['source_status']['sync_revision'] + 1
    assert state['projects'][0]['case_visibility'] == 'source_reference'
    assert state['projects'][0]['id'] == original['projects'][0]['id']
