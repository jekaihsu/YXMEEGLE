from .models import BusinessRow
from .test_sop_import import URL, apply, change, h, overview, post  # noqa: F401  (fixture)

IMPORTED = ['start', 'block', 'complete', 'archive', 'set_applicability', 'edit']


def by_row(h, n):
    return next(t for t in overview(h)['tasks'] if t['origin']['source_row_key'] == f'meegle-v137:A:{n}')


def manual(h, participants=None):
    created = post(h, URL + '/sop-tasks', {'title': 'Review plans', 'node_keys': ['pm'], **({'participants': participants} if participants else {})})
    return created['task']


def act(h, task, action, status=200, **body):
    return post(h, f"{URL}/sop-tasks/{task['id']}/transition", {'expected_revision': task['revision'], 'action': action, **body}, status)


def test_task_flags_and_node_keys_come_without_the_source_grant(h):
    apply(h)
    h.who[0] = 'member'
    shared, single, conditional = by_row(h, 32), by_row(h, 19), by_row(h, 22)
    assert (shared['source_snapshot'], shared['instance_scope'], shared['is_shared'], shared['node_keys']) == (
        None, 'office_shared', True, ['control', 'mapping', 'report'])
    assert (single['instance_scope'], single['is_shared'], single['is_conditional'], single['node_keys']) == (
        'case', False, False, ['confirmation'])
    assert (conditional['applicability'], conditional['is_conditional']) == ('unresolved', True)
    h.who[0] = 'pm'
    decided = act(h, conditional, 'set_applicability', applicability='applicable', reason='有異議')
    assert (decided['task']['applicability'], decided['task']['is_conditional']) == ('applicable', True)


def test_allowed_actions_follow_state_applicability_evidence_and_actor(h):
    apply(h)
    assert by_row(h, 19)['allowed_actions'] == IMPORTED
    assert by_row(h, 22)['allowed_actions'] == ['block', 'archive', 'set_applicability', 'edit']
    task = manual(h, {'executor': 'member', 'checker': 'pm', 'confirmer': 'pm'})
    assert task['allowed_actions'] == ['start', 'block', 'complete', 'archive', 'set_applicability', 'edit']
    h.who[0] = 'member'
    assert next(t for t in overview(h)['tasks'] if t['id'] == task['id'])['allowed_actions'] == ['start', 'block', 'complete']
    assert by_row(h, 19)['allowed_actions'] == []
    h.who[0] = 'other'
    assert next(t for t in overview(h)['tasks'] if t['id'] == task['id'])['allowed_actions'] == []
    h.who[0] = 'pm'
    done = act(h, task, 'complete')['task']
    assert done['allowed_actions'] == ['reopen', 'archive']
    archived = act(h, done, 'archive', reason='重複')['task']
    assert archived['allowed_actions'] == ['restore']
    h.cfg['SOP_TASK_WRITES_ENABLED'] = 'false'
    assert {tuple(t['allowed_actions']) for t in overview(h)['tasks']} == {()}


def test_edit_and_transition_return_the_updated_task(h):
    apply(h)
    task = by_row(h, 19)
    before = overview(h)['checklist_revision']
    edited = change(h, task, {'title': 'Local title'})
    assert (edited['task']['title'], edited['task']['revision'], edited['revision'], edited['checklist_revision']) == (
        'Local title', 2, 2, before + 1)
    started = act(h, edited['task'], 'start')
    assert (started['task']['state'], started['task']['revision'], started['task']['allowed_actions'], started['checklist_revision']) == (
        'in_progress', 3, ['block', 'complete', 'archive', 'set_applicability', 'edit'], before + 2)
    assert started['task'] == by_row(h, 19)


def test_assignable_people_follow_the_participant_rule_and_people_visibility(h):
    response = h.client.get(URL + '/sop-assignees')
    assert response.status_code == 200, response.text
    assert response.json() == {'project_id': 'p1', 'restricted': False, 'next_cursor': None, 'people': [
        {'id': 'pm', 'name': '林育寬', 'case_roles': ['pm'], 'department': None, 'teams': []},
        {'id': 'member', 'name': '陳柏翰', 'case_roles': ['collaborator'], 'department': None, 'teams': []},
        {'id': 'manager', 'name': '張智偉', 'case_roles': ['manager'], 'department': None, 'teams': []},
        {'id': 'other', 'name': '吳柏頤', 'case_roles': [], 'department': None, 'teams': []}]}
    assert manual(h, {'executor': 'other'})['participants'] == {'executor': 'other'}
    failed = post(h, URL + '/sop-tasks', {'title': 'x', 'node_keys': ['pm'], 'participants': {'checker': 'ghost'}}, 422)
    assert failed == {'code': 'participant_unresolved', 'detail': 'participant_unresolved', 'role': 'checker'}
    h.cfg['HR_VIEWERS'] = 'pm'
    h.who[0] = 'member'
    assert h.client.get(URL + '/sop-assignees').json() == {'project_id': 'p1', 'restricted': True, 'next_cursor': None, 'people': [
        {'id': 'member', 'name': '陳柏翰', 'case_roles': ['collaborator'], 'department': None, 'teams': []}]}
    h.who[0] = 'pm'
    assert h.client.get(URL + '/sop-assignees').json()['restricted'] is False
    h.users['member']['active'] = False
    assert [p['id'] for p in h.client.get(URL + '/sop-assignees').json()['people']] == ['pm', 'manager', 'other']
    h.hidden.add('p1')
    assert h.client.get(URL + '/sop-assignees').status_code == 404


