"""Online backup for the audited legacy app's immutable, committed local files.

Read-only database access. Not a generic online backup for newer app versions.
Only snapshot-referenced attachments are included; any inconsistency aborts.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from zipfile import ZipFile, ZIP_DEFLATED

from sqlalchemy import create_engine, MetaData, Table, Column, String, Integer, JSON, select, inspect

META = MetaData()
TABLES = [
    Table('workspaces', META, Column('id', String(120), primary_key=True), Column('version', Integer), Column('data', JSON)),
    Table('receipts', META, Column('id', String(300), primary_key=True), Column('fingerprint', String(64)), Column('result', JSON)),
    Table('source_caches', META, Column('id', String(120), primary_key=True), Column('data', JSON)),
]


def engine_for(url):
    if url.startswith('postgres://'):
        url = 'postgresql+psycopg://' + url[len('postgres://'):]
    elif url.startswith('postgresql://'):
        url = 'postgresql+psycopg://' + url[len('postgresql://'):]
    return create_engine(url, pool_pre_ping=True)


def snapshot(engine):
    with engine.connect() as connection:
        if engine.dialect.name == 'postgresql':
            connection = connection.execution_options(isolation_level='REPEATABLE READ')
        with connection.begin():
            if engine.dialect.name == 'postgresql':
                connection.exec_driver_sql('SET TRANSACTION READ ONLY')
            available = set(inspect(connection).get_table_names())
            if available - {'workspaces', 'receipts', 'source_caches', 'auth_sessions'}:
                raise ValueError('Unexpected database tables; legacy backup is not applicable')
            return {table.name: [dict(row) for row in connection.execute(select(table)).mappings()] for table in TABLES}


def referenced_files(rows):
    refs = {}
    for row in rows['workspaces']:
        folder = hashlib.sha256(row['id'].encode()).hexdigest()
        for project in row['data'].get('projects', []):
            for item in project.get('files', []):
                if item.get('storage') != 'local':
                    continue
                ident, size = item.get('id'), item.get('size')
                if not isinstance(ident, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', ident):
                    raise ValueError('Invalid referenced attachment identifier')
                if type(size) is not int or size < 0:
                    raise ValueError('Invalid referenced attachment size')
                relative = folder + '/' + ident
                if relative in refs and refs[relative] != size:
                    raise ValueError('Conflicting attachment references')
                refs[relative] = size
    return refs


def read_attachment(root, relative, expected_size):
    path = root
    for part in Path(relative).parts:
        path = path / part
        if path.is_symlink():
            raise ValueError('Symlink attachment path is unsupported')
    if not path.resolve().is_relative_to(root) or not path.is_file():
        raise ValueError('Referenced attachment missing or unsafe')
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size != expected_size:
        raise ValueError('Referenced attachment size mismatch')
    with path.open('rb') as handle:
        opened = os.fstat(handle.fileno())
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError('Attachment changed before read')
        data = handle.read(expected_size + 1)
        after = os.fstat(handle.fileno())
    fingerprint = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
    if len(data) != expected_size or fingerprint(before) != fingerprint(after):
        raise ValueError('Attachment changed during read')
    return data


def backup(engine, uploads, target):
    source_root = Path(uploads).absolute()
    if any(p.is_symlink() for p in (source_root, *source_root.parents)):
        raise ValueError('Upload root cannot use symlinks')
    root, target = source_root.resolve(), Path(target).resolve()
    if target.is_relative_to(root) or target.exists():
        raise ValueError('Backup target must be new and outside uploads')
    rows = snapshot(engine)
    refs = referenced_files(rows)
    payload = json.dumps(rows, ensure_ascii=False, separators=(',', ':')).encode()
    manifest = {'schema': 'yx-workspace-backup/1', 'created_at': datetime.now(timezone.utc).isoformat(),
                'mode': 'legacy_snapshot_referenced_files', 'tables': {k: len(v) for k, v in rows.items()},
                'sha256': {'database.json': hashlib.sha256(payload).hexdigest()}}
    target.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        with target.open('xb') as output:
            created = True
            with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
                archive.writestr('database.json', payload)
                for relative, size in sorted(refs.items()):
                    data = read_attachment(root, relative, size)
                    name = 'uploads/' + relative
                    archive.writestr(name, data)
                    manifest['sha256'][name] = hashlib.sha256(data).hexdigest()
                archive.writestr('manifest.json', json.dumps(manifest))
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        return {'tables': manifest['tables'], 'files': len(refs), 'bytes': target.stat().st_size,
                'sha256': digest, 'sessions_restored': False}
    except Exception:
        if created:
            target.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uploads', required=True)
    parser.add_argument('--file', required=True)
    args = parser.parse_args()
    engine = engine_for(os.environ['DATABASE_URL'])
    try:
        print(json.dumps({'ok': True, **backup(engine, args.uploads, args.file)}))
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
