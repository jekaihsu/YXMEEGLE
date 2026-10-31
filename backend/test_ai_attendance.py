import asyncio
import json
from datetime import datetime, timezone

import pytest

from .ai.tools import execute
from .live_read.datasets.weekly_attendance import fetch_week, week_window
from .test_live_read_coordinator import SynchronousExecutor
from .test_live_read_routes import production_client


@pytest.fixture
def attendance_route(tmp_path, monkeypatch, request):
    app, client = production_client(tmp_path)
    mode = getattr(request, 'param', 58)
    size = 8 if mode == 'mixed' else 58 if mode == 'approvals' else mode
    users = [dict(id=f'ou_{i}', name=f'同事{i}', department='工程', directory_status='employed',
                  directory_source={'app_id': 'app', 'record_id': str(i)}) for i in range(size)]
    punches = []
    app.state.attendance_fixture_punches = punches
    class Adapter:
        def request(self, method, path, **kwargs):
            if path == '/contact/v3/users/batch':
                return {'items': [dict(open_id=u['id'], user_id=u['id'].replace('ou_', 'employee-')) for u in users
                                  if u['id'] in kwargs['params']['user_ids']]}
            if path == '/attendance/v1/groups':
                return {'group_list': [], 'has_more': False}
            if path == '/attendance/v1/user_tasks/query':
                tasks = [dict(user_id=f'employee-{i}', day=20261012,
                    records=[dict(check_in_result='NoNeedCheck')]) for i in range(2, 6)]
                tasks += punches
                if mode == 'mixed':
                    tasks += [dict(user_id=f'employee-{i}', day=20261012 + offset,
                        records=[dict(check_in_result='Late' if i == 6 else 'Lack')])
                        for offset in range(5) for i in (6, 7)]
                return {'user_task_results': [t for t in tasks if t['user_id'] in kwargs['json']['user_ids']]}
            approvals = [dict(user_id=f'employee-{i}', leaves=[dict(
                start_time='2026-10-12 00:00:00', end_time='2026-10-12 23:59:59')]) for i in range(2)]
            if mode == 'approvals':
                approvals += [dict(user_id=f'employee-{i}', **{key: [dict(
                    start_time='2026-10-12 00:00:00', end_time='2026-10-12 23:59:59')]})
                    for i, key in ((6, 'trips'), (7, 'outs'))]
            return {'user_approvals': [a for a in approvals if a['user_id'] in kwargs['json']['user_ids']]}

    for cookie in list(client.cookies.jar):
        if cookie.domain != 'testserver.local':
            client.cookies.jar.clear(cookie.domain, cookie.path, cookie.name)
    reader = app.state.people_attendance
    reader.executor = SynchronousExecutor()
    reader.clock = lambda: datetime(2026, 10, 12, tzinfo=timezone.utc)
    reader.refreshers['attendance'] = lambda key: dict(fingerprint='fixture', snapshot=fetch_week(
        Adapter(), users, 'app', 'company', week_window('2026-10-12'), True))
    monkeypatch.setattr('backend.ai.tools.today', lambda: '2026-10-12')
    yield app, client



def call(pair, args):
    app, client = pair
    cookie = '; '.join(f'{k}={v}' for k, v in client.cookies.items())
    raw, error = asyncio.run(execute(app, cookie, 'attendance_today', args))
    assert not error, raw
    return json.loads(raw)


def test_semantic_day(attendance_route):
    result = call(attendance_route, {'range': 'today', 'date': ''})
    assert result['counts']['unaccounted'] == 52
    assert result['counts']['on_leave'] == 2
    assert result['counts']['exempt'] == 4
    assert not result['missing_punch']
    ids = [p['id'] for key in result['counts'] if key != 'arrived' for p in result[key]]
    assert len(ids) == len(set(ids)) == 58
    print('NEW DAY', json.dumps({k: result[k] for k in ('range', 'date', 'counts')}, ensure_ascii=False))
    from .ai.tools import display_attendance
    displays = display_attendance(result)
    assert displays[0]['points'][1] == {'label': '沒有打卡紀錄', 'value': 52}
    assert len(displays[1]['rows']) == 50 and displays[1]['truncated']


