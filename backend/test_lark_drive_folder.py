import httpx
import pytest

from .lark_adapter import LarkAdapter, RemoteFailure


def adapter_with_pages(pages):
    requests=[]

    def handle(request):
        requests.append(request)
        if request.method=='POST':
            return httpx.Response(200,json={'code':0,'data':{'token':'created'}})
        page=request.url.params.get('page_token')
        result=pages[page]
        return httpx.Response(200,json={'code':0,'data':result})

    client=httpx.Client(transport=httpx.MockTransport(handle))
    return LarkAdapter('fake-token',client),requests


def test_drive_folder_searches_all_pages_before_returning_match():
    adapter,requests=adapter_with_pages({
        None:{'files':[{'name':'Output','type':'folder','token':'first'}],
              'has_more':True,'next_page_token':'next'},
        'next':{'files':[{'name':'Output','type':'folder','token':'second'}],
                'has_more':False},
    })
    with pytest.raises(RemoteFailure,match='重名'):
        adapter.folder('parent','Output')
    assert [request.method for request in requests]==['GET','GET']


@pytest.mark.parametrize('payload',[
    {},
    {'files':[]},
    {'files':[],'has_more':True},
    {'files':[],'has_more':True,'next_page_token':'loop'},
])
def test_drive_folder_incomplete_pages_fail_closed_without_creating(payload):
    adapter,requests=adapter_with_pages({None:payload,'loop':payload})
    with pytest.raises(RemoteFailure):
        adapter.folder('parent','Output')
    assert all(request.method=='GET' for request in requests)


def test_drive_folder_creates_only_after_complete_empty_inventory():
    adapter,requests=adapter_with_pages({None:{'files':[],'has_more':False}})
    assert adapter.folder('parent','Output')=='created'
    assert [request.method for request in requests]==['GET','POST']
