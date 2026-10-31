import asyncio
import json

import pytest

from .test_backend import app, client
from .ai.tools import execute


def test_tool_rejects_unknown_and_extra_arguments(app):
    for name, args in [('write', {}), ('attendance_today', {'extra': 'x'}), ('case_progress', {'case_id': '../x/y'})]:
        result, error = asyncio.run(execute(app, '', name, args))
        assert error and 'error' in json.loads(result)


def tool(app, client, name, args):
    cookie = '; '.join(f'{k}={v}' for k, v in client.cookies.items())
    result, error = asyncio.run(execute(app, cookie, name, args))
    assert not error, result
    return json.loads(result)



def test_real_search_and_owners_without_shell(app, client, monkeypatch):
    from .ai.tools import Reader
    requests = []
    original = Reader.get
    async def observed(self, path, **params):
        requests.append(path)
        return await original(self, path, **params)
    monkeypatch.setattr(Reader, 'get', observed)
    page = client.get('/api/projects', params={'limit': 8}).json()
    assert page['items']
    query = page['items'][0]['code']
    source = client.get('/api/projects', params={'q': query, 'limit': 8}).json()
    result = tool(app, client, 'search_cases', {'query': query})
    assert requests == ['/api/projects']
    requests.clear()
    assert result['total'] == source['total']
    assert result['cases'] == [{k: p[k] for k in ('id', 'code', 'name', 'status', 'pm_id', 'due_date')} for p in source['items']]
    pid = source['items'][0]['id']
    assert client.get('/api/projects/' + pid).status_code == 404
    detail = client.get('/api/case-detail/' + pid).json()
    owners = tool(app, client, 'case_owners', {'case_id': pid})
    assert requests == ['/api/case-detail/' + pid]
    assert owners['pm']['id'] == source['items'][0]['pm_id']
    assert owners['pm']['name'] == detail['header']['pm']['name']
    assert owners['node_assignment_status'] == 'node assignment data unavailable'
    assert owners['nodes'] is None
    progress = client.get('/api/projects/' + pid + '/progress').json()
    result = tool(app, client, 'case_progress', {'case_id': pid})
    assert result['as_of'] == progress['as_of']
    assert result['stages'][0]['basis'] == progress['stages'][0]['basis']



@pytest.mark.parametrize('pid', ['../x', 'a/progress', '%2F', '.', '..'])
def test_invalid_id_before_http(app, monkeypatch, pid):
    async def forbidden(*args, **kwargs):
        pytest.fail('invalid id reached HTTP')
    monkeypatch.setattr('backend.ai.tools.Reader.get', forbidden)
    result, error = asyncio.run(execute(app, '', 'case_progress', {'case_id': pid}))
    assert error and json.loads(result)['error'] == '工具參數錯誤'



