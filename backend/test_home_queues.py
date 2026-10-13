"""Personal Home queues require current, explicit ownership or review evidence."""
from copy import deepcopy

from .home_queues import home_queues
from .operations import delivery_fingerprint, review_hash


def workspace():
    users = [{'id': ident, 'name': ident, 'active': True} for ident in ('viewer', 'other', 'proxy')]
    assigned = {'id': 'assigned', 'title': 'Assigned by viewer', 'owner_id': 'other', 'status': 'pending',
                'assignment_history': [{'actor_id': 'viewer', 'after': {'owner_id': 'other'}, 'at': '2026-10-01T09:00:00+08:00'}]}
    delegated = {'id': 'delegated', 'title': 'Viewer owns task', 'owner_id': 'viewer', 'status': 'pending',
                 'assignment_history': [{'actor_id': 'other', 'after': {'owner_id': 'viewer'}, 'at': '2026-10-01T09:00:00+08:00'}]}
    node = {'id': 'node', 'key': 'sales', 'name': 'Sales review', 'status': 'pending', 'owner_id': 'viewer',
            'reviewers': [], 'review_mode': 'all', 'requirements': [], 'tasks': [assigned, delegated], 'review_cycles': []}
    project = {'id': 'case', 'code': 'CASE', 'name': 'Case', 'execution_system': 'workbench', 'nodes': [node],
               'evidence': [], 'files': [], 'finance_versions': [], 'payment_batches': []}
    ws = {'environment': 'production', 'users': users, 'projects': [project], 'delegations': [],
          'approved_leave_delegations': [], 'handover_requests': []}
    node['review_cycles'] = [{'id': 'cycle', 'status': 'pending', 'mode': 'all', 'content_hash': review_hash(project, node),
                              'seats': {'owner': 'viewer'}, 'votes': []}]
    return ws


def test_current_review_handover_assignment_and_delegation_are_distinct_and_read_only():
    ws = workspace()
    ws['handover_requests'] = [{'id': 'handover', 'project_id': 'case', 'from_id': 'other',
                                'to_id': 'viewer', 'status': 'awaiting_acceptance'}]
    ws['delegations'] = [{'id': 'delegate', 'project_id': 'case', 'principal_id': 'viewer',
                          'delegate_id': 'proxy', 'scope': 'tasks', 'seat': 'owner', 'task_ids': ['delegated'],
                          'status': 'active', 'start_date': '2020-01-01', 'end_date': '2099-12-31',
                          'source': 'supervisor', 'qualified': True, 'qualification_evidence': 'approved'}]
    before = deepcopy(ws)
    got = home_queues(ws, ws['users'][0])
    assert ws == before
    assert {x['kind'] for x in got['awaiting_confirmation']} == {'node_review', 'handover_acceptance'}
    assert {x['kind'] for x in got['delegated_by_me']} == {'task_assignment', 'task_delegation'}
    assert all(x['project_id'] == 'case' and x['tab'] == 'flow' for x in got['awaiting_confirmation'] + got['delegated_by_me'])
    assert next(x for x in got['delegated_by_me'] if x['kind'] == 'task_assignment')['task_id'] == 'assigned'
    assert got['unavailable'] == []


def test_stale_vote_changed_seat_hash_and_closed_work_are_excluded():
    ws = workspace(); node = ws['projects'][0]['nodes'][0]; task = node['tasks'][0]
    node['review_cycles'][-1]['votes'] = [{'seat': 'owner', 'actor_id': 'viewer', 'result': 'approved'}]
    task['status'] = 'completed'
    got = home_queues(ws, ws['users'][0])
    assert not got['awaiting_confirmation'] and not got['delegated_by_me']
    node['review_cycles'][-1]['votes'] = []
    node['review_cycles'][-1]['content_hash'] = 'stale'
    assert not home_queues(ws, ws['users'][0])['awaiting_confirmation']
    node['review_cycles'][-1]['content_hash'] = review_hash(ws['projects'][0], node)
    node['review_cycles'][-1]['seats'] = {'owner': 'other'}
    assert not home_queues(ws, ws['users'][0])['awaiting_confirmation']
    node['review_cycles'][-1]['seats'] = {'owner': 'viewer'}
    node['status'] = 'completed'
    assert not home_queues(ws, ws['users'][0])['awaiting_confirmation']


def test_no_pm_inference_missing_assignment_history_and_cross_case_ids():
    ws = workspace(); p = ws['projects'][0]; node = p['nodes'][0]
    p['pm_id'] = 'viewer'
    node['tasks'][0].pop('assignment_history')
    ws['handover_requests'] = [{'id': 'foreign', 'project_id': 'elsewhere', 'to_id': 'viewer',
                                'status': 'awaiting_acceptance'},
                               {'id': 'pending', 'project_id': 'case', 'to_id': 'viewer', 'status': 'pending'}]
    ws['delegations'] = [{'id': 'foreign', 'project_id': 'elsewhere', 'principal_id': 'viewer',
                          'delegate_id': 'proxy', 'scope': 'tasks', 'seat': 'owner', 'task_ids': ['delegated'],
                          'status': 'active', 'start_date': '2020-01-01', 'end_date': '2099-12-31',
                          'source': 'supervisor', 'qualified': True, 'qualification_evidence': 'approved'}]
    got = home_queues(ws, ws['users'][0])
    assert not got['delegated_by_me']
    assert [x['id'] for x in got['awaiting_confirmation']] == ['review:cycle:owner']
    assert got['unavailable'][0]['id'] == 'assignment-audit-unavailable'
    assert 'assignment_history' in got['unavailable'][0]['reason']
    ws['users'][0]['active'] = False
    assert home_queues(ws, ws['users'][0]) == {'awaiting_confirmation': [], 'delegated_by_me': [], 'unavailable': []}


