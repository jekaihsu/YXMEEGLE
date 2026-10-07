"""Run the durable application worker (separate Zeabur service/process)."""
import argparse
import sys
import time
import json
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from backend.live_read.config import LiveReadConfig
from backend.app import app, WorkspaceRow, CacheRow


def heartbeat(status,stage='idle',error_type=None):
    with app.state.sessions.begin() as db:
        row=db.get(CacheRow,'runtime:worker')
        current=dict(row.data) if row else {}
        current.update(status=status,stage=stage,at=datetime.now(timezone.utc).isoformat())
        if error_type: current['error_type']=error_type
        else: current.pop('error_type',None)
        if status=='ok': current['last_success_at']=current['at']
        if row: row.data=current
        else: db.add(CacheRow(id='runtime:worker',data=current))

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--once',action='store_true'); args=parser.parse_args()
    while True:
        try:
            heartbeat('running','enumerate')
            with app.state.sessions() as db: ids=list(db.scalars(select(WorkspaceRow.id)))
        except Exception as exc:
            print(json.dumps({'component':'worker','stage':'database','error_type':type(exc).__name__}),flush=True)
            if args.once: raise
            time.sleep(30); continue
        failed=False
        for wid in ids:
            try:
                app.state.native_poller.run_due(wid)
            except Exception as exc:
                failed=True; print(json.dumps({'component':'approval_poll','error_type':type(exc).__name__}),flush=True)
            if not LiveReadConfig.from_env(app.state.cfg).enabled:
                try:
                    app.state.people_directory.run_due(wid)
                except Exception as exc:
                    failed=True; print(json.dumps({'component':'people','error_type':type(exc).__name__}),flush=True)
                try:
                    app.state.attendance_schedule.run_due(wid)
                except Exception as exc:
                    failed=True; print(json.dumps({'component':'attendance','error_type':type(exc).__name__}),flush=True)
                try:
                    app.state.source_sync.run_due(wid)
                except Exception as exc:
                    failed=True; print(json.dumps({'component':'source','error_type':type(exc).__name__}),flush=True)
            try:
                app.state.worker.run_one(wid)
            except Exception as exc:
                failed=True; print(json.dumps({'component':'jobs','error_type':type(exc).__name__}),flush=True)
        heartbeat('degraded' if failed else 'ok','cycle_complete')
        if args.once: return
        time.sleep(30)

if __name__=='__main__': main()
