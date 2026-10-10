import json
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from .app import create_app, WorkspaceRow, AuthRow, BusinessRow
from . import storage
from .seed import seed
from .sources import import_sources, number, day
from .workflow import now

@pytest.fixture
def app(tmp_path):
    return create_app({'DATABASE_URL':f'sqlite:///{tmp_path}/test.db','UPLOAD_DIR':str(tmp_path/'uploads'),'SESSION_SECRET':'test-secret'*5,'APP_ENV':'development','DEMO_MODE':'true'})
@pytest.fixture
def client(app):
    c=TestClient(app); assert c.get('/api/session').status_code==200; return c
def workspace(c): return c.get('/api/workspace').json()
def act(c,action,payload=None,task=None,node=None,version=None,request_id=None,project='p1'):
    import uuid
    return c.post('/api/actions',json={'action':action,'version':workspace(c)['version'] if version is None else version,'request_id':request_id or uuid.uuid4().hex,'project_id':project,'node_id':node,'task_id':task,'payload':payload or {}})
def role(c,user): assert c.post('/api/demo/session',json={'user_id':user}).status_code==200
def task(ws,tid): return next(t for p in ws['projects'] for n in p['nodes'] for t in n['tasks'] if t['id']==tid)
def proposal(c,kind='change',ids=None,dates=None):
    r=act(c,'approval_create',{'type':kind,'reason':'業主設計調整','title':'控制點變更','task_ids':ids or ['p1-control-t1'],'dates':dates or []}); assert r.status_code==200,r.text
    return r.json()['approvals'][0]['id']

def test_seed_owner_gate_outputs_proxy_and_dependencies(app,client):
    assert len(workspace(client)['projects'])==7
    assert act(client,'task_complete',{'output':'成果'},task='p1-control-t1').status_code==403
    role(client,'u-manager'); assert act(client,'task_complete',{'output':'成果'},task='p1-control-t1').status_code==403
    deputy={'principal_id':'u-control','delegate_id':'u-agent','seat':'owner','scope':'tasks','source':'approval','task_ids':['p1-control-t1'],'approval_instance_id':'verified-leave','start_date':'2026-09-01','end_date':'2099-12-31','qualified':True,'qualification_note':'測試主管資格確認','qualification_evidence':'已核定能力紀錄'}
    # A client supplied approval code cannot establish authority on its own.
    assert act(client,'delegation_set',deputy).status_code==409
    wid=app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
    with app.state.sessions.begin() as db:
        row=db.get(WorkspaceRow,wid); state=storage.load(db,BusinessRow,row)
        state['approved_leave_delegations']=[{'id':'verified-leave','principal_id':'u-control','delegate_id':'u-agent','from':'2026-09-01T00:00:00+08:00','to':'2099-12-31T23:59:59+08:00','status':'APPROVED','verified_at':now(),'approval_code':'leave-definition'}]
        row.data=storage.save(db,BusinessRow,wid,state)
    assert act(client,'delegation_set',deputy).status_code==200
    role(client,'u-agent'); assert act(client,'task_complete',{},task='p1-control-t1').status_code==400
    assert act(client,'task_complete',{'output':'平差報告 v1'},task='p1-control-t1').status_code==200
    role(client,'u-control'); assert act(client,'task_start',task='p3-control-t1',project='p3').status_code==409
    assert act(client,'node_complete',node='p1-control').status_code==409

def assign_demo_manager_as_pm(client):
    """Explicit business assignment; system manager alone has no case authority."""
    app=client.app
    wid=app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
    with app.state.sessions.begin() as db:
        row=db.get(WorkspaceRow,wid); state=storage.load(db,BusinessRow,row)
        state['projects'][0]['pm_id']='u-manager'
        row.data=storage.save(db,BusinessRow,wid,state)


def test_change_only_same_work_item_downstream_revisions(client):
    aid=proposal(client); r=act(client,'approval_submit',{'approval_id':aid}); assert r.status_code==200
    ws=r.json(); assert task(ws,'p1-control-t1')['status']=='paused'; assert task(ws,'p1-mapping-t1')['status']=='paused'
    assert task(ws,'p1-control-t2')['status']=='pending'; assert task(ws,'p1-field-t1')['status']=='completed'
    role(client,'u-control'); assert act(client,'task_start',task='p1-control-t3').status_code==409
    assign_demo_manager_as_pm(client); role(client,'u-manager')
    assert act(client,'approval_lark',{'approval_id':aid,'result':'approved'}).json()['approvals'][0]['status']=='pending'
    assert act(client,'approval_execute',{'approval_id':aid}).status_code==409
    for party in ('owner','client'): assert act(client,'approval_confirm',{'approval_id':aid,'party':party}).status_code==200
    result=act(client,'approval_execute',{'approval_id':aid},request_id='execute-once'); assert result.status_code==200,result.text
    ws=result.json(); assert task(ws,'p1-control-t1')['status']=='superseded'
    replacements=[t for p in ws['projects'] for n in p['nodes'] for t in n['tasks'] if t.get('replaces_task_id')=='p1-control-t1']
    assert len(replacements)==1 and replacements[0]['revision']==2
    assert act(client,'approval_execute',{'approval_id':aid},request_id='execute-once',version=1).status_code==200
    assert act(client,'approval_execute',{'approval_id':aid}).status_code==409

