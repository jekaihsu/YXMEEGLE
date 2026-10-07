"""Sibling mutation routes reject malformed bodies before state or remote work."""
import httpx
import pytest
from . import features
from .test_backend import app, client
from .app import WorkspaceRow, BusinessRow
from . import storage
from .test_production_access import company, _snapshot


FORMAL_ROUTES = [
    '/api/approvals/x/refresh',
    '/api/learning/sync',
    '/api/delegations/verify-approval',
    '/api/attendance/sync',
    '/api/files/x/store-lark',
    '/api/learning/mappings/verify',
    '/api/projects/x/nodes/x/inputs',
    '/api/input-revisions/x/reconcile',
    '/api/input-revisions/x/dispose-not-created',
    '/api/input-mappings/x/verify',
]
INVALID_BODIES = [b'[]', b'null', b'{bad', b'1', b'"x"', b'true', b'', b'\xff']


@pytest.fixture
def formal_api(tmp_path, monkeypatch):
    app, client = company(tmp_path)
    cookie = client.cookies.get('meegle_session')
    client.cookies.clear()
    client.cookies.set('meegle_session', cookie, domain='testserver.local', path='/')
    assert client.post('/api/workspace/switch', json={'environment': 'production'}).status_code == 200
    # Exercise the paused learning routes beyond their feature gate.
    monkeypatch.setattr(features, 'FEATURE_LEARNING', True)
    def forbidden(*args, **kwargs):
        pytest.fail('Invalid body must not initiate remote work')
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', forbidden)
    monkeypatch.setattr(app.state.attendance_schedule, 'sync', forbidden)
    return app, client


@pytest.mark.parametrize('path', FORMAL_ROUTES)
@pytest.mark.parametrize('raw', INVALID_BODIES)
def test_formal_siblings_reject_invalid_objects_without_changes(formal_api, path, raw):
    app, client = formal_api
    before = _snapshot(app, client)
    response = client.post(path, content=raw, headers={'content-type': 'application/json'})
    assert response.status_code == 422, response.text
    assert _snapshot(app, client) == before


@pytest.mark.parametrize('path', [p for p in FORMAL_ROUTES if p != '/api/attendance/sync'])
@pytest.mark.parametrize('raw', [b'{}', b'{"version":null}', b'{"version":true}'])
def test_formal_siblings_reject_missing_or_invalid_versions(formal_api, path, raw):
    app, client = formal_api
    before = _snapshot(app, client)
    response = client.post(path, content=raw, headers={'content-type': 'application/json'})
    assert response.status_code == 422, response.text
    assert _snapshot(app, client) == before


@pytest.mark.parametrize('raw', INVALID_BODIES + [b'{}'])
def test_demo_session_rejects_invalid_body_without_identity_or_state_change(client, raw):
    cookie = client.cookies.get('meegle_session')
    wid = client.app.state.signer.loads(cookie)['wid']
    def snapshot():
        with client.app.state.sessions() as db:
            row = db.get(WorkspaceRow, wid)
            return row.version, storage.load(db, BusinessRow, row), client.cookies.get('meegle_session')
    before = snapshot()
    response = client.post('/api/demo/session', content=raw, headers={'content-type': 'application/json'})
    assert 400 <= response.status_code < 500, response.text
    assert snapshot() == before


def test_attendance_object_can_omit_optional_dates(formal_api, monkeypatch):
    app, client = formal_api
    calls = []
    monkeypatch.setattr(app.state.attendance_schedule, 'sync',
                        lambda *args: calls.append(args) or {'status': 'ready'})
    assert client.post('/api/attendance/sync', json={}).status_code == 200
    assert calls == [('lark-company', 'u-manager', None, None)]


def test_learning_mapping_rejects_non_object_mapping(formal_api):
    app, client = formal_api
    before = _snapshot(app, client)
    response = client.post('/api/learning/mappings/verify', json={'version': 1, 'mapping': [1]})
    assert response.status_code == 422
    assert _snapshot(app, client) == before
