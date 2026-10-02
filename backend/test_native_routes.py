from copy import deepcopy
from types import SimpleNamespace
import json
import pytest
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from . import native_routes,storage
from .native_approval import NativeApprovalService
from .test_source_sync import harness
from .test_native_approval import fixture


@pytest.fixture
def api(harness,monkeypatch):
    h=harness;state,_=h.read();p=state['projects'][0];n=next(n for n in p['nodes'] if n['key']=='control')
    p.update(pm_id='ou_pm',admin_id='ou_admin',supervisor_id='ou_sup',execution_system='workbench');n['owner_id']='ou_pm'
    state['users']=[{'id':i,'name':i,'role':'member','active':True,'identity_app_id':'app1',
        'directory_status':'employed','directory_source':{'app_id':'app1','record_id':'rec-'+i}}
        for i in ('ou_pm','ou_admin','ou_sup')]
    item={'id':'request','type':'extension','project_id':p['id'],'node_id':n['id'],
          'project_revision':p['revision'],'reason':'延後','status':'draft','created_by':'ou_pm',
          'task_ids':[n['tasks'][0]['id']],'dates':[{'task_id':n['tasks'][0]['id'],'due_date':'2026-10-01'}]}
    state['approvals']=[item]
    fn=next(node for node in p['nodes'] if node['key']=='pricing')
    p['evidence']=[{'id':'e1','node_id':fn['id'],'value':'交付證明','status':'accepted'}]
    with h.sessions.begin() as db:
        row=db.get(h.W,h.wid);row.data=storage.save(db,h.B,h.wid,state)
    mapping,definition,*_=fixture();mapping['kind']='extension'
    h.cfg['LARK_NATIVE_APPROVAL_MAPPINGS_JSON']=json.dumps({'extension':mapping})
    h.cfg['LARK_NATIVE_APPROVAL_SUBMIT_ENABLED']='true'
    calls=[];payload={};external=['PENDING']
    class Adapter:
        client=SimpleNamespace(close=lambda:None)
        def request(self,method,path,**kwargs):
            calls.append((method,path))
            if '/approvals/' in path:return deepcopy(definition)
            if method=='POST':payload.update(deepcopy(kwargs['json']));return {'instance_code':'instance'}
            ids=[v for node in payload['node_approver_open_id_list'] for v in node['value']]
            return dict(approval_code=payload['approval_code'],uuid=payload['uuid'],open_id=payload['open_id'],
                        instance_code='instance',form=payload['form'],status=external[0],
                        task_list=[{'id':i,'node_id':'node-real-id','open_id':i,'type':'AND','status':'APPROVED'} for i in ids],
                        timeline=[{'task_id':i,'open_id':i,'type':'PASS'} for i in ids])
    service=NativeApprovalService(h.cfg,lambda _:Adapter())
    monkeypatch.setattr(native_routes,'NativeApprovalService',lambda _:service)
    def load(db,row):return storage.load(db,h.B,row)
    actor=['ou_pm']
    def identity(_):return {'mode':'lark','wid':h.wid},next(u for u in h.read()[0]['users'] if u['id']==actor[0])
    def persist(wid,version,callback,**kwargs):
        with h.sessions.begin() as db:
            row=db.get(h.W,wid)
            if version!=row.version:raise HTTPException(409,'version')
            state=load(db,row);callback(state);state['version']=row.version+1
            row.version=state['version'];row.data=storage.save(db,h.B,wid,state)
            return deepcopy(state)
    app=FastAPI();native_routes.register(app,identity,load,persist,h.sessions,h.W,h.cfg)
    client=TestClient(app)
    return SimpleNamespace(h=h,client=client,calls=calls,external=external,actor=actor,pid=p['id'],nid=n['id'],financial_nid=fn['id'],adapter_factory=lambda _:Adapter())


def operate(api,op,kind='extension'):
    return api.client.post('/api/native-approvals/'+kind+'/request/'+op,json={'version':api.h.read()[0]['version']})


def test_only_original_applicant_can_request_remote_cancellation(api):
    assert operate(api,'prepare').status_code==200
    assert operate(api,'submit').status_code==200
    before=len(api.calls);api.actor[0]='ou_sup'
    assert operate(api,'cancel').status_code==403
    assert api.calls[before:]==[]


def test_actual_routes_prepare_submit_poll_bind_and_preserve_task_progress(api):
    before=deepcopy(api.h.read()[0]['projects'][0]['nodes'])
    response=operate(api,'prepare');assert response.status_code==200,response.text
    assert not any(method=='POST' for method,_ in api.calls)
    response=operate(api,'submit');assert response.status_code==200,response.text
    request=response.json()['approvals'][0]
    assert request['status']=='pending' and request['native_binding']['attempted']
    assert not request['native_receipt']['approved']
    assert operate(api,'submit').status_code==200
    assert sum(method=='POST' for method,_ in api.calls)==1
    api.external[0]='APPROVED';response=operate(api,'poll')
    assert response.status_code==200,response.text
    state=response.json();request=state['approvals'][0]
    from .native_requests import receipt_valid
    p=state['projects'][0];n=next(n for n in p['nodes'] if n['id']==api.nid)
    assert receipt_valid(state,p,n,request) and p['nodes']==before
    api.external[0]='CANCELED';response=operate(api,'poll')
    assert response.status_code==200
    assert response.json()['approvals'][0]['status']=='withdrawn'


def test_scope_change_after_prepare_prevents_real_post(api):
    assert operate(api,'prepare').status_code==200
    with api.h.sessions.begin() as db:
        row=db.get(api.h.W,api.h.wid);state=storage.load(db,api.h.B,row)
        state['projects'][0]['revision']+=1;row.data=storage.save(db,api.h.B,api.h.wid,state)
    response=operate(api,'submit')
    assert response.status_code in (409,503)
    assert not any(method=='POST' for method,_ in api.calls)


