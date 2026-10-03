"""Synthetic reproductions of current defects, not passing fix regressions."""
from backend.test_operations import ws, call, ready
from backend.operations import delivery_current, missing
import pytest
from fastapi import HTTPException
from backend.test_public_case_http_boundaries import isolated_http
from backend.app import WorkspaceRow, BusinessRow
from backend import storage


def test_delivery_can_be_approved_by_replaced_supervisor(ws):
    p, n = ready(ws, 'control')
    n['supervisor_id'] = 'u-control'
    old_supervisor = next(u for u in ws['users'] if u['id'] == 'u-control')
    assert old_supervisor['role'] == 'member' and not old_supervisor.get('_business_authority')
    proof = next(e for e in p['evidence'] if e['node_id'] == n['id'] and e['key'] == 'deliverable')
    call(ws, 'delivery_submit', {'work_item_ids': [n['tasks'][0]['id']],
        'evidence_ids': [proof['id']], 'quantity': 1, 'unit': 'batch'}, user='u-pm')
    item = p['delivery_batches'][-1]
    assert item['required_reviewer_ids'] == ['u-control']
    call(ws, 'project_roles', {'node_supervisor_id': 'u-field'}, key='control')
    assert n['supervisor_id'] == 'u-field'
    call(ws, 'delivery_review', {'id': item['id'], 'result': 'approved'}, user='u-control')
    assert item['status'] == 'approved'
    assert item['approvals'][0]['actor_id'] != n['supervisor_id']
    assert delivery_current(p, item)


def test_new_confirmation_evidence_can_finish_using_old_issue_acknowledgments(ws, isolated_http):
    p, n = ready(ws, 'confirmation')
    call(ws, 'confirmation_issue', {'version': '1', 'recipients': ['u-field']})
    old = p['confirmation_issues'][-1]
    # Run the real durable Worker simulation against an isolated database.
    app, _, _, _ = isolated_http
    wid = 'demo-review3-confirmation'
    with app.state.sessions.begin() as db:
        row = WorkspaceRow(id=wid, version=ws['version'], data={})
        db.add(row); db.flush()
        row.data = storage.save(db, BusinessRow, wid, ws)
    app.state.worker.run_one(wid)
    with app.state.sessions() as db:
        completed = storage.load(db, BusinessRow, db.get(WorkspaceRow, wid))
    ws.clear(); ws.update(completed)
    p = ws['projects'][0]
    n = next(node for node in p['nodes'] if node['key'] == 'confirmation')
    old = p['confirmation_issues'][-1]
    assert old['status'] == 'simulated' and old['receipts']
    call(ws, 'confirmation_ack', {'id': old['id'], 'evidence': 'old version checked'}, user='u-field')
    call(ws, 'evidence_submit', {'key': 'confirmation', 'note': 'changed scope version 2',
        'url': 'https://example.com/confirmation-v2'}, user='u-pm', key='confirmation')
    new_proof = p['evidence'][-1]
    assert new_proof['id'] != old['evidence_id']
    assert next(e for e in p['evidence'] if e['id'] == old['evidence_id'])['withdrawn']
    assert not missing(p, n, ws)
    call(ws, 'review_submit', key='confirmation', user='u-pm')
    cycle = n['review_cycles'][-1]
    call(ws, 'review_vote', {'cycle_id': cycle['id'], 'seat': 'owner', 'result': 'approved'},
         key='confirmation', user='u-pm')
    assert n['status'] == 'completed'
    assert len(p['confirmation_issues']) == 1


def test_handover_keeps_old_node_supervisor_and_review_seats(ws):
    p, n = ready(ws, 'control')
    call(ws, 'review_submit', key='control', user='u-pm')
    cycle = n['review_cycles'][-1]
    call(ws, 'handover_request', {'from_id': 'u-manager', 'to_id': 'u-field', 'reason': 'replacement'}, user='u-pm')
    h = ws['handover_requests'][-1]
    call(ws, 'handover_approve', {'id': h['id']})
    call(ws, 'handover_accept', {'id': h['id']}, user='u-field')
    assert p['supervisor_id'] == 'u-field'
    assert cycle['seats']['supervisor'] == 'u-field'
    assert n['supervisor_id'] == 'u-manager'
    # Resubmission returns the same internally inconsistent pending cycle.
    call(ws, 'review_submit', key='control', user='u-pm')
    assert n['review_cycles'][-1] is cycle
    with pytest.raises(HTTPException) as error:
        call(ws, 'review_vote', {'cycle_id': cycle['id'], 'seat': 'supervisor', 'result': 'approved'},
             key='control', user='u-field')
    assert error.value.status_code == 409
    assert '職責已變更' in error.value.detail
