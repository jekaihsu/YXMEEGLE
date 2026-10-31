import asyncio
import json
import socket
import threading
import time
from datetime import datetime, timezone

import httpx
import pytest
import uvicorn
from sqlalchemy import select

from .test_backend import app, client, role, WorkspaceRow, BusinessRow, storage
from .ai.catalog import Usage
from .ai.ledger import AiUsageRow, today
from .ai.providers import Claude, Event, ProviderError, ToolCall
from .ai.tools import execute


BODY = {'model': 'claude', 'conversation_id': 'c-123', 'messages': [{'role': 'user', 'content': '查詢公司資料'}]}


class Fake(Claude):
    def __init__(self, *, calls=(), failure=False, delay=0):
        self.calls, self.failure, self.delay = calls, failure, delay
        self.inputs = []

    async def stream(self, spec, system, messages, tools):
        self.inputs.append(list(messages))
        yield Event('usage', Usage(10, 20, 30, 40))
        if self.failure:
            raise ProviderError()
        if self.calls and len(self.inputs) == 1:
            for call in self.calls:
                yield Event('tool', call)
            yield Event('stop', [{'type': 'tool_use', 'id': c.id, 'name': c.name, 'input': c.args} for c in self.calls])
            return
        yield Event('text', '截至目前，')
        await asyncio.sleep(self.delay)
        text = json.dumps(messages[-1]['content'], ensure_ascii=False) if self.calls else '查詢完成'
        yield Event('text', text)
        yield Event('stop', [{'type': 'text', 'text': text}])


def events(response):
    assert response.status_code == 200, response.text
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]


def rows(app):
    with app.state.sessions() as db:
        return list(db.scalars(select(AiUsageRow)))


def wid(app, client):
    return app.state.signer.loads(client.cookies.get('meegle_session'))['wid']


def test_models_missing_key_and_request_validation(app, client):
    app.state.ai_providers = {}
    assert client.get('/api/ai/models').json() == {'default': 'claude', 'models': [
        {'id': 'claude', 'label': 'Claude', 'available': False}, {'id': 'gpt', 'label': 'GPT', 'available': False}]}
    response = client.post('/api/ai/chat', json=BODY)
    assert response.status_code == 503
    assert response.json()['code'] == 'ai_unconfigured'
    assert rows(app) == []
    invalid = [dict(BODY, model='other'), dict(BODY, effort='high'), dict(BODY, messages=BODY['messages'] * 21),
               dict(BODY, messages=[]), dict(BODY, messages=[{'role': 'assistant', 'content': 'x'}]),
               dict(BODY, messages=[{'role': 'user', 'content': 'x' * 4001}]),
               dict(BODY, messages=[{'role': 'user', 'content': 'x', 'extra': True}]),
               dict(BODY, messages=[{'role': 'system', 'content': 'x'}])]
    for body in invalid:
        assert client.post('/api/ai/chat', json=body).status_code == 422


def test_success_error_usage_and_cost_visibility(app, client):
    role(client, 'u-control')
    app.state.ai_providers = {'claude': Fake()}
    result = events(client.post('/api/ai/chat', json=BODY))
    assert result[0]['type'] == 'start'
    assert result[-1] == {'type': 'done', 'usage': {'input_tokens': 60, 'output_tokens': 40}}
    row = rows(app)[0]
    assert (row.status, row.input_tokens, row.cache_read_tokens, row.cache_write_tokens, row.output_tokens) == ('ok', 60, 20, 30, 40)
    assert row.cost_micro_usd == 499
    assert row.first_token_ms is not None and row.latency_ms >= row.first_token_ms
    assert row.actor_id == 'u-control' and row.day == today()
    assert client.get('/api/ai/usage').status_code == 403
    role(client, 'u-manager')
    result = events(client.post('/api/ai/chat', json=BODY))
    assert result[-1]['cost_usd'] == 0.000499
    app.state.ai_providers['claude'] = Fake(failure=True)
    result = events(client.post('/api/ai/chat', json=BODY))
    assert result[-1]['code'] == 'ai_upstream'
    assert len(rows(app)) == 3
    assert rows(app)[-1].status == 'error'
    assert rows(app)[-1].input_tokens == 60
    dashboard = client.get('/api/ai/usage').json()
    assert dashboard['totals'] == {'questions': 3, 'input_tokens': 180, 'output_tokens': 120,
                                   'cost_usd': .001497, 'unpriced_calls': 0}


