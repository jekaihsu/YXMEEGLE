import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from .home_panels import HomePanels
from .node_assignment.service import NodeAssignmentService
from .live_read.token_cache import TenantTokenCache
from .test_node_assignment_routes import FakeBitable, NoBucket, NODES, TASKS, PEOPLE, CODE, T0, project


@pytest.fixture
def home():
    fake = FakeBitable()
    clock = [T0]
    cfg = {'NODE_ASSIGNMENT_ENABLED': 'true', 'LARK_WORKER_IDENTITY': 'application', 'LARK_APP_ID': 'app-home',
           'LARK_APP_SECRET': 'synthetic', 'LARK_WORKER_ORGANIZATION': 'company'}
    nodes = NodeAssignmentService(cfg, sessions=None, receipt_model=None, audit_model=None, skipped_nodes=lambda *_: False,
                                  transport=httpx.MockTransport(fake), clock=lambda: clock[0],
                                  client_options={'token_cache': TenantTokenCache(), 'bucket': NoBucket(), 'sleep': lambda _: None})
    service = HomePanels(nodes)
    p = dict(project(), name='真實格式測試案', source_kind='lark', case_visibility='source_reference')
    for node in p['nodes']:
        node['tasks'] = []
    state = {'environment': 'production', 'users': [{'id': 'ou_member', 'name': '王外業', 'active': True}],
             'projects': [p], 'approvals': [], 'settings': {'external_enabled': True}, 'features': {'routines': False, 'change_extension': False}}
    def read(who='ou_member', **params):
        return service.query(state, {'wid': 'lark-company', 'mode': 'lark'}, {'id': who, 'active': True}, params)
    return SimpleNamespace(fake=fake, clock=clock, service=service, state=state, read=read)


def node(h, label='外業', owner='ou_member', **extra):
    return h.fake.add(NODES, {'指派鍵': CODE + '|' + label, '確認單編號': CODE, '節點': label,
                              '工程確認單': ['recCONF1'], '負責人': [{'id': owner}] if owner else [], '狀態': '未開始', **extra})


def task(h, parent, title='校核', owner='ou_member', **extra):
    return h.fake.add(TASKS, {'標題': title, '節點指派': [parent] if parent else [],
                              '負責人': [{'id': owner}] if owner else [], '狀態': '待處理', '部門': '外業', **extra})


def test_member_keeps_waiting_and_separate_grains(home):
    n = node(home)
    t = task(home, n, 截止日=int((T0 - 86400) * 1000))
    result = home.read()
    assert result['counts'] == {'node_assignments': 1, 'tasks': 1, 'local_workflow': 0, 'sop_tasks': 0, 'count_scope': 'viewer_visible', 'complete': True}
    rows = {i['source']['record_id']: i for i in result['items']}
    assert rows[n]['deadline'] == '2026-09-20'
    assert rows[n]['next_due'] == '2026-09-20'
    assert rows[n]['original_deadline'] is None
    assert rows[n]['blocked_reasons'] == ['等待前置節點']
    assert rows[n]['can_execute'] is False
    assert rows[t]['case'] == {'id': 'p1', 'code': CODE, 'name': '真實格式測試案', 'relation_state': 'verified'}
    assert rows[t]['target'] == {'view': 'project', 'project': 'p1', 'tab': 'flow', 'assignment_node': 'field', 'assignment_task': t}
    assert rows[t]['overdue'] is True
    assert result['total_count'] == 2
    assert home.fake.writes() == []


def test_member_has_no_cross_user_leakage_and_manager_is_scoped(home):
    mine = node(home)
    teammate = node(home, owner='ou_depth')
    administration = node(home, label='計價', owner='ou_om')
    a = task(home, teammate, title='同組工作', owner='ou_depth')
    secret = task(home, administration, title='別組工作', owner='ou_om')
    assert [i['source']['record_id'] for i in home.read()['items']] == [mine]
    with pytest.raises(HTTPException) as exc:
        home.read(scope='team')
    assert exc.value.status_code == 403
    team = home.read('ou_fm', scope='team')
    assert {i['source']['record_id'] for i in team['items']} == {mine, teammate, a}
    assert secret not in json.dumps(team)
    assert administration not in json.dumps(team)
    assert home.read('ou_fm')['items'] == []
    assert len(home.read('ou_vp', scope='team')['items']) == 5


def test_duplicate_keys_are_retained_but_not_actionable(home):
    a, b = node(home), node(home)
    result = home.read()
    assert {i['source']['record_id'] for i in result['items']} == {a, b}
    assert [i['assignment_state'] for i in result['items']] == ['duplicate', 'duplicate']
    assert all(i['can_execute'] is False and '指派鍵重複，請管理員核對' in i['blocked_reasons'] for i in result['items'])


