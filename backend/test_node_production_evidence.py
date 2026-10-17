"""Production nodes (外業/控制/圖資/報告) take status and numbers from the case's own source evidence."""
from decimal import Decimal

import pytest

from .node_assignment.domain import NodeFacts, NodeKey, NodeStatus, TaskStatus, derive_chain, derive_status
from .node_assignment.evidence import Signal, production_signal
from .test_node_assignment_evidence import case, lark_rows, lark_statuses, statuses, with_lines
from .test_node_assignment_routes import NODES, PEOPLE, URL, act, h, node, project, view  # noqa: F401
from .test_node_assignment_start_sop import SOP, counts, preview, s, set_plan, start  # noqa: F401

DEPT = {'field': '外業組', 'control': '控制組', 'mapping': '圖資組', 'report': '報告組'}
NO_DAILY = '尚無日報連結到此案件'


def daily(h, key, *dates, points=2.5, pid_project=None):
    rows = [{'id': f'{key}-{i}', 'date': d, 'department': DEPT[key], 'points': points} for i, d in enumerate(dates)]
    h.case['project'] = {**h.case['project'], 'daily_reports': [*h.case['project'].get('daily_reports', []), *rows]}


def open_case(h, code='115588'):
    """Early nodes are proven done by the confirmation and its lines, so 外業 is the first open node."""
    case(h, code)
    with_lines(h, 3)
    set_plan(h)


def evidence_of_node(body, key):
    return node(body, key)['evidence']


def test_mapped_field_rows_and_no_tasks_start_the_field_node_by_evidence(h):
    open_case(h)
    lark_rows(h, '115588')
    daily(h, 'field', '2026-10-08', '2026-10-12')
    body = view(h)
    assert statuses(body)[:5] == ['已完成'] * 3 + ['進行中', '未開始']
    field = node(body, 'field')
    assert field['evidence'] == {
        'planned_qty': '123.45', 'lines': 2, 'items': 5, 'work_orders': 2, 'latest_date': '2026-10-12',
        'actual_known': True, 'actual_value': '5', 'actual_source': 'v4_daily',
        'reason': '已有 2 筆日報連結到此案件', 'drives_status': True}
    assert field['can_submit_hint'] is False
    assert field['tasks'] == {'done': 0, 'total': 0} and field['status'] == '未開始'
    assert field['warnings'] == []
    assert body['summary'] == {'done': 3, 'total': 9, 'current_node': 'field'}
    assert set(lark_statuses(h).values()) == {'未開始'}
    assert h.fake.writes() == []


def test_no_rows_leave_the_node_pending_and_say_so_without_a_zero(h):
    open_case(h)
    body = view(h)
    assert statuses(body)[3] == '待處理'
    field = node(body, 'field')
    assert field['evidence'] == {
        'planned_qty': '123.45', 'lines': 2, 'items': 5, 'work_orders': 0, 'latest_date': None,
        'actual_known': False, 'actual_value': None, 'actual_source': None, 'reason': NO_DAILY, 'drives_status': False}
    assert field['can_submit_hint'] is False and field['progress'] == 0.0


def test_non_production_nodes_carry_no_evidence(h):
    open_case(h)
    body = view(h)
    for key in ('sales', 'pm', 'confirmation', 'pricing', 'settlement'):
        assert (node(body, key)['evidence'], node(body, key)['can_submit_hint']) == (None, False)


def test_evidence_never_yields_review_or_done_however_much_work_is_reported(h):
    open_case(h)
    daily(h, 'field', *[f'2026-10-{d:02d}' for d in range(1, 11)], points=50)
    field = node(view(h), 'field')
    assert field['derived_status'] == '進行中' and field['approver'] is None and field['approved_at'] is None
    assert field['evidence']['actual_value'] == '500'
    assert field['can_submit_hint'] is True


