from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect, select

from .app import create_app
from .ai import ledger
from .models import Base
from .test_ai_database import ai_database_url, app, app_config, client
from .test_ai_api import wid
from .test_backend import role


# Frozen from c9659a8e, before scope and project_id shipped.
LEGACY_USAGE = '''CREATE TABLE ai_usage (
    id VARCHAR(36) NOT NULL PRIMARY KEY, created_at TIMESTAMP WITH TIME ZONE NOT NULL, day VARCHAR(10) NOT NULL,
    workspace_id VARCHAR(120) NOT NULL, actor_id VARCHAR(120) NOT NULL,
    actor_name VARCHAR(240) NOT NULL, conversation_id VARCHAR(120) NOT NULL,
    provider VARCHAR(16) NOT NULL, model VARCHAR(120) NOT NULL, effort VARCHAR(24) NOT NULL,
    input_tokens BIGINT NOT NULL, cache_read_tokens BIGINT NOT NULL,
    cache_write_tokens BIGINT NOT NULL, output_tokens BIGINT NOT NULL,
    cost_micro_usd BIGINT, price_version VARCHAR(120) NOT NULL, steps INTEGER NOT NULL,
    tool_calls INTEGER NOT NULL, latency_ms INTEGER NOT NULL, first_token_ms INTEGER,
    status VARCHAR(16) NOT NULL, error_code VARCHAR(64))'''


def values(**extra):
    return dict(workspace_id='w', actor_id='a', actor_name='Old name', conversation_id='c',
                provider='claude', model='m', effort='medium', input_tokens=3_000_000_000,
                cache_read_tokens=0, cache_write_tokens=0, output_tokens=7,
                cost_micro_usd=11, price_version='v', steps=1, tool_calls=0,
                latency_ms=10, status='ok', **extra)


def test_legacy_boot_upgrade_and_concurrent_apps(ai_database_url, tmp_path):
    engine = create_engine(ai_database_url)
    Base.metadata.create_all(engine)
    with engine.begin() as db:
        ledger.AiUsageRow.__table__.drop(db)
        db.exec_driver_sql(LEGACY_USAGE)
        for name in ('day', 'actor_id'):
            db.exec_driver_sql(f'CREATE INDEX ix_ai_usage_{name} ON ai_usage ({name})')
        for uid in ('old-1', 'old-2'):
            db.exec_driver_sql("INSERT INTO ai_usage (id, created_at, day, workspace_id, actor_id, actor_name, conversation_id, provider, model, effort, input_tokens, cache_read_tokens, cache_write_tokens, output_tokens, price_version, steps, tool_calls, latency_ms, status) VALUES ('" + uid + "', '2026-10-30 15:30:00', '2026-10-30', 'w', 'a', 'Name', 'c', 'claude', 'm', 'medium', 1, 0, 0, 1, 'v', 1, 0, 1, 'ok')")
    barrier = Barrier(2)
    def boot(_):
        barrier.wait(timeout=10)
        return create_app(app_config(ai_database_url, tmp_path))
    with ThreadPoolExecutor(2) as pool:
        applications = list(pool.map(boot, range(2)))
    try:
        assert {'scope', 'project_id'} <= {c['name'] for c in inspect(engine).get_columns('ai_usage')}
        with applications[0].state.sessions() as db:
            rows = db.scalars(select(ledger.AiUsageRow).order_by(ledger.AiUsageRow.id)).all()
            assert [(r.id, r.scope, r.project_id, r.actor_name) for r in rows] == [
                ('old-1', 'global', None, 'Name'), ('old-2', 'global', None, 'Name')]
        statements = []
        def capture(conn, cursor, statement, *args):
            statements.append(statement)
        event.listen(engine, 'before_cursor_execute', capture)
        ledger.ensure_schema(engine)
        assert not any(s.startswith(('ALTER', 'CREATE', 'UPDATE')) for s in statements)
        third = create_app(app_config(ai_database_url, tmp_path))
        third.state.sessions.kw['bind'].dispose()
        assert ledger.query(applications[0].state.sessions, 'w', '2026-10-30', '2026-10-30')['totals']['questions'] == 2
    finally:
        for application in applications:
            application.state.sessions.kw['bind'].dispose()
        engine.dispose()


