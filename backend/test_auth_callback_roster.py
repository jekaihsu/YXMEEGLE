"""Tenant OAuth admits reads without fetching a roster or granting business authority."""
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from .app import PersonRow, AuthRow
from .test_live_read_routes import production_client

HTML = {'accept': 'text/html'}
JSON = {'accept': 'application/json'}


def stale(app, oid='u-manager', **fields):
    with app.state.sessions.begin() as db:
        p = db.get(PersonRow, ('lark-company', oid))
        p.data = {**p.data, 'directory_last_seen_at': (datetime.now(timezone.utc) - timedelta(seconds=901)).isoformat(), **fields}


def oauth(monkeypatch, *, open_id='u-tenant', tenant='company', scope=''):
    class OAuth:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, **kwargs):
            return httpx.Response(200, json={'access_token': 'synthetic', 'expires_in': 3600, 'scope': scope}, request=httpx.Request('POST', url))
        def get(self, url, **kwargs):
            return httpx.Response(200, json={'data': {'open_id': open_id, 'name': 'Synthetic', 'tenant_key': tenant}}, request=httpx.Request('GET', url))
    monkeypatch.setattr('backend.app.httpx.Client', OAuth)


def begin(client, next='/', headers=None):
    r=client.get('/api/auth/lark/login',params={'next':next},headers=headers or {},follow_redirects=False)
    return parse_qs(urlparse(r.headers['location']).query)['state'][0]


def finish(client,saved_state,**params):
    return client.get('/api/auth/lark/callback',params={'state':saved_state,'code':'synthetic',**params},follow_redirects=False)


@pytest.mark.parametrize('fields',[{}, {'directory_status':'employed'}])
def test_stale_roster_and_failed_reads_never_block_login(tmp_path,monkeypatch,fields):
    app,_=production_client(tmp_path);stale(app,role='member',authz_version=1,**fields)
    oauth(monkeypatch,open_id='u-manager')
    calls=[]
    def unavailable(*args,**kwargs):
        calls.append(args)
        raise RuntimeError('private upstream failure')
    monkeypatch.setattr(app.state.live_read,'ensure',unavailable)
    client=TestClient(app)
    r=finish(client,begin(client))
    assert r.status_code==307 and r.headers['location']=='http://testserver/'
    assert calls==[]
    cookie=next(c for c in r.headers.get_list('set-cookie') if c.startswith('meegle_session='))
    assert 'Secure' not in cookie and 'HttpOnly' in cookie and 'SameSite=lax' in cookie
    # Status is a read-only cache view; neither stale nor absent roster is a login gate.
    assert client.get('/api/live/status').status_code==200
    assert client.get('/api/session').json()['access_mode']=='tenant-read'
    assert 'lark_oauth_state' not in client.cookies


def test_unknown_tenant_member_reads_but_cannot_use_privileged_routes(tmp_path,monkeypatch):
    app,_=production_client(tmp_path);oauth(monkeypatch)
    client=TestClient(app);assert finish(client,begin(client)).status_code==307
    session=client.get('/api/session').json()
    assert session['access_mode']=='tenant-read' and session['user']['role']=='member'
    assert session['user']['capabilities']==[]
    for path in ('/api/workspace','/api/sources','/api/live/status','/api/company-dashboard','/api/manager-overview'):
        response=client.get(path)
        assert response.status_code==200,(path,response.text)
    for method,path,body in [
        ('POST','/api/people/sync',{}),('POST','/api/attendance/sync',{}),
        ('POST','/api/actions',{'action':'admin_person','version':1,'request_id':'tenant-denied'}),
        ('POST','/api/workspace/switch',{'environment':'test'}),
        ('POST','/api/live/refresh',{'datasets':['roster'],'force':True}),
        ('GET','/api/admin/runtime-health',None),('GET','/api/admin/index-health',None),
        ('POST','/api/native-approvals/definitions/verify',{'version':1}),
        ('POST','/api/native-approvals/financial/request',{}),
        ('POST','/api/admin/worker/run',{}),
    ]:
        response=client.request(method,path,json=body)
        assert response.status_code==403,(path,response.text)
    with app.state.sessions() as db:
        p=db.get(PersonRow,('lark-company','u-tenant')).data
        assert p['role']=='member' and p['capabilities']==[] and not p.get('bootstrap_admin')


