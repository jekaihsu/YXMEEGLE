"""Long-lived app sessions must not send expired user tokens to Lark."""
import time
from types import SimpleNamespace

import httpx
import pytest

from . import storage
from .app import AuthRow, WorkspaceRow, BusinessRow
from .test_live_read_routes import production_client

ROUTES = ['/api/sources/sync', '/api/approvals/a1/refresh', '/api/learning/sync', '/api/delegations/verify-approval']


@pytest.fixture
def token_client(tmp_path, monkeypatch):
    monkeypatch.setattr('backend.features.FEATURE_LEARNING', True)
    app, client = production_client(tmp_path, enabled=False)
    with app.state.sessions.begin() as db:
        auth = db.get(AuthRow, 'sid')
        auth.data = {**auth.data, 'access_token': 'synthetic-user-token', 'token_expires': time.time() + 3600}
        row = db.get(WorkspaceRow, 'lark-company')
        state = storage.load(db, BusinessRow, row)
        state['projects'][0]['pm_id'] = 'u-manager'
        state['projects'][0].update(case_visibility='new_case', execution_system='workbench')
        state['users'].append({'id': 'ou_staff', 'name': 'Staff', 'active': True, 'role': 'member', 'capabilities': []})
        state['approvals'] = [{'id': 'a1', 'project_id': 'p1', 'type': 'change', 'status': 'draft', 'history': []}]
        row.data = storage.save(db, BusinessRow, row.id, state)
    return app, client


@pytest.mark.parametrize('path', ROUTES)
@pytest.mark.parametrize('expiry', ['expired', 'missing'])
def test_expired_or_missing_user_token_requires_sign_in(token_client, monkeypatch, path, expiry):
    app, client = token_client
    with app.state.sessions.begin() as db:
        auth = db.get(AuthRow, 'sid')
        data = {**auth.data, 'token_expires': time.time() - 1}
        if expiry == 'missing': data.pop('token_expires')
        auth.data = data
    def no_remote(*args, **kwargs):
        pytest.fail('Expired tokens must be rejected before remote work')
    monkeypatch.setattr(app.state.source_sync, 'sync', no_remote)
    monkeypatch.setattr('backend.app.httpx.Client', no_remote)
    monkeypatch.setattr('backend.lark_adapter.LarkAdapter', no_remote)
    response = client.post(path, json={'version': 1, 'instance_code': 'leave-test'})
    assert response.status_code == 401, response.text
    assert response.json() == {'code': 'user_token_expired', 'detail': 'Lark 授權已過期，請重新登入'}


@pytest.mark.parametrize('path', ROUTES)
def test_valid_user_token_preserves_existing_route_behavior(token_client, monkeypatch, path):
    from .learning_sources import LEAVE_DEFINITION, DELEGATE_FIELD
    app, client = token_client
    tokens = []
    snapshot = {'status': 'ready', 'configured': True, 'records': [], 'tables': []}
    def sync(wid, actor, token):
        tokens.append(token)
        return snapshot
    monkeypatch.setattr(app.state.source_sync, 'sync', sync)
    remote = {'definition_code': LEAVE_DEFINITION, 'instance_code': 'leave-test',
              'open_id': 'ou_staff', 'status': 'APPROVED', 'form': [
                  {'id': DELEGATE_FIELD, 'value': [{'id': 'ou_staff'}]},
                  {'id': 'widgetLeaveGroupStartTime', 'value': '2026-10-09T08:00:00+08:00'},
                  {'id': 'widgetLeaveGroupEndTime', 'value': '2026-10-09T17:00:00+08:00'},
              ]}
    class Provider:
        def __init__(self, token):
            tokens.append(token)
            self.client = SimpleNamespace(close=lambda: None)
        def request(self, *args, **kwargs): return remote
    class ApprovalProvider:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, url, headers, params):
            tokens.append(headers['Authorization'].removeprefix('Bearer '))
            return httpx.Response(200, json={'code': 0, 'data': {'status': 'APPROVED'}})
    monkeypatch.setattr('backend.app.httpx.Client', ApprovalProvider)
    monkeypatch.setattr('backend.lark_adapter.LarkAdapter', Provider)
    monkeypatch.setattr('backend.learning_sources.read_capabilities', lambda adapter: ([], []))
    response = client.post(path, json={'version': 1, 'instance_code': 'leave-test'})
    assert response.status_code == 200, response.text
    assert tokens == ['synthetic-user-token']
    if path.endswith('/refresh'):
        assert response.json()['approvals'][0]['lark_external_status'] == 'APPROVED'
    elif path == '/api/learning/sync':
        assert response.json()['capability_source_status']['status'] == 'ready'
    elif path == '/api/delegations/verify-approval':
        assert response.json()['approved_leave_delegations'][0]['id'] == 'leave-test'
    else:
        assert response.json()['status'] == 'ready'
