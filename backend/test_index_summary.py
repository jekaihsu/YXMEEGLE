"""VCC-97 P2-4: project_index.summary equals the live project_summary for every fixture project."""
from copy import deepcopy
from sqlalchemy import select
from backend import index_tables
from backend.models import ProjectIndex
from backend.policy import upgrade
from backend.operations import project_summary
from backend.perf_fixture import build_scaled_workspace
from backend.test_index_maintenance import make, commit, load


def test_stored_summary_equals_live_computation_for_all_fixture_projects(tmp_path):
    engine,sessions=make(tmp_path,True); state=upgrade(build_scaled_workspace(319)); commit(sessions,state)
    state=upgrade(load(sessions))
    with sessions() as db: stored={r.project_id:r.summary for r in db.execute(select(ProjectIndex.project_id,ProjectIndex.summary))}
    assert len(stored)==319
    for p in state['projects']:
        assert stored[p['id']]==project_summary(state,deepcopy(p)),p['id']
    engine.dispose()


def test_summary_refreshes_with_the_changed_project_only(tmp_path):
    engine,sessions=make(tmp_path,True); commit(sessions,upgrade(build_scaled_workspace(6)))
    state=upgrade(load(sessions)); node=state['projects'][2]['nodes'][8]; node['status']='in_progress'
    with sessions() as db: before={r.project_id:r.summary for r in db.execute(select(ProjectIndex.project_id,ProjectIndex.summary))}
    commit(sessions,state)
    with sessions() as db: after={r.project_id:r.summary for r in db.execute(select(ProjectIndex.project_id,ProjectIndex.summary))}
    changed={k for k in after if after[k]!=before[k]}
    assert changed=={state['projects'][2]['id']}
    assert after[state['projects'][2]['id']]['nodes'][8]['status']=='in_progress'
    engine.dispose()


def test_unsummarizable_project_stores_null_and_does_not_block_write(tmp_path):
    engine,sessions=make(tmp_path,True); state=upgrade(build_scaled_workspace(2)); state['projects'][0]['nodes'][0].pop('key')
    commit(sessions,state)
    with sessions() as db:
        assert db.scalar(select(ProjectIndex.summary).where(ProjectIndex.project_id==state['projects'][0]['id'])) is None
        assert db.scalar(select(ProjectIndex.summary).where(ProjectIndex.project_id==state['projects'][1]['id'])) is not None
    engine.dispose()
