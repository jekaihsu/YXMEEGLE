import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from .live_read.token_cache import TenantTokenCache
from .models import AuditRow, Base, Receipt
from .node_assignment.routes import register

BASE = 'H7W6b0PFWaVF1BsgqXJj3pQ9pXb'
NODES, TASKS, PEOPLE = 'tblcPZPmezkyeVb7', 'tblsoyGcC6K5AipF', 'tblfaCO2xPUNptQH'
CODE = 'A115001-01'
T0 = 1_790_000_000.0  # 2026-09-21T22:13:20+08:00
SCHEMA = {
    NODES: [('指派鍵', 1), ('確認單編號', 1), ('節點', 3), ('負責人', 11), ('指派方式', 3), ('指派人', 11), ('狀態', 3),
            ('進度', 2), ('開始時間', 5), ('完成時間', 5), ('核准人', 11), ('核准時間', 5), ('退回原因', 1),
            ('工程確認單', 18), ('案件總覽', 18), ('任務', 21)],
    TASKS: [('標題', 1), ('節點指派', 21), ('內容', 1), ('負責人', 11), ('指派人', 11), ('部門', 3), ('截止日', 5),
            ('狀態', 3), ('完成時間', 5), ('建立時間', 1001)],
    PEOPLE: [('姓名', 1), ('所屬組別', 4), ('職級', 3), ('在職', 7), ('Lark帳號', 11), ('同步_OpenID', 1)],
}
TEXT = {'指派鍵', '確認單編號', '退回原因', '標題', '內容', '姓名'}
STAFF = [('ou_member', '王外業', ['外業'], '組員', True), ('ou_depth', '陳水深', ['水深B'], '組員', True),
         ('ou_fm', '林經理', ['水深A', '外業'], '經理', True), ('ou_om', '張經理', ['行政'], '經理', True),
         ('ou_vp', '吳副總', [], '副總', True), ('ou_gone', '李離職', ['外業'], '經理', False),
         ('ou_sales', '周業務', ['業務'], '組員', True), ('ou_sm', '蔡經理', ['業務'], '經理', True)]
NAMES = {ident: name for ident, name, *_ in STAFF}


class FakeBitable:
    """A small in-memory Bitable: real search, create, update, batch_get and reverse links."""

    def __init__(self):
        self.tables = {NODES: {}, TASKS: {}, PEOPLE: {}}
        self.requests, self.faults, self.tokens, self.seq = [], [], {}, 0
        for ident, name, groups, rank, employed in STAFF:
            self.add(PEOPLE, {'姓名': name, '所屬組別': groups, '職級': rank, '在職': employed,
                              'Lark帳號': [{'id': ident}], '同步_OpenID': ident})

    def add(self, table, fields):
        self.seq += 1
        rid = f'rec{table[-4:]}{self.seq:04d}'
        stored = {k: v for k, v in fields.items() if v is not None}
        if table == TASKS:
            stored['建立時間'] = int(T0 * 1000) + self.seq
        self.tables[table][rid] = stored
        return rid

    def rows(self, table, **match):
        return {rid: f for rid, f in self.tables[table].items() if all(f.get(k) == v for k, v in match.items())}

    def fault(self, method, suffix, respond, times=1):
        self.faults.append([method, suffix, respond, times])

    def writes(self):
        return [(m, p) for m, p in self.requests if m in ('PUT',) or (m == 'POST' and p.endswith('/records'))]

    def render(self, table, rid, style):
        fields = {}
        for name, value in self.tables[table][rid].items():
            kind = dict(SCHEMA[table])[name]
            if kind == 11:
                value = [{'id': v['id'], 'name': NAMES.get(v['id'], '')} for v in value]
            elif kind in (18, 21):
                value = {'link_record_ids': value} if style == 'search' else [{'record_ids': value, 'text': '', 'type': 'text'}]
            elif name in TEXT and style == 'search':
                value = [{'text': value, 'type': 'text'}]
            fields[name] = value
        if table == NODES:
            linked = [t for t, f in self.tables[TASKS].items() if rid in f.get('節點指派', [])]
            if linked:
                fields['任務'] = {'link_record_ids': linked} if style == 'search' else [{'record_ids': linked, 'type': 'text'}]
        return {'record_id': rid, 'fields': fields}

    def __call__(self, request):
        path, method = request.url.path, request.method
        self.requests.append((method, path))
        for fault in list(self.faults):
            if fault[0] == method and path.endswith(fault[1]):
                fault[3] -= 1
                if fault[3] == 0:
                    self.faults.remove(fault)
                response = fault[2](request)
                if response is not None:
                    return response
        if path.endswith('/tenant_access_token/internal'):
            return httpx.Response(200, json={'code': 0, 'tenant_access_token': 't-synthetic', 'expire': 7200})
        parts = path.split('/')
        assert parts[:6] == ['', 'open-apis', 'bitable', 'v1', 'apps', BASE], path
        table, rest = parts[7], parts[8:]
        body = json.loads(request.content) if request.content else {}
        if rest == ['fields']:
            items = [{'field_id': f'fld{i}', 'field_name': n, 'type': t} for i, (n, t) in enumerate(SCHEMA[table])]
            return ok({'items': items, 'has_more': False, 'total': len(items)})
        if rest == ['records'] and method == 'GET':
            names = json.loads(request.url.params['field_names'])
            items = [{'record_id': rid, 'fields': {k: v for k, v in self.render(table, rid, 'get')['fields'].items() if k in names}}
                     for rid in self.tables[table]]
            return ok({'items': items, 'has_more': False, 'total': len(items)})
        if rest == ['records', 'search']:
            conditions = body['filter']['conditions']
            test = any if body['filter']['conjunction'] == 'or' else all
            hits = [self.render(table, rid, 'search') for rid, f in self.tables[table].items()
                    if test(f.get(c['field_name']) == c['value'][0] for c in conditions)]
            return ok({'items': hits, 'has_more': False, 'total': len(hits)} if hits else {'has_more': False, 'total': 0})
        if rest == ['records', 'batch_get']:
            ids = body['record_ids']
            return ok({'records': [self.render(table, rid, 'get') for rid in ids if rid in self.tables[table]],
                       'absent_record_ids': [rid for rid in ids if rid not in self.tables[table]]})
        if rest == ['records'] and method == 'POST':
            token = request.url.params['client_token']
            if token not in self.tokens:
                self.tokens[token] = self.add(table, body['fields'])
            return ok({'record': self.render(table, self.tokens[token], 'get')})
        if len(rest) == 2 and method == 'GET':
            if rest[1] not in self.tables[table]:
                return httpx.Response(200, json={'code': 1254043, 'msg': 'RecordIdNotFound'})
            return ok({'record': self.render(table, rest[1], 'get')})
        if len(rest) == 2 and method == 'PUT':
            stored = self.tables[table][rest[1]]
            for name, value in body['fields'].items():
                if value is None:
                    stored.pop(name, None)
                else:
                    stored[name] = value
            return ok({'record': self.render(table, rest[1], 'get')})
        raise AssertionError((method, path))


