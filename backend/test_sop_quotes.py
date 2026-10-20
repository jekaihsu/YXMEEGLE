"""Quote register over a synthetic production workspace through the real app; never Lark or cloud data."""
import time
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from . import storage
from .app import AuthRow, BusinessRow, WorkspaceRow, create_app
from .models import PersonRow
from .policy import upgrade
from .seed import seed
from .sop_import.catalog import load_catalog, publish, stage
from .v4_sources import import_v4

CAPS = ['sop_task_read', 'sop_task_import', 'sop_task_work', 'sop_task_read_source']
WID = 'lark-quotes'


def quote_row(record_id, quote_no, project_id=None, **fields):
    identity = {'base_token': 'qbase', 'table_id': 'qtable', 'record_id': record_id}
    return {'id': f'qbase/qtable/{record_id}', 'source_identity': identity, 'source_kind': 'quote', 'source_missing': False,
            'source_url': f'https://example.invalid/{record_id}', 'project_id': project_id,
            'project_ids': [project_id] if project_id else [], 'code': quote_no, 'readonly': True,
            'fields': {'報價編號': quote_no, **fields}}


def harness(tmp_path, caps=None, **config):
    app = create_app({'DATABASE_URL': f'sqlite:///{tmp_path}/quotes.db', 'UPLOAD_DIR': str(tmp_path / 'files'),
                      'DEMO_MODE': 'false', 'APP_ENV': 'development', 'SESSION_SECRET': 'quotes-only' * 4,
                      'LARK_WORKER_ORGANIZATION': 'quotes', 'LARK_ALLOWED_TENANTS': 'quotes',
                      'SOP_TASK_WRITES_ENABLED': 'true', **config})
    state = upgrade(seed())
    state['environment'] = 'production'
    for p in state['projects']:
        p.update(source_kind='lark', case_visibility='excluded_history', execution_system='meegle')
    formal, hidden = state['projects'][:2]
    formal.update(case_visibility='source_reference', execution_system='pending',
                  source_records=[{'id': 'v4-confirmation', 'kind': 'confirmation', 'fields': {'工程確認單編號': 'C115236'}}])
    hidden['name'] = 'HIDDEN_CASE_SENTINEL'
    source = seed(True)
    import_v4(source, [{'kind': 'quote', 'base_token': 'qbase', 'table_id': 'qtable', 'record_id': rid,
                        'fields': {'報價編號': '115600', '工程名稱': '雲林布袋戲館', '此案確認單': []}} for rid in ('recDupA', 'recDupB')])
    intake, twin = sorted(source['projects'], key=lambda p: p['source_identity']['record_id'])
    for case in (intake, twin):
        case.update(case_visibility='source_reference', execution_system='pending')
        state['projects'].append(case)
    rows = [
        quote_row('recFormal', '115236', formal['id'], 工程編號='C115236', 工程名稱='桃園捷運綠線控制點測量',
                  行號單位='桃園軌道工程處', 報價日期=1786291200000, 報價期限=1787500800000, 回傳單日期=1789574400000,
                  **{'契約價格(未稅)': 109590, '狀態': '成案', '報價負責人': [{'id': 'ou_1', 'name': '吳柏頤', 'email': 'private'}],
                     '案件負責人': [{'id': 'ou_2', 'name': '林育寬'}]}),
        quote_row('recDupA', '115600', intake['id'], 工程名稱='雲林布袋戲館', 行號單位='雲林縣政府',
                  報價日期='2026-10-05', 報價期限='2026-11-05'),
        quote_row('recDupB', '115600', twin['id'], 回傳單日期='2026-10-15', **{'契約價格(未稅)': 0}),
        quote_row('recUnadmitted', '115700', None, 工程名稱='HIDDEN_QUOTE_SENTINEL'),
        quote_row('recHiddenCase', '115800', hidden['id'], 工程名稱='HIDDEN_CASE_SENTINEL'),
        quote_row('recShell', '', None),
        dict(quote_row('recDeleted', '115900', None, 工程名稱='DELETED_SENTINEL'), source_missing=True),
    ]
    state['source_quotes'] = rows
    state['source_visible_record_ids'] = sorted('|'.join(r['source_identity'].values()) for r in rows
                                                if r['source_identity']['record_id'] != 'recUnadmitted')
    with app.state.sessions.begin() as db:
        row = WorkspaceRow(id=WID, version=state['version'], data={})
        db.add(row)
        db.flush()
        row.data = storage.save(db, BusinessRow, WID, state)
        db.add(AuthRow(id='quotes-session', data={'wid': WID, 'expires': time.time() + 3600}))
        for user in state['users']:
            granted = (caps or {'u-manager': CAPS}).get(user['id'], [])
            db.add(PersonRow(organization_id=WID, person_id=user['id'], data={**deepcopy(user), 'capabilities': granted}))
        version = stage(db, WID, 'plumb-v0.2-1', load_catalog(), source_verified=True)
        publish(db, version, 'u-manager', 100)
    client = TestClient(app)

    def signin(ident):
        client.cookies.set('meegle_session', app.state.signer.dumps({'mode': 'lark', 'sid': 'quotes-session', 'wid': WID, 'uid': ident}))
    signin('u-manager')
    return app, client, signin, {'formal': formal['id'], 'intake': intake['id'], 'twin': twin['id'], 'version': version.id}


