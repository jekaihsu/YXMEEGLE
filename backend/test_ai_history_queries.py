"""Populated history reads use bounded SQL and never need a provider."""
from datetime import datetime, timedelta, timezone
import json
from time import perf_counter

import pytest
from sqlalchemy import create_engine, delete, event
from sqlalchemy.orm import sessionmaker

from .ai import ledger


@pytest.fixture
def history_db(tmp_path, monkeypatch):
    engine = create_engine(f'sqlite:///{tmp_path}/history.db')
    ledger.ensure_schema(engine)
    sessions = sessionmaker(bind=engine)
    # Any accidental provider request in a history read must fail, even with keys configured.
    import httpx
    def forbidden(*args, **kwargs):
        pytest.fail('history attempted an HTTP/provider request')
    monkeypatch.setattr(httpx.Client, 'send', forbidden)
    monkeypatch.setattr(httpx.AsyncClient, 'send', forbidden)
    yield sessions
    engine.dispose()


def seed_turn(sessions, ident, conversation, *, stamp=None, workspace='w', actor='a',
              scope='global', project=None, question=None, exchange_workspace=None, exchange_actor=None):
    stamp = stamp or datetime.now(timezone.utc)
    with sessions.begin() as db:
        db.add(ledger.AiUsageRow(id=ident, created_at=stamp, day=stamp.date().isoformat(),
            workspace_id=workspace, actor_id=actor, actor_name='Fixture', conversation_id=conversation,
            provider='claude', scope=scope, project_id=project, model='fixture', effort='medium',
            input_tokens=1, cache_read_tokens=0, cache_write_tokens=0, output_tokens=1,
            price_version='fixture', steps=1, tool_calls=0, latency_ms=1, status='ok'))
        db.add(ledger.AiExchangeRow(usage_id=ident, created_at=stamp,
            workspace_id=exchange_workspace or workspace, actor_id=exchange_actor or actor,
            question=question or f'  Title {conversation}\n question  ', answer='answer' * 1000, tool_names='[]'))


def read(sessions, *, scope='global', project=None, limit=30, before=None, enabled=True):
    return ledger.conversations(sessions, 'w', 'a', scope, project, limit, before,
                                content_enabled=enabled, retention_days=90)


def capture(sessions, **kwargs):
    statements = []
    def record(conn, cursor, statement, *args):
        statements.append(statement)
    engine = sessions.kw['bind']
    event.listen(engine, 'before_cursor_execute', record)
    try:
        started = perf_counter()
        result = read(sessions, **kwargs)
        elapsed = (perf_counter() - started) * 1000
    finally:
        event.remove(engine, 'before_cursor_execute', record)
    return result, statements, elapsed


def test_thirty_conversations_bounded_sql_and_payload(history_db):
    stamp = datetime.now(timezone.utc) - timedelta(hours=1)
    for i in range(30):
        for turn in range(2):
            seed_turn(history_db, f'{i:03}-{turn}', f'c{i:03}', stamp=stamp + timedelta(seconds=turn))
    result, statements, elapsed = capture(history_db)
    assert len(result['items']) == 30
    assert all(item['turns'] == 2 and item['title'] == f"Title {item['id']} question" for item in result['items'])
    assert result['next_cursor'] is None
    assert len(statements) <= 3, f'{len(statements)} SQL statements for 30 conversations'
    assert not any('answer' in sql.lower() for sql in statements)
    payload = len(json.dumps(result, ensure_ascii=False).encode())
    print(json.dumps(dict(conversations=30, turns=60, ledger_sql=len(statements),
                         payload_bytes=payload, elapsed_ms=round(elapsed, 3))))


def test_scope_applies_to_titles_counts_and_order(history_db):
    stamp = datetime.now(timezone.utc) - timedelta(hours=1)
    seed_turn(history_db, 'global', 'shared', stamp=stamp, question='Global title')
    for ident, options in [
        ('other-actor', dict(actor='other')),
        ('other-workspace', dict(workspace='other')),
        ('project-p1', dict(scope='project', project='p1')),
        ('project-p2', dict(scope='project', project='p2')),
        ('wrong-exchange-actor', dict(exchange_actor='other')),
        ('wrong-exchange-workspace', dict(exchange_workspace='other')),
    ]:
        seed_turn(history_db, ident, 'shared', stamp=stamp - timedelta(minutes=1), question=ident, **options)
    page = read(history_db)
    assert [(i['title'], i['turns'], i['project_id']) for i in page['items']] == [('Global title', 1, None)]
    for project in ('p1', 'p2'):
        page = read(history_db, scope='project', project=project)
        assert [(i['title'], i['turns'], i['project_id']) for i in page['items']] == [(f'project-{project}', 1, project)]


def test_page_ties_and_one_hundred_item_bound(history_db):
    stamp = datetime.now(timezone.utc) - timedelta(hours=1)
    for i in range(105):
        # Insert same-time turns backwards to exercise the usage-id title tie break.
        for suffix in ('z', 'a'):
            seed_turn(history_db, f'{i:03}-{suffix}', f'c{i:03}', stamp=stamp, question=f'{suffix} title')
    first, statements, _ = capture(history_db, limit=100)
    assert len(first['items']) == 100 and first['next_cursor']
    assert len(statements) <= 3
    second = read(history_db, limit=100, before=first['next_cursor'])
    items = first['items'] + second['items']
    assert [i['id'] for i in items] == [f'c{i:03}' for i in reversed(range(105))]
    assert all(i['title'] == 'a title' and i['turns'] == 2 for i in items)
    assert second['next_cursor'] is None


def test_retained_first_title_after_deletion_and_expiry(history_db):
    stamp = datetime.now(timezone.utc)
    seed_turn(history_db, 'expired', 'c', stamp=stamp - timedelta(days=91), question='Expired secret')
    seed_turn(history_db, 'deleted', 'c', stamp=stamp - timedelta(hours=2), question='Deleted secret')
    seed_turn(history_db, 'retained', 'c', stamp=stamp - timedelta(hours=1), question='  Retained\n first ')
    seed_turn(history_db, 'expired-only', 'expired-only', stamp=stamp - timedelta(days=91))
    with history_db.begin() as db:
        db.execute(delete(ledger.AiExchangeRow).where(ledger.AiExchangeRow.usage_id == 'deleted'))
    result = read(history_db)
    assert [(i['id'], i['title'], i['turns']) for i in result['items']] == [('c', 'Retained first', 1)]
    generation = ledger.conversation_generation(history_db, 'w', 'a', 'c')
    ledger.delete_conversation(history_db, 'w', 'a', 'c')
    assert read(history_db)['items'] == []
    with history_db() as db:
        assert db.get(ledger.AiConversationGeneration, ('w', 'a', 'c')).generation == generation + 1
        assert db.get(ledger.AiUsageRow, 'retained') is not None


def test_no_content_executes_no_sql(history_db):
    seed_turn(history_db, 'stored', 'c')
    result, statements, _ = capture(history_db, enabled=False)
    assert result == dict(history_available=False, items=[], next_cursor=None)
    assert statements == []
