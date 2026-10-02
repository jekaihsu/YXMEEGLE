from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from .runtime_health import snapshot, register

NOW=datetime(2026,9,28,12,tzinfo=timezone.utc)


def sessions(data=None,*,fail=False):
    @contextmanager
    def factory():
        if fail: raise RuntimeError('credential must never appear')
        yield SimpleNamespace(get=lambda model,key:SimpleNamespace(data=data) if data is not None else None)
    return factory


def backup(tmp_path,**values):
    data={'status':'ok','last_success_at':(NOW-timedelta(hours=12)).isoformat(),
          'last_checked_at':NOW.isoformat(),'daily':'private-filename','secret':'do not expose',
          'offsite':{'status':'verified','encrypted':True,'last_verified_at':NOW.isoformat()}}
    data.update(values)
    (tmp_path/'status.json').write_text(json.dumps(data),encoding='utf-8')
    return {'BACKUP_DIR':str(tmp_path)}


def test_current_status_uses_real_snapshot_age_and_exposes_no_paths(tmp_path):
    data={'status':'ok','at':NOW.isoformat(),'last_success_at':(NOW-timedelta(seconds=20)).isoformat(),
          'stage':'private-stage','error_type':'credential'}
    result=snapshot(sessions(data),object,backup(tmp_path),now=NOW)
    assert result['status']=='attention'  # Missing directory proof cannot be green.
    assert result['worker']['status']=='ok' and result['backup']['status']=='ok'
    assert result['worker']['success_age_seconds']==20
    assert result['backup']['success_age_seconds']==12*3600
    encoded=json.dumps(result)
    assert all(value not in encoded for value in (str(tmp_path),'private-filename','private-stage','credential','do not expose'))
    assert result['external_integrations_verified'] is False
    assert result['backup_archive_verified_by_this_request'] is False


def test_missing_configuration_and_worker_are_explicit():
    result=snapshot(sessions(),object,{},now=NOW)
    assert result['status']=='attention'
    assert result['worker']['status']=='missing'
    assert result['backup']['status']=='not_configured'


def test_recent_heartbeat_does_not_hide_old_worker_success():
    result=snapshot(sessions({'status':'running','at':NOW.isoformat(),
                             'last_success_at':(NOW-timedelta(hours=1)).isoformat()}),object,{},now=NOW)
    assert result['worker']['status']=='stale'


def test_backup_recent_check_does_not_hide_old_snapshot(tmp_path):
    result=snapshot(sessions(),object,backup(tmp_path,last_success_at=(NOW-timedelta(days=2)).isoformat()),now=NOW)
    assert result['backup']['status']=='stale'


@pytest.mark.parametrize('value',['2026-09-28T12:00:00','not-a-time','2026-09-29T12:00:00Z'])
def test_untrusted_timestamps_cannot_claim_success(tmp_path,value):
    result=snapshot(sessions({'status':'ok','at':value,'last_success_at':value}),object,
                    backup(tmp_path,last_success_at=value),now=NOW)
    assert result['worker']['status']=='invalid'
    assert result['backup']['status']=='invalid'


def test_corrupt_status_and_db_error_do_not_leak_details(tmp_path):
    (tmp_path/'status.json').write_text('{secretbroken',encoding='utf-8')
    result=snapshot(sessions(fail=True),object,{'BACKUP_DIR':str(tmp_path)},now=NOW)
    assert result['worker']['status']=='unavailable'
    assert result['backup']['status']=='invalid'
    assert 'secret' not in json.dumps(result)


@pytest.mark.parametrize('mode,wid,role,active',[
    ('demo','lark-company','manager',True),('lark','test-lark-company','manager',True),
    ('lark','lark-other','manager',True),('lark','lark-company','member',True),
    ('lark','lark-company','manager',False),
])
def test_route_denies_nonformal_manager_without_reading_health(mode,wid,role,active):
    app=FastAPI()
    def never_read(): raise AssertionError('unauthorized caller must not read health')
    register(app,lambda request:({'mode':mode,'wid':wid},{'role':role,'active':active}),
             never_read,object,{'LARK_WORKER_ORGANIZATION':'company'})
    assert TestClient(app).get('/api/admin/runtime-health').status_code==403


def test_formal_manager_route_is_readonly_and_not_cacheable():
    app=FastAPI()
    register(app,lambda request:({'mode':'lark','wid':'lark-company'},{'role':'manager','active':True}),
             sessions(),object,{'LARK_WORKER_ORGANIZATION':'company'})
    client=TestClient(app); response=client.get('/api/admin/runtime-health')
    assert response.status_code==200
    assert response.headers['cache-control']=='no-store'
    assert response.json()['worker']['status']=='missing'
    assert client.post('/api/admin/runtime-health').status_code==405


def test_bootstrap_recovery_can_read_health_from_own_test_context_only():
    app=FastAPI();user={'role':'manager','active':True,'bootstrap_admin':True,'identity_app_id':'app'}
    register(app,lambda request:({'mode':'lark','wid':'test-lark-company','organization':'lark-company'},user),
             sessions(),object,{'LARK_WORKER_ORGANIZATION':'company','LARK_APP_ID':'app'})
    assert TestClient(app).get('/api/admin/runtime-health').status_code==200


def test_local_backup_never_claims_verified_offsite(tmp_path):
    result=snapshot(sessions(),object,backup(tmp_path,offsite={}),now=NOW)
    assert result['backup']['status']=='local_only'
