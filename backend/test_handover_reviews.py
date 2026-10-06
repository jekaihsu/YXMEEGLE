"""Issue #55: accepted responsibilities remain usable in pending reviews."""
from copy import deepcopy

import pytest
from fastapi import HTTPException

from .operations import review_hash, seats
from .test_operations import ws, call, ready


def accept(ws, prior='u-manager', replacement='u-field'):
    call(ws, 'handover_request', {'from_id': prior, 'to_id': replacement, 'reason': '職責交接'})
    handover = ws['handover_requests'][-1]
    call(ws, 'handover_approve', {'id': handover['id']})
    call(ws, 'handover_accept', {'id': handover['id']}, user=replacement)


def approve(ws, node, seat, actor):
    call(ws, 'review_vote', {'cycle_id': node['review_cycles'][-1]['id'],
                           'seat': seat, 'result': 'approved'}, user=actor, key=node['key'])


@pytest.mark.parametrize('resubmit', [False, True])
def test_supervisor_handover_can_finish_pending_review(ws, resubmit):
    p, node = ready(ws, 'control')
    _, unrelated = ready(ws, 'field')
    unrelated['supervisor_id'] = 'u-control'
    call(ws, 'review_submit', key='field', user='u-pm')
    untouched = deepcopy(unrelated)
    call(ws, 'review_submit', key='control', user='u-pm')
    cycle = node['review_cycles'][-1]
    approve(ws, node, 'supervisor', 'u-manager')
    accept(ws)
    assert p['supervisor_id'] == node['supervisor_id'] == 'u-field'
    assert unrelated == untouched
    assert cycle['seats'] == seats(p, node)
    assert cycle['content_hash'] == review_hash(p, node)
    assert cycle['votes'][0]['invalidated'] == '職責交接'
    if resubmit:
        call(ws, 'review_submit', key='control', user='u-pm')
        assert node['review_cycles'][-1] is cycle
    with pytest.raises(HTTPException) as error:
        approve(ws, node, 'supervisor', 'u-manager')
    assert error.value.status_code == 403
    approve(ws, node, 'owner', 'u-pm')
    assert cycle['status'] == 'pending'
    approve(ws, node, 'supervisor', 'u-field')
    assert cycle['status'] == 'approved' and node['status'] == 'completed'


def test_reviewer_handover_rekeys_seat_and_preserves_other_vote(ws):
    p, node = ready(ws, 'sales')
    node.update(reviewers=['u-manager', 'u-pm', 'u-control'], review_mode='all')
    call(ws, 'review_submit', key='sales', user='u-pm')
    approve(ws, node, 'person:u-manager', 'u-manager')
    approve(ws, node, 'person:u-pm', 'u-pm')
    cycle = node['review_cycles'][-1]
    assert cycle['status'] == 'pending'
    accept(ws)
    assert node['reviewers'] == ['u-field', 'u-pm', 'u-control']
    assert cycle['seats'] == seats(p, node)
    assert 'person:u-manager' not in cycle['seats']
    assert cycle['content_hash'] == review_hash(p, node)
    assert cycle['votes'][0]['invalidated'] == '職責交接'
    assert not cycle['votes'][1].get('invalidated')
    approve(ws, node, 'person:u-field', 'u-field')
    approve(ws, node, 'person:u-control', 'u-control')
    assert node['status'] == 'completed'


def test_owner_handover_and_financial_handover_preserve_other_votes(ws):
    p, node = ready(ws, 'control')
    call(ws, 'review_submit', key='control', user='u-pm')
    approve(ws, node, 'supervisor', 'u-manager')
    accept(ws, prior='u-pm', replacement='u-agent')
    assert p['pm_id'] == node['owner_id'] == 'u-agent'
    assert node['review_cycles'][-1]['content_hash'] == review_hash(p, node)
    approve(ws, node, 'owner', 'u-agent')
    assert node['status'] == 'completed'

    _, financial = ready(ws, 'pricing')
    call(ws, 'review_submit', key='pricing', user='u-agent')
    approve(ws, financial, 'pm', 'u-agent')
    accept(ws)
    cycle = financial['review_cycles'][-1]
    assert cycle['seats'] == seats(p, financial)
    assert cycle['content_hash'] == review_hash(p, financial)
    assert not cycle['votes'][0].get('invalidated')
    approve(ws, financial, 'admin', 'u-field')
    assert financial['status'] == 'completed'


def test_handover_does_not_refresh_a_stale_content_hash(ws):
    p, node = ready(ws, 'control')
    call(ws, 'review_submit', key='control', user='u-pm')
    cycle = node['review_cycles'][-1]
    node['tasks'][0]['output'] = '已變更成果'
    accept(ws)
    assert cycle['status'] == 'invalidated'
    assert cycle['content_hash'] != review_hash(p, node)
    call(ws, 'review_submit', key='control', user='u-pm')
    approve(ws, node, 'owner', 'u-pm')
    approve(ws, node, 'supervisor', 'u-field')
    assert node['status'] == 'completed'
