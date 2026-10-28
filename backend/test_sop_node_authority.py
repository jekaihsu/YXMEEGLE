from types import SimpleNamespace

import pytest

from .node_assignment.domain import Person
from .node_assignment.roster import Roster
from .test_sop_import import h, URL, post, change, overview  # noqa: F401
from .test_sop_task_views import act
from .test_sop_local_case import local  # noqa: F401


def roster(rank='經理'):
    return Roster({'member': Person('member', '陳柏翰', frozenset({'PM'}), rank, True),
                   'other': Person('other', '吳柏頤', frozenset({'控制'}), None, True)}, frozenset())


def setup(h):
    x = post(h, URL + '/sop-tasks', {'title': 'X', 'node_keys': ['pm']})['task']
    y = post(h, URL + '/sop-tasks', {'title': 'Y', 'node_keys': ['control']})['task']
    shared = post(h, URL + '/sop-tasks', {'title': 'shared', 'node_keys': ['pm', 'control']})['task']
    h.service.roster_provider = lambda fresh=False: roster()
    h.who[0] = 'member'
    return x, y, shared


def test_manager_can_edit_and_complete_only_their_nodes(h):
    x, y, shared = setup(h)
    tasks = {t['title']: t for t in overview(h)['tasks']}
    assert tasks['X']['can'] == {'manage': True}
    assert tasks['Y']['can'] == {'manage': False}
    assert tasks['shared']['allowed_actions'] == []
    assert tasks['X']['allowed_actions'] == ['start', 'block', 'complete', 'archive', 'set_applicability', 'edit']
    assert tasks['Y']['completion_blocked_reason'] == 'sop_import_forbidden'
    assert change(h, x, {'participants': {'executor': 'other'}})['task']['participants'] == {'executor': 'other'}
    assert change(h, y, {'participants': {'executor': 'member'}}, 403)['code'] == 'sop_import_forbidden'
    assert act(h, y, 'complete', 403)['code'] == 'sop_import_forbidden'
    assert act(h, shared, 'complete', 403)['code'] == 'sop_import_forbidden'
    updated = next(t for t in overview(h)['tasks'] if t['id'] == x['id'])
    assert act(h, updated, 'complete')['state'] == 'done'


@pytest.mark.parametrize('action', ['start', 'block', 'complete', 'archive', 'set_applicability', 'reopen', 'restore'])
def test_all_transition_paths_deny_other_node(h, action):
    _, y, _ = setup(h)
    assert act(h, y, action, 403, reason='驗證', applicability='not_applicable')['code'] == 'sop_import_forbidden'


def test_suggestion_single_bulk_dismiss_and_proof_paths_deny_other_node(h):
    x, y, _ = setup(h)
    single = {'action': 'accept_suggestion', 'facts_hash': 'a' * 64, 'expected_revision': 1}
    assert post(h, URL + f"/sop-tasks/{y['id']}/suggestion", single, 403)['code'] == 'sop_import_forbidden'
    assert post(h, URL + '/sop-tasks/suggestions/accept', {'tasks': [
        {'task_id': y['id'], 'facts_hash': 'a' * 64, 'expected_revision': 1}]}, 403)['code'] == 'sop_import_forbidden'
    assert post(h, URL + f"/sop-tasks/{y['id']}/suggestion", {'action': 'dismiss_suggestion', 'facts_hash': 'a' * 64}, 403)['code'] == 'sop_import_forbidden'
    h.service.node_done = lambda ctx: {'control': SimpleNamespace(rule='test', reason_zh='完成')}
    assert post(h, URL + '/sop-tasks/close-node', {'node_key': 'control'}, 403)['code'] == 'sop_import_forbidden'
    assert post(h, URL + '/sop-tasks', {'title': '越權', 'node_keys': ['control']}, 403)['code'] == 'sop_import_forbidden'


@pytest.mark.parametrize('rank', ['副總', '老闆'])
def test_executives_keep_global_authority(h, rank):
    _, y, _ = setup(h)
    h.service.roster_provider = lambda fresh=False: roster(rank)
    assert change(h, y, {'title': '核對'})['task']['title'] == '核對'


def test_executor_own_task_and_admin_global_and_nonmanager_denial(h):
    _, y, _ = setup(h)
    h.who[0] = 'manager'
    h.users['manager']['role'] = 'admin'
    updated = change(h, y, {'participants': {'executor': 'other'}})['task']
    h.who[0] = 'other'
    assert 'edit' not in next(t for t in overview(h)['tasks'] if t['id'] == y['id'])['allowed_actions']
    assert act(h, updated, 'start')['state'] == 'in_progress'
    assert change(h, updated, {'title': '越權'}, 403)['code'] == 'sop_import_forbidden'
    h.users['member']['active'] = False
    h.who[0] = 'member'
    assert h.client.get(URL + '/sop-tasks').status_code == 403


