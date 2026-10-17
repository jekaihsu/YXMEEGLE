"""GET /api/projects/{id}/progress over the isolated P2 SQLite workspace plus a synthetic reports snapshot."""
import json
import pytest
from .contract_links import build_projection, record_key
from .reports.snapshot import SnapshotStore
from .test_p2_int_routes import http, B, CT, KT, WT, WID, conf, contract, work, ident, fresh_cache, build_state  # noqa: F401

TBL_QUOTE = 'tblQuote'
SECRET_PERSON = 'SECRET_PERSON_NAME'

# C115264 chain from JOIN_MAP section 3: (line rec, 工編號碼, {category: (qty, item name)})
LINES = [
    ('recL1', 'C115264-1', {'外業': (10, '直接水準測量坡度14~19%'), '控制': (10, '地形檢查'), '圖資': (10, ''), '報告': (5, '工作安全評估(JSA)')}),
    ('recL2', 'C115264-1', {'外業': (50, '導線測量1/20000(2測回)'), '控制': (50, '點誌記(三支距)'), '圖資': (2, '空拍(無等高線)一般(田埂)'), '報告': (1, '職業安全計畫')}),
    ('recL3', 'C115264-2', {'外業': (5, '直接水準測量坡度5%~9%'), '控制': (20, '水準計算'), '圖資': (2, '點雲(刺點)一般斷面圖'), '報告': (1, '服務建議書(有公版)')}),
    ('recL4', 'C115264-3', {'報告': (1, '職業安全計畫')}),
]


class RawReader:
    def __init__(self, cases=(), work_orders=()):
        self.raw = {
            'case': {'name': '案件', 'status': 'ok', 'records': [
                {'record_id': key, 'fields': {'案件編號': code, '狀態': status, '預期營業額點數': 0.5775, '累計外業營業額點數': done}}
                for key, code, status, done in cases]},
            'field': {'name': '外業工作單', 'status': 'ok', 'records': [
                {'record_id': f'wo{i}', 'fields': {'工作單號': f'WO{i}', '案件編號': code, '出工日期': date, '最終營業額點數': points,
                                                  '檢核狀態': '待檢核', '營業額人員-明細': SECRET_PERSON}}
                for i, (code, date, points) in enumerate(work_orders)]}}

    def read(self):
        return self.raw


def contract_fields(code, spec):
    fields = {'工編號碼': code}
    for category, (qty, name) in spec.items():
        fields.update({category + '數量': qty, category + '工項': name})
    return fields


def chain_state(code='C115264', *, confirmation=True, lines=True, quotes=(('115588', 'C115264', '報價中'),), daily=(), finance=None):
    """The visible case of build_state() carrying the JOIN_MAP chain (confirmation, 4 lines, 12 fill items, derived plan)."""
    state, vis, hid = build_state()
    project = next(p for p in state['projects'] if p['id'] == vis)
    ids = [f'{B}|{CT}|recC1']
    records, conf_rows, line_rows, items = [], [], [], []
    if confirmation:
        row = conf('recC1', code, vis, 'Visible case')
        row['fields'] = {'工程名稱': 'Visible case', '合約總額': 918273, '狀態': '執行中', '案件已入帳': False}
        conf_rows.append(row)
        records.append(dict(base_token=B, table_id=CT, record_id='recC1', kind='confirmation', fields={'工程確認單編號': code}))
    if confirmation and lines:
        for rec, line_code, spec in LINES:
            c = contract(rec, 'recC1', vis, 'Line ' + rec)
            c['fields'] = contract_fields(line_code, spec)
            line_rows.append(c)
            records.append(dict(base_token=B, table_id=KT, record_id=rec, kind='contract', fields=c['fields']))
            ids.append(f'{B}|{KT}|{rec}')
            for category, (qty, name) in spec.items():
                if name:
                    n = len(items)
                    items.append(work(f'recW{n}', vis, rec) | {'category': category})
                    records.append(dict(base_token=B, table_id=WT, record_id=f'recW{n}', kind='reporting',
                                        fields={'工編號碼': line_code, '工項類別': category, '基準數量': qty, '填報工項': f'{line_code}|{category}|{name}'}))
                    ids.append(f'{B}|{WT}|recW{n}')
    state['source_confirmations'], state['contract_items'], state['source_work_items'] = conf_rows, line_rows, items
    state['source_work_items_status'] = {vis: dict(partial=False, truncated=False)}
    confs = {record_key(r): vis for r in records if r['kind'] == 'confirmation'}
    native = {record_key(r): vis for r in records if r['kind'] == 'contract'}
    state['derived_plan'] = build_projection(records, confs, native).plans if records else {}
    state['source_visible_record_ids'] = ids
    project.update(code=code, daily_reports=list(daily), source_records=[],
                   quotes=[dict(id=f'src-q{i}', quote_code=number, engineering_code=eng, source_url='https://x/q', amount=1,
                                fields=dict({'報價編號': number, '工程編號': eng, '狀態': status}, **(finance or {})))
                           for i, (number, eng, status) in enumerate(quotes)])
    return state, vis, hid


