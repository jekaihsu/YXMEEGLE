import asyncio
import json

import pytest

from .test_backend import app, client, role, WorkspaceRow, BusinessRow, storage
from .test_ai_api import BODY, Fake, events, rows, wid, live_server


class Capture(Fake):
    async def stream(self, spec, system, messages, tools):
        self.system, self.tools = system, tools
        async for event in super().stream(spec, system, messages, tools):
            yield event


def project(client):
    return client.get('/api/projects').json()['items'][0]['id']


@pytest.mark.parametrize('model', ['claude', 'gpt'])
def test_project_real_routes_single_call_and_ledger(app, client, model):
    pid = project(client)
    detail = client.get('/api/case-detail/' + pid).json()
    fake = Capture()
    app.state.ai_providers = {model: fake}
    result = events(client.post('/api/ai/chat', json=dict(BODY, model=model, project_id=pid)))
    assert result[0]['scope'] == 'project'
    assert result[-1]['type'] == 'done'
    assert not any(e['type'] == 'tool' for e in result)
    assert len(fake.inputs) == 1 and fake.tools == {}
    for value in (detail['header']['project_name'], detail['header']['case_number'], detail['header']['pm']['name']):
        assert value in fake.system
    assert 'contract_amounts' not in fake.system
    for phrase in ('已整理', '詳見上方結果', '依你可查看的資料'):
        assert phrase not in fake.system
    assert '本對話只涵蓋這個案件' in fake.system
    row, = rows(app)
    assert (row.scope, row.project_id, row.steps, row.tool_calls) == ('project', pid, 1, 0)
    assert client.post('/api/ai/feedback', json=dict(usage_id=row.id, rating='up')).status_code == 200


def test_project_hidden_and_unknown_are_identical_without_ledger(app, client):
    with app.state.sessions.begin() as db:
        root = db.get(WorkspaceRow, wid(app, client))
        state = storage.load(db, BusinessRow, root)
        p = state['projects'][0]
        p.update(planning_origin='local', created_by='u-manager', pm_id='u-manager', collaborator_ids=[])
        pid = p['id']
        root.data = storage.save(db, BusinessRow, root.id, state)
    role(client, 'u-control')
    assert client.get('/api/case-detail/' + pid).status_code == 404
    fake = Capture()
    app.state.ai_providers = {'claude': fake}
    responses = [client.post('/api/ai/chat', json=dict(BODY, project_id=value)) for value in (pid, 'unknown')]
    assert [r.status_code for r in responses] == [403, 403]
    assert responses[0].json() == responses[1].json()
    assert responses[0].json()['code'] == 'ai_forbidden'
    assert fake.inputs == [] and rows(app) == []


@pytest.mark.parametrize('value', ['', '.', '..', '../x', 'x/y', '中', 'x' * 201])
def test_project_id_validation(app, client, value):
    assert client.post('/api/ai/chat', json=dict(BODY, project_id=value)).status_code == 422


def test_usage_scope_filter_all_aggregates(app, client):
    pid = project(client)
    app.state.ai_providers = {'claude': Fake()}
    role(client, 'u-manager')
    events(client.post('/api/ai/chat', json=BODY))
    role(client, 'u-control')
    result = events(client.post('/api/ai/chat', json=dict(BODY, project_id=pid)))
    assert client.post('/api/ai/feedback', json=dict(usage_id=result[0]['usage_id'], rating='down', reason='wrong')).status_code == 200
    role(client, 'u-manager')
    for scope, actor in [('global', 'u-manager'), ('project', 'u-control')]:
        data = client.get('/api/ai/usage', params=dict(scope=scope)).json()
        assert data['totals']['questions'] == 1
        for group in ('by_day', 'by_person', 'by_provider'):
            assert sum(r['questions'] for r in data[group]) == 1
        assert data['people'] == [dict(actor_id=actor, name=data['by_person'][0]['name'])]
        assert len(data['recent']) == 1 and data['recent'][0]['scope'] == scope
        assert data['totals']['feedback']['down'] == (scope == 'project')
        assert data['reasons']['wrong'] == (scope == 'project')
    assert client.get('/api/ai/usage?scope=bad').status_code == 422


