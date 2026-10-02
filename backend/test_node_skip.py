"""A waiver is a versioned two-person decision, never delivered work or paid money."""
from copy import deepcopy

import pytest
from fastapi import HTTPException

from .seed import seed
from .policy import upgrade
from .node_skip import valid_waiver
from .operations import apply_operation, missing, project_summary, refresh_project_state
from .workflow import apply_action


@pytest.fixture
def ws():
    state = upgrade(seed()); state['environment'] = 'test'
    state['projects'][0]['supervisor_id'] = 'u-manager'
    state['projects'][0]['execution_system']='workbench'
    return state


def act(ws, action, payload=None, user='u-pm', key='control', demo=True):
    return apply_operation(ws, next(u for u in ws['users'] if u['id'] == user),
        {'action': 'node_skip_' + action, 'project_id': 'p1', 'node_id': 'p1-' + key,
         'payload': payload or {}}, demo)


def draft(ws, demo=True, key='control', user='u-pm'):
    act(ws, 'create', {'reason': '本案不適用', 'impact': '此範圍不納入交付；其他成果照常'}, key=key, demo=demo, user=user)
    return ws['node_skip_requests'][-1]


def approved(ws):
    item = draft(ws); act(ws, 'submit', {'id': item['id']})
    act(ws, 'vote', {'id': item['id'], 'seat': 'pm', 'result': 'approved'})
    act(ws, 'vote', {'id': item['id'], 'seat': 'supervisor', 'result': 'approved'}, user='u-manager')
    return item


def applied(ws):
    item = approved(ws); act(ws, 'apply', {'id': item['id']})
    return item


def node(ws, key='control'):
    return next(n for n in ws['projects'][0]['nodes'] if n['key'] == key)


def test_full_simulation_preserves_tasks_and_outputs_and_exposes_separate_counts(ws):
    n = node(ws); before = deepcopy(n['tasks']); item = applied(ws)
    assert n['status'] == 'approved_skipped' and n['tasks'] == before
    assert n['completed_at'] is None and valid_waiver(ws, ws['projects'][0], n)
    assert item['simulated'] and len(item['votes']) == 2
    summary = project_summary(ws, ws['projects'][0])
    assert summary['progress'] == {'completed_nodes': 4, 'approved_skipped_nodes': 1, 'total_nodes': 9}
    assert next(n for n in summary['nodes'] if n['id'] == 'p1-control')['skip']['label'] == '核准跳過（模擬）'

@pytest.mark.parametrize('status',['withdrawn','rejected','invalidated'])
def test_native_poll_terminal_status_removes_applied_waiver_without_erasing_history(ws,status):
    n=node(ws); previous=n['status']; item=applied(ws); tasks=deepcopy(n['tasks'])
    item['status']=status
    refresh_project_state(ws['projects'][0],ws)
    assert n['status']==previous and not n.get('skip_request_id')
    assert item['status']==status and n['tasks']==tasks


def test_formal_draft_never_submits_or_accepts_demo_votes(ws):
    ws['environment'] = 'production'; n = node(ws); before = deepcopy(n)
    item = draft(ws, demo=False)
    for action, extra in [('submit', {}), ('vote', {'seat': 'pm', 'result': 'approved'}), ('apply', {})]:
        with pytest.raises(HTTPException) as exc:
            act(ws, action, {'id': item['id'], **extra}, demo=False)
        assert exc.value.status_code == (409 if action=='apply' else 503)
    assert item['status'] == 'draft' and not item['simulated'] and n == before
    with pytest.raises(HTTPException): act(ws, 'submit', {'id': item['id']}, demo=True)


def test_one_actor_cannot_approve_both_seats_and_manager_has_no_override(ws):
    item = draft(ws); act(ws, 'submit', {'id': item['id']})
    with pytest.raises(HTTPException):
        act(ws, 'vote', {'id': item['id'], 'seat': 'pm', 'result': 'approved'}, user='u-manager')
    act(ws, 'vote', {'id': item['id'], 'seat': 'pm', 'result': 'approved'})
    with pytest.raises(HTTPException):
        act(ws, 'vote', {'id': item['id'], 'seat': 'supervisor', 'result': 'approved'})
    with pytest.raises(HTTPException): act(ws, 'apply', {'id': item['id']})
    assert item['status'] == 'pending' and node(ws)['status'] == 'in_progress'


@pytest.mark.parametrize('supervisor', ['', 'u-pm'])
def test_missing_or_identical_approvers_cannot_submit(ws, supervisor):
    ws['projects'][0]['supervisor_id'] = supervisor
    item = draft(ws)
    with pytest.raises(HTTPException): act(ws, 'submit', {'id': item['id']})
    assert item['status'] == 'draft'


