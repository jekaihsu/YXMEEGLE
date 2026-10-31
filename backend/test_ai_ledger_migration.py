from sqlalchemy import create_engine, inspect
from .models import Base
from .ai.ledger import AiUsageRow
from scripts.migrate_ai_usage import migrate


def test_startup_creates_usage_table(tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'new.db'))
    Base.metadata.create_all(engine)
    assert 'ai_usage' in inspect(engine).get_table_names()
    indexes = {tuple(i['column_names']) for i in inspect(engine).get_indexes('ai_usage')}
    assert {('day',), ('actor_id',)} <= indexes
    assert {c['name'] for c in inspect(engine).get_columns('ai_usage')} == {
        'id', 'created_at', 'day', 'workspace_id', 'actor_id', 'actor_name', 'conversation_id', 'provider',
        'model', 'effort', 'input_tokens', 'cache_read_tokens', 'cache_write_tokens', 'output_tokens',
        'cost_micro_usd', 'price_version', 'steps', 'tool_calls', 'latency_ms', 'first_token_ms', 'status', 'error_code'}
    engine.dispose()


def test_additive_migration_preserves_existing_rows_and_repairs_indexes(tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'old.db'))
    Base.metadata.create_all(engine)
    with engine.begin() as db:
        AiUsageRow.__table__.drop(db)
        db.exec_driver_sql("INSERT INTO workspaces VALUES ('w',1,'{}')")
    migrate(engine)
    migrate(engine)
    with engine.begin() as db:
        db.exec_driver_sql('DROP INDEX ix_ai_usage_day')
    migrate(engine)
    assert 'ix_ai_usage_day' in {i['name'] for i in inspect(engine).get_indexes('ai_usage')}
    with engine.connect() as db:
        assert db.exec_driver_sql('SELECT id FROM workspaces').all() == [('w',)]
    engine.dispose()


def test_ledger_failure_never_raises_or_logs_values(caplog):
    from .ai.ledger import record
    class Broken:
        def begin(self):
            raise RuntimeError('private question must not be logged')
    record(Broken(), conversation_id='private question must not be logged')
    assert 'ai_usage_write_failed' in caplog.text
    assert 'private question' not in caplog.text
