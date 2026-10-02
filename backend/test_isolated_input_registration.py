"""Real route→persistence→worker, with HTTP effects replaced by a fake readback."""
import json
from copy import deepcopy
from uuid import uuid4
import pytest
from .test_isolated_live import isolated,make_client
from .test_source_sync import harness
from .test_input_registration import Fake,is_write
from .input_registration import FIELD_NAMES,registration_fields
from .jobs import Worker
from .remote_policy import connection_policy
from .lark_adapter import RemoteFailure


@pytest.fixture
def registration(isolated):
    x=isolated;state=x.read()
    state['input_mappings']=[];state['input_revisions']=[];state['jobs']=[]
    state['settings'].update(input_base='formalInput',input_table='tblFormal')
    x.save(state)
    x.cfg.update(LARK_INPUT_BASE_TOKEN='formalInput',LARK_INPUT_TABLE_ID='tblFormal',
        LARK_INPUT_REGISTRATION_FIELDS_JSON=json.dumps({k:{'field_id':'fldFormal'+k,'field_name':v} for k,v in FIELD_NAMES.items()}),
        LARK_TEST_INPUT_REGISTRATION_FIELDS_JSON=json.dumps({k:{'field_id':'fldTest'+k,'field_name':v} for k,v in FIELD_NAMES.items()}))
    return x


def post(x,client):
    state=x.read();p=state['projects'][0];n=p['nodes'][0]
    return client.post(f'/api/projects/{p["id"]}/nodes/{n["id"]}/inputs',json={
        'version':state['version'],'request_id':str(uuid4()),'key':'work_input',
        'label':'隔離測試交付','value':'只進測試登錄表'})


def test_isolated_route_to_worker_appends_and_verifies_only_test_destination(registration,monkeypatch):
    x=registration
    with make_client(x,monkeypatch) as client:
        response=post(x,client)
    assert response.status_code==200,response.text
    plan=x.read()['input_revisions'][-1]['registration_plan']
    assert plan['destination']['table_id']=='tblInput'
    assert all(f['field_id'].startswith('fldTest') for f in plan['destination']['fields'].values())
    fake=Fake(plan)
    class Client:
        def close(self):pass
    fake.client=Client()
    worker=Worker(x.h.sessions,x.h.W,x.h.B,x.h.P,x.cfg,x.uploads,adapter_factory=lambda cfg:fake)
    worker.run_one(x.wid)
    saved=x.read()['input_revisions'][-1]
    assert saved['status']=='succeeded' and saved['receipt']['verified']
    assert saved['receipt']['remote_mode']=='isolated_live' and not saved['receipt']['simulated']
    assert sum(map(is_write,fake.calls))==1
    assert all('/apps/isolatedBase/tables/tblInput/' in c[1] for c in fake.calls)
    assert not any('formalInput' in c[1] or 'tblFormal' in c[1] for c in fake.calls)


@pytest.mark.parametrize('mutation',['missing_table','wrong_table','formal_table','formal_base','missing_schema','formal_fields'])
def test_isolated_submission_rejects_cross_target_before_queue(registration,monkeypatch,mutation):
    x=registration;state=x.read()
    if mutation=='missing_table':x.cfg.pop('LARK_TEST_INPUT_TABLE_ID')
    elif mutation=='wrong_table':x.cfg['LARK_TEST_INPUT_TABLE_ID']='other'
    elif mutation=='formal_table':
        x.cfg['LARK_TEST_INPUT_TABLE_ID']='tblFormal';state['settings']['test_input_table']='tblFormal'
    elif mutation=='formal_base':
        x.cfg['LARK_TEST_BASE_TOKEN']='formalInput';state['settings']['test_base']='formalInput'
    elif mutation=='missing_schema':x.cfg.pop('LARK_TEST_INPUT_REGISTRATION_FIELDS_JSON')
    elif mutation=='formal_fields':x.cfg['LARK_TEST_INPUT_REGISTRATION_FIELDS_JSON']=x.cfg['LARK_INPUT_REGISTRATION_FIELDS_JSON']
    x.save(state)
    with make_client(x,monkeypatch) as client:r=post(x,client)
    assert r.status_code==409,r.text
    assert not x.read()['input_revisions'] and not x.read()['jobs'] and not x.remote['requests']


def test_schema_change_after_queue_stops_worker_before_remote_factory(registration,monkeypatch):
    x=registration
    with make_client(x,monkeypatch) as client:assert post(x,client).status_code==200
    x.cfg['LARK_TEST_INPUT_REGISTRATION_FIELDS_JSON']=x.cfg['LARK_INPUT_REGISTRATION_FIELDS_JSON']
    calls=[]
    def factory(cfg):calls.append(True);raise AssertionError('Must not construct remote adapter')
    worker=Worker(x.h.sessions,x.h.W,x.h.B,x.h.P,x.cfg,x.uploads,adapter_factory=factory)
    worker.run_one(x.wid)
    assert next(j for j in x.read()['jobs'] if j['kind']=='input')['status']=='blocked' and not calls


def test_production_cannot_reuse_test_base_or_table(registration):
    x=registration;state=x.read();state['environment']='production'
    state['settings']['input_table']='tblInput';x.cfg['LARK_INPUT_TABLE_ID']='tblInput'
    with pytest.raises(RemoteFailure):connection_policy('lark-tenant',state,x.cfg,'input')


def test_formal_schema_cannot_reuse_test_field_ids(registration):
    x=registration;x.cfg['LARK_INPUT_REGISTRATION_FIELDS_JSON']=x.cfg['LARK_TEST_INPUT_REGISTRATION_FIELDS_JSON']
    with pytest.raises(RemoteFailure):registration_fields(x.cfg,{'mode':'production','simulated':False})


def test_isolated_unknown_reconciliation_uses_test_schema_and_reads_only(registration,monkeypatch):
    x=registration
    with make_client(x,monkeypatch) as client:assert post(x,client).status_code==200
    revision=x.read()['input_revisions'][-1];plan=revision['registration_plan'];fake=Fake(plan)
    class Client:
        def close(self):pass
    fake.client=Client();fake.timeout=True;fake.lost=True
    Worker(x.h.sessions,x.h.W,x.h.B,x.h.P,x.cfg,x.uploads,adapter_factory=lambda cfg:fake).run_one(x.wid)
    assert x.read()['input_revisions'][-1]['status']=='outcome_unknown'
    fake.rows=[{'record_id':'recRecovered','fields':{FIELD_NAMES[k]:v for k,v in plan['values'].items()}}]
    count=len(fake.calls);x.factory=lambda cfg:fake
    with make_client(x,monkeypatch) as client:
        r=client.post(f'/api/input-revisions/{revision["id"]}/reconcile',json={'version':x.read()['version']})
    assert r.status_code==200,r.text
    assert not any(map(is_write,fake.calls[count:]))
    assert x.read()['input_revisions'][-1]['receipt']['record_id']=='recRecovered'


def test_admin_settings_accepts_test_table_and_rejects_formal_table(registration):
    from .operations import apply_operation
    from fastapi import HTTPException
    x=registration;state=x.read();actor=next(u for u in state['users'] if u['role']=='manager')
    body={'action':'admin_settings','payload':{'test_input_table':'tblNewTest'}}
    apply_operation(state,actor,body,True)
    assert state['settings']['test_input_table']=='tblNewTest'
    body['payload']['test_input_table']=state['settings']['input_table']
    with pytest.raises(HTTPException):apply_operation(state,actor,body,True)
