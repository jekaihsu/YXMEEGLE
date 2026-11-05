from datetime import datetime

from .node_assignment.domain import Actor, NodeKey, NodeStatus, TaskStatus
from .node_assignment.lark_table import CaseSnapshot, TAIPEI, parse_node, parse_task
from .node_assignment.views import case_view, node_detail, node_view, task_sort_key


NOW = int(datetime(2026, 10, 15, 0, 5, tzinfo=TAIPEI).timestamp() * 1000)


def task(ident, deadline=None, status='待處理'):
    fields = {'標題': ident, '節點指派': ['recNode'], '狀態': status, '部門': '圖報A'}
    if deadline:
        fields['截止日'] = int(datetime.fromisoformat(deadline).replace(tzinfo=TAIPEI).timestamp() * 1000)
    return parse_task({'record_id': ident, 'fields': fields})


def snapshot(tasks=()):
    row = parse_node({'record_id': 'recNode', 'fields': {'指派鍵': 'C115264|業務', '狀態': '待處理'}})
    return CaseSnapshot('C115264', {NodeKey.SALES: (row,)}, {'recNode': tuple(tasks)})


def test_next_due_is_the_earliest_open_task_and_deadline_keeps_the_last_task_date():
    data = snapshot([task('recDone', '2026-10-30', '已完成'), task('recOpen', '2026-10-16'),
                     task('recEarly', '2026-10-14'), task('recCancel', '2026-12-31', '取消')])
    view = node_view(NodeKey.SALES, data, NodeStatus.IN_PROGRESS, NOW)
    assert (view['next_due'], view['deadline'], view['deadline_basis']) == (
        '2026-10-14', '2026-10-30', 'related_tasks_max')
    assert view['tasks'] == {'done': 1, 'total': 3}
    assert (view['origin'], view['assignment_key']) == ('lark', 'C115264|業務')


def test_empty_task_table_preserves_missing_dates_without_local_template_counts():
    data = snapshot()
    _, case = case_view(data, set(), Actor(None, 'ou_viewer'), False, NOW)
    assert len(case['nodes']) == 9
    assert case['nodes'][0]['tasks'] == {'done': 0, 'total': 0}
    assert case['nodes'][0]['deadline'] is None
    assert case['nodes'][0]['next_due'] is None
    assert case['nodes'][1]['record_id'] is None
    assert case['nodes'][1]['status'] is None
    assert case['nodes'][1]['assignment_key'] is None


def test_task_order_uses_taipei_date_status_priority_null_last_and_literal_ties():
    rows = [task('recNull'), task('recDone', '2026-10-01', '已完成'),
            task('recB', '2026-10-14'), task('recA', '2026-10-14'),
            task('recActive', '2026-10-14', '進行中'), task('recToday', '2026-10-15'),
            task('recCancel', '2026-09-01', '取消')]
    assert [t.record_id for t in sorted(rows, key=lambda t: task_sort_key(t, NOW))] == [
        'recActive', 'recA', 'recB', 'recCancel', 'recDone', 'recToday', 'recNull']
    detail = node_detail(snapshot(rows), set(), Actor(None, 'ou_viewer'), None, NodeKey.SALES, False, NOW)
    assert [t['id'] for t in detail['tasks']] == [
        'recActive', 'recA', 'recB', 'recCancel', 'recDone', 'recToday', 'recNull']
    assert detail['tasks'][0]['department'] == '圖報A'
    assert detail['tasks'][0]['can'] == {
        'edit_status': False, 'cancel': False, 'assign': False, 'claim': False, 'edit_details': False}


def test_only_done_or_cancelled_tasks_have_no_next_due():
    data = snapshot([task('recDone', '2026-10-16', TaskStatus.DONE.value),
                     task('recCancel', '2026-10-17', TaskStatus.CANCELLED.value)])
    view = node_view(NodeKey.SALES, data, NodeStatus.IN_REVIEW, NOW)
    assert view['next_due'] is None
    assert view['deadline'] == '2026-10-16'
