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
from sqlalchemy import create_engine, MetaData, select, inspect
try:
    from .backup_publish import publish
except ImportError:
    from backup_publish import publish

def _canonical_base():
    try:
        from backend.app import Base
    except ImportError:
        import sys
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
        from backend.app import Base
    return Base

# The application's SQLAlchemy models are the only schema definition. Login
# sessions are deliberately not portable and are recreated by the app on start.
META=_canonical_base().metadata
PORTABLE=('workspaces','receipts','source_caches','business_records','company_people','action_audit')
TABLES=[META.tables[name] for name in PORTABLE]

def assert_schema(engine):
    """create_all never alters existing tables, so verify the live schema."""
    with engine.connect() as connection:
        inspector=inspect(connection)
        actual_names=set(inspector.get_table_names())
        for table in TABLES:
            if table.name not in actual_names: raise ValueError(f'Restore schema mismatch: missing table {table.name}')
            want={'columns':{c.name:c.nullable for c in table.columns},
                  'pk':sorted(c.name for c in table.primary_key.columns),
                  'fks':sorted((tuple(f.parent.name for f in k.elements),k.referred_table.name,tuple(f.column.name for f in k.elements)) for k in table.foreign_key_constraints),
                  'indexes':sorted((tuple(c.name for c in i.columns),bool(i.unique)) for i in table.indexes)}
            have={'columns':{c['name']:c['nullable'] for c in inspector.get_columns(table.name)},
                  'pk':sorted(inspector.get_pk_constraint(table.name)['constrained_columns']),
                  'fks':sorted((tuple(f['constrained_columns']),f['referred_table'],tuple(f['referred_columns'])) for f in inspector.get_foreign_keys(table.name)),
                  'indexes':sorted((tuple(i['column_names']),bool(i['unique'])) for i in inspector.get_indexes(table.name))}
            for key in want:
                if want[key]!=have[key]: raise ValueError(f'Restore schema mismatch: {table.name} {key}')

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
    META.create_all(engine,tables=TABLES)
    assert_schema(engine)
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