def test_rejection_keeps_pause_until_explicit_resume(client):
    aid=proposal(client); act(client,'approval_submit',{'approval_id':aid}); assign_demo_manager_as_pm(client); role(client,'u-manager')
    r=act(client,'approval_lark',{'approval_id':aid,'result':'rejected'}); assert task(r.json(),'p1-control-t1')['status']=='paused'
    assert act(client,'change_resume',{'approval_id':aid}).status_code==400
    r=act(client,'change_resume',{'approval_id':aid,'reason':'回到原設計繼續'}); assert r.status_code==200; assert task(r.json(),'p1-control-t1')['status']=='in_progress'

def test_extension_does_not_freeze_preserves_original_and_requires_approval(client):
    original=task(workspace(client),'p1-control-t1')['due_date']
    assert act(client,'task_update',{'due_date':'2026-10-20'},task='p1-control-t1').status_code==409
    aid=proposal(client,'extension',dates=[{'task_id':'p1-control-t1','due_date':'2026-10-20'}]); act(client,'approval_submit',{'approval_id':aid})
    assert task(workspace(client),'p1-control-t1')['status']=='in_progress'
    assign_demo_manager_as_pm(client); role(client,'u-manager'); act(client,'approval_lark',{'approval_id':aid,'result':'approved'}); result=act(client,'approval_execute',{'approval_id':aid})
    t=task(result.json(),'p1-control-t1'); assert t['due_date']=='2026-10-20' and t['original_due_date']==original

def test_initial_schedule_assignment_history_and_replay(client):
    result=act(client,'task_add',{'title':'補充 SOP','owner_id':'u-control'},node='p1-control'); assert result.status_code==200
    tid=result.json()['events'][0]['task_id']
    result=act(client,'task_update',{'due_date':'2026-10-01','start_date':'2026-09-30'},task=tid,request_id='schedule-once'); assert result.status_code==200
    version=result.json()['version']; assert task(result.json(),tid)['original_due_date']=='2026-10-01'
    assert act(client,'task_update',{'due_date':'2026-10-01','start_date':'2026-09-30'},task=tid,request_id='schedule-once',version=1).json()['version']==version
    assert act(client,'task_update',{'title':'different'},task=tid,request_id='schedule-once').status_code==409
    assert act(client,'comment_add',{'body':'stale'},version=1).status_code==409
    result=act(client,'participants_update',{'nodes':[{'node_id':'p1-control','owner_id':'u-agent','collaborator_ids':[]}]})
    assert task(result.json(),tid)['owner_id']=='u-control'

def test_restart_and_demo_isolation(app,client,tmp_path):
    assert act(client,'comment_add',{'body':'重新啟動仍保留'}).status_code==200
    restarted=create_app({'DATABASE_URL':f'sqlite:///{tmp_path}/test.db','UPLOAD_DIR':str(tmp_path/'uploads'),'SESSION_SECRET':'test-secret'*5,'APP_ENV':'development','DEMO_MODE':'true'})
    c2=TestClient(restarted); c2.cookies.update(client.cookies); assert workspace(c2)['projects'][0]['comments'][0]['body']=='重新啟動仍保留'
    isolated=TestClient(app); isolated.get('/api/session'); assert workspace(isolated)['projects'][0]['comments']==[]
    assert isolated.get('/api/sources').json()['records']==[]; assert isolated.post('/api/sources/sync').status_code==403
    assert isolated.post('/api/actions',headers={'origin':'https://evil.invalid'},json={}).status_code==403

def test_upload_private_safe_name_and_version(app,client):
    response=client.post('/api/files',data={'project_id':'p1','node_id':'p1-control','direction':'output','version':workspace(client)['version']},files={'file':('../../outside.txt',b'control deliverable','text/plain')})
    assert response.status_code==200,response.text
    f=response.json()['projects'][0]['files'][0]; assert f['name']=='outside.txt'
    assert client.get(f['url']).content==b'control deliverable'
    anonymous=TestClient(app); assert anonymous.get(f['url']).status_code==401
    anonymous.get('/api/session'); assert anonymous.get(f['url']).status_code==404
    role(client,'u-map'); response=client.post('/api/files',data={'project_id':'p1','node_id':'p1-control','direction':'output','version':workspace(client)['version']},files={'file':('x.txt',b'x')}); assert response.status_code==403

