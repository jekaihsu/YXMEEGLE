"""Populate project_index, task_index and workspace_counters from business_records.

Run: DATABASE_URL=... .venv/bin/python scripts/backfill_index.py [--workspace ID] [--batch 50] [--dry-run]
Idempotent and re-runnable. The workspace is read once in a short read-only
transaction; rows are written in small batches, each its own transaction that
locks and re-checks workspaces.version before changing index rows. A concurrent
write restarts that workspace. Extra rows for vanished projects are removed at
the end. Each batch and final publication hold the workspace writer lock until
commit; writers may proceed between batches. Quiesce all writers for rollout.
"""
import argparse
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker

from backend import index_tables, storage
from backend.policy import upgrade
from backend.models import BusinessRow, WorkspaceRow


def lock_version(db,wid,version):
    """Use the same conditional workspace UPDATE as admin repair.

    PostgreSQL waits for a concurrent writer, then rechecks the version predicate;
    success holds the row lock through index replacement and transaction commit.
    Unlike SELECT FOR UPDATE this also acquires a write lock on SQLite.
    """
    return db.execute(update(WorkspaceRow).where(WorkspaceRow.id==wid,WorkspaceRow.version==version)
                      .values(version=version)).rowcount==1


def backfill_workspace(sessions,wid,*,batch=50,dry_run=False,retries=3):
    for _ in range(retries):
        with sessions() as db:
            row=db.get(WorkspaceRow,wid)
            if row is None: return {'workspace':wid,'missing':True}
            version=row.version; state=upgrade(storage.load(db,BusinessRow,row)); state['version']=version
        ids=[p['id'] for p in state['projects']]; counts={'workspace':wid,'projects':len(ids),'tasks':sum(len(n['tasks']) for p in state['projects'] for n in p['nodes']),'dry_run':dry_run}
        if dry_run: return counts
        stale=False
        for start in range(0,len(ids),batch):
            with sessions.begin() as db:
                if not lock_version(db,wid,version): stale=True; break
                index_tables.replace_projects(db,BusinessRow,wid,state,ids[start:start+batch])
        if stale: continue
        with sessions.begin() as db:
            if not lock_version(db,wid,version): continue
            pi,ti,_=index_tables.tables(BusinessRow)
            known=set(ids); extra=[r for r in db.scalars(select(pi.c.project_id).where(pi.c.workspace_id==wid)) if r not in known]
            index_tables.replace_projects(db,BusinessRow,wid,state,extra)
            index_tables.replace_counters(db,BusinessRow,wid,state)
            index_tables.mark_rebuilt(db,BusinessRow,wid)
        return counts
    raise RuntimeError(f'workspace {wid} kept changing during backfill; re-run')


def backfill(engine,*,workspace=None,batch=50,dry_run=False):
    sessions=sessionmaker(engine,expire_on_commit=False)
    with sessions() as db:
        wids=[workspace] if workspace else list(db.scalars(select(WorkspaceRow.id).order_by(WorkspaceRow.id)))
    return [backfill_workspace(sessions,wid,batch=batch,dry_run=dry_run) for wid in wids]


def main():
    parser=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--workspace'); parser.add_argument('--batch',type=int,default=50); parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    url=os.getenv('DATABASE_URL')
    if not url: raise SystemExit('DATABASE_URL is required')
    engine=create_engine(url)
    try:
        for result in backfill(engine,workspace=args.workspace,batch=args.batch,dry_run=args.dry_run): print(result)
    finally:
        engine.dispose()


if __name__=='__main__':
    main()
