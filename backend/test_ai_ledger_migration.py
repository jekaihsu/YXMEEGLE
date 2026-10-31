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
        'cost_micro_usd', 'price_version', 'steps', 'tool_calls', 'latency_ms', 'first_token_ms', 'status', 'error_code', 'scope', 'project_id'}
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


def test_feedback_additive_migration(tmp_path):
    from .ai.ledger import AiFeedbackRow
    engine = create_engine('sqlite:///' + str(tmp_path / 'feedback.db'))
    AiUsageRow.__table__.create(engine)
    with engine.begin() as db:
        db.exec_driver_sql('CREATE TABLE sentinel (value TEXT)')
        db.exec_driver_sql("INSERT INTO sentinel VALUES ('preserve')")
    migrate(engine)
    migrate(engine)
    inspector = inspect(engine)
    assert inspector.get_pk_constraint('ai_feedback')['constrained_columns'] == ['usage_id', 'actor_id']
    assert {c['name'] for c in inspector.get_columns('ai_feedback')} == {
        'usage_id', 'actor_id', 'rating', 'reason', 'created_at', 'updated_at'}
    with engine.connect() as db:
        assert db.exec_driver_sql('SELECT value FROM sentinel').scalar() == 'preserve'
    engine.dispose()


def test_scope_migration_preserves_old_rows_and_is_noop_on_repeat(tmp_path):
    from sqlalchemy import event
    from datetime import datetime, timezone
    engine = create_engine('sqlite:///' + str(tmp_path / 'scope.db'))
    with engine.begin() as db:
        AiUsageRow.__table__.create(db)
        db.exec_driver_sql('ALTER TABLE ai_usage DROP COLUMN scope')
        db.exec_driver_sql('ALTER TABLE ai_usage DROP COLUMN project_id')
        db.exec_driver_sql("INSERT INTO ai_usage (id, created_at, day, workspace_id, actor_id, actor_name, conversation_id, provider, model, effort, input_tokens, cache_read_tokens, cache_write_tokens, output_tokens, cost_micro_usd, price_version, steps, tool_calls, latency_ms, status) VALUES ('old', ?, '2026-10-31', 'w', 'actor', 'Name', 'c', 'claude', 'model', 'medium', 10, 0, 0, 5, 1, 'v1', 1, 0, 20, 'ok')", (datetime.now(timezone.utc).isoformat(),))
    migrate(engine)
    with engine.connect() as db:
        assert db.exec_driver_sql('SELECT id, scope, project_id, input_tokens, output_tokens, actor_name FROM ai_usage').all() == [('old', 'global', None, 10, 5, 'Name')]
    statements = []
    event.listen(engine, 'before_cursor_execute', lambda conn, cursor, statement, *args: statements.append(statement))
    migrate(engine)
    assert not any(s.startswith(('ALTER', 'CREATE', 'UPDATE')) for s in statements)
    engine.dispose()


def test_scope_migration_postgres_ddl():
    from sqlalchemy.dialects import postgresql
    from scripts.migrate_ai_usage import scope_column_ddl
    dialect = postgresql.dialect()
    assert scope_column_ddl('scope', dialect) == "ALTER TABLE ai_usage ADD COLUMN scope VARCHAR(16) DEFAULT 'global' NOT NULL"
    assert scope_column_ddl('project_id', dialect) == 'ALTER TABLE ai_usage ADD COLUMN project_id VARCHAR(200)'


def test_app_startup_adds_missing_columns_to_an_existing_usage_table(tmp_path):
    """Staging failed with 'column ai_usage.scope does not exist' because create_all never alters an existing table."""
    from datetime import datetime, timezone
    from .app import create_app
    db = tmp_path / 'legacy.db'
    engine = create_engine('sqlite:///' + str(db))
    with engine.begin() as connection:
        AiUsageRow.__table__.create(connection)
        connection.exec_driver_sql('ALTER TABLE ai_usage DROP COLUMN scope')
        connection.exec_driver_sql('ALTER TABLE ai_usage DROP COLUMN project_id')
        connection.exec_driver_sql("INSERT INTO ai_usage (id, created_at, day, workspace_id, actor_id, actor_name, conversation_id, provider, model, effort, input_tokens, cache_read_tokens, cache_write_tokens, output_tokens, price_version, steps, tool_calls, latency_ms, status) VALUES ('old', ?, '2026-10-30', 'w', 'a', 'Name', 'c', 'claude', 'm', 'medium', 1, 0, 0, 1, 'v', 1, 0, 1, 'ok')", (datetime(2026, 10, 30, tzinfo=timezone.utc).isoformat(),))
    engine.dispose()
    app = create_app(dict(APP_ENV='development', DEMO_MODE='true', DATABASE_URL='sqlite:///' + str(db), SESSION_SECRET='x' * 40,
                          UPLOAD_DIR=str(tmp_path / 'uploads')))
    columns = {c['name'] for c in inspect(app.state.sessions.kw['bind']).get_columns('ai_usage')}
    assert {'scope', 'project_id'} <= columns
    with app.state.sessions() as session:
        assert session.execute(AiUsageRow.__table__.select()).first().scope == 'global'
