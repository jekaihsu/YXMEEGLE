"""Public responses must enforce the existing leave visibility policy server-side."""
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from .app import create_app, WorkspaceRow, BusinessRow
from . import storage
from .seed import seed
from .workspace_projection import public_copy, filter_private_workspace


def sample():
    state = seed()
    state['migration_archive'] = {'private': 'ARCHIVE_SECRET_MARKER'}
    state['projects'][0]['migration_archive'] = {'private': 'NESTED_ARCHIVE_MARKER'}
    state['approved_leave_delegations'] = [
        {'id': 'own', 'principal_id': 'u-control', 'delegate_id': 'u-agent', 'from': '2026-09-01'},
        {'id': 'delegate', 'principal_id': 'u-field', 'delegate_id': 'u-control', 'from': '2026-09-02'},
        {'id': 'OTHER_PRIVATE_LEAVE_MARKER', 'principal_id': 'u-report', 'delegate_id': 'u-map', 'from': '2026-09-03'},
    ]
    return state


@pytest.mark.parametrize('ident,expected', [('u-control', {'own', 'delegate'}),
    ('u-manager', {'own', 'delegate', 'OTHER_PRIVATE_LEAVE_MARKER'}), ('u-pm', set()), ('unknown', set())])
def test_projection_uses_actual_profile_and_preserves_storage(ident, expected):
    state = sample(); original = deepcopy(state)
    # Stale caller claims must not elevate the current workspace profile.
    public = filter_private_workspace(public_copy(state), {'id': ident, 'role': 'manager'})
    assert {a['id'] for a in public['approved_leave_delegations']} == expected
    assert 'migration_archive' not in public and 'migration_archive' not in public['projects'][0]
    assert state == original


def test_handover_capability_and_disabled_or_missing_actor_fail_closed():
    state = sample(); actor = next(u for u in state['users'] if u['id'] == 'u-pm')
    actor['capabilities'] = ['manage_handover']
    assert len(filter_private_workspace(public_copy(state), actor)['approved_leave_delegations']) == 3
    actor['active'] = False
    assert filter_private_workspace(public_copy(state), actor)['approved_leave_delegations'] == []
    assert filter_private_workspace(public_copy(state), None)['approved_leave_delegations'] == []


@pytest.fixture
def setup(tmp_path):
    app = create_app({'DATABASE_URL': f'sqlite:///{tmp_path}/privacy.sqlite',
                      'UPLOAD_DIR': str(tmp_path / 'uploads'), 'DEMO_MODE': 'true',
                      'APP_ENV': 'development', 'SESSION_SECRET': 'privacy-test-only' * 3})
    wid = 'demo-privacy'
    with app.state.sessions.begin() as db:
        db.add(WorkspaceRow(id=wid, version=1, data=sample()))
    client = TestClient(app)
    def actor(ident):
        client.cookies.set('meegle_session', app.state.signer.dumps({'mode': 'demo', 'uid': ident, 'wid': wid}))
    actor('u-control')
    return app, client, wid, actor


def test_get_mutation_and_replay_hide_unrelated_leave_and_archives(setup):
    app, client, wid, actor = setup
    response = client.get('/api/workspace')
    assert response.status_code == 200
    body = {'action': 'comment_add', 'version': response.json()['version'], 'request_id': 'privacy-comment',
            'project_id': 'p1', 'payload': {'body': '本機隱私驗證'}}
    for response in (response, client.post('/api/actions', json=body), client.post('/api/actions', json=body)):
        assert response.status_code == 200, response.text
        assert {a['id'] for a in response.json()['approved_leave_delegations']} == {'own', 'delegate'}
        assert 'OTHER_PRIVATE_LEAVE_MARKER' not in response.text
        assert 'ARCHIVE_SECRET_MARKER' not in response.text and 'NESTED_ARCHIVE_MARKER' not in response.text
    with app.state.sessions() as db:
        saved = storage.load(db, BusinessRow, db.get(WorkspaceRow, wid))
        assert len(saved['approved_leave_delegations']) == 3
        assert 'migration_archive' not in saved
        assert saved['migration_archive_ref'] == 'original'
        archived = db.get(BusinessRow, (wid, 'migration_archive', 'original'))
        assert archived.data['private'] == 'ARCHIVE_SECRET_MARKER'
        assert saved['projects'][0]['migration_archive']['private'] == 'NESTED_ARCHIVE_MARKER'
        assert 'task_capabilities_checked_at' not in saved
        assert all('can_execute' not in task for p in saved['projects'] for n in p['nodes'] for task in n['tasks'])


