import base64
import hashlib
import io
import json
from types import SimpleNamespace
from zipfile import ZipFile
import pytest
from scripts import workbench_snapshot as snapshot


@pytest.fixture
def capture(tmp_path,monkeypatch):
    monkeypatch.setattr(snapshot,'ROOT',tmp_path)
    monkeypatch.setattr(snapshot,'DIRECTORY',tmp_path/'.runtime/workbench-snapshot')
    for name in snapshot.MODULES:
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('reviewed module')
    tables={k:0 for k in ('workspaces','receipts','source_caches','business_records','company_people','action_audit')}
    database=json.dumps({k:[] for k in tables}).encode()
    output=io.BytesIO()
    with ZipFile(output,'w') as z:
        z.writestr('database.json',database)
        z.writestr('manifest.json',json.dumps({'schema':'yx-workspace-backup/3','tables':tables,
             'sha256':{'database.json':hashlib.sha256(database).hexdigest()}}))
    data=output.getvalue();calls=[];failure=[False]
    def remote(operation,attempt):
        calls.append(operation)
        if failure[0]:raise snapshot.SnapshotError('transport_outcome_unknown')
        result={'id':attempt['id'],'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),
                'observed_at':snapshot.stamp(),'snapshot':{'tables':tables,'files':0,
                 'committed_file_hashes_verified':0,'legacy_file_references_without_hash':0,
                 'archive_schema':'yx-workspace-backup/3','database_isolation':'REPEATABLE READ READ ONLY'}}
        if operation=='fetch':result['archive_base64']=base64.b64encode(data).decode()
        return result
    monkeypatch.setattr(snapshot,'run_remote',remote)
    return SimpleNamespace(calls=calls,failure=failure,data=data,remote=remote)


def test_capture_validates_archive_and_prints_only_safe_receipt(capture,capsys):
    assert snapshot.main(['capture'])==0
    printed=capsys.readouterr().out
    assert 'archive_base64' not in printed and base64.b64encode(capture.data).decode() not in printed
    receipt=json.loads((snapshot.DIRECTORY/'receipt.json').read_text())
    assert receipt['source_service_id']==snapshot.SERVICE
    assert receipt['sha256']==hashlib.sha256(capture.data).hexdigest()
    assert capture.calls==['create','fetch']
    assert (snapshot.DIRECTORY/'snapshot.zip').read_bytes()==capture.data


def test_unknown_capture_preserves_marker_and_recovery_never_recreates(capture):
    capture.failure[0]=True
    with pytest.raises(snapshot.SnapshotError,match='unknown'):snapshot.execute('capture')
    assert (snapshot.DIRECTORY/'attempt.json').exists()
    with pytest.raises(snapshot.SnapshotError,match='existing_attempt'):snapshot.execute('capture')
    capture.failure[0]=False
    assert snapshot.execute('recover')['sha256']==hashlib.sha256(capture.data).hexdigest()
    assert capture.calls==['create','fetch']
    snapshot.execute('status');snapshot.execute('recover')
    assert capture.calls==['create','fetch']


def test_transport_hash_mismatch_never_publishes_receipt(capture,monkeypatch):
    def wrong(operation,attempt):
        result=capture.remote(operation,attempt)
        if operation=='fetch':result['archive_base64']=base64.b64encode(b'bad').decode()
        return result
    monkeypatch.setattr(snapshot,'run_remote',wrong)
    with pytest.raises(snapshot.SnapshotError,match='transport_mismatch'):snapshot.execute('capture')
    assert not (snapshot.DIRECTORY/'receipt.json').exists()
    assert not (snapshot.DIRECTORY/'snapshot.zip').exists()


def test_remote_code_has_fixed_readonly_backup_and_fetch_does_not_rebuild():
    code=snapshot.remote_source('fetch',{'id':'a'*32,'module_hashes':{}})
    compile(code,'<remote>','exec')
    assert 'from scripts.backup_restore import engine_for,backup,validate_archive' in code
    assert 'engine.dialect.name==\'postgresql\'' in code
    assert 'folder.mkdir(mode=0o700)' in code
    assert "operation='fetch'" in code
    assert 'backup_live_legacy import backup' not in code


def test_invalid_remote_output_is_never_echoed(monkeypatch,capsys):
    def transport(command,**kwargs):
        assert command[command.index('--id')+1]==snapshot.SERVICE
        assert command[command.index('--env-id')+1]==snapshot.ENVIRONMENT
        assert kwargs['capture_output'] is True
        return SimpleNamespace(returncode=1,stdout='private records and archive',stderr='secret password')
    monkeypatch.setattr(snapshot.subprocess,'run',transport)
    with pytest.raises(snapshot.SnapshotError):snapshot.run_remote('fetch',{'id':'a'*32})
    assert capsys.readouterr().out==''


