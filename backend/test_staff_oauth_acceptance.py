"""Local HTTP acceptance: synthetic roster and OAuth, never colleague sessions."""
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from .app import create_app, PersonRow


# Used only to simulate the gap between collection and test execution.
COLLECTION_TIME = datetime.now(timezone.utc)


@pytest.fixture(autouse=True, params=[0, 360], ids=['immediate', 'six-minute-collection-delay'])
def oauth_clock(request, monkeypatch):
    clock = COLLECTION_TIME + timedelta(seconds=request.param)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock.astimezone(tz) if tz else clock.replace(tzinfo=None)

    monkeypatch.setattr(__name__ + '.datetime', FrozenDateTime)
    monkeypatch.setattr('backend.production_access.datetime', FrozenDateTime)


@pytest.fixture
def staff(tmp_path, monkeypatch):
    app = create_app({'DATABASE_URL': f'sqlite:///{tmp_path}/staff.db',
        'UPLOAD_DIR': str(tmp_path/'uploads'), 'APP_ENV': 'development', 'DEMO_MODE': 'false',
        'SESSION_SECRET': 'staff-local-acceptance'*4, 'LARK_APP_ID': 'staff-app',
        'LARK_APP_SECRET': 'test-only', 'LARK_REDIRECT_URI': 'https://example.test/api/auth/lark/callback',
        'LARK_ALLOWED_TENANTS': 'company', 'LARK_WORKER_ORGANIZATION':'company',
        'LARK_WORKER_IDENTITY':'application'})
    person = {'id': 'ou_staff', 'name': 'Synthetic colleague', 'role': 'member',
        'active': True, 'capabilities': [], 'default_workspace': 'production',
        'identity_app_id': 'staff-app', 'directory_status': 'employed',
        'directory_last_seen_at': datetime.now(timezone.utc).isoformat(),
        'directory_source': {'app_id': 'staff-app', 'record_id': 'synthetic-record'}}
    with app.state.sessions.begin() as db:
        db.add(PersonRow(organization_id='lark-company', person_id=person['id'], data=person))
    class OAuth:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, **kwargs):
            return httpx.Response(200, json={'access_token': 'synthetic-token', 'expires_in': 3600}, request=httpx.Request('POST', url))
        def get(self, url, **kwargs):
            return httpx.Response(200, json={'data': {'open_id': 'ou_staff', 'name': 'Synthetic colleague', 'tenant_key': 'company'}}, request=httpx.Request('GET', url))
    monkeypatch.setattr('backend.app.httpx.Client', OAuth)
    client = TestClient(app)
    def login():
        response = client.get('/api/auth/lark/login', follow_redirects=False)
        nonce = parse_qs(urlparse(response.headers['location']).query)['state'][0]
        return client.get('/api/auth/lark/callback', params={'state': nonce, 'code': 'synthetic'}, follow_redirects=False)
    def change(patch):
        with app.state.sessions.begin() as db:
            row = db.get(PersonRow, ('lark-company', 'ou_staff'))
            row.data = {**row.data, **patch}
    return app, client, login, change


def test_fresh_staff_oauth_enters_production_without_admin_authority(staff):
    app, client, login, _ = staff
    assert login().status_code == 307
    session = client.get('/api/session').json()
    assert session['access_mode'] == 'normal'
    assert session['workspace_id'] == 'lark-company'
    assert session['user']['role'] == 'member'
    assert not session['user'].get('bootstrap_admin')
    ws = client.get('/api/workspace')
    assert ws.status_code == 200
    assert client.post('/api/people/sync').status_code == 403
    assert client.post('/api/actions', json={'action': 'admin_person', 'version': ws.json()['version'],
        'request_id': 'synthetic-escalation', 'payload': {'id': 'ou_staff', 'role': 'manager'}}).status_code == 403
    with app.state.sessions() as db:
        person = db.get(PersonRow, ('lark-company', 'ou_staff')).data
        assert person['role'] == 'member'
        assert person['oauth_identity']['open_id'] == 'ou_staff'


@pytest.mark.parametrize('role',['member','manager'])
def test_fresh_oauth_ignores_historical_test_default(staff,role):
    app,client,login,change=staff
    change({'role':role,'default_workspace':'test'})
    assert login().status_code==307
    assert client.get('/api/session').json()['workspace_id']=='lark-company'
    assert client.get('/api/workspace').status_code==200
    if role=='manager':
        response=client.post('/api/workspace/switch',json={'environment':'test'})
        assert response.status_code==200
        assert client.get('/api/session').json()['workspace_id']=='test-lark-company'
        assert login().status_code==307
        assert client.get('/api/session').json()['workspace_id']=='lark-company'


@pytest.mark.parametrize('patch', [
    {'active': False}, {'directory_status': 'left'}, {'directory_status': 'unknown'},
    {'directory_missing': True}, {'identity_app_id': 'another-app'},
    {'directory_source': {'app_id': 'another-app', 'record_id': 'synthetic-record'}},
    {'directory_last_seen_at': (datetime.now(timezone.utc)-timedelta(seconds=901)).isoformat()},
])
def test_existing_staff_session_immediately_rechecks_roster(staff, patch):
    _, client, login, change = staff
    assert login().status_code == 307
    assert client.get('/api/workspace').status_code == 200
    change(patch)
    assert client.get('/api/workspace').status_code == 403
    assert client.get('/api/session').json()['user'] is None


@pytest.mark.parametrize('patch', [
    {'active': False}, {'directory_status': 'left'}, {'directory_missing': True},
    {'identity_app_id': 'another-app'},
])
def test_oauth_does_not_reactivate_or_remap_unverified_staff(staff, patch):
    _, client, login, change = staff
    change(patch)
    assert login().status_code in (303, 307, 403)
    assert client.get('/api/session').json()['user'] is None
    assert client.get('/api/workspace').status_code == 401


@pytest.mark.parametrize('stamp',[
    timedelta(seconds=-901),
    timedelta(minutes=5),
    'invalid',None,
])
def test_oauth_rejects_stale_proof_before_creating_session(staff,stamp):
    from sqlalchemy import select
    from .app import AuthRow
    app,client,login,change=staff
    if isinstance(stamp,timedelta):
        stamp=(datetime.now(timezone.utc)+stamp).isoformat()
    change({'directory_last_seen_at':stamp})
    response=login()
    assert response.status_code==403
    assert 'meegle_session' not in client.cookies
    with app.state.sessions() as db:
        assert not [row for row in db.scalars(select(AuthRow)) if row.data.get('uid')=='ou_staff']
    assert client.get('/api/workspace').status_code==401