def test_production_config_and_oauth_state(tmp_path):
    with pytest.raises(RuntimeError): create_app({'APP_ENV':'production','DEMO_MODE':'false','DATABASE_URL':'sqlite://','SESSION_SECRET':'x'*40})
    a=create_app({'DATABASE_URL':f'sqlite:///{tmp_path}/auth.db','UPLOAD_DIR':str(tmp_path/'u'),'APP_ENV':'development','DEMO_MODE':'false','LARK_APP_ID':'test','LARK_APP_SECRET':'test','LARK_REDIRECT_URI':'https://example.org/api/auth/lark/callback','LARK_ALLOWED_TENANTS':'tenant'})
    c=TestClient(a); assert c.get('/api/session').json()['user'] is None; assert c.get('/api/workspace').status_code==401
    assert c.post('/api/demo/session',json={'user_id':'u-manager'}).status_code==403
    assert c.get('/api/auth/lark/callback?state=forged&code=fake').status_code==400
    r=c.get('/api/auth/lark/login',follow_redirects=False); assert 'app_id=test' in r.headers['location']

def test_lark_oauth_denial_returns_safe_actionable_error_redirect(tmp_path):
    from urllib.parse import parse_qs,urlparse
    cfg={'DATABASE_URL':f'sqlite:///{tmp_path}/oauth-denial.db','UPLOAD_DIR':str(tmp_path/'u'),
         'APP_ENV':'development','DEMO_MODE':'false','SESSION_SECRET':'oauth-denial-test'*4,
         'LARK_APP_ID':'test','LARK_APP_SECRET':'test','LARK_REDIRECT_URI':'https://example.org/api/auth/lark/callback',
         'LARK_ALLOWED_TENANTS':'tenant'}
    client=TestClient(create_app(cfg))
    login=client.get('/api/auth/lark/login',follow_redirects=False)
    state=parse_qs(urlparse(login.headers['location']).query)['state'][0]
    denied=client.get('/api/auth/lark/callback',params={'state':state,'error':'access_denied',
        'error_description':'synthetic private provider detail'},follow_redirects=False)
    assert denied.status_code==303
    assert denied.headers['location']=='/?auth_error=authorization_denied'
    assert 'synthetic' not in denied.headers['location']
    assert 'lark_oauth_state' in denied.headers.get('set-cookie','')

def test_source_normalization_formula_values_repeated_sync_and_manual_protection():
    ws=seed(True)
    def rec(kind,ident,fields): return {'kind':kind,'base_token':'base','table_id':kind,'record_id':ident,'fields':fields}
    records=[rec('quote','q1',{'工程編號':'C115001','報價編號':'115001','工程名稱':'真實来源範例','行號單位':'測試業主','契約價格(未稅)':[{'text':'12345','type':'text'}]}),rec('reporting','t1',{'所屬案件':[{'text':'115001'}],'工項類別':'控制','工項名稱':'控制平差','對應營業額':[{'text':'3.5'}],'來源合約明細（日報關聯）':{'link_record_ids':['c1']}}),rec('daily','d1',{'案件編號':[{'text':'C115001'}],'工作日期-營業額明細':1790251200000,'營業額組別-明細':[{'text':'控制組'}],'姓名':[{'text':'測試成員'}],'營業額點數':[{'text':'1.5'}]})]
    records[0]=rec('confirmation','q1',{'工程確認單編號':'C115001','所屬案件':'115001','工程名稱':'真實來源範例','合約總額':12345,'狀態':'執行中'})
    import_sources(ws,records); assert len(ws['projects'])==1
    p=ws['projects'][0]; t=p['nodes'][4]['tasks'][-1]; assert p['contract_amount'] is None and p['source_finance']['合約總額']==12345 and t['points']==3.5; assert p['daily_reports'][0]['department']=='控制組'
    import_sources(ws,records); assert len(ws['projects'])==1 and len(p['nodes'][4]['tasks'])==3
    t['manual_updated']=True; t['title']='人工編輯'; t['due_date']='2026-11-01'; records[1]['fields']['工項名稱']='上游新版'
    import_sources(ws,records); assert t['title']=='人工編輯' and t['due_date']=='2026-11-01' and t['source_change_pending']
    assert not any(x['id'].startswith('p1') for x in ws['projects'])
    assert p['daily_reports'][0]['source_url']=='https://yong-xiang-survey.jp.larksuite.com/base/base?table=daily&record=d1'