def ok(data):
    return httpx.Response(200, json={'code': 0, 'msg': 'success', 'data': data})


class NoBucket:
    def acquire(self, deadline):
        pass

    def penalize(self, until):
        pass


def project(code=CODE, skipped=()):
    return {'id': 'p1', 'code': code, 'case_type': 'formal',
            'nodes': [{'id': f'p1-{k}', 'key': k, 'status': 'approved_skipped' if k in skipped else 'pending'}
                      for k in ('sales', 'pm', 'confirmation', 'field', 'control', 'mapping', 'report', 'pricing', 'settlement')],
            'source_records': [{'id': 'src-1', 'kind': 'confirmation',
                                'url': f'https://x.larksuite.com/base/{BASE}?table=tblmSQrcCs9vPQZx&record=recCONF1'}]}


@pytest.fixture
def h():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    fake = FakeBitable()
    cfg = {'NODE_ASSIGNMENT_ENABLED': 'true', 'LARK_WORKER_IDENTITY': 'application', 'LARK_APP_ID': 'app-na',
           'LARK_APP_SECRET': 'synthetic', 'LARK_WORKER_ORGANIZATION': 'company'}
    clock = [T0]
    state = {'environment': 'production', 'settings': {'external_enabled': True}}
    case = {'project': project()}
    who = ['ou_member']
    user_fields = {}

    def identity(_request):
        return {'mode': 'lark', 'wid': 'lark-company'}, {'id': who[0], 'active': True, **user_fields}

    def load_case(_data, _user, project_id):
        assert project_id == 'p1'
        return state, case['project']

    def build(overrides=None):
        app = FastAPI()
        register(app, identity=identity, load_case=load_case, sessions=sessions, receipt_model=Receipt,
                 audit_model=AuditRow, cfg={**cfg, **(overrides or {})},
                 skipped_nodes=lambda _s, _p, node: node.get('status') == 'approved_skipped',
                 transport=httpx.MockTransport(fake), clock=lambda: clock[0],
                 client_options={'token_cache': TenantTokenCache(), 'bucket': NoBucket(), 'sleep': lambda _s: None})
        return TestClient(app)

    def audits():
        with sessions() as db:
            return [(r.action, r.actor_id, r.data) for r in db.scalars(select(AuditRow).order_by(AuditRow.created_at))]

    yield SimpleNamespace(client=build(), build=build, fake=fake, clock=clock, state=state, case=case, who=who,
                          audits=audits, user_fields=user_fields)
    engine.dispose()


URL = '/api/projects/p1/node-assignments'


def act(h, who, path, body=None, method='post'):
    h.who[0] = who
    return getattr(h.client, method)(URL + path, json=body)


def view(h, who='ou_member', key=None):
    h.who[0] = who
    response = h.client.get(URL + (f'/nodes/{key}' if key else ''))
    assert response.status_code == 200, response.text
    return response.json()


def node(body, key):
    return next(n for n in body['nodes'] if n['key'] == key)


def test_flag_off_answers_404_on_every_route_without_touching_lark(h):
    client = h.build({'NODE_ASSIGNMENT_ENABLED': 'false'})
    responses = [client.get(URL), client.get(URL + '/nodes/sales'),
                 client.post(URL + '/nodes/sales/claim', json={'request_id': 'r1'}),
                 client.post(URL + '/nodes/sales/tasks', json={'request_id': 'r2', 'title': 'x'}),
                 client.patch(URL + '/nodes/sales/tasks/rec1', json={'request_id': 'r3'})]
    assert [(r.status_code, r.json()['code']) for r in responses] == [(404, 'disabled')] * 5
    assert h.fake.requests == []


def test_empty_case_overview_is_derived_without_creating_rows(h):
    body = view(h)
    assert body['summary'] == {'done': 0, 'total': 9, 'current_node': 'sales'}
    assert [n['derived_status'] for n in body['nodes']] == ['待處理'] + ['未開始'] * 8
    assert node(body, 'field')['record_id'] is None and node(body, 'field')['status'] is None
    assert body['can']['field'] == {'claim': True, 'assign': False, 'complete': False, 'approve': False,
                                    'reject': False, 'create_task': True}
    assert body['can']['sales'] == {'claim': False, 'assign': False, 'complete': False, 'approve': False,
                                    'reject': False, 'create_task': False}
    assert (body['stale'], body['writes_enabled'], body['roster']) == (False, True, {'available': True, 'stale': False})
    assert h.fake.writes() == []


