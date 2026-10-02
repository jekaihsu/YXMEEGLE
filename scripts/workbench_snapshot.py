"""Fixed formal-service snapshot; private transport, durable at-most-once creation."""
import argparse
import base64
from datetime import datetime,timezone
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import zlib
from zipfile import ZipFile,ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]
ZEABUR=(str(Path(os.environ['APPDATA'])/'npm/node_modules/zeabur/zeabur_windows_amd64_v1/zeabur.exe')
        if os.name=='nt' else 'zeabur')
sys.path.insert(0,str(ROOT))
from scripts.backup_restore import validate_archive
from scripts.backup_publish import publish

SERVICE='6ab61834a4c05a5bcb57ad69'
ENVIRONMENT='6ab6168036d2a6cac409f0c6'
DIRECTORY=ROOT/'.runtime/workbench-snapshot'
MAX_BYTES=128*1024*1024
MARKER='YX_WORKBENCH_SNAPSHOT='
MODULES=('scripts/backup_restore.py','scripts/backup_live_legacy.py','scripts/backup_publish.py')


class SnapshotError(Exception):pass


def check(ok,code):
    if not ok:raise SnapshotError(code)


def stamp():return datetime.now(timezone.utc).isoformat()


def exclusive_json(path,value):
    with path.open('x',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2);stream.flush();os.fsync(stream.fileno())