def test_usage_filters_and_unpriced(app, client):
    role(client, 'u-manager')
    app.state.ai_providers = {'claude': Fake(), 'gpt': Fake()}
    events(client.post('/api/ai/chat', json=BODY))
    role(client, 'u-control')
    events(client.post('/api/ai/chat', json=dict(BODY, model='gpt')))
    with app.state.sessions.begin() as db:
        source = dict(rows(app)[0].__dict__)
        source.pop('_sa_instance_state')
        source.pop('id')
        source.update(day='2020-01-01', created_at=datetime(2020, 1, 1, tzinfo=timezone.utc), cost_micro_usd=None)
        db.add(AiUsageRow(**source))
        source.update(workspace_id='other-workspace', day=today())
        db.add(AiUsageRow(**source))
    role(client, 'u-manager')
    dashboard = client.get('/api/ai/usage', params={'from': today(), 'to': today(), 'actor': 'u-control', 'provider': 'gpt'}).json()
    assert dashboard['totals']['questions'] == 1
    assert dashboard['by_person'][0]['actor_id'] == 'u-control'
    assert dashboard['by_provider'][0]['provider'] == 'gpt'
    dashboard = client.get('/api/ai/usage', params={'actor': 'u-control'}).json()
    assert {p['actor_id'] for p in dashboard['people']} == {'u-control', 'u-manager'}
    dashboard = client.get('/api/ai/usage', params={'from': '2020-01-01', 'to': '2020-01-01'}).json()
    assert dashboard['totals']['questions'] == dashboard['totals']['unpriced_calls'] == 1
    assert dashboard['recent'][0]['cost_usd'] is None
    assert client.get('/api/ai/usage', params={'from': 'bad'}).status_code == 422
    assert client.get('/api/ai/usage', params={'from': '2030-01-01', 'to': '2020-01-01'}).status_code == 422


def test_quota_before_stream(app, client):
    app.state.ai_providers = {'claude': Fake()}
    events(client.post('/api/ai/chat', json=BODY))
    with app.state.sessions.begin() as db:
        db.scalar(select(AiUsageRow)).input_tokens = 400000
    response = client.post('/api/ai/chat', json=BODY)
    assert response.status_code == 429 and response.json()['code'] == 'ai_quota'
    assert len(rows(app)) == 1


def test_hr_and_case_permissions_apply_to_tools_and_sse(app, client):
    role(client, 'u-control')
    app.state.cfg['HR_VIEWERS'] = 'u-manager'
    cookie = '; '.join(f'{k}={v}' for k, v in client.cookies.items())
    assert client.get('/api/people/attendance').status_code == 403
    result, error = asyncio.run(execute(app, cookie, 'attendance_today', {}))
    assert error and json.loads(result) == {'error': '你沒有權限查看出勤資料'}
    with app.state.sessions.begin() as db:
        root = db.get(WorkspaceRow, wid(app, client))
        state = storage.load(db, BusinessRow, root)
        project = state['projects'][0]
        project['planning_origin'] = 'local'
        project['created_by'] = 'u-manager'
        project['pm_id'] = 'u-manager'
        project['collaborator_ids'] = []
        project['name'] = '機密隱藏案件不得洩漏'
        hidden_id = project['id']
        root.data = storage.save(db, BusinessRow, root.id, state)
    assert client.get('/api/projects/' + hidden_id + '/progress').status_code == 404
    result, error = asyncio.run(execute(app, cookie, 'case_progress', {'case_id': hidden_id}))
    assert error and '機密隱藏案件' not in result
    result, _ = asyncio.run(execute(app, cookie, 'search_cases', {'query': '機密隱藏案件'}))
    assert json.loads(result)['cases'] == []
    app.state.ai_providers = {'claude': Fake(calls=[ToolCall('a', 'attendance_today', {}),
        ToolCall('b', 'case_progress', {'case_id': hidden_id})])}
    response = client.post('/api/ai/chat', json=BODY)
    result = events(response)
    text = ''.join(e['delta'] for e in result if e['type'] == 'text')
    assert '你沒有權限查看出勤資料' in text
    assert '機密隱藏案件' not in text
    assert 'late' not in text and 'production' not in text
    assert rows(app)[0].tool_calls == 2 and rows(app)[0].steps == 2


def test_tool_deduplication_and_multistep_accounting(app, client, monkeypatch):
    count = []
    async def tool(*args):
        count.append(args[2])
        await asyncio.sleep(.01)
        return '{"ok":true}', False
    monkeypatch.setattr('backend.ai.agent.execute', tool)
    app.state.ai_providers = {'claude': Fake(calls=[ToolCall('a', 'attendance_today', {}),
        ToolCall('b', 'attendance_today', {}), ToolCall('c', 'search_cases', {'query': 'a'})])}
    result = events(client.post('/api/ai/chat', json=BODY))
    assert count == ['attendance_today', 'search_cases']
    assert result[-1]['usage'] == {'input_tokens': 120, 'output_tokens': 80}
    assert rows(app)[0].tool_calls == 2 and rows(app)[0].steps == 2


@pytest.fixture
def live_server(app):
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, lifespan='off', log_level='error'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(.01)
    assert server.started
    try:
        yield f'http://127.0.0.1:{port}'
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive()


