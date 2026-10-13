"""Synthetic, read-only behavioral coverage for the injected population protocol."""
from copy import deepcopy
import json

import pytest

from .data_state import data_state
from .manager_overview import build_manager_overview as build
from .source_health import build_source_health


AS_OF = '2026-10-14T08:00:00+08:00'


def workspace():
    return {'environment': 'production',
            'users': [{'id': 'pm-A', 'name': 'Synthetic PM'}],
            'projects': [
                {'id': 'case-A', 'code': 'DUP', 'name': 'Old unfinished', 'pm_id': 'pm-A',
                 'execution_status': 'in_progress', 'created_at': '2020-01-01',
                 'case_visibility': 'source_reference', 'execution_system': 'workbench',
                 'due_date': '2020-02-01'},
                {'id': 'case-B', 'code': 'DUP', 'name': 'Separate case',
                 'execution_status': 'paused', 'created_at': '2026-10-13'},
                {'id': 'case-C', 'name': 'Completed case', 'execution_status': 'completed'}],
            # Fake population contains exactly the required two identity keys;
            # it does not smuggle business predicates or read metadata in rows.
            'confirmation_fixture': [
                {'row_key': 'rk-01', 'project_id': 'case-A'},
                {'row_key': 'rk-02', 'project_id': 'case-A'},
                {'row_key': 'rk-03', 'project_id': 'case-B'},
                {'row_key': 'rk-04', 'project_id': None},
                {'row_key': 'rk-05', 'project_id': 'case-C'}]}


def population(state, filters):
    """Stand-in for the reviewed shared function, with identical authorization scope."""
    visible = {p['id']: p for p in state['projects']}
    rows = [r for r in state['confirmation_fixture'] if r['project_id'] is None or r['project_id'] in visible]
    if filters.get('version'):
        rows = [r for r in rows if {'rk-01': 'v3', 'rk-02': 'v4', 'rk-03': 'v4', 'rk-04': 'v4', 'rk-05': 'v4'}[r['row_key']] == filters['version']]
    if filters.get('pm_id'):
        rows = [r for r in rows if visible.get(r['project_id'], {}).get('pm_id') == filters['pm_id']]
    if filters.get('execution_status'):
        rows = [r for r in rows if visible.get(r['project_id'], {}).get('execution_status') == filters['execution_status']]
    return deepcopy(rows)


def overview(state=None, **options):
    return build(state if state is not None else workspace(), population=population, as_of=AS_OF, **options)


def cards(result):
    return {c['id']: c for c in result['snapshot']['cards']}


def test_old_unfinished_case_is_visible_for_every_activity_period():
    old = overview(period={'start': '2020-01-01', 'end': '2020-01-07'})
    recent = overview(period={'start': '2026-10-12', 'end': '2026-10-18'})
    assert recent['snapshot'] == old['snapshot']
    assert [r['project_id'] for r in recent['snapshot']['cases']] == ['case-A', 'case-B']
    assert recent['snapshot']['cases'][0]['unfinished']['value'] is True
    assert recent['weekly_activity']['state']['states'] == ['unlocated']
    assert recent['weekly_activity']['rows'] is None
    assert recent['weekly_activity']['period']['start'] == '2026-10-12'


@pytest.mark.parametrize('filters', [{}, {'version': 'v4'}, {'pm_id': 'pm-A'},
                                     {'execution_status': 'paused'}, {'version': 'v3', 'pm_id': 'pm-A'}])
def test_every_implemented_kpi_equals_identical_drilldown_population(filters):
    state = workspace()
    result = overview(state, filters=filters)
    for card in result['snapshot']['cards']:
        assert card['drilldown']['route'] == 'confirmations'
        assert card['drilldown']['filters'] == filters
        assert card['as_of'] == AS_OF
        if card['value'] is None:
            assert card['reason']
            continue
        same_set = population(state, card['drilldown']['filters'])
        expected = len(same_set) if card['unit'] == 'confirmation_version' else len(
            {r['project_id'] for r in same_set if r['project_id'] is not None})
        assert card['value'] == expected
        assert card['state']['count'] == expected
    assert cards(result)['confirmation_versions']['value'] is not None
    assert cards(result)['stable_cases']['value'] is not None


def test_two_versions_count_one_case_and_duplicate_codes_stay_separate():
    result = overview(filters={'pm_id': 'pm-A'})
    assert cards(result)['confirmation_versions']['value'] == 2
    assert cards(result)['stable_cases']['value'] == 1
    assert len(result['snapshot']['cases'][0]['details']['row_keys']) == 2
    all_cases = overview()['snapshot']['cases']
    assert [r['label'] for r in all_cases] == ['Old unfinished', 'Separate case']


