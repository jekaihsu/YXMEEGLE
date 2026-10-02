"""Fixed staging encrypted transport: nonce probe and read-only empty DB check.

The remote private key never leaves the container. Local callers cannot select
payloads, paths or target services. Every cloud call requires normal approval.
"""
import argparse
import base64
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import textwrap
import zlib
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import padding,rsa

ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'.runtime/cloud-restore'
STAGING='6abc0821454b8f31a5ef614a'
ENV='6ab6168036d2a6cac409f0c6'
MARKER='YX_RESTORE_ENVELOPE='
NONCE='YX_NONSECRET_ENVELOPE_PROBE_20260930'
DIRECTORY='/tmp/yx-restore-20260930'
RESTORE='6abce665454b8f31a5efc37e'

REMOTE_COMMON=r'''
import base64,hashlib,json,os,stat
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa,padding
root=Path('/tmp/yx-restore-20260930')
def safe(path,directory=False):
 s=path.lstat()
 if s.st_uid!=os.geteuid() or stat.S_IMODE(s.st_mode)!=(0o700 if directory else 0o600):
  raise RuntimeError('Unsafe restore transport permissions')
 if not (stat.S_ISDIR(s.st_mode) if directory else stat.S_ISREG(s.st_mode)):
  raise RuntimeError('Unsafe restore transport file type')
 if not directory and s.st_nlink!=1:raise RuntimeError('Unsafe restore transport hardlink')
def create(name,content):
 p=root/name
 fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb') as out:
  out.write(content);out.flush();os.fsync(out.fileno())
 safe(p)
def read(name):
 p=root/name;safe(p)
 fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as source:
  info=os.fstat(source.fileno())
  if info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=0o600 or info.st_nlink!=1:raise RuntimeError('Unsafe opened key')
  return source.read(32768)
def emit(value):print('YX_RESTORE_ENVELOPE='+json.dumps(value))
'''
REMOTE_PREPARE=r'''
if not root.exists():root.mkdir(mode=0o700)
safe(root,True)
keyfile=root/'private.pem'
if keyfile.exists():
 if not (root/'key-ready.json').exists():raise RuntimeError('Prior key preparation incomplete; reconcile without regeneration')
 key=serialization.load_pem_private_key(read('private.pem'),password=None)
 receipt=json.loads(read('key-ready.json'))
else:
 if (root/'key-attempt.json').exists():raise RuntimeError('Prior key creation unknown; never regenerate')
 create('key-attempt.json',b'{"attempted":true}')
 key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
 create('private.pem',key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
 public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
 receipt={'fingerprint':hashlib.sha256(public).hexdigest()}
 create('key-ready.json',json.dumps(receipt).encode())
if not isinstance(key,rsa.RSAPrivateKey) or key.key_size!=3072:raise RuntimeError('Unexpected key type')
public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
fingerprint=hashlib.sha256(public).hexdigest()
if receipt['fingerprint']!=fingerprint:raise RuntimeError('Key receipt mismatch')
emit({'ok':True,'public_key':public.decode(),'fingerprint':fingerprint,'private_key_exported':False})
'''
REMOTE_PROBE=r'''
safe(root,True)
key=serialization.load_pem_private_key(read('private.pem'),password=None)
public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
fingerprint=hashlib.sha256(public).hexdigest()
if envelope.get('version')!=1 or envelope.get('fingerprint')!=fingerprint:raise RuntimeError('Envelope key mismatch')
wrapped=base64.b64decode(envelope['wrapped_key'],validate=True)
fernet_key=key.decrypt(wrapped,padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),algorithm=hashes.SHA256(),label=b'yx-restore-probe-v1'))
payload=json.loads(Fernet(fernet_key).decrypt(envelope['ciphertext'].encode(),ttl=300))
valid=payload=={'purpose':'transport_probe','nonce':'YX_NONSECRET_ENVELOPE_PROBE_20260930','service_id':'6abc0821454b8f31a5ef614a'}
emit({'ok':valid,'decrypted_nonce_matches':valid,'fingerprint':fingerprint,'private_key_exported':False})
'''


