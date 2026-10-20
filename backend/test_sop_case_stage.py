from datetime import date

import pytest

from .sop_import.case_stage import stage, start_node
from .sop_import.quote_facts import case_facts, collect
from .sources import FIELDS, SERVER_ONLY_FIELDS, source_id
from .workspace_projection import public_source_cache

TODAY = date(2026, 10, 20)


def quote(record_id, **fields):
    return {'id': 'src-' + record_id, 'kind': 'quote', 'fields': {'報價編號': '115588', **fields}}


def entity(record_id, **fields):
    return {'id': f'base/quotes/{record_id}', 'source_identity': {'base_token': 'base', 'table_id': 'quotes', 'record_id': record_id},
            'source_missing': False, 'code': '115588', 'fields': {'報價編號': '115588', **fields}}


def stage_of(*rows):
    return stage(collect(list(rows), today=TODAY)).value


@pytest.mark.parametrize('fields,expected', [
    ({}, 'inquiry'),
    ({'報價日期': '2026-10-01', '報價期限': '2026-10-20'}, 'quoted'),
    ({'提供給PM日期': 1790208000000, '報價期限': '2026-10-19'}, 'quote_expired'),
    ({'回傳單日期': '2026-09-17'}, 'returned'),
    ({'回傳單日期': '2026-09-17', '工程編號': '報編115588'}, 'returned'),
    ({'回傳單日期': '2026-09-17', '工程編號': 'C000000'}, 'returned'),
    ({'狀態': '成案'}, 'inquiry'),
    ({'狀態': '成案', '工程編號': 'K115001'}, 'numbered'),
    ({'回傳單日期': '2026-09-17', '編號': 'X115002'}, 'numbered'),
    ({'此案確認單': [{'id': 'recCost'}], '工程編號': 'C115243'}, 'inquiry'),
    ({'此案確認單': [{'id': 'recCost'}], '工程編號': 'C115243', '回傳單日期': '2026-09-17'}, 'confirmation'),
    ({'確認單回傳開會日期': '2026-09-20', '工程編號': 'A115001', '回傳單日期': '2026-09-17'}, 'confirmation'),
    ({'確認單回傳開會日期': '2026-09-20', '回傳單日期': '2026-09-17'}, 'returned'),
    ({'狀態 (1)': '0.未開立確認單'}, 'confirmation'),
    ({'狀態 (1)': 'H.待業主通知'}, 'pricing'),
    ({'狀態 (1)': 'J.外包案件', '回傳單日期': '2026-09-17'}, 'returned'),
    ({'狀態 (1)': 'I.案件取消'}, 'cancelled'),
])
def test_stage_ladder(fields, expected):
    assert stage_of({'報價編號': '115588', **fields}) == expected


@pytest.mark.parametrize('prefix', ['C', 'A', 'B', 'K', 'X'])
def test_every_engineering_letter_counts_as_numbered(prefix):
    assert stage_of({'回傳單日期': '2026-09-17', '工程編號': prefix + '115243-01A'}) == 'numbered'


def test_cancellation_needs_every_row_and_live_label_is_the_furthest():
    assert stage_of({'狀態 (1)': 'I.案件取消'}, {'狀態 (1)': 'B.外業執行中'}) == 'field'
    assert stage_of({'狀態 (1)': 'C.內業執行中'}, {'狀態 (1)': 'B.外業執行中'}) == 'office'
    assert stage_of({'狀態 (1)': 'I.案件取消(母案)'}, {'狀態 (1)': 'I.案件取消'}) == 'cancelled'


def test_duplicate_rows_of_one_quote_number_merge_into_one_case():
    project = {'id': 'p1', 'quotes': [quote('recA', 回傳單日期='2026-09-17', 工程編號='C115243')], 'source_records': []}
    sibling = entity('recB', 確認單回傳開會日期='2026-09-20')
    deleted = dict(entity('recC', **{'狀態 (1)': 'G.已付款'}), source_missing=True)
    other_case = dict(entity('recD', **{'狀態 (1)': 'G.已付款'}), code='115589', fields={'報價編號': '115589', '狀態 (1)': 'G.已付款'})
    alone = case_facts(project, {}, TODAY)
    merged = case_facts(project, {'source_quotes': [sibling, deleted, other_case]}, TODAY)
    assert (stage(alone).value, alone.source_rows) == ('numbered', 1)
    assert (stage(merged).value, merged.source_rows, merged.quote_nos) == ('confirmation', 2, ('115588',))


def test_a_case_row_and_its_source_entity_count_once():
    project = {'id': 'p1', 'quotes': [quote('recA')], 'source_records': []}
    project['quotes'][0]['id'] = source_id({'base_token': 'base', 'table_id': 'quotes', 'record_id': 'recA'})
    assert case_facts(project, {'source_quotes': [entity('recA')]}, TODAY).source_rows == 1


def test_confirmation_records_distinguish_v4_confirmations_from_quote_costing_sheets():
    v4 = {'id': 'p1', 'quotes': [], 'source_records': [{'id': 'c1', 'kind': 'confirmation', 'fields': {}}]}
    costing = {'id': 'p2', 'quotes': [quote('recA', 工程編號='C115243')],
               'source_records': [{'id': 'c2', 'kind': 'quote_confirmation', 'fields': {}}]}
    assert stage(case_facts(v4, {}, TODAY)).value == 'confirmation'
    assert stage(case_facts(costing, {}, TODAY)).value == 'inquiry'
    costing['quotes'][0]['fields']['回傳單日期'] = '2026-09-17'
    assert stage(case_facts(costing, {}, TODAY)).value == 'confirmation'


def test_start_node_is_the_furthest_of_stage_lifecycle_and_node_progress():
    facts = collect([{'回傳單日期': '2026-09-17', '狀態 (1)': 'I.案件取消'}], today=TODAY)
    assert start_node({}, [], facts) == 'pm'
    assert start_node({}, [{'key': 'field', 'status': 'completed'}], facts) == 'control'
    lifecycle = {'source_lifecycle': {'state': 'mapped', 'canonical': '已完工', 'reasons': []}}
    assert start_node(lifecycle, [], facts) == 'pricing'


def test_quote_projection_fetches_evidence_and_keeps_money_and_points_server_side():
    assert {'回傳單日期', '提供給PM日期', '狀態 (1)', '確認單回傳開會日期', '編號', '報價日期', '外業確認單營業額',
            '契約價格(含稅)'} <= set(FIELDS['quote'])
    public = public_source_cache({'records': [{'kind': 'quote', 'record_id': 'r', 'fields': {
        '回傳單日期': 1790208000000, '狀態 (1)': 'B.外業執行中', '外業確認單營業額': 1.5, '契約價格(含稅)': 105000}}]})
    assert public['records'][0]['fields'] == {'回傳單日期': 1790208000000, '狀態 (1)': 'B.外業執行中'}
    assert {'契約價格(含稅)', '行政確認單營業額'} <= SERVER_ONLY_FIELDS
