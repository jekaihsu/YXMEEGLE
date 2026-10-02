"""Legacy null-environment workspace can bootstrap only via verified OAuth."""
import json
from datetime import datetime,timezone
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi.testclient import TestClient

from .app import create_app, WorkspaceRow, BusinessRow, PersonRow
from .seed import seed
from . import storage


def test_existing_normalized_workspace_first_manager_login_admits_sync(tmp_path, monkeypatch):
    cfg={'DATABASE_URL':f'sqlite:///{tmp_path}/legacy.db','UPLOAD_DIR':str(tmp_path/'uploads'),
         'APP_ENV':'development','DEMO_MODE':'false','SESSION_SECRET':'legacy-oauth-test'*4,
         'LARK_APP_ID':'app-test','LARK_APP_SECRET':'test-secret',
         'LARK_REDIRECT_URI':'https://example.org/api/auth/lark/callback',
         'LARK_ALLOWED_TENANTS':'company','LARK_ROLE_MAP_JSON':json.dumps({'ou_manager':'manager'}),
         'LARK_WORKER_ORGANIZATION':'company','LARK_WORKER_IDENTITY':'application'}
    app=create_app(cfg)
    with app.state.sessions.begin() as db:
        state=seed(True)
        state['users']=[{'id':'ou_manager','name':'Legacy manager','role':'manager','active':True,'capabilities':[]}]
        state.pop('environment',None)
        row=WorkspaceRow(id='lark-company',version=1,data={}); db.add(row); db.flush()
        row.data=storage.save(db,BusinessRow,row.id,state)
        assert db.get(PersonRow,('lark-company','ou_manager')) is None
    class OAuth:
        def __init__(self,**kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def post(self,url,**kwargs): return httpx.Response(200,json={'access_token':'test-only','expires_in':3600},request=httpx.Request('POST',url))
        def get(self,url,**kwargs): return httpx.Response(200,json={'data':{'open_id':'ou_manager','name':'Verified manager','tenant_key':'company'}},request=httpx.Request('GET',url))
    monkeypatch.setattr('backend.app.httpx.Client',OAuth)
    client=TestClient(app)
    login=client.get('/api/auth/lark/login',follow_redirects=False)
    nonce=parse_qs(urlparse(login.headers['location']).query)['state'][0]
    result=client.get('/api/auth/lark/callback',params={'state':nonce,'code':'test-valid'},follow_redirects=False)
    assert result.status_code==307
    assert client.get('/api/session').json()['environment']=='production'
    assert client.get('/api/workspace').status_code==403
    assert client.post('/api/workspace/switch',json={'environment':'production'}).status_code==403
    with app.state.sessions.begin() as db:
        profile=db.get(PersonRow,('lark-company','ou_manager'))
        profile.data={**profile.data,'directory_status':'employed','directory_missing':False,
                      'directory_last_seen_at':datetime.now(timezone.utc).isoformat(),
                      'directory_source':{'app_id':'app-test','record_id':'verified-roster'}}
    assert client.post('/api/workspace/switch',json={'environment':'production'}).status_code==200
    assert client.get('/api/session').json()['environment']=='lark'
    with app.state.sessions() as db:
        profile=db.get(PersonRow,('lark-company','ou_manager')).data
        assert profile['bootstrap_admin'] and profile['identity_app_id']=='app-test'
        row=db.get(WorkspaceRow,'lark-company')
        assert row.data.get('environment') is None
        state=app.state.people_directory._state(db,row)
        assert app.state.people_directory._actor(state,'ou_manager')['id']=='ou_manager'
    assert app.state.people_directory._policy('lark-company')==('app-test','company')
    assert app.state.source_sync._authorize('lark-company','ou_manager')['id']=='ou_manager'
