"""Weekly view contracts, using only synthetic Lark evidence."""
from datetime import datetime, timedelta, timezone
import pytest
from .live_read.datasets.weekly_attendance import project_people, fetch_week, week_window, PERSON_FIELDS
from .live_read.client import ALLOWED_GETS, ALLOWED_POSTS, ReadNeedsPermission, ReadFailure, ReadBlocked
from .live_read.people_attendance import PeopleAttendance
from .test_live_read_client import make_client
from .test_live_read_routes import harness, production_client
from .test_live_read_coordinator import SynchronousExecutor


def person(**extra):
    return dict(id='ou_one',name='合成人員',department='控制組',directory_status='employed',
                directory_source={'app_id':'app','record_id':'synthetic'},salary=999,phone='private',**extra)


def test_projection_and_unknown_group():
    p=project_people([person()], 'app')[0]
    assert set(p)==set(PERSON_FIELDS)
    assert p['in_service'] is True and p['group']=='控制組'
    assert project_people([person(department_source='work_category_unmapped')], 'app')[0]['group'] is None
    assert not project_people([person(directory_missing=True)], 'app')
    assert not project_people([person()], 'other-app')


def test_taipei_week_boundaries():
    sunday=datetime(2026,10,11,15,59,tzinfo=timezone.utc)
    monday=sunday+timedelta(minutes=1)
    assert week_window(now=sunday)==['2026-10-05','2026-10-06','2026-10-07','2026-10-08','2026-10-09','2026-10-10','2026-10-11']
    assert week_window(now=monday)[0]=='2026-10-12'
    assert week_window('2026-10-18')[-1]=='2026-10-18'


def test_attendance_allowlist_is_exact():
    gets={p for p in ALLOWED_GETS if '/attendance/' in p}
    posts={p for p in ALLOWED_POSTS if '/attendance/' in p}
    assert gets=={r'/attendance/v1/shifts/[^/]+',r'/attendance/v1/groups'}
    assert posts=={r'/attendance/v1/user_daily_shifts/query',r'/attendance/v1/user_tasks/query',r'/attendance/v1/user_approvals/query'}
    for method,path in [('POST','/attendance/v1/groups'),('GET','/attendance/v1/user_tasks/query'),('GET','/attendance/v1/groups/123'),('POST','/attendance/v1/user_tasks'),('DELETE','/attendance/v1/shifts/123')]:
        with make_client(lambda _: pytest.fail('unexpected transport')) as client:
            with pytest.raises(ReadBlocked):client.request(method,path)


class Adapter:
    def __init__(self,missing=False,invalid=False):self.calls=[];self.missing=missing;self.invalid=invalid
    def request(self,method,path,**kwargs):
        self.calls.append((method,path,kwargs))
        if self.missing:raise ReadNeedsPermission(['attendance:task:readonly'])
        if path=='/contact/v3/users/batch':return {'items':[{'open_id':'ou_one','user_id':'employee-one','phone':'not-projected'}]}
        if path=='/attendance/v1/groups':return {'group_list':[{'group_name':'synthetic'}],'has_more':False}
        if path=='/attendance/v1/user_tasks/query':return {'user_task_results':[{'user_id':'employee-one','day':20261012,'records':[{'check_in_result':'Normal','check_out_result':'Normal','location':'private'}]}],'invalid_user_ids':['employee-one'] if self.invalid else []}
        return {'user_approvals':[{'user_id':'employee-one','date':20261012,'trips':[{'approval_id':'trip1','start_time':'2026-10-12 09:00:00','end_time':'2026-10-13 00:00:00','reason':'private'}],'leaves':[]}]}


def test_weekly_evidence_is_projected_and_unknown_is_null():
    adapter=Adapter();view=fetch_week(adapter,[person()],'app','company',week_window('2026-10-12'),True)
    assert view['people'][0]['attendance']==['到班',None,None,None,None,None,None]
    assert view['status']=='incomplete'
    assert view['summary']['on_trip']==1 and view['summary']['on_leave']==0
    assert view['trips'][0]['end']=='2026-10-12'
    assert not any(secret in str(view) for secret in ('salary','phone','location','reason\': \'private','employee-one'))
    assert {c[:2] for c in adapter.calls}=={('GET','/contact/v3/users/batch'),('GET','/attendance/v1/groups'),('POST','/attendance/v1/user_tasks/query'),('POST','/attendance/v1/user_approvals/query')}
    invalid=fetch_week(Adapter(invalid=True),[person()],'app','company',week_window('2026-10-12'),True)
    assert invalid['summary']['on_trip'] is None and invalid['people'][0]['attendance'][0] is None
    partial=fetch_week(Adapter(),[person()],'app','company',week_window('2026-10-12'),False)
    assert all(v is None for v in partial['summary'].values())


