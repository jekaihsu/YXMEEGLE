import asyncio
import json
from datetime import date, timedelta
from .test_backend import app, client, role
from .ai.tools import project_attendance, project_progress, project_owners, execute
from .ai.ledger import today


def test_attendance_uses_today_column_and_preserves_unknowns():
    current = date.fromisoformat(today())
    days = [(current - timedelta(days=current.weekday()) + timedelta(days=i)).isoformat() for i in range(7)]
    index = days.index(today())
    people = []
    for n, label in enumerate(['遲到、到班', '缺卡', '請假', '出差', '外出', None, '到班', None]):
        values = ['到班'] * 7
        values[index] = label
        people.append(dict(id=str(n), name='同事' + str(n), in_service=True, attendance=values))
    people.append(dict(id='left', name='已離職', in_service=False, attendance=[None] * 7))
    result = project_attendance({'day': today(), 'view': dict(days=days, people=people, as_of='stamp', status='ok',
        trips=[dict(person_id='7', kind='out', start=today(), end=today())], leaves=[])})
    assert result['late'] == [{'id': '0', 'name': '同事0'}]
    assert result['missing_punch'] == [{'id': '1', 'name': '同事1'}]
    assert result['no_record'] == [{'id': '5', 'name': '同事5'}, {'id': '7', 'name': '同事7'}]
    assert result['out'] == [{'id': '4', 'name': '同事4'}, {'id': '7', 'name': '同事7'}]
    assert result['arrived_count'] == 2 and result['incomplete'] is True
    assert result['as_of'] == 'stamp'
    assert 'no record yet' in result['no_record_label']
    assert 'absent' not in result


def test_progress_and_owner_projection_exclude_finance():
    raw = dict(project_id='case', as_of='time', finance={'secret_amount': 123456},
               stages=[dict(key='field', label='外業', state='active', evidence=[{'amount': 999}]),
                       dict(key='billing', label='計價', state='done')],
               production={'field': {'progress': dict(items_done=3, items_total=5, percent='60', earned_points='900')}},
               gaps=[dict(id='finance_empty', message_zh='money'), dict(id='plan_unavailable', message_zh='no plan')])
    result = project_progress(raw)
    assert result == dict(project_id='case', as_of='time', stages=[dict(key='field', label='外業', state='active')],
                          nodes={'field': dict(items_done=3, items_total=5, percent='60')},
                          gaps=[dict(id='plan_unavailable', message_zh='no plan')])
    owners = project_owners(dict(detail=dict(as_of='t', project={'id': 'p', 'pm_id': 'u', 'amount': 100},
        users=[{'id': 'u', 'name': '主管', 'salary': 1000}]), assignments={'nodes': [
            {'key': 'field', 'label': '外業', 'owners': [{'open_id': 'u', 'name': '主管', 'salary': 1000}]}]}))
    assert owners['pm'] == {'id': 'u', 'name': '主管'}
    assert 'salary' not in json.dumps(owners) and 'amount' not in json.dumps(owners)


def test_attendance_route_cookie_forwarded_for_allowed_viewer(app, client, monkeypatch):
    role(client, 'u-manager')
    app.state.cfg['HR_VIEWERS'] = 'u-manager'
    calls = []
    def view(workspace_id, week):
        calls.append((workspace_id, week))
        return dict(days=[today()], people=[dict(id='u', name='准許查看的人員', in_service=True, attendance=['遲到'])],
                    status='ok', as_of='2026-10-31T09:00:00+08:00')
    monkeypatch.setattr(app.state.people_attendance, 'view', view)
    cookie = '; '.join(f'{k}={v}' for k, v in client.cookies.items())
    result, error = asyncio.run(execute(app, cookie, 'attendance_today', {}))
    assert error is False
    assert json.loads(result)['late'] == [{'id': 'u', 'name': '准許查看的人員'}]
    assert calls[0][1] == today()


def test_tool_rejects_unknown_and_extra_arguments(app):
    for name, args in [('write', {}), ('attendance_today', {'extra': 'x'}), ('case_progress', {'case_id': '../x/y'})]:
        result, error = asyncio.run(execute(app, '', name, args))
        assert error and 'error' in json.loads(result)
