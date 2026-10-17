import pytest

from .node_assignment.domain import NodeKey
from .node_assignment.evidence import evidence_for
from .test_node_assignment_routes import NODES, PEOPLE, URL, act, h, node, project, view  # noqa: F401

LABELS = {'sales': '業務', 'pm': 'PM', 'confirmation': '確認單', 'field': '外業', 'control': '控制',
          'mapping': '圖資', 'report': '報告', 'pricing': '計價', 'settlement': '結算'}
C_REASON = '工編以 C 開頭，業務階段已完成'


def lark_rows(h, code):
    """The nine rows Lark's 開啟SOP button creates: everything 未開始, nothing else."""
    for key, label in LABELS.items():
        h.fake.add(NODES, {'指派鍵': f'{code}|{label}', '確認單編號': code, '節點': label, '狀態': '未開始'})


def with_lines(h, count, pid='p1'):
    h.state['contract_items'] = [{'id': f'ct{i}', 'project_id': pid} for i in range(count)] + [
        {'id': 'other', 'project_id': 'p2'}]


def statuses(body):
    return [n['derived_status'] for n in body['nodes']]


def lark_statuses(h):
    return {f['節點']: f['狀態'] for f in h.fake.rows(NODES).values()}


def case(h, code, confirmation=True):
    h.case['project'] = {**project(code=code), **({} if confirmation else {'source_records': []})}


def test_c_code_marks_sales_done_without_writing_to_lark(h):
    case(h, 'C115264', confirmation=False)
    lark_rows(h, 'C115264')
    body = view(h)
    assert statuses(body) == ['已完成', '待處理'] + ['未開始'] * 7
    assert node(body, 'sales')['auto_done'] == {'rule': 'c_code', 'reason': C_REASON}
    assert node(body, 'sales')['progress'] == 1.0 and node(body, 'sales')['warnings'] == []
    assert all(n['auto_done'] is None for n in body['nodes'][1:])
    assert body['summary'] == {'done': 1, 'total': 9, 'current_node': 'pm'}
    assert set(lark_statuses(h).values()) == {'未開始'}
    assert h.fake.writes() == []


def test_lowercase_and_suffixed_c_codes_match(h):
    for code in ('c115238', 'C115238-01'):
        case(h, code, confirmation=False)
        assert view(h)['nodes'][0]['auto_done']['rule'] == 'c_code'


def test_confirmation_with_contract_lines_marks_the_three_early_nodes_done(h):
    case(h, '115588')
    with_lines(h, 3)
    lark_rows(h, '115588')
    body = view(h)
    assert statuses(body) == ['已完成'] * 3 + ['待處理'] + ['未開始'] * 5
    reason = '已建立工程確認單（3 筆合約工項）'
    assert [n['auto_done'] for n in body['nodes'][:3]] == [{'rule': 'confirmation_lines', 'reason': reason}] * 3
    assert body['summary'] == {'done': 3, 'total': 9, 'current_node': 'field'}
    assert h.fake.writes() == []


def test_c_code_with_confirmation_and_lines_keeps_the_first_matching_rule_per_node(h):
    case(h, 'C115264')
    with_lines(h, 1)
    body = view(h)
    assert [n['auto_done']['rule'] for n in body['nodes'][:3]] == ['c_code', 'confirmation_lines', 'confirmation_lines']
    assert statuses(body)[3] == '待處理'


@pytest.mark.parametrize('code, confirmation, lines', [
    ('115588', True, 0), ('115588', False, 2), ('A115001-01', True, 0), ('B115264', False, 0), ('1C115264', False, 0)])
def test_no_evidence_leaves_behaviour_unchanged(h, code, confirmation, lines):
    case(h, code, confirmation)
    with_lines(h, lines)
    body = view(h)
    assert statuses(body) == ['待處理'] + ['未開始'] * 8
    assert all(n['auto_done'] is None for n in body['nodes'])
    assert body['summary'] == {'done': 0, 'total': 9, 'current_node': 'sales'}


def test_an_app_skipped_node_stays_skipped_and_is_not_auto_done(h):
    h.case['project'] = {**project(code='C115264', skipped=('sales',)), 'source_records': []}
    body = view(h)
    assert statuses(body)[:2] == ['略過', '待處理']
    assert node(body, 'sales')['auto_done'] is None