def test_concurrent_record_and_feedback(app, monkeypatch):
    clock = datetime(2026, 10, 30, 16, 30, tzinfo=timezone.utc)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock.astimezone(tz)
    monkeypatch.setattr(ledger, 'datetime', Clock)
    monkeypatch.setattr(ledger, 'today', lambda: '2026-10-31')
    sessions = app.state.sessions
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda i: ledger.record(sessions, id=f'row-{i}', **values()), range(24)))
        list(pool.map(lambda i: ledger.record(sessions, id='same', **values()), range(16)))
        list(pool.map(lambda i: ledger.feedback(sessions, 'same', 'a', 'up' if i % 2 else 'down', None), range(24)))
    with sessions() as db:
        saved = db.scalars(select(ledger.AiUsageRow)).all()
        ratings = db.scalars(select(ledger.AiFeedbackRow)).all()
        assert len(saved) == 25
        assert {r.day for r in saved} == {'2026-10-31'}
        assert len(ratings) == 1 and ratings[0].rating in (-1, 1)
    assert ledger.daily_tokens(sessions, 'w', 'a') == 25 * 3_000_000_007
    ledger.feedback(sessions, 'same', 'a', 'down', 'wrong')
    assert ledger.query(sessions, 'w', '2026-10-31', '2026-10-31')['reasons']['wrong'] == 1


def test_usage_json_backend_parity(ai_database_url, tmp_path):
    outputs = []
    for url in (f'sqlite:///{tmp_path}/reference.db', ai_database_url):
        application = create_app(app_config(url, tmp_path))
        try:
            with TestClient(application) as connection:
                assert connection.get('/api/session').status_code == 200
                role(connection, 'u-manager')
                workspace = wid(application, connection)
                with application.state.sessions.begin() as db:
                    for i in range(6):
                        timestamp = datetime(2026, 10, 30, 15 if i < 3 else 16, 30, tzinfo=timezone.utc)
                        data = values()
                        data.update(id=f'seed-{i}', workspace_id=workspace, actor_id='a' if i % 2 else 'b',
                                    actor_name='New name' if i == 5 else 'Old name',
                                    created_at=timestamp, day=timestamp.astimezone(ledger.TAIPEI).date().isoformat(),
                                    provider='gpt' if i % 2 else 'claude', scope='project' if i % 2 else 'global',
                                    project_id='p1' if i % 2 else None, cost_micro_usd=None if i == 5 else 11)
                        db.add(ledger.AiUsageRow(**data))
                for i in (0, 1, 3, 4):
                    ledger.feedback(application.state.sessions, f'seed-{i}', 'a' if i % 2 else 'b',
                                    'up' if i == 0 else 'down', 'wrong' if i == 1 else None)
                results = []
                for filters in ({}, {'actor': 'a'}, {'provider': 'claude'}, {'provider': 'gpt'},
                                {'rating': 'up'}, {'rating': 'down'}, {'rating': 'none'},
                                {'scope': 'global'}, {'scope': 'project'},
                                {'actor': 'a', 'provider': 'gpt', 'rating': 'down', 'scope': 'project'},
                                {'from': '2026-10-30', 'to': '2026-10-30'},
                                {'from': '2026-10-31', 'to': '2026-10-31'}):
                    params = {'from': '2026-10-30', 'to': '2026-10-31', **filters}
                    response = connection.get('/api/ai/usage', params=params)
                    assert response.status_code == 200, response.text
                    results.append(response.json())
                assert results[0]['totals']['questions'] == 6
                assert results[0]['totals']['unpriced_calls'] == 1
                assert results[0]['reasons']['unspecified'] == 2
                assert results[0]['people'] == [dict(actor_id='a', name='New name'), dict(actor_id='b', name='Old name')]
                assert [r['questions'] for r in results[0]['by_day']] == [3, 3]
                assert connection.get('/api/ai/usage?from=2025-10-31&to=2026-10-31').status_code == 200
                assert connection.get('/api/ai/usage?from=2025-10-30&to=2026-10-31').status_code == 422
                outputs.append(results)
        finally:
            application.state.sessions.kw['bind'].dispose()
    for left, right in zip(*outputs):
        for key in left:
            assert left[key] == right[key], (key, left[key], right[key])