@pytest.mark.parametrize('attendance_route', [800], indirect=True)
@pytest.mark.parametrize('period', ['today', 'week'])
def test_truncation(attendance_route, period, monkeypatch):
    monkeypatch.setattr('backend.ai.tools.today', lambda: '2026-10-16')
    result = call(attendance_route, {'range': period, 'date': '2026-10-12'})
    assert result['truncated']
    assert len(json.dumps(result, ensure_ascii=False)) <= 6000
    if period == 'today':
        assert result['counts']['unaccounted'] == 794
    else:
        assert result['summary']['unaccounted']['person_days'] == 3994
        assert result['days'][0]['counts']['unaccounted'] == 794
    from .ai.tools import display_attendance
    assert all(d['truncated'] for d in display_attendance(result))


def test_week_and_weekends(attendance_route, monkeypatch):
    monkeypatch.setattr('backend.ai.tools.today', lambda: '2026-10-16')
    result = call(attendance_route, {'range': 'week', 'date': '2026-10-12'})
    assert len(result['days']) == 7
    assert [d['counts']['unaccounted'] for d in result['days']] == [52, 58, 58, 58, 58, 0, 0]
    assert result['summary']['unaccounted'] == {'people': 58, 'person_days': 284}
    assert result['top_unaccounted'][0]['unaccounted_days'] == 5
    assert 'public holidays not excluded' in result['basis']
    assert all(not d['evaluated'] for d in result['days'][5:])
    print('NEW WEEK', json.dumps({k: result[k] for k in ('week_start', 'week_end', 'summary')}, ensure_ascii=False))
    from .ai.tools import display_attendance
    table, chart = display_attendance(result)
    assert len(table['columns']) == 8 and len(table['rows']) <= 50
    assert '2026-10-12 至 2026-10-18' in table['caption']
    assert [p['value'] for p in chart['points']] == [52, 58, 58, 58, 58]
    assert all(row['2026-10-17'] == row['2026-10-18'] == '不評估' for row in table['rows'])
    assert all(isinstance(v, (str, int, float)) or v is None for row in table['rows'] for v in row.values())
    weekend = call(attendance_route, {'range': 'today', 'date': '2026-10-17'})
    assert not weekend['unaccounted']


@pytest.mark.parametrize('args', [
    {'range': 'week', 'date': '2026-02-30'}, {'range': 'today', 'date': 'yesterday'},
    {'range': 'today', 'date': '20261012'}, {'range': 'month', 'date': ''},
    {'range': 'today', 'date': '2000-01-01'}, {'range': 'week', 'date': '2026-1-2'},
    {'range': 'today', 'date': 'x' * 241}, {'range': 'today', 'date': 123}, {},
])
def test_invalid_dates_before_http(attendance_route, monkeypatch, args):
    async def forbidden(*a, **kw):
        pytest.fail('invalid args reached route')
    monkeypatch.setattr('backend.ai.tools.Reader.get', forbidden)
    app, client = attendance_route
    raw, error = asyncio.run(execute(app, '', 'attendance_today', args))
    assert error and 'error' in json.loads(raw)


def test_prompt_and_strict_schema():
    from .ai.prompts import system_prompt
    from .ai.tools import TOOLS
    prompt = system_prompt()
    for rule in ('沒打卡／沒到／還沒打卡 = unaccounted', '缺卡 missing_punch',
                 'unaccounted 非空時不得回答「沒有人」', '沒有打卡紀錄 N 人',
                 'as_of 只提一次', '依 week summary', '不要評論先前回覆', '不得使用「缺席」'):
        assert rule in prompt
    schema = TOOLS['attendance_today'].schema
    assert set(schema['required']) == set(schema['properties']) == {'range', 'date'}
    assert schema['additionalProperties'] is False
    assert schema['properties']['date']['type'] == 'string'


