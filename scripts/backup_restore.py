"""Portable application backup, excluding expiring login sessions.

Pause writes before taking a backup. Restore only to an empty database and empty
upload directory. Never overwrite a running workspace. DATABASE_URL is read from
the environment and is never printed.
"""
import argparse
import hashlib
import json
import os
import secrets
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from datetime import datetime, timezone
from sqlalchemy import create_engine, MetaData, Table, Column, String, Integer, JSON, select, inspect
try:
    from .backup_publish import publish
except ImportError:
    from backup_publish import publish

META=MetaData()
TABLES=[
    Table('workspaces',META,Column('id',String(120),primary_key=True),Column('version',Integer,nullable=False),Column('data',JSON,nullable=False)),
    Table('receipts',META,Column('id',String(300),primary_key=True),Column('fingerprint',String(64)),Column('result',JSON)),
    Table('source_caches',META,Column('id',String(120),primary_key=True),Column('data',JSON)),
    Table('business_records',META,Column('workspace_id',String(120),primary_key=True),Column('kind',String(60),primary_key=True),Column('entity_id',String(160),primary_key=True),Column('parent_id',String(160),nullable=False,index=True),Column('ordinal',Integer,nullable=False),Column('data',JSON,nullable=False)),
    Table('company_people',META,Column('organization_id',String(120),primary_key=True),Column('person_id',String(120),primary_key=True),Column('data',JSON,nullable=False)),
    Table('action_audit',META,Column('id',String(64),primary_key=True),Column('workspace_id',String(120),nullable=False,index=True),Column('actor_id',String(120),nullable=False),Column('action',String(120),nullable=False),Column('created_at',String(64),nullable=False,index=True),Column('data',JSON,nullable=False)),
]

def engine_for(url):
    if url.startswith('postgres://'):url='postgresql+psycopg://'+url[len('postgres://'):]
    elif url.startswith('postgresql://'):url='postgresql+psycopg://'+url[len('postgresql://'):]
    return create_engine(url,pool_pre_ping=True)

def backup(engine,uploads,target):
    target=Path(target).resolve();uploads=Path(uploads).resolve()
    if target.is_relative_to(uploads):raise ValueError('Backup must be outside uploads')
    if target.exists():raise ValueError('Backup file already exists')
    with engine.connect() as connection:
        if engine.dialect.name=='postgresql':connection=connection.execution_options(isolation_level='REPEATABLE READ')
        with connection.begin():
            if engine.dialect.name=='postgresql': connection.exec_driver_sql('SET TRANSACTION READ ONLY')
            available=set(inspect(connection).get_table_names())
            rows={table.name:[dict(row) for row in connection.execute(select(table)).mappings()] if table.name in available else [] for table in TABLES}
    payload=json.dumps(rows,ensure_ascii=False,separators=(',',':')).encode()
    # Only committed immutable files referenced by this DB snapshot belong in
    # the backup. In-flight uploads and orphan temporary files are excluded.
    try:
        from scripts.backup_live_legacy import referenced_files, read_attachment
    except ImportError:
        from backup_live_legacy import referenced_files, read_attachment
    refs=referenced_files(rows)
    for item in rows['business_records']:
        f=item['data']
        if item['kind']=='project_files' and f.get('storage')=='local':
            one={'workspaces':[{'id':item['workspace_id'],'data':{'projects':[{'files':[f]}]}}]}
            for path,size in referenced_files(one).items():
                if path in refs and refs[path]!=size: raise ValueError('Conflicting attachment references')
                refs[path]=size
    manifest={'schema':'yx-workspace-backup/3','created_at':datetime.now(timezone.utc).isoformat(),
              'tables':{k:len(v) for k,v in rows.items()},'sha256':{'database.json':hashlib.sha256(payload).hexdigest()}}
    target.parent.mkdir(parents=True,exist_ok=True)
    temporary=target.with_name(target.name+'.partial-'+secrets.token_hex(8))
    try:
        with temporary.open('xb') as handle:
            with ZipFile(handle,'w',ZIP_DEFLATED) as archive:
                archive.writestr('database.json',payload)
                for relative,size in sorted(refs.items()):
                    data=read_attachment(uploads,relative,size); name='uploads/'+relative
                    archive.writestr(name,data);manifest['sha256'][name]=hashlib.sha256(data).hexdigest()
                archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False))
            handle.flush(); os.fsync(handle.fileno())
        validate_archive(temporary)
        publish(temporary,target)  # atomic, exclusive publication; never overwrite
    finally:
        temporary.unlink(missing_ok=True)
    return {'tables':manifest['tables'],'files':len(refs),'sessions_restored':False}


