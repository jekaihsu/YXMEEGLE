from copy import deepcopy
import httpx
import pytest
from .lark_adapter import LarkAdapter,RemoteFailure,NativeRequestRejected
from .native_approval import creation_not_performed,remote_binding_resolved
from .test_native_service import setup
from .test_native_routes import api,operate
from .test_source_sync import harness
from .test_native_poller import mutate,make


@pytest.mark.parametrize('path,code,operation',[
    ('/approval/v4/instances',1390001,'create'),('/approval/v4/instances',1390015,'create'),
    ('/approval/v4/instances',1390013,'create'),('/approval/v4/instances/cancel',1390003,'cancel')])
def test_only_documented_post_validation_errors_are_definite(path,code,operation):
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(400,json={'code':code}))) as client:
        adapter=LarkAdapter('test',client)
        with pytest.raises(NativeRequestRejected) as error:adapter.request('POST',path,json={})
        assert error.value.operation==operation and error.value.api_code==code


@pytest.mark.parametrize('method,path,status,code',[
    ('POST','/approval/v4/instances',400,1395001),('POST','/approval/v4/instances',400,60012),
    ('POST','/approval/v4/instances',503,1390001),('GET','/approval/v4/instances/uuid',400,1390003),
    ('POST','/other',400,1390001),('POST','/approval/v4/instances',200,1390001)])
def test_ambiguous_errors_and_get_absence_never_prove_write_rejected(method,path,status,code):
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(status,json={'code':code}))) as client:
        with pytest.raises(RemoteFailure) as error:LarkAdapter('test',client).request(method,path)
        assert not isinstance(error.value,NativeRequestRejected)


def test_definite_create_rejection_retries_same_uuid_after_enablement_and_keeps_audit():
    service,fake,ctx,binding,_=setup();original=fake.request;saved=[];posts=[]
    def reject(method,path,**kwargs):
        if method=='POST':posts.append(deepcopy(kwargs['json']));raise NativeRequestRejected('create',1390015)
        return original(method,path,**kwargs)
    fake.request=reject
    with pytest.raises(NativeRequestRejected):service.submit(binding,ctx,lambda b:saved.append(deepcopy(b)),lambda:ctx)
    assert creation_not_performed(binding) and binding['attempted']
    assert saved[0]['status']=='outcome_unknown' and saved[-1]['status']=='not_created'
    assert remote_binding_resolved({'native_binding':binding})
    service.cfg['LARK_NATIVE_APPROVAL_SUBMIT_ENABLED']='false'
    with pytest.raises(RemoteFailure):service.submit(binding,ctx,lambda _:None,lambda:ctx)
    assert len(posts)==1
    service.cfg['LARK_NATIVE_APPROVAL_SUBMIT_ENABLED']='true'
    def accept(method,path,**kwargs):
        if method=='POST':posts.append(deepcopy(kwargs['json']))
        return original(method,path,**kwargs)
    fake.request=accept
    assert service.submit(binding,ctx,lambda b:saved.append(deepcopy(b)),lambda:ctx)['approved']
    assert posts[0]==posts[1] and not creation_not_performed(binding)
    assert binding['rejection_history'][0]['api_code']==1390015


def test_definite_cancel_rejection_does_not_permanently_disable_retry():
    service,fake,ctx,binding,_=setup();fake.instance['status']='PENDING';saved=[]
    service.submit(binding,ctx,lambda b:saved.append(deepcopy(b)),lambda:ctx)
    original=fake.request;posts=[]
    def reject(method,path,**kwargs):
        if path.endswith('/cancel'):posts.append(path);raise NativeRequestRejected('cancel',1390001)
        return original(method,path,**kwargs)
    fake.request=reject
    with pytest.raises(NativeRequestRejected):service.cancel(binding,ctx,lambda b:saved.append(deepcopy(b)),lambda:ctx)
    assert binding['cancel_attempted'] is False and binding['cancel_rejection']['api_code']==1390001
    def cancel(method,path,**kwargs):
        if path.endswith('/cancel'):posts.append(path);fake.instance['status']='CANCELED'
        return original(method,path,**kwargs)
    fake.request=cancel
    assert service.cancel(binding,ctx,lambda b:saved.append(deepcopy(b)),lambda:ctx)['external_status']=='CANCELED'
    assert len(posts)==2


def test_cancel_already_approved_returns_current_proof_without_post_or_invalidation():
    service,fake,ctx,binding,_=setup()
    service.submit(binding,ctx,lambda _:None,lambda:ctx);before=len(fake.calls)
    receipt=service.cancel(binding,ctx,lambda _:None,lambda:ctx)
    assert receipt['approved'] and not binding.get('cancel_attempted') and not binding.get('verification_failed_at')
    assert all(method=='GET' for method,_,*rest in fake.calls[before:])


