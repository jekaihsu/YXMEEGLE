from copy import deepcopy
import pytest
from fastapi import HTTPException
from .seed import seed
from .policy import upgrade,template
from .sources import project_nodes,new_task
from .sop_contracts import catalog,VERSION,source_contracts,approved_definitions,merge_project_tasks,decorate_task,execution_reasons,applicability
from .workflow_rules import assign_node,activate_scheduled

@pytest.fixture
def company():
    ws=upgrade(seed());ws['environment']='demo'
    p=ws['projects'][0];p['nodes']=project_nodes(p['id'])
    p.update(execution_system='workbench',execution_status='pending',source_status='執行中',case_type='confirmed',supervisor_id='u-manager')
    for n in p['nodes']:n['owner_id']='u-pm'
    return ws,p,next(u for u in ws['users']if u['id']=='u-manager')

def decision(applies):return {'applies':applies,'contract_version':VERSION,'decided_by':'u-manager','reason':'已核定下包範圍'}

def conditional_template():
    value=template()
    for node in value['nodes']:
        node['task_definitions'].extend(node['deferred_task_definitions'])
    return value

def test_all_52_source_tasks_have_distinct_versioned_contracts_and_delivery_rules():
    data=catalog();full=next(t for t in data['templates']if t['id']==334662)
    tasks=[x for n in full['nodes']for x in n['tasks']]
    assert len(tasks)==52 and len({t['contract_id']for t in tasks})==52
    assert all(t['contract_id'].endswith(':v137')for t in tasks)
    assert sum(t['node_pass_required']['value']is True for t in tasks)==29
    assert any(t['deliverable']for t in tasks)
    tasks[0]['name']='bad'
    assert catalog()['templates'][0]['nodes'][1]['tasks'][0]['name']!='bad'

def test_disabled_source_nodes_are_explicit_and_never_defaults():
    disabled=source_contracts(['state_52','state_58'])
    assert len(disabled)==2 and all(n['disabled']and n['disabled_reason']for n in disabled)
    assert not any(r['node_key']in ('state_52','state_58')for n in template()['nodes']for t in n['task_definitions']for r in t['source_contract_refs'])

def test_default_release_does_not_create_unresolvable_condition_dead_end(company):
    ws,p,actor=company
    assert all(not n['sop_applicability_pending']for n in p['nodes'])
    assert not merge_project_tasks(ws,p,template(),actor)['pending']
    assert sum(len(n['deferred_task_definitions'])for n in template()['nodes'])==6
    recurring=[t for n in p['nodes']for t in n['tasks']if t.get('recurring_kind')]
    assert len(recurring)==2 and all(not t['required']and t['completion_scope']=='single_occurrence_record'for t in recurring)

def test_unknown_condition_is_not_materialized_as_mandatory(company):
    ws,p,actor=company
    result=merge_project_tasks(ws,p,conditional_template(),actor)
    assert result['pending']
    sales=next(n for n in p['nodes']if n['key']=='sales')
    assert not any(t.get('sop_task_key')=='approved:sales:subcontract_quote_collection'for t in sales['tasks'])
    assert sales['sop_applicability_pending']

@pytest.mark.parametrize('bad',[True,{'applies':True},dict(applies='true',contract_version=VERSION,decided_by='u-manager',reason='x')])
def test_unattributed_or_wrong_type_decision_does_not_activate(bad):
    assert applicability({'sop_applicability':{'subcontract':bad}},{'applicability':'subcontract'})is None

def test_approved_no_subcontract_skips_without_fake_completion(company):
    ws,p,actor=company;p['sop_applicability']={'subcontract':decision(False)}
    result=merge_project_tasks(ws,p,conditional_template(),actor)
    assert not result['pending']
    assert not any(t.get('sop_applicability','always')!='always'for n in p['nodes']for t in n['tasks'])