@pytest.mark.parametrize('large', [False, True])
def test_attendance_real_producer_route_and_structural_truncation(app, client, monkeypatch, large):
    from datetime import datetime, timezone
    from .live_read.datasets.weekly_attendance import fetch_week, week_window
    from .test_live_read_coordinator import SynchronousExecutor
    labels = [('Normal', None), ('Late', None), ('Early', None), ('Lack', None), ('NoNeedCheck', None),
              ('Normal', 'CardReplacement'), ('Normal', 'Leave'), ('Normal', 'Travel'), ('Normal', 'GoOut'), (None, None)]
    users = [dict(id=f'ou_{i}', name=f'同事{i}', directory_status='employed',
                  directory_source={'app_id': 'app', 'record_id': f'rec{i}'}) for i in range(800 if large else 10)]
    class Adapter:
        def request(self, method, path, **kwargs):
            if path == '/contact/v3/users/batch':
                return {'items': [dict(open_id=u['id'], user_id=u['id'].replace('ou_', 'employee-')) for u in users if u['id'] in kwargs['params']['user_ids']]}
            if path == '/attendance/v1/groups':
                return {'group_list': [], 'has_more': False}
            if path == '/attendance/v1/user_tasks/query':
                return {'user_task_results': [dict(user_id=u['id'].replace('ou_', 'employee-'), day=20261012, records=[dict(
                    check_in_result=labels[i % 10][0], check_in_result_supplement=labels[i % 10][1])])
                    for i, u in enumerate(users) if u['id'].replace('ou_', 'employee-') in kwargs['json']['user_ids']], 'invalid_user_ids': []}
            return {'user_approvals': []}
    reader = app.state.people_attendance
    reader.executor = SynchronousExecutor()
    reader.clock = lambda: datetime(2026, 10, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(reader, '_enabled', lambda wid: True)
    reader.refreshers['attendance'] = lambda key: dict(fingerprint='test', snapshot=fetch_week(
        Adapter(), users, 'app', 'company', week_window('2026-10-12'), True))
    monkeypatch.setattr('backend.ai.tools.today', lambda: '2026-10-12')
    source = client.get('/api/people/attendance?week=2026-10-12').json()
    assert source['people'] and source['as_of']
    result = tool(app, client, 'attendance_today', {})
    assert result['as_of'] == source['as_of'] and result['incomplete'] is True
    assert result['labelled_arrival_count'] == (80 if large else 1)
    if large:
        assert result['truncated'] is True and 'partial_data' not in result
        assert len(json.dumps(result, ensure_ascii=False)) <= 6000
    else:
        for group, i in [('late', 1), ('early_leave', 2), ('missing_punch', 3), ('exempt', 4),
                         ('supplemented', 5), ('leave', 6), ('trip', 7), ('out', 8), ('no_record', 9)]:
            assert result[group] == [{'id': f'ou_{i}', 'name': f'同事{i}'}]
    assert '缺席' not in json.dumps(result, ensure_ascii=False)



def test_pm_name_unavailable_preserves_real_id(app, client):
    from .test_backend import WorkspaceRow, BusinessRow, storage
    wid = app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
    with app.state.sessions.begin() as db:
        row = db.get(WorkspaceRow, wid)
        state = storage.load(db, BusinessRow, row)
        project = state['projects'][0]
        pid = project['id']
        project['pm_id'] = 'unresolved-person'
        row.data = storage.save(db, BusinessRow, wid, state)
    result = tool(app, client, 'case_owners', {'case_id': pid})
    assert result['pm'] == {'id': 'unresolved-person', 'name': 'name_unavailable'}


@pytest.mark.parametrize('failure', ['503', 'timeout'])
def test_owners_assignment_failure_keeps_pm(app, client, monkeypatch, failure):
    import httpx
    from fastapi.testclient import TestClient
    from .app import create_app
    from .node_assignment.errors import Failure
    app = create_app({**app.state.cfg, 'NODE_ASSIGNMENT_ENABLED': 'true'})
    client = TestClient(app, cookies=dict(client.cookies.items()))
    if failure == '503':
        def unavailable(ctx):
            raise Failure('lark_unavailable', 'Lark unavailable')
        monkeypatch.setattr(app.state.node_assignment, 'overview', unavailable)
        response = client.get('/api/projects/p1/node-assignments')
        assert response.status_code == 503 and response.json()['code'] == 'lark_unavailable'
    else:
        class TimeoutTransport(httpx.ASGITransport):
            async def handle_async_request(self, request):
                if request.url.path.endswith('/node-assignments'):
                    raise httpx.ReadTimeout('node read timed out', request=request)
                return await super().handle_async_request(request)
        monkeypatch.setattr('backend.ai.tools.httpx.ASGITransport', TimeoutTransport)
    pid = client.get('/api/projects').json()['items'][0]['id']
    detail = client.get('/api/case-detail/' + pid).json()
    result = tool(app, client, 'case_owners', {'case_id': pid})
    assert result['pm']['name'] == detail['header']['pm']['name']
    assert result['node_assignment_status'] == 'node assignment data unavailable'
    assert result['nodes'] is None


def test_owners_real_source_timestamp_and_missing_time(app, client):
    from .test_backend import WorkspaceRow, BusinessRow, storage
    wid = app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
    for timestamp in ['2026-10-30T01:02:03Z', None]:
        with app.state.sessions.begin() as db:
            row = db.get(WorkspaceRow, wid)
            state = storage.load(db, BusinessRow, row)
            pid = state['projects'][0]['id']
            state['source_status'] = {'last_sync': timestamp}
            row.data = storage.save(db, BusinessRow, wid, state)
        detail = client.get('/api/case-detail/' + pid).json()
        assert 'as_of' not in detail
        assert detail['sections']['overview']['source_time']['value'] == timestamp
        result = tool(app, client, 'case_owners', {'case_id': pid})
        if timestamp:
            assert result['as_of'] == timestamp
        else:
            assert 'as_of' not in result
        assert 'node_assignments_as_of' not in result


def test_search_real_routes_do_not_claim_timestamp(app, client):
    from .ai.prompts import system_prompt
    page = client.get('/api/projects').json()
    query = page['items'][0]['code']
    assert 'as_of' not in page
    assert 'as_of' not in client.get('/api/projects', params={'q': query}).json()
    assert 'as_of' not in tool(app, client, 'search_cases', {'query': query})
    prompt = system_prompt()
    assert '查詢當下資料' in prompt
    assert 'case_progress' in prompt and 'attendance_today' in prompt