def test_null_deadline_last_and_query_bound_pagination(home):
    n = node(home, owner=None)
    task(home, n, title='未排期限')
    task(home, n, title='較晚', 截止日=int((T0 + 86400) * 1000))
    task(home, n, title='已過期', 截止日=int((T0 - 86400) * 1000))
    page = home.read(limit='2')
    assert [i['title'] for i in page['items']] == ['已過期', '較晚']
    assert page['has_more'] is True
    last = home.read(limit='2', cursor=page['next_cursor'])
    assert [i['title'] for i in last['items']] == ['未排期限']
    assert last['has_more'] is False
    assert [i['title'] for i in home.read(deadline='unscheduled')['items']] == ['未排期限']
    with pytest.raises(HTTPException) as exc:
        home.read('ou_depth', limit='2', cursor=page['next_cursor'])
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException):
        home.read(limit='2', q='其他', cursor=page['next_cursor'])


def test_case_names_never_join_and_unmatched_assignment_remains(home):
    n = node(home, 工程確認單=['recMISSING'])
    result = home.read()
    assert result['items'][0]['case'] == {'id': None, 'code': CODE, 'name': None, 'relation_state': 'unverified'}
    assert result['items'][0]['target'] is None
    assert result['items'][0]['blocked_reasons'] == ['案件關聯待核對', '等待前置節點']
    assert result['items'][0]['source']['record_id'] == n


def test_outgoing_and_real_node_confirmation(home):
    n = node(home, label='業務', owner='ou_sales', 指派人=[{'id': 'ou_member'}])
    t = task(home, n, owner='ou_sales', 狀態='已完成', 完成時間=int(T0 * 1000), 指派人=[{'id': 'ou_member'}])
    assert [i['source']['record_id'] for i in home.read(panel='delegated')['items']] == [n]
    review = home.read('ou_sm', panel='confirmation')
    assert [i['source']['record_id'] for i in review['items']] == [n]
    assert home.read(panel='confirmation')['items'] == []
    assert [i['source']['record_id'] for i in home.read('ou_sales', panel='completed')['items']] == [t]


def test_table_failures_are_partial_not_zero(home):
    node(home)
    home.fake.fault('GET', '/' + TASKS + '/records', lambda _: httpx.Response(403, json={'code': 91403}), times=20)
    result = home.read()
    assert result['readState'] == 'partial'
    assert result['counts']['node_assignments'] == 1
    assert result['counts']['tasks'] is None
    assert result['total_count'] is None
    assert result['complete'] is False
    assert len(result['items']) == 1


def test_stale_cache_label_and_singleflight(home):
    node(home)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: home.read(), range(8)))
    assert all(r['counts']['node_assignments'] == 1 for r in results)
    assert sum(p.endswith('/' + NODES + '/records') for _, p in home.fake.requests) == 1
    assert sum(p.endswith('/' + TASKS + '/records') for _, p in home.fake.requests) == 1
    home.clock[0] += 61
    home.fake.fault('GET', '/' + NODES + '/records', lambda _: httpx.Response(503), times=30)
    stale = home.read()
    assert stale['freshness']['status'] == 'stale'
    assert stale['sources']['node_assignments']['readState'] == 'stale'
    assert stale['sources']['node_assignments']['as_of'] == results[0]['sources']['node_assignments']['as_of']
    assert len(stale['items']) == 1


def test_disabled_and_demo_never_reach_lark_or_count_seeds(home):
    from dataclasses import replace
    from .seed import seed
    home.service.config = replace(home.service.config, enabled=False)
    result = home.read()
    assert result['readState'] == 'disabled'
    assert result['counts']['node_assignments'] is None
    assert result['counts']['tasks'] is None
    assert home.fake.requests == []
    demo = home.service.query(seed(), {'wid': 'demo'}, {'id': 'u-control'}, {})
    assert demo['items'] == []
    assert 'approval' not in json.dumps(demo)
    assert 'routine' not in json.dumps(demo)


def test_templates_and_duplicate_lark_mirrors_are_excluded(home):
    from .home_details import local_work_instance
    p = {'source_kind': 'lark'}
    assert local_work_instance(p, {'owner_id': 'me', 'owner_inherited': True}) is False
    assert local_work_instance(p, {'owner_id': 'me', 'sop_definition_version': 'v1'}) is False
    assert local_work_instance(p, {'owner_id': 'me', 'origin': 'lark'}) is False
    assert local_work_instance(p, {'owner_id': 'me', 'owner_inherited': True, 'assignment_history': [
        {'actor_id': 'manager', 'at': '2026-10-15T10:00:00+08:00', 'after': {'owner_id': 'me'}}]}) is True


def test_hidden_case_never_leaks_its_assignment_or_task(home):
    n = node(home)
    task(home, n, title='不可見的案件內容')
    home.state['projects'][0]['case_visibility'] = 'excluded_history'
    result = home.read()
    assert result['items'] == []
    assert result['counts']['node_assignments'] == 0
    assert result['counts']['tasks'] == 0
    assert '不可見的案件內容' not in json.dumps(result)


def test_unknown_task_relation_remains_visible_to_its_assignee(home):
    task(home, None, title='關聯待補')
    result = home.read()
    assert result['items'][0]['title'] == '關聯待補'
    assert result['items'][0]['case']['relation_state'] == 'unverified'
    assert result['items'][0]['target'] is None