def test_unresolved_is_reported_separately_and_never_counted_as_a_case():
    result = overview()
    assert cards(result)['confirmation_versions']['value'] == 5
    assert cards(result)['stable_cases']['value'] == 3
    assert result['snapshot']['unresolved']['value'] == 1
    assert result['snapshot']['unresolved']['rows'] == [
        {'details': {'row_key': 'rk-04', 'mapping_state': 'receipt_missing'}}]
    state = workspace()
    state['confirmation_fixture'] = [state['confirmation_fixture'][3]]
    assert cards(overview(state))['stable_cases']['value'] is None  # no proven complete zero
    assert overview(state)['snapshot']['cases'] == []


def test_overlapping_populations_are_not_summed_into_a_total():
    result = overview()
    assert cards(result)['confirmation_versions']['value'] == 5
    assert cards(result)['stable_cases']['value'] == 3
    versions = overview(filters={'version': 'v4'})
    pm = overview(filters={'pm_id': 'pm-A'})
    assert cards(versions)['stable_cases']['value'] == 3
    assert cards(pm)['stable_cases']['value'] == 1
    assert set(r['project_id'] for r in versions['snapshot']['cases']) & set(
        r['project_id'] for r in pm['snapshot']['cases']) == {'case-A'}
    assert 'total' not in result['snapshot']
    assert 'never be summed' in result['snapshot']['bucket_policy']


def test_undefined_cards_stay_unavailable_even_for_proven_empty_read():
    result = overview(filters={'version': 'absent'}, population_state=data_state('complete_empty'))
    assert cards(result)['confirmation_versions']['value'] == 0
    for ident in ('pending_decisions', 'overdue_cases'):
        assert cards(result)[ident]['value'] is None
        assert cards(result)[ident]['state'] == data_state('unknown')
        assert cards(result)[ident]['reason']


def test_missing_completeness_never_turns_empty_or_filtered_empty_into_zero():
    nonempty = overview()
    assert cards(nonempty)['confirmation_versions']['state']['states'] == ['partial']
    empty = overview(filters={'version': 'absent'})
    assert cards(empty)['confirmation_versions']['value'] is None
    assert cards(empty)['stable_cases']['value'] is None
    assert empty['snapshot']['state'] == data_state('unknown')
    for state in ('complete_empty', 'filtered_empty'):
        proven = overview(filters={'version': 'absent'}, population_state=data_state(state))
        assert cards(proven)['confirmation_versions']['value'] == 0
        assert cards(proven)['stable_cases']['value'] == 0
        assert cards(proven)['stable_cases']['state'] == data_state(state)
        assert proven['snapshot']['unresolved']['value'] == 0


@pytest.mark.parametrize('states', [('loading',), ('unlocated',), ('unknown',), ('read_failed',),
                                  ('partial',), ('stale',), ('partial', 'stale')])
def test_population_read_state_propagates_without_erasing_retained_cases(states):
    result = overview(population_state=data_state(*states))
    assert result['snapshot']['state']['states'] == list(states)
    assert [r['project_id'] for r in result['snapshot']['cases']] == ['case-A', 'case-B']
    counted = states[0] in ('partial', 'stale')
    assert cards(result)['confirmation_versions']['value'] == (5 if counted else None)
    assert cards(result)['confirmation_versions']['state']['states'] == list(states)


def test_case_gaps_receipt_claims_due_dates_and_amounts_do_not_become_facts():
    state = workspace()
    p = state['projects'][0]
    p.update(source_status='已結案', source_lifecycle={'state': 'mapped', 'canonical': '已結案', 'reasons': []},
             verified_by='owner', evidence_ref='approved', contract_amount=918273,
             effective_due_date='2026-10-20', due_date_verified=True,
             pending_requested_date='2026-11-01', estimated_due_date='2026-12-01')
    row = overview(state)['snapshot']['cases'][0]
    assert row['label'] == 'Old unfinished'
    assert row['responsible']['value'] == 'Synthetic PM'
    assert row['unfinished']['value'] is True
    for key in ('actionable', 'current_stage', 'effective_due_date', 'blocker', 'pending_decision'):
        assert row[key]['value'] is None
        assert row[key]['reason']
    assert row['details']['mapping_state'] == 'receipt_missing'
    assert row['details']['amounts']['state'] == 'withheld'
    serialized = json.dumps(row)
    assert all(value not in serialized for value in ('918273', '2026-10-20', '2026-11-01', '2026-12-01'))


def test_unknown_execution_stays_visible_and_pending_handover_does_not_replace_pm():
    state = workspace()
    state['projects'][0].pop('execution_status')
    state['handover_requests'] = [{'project_id': 'case-A', 'status': 'awaiting_acceptance', 'to_id': 'future-PM'}]
    result = overview(state)
    row = result['snapshot']['cases'][0]
    assert row['unfinished']['value'] is None
    assert row['responsible']['value'] == 'Synthetic PM'
    assert row['details']['pm_id'] == 'pm-A'
    assert row['entry_point']['route'] == '/#view=project&project=case-A&tab=flow'


