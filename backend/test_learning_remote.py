"""Former training export scenarios now stop before any salary Base request."""
from copy import deepcopy
import httpx
import pytest
from .lark_adapter import LarkAdapter, RemoteFailure
from .capability_write_policy import CAPABILITY_BASE

@pytest.mark.parametrize('version,status,existing',[(1,'planned',False),(2,'submitted',True),(3,'recognition_pending',True),(4,'approved',True),(5,'planned',True)])
@pytest.mark.parametrize('workspace',['demo-user','test-isolated','lark-company'])
def test_all_training_revisions_pause_before_search_create_or_readback(version,status,existing,workspace):
    calls=[]
    def forbidden(request):
        calls.append((request.method,str(request.url)))
        pytest.fail('Paused training export must make zero HTTP requests')
    mapping={'id':'mapping1','base_token':CAPABILITY_BASE,'table_id':'tblTraining','purpose':'training','fields':{},'verified':True}
    plan={'id':'plan1','version':version,'title':'training','status':status,'record_receipt':{'record_id':'old-revision','verified':True} if existing else None}
    before=deepcopy((mapping,plan))
    with httpx.Client(transport=httpx.MockTransport(forbidden)) as client:
        adapter=LarkAdapter('fake-token',client)
        for _ in range(2):
            with pytest.raises(RemoteFailure) as error: adapter.write_training(mapping,plan,workspace)
            assert error.value.status=='blocked'
    assert calls==[] and (mapping,plan)==before
