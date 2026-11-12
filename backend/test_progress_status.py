"""Progress presentation stays independent of the fail-closed lifecycle gate."""
import pytest
from .test_lifecycle_fail_closed import setup, lark, BAD
from .operations import refresh_project_state, TECHNICAL, project_summary
from .workspace_projection import public_copy
from .company_dashboard import overview

@pytest.mark.parametrize('node_state,prior,expected', [
    (None, 'paused', 'pending'), ('pending', 'paused', 'pending'),
    ('in_progress', 'paused', 'in_progress'), ('rework', 'paused', 'in_progress'),
    ('completed', 'paused', 'in_progress'), (None, 'in_progress', 'pending'), ('pending', 'in_progress', 'pending'),
])
def test_unverified_progress(setup, node_state, prior, expected):
    ws,p,n,_=setup
    lark(p,BAD['blank'])
    n=next(node for node in p['nodes'] if node['key']=='sales')
    p['nodes']=[n] if node_state else []
    if node_state: n['status']=node_state
    p['execution_status']=prior
    refresh_project_state(p,ws)
    assert p['execution_status']==p['status']=='paused'
    assert p['progress_status']==expected
    refresh_project_state(p,ws)
    assert p['progress_status']==expected
    assert public_copy(p)['progress_status']==p['progress_status']
    assert project_summary(ws,p)['progress_status']==p['progress_status']
    row=overview(ws)['cases'][0]
    assert row['progress_status']==p['progress_status'] and row['execution_status']=='paused'


def test_declared_stop(setup):
    ws,p,n,_=setup
    lark(p,dict(state='mapped',canonical='中止',reasons=[]))
    p['nodes']=[n]; n['status']='in_progress'
    refresh_project_state(p,ws)
    assert p['progress_status']==p['execution_status']=='paused'


def test_engineering_completion_wins_over_lifecycle_gate(setup):
    ws,p,_,_=setup
    lark(p,BAD['blank'])
    p['nodes']=[n for n in p['nodes'] if n['key'] in TECHNICAL]
    for n in p['nodes']: n['status']='completed'
    refresh_project_state(p,ws)
    assert p['progress_status']==p['execution_status']=='engineering_complete'


def test_settlement_and_engineering_completed(setup):
    ws,p,_,_=setup
    lark(p,BAD['blank'])
    p['payment_reconciliation']={'confirmed': True}
    for n in p['nodes']: n['status']='completed'
    refresh_project_state(p,ws)
    assert p['progress_status']==p['execution_status']=='completed'


@pytest.mark.parametrize('node_state,expected', [('pending','pending'), ('in_progress','in_progress')])
def test_manager_legacy_project_derives_progress_without_mutating(setup,node_state,expected):
    from copy import deepcopy
    from .manager_overview import build_manager_overview
    ws,p,_,_=setup
    lark(p,BAD['blank'])
    p['execution_status']='paused'
    p.pop('progress_status',None)
    for n in p['nodes']: n['status']=node_state
    before=deepcopy(ws)
    result=build_manager_overview(ws,population=lambda *_: [])
    row=next(c for c in result['snapshot']['cases'] if c['project_id']==p['id'])
    assert row['details']['progress_status']==expected
    assert row['details']['execution_status']=='paused'
    assert ws==before


