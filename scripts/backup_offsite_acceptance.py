"""One encrypted Drive roundtrip + EMPTY PostgreSQL drill; no retention.

Default is local preflight only. --execute uploads encrypted files and restores
into RESTORE_DRILL_DATABASE_URL. Never generates keys or modifies service env.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.backup_offsite import replicate, settings, backup_adapter
from scripts.backup_restore import validate_archive, engine_for, assert_empty_database
from scripts.restore_drill import validate_target, run as restore_drill


def preflight(source, directory, cfg):
    source = Path(source).resolve(strict=True)
    directory = Path(directory).resolve()
    if directory.exists():
        raise ValueError('Acceptance directory must be new; preserve earlier receipts')
    settings(cfg)
    validate_target(cfg['DATABASE_URL'], cfg['RESTORE_DRILL_DATABASE_URL'])
    if not all(cfg.get(k) for k in ('BACKUP_LARK_APP_ID','BACKUP_LARK_APP_SECRET','BACKUP_LARK_ORGANIZATION')) or cfg['BACKUP_LARK_APP_ID']==cfg.get('LARK_APP_ID'):
        raise ValueError('Independent backup application adapter is not configured')
    validate_archive(source)
    return source, directory


def download_files(adapter, state, destination):
    """Recover only remotely fetched ciphertext; never copy encryption staging."""
    from backend.lark_adapter import API
    destination = Path(destination)
    destination.mkdir(exist_ok=False)
    manifest = None
    for item in state['files']:
        name = item['name']
        if Path(name).name != name or '/' in name or '\\' in name:
            raise ValueError('Unsafe encrypted filename')
        response = adapter.client.get(API + '/drive/v1/files/' + quote(item['token'], safe='') + '/download',
                                      headers={'Authorization': 'Bearer ' + adapter.token}, follow_redirects=True)
        if response.status_code != 200 or hashlib.sha256(response.content).hexdigest() != item['sha256']:
            raise ValueError('Remote ciphertext download checksum mismatch')
        target = destination / name
        with target.open('xb') as output:
            output.write(response.content)
        if name.endswith('-manifest.fernet'):
            if manifest is not None:
                raise ValueError('Multiple encrypted manifests')
            manifest = target
    if manifest is None:
        raise ValueError('Encrypted manifest missing')
    return manifest


def execute(source, directory, cfg):
    # Direct callers receive the same guards as the CLI. Reject a populated
    # drill database before publishing any remote files; restore checks again
    # later because this read is not a lock on the target database.
    source, directory = preflight(source, directory, cfg)
    engine = engine_for(cfg['RESTORE_DRILL_DATABASE_URL'])
    try:
        assert_empty_database(engine)
    finally:
        engine.dispose()
    directory.mkdir(parents=True, exist_ok=False)
    adapter = backup_adapter(cfg)
    try:
        result = replicate(source, directory / 'encrypted', cfg, adapter)
        checkpoints = list((directory / 'encrypted').glob('*/receipt.json'))
        if len(checkpoints) != 1:
            raise ValueError('Expected one encrypted bundle checkpoint')
        state = json.loads(checkpoints[0].read_text(encoding='utf-8'))
        manifest = download_files(adapter, state, directory / 'downloaded')
    finally:
        adapter.client.close()
    # Existing drill validates the target and compares all rows and attachments.
    restored = restore_drill(manifest, directory / 'restored-uploads', directory / 'restore-receipt.json', encrypted=True, cfg=cfg)
    if restored['source_sha256'] != state['source_sha256']:
        raise ValueError('Downloaded recovery does not match original snapshot')
    receipt = {'ok': True, 'encrypted_offsite': result['status'] == 'verified',
               'downloaded_files': len(state['files']), 'downloaded_ciphertext_only': True,
               'postgresql_rows_equal': restored['rows_equal'], 'attachments_equal': restored['attachments_equal'],
               'source_sha256': restored['source_sha256'], 'retention_run': False}
    with (directory / 'acceptance-receipt.json').open('x', encoding='utf-8') as handle:
        json.dump(receipt, handle, indent=2)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', required=True, type=Path)
    parser.add_argument('--directory', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    try:
        source, directory = preflight(args.file, args.directory, os.environ)
        result = execute(source, directory, os.environ) if args.execute else {
            'ok': True, 'local_preflight_only': True, 'remote_or_database_access': False,
            'note': 'Empty target DB, mount, key custody and current ACL still require operator evidence'}
        print(json.dumps(result))
    except Exception as exc:
        print(json.dumps({'ok': False, 'error_type': type(exc).__name__}))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
