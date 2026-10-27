"""Run in a maintenance window before using test cleanup on an existing DB.

DATABASE_URL=... python -m backend.sop_import.cleanup_migration
Only the audit-to-task FK is removed; audit data and indexes are preserved.
"""
import os

from sqlalchemy import MetaData, create_engine, inspect
from sqlalchemy.schema import CreateTable

from .models import TaskEvent


def migrate(engine):
    with engine.connect() as connection:
        if engine.dialect.name == 'sqlite':
            connection.exec_driver_sql('BEGIN IMMEDIATE')
        else:
            connection.begin()
        try:
            foreign_keys = inspect(connection).get_foreign_keys(TaskEvent.__tablename__)
            if not foreign_keys:
                connection.commit()
                return
            if (len(foreign_keys) != 1 or foreign_keys[0]['referred_table'] != 'sop_local_tasks'
                    or foreign_keys[0]['constrained_columns'] != ['workspace_id', 'project_id', 'task_id']):
                raise ValueError('Unexpected audit foreign keys; manual review required')
            if engine.dialect.name == 'postgresql':
                quote = engine.dialect.identifier_preparer.quote
                connection.exec_driver_sql('ALTER TABLE sop_task_events DROP CONSTRAINT '
                                           + quote(foreign_keys[0]['name']))
            elif engine.dialect.name == 'sqlite':
                # Refuse custom schema rather than silently lose columns or indexes.
                table = TaskEvent.__table__
                actual = inspect(connection)
                if {c['name'] for c in actual.get_columns(table.name)} != set(table.columns.keys()):
                    raise ValueError('Unexpected audit columns; manual review required')
                if {i['name'] for i in actual.get_indexes(table.name)} != {i.name for i in table.indexes}:
                    raise ValueError('Unexpected audit indexes; manual review required')
                if connection.exec_driver_sql("SELECT 1 FROM sqlite_master WHERE type='trigger' AND tbl_name='sop_task_events'").first():
                    raise ValueError('Unexpected audit triggers; manual review required')
                replacement = table.to_metadata(MetaData(), name='sop_task_events_cleanup_migration')
                connection.execute(CreateTable(replacement))
                columns = ', '.join(engine.dialect.identifier_preparer.quote(c.name) for c in table.columns)
                connection.exec_driver_sql(f'INSERT INTO {replacement.name} ({columns}) SELECT {columns} FROM {table.name}')
                connection.exec_driver_sql('DROP TABLE sop_task_events')
                connection.exec_driver_sql(f'ALTER TABLE {replacement.name} RENAME TO sop_task_events')
                for index in table.indexes:
                    index.create(connection)
                if connection.exec_driver_sql('PRAGMA foreign_key_check(sop_task_events)').first():
                    raise ValueError('Audit foreign key check failed')
            else:
                raise ValueError('Unsupported database dialect')
            connection.commit()
        except Exception:
            connection.rollback()
            raise


if __name__ == '__main__':
    engine = create_engine(os.environ['DATABASE_URL'])
    try:
        migrate(engine)
        print('Audit history foreign key migration complete')
    finally:
        engine.dispose()