def test_invalidated_scope_api_observes_until_terminal_without_reusing_approval(api):
    assert operate(api,'prepare').status_code==200 and operate(api,'submit').status_code==200
    def invalidate(state):
        state['projects'][0]['revision']+=1
        state['approvals'][0].update(status='invalidated',remote_resolution_required=True)
    mutate(api,invalidate);before=len(api.calls)
    response=operate(api,'poll');assert response.status_code==200,response.text
    item=response.json()['approvals'][0]
    assert item['remote_resolution_required'] and not remote_binding_resolved(item)
    api.external[0]='APPROVED'
    response=operate(api,'poll');assert response.status_code==200,response.text
    item=response.json()['approvals'][0]
    assert item['status']=='invalidated' and not item['native_receipt']['approved']
    assert not item['remote_resolution_required'] and remote_binding_resolved(item)
    assert all(method=='GET' for method,_ in api.calls[before:])


def test_changed_definition_still_records_terminal_observation_but_never_business_approval(api,monkeypatch):
    poller,_=make(api,monkeypatch);factory=poller.adapter_factory
    def changed(cfg):
        adapter=factory(cfg);original=adapter.request
        def request(method,path,**kwargs):
            if '/approvals/' in path:
                value=original(method,path,**kwargs);value['status']='INACTIVE';return value
            return original(method,path,**kwargs)
        adapter.request=request;return adapter
    poller.adapter_factory=changed;api.external[0]='APPROVED'
    assert poller.run_due(api.h.wid)==[{'id':'request','status':'observed'}]
    item=api.h.read()[0]['approvals'][0]
    assert item['status']=='invalidated' and not item['native_receipt']['approved']
    assert remote_binding_resolved(item)


def test_api_definite_rejection_can_be_abandoned_with_audit_without_remote_cancel(api):
    assert operate(api,'prepare').status_code==200
    service=api.client.app.state.native_approval_service;factory=service.adapter_factory;writes=[]
    def rejected(cfg):
        adapter=factory(cfg);original=adapter.request
        def request(method,path,**kwargs):
            if method=='POST':writes.append(path);raise NativeRequestRejected('create',1390015)
            return original(method,path,**kwargs)
        adapter.request=request;return adapter
    service.adapter_factory=rejected
    assert operate(api,'submit').status_code==503
    item=api.h.read()[0]['approvals'][0]
    assert item['lark_status']=='not_created' and creation_not_performed(item['native_binding'])
    response=operate(api,'abandon');assert response.status_code==200,response.text
    item=response.json()['approvals'][0]
    assert item['status']=='withdrawn' and remote_binding_resolved(item)
    assert item['history'][-1]['action']=='native_abandon_uncreated'
    assert writes==['/approval/v4/instances']


def test_api_unknown_submit_cannot_be_abandoned_even_when_get_reports_absence(api):
    assert operate(api,'prepare').status_code==200
    service=api.client.app.state.native_approval_service;factory=service.adapter_factory;writes=[]
    def uncertain(cfg):
        adapter=factory(cfg);original=adapter.request
        def request(method,path,**kwargs):
            if method=='POST':writes.append(path);raise RemoteFailure('timeout','outcome_unknown')
            if '/instances/' in path:raise RemoteFailure('not found','blocked')
            return original(method,path,**kwargs)
        adapter.request=request;return adapter
    service.adapter_factory=uncertain
    assert operate(api,'submit').status_code==503
    assert operate(api,'abandon').status_code==409
    assert operate(api,'submit').status_code==503
    assert writes==['/approval/v4/instances']
    assert not remote_binding_resolved(api.h.read()[0]['approvals'][0])


def test_api_cancel_rejection_clears_requested_flag_and_retains_reason(api):
    assert operate(api,'prepare').status_code==200 and operate(api,'submit').status_code==200
    service=api.client.app.state.native_approval_service;factory=service.adapter_factory
    def rejected(cfg):
        adapter=factory(cfg);original=adapter.request
        def request(method,path,**kwargs):
            if path.endswith('/cancel'):raise NativeRequestRejected('cancel',1390001)
            return original(method,path,**kwargs)
        adapter.request=request;return adapter
    service.adapter_factory=rejected
    assert operate(api,'cancel').status_code==503
    item=api.h.read()[0]['approvals'][0]
    assert not item['cancel_requested'] and not item['native_binding']['cancel_attempted']
    assert item['native_binding']['cancel_rejection']['api_code']==1390001