def test_receipt_replay_uses_current_role_after_revocation(setup):
    app, client, wid, actor = setup; actor('u-manager')
    ws = client.get('/api/workspace').json()
    body = {'action': 'comment_add', 'version': ws['version'], 'request_id': 'role-replay',
            'project_id': 'p1', 'payload': {'body': '同一回執重播'}}
    assert len(client.post('/api/actions', json=body).json()['approved_leave_delegations']) == 3
    with app.state.sessions.begin() as db:
        row = db.get(WorkspaceRow, wid); state = storage.load(db, BusinessRow, row)
        person = next(u for u in state['users'] if u['id'] == 'u-manager')
        person.update(role='member', capabilities=[])
        row.data = storage.save(db, BusinessRow, wid, state)
    replay = client.post('/api/actions', json=body)
    assert replay.status_code == 200
    assert replay.json()['approved_leave_delegations'] == []


def _handover_state():
    from .seed import USERS
    from .sources import import_sources
    from .operations import apply_operation
    ws = seed(True)
    ws['users'] = deepcopy(USERS)
    import_sources(ws, [dict(kind='confirmation', base_token='v4', table_id='c', record_id='rec1',
                             fields={'工程確認單編號': 'C1', '工程名稱': '交接案', '狀態': '執行中'})])
    project = ws['projects'][0]
    project.update(pm_id='u-pm', admin_id='u-manager', supervisor_id='u-manager', execution_system='workbench')
    def act(name, data, uid):
        user = next(u for u in ws['users'] if u['id'] == uid)
        return apply_operation(ws, user, dict(action=name, payload=data, project_id=project['id'], node_id=None), True)
    # PM proposes a handover between two other people (from_id/to_id schema).
    act('handover_request', {'from_id': 'u-field', 'to_id': 'u-agent', 'reason': '調派'}, 'u-pm')
    return ws, act


def _visible(ws, uid):
    user = next(u for u in ws['users'] if u['id'] == uid)
    return [h['id'] for h in filter_private_workspace(public_copy(ws), user)['handover_requests']]


@pytest.mark.parametrize('uid,seen', [('u-field', True), ('u-agent', True), ('u-pm', True),
                                      ('u-manager', True), ('u-map', False), ('u-report', False)])
def test_handover_projection_uses_from_to_schema(uid, seen):
    ws, _ = _handover_state()
    hid = ws['handover_requests'][0]['id']
    assert (hid in _visible(ws, uid)) is seen


def test_project_lead_sees_handover_requested_by_someone_else():
    ws, _ = _handover_state()
    ws['handover_requests'][0]['requested_by'] = 'u-manager'
    ws['projects'][0]['pm_id'] = 'u-control'
    assert _visible(ws, 'u-control') == [ws['handover_requests'][0]['id']]
    assert _visible(ws, 'u-map') == []


def test_recipient_accepts_projected_handover_and_delegations_keep_own_schema():
    ws, act = _handover_state()
    hid = ws['handover_requests'][0]['id']
    act('handover_approve', {'id': hid}, 'u-manager')
    assert hid in _visible(ws, 'u-agent')
    act('handover_accept', {'id': hid}, 'u-agent')
    assert ws['handover_requests'][0]['status'] == 'accepted'
    assert hid in _visible(ws, 'u-field') and hid not in _visible(ws, 'u-map')
    # Delegations are principal_id/delegate_id; from_id/to_id must not leak into them.
    ws['delegations'] = [dict(id='d1', principal_id='u-field', delegate_id='u-agent'),
                         dict(id='d2', from_id='u-map', to_id='u-report')]
    user = next(u for u in ws['users'] if u['id'] == 'u-agent')
    got = filter_private_workspace(public_copy(ws), user)['delegations']
    assert [d['id'] for d in got] == ['d1']


def test_persisted_handover_is_visible_and_acceptable_through_api(setup):
    app, client, wid, actor = setup
    ws, act = _handover_state()
    hid = ws['handover_requests'][0]['id']
    project_id = ws['projects'][0]['id']
    act('handover_approve', {'id': hid}, 'u-manager')
    with app.state.sessions.begin() as db:
        row = db.get(WorkspaceRow, wid)
        row.data = storage.save(db, BusinessRow, wid, ws)

    for ident, expected in [('u-field', [hid]), ('u-agent', [hid]),
                            ('u-pm', [hid]), ('u-manager', [hid]), ('u-map', [])]:
        actor(ident)
        response = client.get('/api/workspace')
        assert response.status_code == 200, response.text
        assert [h['id'] for h in response.json()['handover_requests']] == expected

    actor('u-agent')
    current = client.get('/api/workspace').json()
    assert current['handover_requests'][0]['status'] == 'awaiting_acceptance'
    response = client.post('/api/actions', json={
        'action': 'handover_accept', 'project_id': project_id,
        'version': current['version'], 'request_id': 'accept-persisted-handover',
        'payload': {'id': hid},
    })
    assert response.status_code == 200, response.text
    assert response.json()['handover_requests'][0]['status'] == 'accepted'
    assert client.get('/api/workspace').json()['handover_requests'][0]['status'] == 'accepted'
    with app.state.sessions() as db:
        saved = storage.load(db, BusinessRow, db.get(WorkspaceRow, wid))
        assert saved['handover_requests'][0]['status'] == 'accepted'
        assert saved['projects'][0]['handoffs'][0]['id'] == hid
