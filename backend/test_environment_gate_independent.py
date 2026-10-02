from copy import deepcopy
import pytest
from fastapi import HTTPException
from .workspace_environment import normalize_environment
from .case_cutover import execution_allowed
from .test_native_routes import api,operate
from .test_source_sync import harness
from . import storage


CFG={'LARK_WORKER_ORGANIZATION':'company','LARK_ALLOWED_TENANTS':'company',
     'LARK_WORKER_IDENTITY':'application'}


@pytest.mark.parametrize('wid,expected',[('lark-company','production'),('test-lark-company','test'),('demo-person','demo')])
@pytest.mark.parametrize('legacy',[None,''])
def test_namespace_migration_does_not_grant_formal_case_execution(wid,expected,legacy):
    state={'environment':legacy,'projects':[{'id':'p','tasks':['keep']}],'history':['retain']}
    before=deepcopy(state)
    normalize_environment(state,wid,CFG)
    assert state['environment']==expected and state['projects']==before['projects'] and state['history']==before['history']
    assert execution_allowed(state,state['projects'][0])==(expected!='production')


@pytest.mark.parametrize('wid,existing',[('lark-company','demo'),('lark-company','test'),
    ('test-lark-company','production'),('demo-person','production')])
def test_conflicting_environment_is_not_silently_reclassified(wid,existing):
    state={'environment':existing};before=deepcopy(state)
    with pytest.raises(HTTPException) as caught:normalize_environment(state,wid,CFG)
    assert caught.value.status_code==409 and state==before


@pytest.mark.parametrize('wid,cfg',[('lark-other',CFG),('test-lark-other',CFG),
    ('lark-company',dict(CFG,LARK_ALLOWED_TENANTS='other'))])
def test_unknown_or_unapproved_namespace_cannot_gain_demo_or_test_execution(wid,cfg):
    state={'projects':[{'id':'p'}]}
    with pytest.raises(HTTPException) as exc:normalize_environment(state,wid,cfg)
    assert exc.value.status_code==403
    assert not state.get('environment') and not execution_allowed(state,state['projects'][0])


def test_missing_application_identity_cannot_make_legacy_company_nonproduction():
    state={'environment':'','projects':[{'id':'p'}]}
    normalize_environment(state,'lark-company',dict(CFG,LARK_WORKER_IDENTITY='user'))
    assert state['environment']=='production' and not execution_allowed(state,state['projects'][0])


def change_case(api,target):
    h=api.h
    with h.sessions.begin() as db:
        row=db.get(h.W,h.wid);state=storage.load(db,h.B,row)
        state['projects'][0]['execution_system']=target;row.data=storage.save(db,h.B,h.wid,state)


@pytest.mark.parametrize('target',['pending','meegle'])
def test_formal_native_prepare_denied_before_remote_for_nonworkbench_case(api,target):
    change_case(api,target)
    response=operate(api,'prepare')
    assert response.status_code==409 and not api.calls


def test_cutover_revoked_during_definition_fetch_stops_submission_before_attempt(api):
    assert operate(api,'prepare').status_code==200
    service=api.client.app.state.native_approval_service
    original_factory=service.adapter_factory
    def factory(cfg):
        adapter=original_factory(cfg);original=adapter.request
        def request(method,path,**kwargs):
            result=original(method,path,**kwargs)
            if '/approvals/' in path:change_case(api,'meegle')
            return result
        adapter.request=request;return adapter
    service.adapter_factory=factory
    response=operate(api,'submit')
    assert response.status_code==409,response.text
    item=api.h.read()[0]['approvals'][0]
    assert not item['native_binding']['attempted']
    assert not any(method=='POST' for method,_ in api.calls)