@pytest.fixture
def quotes_http(tmp_path):
    built = harness(tmp_path)
    yield built
    built[0].state.engine.dispose()


def get(client, path, status=200):
    response = client.get(path)
    assert response.status_code == status, response.text
    return response.json()


def test_register_merges_rows_by_quote_number_and_hides_what_the_viewer_cannot_see(quotes_http):
    app, client, signin, ids = quotes_http
    body = get(client, '/api/quotes')
    assert (body['total'], body['offset'], body['limit'], body['amount_restricted']) == (2, 0, 30, False)
    merged, formal = body['items']
    assert merged == {'origin': 'source', 'quote_no': '115600', 'local_reference': None, 'engineering_no': None, 'name': '雲林布袋戲館',
                      'client': '雲林縣政府', 'quoted_on': '2026-10-05', 'quote_deadline': '2026-11-05',
                      'contract_amount': 0.0, 'amount_restricted': False, 'quote_owners': [], 'pm_names': [], 'pm_id': None,
                      'status': None, 'stage_label': None, 'stage': 'returned', 'project_id': min(ids['intake'], ids['twin']),
                      'project_ids': sorted([ids['intake'], ids['twin']]), 'source_rows': 2, 'duplicated': True, 'sop_counts': None}
    assert {k: formal[k] for k in ('quote_no', 'engineering_no', 'contract_amount', 'quote_owners', 'pm_names', 'status',
                                   'stage', 'project_id', 'quoted_on')} == {
        'quote_no': '115236', 'engineering_no': 'C115236', 'contract_amount': 109590.0, 'quote_owners': ['吳柏頤'],
        'pm_names': ['林育寬'], 'status': '成案', 'stage': 'confirmation', 'project_id': ids['formal'], 'quoted_on': '2026-08-10'}
    text = client.get('/api/quotes').text
    assert not any(s in text for s in ('HIDDEN_QUOTE_SENTINEL', 'HIDDEN_CASE_SENTINEL', 'DELETED_SENTINEL', 'private'))
    assert get(client, '/api/quotes/115700', 404)['code'] == 'quote_not_found'
    assert get(client, '/api/quotes/115800', 404)['code'] == 'quote_not_found'


def test_amounts_follow_the_progress_gate(quotes_http):
    app, client, signin, ids = quotes_http
    signin('u-field')
    body = get(client, '/api/quotes')
    assert body['amount_restricted'] is True
    assert [(i['quote_no'], i['contract_amount'], i['amount_restricted']) for i in body['items']] == [
        ('115600', None, True), ('115236', None, True)]
    assert get(client, '/api/quotes/115236')['contract_amount'] is None


def test_filter_search_and_pagination(quotes_http):
    app, client, signin, ids = quotes_http
    assert [i['quote_no'] for i in get(client, '/api/quotes?stage=returned')['items']] == ['115600']
    assert get(client, '/api/quotes?stage=won', 422)['code'] == 'invalid_request'
    assert [i['quote_no'] for i in get(client, '/api/quotes?q=桃園軌道')['items']] == ['115236']
    assert [i['quote_no'] for i in get(client, '/api/quotes?q=布袋戲')['items']] == ['115600']
    assert [i['quote_no'] for i in get(client, '/api/quotes?q=115236')['items']] == ['115236']
    page = get(client, '/api/quotes?offset=1&limit=1')
    assert (page['total'], [i['quote_no'] for i in page['items']]) == (2, ['115236'])
    assert get(client, '/api/quotes?limit=101', 422)['code'] == 'invalid_request'


