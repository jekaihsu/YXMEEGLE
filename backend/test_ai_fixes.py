import asyncio

from .test_backend import app, client, role
from .test_ai_api import BODY, Fake, events, rows, live_server
from .ai.providers import Event
from .test_tenant_read_views import tenant_views


def test_role_specific_history_limits(app, client):
    app.state.ai_providers = {'claude': Fake()}
    for size, status in [(20000, 200), (20001, 422)]:
        body = dict(BODY, messages=[{'role': 'assistant', 'content': 'x' * size}, *BODY['messages']])
        assert client.post('/api/ai/chat', json=body).status_code == status


def test_deadline_estimates_and_releases(app, client, monkeypatch, caplog):
    class NoUsage(Fake):
        async def stream(self, *args):
            yield Event('text', '已產生文字')
            await asyncio.sleep(10)
    monkeypatch.setattr('backend.ai.agent.QUESTION_TIMEOUT_SECONDS', .02, raising=False)
    app.state.ai_providers = {'claude': NoUsage()}
    result = events(client.post('/api/ai/chat', json=BODY))
    assert result[-1]['code'] == 'ai_upstream' and '逾時' in result[-1]['message']
    row = rows(app)[0]
    assert row.input_tokens > 0 and row.output_tokens == len('已產生文字')
    assert row.cost_micro_usd > 0 and row.error_code == 'usage_estimated'
    assert 'TimeoutError' in caplog.text
    app.state.ai_providers['claude'] = Fake()
    assert events(client.post('/api/ai/chat', json=BODY))[-1]['type'] == 'done'


def test_usage_range_and_unpriced_groups(app, client):
    role(client, 'u-manager')
    assert client.get('/api/ai/usage?from=2020-01-01&to=2022-01-01').status_code == 422
    app.state.ai_providers = {'claude': Fake()}
    events(client.post('/api/ai/chat', json=BODY))
    result = client.get('/api/ai/usage').json()
    assert result['by_person'][0]['unpriced_calls'] == 0
    assert result['by_provider'][0]['unpriced_calls'] == 0


def test_disconnect_without_usage_is_estimated(app, client, live_server):
    import httpx
    import time
    class NoUsage(Fake):
        async def stream(self, *args):
            yield Event('text', '尚未回報用量')
            await asyncio.sleep(10)
    app.state.ai_providers = {'claude': NoUsage()}
    with httpx.Client(base_url=live_server, cookies=dict(client.cookies.items()), timeout=5) as connection:
        with connection.stream('POST', '/api/ai/chat', json=BODY) as response:
            for line in response.iter_lines():
                if '"type": "text"' in line:
                    break
    deadline = time.monotonic() + 3
    while not rows(app) and time.monotonic() < deadline:
        time.sleep(.02)
    row, = rows(app)
    assert row.status == 'aborted' and row.error_code == 'usage_estimated'
    assert row.input_tokens > 0 and row.output_tokens == len('尚未回報用量') and row.cost_micro_usd > 0


def test_partial_usage_is_estimated_and_error_log_is_safe(app, client, caplog):
    from .ai.catalog import Usage
    class SDKFailure(Exception):
        status_code = 502
        request_id = 'req-safe'
    class Partial(Fake):
        async def stream(self, *args):
            yield Event('usage', Usage(10, 0, 0, 0), final_usage=False)
            yield Event('text', '文字')
            raise SDKFailure('secret prompt cookie')
    app.state.ai_providers = {'claude': Partial()}
    assert events(client.post('/api/ai/chat', json=BODY))[-1]['code'] == 'ai_upstream'
    row, = rows(app)
    assert row.error_code == 'usage_estimated' and row.input_tokens > 10 and row.output_tokens == 2
    assert 'exception=SDKFailure status_code=502 request_id=req-safe' in caplog.text
    assert 'secret prompt cookie' not in caplog.text


