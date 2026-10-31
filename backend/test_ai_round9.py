import json
from datetime import datetime, timedelta, timezone
from threading import Event

import pytest
from sqlalchemy import event, select

from .ai import ledger
from .test_ai_database import ai_database_url, app, app_config, client
from .test_ai_api import BODY, Fake, events, live_server
from .test_ai_postgres import values
from .test_backend import role


@pytest.mark.parametrize('sample', [
    'sk-' + 'a' * 16, 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.signature',
    'AIza' + 'a' * 35, 'ghp_' + 'a' * 36, 'xoxb-123456789-abcdef',
    'xoxa-123456789-abcdef', 'xoxp-123456789-abcdef', 'xoxr-123456789-abcdef',
    'password=hunter2', 'token=abc123', 'secret="two words"', 'Bearer abc.def',
    '0912-345-678', '0912 345 678', '0912345678', 'A123456789',
    '1234567890123', '1234 5678 9012 3456',
])
def test_redaction_sensitive(sample):
    assert '[redacted]' in ledger.redact(sample, 4000)
    assert sample not in ledger.redact(sample, 4000)


@pytest.mark.parametrize('sample', ['risk-based', 'task-force', 'disk-usage', 'mask-1', 'Task-4',
                                    '123456789', '12345678901', '123456789012', 'sk-short'])
def test_redaction_preserves_orders_and_words(sample):
    assert ledger.redact(sample, 4000) == sample


def test_redaction_controls():
    assert ledger.redact('a\x00\x01\x08\x0b\x1f\x7f\x85b\n\tc', 4000) == 'ab\n\tc'


@pytest.mark.parametrize('field', ['question', 'answer'])
def test_nul_content_accounted(app, field):
    exchange = dict(question='question', answer='answer', tools=[], error_detail=None)
    exchange[field] = 'before\x00after'
    ledger.record(app.state.sessions, id='nul', exchange=exchange, **values())
    with app.state.sessions() as db:
        assert db.get(ledger.AiUsageRow, 'nul').input_tokens == 3_000_000_000
        assert getattr(db.get(ledger.AiExchangeRow, 'nul'), field) == 'beforeafter'


def test_exchange_failure_keeps_accounting(app):
    engine = app.state.sessions.kw['bind']
    def fail(conn, cursor, statement, *args):
        if statement.startswith('INSERT INTO ai_exchange'):
            raise RuntimeError('forced exchange failure')
    event.listen(engine, 'before_cursor_execute', fail)
    try:
        ledger.record(app.state.sessions, id='failure', exchange=dict(question='q', answer='a', tools=[], error_detail=None), **values())
    finally:
        event.remove(engine, 'before_cursor_execute', fail)
    with app.state.sessions() as db:
        assert db.get(ledger.AiUsageRow, 'failure') is not None
        assert db.get(ledger.AiExchangeRow, 'failure') is None


def test_request_nul_rejected(app, client):
    app.state.ai_providers = {'claude': Fake()}
    response = client.post('/api/ai/chat', json=dict(BODY, messages=[dict(role='user', content='bad\x00text')]))
    assert response.status_code == 422


@pytest.mark.parametrize('raw, expected', [(s, True) for s in ('true', '1', 'yes', 'on', ' TRUE ')] +
                         [(s, False) for s in ('false', '0', 'no', 'off', ' OFF ', '', 'typo')])
def test_content_config(raw, expected, tmp_path, caplog):
    from .app import create_app
    cfg = app_config(f'sqlite:///{tmp_path}/config.db', tmp_path)
    cfg['AI_STORE_CONTENT'] = raw
    application = create_app(cfg)
    try:
        assert application.state.ai_store_content is expected
        if raw in ('', 'typo'):
            assert 'AI_STORE_CONTENT' in caplog.text
    finally:
        application.state.sessions.kw['bind'].dispose()


@pytest.mark.parametrize('raw', ['bad', '', '-1'])
def test_bad_retention_routes_and_ledger(raw, ai_database_url, tmp_path, caplog):
    from fastapi.testclient import TestClient
    from .app import create_app
    cfg = app_config(ai_database_url, tmp_path)
    cfg['AI_CONTENT_RETENTION_DAYS'] = raw
    application = create_app(cfg)
    try:
        assert application.state.ai_content_retention_days == 90
        assert 'AI_CONTENT_RETENTION_DAYS' in caplog.text
        with TestClient(application) as connection:
            connection.get('/api/session')
            application.state.ai_providers = {'claude': Fake()}
            uid = events(connection.post('/api/ai/chat', json=BODY))[0]['usage_id']
            role(connection, 'u-manager')
            assert connection.get('/api/ai/usage').json()['totals']['questions'] == 1
            assert connection.get('/api/ai/usage/export').status_code == 200
            assert connection.get(f'/api/ai/usage/{uid}/exchange').json()['answer'] == '截至目前，查詢完成'
    finally:
        application.state.sessions.kw['bind'].dispose()


