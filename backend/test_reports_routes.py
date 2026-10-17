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
            response=client.get('/api/reports/'+endpoint,params={'week':'2026-10-12'} if endpoint.startswith('review') or endpoint=='progress' else {})
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
    assert store.result('sales',{})['meta']['refresh_error'] is True
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


@pytest.mark.parametrize('endpoint', ['review','review/rows','sales','assets','progress','sources'])
def test_unknown_query_keys_rejected(endpoint):
    app,store=app_for()
    with TestClient(app) as client:
        r=client.get('/api/reports/'+endpoint+'?data=x')
        assert r.status_code==422 and isinstance(r.json()['detail'],str)
    store.close()


@pytest.mark.parametrize('role', ['staff','pm','manager'])
def test_role_gate_all_reports_and_refresh(role):
    app=FastAPI();store=register(app,lambda _:({'wid':'company','mode':'lark'},{'role':role}),{},reader=FixtureReader(FIXTURES),allow=lambda d,u:u['role'] in ('pm','manager'),authorize=lambda *a:None,live_enabled=lambda w:True)
    with TestClient(app) as client:
        for endpoint in ('review','review/rows','sales','assets','progress','sources'):
            assert client.get('/api/reports/'+endpoint).status_code==(403 if role=='staff' else 200)
        r=client.post('/api/reports/refresh')
        assert r.status_code==403 if role=='staff' else r.status_code in (200,202)
    store.close()


def test_identical_result_misses_single_flight_and_lru(monkeypatch):
    from backend.reports import compute
    from threading import Lock
    started,release=Event(),Event();calls=[];lock=Lock()
    original=compute.sales
    def sales(data,**params):
        with lock: calls.append(params.get('pm',''))
        if params.get('pm')=='blocked': started.set();assert release.wait(3)
        return original(data,**params)
    monkeypatch.setattr(compute,'sales',sales)
    store=SnapshotStore(FixtureReader(FIXTURES));store.get()
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures=[pool.submit(store.result,'sales',{'pm':'blocked'}) for _ in range(8)]
        assert started.wait(2);release.set()
        assert all(f.result()['total']==0 for f in futures)
    assert calls.count('blocked')==1
    store.result('sales',{'pm':'hot'})
    for i in range(510): store.result('sales',{'pm':str(i)})
    store.result('sales',{'pm':'hot'})
    store.result('sales',{'pm':'extra'})
    store.result('sales',{'pm':'hot'})
    assert calls.count('hot')==1
    store.result('sales',{'pm':'blocked'})
    assert calls.count('blocked')==2
    store.close()


def test_snapshot_gaps_do_not_rescan_requests(monkeypatch):
    from backend.reports import compute
    calls=[];original=compute.report_gaps
    def gaps(*args,**kwargs): calls.append((args[1],args[2] if len(args)>2 else 'field'));return original(*args,**kwargs)
    monkeypatch.setattr(compute,'report_gaps',gaps)
    store=SnapshotStore(FixtureReader(FIXTURES));store.get();count=len(calls)
    for dept in ('field','office','control'):
        for weeks in (1,2,3): store.result('review',{'dept':dept,'weeks':weeks,'week':'2026-10-12'})
    assert len(calls)==count
    store.close()


def test_round2_blank_select_roundtrips_and_day_sort_keys():
    raw=FixtureReader(FIXTURES).read()
    raw['plan']['records'][0]['fields']['組別']=''
    for r in raw['field_cost']['records']: r['fields']['組別']=''
    for r in raw['instrument']['records']:
        r['fields']['類別']='';r['fields']['狀態']=''
    class Reader:
        def read(self): return raw
    app=FastAPI();store=register(app,lambda _:({'wid':'company','mode':'lark'},{}),{},reader=Reader())
    with TestClient(app) as client:
        for key in ('owner','category','status'):
            params={'kind':'instrument','from':'2026-10-12','to':'2026-10-18'}
            options=client.get('/api/reports/assets',params=params).json()['options'][key]
            assert '__blank__' in options and '' not in options
            result=client.get('/api/reports/assets',params={**params,key:'__blank__'})
            assert result.status_code==200
            assert result.json()['total']>0
            assert all(r[key]=='' for r in result.json()['items'])
        for group in ('未分組','__blank__'):
            for key in ('matched_days','unplanned_days'):
                result=client.get('/api/reports/progress',params={'week':'2026-10-12','group':group,'sort':key})
                assert result.status_code==200
                body=result.json()
                assert '__blank__' in body['options']['group']
                assert body['kpi']['planned_days']>0 and body['kpi']['actual_days']>0
                assert [r[key] for r in body['items']]==sorted(r[key] for r in body['items'])
    store.close()