def test_shared_cache_last_good_permission_and_week_isolation(harness):
    _,live,_,_,_=harness
    clock=[datetime(2026,10,14,tzinfo=timezone.utc)]
    reader=PeopleAttendance(live.Session,live.CacheRow,live,live.cfg,executor=SynchronousExecutor(),clock=lambda:clock[0])
    outcome=[fetch_week(Adapter(),[person()],'app','company',week_window('2026-10-12'),True)]
    def weekly(key):
        if isinstance(outcome[0],Exception):raise outcome[0]
        return {'fingerprint':'one','snapshot':outcome[0]}
    reader.refreshers['attendance']=weekly
    first=reader.view('lark-company','2026-10-12')
    assert first['people'] and first['as_of']
    clock[0]+=timedelta(seconds=301)
    outcome[0]=ReadNeedsPermission(['attendance:rule:readonly'])
    denied=reader.view('lark-company','2026-10-12')
    assert denied['status']=='needs-permission' and denied['missing_scopes']==['attendance:rule:readonly']
    assert denied['people']==first['people'] and all(v is None for v in denied['summary'].values())
    other=reader.view('lark-company','2026-10-19')
    assert other['people']==[] and other['week_start']=='2026-10-19'
    assert reader.view('demo-one')['status']=='not-connected'
    with pytest.raises(Exception):reader.view('lark-company','bad')


def test_route_hr_visibility_and_tenant_get_only(tmp_path):
    from .production_access import TENANT_READ_ROUTES
    assert '/api/people/attendance' in TENANT_READ_ROUTES
    app,client=production_client(tmp_path,enabled=False)
    # Use the existing fixture's manager login; the route still applies HR_VIEWERS.
    response=client.get('/api/people/attendance')
    assert response.status_code==200,response.text
    assert response.json()['status']=='not-connected'
    app.state.cfg['HR_VIEWERS']='someone-else'
    assert client.get('/api/people/attendance').status_code==403
    assert client.post('/api/people/attendance').status_code==405


def test_stale_snapshot_returns_while_refresh_is_blocked(harness):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    _,live,_,_,_=harness
    clock=[datetime(2026,10,14,tzinfo=timezone.utc)]
    reader=PeopleAttendance(live.Session,live.CacheRow,live,live.cfg,executor=SynchronousExecutor(),clock=lambda:clock[0])
    good=fetch_week(Adapter(),[person()],'app','company',week_window('2026-10-12'),True)
    reader.refreshers['attendance']=lambda key:dict(fingerprint='one',snapshot=good)
    initial=reader.view('lark-company','2026-10-12')
    clock[0]+=timedelta(seconds=301)
    started,release=Event(),Event()
    def slow(key):
        started.set()
        assert release.wait(5)
        return dict(fingerprint='two',snapshot=good)
    reader.refreshers['attendance']=slow
    reader.executor=ThreadPoolExecutor(max_workers=1)
    reader.roster_executor=reader.executor
    try:
        stale=reader.view('lark-company','2026-10-12')
        assert started.wait(2)
        assert stale['status']=='stale' and stale['people']==initial['people'] and stale['as_of']==initial['as_of']
        assert not release.is_set()
        release.set()
        reader.ensure('lark-company|2026-10-12','attendance',wait=True)
        assert reader.view('lark-company','2026-10-12')['status']=='incomplete'
    finally:
        release.set();reader.close()


@pytest.mark.parametrize('method,path,scope',[
    ('GET','/attendance/v1/groups','attendance:rule:readonly'),
    ('POST','/attendance/v1/user_tasks/query','attendance:task:readonly'),
    ('POST','/attendance/v1/user_approvals/query','attendance:task:readonly'),
])
def test_missing_scope_names_at_real_http_boundary(method,path,scope):
    import httpx
    from .test_live_read_client import responses
    _,handler=responses([httpx.Response(200,json={'code':99991672,'msg':'permission missing'})])
    with make_client(handler) as client:
        with pytest.raises(ReadNeedsPermission) as exc:client.request(method,path)
    assert exc.value.missing_scopes==[scope]


