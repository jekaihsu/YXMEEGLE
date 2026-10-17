import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from .node_assignment.lark_table import date_millis
from .test_node_assignment_routes import NODES, PEOPLE, TASKS, URL, act, h, project  # noqa: F401  (h is the shared fixture)

SOP = URL + '/start-sop'


def counts(qty='0', lines=0, items=0, **extra):
    return {'lines': lines, 'planned_qty': qty, 'items': items, 'items_native': 0, 'items_native_unresolved': 0,
            'items_derived': 0, 'items_ambiguous': 0, 'items_unlinked': 0, 'needs_review': 0, **extra}


def set_plan(h, truncated=False, **categories):
    base = {'外業': counts('123.45', 2, 5, items_native=5), '控制': counts('10', 1, 1, items_native=1),
            '圖資': counts('8.5', 1, 2, items_native=2), '報告': counts('3', 1, 0)}
    h.state['derived_plan'] = {'p1': {'rule_version': 'contract-links-20261017.1', 'truncated': truncated,
                                      'categories': {**base, **categories}}}


def quote(qid, project_id='p1', **fields):
    return {'id': qid, 'project_id': project_id, 'project_ids': [project_id] if project_id else [],
            'confirmation_ids': [], 'fields': fields}


DEADLINES = {'外業期限': date_millis('2026-10-30'), '內業期限(控)': '2026-11-05', '內業期限(圖)': date_millis('2026-11-10'),
             '內業期限(報)': '2026-11-20'}


@pytest.fixture
def s(h):
    h.case['project'] = {**project(), 'pm_id': 'ou_pm'}
    set_plan(h)
    h.state['source_quotes'] = [quote('q1', **DEADLINES)]
    for ident, name in (('ou_pm', '張專案'), ('ou_sup', '李主管'), ('ou_nsup', '趙節點')):
        h.fake.add(PEOPLE, {'姓名': name, '所屬組別': ['PM'], '職級': '組員', '在職': True,
                            'Lark帳號': [{'id': ident}], '同步_OpenID': ident})
    return h


def preview(h, who='ou_pm'):
    h.who[0] = who
    response = h.client.get(SOP)
    assert response.status_code == 200, response.text
    return response.json()


def start(h, rid='r1', who='ou_pm', digest=None, expect=200):
    h.who[0] = who
    response = h.client.post(SOP, json={'request_id': rid, 'preview_hash': digest or preview(h, who)['preview_hash']})
    assert response.status_code == expect, response.text
    return response


def fail_nth_create(h, table, nth, response):
    """Answer the nth create on a table with `response`; every other request passes through."""
    seen = []

    def respond(_request):
        seen.append(1)
        return response if len(seen) == nth else None
    h.fake.fault('POST', f'{table}/records', respond, times=nth)


def post_methods(h):
    return [m for m, _ in h.fake.writes()]


def seeded_nodes(h):
    return sorted(f['節點'] for f in h.fake.rows(NODES).values())


def test_preview_describes_the_plan_without_writing(s):
    body = preview(s)
    assert [n['key'] for n in body['nodes']] == ['field', 'control', 'mapping', 'report']
    field = body['nodes'][0]
    assert field == {
        'key': 'field', 'label': '外業', 'category': '外業', 'planned_qty': '123.45', 'lines': 2, 'items': 5,
        'items_basis': {'native': 5, 'derived': 0, 'ambiguous': 0, 'unlinked': 0}, 'deadline': '2026-10-30',
        'node_exists': False, 'seed_task_exists': False, 'will_create_node': True, 'will_create_task': True,
        'task_title': '外業：依計畫數量完成',
        'task_detail': '依計畫數量完成外業。\n計畫數量：123.45\n合約明細：2 筆；工項：5 項\n'
                       '工項連結：原生 5、推導 0、待確認 0、未連結 0\n[SOP-START:v1:field]'}
    assert [n['deadline'] for n in body['nodes']] == ['2026-10-30', '2026-11-05', '2026-11-10', '2026-11-20']
    assert (body['project_id'], body['code'], body['eligible'], body['already_started'], body['blockers'],
            body['plan_rule_version']) == ('p1', 'A115001-01', True, False, [], 'contract-links-20261017.1')
    assert body['warnings'] == []
    assert body['chain_note'] == '節點狀態仍依九節點流程推導；啟動 SOP 只建立節點列與一筆種子任務，不會變更任何節點狀態。'
    assert len(body['preview_hash']) == 64
    assert s.fake.writes() == []


