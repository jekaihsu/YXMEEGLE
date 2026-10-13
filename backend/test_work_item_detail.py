"""Synthetic behavioral and negative checks for the unwired detail model."""
from copy import deepcopy
import json

from .work_item_detail import build_work_item_detail


ITEM = 'base/items/record'


def fixture():
    return {'source_work_items': [{'id': ITEM, 'project_id': 'p', 'contract_ids': ['base/contracts/c'],
                                   'category': 'report', 'source_missing': False}],
            'contract_items': [{'id': 'base/contracts/c', 'title': 'Line', 'confirmation_ids': ['base/conf/a'],
                                'reporting_ids': [ITEM], 'amount_original': 123456, 'amount_reported': 654321}],
            'source_confirmations': [{'id': 'base/conf/a', 'code': 'duplicate'}],
            'users': [{'id': 'person', 'name': 'Synthetic person'}],
            'projects': [{'id': 'p', 'code': 'duplicate', 'daily_reports': [], 'files': [], 'nodes': [
                {'id': 'n', 'key': 'report', 'status': 'in_progress', 'tasks': [
                    {'id': 't', 'title': 'Survey report', 'owner_id': 'person', 'status': 'in_progress',
                     'completed_at': None, 'source_identity': {'base_token': 'base', 'table_id': 'items',
                                                              'record_id': 'record'}, 'output': ''}]}]}]}


def detail(state):
    return build_work_item_detail(state, ITEM, as_of='2026-10-14')


def test_native_parent_edges_both_directions_and_confirmation_breadcrumb():
    state = fixture()
    for direction in ('child', 'parent'):
        current = deepcopy(state)
        if direction == 'child':
            current['contract_items'][0]['reporting_ids'] = []
        else:
            current['source_work_items'][0]['contract_ids'] = []
        result = detail(current)
        parent = result['parents']['rows'][0]
        assert parent['id'] == 'base/contracts/c'
        assert parent['confirmations'] == [{'id': 'base/conf/a', 'code': 'duplicate',
                                            'verification': 'receipt_missing'}]
        assert parent['verification'] == 'receipt_missing'
        assert result['header']['name'] == {'state': 'existing', 'values': ['Survey report']}


def test_native_edge_only_guard_rejects_equal_names_case_numbers_and_suffixes():
    state = fixture()
    assert detail(state)['parents']['rows'][0]['title'] == 'Line'
    state['source_work_items'][0].update(contract_ids=[], name='Line', case_number='duplicate')
    state['contract_items'][0].update(reporting_ids=[], case_number='duplicate')
    result = detail(state)
    assert result['parents']['rows'] == []
    assert result['parents']['unresolved'] == [{'reason': 'native_parent_edge_absent'}]
    # Same record suffix in a different Base is a distinct task source.
    state['projects'][0]['nodes'][0]['tasks'][0]['source_identity']['base_token'] = 'other'
    assert detail(state)['nodes']['rows'] == []


def test_rework_has_distinct_round_instance_and_preserves_previous_completion():
    state = fixture()
    task = state['projects'][0]['nodes'][0]['tasks'][0]
    task.update(status='completed', completed_at='2026-10-10', output='Earlier delivery')
    before = detail(state)['nodes']['rows'][0]
    task.update(status='rework', completed_at=None, sop_round=1,
                round_history=[{'round': 1, 'before': {'status': 'completed', 'owner_id': 'person',
                                                      'output': 'Earlier delivery',
                                                      'completed_at': '2026-10-10', 'node_status': 'completed'}}])
    result = detail(state)['nodes']['rows'][0]
    assert result['instance_identity'] != before['instance_identity']
    assert result['task']['status'] == 'rework'
    assert result['history'][0]['before'] == {'status': 'completed', 'output': 'Earlier delivery',
                                             'completed_at': '2026-10-10', 'node_status': 'completed'}
    assert result['history'][0]['instance_identity'] != result['instance_identity']
    # Two stored node instances with the same SOP key are never collapsed.
    other = deepcopy(state['projects'][0]['nodes'][0]); other['id'] = 'n-reworked'
    state['projects'][0]['nodes'].append(other)
    assert [r['node']['id'] for r in detail(state)['nodes']['rows']] == ['n', 'n-reworked']