def test_auto_done_beats_an_explicit_lark_rejection_on_the_early_nodes(h):
    case(h, 'C115264', confirmation=False)
    h.fake.add(NODES, {'指派鍵': 'C115264|業務', '確認單編號': 'C115264', '節點': '業務', '狀態': '待處理',
                       '退回原因': '資料有誤'})
    body = view(h)
    assert node(body, 'sales')['derived_status'] == '已完成'
    assert node(body, 'sales')['auto_done']['rule'] == 'c_code'


def test_actions_stay_illegal_on_an_auto_done_node(h):
    case(h, 'C115264', confirmation=False)
    lark_rows(h, 'C115264')
    overview = view(h, 'ou_vp')
    rev = node(overview, 'sales')['revision']
    can = overview['can']['sales']
    assert can == {'claim': False, 'assign': False, 'complete': False, 'approve': False, 'reject': False,
                   'create_task': False}
    for who, path, body in (('ou_sales', '/nodes/sales/claim', {'expected_revision': rev}),
                            ('ou_sm', '/nodes/sales/complete', {'expected_revision': rev}),
                            ('ou_vp', '/nodes/sales/reject', {'expected_revision': rev, 'reason': '再確認'}),
                            ('ou_vp', '/nodes/sales/assign', {'expected_revision': rev, 'owner_open_ids': ['ou_sales']}),
                            ('ou_sm', '/nodes/sales/tasks', {'title': 'x'})):
        response = act(h, who, path, {'request_id': 'r-' + path.rsplit('/', 1)[1], **body})
        assert response.status_code == 409, (path, response.text)
        assert response.json()['code'] == 'illegal_transition'
    assert h.fake.writes() == []


def test_completing_the_next_node_works_and_never_touches_the_untouched_early_rows(h):
    case(h, 'C115264', confirmation=False)
    lark_rows(h, 'C115264')
    row = next(rid for rid, f in h.fake.rows(NODES).items() if f['節點'] == 'PM')
    revision = node(view(h, 'ou_vp'), 'pm')['revision']
    response = act(h, 'ou_vp', '/nodes/pm/complete', {'request_id': 'c1', 'expected_revision': revision})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['node']['derived_status'] == '已完成'
    assert lark_statuses(h) == {**{label: '未開始' for label in LABELS.values()}, 'PM': '已完成'}
    assert h.fake.tables[NODES][row]['狀態'] == '已完成'
    after = view(h)
    assert statuses(after)[:4] == ['已完成', '已完成', '待處理', '未開始']
    assert after['summary'] == {'done': 2, 'total': 9, 'current_node': 'confirmation'}


def test_a_lazily_created_next_node_row_starts_with_the_evidence_aware_status(h):
    case(h, 'C115264', confirmation=False)
    h.fake.add(PEOPLE, {'姓名': '孫PM', '所屬組別': ['PM'], '職級': '組員', '在職': True,
                        'Lark帳號': [{'id': 'ou_pm'}], '同步_OpenID': 'ou_pm'})
    response = act(h, 'ou_pm', '/nodes/pm/claim', {'request_id': 'k1', 'expected_revision': None})
    assert response.status_code == 200, response.text
    assert {f['節點']: f['狀態'] for f in h.fake.rows(NODES).values()} == {'PM': '待處理'}
    assert response.json()['node']['derived_status'] == '待處理'


def test_pure_rules(h):
    pm_only = {'id': 'p1', 'code': 'C115264', 'source_records': []}
    found = evidence_for(pm_only, {})
    assert list(found) == [NodeKey.SALES] and found[NodeKey.SALES].reason_zh == C_REASON
    assert found[NodeKey.SALES].rule == 'c_code'
    by_state = {'source_confirmations': [{'id': 'sc', 'project_id': 'p1', 'source_kind': 'confirmation'}],
                'contract_items': [{'id': 'a', 'project_id': 'p1'}, {'id': 'b', 'project_id': 'p1'}]}
    assert set(evidence_for({'id': 'p1', 'code': '115588'}, by_state)) == {NodeKey.SALES, NodeKey.PM, NodeKey.CONFIRMATION}
    assert evidence_for({'id': 'p1', 'code': '115588'}, {'contract_items': by_state['contract_items']}) == {}
    assert evidence_for({'id': 'p1', 'code': ''}, {}) == {}
    assert evidence_for({'id': 'p1'}, {}) == {}
