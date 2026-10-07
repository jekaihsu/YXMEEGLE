"""Create the Phase 2 index tables and their indexes on an existing database.

Run: DATABASE_URL=... .venv/bin/python -m scripts.migrate_index_tables
Tables are created IF NOT EXISTS (new, empty, so no table rewrite). Each index is
then built with CREATE INDEX IF NOT EXISTS; PostgreSQL uses CONCURRENTLY outside a
transaction, allowing writes. SQLite: pause application writes. Safe to repeat; a
conflicting or invalid index fails verification. If a PostgreSQL build is
interrupted, drop its invalid index before retrying. Nothing reads these tables
unless INDEX_TABLES_ENABLED is on; populate them with scripts.backfill_index.
"""
import os

from sqlalchemy import create_engine, inspect, text

from backend.models import Base, ProjectIndex, TaskIndex, WorkspaceCounter

TABLES=(ProjectIndex.__table__,TaskIndex.__table__,WorkspaceCounter.__table__)


def migrate(engine):
    dialect=engine.dialect.name
    if dialect not in ('sqlite','postgresql'):
        raise ValueError('Index table migration supports SQLite and PostgreSQL')
    concurrent='CONCURRENTLY ' if dialect=='postgresql' else ''
    Base.metadata.create_all(engine,tables=list(TABLES),checkfirst=True)
    with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as connection:
        for table in TABLES:
            for index in sorted(table.indexes,key=lambda i:i.name):
                columns=', '.join(c.name for c in index.columns)
                connection.exec_driver_sql(f'CREATE INDEX {concurrent}IF NOT EXISTS {index.name} ON {table.name} ({columns})')
                actual=next((i for i in inspect(connection).get_indexes(table.name) if i['name']==index.name),None)
                if not actual or actual['column_names']!=[c.name for c in index.columns] or actual['unique']:
                    raise ValueError(f'Index {index.name} has an incompatible definition')
                if dialect=='postgresql':
                    valid=connection.execute(text('SELECT indisvalid FROM pg_index WHERE indexrelid=to_regclass(:name)'),{'name':index.name}).scalar_one()
                    if not valid:
                        raise ValueError(f'Index {index.name} is invalid; drop the invalid index and retry')


def main():
    url=os.getenv('DATABASE_URL')
    if not url:
        raise SystemExit('DATABASE_URL is required')
    engine=create_engine(url)
    try:
        migrate(engine)
        print('Index tables verified')
    finally:
        engine.dispose()


if __name__=='__main__':
    main()