def test_claim_lazily_creates_exactly_one_row_with_the_workflow_key(h):
    response = act(h, 'ou_sales', '/nodes/sales/claim', {'request_id': 'claim-1', 'expected_revision': None})
    assert response.status_code == 200, response.text
    rows = h.fake.rows(NODES)
    assert len(rows) == 1
    (rid, fields), = rows.items()
    assert fields == {'指派鍵': 'A115001-01|業務', '確認單編號': 'A115001-01', '節點': '業務', '狀態': '待處理',
                      '工程確認單': ['recCONF1'], '負責人': [{'id': 'ou_sales'}], '指派方式': '自行認領',
                      '指派人': [{'id': 'ou_sales'}], '進度': 0.0}
    result = response.json()['node']
    assert (result['record_id'], result['owners'], result['assignment_method']) == (
        rid, [{'open_id': 'ou_sales', 'name': '周業務'}], '自行認領')
    again = act(h, 'ou_sm', '/nodes/sales/claim', {'request_id': 'claim-2', 'expected_revision': result['revision']})
    assert (again.status_code, again.json()['code']) == (409, 'illegal_transition')
    assert len(h.fake.rows(NODES)) == 1


def test_claim_reuses_the_row_created_by_the_lark_workflow(h):
    rid = h.fake.add(NODES, {'指派鍵': 'A115001-01|外業', '確認單編號': CODE, '節點': '外業', '狀態': '未開始'})
    revision = node(view(h), 'field')['revision']
    response = act(h, 'ou_depth', '/nodes/field/claim', {'request_id': 'c1', 'expected_revision': revision})
    assert response.status_code == 200, response.text
    assert list(h.fake.rows(NODES)) == [rid]
    assert h.fake.tables[NODES][rid]['負責人'] == [{'id': 'ou_depth'}]


def test_a_duplicate_created_during_lazy_creation_is_reported_not_picked(h):
    def racing_workflow(request):
        h.fake.add(NODES, {'指派鍵': 'A115001-01|業務', '確認單編號': CODE, '節點': '業務', '狀態': '待處理'})
    h.fake.fault('POST', f'{NODES}/records', racing_workflow)
    response = act(h, 'ou_sales', '/nodes/sales/claim', {'request_id': 'race'})
    body = response.json()
    assert (response.status_code, body['code']) == (409, 'duplicate_assignment_key')
    assert sorted(body['record_ids']) == sorted(h.fake.rows(NODES))
    assert len(body['record_ids']) == 2
    assert [m for m, p in h.fake.writes() if m == 'PUT'] == []
    assert node(view(h), 'sales')['warnings'] == ['duplicate_assignment_key']
    assert view(h)['can']['sales']['claim'] is False


def test_an_uncertain_create_is_resolved_by_search_and_never_resent(h):
    def lost_response(request):
        h.fake.add(NODES, json.loads(request.content)['fields'])
        return httpx.Response(504, text='gateway timeout')
    h.fake.fault('POST', f'{NODES}/records', lost_response)
    response = act(h, 'ou_sales', '/nodes/sales/claim', {'request_id': 'lost'})
    assert response.status_code == 200, response.text
    assert len(h.fake.rows(NODES)) == 1
    assert [p for m, p in h.fake.requests if m == 'POST' and p.endswith(f'{NODES}/records')] == [
        f'/open-apis/bitable/v1/apps/{BASE}/tables/{NODES}/records']


def test_replay_returns_the_same_result_and_a_different_body_is_rejected(h):
    first = act(h, 'ou_sales', '/nodes/sales/claim', {'request_id': 'same'})
    writes = len(h.fake.writes())
    replay = act(h, 'ou_sales', '/nodes/sales/claim', {'request_id': 'same'})
    assert replay.status_code == 200 and replay.json() == first.json()
    assert replay.headers['idempotent-replayed'] == 'true'
    assert len(h.fake.writes()) == writes
    other = act(h, 'ou_sales', '/nodes/sales/claim', {'request_id': 'same', 'expected_revision': '0' * 16})
    assert (other.status_code, other.json()['code']) == (409, 'idempotency_conflict')


def test_two_managers_on_the_same_revision_cannot_both_win(h):
    revision = node(view(h, 'ou_fm'), 'field')['revision']
    first = act(h, 'ou_fm', '/nodes/field/assign', {'request_id': 'a', 'expected_revision': revision,
                                                    'owner_open_ids': ['ou_member']})
    assert first.status_code == 200, first.text
    second = act(h, 'ou_vp', '/nodes/field/assign', {'request_id': 'b', 'expected_revision': revision,
                                                     'owner_open_ids': ['ou_depth']})
    body = second.json()
    assert (second.status_code, body['code']) == (409, 'revision_conflict')
    assert body['current_revision'] == first.json()['node']['revision']
    (fields,) = h.fake.rows(NODES).values()
    assert fields['負責人'] == [{'id': 'ou_member'}] and fields['指派人'] == [{'id': 'ou_fm'}]


def test_concurrent_assignments_are_serialized_and_one_conflicts(h):
    rid = h.fake.add(NODES, {'指派鍵': 'A115001-01|外業', '確認單編號': CODE, '節點': '外業', '狀態': '未開始'})
    revision = node(view(h, 'ou_fm'), 'field')['revision']
    h.who[0] = 'ou_fm'

    def assign(owner):
        return h.client.post(URL + '/nodes/field/assign', json={'request_id': 'r-' + owner, 'expected_revision': revision,
                                                                'owner_open_ids': [owner]})
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(assign, ['ou_member', 'ou_depth']))
    assert sorted(r.status_code for r in results) == [200, 409]
    winner = next(r for r in results if r.status_code == 200).json()['node']['owners'][0]['open_id']
    assert h.fake.tables[NODES][rid]['負責人'] == [{'id': winner}]


