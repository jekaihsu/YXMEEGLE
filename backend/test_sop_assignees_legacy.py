import pytest

from .test_sop_import import h, URL, post  # noqa: F401


@pytest.mark.parametrize('actor', ['admin', 'manager', 'member', 'restricted'])
def test_no_parameter_assignees_match_pre_picker_contract(h, actor):
    h.users['admin'] = {'id': 'admin', 'name': '管理員', 'role': 'admin'}
    h.users['restricted'] = {'id': 'restricted', 'name': '唯讀參與者', 'role': 'member', 'capabilities': []}
    for i in range(25):
        h.users[f'person-{i:02}'] = {'id': f'person-{i:02}', 'name': f'名冊{i:02}', 'department': '控制'}
    h.users['inactive'] = {'id': 'inactive', 'name': '離職', 'active': False}
    h.users['member']['department'] = 'PM'
    post(h, URL + '/sop-tasks', {'title': '參與任務', 'node_keys': ['pm'],
                              'participants': {'checker': 'restricted'}})
    h.who[0] = actor
    response = h.client.get(URL + '/sop-assignees')
    assert response.status_code == 200, response.text
    ids = ['restricted'] if actor == 'restricted' else [
        'pm', 'member', 'manager', *[f'person-{i:02}' for i in range(25)], 'other', 'restricted', 'admin']
    expected = [{'id': uid, 'name': h.users[uid]['name'],
                 'case_roles': {'pm': ['pm'], 'member': ['collaborator'], 'manager': ['manager']}.get(uid, []),
                 'department': h.users[uid].get('department')} for uid in ids]
    assert response.json() == {'project_id': 'p1', 'restricted': actor == 'restricted', 'people': expected}