def test_start_creates_four_nodes_and_one_marked_task_each(s):
    response = start(s)
    body = response.json()
    assert (body['started'], body['complete']) == (True, True)
    assert body['results'] == [{'key': k, 'node': 'created', 'task': 'created', 'error': None, 'sync': 'ok'}
                               for k in ('field', 'control', 'mapping', 'report')]
    assert post_methods(s) == ['POST', 'POST', 'PUT'] * 4
    assert seeded_nodes(s) == ['圖資', '報告', '外業', '控制']
    tasks = {f['標題']: f for f in s.fake.rows(TASKS).values()}
    assert sorted(tasks) == ['圖資：依計畫數量完成', '報告：依計畫數量完成', '外業：依計畫數量完成', '控制：依計畫數量完成']
    field = tasks['外業：依計畫數量完成']
    assert (field['內容'], field['部門'], field['狀態'], field['截止日'], field['指派人']) == (
        '依計畫數量完成外業。\n計畫數量：123.45\n合約明細：2 筆；工項：5 項\n'
        '工項連結：原生 5、推導 0、待確認 0、未連結 0\n[SOP-START:v1:field]',
        '外業', '待處理', date_millis('2026-10-30'), [{'id': 'ou_pm'}])
    assert tasks['控制：依計畫數量完成']['內容'] == (
        '依計畫數量完成控制。\n計畫數量：10\n合約明細：1 筆；工項：1 項\n'
        '工項連結：原生 1、推導 0、待確認 0、未連結 0\n[SOP-START:v1:control]')
    assert tasks['圖資：依計畫數量完成']['內容'] == (
        '依計畫數量完成圖資。\n計畫數量：8.5\n合約明細：1 筆；工項：2 項\n'
        '工項連結：原生 2、推導 0、待確認 0、未連結 0\n[SOP-START:v1:mapping]')
    assert '負責人' not in field
    assert tasks['圖資：依計畫數量完成']['部門'] == '圖報A'
    assert tasks['報告：依計畫數量完成']['內容'] == (
        '依計畫數量完成報告。\n計畫數量：3\n合約明細：1 筆；工項：0 項\n'
        '工項連結：原生 0、推導 0、待確認 0、未連結 0\n[SOP-START:v1:report]')
    assert tasks['控制：依計畫數量完成']['截止日'] == date_millis('2026-11-05')
    node = next(f for f in s.fake.rows(NODES).values() if f['節點'] == '外業')
    assert (node['指派鍵'], node['狀態'], node['工程確認單']) == ('A115001-01|外業', '未開始', ['recCONF1'])
    overview = {n['key']: n for n in body['overview']['nodes']}
    assert (overview['field']['tasks'], overview['field']['derived_status']) == ({'done': 0, 'total': 1}, '未開始')
    assert overview['field']['deadline'] == '2026-10-30'


def test_pressing_again_creates_nothing_and_reports_existing(s):
    first = preview(s)
    start(s, 'r1')
    again = preview(s)
    assert (again['already_started'], again['eligible']) == (True, False)
    assert again['preview_hash'] == first['preview_hash']
    assert all(n['node_exists'] and n['seed_task_exists'] and not n['will_create_node'] and not n['will_create_task']
               for n in again['nodes'])
    writes = len(s.fake.writes())
    body = start(s, 'r2').json()
    assert (body['started'], body['complete']) == (False, True)
    assert body['results'] == [{'key': k, 'node': 'existing', 'task': 'existing', 'error': None, 'sync': 'ok'}
                               for k in ('field', 'control', 'mapping', 'report')]
    assert len(s.fake.writes()) == writes and len(s.fake.rows(TASKS)) == 4


def test_replaying_a_request_id_returns_the_stored_body_and_a_different_body_conflicts(s):
    first = start(s, 'same')
    writes = len(s.fake.writes())
    replay = s.client.post(SOP, json={'request_id': 'same', 'preview_hash': preview(s)['preview_hash']})
    assert replay.status_code == 200 and replay.json() == first.json()
    assert replay.headers['idempotent-replayed'] == 'true'
    assert len(s.fake.writes()) == writes
    other = s.client.post(SOP, json={'request_id': 'same', 'preview_hash': '0' * 64})
    assert (other.status_code, other.json()['code']) == (409, 'idempotency_conflict')


def test_a_changed_plan_makes_the_preview_stale(s):
    stale = preview(s)['preview_hash']
    set_plan(s, 外業=counts('130', 2, 5, items_native=5))
    body = start(s, 'r1', digest=stale, expect=409).json()
    assert body['code'] == 'preview_stale'
    assert s.fake.writes() == []
    assert preview(s)['preview_hash'] != stale
    s.state['source_quotes'] = [quote('q1', **{**DEADLINES, '外業期限': '2026-10-31'})]
    assert start(s, 'r2', digest=stale, expect=409).json()['code'] == 'preview_stale'


def test_a_plan_identical_across_two_projects_hashes_differently(s):
    s.case['others']['p2'] = {**project(code='A115002-01', pid='p2'), 'pm_id': 'ou_pm'}
    s.state['derived_plan']['p2'] = s.state['derived_plan']['p1']
    s.state['source_quotes'] = [quote('q1', **DEADLINES), quote('q2', project_id='p2', **DEADLINES)]
    s.who[0] = 'ou_pm'
    other = s.client.get('/api/projects/p2/node-assignments/start-sop').json()
    first = preview(s)
    assert (other['project_id'], other['code']) == ('p2', 'A115002-01')
    assert [n['planned_qty'] for n in first['nodes']] == [n['planned_qty'] for n in other['nodes']] == [
        '123.45', '10', '8.5', '3']
    assert [n['deadline'] for n in first['nodes']] == [n['deadline'] for n in other['nodes']]
    assert first['preview_hash'] != other['preview_hash']


def test_hash_does_not_change_when_lark_state_changes(s):
    before = preview(s)['preview_hash']
    start(s)
    assert preview(s)['preview_hash'] == before


def test_malformed_preview_hash_is_rejected(s):
    s.who[0] = 'ou_pm'
    response = s.client.post(SOP, json={'request_id': 'r1', 'preview_hash': 'abc'})
    assert (response.status_code, response.json()['code']) == (422, 'invalid')


def test_a_plain_member_is_forbidden_and_the_denial_is_audited(s):
    body = preview(s, 'ou_member')
    assert ([b['code'] for b in body['blockers']], body['eligible']) == (['forbidden'], False)
    response = start(s, 'r1', who='ou_member', expect=403)
    assert response.json()['code'] == 'forbidden'
    assert s.fake.writes() == []
    denied = [(a[0], a[1], a[2]['request_id'], a[2]['nodes']) for a in s.audits() if a[2]['result'] == 'denied']
    assert denied == [('node_assignment.start_sop', 'ou_member', 'r1', ['field', 'control', 'mapping', 'report'])]


