"""Add the audit paging index to an existing database without rebuilding tables.

Run: DATABASE_URL=... .venv/bin/python -m scripts.migrate_audit_index
SQLite: pause application writes while this runs. PostgreSQL: builds concurrently
outside a transaction, allowing writes. Safe to repeat; a conflicting or invalid
index fails verification rather than being silently accepted. If a PostgreSQL
build is interrupted, drop its invalid index before retrying. New databases get
this index from the canonical models; create_all does not upgrade existing ones.
"""
import os

from sqlalchemy import create_engine, inspect, text

from backend.models import AuditRow

INDEX=next(i for i in AuditRow.__table__.indexes if i.name=='ix_action_audit_workspace_created_id')


def migrate(engine):
    dialect=engine.dialect.name
    if dialect not in ('sqlite','postgresql'):
        raise ValueError('Audit index migration supports SQLite and PostgreSQL')
    concurrent='CONCURRENTLY ' if dialect=='postgresql' else ''
    with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as connection:
        connection.exec_driver_sql(
            f'CREATE INDEX {concurrent}IF NOT EXISTS {INDEX.name} '
            'ON action_audit (workspace_id, created_at, id)')
        actual=next((i for i in inspect(connection).get_indexes('action_audit') if i['name']==INDEX.name),None)
        if not actual or actual['column_names']!=[c.name for c in INDEX.columns] or actual['unique']:
            raise ValueError('Audit paging index has an incompatible definition')
        if dialect=='postgresql':
            valid=connection.execute(text('SELECT indisvalid FROM pg_index WHERE indexrelid=to_regclass(:name)'),{'name':INDEX.name}).scalar_one()
            if not valid:
                raise ValueError('Audit paging index is invalid; drop the invalid index and retry')


def main():
    url=os.getenv('DATABASE_URL')
    if not url:
        raise SystemExit('DATABASE_URL is required')
    engine=create_engine(url)
    try:
        migrate(engine)
        print('Audit paging index verified')
    finally:
        engine.dispose()


if __name__=='__main__':
    main()
