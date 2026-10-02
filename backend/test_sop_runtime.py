from copy import deepcopy
import json

from .sop_runtime import topology_projection
from .sop_contracts import VERSION


def project(*refs, status='pending'):
    return {'nodes': [{'id': 'n', 'status': 'completed', 'tasks': [{
        'id': 't', 'status': status, 'source_contract_refs': list(refs),
        'owner_id': 'owner', 'output': 'preserved', 'review_cycles': [{'votes': ['kept']}],
    }]}]}


def ref(key='state_75', version=137):
    return {'template_id': 334662, 'version': version, 'node_key': key}


def test_summary_uses_packaged_source_graph_and_is_small():
    result = topology_projection(project())
    assert result['source_node_count'] == 62
    assert result['source_edge_count'] == 71
    assert result['disabled_node_count'] == 2
    assert result['unreferenced_node_count'] == 60
    assert 'nodes' not in result
    assert len(json.dumps(result)) < 700


def test_completed_local_task_never_claims_complete_source_node_or_closure():
    value = project(ref(), status='completed')
    before = deepcopy(value)
    result = topology_projection(value, details=True)
    node = next(n for n in result['nodes'] if n['key'] == 'state_75')
    assert node['local_completed_task_count'] == 1
    assert node['status'] == 'blocked'
    assert node['mapping_status'] == 'referenced_only'
    assert result['source_execution_verified'] is False
    assert value == before


def test_version_drift_and_unknown_identity_do_not_count_as_coverage():
    result = topology_projection(project(ref(version=138), ref('nonexistent'), {'template_id': 334662}))
    assert result['invalid_reference_count'] == 3
    assert result['referenced_node_count'] == 0


def test_other_template_is_not_merged_by_matching_node_name():
    other = ref()
    other['template_id'] = 566082
    result = topology_projection(project(other))
    assert result['referenced_node_count'] == result['invalid_reference_count'] == 0


def test_repeated_refs_deduplicated_but_distinct_tasks_preserved():
    value = project(ref(), ref())
    duplicate_task = deepcopy(value['nodes'][0]['tasks'][0])
    duplicate_task['id'] = 'different-task'
    value['nodes'][0]['tasks'].append(duplicate_task)
    result = topology_projection(value, details=True)
    assert result['referenced_node_count'] == 1
    assert next(n for n in result['nodes'] if n['key'] == 'state_75')['local_task_count'] == 2


def test_pending_condition_not_forged_to_false_or_completed():
    value = project(ref('state_82'))
    value['nodes'][0]['tasks'][0]['sop_applicability'] = 'subcontract'
    assert topology_projection(value)['conditional_pending_node_count'] == 1
    value['sop_applicability'] = {'subcontract': dict(
        contract_version=VERSION, decided_by='supervisor', reason='verified scope', applies=False)}
    result = topology_projection(value)
    assert result['conditional_pending_node_count'] == 0
    assert result['source_execution_verified'] is False


def test_parallel_edges_are_kept_and_disabled_assessment_stays_disabled():
    result = topology_projection(project(), details=True)
    nodes = {n['key']: n for n in result['nodes']}
    for key in ('state_75', 'state_76', 'state_77'):
        assert nodes[key]['predecessors'] == ['state_45']
    assert nodes['state_52']['status'] == nodes['state_58']['status'] == 'disabled'
    assert nodes['state_65']['status'] == 'blocked'


def test_real_summary_path_exposes_compact_projection_without_overwriting_history():
    from .seed import seed
    from .policy import upgrade
    from .operations import project_summary
    ws = upgrade(seed())
    p = ws['projects'][0]
    tasks = deepcopy([n['tasks'] for n in p['nodes']])
    result = project_summary(ws, p)
    assert result['sop_topology']['status'] == 'execution_mapping_pending'
    assert 'nodes' not in result['sop_topology']
    assert [n['tasks'] for n in p['nodes']] == tasks