def test_can_start_tells_the_frontend_whether_the_button_works(s):
    assert (preview(s, 'ou_pm')['can_start'], preview(s, 'ou_member')['can_start']) == (True, False)
    start(s, 'r1')
    again = preview(s, 'ou_pm')
    assert (again['can_start'], again['eligible']) == (True, False)
    assert preview(s, 'ou_fm')['can_start'] is True
    s.state['settings']['external_enabled'] = False
    assert preview(s, 'ou_pm')['can_start'] is True


def test_a_lead_who_is_not_in_the_roster_cannot_start(s):
    s.case['project'] = {**s.case['project'], 'pm_id': 'ou_ghost'}
    body = preview(s, 'ou_ghost')
    assert (body['can_start'], [b['code'] for b in body['blockers']]) == (False, ['forbidden'])
    response = start(s, 'r1', who='ou_ghost', digest=body['preview_hash'], expect=403)
    assert response.json()['code'] == 'forbidden'
    assert s.fake.writes() == []
    assert [a[2]['nodes'] for a in s.audits() if a[2]['result'] == 'denied'] == [
        ['field', 'control', 'mapping', 'report']]


def test_an_unemployed_lead_cannot_start(s):
    s.fake.add(PEOPLE, {'姓名': '離職PM', '所屬組別': ['PM'], '職級': '組員', '在職': False,
                        'Lark帳號': [{'id': 'ou_left'}], '同步_OpenID': 'ou_left'})
    s.case['project'] = {**s.case['project'], 'pm_id': 'ou_left', 'supervisor_id': 'ou_left'}
    body = preview(s, 'ou_left')
    assert (body['can_start'], body['eligible']) == (False, False)
    response = start(s, 'r1', who='ou_left', digest=body['preview_hash'], expect=403)
    assert response.json()['detail'] == '你不在人員名單或尚未在職，無法啟動 SOP'
    assert s.fake.writes() == []


def test_a_system_admin_outside_the_roster_may_still_start(s):
    s.user_fields['role'] = 'manager'
    assert preview(s, 'ou_boss')['can_start'] is True
    assert start(s, 'r1', who='ou_boss').json()['complete'] is True
    assert [f['指派人'] for f in s.fake.rows(TASKS).values()] == [[{'id': 'ou_boss'}]] * 4


def test_an_account_that_is_not_a_lark_open_id_is_not_written_as_assigned_by(s):
    s.fake.add(PEOPLE, {'姓名': '舊帳號', '所屬組別': ['PM'], '職級': '組員', '在職': True,
                        'Lark帳號': [{'id': 'legacy-7'}], '同步_OpenID': 'legacy-7'})
    s.case['project'] = {**s.case['project'], 'pm_id': 'legacy-7'}
    body = preview(s, 'legacy-7')
    assert body['can_start'] is False
    response = start(s, 'r1', who='legacy-7', digest=body['preview_hash'], expect=403)
    assert response.json()['detail'] == '你的帳號不是有效的 Lark 帳號，無法啟動 SOP'
    assert s.fake.writes() == []


def test_project_pm_supervisor_node_supervisor_and_system_admin_may_start(s):
    s.case['project'] = {**s.case['project'], 'pm_id': 'u-other', 'supervisor_id': 'ou_sup'}
    assert preview(s, 'ou_sup')['blockers'] == []
    s.case['project']['nodes'] = [{**n, 'supervisor_id': 'ou_nsup'} if n['key'] == 'field' else n
                                  for n in s.case['project']['nodes']]
    assert preview(s, 'ou_nsup')['blockers'] == []
    start(s, 'r1', who='ou_nsup')
    assert len(s.fake.rows(NODES)) == 1
    s.user_fields['role'] = 'manager'
    assert preview(s, 'ou_boss')['blockers'] == []
    assert start(s, 'r2', who='ou_boss').json()['complete'] is True
    assert len(s.fake.rows(NODES)) == 4 and len(s.fake.rows(TASKS)) == 4


def test_a_department_manager_seeds_only_their_node(s):
    body = start(s, 'r1', who='ou_fm').json()
    assert body['complete'] is False
    assert body['results'][0] == {'key': 'field', 'node': 'created', 'task': 'created', 'error': None, 'sync': 'ok'}
    assert [(r['key'], r['node'], r['task'], r['error']) for r in body['results'][1:]] == [
        (k, 'failed', 'failed', 'forbidden') for k in ('control', 'mapping', 'report')]
    assert seeded_nodes(s) == ['外業']
    assert [a[2]['nodes'] for a in s.audits() if a[2]['result'] == 'denied'] == [['control', 'mapping', 'report']]


def test_case_without_confirmation_code_cannot_start(s):
    s.case['project'] = {**s.case['project'], 'code': ''}
    body = preview(s)
    assert (body['code'], body['eligible'], [b['code'] for b in body['blockers']]) == (
        None, False, ['no_confirmation_code'])
    assert len(body['nodes']) == 4
    s.who[0] = 'ou_pm'
    response = s.client.post(SOP, json={'request_id': 'r1', 'preview_hash': body['preview_hash']})
    assert (response.status_code, response.json()['code']) == (409, 'nothing_to_start')
    assert s.fake.requests == []


def test_case_without_planned_quantity_cannot_start(s):
    set_plan(s, **{c: counts('0', 1, 1) for c in ('外業', '控制', '圖資', '報告')})
    body = preview(s)
    assert (body['nodes'], body['eligible'], [b['code'] for b in body['blockers']]) == ([], False, ['no_planned_quantity'])
    s.who[0] = 'ou_pm'
    response = s.client.post(SOP, json={'request_id': 'r1', 'preview_hash': body['preview_hash']})
    assert (response.status_code, response.json()['code']) == (409, 'nothing_to_start')