def test_diagnose_keeps_attempt_unchanged_and_only_reports_safe_facts(capture,monkeypatch):
    capture.failure[0]=True
    with pytest.raises(snapshot.SnapshotError):snapshot.execute('capture')
    checkpoint=snapshot.DIRECTORY/'attempt.json';original=checkpoint.read_bytes()
    def remote(operation,attempt):
        assert operation=='diagnose'
        return {'module_hash_matches':{name:False for name in snapshot.MODULES},
                'uploads_configured':True,'uploads_directory_exists':True,'uploads_no_symlink':True,
                'attempt_directory_exists':False,'attempt_directory_not_symlink':True,
                'archive_exists':False,'metadata_exists':False,'database_dialect':'postgresql',
                'unexpected_private_path':'must not echo'}
    monkeypatch.setattr(snapshot,'run_remote',remote)
    result=snapshot.execute('diagnose')
    assert result['read_only'] and not result['remote_created']
    assert 'unexpected_private_path' not in result
    assert checkpoint.read_bytes()==original
    assert not (snapshot.DIRECTORY/'receipt.json').exists()
    code=snapshot.remote_source('diagnose',json.loads(original))
    compile(code,'<remote>','exec')
    diagnostic=code[code.index("if operation=='diagnose':"):code.index("if operation=='repair-reviewed-helper':")]
    assert 'mkdir' not in diagnostic.split('\n',2)[2]
    assert 'engine.connect' not in diagnostic and 'backup(' not in diagnostic


def write_diagnostic():
    attempt=json.loads((snapshot.DIRECTORY/'attempt.json').read_text())
    data={'id':attempt['id'],'source_service_id':snapshot.SERVICE,'source_environment_id':snapshot.ENVIRONMENT,
          'observed_at':snapshot.stamp(),'attempt_directory_exists':False,'archive_exists':False,'metadata_exists':False,
          'uploads_configured':True,'uploads_directory_exists':True,'uploads_no_symlink':True,
          'attempt_directory_not_symlink':True,'database_dialect':'postgresql'}
    snapshot.exclusive_json(snapshot.DIRECTORY/'diagnostic.json',data)
    return attempt


def test_unknown_repair_preserves_original_and_never_resends(capture,monkeypatch):
    capture.failure[0]=True
    with pytest.raises(snapshot.SnapshotError):snapshot.execute('capture')
    checkpoint=snapshot.DIRECTORY/'attempt.json';original=checkpoint.read_bytes()
    write_diagnostic()
    with pytest.raises(snapshot.SnapshotError,match='unknown'):snapshot.execute('repair-reviewed-helper')
    assert (snapshot.DIRECTORY/'repair-attempt.json').is_file()
    with pytest.raises(snapshot.SnapshotError,match='existing_repair'):snapshot.execute('repair-reviewed-helper')
    assert capture.calls==['create','repair-reviewed-helper']
    assert checkpoint.read_bytes()==original
    capture.failure[0]=False;snapshot.execute('recover')
    assert capture.calls==['create','repair-reviewed-helper','fetch']


def test_repair_refuses_wrong_diagnostic_or_existing_remote_directory(capture):
    capture.failure[0]=True
    with pytest.raises(snapshot.SnapshotError):snapshot.execute('capture')
    write_diagnostic();path=snapshot.DIRECTORY/'diagnostic.json';data=json.loads(path.read_text())
    data['attempt_directory_exists']=True;path.write_text(json.dumps(data))
    with pytest.raises(snapshot.SnapshotError,match='absent_attempt'):snapshot.execute('repair-reviewed-helper')
    assert not (snapshot.DIRECTORY/'repair-attempt.json').exists()
    assert capture.calls==['create']
    data['attempt_directory_exists']=False;data['id']='b'*32;path.write_text(json.dumps(data))
    with pytest.raises(snapshot.SnapshotError,match='diagnosis_attempt_mismatch'):snapshot.execute('repair-reviewed-helper')


def test_reviewed_bundle_imports_from_private_directory_and_command_is_bounded(capture,tmp_path):
    import subprocess,sys
    from pathlib import Path
    repository=Path(__file__).resolve().parents[1]
    for name in snapshot.MODULES:
        (tmp_path/name).parent.mkdir(parents=True,exist_ok=True)
        (tmp_path/name).write_bytes((repository/name).read_bytes())
    capture.failure[0]=True
    with pytest.raises(snapshot.SnapshotError):snapshot.execute('capture')
    attempt=write_diagnostic()
    repair,marker=snapshot.reviewed_repair_attempt(attempt,snapshot.DIRECTORY)
    assert marker['command_characters']<32000 and repair['id']==attempt['id']
    root=tmp_path/'private-reviewed-helper';root.mkdir()
    with ZipFile(io.BytesIO(base64.b64decode(repair['helper_bundle']))) as z:
        assert set(z.namelist())==set(snapshot.MODULES)|{'scripts/__init__.py','backend/__init__.py'}
        z.extractall(root)  # Known exact, reviewed test bundle only.
    code="import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);import scripts.backup_restore as a;import scripts.backup_publish as b;import scripts.backup_live_legacy as c;assert all(Path(m.__file__).resolve().is_relative_to(Path(sys.argv[1])) for m in (a,b,c));print('isolated')"
    result=subprocess.run([sys.executable,'-c',code,str(root)],cwd=tmp_path,capture_output=True,text=True)
    assert result.returncode==0 and result.stdout.strip()=='isolated'
    remote=snapshot.remote_source('repair-reviewed-helper',repair)
    compile(remote,'<repair>','exec')
    assert "folder/'reviewed-helpers'" in remote
    assert "not folder.exists() and not folder.is_symlink()" in remote
    assert "(helper/name).open('xb')" in remote
    assert "Path('/app',name).write" not in remote
