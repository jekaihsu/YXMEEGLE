from copy import deepcopy
import json
import pytest
import httpx
from fastapi import HTTPException
from .seed import seed, USERS
from .policy import upgrade
from .learning import apply_learning, cutoff
from .operations import apply_operation
from .learning_sources import parse_leave, LEAVE_DEFINITION, DELEGATE_FIELD
from .lark_adapter import LarkAdapter, RemoteFailure


@pytest.fixture
def legacy_learning_enabled(monkeypatch):
    # Exercise retained local history logic only; remote salary Base stays blocked.
    from . import features
    monkeypatch.setattr(features, 'FEATURE_LEARNING', True)


@pytest.fixture
def state():
    ws=upgrade(seed(True)); ws['users']=deepcopy(USERS)
    for user in ws['users']:
        if user['id']=='u-manager': user['capabilities']=['manage_training','approve_capability','calendar_edit']
    ws['capability_catalog']=[{'id':'recSkill1','name':'控制測量','active':True}]
    return ws


def act(ws,action,payload,user='u-manager'):
    actor=next(x for x in ws['users'] if x['id']==user)
    body={'action':action,'payload':payload}
    return apply_learning(ws,actor,body,True) or apply_operation(ws,actor,body,True)


def train(ws):
    act(ws,'training_save',{'title':'控制訓練','trainee_id':'u-control','trainer_id':'u-manager','skill_ids':['recSkill1'],'planned_date':'2026-09-28'})
    p=ws['training_plans'][-1]
    act(ws,'training_submit',{'id':p['id'],'summary':'已完成實作','evidence_urls':['https://example.com/evidence']},'u-control')
    return p


def test_training_requires_separate_recognition_and_never_fakes_remote_success(state,legacy_learning_enabled):
    plan=train(state)
    act(state,'training_pass',{'id':plan['id']})
    assert plan['status']=='recognition_pending' and not state['capability_awards']
    act(state,'capability_approve',{'training_id':plan['id']})
    assert plan['status']=='approved' and plan['remote_status']=='writeback_paused'
    assert state['capability_awards'][0]['remote_status']=='writeback_paused'
    assert state['jobs']==[]
    with pytest.raises(HTTPException): act(state,'capability_approve',{'id':plan['id']})
    assert len(state['capability_awards'])==1


def test_manager_without_explicit_capability_permission_cannot_recognize(state,legacy_learning_enabled):
    plan=train(state); act(state,'training_pass',{'id':plan['id']})
    next(u for u in state['users'] if u['id']=='u-manager')['capabilities']=[]
    with pytest.raises(HTTPException,match='能力認定權限'): act(state,'capability_approve',{'id':plan['id']})


def test_training_cannot_self_certify_or_mutate_submitted_record(state,legacy_learning_enabled):
    plan=train(state)
    next(u for u in state['users'] if u['id']=='u-control')['capabilities']=['manage_training','approve_capability']
    with pytest.raises(HTTPException,match='自己的訓練'): act(state,'training_pass',{'id':plan['id']},'u-control')
    with pytest.raises(HTTPException,match='不可覆寫'): act(state,'training_save',{'id':plan['id'],'title':'換成果'})


def test_shift_deadline_is_not_clockout_or_legacy_fixed_time(state):
    state['settings']['cutoff_time']='17:00'
    assert cutoff(state,'u-control','2026-09-30')['status']=='pending_schedule'
    act(state,'schedule_set',{'user_id':'u-control','day':'2026-09-30','end_time':'18:30'})
    assert cutoff(state,'u-control','2026-09-30')['time']=='18:30'
    assert cutoff(state,'u-control','2026-10-01')['time'] is None
    act(state,'schedule_set',{'user_id':'u-control','day':'2026-09-30','end_time':'18:00'})
    assert state['work_schedules'][0]['history'][0]['end_time']=='18:30'
    assert len(state['work_schedules'])==1


def test_standard_preserves_versions_without_making_scores(state,legacy_learning_enabled):
    for value in ('每月核定目標','新版按職務定義'):
        act(state,'learning_standard_set',{'kind':'survival','title':'生存底線','value':value,'effective_from':'2026-10-01'})
    assert len(state['learning_standards'])==2
    assert all(s['calculation_status']=='definition_only' for s in state['learning_standards'])