def test_only_categories_with_quantity_become_nodes(s):
    set_plan(s, 控制=counts('0', 1, 1), 報告=counts('0'))
    body = start(s).json()
    assert [r['key'] for r in body['results']] == ['field', 'mapping']
    assert seeded_nodes(s) == ['圖資', '外業']


def test_writes_disabled_blocks_preview_and_run(s):
    s.state['settings']['external_enabled'] = False
    body = preview(s)
    assert ([b['code'] for b in body['blockers']], body['eligible']) == (['writes_disabled'], False)
    s.who[0] = 'ou_pm'
    response = s.client.post(SOP, json={'request_id': 'r1', 'preview_hash': body['preview_hash']})
    assert (response.status_code, response.json()['code']) == (403, 'writes_disabled')
    assert s.fake.writes() == []


def test_disabled_feature_answers_404_without_touching_lark(s):
    client = s.build({'NODE_ASSIGNMENT_ENABLED': 'false'})
    responses = [client.get(SOP), client.post(SOP, json={'request_id': 'r1', 'preview_hash': '0' * 64})]
    assert [(r.status_code, r.json()['code']) for r in responses] == [(404, 'disabled')] * 2
    assert s.fake.requests == []


def test_lark_read_failure_blocks_the_preview(s):
    s.fake.fault('POST', '/records/search', lambda request: httpx.Response(503, text='down'), times=3)
    body = preview(s)
    assert ([b['code'] for b in body['blockers']], body['eligible'], body['already_started']) == (
        ['lark_unavailable'], False, False)
    assert all(not n['will_create_node'] and not n['will_create_task'] for n in body['nodes'])


def test_quotes_that_disagree_on_a_date_give_no_deadline_and_a_warning(s):
    s.state['source_confirmations'] = [{'id': 'c1', 'project_id': 'p1', 'quote_ids': ['q2']}]
    s.state['source_quotes'] = [
        quote('q1', **DEADLINES),
        quote('q2', project_id=None, **{**DEADLINES, '外業期限': '2026-10-31', '內業期限(控)': date_millis('2026-11-05')}),
        quote('q3', project_id='other', **{'外業期限': '2027-01-01', '內業期限(圖)': '2027-01-01'})]
    body = preview(s)
    assert [n['deadline'] for n in body['nodes']] == [None, '2026-11-05', '2026-11-10', '2026-11-20']
    assert body['warnings'] == [{'code': 'deadline_conflict', 'node': 'field',
                                 'message': '外業期限在報價間不一致（2026-10-30、2026-10-31），未帶入截止日'}]
    assert '注意：外業期限在報價間不一致（2026-10-30、2026-10-31），未帶入截止日\n[SOP-START:v1:field]' in body['nodes'][0]['task_detail']
    start(s)
    field = next(f for f in s.fake.rows(TASKS).values() if f['標題'].startswith('外業'))
    assert '截止日' not in field


def test_quote_linked_only_through_the_quotes_own_confirmation_list_counts(s):
    s.state['source_confirmations'] = [{'id': 'c1', 'project_id': 'p1', 'quote_ids': []}]
    s.state['source_quotes'] = [{**quote('q9', project_id=None, **{'外業期限': '2026-12-01'}), 'confirmation_ids': ['c1']}]
    assert preview(s)['nodes'][0]['deadline'] == '2026-12-01'


def test_plan_warnings_are_reported_and_recorded_in_the_task(s):
    s.case['project'] = {**s.case['project'], 'pm_id': ''}
    set_plan(s, truncated=True, 外業=counts('123.45', 2, 5, items_native=2, items_ambiguous=2, items_derived=1),
             控制=counts('0', 3, 0, needs_review=3))
    body = preview(s)
    assert [(w['code'], w['node']) for w in body['warnings']] == [
        ('no_pm', None), ('plan_truncated', None), ('ambiguous_links', 'field'), ('derived_links', 'field'),
        ('needs_review', 'control')]
    detail = body['nodes'][0]['task_detail']
    assert detail.endswith('注意：計畫明細過多已截斷，工項數量可能不完整\n[SOP-START:v1:field]')
    assert '注意：外業有 2 個工項對到多筆合約明細，連結不明確' in detail
    assert '注意：外業有 1 個工項連結為系統推導，非來源原生關聯' in detail
    assert '工項連結：原生 2、推導 1、待確認 2、未連結 0' in detail
    assert len(detail) < 2000
    assert 'no_pm' not in detail


def test_partial_failure_then_the_same_request_resumes_without_duplicates(s):
    fail_nth_create(s, NODES, 2, httpx.Response(500, text='boom'))
    first = start(s, 'r1').json()
    assert first['complete'] is False
    assert [(r['key'], r['node'], r['task'], r['error']) for r in first['results']] == [
        ('field', 'created', 'created', None), ('control', 'failed', 'failed', 'outcome_unknown'),
        ('mapping', 'created', 'created', None), ('report', 'created', 'created', None)]
    assert len(s.fake.rows(NODES)) == 3 and len(s.fake.rows(TASKS)) == 3
    resumed = start(s, 'r1').json()
    assert (resumed['complete'], resumed['started']) == (True, True)
    assert [(r['key'], r['node'], r['task']) for r in resumed['results']] == [
        ('field', 'created', 'created'), ('control', 'created', 'created'),
        ('mapping', 'created', 'created'), ('report', 'created', 'created')]
    assert seeded_nodes(s) == ['圖資', '報告', '外業', '控制'] and len(s.fake.rows(TASKS)) == 4
    third = start(s, 'r2').json()
    assert (third['started'], third['complete']) == (False, True)
    assert len(s.fake.rows(NODES)) == 4 and len(s.fake.rows(TASKS)) == 4


