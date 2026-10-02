"""Semantic tests against the preserved 334662/v137 source graph."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from .sop_topology import FieldSpec, SourceKey, Topology, compile_condition, index_contracts


@pytest.fixture
def fixture():
    return json.loads((Path(__file__).parents[1] / 'docs/fixtures/SOP_TOPOLOGY_334662_V137_20260929.json').read_text(encoding='utf-8'))


def predicate(value='yes', operator='Eq', field='subcontract'):
    return {'usage_mode': 'conditional', 'condition_group': {'conjunction': 'AND', 'conditions': [
        {'field': field, 'operator': operator, 'field_type': 'radio', 'originalValue': value}]}}


SCHEMA = {'subcontract': FieldSpec('radio', frozenset({'yes', 'no'}))}


@pytest.mark.parametrize('values,expected', [({}, None), ({'subcontract': None}, None),
    ({'subcontract': 'new-option'}, None), ({'subcontract': True}, None),
    ({'subcontract': 'yes'}, True), ({'subcontract': 'no'}, False)])
def test_typed_predicate_keeps_missing_and_unknown_options_unknown(values, expected):
    assert compile_condition(predicate(), SCHEMA).evaluate(values).value is expected


@pytest.mark.parametrize('source', [predicate(operator='Execute'), predicate(value='unmapped'),
    predicate(field='missing'), {'usage_mode': 'conditional', 'condition_group': {'conjunction': 'AND'}},
    {'usage_mode': 'none', 'value': True, 'formula_expression': '__import__("os")'},
    {'usage_mode': 'custom', 'value': 1}])
def test_unsupported_source_is_unknown_with_reason(source):
    result = compile_condition(source, SCHEMA).evaluate({'subcontract': 'yes'})
    assert result.value is None and result.reasons


def test_unknown_child_not_hidden_by_other_branch():
    raw = predicate()
    raw['condition_group']['conjunction'] = 'OR'
    raw['condition_group']['conditions'].append({'field': 'missing', 'operator': 'Eq', 'originalValue': True})
    assert compile_condition(raw, SCHEMA).evaluate({'subcontract': 'yes'}).value is None


def test_boolean_number_types_are_not_interchangeable():
    raw = predicate(value=True)
    raw['condition_group']['conditions'][0]['field_type'] = 'boolean'
    compiled = compile_condition(raw, {'subcontract': FieldSpec('boolean')})
    assert compiled.evaluate({'subcontract': True}).value is True
    assert compiled.evaluate({'subcontract': 1}).value is None


def test_source_visibility_is_compilable_only_with_verified_option_schema(fixture):
    node = next(n for n in fixture['nodes'] if n['key'] == 'state_33')
    assert compile_condition(node['visibility'], {}).evaluate({}).value is None
    # These are source option IDs, not labels. This test explicitly supplies the
    # metadata contract; production must resolve it from verified source metadata.
    schema = {'field_30fd9d': FieldSpec('radio', frozenset({'ko8resdi4', 'zb41oy7bf'}))}
    condition = compile_condition(node['visibility'], schema)
    assert condition.evaluate({'field_30fd9d': 'ko8resdi4'}).value is True
    assert condition.evaluate({'field_30fd9d': 'unknown'}).value is None


def test_identity_index_preserves_same_names_and_versions():
    node = {'state_key': 'one', 'name': 'same', 'tasks': [
        {'task_key': 'a', 'name': 'same'}, {'task_key': 'b', 'name': 'same'}]}
    catalog = {'templates': [{'id': 1, 'version': version, 'nodes': [deepcopy(node)]} for version in (1, 2)]}
    result = index_contracts(catalog)
    assert len(result) == 6
    assert SourceKey(1, 2, 'one', 'b') in result
    catalog['templates'][0]['nodes'][0]['tasks'].append({'task_key': 'a'})
    with pytest.raises(ValueError, match='duplicate task'):
        index_contracts(catalog)


def test_full_catalog_has_52_distinct_task_identities():
    catalog = json.loads(Path(__file__).with_name('sop_source_contracts.json').read_text(encoding='utf-8'))
    result = index_contracts(catalog)
    assert sum(k.task is not None and k.template == 334662 and k.version == 137 for k in result) == 52


def state(topology, unfinished=()):
    return dict.fromkeys(topology.nodes, True), set(topology.nodes) - set(unfinished)


def test_no_subcontract_join_excludes_explicitly_inapplicable_without_completion(fixture):
    topology = Topology(fixture)
    applies, completed = state(topology, ('state_33', 'state_35', 'state_15'))
    applies.update(state_33=False, state_35=False)
    before = deepcopy(completed)
    results = topology.readiness(applies, completed)
    assert results['state_15'].status == 'ready'
    assert results['state_33'].status == results['state_35'].status == 'not_applicable'
    assert completed == before and 'state_35' not in completed


def test_unknown_subcontract_blocks_join_even_if_other_branch_completed(fixture):
    topology = Topology(fixture)
    applies, completed = state(topology, ('state_33', 'state_35', 'state_15'))
    applies['state_33'] = None
    result = topology.readiness(applies, completed)['state_15']
    assert result.status == 'blocked' and 'state_33' in result.unknown


def test_exclusion_does_not_erase_upstream_work(fixture):
    topology = Topology(fixture)
    applies, completed = state(topology, ('state_29', 'state_33', 'state_34', 'state_35', 'state_15'))
    applies.update(state_33=False, state_34=False, state_35=False)
    result = topology.readiness(applies, completed)['state_15']
    assert result.status == 'blocked' and 'state_29' in result.waiting_for


def test_parallel_groups_are_independent_and_do_not_complete_each_other(fixture):
    topology = Topology(fixture)
    applies, completed = state(topology, ('state_75', 'state_76', 'state_77'))
    result = topology.readiness(applies, completed)
    assert all(result[k].status == 'ready' for k in ('state_75', 'state_76', 'state_77'))
    completed.add('state_75')
    result = topology.readiness(applies, completed)
    assert result['state_75'].status == 'completed'
    assert result['state_76'].status == result['state_77'].status == 'ready'


def test_disabled_nodes_cannot_be_reenabled_or_complete_by_source_auto_flags(fixture):
    for node in fixture['nodes']:
        node['disabled'] = False
    topology = Topology(fixture)
    applies, completed = state(topology)
    result = topology.readiness(applies, completed)
    assert result['state_52'].status == result['state_58'].status == 'disabled'


def test_no_label_edges_or_implicit_leaf_project_completion(fixture):
    topology = Topology(fixture)
    assert len(topology.nodes) == 62
    assert sum(map(len, topology.successors.values())) == 71
    assert topology.successors['state_65'] == set()
    applies, completed = state(topology, ('state_65',))
    assert topology.readiness(applies, completed)['state_65'].status == 'ready'
    assert not hasattr(topology, 'project_complete')


def test_missing_applicability_and_unexpected_boolean_types_fail_closed(fixture):
    topology = Topology(fixture)
    assert topology.readiness({}, set())['started'].status == 'blocked'
    assert topology.readiness({'started': 1}, set())['started'].unknown == ('started',)


@pytest.mark.parametrize('mutation', ['cycle', 'unknown', 'duplicate', 'mode'])
def test_invalid_topologies_rejected(fixture, mutation):
    if mutation == 'cycle':
        fixture['edges'].append({'start': 'state_65', 'end': 'started'})
    elif mutation == 'unknown':
        fixture['edges'].append({'start': 'missing', 'end': 'started'})
    elif mutation == 'duplicate':
        fixture['nodes'].append(deepcopy(fixture['nodes'][0]))
    else:
        fixture['nodes'][0]['start_mode'] = 'any'
    with pytest.raises(ValueError):
        Topology(fixture)
