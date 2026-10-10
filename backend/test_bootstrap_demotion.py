"""Issue #58: real demotion preserves only fresh employee admission."""
from datetime import datetime, timedelta, timezone

import pytest

from . import storage
from .app import BusinessRow, PersonRow, WorkspaceRow
from .policy import upgrade
from .seed import seed
from .test_staff_oauth_acceptance import staff


@pytest.fixture
def demoted(staff):
    app, client, login, change = staff
    change({'role': 'manager', 'bootstrap_admin': True})
    with app.state.sessions.begin() as db:
        person = db.get(PersonRow, ('lark-company', 'ou_staff')).data
        db.add(PersonRow(organization_id='lark-company', person_id='ou_other',
                         data={**person, 'id': 'ou_other', 'name': 'Remaining manager'}))
    assert login().status_code == 307
    assert client.get('/api/session').json()['access_mode'] == 'normal'
    with app.state.sessions.begin() as db:
        row = db.get(WorkspaceRow, 'lark-company')
        state = storage.load(db, BusinessRow, row)
        project = upgrade(seed())['projects'][0]
        project.update(execution_system='workbench', pm_id='ou_staff')
        state['projects'] = [project]
        row.data = storage.save(db, BusinessRow, row.id, state)
    workspace = client.get('/api/workspace').json()
    response = client.post('/api/actions', json={'action': 'admin_person',
        'version': workspace['version'], 'request_id': 'bootstrap-demotion',
        'payload': {'id': 'ou_staff', 'role': 'member', 'active': True, 'capabilities': []}})
    assert response.status_code == 200, response.text
    with app.state.sessions() as db:
        person = db.get(PersonRow, ('lark-company', 'ou_staff')).data
        assert person['bootstrap_admin'] and person['active'] and person['role'] == 'member'
        assert person['authz_version'] > 0
    return staff, project['id']


def test_demoted_bootstrap_can_comment_and_relogin_without_admin_or_recovery(demoted):
    (_, client, login, _), project_id = demoted
    for relogin in (False, True):
        if relogin:
            assert client.post('/api/logout').status_code == 200
            assert login().status_code == 307
        session = client.get('/api/session').json()
        assert session['access_mode'] == 'normal'
        assert session['user']['role'] == 'member'
        workspace = client.get('/api/workspace')
        assert workspace.status_code == 200
        response = client.post('/api/actions', json={'action': 'comment_add',
            'project_id': project_id, 'version': workspace.json()['version'],
            'request_id': f'member-comment-{relogin}', 'payload': {'body': 'Employee access retained'}})
        assert response.status_code == 200, response.text
        assert client.post('/api/actions', json={'action': 'admin_person',
            'version': response.json()['version'], 'request_id': f'no-escalation-{relogin}',
            'payload': {'id': 'ou_staff', 'role': 'manager'}}).status_code == 403
        assert client.post('/api/people/sync').status_code == 403
        assert client.get('/api/admin/runtime-health').status_code == 403


@pytest.mark.parametrize('patch', [
    {'directory_last_seen_at': (datetime.now(timezone.utc)-timedelta(seconds=901)).isoformat()},
    {'directory_missing': True},
    {'directory_source': {}},
    {'directory_status': 'left'},
], ids=['stale', 'missing-row', 'missing-proof', 'departed'])
def test_demoted_bootstrap_cannot_recover_or_relogin_without_fresh_roster(demoted, patch):
    (_, client, login, change), _ = demoted
    change(patch)
    assert client.get('/api/workspace').status_code == 403
    assert client.get('/api/session').json()['user'] is None
    assert client.post('/api/people/sync').status_code == 403
    assert client.get('/api/admin/runtime-health').status_code == 403
    assert client.post('/api/logout').status_code == 200
    assert login().status_code == 403
    assert client.get('/api/workspace').status_code == 401