def test_readback_mismatch_keeps_the_request_pending_and_a_replay_reconciles(h):
    act(h, 'ou_fm', '/nodes/field/assign', {'request_id': 'seed', 'owner_open_ids': ['ou_member']})
    revision = node(view(h, 'ou_fm'), 'field')['revision']
    h.fake.fault('PUT', '', lambda request: ok({'record': {}}))
    body = {'request_id': 'mismatch', 'expected_revision': revision, 'owner_open_ids': ['ou_depth']}
    failed = act(h, 'ou_fm', '/nodes/field/assign', body)
    assert (failed.status_code, failed.json()['code'], failed.json()['fields']) == (409, 'readback_mismatch', ['負責人'])
    (fields,) = h.fake.rows(NODES).values()
    assert fields['負責人'] == [{'id': 'ou_member'}]
    resumed = act(h, 'ou_fm', '/nodes/field/assign', body)
    assert resumed.status_code == 200, resumed.text
    assert fields['負責人'] == [{'id': 'ou_depth'}]
    assert [a[0] for a in h.audits()][-2:] == ['node_assignment.assign', 'node_assignment.assign']
    assert [a[2]['result'] for a in h.audits()][-2:] == ['failed', 'success']


def test_pending_write_overtaken_by_another_edit_becomes_a_stable_conflict(h):
    act(h, 'ou_fm', '/nodes/field/assign', {'request_id': 'seed', 'owner_open_ids': ['ou_member']})
    revision = node(view(h, 'ou_fm'), 'field')['revision']
    h.fake.fault('PUT', '', lambda request: httpx.Response(500, json={'code': 1}))
    body = {'request_id': 'unknown', 'expected_revision': revision, 'owner_open_ids': ['ou_depth']}
    failed = act(h, 'ou_fm', '/nodes/field/assign', body)
    assert (failed.status_code, failed.json()['code']) == (502, 'outcome_unknown')
    (fields,) = h.fake.rows(NODES).values()
    fields['負責人'] = [{'id': 'ou_fm'}]
    first = act(h, 'ou_fm', '/nodes/field/assign', body)
    second = act(h, 'ou_fm', '/nodes/field/assign', body)
    assert (first.status_code, first.json()['code']) == (409, 'revision_conflict')
    assert second.json() == first.json() and fields['負責人'] == [{'id': 'ou_fm'}]


@pytest.mark.parametrize('code,status,expected_scopes', [
    (91403, 403, ['bitable:app:readonly']),
    (1254302, 200, ['bitable:app:readonly']),
    (99991672, 400, ['bitable:app:readonly', 'bitable:app']),
])
def test_lark_permission_errors_map_to_lark_permission(h, code, status, expected_scopes):
    payload = {'code': code, 'msg': 'denied'}
    if code == 99991672:
        payload['error'] = {'permission_violations': [{'subject': 'bitable:app:readonly'}, {'subject': 'bitable:app'}]}
    h.fake.fault('POST', '/records/search', lambda request: httpx.Response(status, json=payload))
    h.who[0] = 'ou_member'
    response = h.client.get(URL)
    assert response.status_code == 502
    assert response.json() == {'detail': 'Lark 應用缺少多維表格權限或未獲此 Base 授權，請管理員於 Lark 後台補齊',
                               'code': 'lark_permission', 'lark_code': code, 'missing_scopes': sorted(expected_scopes)}
    assert 't-synthetic' not in response.text


def test_write_permission_error_maps_and_drops_the_pending_receipt(h):
    h.fake.fault('PUT', '', lambda request: httpx.Response(403, json={'code': 1254302, 'msg': 'NoPermission'}))
    failed = act(h, 'ou_sales', '/nodes/sales/claim', {'request_id': 'perm'})
    assert (failed.status_code, failed.json()['code'], failed.json()['missing_scopes']) == (502, 'lark_permission', ['bitable:app'])
    retried = act(h, 'ou_sales', '/nodes/sales/claim', {'request_id': 'perm'})
    assert retried.status_code == 200, retried.text


def test_reads_serve_stale_data_on_lark_failure_then_fail_clearly(h):
    act(h, 'ou_sales', '/nodes/sales/claim', {'request_id': 'seed'})
    h.clock[0] += 61
    h.fake.fault('POST', '/records/search', lambda request: httpx.Response(503, text='down'), times=3)
    stale = view(h)
    assert (stale['stale'], stale['stale_reason']) == (True, 'refreshing')
    assert node(stale, 'sales')['owners'] == [{'open_id': 'ou_sales', 'name': '周業務'}]
    h.clock[0] += 1000
    h.fake.fault('POST', '/records/search', lambda request: httpx.Response(503, text='down'), times=3)
    h.who[0] = 'ou_member'
    failed = h.client.get(URL)
    assert (failed.status_code, failed.json()['code']) == (503, 'lark_unavailable')


def test_incomplete_pagination_is_never_shown_as_complete(h):
    h.fake.fault('POST', '/records/search', lambda request: ok({'items': [], 'has_more': True, 'page_token': 'p1'}), times=2)
    h.who[0] = 'ou_member'
    response = h.client.get(URL)
    assert (response.status_code, response.json()['code']) == (502, 'lark_error')


def test_permission_matrix_through_the_api(h):
    assign = lambda who, owners, rid: act(h, who, '/nodes/field/assign', {'request_id': rid, 'owner_open_ids': owners})
    assert assign('ou_om', ['ou_member'], 'x1').json()['code'] == 'forbidden'
    assert assign('ou_gone', ['ou_member'], 'x2').json()['code'] == 'forbidden'
    assert act(h, 'ou_gone', '/nodes/field/claim', {'request_id': 'x3'}).json()['code'] == 'forbidden'
    invalid = assign('ou_fm', ['ou_om'], 'x4')
    assert (invalid.status_code, invalid.json()['detail']) == (422, '負責人必須是本節點所屬組別的在職同仁')
    assert assign('ou_fm', ['ou_depth', 'ou_member'], 'x5').status_code == 200
    revision = node(view(h), 'field')['revision']
    vp = act(h, 'ou_vp', '/nodes/field/assign', {'request_id': 'x6', 'owner_open_ids': ['ou_member'],
                                                 'expected_revision': revision})
    assert vp.status_code == 200, vp.text
    denied = [a for a in h.audits() if a[2]['result'] == 'denied']
    assert [(a[0], a[1], a[2]['request_id'], a[2]['project_id']) for a in denied] == [
        ('node_assignment.assign', 'ou_om', 'x1', 'p1'), ('node_assignment.assign', 'ou_gone', 'x2', 'p1'),
        ('node_assignment.claim', 'ou_gone', 'x3', 'p1')]
    assert h.fake.writes()[-1][0] == 'PUT'