def test_real_socket_stream_is_not_buffered(app, client, live_server):
    app.state.ai_providers = {'claude': Fake(delay=.8)}
    observed = []
    with httpx.Client(base_url=live_server, cookies=dict(client.cookies.items()), timeout=5) as connection:
        start = time.monotonic()
        with connection.stream('POST', '/api/ai/chat', json=BODY, headers={'Accept-Encoding': 'gzip'}) as response:
            assert response.status_code == 200
            assert response.headers['cache-control'] == 'no-store'
            assert response.headers['x-accel-buffering'] == 'no'
            for line in response.iter_lines():
                if line.startswith('data: '):
                    observed.append((time.monotonic() - start, json.loads(line[6:])))
    texts = [at for at, event in observed if event['type'] == 'text']
    assert len(texts) == 2
    assert texts[0] < .5, observed
    assert texts[1] - texts[0] > .65, observed
    assert observed[-1][1]['type'] == 'done'
    print(f'socket text deltas at {texts[0]:.3f}s and {texts[1]:.3f}s')


def test_disconnect_records_aborted_and_releases_slot(app, client, live_server):
    app.state.ai_providers = {'claude': Fake(delay=10)}
    with httpx.Client(base_url=live_server, cookies=dict(client.cookies.items()), timeout=5) as connection:
        with connection.stream('POST', '/api/ai/chat', json=BODY) as response:
            for line in response.iter_lines():
                if '"type": "text"' in line:
                    break
    deadline = time.monotonic() + 3
    while not rows(app) and time.monotonic() < deadline:
        time.sleep(.02)
    saved = rows(app)
    assert len(saved) == 1
    assert saved[0].status == 'aborted' and saved[0].input_tokens == 60
    assert saved[0].first_token_ms is not None
    app.state.ai_providers['claude'] = Fake()
    assert events(client.post('/api/ai/chat', json=BODY))[-1]['type'] == 'done'


def test_two_concurrent_chats_limit(app, client, live_server):
    app.state.ai_providers = {'claude': Fake(delay=10)}
    with httpx.Client(base_url=live_server, cookies=dict(client.cookies.items()), timeout=5) as connection:
        with connection.stream('POST', '/api/ai/chat', json=BODY) as first:
            assert first.status_code == 200
            with connection.stream('POST', '/api/ai/chat', json=BODY) as second:
                assert second.status_code == 200
                response = connection.post('/api/ai/chat', json=BODY)
                assert response.status_code == 429 and response.json()['code'] == 'ai_busy'


def test_five_model_step_bound_and_cross_step_deduplication(app, client, monkeypatch):
    count = []
    async def tool(*args):
        count.append(args[2])
        return '{"ok":true}', False
    class Loop(Fake):
        async def stream(self, spec, system, messages, tools):
            yield Event('usage', Usage(1, 0, 0, 2))
            yield Event('tool', ToolCall('a', 'attendance_today', {}))
            yield Event('stop', [{'type': 'tool_use', 'id': 'a', 'name': 'attendance_today', 'input': {}}])
    monkeypatch.setattr('backend.ai.agent.execute', tool)
    app.state.ai_providers = {'claude': Loop()}
    result = events(client.post('/api/ai/chat', json=BODY))
    assert result[-1]['code'] == 'ai_upstream'
    row = rows(app)[0]
    assert (row.steps, row.tool_calls, row.input_tokens, row.output_tokens, row.status) == (5, 1, 5, 10, 'error')
    assert count == ['attendance_today']


def test_tool_timeout_becomes_safe_result(app, client, monkeypatch):
    original = asyncio.wait_for
    async def short_timeout(awaitable, timeout):
        assert timeout == 15
        return await original(awaitable, timeout=.01)
    async def slow(*args):
        await asyncio.sleep(1)
    monkeypatch.setattr('backend.ai.agent.asyncio.wait_for', short_timeout)
    monkeypatch.setattr('backend.ai.agent.execute', slow)
    app.state.ai_providers = {'claude': Fake(calls=[ToolCall('a', 'attendance_today', {})])}
    result = events(client.post('/api/ai/chat', json=BODY))
    assert any(e['type'] == 'tool' and e['status'] == 'error' for e in result)
    assert '查詢逾時' in ''.join(e['delta'] for e in result if e['type'] == 'text')
    assert rows(app)[0].status == 'ok'


def test_fallback_model_is_recorded_unpriced(app, client):
    class Fallback(Fake):
        async def stream(self, *args):
            yield Event('usage', Usage(100, 20, 30, 40), 'claude-opus-4-8', True)
            yield Event('text', '完成')
            yield Event('stop', [{'type': 'text', 'text': '完成'}])
    role(client, 'u-manager')
    app.state.ai_providers = {'claude': Fallback()}
    result = events(client.post('/api/ai/chat', json=BODY))
    assert result[-1]['cost_usd'] is None
    row = rows(app)[0]
    assert row.model == 'claude-opus-4-8' and row.cost_micro_usd is None
    assert client.get('/api/ai/usage').json()['totals']['unpriced_calls'] == 1