def remote(source):
    source="import json\ntry:\n"+textwrap.indent(source,' ') + "\nexcept Exception as exc:\n print('YX_RESTORE_ENVELOPE='+json.dumps({'ok':False,'error_class':type(exc).__name__}))\n"
    encoded=base64.b64encode(zlib.compress(source.encode())).decode()
    launcher='import base64,zlib;exec(zlib.decompress(base64.b64decode('+repr(encoded)+')))'
    binary=(str(Path(os.environ['APPDATA'])/'npm/node_modules/zeabur/zeabur_windows_amd64_v1/zeabur.exe') if os.name=='nt' else 'zeabur')
    cmd=[binary,'service','exec','--id',STAGING,'--env-id',ENV,'-i=false','--','python','-c',launcher]
    completed=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=90)
    results=[line.split(MARKER,1)[1] for line in completed.stdout.splitlines() if line.startswith(MARKER)]
    if completed.returncode or len(results)!=1:raise RuntimeError('Encrypted transport probe failed; remote output suppressed')
    data=json.loads(results[0])
    if data.get('ok') is not True:raise RuntimeError('Encrypted transport verification failed')
    return data


def _encrypt(public_pem,payload):
    key=serialization.load_pem_public_key(public_pem.encode())
    if not isinstance(key,rsa.RSAPublicKey) or key.key_size!=3072:raise RuntimeError('Unexpected public key')
    symmetric=Fernet.generate_key()
    encrypted=Fernet(symmetric).encrypt(json.dumps(payload).encode()).decode()
    wrapped=key.encrypt(symmetric,padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),algorithm=hashes.SHA256(),label=b'yx-restore-probe-v1'))
    return {'version':1,'fingerprint':hashlib.sha256(public_pem.encode()).hexdigest(),
            'wrapped_key':base64.b64encode(wrapped).decode(),'ciphertext':encrypted}


def envelope_for(public_pem):
    return _encrypt(public_pem,{'purpose':'transport_probe','nonce':NONCE,'service_id':STAGING})


def prepare():
    result=remote(REMOTE_COMMON+REMOTE_PREPARE)
    public=result['public_key'];key=serialization.load_pem_public_key(public.encode())
    if not isinstance(key,rsa.RSAPublicKey) or key.key_size!=3072 or hashlib.sha256(public.encode()).hexdigest()!=result['fingerprint']:
        raise RuntimeError('Invalid public key response')
    STATE.mkdir(parents=True,exist_ok=True);path=STATE/'envelope-public.json'
    if path.exists():
        old=json.loads(path.read_text(encoding='utf-8'))
        if old!=result:raise RuntimeError('Remote key changed; reconcile before accepting a new key')
    else:
        with path.open('x',encoding='utf-8') as out:json.dump(result,out)
    return {'ok':True,'step':'prepare','fingerprint':result['fingerprint'],'private_key_exported':False}


