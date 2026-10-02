"""Authenticated encryption and resumable Drive copies of immutable backups.

Keys and the independently restricted destination are deployment settings only.
This module never imports the application or starts its worker.
"""
import hashlib
import json
import os
import re
import secrets
from pathlib import Path
from datetime import datetime,timezone
from datetime import timedelta
from urllib.parse import quote
from cryptography.fernet import Fernet,MultiFernet
try:
    from .backup_publish import publish
except ImportError:
    from backup_publish import publish

CHUNK_BYTES=8*1024*1024


def backup_adapter(cfg):
    """Never fall back to the application that operates production workflows."""
    from backend.lark_adapter import application_adapter
    keys=('BACKUP_LARK_APP_ID','BACKUP_LARK_APP_SECRET','BACKUP_LARK_ORGANIZATION')
    if not all(cfg.get(k) for k in keys) or cfg['BACKUP_LARK_APP_ID']==cfg.get('LARK_APP_ID'):
        raise ValueError('Independent backup credentials are required')
    return application_adapter({'LARK_APP_ID':cfg[keys[0]],'LARK_APP_SECRET':cfg[keys[1]],
        'LARK_WORKER_ORGANIZATION':cfg[keys[2]],'LARK_WORKER_IDENTITY':'application'})


def cipher(cfg):
    raw=json.loads(cfg.get('BACKUP_ENCRYPTION_KEYS_JSON','[]'))
    if not isinstance(raw,list) or not raw or not all(isinstance(k,str) for k in raw):
        raise ValueError('Backup encryption keys are not configured')
    return MultiFernet([Fernet(k.encode()) for k in raw])


def settings(cfg):
    root=cfg.get('BACKUP_DRIVE_ROOT_TOKEN')
    if not root or root!=cfg.get('BACKUP_DRIVE_ALLOWED_ROOT') or not re.fullmatch(r'[A-Za-z0-9_-]+',root):
        raise ValueError('Independent backup destination is not allowlisted')
    if cfg.get('BACKUP_DRIVE_PRIVATE_ROOT_VERIFIED')!='true':
        raise ValueError('Backup destination access review is required')
    if root in {cfg.get('LARK_DRIVE_ROOT'),cfg.get('LARK_TEST_DRIVE_ROOT'),cfg.get('LARK_DRIVE_ROOT_TOKEN'),cfg.get('LARK_DRIVE_FOLDER_TOKEN')}:
        raise ValueError('Backup destination must be separate from deliverables')
    return root,cipher(cfg)


def atomic_json(path,value):
    temp=path.with_name(path.name+'.partial-'+secrets.token_hex(6))
    try:
        with temp.open('x',encoding='utf-8') as handle:
            json.dump(value,handle,separators=(',',':'));handle.flush();os.fsync(handle.fileno())
        temp.replace(path)
    finally:temp.unlink(missing_ok=True)


def exclusive(path,data):
    temp=path.with_name(path.name+'.partial-'+secrets.token_hex(6))
    try:
        with temp.open('xb') as handle:handle.write(data);handle.flush();os.fsync(handle.fileno())
        publish(temp,path)
    finally:temp.unlink(missing_ok=True)