@pytest.mark.parametrize('environment', ['demo','production'])
def test_startup_reindexes_legacy_summary_once(tmp_path,setup,environment):
    import os
    from copy import deepcopy
    from sqlalchemy import delete,select
    from .app import create_app
    from . import storage,index_reads
    from .models import BusinessRow,WorkspaceRow,ProjectIndex,WorkspaceCounter
    ws,p,_,_=setup
    ws['environment']=environment
    lark(p,BAD['blank'])
    p['nodes']=[next(n for n in p['nodes'] if n['key']=='sales')]
    p['nodes'][0]['status']='in_progress'
    p['execution_status']=p['status']='paused'
    p.pop('progress_status',None)
    wid='legacy-'+environment
    cfg={'DATABASE_URL':os.environ.get('PROGRESS_TEST_DATABASE_URL',f'sqlite:///{tmp_path}/legacy.db'),'UPLOAD_DIR':str(tmp_path/'uploads'),
         'SESSION_SECRET':'x'*40,'APP_ENV':'development','DEMO_MODE':'true',
         'INDEX_TABLES_ENABLED':'true','LARK_APP_ID':'','LARK_APP_SECRET':'','LARK_ALLOWED_TENANTS':''}
    app=create_app(cfg)
    with app.state.sessions.begin() as db:
        ws['version']=7
        row=WorkspaceRow(id=wid,version=7,data={})
        db.add(row)
        db.flush()
        row.data=storage.save(db,BusinessRow,wid,ws)
        db.flush()
        indexed=db.get(ProjectIndex,(wid,p['id']))
        summary=deepcopy(indexed.summary)
        summary.pop('progress_status')
        indexed.summary=summary
        db.execute(delete(WorkspaceCounter).where(WorkspaceCounter.workspace_id==wid,WorkspaceCounter.key=='summary_version'))
    with app.state.sessions() as db:
        assert not index_reads.ready(db,BusinessRow,db.get(WorkspaceRow,wid))
    app.state.engine.dispose()
    for expected_version in (8,8):
        app=create_app(cfg)  # Real startup path, including the second idempotent boot.
        with app.state.sessions() as db:
            row=db.get(WorkspaceRow,wid)
            assert row.version==expected_version
            assert index_reads.ready(db,BusinessRow,row)
            indexed=db.get(ProjectIndex,(wid,p['id']))
            assert indexed.summary['progress_status']=='in_progress'
            assert indexed.summary['execution_status']=='paused'
            from .shell import card
            assert card(dict(db.execute(select(ProjectIndex.__table__).where(ProjectIndex.workspace_id==wid,ProjectIndex.project_id==p['id'])).mappings().one()),ws,{})['progress_status']=='in_progress'
        app.state.engine.dispose()


@pytest.fixture(params=['sqlite', 'postgresql'])
def rollout_db(request, tmp_path):
    import os
    from uuid import uuid4
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from .models import Base, BusinessRow, WorkspaceRow
    from . import storage
    from .perf_fixture import build_scaled_workspace
    from .policy import upgrade
    url = f'sqlite:///{tmp_path}/rollout.db' if request.param == 'sqlite' else os.getenv('PROGRESS_TEST_DATABASE_URL')
    if not url:
        pytest.skip('PROGRESS_TEST_DATABASE_URL is not configured')
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False, info={'index_tables': True})
    wid = 'rollout-' + uuid4().hex
    state = upgrade(build_scaled_workspace(2))
    state['version'] = 7
    with sessions.begin() as db:
        row = WorkspaceRow(id=wid, version=7, data={})
        db.add(row)
        db.flush()
        row.data = storage.save(db, BusinessRow, wid, state)
    try:
        yield sessions, wid
    finally:
        engine.dispose()


@pytest.mark.parametrize('remaining', [0, 1])
def test_startup_reconciles_deleted_projects(rollout_db, remaining):
    from sqlalchemy import select
    from . import storage, index_reads
    from .models import BusinessRow, WorkspaceRow, ProjectIndex, TaskIndex
    from .policy import upgrade
    from .workspace_migration import _migrate_one
    sessions, wid = rollout_db
    with sessions.begin() as db:
        row = db.get(WorkspaceRow, wid)
        state = storage.load(db, BusinessRow, row)
        removed = {p['id'] for p in state['projects'][remaining:]}
        state['projects'] = state['projects'][:remaining]
        state['version'] = row.version = 8
        db.info['index_tables'] = False  # Deletion while maintenance is disabled.
        row.data = storage.save(db, BusinessRow, wid, state)
    with sessions() as db:
        assert not index_reads.ready(db, BusinessRow, db.get(WorkspaceRow, wid))
    for migrated in (True, False):
        assert _migrate_one(sessions, WorkspaceRow, BusinessRow, upgrade, storage, wid, 8, None) is migrated
        with sessions() as db:
            row = db.get(WorkspaceRow, wid)
            assert row.version == 9
            assert index_reads.ready(db, BusinessRow, row)
            assert not set(db.scalars(select(ProjectIndex.project_id).where(ProjectIndex.workspace_id == wid))) & removed
            assert not set(db.scalars(select(TaskIndex.project_id).where(TaskIndex.workspace_id == wid))) & removed