@pytest.fixture
def progress(http, request):
    app, client, seat, signin = http
    stores = []

    def run(state, vis, *, cases=(), work_orders=(), warm=True, uid='u-manager', store=True):
        seat(state)
        signin(uid)
        if store:
            reports = SnapshotStore(RawReader(cases, work_orders))
            stores.append(reports)
            app.state.reports = reports
            if warm:
                reports.get()
        return client.get(f'/api/projects/{vis}/progress')

    yield run, client, app
    for store in stores:
        store.close()


def stage(body, key):
    return next(s for s in body['stages'] if s['key'] == key)


def daily(department='外業組', points=0.25, date='2026-10-13', ident='d1'):
    return dict(id=ident, date=date, department=department, points=points, person=SECRET_PERSON, source_fields={'姓名': SECRET_PERSON},
                case_mapping_status='matched')


def test_c_prefixed_case_with_confirmation_and_lines(progress):
    run, _, _ = progress
    state, vis, _ = chain_state()
    response = run(state, vis, cases=[('recvsaz8kBOaj0', '115588', '報價中', None)])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['schema_version'] == 1 and body['project_id'] == vis
    assert body['identity']['code'] == 'C115264' and body['identity']['is_c_prefix'] is True
    assert body['identity']['confirmation'] == {'present': True, 'line_count': 4, 'fill_item_count': 12, 'source_status': '執行中'}
    assert body['identity']['quotes'] == [{'number': '115588', 'engineering_code': 'C115264', 'status': '報價中'}]
    for key in ('sales', 'pm', 'confirmation'):
        assert (stage(body, key)['state'], stage(body, key)['basis']) == ('done', 'rule')
    assert stage(body, 'sales')['evidence'][0] == {'label': '判斷', 'value': '工編以 C 開頭', 'tone': 'ok'}
    field = body['production']['field']
    assert field['planned'] == {'lines': 3, 'items': 3, 'qty': '65', 'needs_review': 0, 'basis': {'native': 0, 'derived': 3, 'ambiguous': 0, 'unlinked': 0}}
    assert [body['production'][k]['planned']['qty'] for k in ('control', 'mapping', 'report')] == ['80', '14', '8']
    assert {i['name']: (i['code'], i['planned_qty'], i['link_basis']) for i in field['items']}['導線測量1/20000(2測回)'] == ('C115264-1', '50', 'derived')
    assert field['actual'] == {'known': False, 'value': None, 'unit_note': None, 'reason': '尚無日報連結到此案件', 'source': None}
    assert field['work_orders'] == {'count': None, 'latest_date': None}
    assert (stage(body, 'field')['state'], stage(body, 'field')['basis']) == ('unknown', 'none')
    assert [stage(body, k)['state'] for k in ('billing', 'settlement')] == ['unknown', 'unknown']
    assert 'no_daily_linked' in {g['id'] for g in body['gaps']}


def test_numeric_code_with_confirmation_is_rule_done_without_c_prefix(progress):
    run, _, _ = progress
    state, vis, _ = chain_state(code='115552', quotes=())
    body = run(state, vis).json()
    assert body['identity']['is_c_prefix'] is False
    assert [(stage(body, k)['state'], stage(body, k)['basis']) for k in ('sales', 'pm', 'confirmation')] == [('done', 'rule')] * 3
    assert stage(body, 'sales')['evidence'][0]['value'] == '已有確認單與合約明細'


def test_case_without_confirmation_is_waiting_or_unknown(progress):
    run, _, _ = progress
    state, vis, _ = chain_state(code='115590', confirmation=False)
    body = run(state, vis).json()
    assert body['identity']['confirmation'] == {'present': False, 'line_count': 0, 'fill_item_count': 0, 'source_status': None}
    assert (stage(body, 'sales')['state'], stage(body, 'sales')['basis']) == ('unknown', 'none')
    assert [stage(body, k)['state'] for k in ('pm', 'confirmation', 'field', 'report')] == ['waiting'] * 4
    assert body['production']['field']['planned'] is None
    assert {'no_confirmation', 'plan_unavailable'} <= {g['id'] for g in body['gaps']}


def test_c_prefixed_case_without_confirmation_keeps_sales_done_only(progress):
    run, _, _ = progress
    state, vis, _ = chain_state(code='C115300', confirmation=False)
    body = run(state, vis).json()
    assert stage(body, 'sales')['state'] == 'done' and stage(body, 'pm')['state'] == 'waiting'


