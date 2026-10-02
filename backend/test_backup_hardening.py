import errno
import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
import pytest
from scripts import backup_offsite as offsite,backup_schedule as schedule,backup_publish,backup_reconcile
from .test_backup_offsite import cfg,Drive
from .test_backup_safety import source as fixture_source


def test_no_hardlinks_uses_atomic_publication_and_never_overwrites(tmp_path,monkeypatch):
    temporary=tmp_path/'complete.tmp';temporary.write_bytes(b'complete')
    target=tmp_path/'published'
    def unsupported(*args):raise OSError(errno.ENOTSUP,'unsupported')
    monkeypatch.setattr(backup_publish.os,'link',unsupported)
    backup_publish.publish(temporary,target)
    assert target.read_bytes()==b'complete'
    temporary.write_bytes(b'replacement')
    with pytest.raises(FileExistsError):backup_publish.publish(temporary,target)
    assert target.read_bytes()==b'complete'


def test_verified_bundle_frees_chunks_and_can_reverify_without_upload(tmp_path):
    source=tmp_path/'yx-daily-2026-09-30.zip';source.write_bytes(b'evidence')
    directory=tmp_path/'encrypted';drive=Drive();settings=cfg()
    offsite.replicate(source,directory,settings,drive)
    assert not list(directory.rglob('*.fernet'))
    checkpoint=next(directory.rglob('receipt.json'))
    state=json.loads(checkpoint.read_text());state['verified_at']='2026-01-01T00:00:00+00:00'
    checkpoint.write_text(json.dumps(state))
    offsite.replicate(source,directory,settings,drive)
    assert drive.uploads==2 and not list(directory.rglob('*.fernet'))


def test_reconcile_recovers_lost_receipt_without_remote_write(tmp_path):
    source=tmp_path/'yx-daily-2026-09-30.zip';source.write_bytes(b'evidence')
    directory=tmp_path/'encrypted';drive=Drive();settings=cfg();drive.fail_after_upload=True
    with pytest.raises(TimeoutError):offsite.replicate(source,directory,settings,drive)
    checkpoint=next(directory.rglob('receipt.json'));before=checkpoint.read_bytes()
    result=backup_reconcile.reconcile(checkpoint,settings,drive)
    assert result['can_resume_without_unknown'] and checkpoint.read_bytes()==before
    assert drive.uploads==1 and drive.deleted==[]
    backup_reconcile.reconcile(checkpoint,settings,drive,True)
    assert json.loads(checkpoint.read_text())['files'][0]['token']=='token0'
    offsite.replicate(source,directory,settings,drive)
    assert drive.uploads==2


def test_reconcile_absence_never_clears_attempted_or_uploads(tmp_path):
    source=tmp_path/'snapshot.zip';source.write_bytes(b'evidence');settings=cfg();drive=Drive()
    bundle,state=offsite.prepare(source,tmp_path/'encrypted',settings)
    state['files'][0]['attempted']=True;checkpoint=bundle/'receipt.json';checkpoint.write_text(json.dumps(state))
    result=backup_reconcile.reconcile(checkpoint,settings,drive,True)
    assert not result['can_resume_without_unknown']
    assert json.loads(checkpoint.read_text())['files'][0]['attempted'] is True
    assert drive.uploads==0 and drive.deleted==[]


@pytest.mark.parametrize('credentials',[{}, {'BACKUP_LARK_APP_ID':'production','BACKUP_LARK_APP_SECRET':'s','BACKUP_LARK_ORGANIZATION':'o'}])
def test_backup_credentials_never_fall_back_to_production(credentials,monkeypatch):
    from backend import lark_adapter
    monkeypatch.setattr(lark_adapter,'application_adapter',lambda cfg:pytest.fail('must not acquire production credentials'))
    with pytest.raises(ValueError,match='Independent'):offsite.backup_adapter({'LARK_APP_ID':'production',**credentials})


def test_remote_deletion_disabled_by_default(tmp_path):
    settings=cfg();settings.pop('BACKUP_REMOTE_PRUNE_ENABLED');drive=Drive()
    assert offsite.prune(tmp_path,settings,drive,datetime.now(timezone.utc))==0
    assert drive.deleted==[]


def test_same_day_tick_skips_database_hashing_and_credentials(tmp_path,monkeypatch):
    engine,uploads=fixture_source(tmp_path)
    destination=tmp_path/'backups'
    monkeypatch.setenv('DATABASE_URL',str(engine.url));monkeypatch.setenv('UPLOAD_DIR',str(uploads))
    monkeypatch.setenv('BACKUP_DIR',str(destination));monkeypatch.delenv('BACKUP_OFFSITE_ENABLED',raising=False)
    clock=datetime(2026,9,30,tzinfo=timezone.utc)
    schedule.tick(clock)
    original=json.loads((destination/'status.json').read_text())
    monkeypatch.setattr(schedule,'engine_for',lambda cfg:pytest.fail('unchanged snapshot should not open database'))
    monkeypatch.setattr(schedule,'validate_archive',lambda path:pytest.fail('unchanged snapshot should not hash files'))
    schedule.tick(clock+timedelta(minutes=1))
    current=json.loads((destination/'status.json').read_text())
    assert current['last_full_checked_at']==original['last_full_checked_at']
    assert current['last_checked_at']==(clock+timedelta(minutes=1)).isoformat()
    engine.dispose()


def test_capacity_limit_stops_new_snapshots_without_erasing_unknown_bundles(tmp_path,monkeypatch):
    destination=tmp_path/'backups';destination.mkdir()
    unknown=destination/'unknown.fernet';unknown.write_bytes(b'uncertain')
    monkeypatch.setenv('BACKUP_DIR',str(destination));monkeypatch.setenv('UPLOAD_DIR',str(tmp_path/'uploads'))
    monkeypatch.setenv('BACKUP_MAX_LOCAL_BYTES','1')
    monkeypatch.setattr(schedule,'engine_for',lambda cfg:pytest.fail('capacity check must precede DB access'))
    with pytest.raises(ValueError,match='capacity'):schedule.tick(datetime(2026,9,30,tzinfo=timezone.utc))
    assert unknown.read_bytes()==b'uncertain'
    assert json.loads((destination/'status.json').read_text())['offsite']['status']=='capacity_blocked'
