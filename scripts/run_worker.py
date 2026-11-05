"""Run the durable application worker (separate Zeabur service/process)."""
import argparse
import sys
import time
import json
import os
import random
import signal
from threading import Event
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi import HTTPException
from sqlalchemy import select
from backend.resource_gauge import user_active, container_busy, release_working_memory, log_stage, processes
from backend.live_read.config import LiveReadConfig
from backend.app import app, WorkspaceRow, CacheRow


def report(component,exc):
    # HTTPException carries a numeric status only; its detail may name people or resources.
    code=exc.status_code if isinstance(exc,HTTPException) else None
    print(json.dumps({'component':component,'error_type':type(exc).__name__,**({'status_code':code} if code else {})}),flush=True)


def heartbeat(status,stage='idle',error_type=None):
    with app.state.sessions.begin() as db:
        row=db.get(CacheRow,'runtime:worker')
        current=dict(row.data) if row else {}
        current.update(status=status,stage=stage,at=datetime.now(timezone.utc).isoformat(),
                       queue_depth=app.state.live_read.queue_depth + app.state.people_attendance.queue_depth)
        if error_type: current['error_type']=error_type
        else: current.pop('error_type',None)
        if status=='ok': current['last_success_at']=current['at']
        if row: row.data=current
        else: db.add(CacheRow(id='runtime:worker',data=current))

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--once',action='store_true'); args=parser.parse_args()
    if hasattr(os, 'nice'): os.nice(10)
    stopped = Event()
    for sig in (signal.SIGTERM, signal.SIGINT): signal.signal(sig, lambda *_: stopped.set())
    cfg = app.state.cfg
    # One background interpreter owns refreshes and durable jobs. DB leases
    # remain the authority; web force/wait reads still use their existing fences.
    app.state.live_read.cfg = dict(cfg, LIVE_READ_BACKGROUND_PROCESS='false')
    app.state.people_attendance.cfg = dict(cfg, LIVE_READ_BACKGROUND_PROCESS='false')
    refresh_deadline = Path('/tmp/yx-workbench-refresh-deadline')
    try:
        next_refresh = float(refresh_deadline.read_text())
        if not time.monotonic() <= next_refresh <= time.monotonic()+360: next_refresh = 0
    except (OSError, ValueError):
        next_refresh = 0
    while not stopped.is_set():
        try:
            heartbeat('running','enumerate')
            with app.state.sessions() as db:
                query = select(WorkspaceRow.id)
                tenant = cfg.get('LARK_WORKER_ORGANIZATION')
                if cfg.get('APP_ENV') == 'production' and tenant:
                    query = query.where(WorkspaceRow.id.in_(['lark-'+tenant, 'test-lark-'+tenant]))
                ids = list(db.scalars(query))
        except Exception as exc:
            print(json.dumps({'component':'worker','stage':'database','error_type':type(exc).__name__}),flush=True)
            if args.once: raise
            stopped.wait(30); continue
        failed=False
        if time.monotonic() >= next_refresh:
            wid = 'lark-' + cfg.get('LARK_WORKER_ORGANIZATION', '')
            if wid in ids and LiveReadConfig.from_env(cfg).enabled:
                for dataset in ('roster', 'attendance', 'sources'):
                    if dataset != 'roster' and (not user_active() or container_busy()): continue
                    started, cpu = time.monotonic(), time.process_time()
                    try:
                        app.state.live_read.ensure(wid, dataset, wait=True, timeout=120)
                    except Exception as exc:
                        failed=True; report('live_'+dataset, exc)
                    log_stage('live_'+dataset, started, cpu)
                if user_active() and not container_busy():
                    app.state.people_attendance.view(wid)
            next_refresh = time.monotonic() + (random.uniform(285, 315) if user_active() else random.uniform(28, 32))
            try:
                refresh_deadline.write_text(str(next_refresh))
            except OSError:
                pass
        started, cpu = time.monotonic(), time.process_time()
        for wid in ids:
            try:
                app.state.native_poller.run_due(wid)
            except Exception as exc:
                failed=True; report('approval_poll',exc)
            if not LiveReadConfig.from_env(app.state.cfg).enabled:
                try:
                    app.state.people_directory.run_due(wid)
                except Exception as exc:
                    failed=True; report('people',exc)
                try:
                    app.state.attendance_schedule.run_due(wid)
                except Exception as exc:
                    failed=True; report('attendance',exc)
                try:
                    app.state.source_sync.run_due(wid)
                except Exception as exc:
                    failed=True; report('source',exc)
            try:
                app.state.worker.run_one(wid)
            except Exception as exc:
                failed=True; report('jobs',exc)
        try:
            app.state.sop_projection.drain()
        except Exception as exc:
            failed=True; report('sop_projection', exc)
        log_stage('durable', started, cpu)
        release_working_memory()
        log_stage('released', time.monotonic(), time.process_time())
        heartbeat('degraded' if failed else 'ok','cycle_complete')
        if args.once: return
        own = next((row for row in processes() if row['pid'] == os.getpid()), {})
        if own.get('rss_bytes', 0) > 200 * 1024 * 1024:
            # Only after durable work/heartbeat commit; the supervisor replaces
            # this interpreter alone. Leases and snapshots live in PostgreSQL.
            app.state.people_attendance.close()
            app.state.live_read.close()
            app.state.read_snapshots.close()
            app.state.engine.dispose()
            print('worker recycle requested: RSS above 200 MiB after release', flush=True)
            return 75
        stopped.wait(random.uniform(28, 32))

if __name__=='__main__': raise SystemExit(main())