def grantless(h, ident='staff'):
    h.users[ident] = {'id': ident, 'name': '王小明', 'role': 'member', 'active': True, 'capabilities': []}
    return ident


def test_an_assigned_person_without_any_grant_sees_and_works_only_their_task(h):
    staff = grantless(h)
    mine = manual(h, {'executor': staff})
    manual(h)
    h.who[0] = staff
    seen = overview(h)
    assert [t['id'] for t in seen['tasks']] == [mine['id']]
    assert seen['allowed_actions'] == {'import': False, 'manage': False, 'work': True, 'decide_suggestions': False}
    assert seen['tasks'][0]['allowed_actions'] == ['start', 'block', 'complete']
    started = act(h, mine, 'start')
    assert started['state'] == 'in_progress'
    assert change(h, started['task'], {'title': 'renamed'}, 403)['code'] == 'sop_import_forbidden'


def test_a_person_with_no_grant_and_no_task_on_the_case_is_refused(h):
    manual(h, {'executor': grantless(h, 'assigned')})
    h.who[0] = grantless(h, 'bystander')
    assert h.client.get(URL + '/sop-tasks').status_code == 403
    assert h.client.get(URL + '/sop-assignees').status_code == 403


def prove_sales(h):
    with h.sessions.begin() as db:
        row = db.get(BusinessRow, ('w', 'projects', 'p1'))
        row.data = {**row.data, 'code': 'C115264'}


def close(h, node, status=200):
    return post(h, URL + '/sop-tasks/close-node', {'node_key': node}, status)


def test_close_node_completes_open_tasks_of_a_node_the_data_proves_done(h):
    apply(h)
    before = overview(h)
    assert before['node_done'] == {}
    assert close(h, 'sales', 409)['code'] == 'node_not_done_by_data'
    prove_sales(h)
    proven = overview(h)
    assert proven['node_done'] == {'sales': {'rule': 'c_code', 'reason': '工編以 C 開頭，業務階段已完成'}}
    open_sales = [t for t in proven['tasks'] if t['node_keys'] == ['sales'] and t['applicability'] == 'applicable']
    assert open_sales
    done = close(h, 'sales')
    assert done['closed'] == len(open_sales) and done['rule']['rule'] == 'c_code'
    after = overview(h)
    assert all(t['state'] == 'done' for t in after['tasks'] if t['id'] in {o['id'] for o in open_sales})
    assert after['node_counts']['sales']['done'] == after['node_counts']['sales']['total']
    assert all(t['state'] == 'pending' for t in after['tasks'] if t['node_keys'] == ['pm'])
    assert close(h, 'sales')['closed'] == 0
    assert close(h, 'field', 409)['code'] == 'node_not_done_by_data'


def test_close_node_leaves_unresolved_tasks_open_and_needs_a_manager(h):
    apply(h)
    prove_sales(h)
    h.who[0] = 'member'
    assert post(h, URL + '/sop-tasks/close-node', {'node_key': 'sales'}, 403)['code'] == 'sop_import_forbidden'
    h.who[0] = 'pm'
    held = by_row(h, 1)
    act(h, held, 'set_applicability', applicability='unresolved', reason='待確認')
    result = close(h, 'sales')
    assert result['left_open'] == {'shared': 0, 'unresolved': 1}
    assert by_row(h, 1)['state'] == 'pending'


def test_a_system_manager_without_any_grant_can_do_everything(h):
    apply(h)
    prove_sales(h)
    h.users['boss'] = {'id': 'boss', 'name': '系統管理員', 'role': 'manager', 'active': True, 'capabilities': []}
    h.who[0] = 'boss'
    allowed = overview(h)['allowed_actions']
    assert allowed['import'] and allowed['manage'] and allowed['work']
    assert close(h, 'sales')['closed'] > 0


def test_checker_reads_only_assigned_tasks_without_execution_and_assignees_stay_restricted(h):
    checker = grantless(h, 'checker')
    manual(h, {'checker': checker})
    h.who[0] = checker
    seen = overview(h)
    assert len(seen['tasks']) == 1 and seen['tasks'][0]['allowed_actions'] == []
    staff = grantless(h, 'staff')
    h.who[0] = 'pm'
    manual(h, {'executor': staff})
    h.who[0] = staff
    h.cfg['HR_VIEWERS'] = '*'
    listed = h.client.get(URL + '/sop-assignees').json()
    assert listed['restricted'] is True and [p['id'] for p in listed['people']] == [staff]
    assert overview(h)['node_done'] == {}


def test_a_waived_node_is_not_done_by_data_and_cannot_be_closed(h, monkeypatch):
    apply(h)
    prove_sales(h)
    assert 'sales' in overview(h)['node_done']
    monkeypatch.setattr('backend.sop_import.service.valid_waiver', lambda ws, p, n: n.get('key') == 'sales')
    with h.sessions.begin() as db:
        row = db.get(BusinessRow, ('w', 'projects', 'p1'))
        row.data = {**row.data, 'nodes': [{'id': 'real-p1-0', 'key': 'sales'}]}
    assert overview(h)['node_done'] == {}
    assert close(h, 'sales', 409)['code'] == 'node_not_done_by_data'