def test_one_failed_source_scopes_only_health_and_hides_inventory():
    snapshot = {'status': 'ready', 'tables': [
        {'base_token': 'base-A', 'table_id': 'table-A', 'status': 'ready', 'pages_read': 1, 'count': 5},
        {'base_token': 'base-B', 'table_id': 'table-B', 'status': 'error', 'name': 'Restricted-ish diagnostic label'},
        {'base_token': 'SECRET', 'table_id': 'SECRET', 'status': 'forbidden', 'name': 'Forbidden source', 'count': 888}]}
    health = build_source_health(snapshot, {'status': 'fresh'}, diagnostic=True)
    assert health['page_state'] == data_state('read_failed')
    result = overview(source_health=health)
    assert result['snapshot'] == overview()['snapshot']
    assert result['source_health']['failure']['state'] == data_state('read_failed')
    assert result['source_health']['unmatched']['value'] is None
    assert all(v not in json.dumps(result) for v in ('SECRET', 'Forbidden source', '888', 'Restricted-ish'))
    clean = overview(source_health={'page_state': None, 'sources': []})
    assert clean['source_health']['state'] == data_state('unknown')


def test_forbidden_absent_case_leaves_no_identity_label_or_count_hint():
    state = workspace()
    state['projects'] = state['projects'][1:]
    state['confirmation_fixture'][0]['label'] = 'Forbidden old case'
    result = overview(state)
    assert cards(result)['confirmation_versions']['value'] == 3
    assert cards(result)['stable_cases']['value'] == 2
    assert [r['project_id'] for r in result['snapshot']['cases']] == ['case-B']
    serialized = json.dumps(result)
    assert all(s not in serialized for s in ('case-A', 'Old unfinished', 'Forbidden old case', 'hidden_count'))
    assert cards(overview())['confirmation_versions']['value'] == 5


def test_forbidden_population_does_not_call_population_or_emit_cards():
    def forbidden_population(*args):
        raise AssertionError('must not read forbidden population')
    result = build(workspace(), population=forbidden_population, population_state=data_state('forbidden'))
    assert result['snapshot'] == {'state': {'states': ['forbidden']}}
    assert overview()['snapshot']['cases'][0]['label'] == 'Old unfinished'


def test_broken_injection_fails_without_exposing_out_of_scope_id():
    with pytest.raises(ValueError, match='outside the authorized workspace') as error:
        build(workspace(), population=lambda s, f: [{'row_key': 'opaque', 'project_id': 'SECRET'}])
    assert 'SECRET' not in str(error.value)
    assert cards(overview())['stable_cases']['value'] == 3


def test_input_and_filter_context_are_preserved_without_mutation():
    state = workspace()
    before = deepcopy(state)
    filters = {'version': 'v4', 'cutoff': AS_OF, 'scope': {'source': 'authorized'}}
    result = overview(state, filters=filters)
    assert state == before
    assert cards(result)['confirmation_versions']['value'] == 4
    result['snapshot']['cards'][0]['drilldown']['filters']['scope']['source'] = 'changed'
    assert filters['scope']['source'] == 'authorized'
    assert result['snapshot']['filters'] == filters


def test_complete_claim_cannot_contradict_rows_and_ready_is_not_a_c_state():
    with pytest.raises(ValueError, match='contradicts'):
        overview(population_state=data_state('complete_empty'))
    with pytest.raises(ValueError, match='unsupported state'):
        overview(population_state={'states': ['ready']})
    assert cards(overview())['stable_cases']['value'] == 3


@pytest.mark.parametrize('states', [None, ('unknown',), ('loading',), ('read_failed',),
                                  ('unlocated',), ('partial',), ('stale',), ('partial', 'stale'),
                                  ('complete_empty',), ('filtered_empty',)])
def test_unavailable_population_is_never_an_empty_denominator(states):
    result = build(workspace(), population=lambda s, f: None,
                   population_state=data_state(*states) if states else None, as_of=AS_OF)
    expected = list(states) if states and states[0] not in ('complete_empty', 'filtered_empty') else ['unknown']
    assert result['snapshot']['state']['states'] == expected
    assert result['snapshot']['cases'] == []
    assert result['snapshot']['unresolved']['value'] is None
    for card in result['snapshot']['cards']:
        assert card['value'] is None
        assert card['reason']
    for key in ('confirmation_versions', 'stable_cases'):
        assert cards(result)[key]['state']['states'] == expected
    assert cards(overview())['confirmation_versions']['value'] == 5


@pytest.mark.parametrize('key', [None, '', ['unencoded', 'key'], {'raw_fields': 123}, 'rk-01'])
def test_malformed_or_duplicate_population_identity_is_rejected(key):
    state = workspace()
    state['confirmation_fixture'][1]['row_key'] = key
    with pytest.raises(ValueError, match='unique nonempty opaque string'):
        overview(state)
    assert cards(overview())['confirmation_versions']['value'] == 5
