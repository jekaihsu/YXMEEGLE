"""VCC-97 P2-5: index-health detects missing/extra/stale rows and counter drift, and repairs with an audit event."""
from fastapi.testclient import TestClient
from sqlalchemy import select, delete, update
from backend import storage
from backend.app import create_app
from backend.models import AuditRow, BusinessRow, WorkspaceRow, ProjectIndex, TaskIndex, WorkspaceCounter
from backend.policy import upgrade
from backend.perf_fixture import build_scaled_workspace
from scripts.backfill_index import backfill


def booted(tmp_path,flag='true'):
    app=create_app({'DATABASE_URL':f'sqlite:///{tmp_path}/h.db','UPLOAD_DIR':str(tmp_path/'u'),'SESSION_SECRET':'x'*40,'APP_ENV':'development','DEMO_MODE':'true','INDEX_TABLES_ENABLED':flag,'LARK_APP_ID':'','LARK_APP_SECRET':'','LARK_ALLOWED_TENANTS':''})
    client=TestClient(app); client.__enter__(); client.get('/api/session')
    wid=app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
    with app.state.sessions.begin() as db:
        row=db.get(WorkspaceRow,wid); state=upgrade(build_scaled_workspace(8)); state['version']=row.version+1
        row.version=state['version']; row.data=storage.save(db,BusinessRow,wid,state)
    assert client.post('/api/demo/session',json={'user_id':'u-manager'}).status_code==200
    return app,client,wid


def test_detects_and_repairs_corruption_with_audit(tmp_path):
    app,client,wid=booted(tmp_path)
    try:
        report=client.get('/api/admin/index-health').json()
        assert report['healthy'] and report['enabled'] and report['projects']['actual']==8
        with app.state.sessions.begin() as db:
            task=db.scalars(select(TaskIndex.task_id).where(TaskIndex.project_id=='p001')).first()
            db.execute(delete(TaskIndex).where(TaskIndex.task_id==task))                                  # missing
            db.execute(update(ProjectIndex).where(ProjectIndex.project_id=='p002').values(status='bogus'))  # stale
            db.execute(ProjectIndex.__table__.insert().values(workspace_id=wid,project_id='ghost'))        # extra
            db.execute(update(WorkspaceCounter).where(WorkspaceCounter.key=='projects_total').values(value=99))  # drift
        report=client.get('/api/admin/index-health').json()
        assert not report['healthy'] and not report['repaired']
        assert report['tasks']['missing']==[task] and report['projects']['stale']==['p002'] and report['projects']['extra']==['ghost']
        assert report['counters']['drift'][0]['stored']==99
        assert set(report['dirty_projects'])=={'p001','p002','ghost'}
        fixed=client.post('/api/admin/index-health/repair').json()
        assert fixed['repaired']
        again=client.get('/api/admin/index-health').json()
        assert again['healthy'] and again['projects']['actual']==8
        with app.state.sessions() as db:
            events=db.scalars(select(AuditRow).where(AuditRow.action=='admin_index_repair')).all()
            assert len(events)==1 and events[0].data['project_count']==3
    finally:
        client.__exit__(None,None,None); app.state.engine.dispose()


def test_manager_only_and_repair_needs_flag(tmp_path):
    app,client,wid=booted(tmp_path,'false')
    try:
        assert client.get('/api/admin/index-health').json()['enabled'] is False
        assert client.post('/api/admin/index-health/repair').status_code==409
        assert client.post('/api/demo/session',json={'user_id':'u-pm'}).status_code==200
        assert client.get('/api/admin/index-health').status_code==403
        assert client.post('/api/admin/index-health/repair').status_code==403
    finally:
        client.__exit__(None,None,None); app.state.engine.dispose()


def test_backfill_then_health_is_clean(tmp_path):
    app,client,wid=booted(tmp_path,'false')
    try:
        backfill(app.state.engine)
        assert client.get('/api/admin/index-health').json()['healthy']
    finally:
        client.__exit__(None,None,None); app.state.engine.dispose()
