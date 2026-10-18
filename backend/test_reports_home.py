from collections import Counter
from copy import deepcopy
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest
from backend.reports import compute, routes
from backend.reports.home import PARTS, compose
from backend.reports.reader import FixtureReader
from backend.test_reports_compute import FIXTURES


@pytest.fixture
def home(monkeypatch):
    class Monday(datetime):
        @classmethod
        def now(cls, tz=None): return cls(2026,10,19,12,tzinfo=tz)
    monkeypatch.setattr(routes,'datetime',Monday)
    app=FastAPI()
    store=routes.register(app,lambda _:({'wid':'company','mode':'lark'},{'role':'pm'}),{},reader=FixtureReader(FIXTURES),allow=lambda d,u:u['role'] in ('pm','manager'))
    with TestClient(app) as client: yield client,store
    store.close()


def test_home_fixture_shape_projections_and_literals(home):
    client,store=home
    response=client.get('/api/reports/home')
    assert response.status_code==200,response.text
    assert response.headers['cache-control']=='no-store'
    body=response.json()
    assert set(body)=={'meta','week','quality','quality_office','sales','progress','assets'}
    assert set(body['meta'])=={'fetched_at','stale','snapshot','gaps','refresh_error'}
    assert body['week']=='2026-10-12'
    gaps={}
    for part in PARTS:
        reports=[]
        for endpoint,params in part.sources:
            report=client.get('/api/reports/'+endpoint,params=params).json()
            assert report['meta']['snapshot']==body['meta']['snapshot']
            reports.append(report)
            for gap in report['meta']['gaps']: gaps.setdefault(gap['id'],gap)
        if part.name=='assets':
            expected={kind:{key:report[key] for key in ('kpi','by_category')} for kind,report in zip(('instrument','vehicle'),reports)}
        else:
            keys={'quality':('kpi','kpi_prev','trend','by_group','control'),'quality_office':('kpi',),'sales':('kpi','by_status'),'progress':('week','basis','kpi','by_group')}[part.name]
            expected={key:reports[0][key] for key in keys}
            if part.name=='sales': expected['top_receivable']=[row for row in reports[0]['items'] if row['receivable'] is not None and row['receivable']>0][:5]
        assert body[part.name]==expected
    assert body['meta']['gaps']==list(gaps.values())
    assert body['quality']['kpi']==dict(total=4,passed=1,returned=1,pending=1,unset=1,error_rate=.5,pending_rate=.25,coverage=.5)
    assert body['quality']['control']==dict(checked=1,unchecked=1,violated=1)
    assert body['quality_office']['kpi']['coverage']==0
    assert body['sales']['kpi']['contract_total']==100
    assert body['progress']['kpi']['planned_points']==8
    assert body['assets']['instrument']['kpi']['repair']==1
    assert body['sales']['kpi']['billed_total'] is None
    assert body['sales']['kpi']['received_total'] is None
    assert body['sales']['kpi']['unbilled_billable'] is None
    assert body['assets']['vehicle']['kpi']['daily_rent_total'] is None


def test_home_top_receivable_caps_filters_and_sorts(home):
    client,store=home
    raw=FixtureReader(FIXTURES).read()
    raw['case']['records']=[dict(record_id='rec'+str(i),fields={'案件編號':str(i),'應收未收':amount}) for i,amount in enumerate([None,0,-3,2,70,5,10,30,20,40,60])]
    store.reader.read=lambda:raw
    body=client.get('/api/reports/home').json()
    rows=body['sales']['top_receivable']
    assert len(rows)==5
    assert [row['receivable'] for row in rows]==[70,60,40,30,20]
    assert all(row['receivable']>0 for row in rows)
    assert all(row['contract'] is None and row['billable_unbilled'] is None for row in rows)
    assert rows==client.get('/api/reports/sales?sort=receivable&order=desc&limit=200').json()['items'][:5]


@pytest.mark.parametrize('part,endpoint,filter_key,filter_value',[
    ('quality','review','dept','field'),('quality_office','review','dept','office'),
    ('sales','sales',None,None),('progress','progress',None,None),
    ('assets','assets','kind','instrument'),('assets','assets','kind','vehicle'),
])
def test_home_part_failure_is_independent(home,monkeypatch,part,endpoint,filter_key,filter_value):
    client,store=home
    baseline=client.get('/api/reports/home').json()
    result=store.result
    def failing(name,params,**kwargs):
        if name==endpoint and (filter_key is None or params[filter_key]==filter_value): raise RuntimeError('private diagnostic')
        return result(name,params,**kwargs)
    monkeypatch.setattr(store,'result',failing)
    response=client.get('/api/reports/home');body=response.json()
    assert response.status_code==200
    assert body[part] is None
    for key in ('quality','quality_office','sales','progress','assets'):
        if key!=part: assert body[key]==baseline[key]
    failure=next(g for g in body['meta']['gaps'] if g['id']=='home-'+part+'-failed')
    assert failure==dict(id='home-'+part+'-failed',severity='warn',message=next(p.failure for p in PARTS if p.name==part))
    assert 'private diagnostic' not in response.text
    assert len({g['id'] for g in body['meta']['gaps']})==len(body['meta']['gaps'])


