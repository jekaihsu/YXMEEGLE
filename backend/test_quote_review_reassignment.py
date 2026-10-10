"""Issue #56: quote votes belong to current, active PM and sales principals."""
from copy import deepcopy

import pytest
from fastapi import HTTPException

from .operations import apply_operation, digest
from .policy import upgrade
from .seed import USERS, seed


@pytest.fixture
def state():
    ws = upgrade(seed())
    ws['users'] = deepcopy(USERS)
    ws['projects'][0].update(pm_id='u-pm', sales_id='u-field', admin_id='u-manager',
                             quotes=[{'id': 'quote1', 'amount': 100}])
    return ws


def action(ws, name, payload, actor='u-manager'):
    user = next(u for u in ws['users'] if u['id'] == actor)
    return apply_operation(ws, user, {'action': name, 'project_id': ws['projects'][0]['id'],
                                     'payload': payload}, True)


def vote(ws, actor, seat):
    return action(ws, 'quote_review', {'quote_id': 'quote1', 'seat': seat,
                                     'classification': 'effective'}, actor)


def reassign(ws, method, seat):
    if method == 'project_roles':
        action(ws, method, {seat + '_id': 'u-control'})
    else:
        prior = ws['projects'][0][seat + '_id']
        action(ws, 'handover_request', {'from_id': prior, 'to_id': 'u-control', 'reason': '調派'},
               ws['projects'][0]['pm_id'])
        ident = ws['handover_requests'][-1]['id']
        action(ws, 'handover_approve', {'id': ident})
        action(ws, 'handover_accept', {'id': ident}, 'u-control')


@pytest.mark.parametrize('method,seat', [('project_roles', 'pm'), ('project_roles', 'sales'),
                                       ('handover', 'pm')])
def test_reassignment_requires_replacement_vote_and_preserves_history(state, method, seat):
    p = state['projects'][0]
    prior = p[seat + '_id']
    other_seat = 'sales' if seat == 'pm' else 'pm'
    other = p[other_seat + '_id']
    vote(state, prior, seat)
    old = p['quote_reviews'][-1]
    old_votes = deepcopy(old['votes'])
    reassign(state, method, seat)
    assert old['status'] == 'invalidated'
    assert old['invalidated_reason'] and old['invalidated_at']
    assert old['votes'] == old_votes
    with pytest.raises(HTTPException) as error:
        vote(state, prior, seat)
    assert error.value.status_code == 403
    vote(state, other, other_seat)
    current = p['quote_reviews'][-1]
    assert current['status'] == 'pending'
    vote(state, 'u-control', seat)
    assert current['status'] == 'approved'
    assert current['principal_ids'] == {'pm': p['pm_id'], 'sales': p['sales_id']}
    assert current['source_hash'] == digest(p['quotes'][0])
    assert {v['seat']: v['actor_id'] for v in current['votes']} == current['principal_ids']
    assert old['status'] == 'invalidated' and old['votes'] == old_votes


@pytest.mark.parametrize('method', ['project_roles', 'handover'])
def test_completed_review_is_unchanged_by_reassignment(state, method):
    vote(state, 'u-pm', 'pm')
    vote(state, 'u-field', 'sales')
    old = state['projects'][0]['quote_reviews'][-1]
    before = deepcopy(old)
    reassign(state, method, 'pm')
    assert old == before and old['status'] == 'approved'


@pytest.mark.parametrize('method', ['project_roles', 'handover'])
def test_unchanged_seats_keep_pending_vote_and_complete_normally(state, method):
    vote(state, 'u-pm', 'pm')
    if method == 'project_roles':
        action(state, method, {'pm_id': 'u-pm', 'sales_id': 'u-field'})
    else:
        reassign(state, method, 'admin')
    vote(state, 'u-field', 'sales')
    reviews = state['projects'][0]['quote_reviews']
    assert len(reviews) == 1 and reviews[0]['status'] == 'approved'


@pytest.mark.parametrize('seat', ['pm', 'sales'])
@pytest.mark.parametrize('already_voted', [False, True])
def test_inactive_counterpart_cannot_contribute_to_review(state, seat, already_voted):
    p = state['projects'][0]
    prior = p[seat + '_id']
    other_seat = 'sales' if seat == 'pm' else 'pm'
    if already_voted:
        vote(state, prior, seat)
    next(u for u in state['users'] if u['id'] == prior)['active'] = False
    before = deepcopy(p['quote_reviews'])
    with pytest.raises(HTTPException) as error:
        vote(state, p[other_seat + '_id'], other_seat)
    assert error.value.status_code == 403
    assert p['quote_reviews'] == before


@pytest.mark.parametrize('change', ['quote_version', 'legacy_principals'])
def test_votes_with_different_or_missing_binding_cannot_complete_review(state, change):
    p = state['projects'][0]
    vote(state, 'u-pm', 'pm')
    old = p['quote_reviews'][-1]
    if change == 'quote_version':
        p['quotes'][0]['amount'] = 200
    else:
        del old['principal_ids']
    vote(state, 'u-field', 'sales')
    current = p['quote_reviews'][-1]
    assert current['id'] != old['id'] and current['status'] == 'pending'
    assert old['status'] != 'approved'
    vote(state, 'u-pm', 'pm')
    assert current['status'] == 'approved'
    assert current['source_hash'] == digest(p['quotes'][0])