def test_admin_override_follows_the_company_admin_business_grant(h, monkeypatch):
    from .node_assignment import service
    monkeypatch.setattr(service, 'can_business_override', lambda user: user['id'] == 'ou_admin')
    response = act(h, 'ou_admin', '/nodes/pricing/assign', {'request_id': 'adm', 'owner_open_ids': ['ou_om']})
    assert response.status_code == 200, response.text
    assert act(h, 'ou_admin', '/nodes/pricing/claim', {'request_id': 'adm2'}).json()['code'] == 'forbidden'


def test_manager_completes_a_node_with_zero_tasks_and_the_chain_moves_on(h):
    h.clock[0] = T0 + 0.5
    response = act(h, 'ou_sm', '/nodes/sales/complete', {'request_id': 'done'})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['node']['derived_status'] == '已完成' and body['node']['status'] == '已完成'
    assert body['node']['approver'] == {'open_id': 'ou_sm', 'name': '蔡經理'}
    assert body['node']['approved_at'] == '2026-09-21T22:13:20+08:00'
    assert body['summary'] == {'done': 1, 'total': 9, 'current_node': 'pm'}
    (rid, fields), = h.fake.rows(NODES).items()
    assert (fields['核准時間'], fields['完成時間'], fields['進度']) == (1790000000500, 1790000000500, 1.0)
    assert (body['record_id'], body['roster'], body['writes_enabled'], body['stale']) == (
        rid, {'available': True, 'stale': False}, True, False)


def test_picker_lists_eligible_people_only_for_someone_who_manages_the_node(h):
    assert view(h, 'ou_member', 'field')['assignable_people'] == []
    assert view(h, 'ou_fm', 'field')['assignable_people'] == [
        {'open_id': 'ou_fm', 'name': '林經理', 'departments': ['外業', '水深A']},
        {'open_id': 'ou_member', 'name': '王外業', 'departments': ['外業']},
        {'open_id': 'ou_depth', 'name': '陳水深', 'departments': ['水深B']}]


def test_task_lifecycle_drives_node_status_through_review_rejection_and_rework(h):
    created = act(h, 'ou_fm', '/nodes/field/tasks', {'request_id': 't1', 'title': '控制點佈設', 'detail': '北側 12 點',
                                                     'assignee_open_id': 'ou_depth', 'deadline': '2026-10-20'})
    assert created.status_code == 200, created.text
    task = created.json()['tasks'][0]
    assert (task['title'], task['assignee']['open_id'], task['department'], task['deadline'], task['status']) == (
        '控制點佈設', 'ou_depth', '水深B', '2026-10-20', '待處理')
    (stored,) = h.fake.rows(TASKS).values()
    assert stored['截止日'] == 1792425600000 and stored['指派人'] == [{'id': 'ou_fm'}]
    act(h, 'ou_sm', '/nodes/sales/complete', {'request_id': 's'})
    act(h, 'ou_vp', '/nodes/pm/complete', {'request_id': 'p'})
    act(h, 'ou_vp', '/nodes/confirmation/complete', {'request_id': 'c'})

    def patch(who, rid, revision, **changes):
        return act(h, who, f'/nodes/field/tasks/{task["id"]}', {'request_id': rid, 'expected_revision': revision, **changes},
                   method='patch')
    started = patch('ou_depth', 'p1', task['revision'], status='進行中')
    assert started.status_code == 200, started.text
    assert started.json()['node']['derived_status'] == '進行中' and started.json()['node']['status'] == '進行中'
    revision = started.json()['tasks'][0]['revision']
    finished = patch('ou_depth', 'p2', revision, status='已完成')
    assert finished.json()['node']['derived_status'] == '待審核'
    assert finished.json()['node']['tasks'] == {'done': 1, 'total': 1}
    node_revision = finished.json()['node']['revision']
    rejected = act(h, 'ou_fm', '/nodes/field/reject', {'request_id': 'rj', 'expected_revision': node_revision,
                                                       'reason': '缺少檢核表'})
    assert rejected.json()['node']['derived_status'] == '進行中'
    assert rejected.json()['node']['reject_reason'] == '缺少檢核表'
    revision = rejected.json()['tasks'][0]['revision']
    reopened = patch('ou_depth', 'p3', revision, status='進行中')
    redone = patch('ou_depth', 'p4', reopened.json()['tasks'][0]['revision'], status='已完成')
    assert redone.json()['node']['derived_status'] == '待審核' and redone.json()['node']['reject_reason'] is None
    approved = act(h, 'ou_fm', '/nodes/field/approve', {'request_id': 'ap', 'expected_revision': redone.json()['node']['revision']})
    assert approved.json()['node']['derived_status'] == '已完成'
    locked = patch('ou_fm', 'p5', approved.json()['tasks'][0]['revision'], detail='改')
    assert (locked.status_code, locked.json()['code']) == (409, 'illegal_transition')


