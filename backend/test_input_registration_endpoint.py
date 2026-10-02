import json
from copy import deepcopy
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from .app import create_app,WorkspaceRow,BusinessRow
from . import storage,integration_routes
from .test_backend import workspace
from .input_registration import FIELD_NAMES
from .test_input_registration import Fake,is_write


@pytest.fixture
def setup(tmp_path,monkeypatch):
    fields={k:{'field_id':'fld'+k,'field_name':v} for k,v in FIELD_NAMES.items()}
    app=create_app({'DATABASE_URL':f'sqlite:///{tmp_path}/input.db','UPLOAD_DIR':str(tmp_path/'uploads'),
        'SESSION_SECRET':'test-secret'*5,'APP_ENV':'development','DEMO_MODE':'true',
        'LARK_INPUT_REGISTRATION_FIELDS_JSON':json.dumps(fields)})
    client=TestClient(app);client.get('/api/session')
    monkeypatch.setattr(integration_routes,'connection_policy',lambda *a,**k:{'mode':'production','simulated':False,'base_token':'dedicated','table_id':'table'})
    return app,client


def submit(client,request_id=None,value='交付內容'):
    return client.post('/api/projects/p1/nodes/p1-pm/inputs',json={
        'version':workspace(client)['version'],'request_id':request_id or str(uuid4()),
        'key':'client_contact','label':'業主聯繫','value':value})


def read_raw(app,client):
    wid=app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
    with app.state.sessions() as db:return storage.load(db,BusinessRow,db.get(WorkspaceRow,wid))


def test_actual_endpoint_persists_queue_plan_and_idempotency_before_any_remote(setup):
    app,client=setup;ident=str(uuid4())
    result=submit(client,ident);assert result.status_code==200,result.text
    state=read_raw(app,client);revision=state['input_revisions'][-1]
    assert revision['status']=='queued' and revision['key']=='client_contact'
    assert revision['registration_plan']['values']['actor_id']==revision['actor_id']
    assert len([j for j in state['jobs'] if j['key']=='input:'+revision['id']])==1
    assert submit(client,ident).status_code==200
    assert len(read_raw(app,client)['input_revisions'])==len(state['input_revisions'])
    assert submit(client,ident,'different').status_code==409


def test_missing_request_identifier_and_unapproved_policy_cannot_queue(setup,monkeypatch):
    app,client=setup;before=read_raw(app,client)
    r=client.post('/api/projects/p1/nodes/p1-pm/inputs',json={'version':before['version'],'key':'x','label':'x','value':'v'})
    assert r.status_code==422
    monkeypatch.setattr(integration_routes,'connection_policy',lambda *a,**k:{'mode':'production','simulated':False,'base_token':'VwAsbezz9app3YsramgjduLYp2U','table_id':'table'})
    assert submit(client).status_code==409
    assert read_raw(app,client)['input_revisions']==before['input_revisions']


def test_unknown_reconciliation_endpoint_reads_only_and_marks_verified(setup,monkeypatch):
    app,client=setup;assert submit(client).status_code==200
    wid=app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
    with app.state.sessions.begin() as db:
        row=db.get(WorkspaceRow,wid);state=storage.load(db,BusinessRow,row)
        revision=state['input_revisions'][-1];revision['status']='outcome_unknown'
        job=next(j for j in state['jobs'] if j['key']=='input:'+revision['id']);job['status']='outcome_unknown'
        plan=deepcopy(revision['registration_plan']);ident=revision['id'];row.data=storage.save(db,BusinessRow,wid,state)
    fake=Fake(plan)
    fake.rows=[{'record_id':'recRemote','fields':{FIELD_NAMES[k]:v for k,v in plan['values'].items()}}]
    class Client:
        def close(self):pass
    fake.client=Client()
    monkeypatch.setattr(integration_routes,'application_adapter',lambda cfg:fake)
    response=client.post(f'/api/input-revisions/{ident}/reconcile',json={'version':workspace(client)['version']})
    assert response.status_code==200,response.text
    assert not any(map(is_write,fake.calls))
    current=next(i for i in read_raw(app,client)['input_revisions'] if i['id']==ident)
    assert current['status']=='succeeded' and current['receipt']['record_id']=='recRemote'