def test_true_condition_adds_only_selected_group_inherits_then_manual_override_survives(company):
    ws,p,actor=company
    p['sop_applicability']={'subcontract':decision(True),**{'subcontract_'+k:decision(k=='control')for k in ('field','control','mapping','report')}}
    first=merge_project_tasks(ws,p,conditional_template(),actor)
    n=next(n for n in p['nodes']if n['key']=='control')
    t=next(t for t in n['tasks']if t.get('sop_task_key')=='approved:control:subcontract_dispatch')
    assert t['owner_id']=='u-pm' and t['owner_inherited']
    t.update(owner_id='u-control',owner_inherited=False,assignment_history=[{'actor_id':'u-manager','after':{'owner_id':'u-control'}}])
    before=deepcopy(t)
    assign_node(ws,p,n,'u-field',actor)
    assert t==before
    assert not merge_project_tasks(ws,p,conditional_template(),actor)['added']
    assert next(x for x in p['nodes']if x['id']==n['id'])['tasks'][-1]==before
    assert not first['pending']

def test_completed_node_and_individual_result_preserved_through_new_version(company):
    ws,p,actor=company
    p['nodes'][0].update(status='completed',completed_at='yesterday',review_cycles=[{'status':'approved'}])
    completed=deepcopy(p['nodes'][0])
    n=p['nodes'][1];t=n['tasks'][0]
    t.update(status='completed',output='signed-result',completed_at='yesterday',owner_id='u-control',owner_inherited=False,revision=7,confirmations=[{'actor_id':'u-control'}])
    saved=deepcopy(t)
    version=template();version['id']='next-contract-version'
    version['nodes'][1]['task_definitions'][0]['title']='revised-title'
    merge_project_tasks(ws,p,version,actor)
    assert p['nodes'][0]==completed
    assert p['nodes'][1]['tasks'][0]==saved

@pytest.mark.parametrize('system',['pending','meegle'])
def test_formal_legacy_and_unclassified_upgrade_is_noop_error(company,system):
    ws,p,actor=company;ws['environment']='production';p['execution_system']=system
    before=deepcopy(p)
    with pytest.raises(HTTPException)as err:merge_project_tasks(ws,p,template(),actor)
    assert err.value.status_code==409 and p==before

def test_late_duplicate_validation_does_not_partially_change_earlier_nodes(company):
    ws,p,actor=company
    last=p['nodes'][-1];last['tasks'].append(deepcopy(last['tasks'][0]))
    before=deepcopy(p)
    with pytest.raises(HTTPException):merge_project_tasks(ws,p,template(),actor)
    assert p==before

def test_disabled_custom_definition_never_creates_scheduler_work(company):
    ws,p,actor=company;v=template()
    v['nodes'][1]['task_definitions'].append({'key':'disabled-assessment','title':'考評','source_node_ids':['state_52']})
    merge_project_tasks(ws,p,v,actor)
    assert not any(t.get('sop_task_key')=='disabled-assessment'for n in p['nodes']for t in n['tasks'])
    n=p['nodes'][1];t=new_task('disabled-old','歷史考評',None)
    t.update(owner_id='u-pm',start_date='2026-09-01',source_contract_refs=[{'template_id':334662,'node_key':'state_58','version':137}])
    n['tasks'].append(t)
    assert execution_reasons(p,n,t)
    assert t['id']not in activate_scheduled(ws,'2026-09-29T10:00:00+08:00')
    assert t['status']=='pending'

def test_removed_applicability_decision_blocks_previously_created_work(company):
    ws,p,actor=company
    definition=next(d for d in approved_definitions('sales') if d['applicability']=='subcontract')
    t=decorate_task(new_task('conditional','下包報價',None),definition,VERSION)
    assert execution_reasons(p,p['nodes'][0],t)
    p['sop_applicability']={'subcontract':decision(True)}
    assert not execution_reasons(p,p['nodes'][0],t)
    p['sop_applicability']['subcontract']=decision(False)
    assert execution_reasons(p,p['nodes'][0],t)

@pytest.mark.parametrize('payload',[{'required':'false'},{'source_contract_refs':['state_52']},{'source_node_ids':'state_52'},{'applicability':{}}])
def test_invalid_custom_definition_returns_422_without_partial_upgrade(company,payload):
    ws,p,actor=company;v=template();before=deepcopy(p)
    v['nodes'][-1]['task_definitions'].append({'key':'invalid','title':'invalid',**payload})
    with pytest.raises(HTTPException)as err:merge_project_tasks(ws,p,v,actor)
    assert err.value.status_code==422 and p==before