def test_picker_roster_teams_search_paging_and_restricted_reader(h):
    setup(h)
    h.users['pm']['department'] = 'PM'
    h.users['manager']['department'] = '控制'
    url = URL + '/sop-assignees'
    team = h.client.get(url + '?node_key=pm').json()
    assert [p['id'] for p in team['people']] == ['pm', 'member']
    assert team['people'][1]['teams'] == ['PM']
    assert 'rank' not in team['people'][1]
    assert h.client.get(url + '?node_key=pm&q=吳&scope=all').json()['people'] == [
        {'id': 'other', 'name': '吳柏頤', 'department': None, 'case_roles': [], 'teams': ['控制']}]
    first = h.client.get(url + '?node_key=pm&scope=all&limit=2').json()
    assert [p['id'] for p in first['people']] == ['pm', 'member']
    assert first['next_cursor'] == '2'
    second = h.client.get(url + '?node_key=pm&scope=all&limit=2&cursor=2').json()
    assert [p['id'] for p in second['people']] == ['manager', 'other']
    assert second['next_cursor'] is None
    assert h.client.get(url + '?limit=51').status_code == 422
    h.cfg['HR_VIEWERS'] = 'pm'
    manager_restricted = h.client.get(url + '?node_key=control&scope=all').json()
    assert manager_restricted['restricted'] is True
    assert [p['id'] for p in manager_restricted['people']] == ['member']
    h.who[0] = 'other'
    restricted = h.client.get(url + '?node_key=pm&scope=all').json()
    assert restricted['restricted'] is True
    assert [p['id'] for p in restricted['people']] == ['other']
    assert h.client.get(url + '?scope=all&q=陳').json()['people'] == []


def test_local_node_manager_actions_and_flags(local):
    from .test_sop_local_nodes import setup, change_workspace, prepare_completion
    from .test_sop_local_case import call
    app, client, signin, _, url = setup(local)
    change_workspace(app, prepare_completion)
    app.state.sop_import.roster_provider = lambda fresh=False: Roster({
        'u-field': Person('u-field', '同仁', frozenset({'業務'}), '經理', True)}, frozenset())
    signin('u-field')
    nodes = {n['key']: n for n in call(client, 'GET', url + '/sop-tasks')['local_nodes']}
    assert nodes['sales']['can']['assign'] is True
    assert nodes['control']['can'] == {'assign': False, 'complete': False, 'reject': False, 'create_task': False}
    for action in ['assign', 'complete', 'reject']:
        assert call(client, 'POST', url + '/sop-nodes/control', {
            'action': action, 'expected_revision': 0, 'owner_id': 'u-field', 'reason': '核對'}, 403)['code'] == 'sop_import_forbidden'
    call(client, 'POST', url + '/sop-nodes/sales', {'action': 'assign', 'expected_revision': 0, 'owner_id': 'u-field'})
    call(client, 'POST', url + '/sop-nodes/sales', {'action': 'complete', 'expected_revision': 1, 'reason': '核對完成'})
    assert call(client, 'POST', url + '/sop-nodes/sales', {'action': 'reject', 'expected_revision': 2, 'reason': '補正'})['status'] == 'in_progress'


def test_executor_transition_does_not_need_a_roster_network_read(h):
    task = post(h, URL + '/sop-tasks', {'title': '執行', 'node_keys': ['control'], 'participants': {'executor': 'member'}})['task']
    h.who[0] = 'member'
    def provider(fresh=False):
        assert fresh is False, 'executor transitions must not depend on a roster refresh'
        return None
    h.service.roster_provider = provider
    assert act(h, task, 'start')['state'] == 'in_progress'


@pytest.mark.parametrize('role', ['admin'])
def test_existing_system_and_application_admin_grants_stay_global(h, role):
    _, y, _ = setup(h)
    h.users['other']['role'] = role
    h.who[0] = 'other'
    assert change(h, y, {'title': '全域核對'})['task']['title'] == '全域核對'


def test_proof_bulk_close_cannot_touch_a_shared_task_outside_manager_scope(h):
    x, _, shared = setup(h)
    proof = SimpleNamespace(rule='test', reason_zh='完成', public=lambda: {'rule': 'test'})
    h.service.node_done = lambda ctx: {
        'pm': proof, 'control': proof}
    result = post(h, URL + '/sop-tasks/close-node', {'node_key': 'pm'})
    assert result['closed'] == 1
    assert result['left_open'] == {'shared': 1, 'unresolved': 0}
    h.service.node_done = lambda ctx: {}
    tasks = {t['id']: t for t in overview(h)['tasks']}
    assert tasks[x['id']]['state'] == 'done'
    assert tasks[shared['id']]['state'] == 'pending'


def test_workspace_manager_title_does_not_bypass_roster_scope(h):
    x, y, _ = setup(h)
    h.users['member']['role'] = 'manager'
    assert change(h, x, {'title': '同組核對'})['task']['title'] == '同組核對'
    assert change(h, y, {'title': '越權'}, 403)['code'] == 'sop_import_forbidden'
    h.service.roster_required = True
    h.service.roster_provider = lambda fresh=False: None
    assert change(h, y, {'title': '名冊未知'}, 403)['code'] == 'sop_import_forbidden'


@pytest.mark.parametrize('path, body', [
    ('test-tag', {'expected_revision': 1, 'is_test': True, 'reason': '核對'}),
    ('cleanup-test', {'expected_revision': 1, 'reason': '核對'})])
def test_test_fixture_mutations_also_obey_node_scope(h, path, body):
    _, y, _ = setup(h)
    h.users['member']['role'] = 'manager'
    assert post(h, URL + f"/sop-tasks/{y['id']}/{path}", body, 403)['code'] == 'sop_import_forbidden'
