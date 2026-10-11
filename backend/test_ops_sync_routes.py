"""Flag-gated local/mock ops API: flag off => 404, authorization, delivery states, stale baseline, no network."""
import socket

import pytest
from fastapi.testclient import TestClient

from .app import create_app, WorkspaceRow
from .ops_sync.adapter import BINDING, MockLarkAdapter
from .ops_sync.engine import OpsEngine
from .ops_sync.workspace_store import WorkspaceStore
from .ops_sync.routes import ADAPTER_NAMESPACE, NOTICE
from .seed import seed

PATHS = [('get', '/api/ops-sync/flow'), ('post', '/api/ops-sync/flow/assign'), ('post', '/api/ops-sync/flow/propose'),
         ('post', '/api/ops-sync/flow/decide'), ('post', '/api/ops-sync/flow/reconcile'),
         ('post', '/api/ops-sync/flow/resolve-conflict'), ('post', '/api/ops-sync/flow/resume-dispatch')]


def make(tmp_path, flag, user='u-pm'):
    cfg = {'DATABASE_URL': f'sqlite:///{tmp_path}/ops.db', 'UPLOAD_DIR': str(tmp_path / 'up'), 'DEMO_MODE': 'true',
           'APP_ENV': 'development', 'SESSION_SECRET': 'ops-routes-tests' * 4}
    if flag is not None:
        cfg['FEATURE_LARK_AUTHORITATIVE_OPS'] = flag
    app = create_app(cfg)
    with app.state.sessions.begin() as db:
        db.add(WorkspaceRow(id='demo-ops', version=1, data=seed()))
    return app, as_user(app, user)


def as_user(app, user):
    client = TestClient(app)
    client.cookies.set('meegle_session', app.state.signer.dumps({'mode': 'demo', 'uid': user, 'wid': 'demo-ops', 'sid': 'demo-ops'}))
    return client


def body(cid, field='case.pm', expected=None, rev=0, intended='synthetic|yxs-local|u-pm', entity='case:p1'):
    return {'command_id': cid, 'entity_id': entity, 'field_id': field, 'expected': expected or {'t': 'clear'},
            'expected_revision': rev, 'intended': {'t': 'set', 'v': intended}, 'schema_binding_version': BINDING, 'occurred_at': '2026-10-11T00:00:00+00:00'}


def engine(app):
    sessions = app.state.sessions
    return OpsEngine(app.state.ops_store_for('demo-ops'), MockLarkAdapter(WorkspaceStore(sessions, 'demo-ops', namespace=ADAPTER_NAMESPACE)),
                     approval_required=('case.deadline', 'node.deadline'))


@pytest.mark.parametrize('flag', [None, False, 'false', 'no'])
def test_flag_off_routes_do_not_exist(tmp_path, flag):
    app, client = make(tmp_path, flag)
    assert app.state.ops_store_for is None
    # The app answers any unregistered POST with 405 (GET catch-all); the ops paths must be indistinguishable from that.
    assert client.get('/api/ops-sync/flow').status_code == 404
    unregistered = client.post('/api/never-registered', json={}).status_code
    assert unregistered in (404, 405)
    for method, path in PATHS:
        got = getattr(client, method)(path, **({} if method == 'get' else {'json': {}})).status_code
        assert got == (404 if method == 'get' else unregistered)
    assert 'ops_sync' not in client.get('/api/workspace').text


def assign_body(cid, entity='case:p1', people=('u-pm',)):
    return {'command_id': cid, 'entity_id': entity, 'person_ids': list(people), 'occurred_at': '2026-10-11T00:00:00+00:00'}


def test_live_writes_stay_disabled_and_no_network(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: calls.append(a))
    app, client = make(tmp_path, 'true')
    assert MockLarkAdapter.live is False
    assert client.post('/api/ops-sync/flow/assign', json=assign_body('c1')).status_code == 200
    assert calls == []


def test_assign_is_confirmed_only_after_mock_readback_and_is_idempotent(tmp_path):
    app, client = make(tmp_path, 'true')
    first = client.post('/api/ops-sync/flow/assign', json=assign_body('c1')).json()
    assert first['command']['state'] == 'confirmed' and first['command']['attempts'] == 1
    assert first['live'] is False and first['notice'] == NOTICE
    dup = client.post('/api/ops-sync/flow/assign', json=assign_body('c1')).json()
    assert dup['outcome']['duplicate'] and len(client.get('/api/ops-sync/flow').json()['commands']) == 1


def test_deadline_waits_for_approval_and_never_writes(tmp_path):
    app, client = make(tmp_path, 'true')
    out = client.post('/api/ops-sync/flow/propose', json={'command_id': 'd1', 'entity_id': 'case:p1', 'intended': '2026-10-20',
                                                         'expected_revision': 0}).json()
    assert out['command']['state'] == 'waiting_approval' and out['command']['attempts'] == 0
    assert MockLarkAdapter(WorkspaceStore(app.state.sessions, 'demo-ops', namespace=ADAPTER_NAMESPACE)).write_count == 0


def test_unknown_then_reconcile_confirms(tmp_path):
    app, client = make(tmp_path, 'true')
    out = client.post('/api/ops-sync/flow/assign', json={**assign_body('u1'), 'mock_outcome': 'timeout_after_commit'}).json()
    assert out['command']['state'] == 'unknown' and out['command']['reconcile']['phase'] == 'pending'
    done = client.post('/api/ops-sync/flow/reconcile', json={'command_id': 'u1'}).json()
    assert [c['state'] for c in done['commands']] == ['confirmed']
    assert client.post('/api/ops-sync/flow/reconcile', json={'command_id': 'nope'}).status_code == 404


def test_permission_denied_for_non_lead_and_unknown_entity(tmp_path):
    app, _ = make(tmp_path, 'true')
    member = as_user(app, 'u-field')
    assert member.post('/api/ops-sync/flow/assign', json=assign_body('m1')).status_code == 403
    assert member.get('/api/ops-sync/flow').json()['commands'] == []
    pm = as_user(app, 'u-pm')
    assert pm.post('/api/ops-sync/flow/assign', json=assign_body('m2', entity='case:nope')).status_code == 404
    assert pm.post('/api/ops-sync/flow/assign', json=assign_body('m3', entity='garbage')).status_code == 404
    assert pm.get('/api/ops-sync/flow').json()['commands'] == []       # nothing recorded for denied calls


def test_other_lead_cannot_read_commands_or_act_as_body_actor(tmp_path):
    app, pm = make(tmp_path, 'true')
    pm.post('/api/ops-sync/flow/assign', json=assign_body('c1'))
    other = as_user(app, 'u-control')
    assert other.get('/api/ops-sync/flow').json()['commands'] == []
    assert other.post('/api/ops-sync/flow/reconcile', json={'command_id': 'c1'}).status_code == 403
    out = pm.post('/api/ops-sync/flow/assign', json={**assign_body('c9', people=('u-manager',)), 'actor': 'u-manager'}).json()
    assert out['command']['actor'] == 'u-pm'                                         # actor comes from the session


def test_no_session_is_rejected(tmp_path):
    app, _ = make(tmp_path, 'true')
    assert TestClient(app).get('/api/ops-sync/flow').status_code == 401
