from copy import deepcopy

import pytest
from fastapi import HTTPException

from .jobs import schedule
from .operations import apply_operation
from .workflow import apply_action
from .workflow_rules import confirmation_hash
from .test_workflow_automation import setup, body, items
from .test_ux_disabled import client


@pytest.fixture
def production(setup):
    ws, p, n, user = setup
    ws['environment'] = 'production'
    ws['features'] = {'routines': False, 'change_extension': False}
    ws['people_directory_status'] = {'app_id': 'app1'}
    user.update(identity_app_id='app1', directory_status='employed',
                directory_source={'app_id': 'app1', 'record_id': 'synthetic'},
                directory_last_seen_at='2026-09-28T08:00:00+08:00')
    p.update(source_kind='lark', execution_system='workbench', case_type='formal',
             source_lifecycle={'state': 'mapped', 'canonical': '執行中', 'reasons': []})
    return ws, p, n, user


OWNERSHIP = [
    {'sop_rule_id': 'quote_followup'},
    {'completion_scope': 'post_completion_followup'},
    {'sop_round': 1},
]


@pytest.mark.parametrize('ownership', OWNERSHIP)
@pytest.mark.parametrize('action', ['task_start', 'task_complete', 'task_update', 'task_batch_complete', 'review_submit', 'node_complete'])
def test_disabled_task_mutations_are_atomic(production, ownership, action):
    ws, p, n, user = production
    t = n['tasks'][-1]
    t.update(ownership)
    if action in ('task_complete', 'task_batch_complete'):
        for task in n['tasks']:
            task['status'] = 'in_progress'
    if action in ('review_submit', 'node_complete'):
        for task in n['tasks']:
            task.update(status='completed', output='成果')
    payload = {'output': '成果', 'title': '改名'}
    if action == 'task_batch_complete':
        payload = {'items': items(p, n)}
    request = body(p, n, action, payload, t if action in ('task_start', 'task_complete', 'task_update') else None)
    before = deepcopy(ws)
    with pytest.raises(HTTPException) as error:
        if not apply_operation(ws, user, request):
            apply_action(ws, user, request)
    assert error.value.status_code == 403
    assert error.value.detail['code'] == 'feature_disabled'
    assert ws == before


@pytest.mark.parametrize('ownership', OWNERSHIP)
def test_scheduled_activation_skips_disabled_tasks_and_resumes_on_opt_in(production, ownership):
    ws, p, n, user = production
    t = n['tasks'][-1]
    t.update(ownership)
    before = deepcopy(t)
    schedule(ws, '2026-09-28T09:01:00+08:00')
    assert t == before
    assert n['tasks'][0]['status'] == 'in_progress'
    assert not any(e.get('task_id') == t['id'] for e in ws['events'])
    assert ws['jobs'] == []
    ws['features'] = {'routines': True, 'change_extension': True}
    schedule(ws, '2026-09-28T09:02:00+08:00')
    assert t['status'] == 'in_progress'
    assert t['activation_source'] == 'schedule'


@pytest.mark.parametrize('ownership', OWNERSHIP)
def test_opt_in_preserves_start_complete_and_batch(production, ownership):
    ws, p, n, user = production
    ws['features'] = {'routines': True, 'change_extension': True}
    t = n['tasks'][0]
    t.update(ownership)
    apply_action(ws, user, body(p, n, 'task_start', t=t))
    assert t['status'] == 'in_progress'
    apply_action(ws, user, body(p, n, 'task_complete', {'output': '成果'}, t))
    assert (t['status'], t['output']) == ('completed', '成果')
    t = n['tasks'][1]
    t.update(ownership, status='in_progress')
    item = dict(project_id=p['id'], node_id=n['id'], task_id=t['id'], revision=t['revision'],
                confirmation_hash=confirmation_hash(p, n, t), output='批次成果')
    apply_action(ws, user, body(p, n, 'task_batch_complete', {'items': [item]}))
    assert (t['status'], t['output']) == ('completed', '批次成果')


@pytest.mark.parametrize('action', ['task_start', 'task_complete', 'task_update', 'task_batch_complete', 'review_submit'])
def test_http_denial_has_only_one_denied_audit(client, action):
    from sqlalchemy import select
    from .app import WorkspaceRow, BusinessRow, AuditRow
    from . import storage
    from .test_ux_disabled import snapshot
    with client.app.state.sessions.begin() as db:
        row = db.scalar(select(WorkspaceRow))
        ws = storage.load(db, BusinessRow, row)
        p = ws['projects'][0]
        n = next(n for n in p['nodes'] if n['key'] == 'control')
        t = n['tasks'][0]
        t.update(sop_rule_id='quote_followup', status='in_progress')
        row.data = storage.save(db, BusinessRow, row.id, ws)
    before = snapshot(client)
    payload = {'output': '成果', 'title': '改名'}
    request = body(p, n, action, payload, t if action.startswith('task_') else None)
    if action == 'task_batch_complete':
        request['task_id'] = None
        request['payload'] = {'items': items(p, n)}
    request.update(version=before[1], request_id='disabled-task')
    response = client.post('/api/actions', json=request)
    assert response.status_code == 403
    assert response.json()['code'] == 'feature_disabled'
    assert response.headers['cache-control'] == 'no-store'
    assert snapshot(client) == before
    with client.app.state.sessions() as db:
        records = list(db.scalars(select(AuditRow)))
        assert len(records) == 1
        assert records[0].data['result'] == 'denied'


@pytest.mark.parametrize('action', ['approval_create', 'approval_submit'])
def test_enabled_approval_cannot_mutate_disabled_routine(production, action):
    ws, p, n, user = production
    ws['features']['change_extension'] = True
    t = n['tasks'][0]
    t['sop_rule_id'] = 'quote_followup'
    ws['approvals'] = [dict(id='existing', project_id=p['id'], task_ids=[t['id']])]
    payload = {'approval_id': 'existing'} if action == 'approval_submit' else {
        'type': 'extension', 'dates': [{'task_id': t['id'], 'due_date': '2026-10-01'}]}
    before = deepcopy(ws)
    with pytest.raises(HTTPException) as error:
        apply_action(ws, user, body(p, n, action, payload))
    assert error.value.status_code == 403
    assert error.value.detail['code'] == 'feature_disabled'
    assert error.value.detail['feature'] == 'routines'
    assert ws == before


def test_disabled_task_mentions_are_not_generated_or_dispatched(production):
    from .mention_notifications import enqueue_mentions, check_notification
    ws, p, n, user = production
    t = n['tasks'][0]
    t['sop_rule_id'] = 'quote_followup'
    comment = dict(id='old-comment', author_id=user['id'], mentions=['u-pm'])
    t['comments'].append(comment)
    enqueue_mentions(ws, user, p, n, t, comment, True)
    assert comment['notifications'] == []
    assert ws['jobs'] == []
    payload = dict(project_id=p['id'], node_id=n['id'], task_id=t['id'],
                   comment_id=comment['id'], recipient_id='u-pm')
    before = deepcopy(ws)
    with pytest.raises(HTTPException) as error:
        check_notification(ws, user, payload, {}, True)
    assert error.value.detail['code'] == 'feature_disabled'
    assert ws == before
    ws['features']['routines'] = True
    enqueue_mentions(ws, user, p, n, t, comment, True)
    assert len(ws['jobs']) == 1
    assert ws['jobs'][0]['kind'] == 'mention'
    assert check_notification(ws, user, payload, {}, True) == (p, comment)