def test_evidence_cannot_complete_guard_and_input_remains_unchanged():
    state = fixture()
    before = detail(state)
    project = state['projects'][0]
    project['daily_reports'] = [{'id': 'daily', 'date': '2026-10-13', 'description': 'All done',
                                  'points': 100, 'status': 'completed'}]
    project['files'] = [{'id': 'file', 'node_id': 'n', 'name': 'Delivery', 'status': 'completed'}]
    state['source_attachment_index'] = [{'id': 'native-file', 'name': 'Native attachment',
                                         'source_record_id': 'src-aaaa2a4a05acb23423fc',
                                         'base_token': 'base', 'table_id': 'items'}]
    snapshot = deepcopy(state)
    after = detail(state)
    assert after['nodes'] == before['nodes']
    assert after['header']['execution_state'] == {'state': 'existing', 'tasks': [
        {'id': 't', 'status': 'in_progress', 'completed_at': None}]}
    assert [r['id'] for r in after['deliverables']['rows']] == ['daily', 'file', 'native-file']
    assert all(r['evidence_only'] for r in after['deliverables']['rows'])
    assert after['deliverables']['rows'][0]['work_item_relation'] == 'unlocated'
    assert 'points' not in json.dumps(after)
    assert state == snapshot


def test_plan_actual_unavailable_units_never_mixed_amounts_withheld():
    state = fixture()
    state['source_work_items'][0].update(quantity=3, unit='metres', amount_original=123456)
    state['projects'][0]['nodes'][0]['tasks'][0].update(quantity=5, unit='hours', points=99, due_date='2026-11-01')
    result = detail(state)
    assert result['plan_actual']['available'] is False
    assert result['plan_actual']['read_state'] == {'states': ['unlocated'], 'count': None}
    assert result['work_content']['quantity']['value'] is None
    assert result['work_content']['unit']['value'] is None
    assert result['work_content']['amounts'] == {'state': 'withheld', 'reason': 'G-AMT approval absent'}
    assert not any(value in json.dumps(result) for value in ('metres', 'hours', '123456', '654321', '2026-11-01'))
    assert result['side']['effective_due']['state'] == 'unknown'
    assert result['side']['source_updated_at']['value'] is None


def test_work_orders_unlocated_never_join_by_case_number():
    state = fixture()
    state['work_orders'] = [{'id': 'order', 'case_number': 'duplicate', 'quantity': 9}]
    result = detail(state)
    assert result['header']['id'] == ITEM
    assert result['work_orders']['rows'] == []
    assert result['work_orders']['read_state'] == {'states': ['unlocated'], 'count': None}
    assert result['work_orders']['source_health_link'] == {'view': 'sources'}


def test_forbidden_absent_guard_no_dangling_task_identity_or_count():
    state = fixture()
    assert detail(state)['nodes']['rows'][0]['task']['id'] == 't'
    state['contract_items'][0]['task_refs'] = [{'project_id': 'p', 'node_id': 'n', 'task_id': 'restricted-task'}]
    state['projects'][0]['nodes'][0]['tasks'] = []  # caller revoked this object
    result = detail(state)
    assert result['nodes'] == {'read_state': {'states': ['unlocated'], 'count': None}, 'rows': []}
    assert 'restricted-task' not in json.dumps(result)
    state['source_work_items'] = []
    assert detail(state) == {'read_state': {'states': ['unknown'], 'count': None}}


def test_missing_parent_unresolved_but_forbidden_parent_has_no_hint():
    state = fixture()
    state['source_work_items'][0]['contract_ids'] = []
    state['contract_items'] = []
    assert detail(state)['parents']['unresolved'] == [{'reason': 'native_parent_edge_absent'}]
    state['source_work_items'][0]['contract_ids'] = ['restricted-contract']
    result = detail(state)
    assert result['parents'] == {'read_state': {'states': ['unlocated'], 'count': None}, 'rows': []}
    assert 'restricted-contract' not in json.dumps(result)


def test_unknown_operation_keeps_existing_identity_no_retry_hint():
    state = fixture()
    state['jobs'] = [{'id': 'original-operation', 'status': 'outcome_unknown',
                       'payload': {'project_id': 'p', 'node_id': 'n', 'task_id': 't'}}]
    result = detail(state)
    assert result['nodes']['rows'][0]['operations'] == [{'id': 'original-operation', 'status': 'outcome_unknown'}]
    assert 'retry' not in json.dumps(result) and 'resubmit' not in json.dumps(result)


def test_sections_fail_independently_without_returning_exception_payload():
    state = fixture()
    state['contract_items'] = [{'secret': 'restricted-id'}]
    result = detail(state)
    assert result['parents']['read_state'] == {'states': ['read_failed'], 'count': None}
    assert result['nodes']['rows'][0]['task']['status'] == 'in_progress'
    assert result['work_orders']['read_state']['states'] == ['unlocated']
    assert 'restricted-id' not in json.dumps(result)