@pytest.mark.parametrize('key', ['pricing', 'settlement', 'field'])
def test_financial_and_completed_nodes_cannot_skip(ws, key):
    with pytest.raises(HTTPException): draft(ws, key=key)
    assert not ws['node_skip_requests']


@pytest.mark.parametrize('change', ['revision', 'owner', 'supervisor', 'pm', 'task', 'evidence', 'disabled'])
def test_applied_skip_invalidates_on_changed_scope_or_authority_without_losing_history(ws, change):
    item = applied(ws); p = ws['projects'][0]; n = node(ws)
    old_history = deepcopy(item['history'])
    if change == 'revision': p['revision'] += 1
    elif change == 'owner': n['owner_id'] = 'u-agent'
    elif change == 'supervisor': p['supervisor_id'] = 'u-agent'
    elif change == 'pm': p['pm_id'] = 'u-agent'
    elif change == 'task': n['tasks'][0]['output'] = '新成果'
    elif change == 'evidence': p['evidence'].append({'id': 'new', 'node_id': n['id'], 'key': 'daily'})
    else: next(u for u in ws['users'] if u['id'] == 'u-manager')['active'] = False
    assert not valid_waiver(ws, p, n)
    refresh_project_state(p, ws)
    assert item['status'] == 'invalidated' and n['status'] == 'in_progress'
    assert item['history'][:-1] == old_history and len(item['votes']) == 2
    replacement = draft(ws, user=p['pm_id'])
    assert replacement['version'] == 2 and replacement['id'] != item['id']


def test_skipped_input_still_blocks_successor_that_requires_a_real_deliverable(ws):
    applied(ws)
    user = next(u for u in ws['users'] if u['id'] == 'u-map')
    with pytest.raises(HTTPException) as exc:
        apply_action(ws, user, {'action': 'task_start', 'project_id': 'p1',
            'task_id': 'p1-mapping-t1', 'payload': {}}, True)
    assert '不能替代實際交付資料' in exc.value.detail
    assert node(ws, 'mapping')['tasks'][0]['status'] == 'pending'


def test_valid_scope_waiver_never_bypasses_financial_requirements(ws):
    applied(ws); p = ws['projects'][0]
    for n in p['nodes']:
        if n['key'] in ('mapping', 'report'): n['status'] = 'completed'
    refresh_project_state(p, ws)
    assert p['execution_status'] == 'engineering_complete' and p['engineering_waivers']
    issues = missing(p, node(ws, 'settlement'), ws)
    assert '財務基準尚未核定' in issues and '收付款總額尚未核對結清' in issues
    assert p['execution_status'] != 'completed'
    assert missing(p, node(ws), ws) == ['此節點為核准跳過，不能當作完成或交付成果']


def test_rejection_withdrawal_and_stale_draft_leave_work_untouched(ws):
    before = deepcopy(node(ws)); item = draft(ws)
    act(ws, 'submit', {'id': item['id']})
    act(ws, 'vote', {'id': item['id'], 'seat': 'supervisor', 'result': 'rejected',
                    'reason': '仍需交付'}, user='u-manager')
    assert node(ws) == before and item['status'] == 'rejected'
    newer = draft(ws); ws['projects'][0]['revision'] += 1
    with pytest.raises(HTTPException): act(ws, 'submit', {'id': newer['id']})
    act(ws, 'withdraw', {'id': newer['id'], 'reason': '改版重提'})
    assert newer['status'] == 'withdrawn'


def test_simulated_waiver_cannot_be_reused_in_formal_workspace(ws):
    item = applied(ws); ws['environment'] = 'production'
    refresh_project_state(ws['projects'][0], ws)
    assert item['status'] == 'invalidated' and node(ws)['status'] != 'approved_skipped'


def test_node_review_cannot_turn_skip_into_completed(ws):
    applied(ws)
    with pytest.raises(HTTPException) as exc:
        apply_operation(ws, next(u for u in ws['users'] if u['id'] == 'u-pm'),
            {'action': 'node_complete', 'project_id': 'p1', 'node_id': 'p1-control', 'payload': {}}, True)
    assert '不能當作完成' in exc.value.detail


@pytest.mark.parametrize('change', ['archived', 'completed', 'source_completed', 'reason'])
def test_ready_approval_is_not_usable_after_completion_archive_or_content_change(ws, change):
    item = approved(ws); p = ws['projects'][0]; n = node(ws)
    if change == 'archived': p['archived_at'] = '2026-09-27T10:00:00+08:00'
    elif change == 'completed': n['status'] = 'completed'
    elif change == 'source_completed': n['source_completed'] = True
    else: item['reason'] = '已改成另一理由'
    refresh_project_state(p, ws)
    assert item['status'] == 'invalidated'
    with pytest.raises(HTTPException): act(ws, 'apply', {'id': item['id']})
    assert n['status'] != 'approved_skipped'