def test_ledger_retries_off_event_loop(app, client, monkeypatch):
    import threading
    from .ai import ledger
    original = ledger.record
    loop_threads, threads = [], []
    class Observed(Fake):
        async def stream(self, *args):
            loop_threads.append(threading.get_ident())
            async for event in super().stream(*args):
                yield event
    def record(*args, **kwargs):
        threads.append(threading.get_ident())
        return original(*args, **kwargs)
    monkeypatch.setattr(ledger, 'record', record)
    app.state.ai_providers = {'claude': Observed()}
    events(client.post('/api/ai/chat', json=BODY))
    assert threads and loop_threads and set(threads).isdisjoint(loop_threads)
    assert len(rows(app)) == 1


def test_forbidden_body(tmp_path):
    from .test_production_access import company
    from .app import PersonRow
    app, client = company(tmp_path)
    with app.state.sessions.begin() as db:
        person = db.get(PersonRow, ('lark-company', 'u-manager'))
        person.data = {**person.data, 'directory_missing': True}
    for path in ['/api/ai/models', '/api/ai/usage']:
        response = client.get(path)
        assert response.status_code == 403
        assert response.json() == {'code': 'ai_forbidden', 'message': '你沒有權限使用此 AI 功能'}
    assert client.post('/api/ai/chat', json=BODY).json()['code'] == 'ai_forbidden'


def test_ledger_transient_retry(app, client, monkeypatch, caplog):
    from contextlib import contextmanager
    original = app.state.sessions.begin
    attempts = []
    @contextmanager
    def flaky():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError('private SQL parameters')
        with original() as db:
            yield db
    monkeypatch.setattr(app.state.sessions, 'begin', flaky)
    app.state.ai_providers = {'claude': Fake()}
    events(client.post('/api/ai/chat', json=BODY))
    assert len(attempts) == 2 and len(rows(app)) == 1
    assert 'ai_usage_write_failed' not in caplog.text and 'private SQL' not in caplog.text


def test_tenant_without_ai_admission_has_clear_body(tenant_views):
    app, client, ids = tenant_views
    assert client.get('/api/projects').status_code == 200
    for path in ['/api/ai/models', '/api/ai/usage']:
        response = client.get(path)
        assert response.status_code == 403 and response.json()['code'] == 'ai_forbidden'
    assert client.post('/api/ai/chat', json=BODY).json()['code'] == 'ai_forbidden'


def test_usage_uses_latest_name_and_group_unpriced_counts(app, client):
    from datetime import datetime, timedelta, timezone
    from .ai.ledger import AiUsageRow
    role(client, 'u-manager')
    app.state.ai_providers = {'claude': Fake()}
    events(client.post('/api/ai/chat', json=BODY))
    original = rows(app)[0]
    with app.state.sessions.begin() as db:
        first = db.get(AiUsageRow, original.id)
        first.actor_name = 'ZZZ old'
        newer = {k: v for k, v in original.__dict__.items() if k not in ('id', '_sa_instance_state')}
        newer.update(actor_name='AAA new', cost_micro_usd=None,
                     created_at=datetime.now(timezone.utc) + timedelta(seconds=1))
        db.add(AiUsageRow(**newer))
    result = client.get('/api/ai/usage').json()
    assert result['by_person'][0]['name'] == result['people'][0]['name'] == 'AAA new'
    assert result['by_person'][0]['unpriced_calls'] == result['by_provider'][0]['unpriced_calls'] == 1


def test_length_finish_is_ok_even_with_incomplete_tool(app, client):
    from .ai.catalog import Usage
    from .ai.providers import ToolCall
    class Length(Fake):
        async def stream(self, *args):
            yield Event('text', '回答')
            yield Event('tool', ToolCall('partial', 'case_owners', {}))
            yield Event('usage', Usage(10, 0, 0, 20))
            yield Event('text', '（回答太長，已截斷）')
            yield Event('stop', [], truncated=True)
    app.state.ai_providers = {'claude': Length()}
    result = events(client.post('/api/ai/chat', json=BODY))
    assert result[-1]['type'] == 'done'
    row, = rows(app)
    assert row.status == 'ok' and row.tool_calls == 0 and row.cost_micro_usd > 0