def probe():
    public=json.loads((STATE/'envelope-public.json').read_text(encoding='utf-8'))
    envelope=envelope_for(public['public_key'])
    if envelope['fingerprint']!=public['fingerprint']:raise RuntimeError('Stored public key mismatch')
    # Only encrypted data enters argv; no unencrypted configuration or credentials.
    source=REMOTE_COMMON+'\nenvelope='+repr(envelope)+'\n'+REMOTE_PROBE
    result=remote(source)
    if result.get('fingerprint')!=public['fingerprint'] or result.get('decrypted_nonce_matches') is not True:
        raise RuntimeError('Encrypted probe receipt mismatch')
    receipt={'ok':True,'step':'probe','fingerprint':result['fingerprint'],'decrypted_nonce_matches':True,'contains_credentials':False}
    (STATE/'envelope-probe.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    return receipt


REMOTE_DB_CHECK=r'''
safe(root,True)
key=serialization.load_pem_private_key(read('private.pem'),password=None)
public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
fingerprint=hashlib.sha256(public).hexdigest()
if envelope.get('version')!=1 or envelope.get('fingerprint')!=fingerprint:raise RuntimeError('Envelope key mismatch')
symmetric=key.decrypt(base64.b64decode(envelope['wrapped_key'],validate=True),padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),algorithm=hashes.SHA256(),label=b'yx-restore-probe-v1'))
payload=json.loads(Fernet(symmetric).decrypt(envelope['ciphertext'].encode(),ttl=300))
if set(payload)!={'purpose','service_id','database_url'} or payload['purpose']!='readonly_empty_database_check' or payload['service_id']!='6abce665454b8f31a5efc37e':raise RuntimeError('Unexpected database-check scope')
from sqlalchemy.engine import make_url
dsn=make_url(payload['database_url'])
if dsn.drivername!='postgresql+psycopg' or dsn.host!=expected_host or dsn.port!=5432 or dsn.database!='workbench_restore_drill' or dsn.username!='restore_drill':raise RuntimeError('Database identity mismatch')
if dict(dsn.query)!={'connect_timeout':'10','options':'-c default_transaction_read_only=on -c statement_timeout=15000'}:raise RuntimeError('Read-only connection required')
from scripts.backup_restore import engine_for,assert_empty_database
engine=engine_for(payload['database_url'])
try:
 assert_empty_database(engine)
finally:
 engine.dispose()
emit({'ok':True,'database_empty_verified':True,'restore_performed':False,'fingerprint':fingerprint})
'''


def database_config():
    # Resolve only the fixed service through authenticated provider inventory.
    try:from .workbench_restore_setup import inventory,PROJECT
    except ImportError:from workbench_restore_setup import inventory,PROJECT
    rows=inventory()
    matches=[r for r in rows if r.get('_id')==RESTORE or r.get('name')=='yongxiang-workbench-restore-drill']
    if len(matches)!=1 or matches[0].get('_id')!=RESTORE or matches[0].get('name')!='yongxiang-workbench-restore-drill':
        raise RuntimeError('Restore inventory identity mismatch')
    service=matches[0];dns=service.get('dnsName','')
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',dns):raise RuntimeError('Invalid private DNS identity')
    if any(r.get('_id')!=RESTORE and r.get('dnsName')==dns for r in rows):raise RuntimeError('Ambiguous private DNS identity')
    created=json.loads((STATE/'created.json').read_text(encoding='utf-8'))
    if created!={'service_id':RESTORE,'project_id':PROJECT,'environment_id':ENV}:raise RuntimeError('Restore creation receipt mismatch')
    private=json.loads((STATE/'secrets.json').read_text(encoding='utf-8'))
    if private.get('database_user')!='restore_drill' or private.get('database_name')!='workbench_restore_drill' or not isinstance(private.get('database_password'),str) or len(private['database_password'])<32:
        raise RuntimeError('Invalid isolated database credentials')
    from sqlalchemy.engine import URL
    host=dns+'.zeabur.internal'
    dsn=URL.create('postgresql+psycopg',username='restore_drill',password=private['database_password'],host=host,port=5432,database='workbench_restore_drill',query={'connect_timeout':'10','options':'-c default_transaction_read_only=on -c statement_timeout=15000'})
    return host,{'purpose':'readonly_empty_database_check','service_id':RESTORE,'database_url':dsn.render_as_string(hide_password=False)}


def db_check():
    host,payload=database_config()
    public=json.loads((STATE/'envelope-public.json').read_text(encoding='utf-8'))
    envelope=_encrypt(public['public_key'],payload)
    if envelope['fingerprint']!=public['fingerprint']:raise RuntimeError('Stored public key mismatch')
    source=REMOTE_COMMON+'\nexpected_host='+repr(host)+'\nenvelope='+repr(envelope)+'\n'+REMOTE_DB_CHECK
    result=remote(source)
    if result.get('fingerprint')!=public['fingerprint'] or result.get('database_empty_verified') is not True:raise RuntimeError('Database check receipt mismatch')
    receipt={'ok':True,'step':'db-check','service_id':RESTORE,'database_empty_verified':True,'restore_performed':False,'fingerprint':public['fingerprint']}
    (STATE/'envelope-db-check.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('step',choices=['prepare','probe','db-check'])
    step=parser.parse_args().step
    print(json.dumps({'prepare':prepare,'probe':probe,'db-check':db_check}[step]()))


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'ok':False,'error':str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__}))
        sys.exit(1)
