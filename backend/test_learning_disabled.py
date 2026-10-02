"""D1-D3 shutdown: learning actions stop; management stays; salary Base is read-only."""
from copy import deepcopy
import httpx
import pytest
from fastapi import HTTPException
from . import features, storage
from .capability_write_policy import CAPABILITY_BASE
from .learning import apply_learning
from .lark_adapter import LarkAdapter, RemoteFailure
from .operations import apply_operation
from .policy import upgrade
from .remote_policy import connection_policy
from .seed import seed, USERS
from .jobs import Worker
from .test_backend import app, client, workspace, act, role
from .test_source_sync import harness

ACTION_NAMES=['training_save','training_submit','training_pass','training_return','capability_approve','learning_retry','learning_standard_set','training_unknown','capability_unknown','learning_unknown']

def test_feature_is_disabled_in_production_code():
    assert features.FEATURE_LEARNING is False

@pytest.mark.parametrize('action',ACTION_NAMES)
def test_disabled_actions_cannot_mutate_even_for_authorized_manager(action):
    state=upgrade(seed(True)); state['users']=deepcopy(USERS)
    actor=next(u for u in state['users'] if u['id']=='u-manager')
    actor['capabilities']=['manage_training','approve_capability','manage_sources']
    before=deepcopy(state)
    with pytest.raises(HTTPException) as error: apply_learning(state,actor,{'action':action,'payload':{}},True)
    assert error.value.status_code==404 and state==before

@pytest.mark.parametrize('action',ACTION_NAMES)
def test_public_action_endpoint_cannot_bypass_disabled_feature(client,action):
    role(client,'u-manager'); before=workspace(client)
    response=act(client,action)
    assert response.status_code==404,response.text
    after=workspace(client)
    for key in ('version','jobs','training_plans','capability_awards','learning_standards','events'):
        assert after.get(key)==before.get(key)

@pytest.mark.parametrize('path',['/api/learning/sync','/api/learning/mappings/verify'])
def test_learning_apis_return_404_before_adapter_or_payload_processing(client,monkeypatch,path):
    from . import integration_routes, learning_sources
    monkeypatch.setattr(integration_routes,'application_adapter',lambda *_:pytest.fail('No adapter allowed'))
    monkeypatch.setattr(learning_sources,'read_capabilities',lambda *_:pytest.fail('No source read allowed'))
    before=workspace(client)
    assert client.post(path,content='invalid-json').status_code==404
    assert workspace(client)['version']==before['version']

def test_schedule_management_still_saves_and_versions_with_feature_off(client):
    role(client,'u-manager')
    for value in ('18:30','18:00'):
        response=act(client,'schedule_set',{'user_id':'u-control','day':'2026-09-30','end_time':value})
        assert response.status_code==200,response.text
    row=next(x for x in response.json()['work_schedules'] if x['user_id']=='u-control' and x['day']=='2026-09-30')
    assert row['end_time']=='18:00' and row['history'][0]['end_time']=='18:30' and row['version']==2

def test_schedule_permission_is_not_relaxed_by_learning_shutdown(client):
    role(client,'u-control')
    response=act(client,'schedule_set',{'user_id':'u-control','day':'2026-09-30','end_time':'18:00'})
    assert response.status_code==403

def test_quote_management_action_is_still_routed_by_public_api(app,client):
    from .app import WorkspaceRow, BusinessRow
    wid=app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
    with app.state.sessions.begin() as db:
        row=db.get(WorkspaceRow,wid); state=storage.load(db,BusinessRow,row)
        state['projects'][0].update(pm_id='u-pm',sales_id='u-field',quotes=[{'id':'quote1','amount':100}])
        row.data=storage.save(db,BusinessRow,wid,state)
    for user,seat,status in [('u-pm','pm','pending'),('u-field','sales','approved')]:
        role(client,user)
        response=act(client,'quote_review',{'quote_id':'quote1','classification':'effective','seat':seat})
        assert response.status_code==200,response.text
        assert response.json()['projects'][0]['quote_reviews'][0]['status']==status

def test_quote_review_still_requires_actual_two_distinct_seats():
    state=upgrade(seed()); state['users']=deepcopy(USERS)
    project=state['projects'][0]; project.update(pm_id='u-control',sales_id='u-field',quotes=[{'id':'quote1','amount':100}])
    def vote(actor,seat):
        return apply_operation(state,next(u for u in state['users'] if u['id']==actor),{'action':'quote_review','project_id':project['id'],'payload':{'quote_id':'quote1','classification':'effective','seat':seat}},True)
    assert vote('u-control','pm')
    assert project['quote_reviews'][0]['status']=='pending'
    with pytest.raises(HTTPException) as error: vote('u-manager','sales')
    assert error.value.status_code==403
    assert vote('u-field','sales')
    assert project['quote_reviews'][0]['status']=='approved'
    assert len(project['quote_reviews'][0]['votes'])==2 and not state['jobs']