def test_assignment_chain_does_not_join_cases_by_code(home):
    p2 = dict(project(), id='p2', name='另一確認單', source_kind='lark', case_visibility='source_reference')
    p2['source_records'] = [{'kind': 'confirmation', 'url': home.state['projects'][0]['source_records'][0]['url'].replace('recCONF1', 'recCONF2')}]
    home.state['projects'].append(p2)
    node(home, label='業務', 狀態='已完成', 核准人=[{'id': 'ou_sm'}], 核准時間=int(T0 * 1000))
    pm = node(home, label='PM', 工程確認單=['recCONF2'])
    rows = {i['source']['record_id']: i for i in home.read()['items']}
    assert rows[pm]['case']['id'] == 'p2'
    assert rows[pm]['derived_status'] == 'not_started'
    assert rows[pm]['blocked_reasons'] == ['等待前置節點']


def test_live_flag_off_does_not_hide_explicit_local_work(home):
    from dataclasses import replace
    p = home.state['projects'][0]
    p['nodes'][0].update(name='業務', status='pending')
    p['nodes'][0]['tasks'] = [{'id': 'local-1', 'title': '本地明確指派', 'owner_id': 'ou_member', 'status': 'pending',
                              'owner_inherited': True, 'assignment_history': [{'actor_id': 'ou_fm', 'at': '2026-10-15T10:00:00+08:00', 'after': {'owner_id': 'ou_member'}}]}]
    home.service.config = replace(home.service.config, enabled=False)
    result = home.read(panel='local')
    assert [i['title'] for i in result['items']] == ['本地明確指派']
    assert result['counts']['local_workflow'] == 1
    assert home.fake.requests == []


def test_real_app_routes_require_identity_and_use_the_new_query_contract(tmp_path):
    from fastapi.testclient import TestClient
    from .app import create_app
    app = create_app({'DATABASE_URL': f'sqlite:///{tmp_path}/home.db', 'UPLOAD_DIR': str(tmp_path / 'uploads'),
                      'SESSION_SECRET': 'home-test' * 8, 'APP_ENV': 'development', 'DEMO_MODE': 'true',
                      'NODE_ASSIGNMENT_ENABLED': 'false', 'LARK_LIVE_READ_TRANSPORT': 'deny'})
    client = TestClient(app)
    assert client.get('/api/home-panels').status_code == 401
    client.get('/api/session')
    for path in ('/api/home-panels', '/api/my-work?kinds=node_assignment,task&scope=mine&status=open&sort=urgency&limit=25'):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'
        assert response.json()['items'] == []
        assert response.json()['counts']['node_assignments'] is None
        assert response.json()['counts']['tasks'] is None
    assert client.get('/api/home-panels?scope=team').status_code == 403
    assert client.get('/api/home-panels?sort=arbitrary_formula').status_code == 422


def test_roster_failure_does_not_claim_zero_confirmations(home):
    node(home, label='業務', owner='ou_sales')
    home.fake.fault('GET', '/' + PEOPLE + '/records', lambda _: httpx.Response(403, json={'code': 91403}), times=20)
    result = home.read('ou_sm', panel='confirmation')
    assert result['readState'] == 'authorization_unavailable'
    assert result['counts']['node_assignments'] is None
    assert result['total_count'] is None
    assert result['complete'] is False


def test_evidence_done_node_with_a_rejection_reason_is_completed_not_rework(home):
    home.state['projects'][0]['code'] = 'C115264'
    rid = home.fake.add(NODES, {'指派鍵': 'C115264|業務', '確認單編號': 'C115264', '節點': '業務', '工程確認單': ['recCONF1'],
                               '負責人': [{'id': 'ou_sales'}], '狀態': '待處理', '退回原因': '資料有誤'})
    completed = home.read('ou_sales', panel='completed')['items']
    assert [(i['source']['record_id'], i['derived_status'], i['status']) for i in completed] == [(rid, 'done', 'done')]
    assert rid not in [i['source']['record_id'] for i in home.read('ou_sales', panel='assigned')['items']]


def test_a_rejected_open_node_is_still_rework(home):
    rid = node(home, '外業', owner='ou_sales', 退回原因='資料有誤')
    row = next(r for r in home.read('ou_sales')['items'] if r['source']['record_id'] == rid)
    assert row['status'] == 'rework'


def test_production_evidence_moves_a_node_to_in_progress_on_the_home_panels_too(home):
    p = home.state['projects'][0]
    for label in ('業務', 'PM', '確認單'):
        node(home, label, owner='ou_sales', 狀態='已完成', 核准人=[{'id': 'ou_vp'}], 核准時間=int(T0 * 1000))
    rid = node(home, '外業')
    before = next(r for r in home.read()['items'] if r['source']['record_id'] == rid)
    p['daily_reports'] = [{'id': 'd1', 'date': '2026-10-08', 'department': '外業組', 'points': 1}]
    home.clock[0] += 1000
    after = next(r for r in home.read()['items'] if r['source']['record_id'] == rid)
    assert (before['derived_status'], after['derived_status']) == ('todo', 'in_progress')
    assert home.fake.writes() == []
