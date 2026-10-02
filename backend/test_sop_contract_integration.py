from copy import deepcopy
from .seed import seed,USERS
from .policy import upgrade,template
from .sources import import_sources
from .operations import apply_operation,missing
from .sop_contracts import VERSION

def record(ident,code):
    return {'kind':'confirmation','base_token':'v4','table_id':'confirmation','record_id':ident,
      'fields':{'工程確認單編號':code,'工程名稱':code,'狀態':'執行中'}}

def empty_company():
    ws=seed(True);ws['users']=deepcopy(USERS);ws['environment']='production'
    return upgrade(ws)

def old_template():
    value=template();value.update(id='company-custom-v8',version=8,name='公司既有自訂 SOP')
    for n in value['nodes']:
        n['task_definitions']=[d for d in n['task_definitions']if not d['key'].startswith('approved:')]
        for t in n['task_definitions']:
            for k in ('source_contract_refs','contract_version'):t.pop(k,None)
        n['tasks']=[d['title']for d in n['task_definitions']]
    return value

def test_existing_workspace_gets_one_draft_without_replacing_any_published_history():
    ws=upgrade(seed());ws['environment']='production';ws['sop_templates']=[old_template()]
    original=deepcopy(ws['sop_templates'][0]);projects=deepcopy(ws['projects']);count=len(ws['events'])
    upgrade(ws)
    assert ws['sop_templates'][0]==original and ws['projects']==projects
    candidate=ws['sop_templates'][-1]
    assert candidate['id']==VERSION and candidate['status']=='draft'and candidate['version']==9
    assert len(ws['events'])==count+1 and ws['events'][0]['action']=='sop_candidate_available'
    upgrade(ws)
    assert len(ws['sop_templates'])==2 and len(ws['events'])==count+1

def test_real_v4_import_path_keeps_contract_metadata_without_bypassing_cutover():
    ws=empty_company();import_sources(ws,[record('rec-1','C001')])
    p=ws['projects'][0]
    assert p['execution_system']=='pending'and p['sop_version']==VERSION
    tasks=[t for n in p['nodes']for t in n['tasks']if not t.get('source_identity')]
    assert tasks and all(t.get('sop_task_key')and t.get('sop_contract_version')==VERSION for t in tasks)
    assert any(t['source_contract_refs']for t in tasks)
    recurring=[t for t in tasks if t.get('recurring_kind')]
    assert len(recurring)==2 and all(not t['required']for t in recurring)
    assert not any(n['sop_applicability_pending']for n in p['nodes'])

def test_existing_company_uses_old_published_until_explicit_publish_then_only_new_cases_change():
    ws=empty_company();ws['sop_templates']=[old_template()];upgrade(ws)
    import_sources(ws,[record('old-case','C001')])
    old=ws['projects'][0];old['execution_system']='meegle'
    old_task=old['nodes'][0]['tasks'][0]
    old_task.update(status='completed',output='preserved-proof',owner_id='u-control',owner_inherited=False)
    before=deepcopy(old['nodes']);old_version=old['sop_version']
    candidate=ws['sop_templates'][-1]
    assert old_version=='company-custom-v8'and candidate['status']=='draft'
    manager=next(u for u in ws['users']if u['id']=='u-manager')
    apply_operation(ws,manager,{'action':'sop_publish','payload':{'id':candidate['id']}},False)
    import_sources(ws,[record('old-case','C001'),record('new-case','C002')])
    assert old['sop_version']==old_version and old['nodes']==before and old['execution_system']=='meegle'
    new=next(p for p in ws['projects']if p['code']=='C002')
    assert new['sop_version']==VERSION and new['execution_system']=='pending'
    assert any(t.get('sop_task_key')=='approved:sales:subcontract_scope_review'for n in new['nodes']for t in n['tasks'])

def test_prematurely_published_conditional_definition_blocks_completion_and_creates_no_fake_work():
    ws=empty_company();sop=ws['sop_templates'][0]
    sales=sop['nodes'][0];definition=deepcopy(sales['deferred_task_definitions'][0])
    sales['task_definitions'].append(definition);sales['tasks'].append(definition['title'])
    import_sources(ws,[record('conditional-case','C003')])
    p=ws['projects'][0];n=p['nodes'][0]
    assert n['sop_applicability_pending']
    assert not any(t.get('sop_task_key')==definition['key']for t in n['tasks'])
    assert any('SOP 適用條件' in reason for reason in missing(p,n,ws))