@pytest.mark.parametrize('kind',['capability','training_record'])
@pytest.mark.parametrize('environment',['demo','test','production'])
def test_remote_policy_cannot_simulate_or_enable_stopped_jobs(kind,environment):
    state=upgrade(seed(True)); state['environment']=environment
    state['settings']['connection']={'external_enabled':True,'isolated_live_enabled':True}
    with pytest.raises(RemoteFailure) as error: connection_policy('test-isolated',state,{},kind)
    assert error.value.status=='blocked'

@pytest.mark.parametrize('kind',['capability','training_record'])
@pytest.mark.parametrize('status',['queued','running','failed','blocked','retry','outcome_unknown'])
@pytest.mark.parametrize('orphan',[False,True])
def test_legacy_jobs_block_without_adapter_or_simulated_receipt(harness,tmp_path,kind,status,orphan):
    h=harness; state,_=h.read(); state['environment']='production'
    plan={'id':'plan1','version':1,'award_id':'award1','record_sync_status':'queued','remote_status':'queued'}
    state['training_plans']=[] if orphan else [plan]
    state['capability_awards']=[] if orphan else [{'id':'award1','training_id':'plan1','training_version':1,'remote_status':'queued'}]
    payload={'training_id':'plan1','version':1} if kind=='training_record' else {'award_id':'award1'}
    state['jobs']=[{'id':'job1','kind':kind,'payload':payload,'status':status,'lease_token':'expired','lease_until':'2020-01-01T00:00:00+08:00'}]
    with h.sessions.begin() as db:
        row=db.get(h.W,h.wid); row.data=storage.save(db,h.B,h.wid,state)
    worker=Worker(h.sessions,h.W,h.B,h.P,h.cfg,tmp_path,adapter_factory=lambda *_:pytest.fail('Blocked job requested adapter'))
    assert worker.run_one(h.wid) is None
    result,_=h.read(); job=result['jobs'][0]
    assert job['status']=='blocked' and '業主裁示' in job['error']
    assert not job.get('lease_token') and not job.get('lease_until') and not job.get('receipt') and not job.get('simulated')
    actor=next(u for u in result['users'] if u['id']=='u-manager')
    with pytest.raises(HTTPException) as error: apply_operation(result,actor,{'action':'job_retry','payload':{'id':'job1'}},True)
    assert error.value.status_code==403 and result['jobs'][0]['status']=='blocked'

@pytest.mark.parametrize('method,suffix',[
    ('POST','/records'),('PUT','/records/rec1'),('PATCH','/records/rec1'),('DELETE','/records/rec1'),
    ('POST','/records/batch_create'),('POST','/records/batch_update'),('POST','/records/batch_delete'),
    ('POST','/fields'),('PUT','/fields/fld1'),('DELETE','/fields/fld1'),
])
@pytest.mark.parametrize('encoded',[False,True])
def test_salary_base_http_mutations_block_before_network(method,suffix,encoded):
    calls=[]
    def request(r): calls.append(r); return httpx.Response(200,json={'data':{}})
    base=CAPABILITY_BASE.replace('V','%56',1) if encoded else CAPABILITY_BASE
    with httpx.Client(transport=httpx.MockTransport(request)) as client:
        with pytest.raises(RemoteFailure) as error: LarkAdapter('fake-token',client).request(method,f'/bitable/v1/apps/{base}/tables/tbl1{suffix}')
    assert error.value.status=='blocked' and calls==[]

@pytest.mark.parametrize('method,suffix',[('GET','/records/rec1'),('GET','/fields'),('POST','/records/search')])
def test_salary_base_readonly_access_is_retained(method,suffix):
    calls=[]
    def request(r): calls.append(r.method); return httpx.Response(200,json={'data':{'read_only':True}})
    with httpx.Client(transport=httpx.MockTransport(request)) as client:
        result=LarkAdapter('fake-token',client).request(method,f'/bitable/v1/apps/{CAPABILITY_BASE}/tables/tbl1{suffix}')
    assert result=={'read_only':True} and calls==[method]

def test_generic_input_cannot_write_salary_base_even_when_mapping_verified():
    with httpx.Client(transport=httpx.MockTransport(lambda _:pytest.fail('No HTTP allowed'))) as client:
        with pytest.raises(RemoteFailure) as error: LarkAdapter('fake-token',client).write_input({'base_token':CAPABILITY_BASE,'verified':True},{'value':['new-skill']})
    assert error.value.status=='blocked'

@pytest.mark.parametrize('kind',['capability','training_record'])
@pytest.mark.parametrize('status',['succeeded','canceled','cancelled'])
def test_shutdown_retains_finished_job_history_without_resending(harness,tmp_path,kind,status):
    h=harness; state,_=h.read()
    original={'id':'historic','kind':kind,'payload':{},'status':status,'receipt':{'record_id':'historical-record','verified':True}}
    state['jobs']=[deepcopy(original)]
    with h.sessions.begin() as db:
        row=db.get(h.W,h.wid); row.data=storage.save(db,h.B,h.wid,state)
    worker=Worker(h.sessions,h.W,h.B,h.P,h.cfg,tmp_path,adapter_factory=lambda *_:pytest.fail('History must not resend'))
    assert worker.run_one(h.wid) is None
    assert h.read()[0]['jobs']==[original]
