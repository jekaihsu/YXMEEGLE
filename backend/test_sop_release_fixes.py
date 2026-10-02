from copy import deepcopy
from unittest.mock import patch
import pytest
from fastapi import HTTPException
from .seed import seed
from .policy import upgrade, template
from .operations import apply_operation
from .sources import project_nodes
from .workflow_rules import execution_reasons


@pytest.fixture
def company():
    ws=upgrade(seed()); ws['environment']='demo'
    p=ws['projects'][0]
    p.update(nodes=project_nodes(p['id']),execution_system='workbench',pm_id='u-pm',supervisor_id='u-manager',
             source_status='執行中',execution_status='pending',sop_version=template()['id'])
    upgrade(ws)
    for n in p['nodes']:
        n.update(owner_id='u-pm',supervisor_id='u-manager')
        for t in n['tasks']:t['owner_id']='u-pm'
    return ws,p


def act(company,action,payload,user='u-pm',node=None):
    ws,p=company
    return apply_operation(ws,next(u for u in ws['users'] if u['id']==user),
        dict(action=action,project_id=p['id'],node_id=node,payload=payload))


def test_upgrade_compiles_once_not_per_node_and_preserves_custom_requirements(company):
    ws,p=company; p['nodes'][0]['requirements']=[{'key':'custom','label':'keep'}]
    with patch('backend.policy.template',wraps=template) as compiled:
        upgrade(ws)
    assert compiled.call_count==1
    assert p['nodes'][0]['requirements']==[{'key':'custom','label':'keep'}]


def test_unsupported_condition_rejected_on_publication(company):
    ws,p=company;t=template();t.update(id='unsupported',status='draft')
    t['nodes'][0]['task_definitions'][0]['applicability']='execute_arbitrary_formula'
    ws['sop_templates'].append(t)
    with pytest.raises(HTTPException,match='適用條件'):
        act(company,'sop_publish',{'id':t['id']},user='u-manager')
    assert t['status']=='draft'


def test_pm_cannot_choose_own_reviewer_but_manager_can_manage_roles(company):
    ws,p=company;n=p['nodes'][0];prior=deepcopy(n)
    for data in ({'supervisor_id':'u-pm'},{'node_supervisor_id':'u-pm'}, {'reviewers':['u-pm']},{'review_mode':'any'}):
        with pytest.raises(HTTPException,match='PM 不得'):
            act(company,'project_roles',data,node=n['id'])
    assert n==prior
    act(company,'project_roles',{'node_supervisor_id':'u-control'},user='u-manager',node=n['id'])
    assert n['supervisor_id']=='u-control'


def test_quotation_assistant_roles_accept_real_assignment(company):
    ws,p=company
    act(company,'project_roles',{'quotation_id':'u-field','assistant_id':'u-report'})
    act(company,'sop_event_record',{'event_type':'inquiry_received','scope_key':'quote1','date':'2026-09-30','evidence_url':'https://example.com/proof'})
    task=next(t for n in p['nodes'] for t in n['tasks'] if t.get('sop_rule_id')=='quote_provide')
    assert task['owner_id']=='u-field'
    assert p['assistant_id']=='u-report'


def test_pre_dispatch_contact_can_start_without_permit_but_fieldwork_cannot(company):
    ws,p=company;n=next(n for n in p['nodes'] if n['key']=='field');user=next(u for u in ws['users'] if u['id']=='u-pm')
    contact,work=n['tasks'][:2]
    assert not execution_reasons(ws,p,n,contact)
    assert any('行政公務' in r for r in execution_reasons(ws,p,n,work))
    contact['sop_contract_version']='old-contract'
    assert any('行政公務' in r for r in execution_reasons(ws,p,n,contact))


def test_no_subcontract_decision_unlocks_quote_without_fake_completed_work(company):
    ws,p=company;n=p['nodes'][0];t=next(t for t in n['tasks'] if t.get('sop_task_key')=='quote_provide')
    assert execution_reasons(ws,p,n,t)
    act(company,'sop_applicability_propose',{'applies':False,'groups':[],'reason':'自行施作'})
    prop=p['sop_applicability_proposal']
    with pytest.raises(HTTPException,match='對應組主管'):
        act(company,'sop_applicability_confirm',{'proposal_id':prop['id'],'result':'approved'})
    act(company,'sop_applicability_confirm',{'proposal_id':prop['id'],'result':'approved'},user='u-manager')
    assert not execution_reasons(ws,p,n,t)
    assert t['status']=='pending'
    assert not any(t.get('sop_applicability')=='subcontract' for n in p['nodes'] for t in n['tasks'])


def test_subcontract_multiple_supervisors_confirm_only_own_scope(company):
    ws,p=company
    next(n for n in p['nodes'] if n['key']=='control')['supervisor_id']='u-control'
    next(n for n in p['nodes'] if n['key']=='report')['supervisor_id']='u-report'
    act(company,'sop_applicability_propose',{'applies':True,'groups':['control','report'],'reason':'兩組下包'})
    prop=p['sop_applicability_proposal']; payload={'proposal_id':prop['id'],'result':'approved'}
    with pytest.raises(HTTPException,match='對應組主管'):act(company,'sop_applicability_confirm',payload,user='u-manager')
    act(company,'sop_applicability_confirm',payload,user='u-control')
    assert prop['status']=='pending' and not p.get('sop_applicability')
    act(company,'sop_applicability_confirm',payload,user='u-report')
    assert prop['status']=='approved'
    conditional=[(n['key'],t) for n in p['nodes'] for t in n['tasks'] if t.get('sop_applicability','always')!='always']
    assert {key for key,t in conditional}=={'sales','control','report','pricing'}
    assert all(t['owner_id']=='u-pm' for key,t in conditional)
    n=p['nodes'][0];quote=next(t for t in n['tasks'] if t.get('sop_task_key')=='quote_provide')
    assert any('下包報價收件' in r for r in execution_reasons(ws,p,n,quote))
    next(t for key,t in conditional if key=='sales')['status']='completed'
    assert not execution_reasons(ws,p,n,quote)


def test_supervisor_change_stales_pending_proposal(company):
    ws,p=company
    act(company,'sop_applicability_propose',{'applies':False,'groups':[],'reason':'不下包'})
    prop=p['sop_applicability_proposal'];p['supervisor_id']='u-control'
    with pytest.raises(HTTPException,match='已變更'):
        act(company,'sop_applicability_confirm',{'proposal_id':prop['id'],'result':'approved'},user='u-manager')


def test_event_after_completion_preserves_node_and_creates_owned_followup(company):
    ws,p=company;n=next(n for n in p['nodes'] if n['key']=='field')
    n.update(status='completed',completed_at='2026-09-29',review_cycles=[{'status':'approved','votes':['keep']}])
    before=deepcopy(n)
    payload={'event_type':'field_stage_completed','scope_key':'batch1','date':'2026-09-30','evidence_url':'https://example.com/proof'}
    act(company,'sop_event_record',payload)
    assert n==before and len(p['sop_followups'])==1
    act(company,'sop_event_record',payload)
    assert n==before and len(p['sop_followups'])==1
    task=p['sop_followups'][0]
    act(company,'sop_followup_complete',{'id':task['id'],'output':'已通知業主'})
    assert task['status']=='completed' and n==before


def test_daily_reports_remain_reference_not_all_node_mandatory_output():
    release=template()
    assert all(not any(r['key'] in ('daily','photos') for r in n['requirements']) for n in release['nodes'])
