import hashlib
from types import SimpleNamespace
import pytest
from scripts import backup_offsite_acceptance as acceptance


def adapter_for(content, status=200):
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        return SimpleNamespace(status_code=status, content=content)
    return SimpleNamespace(token='local-test-token', client=SimpleNamespace(get=get)), calls


def test_download_uses_remote_bytes_in_new_recovery_directory(tmp_path):
    remote = b'remote encrypted bytes'
    adapter, calls = adapter_for(remote)
    state = {'files': [{'name': 'acceptance-manifest.fernet', 'token': 'file1',
                       'sha256': hashlib.sha256(remote).hexdigest()}]}
    output = acceptance.download_files(adapter, state, tmp_path / 'downloaded')
    assert output.read_bytes() == remote
    assert len(calls) == 1 and calls[0].endswith('/file1/download')
    with pytest.raises(FileExistsError):
        acceptance.download_files(adapter, state, tmp_path / 'downloaded')


@pytest.mark.parametrize('status,content', [(200, b'corrupted'), (403, b'expected')])
def test_failed_remote_download_never_publishes_ciphertext(tmp_path, status, content):
    adapter, _ = adapter_for(content, status)
    state = {'files': [{'name': 'acceptance-manifest.fernet', 'token': 'file1',
                       'sha256': hashlib.sha256(b'expected').hexdigest()}]}
    with pytest.raises(ValueError, match='checksum'):
        acceptance.download_files(adapter, state, tmp_path / 'downloaded')
    assert not list((tmp_path / 'downloaded').iterdir())


def test_preflight_rejects_production_database_before_output_or_network(tmp_path, monkeypatch):
    source = tmp_path / 'snapshot.zip'
    source.write_bytes(b'not opened before safety check')
    monkeypatch.setattr(acceptance, 'settings', lambda cfg: None)
    cfg = {'DATABASE_URL': 'postgresql://local/workspace',
           'RESTORE_DRILL_DATABASE_URL': 'postgresql://different-host/workspace'}
    with pytest.raises(ValueError, match='separately named'):
        acceptance.preflight(source, tmp_path / 'acceptance', cfg)
    assert not (tmp_path / 'acceptance').exists()


def test_execute_rejects_live_session_target_before_drive_or_output(tmp_path, monkeypatch):
    from sqlalchemy import create_engine, text
    from backend import lark_adapter
    engine = create_engine('sqlite:///' + str(tmp_path / 'live.db'))
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE auth_sessions (id TEXT PRIMARY KEY)'))
        connection.execute(text("INSERT INTO auth_sessions VALUES ('existing-session')"))
    source = tmp_path / 'snapshot.zip'
    destination = tmp_path / 'acceptance'
    monkeypatch.setattr(acceptance, 'preflight', lambda *args: (source, destination))
    monkeypatch.setattr(acceptance, 'engine_for', lambda url: engine)
    def unexpected_adapter(cfg):
        pytest.fail('Drive credentials must not be acquired for a populated target')
    monkeypatch.setattr(lark_adapter, 'application_adapter', unexpected_adapter)
    with pytest.raises(ValueError, match='must be empty'):
        acceptance.execute(source, destination, {'RESTORE_DRILL_DATABASE_URL': 'postgresql://host/drill'})
    assert not destination.exists()
    with engine.connect() as connection:
        assert connection.execute(text('SELECT id FROM auth_sessions')).scalar_one() == 'existing-session'
    engine.dispose()


def test_drill_explicit_config_controls_both_keys_and_target(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from scripts import backup_restore, backup_offsite, restore_drill
    from .test_backup_safety import source as fixture_source
    from .test_backup_offsite import cfg as encryption_config
    source_engine, uploads = fixture_source(tmp_path)
    archive = tmp_path / 'backup.zip'
    backup_restore.backup(source_engine, uploads, archive)
    cfg = encryption_config()
    cfg.update(DATABASE_URL='postgresql://host/company', RESTORE_DRILL_DATABASE_URL='postgresql://host/approved_drill')
    bundle, state = backup_offsite.prepare(archive, tmp_path / 'encrypted', cfg)
    # Ambient environment deliberately names production and supplies no key.
    monkeypatch.setenv('DATABASE_URL', 'postgresql://host/company')
    monkeypatch.setenv('RESTORE_DRILL_DATABASE_URL', 'postgresql://host/company')
    monkeypatch.setenv('BACKUP_ENCRYPTION_KEYS_JSON', '[]')
    drill_engine = create_engine('sqlite:///' + str(tmp_path / 'drill.db'))
    calls = []
    def selected_engine(url):
        calls.append(url)
        return drill_engine
    monkeypatch.setattr(restore_drill, 'engine_for', selected_engine)
    result = restore_drill.run(bundle / state['files'][-1]['name'], tmp_path / 'restored',
                               tmp_path / 'receipt.json', encrypted=True, cfg=cfg)
    assert calls == [cfg['RESTORE_DRILL_DATABASE_URL']]
    assert result['rows_equal'] and result['attachments_equal']
    assert result['source_sha256'] == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert not list(tmp_path.glob('drill-decrypted-*'))
    source_engine.dispose()
