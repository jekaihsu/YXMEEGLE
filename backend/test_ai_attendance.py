import asyncio
import json
from datetime import datetime, timezone

import pytest

from .ai.tools import execute
from .live_read.datasets.weekly_attendance import fetch_week, week_window
from .test_live_read_coordinator import SynchronousExecutor
from .test_live_read_routes import production_client


@pytest.fixture
def attendance_route(tmp_path, monkeypatch):
    app, client = production_client(tmp_path)
    users = [dict(id=f'ou_{i}', name=f'同事{i}', department='工程', directory_status='employed',
                  directory_source={'app_id': 'app', 'record_id': str(i)}) for i in range(58)]
    class Adapter:
        def request(self, method, path, **kwargs):
            if path == '/contact/v3/users/batch':
                return {'items': [dict(open_id=u['id'], user_id=u['id'].replace('ou_', 'employee-')) for u in users
                                  if u['id'] in kwargs['params']['user_ids']]}
            if path == '/attendance/v1/groups':
                return {'group_list': [], 'has_more': False}
            if path == '/attendance/v1/user_tasks/query':
                return {'user_task_results': [dict(user_id=f'employee-{i}', day=20261012,
                    records=[dict(check_in_result='NoNeedCheck')]) for i in range(2, 6)
                    if f'employee-{i}' in kwargs['json']['user_ids']]}
            return {'user_approvals': [dict(user_id=f'employee-{i}', leaves=[dict(
                start_time='2026-10-12 00:00:00', end_time='2026-10-12 23:59:59')])
                for i in range(2) if f'employee-{i}' in kwargs['json']['user_ids']]}
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


def test_reproduce_old_attendance(attendance_route):
    result = call(attendance_route, {})
    print('OLD', json.dumps({k: len(result[k]) for k in ('missing_punch', 'no_record', 'leave', 'exempt')}))
    assert len(result['no_record']) == 54
    assert len(result['leave']) == 2
    assert len(result['exempt']) == 4
    assert not result['missing_punch']
    assert {p['id'] for p in result['leave']} <= {p['id'] for p in result['no_record']}
    assert 'days' not in result
