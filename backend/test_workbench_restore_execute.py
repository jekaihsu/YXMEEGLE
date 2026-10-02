import json
import pytest
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from scripts import workbench_restore_execute as execute


@pytest.fixture
def prepared(tmp_path,monkeypatch):
    monkeypatch.setattr(execute,'STATE',tmp_path)
    private=rsa.generate_private_key(public_exponent=65537,key_size=3072)
    public=private.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    fingerprint=execute.hashlib.sha256(public.encode()).hexdigest()
    (tmp_path/'envelope-public.json').write_text(json.dumps({'public_key':public,'fingerprint':fingerprint}))
    payload={'purpose':'fixed_isolated_restore','service_id':execute.transport.RESTORE,'database_url':'postgresql://RESTORE_SECRET',
             'backup_config':{'BACKUP_LARK_APP_SECRET':'BACKUP_SECRET','BACKUP_ENCRYPTION_KEYS_JSON':'ENCRYPTION_SECRET'},
             'checkpoint':{},'source_sha256':'a'*64}
    monkeypatch.setattr(execute,'configuration',lambda:('restore.zeabur.internal',payload))
    return tmp_path,payload,fingerprint


def test_remote_restore_program_compiles():
    compile(execute.transport.REMOTE_COMMON+'\nenvelope={}\nexpected_host="host"\n'+execute.REMOTE_RESTORE,'restore','exec')
    compile(execute.transport.REMOTE_COMMON+execute.REMOTE_STATUS,'status','exec')
    assert execute.REMOTE_RESTORE.index("create('restore-attempt.json'")<execute.REMOTE_RESTORE.index('manifest=download_files')
    assert execute.REMOTE_RESTORE.index('if actual!=')<execute.REMOTE_RESTORE.index('restored=restore_run')
    assert 'assert_empty_database(engine)' in execute.REMOTE_RESTORE
    assert 'restore_run(decrypted' in execute.REMOTE_RESTORE


def test_secret_configuration_never_in_remote_argv(prepared,monkeypatch):
    directory,payload,fingerprint=prepared
    def remote(source):
        for secret in ('RESTORE_SECRET','BACKUP_SECRET','ENCRYPTION_SECRET'):
            assert secret not in source
        assert (directory/'restore-dispatch-attempt.json').exists()
        return {'ok':True,'service_id':execute.transport.RESTORE,'source_sha256':payload['source_sha256'],'fingerprint':fingerprint,
                'postgresql_rows_equal':True,'attachments_equal':True,'restore_performed':True}
    monkeypatch.setattr(execute.transport,'remote',remote)
    result=execute.restore()
    assert result['postgresql_rows_equal']
    assert 'SECRET' not in (directory/'restore-verified.json').read_text()


def test_unknown_dispatch_never_retries(prepared,monkeypatch):
    directory,_,_=prepared
    monkeypatch.setattr(execute.transport,'remote',lambda _:(_ for _ in ()).throw(RuntimeError('timeout')))
    with pytest.raises(RuntimeError,match='timeout'):execute.restore()
    assert (directory/'restore-dispatch-attempt.json').exists()
    monkeypatch.setattr(execute.transport,'remote',lambda _:pytest.fail('must not repeat'))
    with pytest.raises(RuntimeError,match='status only'):execute.restore()


def test_status_recovers_only_matching_receipt(prepared,monkeypatch):
    directory,payload,fingerprint=prepared
    expected={'service_id':execute.transport.RESTORE,'source_sha256':payload['source_sha256'],'fingerprint':fingerprint}
    (directory/'restore-dispatch-attempt.json').write_text(json.dumps(expected))
    monkeypatch.setattr(execute.transport,'remote',lambda _: {'ok':True,'status':'verified','receipt':{'ok':True,'postgresql_rows_equal':True,'attachments_equal':True,'restore_performed':True,**expected}})
    assert execute.status()['status']=='verified'
    assert (directory/'restore-verified.json').exists()


def test_status_unknown_does_not_authorize_restore(prepared,monkeypatch):
    directory,_,_=prepared
    monkeypatch.setattr(execute.transport,'remote',lambda _: {'ok':True,'status':'outcome_unknown','retry_authorized':False})
    assert execute.status()['retry_authorized'] is False
    assert not (directory/'restore-verified.json').exists()