@pytest.mark.parametrize('save_kind', ['full', 'prepared'])
def test_dirty_save_does_not_restore_summary_marker(rollout_db, save_kind):
    from copy import deepcopy
    from sqlalchemy import delete
    from . import storage, index_reads
    from .models import BusinessRow, WorkspaceRow, ProjectIndex, WorkspaceCounter
    from .policy import upgrade
    from .workspace_migration import _migrate_one
    sessions, wid = rollout_db
    # Start with a full migration's marker, then emulate an old worker writing A.
    _migrate_one(sessions, WorkspaceRow, BusinessRow, upgrade, storage, wid, 8, None)
    with sessions.begin() as db:
        row = db.get(WorkspaceRow, wid)
        state = storage.load(db, BusinessRow, row)
        a, b = [p['id'] for p in state['projects']]
        indexed = db.get(ProjectIndex, (wid, a))
        legacy = deepcopy(indexed.summary)
        legacy.pop('progress_status')
        indexed.summary = legacy
        db.execute(delete(WorkspaceCounter).where(WorkspaceCounter.workspace_id == wid, WorkspaceCounter.key == 'summary_version'))
    # A new worker changes only B; A's legacy summary must keep readiness false.
    with sessions.begin() as db:
        row = db.get(WorkspaceRow, wid)
        existing = {}
        state = storage.load(db, BusinessRow, row, row_snapshot=existing)
        state['projects'][1]['name'] = 'Changed B'
        if save_kind == 'prepared':
            plan = storage.prepare_save(BusinessRow, wid, state, existing, row.data, indexed=True)
        state['version'] = row.version = row.version + 1
        row.data = (storage.save_prepared(db, BusinessRow, wid, state, plan) if save_kind == 'prepared'
                    else storage.save(db, BusinessRow, wid, state))
    with sessions() as db:
        row = db.get(WorkspaceRow, wid)
        assert db.get(ProjectIndex, (wid, b)).name == 'Changed B'
        assert 'progress_status' not in db.get(ProjectIndex, (wid, a)).summary
        assert db.get(WorkspaceCounter, (wid, 'summary_version', '')) is None
        assert not index_reads.ready(db, BusinessRow, row)
    assert _migrate_one(sessions, WorkspaceRow, BusinessRow, upgrade, storage, wid, 8, None)
    with sessions() as db:
        assert index_reads.ready(db, BusinessRow, db.get(WorkspaceRow, wid))
        assert 'progress_status' in db.get(ProjectIndex, (wid, a)).summary
    assert not _migrate_one(sessions, WorkspaceRow, BusinessRow, upgrade, storage, wid, 8, None)