def test_a_task_create_lost_after_landing_is_reconciled_not_repeated(s):
    def lost_response(request):
        s.fake.add(TASKS, json.loads(request.content)['fields'])
        return httpx.Response(504, text='gateway timeout')
    s.fake.fault('POST', f'{TASKS}/records', lost_response)
    first = start(s, 'r1').json()
    assert first['complete'] is False
    assert (first['results'][0]['task'], first['results'][0]['error']) == ('failed', 'outcome_unknown')
    resumed = start(s, 'r1').json()
    assert resumed['complete'] is True
    assert len(s.fake.rows(TASKS)) == 4
    assert sorted(f['標題'] for f in s.fake.rows(TASKS).values()).count('外業：依計畫數量完成') == 1
    assert (resumed['results'][0]['task'], resumed['results'][0]['error']) == ('created', None)


def test_a_rejected_task_after_the_node_landed_is_a_partial_success(s):
    fail_nth_create(s, TASKS, 1, httpx.Response(400, json={'code': 1254001, 'msg': 'bad'}))
    response = start(s, 'r1')
    body = response.json()
    assert (body['started'], body['complete']) == (True, False)
    assert [(r['key'], r['node'], r['task'], r['error']) for r in body['results']] == [
        ('field', 'created', 'failed', 'lark_error'), ('control', 'created', 'created', None),
        ('mapping', 'created', 'created', None), ('report', 'created', 'created', None)]
    assert len(s.fake.rows(NODES)) == 4 and len(s.fake.rows(TASKS)) == 3
    resumed = start(s, 'r1').json()
    assert resumed['complete'] is True
    assert len(s.fake.rows(TASKS)) == 4


def test_every_task_rejected_still_answers_200_because_the_nodes_landed(s):
    s.fake.fault('POST', f'{TASKS}/records', lambda request: httpx.Response(400, json={'code': 1254001, 'msg': 'bad'}),
                 times=4)
    body = start(s, 'r1').json()
    assert (body['started'], body['complete']) == (True, False)
    assert [(r['node'], r['task'], r['error']) for r in body['results']] == [('created', 'failed', 'lark_error')] * 4
    assert len(s.fake.rows(NODES)) == 4 and len(s.fake.rows(TASKS)) == 0


def test_resume_after_a_crash_that_landed_reports_created_then_a_plain_press_reports_existing(s):
    def lost_response(request):
        s.fake.tokens[request.url.params['client_token']] = s.fake.add(TASKS, json.loads(request.content)['fields'])
        return httpx.Response(504, text='gateway timeout')
    s.fake.fault('POST', f'{TASKS}/records', lost_response)
    first = start(s, 'r1').json()
    assert [(r['node'], r['task'], r['error']) for r in first['results']][:2] == [
        ('created', 'failed', 'outcome_unknown'), ('created', 'created', None)]
    resumed = start(s, 'r1').json()
    assert (resumed['started'], resumed['complete']) == (True, True)
    assert [(r['node'], r['task']) for r in resumed['results']] == [('created', 'created')] * 4
    plain = start(s, 'r2').json()
    assert (plain['started'], plain['complete']) == (False, True)
    assert [(r['node'], r['task']) for r in plain['results']] == [('existing', 'existing')] * 4
    assert len(s.fake.rows(TASKS)) == 4


def after_first_task_create(s, change):
    """Run `change` once the first seed task has been sent to Lark, then let the request through."""
    def hook(_request):
        change()
    s.fake.fault('POST', f'{TASKS}/records', hook)


def test_a_pm_removed_mid_run_stops_the_later_nodes(s):
    after_first_task_create(s, lambda: s.case.update(project={**s.case['project'], 'pm_id': 'ou_other'}))
    body = start(s, 'r1').json()
    assert (body['started'], body['complete']) == (True, False)
    assert [(r['key'], r['node'], r['task'], r['error']) for r in body['results']] == [
        ('field', 'created', 'created', None), ('control', 'failed', 'failed', 'forbidden'),
        ('mapping', 'failed', 'failed', 'forbidden'), ('report', 'failed', 'failed', 'forbidden')]
    assert seeded_nodes(s) == ['外業'] and len(s.fake.rows(TASKS)) == 1
    assert [a[2]['node'] for a in s.audits() if a[2]['result'] == 'denied'] == ['control', 'mapping', 'report']


def test_a_plan_that_changes_mid_run_stops_the_remaining_nodes_and_a_new_preview_resumes(s):
    after_first_task_create(s, lambda: set_plan(s, 控制=counts('11', 1, 1, items_native=1)))
    first = start(s, 'r1').json()
    assert (first['started'], first['complete']) == (True, False)
    assert [(r['key'], r['node'], r['task'], r['error']) for r in first['results']] == [
        ('field', 'created', 'created', None), ('control', 'failed', 'failed', 'preview_stale'),
        ('mapping', 'failed', 'failed', 'preview_stale'), ('report', 'failed', 'failed', 'preview_stale')]
    assert seeded_nodes(s) == ['外業']
    fresh = preview(s)['preview_hash']
    resumed = start(s, 'r2', digest=fresh).json()
    assert [(r['key'], r['node'], r['task']) for r in resumed['results']] == [
        ('field', 'existing', 'existing'), ('control', 'created', 'created'),
        ('mapping', 'created', 'created'), ('report', 'created', 'created')]
    assert next(f for f in s.fake.rows(TASKS).values() if f['標題'].startswith('控制'))['內容'].startswith(
        '依計畫數量完成控制。\n計畫數量：11\n')


def test_a_quote_deadline_that_changes_mid_run_is_also_stale(s):
    after_first_task_create(s, lambda: s.state.update(source_quotes=[quote('q1', **{**DEADLINES, '內業期限(報)': '2026-12-01'})]))
    body = start(s, 'r1').json()
    assert [(r['key'], r['error']) for r in body['results']] == [
        ('field', None), ('control', None), ('mapping', None), ('report', 'preview_stale')]


