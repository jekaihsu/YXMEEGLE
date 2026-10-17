"""Entity history distinguishes observed source values from import projections."""
from copy import deepcopy

from .source_entities import entity_id, update_entities
from .sources import source_id
from .test_new_daily_acceptance import BASE, link, row


def fixture():
    contract = row('contract', 'recContract', {'合約工作項目': 'survey', '分項金額(報出)': 100})
    reports = [row('reporting', rid, {'來源合約明細（日報關聯）': link('contract', 'recContract')})
               for rid in ('recReportA', 'recReportB')]
    tasks = [{'id': source_id(report)} for report in reports]
    ws = {'projects': [{'id': 'project', 'nodes': [{'id': 'node', 'tasks': tasks}], 'quotes': []}]}
    return ws, contract, reports


def item(ws):
    return ws['contract_items'][0]


def test_report_fetch_order_does_not_bump_contract_revision():
    ws, contract, reports = fixture()
    update_entities(ws, [contract, *reports], [], {source_id(contract): 'project'})
    before = deepcopy(item(ws))
    update_entities(ws, [reports[1], contract, reports[0]], [], {source_id(contract): 'project'})
    assert item(ws) == before
    assert item(ws)['reporting_ids'] == sorted(entity_id(report) for report in reports)


def test_history_explains_raw_field_and_projection_changes_separately():
    ws, contract, reports = fixture()
    update_entities(ws, [contract, *reports], [], {source_id(contract): 'project'})
    prior = deepcopy(item(ws))
    contract['fields']['分項金額(報出)'] = 125
    ws['projects'][0]['nodes'][0]['tasks'].pop()
    update_entities(ws, [contract, *reports], [], {source_id(contract): 'project'})
    entry = item(ws)['history'][-1]
    assert entry['snapshot']['fields'] == prior['fields']
    changes = {change['path']: change for change in entry['change_explanation']}
    assert changes['fields.分項金額(報出)'] == {
        'path': 'fields.分項金額(報出)', 'before': 100, 'after': 125,
        'provenance': 'source_observed', 'source_field': '分項金額(報出)'}
    assert changes['amount_reported'] == {
        'path': 'amount_reported', 'before': 100.0, 'after': 125.0,
        'provenance': 'derived',
        'derived_from': {'source_fields': ['contract:分項金額(報出)']}}
    assert changes['task_refs']['provenance'] == 'derived'
    assert changes['task_refs']['derived_from'] == {
        'source_fields': ['reporting:來源合約明細（日報關聯）'],
        'other_inputs': ['workspace_tasks']}
    assert changes['task_refs']['before'] != changes['task_refs']['after']
    assert 'formula' not in changes['fields.分項金額(報出)']
    assert changes['reporting_ids']['provenance'] == 'derived'
    assert changes['reporting_ids']['derived_from']['other_inputs'] == ['workspace_tasks']


def test_formula_schema_marks_observation_without_claiming_human_edit():
    ws, contract, reports = fixture()
    table = {'base_token': BASE, 'table_id': contract['table_id'], 'status': 'ready',
             'field_schema': [{'field_name': '分項金額(報出)', 'type': 20,
                               'property': {'formula': 'SUM(1,2)'}}]}
    update_entities(ws, [contract, *reports], [table], {})
    contract['fields']['分項金額(報出)'] = 125
    update_entities(ws, [contract, *reports], [table], {})
    changes = {change['path']: change for change in item(ws)['history'][-1]['change_explanation']}
    assert changes['fields.分項金額(報出)']['provenance'] == 'source_formula_observed'
    assert changes['fields.分項金額(報出)']['formula'] == 'SUM(1,2)'


def test_link_order_is_normalized_but_missing_and_resolved_remain_distinct():
    a = row('confirmation', 'recA', {})
    b = row('confirmation', 'recB', {})
    contract = row('contract', 'recContract', {'所屬成案確認單（日報關聯）': link('confirmation', 'recB', 'recA')})
    ws = {'projects': []}
    update_entities(ws, [contract, a, b], [], {})
    assert item(ws)['confirmation_ids'] == sorted((entity_id(a), entity_id(b)))
    before = deepcopy(item(ws))
    contract['fields']['所屬成案確認單（日報關聯）'] = link('confirmation', 'recA', 'recB')
    update_entities(ws, [b, contract, a], [], {})
    # Raw link order is preserved as observed evidence, even if projection order is stable.
    assert item(ws)['confirmation_ids'] == before['confirmation_ids']
    assert item(ws)['history'][-1]['change_explanation'][0]['path'].startswith('fields.')


