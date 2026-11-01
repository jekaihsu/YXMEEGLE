import asyncio
import json
import pytest
from .test_ai_database import app, client, ai_database_url
from .ai.datasets import REGISTRY, query, describe, index
from .ai.tools import execute, result_display, TOOLS
from .ai.providers import Event, ToolCall
from .test_ai_api import Fake, BODY, events


PAYLOADS = {
 'report_review':{'items':[dict(date='2026-10-26',person='甲',case_code='C1',status='passed',points=2)],'total':1},
 'report_sales':{'items':[dict(code='C1',name='工程',client='業主',pm='甲',status='open',contract=999999)],'total':1},
 'report_progress':{'items':[dict(case_code='C1',case_name='工程',expected_total=4,done_total=2,remaining=2,status='open')],'total':1},
 'report_assets':{'items':[dict(name='車1',category='車',status='active',owner='甲',uses=4,idle_days=2,daily_rent=999)],'total':1},
 'report_contacts':{'items':[dict(contact_date='2026-10-26',case_code='C1',case_name='工程',person='甲',next_date='2026-11-02',result_status='pending')],'total':1},
 'daily_reports':{'items':[dict(id='d1',date='2026-10-26',person='甲',project_code='C1',department='field',description='測量')],'total':1},
 'sop_tasks':{'tasks':[dict(id='t1',title='測量',state='in_progress',overdue=True,applicability='applicable')]},
 'node_detail':{'tasks':[dict(id='t1',title='測量',status='pending',assignee={'name':'甲'},deadline='2026-11-02')]},
 'contract_detail':{'sections':{'contract_lines':{'rows':[dict(item_number='1',label='測量',amount=999)]}}},
 'dispatch_board':{'slots':[dict(slot_id='s1',interval={'start':'2026-11-02'},group='外業',case={'name':'工程'},work_content='測量',planning_status='confirmed')]},
}


@pytest.mark.parametrize('ident',PAYLOADS)
def test_projectors(ident):
    class Reader:
        async def get(self,path,**params):
            assert path.startswith('/api/') and '{' not in path
            if ident=='node_detail':
                assert params=={}
            return PAYLOADS[ident]
    params={'case_id':'p1'} if ident=='sop_tasks' else {'case_id':'p1','node_key':'field'} if ident=='node_detail' else {'case_id':'p1'} if ident=='contract_detail' else {}
    data=asyncio.run(query(Reader(),ident,params,20,0))
    assert len(data['rows'])==1
    assert set(data['rows'][0])=={c['name'] for c in data['columns']}
    assert all(v is not None for k,v in data['rows'][0].items() if k in ('name','code','title','id'))
    assert '999' not in json.dumps(data['rows'])
    assert data['total']==1 and data['next_offset'] is None and data['result_id'].startswith('r')
    assert describe(ident)['params']['additionalProperties'] is False


@pytest.mark.parametrize('args',[
 dict(id='bad',params={},limit=20,offset=0),dict(id='report_sales',params={'sql':'x'},limit=20,offset=0),
 dict(id='report_sales',params={},limit=True,offset=0),dict(id='report_sales',params={},limit=51,offset=0),
 dict(id='case_owners',params={'case_id':'../x'},limit=20,offset=0),
 dict(id='report_assets',params={'from':'not-date'},limit=20,offset=0)])
def test_validation(app,args):
    result,error=asyncio.run(execute(app,'','query_dataset',args))
    assert error and json.loads(result)['error'] in ('工具參數錯誤', '參數錯誤')


@pytest.mark.parametrize('status',[403,404])
def test_denied_route(app,monkeypatch,status):
    import httpx
    async def get(self,path,**kwargs):
        return httpx.Response(status,request=httpx.Request('GET','http://ai.internal'+path))
    monkeypatch.setattr(httpx.AsyncClient,'get',get)
    result,error=asyncio.run(execute(app,'','query_dataset',dict(id='report_sales',params={},limit=20,offset=0)))
    assert error and json.loads(result)['code']=='ai_forbidden'


