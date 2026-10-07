"""VCC-97 P2-2: backfill fills index tables from business_records, idempotently."""
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from backend import storage
from backend.models import Base, BusinessRow, WorkspaceRow, ProjectIndex, TaskIndex, WorkspaceCounter
from backend.perf_fixture import build_scaled_workspace
from scripts.backfill_index import backfill


def seeded(tmp_path,n=12):
    engine=create_engine('sqlite:///'+str(tmp_path/'b.db')); Base.metadata.create_all(engine)
    sessions=sessionmaker(engine,expire_on_commit=False); state=build_scaled_workspace(n); state['version']=1
    with sessions.begin() as db:
        db.add(WorkspaceRow(id='w',version=1,data={})); db.flush()
        db.get(WorkspaceRow,'w').data=storage.save(db,BusinessRow,'w',state)
    return engine,sessions,state


def count(sessions,model):
    with sessions() as db: return db.scalar(select(func.count()).select_from(model))


def test_backfill_populates_and_is_idempotent(tmp_path):
    engine,sessions,state=seeded(tmp_path)
    assert backfill(engine,dry_run=True)[0]['projects']==12 and count(sessions,ProjectIndex)==0
    backfill(engine,batch=5); first=count(sessions,TaskIndex)
    assert count(sessions,ProjectIndex)==12 and first==sum(len(n['tasks']) for p in state['projects'] for n in p['nodes'])
    with sessions() as db:
        assert db.scalar(select(WorkspaceCounter.value).where(WorkspaceCounter.key=='projects_total'))==12
    backfill(engine); assert (count(sessions,ProjectIndex),count(sessions,TaskIndex))==(12,first)
    engine.dispose()


def test_backfill_removes_extra_rows(tmp_path):
    engine,sessions,_=seeded(tmp_path,4)
    backfill(engine)
    with sessions.begin() as db:
        db.execute(ProjectIndex.__table__.insert().values(workspace_id='w',project_id='ghost'))
    backfill(engine); assert count(sessions,ProjectIndex)==4
    engine.dispose()
