import hashlib
import json
from datetime import datetime, timezone
from zipfile import ZipFile

import pytest
from sqlalchemy import Column, MetaData, String, Table, create_engine, select

from scripts import backup_restore as br
from scripts import backup_schedule as schedule
from scripts.restore_drill import validate_target


def source(tmp_path, *, attachment=True):
    engine=create_engine('sqlite:///'+str(tmp_path/'source.db'))
    br.META.create_all(engine)
    uploads=tmp_path/'uploads'; uploads.mkdir()
    files=[]
    if attachment:
        folder=uploads/hashlib.sha256(b'company').hexdigest(); folder.mkdir()
        (folder/'file_one').write_bytes(b'company evidence')
        files=[{'id':'file_one','storage':'local','size':16}]
    with engine.begin() as db:
        db.execute(br.TABLES[0].insert(),{'id':'company','version':3,'data':{'projects':[{'id':'p1','files':files}]}})
        db.execute(br.TABLES[-1].insert(),{'id':'audit1','workspace_id':'company','actor_id':'owner','action':'file_upload','created_at':'2026-09-28','data':{'outcome':'success'}})
    return engine,uploads


def test_backup_failure_does_not_publish_partial_archive(tmp_path):
    engine,uploads=source(tmp_path)
    next(uploads.rglob('file_one')).unlink()
    target=tmp_path/'backup.zip'
    with pytest.raises(ValueError,match='missing'):
        br.backup(engine,uploads,target)
    assert not target.exists()
    assert not list(tmp_path.glob('*.partial-*'))


def test_backup_is_exclusive_and_ignores_uncommitted_files(tmp_path):
    engine,uploads=source(tmp_path)
    (uploads/'uncommitted').write_bytes(b'in flight')
    target=tmp_path/'backup.zip'
    assert br.backup(engine,uploads,target)['files']==1
    original=target.read_bytes()
    with pytest.raises(ValueError,match='already exists'):
        br.backup(engine,uploads,target)
    assert target.read_bytes()==original
    with ZipFile(target) as archive:
        assert all('uncommitted' not in name for name in archive.namelist())


def test_restore_preserves_audit_and_attachment_bytes(tmp_path):
    engine,uploads=source(tmp_path)
    target=tmp_path/'backup.zip'; br.backup(engine,uploads,target)
    restored=create_engine('sqlite:///'+str(tmp_path/'restored.db'))
    output=tmp_path/'restored-uploads'
    result=br.restore(restored,output,target)
    assert result['tables']['action_audit']==1
    assert result['sessions_restored'] is False
    assert next(output.rglob('file_one')).read_bytes()==b'company evidence'
    with restored.connect() as db:
        assert db.execute(select(br.TABLES[-1].c.data)).scalar_one()=={'outcome':'success'}


def test_restore_rejects_live_session_only_target(tmp_path):
    engine,uploads=source(tmp_path,attachment=False)
    target=tmp_path/'backup.zip'; br.backup(engine,uploads,target)
    restored=create_engine('sqlite:///'+str(tmp_path/'restored.db'))
    metadata=MetaData()
    auth=Table('auth_sessions',metadata,Column('id',String,primary_key=True))
    metadata.create_all(restored)
    with restored.begin() as db: db.execute(auth.insert(),{'id':'active-session'})
    with pytest.raises(ValueError,match='must be empty'):
        br.restore(restored,tmp_path/'restored-uploads',target)
    with restored.connect() as db: assert db.execute(select(auth.c.id)).scalar_one()=='active-session'


@pytest.mark.parametrize('failure_stage', ['settings', 'credentials'])
def test_offsite_early_failure_replaces_previous_green_status(tmp_path, monkeypatch, failure_stage):
    from scripts import backup_offsite
    from backend import lark_adapter
    engine, uploads = source(tmp_path)
    destination = tmp_path / 'backups'
    destination.mkdir()
    (destination / 'status.json').write_text(json.dumps({'status': 'ok', 'offsite': {'status': 'verified'}}))
    retained = destination / 'yx-daily-2020-01-01.zip'
    retained.write_bytes(b'old backup must not be pruned on failure')
    monkeypatch.setenv('DATABASE_URL', str(engine.url))
    monkeypatch.setenv('UPLOAD_DIR', str(uploads))
    monkeypatch.setenv('BACKUP_DIR', str(destination))
    monkeypatch.setenv('BACKUP_OFFSITE_ENABLED', 'true')
    def failure(*args):
        raise ValueError('Private failure details must not appear in status')
    def unexpected_adapter(*args):
        pytest.fail('Settings failure must stop before acquiring credentials')
    monkeypatch.setattr(backup_offsite, 'settings', failure if failure_stage == 'settings' else lambda cfg: None)
    monkeypatch.setattr(lark_adapter, 'application_adapter', unexpected_adapter if failure_stage == 'settings' else failure)
    with pytest.raises(ValueError):
        schedule.tick(datetime(2026, 9, 29, tzinfo=timezone.utc))
    status = json.loads((destination / 'status.json').read_text())
    assert status['status'] == 'error' and status['offsite']['status'] == 'error'
    assert 'Private' not in json.dumps(status)
    assert not retained.exists()
    assert br.validate_archive(destination/'yx-daily-2026-09-29.zip')
    engine.dispose()


def test_schedule_repairs_monthly_and_keeps_snapshot_age(tmp_path,monkeypatch):
    engine,uploads=source(tmp_path)
    destination=tmp_path/'backups'
    monkeypatch.setenv('DATABASE_URL',str(engine.url))
    monkeypatch.setenv('UPLOAD_DIR',str(uploads))
    monkeypatch.setenv('BACKUP_DIR',str(destination))
    clock=datetime(2026,9,28,4,tzinfo=timezone.utc)
    schedule.tick(clock)
    initial=json.loads((destination/'status.json').read_text())
    monthly=destination/'yx-monthly-2026-09.zip'; monthly.write_bytes(b'broken')
    later=clock.replace(hour=5)
    schedule.tick(later)
    assert br.validate_archive(monthly)['schema']=='yx-workspace-backup/3'
    assert len(list(destination.glob('*.invalid-*')))==1
    current=json.loads((destination/'status.json').read_text())
    assert current['last_success_at']==initial['last_success_at']
    assert current['last_checked_at']==later.isoformat()


@pytest.mark.parametrize('target',[
    'postgresql://user@alias/company',
    'postgresql://user@host/postgres',
    'postgresql://user@host/template1',
    'sqlite:///empty.db',
])
def test_pg_drill_rejects_production_alias_and_unsafe_targets(target):
    with pytest.raises(ValueError): validate_target('postgresql://user@host/company',target)


def test_pg_drill_accepts_separately_named_postgresql_database():
    validate_target('postgresql://user@host/company','postgresql+psycopg://user@host/yx_restore_20260928')
