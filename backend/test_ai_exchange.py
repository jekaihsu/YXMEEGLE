import json

from .test_ai_database import app, client, ai_database_url
from .test_ai_api import BODY, Fake, events, live_server
from .test_backend import role


def test_exchange_routes(app, client):
    app.state.ai_providers = {'claude': Fake()}
    uid = events(client.post('/api/ai/chat', json=BODY))[0]['usage_id']
    assert client.get(f'/api/ai/usage/{uid}/exchange').status_code == 403
    assert client.get('/api/ai/usage/export').status_code == 403
    role(client, 'u-manager')
    response = client.get(f'/api/ai/usage/{uid}/exchange')
    assert response.status_code == 200
    value = response.json()
    assert value['question'] == '查詢公司資料'
    assert value['answer'] == '截至目前，查詢完成'
    assert value['tools'] == []
    recent, = client.get('/api/ai/usage').json()['recent']
    assert recent['usage_id'] == uid
    assert recent['question_preview'] == '查詢公司資料'
    assert recent['answer_preview'] == value['answer']
    exported, = [json.loads(line) for line in client.get('/api/ai/usage/export').text.splitlines()]
    assert exported['question'] == value['question']
    assert client.get('/api/ai/usage/missing/exchange').status_code == 404


def ask(app, client, text, adapter=None):
    app.state.ai_providers = {'claude': adapter or Fake()}
    body = dict(BODY, messages=[dict(role='user', content='earlier secret'),
                              dict(role='assistant', content='earlier answer'),
                              dict(role='user', content=text)])
    return events(client.post('/api/ai/chat', json=body))[0]['usage_id']


def detail(client, uid):
    role(client, 'u-manager')
    response = client.get(f'/api/ai/usage/{uid}/exchange')
    assert response.status_code == 200, response.text
    return response.json()


def test_redaction_last_turn_and_caps(app, client):
    from .ai.providers import Event
    class LongAnswer(Fake):
        async def stream(self, *args):
            yield Event('text', 'Bearer abc.secret sk-aaaaaaaaaaaaaaaa 1234567890123 42 ' + '答' * 21000)
            yield Event('stop', [])
    uid = ask(app, client, 'sk-bbbbbbbbbbbbbbbb Bearer xyz.secret A123456789 1234 ' + '問' * 3900, LongAnswer())
    value = detail(client, uid)
    assert value['question'].startswith('[redacted] [redacted] [redacted] 1234 ')
    assert 'earlier' not in value['question']
    assert value['answer'].startswith('[redacted] [redacted] [redacted] 42 ')
    assert len(value['question']) <= 4000 and len(value['answer']) <= 20000
    uid = ask(app, client, '問' * 4000, LongAnswer())
    assert len(detail(client, uid)['question']) == 4000
    recent = client.get('/api/ai/usage').json()['recent'][0]
    assert recent['question_preview'] == '問' * 120
    assert len(recent['answer_preview']) == 120


def test_search_literal_and_composed_filters(app, client):
    role(client, 'u-manager')
    uid = ask(app, client, r'MixedCase 50% a_b c\d')
    role(client, 'u-manager')
    for query in ['mixedcase', '%', '_', '\\', '查詢完成']:
        result = client.get('/api/ai/usage', params={'q': query}).json()
        assert [r['usage_id'] for r in result['recent']] == [uid]
        exported = client.get('/api/ai/usage/export', params={'q': query})
        assert [json.loads(line)['usage_id'] for line in exported.text.splitlines()] == [uid]
    for query in ['absent', 'aXb', 'cXd']:
        assert client.get('/api/ai/usage', params={'q': query}).json()['recent'] == []
    assert client.post('/api/ai/feedback', json=dict(usage_id=uid, rating='down', reason='wrong')).status_code == 200
    params = dict(q='mixed', actor='u-member', provider='claude', rating='down', scope='global')
    params['actor'] = detail(client, uid)['actor_id']
    assert client.get('/api/ai/usage', params=params).json()['totals']['questions'] == 1
    for key, value in [('actor', 'missing'), ('provider', 'gpt'), ('rating', 'up'), ('scope', 'project')]:
        assert client.get('/api/ai/usage', params={**params, key: value}).json()['recent'] == []
    assert client.get('/api/ai/usage', params={'q': 'x' * 201}).status_code == 422