def test_revoked_or_expired_delegation_and_reference_only_case_are_not_action_queues():
    ws = workspace(); p = ws['projects'][0]
    ws['delegations'] = [{'id': 'revoked', 'project_id': 'case', 'principal_id': 'viewer',
                          'delegate_id': 'proxy', 'scope': 'tasks', 'seat': 'owner', 'task_ids': ['delegated'],
                          'status': 'revoked', 'start_date': '2020-01-01', 'end_date': '2099-12-31',
                          'source': 'supervisor', 'qualified': True, 'qualification_evidence': 'approved'}]
    assert {x['kind'] for x in home_queues(ws, ws['users'][0])['delegated_by_me']} == {'task_assignment'}
    p['execution_system'] = 'meegle'
    ws['handover_requests'] = [{'id': 'h', 'project_id': 'case', 'to_id': 'viewer', 'status': 'awaiting_acceptance'}]
    assert home_queues(ws, ws['users'][0])['awaiting_confirmation'] == []


def test_delivery_review_requires_current_seat_hash_and_no_existing_vote():
    ws = workspace(); ws['environment'] = 'test'; project = ws['projects'][0]; node = project['nodes'][0]
    node['supervisor_id'] = 'viewer'
    batch = {'id': 'batch', 'status': 'submitted', 'work_item_ids': ['assigned'],
             'required_reviewer_seats': {'node': 'viewer'}, 'approvals': [],
             'quantity': '1', 'unit': 'item', 'evidence_ids': [], 'task_snapshots': [], 'version': 1}
    batch['content_hash'] = delivery_fingerprint(batch)
    project['delivery_batches'] = [batch]
    got = home_queues(ws, ws['users'][0])['awaiting_confirmation']
    assert any(item['id'] == 'delivery:batch' and item['kind'] == 'delivery_review' and item['node_id'] == 'node'
               for item in got)
    batch['approvals'] = [{'actor_id': 'viewer', 'content_hash': batch['content_hash'], 'node_ids': ['node']}]
    assert not any(item['kind'] == 'delivery_review' for item in home_queues(ws, ws['users'][0])['awaiting_confirmation'])
    batch['approvals'] = []
    node['supervisor_id'] = 'other'
    assert not any(item['kind'] == 'delivery_review' for item in home_queues(ws, ws['users'][0])['awaiting_confirmation'])
    node['supervisor_id'] = 'viewer'
    batch['content_hash'] = 'stale'
    assert not any(item['kind'] == 'delivery_review' for item in home_queues(ws, ws['users'][0])['awaiting_confirmation'])


def test_outgoing_handover_uses_explicit_from_id_and_open_status_only():
    ws = workspace()
    ws['handover_requests'] = [
        {'id': 'mine', 'project_id': 'case', 'from_id': 'viewer', 'to_id': 'other', 'status': 'pending'},
        {'id': 'closed', 'project_id': 'case', 'from_id': 'viewer', 'to_id': 'other', 'status': 'accepted'},
        {'id': 'foreign', 'project_id': 'elsewhere', 'from_id': 'viewer', 'to_id': 'other', 'status': 'pending'},
        {'id': 'other', 'project_id': 'case', 'from_id': 'other', 'to_id': 'proxy', 'status': 'pending'}]
    outgoing = [item for item in home_queues(ws, ws['users'][0])['delegated_by_me']
                if item['kind'] == 'handover_outgoing']
    assert [item['id'] for item in outgoing] == ['handover-outgoing:mine']
    assert '原負責人' in outgoing[0]['reason']


def test_partial_legacy_assignment_audit_requires_real_timestamp():
    ws = workspace(); task = ws['projects'][0]['nodes'][0]['tasks'][0]
    history = task['assignment_history'][-1]
    for timestamp in (None, '', '2026-10-01', 'not-a-time'):
        history['at'] = timestamp
        got = home_queues(ws, ws['users'][0])
        assert not any(item['kind'] == 'task_assignment' for item in got['delegated_by_me'])
        assert got['unavailable'][0]['kind'] == 'assignment_audit_unavailable'
    history['at'] = '2026-10-01T09:00:00+08:00'
    assert any(item['kind'] == 'task_assignment' for item in home_queues(ws, ws['users'][0])['delegated_by_me'])
    history.pop('actor_id')
    got = home_queues(ws, ws['users'][0])
    assert not any(item['kind'] == 'task_assignment' for item in got['delegated_by_me'])
    assert got['unavailable']
    history['actor_id'] = 'viewer'
    history['after'] = {}
    got = home_queues(ws, ws['users'][0])
    assert not any(item['kind'] == 'task_assignment' for item in got['delegated_by_me'])
    assert got['unavailable']
