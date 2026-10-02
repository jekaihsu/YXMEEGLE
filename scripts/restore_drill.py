"""Restore into a separately provisioned EMPTY PostgreSQL database and verify it.

DATABASE_URL identifies production only for the safety comparison. The script
never connects to it. RESTORE_DRILL_DATABASE_URL is the empty drill database.
Keep the target web/worker stopped. No database or resource is created/deleted.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
from zipfile import ZipFile
from sqlalchemy.engine import make_url

try:
    from .backup_restore import backup, restore, engine_for, TABLES
except ImportError:
    from backup_restore import backup, restore, engine_for, TABLES


def validate_target(production, target):
    original=make_url(production); drill=make_url(target)
    if not drill.drivername.startswith(('postgresql','postgres')):
        raise ValueError('Restore drill requires PostgreSQL')
    # Intentionally conservative: even a different host must use a distinct DB
    # name. This avoids accidental service/host aliases of the production DB.
    if not drill.database or drill.database==original.database or drill.database in ('postgres','template0','template1'):
        raise ValueError('Use a separately named empty drill database')


def database_payload(path):
    with ZipFile(path) as archive: rows=json.loads(archive.read('database.json'))
    for table in TABLES: rows.setdefault(table.name,[])
    return {name:sorted(json.dumps(row,sort_keys=True,ensure_ascii=False,separators=(',',':')) for row in values) for name,values in rows.items()}


def run(source,uploads,receipt,encrypted=False,cfg=None):
    cfg=os.environ if cfg is None else cfg
    production=cfg['DATABASE_URL']; target=cfg['RESTORE_DRILL_DATABASE_URL']
    validate_target(production,target)
    receipt=Path(receipt).resolve()
    if receipt.exists(): raise ValueError('Receipt already exists')
    receipt.parent.mkdir(parents=True,exist_ok=True)
    roundtrip=receipt.with_name('drill-roundtrip-'+secrets.token_hex(8)+'.zip')
    decrypted=None
    if encrypted:
        try:from .backup_offsite import decrypt_bundle
        except ImportError:from backup_offsite import decrypt_bundle
        decrypted=receipt.with_name('drill-decrypted-'+secrets.token_hex(8)+'.zip')
        decrypt_bundle(source,decrypted,cfg)
        source=decrypted
    engine=None
    try:
        engine=engine_for(target)
        restored=restore(engine,uploads,source)
        backup(engine,uploads,roundtrip)
        if database_payload(source)!=database_payload(roundtrip): raise ValueError('Restored table contents differ')
        with ZipFile(source) as original,ZipFile(roundtrip) as replay:
            before=json.loads(original.read('manifest.json'))['sha256']
            after=json.loads(replay.read('manifest.json'))['sha256']
        attachments=lambda values:{k:v for k,v in values.items() if k.startswith('uploads/')}
        if attachments(before)!=attachments(after): raise ValueError('Restored attachments differ')
        result={'ok':True,'database':'postgresql','rows_equal':True,'attachments_equal':True,
                'source_sha256':hashlib.sha256(Path(source).read_bytes()).hexdigest(),**restored}
        with receipt.open('x',encoding='utf-8') as handle: json.dump(result,handle,ensure_ascii=False,indent=2)
        return result
    finally:
        if engine is not None:engine.dispose()
        roundtrip.unlink(missing_ok=True)
        if decrypted:decrypted.unlink(missing_ok=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file',required=True)
    parser.add_argument('--uploads',required=True)
    parser.add_argument('--receipt',required=True)
    parser.add_argument('--encrypted-manifest',action='store_true',help='--file is a downloaded encrypted manifest beside its encrypted chunks')
    args=parser.parse_args()
    # Connection errors can contain DB addresses; emit only a safe error class.
    try: print(json.dumps(run(args.file,args.uploads,args.receipt,args.encrypted_manifest)))
    except Exception as exc:
        print(json.dumps({'ok':False,'error_type':type(exc).__name__}))
        raise SystemExit(1)
