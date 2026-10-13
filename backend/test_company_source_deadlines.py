"""VCC-119: source deadlines past due on cases without execution authority stay visible, in three distinct buckets, and never merge into workload."""
from datetime import datetime, timezone
from .company_dashboard import overview

CLOCK = datetime(2026, 10, 13, tzinfo=timezone.utc)


def case(ident, *, intake=False, source_status='', runnable=False, dues=('2026-09-10',), relationship=None):
    lifecycle = {'relationship': relationship or ('待確認單' if intake else '已關聯確認單'), 'state': 'needs_verification', 'canonical': None, 'reasons': ['blank']}
    tasks = [{'status': 'pending', 'due_date': d} for d in dues]
    return {'id': ident, 'code': ident, 'name': 'Synthetic', 'source_kind': 'lark', 'case_type': 'intake' if intake else 'formal', 'source_status': source_status,
            'execution_status': 'paused', 'execution_allowed': runnable, 'source_lifecycle': lifecycle,
            'nodes': [{'key': 'sales', 'tasks': tasks}]}


def staging_shaped():
    """608 / 40 / 4 overdue source-dated tasks, scaled to 76 / 5 / 1 cases of 8 / 8 / 4 tasks."""
    cases = [case(f'i{n}', intake=True, source_status='', dues=('2026-09-10',) * 8) for n in range(76)]
    cases += [case(f'e{n}', source_status='執行中', dues=('2026-09-10',) * 8) for n in range(5)]
    cases += [case('v0', source_status='來源狀態待核對', dues=('2026-09-10',) * 4)]
    return cases


def test_staging_shaped_fixture_splits_into_three_buckets_without_merging():
    result = overview({'projects': staging_shaped()}, clock=CLOCK)
    group = result['source_deadlines']
    buckets = {b['key']: b for b in group['buckets']}
    assert [b['key'] for b in group['buckets']] == ['intake', 'formal_executing', 'formal_unverified', 'other']
    assert (buckets['intake']['tasks'], buckets['formal_executing']['tasks'], buckets['formal_unverified']['tasks'], buckets['other']['tasks']) == (608, 40, 4, 0)
    assert (buckets['intake']['cases'], buckets['formal_executing']['cases'], buckets['formal_unverified']['cases']) == (76, 5, 1)
    assert group['tasks'] == 652 and group['cases'] == 82
    assert result['totals']['tasks_overdue'] == 0 and result['totals']['tasks_total'] == 0  # not merged into workload


def test_unknown_states_land_in_the_remainder_bucket_and_enabled_or_future_work_is_excluded():
    cases = [case('x', source_status='已結案'), case('live', source_status='執行中', runnable=True), case('future', intake=True, dues=('2026-12-01', '', 'bad')),
             case('mixed', intake=True, dues=('2026-09-10', '2026-12-01'))]
    cases[0]['nodes'][0]['tasks'].append({'status': 'completed', 'due_date': '2026-09-01'})
    cases[3]['nodes'][0]['tasks'].append({'status': 'superseded', 'due_date': '2026-09-01'})
    group = overview({'projects': cases}, clock=CLOCK)['source_deadlines']
    buckets = {b['key']: (b['cases'], b['tasks']) for b in group['buckets']}
    assert buckets == {'intake': (1, 1), 'formal_executing': (0, 0), 'formal_unverified': (0, 0), 'other': (1, 1)}