def lose_and_hide_the_first_task(s):
    """The first task create lands in Lark under its client token but the answer is lost and the node does not list it yet."""
    def lost_response(request):
        rid = s.fake.add(TASKS, json.loads(request.content)['fields'])
        s.fake.tokens[request.url.params['client_token']] = rid
        s.fake.hidden.add(rid)
        return httpx.Response(504, text='gateway timeout')
    s.fake.fault('POST', f'{TASKS}/records', lost_response)


def field_tasks(s):
    return [f for f in s.fake.tables[TASKS].values() if f['標題'].startswith('外業')]


def test_a_new_request_by_another_person_reconciles_an_uncertain_create_instead_of_duplicating(s):
    s.case['project'] = {**s.case['project'], 'supervisor_id': 'ou_sup'}
    lose_and_hide_the_first_task(s)
    first = start(s, 'r1').json()
    assert [(r['node'], r['task'], r['error']) for r in first['results']][:2] == [
        ('created', 'failed', 'outcome_unknown'), ('created', 'created', None)]
    second = start(s, 'r2', who='ou_sup').json()
    assert [(r['key'], r['node'], r['task'], r['error']) for r in second['results']] == [
        ('field', 'created', 'created', None), ('control', 'existing', 'existing', None),
        ('mapping', 'existing', 'existing', None), ('report', 'existing', 'existing', None)]
    s.fake.hidden.clear()
    assert len(field_tasks(s)) == 1 and len(s.fake.rows(TASKS)) == 4
    assert field_tasks(s)[0]['指派人'] == [{'id': 'ou_pm'}]
    third = start(s, 'r3', who='ou_sup').json()
    assert (third['started'], third['complete']) == (False, True)
    assert len(s.fake.rows(TASKS)) == 4


def test_an_uncertain_create_is_reconciled_even_when_the_task_became_visible_before_the_retry(s):
    lose_and_hide_the_first_task(s)
    start(s, 'r1')
    s.fake.hidden.clear()
    body = start(s, 'r2').json()
    assert body['results'][0] == {'key': 'field', 'node': 'created', 'task': 'created', 'error': None, 'sync': 'ok'}
    assert len(field_tasks(s)) == 1
    assert start(s, 'r3').json()['results'][0] == {'key': 'field', 'node': 'existing', 'task': 'existing', 'error': None, 'sync': 'ok'}


def test_cancelling_the_seed_and_pressing_again_creates_exactly_one_new_task(s):
    start(s, 'r1')
    old = edit_seed_detail(s, '外業', '外業：舊的\n[SOP-START:v1:field]')
    s.fake.tables[TASKS][old]['狀態'] = '取消'
    s.clock[0] += 3600
    assert start(s, 'r2').json()['results'][0]['task'] == 'created'
    assert [f['狀態'] for f in field_tasks(s)].count('取消') == 1 and len(field_tasks(s)) == 2
    assert start(s, 'r3').json()['started'] is False
    assert len(field_tasks(s)) == 2


def test_a_marker_task_from_before_the_ledger_stays_the_seed_after_its_marker_is_edited_away(s):
    node = s.fake.add(NODES, {'指派鍵': 'A115001-01|外業', '確認單編號': 'A115001-01', '節點': '外業', '狀態': '未開始'})
    legacy = s.fake.add(TASKS, {'標題': '外業：依計畫數量完成', '內容': '舊版\n[SOP-START:v1:field]', '節點指派': [node],
                                '狀態': '待處理', '部門': '外業'})
    start(s, 'r1')
    s.fake.tables[TASKS][legacy]['內容'] = '舊版，標記已刪除'
    s.clock[0] += 3600
    assert start(s, 'r2').json()['results'][0] == {'key': 'field', 'node': 'existing', 'task': 'existing', 'error': None, 'sync': 'ok'}
    assert len(field_tasks(s)) == 1


def test_a_failure_on_every_node_is_returned_as_the_lark_error(s):
    s.fake.fault('POST', f'{NODES}/records', lambda request: httpx.Response(
        403, json={'code': 1254302, 'msg': 'NoPermission'}))
    response = start(s, 'r1', expect=502)
    assert (response.json()['code'], response.json()['missing_scopes']) == ('lark_permission', ['bitable:app'])
    assert [r for r in s.fake.requests if r[0] == 'POST' and r[1].endswith(f'{NODES}/records')] != []
    assert len(s.fake.rows(NODES)) == 0
    retried = start(s, 'r1').json()
    assert retried['complete'] is True and len(s.fake.rows(TASKS)) == 4


def test_a_permission_failure_after_progress_stops_the_run_and_reports_the_rest(s):
    fail_nth_create(s, NODES, 2, httpx.Response(403, json={'code': 1254302, 'msg': 'NoPermission'}))
    body = start(s, 'r1').json()
    assert [(r['key'], r['node'], r['error']) for r in body['results']] == [
        ('field', 'created', None), ('control', 'failed', 'lark_permission'),
        ('mapping', 'failed', 'lark_permission'), ('report', 'failed', 'lark_permission')]
    assert len(s.fake.rows(NODES)) == 1


def test_concurrent_double_press_creates_one_set(s):
    digest = preview(s)['preview_hash']
    s.who[0] = 'ou_pm'

    def press(rid):
        return s.client.post(SOP, json={'request_id': rid, 'preview_hash': digest})
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(press, ['a', 'b']))
    assert [r.status_code for r in results] == [200, 200]
    assert [r.json()['complete'] for r in results] == [True, True]
    assert len(s.fake.rows(NODES)) == 4 and len(s.fake.rows(TASKS)) == 4
    created = [r['task'] for res in results for r in res.json()['results']].count('created')
    assert created == 4


