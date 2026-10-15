"""Case 基本資料 read from the live quote and confirmation Bases (company names anonymized, ids and codes literal)."""
from .seed import seed
from .sources import import_sources

V4 = 'H7W6b0PFWaVF1BsgqXJj3pQ9pXb'
QUOTE_BASE = 'JoOqbggsVar0ATsVgbcjh6IIp1g'


def confirmation(code='C115264', rid='recvsnzx3bjtAA'):
    return dict(base_token=V4, table_id='tblmSQrcCs9vPQZx', kind='confirmation', record_id=rid,
                fields={'工程確認單編號': code, '合約總額': 516964})


def quote(rid, client, number='115588', engineering='C115264', amount=None):
    fields = {'工程編號': engineering, '報價編號': number, '行號單位': client}
    if amount is not None:
        fields['契約價格(未稅)'] = amount
    return dict(base_token=QUOTE_BASE, table_id='tblENZvYAya93Twa', kind='quote', record_id=rid, fields=fields)


def imported(rows):
    state = seed(True)
    import_sources(state, rows)
    return state


def case(state, code):
    return next(p for p in state['projects'] if p['code'] == code)


def test_client_comes_from_the_quote_company_field():
    state = imported([confirmation(), quote('recvs99lJ624pD', '客戶甲')])
    assert case(state, 'C115264')['client'] == '客戶甲'


def test_duplicate_quote_rows_with_the_same_company_still_give_one_client():
    state = imported([confirmation(), quote('recvs99lJ624pD', '客戶甲'), quote('recvtieNVfGZWN', '客戶甲', amount=343255)])
    project = case(state, 'C115264')
    assert len(project['quotes']) == 2 and project['client'] == '客戶甲'


def test_conflicting_company_values_are_left_blank_and_reported():
    state = imported([confirmation(), quote('recvs99lJ624pD', '客戶甲'), quote('recvtieNVfGZWN', '客戶乙')])
    project = case(state, 'C115264')
    assert project['client'] == ''
    assert project['source_conflicts']['行號單位'] == ['客戶乙', '客戶甲']


def test_unconfirmed_quote_case_also_shows_its_company():
    state = imported([quote('recvsJGnMXU4gK', '客戶丙', number='115576', engineering='')])
    intake = case(state, '115576')
    assert intake['case_type'] == 'intake' and intake['client'] == '客戶丙'
