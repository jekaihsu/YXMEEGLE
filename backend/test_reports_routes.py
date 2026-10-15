from concurrent.futures import ThreadPoolExecutor
from threading import Event
from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest
from backend.reports.reader import FixtureReader, LarkReader
from backend.reports.registry import BY_KIND
from backend.reports.routes import register
from backend.reports.snapshot import SnapshotStore
from backend.test_reports_compute import FIXTURES


def app_for(**kwargs):
    app=FastAPI()
    store=register(app,lambda request:({'wid':'company','mode':'lark'},{'id':'P01'}),{},reader=FixtureReader(FIXTURES),**kwargs)
    return app,store


def test_endpoints_and_validation():
    app,store=app_for()
    with TestClient(app) as client:
        for endpoint in ('review','review/rows','sales','assets','progress','sources'):
            response=client.get('/api/reports/'+endpoint,params={'week':'2026-10-12'})
            assert response.status_code==200,response.text
            assert response.headers['cache-control']=='no-store'
            assert len(response.json()['meta']['snapshot'])==12
        for params in ({'limit':'201'},{'limit':'a'},{'offset':'-1'},{'sort':'bad'},{'week':'2026-10-13'},{'dept':'bad'}):
            response=client.get('/api/reports/review/rows',params=params)
            assert response.status_code==422
            assert isinstance(response.json()['detail'],str)
        assert client.get('/api/reports/assets?from=bad').status_code==422
        assert client.post('/api/reports/refresh').status_code==403
    store.close()


def test_refresh_authorization_and_throttle():
    calls=[]
    app,store=app_for(authorize=lambda *args:calls.append(args),live_enabled=lambda wid:True)
    with TestClient(app) as client:
        response=client.post('/api/reports/refresh');assert response.status_code in (200,202)
        store.get()
        assert client.post('/api/reports/refresh').status_code==429
    assert calls[0][1]=='sources'
    store.close()


def test_single_flight_stale_unchanged_and_cold_budget():
    started,release=Event(),Event()
    class Blocking:
        count=0
        def read(self):
            self.count+=1;started.set();release.wait(2)
            return FixtureReader(FIXTURES).read()
    reader=Blocking();clock=[0]
    store=SnapshotStore(reader,{'REPORTS_COLD_WAIT_SECONDS':'.01','REPORTS_TTL_SECONDS':'1'},clock=lambda:clock[0])
    with pytest.raises(Exception) as error: store.get()
    assert error.value.status_code==503
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures=list(pool.map(lambda _:store.start(),range(10)))
    assert len(set(futures))==1
    release.set();first=futures[0].result();store.result('sales',{})
    clock[0]=2
    assert store.get() is first
    second=store.start().result()
    assert first['data'] is second['data']
    assert first['cache'] is second['cache']
    assert reader.count==2
    store.close()


def test_lark_reader_projection_and_pagination():
    seen=[]
    def respond(request):
        seen.append(request)
        if '/auth/' in request.url.path:
            return httpx.Response(200,json={'code':0,'tenant_access_token':'token','expire':7200})
        return httpx.Response(200,json={'code':0,'data':{'items':[{'record_id':'v1','fields':{'車牌':'TEST','salary':999}}],'has_more':False}})
    reader=LarkReader({'LARK_APP_ID':'test','LARK_APP_SECRET':'test'},transport=httpx.MockTransport(respond),tables=(BY_KIND['vehicle'],))
    data=reader.read()
    assert data['vehicle']['records'][0]['fields']=={'車牌':'TEST'}
    assert seen[-1].url.params['page_size']=='500'
    assert 'field_names' in seen[-1].url.params
    assert seen[-1].method=='GET'


def test_reports_disabled_and_demo_isolation():
    for cfg,mode,expected in (({'REPORTS_ENABLED':'false'},'lark',404),({},'demo',403)):
        app=FastAPI();store=register(app,lambda _:({'wid':'company','mode':mode},{}),cfg,reader=FixtureReader(FIXTURES))
        with TestClient(app) as client:
            response=client.get('/api/reports/sales')
            assert response.status_code==expected
            assert response.headers['cache-control']=='no-store'
            assert isinstance(response.json()['detail'],str)
        store.close()


def test_refresh_failure_keeps_last_snapshot_and_cache_cannot_be_mutated():
    class Failing:
        fail=False
        def read(self):
            if self.fail: raise RuntimeError('private upstream diagnostic')
            return FixtureReader(FIXTURES).read()
    reader=Failing();store=SnapshotStore(reader)
    first=store.result('sales',{})
    first['items'][0]['name']='changed'
    assert store.result('sales',{})['items'][0]['name']=='測試案'
    reader.fail=True
    with pytest.raises(RuntimeError):store.start().result()
    assert store.result('sales',{})['meta']['snapshot']==first['meta']['snapshot']
    store.close()


def test_lark_reader_rejects_incomplete_page():
    def respond(request):
        if '/auth/' in request.url.path:
            return httpx.Response(200,json={'code':0,'tenant_access_token':'token','expire':7200})
        return httpx.Response(200,json={'code':0,'data':{'items':[],'has_more':True}})
    reader=LarkReader({'LARK_APP_ID':'test2','LARK_APP_SECRET':'test2'},transport=httpx.MockTransport(respond),tables=(BY_KIND['vehicle'],))
    with pytest.raises(Exception,match='pagination'):reader.read()


@pytest.mark.parametrize('path,params',[
    ('review',{'week':'not-a-week'}),('review',{'week':'2026-10-13'}),
    ('review/rows',{'limit':'0'}),('review/rows',{'limit':'999'}),
    ('review/rows',{'sort':'unknown'}),('review',{'dept':'unknown'}),
    ('progress',{'dept':'control'}),('progress',{'scope':'unknown'}),
])
def test_invalid_report_parameters_are_client_errors(path,params):
    app=FastAPI();store=register(app,lambda _:({'wid':'company','mode':'lark'},{}),{},reader=FixtureReader(FIXTURES))
    with TestClient(app) as client:
        response=client.get('/api/reports/'+path,params=params)
        assert response.status_code==422
    store.close()


def test_dev_cli_transport_retries_429_without_misreading_record_values(monkeypatch):
    import subprocess
    from backend.reports.dev_lark_cli_transport import LarkCliTransport
    responses=iter([
        subprocess.CompletedProcess([],1,'','HTTP 429'),
        subprocess.CompletedProcess([],0,'{"ok":true,"data":{"items":[{"value":429}],"has_more":false}}',''),
    ])
    sleeps=[]
    monkeypatch.setattr('backend.reports.dev_lark_cli_transport.subprocess.run',lambda *a,**k:next(responses))
    monkeypatch.setattr('backend.reports.dev_lark_cli_transport.time.sleep',sleeps.append)
    transport=LarkCliTransport()
    response=transport.handle_request(httpx.Request('GET','https://open.feishu.cn/open-apis/bitable/v1/apps/base/tables/table/records'))
    assert response.json()['data']['items'][0]['value']==429
    assert len(sleeps)==1 and 1<=sleeps[0]<2