def test_existing_node_with_a_manual_task_still_gets_the_seed_task(s):
    node = s.fake.add(NODES, {'指派鍵': 'A115001-01|外業', '確認單編號': 'A115001-01', '節點': '外業', '狀態': '未開始'})
    s.fake.add(TASKS, {'標題': '手動任務', '內容': '現場確認', '節點指派': [node], '狀態': '待處理', '部門': '外業'})
    before = preview(s)['nodes'][0]
    assert (before['node_exists'], before['seed_task_exists'], before['will_create_node'], before['will_create_task']) == (
        True, False, False, True)
    body = start(s).json()
    assert body['results'][0] == {'key': 'field', 'node': 'existing', 'task': 'created', 'error': None, 'sync': 'ok'}
    assert sorted(f['標題'] for f in s.fake.tables[TASKS].values() if node in f['節點指派']) == [
        '外業：依計畫數量完成', '手動任務']
    assert len(s.fake.rows(NODES)) == 4


def test_a_cancelled_seed_task_is_ignored_and_a_live_one_is_honored(s):
    node = s.fake.add(NODES, {'指派鍵': 'A115001-01|外業', '確認單編號': 'A115001-01', '節點': '外業', '狀態': '未開始'})
    cancelled = s.fake.add(TASKS, {'標題': '外業：依計畫數量完成', '內容': 'x\n[SOP-START:v1:field]', '節點指派': [node],
                                   '狀態': '取消', '部門': '外業'})
    assert preview(s)['nodes'][0]['seed_task_exists'] is False
    start(s)
    live = [rid for rid, f in s.fake.tables[TASKS].items() if node in f['節點指派'] and f['狀態'] != '取消']
    assert len(live) == 1 and live[0] != cancelled
    s.fake.tables[TASKS][live[0]]['狀態'] = '進行中'
    again = preview(s)['nodes'][0]
    assert (again['seed_task_exists'], again['will_create_task']) == (True, False)
    assert start(s, 'r2').json()['started'] is False
    assert len(s.fake.rows(TASKS)) == 5


def edit_seed_detail(s, label, detail):
    rid = next(rid for rid, f in s.fake.tables[TASKS].items() if f['標題'].startswith(label))
    s.fake.tables[TASKS][rid]['內容'] = detail
    s.clock[0] += 3600  # the preview reads the cached snapshot until its TTL passes
    return rid


def test_a_seed_task_stays_the_seed_after_someone_edits_the_marker_away(s):
    start(s, 'r1')
    edit_seed_detail(s, '外業', '現場調整後的說明')
    again = preview(s)
    assert (again['already_started'], again['nodes'][0]['seed_task_exists'], again['nodes'][0]['will_create_task']) == (
        True, True, False)
    writes = len(s.fake.writes())
    body = start(s, 'r2').json()
    assert (body['started'], body['complete']) == (False, True)
    assert body['results'][0] == {'key': 'field', 'node': 'existing', 'task': 'existing', 'error': None, 'sync': 'ok'}
    assert len(s.fake.writes()) == writes and len(s.fake.rows(TASKS)) == 4


def test_a_cancelled_seed_counts_as_absent_even_without_its_marker(s):
    start(s, 'r1')
    rid = edit_seed_detail(s, '外業', '已取消的舊任務')
    s.fake.tables[TASKS][rid]['狀態'] = '取消'
    s.clock[0] += 3600
    assert preview(s)['nodes'][0]['will_create_task'] is True
    assert start(s, 'r2').json()['results'][0] == {'key': 'field', 'node': 'existing', 'task': 'created', 'error': None, 'sync': 'ok'}
    live = [f for f in s.fake.tables[TASKS].values() if f['標題'].startswith('外業') and f['狀態'] != '取消']
    assert len(live) == 1 and live[0]['內容'].endswith('[SOP-START:v1:field]')


def test_a_finished_node_is_not_given_a_task(s):
    done = s.fake.add(NODES, {'指派鍵': 'A115001-01|外業', '確認單編號': 'A115001-01', '節點': '外業', '狀態': '已完成',
                              '核准人': [{'id': 'ou_vp'}], '核准時間': date_millis('2026-10-01')})
    node = preview(s)['nodes'][0]
    assert (node['node_exists'], node['will_create_node'], node['will_create_task']) == (True, False, False)
    body = start(s).json()
    assert body['results'][0] == {'key': 'field', 'node': 'existing', 'task': 'skipped', 'error': None, 'sync': 'ok'}
    assert [f for f in s.fake.tables[TASKS].values() if done in f.get('節點指派', [])] == []
    assert len(s.fake.rows(NODES)) == 4 and len(s.fake.rows(TASKS)) == 3


def approve_earlier_nodes(s):
    for label in ('業務', 'PM', '確認單'):
        s.fake.add(NODES, {'指派鍵': f'A115001-01|{label}', '確認單編號': 'A115001-01', '節點': label, '狀態': '已完成',
                           '核准人': [{'id': 'ou_vp'}], '核准時間': date_millis('2026-10-01')})


def test_a_fresh_node_mirrors_its_derived_status_and_progress(s):
    start(s)
    nodes = {f['節點']: f for f in s.fake.rows(NODES).values()}
    assert [(nodes[k]['狀態'], nodes[k]['進度'], '開始時間' in nodes[k]) for k in ('外業', '控制', '圖資', '報告')] == [
        ('未開始', 0.0, False)] * 4