def test_ordinary_member_cannot_call_contract_merge_directly(company):
    ws,p,actor=company;before=deepcopy(p)
    member=next(u for u in ws['users']if u['id']=='u-control')
    with pytest.raises(HTTPException)as err:merge_project_tasks(ws,p,template(),member)
    assert err.value.status_code==403 and p==before

@pytest.mark.parametrize('legacy',[False,True])
@pytest.mark.parametrize('completed',[False,True])
def test_new_conditional_rule_on_existing_task_never_bypasses_unknown_gate(company,legacy,completed):
    from .sop_contracts import completion_reasons
    ws,p,actor=company;n=p['nodes'][1];task=n['tasks'][0]
    task.update(owner_id='u-control',owner_inherited=False,output='prior-result')
    if legacy:task.pop('sop_task_key')
    if completed:task.update(status='completed',completed_at='earlier')
    before=deepcopy(task);v=template();v['nodes'][1]['task_definitions'][0]['applicability']='subcontract'
    merge_project_tasks(ws,p,v,actor)
    assert n['sop_applicability_pending']and completion_reasons(p,n)
    assert task['owner_id']==before['owner_id']and task['output']==before['output']and task['status']==before['status']
    if completed:assert task==before
    else:
        assert task['sop_applicability']=='subcontract'and task['sop_contract_history']
        assert execution_reasons(p,n,task)

def test_explicit_false_on_existing_conditional_task_keeps_result_without_fake_completion(company):
    ws,p,actor=company;n=p['nodes'][1];task=n['tasks'][0];task['output']='draft-result'
    v=template();v['nodes'][1]['task_definitions'][0]['applicability']='subcontract'
    merge_project_tasks(ws,p,v,actor)
    p['sop_applicability']={'subcontract':decision(False)}
    merge_project_tasks(ws,p,v,actor)
    assert not n['sop_applicability_pending']and not task['required']
    assert task['status']=='pending'and task['output']=='draft-result'and len(task['sop_contract_history'])==2


def test_explicit_apply_upgrades_pending_contract_and_quote_gate_preserving_history(company):
    from .operations import apply_operation
    ws,p,actor=company
    old='sop-contracts-20260929.1'
    p['sop_version']=old
    sales=next(n for n in p['nodes'] if n['key']=='sales')
    quote=next(t for t in sales['tasks'] if t['sop_task_key']=='quote_provide')
    quote.update(sop_contract_version=old,sop_definition_version=old,
                 owner_id='u-control',owner_inherited=False,output='draft quote')
    sales['requirements']=[{'key':'daily','label':'legacy daily requirement'}]
    completed=next(n for n in p['nodes'] if n['key']=='field')
    completed.update(status='completed',completed_at='yesterday',
                     requirements=[{'key':'daily','label':'historical rule'}],
                     review_cycles=[],review_mode='all',reviewers=[],supervisor_id='')
    historical=deepcopy(completed)
    # Merely reading/upgrading the workspace cannot rewrite an existing release.
    upgrade(ws)
    assert quote['sop_contract_version']==old
    assert sales['requirements'][0]['key']=='daily'
    assert not execution_reasons(p,sales,quote)
    candidate=next(t for t in ws['sop_templates'] if t['id']==VERSION)
    candidate['status']='published'
    apply_operation(ws,actor,{'action':'sop_request','project_id':p['id'],
                              'payload':{'id':VERSION,'reason':'approved migration'}},True)
    request=ws['sop_requests'][-1]
    apply_operation(ws,actor,{'action':'sop_apply','project_id':p['id'],
                              'payload':{'id':request['id']}},True)
    assert quote['sop_contract_version']==VERSION and quote['sop_definition_version']==VERSION
    assert execution_reasons(p,sales,quote)  # Unknown subcontract need blocks quote submission.
    assert quote['owner_id']=='u-control' and quote['output']=='draft quote'
    history=quote['sop_contract_history'][-1]
    assert history['before']['sop_contract_version']==old
    assert history['after']['sop_contract_version']==VERSION
    assert history['actor_id']==actor['id']
    assert not any(r['key']=='daily' for r in sales['requirements'])
    assert completed==historical