def test_v3_match_by_quote_number_and_report_rows(progress):
    run, _, _ = progress
    state, vis, _ = chain_state(code='C115238-01', quotes=(('115573', 'C115238-01', '報價中'),))
    body = run(state, vis, cases=[('recvsaz8kB86Jh', '115573', '未填', 0.25)], work_orders=[('115573', '2026-08-13', 0.25)]).json()
    assert body['identity']['v3_cases'] == [{'case_key': 'recvsaz8kB86Jh', 'case_code': '115573', 'status': '未填', 'match': 'quote_number'}]
    assert body['identity']['v3_ambiguous'] is False
    rows = body['production']['report_rows']
    assert len(rows) == 1 and rows[0]['case_key'] == 'recvsaz8kB86Jh' and rows[0]['dept'] == 'field' and rows[0]['week'] == '2026-08-10'
    assert (rows[0]['actual'], rows[0]['actual_days'], rows[0]['planned_days'], rows[0]['done_total'], rows[0]['status']) == (0.25, 1, 0, 0.25, '未填')
    assert body['production']['field']['actual'] == {'known': True, 'value': '0.25', 'unit_note': '營業額點數（v3 案件累計外業，未經驗收）',
                                                      'reason': None, 'source': 'v3_reports'}
    assert body['sources']['reports_status'] == 'ok' and body['sources']['reports_fetched_at']


def test_exact_code_match_wins_over_same_case_quote_number(progress):
    run, _, _ = progress
    state, vis, _ = chain_state(code='C115238-01', quotes=(('C115238-01', 'C115238-01', '報價中'),))
    body = run(state, vis, cases=[('recX', 'C115238-01', '未填', None)]).json()
    assert [(c['case_code'], c['match']) for c in body['identity']['v3_cases']] == [('C115238-01', 'code')]


def test_ambiguous_v3_lists_both_and_never_borrows_actuals(progress):
    run, _, _ = progress
    state, vis, _ = chain_state(code='C115236', quotes=(('115547', 'C115236', '報價中'),))
    body = run(state, vis, cases=[('recA', '115547', '報價中', 0.5), ('recB', 'C115236', '未填', 0.75)],
               work_orders=[('115547', '2026-08-13', 0.5)]).json()
    assert body['identity']['v3_ambiguous'] is True
    assert [(c['case_key'], c['match']) for c in body['identity']['v3_cases']] == [('recB', 'code'), ('recA', 'quote_number')]
    assert {r['case_key'] for r in body['production']['report_rows']} == {'recA'}
    assert body['production']['field']['actual']['known'] is False
    assert 'v3_ambiguous' in {g['id'] for g in body['gaps']}


def test_reports_snapshot_cold_returns_the_rest_with_a_gap(progress):
    run, _, _ = progress
    state, vis, _ = chain_state()
    body = run(state, vis, cases=[('recX', 'C115264', '未填', None)], warm=False).json()
    assert body['sources'] == {'source_synced_at': body['sources']['source_synced_at'], 'source_status': body['sources']['source_status'],
                               'reports_status': 'cold', 'reports_fetched_at': None, 'reports_stale': None}
    assert body['identity']['confirmation']['present'] is True and stage(body, 'sales')['state'] == 'done'
    assert body['identity']['v3_cases'] == [] and 'reports_cold' in {g['id'] for g in body['gaps']}


def test_cold_store_is_not_waited_on_and_missing_store_is_a_gap(progress):
    run, client, app = progress
    state, vis, _ = chain_state()

    class Never:
        def read(self):
            raise RuntimeError('boom')
    seat_response = run(state, vis, store=False)
    app.state.reports = SnapshotStore(Never())
    body = client.get(f'/api/projects/{vis}/progress').json()
    assert seat_response.status_code == 200
    assert body['sources']['reports_status'] == 'cold'
    assert 'reports_cold' in {g['id'] for g in body['gaps']}
    assert body['stages'][0]['state'] == 'done'
    app.state.reports.close()


def test_mapped_daily_row_produces_known_actual(progress):
    run, _, _ = progress
    state, vis, _ = chain_state(daily=[daily(points=0.25, date='2026-10-12'), daily(points=0.5, date='2026-10-13', ident='d2'), daily('控制組', None, ident='d3')])
    body = run(state, vis).json()
    field = body['production']['field']
    assert field['actual'] == {'known': True, 'value': '0.75', 'unit_note': '營業額點數（日報回報，未經驗收；非合約數量）', 'reason': None, 'source': 'v4_daily'}
    assert field['work_orders'] == {'count': 2, 'latest_date': '2026-10-13'}
    assert (stage(body, 'field')['state'], stage(body, 'field')['basis']) == ('active', 'source')
    control = body['production']['control']
    assert control['actual'] == {'known': False, 'value': None, 'unit_note': None, 'source': None, 'reason': '已有日報連結，但完成數量尚未投影'}
    assert control['work_orders']['count'] == 1
    mapping = body['production']['mapping']['actual']
    assert mapping['reason'] == '此案件的日報沒有歸屬到圖資'
    assert 'no_daily_linked' not in {g['id'] for g in body['gaps']}
    assert SECRET_PERSON not in json.dumps(body, ensure_ascii=False)


