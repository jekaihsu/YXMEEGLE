"""Add the measured scoped-read index to existing tables, without data migration.

Postgres builds concurrently on an AUTOCOMMIT connection. This permits normal
reads/writes during the build, but startup waits for completion. SQLite has no
concurrent index DDL: its one-time build takes a write lock. Both have a bounded
lock wait (2 seconds); the existing startup initializer retries operational errors.

A failed concurrent build can leave an INVALID index. We deliberately fail startup
rather than silently accept it or drop an index another process may be building.
After checking that no builder is active, an operator can run outside a transaction:
DROP INDEX CONCURRENTLY IF EXISTS ix_business_records_scope_parent_order;
then restart to retry. No canonical rows or workspace revisions are touched.
"""
from sqlalchemy import inspect

INDEX_NAME = 'ix_business_records_scope_parent_order'
INDEX_COLUMNS = ('workspace_id', 'kind', 'parent_id', 'ordinal')
SQLITE_CREATE = (
    'CREATE INDEX IF NOT EXISTS ' + INDEX_NAME +
    ' ON business_records(workspace_id, kind, parent_id, ordinal)'
)
POSTGRES_CREATE = SQLITE_CREATE.replace('CREATE INDEX ', 'CREATE INDEX CONCURRENTLY ', 1)


def _verify(connection):
    indexes = inspect(connection).get_indexes('business_records')
    index = next((index for index in indexes if index['name'] == INDEX_NAME), None)
    if (index is None or tuple(index['column_names']) != INDEX_COLUMNS or index['unique']
            or any(str(key).endswith('_where') for key in index.get('dialect_options', {}))):
        raise RuntimeError(f'{INDEX_NAME}: unexpected index definition; inspect before retrying')
    if connection.dialect.name == 'postgresql':
        valid = connection.exec_driver_sql(
            'SELECT i.indisvalid AND i.indisready FROM pg_index i '
            'WHERE i.indexrelid = to_regclass(%s)', (INDEX_NAME,)
        ).scalar()
        if valid is not True:
            raise RuntimeError(f'{INDEX_NAME}: invalid or unfinished concurrent index; see read_index_migration.py')


def ensure_read_indexes(engine):
    """Idempotent for populated SQLite/Postgres databases; requires schema DDL rights."""
    dialect = engine.dialect.name
    if dialect not in ('sqlite', 'postgresql'):
        raise ValueError(f'unsupported read-index migration dialect: {dialect}')
    if dialect == 'postgresql':
        # engine.begin()/Session would make CREATE INDEX CONCURRENTLY illegal.
        with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as connection:
            try:
                connection.exec_driver_sql("SET lock_timeout = '2s'")
                connection.exec_driver_sql(POSTGRES_CREATE)
                _verify(connection)
            finally:
                connection.exec_driver_sql('RESET lock_timeout')
    else:
        with engine.begin() as connection:
            timeout = connection.exec_driver_sql('PRAGMA busy_timeout').scalar()
            try:
                connection.exec_driver_sql('PRAGMA busy_timeout = 2000')
                connection.exec_driver_sql(SQLITE_CREATE)
                _verify(connection)
            finally:
                connection.exec_driver_sql(f'PRAGMA busy_timeout = {int(timeout)}')
