import hashlib
import json
from zipfile import ZipFile

import pytest
from sqlalchemy import create_engine, select

from scripts import backup_live_legacy as live
from scripts import backup_restore


@pytest.fixture
def source(tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'source.sqlite'))
    live.META.create_all(engine)
    uploads = tmp_path / 'uploads'
    path = uploads / hashlib.sha256(b'w1').hexdigest() / 'f1'
    path.parent.mkdir(parents=True)
    path.write_bytes(b'complete')
    with engine.begin() as connection:
        connection.execute(live.TABLES[0].insert(), {'id': 'w1', 'version': 7, 'data': {'projects': [{'files': [{'id': 'f1', 'storage': 'local', 'size': 8}]}]}})
        connection.execute(live.TABLES[1].insert(), {'id': 'r1', 'fingerprint': 'hash', 'result': {'version': 7}})
    yield engine, uploads, path, tmp_path / 'backup.zip'
    engine.dispose()


def test_snapshot_references_only_and_restore_to_empty_database(source, tmp_path):
    engine, uploads, path, target = source
    (path.parent / 'incomplete-orphan').write_bytes(b'partial')
    result = live.backup(engine, uploads, target)
    assert result['files'] == 1 and result['tables']['workspaces'] == 1
    restored = create_engine('sqlite:///' + str(tmp_path / 'restore.sqlite'))
    try:
        outcome = backup_restore.restore(restored, tmp_path / 'restored-uploads', target)
        assert outcome['files'] == 1
        with restored.connect() as connection:
            row = connection.execute(select(backup_restore.TABLES[0])).mappings().one()
            assert row['version'] == 7 and row['data']['projects'][0]['files'][0]['id'] == 'f1'
        assert (tmp_path / 'restored-uploads' / path.relative_to(uploads)).read_bytes() == b'complete'
    finally:
        restored.dispose()


@pytest.mark.parametrize('failure', ['missing', 'wrong_size', 'traversal', 'bad_size', 'symlink'])
def test_attachment_inconsistency_aborts_without_partial_archive(source, failure, monkeypatch):
    engine, uploads, path, target = source
    if failure == 'missing':
        path.unlink()
    elif failure == 'wrong_size':
        path.write_bytes(b'partial')
    elif failure == 'symlink':
        original = live.Path.is_symlink
        monkeypatch.setattr(live.Path, 'is_symlink', lambda p: p == path or original(p))
    else:
        with engine.begin() as connection:
            data = {'projects': [{'files': [{'id': '../outside' if failure == 'traversal' else 'f1', 'storage': 'local', 'size': '8' if failure == 'bad_size' else 8}]}]}
            connection.execute(live.TABLES[0].update().values(data=data))
    with pytest.raises(ValueError):
        live.backup(engine, uploads, target)
    assert not target.exists()


def test_new_schema_is_rejected_and_existing_archive_untouched(source):
    engine, uploads, path, target = source
    target.write_bytes(b'existing')
    with pytest.raises(ValueError):
        live.backup(engine, uploads, target)
    assert target.read_bytes() == b'existing'
    target.unlink()
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE business_records (id TEXT)')
    with pytest.raises(ValueError, match='legacy backup'):
        live.backup(engine, uploads, target)
    assert not target.exists()


def test_concurrent_unreferenced_file_is_never_opened(source, monkeypatch):
    engine, uploads, path, target = source
    original = live.snapshot
    def snapshot_then_new_upload(engine):
        result = original(engine)
        (path.parent / 'new-upload').write_bytes(b'in-progress')
        return result
    monkeypatch.setattr(live, 'snapshot', snapshot_then_new_upload)
    live.backup(engine, uploads, target)
    with ZipFile(target) as archive:
        assert not any('new-upload' in name for name in archive.namelist())
        manifest = json.loads(archive.read('manifest.json'))
        assert all(hashlib.sha256(archive.read(name)).hexdigest() == digest for name, digest in manifest['sha256'].items())


def test_postgresql_snapshot_uses_repeatable_read_and_read_only():
    calls = []
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execution_options(self, **kwargs): calls.append(kwargs); return self
        def begin(self): return self
        def exec_driver_sql(self, command): calls.append(command); raise RuntimeError('stop before query')
    class Engine:
        dialect = type('Dialect', (), {'name': 'postgresql'})()
        def connect(self): return Connection()
    with pytest.raises(RuntimeError): live.snapshot(Engine())
    assert calls == [{'isolation_level': 'REPEATABLE READ'}, 'SET TRANSACTION READ ONLY']