def test_financial_delivery_draft_never_accepts_amount_or_other_case_evidence(api):
    def body():return {'version':api.h.read()[0]['version'],'project_id':api.pid,'node_id':api.financial_nid,
        'evidence_ids':['e1'],'reason':'請核對證明','confirmation_kind':'payment'}
    b=body();b['amount']=12
    assert api.client.post('/api/native-approvals/financial/request',json=b).status_code==422
    b=body();b['evidence_ids']=['other-case']
    assert api.client.post('/api/native-approvals/financial/request',json=b).status_code==409
    before=deepcopy(api.h.read()[0]['projects'])
    response=api.client.post('/api/native-approvals/financial/request',json=body())
    assert response.status_code==200,response.text
    state=response.json()
    # Root financial records participate in the owning project's CAS version.
    expected=next(p for p in before if p['id']==api.pid)
    expected['concurrency_version']+=1
    assert state['projects']==before and state['financial_requests'][0]['status']=='draft'
    ident=state['financial_requests'][0]['id']
    response=api.client.post('/api/native-approvals/financial/'+ident+'/prepare',json={'version':state['version']})
    assert response.status_code==503 and not api.calls


def test_repeated_approved_poll_preserves_applied_skip_and_directory_revocation_blocks(api):
    from .node_skip import apply_skip,valid_waiver
    h=api.h
    mapping=fixture()[0];h.cfg['LARK_NATIVE_APPROVAL_MAPPINGS_JSON']=json.dumps({'node_skip':mapping})
    with h.sessions.begin() as db:
        row=db.get(h.W,h.wid);state=storage.load(db,h.B,row)
        apply_skip(state,state['users'][0],{'action':'node_skip_create','project_id':api.pid,'node_id':api.nid,
                   'payload':{'reason':'不適用','impact':'後續交付照常'}},False)
        state['node_skip_requests'][-1]['id']='request';row.data=storage.save(db,h.B,h.wid,state)
    assert operate(api,'prepare','node_skip').status_code==200
    api.external[0]='APPROVED';assert operate(api,'submit','node_skip').status_code==200
    with h.sessions.begin() as db:
        row=db.get(h.W,h.wid);state=storage.load(db,h.B,row);item=state['node_skip_requests'][0]
        item['status']='applied';p=state['projects'][0];n=next(n for n in p['nodes'] if n['id']==api.nid)
        n.update(status='approved_skipped',skip_request_id='request');row.data=storage.save(db,h.B,h.wid,state)
    response=operate(api,'poll','node_skip');assert response.status_code==200,response.text
    state=response.json();p=state['projects'][0];n=next(n for n in p['nodes'] if n['id']==api.nid)
    assert state['node_skip_requests'][0]['status']=='applied' and valid_waiver(state,p,n)
    with h.sessions.begin() as db:
        row=db.get(h.W,h.wid);state=storage.load(db,h.B,row)
        next(u for u in state['users'] if u['id']=='ou_sup')['directory_status']='unknown'
        row.data=storage.save(db,h.B,h.wid,state)
    state,_=h.read();p=state['projects'][0];n=next(n for n in p['nodes'] if n['id']==api.nid)
    assert not valid_waiver(state,p,n)
    response=operate(api,'poll','node_skip')
    assert response.status_code==200  # Original lifecycle remains observable.
    state=response.json();p=state['projects'][0];n=next(n for n in p['nodes'] if n['id']==api.nid)
    assert not valid_waiver(state,p,n)
    assert state['node_skip_requests'][0]['native_receipt']['applicable'] is False


def test_financial_two_person_receipt_is_bound_to_source_amount_and_file_version(api):
    mapping=fixture()[0];mapping['kind']='financial';mapping['nodes'][0]['seats']=['pm','admin']
    api.h.cfg['LARK_NATIVE_APPROVAL_MAPPINGS_JSON']=json.dumps({'financial':mapping})
    body={'version':api.h.read()[0]['version'],'project_id':api.pid,'node_id':api.financial_nid,
          'evidence_ids':['e1'],'reason':'確認證明','confirmation_kind':'contract'}
    response=api.client.post('/api/native-approvals/financial/request',json=body)
    assert response.status_code==200
    ident=response.json()['financial_requests'][0]['id']
    def post(operation):return api.client.post('/api/native-approvals/financial/'+ident+'/'+operation,
                                              json={'version':api.h.read()[0]['version']})
    assert post('prepare').status_code==200
    before=deepcopy(api.h.read()[0]['projects']);api.external[0]='APPROVED'
    response=post('submit');assert response.status_code==200,response.text
    state=response.json();p=state['projects'][0];n=next(n for n in p['nodes'] if n['id']==api.financial_nid)
    from .native_requests import receipt_valid
    item=state['financial_requests'][0]
    # Submit persists the attempt checkpoint and then the verified receipt.
    # Each changes the case-owned approval record, but no business field.
    expected=next(project for project in before if project['id']==api.pid)
    expected['concurrency_version']+=2
    assert receipt_valid(state,p,n,item) and state['projects']==before
    original_declaration=item['payables_declaration'];item['payables_declaration']='no_payables'
    assert not receipt_valid(state,p,n,item)
    item['payables_declaration']=original_declaration
    n['tasks'][0]['output']='different submitted evidence'
    assert not receipt_valid(state,p,n,item)
    n['tasks'][0]['output']=before[0]['nodes'][next(i for i,x in enumerate(before[0]['nodes']) if x['id']==api.financial_nid)]['tasks'][0]['output']
    p.setdefault('source_finance',{})['合約總額']=999
    assert not receipt_valid(state,p,n,item)
