import hashlib
from datetime import datetime,timezone
from pathlib import Path
import pytest
from cryptography.fernet import Fernet,InvalidToken
import json
from scripts import backup_offsite as offsite


def cfg():return {'BACKUP_ENCRYPTION_KEYS_JSON':json.dumps([Fernet.generate_key().decode()]),
    'BACKUP_DRIVE_ROOT_TOKEN':'private-root','BACKUP_DRIVE_ALLOWED_ROOT':'private-root','BACKUP_DRIVE_PRIVATE_ROOT_VERIFIED':'true','BACKUP_REMOTE_PRUNE_ENABLED':'true'}


class Drive:
    def __init__(self):self.files={};self.uploads=0;self.fail_after_upload=False;self.deleted=[]
    def request(self,method,path,**kwargs):
        if method=='GET':return {'files':[{'token':k,**v['meta']} for k,v in self.files.items()],'has_more':False}
        assert method=='DELETE' and kwargs['params']=={'type':'file'}
        token=path.rsplit('/',1)[1];self.deleted.append(token);self.files.pop(token,None);return {}
    def upload(self,path,root,name):
        token='token'+str(self.uploads);self.uploads+=1
        self.files[token]={'data':Path(path).read_bytes(),'meta':{'name':name,'parent_token':root,'type':'file'}}
        if self.fail_after_upload:self.fail_after_upload=False;raise TimeoutError('lost reply')
        return {'file_token':token}
    def verify_file(self,token,digest):assert hashlib.sha256(self.files[token]['data']).hexdigest()==digest


def test_chunked_encryption_roundtrip_and_key_rotation(tmp_path,monkeypatch):
    monkeypatch.setattr(offsite,'CHUNK_BYTES',5)
    source=tmp_path/'yx-daily-2026-09-29.zip';source.write_bytes(b'private evidence'*6)
    settings=cfg();bundle,state=offsite.prepare(source,tmp_path/'encrypted',settings)
    assert len(state['files'])>3
    assert all(b'private evidence' not in (bundle/f['name']).read_bytes() for f in state['files'])
    rotated={**settings,'BACKUP_ENCRYPTION_KEYS_JSON':json.dumps([Fernet.generate_key().decode()]+json.loads(settings['BACKUP_ENCRYPTION_KEYS_JSON']))}
    target=tmp_path/'restored.zip'
    offsite.decrypt_bundle(bundle/state['files'][-1]['name'],target,rotated)
    assert target.read_bytes()==source.read_bytes()
    with pytest.raises(ValueError):offsite.decrypt_bundle(bundle/state['files'][-1]['name'],target,rotated)


def test_lost_upload_response_reconciles_by_exact_cipher_hash_without_duplicate(tmp_path):
    source=tmp_path/'yx-daily-2026-09-29.zip';source.write_bytes(b'backup');settings=cfg();drive=Drive()
    drive.fail_after_upload=True
    with pytest.raises(TimeoutError):offsite.replicate(source,tmp_path/'encrypted',settings,drive)
    assert drive.uploads==1
    assert offsite.replicate(source,tmp_path/'encrypted',settings,drive)['status']=='verified'
    assert drive.uploads==2  # one chunk plus encrypted manifest only
    offsite.replicate(source,tmp_path/'encrypted',settings,drive)
    assert drive.uploads==2


def test_tamper_or_wrong_key_never_publishes_decrypted_archive(tmp_path):
    source=tmp_path/'yx-daily-2026-09-29.zip';source.write_bytes(b'private');settings=cfg()
    bundle,state=offsite.prepare(source,tmp_path/'encrypted',settings)
    with pytest.raises(InvalidToken):offsite.decrypt_bundle(bundle/state['files'][-1]['name'],tmp_path/'wrong.zip',cfg())
    chunk=bundle/state['files'][0]['name'];chunk.write_bytes(chunk.read_bytes()+b'tampered')
    with pytest.raises(ValueError):offsite.decrypt_bundle(bundle/state['files'][-1]['name'],tmp_path/'tampered.zip',settings)
    assert not (tmp_path/'tampered.zip').exists()


@pytest.mark.parametrize('key',['BACKUP_ENCRYPTION_KEYS_JSON','BACKUP_DRIVE_ALLOWED_ROOT','BACKUP_DRIVE_PRIVATE_ROOT_VERIFIED'])
def test_incomplete_offsite_settings_fail_closed(key):
    settings=cfg();settings.pop(key)
    with pytest.raises(ValueError):offsite.settings(settings)


@pytest.mark.parametrize('key',['LARK_DRIVE_ROOT','LARK_TEST_DRIVE_ROOT'])
def test_backup_root_cannot_share_actual_deliverable_configuration(key):
    settings=cfg();settings[key]=settings['BACKUP_DRIVE_ROOT_TOKEN']
    with pytest.raises(ValueError,match='separate'):offsite.settings(settings)