def validate_archive(source):
    with ZipFile(source) as archive:
        names=archive.namelist(); manifest=json.loads(archive.read('manifest.json'))
        if len(names)!=len(set(names)) or set(names)!=(set(manifest['sha256'])|{'manifest.json'}):
            raise ValueError('Backup entries mismatch')
        for name,digest in manifest['sha256'].items():
            if hashlib.sha256(archive.read(name)).hexdigest()!=digest: raise ValueError('Backup checksum mismatch')
    return manifest

def assert_empty_database(engine):
    """Read every existing table, including tables outside the backup schema."""
    with engine.connect() as connection:
        existing=MetaData()
        existing.reflect(bind=connection)
        if any(connection.execute(select(t).limit(1)).first() for t in existing.tables.values()):
            raise ValueError('Restore target database must be empty')


def restore(engine,uploads,source):
    uploads=Path(uploads).resolve()
    if uploads.exists() and any(uploads.iterdir()):raise ValueError('Restore upload directory must be empty')
    with ZipFile(source) as archive:
        names=archive.namelist()
        if len(names)!=len(set(names)):raise ValueError('Duplicate archive entries')
        manifest=json.loads(archive.read('manifest.json'))
        if manifest.get('schema') not in ('yx-workspace-backup/1','yx-workspace-backup/2','yx-workspace-backup/3'):raise ValueError('Unsupported backup format')
        if set(names)!=(set(manifest['sha256'])|{'manifest.json'}):raise ValueError('Unexpected archive files')
        validated={}
        for name,digest in manifest['sha256'].items():
            if name!='database.json':
                if not name.startswith('uploads/') or '\\' in name:raise ValueError('Invalid upload path')
                dest=(uploads/name[len('uploads/'):]).resolve()
                if not dest.is_relative_to(uploads) or dest==uploads:raise ValueError('Unsafe upload path')
            data=archive.read(name)
            if hashlib.sha256(data).hexdigest()!=digest:raise ValueError('Backup checksum mismatch')
            validated[name]=data
        rows=json.loads(validated.pop('database.json'))
        if manifest['schema']=='yx-workspace-backup/1':
            rows.setdefault('business_records',[]);rows.setdefault('company_people',[])
        if manifest['schema'] in ('yx-workspace-backup/1','yx-workspace-backup/2'): rows.setdefault('action_audit',[])
        if set(rows)!={t.name for t in TABLES}:raise ValueError('Unexpected database tables')
    # A live target can contain only login sessions after a partial reset. It
    # is still not an empty restore target; inspect every table, not just those
    # included in our portable backup. Run restore with the target app stopped.
    assert_empty_database(engine)
    META.create_all(engine)
    written=[]
    try:
        with engine.begin() as connection:
            if any(connection.execute(select(t).limit(1)).first() for t in TABLES):
                raise ValueError('Restore target database must be empty')
            for name,data in validated.items():
                dest=uploads/name[len('uploads/'):];dest.parent.mkdir(parents=True,exist_ok=True)
                with dest.open('xb') as handle:handle.write(data)
                written.append(dest)
            for table in TABLES:
                if rows[table.name]:connection.execute(table.insert(),rows[table.name])
    except Exception:
        for path in written:path.unlink(missing_ok=True)
        raise
    return {'tables':{k:len(v) for k,v in rows.items()},'files':len(written),'sessions_restored':False}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['backup','restore'])
    parser.add_argument('--file',required=True)
    parser.add_argument('--uploads',default=os.getenv('UPLOAD_DIR','./data/uploads'))
    args=parser.parse_args()
    url=os.getenv('DATABASE_URL')
    if not url:raise SystemExit('DATABASE_URL is required')
    engine=engine_for(url)
    try:
        fn=backup if args.action=='backup' else restore
        print(json.dumps({'ok':True,**fn(engine,args.uploads,args.file)}))
    finally:engine.dispose()

if __name__=='__main__':main()