def test_member_may_only_create_tasks_for_themselves_and_claim_unassigned_ones(h):
    other = act(h, 'ou_member', '/nodes/field/tasks', {'request_id': 'm1', 'title': '整理資料', 'assignee_open_id': 'ou_depth'})
    assert (other.status_code, other.json()['code']) == (403, 'forbidden')
    mine = act(h, 'ou_member', '/nodes/field/tasks', {'request_id': 'm2', 'title': '整理資料'})
    assert mine.json()['tasks'][0]['assignee']['open_id'] == 'ou_member'
    open_task = act(h, 'ou_fm', '/nodes/field/tasks', {'request_id': 'm3', 'title': '待認領', 'department': '外業'}).json()
    task = next(t for t in open_task['tasks'] if t['title'] == '待認領')
    assert task['assignee'] is None and task['can']['assign'] is True
    claim = act(h, 'ou_depth', f'/nodes/field/tasks/{task["id"]}', {'request_id': 'm4', 'expected_revision': task['revision'],
                                                                     'assignee_open_id': 'ou_depth'}, method='patch')
    assert claim.status_code == 200, claim.text
    claimed = next(t for t in claim.json()['tasks'] if t['id'] == task['id'])
    assert (claimed['assignee']['open_id'], claimed['assigned_by']['open_id']) == ('ou_depth', 'ou_depth')


def test_reopening_a_finished_node_warns_when_later_work_started_and_does_not_cascade(h):
    done = act(h, 'ou_sm', '/nodes/sales/complete', {'request_id': 's'}).json()
    act(h, 'ou_vp', '/nodes/pm/tasks', {'request_id': 't', 'title': '派工', 'department': 'PM'})
    pm = view(h, 'ou_vp', 'pm')['tasks'][0]
    act(h, 'ou_vp', f'/nodes/pm/tasks/{pm["id"]}', {'request_id': 'u', 'expected_revision': pm['revision'],
                                                    'status': '進行中'}, method='patch')
    before = dict(h.fake.tables[NODES])
    pm_row = next(rid for rid, f in before.items() if f['節點'] == 'PM')
    pm_fields = dict(before[pm_row])
    reopened = act(h, 'ou_sm', '/nodes/sales/reject', {'request_id': 'r', 'reason': '報價需重算',
                                                       'expected_revision': view(h)['nodes'][0]['revision']})
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()['warnings'] == ['later_nodes_started']
    assert h.fake.tables[NODES][pm_row] == pm_fields
    pm_view = node(view(h), 'pm')
    assert (pm_view['derived_status'], pm_view['status'], pm_view['warnings']) == (
        '未開始', '進行中', ['lark_status_drift', 'previous_node_not_done'])
    assert done['node']['derived_status'] == '已完成'


def test_skipped_node_is_derived_from_the_app_and_never_writable(h):
    h.case['project'] = project(skipped=('pm',))
    act(h, 'ou_sm', '/nodes/sales/complete', {'request_id': 's'})
    body = view(h, 'ou_vp')
    assert node(body, 'pm')['derived_status'] == '略過' and node(body, 'confirmation')['derived_status'] == '待處理'
    assert body['summary'] == {'done': 1, 'total': 8, 'current_node': 'confirmation'}
    response = act(h, 'ou_vp', '/nodes/pm/complete', {'request_id': 'k'})
    assert (response.status_code, response.json()['detail']) == (409, '節點目前為「略過」，不能標記完成')


@pytest.mark.parametrize('path,body,status,detail', [
    ('/nodes/field/tasks', {'request_id': 'v', 'title': 'x' * 201}, 422, 'title 不得超過 200 字'),
    ('/nodes/field/tasks', {'request_id': 'v', 'title': '  '}, 422, 'title 不可空白'),
    ('/nodes/field/tasks', {'request_id': 'v', 'title': 't', 'deadline': '2026-02-30'}, 422, '截止日需為 YYYY-MM-DD 的有效日期'),
    ('/nodes/field/tasks', {'request_id': 'v', 'title': 't', 'department': '行政'}, 422,
     '部門必須是本節點所屬組別：外業、水深A、水深B、水深C、水深D、地形A、地形C、地形E、點工B'),
    ('/nodes/field/tasks', {'request_id': 'v', 'title': 't', 'owner': 'x'}, 422, '不支援的欄位：owner'),
    ('/nodes/field/claim', {}, 422, 'request_id 必須是文字'),
    ('/nodes/field/reject', {'request_id': 'v', 'reason': 'r' * 501}, 422, 'reason 不得超過 500 字'),
    ('/nodes/field/assign', {'request_id': 'v', 'owner_open_ids': []}, 422, '請指定 1 至 20 位負責人'),
    ('/nodes/nowhere/claim', {'request_id': 'v'}, 404, '沒有這個節點'),
    ('/nodes/field/explode', {'request_id': 'v'}, 404, '不支援的節點操作'),
    ('/nodes/field/tasks/notatask', {'request_id': 'v', 'expected_revision': '0' * 16, 'detail': 'x'}, 404, '沒有這個任務'),
])
def test_bounded_inputs_are_rejected_before_any_write(h, path, body, status, detail):
    method = 'patch' if '/tasks/' in path else 'post'
    response = act(h, 'ou_fm', path, body, method=method)
    assert (response.status_code, response.json()['detail']) == (status, detail)
    assert h.fake.writes() == []


def test_oversized_body_is_rejected(h):
    h.who[0] = 'ou_fm'
    response = h.client.post(URL + '/nodes/field/tasks', content=b'{"title":"' + b'x' * 17000 + b'"}',
                             headers={'content-type': 'application/json'})
    assert (response.status_code, response.json()['code']) == (413, 'payload_too_large')


def test_writes_disabled_workspace_reads_but_cannot_write(h):
    h.state['settings']['external_enabled'] = False
    body = view(h, 'ou_fm')
    assert (body['writes_enabled'], body['writes_disabled_reason']) == (False, '正式外部連線未啟用，節點指派暫不可修改')
    assert body['can']['field']['assign'] is False
    response = act(h, 'ou_fm', '/nodes/field/assign', {'request_id': 'w', 'owner_open_ids': ['ou_member']})
    assert (response.status_code, response.json()['code']) == (403, 'writes_disabled')


