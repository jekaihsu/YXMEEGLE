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