def test_cold_warming_then_ready():
    release=Event()
    class Slow:
        def read(self):
            release.wait(2)
            return FixtureReader(FIXTURES).read()
    app=FastAPI();store=register(app,lambda _:({'wid':'company','mode':'lark'},{}),{'REPORTS_COLD_WAIT_SECONDS':'.01'},reader=Slow())
    try:
        with TestClient(app) as client:
            response=client.get('/api/reports/sales')
            assert response.json()=={'detail':'報表資料正在首次讀取，請稍候','warming':True,'retry_after':5}
            assert response.status_code==503
            assert response.headers['retry-after']=='5'
            assert response.headers['cache-control']=='no-store'
            release.set();store.start().result()
            assert client.get('/api/reports/sales').status_code==200
    finally: release.set();store.close()


def test_cold_failure_logs_safely(caplog):
    class Failing:
        def read(self): raise ValueError('secret=never-print-this')
    app=FastAPI();store=register(app,lambda _:({'wid':'company','mode':'lark'},{}),{},reader=Failing())
    with caplog.at_level('INFO',logger='backend.reports'),TestClient(app) as client:
        response=client.get('/api/reports/sales')
        assert response.json()=={'detail':'報表來源暫時無法讀取','warming':False}
        assert any(r.levelname=='WARNING' and 'error_class=ValueError' in r.message for r in caplog.records)
        assert 'never-print-this' not in caplog.text
    store.close()


@pytest.mark.parametrize('kind',['live','failure','fixture','disabled','missing'])
def test_startup_warming(kind):
    started=Event()
    class Live(LarkReader):
        def read(self):
            started.set()
            if kind=='failure': raise RuntimeError('unavailable')
            return FixtureReader(FIXTURES).read()
    class Fixture(FixtureReader):
        def read(self): started.set();return super().read()
    cfg={'LARK_APP_ID':'test','LARK_APP_SECRET':'test'}
    if kind=='disabled': cfg['REPORTS_ENABLED']='false'
    if kind=='missing': cfg.pop('LARK_APP_SECRET')
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def lifespan(app): yield
    app=FastAPI(lifespan=lifespan)
    store=register(app,lambda _:({},{}),cfg,reader=Fixture(FIXTURES) if kind=='fixture' else Live(cfg))
    with TestClient(app):
        assert started.wait(.2)==(kind in ('live','failure'))
    store.close()


def test_reports_logger_emits_info_when_app_has_no_logging():
    import logging
    logger=logging.getLogger('backend.reports')
    for handler in list(logger.handlers): logger.removeHandler(handler)
    logger.setLevel(logging.NOTSET)
    app_for()
    assert logger.isEnabledFor(logging.INFO)
    assert logging.getLogger().handlers or logger.handlers


def test_progress_detail_snapshot_privacy_bounds_and_validation():
    app,store=app_for()
    with TestClient(app) as client:
        page=client.get('/api/reports/progress?week=2026-10-12').json()
        key=page['items'][0]['case_key']
        snapshot=store.get()
        snapshot['data']['cases']['C01']['f']['薪資']=999999
        snapshot['data']['plan_indices'][('field','2026-10-12')]*=201
        store.reader.read=lambda:pytest.fail('warm detail must not read Lark')
        response=client.get('/api/reports/progress/case',params={'key':key,'week':'2026-10-12'})
        assert response.status_code==200,response.text
        body=response.json()
        assert body['case']['code']=='C01'
        assert body['case']['contract']=={'expected':100.0,'actual':None}
        assert len(body['week']['plan_rows'])==200
        assert body['week']['truncated'] is True
        assert '薪資' not in response.text and 'fields' not in response.text
        assert response.headers['cache-control']=='no-store'
        assert client.get('/api/reports/progress/case?key=missing').json()=={'detail':'case_not_found'}
        assert client.get('/api/reports/progress/case?key=missing').status_code==404
        for query in ('q='+('x'*51),'status=unknown','sort=unknown'):
            assert client.get('/api/reports/progress?'+query).status_code==422
        assert client.get('/api/reports/progress?sort=name').status_code==200
        assert client.get('/api/reports/progress/case').status_code==422
    store.close()


def test_progress_detail_role_gate():
    app,store=app_for(allow=lambda *_:False)
    with TestClient(app) as client:
        assert client.get('/api/reports/progress/case?key=c1').status_code==403
    store.close()
