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
        'LARK_WORKER_ORGANIZATION':'boundary','LARK_ALLOWED_TENANTS':'boundary',
        'WORKSPACE_SHELL_ENABLED':'true','INDEX_TABLES_ENABLED':'true'})
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


@pytest.mark.parametrize('viewer,admit_hidden', [('u-pm',False),('u-manager',False),('u-manager',True)])
def test_workspace_contract_links_only_name_visible_confirmations(isolated_http,viewer,admit_hidden):
    app,client,_,signin=isolated_http
    with app.state.sessions.begin() as db:
        row=db.get(WorkspaceRow,'lark-boundary');state=storage.load(db,BusinessRow,row)
        state['source_confirmations']=[dict(id=f'base/confirmations/{rid}',project_id='p2',
            source_kind='confirmation',code=code,
            source_identity=dict(base_token='base',table_id='confirmations',record_id=rid))
            for rid,code in [('recVISIBLEA','C115264'),('recHIDDENB','C999777')]]
        state['source_visible_record_ids']+=['base|confirmations|recVISIBLEA','base|contracts|recContract']
        if admit_hidden:state['source_visible_record_ids'].append('base|confirmations|recHIDDENB')
        state['contract_items']=[dict(id='base/contracts/recContract',project_id='p2',title='Visible contract',
            confirmation_ids=['base/confirmations/recVISIBLEA','base/confirmations/recHIDDENB'],
            source_identity=dict(base_token='base',table_id='contracts',record_id='recContract'))]
        row.data=storage.save(db,BusinessRow,row.id,state)
    signin(viewer)
    response=client.get('/api/workspace')
    assert response.status_code==200,response.text
    expected=['base/confirmations/recVISIBLEA']+(['base/confirmations/recHIDDENB'] if admit_hidden else [])
    assert response.json()['contract_items']==[dict(id='base/contracts/recContract',project_id='p2',
        title='Visible contract',confirmation_ids=expected,
        source_identity=dict(base_token='base',table_id='contracts',record_id='recContract'))]
    assert 'recVISIBLEA' in response.text and 'C115264' in response.text
    assert ('recHIDDENB' in response.text)==admit_hidden
    assert ('C999777' in response.text)==admit_hidden
    with app.state.sessions() as db:
        stored=storage.load(db,BusinessRow,db.get(WorkspaceRow,'lark-boundary'))
        assert stored['contract_items'][0]['confirmation_ids']==['base/confirmations/recVISIBLEA','base/confirmations/recHIDDENB']


@pytest.mark.parametrize('enabled',[False,True])
def test_work_item_internal_flags_absent_from_public_routes(isolated_http,enabled):
    app,client,_,_=isolated_http
    with app.state.sessions.begin() as db:
        row=db.get(WorkspaceRow,'lark-boundary');state=storage.load(db,BusinessRow,row)
        state['source_work_items_enabled']=enabled
        state['source_work_items_status']={'p2':{'partial':False}}
        row.data=storage.save(db,BusinessRow,row.id,state)
    for path in ('/api/workspace','/api/workspace?scope=shell','/api/projects/p2',
                 '/api/projects','/api/sources','/api/session','/api/daily-reports'):
        response=client.get(path)
        assert response.status_code==200,(path,response.text)
        assert 'source_work_items_enabled' not in response.text,path
        assert 'source_work_items_status' not in response.text,path
        if path.endswith('scope=shell'):assert response.json()['scope']=='shell'


@pytest.fixture
def linked_sources(isolated_http):
    app,client,_,signin=isolated_http
    with app.state.sessions.begin() as db:
        row=db.get(WorkspaceRow,'lark-boundary');state=storage.load(db,BusinessRow,row)
        def entity(table,rid,pid,code):
            return dict(id=f'base/{table}/{rid}',project_id=pid,code=code,
                source_identity=dict(base_token='base',table_id=table,record_id=rid))
        a,b,c=[f'base/confirmations/{rid}' for rid in ('recA','recHIDDENB','recHIDDENC')]
        state['source_confirmations']=[entity('confirmations',rid,pid,code) for rid,pid,code in
            [('recA','p2','C115264'),('recHIDDENB','p2','C999777'),('recHIDDENC','p1','C888666')]]
        quote=entity('quotes','recQ','p2','Q1');quote['confirmation_ids']=[b,a,c]
        state['source_quotes']=[quote]
        state['contract_items']=[dict(entity('contracts',rid,'p2',rid),confirmation_ids=links)
            for rid,links in [('k1',[a,b]),('k2',[b]),('k3',[b,a])]]
        state['source_visible_record_ids'] += ['base|confirmations|recA','base|confirmations|recHIDDENC',
            'base|quotes|recQ',*[f'base|contracts|k{i}' for i in (1,2,3)]]
        row.data=storage.save(db,BusinessRow,row.id,state)
    return app,client,signin,state


@pytest.mark.parametrize('viewer,admit_hidden',[('u-pm',False),('u-manager',False),('u-manager',True)])
def test_quote_confirmation_links_public_round_trip(linked_sources,viewer,admit_hidden):
    app,client,signin,original=linked_sources
    with app.state.sessions.begin() as db:
        row=db.get(WorkspaceRow,'lark-boundary');state=storage.load(db,BusinessRow,row)
        if admit_hidden:state['source_visible_record_ids'].append('base|confirmations|recHIDDENB')
        row.data=storage.save(db,BusinessRow,row.id,state)
    signin(viewer)
    a,b,c=[f'base/confirmations/{rid}' for rid in ('recA','recHIDDENB','recHIDDENC')]
    expected=[b,a] if admit_hidden else [a]
    workspace=client.get('/api/workspace')
    assert workspace.status_code==200,workspace.text
    body=dict(action='comment_add',project_id='p2',version=workspace.json()['version'],
        request_id='quote-links-roundtrip',payload={'body':'hello'})
    responses=[workspace,client.get('/api/projects/p2'),client.post('/api/actions',json=body),
        client.post('/api/actions',json=body)]
    for response in responses:
        assert response.status_code==200,response.text
        assert response.json()['source_quotes'][0]['confirmation_ids']==expected
        contracts={r['id']:r['confirmation_ids'] for r in response.json()['contract_items']}
        assert contracts['base/contracts/k2']==([b] if admit_hidden else [])
        assert contracts['base/contracts/k3']==([b,a] if admit_hidden else [a])
        for token,visible in [('recHIDDENB',admit_hidden),('C999777',admit_hidden),
                              ('recHIDDENC',False),('C888666',False)]:
            assert (token in response.text)==visible
    with app.state.sessions() as db:
        stored=storage.load(db,BusinessRow,db.get(WorkspaceRow,'lark-boundary'))
        assert stored['source_quotes']==original['source_quotes']
        assert stored['contract_items']==original['contract_items']