def remote_source(operation,attempt):
    check(operation in ('create','fetch','diagnose','repair-reviewed-helper'),'invalid_operation')
    code=r'''
import base64,hashlib,io,json,os,re,sys
from pathlib import Path
from zipfile import ZipFile
from datetime import datetime,timezone
sys.path.insert(0,'/app')
def ensure(value):
    if not value:raise ValueError('snapshot_validation_failed')
def execute():
    operation=OPERATION
    attempt=ATTEMPT
    folder=Path('/tmp')/('yx-workbench-snapshot-'+attempt['id'])
    archive=folder/'snapshot.zip'
    metadata=folder/'snapshot.json'
    if operation=='diagnose':
        # Read-only facts only: no mkdir, token access, DB connection, or backup.
        configured=os.environ.get('UPLOAD_DIR')
        uploads=Path(configured).absolute() if configured else None
        from sqlalchemy.engine import make_url
        try:dialect=make_url(os.environ.get('DATABASE_URL','')).get_backend_name()
        except Exception:dialect='unknown'
        hashes={}
        for name,digest in attempt['module_hashes'].items():
            try:hashes[name]=hashlib.sha256(Path('/app',name).read_bytes()).hexdigest()==digest
            except OSError:hashes[name]=False
        return {'module_hash_matches':hashes,'uploads_configured':bool(configured),
                'uploads_directory_exists':bool(uploads and uploads.is_dir()),
                'uploads_no_symlink':bool(uploads and not any(p.is_symlink() for p in (uploads,*uploads.parents))),
                'attempt_directory_exists':folder.exists(),'attempt_directory_not_symlink':not folder.is_symlink(),
                'archive_exists':archive.is_file(),'metadata_exists':metadata.is_file(),
                'database_dialect':'postgresql' if dialect=='postgresql' else 'other_or_unknown'}
    if operation=='repair-reviewed-helper':
        diagnosis=attempt['repair_diagnosis']
        ensure(diagnosis['id']==attempt['id'] and diagnosis['source_service_id']=='6ab61834a4c05a5bcb57ad69')
        ensure(not diagnosis['attempt_directory_exists'] and not diagnosis['archive_exists'] and not diagnosis['metadata_exists'])
        # Atomic creation below is the final guard after the diagnostic evidence.
        ensure(not folder.exists() and not folder.is_symlink() and not archive.exists() and not metadata.exists())
        uploads=Path(os.environ['UPLOAD_DIR']).absolute()
        ensure(uploads.is_dir() and not any(p.is_symlink() for p in (uploads,*uploads.parents)))
        from sqlalchemy.engine import make_url
        ensure(make_url(os.environ['DATABASE_URL']).get_backend_name()=='postgresql')
        blob=base64.b64decode(attempt['helper_bundle'],validate=True)
        ensure(hashlib.sha256(blob).hexdigest()==attempt['helper_bundle_sha256'])
        with ZipFile(io.BytesIO(blob)) as bundle:
            expected=set(attempt['module_hashes'])|{'scripts/__init__.py'}
            ensure(len(bundle.namelist())==len(expected) and set(bundle.namelist())==expected)
            contents={name:bundle.read(name) for name in expected}
        ensure(contents['scripts/__init__.py']==b'')
        for name,digest in attempt['module_hashes'].items():
            ensure(hashlib.sha256(contents[name]).hexdigest()==digest)
        ensure(not any(k=='scripts' or k.startswith('scripts.') for k in sys.modules))
        folder.mkdir(mode=0o700)  # Original attempt ID, never overwrite any previous attempt.
        helper=folder/'reviewed-helpers';helper.mkdir(mode=0o700)
        (helper/'scripts').mkdir(mode=0o700)
        for name,data in contents.items():
            with (helper/name).open('xb') as out:out.write(data);out.flush();os.fsync(out.fileno())
        sys.dont_write_bytecode=True
        sys.path.insert(0,str(helper))
        import scripts.backup_restore as reviewed_backup
        import scripts.backup_publish as reviewed_publish
        import scripts.backup_live_legacy as reviewed_reader
        ensure(all(Path(m.__file__).resolve().is_relative_to(helper) for m in (reviewed_backup,reviewed_publish,reviewed_reader)))
    if operation in ('create','repair-reviewed-helper'):
        # Review the implementation before executing it on a running database.
        if operation=='create':
            for name,digest in attempt['module_hashes'].items():
                ensure(hashlib.sha256(Path('/app',name).read_bytes()).hexdigest()==digest)
        from scripts.backup_restore import engine_for,backup,validate_archive
        uploads=Path(os.environ['UPLOAD_DIR']).absolute()
        ensure(not any(p.is_symlink() for p in (uploads,*uploads.parents)))
        ensure(uploads.is_dir())
        engine=engine_for(os.environ['DATABASE_URL'])
        ensure(engine.dialect.name=='postgresql')
        # New exclusive directory is the remote attempt checkpoint. Never recreate.
        if operation=='create':folder.mkdir(mode=0o700)
        try:summary=backup(engine,uploads,archive)
        finally:engine.dispose()
        validate_archive(archive)
        # Compare committed DB digests, when available, with captured bytes.
        checked=0;legacy=0
        with ZipFile(archive) as z:
            rows=json.loads(z.read('database.json'))
            refs=[]
            for row in rows['workspaces']:
                for project in row['data'].get('projects',[]):
                    refs.extend((row['id'],f) for f in project.get('files',[]) if f.get('storage')=='local')
            refs.extend((r['workspace_id'],r['data']) for r in rows['business_records']
                        if r['kind']=='project_files' and r['data'].get('storage')=='local')
            for workspace,f in refs:
                name='uploads/'+hashlib.sha256(workspace.encode()).hexdigest()+'/'+f['id']
                expected=f.get('sha256')
                if expected:
                    ensure(re.fullmatch(r'[a-fA-F0-9]{64}',expected) is not None)
                    ensure(hashlib.sha256(z.read(name)).hexdigest()==expected.lower());checked+=1
                else:legacy+=1
        summary.update(committed_file_hashes_verified=checked,legacy_file_references_without_hash=legacy,
                       database_isolation='REPEATABLE READ READ ONLY',archive_schema='yx-workspace-backup/3')
        size=archive.stat().st_size
        ensure(0<size<=MAXIMUM)
        result={'id':attempt['id'],'bytes':size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
                'observed_at':datetime.now(timezone.utc).isoformat(),'snapshot':summary}
        with metadata.open('x',encoding='utf-8') as out:
            json.dump(result,out);out.flush();os.fsync(out.fileno())
        return result
    # Recovery never calls backup, creates directories, or edits the remote zip.
    ensure(not folder.is_symlink() and not archive.is_symlink() and not metadata.is_symlink())
    result=json.loads(metadata.read_text())
    ensure(result['id']==attempt['id'] and 0<result['bytes']<=MAXIMUM)
    data=archive.read_bytes()
    ensure(len(data)==result['bytes'] and hashlib.sha256(data).hexdigest()==result['sha256'])
    result['archive_base64']=base64.b64encode(data).decode('ascii')
    return result
try:print('YX_WORKBENCH_SNAPSHOT='+json.dumps({'ok':True,'result':execute()}))
except Exception:print('YX_WORKBENCH_SNAPSHOT='+json.dumps({'ok':False,'error':'remote_snapshot_unverified'}))
'''
    return code.replace('OPERATION',repr(operation)).replace('ATTEMPT',repr(attempt)).replace('MAXIMUM',str(MAX_BYTES))