def test_connector_pagination_projection_and_permission_error(monkeypatch):
    import httpx
    from .sources import fetch_sources
    from fastapi import HTTPException
    monkeypatch.setenv('LARK_V4_BASE_TOKEN','base')
    monkeypatch.setenv('LARK_SOURCE_TABLES_JSON',json.dumps([{'name':'confirmation','base_token':'base','table_id':'table','kind':'confirmation','field_names':['工程名稱','契約價格(未稅)']}]))
    calls=[]
    class MockClient:
        def __init__(self,**kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def get(self,url,headers,params):
            calls.append((url,deepcopy(params)))
            if url.endswith('/fields'):
                return httpx.Response(200,json={'code':0,'data':{'items':[{'field_name':'工程名稱'},{'field_name':'契約價格(未稅)'}],'has_more':False}})
            items=[{'record_id':'r2' if params.get('page_token') else 'r1','fields':{'工程名稱':'測試'}}]
            return httpx.Response(200,json={'code':0,'data':{'items':items,'has_more':not bool(params.get('page_token')),'page_token':'next'}})
    monkeypatch.setattr('backend.sources.httpx.Client',MockClient)
    result=fetch_sources('fake-token'); assert len(result['records'])==2 and result['status']=='ready'
    assert len(calls)==3; assert json.loads(calls[1][1]['field_names'])==['工程名稱','契約價格(未稅)']
    class Denied(MockClient):
        def get(self,*args,**kwargs): return httpx.Response(200,json={'code':1254302})
    monkeypatch.setattr('backend.sources.httpx.Client',Denied)
    with pytest.raises(HTTPException) as exc: fetch_sources('fake-token')
    assert exc.value.status_code==403 and '1254302' in exc.value.detail

def test_oauth_verified_identity_tenant_and_role_isolation(tmp_path,monkeypatch):
    import httpx
    from urllib.parse import urlparse, parse_qs
    cfg={'DATABASE_URL':f'sqlite:///{tmp_path}/oauth.db','UPLOAD_DIR':str(tmp_path/'u'),'APP_ENV':'development','DEMO_MODE':'true','SESSION_SECRET':'oauth-test'*5,'LARK_APP_ID':'test','LARK_APP_SECRET':'test','LARK_REDIRECT_URI':'https://example.org/api/auth/lark/callback','LARK_ALLOWED_TENANTS':'company','LARK_ROLE_MAP_JSON':'{"ou_manager":"manager"}'}
    cfg['LARK_WORKER_ORGANIZATION']='company'
    app=create_app(cfg); client=TestClient(app); client.get('/api/session')
    class OAuthClient:
        def __init__(self,**kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def post(self,url,**kwargs): return httpx.Response(200,json={'access_token':'server-secret-token','expires_in':3600},request=httpx.Request('POST',url))
        def get(self,url,**kwargs): return httpx.Response(200,json={'code':0,'data':{'open_id':'ou_manager','name':'公司主管','tenant_key':'company'}},request=httpx.Request('GET',url))
    monkeypatch.setattr('backend.app.httpx.Client',OAuthClient)
    response=client.get('/api/auth/lark/login',follow_redirects=False); state=parse_qs(urlparse(response.headers['location']).query)['state'][0]
    response=client.get('/api/auth/lark/callback',params={'state':state,'code':'valid'},follow_redirects=False); assert response.status_code==307
    assert client.get('/api/session').json()['user']['role']=='manager'
    assert client.get('/api/workspace').status_code==403
    # OAuth bootstrap alone grants repair access, not business access. Simulate
    # a fresh authoritative roster result before exercising ordinary isolation.
    from .app import PersonRow
    from .workflow import now
    with app.state.sessions.begin() as db:
        profile=db.get(PersonRow,('lark-company','ou_manager'))
        profile.data={**profile.data,'directory_status':'employed','directory_missing':False,
            'directory_source':{'app_id':'test','record_id':'verified-record'},'directory_last_seen_at':now()}
    assert workspace(client)['projects']==[] and len(workspace(client)['users'])==1
    assert 'server-secret-token' not in client.cookies.get('meegle_session')
    assert client.post('/api/demo/session',json={'user_id':'u-manager'}).status_code==403
    assert client.get('/api/auth/lark/callback',params={'state':state,'code':'replay'},follow_redirects=False).status_code==400
    # Environment role maps are a one-time migration, DB identity remains authoritative.
    downgraded=create_app({**cfg,'LARK_ROLE_MAP_JSON':'{}'})
    existing=TestClient(downgraded); existing.cookies.update(client.cookies)
    assert existing.get('/api/session').json()['user']['role']=='manager'
    session=existing.get('/api/session').json()
    assert session['environment']=='lark'  # Session namespace label; workspace uses production.
    assert session['workspace_id']=='lark-company'
    assert workspace(existing)['environment']=='production'
    with downgraded.state.sessions() as db:
        assert db.get(PersonRow,('lark-company','ou_manager')).data['default_workspace']=='production'
    response=existing.post('/api/sources/sync')
    assert response.status_code==503,response.text
    assert response.json()['detail']=='公司背景唯讀連線尚未設定'
    first=create_app({**cfg,'DATABASE_URL':f'sqlite:///{tmp_path}/first.db','DEMO_MODE':'false','LARK_ROLE_MAP_JSON':'{}'})
    first_client=TestClient(first)
    login=first_client.get('/api/auth/lark/login',follow_redirects=False)
    first_state=parse_qs(urlparse(login.headers['location']).query)['state'][0]
    # Company tenant membership alone must not admit an unverified employee.
    assert first_client.get('/api/auth/lark/callback',params={'state':first_state,'code':'valid'},follow_redirects=False).status_code==403
    assert first_client.get('/api/session').json()['user'] is None

def test_changed_revision_updates_dependency_references(client):
    aid=proposal(client); act(client,'approval_submit',{'approval_id':aid}); assign_demo_manager_as_pm(client); role(client,'u-manager')
    for party in ('owner','client'): act(client,'approval_confirm',{'approval_id':aid,'party':party})
    act(client,'approval_lark',{'approval_id':aid,'result':'approved'}); ws=act(client,'approval_execute',{'approval_id':aid}).json()
    active=[t for n in ws['projects'][0]['nodes'] for t in n['tasks'] if t['status']!='superseded']
    replacement=next(t for t in active if t.get('replaces_task_id')=='p1-mapping-t1')
    predecessor=next(t for t in active if t.get('replaces_task_id')=='p1-control-t3')
    assert replacement['input_task_ids']==[predecessor['id']]

def test_inherited_assignment_updates_but_explicit_owner_and_completed_work_remain(client):
    assert act(client,'task_update',{'owner_id':'u-control'},task='p1-control-t2').status_code==200
    result=act(client,'participants_update',{'nodes':[{'node_id':'p1-control','owner_id':'u-agent','collaborator_ids':[]}]})
    assert result.status_code==200
    ws=result.json(); assert task(ws,'p1-control-t1')['owner_id']=='u-agent'
    assert task(ws,'p1-control-t3')['owner_id']=='u-agent'
    assert task(ws,'p1-control-t2')['owner_id']=='u-control'
    assert task(ws,'p1-control-t2')['owner_inherited'] is False
    result=act(client,'participants_update',{'nodes':[{'node_id':'p1-field','owner_id':'u-agent','collaborator_ids':[]}]})
    assert task(result.json(),'p1-field-t1')['owner_id']=='u-field'

def test_live_submit_fails_without_mutating_draft_or_freezing_work(tmp_path):
    import time
    app=create_app({'DATABASE_URL':f'sqlite:///{tmp_path}/live.db','UPLOAD_DIR':str(tmp_path/'uploads'),
                    'SESSION_SECRET':'live-test-secret'*4,'APP_ENV':'development','DEMO_MODE':'false',
                    'LARK_WORKER_ORGANIZATION':'test','LARK_ALLOWED_TENANTS':'test'})
    live=seed(); live['environment']='production'
    for project in live['projects']:
        project.update(source_kind='lark',execution_system='workbench',case_visibility='new_case')
    with app.state.sessions.begin() as db:
        db.add(WorkspaceRow(id='lark-test',version=1,data=live))
        db.add(AuthRow(id='live-test-session',data={'wid':'lark-test','expires':time.time()+3600,'access_token':'never-used'}))
    c=TestClient(app); c.cookies.set('meegle_session',app.state.signer.dumps({'mode':'lark','uid':'u-pm','wid':'lark-test','sid':'live-test-session'}))
    aid=proposal(c); version=workspace(c)['version']
    response=act(c,'approval_submit',{'approval_id':aid}); assert response.status_code==503
    ws=workspace(c); assert ws['version']==version and ws['approvals'][0]['status']=='draft'
    assert ws['approvals'][0]['frozen'] is False and task(ws,'p1-control-t1')['status']=='in_progress'
    role_cookie=c.cookies.get('meegle_session'); assert role_cookie

def test_deadline_advance_requires_approval_preserves_original(client):
    original=task(workspace(client),'p1-control-t1')['due_date']
    assert act(client,'task_update',{'due_date':'2026-09-23'},task='p1-control-t1').status_code==409
    aid=proposal(client,'extension',dates=[{'task_id':'p1-control-t1','due_date':'2026-09-23'}])
    act(client,'approval_submit',{'approval_id':aid}); assign_demo_manager_as_pm(client); role(client,'u-manager')
    act(client,'approval_lark',{'approval_id':aid,'result':'approved'})
    response=act(client,'approval_execute',{'approval_id':aid}); assert response.status_code==200
    t=task(response.json(),'p1-control-t1'); assert t['due_date']=='2026-09-23' and t['original_due_date']==original
    response=act(client,'approval_create',{'type':'extension','reason':'invalid','task_ids':['p1-control-t1'],'dates':[{'task_id':'p1-control-t1','due_date':'2026-09-01'}]})
    assert response.status_code==400

def test_sqlite_parent_directory_created(tmp_path):
    nested=tmp_path/'missing'/'directory'/'workspace.db'
    a=create_app({'DATABASE_URL':f'sqlite:///{nested}','UPLOAD_DIR':str(tmp_path/'uploads'),'APP_ENV':'development','DEMO_MODE':'true'})
    assert nested.is_file() and TestClient(a).get('/api/health').status_code==200

def test_v4_cost_joins_resolve_real_dates_groups_and_canonical_case():
    from datetime import datetime, timezone
    from .sources import link_ids
    ws=seed(True)
    def rec(kind,ident,fields,table=None,**extra): return dict(kind=kind,base_token='base',table_id=table or kind,record_id=ident,fields=fields,**extra)
    day_ms=int(datetime(2026,9,24,16,tzinfo=timezone.utc).timestamp()*1000)
    records=[
        rec('quote','recQuote',{'工程編號':'C115236','報價編號':'115547','工程名稱':'V4 實案映射'}),
        rec('confirmation','recConfirm',{'工程確認單編號':'C115236','所屬案件':'115547'}),
        rec('cost','recOutdoorCost',{'工作日期':day_ms,'組別':'地形A','組長帳號-津貼自動化':[{'id':'ou1','name':'外業組長'}]},table='outCost'),
        rec('cost','recIndoorCost',{'工作日期':day_ms,'內業組別':'控制','填報帳號':{'id':'ou2','name':'控制人員'}},table='inCost'),
        rec('daily','recOutdoor',{'案件編號':[{'text':'115547'}],'所屬案件':['recConfirm'],'所屬成本單':['recOutdoorCost'],'工作日期-薪資':[{'text':str(day_ms)}],'最終營業額點數':[{'text':'0'}],'營業額點數':10},table='outDaily',department='外業組',cost_table_id='outCost'),
        rec('daily','recIndoor',{'所屬案件':{'link_record_ids':['recConfirm']},'所屬成本單':[{'record_id':'recIndoorCost'}],'姓名':[{'text':'控制人員'}]},table='inDaily',cost_table_id='inCost')]
    mapping=import_sources(ws,records); assert mapping['daily_imported']==2 and mapping['daily_missing_date']==0
    reports=ws['projects'][0]['daily_reports']; outdoor=next(r for r in reports if r['department']=='外業組'); indoor=next(r for r in reports if r['department']=='控制組')
    assert outdoor['date']==indoor['date']=='2026-09-25'
    assert outdoor['case_code']==indoor['case_code']=='C115236' and outdoor['source_case_code']=='115547'
    assert outdoor['source_department']=='地形A' and outdoor['person']=='外業組長'
    assert outdoor['points']==0 and indoor['person']=='控制人員'
    assert all(t['status']=='pending' for n in ws['projects'][0]['nodes'] for t in n['tasks'])
    assert link_ids({'text':'顯示值','record_ids':['recA','recB']})==['recA','recB']

def test_v4_mixed_indoor_team_uses_linked_work_item_category_and_conflicts_are_unknown():
    ws=seed(True)
    def rec(kind,ident,fields,table=None,base='base',**extra): return dict(kind=kind,base_token=base,table_id=table or kind,record_id=ident,fields=fields,**extra)
    records=[rec('confirmation','recQuote',{'工程確認單編號':'C1','工程名稱':'映射驗證'}),
      rec('reporting','recReport',{'所屬案件':'C1','工項類別':'圖資','工項名稱':'製圖'}),
      rec('cost','recCost',{'工作日期':'2026-09-24','內業組別':'圖報A'},table='costA'),
      rec('cost','recCost',{'工作日期':'2026-01-01','內業組別':'控制'},table='costB'),
      rec('cost','recCost',{'工作日期':'2025-01-01','內業組別':'控制'},table='costA',base='unrelated'),
      rec('daily','recDaily',{'內業工項':['recReport'],'所屬成本單':['recCost']},cost_table_id='costA')]
    mapping=import_sources(ws,records); report=ws['projects'][0]['daily_reports'][0]
    assert report['department']=='圖資組' and report['source_department']=='圖報A' and report['description']=='製圖'
    assert report['date']=='2026-09-24' and mapping['daily_missing_date']==0
    records[-1]['fields']['工作日期-薪資']='2026-09-25'
    mapping=import_sources(ws,records); report=ws['projects'][0]['daily_reports'][0]
    assert report['date']=='' and report['mapping_status']=='conflicting_dates' and mapping['daily_conflicting_dates']==1
    del records[-1]['cost_table_id']; del records[-1]['fields']['工作日期-薪資']
    mapping=import_sources(ws,records); assert mapping['daily_missing_date']==1

def test_v4_missing_and_ambiguous_project_mapping_is_reported():
    ws=seed(True)
    records=[{'kind':'quote','base_token':'base','table_id':'quote','record_id':rid,'fields':{'工程編號':'C1','工程名稱':'重複業務碼'}} for rid in ('recA','recB')]
    records.append({'kind':'daily','base_token':'base','table_id':'daily','record_id':'recDaily','fields':{'案件編號':'C1','工作日期-薪資':'2026-09-25'}})
    result=import_sources(ws,records); assert result['daily_unmatched']==1
    assert all(not project['daily_reports'] for project in ws['projects'])

def test_oauth_scope_parameter_is_explicit_minimal_and_configurable(tmp_path):
    from urllib.parse import urlparse, parse_qs
    cfg={'DATABASE_URL':f'sqlite:///{tmp_path}/scope.db','UPLOAD_DIR':str(tmp_path/'uploads'),'APP_ENV':'development','DEMO_MODE':'false','LARK_APP_ID':'test','LARK_APP_SECRET':'test','LARK_REDIRECT_URI':'https://example.org/callback','LARK_ALLOWED_TENANTS':'company'}
    for value,expected in [(None,'bitable:app:readonly'),('bitable:app:readonly, approval:approval:readonly bitable:app:readonly','bitable:app:readonly approval:approval:readonly')]:
        a=create_app({**cfg,**({'LARK_OAUTH_SCOPES':value} if value else {})})
        result=TestClient(a).get('/api/auth/lark/login',follow_redirects=False)
        query=parse_qs(urlparse(result.headers['location']).query)
        assert query['scope']==[expected] and query['response_type']==['code'] and query['app_id']==['test']
    with pytest.raises(RuntimeError): create_app({**cfg,'LARK_ROLE_MAP_JSON':'{"ou_user":"administrator"}'})

def test_native_approval_refresh_uses_official_user_endpoint(app,monkeypatch):
    import time
    import httpx
    live=seed(); live['projects'][0]['source_kind']='lark'
    app.state.cfg.update(LARK_WORKER_ORGANIZATION='approval-test',LARK_ALLOWED_TENANTS='approval-test')
    live['environment']='production'
    for project in live['projects']:
        project.update(case_visibility='new_case',execution_system='workbench')
    with app.state.sessions.begin() as db:
        db.add(WorkspaceRow(id='lark-approval-test',version=1,data=live))
        db.add(AuthRow(id='approval-session',data={'wid':'lark-approval-test','expires':time.time()+3600,'access_token':'user-token'}))
    c=TestClient(app); c.cookies.set('meegle_session',app.state.signer.dumps({'mode':'lark','uid':'u-pm','wid':'lark-approval-test','sid':'approval-session'}))
    aid=proposal(c); requests=[]
    class ReadClient:
        def __init__(self,**kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def get(self,url,headers,params):
            requests.append((url,headers,params))
            return httpx.Response(200,json={'code':0,'data':{'instance_code':'EXISTING_123','definition_code':'definition','status':'APPROVED'}})
    monkeypatch.setattr('backend.app.httpx.Client',ReadClient)
    response=c.post('/api/approvals/'+aid+'/refresh',json={'version':workspace(c)['version'],'instance_code':'EXISTING_123'})
    assert response.status_code==200,response.text
    assert requests[0][0]=='https://open.larksuite.com/open-apis/approval/v4/instances/detail'
    assert requests[0][1]['Authorization']=='Bearer user-token'
    assert requests[0][2]=={'instance_code':'EXISTING_123','locale':'zh-TW','user_id_type':'open_id'}
    approval=response.json()['approvals'][0]
    assert approval['status']=='draft' and approval['lark_external_status']=='APPROVED' and approval['lark_binding_verified'] is False


def test_source_pagination_limit_is_explicit_and_invalid_cursors_fail(monkeypatch):
    import httpx
    from fastapi import HTTPException
    from .sources import fetch_sources
    monkeypatch.setenv('LARK_V4_BASE_TOKEN','base')
    monkeypatch.setenv('LARK_SOURCE_TABLES_JSON',json.dumps([{'base_token':'base','table_id':'confirmation','kind':'confirmation'}]))
    monkeypatch.setenv('LARK_SOURCE_MAX_PAGES','1')
    mode='partial'; calls=[]
    class ReadClient:
        def __init__(self,**kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def get(self,url,headers,params):
            calls.append((url,dict(params)))
            if url.endswith('/fields'):
                payload={'items':[{'field_name':'工程名稱','property':None}],'has_more':mode=='schema_limit','page_token':str(len(calls))}
            else:
                payload={'items':[{'record_id':'rec'+str(len(calls)),'fields':{}}],'has_more':True,'page_token':None if mode=='missing' else 'constant'}
            return httpx.Response(200,json={'code':0,'data':payload})
    monkeypatch.setattr('backend.sources.httpx.Client',ReadClient)
    result=fetch_sources('user-token')
    assert result['status']=='partial' and result['tables'][0]['status']=='partial'
    assert result['tables'][0]['pages_read']==1 and result['tables'][0]['record_limit']==200
    assert calls[-1][1]['user_id_type']=='open_id'
    for mode in ('missing','repeated','schema_limit'):
        calls.clear(); monkeypatch.setenv('LARK_SOURCE_MAX_PAGES','3')
        with pytest.raises(HTTPException) as exc: fetch_sources('user-token')
        assert exc.value.status_code==502
        assert all('/fields' in url for url,_ in calls) if mode=='schema_limit' else True
    monkeypatch.setenv('LARK_SOURCE_MAX_PAGES','invalid')
    with pytest.raises(HTTPException) as exc: fetch_sources('user-token')
    assert exc.value.status_code==503


def test_provisional_daily_case_is_exact_unique_and_keeps_source_unconfirmed():
    from .sources import PROVISIONAL_CASE_FIELD
    def rec(kind,rid,fields): return dict(kind=kind,record_id=rid,table_id=kind,base_token='base',fields=fields)
    records=[rec('confirmation','recQuote',{'工程確認單編號':'C000001-6','工程名稱':'匿名測試工程'}),
             rec('cost','recCost',{'工作日期':'2026-09-25','內業組別':'控制'}),
             rec('daily','recDaily',{'所屬案件':[{'table_id':'confirmation','type':'text','text_arr':[]}],
                 '內業工項':[{'table_id':'reporting','type':'text','text_arr':[]}],
                 '所屬成本單':[{'record_ids':['recCost'],'table_id':'cost'}],
                 PROVISIONAL_CASE_FIELD:'\u200bC000001-6\ufeff\u00a0'})]
    ws=seed(True); stats=import_sources(ws,records)
    assert stats['daily_imported']==1 and stats['daily_provisional']==1 and stats['daily_unmatched']==0
    report=ws['projects'][0]['daily_reports'][0]
    assert report['case_code']=='C000001-6' and report['department']=='控制組' and report['date']=='2026-09-25'
    assert report['match_basis']==report['mapping_status']=='provisional_case_code'
    assert all(t['status']=='pending' for n in ws['projects'][0]['nodes'] for t in n['tasks'])
    # Full suffix is part of identity; a near match must remain unmatched.
    records[-1]['fields'][PROVISIONAL_CASE_FIELD]='C000001'
    other=seed(True); assert import_sources(other,records)['daily_unmatched']==1
    assert import_sources(ws,records)['daily_unmatched']==1
    assert ws['projects'][0]['daily_reports']==[]  # old tentative evidence must not survive a changed code
    # Same confirmation code is one case; differing content stays visible as a conflict.
    records[-1]['fields'][PROVISIONAL_CASE_FIELD]='C000001-6'
    records.append(rec('confirmation','recDuplicate',{'工程確認單編號':'C000001-6','工程名稱':'另一來源版本'}))
    other=seed(True); assert import_sources(other,records)['daily_imported']==1
    assert len(other['projects'])==1 and '工程名稱' in other['projects'][0]['source_conflicts']


def test_provisional_case_never_overrides_unresolved_formal_reference():
    from .sources import PROVISIONAL_CASE_FIELD
    quote={'kind':'confirmation','record_id':'recQuote','table_id':'confirmation','base_token':'base','fields':{'工程確認單編號':'C000001-6','工程名稱':'匿名測試'}}
    for formal in ({'案件編號':'C999999'}, {'所屬案件':['recUnknown']}, {'內業工項':['recUnknown']}):
        daily={'kind':'daily','record_id':'recDaily','table_id':'daily','base_token':'base','fields':{PROVISIONAL_CASE_FIELD:'C000001-6',**formal}}
        stats=import_sources(seed(True),[quote,daily])
        assert stats['daily_provisional']==0 and stats['daily_unmatched']==1


def test_gzip_large_workspace_and_authenticated_sources_preserves_json_and_access(app,client,monkeypatch):
    import time
    from . import workflow
    # Compare transport encodings at the same authorization observation time.
    checked_at=workflow.now(); monkeypatch.setattr(workflow,'now',lambda:checked_at)
    from datetime import datetime
    app.state.live_read.clock=lambda:datetime.fromisoformat(checked_at)
    from .app import CacheRow
    compressed=client.get('/api/workspace',headers={'Accept-Encoding':'gzip'})
    plain=client.get('/api/workspace',headers={'Accept-Encoding':'identity'})
    assert compressed.status_code==plain.status_code==200
    assert compressed.headers.get('content-encoding')=='gzip' and 'content-encoding' not in plain.headers
    assert compressed.json()==plain.json()
    assert int(compressed.headers['content-length'])<len(compressed.content)
    cache={'configured':True,'status':'ready','records':[{'base_token':'base','table_id':'quote','kind':'quote','record_id':f'rec{i}','fields':{'工程名稱':'匿名測試資料'}} for i in range(100)]}
    app.state.cfg.update(LARK_WORKER_ORGANIZATION='compression',LARK_ALLOWED_TENANTS='compression')
    with app.state.sessions.begin() as db:
        state=seed();state['environment']='production'
        state['source_visible_record_ids']=[f'base|quote|rec{i}' for i in range(100)]
        db.add(WorkspaceRow(id='lark-compression',version=1,data=state))
        db.add(AuthRow(id='compression-session',data={'wid':'lark-compression','expires':time.time()+3600,'access_token':'unused'}))
        db.add(CacheRow(id='lark-compression',data=cache))
    live=TestClient(app); live.cookies.set('meegle_session',app.state.signer.dumps({'mode':'lark','uid':'u-pm','wid':'lark-compression','sid':'compression-session'}))
    compressed=live.get('/api/sources',headers={'Accept-Encoding':'gzip'})
    plain=live.get('/api/sources',headers={'Accept-Encoding':'identity'})
    assert compressed.status_code==200 and compressed.headers.get('content-encoding')=='gzip'
    from .source_case_policy import visible_source_snapshot
    from .workspace_projection import public_source_cache
    freshness=app.state.live_read.status('lark-compression')
    expected={**public_source_cache(visible_source_snapshot(state,cache)),
              'as_of':freshness['datasets']['sources']['as_of'],'freshness':freshness}
    assert compressed.json()==plain.json()==expected
    assert client.get('/api/sources',headers={'Accept-Encoding':'gzip'}).json()['records']==[]
