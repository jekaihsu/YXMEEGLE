import base64
import json
from types import SimpleNamespace
import pytest
from cryptography.fernet import Fernet,InvalidToken
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa,padding
from scripts import workbench_restore_envelope as envelope


@pytest.fixture(scope='module')
def pair():
    private=rsa.generate_private_key(public_exponent=65537,key_size=3072)
    public=private.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return private,public


def unwrap(private,wrapped):
    return private.decrypt(base64.b64decode(wrapped),padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),algorithm=hashes.SHA256(),label=b'yx-restore-probe-v1'))


def test_envelope_only_contains_ciphertext(pair):
    private,public=pair;value=envelope.envelope_for(public)
    assert envelope.NONCE not in json.dumps(value)
    key=unwrap(private,value['wrapped_key'])
    payload=json.loads(Fernet(key).decrypt(value['ciphertext'].encode(),ttl=300))
    assert payload=={'purpose':'transport_probe','nonce':envelope.NONCE,'service_id':envelope.STAGING}


def test_ciphertext_tampering_is_rejected(pair):
    private,public=pair;value=envelope.envelope_for(public)
    key=unwrap(private,value['wrapped_key'])
    token=bytearray(base64.urlsafe_b64decode(value['ciphertext']));token[-1]^=1
    with pytest.raises(InvalidToken):Fernet(key).decrypt(base64.urlsafe_b64encode(token))


def test_oaep_wrong_purpose_rejected(pair):
    private,public=pair;value=envelope.envelope_for(public)
    with pytest.raises(ValueError):
        private.decrypt(base64.b64decode(value['wrapped_key']),padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),algorithm=hashes.SHA256(),label=b'other-purpose'))


def test_remote_programs_compile_and_private_key_is_exclusive():
    compile(envelope.REMOTE_COMMON+envelope.REMOTE_PREPARE,'prepare','exec')
    compile(envelope.REMOTE_COMMON+'\nenvelope={}\n'+envelope.REMOTE_PROBE,'probe','exec')
    assert 'os.O_EXCL|os.O_NOFOLLOW' in envelope.REMOTE_COMMON
    assert "create('key-attempt.json'" in envelope.REMOTE_PREPARE
    assert 'never regenerate' in envelope.REMOTE_PREPARE
    assert 'st_uid!=os.geteuid()' in envelope.REMOTE_COMMON
    assert '0o600' in envelope.REMOTE_COMMON and '0o700' in envelope.REMOTE_COMMON


def test_fixed_exec_target_and_no_raw_output(monkeypatch):
    def run(cmd,**kwargs):
        assert cmd[cmd.index('--id')+1]==envelope.STAGING
        assert cmd[cmd.index('--env-id')+1]==envelope.ENV
        assert '-i=false' in cmd
        return SimpleNamespace(returncode=1,stdout='PRIVATE',stderr='PRIVATE')
    monkeypatch.setattr(envelope.subprocess,'run',run)
    with pytest.raises(RuntimeError,match='suppressed') as error:envelope.remote('pass')
    assert 'PRIVATE' not in str(error.value)


def test_changed_remote_public_key_is_not_adopted(tmp_path,monkeypatch,pair):
    _,public=pair
    monkeypatch.setattr(envelope,'STATE',tmp_path)
    result={'ok':True,'public_key':public,'fingerprint':envelope.hashlib.sha256(public.encode()).hexdigest(),'private_key_exported':False}
    monkeypatch.setattr(envelope,'remote',lambda _:result)
    (tmp_path/'envelope-public.json').write_text(json.dumps({'old':'key'}))
    with pytest.raises(RuntimeError,match='changed'):envelope.prepare()
    assert json.loads((tmp_path/'envelope-public.json').read_text())=={'old':'key'}

def test_db_check_configuration_is_fixed_and_readonly(tmp_path,monkeypatch):
    from scripts import workbench_restore_setup as setup
    from sqlalchemy.engine import make_url
    monkeypatch.setattr(envelope,'STATE',tmp_path)
    monkeypatch.setattr(setup,'inventory',lambda:[{'_id':envelope.RESTORE,'name':'yongxiang-workbench-restore-drill','dnsName':'restore-private-dns'}])
    (tmp_path/'created.json').write_text(json.dumps({'service_id':envelope.RESTORE,'project_id':setup.PROJECT,'environment_id':envelope.ENV}))
    (tmp_path/'secrets.json').write_text(json.dumps({'database_user':'restore_drill','database_name':'workbench_restore_drill','database_password':'secret-for-test-'*4}))
    host,payload=envelope.database_config();dsn=make_url(payload['database_url'])
    assert host=='restore-private-dns.zeabur.internal' and dsn.host==host
    assert dsn.database=='workbench_restore_drill'
    assert 'default_transaction_read_only=on' in dsn.query['options']
    assert dsn.query['connect_timeout']=='10'
    assert payload['purpose']=='readonly_empty_database_check'


def test_db_check_wrong_inventory_rejected(monkeypatch):
    from scripts import workbench_restore_setup as setup
    monkeypatch.setattr(setup,'inventory',lambda:[{'_id':envelope.STAGING,'name':'yongxiang-workbench-restore-drill','dnsName':'formal'}])
    with pytest.raises(RuntimeError,match='identity mismatch'):envelope.database_config()


def test_db_check_never_places_plaintext_dsn_in_launcher(tmp_path,monkeypatch,pair):
    _,public=pair;fingerprint=envelope.hashlib.sha256(public.encode()).hexdigest()
    monkeypatch.setattr(envelope,'STATE',tmp_path)
    (tmp_path/'envelope-public.json').write_text(json.dumps({'public_key':public,'fingerprint':fingerprint}))
    secret_dsn='postgresql+psycopg://restore_drill:VERY_SECRET_PASSWORD@exact.zeabur.internal:5432/workbench_restore_drill'
    monkeypatch.setattr(envelope,'database_config',lambda:('exact.zeabur.internal',{'purpose':'readonly_empty_database_check','service_id':envelope.RESTORE,'database_url':secret_dsn}))
    def remote(source):
        assert secret_dsn not in source and 'VERY_SECRET_PASSWORD' not in source
        assert "expected_host='exact.zeabur.internal'" in source
        compile(source,'db-check','exec')
        return {'ok':True,'database_empty_verified':True,'fingerprint':fingerprint}
    monkeypatch.setattr(envelope,'remote',remote)
    receipt=envelope.db_check()
    assert receipt['database_empty_verified'] and 'VERY_SECRET_PASSWORD' not in json.dumps(receipt)
