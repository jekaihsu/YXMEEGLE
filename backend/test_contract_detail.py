"""Synthetic behavior checks for the unwired, already-authorized read model."""
from copy import deepcopy

import pytest

from . import contract_detail as model
from .source_entities import update_entities
from .sources import source_id


BASE, CONF, CONTRACT, ITEM = 'baseSynthetic', 'tblConfirmation', 'tblContract', 'tblItem'
KEY = f'{BASE}/{CONTRACT}/recLine'
AMOUNTS = (918273, 827364, 736455, 645546, 563728, 481920)


def fixture():
    def row(table, kind, record, fields):
        return dict(base_token=BASE, table_id=table, kind=kind, record_id=record, fields=fields)
    records = [row(CONF, 'confirmation', 'recParent', {'工程確認單編號': 'SYN-001'}),
               row(CONTRACT, 'contract', 'recLine', {
                   '合約項次': '1', '合約工作項目': 'Synthetic line',
                   '分項金額(原始)': AMOUNTS[0], '分項金額(報出)': AMOUNTS[1],
                   '所屬成案確認單（日報關聯）': [{'table_id': CONF, 'record_ids': ['recParent']}],
                   '控制預估工天': 2})]
    state = {'projects': [{'id': 'projectSynthetic', 'nodes': []}]}
    update_entities(state, records, [], {source_id(row): 'projectSynthetic' for row in records})
    return state, records