@pytest.mark.parametrize('tenant,expected',[('company',307),('other',403)])
def test_tenant_allowlist(tmp_path,monkeypatch,tenant,expected):
    app,_=production_client(tmp_path);oauth(monkeypatch,tenant=tenant)
    client=TestClient(app);response=finish(client,begin(client))
    assert response.status_code==expected
    assert ('meegle_session' in client.cookies)==(expected==307)
    assert 'lark_oauth_state' not in client.cookies


@pytest.mark.parametrize('params',[{'state':'bad'},{'error':'access_denied'},{'code':''}])
def test_bad_state_cancelled_or_missing_code_never_creates_session(tmp_path,monkeypatch,params):
    app,_=production_client(tmp_path);oauth(monkeypatch)
    client=TestClient(app);state=begin(client)
    response=finish(client,state,**params)
    assert response.status_code in (303,400)
    assert 'meegle_session' not in client.cookies and 'lark_oauth_state' not in client.cookies
    if params.get('error'): assert response.headers['location']=='/?auth_error=authorization_denied'


@pytest.mark.parametrize('next',['https://evil.example','//evil.example','/\\evil.example','/\nLocation:evil'])
def test_login_redirect_rejects_unsafe_targets(tmp_path,next):
    app,_=production_client(tmp_path);client=TestClient(app)
    assert client.get('/api/auth/lark/login',params={'next':next},follow_redirects=False).status_code==422


def test_cookie_attributes_signature_public_origin_and_replay(tmp_path,monkeypatch):
    app,_=production_client(tmp_path);oauth(monkeypatch)
    client=TestClient(app,base_url='https://internal')
    headers={'x-forwarded-host':'public.example','x-forwarded-proto':'https'}
    state=begin(client,'/people?tab=all',headers)
    state_cookie=client.cookies['lark_oauth_state']
    response=client.get('/api/auth/lark/callback',params={'state':state,'code':'synthetic'},headers=headers,follow_redirects=False)
    assert response.headers['location']=='https://public.example/people?tab=all'
    cookie=next(c for c in response.headers.get_list('set-cookie') if c.startswith('meegle_session='))
    for part in ('HttpOnly','Secure','SameSite=lax','Path=/','Max-Age=604800'): assert part in cookie
    # A SHA256 HMAC signature is 32 bytes encoded without padding.
    raw=client.cookies['meegle_session'];assert len(raw.split('.')[-1])==43
    with app.state.sessions() as db:
        data=app.state.signer.loads(raw);auth=db.get(AuthRow,data['sid']).data
        assert auth['expires']-auth['token_expires']>600000
    client.cookies.set('lark_oauth_state',state_cookie)
    replay=finish(client,state)
    assert replay.status_code==400 and '已使用' in replay.json()['detail']
    client.cookies.clear();client.cookies.set('meegle_session',raw[:raw.rfind('.')+1]+('A' if raw[raw.rfind('.')+1]!='A' else 'B')+raw[raw.rfind('.')+2:])
    assert client.get('/api/workspace').status_code==401


def test_inactive_person_stays_denied(tmp_path,monkeypatch):
    app,_=production_client(tmp_path);stale(app,active=False);oauth(monkeypatch,open_id='u-manager')
    client=TestClient(app);response=finish(client,begin(client))
    assert response.status_code==403 and 'meegle_session' not in client.cookies


def test_hr_viewers_list_hides_people_and_attendance(tmp_path,monkeypatch):
    app,_=production_client(tmp_path);oauth(monkeypatch)
    client=TestClient(app);assert finish(client,begin(client)).status_code==307
    assert len(client.get('/api/session').json()['users'])>1
    app.state.cfg['HR_VIEWERS']='someone-else'
    assert [u['id'] for u in client.get('/api/session').json()['users']]==['u-tenant']
    ws=client.get('/api/workspace').json()
    assert ws['hr_view_allowed'] is False and ws['work_schedules']==[]
    assert [u['id'] for u in ws['users']]==['u-tenant']
    app.state.cfg['HR_VIEWERS']='u-tenant'
    assert client.get('/api/workspace').json()['hr_view_allowed'] is True