def test_retention_only_removes_owned_expired_backups_in_allowlisted_root(tmp_path):
    settings=cfg();drive=Drive();directory=tmp_path/'encrypted'
    for label in ('yx-daily-2026-08-01','yx-daily-2026-09-29','yx-monthly-2025-08','yx-monthly-2025-10','yx-monthly-2027-01'):
        source=tmp_path/(label+'.zip');source.write_bytes(label.encode());offsite.replicate(source,directory,settings,drive)
    drive.files['unrelated']={'data':b'company document','meta':{'name':'other','parent_token':'private-root','type':'file'}}
    assert offsite.prune(directory,settings,drive,datetime(2026,9,29,tzinfo=timezone.utc))==2
    assert len(drive.deleted)==4 and 'unrelated' in drive.files


def test_async_delete_keeps_local_bytes_and_never_blindly_retries(tmp_path):
    settings=cfg();drive=Drive();directory=tmp_path/'encrypted'
    source=tmp_path/'yx-daily-2026-08-01.zip';source.write_bytes(b'backup')
    offsite.replicate(source,directory,settings,drive)
    original=drive.request;deletes=[]
    def pending(method,path,**kwargs):
        if method=='DELETE':deletes.append(path);return {'task_id':'pending'}
        return original(method,path,**kwargs)
    drive.request=pending
    for message in ('pending','unknown'):
        with pytest.raises(ValueError,match=message):offsite.prune(directory,settings,drive,datetime(2026,9,29,tzinfo=timezone.utc))
    assert len(deletes)==1 and list(directory.rglob('receipt.json'))
    drive.files.pop(deletes[0].rsplit('/',1)[1]);drive.request=original
    assert offsite.prune(directory,settings,drive,datetime(2026,9,29,tzinfo=timezone.utc))==1
    assert not list(directory.rglob('*.fernet'))


def test_encrypted_remote_copy_restores_all_tables_and_referenced_files(tmp_path):
    from .test_backup_safety import source as fixture_source
    from scripts import backup_restore as br
    from scripts.restore_drill import database_payload
    from sqlalchemy import create_engine
    engine,uploads=fixture_source(tmp_path)
    folder=uploads/hashlib.sha256(b'company').hexdigest()
    (folder/'normalized').write_bytes(b'normalized evidence')
    with engine.begin() as db:
        db.execute(br.TABLES[1].insert(),{'id':'receipt','fingerprint':'f','result':{'ok':True}})
        db.execute(br.TABLES[2].insert(),{'id':'cache','data':{'records':[]}})
        db.execute(br.TABLES[3].insert(),{'workspace_id':'company','kind':'project_files','entity_id':'normalized','parent_id':'p1','ordinal':0,'data':{'id':'normalized','storage':'local','size':19}})
        db.execute(br.TABLES[4].insert(),{'organization_id':'company','person_id':'person','data':{'active':True}})
    archive=tmp_path/'yx-daily-2026-09-29.zip';br.backup(engine,uploads,archive)
    settings=cfg();drive=Drive();offsite.replicate(archive,tmp_path/'encrypted',settings,drive)
    downloaded=tmp_path/'downloaded';downloaded.mkdir()
    for value in drive.files.values():(downloaded/value['meta']['name']).write_bytes(value['data'])
    recovered=tmp_path/'recovered.zip'
    offsite.decrypt_bundle(next(downloaded.glob('*-manifest.fernet')),recovered,settings)
    restored=create_engine('sqlite:///'+str(tmp_path/'restored.db'));restored_uploads=tmp_path/'restored-files'
    result=br.restore(restored,restored_uploads,recovered)
    assert all(result['tables'][table.name]==1 for table in br.TABLES)
    assert result['files']==2 and result['sessions_restored'] is False
    replay=tmp_path/'replay.zip';br.backup(restored,restored_uploads,replay)
    assert database_payload(archive)==database_payload(replay)
    assert {str(p.relative_to(uploads)):p.read_bytes() for p in uploads.rglob('*') if p.is_file()}=={str(p.relative_to(restored_uploads)):p.read_bytes() for p in restored_uploads.rglob('*') if p.is_file()}


def test_drill_engine_failure_removes_decrypted_archive(tmp_path,monkeypatch):
    from scripts import restore_drill
    source=tmp_path/'yx-daily-2026-09-29.zip';source.write_bytes(b'backup');settings=cfg()
    bundle,state=offsite.prepare(source,tmp_path/'encrypted',settings)
    for key,value in settings.items():monkeypatch.setenv(key,value)
    monkeypatch.setenv('DATABASE_URL','postgresql://host/company')
    monkeypatch.setenv('RESTORE_DRILL_DATABASE_URL','postgresql://host/drill')
    def failed(url):raise RuntimeError('engine unavailable')
    monkeypatch.setattr(restore_drill,'engine_for',failed)
    with pytest.raises(RuntimeError):restore_drill.run(bundle/state['files'][-1]['name'],tmp_path/'uploads',tmp_path/'receipt.json',True)
    assert not list(tmp_path.glob('drill-decrypted-*'))
