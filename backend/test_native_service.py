from copy import deepcopy
from types import SimpleNamespace
import json
import pytest
from .native_approval import NativeApprovalService
from .lark_adapter import RemoteFailure
from .test_native_approval import fixture,Fake


def setup():
    mapping,definition,ctx,binding,instance=fixture()
    cfg={'LARK_NATIVE_APPROVAL_SUBMIT_ENABLED':'true','LARK_WORKER_IDENTITY':'application','LARK_APP_ID':'app','LARK_WORKER_ORGANIZATION':'company',
         'LARK_ALLOWED_TENANTS':'company','LARK_NATIVE_APPROVAL_MAPPINGS_JSON':json.dumps({'node_skip':mapping})}
    fake=Fake(definition,instance);fake.client=SimpleNamespace(close=lambda:None)
    service=NativeApprovalService(cfg,lambda _:fake)
    return service,fake,ctx,binding,instance


def test_service_persists_verified_receipt_and_remote_revocation_replaces_approval():
    service,fake,ctx,binding,instance=setup();saved=[]
    receipt=service.submit(binding,ctx,lambda b:saved.append(deepcopy(b)),lambda:deepcopy(ctx))
    assert receipt['approved'] and receipt['verified_at'] and saved[-1]['receipt']==receipt
    assert saved[0]['status']=='outcome_unknown' and len([c for c in fake.calls if c[0]=='POST'])==1
    fake.instance=dict(instance,status='CANCELED')
    receipt=service.poll(binding,ctx,lambda b:saved.append(deepcopy(b)),lambda:deepcopy(ctx))
    assert not receipt['approved'] and saved[-1]['status']=='canceled'


@pytest.mark.parametrize('bad',['identity','configuration','revision','ordinary_review'])
def test_service_blocks_untrusted_configuration_or_live_scope_before_io(bad):
    service,fake,ctx,binding,_=setup();current=deepcopy(ctx)
    if bad=='identity': service.cfg['LARK_WORKER_ORGANIZATION']='another'
    if bad=='configuration': service.cfg['LARK_NATIVE_APPROVAL_MAPPINGS_JSON']='{}'
    if bad=='revision': current['scope_hash']='new-version'
    if bad=='ordinary_review': binding['kind']='review_vote'
    with pytest.raises(RemoteFailure):service.submit(binding,ctx,lambda _:None,lambda:current)
    assert not fake.calls


def test_failed_durable_final_checkpoint_never_returns_success_or_reposts():
    service,fake,ctx,binding,_=setup();saved=[]
    def save(b):
        if b.get('receipt'): raise RuntimeError('commit failed')
        saved.append(deepcopy(b))
    with pytest.raises(RuntimeError):service.submit(binding,ctx,save,lambda:ctx)
    assert saved[0]['attempted'] and not saved[0].get('receipt')
    service.submit(saved[0],ctx,lambda _:None,lambda:ctx)
    assert len([c for c in fake.calls if c[0]=='POST'])==1


def test_prepare_only_reads_definition_and_does_not_submit():
    service,fake,ctx,binding,_=setup()
    result=service.prepare(kind='node_skip',context=ctx,applicant='ou_applicant',
        approvers=binding['approvers'],content={'reason':'test'},authorize=lambda:ctx)
    assert result['status']=='prepared' and not result['attempted']
    assert all(c[0]=='GET' for c in fake.calls)


def test_network_failure_does_not_refresh_old_proof_and_definite_mismatch_invalidates_it():
    service,fake,ctx,binding,_=setup();saved=[]
    service.submit(binding,ctx,lambda b:saved.append(deepcopy(b)),lambda:ctx)
    previous=deepcopy(binding['receipt']);original=fake.request
    def unavailable(method,path,**kwargs):
        if '/instances/' in path:raise RemoteFailure('temporary unavailable','failed')
        return original(method,path,**kwargs)
    fake.request=unavailable
    with pytest.raises(RemoteFailure):service.poll(binding,ctx,lambda b:saved.append(deepcopy(b)),lambda:ctx)
    assert binding['receipt']==previous and binding['verification_failed_at']
    fake.request=original;fake.instance['open_id']='ou_wrong'
    with pytest.raises(RemoteFailure):service.poll(binding,ctx,lambda b:saved.append(deepcopy(b)),lambda:ctx)
    assert not binding['receipt']['approved'] and not binding['receipt']['binding_verified']


@pytest.mark.parametrize('failure',['disabled','demo'])
def test_new_submission_requires_explicit_live_enablement(failure):
    service,fake,ctx,binding,_=setup()
    if failure=='disabled': service.cfg.pop('LARK_NATIVE_APPROVAL_SUBMIT_ENABLED')
    else: service.cfg['DEMO_MODE']='true'
    with pytest.raises(RemoteFailure): service.submit(binding,ctx,lambda _:None,lambda:ctx)
    assert not fake.calls and not binding['attempted']


def test_timeout_then_permission_failure_stays_unknown_and_later_recovers_without_post():
    service,fake,ctx,binding,_=setup();saved=[];original=fake.request
    def outage(method,path,**kwargs):
        if method=='POST':raise RemoteFailure('timeout','outcome_unknown')
        if '/instances/' in path:raise RemoteFailure('permission unavailable','blocked')
        return original(method,path,**kwargs)
    fake.request=outage
    with pytest.raises(RemoteFailure): service.submit(binding,ctx,lambda b:saved.append(deepcopy(b)),lambda:ctx)
    assert saved[-1]['attempted'] and saved[-1]['status']=='outcome_unknown'
    assert not saved[-1].get('receipt')
    fake.request=original;service.cfg['LARK_NATIVE_APPROVAL_SUBMIT_ENABLED']='false'
    receipt=service.submit(binding,ctx,lambda b:saved.append(deepcopy(b)),lambda:ctx)
    assert receipt['approved'] and not any(c[0]=='POST' for c in fake.calls)


def test_cancel_checkpoints_before_remote_and_repeated_cancel_only_reads():
    service,fake,ctx,binding,_=setup();fake.instance['status']='PENDING';saved=[]
    service.submit(binding,ctx,lambda b:saved.append(deepcopy(b)),lambda:ctx)
    original=fake.request
    def cancel(method,path,**kwargs):
        if path.endswith('/cancel'):
            assert saved[-1]['cancel_attempted']
            assert kwargs['json']['user_id']==binding['payload']['open_id']
            fake.instance['status']='CANCELED'
        return original(method,path,**kwargs)
    fake.request=cancel
    receipt=service.cancel(binding,ctx,lambda b:saved.append(deepcopy(b)),lambda:ctx)
    assert receipt['external_status']=='CANCELED'
    service.cancel(binding,ctx,lambda b:saved.append(deepcopy(b)),lambda:ctx)
    assert len([c for c in fake.calls if c[1].endswith('/cancel')])==1


def test_unknown_cancellation_never_reposts_and_does_not_claim_withdrawn():
    service,fake,ctx,binding,_=setup();fake.instance['status']='PENDING';saved=[]
    service.submit(binding,ctx,lambda b:saved.append(deepcopy(b)),lambda:ctx)
    original=fake.request;posts=[]
    def timeout(method,path,**kwargs):
        if path.endswith('/cancel'):
            posts.append(path);raise RemoteFailure('timeout','outcome_unknown')
        return original(method,path,**kwargs)
    fake.request=timeout
    for _ in range(2):
        receipt=service.cancel(binding,ctx,lambda b:saved.append(deepcopy(b)),lambda:ctx)
        assert receipt['external_status']=='PENDING'
    assert len(posts)==1 and binding['cancel_attempted']