def leaves(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from leaves(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from leaves(item)
    else:
        yield value


def assert_amount_guard(result):
    main = result['main']
    assert main['original_amount']['state'] == 'withheld'
    assert main['current_revised_amount']['state'] == 'withheld'
    assert main['original_amount']['reason'].startswith('G-AMT:')
    assert not set(AMOUNTS).intersection(leaves(result))
    assert not {str(amount) for amount in AMOUNTS}.intersection(leaves(result))


def test_current_and_historic_source_versions_are_traceable_not_formal_revisions():
    state, records = fixture()
    records[1]['fields'].update({'合約工作項目': 'Updated synthetic line',
                                '分項金額(原始)': AMOUNTS[2], '分項金額(報出)': AMOUNTS[3]})
    update_entities(state, records, [], {source_id(row): 'projectSynthetic' for row in records})
    result = model.build_contract_detail(state, KEY, as_of='2020-01-01')
    assert result['main']['name'] == 'Updated synthetic line'
    assert result['main']['identity']['version_key'] == [BASE, CONTRACT, 'recLine', 2]
    old = result['version_history']['historical_observations'][0]
    assert old['line']['name'] == 'Synthetic line'
    assert old['line']['identity']['version_key'] == [BASE, CONTRACT, 'recLine', 1]
    assert old['kind'] == 'observed_source_snapshot'
    assert result['version_history']['formal_revisions'] == {'state': {'states': ['unlocated'], 'count': None}}
    assert result['version_history']['effective_business_version']['state'] == 'unknown'
    assert_amount_guard(result)


def test_original_revised_forbidden_and_derived_amounts_never_escape_any_section():
    state, _ = fixture()
    line = state['contract_items'][0]
    line.update(amount_difference=AMOUNTS[4], amount_ratio=AMOUNTS[5], total=AMOUNTS[0] + AMOUNTS[1])
    line['fields'].update({'amount_difference': AMOUNTS[4], 'amount_ratio': AMOUNTS[5],
                           '成本': AMOUNTS[2], '控制工項': {'amount': AMOUNTS[3]},
                           'SourceID': {'value': AMOUNTS[4]}})
    result = model.build_contract_detail(state, KEY)
    assert result['main']['name'] == 'Synthetic line'
    assert result['details']['source_fields'] == {'合約項次': '1', '合約工作項目': 'Synthetic line', '控制預估工天': 2}
    assert_amount_guard(result)
    assert AMOUNTS[0] + AMOUNTS[1] not in list(leaves(result))
    del line['fields']['分項金額(原始)']
    del line['fields']['分項金額(報出)']
    assert_amount_guard(model.build_contract_detail(state, KEY))


def test_missing_quantity_is_unknown_and_unproven_mixed_units_never_total():
    state, _ = fixture()
    line = state['contract_items'][0]
    line.update(quantity=5, unit='meters')
    line['fields'].update({'數量': 5, '單位': 'meters'})
    state['source_work_items'] = [dict(id=f'{BASE}/{ITEM}/recA', contract_ids=[KEY], quantity=7, unit='hours'),
                                  dict(id=f'{BASE}/{ITEM}/recB', contract_ids=[KEY], quantity=9, unit='meters')]
    result = model.build_contract_detail(state, KEY)
    assert result['main']['quantity'] == {'state': 'unknown', 'reason': 'quantity field unlocated'}
    assert result['main']['unit'] == {'state': 'unknown', 'reason': 'unit field unlocated'}
    assert len(result['work_items']['rows']) == 2
    assert all(row['quantity']['state'] == row['unit']['state'] == 'unknown' for row in result['work_items']['rows'])
    assert 'total' not in result['main'] and 'total' not in result['work_items']
    line.pop('quantity')
    assert model.build_contract_detail(state, KEY)['main']['quantity']['state'] == 'unknown'


def test_many_to_many_native_edges_dedupe_before_join_and_leave_parent_grain_intact():
    state, _ = fixture()
    state['contract_items'].append(deepcopy(state['contract_items'][0]))
    state['source_work_items'] = [dict(id=f'{BASE}/{ITEM}/recB', contract_ids=[KEY, KEY, 'other/native/line']),
                                  dict(id=f'{BASE}/{ITEM}/recA', contract_ids=[KEY, 'other/native/line']),
                                  dict(id=f'{BASE}/{ITEM}/recB', contract_ids=[KEY]),
                                  dict(id=f'{BASE}/{ITEM}/recUnrelated', contract_ids=['other/native/line'])]
    result = model.build_contract_detail(state, KEY)
    assert [row['identity']['record_id'] for row in result['work_items']['rows']] == ['recA', 'recB']
    assert result['details']['relationship_count'] == {'states': ['partial'], 'count': 2}
    assert result['main']['quantity']['state'] == 'unknown'
    assert result['details']['source_fields']['控制預估工天'] == 2
    assert result['main']['identity']['source_key'] == KEY


def test_equal_sibling_names_keep_native_identities_and_missing_parent_is_unresolved():
    state, _ = fixture()
    for rid in ('recSiblingA', 'recSiblingB'):
        sibling = deepcopy(state['contract_items'][0])
        sibling['id'] = f'{BASE}/{CONTRACT}/{rid}'
        sibling['source_identity']['record_id'] = rid
        state['contract_items'].append(sibling)
    result = model.build_contract_detail(state, KEY)
    assert [row['identity']['record_id'] for row in result['siblings']['rows']] == ['recSiblingA', 'recSiblingB']
    assert [row['name'] for row in result['siblings']['rows']] == ['Synthetic line', 'Synthetic line']
    assert result['header']['parent_confirmations'][0]['reference'] == 'SYN-001'
    state['source_confirmations'] = []
    state['contract_items'][0]['unresolved_confirmation_ids'] = ['hiddenSyntheticParent']
    result = model.build_contract_detail(state, KEY)
    assert result['header']['parent_state']['states'] == ['unlocated']
    assert result['header']['parent_confirmations'] == [] and result['siblings']['rows'] == []
    assert 'hiddenSyntheticParent' not in list(leaves(result))


def test_already_redacted_absence_never_rewidens_or_echoes_forbidden_identity():
    state, _ = fixture()
    before = deepcopy(state)
    result = model.build_contract_detail(state, KEY)
    assert result['main']['name'] == 'Synthetic line' and state == before
    state['contract_items'] = []
    state['raw_records'] = before['contract_items']
    assert model.build_contract_detail(state, KEY) == {'page_state': {'states': ['unlocated'], 'count': None}}


def test_complete_child_population_zero_is_distinct_from_unknown():
    state, _ = fixture()
    assert model.build_contract_detail(state, KEY)['work_items']['state'] == {'states': ['unknown'], 'count': None}
    state['source_work_items_status'] = {'projectSynthetic': {'partial': False}}
    assert model.build_contract_detail(state, KEY)['work_items']['state'] == {'states': ['complete_empty'], 'count': 0}
    state['source_work_items_status']['projectSynthetic']['partial'] = True
    assert model.build_contract_detail(state, KEY)['work_items']['state'] == {'states': ['unknown'], 'count': None}


@pytest.mark.parametrize('version', [True, 1.0, ' padded '])
def test_invalid_c_id_versions_are_not_silently_coerced(version):
    state, _ = fixture()
    state['contract_items'][0]['revision'] = version
    assert model.build_contract_detail(state, KEY) == {'page_state': {'states': ['unlocated'], 'count': None}}


def test_foreign_history_and_unexplained_differences_do_not_become_revisions():
    state, _ = fixture()
    line = state['contract_items'][0]
    foreign = deepcopy(line)
    foreign['id'] = f'{BASE}/{CONTRACT}/recForeign'
    foreign['source_identity']['record_id'] = 'recForeign'
    line['history'] = [{'revision': 1, 'snapshot': foreign}]
    line['unexplained_differences'] = [{'reason': 'invented revision', 'amount': AMOUNTS[0]}] * 13
    result = model.build_contract_detail(state, KEY)
    assert result['main']['identity']['record_id'] == 'recLine'
    assert result['version_history']['historical_observations'] == []
    assert result['version_history']['formal_revisions']['state']['states'] == ['unlocated']
    assert_amount_guard(result)


def test_mutation_amount_withholding_guard_is_detected(monkeypatch):
    state, _ = fixture()
    monkeypatch.setattr(model, '_amount', lambda: {'state': 'known', 'value': AMOUNTS[0]})
    with pytest.raises(AssertionError):
        assert_amount_guard(model.build_contract_detail(state, KEY))


def test_mutation_unit_isolation_guard_is_detected(monkeypatch):
    original = model._line
    def mutant(row, version=None):
        result = original(row, version)
        result['quantity'] = {'state': 'known', 'value': 21}
        result['unit'] = {'state': 'known', 'value': 'mixed'}
        return result
    monkeypatch.setattr(model, '_line', mutant)
    with pytest.raises(AssertionError):
        test_missing_quantity_is_unknown_and_unproven_mixed_units_never_total()


def test_mutation_dedupe_guard_is_detected(monkeypatch):
    original = model._unique
    class DuplicateJoin(dict):
        def items(self):
            rows = list(super().items())
            return rows + rows
    monkeypatch.setattr(model, '_unique', lambda rows: DuplicateJoin(original(rows)))
    with pytest.raises(AssertionError):
        test_many_to_many_native_edges_dedupe_before_join_and_leave_parent_grain_intact()


def test_mutation_forbidden_derived_field_guard_is_detected(monkeypatch):
    monkeypatch.setattr(model, '_fields', lambda row: row.get('fields') or {})
    with pytest.raises(AssertionError):
        test_original_revised_forbidden_and_derived_amounts_never_escape_any_section()


def test_retained_missing_source_is_partial_and_stale_not_a_new_effective_version():
    state, _ = fixture()
    state['contract_items'][0]['source_missing'] = True
    result = model.build_contract_detail(state, KEY)
    assert result['page_state'] == {'states': ['partial', 'stale'], 'count': None}
    assert result['main']['identity']['version'] == 1
    assert result['version_history']['effective_business_version']['state'] == 'unknown'
