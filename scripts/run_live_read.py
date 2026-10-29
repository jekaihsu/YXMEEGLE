"""Run ordinary Lark refresh and SOP projection outside the web interpreter."""
import logging
import os
from pathlib import Path
import signal
import sys
from threading import Event

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))


def main():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from backend.models import WorkspaceRow, BusinessRow, PersonRow, AuthRow, CacheRow
    from backend.source_sync import SourceSyncService
    from backend.people_directory import PeopleDirectoryService
    from backend.attendance_service import AttendanceScheduleService
    from backend.live_read.coordinator import RefreshCoordinator
    from backend.live_read.datasets import build_refreshers
    from backend.live_read.people_attendance import PeopleAttendance
    from backend.sop_import.lark_projection import Projection
    from backend import storage
    from backend.policy import upgrade
    from backend.workspace_seal import seal
    from backend.report_bridge import load_bridges

    cfg=dict(os.environ, LIVE_READ_BACKGROUND_PROCESS='false')
    url=cfg.get('DATABASE_URL','sqlite:///./backend/workspace.db')
    if url.startswith('postgres://'): url='postgresql+psycopg://'+url[len('postgres://'):]
    elif url.startswith('postgresql://'): url='postgresql+psycopg://'+url[len('postgresql://'):]
    engine=create_engine(url,pool_pre_ping=True,connect_args={'check_same_thread':False,'timeout':20} if url.startswith('sqlite') else {'connect_timeout':5})
    sessions=sessionmaker(engine,expire_on_commit=False,info={'index_tables':str(cfg.get('INDEX_TABLES_ENABLED','false')).lower()=='true'})
    sources=SourceSyncService(sessions,WorkspaceRow,BusinessRow,PersonRow,AuthRow,CacheRow,cfg)
    people=PeopleDirectoryService(sessions,WorkspaceRow,BusinessRow,PersonRow,cfg)
    attendance=AttendanceScheduleService(sessions,WorkspaceRow,BusinessRow,PersonRow,cfg)
    coordinator=RefreshCoordinator(sessions,CacheRow,build_refreshers(sources,people,attendance),cfg)
    weekly=PeopleAttendance(sessions,CacheRow,coordinator,cfg)
    def load_state(wid):
        with sessions() as db:
            row=db.get(WorkspaceRow,wid)
            state=upgrade(storage.load_partial(db,BusinessRow,row,collections=('projects','users','source_quotes')),generate_sop_candidate=False)
            state=seal(db,row,state,cfg)
            state['report_case_bridges']=load_bridges(db,wid)
            return state
    projection=Projection(sessions,cfg,load_state)
    stopped=Event()
    for signum in (signal.SIGINT,signal.SIGTERM): signal.signal(signum,lambda *_:stopped.set())
    tenant=cfg.get('LARK_WORKER_ORGANIZATION')
    allowed={value.strip() for value in cfg.get('LARK_ALLOWED_TENANTS','').split(',') if value.strip()}
    projection.start()
    print('live refresh worker ready',flush=True)
    try:
        while not stopped.is_set():
            if tenant and tenant in allowed:
                wid='lark-'+tenant
                try:
                    for dataset in ('roster','attendance','sources'): coordinator.ensure(wid,dataset,wait=False)
                    weekly.view(wid)
                except Exception as exc:
                    logging.getLogger(__name__).warning('live_worker_retry error_class=%s',type(exc).__name__)
            stopped.wait(5)
    finally:
        projection.close()
        weekly.close()
        coordinator.close()
        engine.dispose()
    return 0


if __name__=='__main__': raise SystemExit(main())