def test_catalog_flow_and_model_selected_chart(app,client,monkeypatch):
    from .ai.tools import Reader
    async def read(self,path,**params):
        assert path=='/api/reports/assets'
        return PAYLOADS['report_assets']
    monkeypatch.setattr(Reader,'get',read)
    class Scripted(Fake):
        async def stream(self,spec,system,messages,tools):
            assert set(tools)=={'list_datasets','describe_dataset','query_dataset','show_display'}
            step=len(self.inputs)
            self.inputs.append(messages.copy())
            if step==0: name,args='list_datasets',{}
            elif step==1: name,args='describe_dataset',{'id':'report_assets'}
            elif step==2: name,args='query_dataset',dict(id='report_assets',params={'kind':'vehicle'},limit=20,offset=0)
            elif step==3:
                data=json.loads(messages[-1]['content'][0]['content'])
                name,args='show_display',dict(result_id=data['result_id'],kind='bar',columns=[],mapping={'x':'name','y':'uses'},max_rows=24)
            else:
                yield Event('text','車1使用4次。')
                yield Event('stop',[])
                return
            call=ToolCall(str(step),name,args)
            yield Event('tool',call)
            yield Event('stop',[{'type':'tool_use','id':call.id,'name':name,'input':args}])
    app.state.ai_providers={'claude':Scripted()}
    output=events(client.post('/api/ai/chat',json=BODY))
    assert not any(e['type']=='error' for e in output),output
    display=next(e['displays'][0] for e in output if e.get('displays'))
    assert display['kind']=='bar' and display['points']==[dict(label='車1',value=4)]


def test_display_validation_and_caps():
    data=dict(dataset_id='assets',columns=[dict(name='name',label='名稱',type='text'),dict(name='uses',label='次數',type='number')],
        rows=[dict(name=str(i),uses=i) for i in range(60)],truncated=False,as_of=None,limitations=[])
    args=dict(result_id='r1',kind='bar',columns=[],mapping={'x':'name','y':'uses'},max_rows=50)
    result,error=result_display({'r1':data},args)
    assert error is None and len(result['points'])==24 and result['truncated']
    assert result_display({'r1':data},{**args,'mapping':{'x':'name','y':'name'}})[1]
    result,error=result_display({'r1':data},{**args,'kind':'table'})
    assert len(result['rows'])==50 and error is None


def test_generic_queries_reuse_real_authorized_routes(app,client):
    cookie='; '.join(f'{k}={v}' for k,v in client.cookies.items())
    source=client.get('/api/daily-reports?limit=20').json()
    data,error=asyncio.run(execute(app,cookie,'query_dataset',dict(id='daily_reports',params={},limit=20,offset=0)))
    result=json.loads(data)
    assert not error and result['total']==source['total']
    assert [r['id'] for r in result['rows']]==[r['id'] for r in source['items']]
    for ident,params in [('report_sales',{}),('node_detail',dict(case_id='p1',node_key='field'))]:
        data,error=asyncio.run(execute(app,cookie,'query_dataset',dict(id=ident,params=params,limit=20,offset=0)))
        assert error and json.loads(data)['code']=='ai_forbidden'


def test_real_report_progress_excludes_financial_points():
    from .test_reports_compute import dataset
    from .reports.compute import progress
    raw = progress(dataset(), dept='field', week='2026-10-12')
    assert raw['items'][0]['remaining'] == 12
    class Reader:
        async def get(self, path, **params):
            return raw
    result = asyncio.run(query(Reader(), 'report_progress', {'week':'2026-10-12'}, 20, 0))
    assert not {'expected_total','done_total','remaining','planned','actual','matched_points','achievement','diff'} & set(result['rows'][0])
    assert result['rows'][0]['planned_days'] == raw['items'][0]['planned_days']


def test_dataset_finance_name_guard():
    import re
    forbidden = re.compile(r'revenue|amount|營業額|金額|expected_total|done_total|remaining|points', re.I)
    for dataset in REGISTRY.values():
        for column in dataset.columns:
            assert not forbidden.search(column.name + column.label), dataset.id