def prepare(source,directory,cfg):
    source=Path(source);directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    root,encryptor=settings(cfg)
    with source.open('rb') as handle:digest=hashlib.file_digest(handle,'sha256').hexdigest()
    bundle=directory/(source.stem+'-'+digest[:16]);bundle.mkdir(exist_ok=True)
    checkpoint=bundle/'receipt.json'
    if checkpoint.exists():
        state=json.loads(checkpoint.read_text())
        if state['source_sha256']!=digest or state['root']!=root:raise ValueError('Backup checkpoint does not match destination')
        return bundle,state
    manifest={'format':'yx-encrypted-backup/1','source_sha256':digest,'source_size':source.stat().st_size,'chunks':[]}
    files=[];observed=hashlib.sha256();observed_size=0
    with source.open('rb') as handle:
        while data:=handle.read(CHUNK_BYTES):
            observed.update(data);observed_size+=len(data)
            name=f'{bundle.name}-{len(files):05d}.fernet';path=bundle/name
            # Resume a process interrupted during staging without replacing any
            # previously encrypted bytes that could already have been uploaded.
            if not path.exists():exclusive(path,encryptor.encrypt(data))
            token=path.read_bytes()
            if encryptor.decrypt(token)!=data:raise ValueError('Encrypted chunk validation failed')
            item={'name':name,'sha256':hashlib.sha256(token).hexdigest(),'plain_sha256':hashlib.sha256(data).hexdigest()}
            manifest['chunks'].append(item);files.append({'name':name,'sha256':item['sha256']})
    if observed.hexdigest()!=digest or observed_size!=manifest['source_size']:raise ValueError('Backup changed during encryption')
    name=bundle.name+'-manifest.fernet';path=bundle/name
    serialized=json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()
    if not path.exists():exclusive(path,encryptor.encrypt(serialized))
    if encryptor.decrypt(path.read_bytes())!=serialized:raise ValueError('Encrypted manifest mismatch')
    files.append({'name':name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    state={'root':root,'source_sha256':digest,'label':source.stem,'files':files,'status':'prepared'}
    atomic_json(checkpoint,state)
    return bundle,state


def listing(adapter,root):
    result=[];cursor=None;seen=set()
    for _ in range(1000):
        params={'folder_token':root,'page_size':200}
        if cursor:params['page_token']=cursor
        page=adapter.request('GET','/drive/v1/files',params=params)
        if not isinstance(page.get('files'),list) or not isinstance(page.get('has_more'),bool):raise ValueError('Incomplete Drive listing')
        result.extend(page['files'])
        if not page['has_more']:return result
        cursor=page.get('next_page_token')
        if not cursor or cursor in seen:raise ValueError('Incomplete Drive pagination')
        seen.add(cursor)
    raise ValueError('Drive listing limit exceeded')


def replicate(source,directory,cfg,adapter):
    bundle,state=prepare(source,directory,cfg);checkpoint=bundle/'receipt.json'
    root,encryptor=settings(cfg)
    if state.get('status')=='verified':
        try:
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(state['verified_at'])).total_seconds()
            if 0<=age<86400:return {'status':'verified','verified_at':state['verified_at'],'encrypted':True,'files':len(state['files'])}
        except (KeyError,ValueError,TypeError):pass
    current=listing(adapter,root)
    for item in state['files']:
        path=bundle/item['name']
        if path.is_symlink() or not path.resolve().is_relative_to(bundle.resolve()):raise ValueError('Unsafe backup chunk')
        matches=[f for f in current if f.get('name')==item['name'] and f.get('type')=='file' and f.get('parent_token')==root]
        if len(matches)>1:raise ValueError('Duplicate backup files require review')
        if item.get('token'):
            if not matches or matches[0]['token']!=item['token']:raise ValueError('Stored backup destination changed')
        elif matches:item['token']=matches[0]['token']
        elif item.get('attempted'):
            raise ValueError('Backup upload outcome unknown; verify before retry')
        else:
            data=path.read_bytes()
            if hashlib.sha256(data).hexdigest()!=item['sha256']:raise ValueError('Staged encrypted backup checksum mismatch')
            encryptor.decrypt(data)  # Never transmit unverified/plaintext staging.
            item['attempted']=True;atomic_json(checkpoint,state)
            uploaded=adapter.upload(bundle/item['name'],root,item['name'])
            item['token']=uploaded['file_token'];atomic_json(checkpoint,state)
        adapter.verify_file(item['token'],item['sha256'])
        item['verified']=True;atomic_json(checkpoint,state)
    state.update(status='verified',verified_at=datetime.now(timezone.utc).isoformat())
    atomic_json(checkpoint,state)
    for item in state['files']:
        path=bundle/item['name']
        if path.is_symlink() or not path.resolve().is_relative_to(bundle.resolve()):raise ValueError('Unsafe backup chunk')
        path.unlink(missing_ok=True)
    return {'status':'verified','verified_at':state['verified_at'],'encrypted':True,'files':len(state['files'])}


def decrypt_bundle(manifest_path,output,cfg):
    """Offline recovery; files are downloaded separately, never start worker."""
    encryptor=cipher(cfg);manifest_path=Path(manifest_path);output=Path(output)
    manifest=json.loads(encryptor.decrypt(manifest_path.read_bytes()))
    if manifest.get('format')!='yx-encrypted-backup/1':raise ValueError('Unsupported encrypted backup')
    if output.exists():raise ValueError('Recovery output must not exist')
    temp=output.with_name(output.name+'.partial-'+secrets.token_hex(6));digest=hashlib.sha256();size=0
    try:
        with temp.open('xb') as handle:
            for item in manifest['chunks']:
                if Path(item['name']).name!=item['name'] or '/' in item['name'] or '\\' in item['name']:raise ValueError('Unsafe encrypted chunk path')
                path=manifest_path.parent/item['name']
                if path.is_symlink():raise ValueError('Encrypted chunk symlinks refused')
                token=path.read_bytes()
                if hashlib.sha256(token).hexdigest()!=item['sha256']:raise ValueError('Encrypted chunk hash mismatch')
                data=encryptor.decrypt(token)
                if hashlib.sha256(data).hexdigest()!=item['plain_sha256']:raise ValueError('Decrypted chunk hash mismatch')
                digest.update(data);size+=len(data);handle.write(data)
            handle.flush();os.fsync(handle.fileno())
        if digest.hexdigest()!=manifest['source_sha256'] or size!=manifest['source_size']:raise ValueError('Restored archive checksum mismatch')
        publish(temp,output)
    finally:temp.unlink(missing_ok=True)
    return {'sha256':digest.hexdigest(),'bytes':size}


def prune(directory,cfg,adapter,clock):
    """Delete only receipt-owned verified backup files still in this root."""
    if cfg.get('BACKUP_REMOTE_PRUNE_ENABLED')!='true':return 0
    root,_=settings(cfg);current={f['token']:f for f in listing(adapter,root)}
    keep_months={f'{(clock.year*12+clock.month-1-i)//12:04d}-{(clock.year*12+clock.month-1-i)%12+1:02d}' for i in range(12)}
    removed=0
    for path in Path(directory).glob('*/receipt.json'):
        if path.is_symlink() or path.parent.is_symlink():continue
        state=json.loads(path.read_text());label=state.get('label','')
        if state.get('root')!=root or state.get('status') not in ('verified','deleting'):continue
        expired=False
        if re.fullmatch(r'yx-daily-\d{4}-\d{2}-\d{2}',label):
            expired=datetime.strptime(label[9:],'%Y-%m-%d').date()<(clock-timedelta(days=29)).date()
        elif re.fullmatch(r'yx-monthly-\d{4}-\d{2}',label):
            datetime.strptime(label[11:],'%Y-%m')
            expired=label[11:]<min(keep_months)
        if not expired:continue
        state['status']='deleting';atomic_json(path,state)
        for item in state['files']:
            token=item.get('token');remote=current.get(token)
            if item.get('deleted'):continue
            if remote:
                if remote.get('parent_token')!=root or remote.get('name')!=item['name'] or remote.get('type')!='file':
                    raise ValueError('Backup retention ownership mismatch')
                if item.get('delete_attempted'):
                    raise ValueError('Backup deletion outcome unknown; verify before retry')
                item['delete_attempted']=True;atomic_json(path,state)
                adapter.request('DELETE','/drive/v1/files/'+quote(token,safe=''),params={'type':'file'})
                # A success response may only acknowledge asynchronous deletion.
                # Keep local recovery bytes until a complete listing confirms absence.
                if any(f.get('token')==token for f in listing(adapter,root)):
                    raise ValueError('Backup deletion pending; verify before retry')
            item['deleted']=True;atomic_json(path,state)
        state['status']='deleted';atomic_json(path,state);removed+=1
        for item in state['files']:
            chunk=path.parent/item['name']
            if chunk.is_symlink() or not chunk.resolve().is_relative_to(path.parent.resolve()):
                raise ValueError('Unsafe local encrypted retention path')
            chunk.unlink(missing_ok=True)
    return removed
