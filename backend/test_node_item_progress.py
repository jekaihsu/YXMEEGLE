"""A production node card carries the progress of its fill items, taken from Lark's own revenue points."""
import pytest

from .node_assignment.domain import NodeKey
from .node_assignment.evidence import ITEM_POINTS_SOURCE, QUANTITY_SOURCE, Signal, production_signal
from .test_node_assignment_evidence import statuses
from .test_node_assignment_routes import URL, act, h, node, project  # noqa: F401
from .test_node_assignment_start_sop import set_plan
from .test_node_production_evidence import approve, create_task, lark_rows, open_case


def points_plan(h, rows, **plan):
    """rows are (category, code, name, qty, planned_points, remaining_points); None leaves the field out like Lark does."""
    lines, items = [], []
    for i, (category, code, name, qty, planned, remaining) in enumerate(rows):
        lines.append({'id': f'ln{i}', 'project_id': 'p1', 'fields': {'工編號碼': code, category + '工項': name, category + '數量': qty}})
        item = {'id': f'b/t/rec{i}', 'category': category, 'line_id': f'ln{i}', 'basis': 'native', 'reason': 'native_link_present'}
        item.update({k: v for k, v in (('planned_points', planned), ('remaining_points', remaining)) if v is not None})
        items.append(item)
    h.state['contract_items'] = lines
    h.state['derived_plan']['p1'].update(items=items, **plan)


@pytest.fixture
def full(h):
    """The same case as a PM sees it: the reports gate is open."""
    open_case(h)
    return h, h.build(reports_visible=lambda _user: True)


def field_of(client, h):
    h.clock[0] += 1000
    return node(client.get(URL).json(), 'field')


PARTIAL = [('外業', 'C1-1', '導線測量', '50', '100', '40'), ('外業', 'C1-2', '水準測量', '5', '100', '100')]
DONE_ALL = [('外業', 'C1-1', '導線測量', '50', '100', '0'), ('外業', 'C1-2', '水準測量', '5', '4.5', '0')]


def test_one_partial_item_starts_the_node_by_evidence_and_shows_the_percent(full):
    h, client = full
    points_plan(h, PARTIAL)
    field = field_of(client, h)
    assert field['derived_status'] == '進行中'
    evidence = field['evidence']
    assert evidence['work_orders'] == 0 and evidence['drives_status'] is True and evidence['actual_known'] is False
    assert evidence['reason'] == '合約填報工項已有進度（來源剩餘營業額小於對應營業額）'
    assert evidence['progress'] == {'percent': '30', 'earned_points': '60', 'planned_points': '200', 'items_done': 0, 'items_total': 2, 'known_items': 1, 'unknown_items': 1}
    assert evidence['items_total'] == 2 and evidence['items_truncated'] is False
    assert evidence['work_items'] == [
        {'code': 'C1-1', 'name': '導線測量', 'planned_qty': '50', 'planned_points': '100', 'remaining_points': '40', 'status': 'partial', 'link_basis': 'native', 'linked_reports': []},
        {'code': 'C1-2', 'name': '水準測量', 'planned_qty': '5', 'planned_points': '100', 'remaining_points': '100', 'status': 'no_signal', 'link_basis': 'native', 'linked_reports': []}]
    assert field['can_submit_hint'] is False
    assert h.fake.writes() == []


def test_every_item_done_offers_the_submit_hint_but_never_review_or_done(full):
    h, client = full
    points_plan(h, DONE_ALL)
    field = field_of(client, h)
    assert field['can_submit_hint'] is True
    assert (field['derived_status'], field['approver'], field['approved_at'], field['finished_at']) == ('進行中', None, None, None)
    assert field['evidence']['progress'] == {'percent': '100', 'earned_points': '104.5', 'planned_points': '104.5', 'items_done': 2, 'items_total': 2, 'known_items': 2, 'unknown_items': 0}
    assert [i['status'] for i in field['evidence']['work_items']] == ['done', 'done']
    assert statuses(client.get(URL).json())[3] == '進行中'


@pytest.mark.parametrize('rows', [
    [('外業', 'C1-1', 'a', '5', '100', '100')],
    [('外業', 'C1-1', 'a', '5', '100', None)],
    [('外業', 'C1-1', 'a', '5', None, '40')],
    [('外業', 'C1-1', 'a', '5', None, None)],
    [('外業', 'C1-1', 'a', '5', '100', '120')],
], ids=['remaining-equals-plan', 'remaining-absent', 'plan-absent', 'both-absent', 'remaining-above-plan'])
def test_no_signal_is_not_zero_percent_and_does_not_start_the_node(full, rows):
    h, client = full
    points_plan(h, rows)
    field = field_of(client, h)
    assert field['derived_status'] == '待處理'
    assert field['evidence']['progress'] is None and field['evidence']['drives_status'] is False
    assert [i['status'] for i in field['evidence']['work_items']] == ['no_signal']
    assert (field['can_submit_hint'], field['evidence']['reason']) == (False, '尚無日報連結到此案件')