def test_cleanup_retry_batches_and_lock(app, monkeypatch):
    monkeypatch.setattr(ledger, '_last_cleanup', None)
    sessions = app.state.sessions
    with sessions.begin() as db:
        db.add_all([ledger.AiExchangeRow(usage_id=str(i), workspace_id='w', actor_id='a',
            question='q', answer='a', tool_names='[]', created_at=datetime.now(timezone.utc) - timedelta(days=91)) for i in range(1201)])
    engine = sessions.kw['bind']
    batches = []
    def capture(conn, cursor, statement, parameters, *args):
        if statement.startswith('DELETE FROM ai_exchange'):
            assert ledger._cleanup_lock.acquire(blocking=False)
            ledger._cleanup_lock.release()
            batches.append(len(parameters))
            if len(batches) == 1:
                raise RuntimeError('retry required')
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        with pytest.raises(RuntimeError):
            ledger.cleanup_content(sessions, 90)
        assert ledger._last_cleanup is None
        ledger.cleanup_content(sessions, 90)
        assert batches == [500, 500, 500, 201]
        with sessions() as db:
            assert db.scalar(select(ledger.AiExchangeRow)) is None
        ledger.cleanup_content(sessions, 90)
        assert len(batches) == 4
    finally:
        event.remove(engine, 'before_cursor_execute', capture)


def test_cleanup_does_not_delay_feedback(app, client, live_server, monkeypatch):
    import httpx
    from concurrent.futures import ThreadPoolExecutor
    writing, allow_write, cleaning, release_cleanup, waiting = Event(), Event(), Event(), Event(), Event()
    original = ledger.record
    def record(*args, **kwargs):
        writing.set()
        assert allow_write.wait(5)
        original(*args, **kwargs)
    def cleanup(*args):
        cleaning.set()
        assert release_cleanup.wait(5)
    original_owns = ledger.owns_usage
    def owns(*args):
        owned = original_owns(*args)
        if not owned:
            waiting.set()
        return owned
    monkeypatch.setattr(ledger, 'owns_usage', owns)
    monkeypatch.setattr(ledger, 'record', record)
    monkeypatch.setattr(ledger, 'cleanup_content', cleanup)
    app.state.ai_providers = {'claude': Fake()}
    try:
        with httpx.Client(base_url=live_server, cookies=dict(client.cookies.items()), timeout=2) as connection:
            uid = events(connection.post('/api/ai/chat', json=BODY))[0]['usage_id']
            assert writing.wait(2)
            with ThreadPoolExecutor(1) as pool:
                pending = pool.submit(connection.post, '/api/ai/feedback', json=dict(usage_id=uid, rating='up'))
                assert waiting.wait(2)
                allow_write.set()
                assert cleaning.wait(2)
                assert pending.result(timeout=2).status_code == 200
                assert not release_cleanup.is_set()
    finally:
        allow_write.set()
        release_cleanup.set()


def test_usage_read_purges_when_off(app, client, monkeypatch):
    monkeypatch.setattr(ledger, '_last_cleanup', None)
    app.state.ai_store_content = False
    with app.state.sessions.begin() as db:
        db.add(ledger.AiExchangeRow(usage_id='old', workspace_id='w', actor_id='a', question='q', answer='a', tool_names='[]', created_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
    role(client, 'u-manager')
    assert client.get('/api/ai/usage').status_code == 200
    with app.state.sessions() as db:
        assert db.get(ledger.AiExchangeRow, 'old') is None


def test_export_skips_aggregates_and_reports_cap(app, client):
    from .test_ai_api import wid
    role(client, 'u-manager')
    workspace = wid(app, client)
    with app.state.sessions.begin() as db:
        for i in range(501):
            data = values()
            data.update(id=str(i), workspace_id=workspace, created_at=datetime.now(timezone.utc), day=ledger.today())
            db.add(ledger.AiUsageRow(**data))
    engine = app.state.sessions.kw['bind']
    statements = []
    def capture(conn, cursor, statement, *args):
        statements.append(statement.lower())
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        response = client.get('/api/ai/usage/export')
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    rows = [json.loads(line) for line in response.text.splitlines()]
    assert response.headers['X-Export-Truncated'] == 'true'
    assert response.headers['X-Export-Row-Count'] == '500'
    assert len(rows) == 501
    assert rows[-1] == dict(truncated=True, limit=500, row_count=500)
    assert not any('sum(' in s or 'count(' in s or 'row_number(' in s for s in statements)


@pytest.mark.parametrize('raw, expected', [('0', 0), (' 12 ', 12), ('365', 365)])
def test_valid_retention(raw, expected):
    assert ledger.content_retention({'AI_CONTENT_RETENTION_DAYS': raw}) == expected


def test_settings_are_parsed_once(app, client):
    app.state.cfg['AI_STORE_CONTENT'] = 'off'
    app.state.cfg['AI_CONTENT_RETENTION_DAYS'] = 'bad'
    app.state.ai_providers = {'claude': Fake()}
    uid = events(client.post('/api/ai/chat', json=BODY))[0]['usage_id']
    role(client, 'u-manager')
    assert client.get('/api/ai/usage').json()['totals']['questions'] == 1
    assert client.get(f'/api/ai/usage/{uid}/exchange').json()['question'] == '查詢公司資料'
