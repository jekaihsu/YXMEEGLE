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
