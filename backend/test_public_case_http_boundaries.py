"""HTTP regression tests use synthetic isolated SQLite, never Lark or cloud data."""
from copy import deepcopy
import json
import time
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from .app import create_app,WorkspaceRow,AuthRow,AuditRow,CacheRow,BusinessRow
from .seed import seed
from .policy import upgrade
from . import storage,audit


@pytest.fixture
def isolated_http(tmp_path):
    app=create_app({'DATABASE_URL':f'sqlite:///{tmp_path}/boundaries.db','UPLOAD_DIR':str(tmp_path/'files'),
        'DEMO_MODE':'false','APP_ENV':'development','SESSION_SECRET':'boundary-only'*4,
        'LARK_WORKER_ORGANIZATION':'boundary','LARK_ALLOWED_TENANTS':'boundary'})
    state=upgrade(seed());state['environment']='production'
    for p in state['projects']:p.update(case_visibility='excluded_history',execution_system='meegle')
    old,new=state['projects'][:2];old['name']='OLD_CASE_SENTINEL';new.update(case_visibility='new_case',execution_system='workbench',name='Current case')
    old['files'].append({'id':'old-file','name':'OLD_CASE_SENTINEL','storage':'local','size':1})
    state['events'].append({'id':'old-event','project_id':old['id'],'message':'OLD_CASE_SENTINEL'})
    state['source_visible_record_ids']=['base|table|recNew']
    source_rows=[{'base_token':'base','table_id':'table','record_id':'recOld','kind':'quote','fields':{'工程名稱':'OLD_CASE_SENTINEL'}},
                 {'base_token':'base','table_id':'table','record_id':'recNew','kind':'quote','fields':{'工程名稱':'Current case'}}]
    state['source_quotes']=[{'id':'old-orphan','source_identity':source_rows[0],'fields':{'工程名稱':'OLD_CASE_SENTINEL'}}]
    state['archived_projects']=[{'id':'old-archive','name':'OLD_CASE_SENTINEL'}]
    with app.state.sessions.begin() as db:
        row=WorkspaceRow(id='lark-boundary',version=state['version'],data={});db.add(row);db.flush()
        row.data=storage.save(db,BusinessRow,row.id,state)
        db.add(AuthRow(id='boundary-session',data={'wid':row.id,'expires':time.time()+3600}))
        db.add(CacheRow(id=row.id,data={'status':'ready','configured':True,'tables':[],'records':source_rows}))
        db.add(audit.record(AuditRow,row.id,'u-manager','task_update',details={'project_id':old['id'],'changes':[
            {'kind':'task','id':'old-task','project_id':old['id'],'after':{'title':'OLD_CASE_SENTINEL'}}]}))
        db.add(audit.record(AuditRow,row.id,'u-manager','task_update',details={'changes':[
            {'kind':'project','id':old['id'],'after':{'name':'OLD_CASE_SENTINEL'}}]}))
        db.add(audit.record(AuditRow,row.id,'u-manager','task_update',details={'project_id':new['id'],'changes':[]}))
    client=TestClient(app)
    def signin(ident):
        client.cookies.set('meegle_session',app.state.signer.dumps({'mode':'lark','sid':'boundary-session','wid':'lark-boundary','uid':ident}))
    signin('u-manager')
    return app,client,state,signin


def test_old_case_never_surfaces_in_ordinary_http_views_or_audit(isolated_http):
    app,client,state,_=isolated_http
    for path in ('/api/workspace','/api/projects','/api/daily-reports','/api/sources','/api/audit'):
        response=client.get(path)
        assert response.status_code==200,(path,response.text)
        assert 'OLD_CASE_SENTINEL' not in response.text,path
    assert client.get('/api/audit').json()['total']==1
    assert client.get('/api/audit?project_id=p1').json()['total']==0
    assert client.get('/api/projects/p1').status_code==404
    assert client.get('/api/files/old-file/download').status_code==404
    assert client.get('/api/projects/p1/file-index.csv').status_code==404
    with app.state.sessions() as db:
        stored=storage.load(db,BusinessRow,db.get(WorkspaceRow,'lark-boundary'))
        assert stored['projects'][0]['name']=='OLD_CASE_SENTINEL'
        assert len(list(db.scalars(select(AuditRow))))==3


def test_history_diagnostics_require_manager_and_do_not_return_archived_payloads(isolated_http):
    _,client,_,signin=isolated_http
    response=client.get('/api/admin/audit/history?project_id=p1')
    assert response.status_code==200 and response.json()['total']==2
    assert 'OLD_CASE_SENTINEL' not in response.text and 'after' not in response.text
    signin('u-pm')
    assert client.get('/api/admin/audit/history').status_code==403
    assert client.get('/api/audit').json()['total']==1


@pytest.mark.parametrize('path',[
    '/api/projects/p2/nodes/p2-sales/inputs','/api/input-revisions/missing/reconcile',
    '/api/input-mappings/missing/verify'])
@pytest.mark.parametrize('body',[None,[],['x'],'text',5,{}, {'version':None},{'version':True},{'version':'1'},{'version':[]}, {'version':-1}])
def test_input_wrong_top_level_and_version_are_422_without_mutation(isolated_http,path,body):
    app,client,_,_=isolated_http
    with app.state.sessions() as db:
        row=db.get(WorkspaceRow,'lark-boundary');before=(row.version,deepcopy(row.data))
    response=client.post(path,content=json.dumps(body),headers={'Content-Type':'application/json'})
    assert response.status_code==422,response.text
    with app.state.sessions() as db:
        row=db.get(WorkspaceRow,'lark-boundary')
        assert (row.version,row.data)==before


@pytest.mark.parametrize('patch',[{'request_id':{}},{'key':{}},{'label':[]}, {'value':float('nan')}])
def test_input_wrong_registration_field_types_are_rejected(isolated_http,patch):
    _,client,state,_=isolated_http
    body={'version':state['version'],'request_id':'2e5b86d1-1778-469d-935d-43d55ce0c822','key':'k','label':'label','value':'valid',**patch}
    response=client.post('/api/projects/p2/nodes/p2-sales/inputs',content=json.dumps(body),headers={'Content-Type':'application/json'})
    assert response.status_code==422,response.text


def test_malformed_input_json_is_422(isolated_http):
    _,client,_,_=isolated_http
    response=client.post('/api/projects/p2/nodes/p2-sales/inputs',content='{',headers={'Content-Type':'application/json'})
    assert response.status_code==422