def test_tenant_reader_uses_same_route_and_hr_list(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from .test_auth_callback_roster import oauth,begin,finish
    app,_=production_client(tmp_path,enabled=False)
    oauth(monkeypatch)
    client=TestClient(app);assert finish(client,begin(client)).status_code==307
    assert client.get('/api/session').json()['access_mode']=='tenant-read'
    assert client.get('/api/people/attendance').status_code==200
    app.state.cfg['HR_VIEWERS']='someone-else'
    assert client.get('/api/people/attendance').status_code==403
    app.state.cfg['HR_VIEWERS']='u-tenant'
    assert client.get('/api/people/attendance').status_code==200
    assert client.post('/api/people/attendance').status_code in (403,405)


@pytest.mark.parametrize('attempt,expected,refreshing',[('busy','loading',True),('refreshing','loading',True),('error','read-failed',False)])
def test_unread_week_preserves_retry_or_failure(harness,monkeypatch,attempt,expected,refreshing):
    _,live,_,_,_=harness
    reader=PeopleAttendance(live.Session,live.CacheRow,live,live.cfg,executor=SynchronousExecutor())
    monkeypatch.setattr(reader,'ensure',lambda *args,**kwargs:{'status':attempt})
    view=reader.view('lark-company')
    assert view['status']==expected and view['refreshing'] is refreshing
    assert not view['incomplete'] and view['summary']['on_trip'] is None


@pytest.mark.parametrize('week',['0001-01-01','9999-12-31','bad','2026-04-06','2027-04-19'])
def test_week_range_rejected_before_refresh(harness,monkeypatch,week):
    from fastapi import HTTPException
    _,live,_,_,_=harness
    reader=PeopleAttendance(live.Session,live.CacheRow,live,live.cfg,executor=SynchronousExecutor(),clock=lambda:datetime(2026,10,14,tzinfo=timezone.utc))
    monkeypatch.setattr(reader,'ensure',lambda *args,**kwargs:pytest.fail('out-of-range date started refresh'))
    with pytest.raises(HTTPException) as exc:reader.view('lark-company',week)
    assert exc.value.status_code==422


@pytest.mark.parametrize('week',['2026-04-13','2027-04-12'])
def test_week_range_edges_are_supported(harness,monkeypatch,week):
    _,live,_,_,_=harness
    reader=PeopleAttendance(live.Session,live.CacheRow,live,live.cfg,executor=SynchronousExecutor(),clock=lambda:datetime(2026,10,14,tzinfo=timezone.utc))
    monkeypatch.setattr(reader,'ensure',lambda *args,**kwargs:{'status':'busy'})
    assert reader.view('lark-company',week)['week_start']==week


def test_weekly_background_refresh_waits_beyond_interactive_roster_timeout(harness):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from dataclasses import replace
    from types import SimpleNamespace

    _, live, _, _, _ = harness
    live.config = replace(live.config, blocking_timeout_seconds=.01, budget_seconds=.5)
    started, release = Event(), Event()
    def roster(wid):
        started.set()
        assert release.wait(2)
        return {'fingerprint': 'roster'}
    live.refreshers['roster'] = roster
    live.roster_executor = ThreadPoolExecutor(max_workers=1)
    expected = {'fingerprint': 'weekly', 'snapshot': {'status': 'incomplete'}}
    live.refreshers['attendance'] = SimpleNamespace(weekly=lambda *args: expected)
    reader = PeopleAttendance(live.Session, live.CacheRow, live, live.cfg)
    reader.config = live.config
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        live.ensure('lark-company', 'roster')
        assert started.wait(1)
        pending = pool.submit(reader._weekly, 'lark-company|2026-10-12')
        with pytest.raises(TimeoutError):
            pending.result(timeout=.05)
        assert not pending.done()
        release.set()
        assert pending.result(timeout=1) == expected
    finally:
        release.set()
        pool.shutdown(wait=True)
        reader.close()
        live.roster_executor.shutdown(wait=True)


def test_weekly_uses_successful_roster_that_finishes_after_soft_ttl(harness):
    from types import SimpleNamespace

    _, live, _, _, _ = harness
    clock = [datetime(2026, 10, 14, tzinfo=timezone.utc)]
    live.clock = lambda: clock[0]
    def roster(wid):
        clock[0] += timedelta(seconds=61)
        return {'fingerprint': 'roster'}
    live.refreshers['roster'] = roster
    expected = {'fingerprint': 'weekly', 'snapshot': {'status': 'incomplete'}}
    live.refreshers['attendance'] = SimpleNamespace(weekly=lambda *args: expected)
    reader = PeopleAttendance(live.Session, live.CacheRow, live, live.cfg)
    try:
        assert reader._weekly('lark-company|2026-10-12') == expected
    finally:
        reader.close()


def test_weekly_rejects_roster_beyond_existing_hard_validity(harness, monkeypatch):
    _, live, _, _, _ = harness
    monkeypatch.setattr(live, 'ensure', lambda *args, **kwargs: {
        'status': 'stale', 'age_seconds': 900, 'hard_max_age_seconds': 900})
    reader = PeopleAttendance(live.Session, live.CacheRow, live, live.cfg)
    try:
        with pytest.raises(ReadFailure, match='Roster has not been read'):
            reader._weekly('lark-company|2026-10-12')
    finally:
        reader.close()