def test_legacy_unsorted_relations_do_not_pollute_real_change_explanation():
    ws, contract, reports = fixture()
    update_entities(ws, [contract, *reports], [], {source_id(contract): 'project'})
    legacy = item(ws)
    legacy['reporting_ids'].reverse()
    legacy['task_refs'].reverse()
    contract['fields']['分項金額(報出)'] = 125
    update_entities(ws, [contract, *reports], [], {source_id(contract): 'project'})
    entry = item(ws)['history'][-1]
    paths = {change['path'] for change in entry['change_explanation']}
    assert paths == {'fields.分項金額(報出)', 'amount_reported'}
    assert entry['snapshot']['reporting_ids'] == list(reversed(item(ws)['reporting_ids']))


def test_formula_type_without_expression_does_not_invent_formula():
    ws, contract, reports = fixture()
    table = {'base_token': BASE, 'table_id': contract['table_id'], 'status': 'ready',
             'field_schema': [{'field_name': '分項金額(報出)', 'type': 20}]}
    update_entities(ws, [contract, *reports], [table], {})
    contract['fields']['分項金額(報出)'] = 125
    update_entities(ws, [contract, *reports], [table], {})
    changes = {change['path']: change for change in item(ws)['history'][-1]['change_explanation']}
    assert changes['fields.分項金額(報出)']['provenance'] == 'source_formula_observed'
    assert 'formula' not in changes['fields.分項金額(報出)']


def test_contract_scalar_and_assignment_explanations_name_inputs():
    ws, contract, reports = fixture()
    update_entities(ws, [contract, *reports], [], {source_id(contract): 'project'})
    contract['fields'].update({'合約工作項目': 'mapping', '合約項次': '2', '分項金額(原始)': 90})
    update_entities(ws, [contract, *reports], [], {})
    changes = {change['path']: change for change in item(ws)['history'][-1]['change_explanation']}
    assert changes['title']['derived_from'] == {'source_fields': ['contract:合約工作項目']}
    assert changes['item_number']['derived_from'] == {'source_fields': ['contract:合約項次']}
    assert changes['amount_original']['derived_from'] == {'source_fields': ['contract:分項金額(原始)']}
    assert changes['project_id']['derived_from'] == {'other_inputs': ['workspace_source_assignments']}


def native_link(table_id, record_id):
    return [{'table_id': table_id, 'record_ids': [record_id]}]


def test_confirmation_link_uses_embedded_target_table_with_duplicate_record_id():
    a = row('confirmation', 'recShared', {});a['table_id'] = 'tbl-confirm-a'
    b = row('confirmation', 'recShared', {});b['table_id'] = 'tbl-confirm-b'
    contract = row('contract', 'recContract', {
        '所屬成案確認單（日報關聯）': native_link(a['table_id'], 'recShared')})
    ws = {'projects': []}
    update_entities(ws, [contract, a, b], [], {})
    assert item(ws)['confirmation_ids'] == [entity_id(a)]
    assert item(ws)['unresolved_confirmation_ids'] == []
    update_entities(ws, [contract, b], [], {})
    assert item(ws)['confirmation_ids'] == []
    assert item(ws)['unresolved_confirmation_ids'] == ['recShared']


def test_reporting_link_uses_embedded_contract_table_with_duplicate_record_id():
    a = row('contract', 'recShared', {});a['table_id'] = 'tbl-contract-a'
    b = row('contract', 'recShared', {});b['table_id'] = 'tbl-contract-b'
    report = row('reporting', 'recReport', {
        '來源合約明細（日報關聯）': native_link(a['table_id'], 'recShared')})
    task = {'id': source_id(report)}
    ws = {'projects': [{'id': 'project', 'nodes': [{'id': 'node', 'tasks': [task]}]}]}
    update_entities(ws, [report, a, b], [], {})
    contracts = {entry['id']: entry for entry in ws['contract_items']}
    assert contracts[entity_id(a)]['reporting_ids'] == [entity_id(report)]
    assert contracts[entity_id(b)]['reporting_ids'] == []
    assert task['contract_item_ids'] == [entity_id(a)]
    update_entities(ws, [report, b], [], {})
    assert task['contract_item_ids'] == []
    assert task['contract_link_unresolved'] is True
