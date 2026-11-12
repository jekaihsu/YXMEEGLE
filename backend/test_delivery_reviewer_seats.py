"""Issue #54: delivery approvals follow current, active node supervisors."""
from copy import deepcopy

import pytest
from fastapi import HTTPException

from .operations import delivery_current, delivery_references
from .test_workflow_completion import state, action, prepared, payment


def submit(ws, supervisors):
    p = ws['projects'][0]
    tasks, evidence = [], []
    for key, supervisor in supervisors.items():
        _, node = prepared(ws, key)
        node['supervisor_id'] = supervisor
        tasks.append(node['tasks'][0]['id'])
        evidence.append(next(e['id'] for e in reversed(p['evidence'])
                             if e['node_id'] == node['id'] and e['key'] in ('deliverable', 'field_report')))
    action(ws, 'delivery_submit', dict(work_item_ids=tasks, evidence_ids=evidence,
                                      quantity='1', unit='批'), user='u-pm')
    return p, p['delivery_batches'][-1]


def approve(ws, item, user):
    action(ws, 'delivery_review', {'id': item['id'], 'result': 'approved'}, user=user)


@pytest.mark.parametrize('result', ['approved', 'returned'])
def test_replaced_member_cannot_vote(state, result):
    p, item = submit(state, {'control': 'u-control'})
    old = next(u for u in state['users'] if u['id'] == 'u-control')
    assert old['role'] == 'member' and not old.get('_business_authority')
    action(state, 'project_roles', {'node_supervisor_id': 'u-field'}, key='control')
    before = deepcopy(item)
    with pytest.raises(HTTPException) as exc:
        action(state, 'delivery_review', {'id': item['id'], 'result': result,
                                        'reason': '退回'}, user='u-control')
    assert exc.value.status_code == 403 and item == before
    approve(state, item, 'u-field')
    assert delivery_current(p, item, state)


def test_partial_vote_reassignment_preserves_history_and_unrelated_seat(state):
    p, item = submit(state, {'control': 'u-control', 'field': 'u-report'})
    approve(state, item, 'u-control')
    prior = deepcopy(item['approvals'][0])
    action(state, 'project_roles', {'node_supervisor_id': 'u-field'}, key='control')
    assert item['approval_history'][0]['actor_id'] == prior['actor_id']
    assert item['approval_history'][0]['at'] == prior['at']
    approve(state, item, 'u-report')
    assert item['status'] == 'submitted' and not delivery_current(p, item, state)
    approve(state, item, 'u-field')
    assert delivery_current(p, item, state)


def test_same_reviewer_set_cannot_reuse_vote_for_new_node_seat(state):
    p, item = submit(state, {'control': 'u-control', 'field': 'u-field'})
    approve(state, item, 'u-field')
    action(state, 'project_roles', {'node_supervisor_id': 'u-field'}, key='control')
    # u-field's earlier vote covered only field, not the newly assigned control seat.
    assert item['status'] == 'submitted' and not delivery_current(p, item, state)
    approve(state, item, 'u-field')
    assert delivery_current(p, item, state)


def test_approved_reassignment_requires_confirmation_and_blocks_payment(state):
    p, item = submit(state, {'control': 'u-control'})
    approve(state, item, 'u-control')
    batch = payment(state, item)
    prior_hash = item['content_hash']
    action(state, 'project_roles', {'node_supervisor_id': 'u-field'}, key='control')
    assert item['status'] == 'submitted' and not delivery_current(p, item, state)
    assert batch['status'] == 'needs_review'
    assert item['approval_history'][0]['actor_id'] == 'u-control'
    with pytest.raises(HTTPException) as exc:
        delivery_references(p, [item['id']], state)
    assert exc.value.status_code == 409
    approve(state, item, 'u-field')
    assert delivery_current(p, item, state) and item['content_hash'] == prior_hash
    assert batch['status'] == 'needs_review'  # Financial confirmation must be renewed separately.


