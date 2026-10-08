"""VCC-97 P2-1: index tables are created by create_all and by the idempotent migration."""
from sqlalchemy import create_engine, inspect
from backend.models import Base
from scripts.migrate_index_tables import TABLES, migrate

EXPECTED={'ix_project_index_visibility_due':['workspace_id','case_visibility','due_date','project_id'],
          'ix_project_index_pm_status':['workspace_id','pm_id','status'],
          'ix_project_index_status_due':['workspace_id','status','due_date','project_id'],
          'ix_project_index_code':['workspace_id','code'],
          'ix_task_index_assignee_status_due':['workspace_id','assignee_id','status','due_date'],
          'ix_task_index_status_due':['workspace_id','status','due_date'],
          'ix_task_index_project':['workspace_id','project_id']}


def indexes(engine):
    found={}
    for table in TABLES: found.update({i['name']:i['column_names'] for i in inspect(engine).get_indexes(table.name)})
    return found


def test_create_all_builds_tables_and_indexes(tmp_path):
    engine=create_engine('sqlite:///'+str(tmp_path/'new.db')); Base.metadata.create_all(engine)
    assert {'project_index','task_index','workspace_counters'}<=set(inspect(engine).get_table_names())
    assert EXPECTED.items()<=indexes(engine).items()
    engine.dispose()


def test_migration_upgrades_old_database_idempotently(tmp_path):
    engine=create_engine('sqlite:///'+str(tmp_path/'old.db')); Base.metadata.create_all(engine)
    with engine.begin() as db:
        for table in TABLES: table.drop(db)
        db.exec_driver_sql("INSERT INTO workspaces VALUES ('w',1,'{}')")
    migrate(engine); migrate(engine)
    assert EXPECTED.items()<=indexes(engine).items()
    with engine.begin() as db:
        for name in EXPECTED: db.exec_driver_sql(f'DROP INDEX {name}')
    migrate(engine)
    assert EXPECTED.items()<=indexes(engine).items()
    with engine.connect() as db: assert db.exec_driver_sql('SELECT id FROM workspaces').all()==[('w',)]
    engine.dispose()


def test_scripts_run_directly_and_honour_help(tmp_path):
    import subprocess, sys
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    for name in ('migrate_index_tables','backfill_index'):
        done=subprocess.run([sys.executable,str(root/'scripts'/f'{name}.py'),'--help'],cwd=tmp_path,capture_output=True,text=True)
        assert done.returncode==0 and 'usage' in done.stdout


def test_shell_facts_column_migration_requires_backfill(tmp_path):
    from sqlalchemy import select
    from backend import index_reads
    from backend.models import BusinessRow, ProjectIndex, WorkspaceRow
    from backend.test_index_backfill import seeded
    from scripts.backfill_index import backfill

    engine, sessions, _ = seeded(tmp_path, 2)
    backfill(engine)
    with engine.begin() as db:
        db.exec_driver_sql('ALTER TABLE project_index DROP COLUMN shell_facts')
    migrate(engine); migrate(engine)
    assert 'shell_facts' in {c['name'] for c in inspect(engine).get_columns('project_index')}
    with sessions() as db:
        db.info['index_tables'] = True
        assert db.scalars(select(ProjectIndex.shell_facts)).all() == [None, None]
        assert not index_reads.ready(db, BusinessRow, db.get(WorkspaceRow, 'w'))
    backfill(engine)
    with sessions() as db:
        db.info['index_tables'] = True
        facts = db.scalars(select(ProjectIndex.shell_facts)).all()
        assert len(facts) == 2 and all(f['v'] == 1 and 'contract_amount' in f for f in facts)
        assert index_reads.ready(db, BusinessRow, db.get(WorkspaceRow, 'w'))
    engine.dispose()