def test_finance_only_for_pm_and_manager_and_never_zero_for_blank(progress):
    run, _, _ = progress
    finance = {'累計已請款': '1,200', '可請款未請': 300, '案件可請款總額': '', '案件已入帳': False}
    state, vis, _ = chain_state(finance=finance)
    body = run(state, vis).json()
    assert body['finance']['restricted'] is False
    assert body['finance']['quotes'] == [{'number': '115588', 'invoiced_total': '1200', 'billable_unrequested': '300', 'billable_total': None,
                                          'received_total': None, 'received_date': None, 'case_received': None}]
    assert (stage(body, 'billing')['state'], stage(body, 'billing')['basis']) == ('active', 'source')
    assert stage(body, 'settlement')['state'] == 'unknown'
    member = run(state, vis, uid='u-field')
    assert member.status_code == 200
    restricted = member.json()
    assert restricted['finance']['restricted'] is True
    assert restricted['finance']['quotes'][0]['invoiced_total'] is None
    assert restricted['sources']['reports_status'] == 'restricted'
    assert '1200' not in member.text and '1,200' not in member.text
    assert {'finance_restricted', 'reports_restricted'} <= {g['id'] for g in restricted['gaps']}


def test_received_case_proves_billing_and_settlement(progress):
    run, _, _ = progress
    state, vis, _ = chain_state(finance={'案件已入帳': True, '入帳日期': '2026-09-30', '累計已入帳': 5})
    body = run(state, vis).json()
    assert [(stage(body, k)['state'], stage(body, k)['basis']) for k in ('billing', 'settlement')] == [('done', 'source')] * 2
    assert body['finance']['case_received'] is True and body['finance']['received_date'] == '2026-09-30'


def test_duplicate_quote_numbers_and_unlinked_items_are_gaps(progress):
    run, _, _ = progress
    state, vis, _ = chain_state(quotes=(('115588', 'C115264', '報價中'), ('115588', 'C115264', '報價中')))
    for item in state['contract_items']:
        item['fields']['外業工項'] = 'renamed'
    body = run(state, vis).json()
    ids = {g['id'] for g in body['gaps']}
    assert 'quotes_duplicated' in ids
    assert len(body['identity']['quotes']) == 2


def test_authorization_and_visibility_match_case_detail(progress):
    run, client, _ = progress
    state, vis, hid = chain_state()
    assert run(state, vis).status_code == 200
    forbidden, absent = client.get(f'/api/projects/{hid}/progress'), client.get('/api/projects/p-does-not-exist/progress')
    detail_forbidden, detail_absent = client.get(f'/api/case-detail/{hid}'), client.get('/api/case-detail/p-does-not-exist')
    assert forbidden.status_code == absent.status_code == detail_forbidden.status_code == detail_absent.status_code == 404
    assert forbidden.json() == absent.json() == detail_forbidden.json() == detail_absent.json()
    assert hid not in forbidden.text and 'HIDDEN' not in forbidden.text
    assert client.get(f'/api/projects/{vis}/progress?x=1').status_code == 422
    assert client.get('/api/projects/' + 'p' * 201 + '/progress').status_code == 422
    client.cookies.clear()
    assert client.get(f'/api/projects/{vis}/progress').status_code == 401


def test_response_carries_no_raw_source_fields_names_or_contract_totals(progress):
    run, _, _ = progress
    state, vis, _ = chain_state(daily=[daily()], finance={'備註': 'RAW_NOTE_SENTINEL'})
    response = run(state, vis, cases=[('recX', 'C115264', '未填', None)], work_orders=[('C115264', '2026-10-13', 0.25)])
    text = response.text
    assert 'source_fields' not in text and 'source_records' not in text and 'fields' not in response.json().keys()
    for sentinel in (SECRET_PERSON, 'RAW_NOTE_SENTINEL', '918273', 'HIDDEN_CASE_SENTINEL', 'recH1'):
        assert sentinel not in text
    assert response.headers['cache-control'] == 'no-store'


def test_nothing_is_mutated_by_a_read(progress):
    run, client, app = progress
    state, vis, _ = chain_state(daily=[daily()])
    run(state, vis)
    from .app import WorkspaceRow
    with app.state.sessions() as db:
        version = db.get(WorkspaceRow, WID).version
    first = client.get(f'/api/projects/{vis}/progress').json()
    assert client.get(f'/api/projects/{vis}/progress').json() == first
    with app.state.sessions() as db:
        assert db.get(WorkspaceRow, WID).version == version