def test_approved_leave_parser_checks_definition_identity_and_timezone():
    form=[{'id':DELEGATE_FIELD,'value':{'open_ids':['ou_delegate']}},{'id':'group','value':[{'id':'widgetLeaveGroupStartTime','value':'2026-09-28T01:00:00Z'},{'id':'widgetLeaveGroupEndTime','value':'2026-09-28T10:00:00Z'}]}]
    remote={'definition_code':LEAVE_DEFINITION,'instance_code':'instance123','user_id':'ou_principal','status':'APPROVED','form':json.dumps(form)}
    result=parse_leave(remote,'instance123')
    assert result['from']=='2026-09-28T09:00:00+08:00'
    assert result['delegate_id']=='ou_delegate'
    remote['reverted']=True; assert parse_leave(remote,'instance123')['status']=='CANCELED'
    remote['definition_code']='different'
    with pytest.raises(HTTPException): parse_leave(remote,'instance123')


def test_capability_update_preserves_existing_skills_and_detects_external_edit():
    m={'base_token':'base','table_id':'table','record_id':'recPerson','field_id':'fldSkill','field_name':'能力地圖點數','type':'link'}
    state={'skills':['recExisting'],'writes':0}
    def handler(request):
        if request.url.path.endswith('/fields'):
            data={'items':[{'field_id':'fldSkill','field_name':'能力地圖點數','type':21}]}
        elif request.method=='PUT':
            state['writes']+=1; state['skills']=json.loads(request.content)['fields']['能力地圖點數']; data={}
        else: data={'record':{'record_id':'recPerson','fields':{'能力地圖點數':state['skills']}}}
        return httpx.Response(200,json={'code':0,'data':data})
    adapter=LarkAdapter('test',httpx.Client(transport=httpx.MockTransport(handler)))
    receipt=adapter.write_input(m,{'base_value':['recExisting'],'value':['recExisting','recNew']})
    assert receipt['verified'] and state['skills']==['recExisting','recNew'] and state['writes']==1
    state['skills']=['recExternal']
    with pytest.raises(RemoteFailure,match='遠端同欄位'): adapter.write_input(m,{'base_value':['recExisting'],'value':['recExisting','recNew']})
    assert state['writes']==1


def test_manager_default_and_self_grant_cannot_bypass_recognition():
    from .operations import apply_operation
    ws=seed(True); ws['users']=deepcopy(USERS); upgrade(ws)
    manager=next(u for u in ws['users'] if u['role']=='manager')
    assert 'approve_capability' not in manager['capabilities']
    with pytest.raises(HTTPException,match='明確指定'):
        apply_operation(ws,manager,{'action':'admin_person','payload':{'id':manager['id'],'role':'manager','capabilities':manager['capabilities']+['approve_capability']}})


def test_retry_after_mapping_cannot_resume_paused_writeback(state,legacy_learning_enabled):
    plan=train(state); act(state,'training_pass',{'id':plan['id']}); act(state,'capability_approve',{'id':plan['id']})
    state['capability_bindings']=[{'id':'person','user_id':plan['trainee_id'],'verified':True}]
    with pytest.raises(HTTPException) as error: act(state,'learning_retry',{'id':plan['id'],'target':'capability'})
    assert error.value.status_code==403
    assert len(state['capability_awards'])==1 and state['jobs']==[]
    assert plan['status']=='approved' and plan['remote_status']=='writeback_paused'


def test_training_return_retains_prior_submission(state,legacy_learning_enabled):
    plan=train(state); original=deepcopy(plan)
    act(state,'training_return',{'id':plan['id'],'reason':'補上計算紀錄'})
    assert plan['status']=='planned' and plan['submissions'][0]['summary']==original['summary']
    act(state,'training_submit',{'id':plan['id'],'summary':'補正後成果','evidence_urls':['https://example.com/new']},'u-control')
    assert plan['summary']!=plan['submissions'][0]['summary'] and plan['version']==original['version']+2


def test_settings_accept_shift_policy_but_reject_fixed_cutoff(state):
    from .operations import apply_operation
    manager=next(u for u in state['users'] if u['role']=='manager')
    apply_operation(state,manager,{'action':'admin_settings','payload':{'digest_time':'09:30'}})
    assert state['settings']['digest_time']=='09:30'
    with pytest.raises(HTTPException,match='正常班表'):
        apply_operation(state,manager,{'action':'admin_settings','payload':{'cutoff_time':'17:00'}})
