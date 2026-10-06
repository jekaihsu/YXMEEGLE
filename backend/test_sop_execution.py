"""Issue #13: versioned execution mapping, real-DAG gates and the 8 fixture scenarios."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from . import sop_execution as ex
from .operations import apply_operation
from .policy import upgrade, template
from .seed import seed
from .sop_runtime import _source_graph, topology_projection
from .sources import project_nodes

FIXTURE = Path(__file__).parents[1] / 'docs/fixtures/SOP_TOPOLOGY_334662_V137_20260929.json'
GRAPH = _source_graph()
YES, NO = 'ko8resdi4', 'zb41oy7bf'
ENFORCED = {'settings': {ex.SETTING: 'enforce'}, 'environment': 'demo'}


def ancestors(*keys):
    seen, stack = set(), list(keys)
    while stack:
        for pred in GRAPH.predecessors[stack.pop()]:
            if pred not in seen:
                seen.add(pred)
                stack.append(pred)
    return seen


def full_mapping():
    """Test-only mapping: one unit per source node so the DAG itself can be exercised."""
    result = deepcopy(ex.execution_mapping())
    for key, entry in result.items():
        if key not in GRAPH.disabled:
            entry.update(units=(('n', key),), status='mapped')
    return result


def facts(**values):
    base = {'field_6455a7': YES, 'field_30fd9d': YES, 'field_b18d40': True, 'field_b63158': False}
    base.update(values)
    return [{'field': f, 'value': v, 'template_id': 334662, 'source_version': 137}
            for f, v in base.items() if v is not None]


def project(done=(), condition_facts=None, pending=()):
    tasks = [{'id': k, 'sop_task_key': k, 'status': 'completed' if k in done else 'pending',
              'sop_applicability': 'always', 'required': True, 'owner_id': 'o'}
             for k in GRAPH.order if k not in GRAPH.disabled and k not in pending]
    return {'id': 'p', 'nodes': [{'id': 'n', 'key': 'n', 'status': 'in_progress', 'tasks': tasks,
                                  'review_cycles': []}],
            'sop_condition_facts': facts() if condition_facts is None else condition_facts}


def state(p, mapping=None):
    readiness, diag, applies = ex.source_state(ENFORCED, p, mapping or full_mapping())
    return readiness, diag, applies


def reasons(p, key):
    node = p['nodes'][0]
    task = next(t for t in node['tasks'] if t['id'] == key)
    return ex.gate_reasons(ENFORCED, p, node, task, full_mapping())


# ---- (1) mapping ------------------------------------------------------------------------

def test_mapping_is_versioned_from_contracts_and_blocks_unknown_or_unmapped():
    mapping = ex.execution_mapping()
    assert len(mapping) == 62 and mapping['state_4']['mapping_version'] == ex.MAPPING_VERSION
    assert mapping['state_4']['units'] == (('confirmation', 'issue_handoff'), ('confirmation', 'prepare_confirmation'))
    assert mapping['state_52']['status'] == mapping['state_58']['status'] == 'disabled'
    assert mapping['state_27']['status'] == 'unmapped'
    assert all(e['template_id'] == 334662 and e['version'] == 137 for e in mapping.values())
    # Unmapped but applicable -> unknown/blocked with a diagnostic, never silently skipped.
    p = project(done=ancestors('state_28') | {'state_28'})
    readiness, diag, _ = state(p, ex.execution_mapping())
    assert readiness['state_28'].status == 'blocked'
    assert any(r.startswith('unmapped_source_node') for r in diag['state_27'])


def test_task_refs_alone_are_not_a_mapping():
    p = {'id': 'p', 'sop_condition_facts': facts(), 'nodes': [{'id': 'n', 'key': 'control', 'status': 'x', 'tasks': [
        {'id': 't', 'status': 'completed', 'source_contract_refs': [{'template_id': 334662, 'version': 137,
                                                                    'node_key': 'state_75'}]}]}]}
    assert ex.project_units(p) == {}
    readiness, diag, _ = ex.source_state(ENFORCED, p)
    assert readiness['state_75'].status == 'blocked'
    assert any('unit_task_missing' in r for r in diag['state_75'])


def test_other_template_is_never_mapped_and_verification_stays_false():
    assert all(e['template_id'] == 334662 for e in ex.execution_mapping().values())
    assert 'template_566082_meaning_unset' in ex.UNRESOLVED_DECISIONS
    assert 'company_baseline_unset' in ex.UNRESOLVED_DECISIONS
    summary = ex.summary(project(), ENFORCED)
    assert summary['source_execution_verified'] is False and topology_projection(project())['source_execution_verified'] is False
    assert len(json.dumps(topology_projection(project()))) < 800


# ---- (2) runtime condition decision ---------------------------------------------------------

def test_missing_condition_blocks_and_unresolved_option_is_not_a_decision():
    p = project(condition_facts=facts(field_30fd9d=None))
    _, diag, applies = state(p)
    assert applies['state_33'] is None and applies['state_34'] is None
    assert 'missing_field:field_30fd9d' in diag['state_33']
    p = project(condition_facts=facts(field_30fd9d='gb2pt_6tb'))
    _, diag, applies = state(p)
    assert applies['state_33'] is None
    assert 'pure_subcontract_meaning_undecided:field_30fd9d' in diag['*']


@pytest.fixture
def company():
    ws = upgrade(seed()); ws['environment'] = 'demo'
    p = ws['projects'][0]
    p.update(nodes=project_nodes(p['id']), execution_system='workbench', pm_id='u-pm', supervisor_id='u-manager',
             source_status='執行中', execution_status='pending', sop_version=template()['id'])
    upgrade(ws)
    for n in p['nodes']:
        n.update(owner_id='u-pm', supervisor_id='u-manager')
        for t in n['tasks']:
            t['owner_id'] = 'u-pm'
    return ws, p


def act(company, action, payload, user='u-pm'):
    ws, p = company
    return apply_operation(ws, next(u for u in ws['users'] if u['id'] == user),
                           dict(action=action, project_id=p['id'], node_id=None, payload=payload))


def test_supervisor_procedure_is_attributed_and_append_only(company):
    ws, p = company
    body = {'field': 'field_30fd9d', 'value': NO, 'evidence': '業主確認無下包'}
    with pytest.raises(HTTPException):
        act(company, 'sop_condition_propose', body, user='u-manager')          # not the PM
    with pytest.raises(HTTPException):
        act(company, 'sop_condition_propose', {**body, 'value': 'gb2pt_6tb'})  # undecided meaning
    with pytest.raises(HTTPException):
        act(company, 'sop_condition_propose', {**body, 'value': 'invented'})
    act(company, 'sop_condition_propose', body)
    assert ex.effective_facts(p) == {}                                           # proposal alone decides nothing
    proposal = p['sop_condition_proposals'][0]
    with pytest.raises(HTTPException):
        act(company, 'sop_condition_confirm', {'proposal_id': proposal['id'], 'result': 'approved'})  # self
    act(company, 'sop_condition_confirm', {'proposal_id': proposal['id'], 'result': 'approved'}, user='u-manager')
    assert ex.effective_facts(p) == {'field_30fd9d': NO}
    assert p['sop_condition_facts'][0]['decided_by'] == 'u-manager'
    with pytest.raises(HTTPException):
        act(company, 'sop_condition_propose', {**body, 'value': YES})            # change needs approved flow
    assert len(p['sop_condition_facts']) == 1


def test_gate_is_opt_in_and_blocks_seeded_project_with_diagnostics(company):
    ws, p = company
    node = next(n for n in p['nodes'] if n['key'] == 'confirmation')
    task = next(t for t in node['tasks'] if t.get('sop_task_key') == 'issue_handoff')
    assert ex.gate_reasons(ws, p, node, task) == []
    ws['settings'][ex.SETTING] = 'enforce'
    blocked = ex.gate_reasons(ws, p, node, task)
    assert blocked and 'state_4' in blocked[0]
    from .workflow_rules import execution_reasons
    assert any('來源拓樸' in r for r in execution_reasons(ws, p, node, task))
    ws['settings'][ex.SETTING] = 'off'
    assert not any('來源拓樸' in r for r in execution_reasons(ws, p, node, task))


# ---- (3) DAG gates / scenarios 1-3 ------------------------------------------------------------

def test_subcontract_unknown_blocks_join_without_inventing_completion():          # subcontract_unknown
    done = ancestors('state_15') - {'state_33', 'state_34', 'state_35'}
    p = project(done, condition_facts=facts(field_30fd9d=None))
    readiness, _, _ = state(p)
    assert readiness['state_15'].status == 'blocked' and 'state_33' in readiness['state_15'].unknown
    assert reasons(p, 'state_15') and not any(t['status'] == 'completed' for t in p['nodes'][0]['tasks']
                                               if t['id'] in ('state_33', 'state_34', 'state_35', 'state_15'))


def test_no_subcontract_excludes_branch_but_keeps_original_completion_distinct():  # subcontract_no
    done = (ancestors('state_15') - {'state_33', 'state_35'}) | {'state_34'}
    p = project(done, condition_facts=facts(field_30fd9d=NO))
    readiness, _, applies = state(p)
    assert readiness['state_33'].status == readiness['state_35'].status == 'not_applicable'
    assert readiness['state_15'].status == 'ready' and reasons(p, 'state_15') == []
    assert applies['state_34'] is True
    assert {t['id']: t['status'] for t in p['nodes'][0]['tasks']}['state_35'] == 'pending'


def test_parallel_groups_have_no_synthetic_serial_edges():                       # parallel_technical_groups
    assert GRAPH.predecessors['state_75'] == GRAPH.predecessors['state_76'] == GRAPH.predecessors['state_77'] == {'state_45'}
    base = ancestors('state_75') | {'state_45'}
    p = project(base)
    assert [reasons(p, k) for k in ('state_75', 'state_76', 'state_77')] == [[], [], []]
    p = project(base | {'state_75'})
    assert [reasons(p, k) for k in ('state_76', 'state_77')] == [[], []]          # 75 done does not complete 76/77
    readiness, _, _ = state(p)
    assert readiness['state_46'].status == 'blocked' and set(readiness['state_46'].waiting_for) == {'state_76', 'state_77'}
    merged = project(base | {'state_75', 'state_76', 'state_77'})
    assert state(merged)[0]['state_46'].status == 'ready'


def test_completion_gate_matches_start_gate_for_not_ready_task():
    p = project(set())
    assert reasons(p, 'state_75')            # predecessors not done blocks start and complete alike


# ---- (4) confirmation issue -> fan-out --------------------------------------------------------

def issue(status='issued', simulated=False, receipts=True):
    return {'id': 'i1', 'version': 'v1', 'status': status, 'simulated': simulated,
            'recipients': ['admin', 'indoor', 'field'],
            'recipient_groups': {'admin': ['state_2'], 'indoor': ['state_38'], 'field': ['state_39', 'state_82']},
            'receipts': [{'key': r, 'receipt': {'message_id': 'm-' + r, **({'simulated': True} if simulated else {})}}
                         for r in ('admin', 'indoor', 'field')] if receipts else []}


@pytest.mark.parametrize('bad', [issue('queued'), issue('draft'), issue('simulated', True), issue('issued', receipts=False),
                                 issue('unknown'), issue('issued', True)])
def test_draft_preview_or_unknown_issue_never_fans_out(bad):                  # confirmation_handoff
    p = {}
    assert ex.record_fan_out(p, bad) == [] and p.get('sop_fan_out', []) == []


def test_formal_issue_fans_out_once_per_group_recipient_and_groups_confirm_independently():
    p, item = {}, issue()
    assert ex.fan_out_targets() == ('state_2', 'state_38', 'state_39', 'state_82')
    first = ex.record_fan_out(p, item)
    assert sorted(e['key'] for e in first) == ['i1:state_2:admin', 'i1:state_38:indoor', 'i1:state_39:field', 'i1:state_82:field']
    assert ex.record_fan_out(p, deepcopy(item)) == [] and len(p['sop_fan_out']) == 4     # resend same version
    assert all(e['status'] == 'notified' for e in p['sop_fan_out'])
    item['acknowledgments'] = [{'user_id': 'indoor'}]
    assert ex.group_confirmations(p, item) == {'state_2': 'pending', 'state_38': 'confirmed',
                                               'state_39': 'pending', 'state_82': 'pending'}


def test_confirmation_issue_validates_groups_and_preview_does_not_hand_off(company):
    ws, p = company
    node = next(n for n in p['nodes'] if n['key'] == 'confirmation')
    p['evidence'].append({'id': 'e1', 'node_id': node['id'], 'key': 'confirmation', 'status': 'accepted'})
    p['issuer_ids'] = ['u-pm']
    payload = {'version': '1', 'recipients': ['u-field'], 'recipient_groups': {'u-field': ['state_65']}}
    with pytest.raises(HTTPException):
        act(company, 'confirmation_issue', payload)
    act(company, 'confirmation_issue', {**payload, 'recipient_groups': {'u-field': ['state_39']}})
    assert p['confirmation_issues'][0]['recipient_groups'] == {'u-field': ['state_39']} and p['handoffs'] == []


# ---- (5) approval-scoped rounds / scenarios 5-6 ---------------------------------------------

def round_project():
    def node(key, ident, status):
        return {'id': ident, 'key': key, 'status': status, 'review_cycles': [{'status': 'approved', 'votes': ['kept']}],
                'tasks': [{'id': ident + '-t', 'sop_task_key': key + '_daily', 'status': 'completed', 'owner_id': 'owner-' + key, 'output': 'out-' + key,
                           'work_item_id': 'w-' + key, 'completed_at': 'then'}]}
    return {'id': 'p', 'nodes': [node('control', 'a', 'completed'), node('field', 'b', 'completed')]}


def test_approved_round_invalidates_only_affected_scope_and_preserves_history():  # revision_rollback
    p, approval = round_project(), {'id': 'ap', 'type': 'change', 'project_id': 'p', 'status': 'approved',
                                    'node_id': 'a', 'task_ids': ['a-t']}
    record = ex.open_round({}, p, approval, {'id': 'pm'}, receipt_ok=lambda: True)
    a, b = p['nodes']
    assert record['round'] == 1 and record['task_ids'] == ['a-t'] and record['source_nodes'] == ['state_75']
    assert a['tasks'][0]['status'] == 'rework' and a['status'] == 'rework' and a['tasks'][0]['sop_round'] == 1
    assert b['status'] == 'completed' and b['tasks'][0]['status'] == 'completed'                 # untouched
    assert a['tasks'][0]['owner_id'] == 'owner-control' and a['tasks'][0]['output'] == 'out-control'
    assert a['review_cycles'][0]['votes'] == ['kept'] and a['review_cycles'][0]['status'] == 'invalidated'
    assert record['previous']['a-t']['status'] == 'completed' and a['tasks'][0]['round_history'][0]['round'] == 1
    assert ex.open_round({}, p, approval, {'id': 'pm'}, receipt_ok=lambda: True) is record      # idempotent
    assert len(p['sop_rounds']) == 1


@pytest.mark.parametrize('mutation', [{'status': 'pending'}, {'type': 'financial'}, {'project_id': 'other'}])
def test_round_requires_approved_native_change(mutation):
    p = round_project()
    approval = {'id': 'ap', 'type': 'change', 'project_id': 'p', 'status': 'approved', 'node_id': 'a',
                'task_ids': ['a-t'], **mutation}
    with pytest.raises(HTTPException):
        ex.open_round({}, p, approval, {'id': 'pm'}, receipt_ok=lambda: True)
    approval = {**approval, 'type': 'change', 'status': 'approved', 'project_id': 'p'}
    with pytest.raises(HTTPException):
        ex.open_round({}, p, approval, {'id': 'pm'}, receipt_ok=lambda: False)
    assert 'sop_rounds' not in p or p['sop_rounds'] == []


def test_rollback_label_is_not_an_edge_and_leaves_are_not_engineering_closure():  # no_label_inferred_edge
    assert GRAPH.successors['state_65'] == set() and 'state_65' not in GRAPH.predecessors['state_55']
    assert sum(len(v) for v in GRAPH.successors.values()) == 71
    semantics = ex.leaf_semantics()
    assert semantics['state_65'] == 'rollback_label_not_edge' and semantics['state_32'] == 'quote_end'
    assert set(semantics) == set(json.loads(FIXTURE.read_text(encoding='utf-8'))['leaf_nodes'])
    assert 'unclassified_leaf' not in semantics.values()


# ---- (6) disabled evaluation / native finance gate --------------------------------------------

def test_disabled_assessment_nodes_never_get_tasks_or_readiness():              # disabled_assessment
    assert all(ex.execution_mapping()[k]['units'] == () for k in ('state_52', 'state_58'))
    readiness, _, applies = state(project())
    assert readiness['state_52'].status == readiness['state_58'].status == 'disabled'
    assert applies['state_52'] is applies['state_58'] is False
    live = {'id': 'x', 'status': 'in_progress', 'required': True,
            'source_contract_refs': [{'template_id': 334662, 'version': 137, 'node_key': 'state_52'}]}
    paused = {**live, 'id': 'y', 'status': 'paused', 'required': False}
    assert ex.evaluation_disabled_violations({'nodes': [{'tasks': [live, paused]}]}) == ['x']


def test_financial_source_flags_never_replace_native_receipt():                 # financial_native_gate
    entry = ex.execution_mapping()['state_55']
    assert entry['units'] and all(local in ('pricing', 'settlement') for local, _ in entry['units'])
    src = {n['key']: n for n in json.loads(FIXTURE.read_text(encoding='utf-8'))['nodes']}['state_55']
    assert src['pass_mode'] == 'multi_user_confirm'   # source flag exists but is inert
    mapping = deepcopy(full_mapping())
    mapping['state_55']['units'] = (('pricing', 'state_55'),)
    p = project(ancestors('state_55') | {'state_55'})
    p['nodes'].append({'id': 'pr', 'key': 'pricing', 'status': 'completed', 'review_cycles': [],
                       'tasks': [{'id': 'state_55', 'sop_task_key': 'state_55', 'status': 'completed',
                                  'sop_applicability': 'always'}]})
    p['nodes'][0]['tasks'] = [t for t in p['nodes'][0]['tasks'] if t['id'] != 'state_55']
    with patch('backend.operations.financial_confirmation', return_value=None):
        readiness, diag, _ = ex.source_state(ENFORCED, p, mapping)
        assert 'native_finance_receipt_required:state_55' in diag['state_55'] and readiness['state_55'].status != 'completed'
        assert ex.node_closure_reasons(ENFORCED, p, p['nodes'][1])
    with patch('backend.operations.financial_confirmation', return_value={'status': 'approved'}):
        readiness, _, _ = ex.source_state(ENFORCED, p, mapping)
        assert readiness['state_55'].status == 'completed'
        assert ex.node_closure_reasons(ENFORCED, p, p['nodes'][1]) == []
    assert ex.node_closure_reasons({'settings': {}}, p, p['nodes'][1]) == []     # gates are opt-in


def test_all_eight_fixture_scenarios_are_covered_by_name():
    ids = {s['id'] for s in json.loads(FIXTURE.read_text(encoding='utf-8'))['test_scenarios']}
    assert ids == {'subcontract_unknown', 'subcontract_no', 'parallel_technical_groups', 'confirmation_handoff',
                   'revision_rollback', 'no_label_inferred_edge', 'disabled_assessment', 'financial_native_gate'}
    source = Path(__file__).read_text(encoding='utf-8')
    assert all(f'# {name}' in source or f'#  {name}' in source or f'  # {name}' in source for name in ids)