def test_can_submit_hint_needs_a_known_actual_at_least_the_plan(h):
    open_case(h)
    set_plan(h, 外業=counts('10', 1, 1))
    daily(h, 'field', '2026-10-01', points=9.99)
    assert node(view(h), 'field')['can_submit_hint'] is False
    h.case['project']['daily_reports'][0]['points'] = 10
    assert node(view(h), 'field')['can_submit_hint'] is True
    h.case['project']['daily_reports'][0]['points'] = None
    unknown = node(view(h), 'field')
    assert (unknown['derived_status'], unknown['can_submit_hint'], unknown['evidence']['actual_known']) == ('進行中', False, False)
    assert unknown['evidence']['actual_value'] is None
    assert unknown['evidence']['reason'] == '已有 1 筆日報連結到此案件'


def test_can_submit_hint_is_off_with_no_plan_or_a_zero_plan(h):
    open_case(h)
    set_plan(h, 外業=counts('0'))
    daily(h, 'field', '2026-10-01', points=3)
    assert node(view(h), 'field')['can_submit_hint'] is False
    h.state.pop('derived_plan')
    unplanned = node(view(h), 'field')
    assert (unplanned['evidence']['planned_qty'], unplanned['evidence']['lines'], unplanned['can_submit_hint']) == (None, None, False)
    assert unplanned['derived_status'] == '進行中'


@pytest.mark.parametrize('key, label', [('control', '控制'), ('mapping', '圖資'), ('report', '報告')])
def test_each_later_production_node_is_started_only_by_its_own_category(h, key, label):
    open_case(h)
    lark_rows(h, '115588')
    for earlier in ('field', 'control', 'mapping', 'report'):
        if earlier != key:
            daily(h, earlier, '2026-10-05')
    body = view(h)
    assert evidence_of_node(body, key)['work_orders'] == 0 and evidence_of_node(body, key)['drives_status'] is False
    assert node(body, key)['derived_status'] != '進行中'
    daily(h, key, '2026-10-09')
    assert evidence_of_node(view(h), key)['work_orders'] == 1


def test_a_later_node_stays_not_started_until_the_earlier_ones_are_finished(h):
    open_case(h)
    daily(h, 'control', '2026-10-09')
    body = view(h)
    assert statuses(body)[3:5] == ['待處理', '未開始']
    assert evidence_of_node(body, 'control')['work_orders'] == 1 and evidence_of_node(body, 'control')['drives_status'] is False


def approve(h, label):
    for rid, fields in h.fake.rows(NODES).items():
        if fields['節點'] == label:
            h.fake.tables[NODES][rid].update({'狀態': '已完成', '核准人': [{'id': 'ou_vp'}], '核准時間': 1_790_000_000_000})


def test_once_field_is_approved_control_starts_by_its_own_rows(h):
    open_case(h)
    lark_rows(h, '115588')
    daily(h, 'field', '2026-10-01')
    daily(h, 'control', '2026-10-09')
    approve(h, '外業')
    body = view(h)
    assert statuses(body)[3:6] == ['已完成', '進行中', '未開始']
    assert evidence_of_node(body, 'control')['drives_status'] is True
    assert evidence_of_node(body, 'field')['drives_status'] is False


def test_an_approved_row_rejected_row_and_a_skip_all_beat_the_evidence(h):
    open_case(h)
    lark_rows(h, '115588')
    daily(h, 'field', '2026-10-08')
    approve(h, '外業')
    assert node(view(h), 'field')['derived_status'] == '已完成'
    for rid, fields in h.fake.rows(NODES).items():
        if fields['節點'] == '外業':
            row = h.fake.tables[NODES][rid]
            row.pop('核准人'), row.pop('核准時間')
            row.update({'狀態': '待處理', '退回原因': '重測'})
    h.clock[0] += 1000
    rejected = node(view(h), 'field')
    assert (rejected['derived_status'], rejected['reject_reason']) == ('進行中', '重測')
    assert rejected['evidence']['drives_status'] is False
    h.case['project'] = {**project(code='115588', skipped=('field',)), 'daily_reports': h.case['project']['daily_reports']}
    h.clock[0] += 1000
    skipped = node(view(h), 'field')
    assert (skipped['derived_status'], skipped['evidence'], skipped['can_submit_hint']) == ('略過', None, False)


def create_task(h, rid='t1'):
    response = act(h, 'ou_fm', '/nodes/field/tasks', {'request_id': rid, 'title': '控制點佈設', 'assignee_open_id': 'ou_depth'})
    assert response.status_code == 200, response.text
    return response.json()