@pytest.mark.parametrize('attendance_route', ['mixed'], indirect=True)
def test_monday_friday_labels(attendance_route, monkeypatch):
    monkeypatch.setattr('backend.ai.tools.today', lambda: '2026-10-19')
    result = call(attendance_route, {'range': 'week', 'date': '2026-10-14'})
    assert result['summary']['late'] == {'people': 1, 'person_days': 5}
    assert result['summary']['missing_punch'] == {'people': 1, 'person_days': 5}
    assert result['summary']['on_leave'] == {'people': 2, 'person_days': 2}
    assert result['summary']['unaccounted'] == {'people': 6, 'person_days': 24}
    rows = {p['id']: p for p in result['people']}
    assert rows['ou_6']['days']['late'] == ['2026-10-12', '2026-10-13', '2026-10-14', '2026-10-15', '2026-10-16']
    assert rows['ou_7']['days']['missing_punch'] == rows['ou_6']['days']['late']
    day = call(attendance_route, {'range': 'today', 'date': '2026-10-13'})
    assert day['date'] == '2026-10-13' and day['counts']['unaccounted'] == 6
    from .ai.tools import display_attendance
    table, _ = display_attendance(result)
    assert any(row['2026-10-12'] == '遲' for row in table['rows'])
    assert any(row['2026-10-12'] == '卡' for row in table['rows'])


def test_future_days_do_not_infer_no_record(attendance_route):
    result = call(attendance_route, {'range': 'week', 'date': ''})
    assert [item['counts']['unaccounted'] for item in result['days']] == [52, 0, 0, 0, 0, 0, 0]


def test_refresh_changes_count_only_when_evidence_changes(attendance_route):
    app, _ = attendance_route
    args = {'range': 'today', 'date': ''}
    assert call(attendance_route, args)['counts']['unaccounted'] == 52
    assert call(attendance_route, args)['counts']['unaccounted'] == 52
    app.state.attendance_fixture_punches.append(dict(user_id='employee-6', day=20261012,
        records=[dict(check_in_result='Normal')]))
    reader = app.state.people_attendance
    reader.clock = lambda: datetime(2026, 10, 12, 1, tzinfo=timezone.utc)
    refreshed = call(attendance_route, args)
    assert refreshed['counts']['unaccounted'] == 51
    assert refreshed['counts']['arrived'] == 1


@pytest.mark.parametrize('attendance_route', ['approvals'], indirect=True)
def test_approval_explanations_exclude_no_record(attendance_route):
    result = call(attendance_route, {'range': 'today', 'date': ''})
    assert result['counts']['unaccounted'] == 50
    assert result['trip'] == [{'id': 'ou_6', 'name': '同事6'}]
    assert result['out'] == [{'id': 'ou_7', 'name': '同事7'}]
    assert not {'ou_0', 'ou_1', 'ou_6', 'ou_7'} & {p['id'] for p in result['unaccounted']}


@pytest.mark.parametrize('attendance_route', ['mixed'], indirect=True)
def test_week_summary_ignores_punch_labels_on_unevaluated_days(attendance_route, monkeypatch):
    monkeypatch.setattr('backend.ai.tools.today', lambda: '2026-10-14')
    result = call(attendance_route, {'range': 'week', 'date': '2026-10-12'})
    assert [d['evaluated'] for d in result['days']] == [True, True, True, False, False, False, False]
    late = result['summary']['late']
    assert late == {'people': 1, 'person_days': 3}, 'the fixture also labels Thursday and Friday, which are still in the future'
    person = next(p for p in result['people'] if p['id'] == 'ou_6')
    assert person['days']['late'] == ['2026-10-12', '2026-10-13', '2026-10-14']
    assert result['summary']['missing_punch']['person_days'] == 3


@pytest.mark.parametrize('attendance_route', ['approvals'], indirect=True)
def test_week_summary_keeps_approved_leave_on_future_weekdays(attendance_route, monkeypatch):
    monkeypatch.setattr('backend.ai.tools.today', lambda: '2026-10-12')
    result = call(attendance_route, {'range': 'week', 'date': '2026-10-12'})
    assert result['summary']['on_leave']['person_days'] == 2
    assert result['summary']['trip']['people'] == 1 and result['summary']['out']['people'] == 1
