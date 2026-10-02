from copy import deepcopy
import pytest
from .test_native_service import setup
from .lark_adapter import RemoteFailure


def pending():
    service,fake,ctx,binding,_=setup();fake.instance['status']='PENDING';saved=[]
    service.submit(binding,ctx,lambda b:saved.append(deepcopy(b)),lambda:ctx)
    fake.calls=[]
    return service,fake,ctx,binding,saved


def test_original_pending_cancel_survives_current_mapping_removal_and_definition_change():
    service,fake,ctx,binding,saved=pending()
    service.cfg['LARK_NATIVE_APPROVAL_MAPPINGS_JSON']='{}'
    fake.definition={'status':'DELETED'}
    original=fake.request
    def cancel(method,path,**kwargs):
        assert '/approvals/' not in path
        if path.endswith('/cancel'):fake.instance['status']='CANCELED'
        return original(method,path,**kwargs)
    fake.request=cancel
    receipt=service.cancel(binding,ctx,lambda b:saved.append(deepcopy(b)),lambda:ctx)
    assert receipt['external_status']=='CANCELED'
    assert len([c for c in fake.calls if c[0]=='POST'])==1


@pytest.mark.parametrize('mutation',['uuid','applicant','form','immutable'])
def test_cancel_never_posts_for_mismatched_original_proof(mutation):
    service,fake,ctx,binding,saved=pending()
    if mutation=='uuid':fake.instance['uuid']='wrong'
    elif mutation=='applicant':fake.instance['open_id']='ou_other'
    elif mutation=='form':fake.instance['form']='[]'
    else:binding['payload']['approval_code']='different'
    with pytest.raises(RemoteFailure):service.cancel(binding,ctx,lambda b:saved.append(deepcopy(b)),lambda:ctx)
    assert not any(c[0]=='POST' for c in fake.calls)


def test_cancel_checkpoint_failure_prevents_external_effect():
    service,fake,ctx,binding,_=pending()
    def failed(_):raise RuntimeError('database unavailable')
    with pytest.raises(RuntimeError):service.cancel(binding,ctx,failed,lambda:ctx)
    assert not any(c[0]=='POST' for c in fake.calls)


def test_approved_instance_cannot_be_canceled_even_after_local_mapping_removed():
    service,fake,ctx,binding,saved=pending();fake.instance['status']='APPROVED'
    service.cfg['LARK_NATIVE_APPROVAL_MAPPINGS_JSON']='{}'
    receipt=service.cancel(binding,ctx,lambda b:saved.append(deepcopy(b)),lambda:ctx)
    assert receipt['external_status']=='APPROVED' and receipt['approved']
    assert not binding.get('cancel_attempted') and not binding.get('verification_failed_at')
    assert not any(c[0]=='POST' for c in fake.calls)
