from copy import deepcopy

import pytest

from .sop_import.models import CasePolicy
from .test_node_assignment_routes import NODES, TASKS, URL, act, h, view


def test_saved_assignment_survives_a_new_client_and_conflicts_without_overwriting(h):
    h.who[0] = 'ou_fm'
    revision = h.client.get(URL + '/nodes/field').json()['node']['revision']
    response = act(h, 'ou_fm', '/nodes/field/assign', {
        'request_id': 'saved-assignment', 'expected_revision': revision, 'owner_open_ids': ['ou_member']})
    assert response.status_code == 200, response.text
    h.clock[0] += 1000
    reloaded = h.build().get(URL + '/nodes/field').json()['node']
    assert [p['open_id'] for p in reloaded['owners']] == ['ou_member']
    before = deepcopy(h.fake.tables)
    stale = act(h, 'ou_fm', '/nodes/field/assign', {
        'request_id': 'stale-assignment', 'expected_revision': revision, 'owner_open_ids': ['ou_depth']})
    assert (stale.status_code, stale.json()['code']) == (409, 'revision_conflict')
    assert h.fake.tables == before
    assert len(h.fake.tables[NODES]) == 1


@pytest.mark.parametrize('who', ['ou_member', 'ou_om', 'ou_gone'])
def test_assignment_role_denial_cannot_create_or_update_a_row(h, who):
    before = deepcopy(h.fake.tables)
    denied = act(h, who, '/nodes/field/assign', {
        'request_id': 'denied-assignment', 'owner_open_ids': ['ou_member']})
    assert (denied.status_code, denied.json()['code']) == (403, 'forbidden')
    assert h.fake.tables == before
    assert h.fake.writes() == []


def test_saved_task_fields_and_nonempty_patch_survive_reload(h):
    created = act(h, 'ou_fm', '/nodes/field/tasks', {
        'request_id': 'saved-task', 'title': 'QA 測量', 'detail': '原備註',
        'assignee_open_id': 'ou_member', 'department': '外業', 'deadline': '2026-11-01'})
    assert created.status_code == 200, created.text
    task = h.build().get(URL + '/nodes/field').json()['tasks'][0]
    assert (task['title'], task['detail'], task['assignee']['open_id'], task['department'], task['deadline'], task['status']) == (
        'QA 測量', '原備註', 'ou_member', '外業', '2026-11-01', '待處理')
    path = f'/nodes/field/tasks/{task["id"]}'
    before = deepcopy(h.fake.tables)
    denied = act(h, 'ou_om', path, {
        'request_id': 'denied-edit', 'expected_revision': task['revision'], 'title': '不可改'}, method='patch')
    assert (denied.status_code, denied.json()['code']) == (403, 'forbidden')
    assert h.fake.tables == before
    edited = act(h, 'ou_fm', path, {
        'request_id': 'saved-edit', 'expected_revision': task['revision'], 'title': 'QA 核對', 'detail': '核對備註',
        'assignee_open_id': 'ou_depth', 'deadline': '2026-11-03', 'status': '進行中'}, method='patch')
    assert edited.status_code == 200, edited.text
    h.clock[0] += 1000
    reloaded = h.build().get(URL + '/nodes/field').json()['tasks'][0]
    assert (reloaded['title'], reloaded['detail'], reloaded['assignee']['open_id'], reloaded['deadline'], reloaded['status']) == (
        'QA 核對', '核對備註', 'ou_depth', '2026-11-03', '進行中')
    before = deepcopy(h.fake.tables)
    stale = act(h, 'ou_fm', path, {
        'request_id': 'stale-edit', 'expected_revision': task['revision'], 'title': '舊版'}, method='patch')
    assert (stale.status_code, stale.json()['code']) == (409, 'revision_conflict')
    assert h.fake.tables == before
    assert len(h.fake.tables[TASKS]) == 1


@pytest.mark.parametrize('patch', [{'title': ' '}, {'deadline': '2026-02-30'}, {'department': '行政'}])
def test_invalid_task_creation_writes_nothing(h, patch):
    before = deepcopy(h.fake.tables)
    response = act(h, 'ou_fm', '/nodes/field/tasks', {
        'request_id': 'invalid-task', 'title': 'QA', 'assignee_open_id': 'ou_member', **patch})
    assert (response.status_code, response.json()['code']) == (422, 'invalid')
    assert h.fake.tables == before
    assert h.fake.writes() == []


@pytest.mark.parametrize('who', ['ou_om', 'ou_gone'])
def test_restricted_task_creator_writes_nothing(h, who):
    before = deepcopy(h.fake.tables)
    response = act(h, who, '/nodes/field/tasks', {'request_id': 'denied-task', 'title': 'QA', 'department': '外業'})
    assert (response.status_code, response.json()['code']) == (403, 'forbidden')
    assert h.fake.tables == before
    assert h.fake.writes() == []


def test_disabled_writes_explain_assignment_and_creation_denial(h):
    h.who[0] = 'ou_fm'
    h.state['settings']['external_enabled'] = False
    client = h.build()
    before = deepcopy(h.fake.tables)
    body = client.get(URL).json()
    assert body['can']['field']['assign'] is False
    for path, payload in [('/nodes/field/assign', {'owner_open_ids': ['ou_member']}),
                          ('/nodes/field/tasks', {'title': 'QA', 'department': '外業'})]:
        response = client.post(URL + path, json={'request_id': 'disabled', **payload})
        assert (response.status_code, response.json()['code']) == (403, 'writes_disabled')
    assert h.fake.tables == before
    assert h.fake.writes() == []
