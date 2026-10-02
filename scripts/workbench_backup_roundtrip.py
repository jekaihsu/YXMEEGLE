"""Fixed encrypted backup roundtrip. Never restores a database or runs retention."""
import argparse
import hashlib
import json
from datetime import datetime,timezone
from pathlib import Path
import sys
from cryptography.fernet import Fernet

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.backup_offsite import backup_adapter,replicate,decrypt_bundle,atomic_json
from scripts.backup_offsite_acceptance import download_files
from scripts.backup_restore import validate_archive

STATE=ROOT/'.runtime/workbench-backup-roundtrip'
APP='cli_aa361fea3678de13'
FOLDER='S6lqfyItLlr42OdCidWjgkLEpic'
SERVICE='6ab61834a4c05a5bcb57ad69'

def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def fresh(value):
    instant=datetime.fromisoformat(value.replace('Z','+00:00'))
    if instant.tzinfo is None or not 0<=(datetime.now(timezone.utc)-instant).total_seconds()<=3600:
        raise ValueError('Fresh timestamp required')
def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def prepare_key():
    STATE.mkdir(parents=True,exist_ok=True);path=STATE/'key-private.json'
    if not path.exists():
        key=Fernet.generate_key().decode('ascii')
        # Exclusive create, never rotate silently or overwrite a prior key.
        with path.open('x',encoding='utf-8') as handle:
            json.dump({'key':key,'fingerprint':hashlib.sha256(key.encode()).hexdigest(),
                'custodian':'jekai','custody_confirmed':False},handle)
            handle.flush();__import__('os').fsync(handle.fileno())
    data=read(path);Fernet(data['key'].encode())
    if hashlib.sha256(data['key'].encode()).hexdigest()!=data['fingerprint']:raise ValueError('Key fingerprint mismatch')
    return {'ok':True,'key_fingerprint':data['fingerprint'],'custodian':'jekai','custody_confirmed':False}

def configuration():
    cfg=read(ROOT/'.runtime/backup-independent-app-private.json')
    if cfg.get('BACKUP_LARK_APP_ID')!=APP:raise ValueError('Wrong backup app')
    proof=read(ROOT/'.runtime/workbench-backup-setup/folder-verified.json');fresh(proof['observed_at'])
    if (proof.get('ok') is not True or proof.get('app_id')!=APP or proof.get('folder')!=FOLDER
        or proof.get('independent_app_listing_verified') is not True or proof.get('public_unchanged') is not True
        or proof.get('public',{}).get('external_access_entity')!='closed'
        or proof.get('public',{}).get('link_share_entity')!='closed'):raise ValueError('Folder evidence invalid')
    key=read(STATE/'key-private.json');Fernet(key['key'].encode())
    if digest_key(key)!=key.get('fingerprint'):raise ValueError('Key fingerprint mismatch')
    cfg.update(BACKUP_ENCRYPTION_KEYS_JSON=json.dumps([key['key']]),BACKUP_DRIVE_ROOT_TOKEN=FOLDER,
        BACKUP_DRIVE_ALLOWED_ROOT=FOLDER,BACKUP_DRIVE_PRIVATE_ROOT_VERIFIED='true')
    return cfg

def digest_key(key):return hashlib.sha256(key['key'].encode()).hexdigest()

def source():
    receipt=read(ROOT/'.runtime/workbench-snapshot/receipt.json');fresh(receipt['observed_at'])
    if receipt.get('source_service_id')!=SERVICE:raise ValueError('Wrong snapshot service')
    path=Path(receipt['archive_path']).resolve(strict=True)
    if not path.is_relative_to((ROOT/'.runtime/workbench-snapshot').resolve()) or path.is_symlink():raise ValueError('Snapshot path outside fixed directory')
    if digest(path)!=receipt.get('sha256'):raise ValueError('Snapshot checksum mismatch')
    validate_archive(path)
    return path,receipt

def upload():
    cfg=configuration();path,receipt=source();pin=STATE/'source-pin.json'
    if pin.exists():
        if read(pin)!=receipt:raise ValueError('Pinned snapshot changed; preserve existing checkpoint')
    else:
        with pin.open('x',encoding='utf-8') as handle:json.dump(receipt,handle)
    adapter=backup_adapter(cfg)
    try:result=replicate(path,STATE/'encrypted',cfg,adapter)
    finally:adapter.client.close()
    checkpoints=list((STATE/'encrypted').glob('*/receipt.json'))
    if len(checkpoints)!=1:raise ValueError('Ambiguous upload checkpoint')
    state=read(checkpoints[0])
    if state.get('status')!='verified' or state.get('source_sha256')!=receipt['sha256']:raise ValueError('Upload not verified')
    result={'ok':True,'encrypted_upload_verified':True,'source_sha256':receipt['sha256'],
        'app_id':APP,'folder':FOLDER,'remote_retention':False,'database_restore_verified':False}
    atomic_json(STATE/'upload-receipt.json',result);return result

def download():
    cfg=configuration();uploaded=read(STATE/'upload-receipt.json');pin=read(STATE/'source-pin.json')
    checkpoints=list((STATE/'encrypted').glob('*/receipt.json'))
    if len(checkpoints)!=1:raise ValueError('Ambiguous upload checkpoint')
    state=read(checkpoints[0])
    if (uploaded.get('source_sha256')!=pin['sha256'] or state.get('source_sha256')!=pin['sha256']
        or state.get('status')!='verified' or state.get('root')!=FOLDER):raise ValueError('Unverified upload receipt')
    if (STATE/'roundtrip-receipt.json').exists():return read(STATE/'roundtrip-receipt.json')
    adapter=backup_adapter(cfg)
    try:manifest=download_files(adapter,state,STATE/'downloaded-ciphertext')
    finally:adapter.client.close()
    restored=STATE/'downloaded-local-validation.zip'
    try:
        decrypt_bundle(manifest,restored,cfg)
        if digest(restored)!=pin['sha256']:raise ValueError('Downloaded backup differs')
        validate_archive(restored)
    finally:restored.unlink(missing_ok=True)
    result={'ok':True,'source_sha256':pin['sha256'],'downloaded_ciphertext_only':True,
        'decrypted_archive_hash_equal':True,'archive_valid':True,'database_restore_verified':False,
        'remote_retention':False,'custody_confirmed':False,'observed_at':datetime.now(timezone.utc).isoformat()}
    atomic_json(STATE/'roundtrip-receipt.json',result);return result

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['prepare-key','upload','download'])
    args=parser.parse_args()
    try:print(json.dumps({'prepare-key':prepare_key,'upload':upload,'download':download}[args.command]()))
    except Exception as exc:print(json.dumps({'ok':False,'error_type':type(exc).__name__}));sys.exit(1)
if __name__=='__main__':main()
