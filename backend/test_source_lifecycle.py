from .test_new_daily_acceptance import setup,row,link,BASE
from .sources import import_sources
from .source_lifecycle import summarize
from .company_dashboard import overview


def project(state,code):
    return next(p for p in state['projects'] if p['code']==code)

def quote(rid,fields):
    return {'base_token':BASE,'table_id':'quotes','record_id':rid,'kind':'quote','fields':fields}


def test_explicit_closed_lifecycle_maps_without_completing_delivery():
    state,records=setup();records[0]['fields']['狀態']='已結案'
    import_sources(state,records);lc=project(state,'C115901')['source_lifecycle']
    assert lc['canonical']=='已結案' and lc['state']=='mapped' and lc['relationship']=='已關聯確認單'
    assert lc['lifecycle_sources'][0]['raw']=='已結案' and project(state,'C115901')['status']=='pending'


def test_blank_lifecycle_needs_verification_and_is_not_inferred_closed():
    state,records=setup();records[0]['fields'].pop('狀態')
    q=quote('recQ',{'報價編號':'Q1','此案確認單':link('confirmation','recCaseA'),'狀態':'成案','案件已入帳':True,'累計已入帳':1000,'入帳日期':'2026-09-28'})
    import_sources(state,records+[q]);p=project(state,'C115901');lc=p['source_lifecycle']
    assert lc['state']=='needs_verification' and lc['reasons']==['blank'] and lc['canonical'] is None
    assert lc['quote_workflow'][0]['raw']=='成案'
    assert p['source_status']=='來源狀態待核對'
    assert not any(n['source_declared_completed'] for n in p['nodes'])


def test_unknown_legacy_option_is_preserved_and_flagged():
    lc=summarize([],[quote('recQ',{'案件狀態':'舊流程標籤','狀態':'2026-09-01'})])
    assert lc['lifecycle_sources'][0]['raw']=='舊流程標籤' and lc['lifecycle_sources'][0]['state']=='unknown'
    assert lc['state']=='needs_verification' and lc['reasons']==['unknown_option'] and lc['canonical'] is None
    assert lc['quote_workflow'][0]['kind']=='date'


def test_quote_lifecycle_conflicting_with_confirmation_has_no_priority():
    state,records=setup();records[0]['fields']['狀態']='已結案'
    q=quote('recQ',{'報價編號':'Q1','此案確認單':link('confirmation','recCaseA'),'案件狀態':'執行中'})
    import_sources(state,records+[q]);p=project(state,'C115901');lc=p['source_lifecycle']
    assert lc['state']=='needs_verification' and lc['reasons']==['conflict'] and lc['canonical'] is None
    assert {e['raw'] for e in lc['lifecycle_sources']}=={'已結案','執行中'}
    assert not any(n['source_declared_completed'] for n in p['nodes'])


def test_relationship_classification_is_separate_from_quote_and_lifecycle():
    state,records=setup()
    q=quote('recOpen',{'報價編號':'Q9','狀態':'成案','案件狀態':'已結案'})
    import_sources(state,records+[q])
    p=next(p for p in state['projects'] if p.get('case_type')=='intake')
    lc=p['source_lifecycle']
    assert p['source_status']=='待確認單' and lc['relationship']=='待確認單'
    assert lc['quote_workflow'][0]['raw']=='成案' and lc['canonical']=='已結案'
    blank=summarize([],[quote('recB',{'狀態':'成案'})])
    assert blank['relationship']=='待確認單' and blank['canonical'] is None and blank['reasons']==['blank']
    row_=next(r for r in overview(state)['cases'] if r['id']==p['id'])
    assert row_['source_status']=='待確認單' and row_['source_lifecycle']['canonical']=='已結案'


def test_quote_projection_requests_both_status_fields_and_keeps_them_separate(monkeypatch):
    import json, httpx
    from .sources import FIELDS, fetch_sources
    assert {'狀態','案件狀態'} <= set(FIELDS['quote'])
    monkeypatch.setenv('LARK_QUOTE_BASE_TOKEN','synthetic-base')
    monkeypatch.setenv('LARK_SOURCE_TABLES_JSON',json.dumps([{'name':'quotes','base_token':'synthetic-base','table_id':'synthetic-quotes','kind':'quote'}]))
    requested=[]
    class MockClient:
        def __init__(self,**kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def get(self,url,headers,params):
            if url.endswith('/fields'):
                names=['報價編號','工程名稱','狀態','案件狀態']
                return httpx.Response(200,json={'code':0,'data':{'items':[{'field_name':n} for n in names],'has_more':False}})
            requested.append(json.loads(params['field_names']))
            fields={'報價編號':'SYN-1','工程名稱':'合成案件','狀態':'成案','案件狀態':'已結案'}
            wanted=requested[-1]
            return httpx.Response(200,json={'code':0,'data':{'items':[{'record_id':'recSyn','fields':{k:v for k,v in fields.items() if k in wanted}}],'has_more':False}})
    monkeypatch.setattr('backend.sources.httpx.Client',MockClient)
    result=fetch_sources('synthetic-token')
    assert {'狀態','案件狀態'} <= set(requested[0])
    fields=result['records'][0]['fields']
    assert fields['狀態']=='成案' and fields['案件狀態']=='已結案'
    lc=summarize([],[{'base_token':'synthetic-base','record_id':'recSyn','table_id':'synthetic-quotes','fields':fields}])
    assert lc['quote_workflow'][0]['raw']=='成案' and lc['canonical']=='已結案' and lc['state']=='mapped'


def test_cockpit_counts_and_filters_lifecycle_apart_from_relationship_and_quote_workflow():
    state,records=setup();records[0]['fields'].pop('狀態')
    q=quote('recQ',{'報價編號':'Q1','此案確認單':link('confirmation','recCaseA'),'狀態':'成案','案件已入帳':True,'入帳日期':'2026-09-28'})
    open_quote=quote('recOpen',{'報價編號':'Q9','狀態':'成案','案件狀態':'已結案'})
    import_sources(state,records+[q,open_quote]);result=overview(state)
    assert result['totals']['lifecycle_counts']=={'待核對':1,'已結案':1,'執行中':1}
    blank=next(r for r in result['cases'] if r['code']=='C115901')
    assert blank['source_lifecycle']['canonical'] is None and blank['source_lifecycle']['relationship']=='已關聯確認單'
    assert blank['source_lifecycle']['quote_workflow']==[{'raw':'成案','kind':'won'}]
    assert [r['code'] for r in overview(state,lifecycle='待核對')['cases']]==['C115901']
    closed=overview(state,lifecycle='已結案')['cases']
    assert len(closed)==1 and closed[0]['source_lifecycle']['relationship']=='待確認單' and closed[0]['source_status']=='待確認單'
