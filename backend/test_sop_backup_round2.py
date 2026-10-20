from sqlalchemy import create_engine, event, select

from .app import create_app
from .sop_import.models import LocalTask, TaskNodeLink, TaskEvent, LocalCaseRun, ImportRun, Version
from .test_sop_local_case import local, create, FORM
from .test_sop_quotes import WID
from scripts import backup_restore as br


def test_sop_backup_restore_survives_startup(local, tmp_path):
    app, client, _, _ = local
    _, receipt = create(client, FORM)
    archive = tmp_path / 'backup.zip'
    br.backup(app.state.engine, tmp_path / 'files', archive)
    url = f'sqlite:///{tmp_path}/restored.db'
    target = create_engine(url)
    @event.listens_for(target, 'connect')
    def fk(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')
    result = br.restore(target, tmp_path / 'restored-files', archive)
    assert result['tables'].get('sop_local_tasks') == 38
    target.dispose()
    restored = create_app({'DATABASE_URL': url, 'UPLOAD_DIR': str(tmp_path / 'restored-files'),
                           'DEMO_MODE': 'false', 'APP_ENV': 'development', 'SESSION_SECRET': 'restore-test' * 4})
    try:
        for model in (LocalTask, TaskNodeLink, TaskEvent, LocalCaseRun, ImportRun, Version):
            with app.state.engine.connect() as source, restored.state.engine.connect() as dest:
                before = list(source.execute(select(model.__table__)).mappings())
                after = list(dest.execute(select(model.__table__)).mappings())
                assert after == before
        with restored.state.sessions() as db:
            assert db.get(LocalCaseRun, (WID, 'r1')).receipt == receipt
    finally:
        restored.state.engine.dispose()


def test_old_archive_without_sop_tables_restores(local, tmp_path):
    import hashlib
    import json
    from zipfile import ZipFile
    app, _, _, _ = local
    archive = tmp_path / 'new.zip'
    br.backup(app.state.engine, tmp_path / 'files', archive)
    with ZipFile(archive) as source:
        manifest = json.loads(source.read('manifest.json'))
        rows = {k: v for k, v in json.loads(source.read('database.json')).items() if not k.startswith('sop_')}
    data = json.dumps(rows).encode()
    manifest['tables'] = {k: len(v) for k, v in rows.items()}
    manifest['sha256'] = {'database.json': hashlib.sha256(data).hexdigest()}
    old = tmp_path / 'old.zip'
    with ZipFile(old, 'w') as dest:
        dest.writestr('manifest.json', json.dumps(manifest))
        dest.writestr('database.json', data)
    engine = create_engine(f'sqlite:///{tmp_path}/old.db')
    try:
        result = br.restore(engine, tmp_path / 'old-files', old)
        assert result['tables']['sop_local_tasks'] == 0
        br.assert_schema(engine)
    finally:
        engine.dispose()