def test_route_validation_error_detail(app, monkeypatch):
    import httpx
    async def get(self, path, **kwargs):
        return httpx.Response(422, json={'detail':'week 必須為週一'}, request=httpx.Request('GET','http://ai.internal'+path))
    monkeypatch.setattr(httpx.AsyncClient, 'get', get)
    data, error = asyncio.run(execute(app, '', 'query_dataset', dict(id='report_review', params={}, limit=20, offset=0)))
    assert error and json.loads(data) == {'error':'參數錯誤','detail':'week 必須為週一'}


def test_catalog_parameter_guidance_and_opaque_ids():
    assert 'actor_id' not in REGISTRY['daily_reports'].params.model_fields
    assert 'q' in REGISTRY['daily_reports'].description
    for dataset in REGISTRY.values():
        description = describe(dataset.id)
        assert description['example']['params']
        assert all(p.get('description') for p in description['params']['properties'].values())
        assert all(c.get('description') for c in description['columns'])
    assert '週一' in describe('report_review')['params']['properties']['week']['description']


def test_query_budget_defaults_and_applied_params(app, monkeypatch):
    from .ai.tools import Reader
    async def get(self, path, **params):
        assert params['limit'] == 20
        return {'items':[dict(name='車'*240, category='車'*240, status='a'*240, owner='甲'*240, uses=i, idle_days=2) for i in range(20)], 'total':40}
    monkeypatch.setattr(Reader, 'get', get)
    text, error = asyncio.run(execute(app, '', 'query_dataset', dict(id='report_assets',params={})))
    assert not error
    result = json.loads(text)
    assert len(text) <= 6000 and 'summary' not in result
    assert result['truncated'] and result['next_offset'] == len(result['rows'])
    assert result['applied_params']['from'] and result['applied_params']['to']


def test_display_human_title_all_kinds():
    data=dict(dataset_id='report_assets',columns=[dict(name='name',label='名稱',type='text'),dict(name='uses',label='次數',type='number')],
        rows=[dict(name='車1',uses=4)],truncated=False,as_of=None,limitations=[])
    for kind in ('table','bar','line','pie','stat'):
        result, error = result_display({'r1':data}, dict(result_id='r1', kind=kind, columns=[], mapping={'x':'name','y':'uses'}, max_rows=20))
        assert error is None and result['title']=='資產使用'
        assert result['rows'] if kind=='table' else result['points']==[dict(label='車1',value=4)]


def test_search_pm_names_and_id_label():
    from .ai.tools import project_search
    raw = dict(population_total=2, matched_total=2, items=[dict(id='p1',state='進行中',pm_id='u1',pm_name='王小明'),dict(id='p2',state='進行中',pm_id='u2')])
    rows = project_search(raw)['cases']
    assert rows[0]['pm_id']=='王小明'
    assert rows[1]['pm_id']=='ID: u2'


@pytest.mark.parametrize('name',['search_cases','attendance_today','invented_tool'])
def test_unoffered_tools_never_execute(app, client, monkeypatch, name):
    async def forbidden(*args):
        pytest.fail('unoffered tool executed')
    monkeypatch.setattr('backend.ai.agent.execute', forbidden)
    app.state.ai_providers={'claude':Fake(calls=[ToolCall('bad',name,{})])}
    output=events(client.post('/api/ai/chat',json=BODY))
    assert any(e.get('status')=='error' or e['type']=='error' for e in output)


def test_opaque_contract_key_replaced_with_discoverable_case_id():
    dataset = REGISTRY['contract_detail']
    assert set(dataset.params.model_fields) == {'case_id'}
    assert 'id' in {c.name for c in REGISTRY['search_cases'].columns}
    class Reader:
        async def get(self, path, **params):
            assert path == '/api/case-detail/p1' and params == {}
            return {'sections':{'contract_lines':{'rows':[dict(key='opaque-contract-key',label='測量',item_number='1',amount=999)]}}}
    result=asyncio.run(query(Reader(),'contract_detail',{'case_id':'p1'},20,0))
    assert result['rows']==[dict(line_number='1',name='測量')]