def cookie(client):
    return '; '.join(f'{k}={v}' for k, v in client.cookies.items())


def test_context_cache_real_routes_ttl_users_workspaces_and_coalescing(app, client, monkeypatch):
    from .ai import project_context as pc
    from .ai.tools import Reader
    pid = project(client)
    first_cookie = cookie(client)
    role(client, 'u-control')
    second_cookie = cookie(client)
    reads = []
    original = Reader.get
    clock = [100.0]
    monkeypatch.setattr(pc, 'monotonic', lambda: clock[0])
    async def observed(self, path, **params):
        reads.append((path, self.client.headers['cookie']))
        await asyncio.sleep(.01)
        return await original(self, path, **params)
    monkeypatch.setattr(Reader, 'get', observed)
    async def run():
        cache = pc.ProjectContextCache(maxsize=2)
        args = (app, first_cookie, 'w', 'u-agent', pid)
        results = await asyncio.gather(*(cache.get(*args) for _ in range(5)))
        assert len(reads) == 2
        assert all(r is results[0] for r in results)
        clock[0] = 189.9
        assert await cache.get(*args) is results[0]
        assert len(reads) == 2
        clock[0] = 190.1
        await cache.get(*args)
        assert len(reads) == 4
        await cache.get(app, second_cookie, 'w', 'u-control', pid)
        assert len(reads) == 6 and reads[-1][1] == second_cookie
        await cache.get(app, first_cookie, 'different-workspace', 'u-agent', pid)
        assert len(reads) == 8 and len(cache.entries) == 2
    asyncio.run(run())


@pytest.mark.parametrize('enabled', [False, True])
def test_context_unavailable_parts_and_amount_projection(app, client, monkeypatch, enabled):
    import httpx
    from .ai.project_context import build
    from .ai.tools import Reader
    pid = project(client)
    app.state.cfg['NODE_ASSIGNMENT_ENABLED'] = str(enabled).lower()
    original = Reader.get
    async def read(self, path, **params):
        if path.endswith(('/progress', '/node-assignments')):
            raise httpx.HTTPStatusError('failed', request=httpx.Request('GET', 'http://test'), response=httpx.Response(503))
        result = await original(self, path, **params)
        result['header']['contract_amounts'] = {'amount': 987654321, 'state': 'withheld'}
        result['sections']['secret_amount'] = {'value': 987654321}
        for part in ('dates', 'blockers', 'current_stage'):
            result['header'][part]['amount'] = 987654321
        result['header']['dates']['effective_approved']['amount'] = 987654321
        return result
    monkeypatch.setattr(Reader, 'get', read)
    context = asyncio.run(build(app, cookie(client), pid))
    data = json.loads(context.json)
    assert data['owners']['nodes'] is None
    assert data['owners']['node_assignment_status'] == 'node assignment data unavailable'
    assert data['progress'] == {'unavailable': 'progress data unavailable'}
    assert 'amount' not in context.json and '987654321' not in context.json


def test_context_truncation_real_detail_keeps_priority_and_valid_json(app, client, monkeypatch):
    from .ai.project_context import build
    from .ai.tools import Reader
    pid = project(client)
    original = Reader.get
    async def read(self, path, **params):
        result = await original(self, path, **params)
        if path.startswith('/api/case-detail/'):
            result['header']['blockers']['items'] = ['blocker-' + str(i) + 'x' * 300 for i in range(100)]
        return result
    monkeypatch.setattr(Reader, 'get', read)
    context = asyncio.run(build(app, cookie(client), pid))
    data = json.loads(context.json)
    assert len(context.json) <= 12000 and data['truncated'] is True
    assert data['project']['id'] == pid and data['owners']['pm']['id']
    assert 0 < len(data['blockers']['items']) < 100


