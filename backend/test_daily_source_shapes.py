"""Daily rows in the exact shapes read from the live V4 Base (names anonymized, ids and values literal)."""
import pytest
from .seed import seed
from .sources import day, import_sources

BASE = 'H7W6b0PFWaVF1BsgqXJj3pQ9pXb'
OUT_COST, OUT_WORK = 'tbl8wRYCUCvbSoJG', 'tbl5zPLS0ExWNEty'
IN_COST, IN_WORK = 'tblKwSDRg6WaGHYr', 'tblrCo8KeZiuJUNh'


def row(table, kind, rid, fields, **extra):
    return dict(base_token=BASE, table_id=table, kind=kind, record_id=rid, fields=fields, **extra)


def link(table, rid):
    return {'table_id': table, 'record_ids': [rid], 'text': '', 'text_arr': [], 'type': 'text'}


def outdoor_rows(**work_fields):
    cost = row(OUT_COST, 'cost', 'rec27NeQeaAvGq', {
        '工作日期': 1784044800000, '組別': '水深C',
        '組長帳號-津貼自動化': [{'id': 'ou_leader', 'name': '組長甲'}],
        '組員帳號-津貼自動化': [{'id': 'ou_member_b', 'name': '組員乙'}]})
    work = row(OUT_WORK, 'daily', 'rec27NhLgqnPpA', {
        '工作日期-薪資': 46217.66667, '組別': '水深C', '最終營業額點數': '0',
        '所屬成本單': link(OUT_COST, 'rec27NeQeaAvGq'), **work_fields},
        department='外業組', cost_table_id=OUT_COST)
    return cost, work


def only_daily(rows):
    state = seed(True)
    stats = import_sources(state, rows)
    assert stats['daily_unmatched'] == 1
    return state['daily_unmatched'][0], stats


@pytest.mark.parametrize('serial', [46217.66667, 46217.666666666664, '46217.66667', 46218])
def test_formula_serial_is_read_as_taipei_midnight(serial):
    assert day(serial, formula_serial=True) == '2026-07-15'


def test_outdoor_formula_date_matches_cost_sheet_date():
    entry, stats = only_daily(outdoor_rows())
    assert entry['date'] == '2026-07-15'
    assert stats['daily_conflicting_dates'] == 0 and stats['daily_missing_date'] == 0


def indoor_rows(**work_fields):
    cost = row(IN_COST, 'cost', 'rec27NW78r5NLM', {
        '工作日期': 1784131200000, '內業組別': '圖報A', '所屬組別': '圖報A',
        '填報帳號': [{'id': 'ou_creator', 'name': '建檔帳號'}]})
    work = row(IN_WORK, 'daily', 'rec27NXPY2wqzV', {
        '姓名': '作業人員甲', '最終營業額點數': '4', '手動點數': 4,
        '所屬成本單': link(IN_COST, 'rec27NW78r5NLM'), **work_fields}, cost_table_id=IN_COST)
    return cost, work


@pytest.mark.parametrize('roster,expected', [
    ('組長甲,組員乙,組員丙', '組長甲、組員乙、組員丙'),
    ('⚠未填組長,組員乙', '組員乙'),
])
def test_outdoor_person_is_the_crew_roster_not_just_account_holders(roster, expected):
    entry, _ = only_daily(outdoor_rows(出工人=roster))
    assert entry['person'] == expected


def test_outdoor_roster_warning_alone_names_nobody():
    cost, work = outdoor_rows(出工人='⚠未填組長')
    cost['fields'].pop('組長帳號-津貼自動化'); cost['fields'].pop('組員帳號-津貼自動化')
    entry, _ = only_daily([cost, work])
    assert entry['person'] == ''


def test_outdoor_person_falls_back_to_account_fields_without_roster():
    entry, _ = only_daily(outdoor_rows())
    assert entry['person'] == '組長甲、組員乙'
    assert entry['source_actor_ids'] == ['ou_leader', 'ou_member_b']


def test_indoor_person_is_the_worker_not_the_account_that_created_the_cost_row():
    entry, _ = only_daily(indoor_rows())
    assert entry['person'] == '作業人員甲'
    assert entry['source_actor_ids'] == ['ou_creator']


def test_indoor_person_falls_back_to_creator_account_when_name_formula_is_empty():
    entry, _ = only_daily(indoor_rows(姓名=None))
    assert entry['person'] == '建檔帳號'


PROVISIONAL = '可能的確認單工編(若暫無確認單才需填寫)'


def test_row_without_any_case_reference_is_not_labelled_provisional():
    entry, stats = only_daily(indoor_rows())
    assert entry['case_mapping_status'] == 'missing_reference'
    assert entry['match_basis'] == 'source_case_or_link'
    assert entry['mapping_status'] == 'ready'
    assert stats['daily_provisional'] == 0


def test_unmatched_provisional_code_stays_provisional():
    entry, stats = only_daily(indoor_rows(**{PROVISIONAL: 'C115211-1'}))
    assert entry['case_mapping_status'] == 'unresolved_reference'
    assert entry['match_basis'] == 'provisional_case_code'
    assert entry['mapping_status'] == 'provisional_case_code'
    assert stats['daily_provisional'] == 1


def test_manual_pairing_is_not_reported_as_provisional_pairing():
    confirmation = row('tblmSQrcCs9vPQZx', 'confirmation', 'recvsZzR9xfEVx', {'工程確認單編號': 'C115236'})
    rows = [confirmation, *indoor_rows(**{PROVISIONAL: 'C115211-1'})]
    state = seed(True)
    import_sources(state, rows)
    entry = state['daily_unmatched'][0]
    project = next(p for p in state['projects'] if p['code'] == 'C115236')
    state['daily_reviews'].append({'id': 'review-1', 'daily_id': entry['id'], 'project_id': project['id'],
                                   'status': 'approved', 'mapping_version': entry['mapping_version']})
    import_sources(state, rows)
    paired = project['daily_reports'][0]
    assert paired['match_basis'] == 'manual_review'
    assert paired['mapping_status'] == 'ready'


def test_date_formula_serial_agrees_with_payroll_date():
    _, work = outdoor_rows(**{'工作日期-薪資': 46245, '日期': 46245})
    entry, stats = only_daily([work])
    assert entry['date'] == '2026-08-11'
    assert entry['mapping_status'] != 'conflicting_dates'
    assert stats['daily_conflicting_dates'] == 0


def test_date_formula_serial_alone_is_not_unix_epoch():
    _, work = outdoor_rows(**{'工作日期-薪資': None, '日期': 46245})
    entry, _ = only_daily([work])
    assert entry['date'] == '2026-08-11'