def remote_command(operation,attempt):
    encoded=base64.b64encode(zlib.compress(remote_source(operation,attempt).encode())).decode()
    launcher='import base64,zlib;exec(zlib.decompress(base64.b64decode('+repr(encoded)+')))'
    command=[ZEABUR,'service','exec','--id',SERVICE,'--env-id',ENVIRONMENT,
             '-i=false','--','python','-c',launcher]
    check(len(subprocess.list2cmdline(command))<32000,'command_exceeds_32k_no_remote_attempt')
    return command


def run_remote(operation,attempt):
    command=remote_command(operation,attempt)
    try:completed=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='strict',timeout=600)
    except (OSError,subprocess.SubprocessError,UnicodeError):raise SnapshotError('transport_outcome_unknown') from None
    # Never print or persist stdout/stderr: fetched stdout contains the private archive.
    lines=[s[len(MARKER):] for s in completed.stdout.splitlines() if s.startswith(MARKER)]
    check(completed.returncode==0 and len(lines)==1,'transport_outcome_unknown')
    try:response=json.loads(lines[0])
    except (ValueError,TypeError):raise SnapshotError('transport_outcome_unknown') from None
    check(response.get('ok') is True,'remote_snapshot_unverified')
    return response['result']


def validated_metadata(result,attempt):
    import re
    check(result.get('id')==attempt['id'],'attempt_mismatch')
    check(type(result.get('bytes')) is int and 0<result['bytes']<=MAX_BYTES,'invalid_archive_size')
    check(isinstance(result.get('sha256'),str) and re.fullmatch(r'[a-f0-9]{64}',result['sha256']),'invalid_archive_hash')
    checked=datetime.fromisoformat(result['observed_at'])
    check(checked.tzinfo is not None,'invalid_observation_time')
    summary=result.get('snapshot',{})
    check(summary.get('archive_schema')=='yx-workspace-backup/3'
          and summary.get('database_isolation')=='REPEATABLE READ READ ONLY','unverified_snapshot_kind')
    # Only safe aggregate values survive into the local receipt.
    tables=summary.get('tables')
    check(isinstance(tables,dict) and set(tables)=={'workspaces','receipts','source_caches','business_records','company_people','action_audit'}
          and all(type(n) is int and n>=0 for n in tables.values()),'invalid_table_counts')
    safe={k:summary[k] for k in ('archive_schema','database_isolation','tables')}
    for k in ('files','committed_file_hashes_verified','legacy_file_references_without_hash'):
        check(type(summary.get(k)) is int and summary[k]>=0,'invalid_snapshot_counts');safe[k]=summary[k]
    safe['sessions_restored']=False
    return {'id':attempt['id'],'bytes':result['bytes'],'sha256':result['sha256'],
            'observed_at':result['observed_at'],'snapshot':safe}