def test_detail_carries_merged_facts_records_and_sop_counts(quotes_http):
    app, client, signin, ids = quotes_http
    url = f"/api/projects/{ids['intake']}"
    plan = client.post(url + '/sop-import/preview', json={'template_version_id': ids['version'], 'node_keys': ['sales']})
    assert plan.status_code == 200, plan.text
    assert client.post(url + '/sop-import/apply', json={'preview_id': plan.json()['preview_id'], 'request_id': 'q'}).status_code == 200
    detail = get(client, '/api/quotes/115600')
    assert detail['sop_counts'] == {'done': 0, 'total': 9, 'unresolved': 0, 'not_applicable': 0, 'archived': 0}
    assert [r['id'] for r in detail['records']] == ['qbase/qtable/recDupA', 'qbase/qtable/recDupB']
    assert {k: detail['facts'][k] for k in ('quote_nos', 'source_rows', 'duplicated', 'returned_date', 'price_positive')} == {
        'quote_nos': ['115600'], 'source_rows': 2, 'duplicated': True, 'returned_date': '2026-10-15', 'price_positive': False}
    assert get(client, f"{url}/sop-tasks")['stage'] == 'returned'


def test_quote_pipeline_covers_duplicates_placeholders_and_blank_shells():
    from .sources import import_sources, source_id
    from .source_case_policy import apply_source_reference_policy, filter_visible_cases
    from .sop_import.quotes import register

    records = [
        {'kind': 'quote', 'base_token': 'b', 'table_id': 'quotes', 'record_id': rid, 'fields': fields}
        for rid, fields in [
            ('recA', {'報價編號': '115701', '工程名稱': 'Intake'}),
            ('recB', {'報價編號': '115701', '工程編號': '報編115701'}),
            ('recC', {'報價編號': '115702', '此案確認單': [{'record_id': 'recMissing'}]}),
            ('recBlank', {}),
            ('recFormal', {'報價編號': '115703', '此案確認單': [{'record_id': 'recConfirmation'}]}),
        ]
    ] + [{'kind': 'confirmation', 'base_token': 'b', 'table_id': 'confirmations',
          'record_id': 'recConfirmation', 'fields': {'工程確認單編號': 'C115703'}}]
    state = seed(True)
    state['environment'] = 'production'
    import_sources(state, records)
    apply_source_reference_policy(state, {'records': records}, {'id': 'scratch', 'name': 'Scratch'})
    before = {source_id(p['source_identity']): p['id'] for p in state['projects']}
    import_sources(state, records)
    assert before == {source_id(p['source_identity']): p['id'] for p in state['projects']}
    assert len(state['projects']) == 5
    blank = next(p for p in state['projects'] if p['source_identity']['record_id'] == 'recBlank')
    assert blank['case_type'] == 'intake'
    filter_visible_cases(state)
    entries = {q['quote_no']: q for q in register(state, today='2026-10-20', amounts=True)}
    assert set(entries) == {'115701', '115702', '115703'}
    assert len(entries['115701']['project_ids']) == 2
    assert entries['115702']['project_id'] == before[source_id(records[2])]
    assert all(q['project_id'] for q in entries.values())
    projects = {p['id']: p for p in state['projects']}
    assert projects[entries['115702']['project_id']]['intake_status'] == 'unresolved_confirmation'
    assert projects[entries['115703']['project_id']]['case_type'] == 'formal'


def test_orphan_quote_is_withheld_even_when_its_source_identity_is_admitted(quotes_http):
    app, client, signin, ids = quotes_http
    with app.state.sessions.begin() as db:
        row = db.get(WorkspaceRow, WID)
        state = storage.load(db, BusinessRow, row)
        state['source_visible_record_ids'].append('qbase|qtable|recUnadmitted')
        row.data = storage.save(db, BusinessRow, WID, state)
    assert get(client, '/api/quotes/115700', 404)['code'] == 'quote_not_found'
    assert get(client, '/api/quotes?q=115700')['total'] == 0


def test_demo_orphan_quote_has_no_case_or_tasks(tmp_path):
    app = create_app({'DATABASE_URL': f'sqlite:///{tmp_path}/demo.db', 'UPLOAD_DIR': str(tmp_path / 'files'),
                      'DEMO_MODE': 'true', 'APP_ENV': 'development', 'SESSION_SECRET': 'demo-quotes' * 4})
    with TestClient(app) as client:
        client.get('/api/session')
        with app.state.sessions.begin() as db:
            row = db.scalar(select(WorkspaceRow))
            state = storage.load(db, BusinessRow, row)
            state['source_quotes'] = [quote_row('recOrphan', '115700', 工程名稱='未納入案件')]
            row.data = storage.save(db, BusinessRow, row.id, state)
        orphan = get(client, '/api/quotes/115700')
        assert (orphan['project_id'], orphan['project_ids'], orphan['sop_counts']) == (None, [], None)
    app.state.engine.dispose()
