from copy import deepcopy
from .test_new_daily_acceptance import setup,row,link,BASE,TABLES
from .sources import import_sources,source_id
from .source_entities import entity_id,update_entities


def test_shared_contract_has_one_amount_entity_with_two_department_task_references():
    state,records=setup();records[2]['fields'].update({'合約工作項目':'共同合約項目','分項金額(報出)':1000})
    records.append(row('reporting','recReportingB',{'來源合約明細（日報關聯）':link('contract','recContractA'),'工項類別':'圖資','工項名稱':'圖資子工作'}))
    import_sources(state,records)
    item=state['contract_items'][0]
    assert item['id']==entity_id(records[2]) and item['amount_reported']==1000
    assert len(item['task_refs'])==2 and len(item['reporting_ids'])==2
    assert sum(i['amount_reported'] or 0 for i in state['contract_items'] if not i['source_missing'])==1000
    assert item['allocation_status']=='unverified' and 'allocated_points' not in item
    tasks=[t for p in state['projects'] for n in p['nodes'] for t in n['tasks'] if t['id'] in {source_id(records[3]),source_id(records[-1])}]
    assert all(t['contract_item_ids']==[item['id']] for t in tasks)


def test_quote_entities_keep_native_confirmation_relation_and_receivable_raw_evidence():
    state,records=setup()
    quote={'base_token':BASE,'table_id':'quotes','record_id':'recQuote','kind':'quote',
           'fields':{'報價編號':'Q001','此案確認單':link('confirmation','recCaseA'),'案件已入帳':True,'累計已入帳':1000,'入帳日期':'2026-09-28'}}
    import_sources(state,records+[quote]);q=state['source_quotes'][0]
    c=next(c for c in state['source_confirmations'] if c['id']==entity_id(records[0]))
    assert q['id']==entity_id(quote) and q['confirmation_ids']==[c['id']] and c['quote_ids']==[q['id']]
    assert q['project_ids']==[c['project_id']] and q['financial']['累計已入帳']==1000
    assert 'paid' not in q and q['readonly']
    before=(q['id'],q['revision'],deepcopy(q['history']))
    import_sources(state,records+[quote]);q=state['source_quotes'][0]
    assert (q['id'],q['revision'],q['history'])==before


def test_entity_revision_and_missing_history_are_idempotent_and_not_inferred_from_partial():
    state,records=setup();prior=deepcopy(state['contract_items'][0])
    records[2]['fields']['分項金額(報出)']=22
    import_sources(state,records);item=state['contract_items'][0]
    assert item['revision']==prior['revision']+1 and item['history'][-1]['snapshot']['fields']==prior['fields']
    remaining=[r for r in records if r['kind']!='contract']
    import_sources(state,remaining)
    assert not state['contract_items'][0]['source_missing']
    table={'base_token':BASE,'table_id':TABLES['contract'],'kind':'contract','status':'ready','count':0}
    import_sources(state,remaining,complete_tables=[table])
    assert state['contract_items'][0]['source_missing']
    history=deepcopy(state['contract_items'][0]['history'])
    import_sources(state,remaining,complete_tables=[table])
    assert state['contract_items'][0]['history']==history


def test_source_closed_is_visible_but_does_not_complete_delivery_or_settlement():
    state,records=setup();records[0]['fields']['狀態']='已結案'
    import_sources(state,records);p=next(p for p in state['projects'] if p['code']=='C115901')
    assert p['source_status']=='已結案' and p['status']==p['execution_status']=='pending'
    assert all(n['status']=='pending' for n in p['nodes'])
    assert all(n['source_declared_completed'] and not n['source_completed'] for n in p['nodes'])
    assert all(t['status']=='pending' for n in p['nodes'] for t in n['tasks'])


def test_quote_with_multiple_confirmations_projects_once_and_preserves_review_identity():
    quote={'base_token':BASE,'table_id':'quotes','record_id':'recQuote','kind':'quote',
           'fields':{'此案確認單':link('confirmation','recA','recB'),'契約價格(未稅)':1000}}
    a=row('confirmation','recA',{});b=row('confirmation','recB',{})
    state={'projects':[{'id':'pA','nodes':[],'quotes':[{'id':source_id(quote)}]},
                       {'id':'pB','nodes':[],'quotes':[]}]}
    update_entities(state,[quote,a,b],[],{source_id(a):'pA',source_id(b):'pB'})
    q=state['source_quotes'][0]
    assert q['project_ids']==['pA','pB'] and q['review_project_ids']==['pA']
    assert q['review_quote_id']==source_id(quote) and q['review_quote_id']!=q['id']
    assert len(state['source_quotes'])==1 and q['amount']==1000
    assert all(p['source_entity_ids']['source_quotes']==[q['id']] for p in state['projects'])