def reviewed_repair_attempt(attempt,directory):
    diagnosis=json.loads((directory/'diagnostic.json').read_text(encoding='utf-8'))
    check(diagnosis.get('id')==attempt['id'] and diagnosis.get('source_service_id')==SERVICE
          and diagnosis.get('source_environment_id')==ENVIRONMENT,'diagnosis_attempt_mismatch')
    observed=datetime.fromisoformat(diagnosis['observed_at'])
    check(observed.tzinfo is not None and 0<=(datetime.now(timezone.utc)-observed).total_seconds()<3600,'fresh_diagnosis_required')
    check(all(diagnosis.get(k) is False for k in ('attempt_directory_exists','archive_exists','metadata_exists'))
          and all(diagnosis.get(k) is True for k in ('uploads_configured','uploads_directory_exists','uploads_no_symlink','attempt_directory_not_symlink'))
          and diagnosis.get('database_dialect')=='postgresql','repair_requires_absent_attempt_and_ready_storage')
    buffer=io.BytesIO()
    with ZipFile(buffer,'w',ZIP_DEFLATED) as bundle:
        bundle.writestr('scripts/__init__.py',b'')
        for name in MODULES:
            data=(ROOT/name).read_bytes()
            check(hashlib.sha256(data).hexdigest()==attempt['module_hashes'][name],'reviewed_helper_changed_since_attempt')
            bundle.writestr(name,data)
    data=buffer.getvalue()
    repair={**attempt,'helper_bundle':base64.b64encode(data).decode(),'helper_bundle_sha256':hashlib.sha256(data).hexdigest(),
            'repair_diagnosis':diagnosis}
    command=remote_command('repair-reviewed-helper',repair)  # Validate size before checkpoint or transport.
    return repair,{'id':attempt['id'],'source_service_id':SERVICE,'source_environment_id':ENVIRONMENT,
                   'started_at':stamp(),'helper_bundle_sha256':repair['helper_bundle_sha256'],
                   'module_hashes':attempt['module_hashes'],'command_characters':len(subprocess.list2cmdline(command))}


