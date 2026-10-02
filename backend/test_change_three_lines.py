from copy import deepcopy
import json
import pytest
from fastapi import HTTPException
from . import storage
from .test_native_routes import api,operate
from .test_source_sync import harness
from .test_native_approval import fixture
from .native_approval import verify_definition
from .native_requests import change_lines_valid,native_business_status
from .lark_adapter import RemoteFailure


def setup_change(api):
    mapping,definition,*_=fixture();mapping['kind']='change'
    mapping['nodes'][0]['seats']=['pm','supervisor']
    api.h.cfg['LARK_NATIVE_APPROVAL_MAPPINGS_JSON']=json.dumps({'change':mapping})
    with api.h.sessions.begin() as db:
        row=db.get(api.h.W,api.h.wid);state=storage.load(db,api.h.B,row)
        item=state['approvals'][0];item.update(type='change',owner_confirmed=False,client_confirmed=False)
        p=state['projects'][0]
        p['evidence'].append({'id':'client-proof','node_id':api.nid,'status':'accepted','value':'業主已同意本次修訂','withdrawn':False})
        row.data=storage.save(db,api.h.B,api.h.wid,state)
    return mapping,definition


def line(api,party):
    return api.client.post('/api/change-approvals/request/confirm-line',json={
        'version':api.h.read()[0]['version'],'party':party,'reason':'核對本次變更範圍',
        'evidence_ids':['client-proof']})


def test_change_lark_approval_never_substitutes_other_two_lines(api):
    setup_change(api)
    assert operate(api,'prepare','change').status_code==200
    api.external[0]='APPROVED'
    response=operate(api,'submit','change');assert response.status_code==200,response.text
    item=response.json()['approvals'][0]
    assert item['lark_status']=='approved' and item['native_receipt']['approved']
    assert item['status']=='pending' and not item['owner_confirmed'] and not item['client_confirmed']
    # PM can record client evidence, not personally cast the supervisor's confirmation.
    assert line(api,'supervisor').status_code==403
    response=line(api,'client');assert response.status_code==200,response.text
    assert response.json()['approvals'][0]['status']=='pending'
    api.actor[0]='ou_sup';response=line(api,'supervisor')
    assert response.status_code==200,response.text
    state=response.json();item=state['approvals'][0];p=state['projects'][0]
    n=next(n for n in p['nodes'] if n['id']==api.nid)
    assert item['status']=='approved' and change_lines_valid(state,p,n,item)
    assert item['change_confirmations']['client']['basis']=='external_client_evidence'
    assert 'client_approver_id' not in p or not p['client_approver_id']
    p['evidence'][-1]['withdrawn']=True
    assert not change_lines_valid(state,p,n,item)
    assert native_business_status(state,p,n,item,True)=='pending'
    p['evidence'][-1]['withdrawn']=False
    from .workflow import apply_action
    before_revision=p['revision']
    # Browser approval actions do not send node_id; derive it from the stored request.
    apply_action(state,state['users'][0],{'action':'approval_execute','project_id':p['id'],
                 'payload':{'approval_id':item['id']}},False)
    assert item['status']=='executed' and p['revision']==before_revision+1


def test_change_legacy_booleans_and_scope_drift_cannot_enable_execution(api):
    setup_change(api);assert operate(api,'prepare','change').status_code==200
    api.external[0]='APPROVED';assert operate(api,'submit','change').status_code==200
    state,_=api.h.read();item=state['approvals'][0];p=state['projects'][0]
    n=next(n for n in p['nodes'] if n['id']==api.nid)
    item.update(owner_confirmed=True,client_confirmed=True,status='approved')
    assert not change_lines_valid(state,p,n,item)
    from .workflow import apply_action
    with pytest.raises(HTTPException) as error:
        apply_action(state,state['users'][0],{'action':'approval_execute','project_id':p['id'],
                     'node_id':n['id'],'payload':{'approval_id':item['id']}},False)
    assert error.value.status_code==409 and '三線' in error.value.detail


def test_change_external_client_is_not_an_employee_approval_seat(api):
    mapping,definition=setup_change(api)
    assert verify_definition(definition,mapping)
    mapping['nodes'][0]['seats']=['owner','client']
    with pytest.raises(RemoteFailure):verify_definition(definition,mapping)


@pytest.mark.parametrize('seats',[['pm'],['supervisor'],['pm','admin'],['owner','supervisor'],['pm','supervisor','admin'],['pm','pm','supervisor']])
def test_change_requires_exact_pm_and_supervisor_in_definition_and_actor_resolution(api,seats):
    from .native_requests import actors
    mapping,definition=setup_change(api);mapping['nodes'][0]['seats']=seats
    with pytest.raises(RemoteFailure):verify_definition(definition,mapping)
    state,_=api.h.read();p=state['projects'][0];n=next(n for n in p['nodes'] if n['id']==api.nid)
    with pytest.raises(HTTPException):actors(state,p,n,state['approvals'][0],mapping,'app1')


def test_change_same_person_cannot_fill_both_required_seats(api):
    from .native_requests import actors
    mapping,_=setup_change(api);state,_=api.h.read();p=state['projects'][0]
    n=next(n for n in p['nodes'] if n['id']==api.nid)
    n['supervisor_id']=p['pm_id']
    with pytest.raises(HTTPException) as error:actors(state,p,n,state['approvals'][0],mapping,'app1')
    assert '不同' in error.value.detail


def test_change_proof_must_be_accepted_and_current(api):
    setup_change(api)
    assert line(api,'client').status_code==409
    assert operate(api,'prepare','change').status_code==200
    assert operate(api,'submit','change').status_code==200
    with api.h.sessions.begin() as db:
        row=db.get(api.h.W,api.h.wid);state=storage.load(db,api.h.B,row)
        state['projects'][0]['evidence'][-1]['status']='submitted'
        row.data=storage.save(db,api.h.B,api.h.wid,state)
    assert line(api,'client').status_code==409


def test_background_approved_observation_keeps_change_pending_without_both_lines(api):
    from .native_poller import NativeApprovalPoller
    setup_change(api);assert operate(api,'prepare','change').status_code==200
    assert operate(api,'submit','change').status_code==200
    api.external[0]='APPROVED';h=api.h
    poller=NativeApprovalPoller(h.sessions,h.W,h.B,h.P,h.cfg,api.adapter_factory)
    assert poller.run_due(h.wid)==[{'id':'request','status':'observed'}]
    item=h.read()[0]['approvals'][0]
    assert item['native_receipt']['approved'] and item['lark_status']=='approved'
    assert item['status']=='pending' and not item['owner_confirmed'] and not item['client_confirmed']