@pytest.mark.parametrize('approved', [False, True])
def test_inactive_supervisor_cannot_count_or_vote(state, approved):
    supervisors = {'control': 'u-control'} if approved else {'control': 'u-control', 'field': 'u-field'}
    p, item = submit(state, supervisors)
    approve(state, item, 'u-control')
    action(state, 'admin_person', {'id': 'u-control', 'active': False})
    assert not delivery_current(p, item, state)
    assert item['approval_history'][0]['actor_id'] == 'u-control'
    with pytest.raises(HTTPException) as exc:
        approve(state, item, 'u-control')
    assert exc.value.status_code == 403
    if not approved:
        with pytest.raises(HTTPException) as exc:
            approve(state, item, 'u-field')
        assert exc.value.status_code == 409
    action(state, 'admin_person', {'id': 'u-control', 'active': True})
    assert not delivery_current(p, item, state)
    approve(state, item, 'u-control')
    if not approved:
        approve(state, item, 'u-field')
    assert delivery_current(p, item, state)


def test_project_fallback_and_unrelated_node_reassignment(state):
    p, item = submit(state, {'control': ''})
    approve(state, item, 'u-manager')
    action(state, 'project_roles', {'node_supervisor_id': 'u-field'}, key='field')
    assert delivery_current(p, item, state) and not item.get('approval_history')
    action(state, 'project_roles', {'supervisor_id': 'u-control'})
    assert not delivery_current(p, item, state)
    approve(state, item, 'u-control')
    assert delivery_current(p, item, state)


def test_missing_supervisor_blocks_entire_batch(state):
    p, item = submit(state, {'control': 'u-control', 'field': 'u-field'})
    approve(state, item, 'u-control')
    action(state, 'project_roles', {'supervisor_id': '', 'node_supervisor_id': ''}, key='field')
    with pytest.raises(HTTPException) as exc:
        approve(state, item, 'u-control')
    assert exc.value.status_code == 409 and not delivery_current(p, item, state)


def test_reassignment_back_does_not_restore_old_approval(state):
    p, item = submit(state, {'control': 'u-control'})
    approve(state, item, 'u-control')
    action(state, 'project_roles', {'node_supervisor_id': 'u-field'}, key='control')
    action(state, 'project_roles', {'node_supervisor_id': 'u-control'}, key='control')
    assert not delivery_current(p, item, state)
    approve(state, item, 'u-control')
    assert delivery_current(p, item, state)


def test_partial_shared_vote_keeps_only_unchanged_node_seat(state):
    p, item = submit(state, {'control': 'u-control', 'field': 'u-control', 'mapping': 'u-report'})
    approve(state, item, 'u-control')
    prior = deepcopy(item['approvals'][0])
    action(state, 'project_roles', {'node_supervisor_id': 'u-field'}, key='control')
    field = next(n for n in p['nodes'] if n['key'] == 'field')
    assert item['approvals'][0]['node_ids'] == [field['id']]
    assert item['approval_history'][0]['node_ids'] == prior['node_ids']
    approve(state, item, 'u-report')
    assert item['status'] == 'submitted'
    approve(state, item, 'u-field')
    assert delivery_current(p, item, state)


def test_handover_retires_delivery_vote(state):
    p, item = submit(state, {'control': 'u-control'})
    approve(state, item, 'u-control')
    action(state, 'handover_request', {'from_id': 'u-control', 'to_id': 'u-field', 'reason': '主管交接'})
    handover = state['handover_requests'][-1]
    action(state, 'handover_approve', {'id': handover['id']})
    action(state, 'handover_accept', {'id': handover['id']}, user='u-field')
    assert item['status'] == 'submitted' and not delivery_current(p, item, state)
    approve(state, item, 'u-field')
    assert delivery_current(p, item, state)


def test_legacy_person_only_vote_requires_seat_confirmation(state):
    p, item = submit(state, {'control': 'u-control'})
    approve(state, item, 'u-control')
    del item['required_reviewer_seats']
    del item['approvals'][0]['node_ids']
    prior = deepcopy(item['approvals'][0])
    from .operations import refresh_project_state
    refresh_project_state(p, state)
    assert item['status'] == 'submitted' and not delivery_current(p, item, state)
    assert all(item['approval_history'][0][key] == value for key, value in prior.items())
    approve(state, item, 'u-control')
    assert delivery_current(p, item, state)


def test_current_check_rejects_inactive_or_missing_reviewer_before_refresh(state):
    p, item = submit(state, {'control': 'u-control'})
    approve(state, item, 'u-control')
    person = next(u for u in state['users'] if u['id'] == 'u-control')
    person['active'] = False
    assert not delivery_current(p, item, state)
    person['active'] = True
    state['users'].remove(person)
    assert not delivery_current(p, item, state)
