"""Daily rows in the exact shapes read from the live V4 Base (names anonymized, ids and values literal)."""
import pytest
from .seed import seed
from .sources import day, import_sources

BASE = 'H7W6b0PFWaVF1BsgqXJj3pQ9pXb'
OUT_COST, OUT_WORK = 'tbl8wRYCUCvbSoJG', 'tbl5zPLS0ExWNEty'


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