def test_unreadable_base_denied_without_model_or_ledger(app, client, monkeypatch):
    from .ai.tools import Reader
    import httpx
    pid = project(client)
    async def fail(self, path, **params):
        raise httpx.HTTPStatusError('failed', request=httpx.Request('GET', 'http://test'), response=httpx.Response(503))
    monkeypatch.setattr(Reader, 'get', fail)
    fake = Capture()
    app.state.ai_providers = {'claude': fake}
    response = client.post('/api/ai/chat', json=dict(BODY, project_id=pid))
    assert response.status_code == 403 and response.json()['code'] == 'ai_forbidden'
    assert not fake.inputs and not rows(app)


def test_project_never_executes_unsolicited_tool_call(app, client):
    from .ai.providers import ToolCall
    fake = Capture(calls=[ToolCall('a', 'attendance_today', {})])
    app.state.ai_providers = {'claude': fake}
    result = events(client.post('/api/ai/chat', json=dict(BODY, project_id=project(client))))
    assert result[-1]['code'] == 'ai_upstream'
    assert len(fake.inputs) == 1 and not any(e['type'] == 'tool' for e in result)
    row, = rows(app)
    assert row.steps == 1 and row.tool_calls == 0


def test_curl_project_stream_and_forbidden_real_socket(app, client, live_server):
    import subprocess
    pid = project(client)
    app.state.ai_providers = {'claude': Capture()}
    for value in (pid, 'unknown'):
        body = dict(BODY, project_id=value)
        response = subprocess.run(['curl', '--silent', '--show-error', '--no-buffer', '--max-time', '10',
            '--write-out', '\nHTTP %{http_code}\n', '--header', 'Content-Type: application/json',
            '--cookie', cookie(client), '--data', json.dumps(body), live_server + '/api/ai/chat'],
            check=True, capture_output=True, text=True).stdout
        print('curl POST /api/ai/chat ' + json.dumps(body, ensure_ascii=False))
        print(response)
        if value == pid:
            result = [json.loads(line[6:]) for line in response.splitlines() if line.startswith('data: ')]
            assert [e['type'] for e in result] == ['start', 'text', 'text', 'done']
            assert result[0]['scope'] == 'project' and 'HTTP 200' in response
        else:
            assert 'ai_forbidden' in response and 'HTTP 403' in response
    assert len(app.state.ai_providers['claude'].inputs) == 1
    row, = rows(app)
    assert row.scope == 'project'


def test_project_timeout_still_records_scope_and_releases_slot(app, client):
    pid = project(client)
    app.state.cfg['AI_QUESTION_TIMEOUT_SECONDS'] = '.1'
    app.state.ai_providers = {'claude': Fake(delay=.2)}
    result = events(client.post('/api/ai/chat', json=dict(BODY, project_id=pid)))
    assert result[-1]['code'] == 'ai_upstream'
    row, = rows(app)
    assert (row.scope, row.project_id, row.status) == ('project', pid, 'error')
    app.state.ai_providers = {'claude': Fake()}
    assert events(client.post('/api/ai/chat', json=dict(BODY, project_id=pid)))[-1]['type'] == 'done'


def test_context_shared_build_survives_waiter_cancellation(app, client, monkeypatch):
    from .ai import project_context as pc
    from .ai.tools import Reader
    pid = project(client)
    original = Reader.get
    reads = []
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        async def read(self, path, **params):
            reads.append(path)
            entered.set()
            await release.wait()
            return await original(self, path, **params)
        monkeypatch.setattr(Reader, 'get', read)
        cache = pc.ProjectContextCache()
        args = (app, cookie(client), 'w', 'u-agent', pid)
        waiter = asyncio.create_task(cache.get(*args))
        await entered.wait()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        release.set()
        context = await cache.get(*args)
        assert json.loads(context.json)['project']['id'] == pid
        assert len(reads) == 2
    asyncio.run(run())