def test_summary_rebuild_rolls_back(rollout_db):
    from sqlalchemy import delete, select
    from . import storage, index_reads
    from .models import BusinessRow, WorkspaceRow, ProjectIndex, TaskIndex, WorkspaceCounter
    from .policy import upgrade
    from .workspace_migration import _migrate_one
    sessions, wid = rollout_db
    with sessions.begin() as db:
        db.execute(delete(WorkspaceCounter).where(WorkspaceCounter.workspace_id == wid, WorkspaceCounter.key == 'summary_version'))
        db.add(ProjectIndex(workspace_id=wid, project_id='orphan'))
        db.add(TaskIndex(workspace_id=wid, project_id='orphan', task_id='orphan-task', node_id='orphan-node'))
    def snapshot():
        with sessions() as db:
            tables = [WorkspaceRow.__table__, BusinessRow.__table__, ProjectIndex.__table__, TaskIndex.__table__, WorkspaceCounter.__table__]
            return [sorted((repr(dict(r)) for r in db.execute(select(t).where((t.c.id if t.name == 'workspaces' else t.c.workspace_id) == wid)).mappings())) for t in tables]
    before = snapshot()
    def fail(name):
        if name == 'before_update':
            raise RuntimeError('abort rebuild')
    with pytest.raises(RuntimeError, match='abort rebuild'):
        _migrate_one(sessions, WorkspaceRow, BusinessRow, upgrade, storage, wid, 8, fail)
    assert snapshot() == before
    assert _migrate_one(sessions, WorkspaceRow, BusinessRow, upgrade, storage, wid, 8, None)
    with sessions() as db:
        assert index_reads.ready(db, BusinessRow, db.get(WorkspaceRow, wid))


def test_concurrent_summary_rebuilds_commit_once(rollout_db):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy import delete, event
    from . import storage, index_reads
    from .models import BusinessRow, WorkspaceRow, WorkspaceCounter
    from .policy import upgrade
    from .workspace_migration import _migrate_one
    sessions, wid = rollout_db
    with sessions.begin() as db:
        db.execute(delete(WorkspaceCounter).where(WorkspaceCounter.workspace_id == wid, WorkspaceCounter.key == 'summary_version'))
    barrier = Barrier(2)
    def migrate(_):
        first = True
        def hook(name):
            nonlocal first
            if name == 'after_read' and first:
                first = False
                barrier.wait(timeout=10)
        return _migrate_one(sessions, WorkspaceRow, BusinessRow, upgrade, storage, wid, 8, hook)
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(migrate, range(2))) == [False, True]
    with sessions() as db:
        row = db.get(WorkspaceRow, wid)
        assert row.version == 8
        assert index_reads.ready(db, BusinessRow, row)
    writes = []
    def capture(conn, cursor, statement, *args):
        if statement.lstrip().split()[0].upper() in ('INSERT', 'UPDATE', 'DELETE'):
            writes.append(statement)
    engine = sessions.kw['bind']
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        assert not _migrate_one(sessions, WorkspaceRow, BusinessRow, upgrade, storage, wid, 8, None)
        assert writes == []
    finally:
        event.remove(engine, 'before_cursor_execute', capture)


def test_dirty_save_preserves_marker_without_republishing(rollout_db):
    from sqlalchemy import delete, event
    from . import storage, index_reads
    from .models import BusinessRow, WorkspaceRow, WorkspaceCounter
    sessions, wid = rollout_db
    engine = sessions.kw['bind']
    removed = False
    def old_worker_removes_marker(conn, cursor, statement, *args):
        nonlocal removed
        if not removed and statement.startswith('SELECT') and 'FROM workspace_counters' in statement:
            removed = True
            # The ordinary save has read the marker, but has not written counters.
            conn.execute(delete(WorkspaceCounter).where(WorkspaceCounter.workspace_id == wid, WorkspaceCounter.key == 'summary_version'))
    with sessions() as db:
        assert index_reads.ready(db, BusinessRow, db.get(WorkspaceRow, wid))
    event.listen(engine, 'after_cursor_execute', old_worker_removes_marker)
    try:
        with sessions.begin() as db:
            row = db.get(WorkspaceRow, wid)
            state = storage.load(db, BusinessRow, row)
            state['projects'][1]['name'] = 'Changed after marker read'
            state['version'] = row.version = row.version + 1
            row.data = storage.save(db, BusinessRow, wid, state)
    finally:
        event.remove(engine, 'after_cursor_execute', old_worker_removes_marker)
    assert removed
    with sessions() as db:
        assert db.get(WorkspaceCounter, (wid, 'summary_version', '')) is None
        assert not index_reads.ready(db, BusinessRow, db.get(WorkspaceRow, wid))