def test_home_cache_reuses_all_six_results(home,monkeypatch):
    client,store=home;calls=Counter();reads=[]
    for endpoint in ('review','sales','progress','assets'):
        original=getattr(compute,endpoint)
        def counted(data,_endpoint=endpoint,_original=original,**params):
            calls[(_endpoint,params.get('dept',params.get('kind','')))]+=1
            return _original(data,**params)
        monkeypatch.setattr(compute,endpoint,counted)
    read=store.reader.read
    def reader(): reads.append(1);return read()
    monkeypatch.setattr(store.reader,'read',reader)
    first=client.get('/api/reports/home').json()
    assert client.get('/api/reports/home').json()==first
    assert calls=={('review','field'):1,('review','office'):1,('sales',''):1,('progress','field'):1,('assets','instrument'):1,('assets','vehicle'):1}
    assert reads==[1]


def test_home_pins_snapshot_when_refresh_changes_store(home,monkeypatch):
    client,store=home
    baseline=client.get('/api/reports/home').json()
    original=store.get();replacement=deepcopy(original)
    replacement.update(fingerprint='different-snapshot',cache={},pending={})
    replacement['data']['tables']['case']=[]
    result=store.result;seen=[]
    def refreshing(endpoint,params,**kwargs):
        seen.append(kwargs['snapshot'])
        if len(seen)==1:
            with store._lock: store._snapshot=replacement
        return result(endpoint,params,**kwargs)
    monkeypatch.setattr(store,'result',refreshing)
    assert client.get('/api/reports/home').json()==baseline
    assert len(seen)==6 and all(snapshot is original for snapshot in seen)
    assert store.get() is replacement


@pytest.mark.parametrize('cfg,wid,mode,role,status',[
    ({},'company','lark','staff',403),({},'demo-company','lark','pm',403),
    ({},'test-company','lark','manager',403),({},'company','demo','pm',403),
    ({'REPORTS_ENABLED':'false'},'company','lark','pm',404),({},'company','lark','manager',200),
])
def test_home_gate(cfg,wid,mode,role,status):
    app=FastAPI();store=routes.register(app,lambda _:({'wid':wid,'mode':mode},{'role':role}),cfg,reader=FixtureReader(FIXTURES),allow=lambda d,u:u['role'] in ('pm','manager'))
    try:
        with TestClient(app) as client:
            response=client.get('/api/reports/home')
            assert response.status_code==status
            assert response.headers['cache-control']=='no-store'
    finally: store.close()


@pytest.mark.parametrize('query',['week=2026-10-12','dept=field','limit=200','q=','anything=x'])
def test_home_rejects_every_query_parameter(home,monkeypatch,query):
    client,store=home
    monkeypatch.setattr(store,'get',lambda:pytest.fail('invalid query must not read snapshot'))
    response=client.get('/api/reports/home?'+query)
    assert response.status_code==422
    assert response.headers['cache-control']=='no-store'


def test_home_snapshot_failure_matches_existing_endpoint(home,monkeypatch):
    client,store=home
    def read(): raise RuntimeError('private upstream diagnostic')
    monkeypatch.setattr(store.reader,'read',read)
    response=client.get('/api/reports/home')
    other=client.get('/api/reports/sales')
    assert response.status_code==other.status_code==503
    assert response.json()==other.json()==dict(detail='報表來源暫時無法讀取',warming=False)
    assert response.headers['cache-control']=='no-store'


def test_home_composer_preserves_http_errors(home):
    client,store=home
    snapshot=store.get()
    def result(*args): raise HTTPException(503,'unavailable')
    with pytest.raises(HTTPException) as error: compose(result,store.meta(snapshot),'2026-10-12')
    assert error.value.status_code==503


def test_home_composer_deduplicates_gaps_without_mutating_meta(home):
    client,store=home
    snapshot=store.get();meta=store.meta(snapshot);before=deepcopy(meta)
    shared=dict(id='shared',severity='warn',message='共用來源缺漏。')
    def result(endpoint,params):
        report=store.result(endpoint,params,snapshot=snapshot)
        report['meta']['gaps']=[shared,shared]
        return report
    body=compose(result,meta,'2026-10-12')
    assert body['meta']['gaps']==[shared]
    assert meta==before


def test_home_cold_warming_matches_existing_endpoint(home,monkeypatch):
    client,store=home
    def warming():
        raise HTTPException(503,dict(detail='報表資料正在首次讀取，請稍候',warming=True,retry_after=5),headers={'Retry-After':'5'})
    monkeypatch.setattr(store,'get',warming)
    response=client.get('/api/reports/home');other=client.get('/api/reports/review')
    assert response.status_code==other.status_code==503
    assert response.json()==other.json()==dict(detail='報表資料正在首次讀取，請稍候',warming=True,retry_after=5)
    assert response.headers['retry-after']=='5'
    assert response.headers['cache-control']=='no-store'
