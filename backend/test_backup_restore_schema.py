import hashlib
from zipfile import ZipFile

import pytest
from sqlalchemy import Column, Integer, JSON, MetaData, String, Table, create_engine, inspect, select

from backend.app import Base, BusinessRow
from scripts import backup_restore as br

PORTABLE={'workspaces','receipts','source_caches','business_records','company_people','action_audit'}


def app_source(tmp_path):
    """A database built by the application's own schema, not by backup_restore."""
    engine=create_engine('sqlite:///'+str(tmp_path/'source.db'))
    Base.metadata.create_all(engine)
    uploads=tmp_path/'uploads'
    folder=uploads/hashlib.sha256(b'company').hexdigest(); folder.mkdir(parents=True)
    (folder/'file_one').write_bytes(b'company evidence')
    file={'id':'file_one','storage':'local','size':16}
    with engine.begin() as db:
        db.execute(Base.metadata.tables['workspaces'].insert(),{'id':'company','version':2,'data':{'storage_schema':2}})
        db.execute(BusinessRow.__table__.insert(),[
            {'workspace_id':'company','kind':'projects','entity_id':'p1','parent_id':'','ordinal':0,'data':{'id':'p1'}},
            {'workspace_id':'company','kind':'project_files','entity_id':'file_one','parent_id':'p1','ordinal':0,'data':file}])
        db.execute(Base.metadata.tables['auth_sessions'].insert(),{'id':'live','data':{}})
    return engine,uploads


def shape(engine,name):
    inspector=inspect(engine)
    return ([(tuple(f['constrained_columns']),f['referred_table'],tuple(f['referred_columns'])) for f in inspector.get_foreign_keys(name)],
            sorted((i['name'],tuple(i['column_names'])) for i in inspector.get_indexes(name)))


def test_portable_tables_are_the_canonical_app_tables():
    assert {t.name for t in br.TABLES}==PORTABLE
    assert all(t is Base.metadata.tables[t.name] for t in br.TABLES)


def test_backup_restore_keeps_rows_attachments_foreign_key_and_indexes(tmp_path):
    source,uploads=app_source(tmp_path)
    archive=tmp_path/'backup.zip'
    assert br.backup(source,uploads,archive)['files']==1
    with ZipFile(archive) as z: assert not any('auth_sessions' in n for n in z.namelist())
    target=create_engine('sqlite:///'+str(tmp_path/'restored.db'))
    out=tmp_path/'restored-uploads'
    result=br.restore(target,out,archive)
    assert result['tables']['business_records']==2 and result['files']==1
    assert next(out.rglob('file_one')).read_bytes()==b'company evidence'
    with target.connect() as db:
        assert db.execute(select(BusinessRow.__table__.c.data).where(BusinessRow.__table__.c.kind=='projects')).scalar_one()=={'id':'p1'}
    assert 'auth_sessions' not in inspect(target).get_table_names()
    for name in PORTABLE: assert shape(target,name)==shape(source,name)
    fks,indexes=shape(target,'business_records')
    assert fks==[(('workspace_id',),'workspaces',('id',))]
    assert [c for _,c in indexes]==[('parent_id',)]
    # The restored FK is enforced, not merely declared.
    with target.connect() as db:
        db.exec_driver_sql('PRAGMA foreign_keys=ON')
        with pytest.raises(Exception,match='FOREIGN KEY'):
            db.execute(BusinessRow.__table__.insert(),{'workspace_id':'ghost','kind':'x','entity_id':'x','parent_id':'','ordinal':0,'data':{}})


def test_repeated_restore_and_create_all_do_not_mask_missing_schema(tmp_path):
    source,uploads=app_source(tmp_path)
    archive=tmp_path/'backup.zip'; br.backup(source,uploads,archive)
    # Stale empty target: tables exist from older hand-written DDL without FK/index.
    stale=create_engine('sqlite:///'+str(tmp_path/'stale.db'))
    old=MetaData()
    Table('workspaces',old,Column('id',String(120),primary_key=True),Column('version',Integer,nullable=False),Column('data',JSON,nullable=False))
    Table('business_records',old,Column('workspace_id',String(120),primary_key=True),Column('kind',String(60),primary_key=True),Column('entity_id',String(160),primary_key=True),Column('parent_id',String(160),nullable=False),Column('ordinal',Integer,nullable=False),Column('data',JSON,nullable=False))
    old.create_all(stale)
    Base.metadata.create_all(stale)  # checkfirst: silently leaves the stale tables alone
    assert shape(stale,'business_records')[0]==[]
    with pytest.raises(ValueError,match='schema mismatch: business_records fks'):
        br.restore(stale,tmp_path/'stale-uploads',archive)
    with stale.connect() as db: assert db.execute(select(BusinessRow.__table__)).first() is None
    assert not (tmp_path/'stale-uploads').exists() or not any((tmp_path/'stale-uploads').iterdir())
    # A second restore into the same, now populated, target is refused.
    good=create_engine('sqlite:///'+str(tmp_path/'good.db'))
    br.restore(good,tmp_path/'good-uploads',archive)
    Base.metadata.create_all(good)
    with pytest.raises(ValueError,match='must be empty'):
        br.restore(good,tmp_path/'again-uploads',archive)
    assert shape(good,'business_records')==shape(source,'business_records')
