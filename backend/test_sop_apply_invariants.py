"""Issue #8: end-to-end synthetic proof of the explicit SOP apply invariants."""
from copy import deepcopy
import pytest
from fastapi import HTTPException
from .operations import apply_operation,missing
from .policy import upgrade
from .sop_contracts import VERSION,execution_reasons,completion_reasons
from .test_sop_contracts import company,decision  # noqa: F401  (fixture)

OLD='sop-contracts-20260929.1'

def request_apply(ws,actor,p):
    candidate=next(t for t in ws['sop_templates']if t['id']==VERSION);candidate['status']='published'
    apply_operation(ws,actor,{'action':'sop_request','project_id':p['id'],'payload':{'id':VERSION,'reason':'migrate'}},True)
    return ws['sop_requests'][-1]

def apply(ws,actor,p,req):
    return apply_operation(ws,actor,{'action':'sop_apply','project_id':p['id'],'payload':{'id':req['id']}},True)

@pytest.fixture
def staged(company):
    ws,p,actor=company;p['sop_version']=OLD;upgrade(ws)
    return ws,p,actor,request_apply(ws,actor,p)

@pytest.mark.parametrize('system,visibility',[('pending',None),('meegle',None),('workbench','excluded_history'),(None,None)])
def test_apply_refused_without_workbench_ownership_and_nothing_changes(staged,system,visibility):
    ws,p,actor,req=staged;ws['environment']='production'  # fixture is demo, which skips ownership
    p['execution_system']=system
    if visibility:p['case_visibility']=visibility
    before=(deepcopy(p),deepcopy(req),len(ws['events']))
    with pytest.raises(HTTPException)as error:apply(ws,actor,p,req)
    assert error.value.status_code==409
    assert (p,req,len(ws['events']))==before and req['status']=='pending' and p['sop_version']==OLD

def test_apply_refused_for_unrelated_actor_and_stale_request(staged):
    ws,p,actor,req=staged
    outsider=next(u for u in ws['users']if u['id']=='u-control')
    with pytest.raises(HTTPException)as error:apply(ws,outsider,p,req)
    assert error.value.status_code==403 and req['status']=='pending'
    p['sop_version']='something-else'
    with pytest.raises(HTTPException)as error:apply(ws,actor,p,req)
    assert error.value.status_code==409 and req['status']=='pending'

def test_apply_saves_attributed_audit_even_when_no_task_changes(staged):
    ws,p,actor,req=staged
    apply(ws,actor,p,req)
    first=len([e for e in ws['events']if e.get('action')=='sop_apply'])
    assert req['status']=='approved' and req['approved_by']==actor['id'] and req['approved_at']
    assert p['sop_version']==VERSION
    audit=[e for e in ws['events']if e.get('action')=='sop_apply'and e['project_id']==p['id']]
    assert first==1 and audit[0]['actor_id']==actor['id']
    with pytest.raises(HTTPException):apply(ws,actor,p,req)  # cannot replay
    assert len([e for e in ws['events']if e.get('action')=='sop_apply'])==1

def test_apply_keeps_history_results_and_people(staged):
    ws,p,actor,req=staged
    sales=next(n for n in p['nodes']if n['key']=='sales');done=sales['tasks'][0]
    done.update(status='completed',completed_at='yesterday',output='final',owner_id='u-control',
                owner_inherited=False,sop_contract_version=OLD,assignment_history=[{'by':'u-pm'}],revision=3)
    open_task=next(t for t in sales['tasks']if t['sop_task_key']=='quote_provide')
    open_task.update(output='draft',owner_id='u-pm',owner_inherited=False,sop_contract_version=OLD)
    sales.update(owner_id='u-manager',collaborator_ids=['u-pm'],confirmations=[{'by':'u-manager'}])
    finished=next(n for n in p['nodes']if n['key']=='field')
    finished.update(status='completed',completed_at='earlier',owner_id='u-control',review_cycles=[{'status':'approved','id':'c'}])
    snapshot=deepcopy((done,finished,sales['owner_id'],sales['collaborator_ids'],sales['confirmations'],
                       {k:p[k]for k in('pm_id','admin_id','supervisor_id')}))
    apply(ws,actor,p,req)
    assert deepcopy((done,finished,sales['owner_id'],sales['collaborator_ids'],sales['confirmations'],
                     {k:p[k]for k in('pm_id','admin_id','supervisor_id')}))==snapshot
    assert open_task['output']=='draft' and open_task['owner_id']=='u-pm'
    assert open_task['sop_contract_version']==VERSION

def test_apply_does_not_decide_subcontract_need_for_humans(staged):
    ws,p,actor,req=staged
    p.pop('sop_applicability',None)
    quote=next(t for t in next(n for n in p['nodes']if n['key']=='sales')['tasks']if t['sop_task_key']=='quote_provide')
    apply(ws,actor,p,req)
    assert 'sop_applicability' not in p or not p['sop_applicability']
    assert execution_reasons(p,next(n for n in p['nodes']if n['key']=='sales'),quote)

def test_subcontract_prerequisite_only_after_valid_explicit_decision(staged):
    ws,p,actor,req=staged;sales=next(n for n in p['nodes']if n['key']=='sales')
    quote=next(t for t in sales['tasks']if t['sop_task_key']=='quote_provide')
    apply(ws,actor,p,req)
    assert execution_reasons(p,sales,quote)  # unknown
    p['sop_applicability']={'subcontract':dict(decision(True),contract_version='old')}
    assert execution_reasons(p,sales,quote)  # wrong-version decision is not authority
    p['sop_applicability']={'subcontract':decision(True)}
    assert execution_reasons(p,sales,quote)==['提出報價前需完成下包報價收件與範圍核對']
    p['sop_applicability']={'subcontract':decision(False)}
    assert not execution_reasons(p,sales,quote)

def test_daily_report_reference_survives_apply_and_stale_reference_still_blocks(staged):
    from .v4_sources import daily_source_version
    ws,p,actor,req=staged;node=next(n for n in p['nodes']if n['key']=='pm')
    daily={'id':'d1','source_fields':{'x':1}};p['daily_reports']=[daily]
    p['evidence']=[{'id':'e1','node_id':node['id'],'key':'daily','status':'accepted','daily_id':'d1',
                    'daily_source_version':daily_source_version(daily)}]
    apply(ws,actor,p,req)
    stored=p['evidence'][0]
    assert stored['status']=='accepted' and stored['daily_id']=='d1'
    node['requirements']=[{'key':'daily','label':'daily proof'}]  # apply re-derives rules from the SOP; reference stays
    assert not any('日報'in r for r in missing(p,node,ws))
    daily['source_fields']={'x':2}
    assert any('日報'in r for r in missing(p,node,ws))