def test_tasks_keep_their_semantics_and_a_finished_task_set_still_awaits_review(h):
    open_case(h)
    daily(h, 'field', '2026-10-08')
    body = create_task(h)
    assert body['node']['derived_status'] == '進行中' and body['node']['evidence']['drives_status'] is True
    task = body['tasks'][0]
    finished = act(h, 'ou_depth', f'/nodes/field/tasks/{task["id"]}',
                   {'request_id': 'p1', 'expected_revision': task['revision'], 'status': '已完成'}, method='patch')
    assert finished.status_code == 200, finished.text
    assert finished.json()['node']['derived_status'] == '待審核'
    assert finished.json()['node']['evidence']['drives_status'] is False
    assert finished.json()['node']['can_submit_hint'] is False


def test_a_started_task_decides_the_status_so_the_evidence_does_not(h):
    open_case(h)
    daily(h, 'field', '2026-10-08')
    task = create_task(h)['tasks'][0]
    started = act(h, 'ou_depth', f'/nodes/field/tasks/{task["id"]}',
                  {'request_id': 'p1', 'expected_revision': task['revision'], 'status': '進行中'}, method='patch')
    assert started.json()['node']['derived_status'] == '進行中'
    assert started.json()['node']['evidence']['drives_status'] is False


def test_a_node_action_syncs_the_evidence_status_only_onto_the_touched_row(h):
    open_case(h)
    lark_rows(h, '115588')
    daily(h, 'field', '2026-10-08')
    daily(h, 'control', '2026-10-09')
    revision = node(view(h, 'ou_fm'), 'field')['revision']
    response = act(h, 'ou_fm', '/nodes/field/assign', {'request_id': 'a1', 'expected_revision': revision,
                                                       'owner_open_ids': ['ou_member']})
    assert response.status_code == 200, response.text
    assert response.json()['node']['derived_status'] == '進行中'
    assert lark_statuses(h)['外業'] == '進行中'
    assert {v for k, v in lark_statuses(h).items() if k != '外業'} == {'未開始'}


def test_the_reject_guard_still_only_protects_auto_done_nodes(h):
    open_case(h)
    daily(h, 'field', '2026-10-08')
    overview = view(h, 'ou_vp')
    assert overview['can']['field']['complete'] is True
    assert overview['can']['field']['reject'] is False  # nothing to reject on an open node


def test_signal_is_pure_decimal_safe_and_does_not_read_a_missing_plan_as_zero():
    proj = {'id': 'p1', 'code': '115588', 'daily_reports': [
        {'id': 'a', 'date': '2026-10-02', 'department': '外業組', 'points': 0.1},
        {'id': 'b', 'date': '2026-10-09', 'department': '外業組', 'points': 0.2},
        {'id': 'c', 'date': '2026-10-11', 'department': '外業組', 'source_missing': True, 'points': 99},
        {'id': 'd', 'date': '2026-10-01', 'department': '控制組', 'points': None}]}
    found = production_signal(proj, {})
    assert list(found) == [NodeKey.FIELD, NodeKey.CONTROL, NodeKey.MAPPING, NodeKey.REPORT]
    field = found[NodeKey.FIELD]
    assert (field.work_orders, field.latest_date, field.actual_value, field.started, field.planned_qty) == (
        2, '2026-10-09', '0.3', True, None)
    control = found[NodeKey.CONTROL]
    assert (control.started, control.actual_known, control.actual_value) == (True, False, None)
    assert found[NodeKey.MAPPING] == Signal(None, None, None, 0, None, False, None, None, False, '此案件的日報沒有歸屬到圖資')
    assert production_signal({'id': 'p1'}, {})[NodeKey.MAPPING].reason_zh == NO_DAILY
    assert Signal('0.3', 1, 1, 1, None, True, '0.3', 'v4_daily', True, '').can_submit is True


class StubReports:
    def __init__(self, cases, totals):
        self.cases, self.totals = cases, totals

    def case(self, code):
        return {'case_key': 'rec' + code, 'case_code': code, 'status': '未填'} if code in self.cases else None

    def field_total(self, code):
        return self.totals.get(code)