def test_app_url_origin_wins_and_callback_revalidates_saved_next(tmp_path,monkeypatch):
    app,_=production_client(tmp_path);oauth(monkeypatch)
    app.state.cfg['APP_URL']='https://public.example/'
    client=TestClient(app,base_url='https://internal');state=begin(client)
    with app.state.sessions.begin() as db:
        row=db.get(AuthRow,'oauth-'+state)
        row.data={**row.data,'next':'//evil.example'}
    response=finish(client,state)
    assert response.status_code==307 and response.headers['location']=='https://public.example/'


def test_startup_warms_all_datasets_without_waiting_for_lark(tmp_path):
    from threading import Event
    from .app import create_app
    release=Event();roster_started=Event();attendance_started=Event()
    app=create_app({'DATABASE_URL':f'sqlite:///{tmp_path}/warm.db','UPLOAD_DIR':str(tmp_path/'uploads'),
        'DEMO_MODE':'false','LARK_WORKER_ORGANIZATION':'company','LARK_ALLOWED_TENANTS':'company',
        'LARK_WORKER_IDENTITY':'application','LARK_LIVE_READ_ENABLED':'true'})
    def roster(wid):
        roster_started.set();assert release.wait(5)
        return {'fingerprint':'roster'}
    def attendance(wid):
        attendance_started.set();assert release.wait(5)
        return {'fingerprint':'attendance'}
    app.state.live_read.refreshers={'roster':roster,'attendance':attendance,'sources':lambda wid:{'fingerprint':'sources'}}
    try:
        with TestClient(app) as client:
            try:
                assert roster_started.wait(2) and attendance_started.wait(2)
                assert client.get('/api/health').status_code==200
                assert app.state.live_read.status('lark-company')['datasets']['roster']['status']=='refreshing'
            finally: release.set()
    finally: release.set()


@pytest.mark.parametrize('fields', [
    {'directory_status': 'left', 'active': False},
    {'directory_missing': True},
    {'active': False},
    {'directory_status': 'left', 'active': None},
])
def test_departed_missing_or_inactive_person_loses_tenant_reads(tmp_path, monkeypatch, fields):
    app, _ = production_client(tmp_path)
    oauth(monkeypatch)
    client = TestClient(app)
    assert finish(client, begin(client)).status_code == 307
    with app.state.sessions.begin() as db:
        person = db.get(PersonRow, ('lark-company', 'u-tenant'))
        data = {**person.data, **fields}
        if fields.get('active', True) is None:
            data.pop('active', None)
        person.data = data
    response = client.get('/api/workspace')
    assert response.status_code == 403
    assert client.get('/api/session').json()['user'] is None


def test_bootstrap_manager_keeps_roster_recovery_after_oauth(tmp_path, monkeypatch):
    app, _ = production_client(tmp_path, enabled=False)
    stale(app, bootstrap_admin=True)
    oauth(monkeypatch, open_id='u-manager')
    client = TestClient(app)
    assert finish(client, begin(client)).status_code == 307
    session = client.get('/api/session').json()
    assert session['access_mode'] == 'recovery' and session['user']['id'] == 'u-manager'
    calls = []
    def sync(wid, actor):
        calls.append((wid, actor))
        return {'status': 'ready'}
    monkeypatch.setattr(app.state.people_directory, 'sync', sync)
    assert client.post('/api/people/sync').status_code == 200
    assert calls == [('lark-company', 'u-manager')]
    assert client.get('/api/admin/runtime-health').status_code == 200
    assert client.post('/api/actions', json={'action': 'admin_person', 'version': 1, 'request_id': 'recovery'}).status_code == 403


def test_tenant_only_identity_cannot_read_test_workspace(tmp_path, monkeypatch):
    app, _ = production_client(tmp_path, enabled=False)
    oauth(monkeypatch)
    client = TestClient(app)
    assert finish(client, begin(client)).status_code == 307
    cookie = app.state.signer.loads(client.cookies['meegle_session'])
    with app.state.sessions.begin() as db:
        auth = db.get(AuthRow, cookie['sid'])
        auth.data = {**auth.data, 'wid': 'test-lark-company'}
    client.cookies.clear()
    client.cookies.set('meegle_session', app.state.signer.dumps({**cookie, 'wid': 'test-lark-company'}))
    assert client.get('/api/workspace').status_code == 403
    assert client.get('/api/session').json()['user'] is None
