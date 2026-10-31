from copy import deepcopy
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from .app import create_app, WorkspaceRow, BusinessRow, AuditRow
from . import storage
from .seed import seed
from .features import resolve_features
from .workflow import apply_action
from .operations import apply_operation
from .jobs import schedule, Worker


@pytest.fixture
def client(tmp_path):
    app = create_app({'DATABASE_URL': 'sqlite:///' + str(tmp_path / 'test.db'),
                      'UPLOAD_DIR': str(tmp_path / 'uploads'), 'DEMO_MODE': 'true',
                      'FEATURE_CHANGE_EXTENSION': 'false', 'FEATURE_ROUTINES': 'false'})
    with TestClient(app) as client:
        client.get('/api/session')
        yield client


def snapshot(client):
    app = client.app
    with app.state.sessions() as db:
        row = db.scalar(select(WorkspaceRow))
        return deepcopy(storage.load(db, BusinessRow, row)), row.version


@pytest.mark.parametrize('action,payload', [
    ('approval_create', {'type': 'change'}), ('approval_create', {'type': 'extension'}),
    ('approval_submit', {'approval_id': 'private'}), ('approval_execute', {'approval_id': 'private'}),
    ('approval_withdraw', {'approval_id': 'private'}), ('change_resume', {'approval_id': 'private'}),
    ('recurring_create', {}), ('recurring_complete', {}), ('recurring_review', {}),
    ('sop_followup_complete', {}), ('sop_round_open', {}),
])
def test_disabled_action_has_no_business_effect(client, action, payload):
    before = snapshot(client)
    response = client.post('/api/actions', json={'action': action, 'payload': payload,
                           'version': before[1], 'request_id': action})
    assert response.status_code == 403
    assert response.json()['code'] == 'feature_disabled'
    assert response.headers['cache-control'] == 'no-store'
    assert snapshot(client) == before
    with client.app.state.sessions() as db:
        rows = list(db.scalars(select(AuditRow)))
        assert len(rows) == 1
        assert rows[0].data['result'] == 'denied'


def test_session_defaults_and_explicit_opt_in(client):
    flags = client.get('/api/session').json()['features']
    assert flags['change_extension'] is False
    assert flags['routines'] is False
    assert resolve_features({'FEATURE_CHANGE_EXTENSION': 'true', 'FEATURE_ROUTINES': 'true'}) == {
        'change_extension': True, 'routines': True}


@pytest.mark.parametrize('path', ['/api/native-approvals/change/private/submit',
                                 '/api/native-approvals/extension/private/poll',
                                 '/api/change-approvals/private/confirm-line',
                                 '/api/approvals/private/refresh'])
def test_native_disabled_without_request_lookup(client, path):
    before = snapshot(client)
    response = client.post(path, json={})
    assert response.status_code == 403
    assert response.json()['code'] == 'feature_disabled'
    assert snapshot(client) == before


def test_domain_guard_and_isolated_opt_in():
    state = seed()
    before = deepcopy(state)
    with pytest.raises(HTTPException) as error:
        apply_action(state, state['users'][0], {'action': 'approval_create', 'payload': {'type': 'change'}})
    assert error.value.detail['code'] == 'feature_disabled'
    assert state == before
    state['features'] = {'change_extension': True, 'routines': True}
    project = state['projects'][0]
    apply_operation(state, state['users'][0], {'action': 'recurring_create', 'project_id': project['id'],
                    'payload': {'kind': 'client_contact', 'owner_id': state['users'][0]['id'],
                                'start_date': '2026-10-15'}}, True)
    assert state['recurring']


def test_scheduler_does_not_create_disabled_routines():
    state = seed()
    state['recurring'] = []
    schedule(state, '2026-10-15T09:01:00+08:00')
    assert state['recurring'] == []
    assert not any(job['kind'] == 'digest' for job in state['jobs'])


def test_old_digest_is_blocked_before_dispatch(client):
    app = client.app
    with app.state.sessions.begin() as db:
        row = db.scalar(select(WorkspaceRow))
        state = storage.load(db, BusinessRow, row)
        state['jobs'] = [{'id': 'old', 'kind': 'digest', 'status': 'queued', 'key': 'old',
                          'actor_id': 'u-pm', 'payload': {'text': '舊追蹤提醒'}, 'attempts': []}]
        row.data = storage.save(db, BusinessRow, row.id, state)
        wid = row.id
    worker = Worker(app.state.sessions, WorkspaceRow, BusinessRow, None, app.state.cfg, app.state.upload_dir,
                    adapter_factory=lambda *args: pytest.fail('disabled job must not create an adapter'))
    worker.run_one(wid)
    assert snapshot(client)[0]['jobs'][0]['status'] == 'blocked_feature'


def enabled_seed(empty=False):
    state = seed(empty)
    state["features"] = {"change_extension": True, "routines": True}
    return state


@pytest.mark.parametrize('environment', ['production', 'demo', 'test'])
def test_mock_server_gate_with_explicit_opt_in(tmp_path, environment):
    app = create_app({'DATABASE_URL': 'sqlite:///' + str(tmp_path / 'mock.db'),
                      'UPLOAD_DIR': str(tmp_path / 'uploads'), 'DEMO_MODE': 'true',
                      'FEATURE_LARK_AUTHORITATIVE_OPS': 'true'})
    state = seed(True)
    state.update(environment=environment, users=[{'id': 'fixture-user', 'name': '隔離測試', 'role': 'manager'}])
    with app.state.sessions.begin() as db:
        row = WorkspaceRow(id='isolated-fixture', version=1, data=state)
        db.add(row)
    client = TestClient(app)
    client.cookies.set('meegle_session', app.state.signer.dumps({
        'mode': 'demo', 'wid': 'isolated-fixture', 'uid': 'fixture-user'}))
    before = snapshot(client)
    response = client.get('/api/ops-sync/flow')
    assert response.status_code == (403 if environment == 'production' else 200)
    if environment == 'production':
        assert response.json() == {'detail': '正式工作區不提供模擬資料'}
        assert snapshot(client) == before
    else:
        assert response.json()['live'] is False


def test_production_quarantines_stored_seed_data(client):
    app = client.app
    with app.state.sessions.begin() as db:
        row = WorkspaceRow(id='isolated-production', version=1, data=seed())
        row.data['environment'] = 'production'
        db.add(row)
    client.cookies.clear()
    client.cookies.set('meegle_session', app.state.signer.dumps({
        'mode': 'demo', 'wid': 'isolated-production', 'uid': 'u-pm'}))
    response = client.get('/api/workspace')
    assert response.status_code == 409
    assert '桃園捷運' not in response.text
    assert response.json()['detail'] == '正式工作區包含隔離示範資料，請由管理員核對'


def test_retry_disabled_digest_preserves_history():
    state = seed()
    state['jobs'] = [{'id': 'old', 'kind': 'digest', 'status': 'blocked_feature', 'actor_id': 'u-manager'}]
    before = deepcopy(state)
    actor = next(user for user in state['users'] if user['id'] == 'u-manager')
    with pytest.raises(HTTPException) as error:
        apply_operation(state, actor, {'action': 'job_retry', 'payload': {'id': 'old'}}, True)
    assert error.value.detail['code'] == 'feature_disabled'
    assert state == before