def test_the_unambiguous_v3_cumulative_actual_starts_only_the_field_node():
    proj = {'id': 'p1', 'code': '115588', 'daily_reports': [], 'quotes': []}
    found = production_signal(proj, {}, StubReports({'115588'}, {'115588': 3.5}))
    assert (found[NodeKey.FIELD].started, found[NodeKey.FIELD].actual_value, found[NodeKey.FIELD].actual_source) == (
        True, '3.5', 'v3_reports')
    assert found[NodeKey.FIELD].reason_zh == '週報登記冊顯示此案件外業累計大於 0'
    assert not any(found[k].started for k in (NodeKey.CONTROL, NodeKey.MAPPING, NodeKey.REPORT))


def test_two_v3_candidates_or_a_zero_total_are_not_evidence():
    proj = {'id': 'p1', 'code': '115588', 'daily_reports': [], 'quotes': [{'quote_code': 'Q-1'}]}
    both = StubReports({'115588', 'Q-1'}, {'115588': 3, 'Q-1': 4})
    assert production_signal(proj, {}, both)[NodeKey.FIELD].started is False
    assert production_signal({**proj, 'quotes': []}, {}, StubReports({'115588'}, {'115588': 0}))[NodeKey.FIELD].started is False
    assert production_signal(proj, {}, None)[NodeKey.FIELD].started is False


def test_a_cold_register_adds_no_evidence_and_never_blocks(h):
    open_case(h)
    from .project_progress import ReportsView
    assert ReportsView(None, warm=False).status == 'disabled'

    class Cold:
        def peek(self):
            return None

        def meta(self, *_):
            return {}

        def start(self):
            raise AssertionError('a node read must not warm the register')
    view_ = ReportsView(Cold(), warm=False)
    assert (view_.status, view_.case('115588'), view_.field_total('115588')) == ('cold', None, None)
    assert production_signal({'id': 'p1', 'code': '115588'}, {}, view_)[NodeKey.FIELD].started is False


def test_v3_figures_follow_the_reports_gate_but_the_status_does_not(h):
    open_case(h)
    lark_rows(h, '115588')
    reports = StubReports({'115588'}, {'115588': 4})
    for visible in (True, False):
        client = h.build(reports=lambda: reports, reports_visible=lambda _user, v=visible: v)
        h.clock[0] += 1000
        field = node(client.get(URL).json(), 'field')
        assert (field['derived_status'], field['evidence']['drives_status'], field['evidence']['actual_known']) == ('進行中', True, True)
        assert field['evidence']['actual_source'] == 'v3_reports'
        assert field['evidence']['actual_value'] == ('4' if visible else None)
        assert field['evidence']['work_orders'] == 0
        detail = client.get(URL + '/nodes/field').json()['node']
        assert detail['evidence']['actual_value'] == ('4' if visible else None)


def test_pure_status_rules():
    base = NodeFacts()
    assert derive_status(NodeFacts(evidence_started=True), True) is NodeStatus.IN_PROGRESS
    assert derive_status(NodeFacts(evidence_started=True), False) is NodeStatus.NOT_STARTED
    assert derive_status(NodeFacts(evidence_started=True, approved=True), True) is NodeStatus.DONE
    assert derive_status(NodeFacts(evidence_started=True, skipped=True), True) is NodeStatus.SKIPPED
    assert derive_status(NodeFacts(evidence_started=True, tasks=(TaskStatus.DONE,)), True) is NodeStatus.IN_REVIEW
    assert derive_status(NodeFacts(evidence_started=True, tasks=(TaskStatus.TODO,)), True) is NodeStatus.IN_PROGRESS
    assert derive_status(NodeFacts(evidence_started=True, tasks=(TaskStatus.CANCELLED,)), True) is NodeStatus.IN_PROGRESS
    assert derive_status(base, True) is NodeStatus.TODO
    assert derive_chain({NodeKey.SALES: NodeFacts(approved=True), NodeKey.PM: NodeFacts(evidence_started=True)})[NodeKey.PM] is NodeStatus.IN_PROGRESS
