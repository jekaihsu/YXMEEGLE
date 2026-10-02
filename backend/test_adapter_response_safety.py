import httpx
import pytest
from .lark_adapter import LarkAdapter,RemoteFailure


@pytest.mark.parametrize('method,status',[('GET','failed'),('POST','outcome_unknown')])
@pytest.mark.parametrize('body',[b'not-json',b'[]',b'{"code":0,"data":[]}'])
def test_malformed_response_never_becomes_verified_success(method,status,body):
    transport=httpx.MockTransport(lambda request:httpx.Response(200,content=body))
    with httpx.Client(transport=transport) as client:
        adapter=LarkAdapter('fake',client)
        with pytest.raises(RemoteFailure) as exc:adapter.request(method,'/approval/v4/instances')
    assert exc.value.status==status