def test_legacy_query_has_no_duplicate_summary(app, client):
    cookie='; '.join(f'{k}={v}' for k,v in client.cookies.items())
    text,error=asyncio.run(execute(app,cookie,'query_dataset',dict(id='search_cases',params={},limit=20,offset=0)))
    assert not error and json.loads(text)['rows']
    assert 'summary' not in json.loads(text) and len(text)<=6000


def test_explicit_query_limit_still_obeys_budget():
    class Reader:
        async def get(self,path,**params):
            return {'items':[dict(name='車'*240,category='車'*240,status='a'*240,owner='甲'*240,uses=i,idle_days=2) for i in range(20)],'total':40}
    result=asyncio.run(query(Reader(),'report_assets',{},20,0))
    assert len(json.dumps(result,ensure_ascii=False))<=6000
    assert result['next_offset']==len(result['rows'])<20 and result['truncated']


def test_default_report_week_is_applied():
    from datetime import date,timedelta
    from .ai.tools import today
    class Reader:
        async def get(self,path,**params):
            self.params=params
            return {'items':[], 'total':0}
    reader=Reader()
    result=asyncio.run(query(reader,'report_review',{},20,0))
    current=date.fromisoformat(today())
    assert result['applied_params']['week']==(current-timedelta(days=current.weekday()+7)).isoformat()
    assert {k:v for k,v in result['applied_params'].items() if v != ''}==reader.params


@pytest.mark.parametrize('failure',[500,'timeout'])
def test_route_failures_remain_retryable(app, monkeypatch, failure):
    import httpx
    async def get(self,path,**params):
        if failure=='timeout':
            raise httpx.ReadTimeout('slow source')
        return httpx.Response(failure,request=httpx.Request('GET','http://ai.internal'+path))
    monkeypatch.setattr(httpx.AsyncClient,'get',get)
    text,error=asyncio.run(execute(app,'','query_dataset',dict(id='report_sales',params={})))
    assert error and json.loads(text)['retryable'] is True


@pytest.mark.parametrize('ident,params,field', [
    ('attendance_today', {'range':'month'}, 'range'),
    ('attendance_today', {'date':'2026-02-30'}, 'date'),
    ('attendance_today', {'date':'2000-01-01'}, 'date'),
    ('case_progress', {'case_id':'../bad'}, 'case_id'),
    ('case_owners', {}, 'case_id'),
    ('report_assets', {'from':'yesterday'}, 'from'),
])
def test_correctable_argument_fields(app, ident, params, field):
    text, error = asyncio.run(execute(app, '', 'query_dataset', dict(id=ident,params=params)))
    data = json.loads(text)
    assert error and data['field'] == ['params', field] and data['detail']


@pytest.mark.parametrize('status', [408,409,429])
def test_transient_client_status_is_retryable(app, monkeypatch, status):
    import httpx
    async def get(self,path,**kwargs):
        return httpx.Response(status,json={'detail':'temporary'},request=httpx.Request('GET','http://ai.internal'+path))
    monkeypatch.setattr(httpx.AsyncClient, 'get', get)
    text,error = asyncio.run(execute(app,'','query_dataset',dict(id='report_sales',params={})))
    assert error and json.loads(text)['retryable'] is True


def test_search_boolean_display_cells(app, client, monkeypatch):
    from .ai.tools import Reader
    source = client.get('/api/workspace').json()
    source['projects'].append(dict(id='closed',code='CLOSED',name='完成案件',nodes=[dict(key='field',status='completed')]))
    async def get(self,path,**params):
        assert path == '/api/workspace'
        return source
    monkeypatch.setattr(Reader,'get',get)
    cookie = '; '.join(f'{k}={v}' for k,v in client.cookies.items())
    text,error = asyncio.run(execute(app,cookie,'query_dataset',dict(id='search_cases',params={})))
    data = json.loads(text)
    assert not error
    assert {row['overdue'] for row in data['rows']} == {True,False}
    display,error = result_display({data['result_id']:data},dict(result_id=data['result_id'],kind='table',
        columns=['name','overdue'],mapping={},max_rows=50))
    assert error is None
    assert {row['overdue'] for row in display['rows']} == {'是','否'}
    assert all(type(v) in (str,int,float,type(None)) for row in display['rows'] for v in row.values())
