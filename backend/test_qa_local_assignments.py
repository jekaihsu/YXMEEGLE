import pytest

from .test_sop_local_nodes import local, setup, change_workspace, prepare_completion, call, persisted


def test_local_assignment_is_saved_reloaded_and_revision_checked(local):
    app, client, signin, pid, url = setup(local)
    change_workspace(app, prepare_completion)
    signin('u-manager')
    path = url + '/sop-nodes/sales'
    result = call(client, 'POST', path, {'action': 'assign', 'expected_revision': 0, 'owner_id': 'u-field'})
    assert result == {'node_key': 'sales', 'revision': 1, 'status': 'pending'}
    reloaded = call(client, 'GET', url + '/sop-tasks')['local_nodes'][0]
    assert (reloaded['key'], reloaded['owner_id'], reloaded['revision']) == ('sales', 'u-field', 1)
    before = persisted(app)
    conflict = call(client, 'POST', path, {'action': 'assign', 'expected_revision': 0, 'owner_id': 'u-pm'}, 409)
    assert conflict['code'] == 'node_revision_conflict'
    assert persisted(app) == before


@pytest.mark.parametrize('who,status,code', [('u-field', 403, 'sop_import_forbidden'), ('u-control', 404, 'case_not_found')])
def test_local_assignment_denied_actor_does_not_write(local, who, status, code):
    app, client, signin, pid, url = setup(local)
    change_workspace(app, prepare_completion)
    before = persisted(app)
    signin(who)
    response = client.post(url + '/sop-nodes/sales', json={'action': 'assign', 'expected_revision': 0, 'owner_id': 'u-field'})
    assert response.status_code == status
    assert response.json()['code'] == code
    assert persisted(app) == before


def test_local_assignment_disabled_flag_keeps_saved_owner(local):
    app, client, signin, pid, url = setup(local)
    change_workspace(app, prepare_completion)
    call(client, 'POST', url + '/sop-nodes/sales', {'action': 'assign', 'expected_revision': 0, 'owner_id': 'u-field'})
    app.state.sop_import.writes_enabled = lambda: False
    before = persisted(app)
    denied = call(client, 'POST', url + '/sop-nodes/sales', {'action': 'assign', 'expected_revision': 1, 'owner_id': 'u-pm'}, 503)
    assert denied['code'] == 'import_unavailable'
    assert persisted(app) == before
    node = call(client, 'GET', url + '/sop-tasks')['local_nodes'][0]
    assert (node['owner_id'], node['revision'], node['can']['assign'], node['disabled_reason']) == (
        'u-field', 1, False, '任務寫入尚未開放')