def test_start_derives_status_from_the_chain_and_never_forces_it(s):
    approve_earlier_nodes(s)
    s.fake.add(NODES, {'指派鍵': 'A115001-01|控制', '確認單編號': 'A115001-01', '節點': '控制', '狀態': '進行中'})
    start(s)
    nodes = {f['節點']: f for f in s.fake.rows(NODES).values()}
    assert (nodes['外業']['狀態'], nodes['外業']['進度'], '開始時間' in nodes['外業']) == ('待處理', 0.0, False)
    assert (nodes['控制']['狀態'], nodes['控制']['進度'], '開始時間' in nodes['控制']) == ('未開始', 0.0, False)
    assert nodes['報告']['狀態'] == '未開始'


def test_a_second_press_after_the_mirror_writes_nothing(s):
    start(s, 'r1')
    writes = len(s.fake.writes())
    assert start(s, 'r2').json()['started'] is False
    assert len(s.fake.writes()) == writes


def add_project(s, pid, number):
    s.case['others'][pid] = {**project(code=f'A11500{number}-01', pid=pid), 'pm_id': 'ou_pm'}
    s.state['derived_plan'][pid] = s.state['derived_plan']['p1']
    s.state['source_quotes'].append(quote('q-' + pid, project_id=pid, **DEADLINES))


def press(s, pid, rid):
    url = f'/api/projects/{pid}/node-assignments/start-sop'
    s.who[0] = 'ou_pm'
    digest = s.client.get(url).json()['preview_hash']
    return s.client.post(url, json={'request_id': rid, 'preview_hash': digest})


def test_the_person_limit_counts_every_lark_write_across_projects(s):
    for number, pid in enumerate(('p2', 'p3', 'p4'), start=2):
        add_project(s, pid, number)
    responses = [press(s, pid, 'r-' + pid) for pid in ('p1', 'p2', 'p3', 'p4')]
    assert [r.status_code for r in responses] == [200, 200, 200, 429]
    assert [[(x['node'], x['task'], x['error']) for x in r.json()['results']] for r in responses[:3]] == [
        [('created', 'created', None)] * 4, [('created', 'created', None)] * 4,
        [('created', 'created', None)] * 2 + [('failed', 'failed', 'rate_limited')] * 2]
    assert responses[3].json()['code'] == 'rate_limited'
    assert len(s.fake.writes()) == 30


def test_presses_that_write_nothing_cost_nothing(s):
    add_project(s, 'p2', 2)
    assert press(s, 'p1', 'first').json()['complete'] is True
    for n in range(12):
        assert press(s, 'p1', f'again-{n}').json()['started'] is False
    second = press(s, 'p2', 'second').json()
    assert [(x['node'], x['task'], x['error']) for x in second['results']] == [('created', 'created', None)] * 4
    assert len(s.fake.writes()) == 24


def test_every_run_leaves_an_audit_row_per_node(s):
    start(s, 'r1')
    rows = [(a[0], a[2]['result'], a[2]['node']) for a in s.audits()]
    assert rows == [('node_assignment.start_sop', 'success', k) for k in ('field', 'control', 'mapping', 'report')]


def test_ordinary_task_creation_still_costs_one_charge_per_call(s):
    codes = [act(s, 'ou_fm', '/nodes/field/tasks', {'request_id': f'c{n}', 'title': f'任務 {n}', 'department': '外業'}).status_code
             for n in range(31)]
    assert codes == [200] * 30 + [429]
    assert len(s.fake.rows(TASKS)) == 30


def test_replaying_a_finished_press_costs_nothing(s):
    first = start(s, 'same')
    for _ in range(40):
        replay = s.client.post(SOP, json={'request_id': 'same', 'preview_hash': preview(s)['preview_hash']})
        assert (replay.status_code, replay.json()) == (200, first.json())
    assert len(s.fake.writes()) == 12


def reject_the_first_node_update_after_the_field_task_create(s):
    def reject_node_update(request):
        node_id = json.loads(request.content)['fields']['節點指派'][0]
        s.fake.fault('PUT', f'{NODES}/records/{node_id}', lambda _: httpx.Response(400, json={'code': 1254001, 'msg': 'bad'}))
    s.fake.fault('POST', f'{TASKS}/records', reject_node_update)


def test_a_failed_node_sync_is_reported_and_a_later_press_retries_only_the_sync(s):
    reject_the_first_node_update_after_the_field_task_create(s)
    first = start(s, 'r1').json()
    assert (first['started'], first['complete']) == (True, False)
    assert [(r['key'], r['node'], r['task'], r['error'], r['sync']) for r in first['results']] == [
        ('field', 'created', 'created', None, 'failed'), ('control', 'created', 'created', None, 'ok'),
        ('mapping', 'created', 'created', None, 'ok'), ('report', 'created', 'created', None, 'ok')]
    assert '進度' not in next(f for f in s.fake.rows(NODES).values() if f['節點'] == '外業')
    writes = len(s.fake.writes())
    second = start(s, 'r2').json()
    assert second['complete'] is True
    assert [r['sync'] for r in second['results']] == ['ok'] * 4
    assert len(s.fake.writes()) == writes + 1
    assert len(field_tasks(s)) == 1 and len(s.fake.rows(TASKS)) == 4
    assert next(f for f in s.fake.rows(NODES).values() if f['節點'] == '外業')['進度'] == 0.0
    third = start(s, 'r3').json()
    assert (third['started'], third['complete']) == (False, True)
    assert len(s.fake.writes()) == writes + 1


def test_repeating_the_same_request_after_a_failed_sync_retries_it_too(s):
    reject_the_first_node_update_after_the_field_task_create(s)
    assert start(s, 'r1').json()['complete'] is False
    writes = len(s.fake.writes())
    again = start(s, 'r1').json()
    assert again['complete'] is True and len(s.fake.writes()) == writes + 1
    assert start(s, 'r1').json() == again
