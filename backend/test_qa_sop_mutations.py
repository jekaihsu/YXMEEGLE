from copy import deepcopy

import pytest
from sqlalchemy import select

from .sop_import.models import LocalTask, TaskEvent
from .test_sop_import import URL, h, overview, post, change


def stored(h):
    with h.sessions() as db:
        return ([tuple(deepcopy(getattr(t, c.name)) for c in LocalTask.__table__.columns) for t in db.scalars(select(LocalTask))],
                [(e.id, e.kind, e.changes) for e in db.scalars(select(TaskEvent))])


def test_saved_manual_task_and_nonempty_edit_reload_with_revision_and_date_reason(h):
    created = post(h, URL + '/sop-tasks', {'title': 'QA 核對', 'instructions': '原備註', 'node_keys': ['field'],
        'participants': {'executor': 'member'}, 'due_date': '2026-11-01'})['task']
    task = overview(h)['tasks'][0]
    assert (task['id'], task['title'], task['instructions'], task['participants'], task['local']['due_date'], task['node_keys'], task['state']) == (
        created['id'], 'QA 核對', '原備註', {'executor': 'member'}, '2026-11-01', ['field'], 'pending')
    before = stored(h)
    h.who[0] = 'member'
    assert change(h, task, {'title': '禁止修改'}, 403)['code'] == 'sop_import_forbidden'
    assert stored(h) == before
    h.who[0] = 'pm'
    assert change(h, task, {'due_date': '2026-11-03'}, 422)['code'] == 'invalid_request'
    assert stored(h) == before
    edited = change(h, task, {'title': 'QA 成果', 'instructions': '核對備註', 'participants': {'executor': 'other'},
        'due_date': '2026-11-03', 'reason': '配合現場時程'})['task']
    post(h, URL + '/sop-tasks/' + task['id'] + '/transition', {'expected_revision': edited['revision'], 'action': 'start'})
    reloaded = overview(h)['tasks'][0]
    assert (reloaded['title'], reloaded['instructions'], reloaded['participants'], reloaded['local']['due_date'], reloaded['local']['date_reason'], reloaded['state'], reloaded['revision']) == (
        'QA 成果', '核對備註', {'executor': 'other'}, '2026-11-03', '配合現場時程', 'in_progress', 3)
    before = stored(h)
    assert change(h, task, {'title': '舊版'}, 409)['code'] == 'task_revision_conflict'
    assert stored(h) == before


@pytest.mark.parametrize('body', [{'title': ' '}, {'due_date': '2026-02-30'}, {'participants': {'executor': 'missing'}}])
def test_invalid_manual_task_never_persists(h, body):
    before = stored(h)
    response = h.client.post(URL + '/sop-tasks', json={'title': 'QA', 'node_keys': ['field'], **body})
    assert response.status_code == 422
    assert response.json()['code'] in ('invalid_request', 'participant_unresolved')
    assert stored(h) == before
    assert overview(h)['counts']['total'] == 0


@pytest.mark.parametrize('who', ['member', 'other', 'restricted'])
def test_manual_task_creation_requires_management_and_writes_nothing_on_denial(h, who):
    h.users['restricted'] = {'id': 'restricted', 'role': 'member', 'active': True, 'capabilities': []}
    h.who[0] = who
    before = stored(h)
    denied = post(h, URL + '/sop-tasks', {'title': 'QA', 'node_keys': ['field']}, 403)
    assert denied['code'] == 'sop_import_forbidden'
    assert stored(h) == before
    h.who[0] = 'pm'
    assert overview(h)['counts']['total'] == 0


def test_manual_task_creation_disabled_keeps_existing_task_readable(h):
    post(h, URL + '/sop-tasks', {'title': '既有任務', 'node_keys': ['field']})
    h.cfg['SOP_TASK_WRITES_ENABLED'] = 'false'
    before = stored(h)
    assert post(h, URL + '/sop-tasks', {'title': 'QA', 'node_keys': ['field']}, 503)['code'] == 'import_unavailable'
    assert stored(h) == before
    assert [t['title'] for t in overview(h)['tasks']] == ['既有任務']