def execute(operation):
    check(operation in ('capture','recover','status','diagnose','repair-preflight','repair-reviewed-helper'),'invalid_operation')
    directory=DIRECTORY.resolve()
    check(directory.is_relative_to((ROOT/'.runtime').resolve()),'private_directory_required')
    directory.mkdir(parents=True,exist_ok=True)
    checkpoint=directory/'attempt.json';receipt_path=directory/'receipt.json';archive=directory/'snapshot.zip'
    if operation=='capture':
        attempt={'id':secrets.token_hex(16),'source_service_id':SERVICE,'source_environment_id':ENVIRONMENT,
                 'started_at':stamp(),'module_hashes':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in MODULES}}
        try:exclusive_json(checkpoint,attempt)
        except FileExistsError:raise SnapshotError('existing_attempt_use_recover_never_recapture') from None
        validated_metadata(run_remote('create',attempt),attempt)
    else:
        check(checkpoint.is_file(),'snapshot_attempt_missing')
        attempt=json.loads(checkpoint.read_text(encoding='utf-8'))
    import re
    check(re.fullmatch(r'[a-f0-9]{32}',attempt.get('id','')) is not None
          and attempt.get('source_service_id')==SERVICE and attempt.get('source_environment_id')==ENVIRONMENT,
          'invalid_attempt_checkpoint')
    if operation=='diagnose':
        result=run_remote('diagnose',attempt)
        expected=('uploads_configured','uploads_directory_exists','uploads_no_symlink',
                  'attempt_directory_exists','attempt_directory_not_symlink','archive_exists','metadata_exists')
        check(all(type(result.get(k)) is bool for k in expected),'invalid_diagnostic')
        hashes=result.get('module_hash_matches',{})
        check(set(hashes)==set(MODULES) and all(type(v) is bool for v in hashes.values()),'invalid_diagnostic')
        check(result.get('database_dialect') in ('postgresql','other_or_unknown'),'invalid_diagnostic')
        diagnostic={**{k:result[k] for k in expected},'module_hash_matches':hashes,
                'database_dialect':result['database_dialect'],'source_service_id':SERVICE,
                'source_environment_id':ENVIRONMENT,'id':attempt['id'],'observed_at':stamp(),
                'read_only':True,'remote_created':False}
        temporary=directory/('diagnostic-'+secrets.token_hex(8)+'.tmp')
        exclusive_json(temporary,diagnostic)
        os.replace(temporary,directory/'diagnostic.json')
        return diagnostic
    if receipt_path.exists():
        receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
        metadata=validated_metadata(receipt,attempt)
        check(receipt.get('archive_path')==str(archive) and receipt.get('source_service_id')==SERVICE
              and receipt.get('source_environment_id')==ENVIRONMENT and not archive.is_symlink()
              and archive.is_file() and archive.stat().st_size==metadata['bytes']
              and hashlib.sha256(archive.read_bytes()).hexdigest()==metadata['sha256'],
              'existing_receipt_mismatch')
        return {**metadata,'archive_path':str(archive),'source_service_id':SERVICE,'source_environment_id':ENVIRONMENT}
    if operation=='status':return {'status':'outcome_unknown','source_service_id':SERVICE,'recovery':'recover same remote archive only'}
    if operation=='repair-preflight':
        _,marker=reviewed_repair_attempt(attempt,directory)
        check(not (directory/'repair-attempt.json').exists(),'existing_repair_attempt_use_recover_never_repair_again')
        return {**marker,'ready_for_reviewed_helper_repair':True,'network_accessed':False,'remote_created':False}
    if operation=='repair-reviewed-helper':
        repair,repair_marker=reviewed_repair_attempt(attempt,directory)
        try:exclusive_json(directory/'repair-attempt.json',repair_marker)
        except FileExistsError:raise SnapshotError('existing_repair_attempt_use_recover_never_repair_again') from None
        validated_metadata(run_remote('repair-reviewed-helper',repair),attempt)
    result=run_remote('fetch',attempt)
    metadata=validated_metadata(result,attempt)
    try:data=base64.b64decode(result['archive_base64'],validate=True)
    except (ValueError,TypeError,KeyError):raise SnapshotError('archive_transport_invalid') from None
    check(len(data)==metadata['bytes'] and hashlib.sha256(data).hexdigest()==metadata['sha256'],'archive_transport_mismatch')
    temporary=directory/('snapshot.partial-'+secrets.token_hex(8))
    try:
        with temporary.open('xb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        manifest=validate_archive(temporary)
        check(manifest.get('schema')=='yx-workspace-backup/3' and manifest['tables']==metadata['snapshot']['tables'],'archive_manifest_mismatch')
        if archive.exists():check(hashlib.sha256(archive.read_bytes()).hexdigest()==metadata['sha256'],'existing_archive_mismatch')
        else:publish(temporary,archive)
    finally:temporary.unlink(missing_ok=True)
    receipt={**metadata,'archive_path':str(archive),'source_service_id':SERVICE,
             'source_environment_id':ENVIRONMENT,'received_at':stamp()}
    exclusive_json(receipt_path,receipt)
    return receipt


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=('capture','recover','status','diagnose','repair-preflight','repair-reviewed-helper'))
    args=parser.parse_args(argv)
    try:
        result=execute(args.operation)
        print(json.dumps({'ok':True,**result}));return 0
    except SnapshotError as exc:code=str(exc)
    except Exception:code='snapshot_unverified'
    print(json.dumps({'ok':False,'error':code,'retry_policy':'recover same archive only; never recreate automatically'}));return 1


if __name__=='__main__':raise SystemExit(main())