def test_off_switch_hides_existing_content_and_disables_writes(app, client):
    from .ai.ledger import AiExchangeRow
    from sqlalchemy import select
    uid = ask(app, client, 'stored')
    app.state.ai_store_content = False
    value = detail(client, uid)
    assert (value['question'], value['answer'], value['tools'], value['error_detail']) == (None, None, [], None)
    recent = client.get('/api/ai/usage').json()['recent'][0]
    assert recent['question_preview'] is recent['answer_preview'] is None
    assert client.get('/api/ai/usage?q=stored').json()['recent'] == []
    assert json.loads(client.get('/api/ai/usage/export').text)['question'] is None
    second = ask(app, client, 'not stored')
    with app.state.sessions() as db:
        assert db.get(AiExchangeRow, second) is None
        assert {row.usage_id for row in db.scalars(select(AiExchangeRow))} <= {uid}


def test_workspace_isolation(app, client):
    from .ai.ledger import AiUsageRow, AiExchangeRow
    uid = ask(app, client, 'private')
    role(client, 'u-manager')
    with app.state.sessions.begin() as db:
        db.get(AiUsageRow, uid).workspace_id = 'another-workspace'
        db.get(AiExchangeRow, uid).workspace_id = 'another-workspace'
    assert client.get(f'/api/ai/usage/{uid}/exchange').json() == client.get('/api/ai/usage/unknown/exchange').json()
    assert client.get(f'/api/ai/usage/{uid}/exchange').status_code == 404
    assert client.get('/api/ai/usage?q=private').json()['recent'] == []
    assert client.get('/api/ai/usage/export').text == ''


def test_error_partial_answer_and_detail(app, client):
    from .ai.providers import Event, ProviderError
    role(client, 'u-manager')
    class Failure(Fake):
        async def stream(self, *args):
            yield Event('text', 'partial answer')
            error = ProviderError()
            error.diagnostics = dict(status_code=401, upstream_code='invalid_api_key', upstream_type=None,
                upstream_param=None, request_id=None, last_event_type=None, message=None)
            raise error
    uid = ask(app, client, 'failure', Failure())
    value = detail(client, uid)
    assert value['status'] == 'error'
    assert value['answer'] == 'partial answer'
    assert value['error_detail'] == 'Anthropic 401 invalid_api_key'
    assert client.get('/api/ai/usage').json()['recent'][0]['error_detail'] == value['error_detail']