def test_a_snapshot_from_before_the_field_existed_has_no_progress(full):
    h, client = full
    set_plan(h)
    for plan in h.state['derived_plan'].values():
        plan['items'] = [{'id': 'b/t/old', 'category': '外業', 'line_id': None, 'basis': 'native', 'reason': 'native_link_present'}]
    field = field_of(client, h)
    assert field['evidence']['progress'] is None and field['derived_status'] == '待處理'
    assert field['evidence']['work_items'][0]['planned_points'] is None and field['evidence']['work_items'][0]['status'] == 'no_signal'


def test_one_unknown_item_keeps_the_hint_off_even_when_the_others_are_done(full):
    h, client = full
    points_plan(h, [*DONE_ALL, ('外業', 'C1-3', 'c', '1', '10', None)])
    field = field_of(client, h)
    assert field['can_submit_hint'] is False
    assert field['evidence']['progress']['items_done'] == 2 and field['evidence']['progress']['items_total'] == 3
    assert field['evidence']['progress']['percent'] == '99.9'   # the unknown item is left out, and 100 is kept for all done


def test_a_truncated_plan_gives_no_percent_and_no_hint(full):
    h, client = full
    points_plan(h, DONE_ALL, truncated=True)
    field = field_of(client, h)
    assert field['can_submit_hint'] is False and field['evidence']['progress'] is None
    assert field['derived_status'] == '待處理'


def test_approval_and_tasks_keep_their_precedence_over_the_hint(full):
    h, client = full
    lark_rows(h, '115588')
    points_plan(h, DONE_ALL)
    assert field_of(client, h)['can_submit_hint'] is True
    approve(h, '外業')
    h.clock[0] += 1000
    approved = field_of(client, h)
    assert (approved['derived_status'], approved['can_submit_hint']) == ('已完成', False)
    assert approved['evidence']['drives_status'] is False


def test_a_finished_task_set_still_awaits_review_and_hides_the_hint(h):
    open_case(h)
    points_plan(h, DONE_ALL)
    task = create_task(h)['tasks'][0]
    finished = act(h, 'ou_depth', f'/nodes/field/tasks/{task["id"]}',
                   {'request_id': 'p1', 'expected_revision': task['revision'], 'status': '已完成'}, method='patch')
    node_ = finished.json()['node']
    assert (node_['derived_status'], node_['can_submit_hint']) == ('待審核', False)


def test_each_category_reads_only_its_own_items(full):
    h, client = full
    points_plan(h, [('外業', 'C1-1', 'f', '5', '10', '10'), ('控制', 'C1-1', 'c', '5', '10', '0'), ('報告', 'C1-1', 'r', '1', '3', '1')])
    body = client.get(URL).json()
    progress = {k: node(body, k)['evidence']['progress'] for k in ('field', 'control', 'mapping', 'report')}
    assert progress['field'] is None and progress['mapping'] is None
    assert progress['control'] == {'percent': '100', 'earned_points': '10', 'planned_points': '10', 'items_done': 1, 'items_total': 1, 'known_items': 1, 'unknown_items': 0}
    assert progress['report']['percent'] == '66.7'
    assert node(body, 'control')['can_submit_hint'] is False   # not started: 外業 is still the open node
    assert node(body, 'field')['derived_status'] == '待處理'


def test_work_items_are_capped_at_fifty_but_counted_fully(full):
    h, client = full
    points_plan(h, [('外業', f'C1-{i}', f'n{i}', '1', '10', '5') for i in range(60)])
    evidence = field_of(client, h)['evidence']
    assert (len(evidence['work_items']), evidence['items_total'], evidence['items_truncated']) == (50, 60, True)
    assert evidence['progress'] == {'percent': '50', 'earned_points': '300', 'planned_points': '600', 'items_done': 0, 'items_total': 60, 'known_items': 60, 'unknown_items': 0}


