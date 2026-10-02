from copy import deepcopy
import pytest
from fastapi import HTTPException
from .finance_readiness import incoming_readiness,financial_readiness
from .seed import seed
from .policy import upgrade
from .operations import apply_operation,missing,project_summary
from .workflow import now

def quote():
    return {'id':'v4:quote:record','quote_code':'115001','fields':{'案件已入帳':True,'入帳日期':'2026-09-27','入帳資料檢核':'已核對','累計已入帳':100,'累計已請款':100,'案件可請款總額':100,'可請款未請':0}}

def prepare(monkeypatch):
    ws=upgrade(seed());ws['environment']='production';p=ws['projects'][0]
    p['execution_system']='workbench'
    p.update(pm_id='u-pm',admin_id='u-manager',source_status='已結案',quotes=[quote()])
    for n in p['nodes']:
        n.update(status='completed',source_completed=False)
        for t in n['tasks']:t.update(status='completed',output='實際成果')
        for rule in n['requirements']:
            p['evidence'].append({'id':n['id']+'-'+rule['key'],'node_id':n['id'],'key':rule['key'],'status':'accepted','url':'https://example.com/source-proof'})
    pricing=next(n for n in p['nodes'] if n['key']=='pricing');settlement=next(n for n in p['nodes'] if n['key']=='settlement');settlement['status']='in_progress'
    ws['financial_requests']=[{'id':'pricing-native','project_id':p['id'],'node_id':pricing['id'],'status':'approved','native_receipt':{'verified_at':now()}},
        {'id':'settlement-native','project_id':p['id'],'node_id':settlement['id'],'status':'approved','payables_declaration':'no_payables','reason':'本案無下包支出，已依結算證據核對','evidence_ids':[settlement['id']+'-settlement'],'native_receipt':{'verified_at':now()}}]
    monkeypatch.setattr('backend.native_requests.receipt_valid',lambda *args,**kwargs:args[3].get('mock_valid',True))
    actor=next(u for u in ws['users'] if u['id']=='u-manager')
    return ws,p,settlement,actor

def test_incoming_compares_each_source_without_double_adding_same_quote():
    q=quote();p={'quotes':[q,deepcopy(q)]};result=incoming_readiness(p)
    assert result['status']=='incoming_settled' and len(result['quotes'])==1 and result['aggregated_amount'] is None

@pytest.mark.parametrize('field,value',[('案件已入帳',False),('案件已入帳','true'),('入帳日期',None),('入帳日期','2099-01-01'),('入帳資料檢核','待檢核'),('累計已入帳',99),('累計已請款',None),('案件可請款總額',101),('可請款未請',1),('累計已入帳','NaN')])
def test_no_checkbox_or_approval_can_replace_full_income_consistency(field,value):
    q=quote();q['fields'][field]=value
    assert incoming_readiness({'quotes':[q]})['status']=='unverified'

def test_empty_quotes_and_zero_local_ledger_never_prove_paid():
    assert incoming_readiness({'quotes':[]})['missing']

def test_formal_settlement_uses_source_and_native_declaration_without_local_ledger(monkeypatch):
    ws,p,n,actor=prepare(monkeypatch)
    p['finance_versions']=[];p['payment_batches']=[];p['payment_reconciliation']={'confirmed':False}
    assert financial_readiness(ws,p)['ready'] and not missing(p,n,ws)
    apply_operation(ws,actor,{'action':'financial_finalize','project_id':p['id'],'node_id':n['id'],'payload':{}},False)
    assert n['status']=='completed' and p['execution_status']=='completed'
    assert n['review_cycles'][-1]['mode']=='native' and n['review_cycles'][-1]['votes']==[]
    assert p['finance_versions']==[] and p['payment_batches']==[]
    assert project_summary(ws,p)['closure']['status']=='completed'

@pytest.mark.parametrize('problem',['unknown_payables','receipt_revoked','evidence_withdrawn','incoming_inconsistent'])
def test_formal_closure_blocks_each_independent_missing_fact(monkeypatch,problem):
    ws,p,n,actor=prepare(monkeypatch);request=ws['financial_requests'][-1]
    if problem=='unknown_payables':request['payables_declaration']='unknown'
    if problem=='receipt_revoked':request['mock_valid']=False
    if problem=='evidence_withdrawn':next(e for e in p['evidence'] if e['id']==request['evidence_ids'][0])['withdrawn']=True
    if problem=='incoming_inconsistent':p['quotes'][0]['fields']['累計已入帳']=10
    with pytest.raises(HTTPException):apply_operation(ws,actor,{'action':'financial_finalize','project_id':p['id'],'node_id':n['id'],'payload':{}},False)
    assert n['status']!='completed'

def test_formal_financial_local_votes_are_disabled_even_with_native_receipt(monkeypatch):
    ws,p,n,actor=prepare(monkeypatch)
    with pytest.raises(HTTPException) as exc:apply_operation(ws,actor,{'action':'review_submit','project_id':p['id'],'node_id':n['id'],'payload':{}},False)
    assert exc.value.status_code==403
