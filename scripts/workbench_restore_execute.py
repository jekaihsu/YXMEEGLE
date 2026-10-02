"""One fixed isolated restore, via encrypted staging exec. No arbitrary payloads.

Local receipts pin the latest snapshot and previously verified Drive roundtrip.
Unknown remote outcomes are only reconciled using status; never retried/reset.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from sqlalchemy.engine import make_url
try:
    from . import workbench_restore_envelope as transport
    from . import workbench_backup_roundtrip as roundtrip
except ImportError:
    import workbench_restore_envelope as transport
    import workbench_backup_roundtrip as roundtrip

STATE=transport.STATE
RECEIPT_FIELDS={'ok','service_id','source_sha256','postgresql_rows_equal','attachments_equal',
                'downloaded_ciphertext_only','restore_performed','retention_run','fingerprint'}
HELPERS=('scripts/backup_restore.py','scripts/backup_publish.py','scripts/restore_drill.py',
         'scripts/backup_offsite.py','scripts/backup_offsite_acceptance.py','backend/lark_adapter.py')


def verified_receipt(result,expected):
    if any(result.get(k)!=expected[k] for k in ('service_id','source_sha256','fingerprint')) or any(result.get(k) is not True for k in ('ok','postgresql_rows_equal','attachments_equal','restore_performed')):
        raise RuntimeError('Restore receipt mismatch')
    return {k:v for k,v in result.items() if k in RECEIPT_FIELDS}
REMOTE_RESTORE=r'''
safe(root,True)
for name,expected_digest in expected_helpers.items():
 helper=Path('/app',name)
 if not helper.is_file() or helper.is_symlink() or hashlib.sha256(helper.read_bytes()).hexdigest()!=expected_digest:raise RuntimeError('Reviewed restore helper differs')
key=serialization.load_pem_private_key(read('private.pem'),password=None)
public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
fingerprint=hashlib.sha256(public).hexdigest()
if envelope.get('version')!=1 or envelope.get('fingerprint')!=fingerprint:raise RuntimeError('Envelope identity mismatch')
symmetric=key.decrypt(base64.b64decode(envelope['wrapped_key'],validate=True),padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),algorithm=hashes.SHA256(),label=b'yx-restore-probe-v1'))
payload=json.loads(Fernet(symmetric).decrypt(envelope['ciphertext'].encode(),ttl=300))
if set(payload)!={'purpose','service_id','database_url','backup_config','checkpoint','source_sha256'} or payload['purpose']!='fixed_isolated_restore' or payload['service_id']!='6abce665454b8f31a5efc37e':raise RuntimeError('Unexpected restore scope')
from sqlalchemy.engine import make_url
url=make_url(payload['database_url'])
if url.drivername!='postgresql+psycopg' or url.host!=expected_host or url.port!=5432 or url.database!='workbench_restore_drill' or url.username!='restore_drill' or dict(url.query)!={'connect_timeout':'10'}:raise RuntimeError('Restore target mismatch')
original=os.environ.get('DATABASE_URL','')
if not original or make_url(original).host==url.host:raise RuntimeError('Cannot restore to active application database')
cfg=payload['backup_config']
if cfg.get('BACKUP_LARK_APP_ID')!='cli_aa361fea3678de13' or cfg.get('BACKUP_DRIVE_ROOT_TOKEN')!='S6lqfyItLlr42OdCidWjgkLEpic' or cfg.get('BACKUP_DRIVE_ALLOWED_ROOT')!='S6lqfyItLlr42OdCidWjgkLEpic':raise RuntimeError('Backup app or folder mismatch')
checkpoint=payload['checkpoint']
if checkpoint.get('status')!='verified' or checkpoint.get('root')!='S6lqfyItLlr42OdCidWjgkLEpic' or checkpoint.get('source_sha256')!=payload['source_sha256']:raise RuntimeError('Backup checkpoint mismatch')
from scripts.backup_restore import engine_for,assert_empty_database,validate_archive
from scripts.backup_offsite import backup_adapter,decrypt_bundle
from scripts.backup_offsite_acceptance import download_files
from scripts.restore_drill import run as restore_run,validate_target
cfg.update(DATABASE_URL=original,RESTORE_DRILL_DATABASE_URL=payload['database_url'])
validate_target(original,payload['database_url'])
# Exclusive attempt precedes any download/restore. A partial prior run blocks.
create('restore-attempt.json',json.dumps({'source_sha256':payload['source_sha256'],'service_id':payload['service_id']}).encode())
work=root/'restore-work';work.mkdir(mode=0o700);safe(work,True)
engine=engine_for(payload['database_url'])
try:assert_empty_database(engine)
finally:engine.dispose()
adapter=backup_adapter(cfg)
try:manifest=download_files(adapter,checkpoint,work/'ciphertext')
finally:adapter.client.close()
decrypted=work/'verified-source.zip'
try:
 decrypt_bundle(manifest,decrypted,cfg)
 with decrypted.open('rb') as source:actual=hashlib.file_digest(source,'sha256').hexdigest()
 if actual!=payload['source_sha256']:raise RuntimeError('Snapshot hash differs before restore')
 validate_archive(decrypted)
 restored=restore_run(decrypted,work/'uploads',work/'drill-receipt.json',encrypted=False,cfg=cfg)
finally:decrypted.unlink(missing_ok=True)
if restored.get('rows_equal') is not True or restored.get('attachments_equal') is not True or restored.get('source_sha256')!=payload['source_sha256']:raise RuntimeError('Restore verification mismatch')
result={'ok':True,'service_id':payload['service_id'],'source_sha256':payload['source_sha256'],'postgresql_rows_equal':True,'attachments_equal':True,'downloaded_ciphertext_only':True,'restore_performed':True,'retention_run':False,'fingerprint':fingerprint}
create('restore-success.json',json.dumps(result).encode())
emit(result)
'''
REMOTE_STATUS=r'''
safe(root,True)
if (root/'restore-success.json').exists():
 value=json.loads(read('restore-success.json'))
 emit({'ok':True,'status':'verified','receipt':{k:v for k,v in value.items() if k in ('ok','service_id','source_sha256','postgresql_rows_equal','attachments_equal','downloaded_ciphertext_only','restore_performed','retention_run','fingerprint')}})
else:
 emit({'ok':True,'status':'outcome_unknown' if (root/'restore-attempt.json').exists() else 'not_attempted','restore_performed':False,'retry_authorized':False})
'''


def configuration():
    check=json.loads((STATE/'envelope-db-check.json').read_text(encoding='utf-8'))
    if check.get('service_id')!=transport.RESTORE or check.get('database_empty_verified') is not True:raise RuntimeError('Prior database preflight missing')
    path,snapshot=roundtrip.source()
    pin=roundtrip.read(roundtrip.STATE/'source-pin.json')
    uploaded=roundtrip.read(roundtrip.STATE/'upload-receipt.json')
    downloaded=roundtrip.read(roundtrip.STATE/'roundtrip-receipt.json')
    if pin!=snapshot:raise RuntimeError('Latest snapshot differs from pinned roundtrip')
    for receipt in (uploaded,downloaded):
        if receipt.get('ok') is not True or receipt.get('source_sha256')!=snapshot['sha256']:raise RuntimeError('Roundtrip snapshot mismatch')
    if uploaded.get('encrypted_upload_verified') is not True or downloaded.get('decrypted_archive_hash_equal') is not True or downloaded.get('archive_valid') is not True:raise RuntimeError('Roundtrip verification incomplete')
    checkpoints=list((roundtrip.STATE/'encrypted').glob('*/receipt.json'))
    if len(checkpoints)!=1:raise RuntimeError('Ambiguous encrypted checkpoint')
    checkpoint=roundtrip.read(checkpoints[0])
    if checkpoint.get('status')!='verified' or checkpoint.get('source_sha256')!=snapshot['sha256'] or checkpoint.get('root')!=roundtrip.FOLDER:raise RuntimeError('Checkpoint mismatch')
    cfg=roundtrip.configuration()
    allowed={'BACKUP_LARK_APP_ID','BACKUP_LARK_APP_SECRET','BACKUP_LARK_ORGANIZATION','BACKUP_ENCRYPTION_KEYS_JSON','BACKUP_DRIVE_ROOT_TOKEN','BACKUP_DRIVE_ALLOWED_ROOT','BACKUP_DRIVE_PRIVATE_ROOT_VERIFIED'}
    cfg={k:v for k,v in cfg.items() if k in allowed}
    host,db=transport.database_config()
    target=make_url(db['database_url']).set(query={'connect_timeout':'10'})
    payload={'purpose':'fixed_isolated_restore','service_id':transport.RESTORE,'database_url':target.render_as_string(hide_password=False),
             'backup_config':cfg,'checkpoint':checkpoint,'source_sha256':snapshot['sha256']}
    return host,payload


def restore():
    if (STATE/'restore-dispatch-attempt.json').exists():raise RuntimeError('Prior dispatch exists; use status only, never blindly restore again')
    host,payload=configuration()
    public=json.loads((STATE/'envelope-public.json').read_text(encoding='utf-8'))
    envelope=transport._encrypt(public['public_key'],payload)
    if envelope['fingerprint']!=public['fingerprint']:raise RuntimeError('Pinned key mismatch')
    helpers={name:hashlib.sha256((transport.ROOT/name).read_bytes()).hexdigest() for name in HELPERS}
    source=transport.REMOTE_COMMON+'\nexpected_helpers='+repr(helpers)+'\nexpected_host='+repr(host)+'\nenvelope='+repr(envelope)+'\n'+REMOTE_RESTORE
    with (STATE/'restore-dispatch-attempt.json').open('x',encoding='utf-8') as out:
        json.dump({'service_id':transport.RESTORE,'source_sha256':payload['source_sha256'],'fingerprint':public['fingerprint']},out)
    result=transport.remote(source)
    result=verified_receipt(result,{'source_sha256':payload['source_sha256'],'service_id':transport.RESTORE,'fingerprint':public['fingerprint']})
    (STATE/'restore-verified.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


def status():
    result=transport.remote(transport.REMOTE_COMMON+REMOTE_STATUS)
    if result.get('status')=='verified':
        expected=json.loads((STATE/'restore-dispatch-attempt.json').read_text(encoding='utf-8'))
        receipt=verified_receipt(result['receipt'],expected)
        result['receipt']=receipt
        (STATE/'restore-verified.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    return result


def cleanup_transport():
    expected=json.loads((STATE/'restore-verified.json').read_text(encoding='utf-8'))
    verified_receipt(expected,expected)
    source=transport.REMOTE_COMMON+'\nexpected='+repr(expected)+r'''
safe(root,True)
receipt=json.loads(read('restore-success.json'))
if any(receipt.get(k)!=expected[k] for k in ('service_id','source_sha256','fingerprint')) or receipt.get('postgresql_rows_equal') is not True or receipt.get('attachments_equal') is not True:
 raise RuntimeError('Successful restore evidence required before cleanup')
private=root/'private.pem'
if private.exists():
 safe(private,False)
 private.unlink()
emit({'ok':True,'transport_private_key_removed':not private.exists(),'backup_recovery_key_unchanged':True})
'''
    result=transport.remote(source)
    (STATE/'transport-cleanup.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['restore','status','cleanup-transport'])
    args=parser.parse_args()
    print(json.dumps({'restore':restore,'status':status,'cleanup-transport':cleanup_transport}[args.command]()))


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'ok':False,'error_type':type(exc).__name__}));sys.exit(1)
