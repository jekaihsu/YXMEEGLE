"""Exercise real local child lifecycles without starting the app or connecting out."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from scripts import deploy_prepare, run_service


ROOT=Path(__file__).resolve().parents[1]


def alive(pid):
    if os.name=='nt':
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong]
        kernel.OpenProcess.restype=ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
        kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        handle=kernel.OpenProcess(0x00100000,False,pid)
        if not handle: return False
        try: return kernel.WaitForSingleObject(handle,0)==0x00000102
        finally: kernel.CloseHandle(handle)
    try: os.kill(pid,0); return True
    except ProcessLookupError: return False


def long_lived(marker):
    script="import os,sys,time; from pathlib import Path; Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(120)"
    return [sys.executable,'-c',script,str(marker)]


def harness(commands):
    script="import json,sys; from scripts.run_service import supervise; sys.exit(supervise(json.loads(sys.argv[1]),shutdown_timeout=1,poll_interval=0.02))"
    return subprocess.run([sys.executable,'-c',script,json.dumps(commands)],cwd=ROOT,capture_output=True,text=True,timeout=12)


@pytest.mark.parametrize('exit_code',[0,7])
def test_unexpected_child_exit_fails_service_and_reaps_other_child(tmp_path,exit_code):
    marker=tmp_path/'web.pid'
    script="import sys,time; from pathlib import Path\nfor _ in range(200):\n if Path(sys.argv[1]).exists(): break\n time.sleep(0.02)\nsys.exit(int(sys.argv[2]))"
    result=harness([('web',long_lived(marker)),('worker',[sys.executable,'-c',script,str(marker),str(exit_code)])])
    assert result.returncode==(exit_code or 1),result.stdout+result.stderr
    assert marker.exists() and not alive(int(marker.read_text()))
    assert 'worker status=' in result.stdout


def test_failed_child_start_cleans_up_already_started_child(tmp_path):
    result=harness([('web',long_lived(tmp_path/'web.pid')),('worker',[str(tmp_path/'missing-executable')])])
    assert result.returncode==1
    first=next(line for line in result.stdout.splitlines() if 'child started: web pid=' in line)
    assert not alive(int(first.split('pid=')[1]))


def test_requested_shutdown_stops_both_real_children(tmp_path):
    stop=threading.Event(); first=tmp_path/'one.pid'; second=tmp_path/'two.pid'
    observed=[]
    def request_stop():
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            if first.exists() and second.exists():
                observed.extend([int(first.read_text()),int(second.read_text())]); break
            time.sleep(0.02)
        stop.set()
    thread=threading.Thread(target=request_stop,daemon=True); thread.start()
    code=run_service.supervise([('web',long_lived(first)),('worker',long_lived(second))],stop_event=stop,shutdown_timeout=1,poll_interval=0.02)
    thread.join(timeout=2)
    assert code==0 and len(observed)==2
    assert all(not alive(pid) for pid in observed)


def test_worker_starts_only_after_web_readiness(tmp_path):
    marker=tmp_path/'schema-ready'
    first="import sys,time; from pathlib import Path; time.sleep(0.3); Path(sys.argv[1]).write_text('ready'); time.sleep(120)"
    second="import sys; from pathlib import Path; sys.exit(7 if Path(sys.argv[1]).exists() else 3)"
    code=run_service.supervise([('web',[sys.executable,'-c',first,str(marker)]),('worker',[sys.executable,'-c',second,str(marker)])],readiness={'web':marker.exists},startup_timeout=2,shutdown_timeout=1,poll_interval=0.01)
    assert code==7


def test_startup_deadline_stops_web_without_launching_worker(tmp_path):
    first=tmp_path/'web.pid'; second=tmp_path/'worker.pid'
    code=run_service.supervise([('web',long_lived(first)),('worker',long_lived(second))],readiness={'web':lambda:False},startup_timeout=0.3,shutdown_timeout=1,poll_interval=0.01)
    assert code==1 and not second.exists()
    assert not first.exists() or not alive(int(first.read_text()))


def test_deployment_staging_includes_runtime_and_omits_credentials(tmp_path,monkeypatch):
    root=tmp_path/'root'; runtime=root/'.runtime'; runtime.mkdir(parents=True)
    paths=['Dockerfile','.dockerignore','backend/requirements.txt','backend/app.py','scripts/backup_restore.py','scripts/backup_live_legacy.py','scripts/run_service.py','scripts/run_worker.py','scripts/run_live_read.py','scripts/backup_schedule.py','frontend/package.json','frontend/package-lock.json','frontend/index.html','frontend/tsconfig.json','frontend/vite.config.ts','frontend/src/app.ts','frontend/public/logo.svg']
    paths.append('scripts/backup_offsite.py')
    paths.append('scripts/restore_drill.py')
    paths += ['backend/sop_source_contracts.json','backend/sop_import/catalog.json','backend/report_link_vocabulary.json','scripts/backup_publish.py',
              'scripts/backup_reconcile.py','scripts/backup_offsite_acceptance.py','backend/requirements.lock',
              'scripts/migrate_index_tables.py','scripts/backfill_index.py','scripts/migrate_ai_usage.py']
    for name in paths:
        path=root/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_text('source',encoding='utf-8')
    config=root/'deployment/source-tables.json'; config.parent.mkdir()
    config.write_text(json.dumps([dict(base_token='resource123',table_id='tbl123',kind='confirmation')]),encoding='utf-8')
    secret='never-stage-test-credential'
    for name in ('.env','.runtime/credentials.json','scripts/private_credentials.py','backend/test_private.py'):
        (root/name).write_text(secret,encoding='utf-8')
    monkeypatch.setattr(deploy_prepare,'ROOT',root); monkeypatch.setattr(deploy_prepare,'RUNTIME',runtime)
    monkeypatch.setattr(deploy_prepare,'build_identity',lambda _root:{'git_sha':'0'*40,'dirty':False,'built_at':'2026-10-26T00:00:00+00:00','branch':'test'})
    # This tests manifest boundaries using placeholder files. The independent
    # package smoke has its own real-package and missing-resource tests.
    from scripts import verify_stage_package
    monkeypatch.setattr(verify_stage_package,'verify_stage',lambda stage:{'ok':True})
    folder=deploy_prepare.staging()
    for name in ('scripts/run_service.py','scripts/run_worker.py','scripts/run_live_read.py','scripts/backup_schedule.py','scripts/backup_live_legacy.py','deployment/source-tables.json'):
        assert (folder/name).is_file()
    assert all(secret not in p.read_text(encoding='utf-8') for p in folder.rglob('*') if p.is_file())
    manifest=json.loads((runtime/'zeabur-stage-manifest.json').read_text())
    assert {f['path'] for f in manifest['files']}==set(paths)|{'deployment/source-tables.json','backend/build-manifest.json'}


def test_source_table_config_rejects_credential_keys_without_echoing_value(tmp_path):
    path=tmp_path/'source-tables.json'; secret='never-log-this-secret'
    path.write_text(json.dumps([dict(base_token='resource',table_id='table',kind='daily',access_token=secret)]))
    with pytest.raises(SystemExit) as exc: deploy_prepare.validate_source_tables(path)
    assert secret not in str(exc.value)


@pytest.mark.parametrize('enabled',[True,False])
def test_worker_once_gates_dataset_timers_but_keeps_jobs_and_heartbeat(tmp_path,monkeypatch,enabled):
    from types import SimpleNamespace
    from backend.app import create_app, WorkspaceRow, CacheRow
    from backend.seed import seed
    from scripts import run_worker
    app=create_app({'DATABASE_URL':f'sqlite:///{tmp_path}/worker.db','UPLOAD_DIR':str(tmp_path/'uploads'),
                    'DEMO_MODE':'true','LARK_LIVE_READ_ENABLED':str(enabled).lower()})
    with app.state.sessions.begin() as db: db.add(WorkspaceRow(id='demo-worker',version=1,data=seed()))
    calls=[]
    def service(name,method): return SimpleNamespace(**{method:lambda wid:calls.append((name,wid))})
    app.state.native_poller=service('native','run_due')
    app.state.worker=service('jobs','run_one')
    app.state.people_directory=service('roster','run_due')
    app.state.attendance_schedule=service('attendance','run_due')
    app.state.source_sync=service('sources','run_due')
    monkeypatch.setattr(run_worker,'app',app)
    monkeypatch.setattr(sys,'argv',['run_worker.py','--once'])
    run_worker.main()
    names=[name for name,wid in calls]
    assert names==(['native','jobs'] if enabled else ['native','roster','attendance','sources','jobs'])
    with app.state.sessions() as db:
        heartbeat=db.get(CacheRow,'runtime:worker').data
    assert heartbeat['status']=='ok' and heartbeat['stage']=='cycle_complete'
    assert heartbeat['last_success_at']==heartbeat['at']


@pytest.mark.parametrize('age,status,blocking',[(30,'ok',False),(650,'warning',False),(900,'warning',False),(901,'stale',True)])
def test_runtime_health_uses_live_roster_and_preserves_hard_limit(age,status,blocking):
    from contextlib import contextmanager
    from datetime import datetime,timedelta,timezone
    from types import SimpleNamespace
    from backend.runtime_health import snapshot
    now=datetime(2026,10,7,tzinfo=timezone.utc)
    @contextmanager
    def sessions(): yield SimpleNamespace(get=lambda model,key:None)
    live={'enabled':True,'datasets':{'roster':{'as_of':(now-timedelta(seconds=age)).isoformat(),'status':'fresh'}}}
    coordinator=SimpleNamespace(status=lambda wid:live,queue_depth=2)
    result=snapshot(sessions,object,{'LARK_WORKER_ORGANIZATION':'company'},now=now,coordinator=coordinator)
    assert result['directory']['status']==status
    assert result['directory']['blocking'] is blocking
    assert result['directory']['max_age_seconds']==900
    assert result['live_read']['queue_depth']==2
    assert result['external_integrations_verified'] is False


def test_worker_log_carries_http_status_without_detail(tmp_path,monkeypatch,capsys):
    from types import SimpleNamespace
    from fastapi import HTTPException
    from backend.app import create_app, WorkspaceRow
    from backend.seed import seed
    from scripts import run_worker
    app=create_app({'DATABASE_URL':f'sqlite:///{tmp_path}/worker.db','UPLOAD_DIR':str(tmp_path/'uploads'),
                    'DEMO_MODE':'true','LARK_LIVE_READ_ENABLED':'false'})
    with app.state.sessions.begin() as db: db.add(WorkspaceRow(id='demo-worker',version=1,data=seed()))
    def boom(wid): raise HTTPException(409,'secret-detail-ou_123')
    noop=SimpleNamespace(run_due=lambda wid:None,run_one=lambda wid:None)
    app.state.native_poller=app.state.people_directory=app.state.attendance_schedule=noop
    app.state.worker=noop; app.state.source_sync=SimpleNamespace(run_due=boom)
    monkeypatch.setattr(run_worker,'app',app); monkeypatch.setattr(sys,'argv',['run_worker.py','--once'])
    run_worker.main()
    out=capsys.readouterr().out
    assert json.loads(out.strip().splitlines()[0])=={'component':'source','error_type':'HTTPException','status_code':409}
    assert 'secret-detail' not in out


def test_live_child_shuts_down_cleanly_without_web_import_or_network(tmp_path):
    from backend.app import create_app
    database=tmp_path/'live-worker.db'
    app=create_app({'DATABASE_URL':f'sqlite:///{database}','UPLOAD_DIR':str(tmp_path/'uploads')})
    app.state.engine.dispose()
    env=dict(os.environ,DATABASE_URL=f'sqlite:///{database}',LARK_WORKER_ORGANIZATION='',
             LARK_ALLOWED_TENANTS='',LARK_LIVE_READ_ENABLED='false',SOP_LARK_PROJECTION_ENABLED='false')
    output=tmp_path/'live-worker.log'
    with output.open('w') as log:
        process=subprocess.Popen([sys.executable,str(ROOT/'scripts'/'run_live_read.py')],cwd=ROOT,env=env,
                                 stdout=log,stderr=log,text=True)
        try:
            deadline=time.monotonic()+8
            while 'live refresh worker ready' not in output.read_text() and time.monotonic()<deadline:
                assert process.poll() is None,output.read_text()
                time.sleep(.02)
            assert 'live refresh worker ready' in output.read_text()
            if hasattr(os,'getpriority'):
                assert os.getpriority(os.PRIO_PROCESS,process.pid)>=10
            process.terminate()
            process.wait(timeout=8)
            assert process.returncode==0,output.read_text()
        finally:
            if process.poll() is None:
                process.kill();process.wait(timeout=3)


def test_requested_worker_recycle_keeps_web_alive(tmp_path):
    stop = threading.Event()
    web_pid = tmp_path/'web.pid'
    worker_pids = tmp_path/'worker.pids'
    code = "import os,sys,time;from pathlib import Path;p=Path(sys.argv[1]);first=not p.exists();p.open('a').write(str(os.getpid())+'\\n');sys.exit(75) if first else time.sleep(120)"
    observed = []
    def finish():
        deadline = time.monotonic()+5
        while time.monotonic() < deadline:
            if worker_pids.exists() and len(worker_pids.read_text().splitlines()) == 2:
                observed.append(alive(int(web_pid.read_text())))
                break
            time.sleep(.02)
        stop.set()
    thread = threading.Thread(target=finish, daemon=True)
    thread.start()
    result = run_service.supervise([('web',long_lived(web_pid)),
        ('worker',[sys.executable,'-c',code,str(worker_pids)])],stop_event=stop,
        shutdown_timeout=1,poll_interval=.02,restart_codes={'worker':75})
    thread.join(timeout=1)
    assert result == 0 and observed == [True]
    assert all(not alive(int(pid)) for pid in worker_pids.read_text().splitlines())
