"""Disabling demo must also revoke still-valid signed demo sessions."""
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from .app import create_app,WorkspaceRow


def test_disabling_demo_revokes_old_cookie_without_creating_workspace(tmp_path):
    cfg={'DATABASE_URL':f'sqlite:///{tmp_path}/demo-cutover.db','UPLOAD_DIR':str(tmp_path/'files'),
         'APP_ENV':'development','SESSION_SECRET':'unchanged-session-secret'*3,
         'LARK_APP_ID':'app','LARK_APP_SECRET':'secret',
         'LARK_REDIRECT_URI':'https://workbench.example/api/auth/lark/callback',
         'LARK_ALLOWED_TENANTS':'company'}
    demo_app=create_app({**cfg,'DEMO_MODE':'true'})
    demo=TestClient(demo_app)
    assert demo.get('/api/session').json()['mode']=='demo'
    old_cookie=demo.cookies.get('meegle_session')
    assert old_cookie
    live_app=create_app({**cfg,'DEMO_MODE':'false','ALLOW_CLOUD_DEMO':'false'})
    live=TestClient(live_app);live.cookies.set('meegle_session',old_cookie)
    with live_app.state.sessions() as db:
        before=db.scalar(select(func.count()).select_from(WorkspaceRow))
    session=live.get('/api/session')
    assert session.status_code==200
    assert session.json()=={'user':None,'users':[],'mode':'lark','auth_configured':True}
    assert live.get('/api/workspace').status_code==401
    assert live.get('/api/projects').status_code==401
    assert live.post('/api/demo/session',json={'user_id':'u-manager'}).status_code==403
    assert live.post('/api/actions',json={'action':'comment_add','version':1,'request_id':'old-demo',
        'project_id':'p1','payload':{'body':'Must not be saved','mentions':[]}}).status_code==401
    live.cookies.clear()
    assert live.get('/api/session').json()['user'] is None
    with live_app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(WorkspaceRow))==before