def test_a_viewer_without_the_reports_gate_gets_statuses_and_counts_but_no_points(h):
    open_case(h)
    points_plan(h, PARTIAL)
    gated = h.client   # the default test identity has no reports gate
    for body in (gated.get(URL).json()['nodes'], [gated.get(URL + '/nodes/field').json()['node']]):
        field = next(n for n in body if n['key'] == 'field')
        assert field['derived_status'] == '進行中' and field['evidence']['drives_status'] is True
        assert field['evidence']['progress'] == {'percent': None, 'earned_points': None, 'planned_points': None, 'items_done': 0, 'items_total': 2, 'known_items': 1, 'unknown_items': 1}
        assert [(i['planned_qty'], i['planned_points'], i['remaining_points'], i['status']) for i in field['evidence']['work_items']] == [
            ('50', None, None, 'partial'), ('5', None, None, 'no_signal')]


def test_the_gated_hint_still_appears_for_everyone(h):
    open_case(h)
    points_plan(h, DONE_ALL)
    h.clock[0] += 1000
    field = node(h.client.get(URL).json(), 'field')
    assert field['can_submit_hint'] is True and field['evidence']['progress']['percent'] is None
    assert field['evidence']['progress']['items_done'] == 2


def test_signal_hint_sources_are_separate():
    base = dict(planned_qty='0.3', lines=1, items=1, work_orders=1, latest_date=None, actual_known=True, actual_value='0.3', started=True, reason_zh='')
    assert Signal(**base, actual_source=QUANTITY_SOURCE).complete_by == QUANTITY_SOURCE
    assert Signal(**base, actual_source='v4_daily').complete_by is None
    assert Signal(**base, actual_source='v4_daily', items_all_done=True).complete_by == ITEM_POINTS_SOURCE
    assert Signal(**{**base, 'planned_qty': None, 'actual_known': False}, actual_source=None, items_all_done=True).can_submit is True


def test_production_signal_without_a_plan_is_unchanged():
    found = production_signal({'id': 'p1', 'code': '115588', 'daily_reports': []}, {})
    assert all((s.progress, s.item_rows, s.items_total, s.items_all_done) == (None, (), 0, False) for s in found.values())
    assert list(found) == [NodeKey.FIELD, NodeKey.CONTROL, NodeKey.MAPPING, NodeKey.REPORT]


def with_basis(h, *bases):
    for item, basis in zip(h.state['derived_plan']['p1']['items'], bases):
        item['basis'] = basis


@pytest.mark.parametrize('basis', ['ambiguous', 'unlinked'])
def test_an_uncertain_item_is_listed_but_never_starts_the_node(full, basis):
    h, client = full
    points_plan(h, [('外業', 'C1-1', 'a', '5', '100', '40')])
    with_basis(h, basis)
    field = field_of(client, h)
    assert field['derived_status'] == '待處理'
    assert field['evidence']['progress'] is None and field['evidence']['drives_status'] is False
    row, = field['evidence']['work_items']
    assert (row['status'], row['link_basis'], row['planned_points'], row['remaining_points']) == ('no_signal', basis, None, None)


@pytest.mark.parametrize('basis', ['ambiguous', 'unlinked'])
def test_an_uncertain_done_item_alone_gives_no_submit_hint(full, basis):
    h, client = full
    points_plan(h, [('外業', 'C1-1', 'a', '5', '100', '0')])
    with_basis(h, basis)
    assert field_of(client, h)['can_submit_hint'] is False


def test_an_uncertain_item_beside_certain_done_items_keeps_the_hint_off_and_out_of_the_percent(full):
    h, client = full
    points_plan(h, [*DONE_ALL, ('外業', 'C1-3', 'c', '1', '100', '0')])
    with_basis(h, 'native', 'derived', 'unlinked')
    field = field_of(client, h)
    assert field['can_submit_hint'] is False
    assert field['evidence']['progress'] == {'percent': '99.9', 'earned_points': '104.5', 'planned_points': '104.5', 'items_done': 2,
                                             'items_total': 3, 'known_items': 2, 'unknown_items': 1}
    assert [i['status'] for i in field['evidence']['work_items']] == ['done', 'done', 'no_signal']


def test_derived_items_keep_their_labels_when_the_contract_line_has_no_project(full):
    h, client = full
    points_plan(h, [('外業', 'C1-1', '導線測量', '50', '100', '40')])
    with_basis(h, 'derived')
    h.state['contract_items'][0]['project_id'] = None
    row, = field_of(client, h)['evidence']['work_items']
    assert (row['code'], row['name'], row['planned_qty']) == ('C1-1', '導線測量', '50')


def test_a_line_of_another_case_never_labels_the_item(full):
    h, client = full
    points_plan(h, [('外業', 'C1-1', '導線測量', '50', '100', '40')])
    h.state['contract_items'][0]['project_id'] = 'other-case'
    row, = field_of(client, h)['evidence']['work_items']
    assert (row['code'], row['name']) == (None, None)
