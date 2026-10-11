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

PATHS = [('get', '/api/ops-sync/status'), ('post', '/api/ops-sync/commands'),
         ('post', '/api/ops-sync/conflicts/x/resolve'), ('post', '/api/ops-sync/reconcile')]


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
    assert client.get('/api/ops-sync/status').status_code == 404
    unregistered = client.post('/api/never-registered', json={}).status_code
    assert unregistered in (404, 405)
    for method, path in PATHS:
        got = getattr(client, method)(path, **({} if method == 'get' else {'json': {}})).status_code
        assert got == (404 if method == 'get' else unregistered)
    assert 'ops_sync' not in client.get('/api/workspace').text


def test_live_writes_stay_disabled_and_no_network(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: calls.append(a))
    app, client = make(tmp_path, 'true')
    assert MockLarkAdapter.live is False
    assert client.post('/api/ops-sync/commands', json=body('c1')).status_code == 200
    assert calls == []


def test_submit_is_confirmed_only_after_mock_readback(tmp_path):
    app, client = make(tmp_path, 'true')
    first = client.post('/api/ops-sync/commands', json=body('c1')).json()
    assert first['accepted'] and first['command']['state'] == 'confirmed' and first['command']['attempts'] == 1
    status = client.get('/api/ops-sync/status').json()
    assert status['live'] is False and status['notice'] == NOTICE and [c['state'] for c in status['commands']] == ['confirmed']
    dup = client.post('/api/ops-sync/commands', json=body('c1')).json()
    assert dup['duplicate'] and len(client.get('/api/ops-sync/status').json()['commands']) == 1
    assert client.post('/api/ops-sync/commands', json=body('c1', intended='synthetic|yxs-local|u-control')).status_code == 409


def test_deadline_waits_for_approval_and_never_writes(tmp_path):
    app, client = make(tmp_path, 'true')
    out = client.post('/api/ops-sync/commands', json={**body('d1', field='case.deadline'), 'intended': {'t': 'set', 'v': '2026-10-20'}}).json()
    assert out['command']['state'] == 'waiting_approval' and out['command']['attempts'] == 0
    assert MockLarkAdapter(WorkspaceStore(app.state.sessions, 'demo-ops', namespace=ADAPTER_NAMESPACE)).write_count == 0


def test_stale_baseline_becomes_conflict_and_can_be_resolved(tmp_path):
    app, client = make(tmp_path, 'true')
    assert client.post('/api/ops-sync/commands', json=body('c1')).json()['command']['state'] == 'confirmed'
    stale = client.post('/api/ops-sync/commands', json=body('c2', intended='synthetic|yxs-local|u-manager')).json()['command']
    assert stale['state'] == 'conflict' and stale['reason'] == 'baseline_changed'
    conflict = client.get('/api/ops-sync/status').json()['conflicts'][0]
    assert conflict['open'] and conflict['expected']['revision'] == 0 and conflict['current']['revision'] == 1
    assert conflict['current']['value'] == 'synthetic|yxs-local|u-pm' and conflict['intended']['value'] == 'synthetic|yxs-local|u-manager'
    resolve = {'command_id': 'r1', 'resolution': 'apply_intended', 'expected': {'t': 'set', 'v': 'synthetic|yxs-local|u-pm'},
               'expected_revision': 1, 'intended': {'t': 'set', 'v': 'synthetic|yxs-local|u-manager'}, 'schema_binding_version': BINDING}
    wrong = client.post(f"/api/ops-sync/conflicts/{conflict['conflict_id']}/resolve", json={**resolve, 'expected_revision': 0})
    assert wrong.status_code == 409
    done = client.post(f"/api/ops-sync/conflicts/{conflict['conflict_id']}/resolve", json=resolve).json()
    assert [c['state'] for c in done['commands']] == ['confirmed', 'conflict', 'confirmed']
    assert not done['conflicts'][0]['open']


def test_unknown_then_reconcile_confirms(tmp_path):
    app, client = make(tmp_path, 'true')
    client.get('/api/ops-sync/status')
    eng = engine(app)
    eng.adapter.inject('timeout_after_commit')
    from .ops_sync.testing import env
    eng.observe('case:p1', ['case.pm'])
    eng.submit(env('u1', field='case.pm', entity='case:p1', actor='u-pm'))
    eng.run_once()
    states = {c['command_id']: c for c in client.get('/api/ops-sync/status').json()['commands']}
    assert states['u1']['state'] == 'unknown' and states['u1']['reconcile']['phase'] == 'pending'
    out = client.post('/api/ops-sync/reconcile', json={'command_id': 'u1'}).json()
    assert [c['state'] for c in out['commands']] == ['confirmed']
    assert client.post('/api/ops-sync/reconcile', json={'command_id': 'nope'}).status_code == 404


def test_permission_denied_for_non_lead_and_unknown_entity(tmp_path):
    app, _ = make(tmp_path, 'true')
    member = as_user(app, 'u-field')
    assert member.post('/api/ops-sync/commands', json=body('m1')).status_code == 403
    assert member.get('/api/ops-sync/status').json()['commands'] == []
    pm = as_user(app, 'u-pm')
    assert pm.post('/api/ops-sync/commands', json=body('m2', entity='case:nope')).status_code == 404
    assert pm.post('/api/ops-sync/commands', json=body('m3', entity='garbage')).status_code == 404
    assert as_user(app, 'u-pm').get('/api/ops-sync/status').json()['commands'] == []   # nothing recorded for denied calls
    assert pm.post('/api/ops-sync/commands', json={**body('m4'), 'expected_revision': 'x'}).status_code == 422


def test_ineligible_actor_cannot_read_other_leads_commands_or_act_as_body_actor(tmp_path):
    app, pm = make(tmp_path, 'true')
    pm.post('/api/ops-sync/commands', json=body('c1'))
    other = as_user(app, 'u-control')
    assert other.get('/api/ops-sync/status').json()['commands'] == []
    assert other.post('/api/ops-sync/reconcile', json={'command_id': 'c1'}).status_code == 403
    out = pm.post('/api/ops-sync/commands', json={**body('c9'), 'actor': 'u-manager'}).json()
    assert out['command']['actor'] == 'u-pm'                                         # actor comes from the session


def test_no_session_is_rejected(tmp_path):
    app, _ = make(tmp_path, 'true')
    assert TestClient(app).get('/api/ops-sync/status').status_code == 401