def test_roster_failure_degrades_reads_and_blocks_writes(h):
    h.fake.fault('GET', f'{PEOPLE}/fields', lambda request: httpx.Response(503, text='down'), times=3)
    body = view(h, 'ou_fm')
    assert body['roster'] == {'available': False, 'stale': True}
    assert body['can']['field']['assign'] is False
    h.fake.fault('GET', f'{PEOPLE}/fields', lambda request: httpx.Response(503, text='down'), times=3)
    response = act(h, 'ou_fm', '/nodes/field/assign', {'request_id': 'r', 'owner_open_ids': ['ou_member']})
    assert (response.status_code, response.json()['code'], response.json()['reason']) == (503, 'roster_unavailable', 'lark_unavailable')


def test_audit_records_actor_change_and_request_without_secrets(h):
    act(h, 'ou_fm', '/nodes/field/tasks', {'request_id': 'aud', 'title': '外業', 'assignee_open_id': 'ou_member'})
    action, actor, data = h.audits()[-1]
    assert (action, actor, data['result'], data['request_id'], data['project_id'], data['node']) == (
        'node_assignment.create_task', 'ou_fm', 'success', 'aud', 'p1', 'field')
    change, = data['changes']
    assert change['kind'] == 'node_task' and change['after']['assignee'] == ['ou_member']
    text = json.dumps(data, ensure_ascii=False)
    assert 't-synthetic' not in text and 'client_token' not in text and 'synthetic' not in text


def test_delayed_node_create_replay_uses_same_token(h):
    pending = []

    def timeout(request):
        pending.append((request.url.params['client_token'], json.loads(request.content)['fields']))
        raise httpx.ReadTimeout('uncertain create', request=request)

    def land_first(request):
        token, fields = pending[0]
        rid = h.fake.add(NODES, fields)
        h.fake.tokens[token] = rid
        return None

    h.fake.fault('POST', f'{NODES}/records', timeout)
    body = {'request_id': 'delayed-node'}
    first = act(h, 'ou_sales', '/nodes/sales/claim', body)
    assert first.json()['code'] == 'outcome_unknown'
    h.fake.fault('POST', f'{NODES}/records', land_first)
    replay = act(h, 'ou_sales', '/nodes/sales/claim', body)
    assert replay.status_code == 200, replay.text
    assert len(h.fake.tables[NODES]) == 1


@pytest.mark.parametrize('changes', [{'detail': 'changed'}, {'status': '已完成'}, {'status': '取消'}])
def test_departed_assignee_cannot_patch_own_task(h, changes):
    created = act(h, 'ou_sales', '/nodes/sales/tasks', {'request_id': 'own', 'title': 'own task'})
    assert created.status_code == 200, created.text
    task = created.json()['tasks'][0]
    person, = h.fake.rows(PEOPLE, Lark帳號=[{'id': 'ou_sales'}]).values()
    person['在職'] = False
    h.clock[0] += 121
    response = act(h, 'ou_sales', f'/nodes/sales/tasks/{task["id"]}',
                   {'request_id': 'departed', 'expected_revision': task['revision'], **changes}, method='patch')
    assert (response.status_code, response.json().get('code')) == (403, 'forbidden')
    assert not any(view(h, 'ou_sales', 'sales')['tasks'][0]['can'].values())


@pytest.mark.parametrize('landed', [False, True])
def test_uncertain_task_create_does_not_reconcile_to_identical_older_task(h, landed):
    body = {'request_id': 'first-task', 'title': 'identical task'}
    first = act(h, 'ou_sales', '/nodes/sales/tasks', body)
    assert first.status_code == 200, first.text
    old_id = first.json()['record_id']

    def timeout(request):
        if landed:
            token = request.url.params['client_token']
            h.fake.tokens[token] = h.fake.add(TASKS, json.loads(request.content)['fields'])
        raise httpx.ReadTimeout('uncertain task create', request=request)

    h.fake.fault('POST', f'{TASKS}/records', timeout)
    body['request_id'] = 'second-task'
    failed = act(h, 'ou_sales', '/nodes/sales/tasks', body)
    assert failed.json()['code'] == 'outcome_unknown'
    h.client = h.build()  # Reconciliation must use the persisted receipt after a restart.
    replay = act(h, 'ou_sales', '/nodes/sales/tasks', body)
    assert replay.status_code == 200, replay.text
    assert replay.json()['record_id'] != old_id
    assert len(h.fake.tables[TASKS]) == 2
    writes = len(h.fake.writes())
    again = act(h, 'ou_sales', '/nodes/sales/tasks', body)
    assert again.json() == replay.json()
    assert len(h.fake.writes()) == writes


def test_create_tokens_are_stable_distinct_uuid4(h):
    from uuid import UUID
    response = act(h, 'ou_sales', '/nodes/sales/tasks', {'request_id': 'tokens', 'title': 'task'})
    assert response.status_code == 200, response.text
    assert len(h.fake.tokens) == 2
    assert all(UUID(token).version == 4 for token in h.fake.tokens)
    from .node_assignment.service import create_token

    tokens = [create_token(*args) for args in [
        ('receipt', 'key', 'node-create'), ('receipt', 'key', 'task-create'),
        ('other', 'key', 'node-create'), ('receipt', 'other', 'node-create'),
    ]]
    assert all(UUID(token).version == 4 for token in tokens)
    assert len(set(tokens)) == len(tokens)
    assert tokens[0] == create_token('receipt', 'key', 'node-create')