def test_retention_cleanup_and_hourly_gate(app, client, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from .ai import ledger
    monkeypatch.setattr(ledger, 'schedule_cleanup', ledger.cleanup_content)
    uid = ask(app, client, 'expired')
    with app.state.sessions.begin() as db:
        db.get(ledger.AiExchangeRow, uid).created_at = datetime.now(timezone.utc) - timedelta(days=91)
    assert detail(client, uid)['question'] is None
    monkeypatch.setattr(ledger, '_last_cleanup', None)
    ask(app, client, 'cleanup')
    with app.state.sessions() as db:
        assert db.get(ledger.AiExchangeRow, uid) is None
        assert db.get(ledger.AiUsageRow, uid) is not None
    uid = ask(app, client, 'hourly')
    with app.state.sessions.begin() as db:
        db.get(ledger.AiExchangeRow, uid).created_at = datetime.now(timezone.utc) - timedelta(days=91)
    ask(app, client, 'same hour')
    with app.state.sessions() as db:
        assert db.get(ledger.AiExchangeRow, uid) is not None
    monkeypatch.setattr(ledger, 'monotonic', lambda: ledger._last_cleanup + 3601)
    ask(app, client, 'next hour')
    with app.state.sessions() as db:
        assert db.get(ledger.AiExchangeRow, uid) is None


def test_finish_failure_is_nonfatal(app, client, monkeypatch):
    from .ai import ledger
    def broken(*args, **kwargs):
        raise RuntimeError('database unavailable')
    monkeypatch.setattr(ledger, 'record', broken)
    app.state.ai_providers = {'claude': Fake()}
    assert events(client.post('/api/ai/chat', json=BODY))[-1]['type'] == 'done'


def test_record_retry_and_idempotence(app, client, monkeypatch):
    from .ai import ledger
    uid = ask(app, client, 'original')
    with app.state.sessions() as db:
        row = db.get(ledger.AiUsageRow, uid)
        values = {c.name: getattr(row, c.name) for c in ledger.AiUsageRow.__table__.columns if c.name not in ('day', 'created_at')}
    for _ in range(2):
        ledger.record(app.state.sessions, exchange=dict(question='replacement', answer='new', tools=[], error_detail=None), **values)
    assert detail(client, uid)['question'] == 'original'
    real = app.state.sessions
    class Flaky:
        calls = 0
        def begin(self):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError('transient')
            return real.begin()
    sessions = Flaky()
    values['id'] = 'retried'
    ledger.record(sessions, exchange=dict(question='retry', answer='saved', tools=[], error_detail=None), **values)
    assert sessions.calls == 3
    assert detail(client, 'retried')['answer'] == 'saved'


def test_legacy_exchange_created_at_startup(ai_database_url, tmp_path):
    from sqlalchemy import create_engine, inspect
    from .app import create_app
    from .test_ai_database import app_config
    from .ai import ledger
    engine = create_engine(ai_database_url)
    ledger.ensure_schema(engine)
    ledger.AiExchangeRow.__table__.drop(engine)
    application = create_app(app_config(ai_database_url, tmp_path))
    try:
        assert 'ai_exchange' in inspect(engine).get_table_names()
        ledger.ensure_schema(engine)
    finally:
        application.state.sessions.kw['bind'].dispose()
        engine.dispose()


def test_socket_end_does_not_wait_for_exchange_write(app, client, live_server, monkeypatch):
    import httpx
    import threading
    from .ai import ledger
    entered, release = threading.Event(), threading.Event()
    original = ledger.record
    def delayed(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        original(*args, **kwargs)
    monkeypatch.setattr(ledger, 'record', delayed)
    app.state.ai_providers = {'claude': Fake()}
    try:
        with httpx.Client(base_url=live_server, cookies=dict(client.cookies.items()), timeout=2) as connection:
            response = connection.post('/api/ai/chat', json=BODY)
            assert events(response)[-1]['type'] == 'done'
            assert entered.wait(2)
            assert connection.get('/api/ai/models').status_code == 200
    finally:
        release.set()


def test_tools_only_names_and_no_context(app, client):
    from .ai.providers import Event, ToolCall
    class ToolAnswer(Fake):
        async def stream(self, *args):
            if not self.inputs:
                self.inputs.append(True)
                yield Event('tool', ToolCall('c1', 'attendance_today', {}))
                yield Event('stop', [])
            else:
                yield Event('text', 'final text')
                yield Event('stop', [])
    uid = ask(app, client, 'tool question', ToolAnswer())
    value = detail(client, uid)
    assert value['tools'] == ['attendance_today']
    assert value['answer'] == 'final text'
    from .ai.ledger import AiExchangeRow
    with app.state.sessions() as db:
        row = db.get(AiExchangeRow, uid)
        assert json.loads(row.tool_names) == ['attendance_today']
        assert set(row.__table__.columns.keys()) == {'usage_id', 'workspace_id', 'actor_id', 'question', 'answer', 'tool_names', 'error_detail', 'created_at'}


def test_aborted_exchange_contains_partial_stream(app, client, live_server):
    import httpx
    import time
    from .ai.ledger import AiExchangeRow
    from sqlalchemy import select
    app.state.ai_providers = {'claude': Fake(delay=10)}
    with httpx.Client(base_url=live_server, cookies=dict(client.cookies.items()), timeout=5) as connection:
        with connection.stream('POST', '/api/ai/chat', json=BODY) as response:
            for line in response.iter_lines():
                if '"type": "text"' in line:
                    break
    deadline = time.monotonic() + 3
    saved = None
    while saved is None and time.monotonic() < deadline:
        with app.state.sessions() as db:
            saved = db.scalar(select(AiExchangeRow))
        if saved is None:
            time.sleep(.02)
    assert saved is not None
    assert saved.question == '查詢公司資料'
    assert saved.answer == '截至目前，'
    assert detail(client, saved.usage_id)['status'] == 'aborted'


def test_exchange_json_database_parity(ai_database_url, tmp_path):
    from datetime import datetime, timezone
    from fastapi.testclient import TestClient
    from .app import create_app
    from .test_ai_database import app_config
    from .test_ai_api import wid
    from .test_ai_postgres import values
    from .ai import ledger
    outputs = []
    timestamp = datetime.now(timezone.utc).replace(microsecond=0)
    for url in (f'sqlite:///{tmp_path}/reference.db', ai_database_url):
        application = create_app(app_config(url, tmp_path))
        try:
            with TestClient(application) as connection:
                connection.get('/api/session')
                role(connection, 'u-manager')
                workspace = wid(application, connection)
                with application.state.sessions.begin() as db:
                    data = values()
                    data.update(id='parity', workspace_id=workspace, created_at=timestamp, day=ledger.today())
                    db.add(ledger.AiUsageRow(**data))
                    db.add(ledger.AiExchangeRow(usage_id='parity', workspace_id=workspace, actor_id='a',
                        created_at=timestamp, question='測試 MiXeD % _ \\', answer='回答', tool_names='["attendance_today"]',
                        error_detail='OpenAI 401 invalid_api_key'))
                ledger.feedback(application.state.sessions, 'parity', 'a', 'down', 'wrong')
                outputs.append([
                    connection.get('/api/ai/usage', params={'q': 'mixed'}).json(),
                    connection.get('/api/ai/usage/parity/exchange').json(),
                    connection.get('/api/ai/usage/export', params={'q': '%', 'rating': 'down'}).text])
        finally:
            application.state.sessions.kw['bind'].dispose()
    assert outputs[0] == outputs[1]


def test_export_limit_and_question_answer_caps(app, client):
    from .ai.providers import Event
    class Full(Fake):
        async def stream(self, *args):
            yield Event('text', 'a' * 21000)
            yield Event('stop', [])
    uid = ask(app, client, 'q' * 4000, Full())
    value = detail(client, uid)
    assert value['question'] == 'q' * 4000
    assert value['answer'] == 'a' * 20000
    from .ai import ledger
    from .test_ai_postgres import values
    from .test_ai_api import wid
    from datetime import datetime, timezone
    with app.state.sessions.begin() as db:
        for i in range(501):
            data = values()
            data.update(id=f'bulk-{i}', workspace_id=wid(app, client), created_at=datetime.now(timezone.utc), day=ledger.today())
            db.add(ledger.AiUsageRow(**data))
    assert len(client.get('/api/ai/usage/export').text.splitlines()) == 500
    assert len(client.get('/api/ai/usage').json()['recent']) == 50


def test_member_failure_stores_manager_detail_without_streaming_it(app, client):
    from .ai.providers import Event, ProviderError
    class Failure(Fake):
        async def stream(self, *args):
            yield Event('text', 'partial')
            error = ProviderError()
            error.diagnostics = dict(status_code=401, upstream_code='invalid_api_key', upstream_type=None,
                upstream_param=None, request_id=None, last_event_type=None, message=None)
            raise error
    app.state.ai_providers = {'gpt': Failure()}
    result = events(client.post('/api/ai/chat', json=dict(BODY, model='gpt')))
    assert 'detail' not in result[-1]
    value = detail(client, result[0]['usage_id'])
    assert value['error_detail'] == 'OpenAI 401 invalid_api_key'
    assert value['answer'] == 'partial'
