"""Issue #49: audit ordering index upgrades populated databases without data loss."""
import pytest
from sqlalchemy import create_engine, inspect
from backend.models import Base
from scripts.migrate_audit_index import INDEX, migrate


def test_new_database_has_audit_order_index(tmp_path):
    engine=create_engine('sqlite:///'+str(tmp_path/'new.db'))
    Base.metadata.create_all(engine)
    index=next(i for i in inspect(engine).get_indexes('action_audit') if i['name']==INDEX.name)
    assert index['column_names']==['workspace_id','created_at','id']
    engine.dispose()


def test_existing_populated_database_migrates_idempotently_and_uses_index(tmp_path):
    engine=create_engine('sqlite:///'+str(tmp_path/'existing.db'))
    Base.metadata.create_all(engine)
    INDEX.drop(engine)  # schema from before the paging index
    with engine.begin() as db:
        db.exec_driver_sql("INSERT INTO action_audit VALUES ('a','w','actor','update','2026-01-01','{}')")
        db.exec_driver_sql("INSERT INTO action_audit VALUES ('b','w','actor','update','2026-01-01','{}')")
        before=db.exec_driver_sql('SELECT * FROM action_audit ORDER BY id').all()
    Base.metadata.create_all(engine)
    assert INDEX.name not in {i['name'] for i in inspect(engine).get_indexes('action_audit')}
    migrate(engine)
    migrate(engine)
    with engine.connect() as db:
        assert db.exec_driver_sql('SELECT * FROM action_audit ORDER BY id').all()==before
        for cursor in ('', "AND (created_at < '2026-02-01' OR (created_at = '2026-02-01' AND id < 'z'))"):
            query=f"SELECT * FROM action_audit WHERE workspace_id='w' {cursor} ORDER BY created_at DESC, id DESC LIMIT 100"
            plan=' '.join(str(row) for row in db.exec_driver_sql('EXPLAIN QUERY PLAN '+query))
            assert INDEX.name in plan
            assert 'TEMP B-TREE' not in plan
            assert [row[0] for row in db.exec_driver_sql(query)]==['b','a']
    engine.dispose()


def test_conflicting_index_is_rejected_without_dropping_it(tmp_path):
    engine=create_engine('sqlite:///'+str(tmp_path/'conflict.db'))
    Base.metadata.create_all(engine)
    INDEX.drop(engine)
    with engine.begin() as db:
        db.exec_driver_sql(f'CREATE INDEX {INDEX.name} ON action_audit (actor_id)')
    with pytest.raises(ValueError,match='incompatible definition'):
        migrate(engine)
    assert next(i for i in inspect(engine).get_indexes('action_audit') if i['name']==INDEX.name)['column_names']==['actor_id']
    engine.dispose()