def test_task_baseline_failure_before_create_can_retry_after_restart(h):
    h.fake.fault('GET', f'{NODES}/records/receVb70009', lambda request: httpx.Response(503), times=3)
    body = {'request_id': 'baseline-retry', 'title': 'task'}
    failed = act(h, 'ou_sales', '/nodes/sales/tasks', body)
    assert failed.json()['code'] == 'lark_unavailable', failed.text
    assert len(h.fake.tables[NODES]) == 1
    assert not h.fake.tables[TASKS]
    h.client = h.build()
    replay = act(h, 'ou_sales', '/nodes/sales/tasks', body)
    assert replay.status_code == 200, replay.text
    assert len(h.fake.tables[NODES]) == len(h.fake.tables[TASKS]) == 1


def test_sent_task_create_without_baseline_still_fails_closed(h, monkeypatch):
    from dataclasses import replace
    from .node_assignment.service import Plan

    def timeout(request):
        raise httpx.ReadTimeout('uncertain task create', request=request)

    h.fake.fault('POST', f'{TASKS}/records', timeout)
    body = {'request_id': 'missing-baseline', 'title': 'task'}
    assert act(h, 'ou_sales', '/nodes/sales/tasks', body).json()['code'] == 'outcome_unknown'
    original = Plan.from_json
    monkeypatch.setattr(Plan, 'from_json', lambda value: replace(original(value), pre_create_task_ids=None))
    writes = len(h.fake.writes())
    replay = act(h, 'ou_sales', '/nodes/sales/tasks', body)
    assert (replay.status_code, replay.json()['code']) == (502, 'outcome_unknown')
    assert len(h.fake.writes()) == writes


def test_manager_session_without_roster_can_manage_ordinary_nodes(h):
    h.user_fields['role'] = 'manager'
    body = view(h, 'ou_admin')
    assert body['can']['sales']['assign'] and body['can']['sales']['create_task']
    assert not body['can']['sales']['claim']
    assigned = act(h, 'ou_admin', '/nodes/sales/assign',
                   {'request_id': 'admin-assign', 'owner_open_ids': ['ou_sales']})
    assert assigned.status_code == 200, assigned.text
    created = act(h, 'ou_admin', '/nodes/sales/tasks',
                  {'request_id': 'admin-task', 'title': 'Review', 'assignee_open_id': 'ou_sales'})
    assert created.status_code == 200, created.text
    task = created.json()['tasks'][0]
    edited = act(h, 'ou_admin', f"/nodes/sales/tasks/{task['id']}",
                 {'request_id': 'admin-edit', 'expected_revision': task['revision'], 'status': '已完成'}, method='patch')
    assert edited.status_code == 200, edited.text
    ready = edited.json()
    assert ready['can']['approve'] and ready['can']['reject']
    approved = act(h, 'ou_admin', '/nodes/sales/approve',
                   {'request_id': 'admin-approve', 'expected_revision': ready['node']['revision']})
    assert approved.status_code == 200, approved.text
    rejected = act(h, 'ou_admin', '/nodes/sales/reject',
                   {'request_id': 'admin-reject', 'expected_revision': approved.json()['node']['revision'], 'reason': 'Rework'})
    assert rejected.status_code == 200, rejected.text
    completed = act(h, 'ou_admin', '/nodes/sales/complete',
                    {'request_id': 'admin-complete', 'expected_revision': rejected.json()['node']['revision']})
    assert completed.status_code == 200, completed.text
    assert node(view(h, 'ou_admin'), 'sales')['derived_status'] == '已完成'


@pytest.mark.parametrize('fields', [{'role': 'member'}, {'role': 'manager', 'manager_revoked': True},
                                   {'role': 'manager', 'active': False}])
def test_session_without_override_cannot_assign(h, fields):
    h.user_fields.update(fields)
    assert not view(h, 'ou_admin')['can']['sales']['assign']
    response = act(h, 'ou_admin', '/nodes/sales/assign',
                   {'request_id': 'denied', 'owner_open_ids': ['ou_sales']})
    assert response.status_code == 403


def test_overview_embeds_details_and_warm_reads_make_no_lark_calls(h, caplog):
    import logging
    caplog.set_level(logging.INFO)
    body = view(h, 'ou_sm')
    assert len(h.fake.requests) == 4  # token, people schema, people records, node search
    assert len(body['node_details']) == 9
    for key, embedded in body['node_details'].items():
        detail = view(h, 'ou_sm', key)
        assert embedded == {k: detail[k] for k in ('tasks', 'assignable_people')}
    view(h, 'ou_sm')
    assert len(h.fake.requests) == 4
    assert 'cache=hit lark_calls=0' in caplog.text
    assert 'cache=miss lark_calls=3' in caplog.text


def test_roster_schema_success_cached_for_ten_minutes(h):
    view(h)
    h.clock[0] += 121
    # Force the synchronous write roster refresh; schema remains cached.
    act(h, 'ou_sales', '/nodes/sales/claim', {'request_id': 'roster-refresh'})
    schema = lambda: sum(p.endswith(f'{PEOPLE}/fields') for _, p in h.fake.requests)
    assert schema() == 1
    h.clock[0] += 601
    act(h, 'ou_sm', '/nodes/sales/assign', {'request_id': 'roster-recheck',
                                         'owner_open_ids': ['ou_sales']})
    assert schema() == 2


def test_cold_roster_and_case_reads_overlap(h):
    import threading
    rendezvous = threading.Barrier(2)
    def wait_for_other(_request):
        rendezvous.wait(timeout=2)
    h.fake.fault('GET', f'{PEOPLE}/fields', wait_for_other)
    h.fake.fault('POST', f'{NODES}/records/search', wait_for_other)
    view(h)


def test_cold_detail_call_count_with_linked_task(h):
    rid = h.fake.add(NODES, {'指派鍵': CODE + '|業務', '確認單編號': CODE, '節點': '業務', '狀態': '待處理'})
    h.fake.add(TASKS, {'標題': 'Task', '節點指派': [rid], '狀態': '待處理'})
    view(h, key='sales')
    assert len(h.fake.requests) == 5  # adds task batch_get to the four-call cold fixture
    view(h, key='sales')
    view(h)
    assert len(h.fake.requests) == 5
