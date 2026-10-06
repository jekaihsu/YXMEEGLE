"""Company workflow acceptance: explicit identity, atomic delivery, repeatable activation."""
from copy import deepcopy
import pytest
from fastapi import HTTPException
from .seed import seed
from .policy import upgrade
from .workflow import apply_action
from .workflow_rules import activate_scheduled, activation_reasons, confirmation_hash, inherit_new_task
from .operations import apply_operation, review_hash, missing, submit_review, vote, refresh_project_state
from .jobs import schedule

@pytest.fixture
def setup():
    ws=upgrade(seed()); ws['environment']='demo'
    p=ws['projects'][0]; p.update(source_status='執行中',supervisor_id='u-manager',admin_id='u-field')
    n=next(x for x in p['nodes'] if x['key']=='control'); n.update(status='pending',owner_id='u-control',supervisor_id='u-manager',started_at=None)
    for t in n['tasks']: t.update(status='pending',owner_id='u-control',owner_inherited=True,start_date='2026-09-28',started_at=None,output='',input_task_ids=[])
    return ws,p,n,next(u for u in ws['users'] if u['id']=='u-control')

def body(p,n,action,payload=None,t=None):
    return dict(action=action,project_id=p['id'],node_id=n['id'],task_id=t['id'] if t else None,payload=payload or {},request_id='request-1')

def items(p,n):
    return [dict(project_id=p['id'],node_id=n['id'],task_id=t['id'],revision=t['revision'],confirmation_hash=confirmation_hash(p,n,t),output='本項成果 '+t['id']) for t in n['tasks']]

def test_scheduled_activation_is_once_and_never_claims_actual_start(setup):
    ws,p,n,user=setup
    assert not any(t['id'] in activate_scheduled(ws,'2026-09-27T23:59:59+08:00') for t in n['tasks'])
    started=activate_scheduled(ws,'2026-09-28T00:00:00+08:00')
    assert all(t['id'] in started and t['started_at'] is None and t['activation_source']=='schedule' for t in n['tasks'])
    assert n['started_at'] is None
    count=len(ws['events']); assert activate_scheduled(ws,'2026-09-28T01:00:00+08:00')==[] and len(ws['events'])==count
    apply_action(ws,user,body(p,n,'task_start',t=n['tasks'][0]))
    assert n['tasks'][0]['started_at'] and n['tasks'][0]['activated_at']=='2026-09-28T00:00:00+08:00'

@pytest.mark.parametrize('reason',['inactive','missing_owner','future','missing_date','paused','superseded','source_change','case_stop','node_skip','intake','completed_node'])
def test_auto_activation_fails_closed_for_every_gate(setup,reason):
    ws,p,n,user=setup; t=n['tasks'][0]
    if reason=='inactive': user['active']=False
    if reason=='missing_owner': t['owner_id']=''
    if reason=='future': t['start_date']='2026-09-29'
    if reason=='missing_date': t['start_date']=None
    if reason in ('paused','superseded'): t['status']=reason
    if reason=='source_change': t['source_change_pending']=True
    if reason=='case_stop': p['source_lifecycle']={'canonical':'中止','state':'mapped'}
    if reason=='node_skip': n['status']='approved_skipped'
    if reason=='intake': p['case_type']='intake'
    if reason=='completed_node': n['status']='completed'
    assert activation_reasons(ws,p,n,t,'2026-09-28T10:00:00+08:00')
    assert t['id'] not in activate_scheduled(ws,'2026-09-28T10:00:00+08:00')
    assert t.get('activated_at') is None and t['started_at'] is None

def test_dependency_delivery_and_permit_must_exist_before_auto_activation(setup):
    ws,p,n,user=setup; first,second=n['tasks'][:2]; second['input_task_ids']=[first['id']]
    assert second['id'] not in activate_scheduled(ws,'2026-09-28T10:00:00+08:00')
    first.update(status='completed',output='已交付平差成果')
    assert second['id'] in activate_scheduled(ws,'2026-09-28T10:00:01+08:00')
    field=next(x for x in p['nodes'] if x['key']=='field'); ft=field['tasks'][0]
    field['status']='pending'; ft.update(status='pending',start_date='2026-09-28')
    assert ft['id'] not in activate_scheduled(ws,'2026-09-28T10:00:02+08:00')
    p['evidence'].append(dict(id='permit',node_id=field['id'],key='permits',status='accepted'))
    assert ft['id'] in activate_scheduled(ws,'2026-09-28T10:00:03+08:00')

def test_personal_batch_revalidates_and_records_each_task_without_fabricated_start(setup):
    ws,p,n,user=setup; activate_scheduled(ws,'2026-09-28T10:00:00+08:00')
    apply_action(ws,user,body(p,n,'task_batch_complete',{'items':items(p,n)}))
    assert all(t['status']=='completed' and t['started_at'] is None and len(t['confirmations'])==1 for t in n['tasks'])
    events=[e for e in ws['events'] if e.get('trigger')=='batch_confirmation']
    assert len(events)==len(n['tasks']) and all(e['before']['status']=='in_progress' and e['after']['status']=='completed' for e in events)
    assert n['status']!='completed' and not n['review_cycles']

@pytest.mark.parametrize('bad',['other_owner','blank_output','old_revision','old_hash','duplicate','not_started','dependency'])
def test_personal_batch_all_or_nothing_before_any_mutation(setup,bad):
    ws,p,n,user=setup; activate_scheduled(ws,'2026-09-28T10:00:00+08:00'); rows=items(p,n); t=n['tasks'][-1]
    if bad=='other_owner': t['owner_id']='u-field'
    if bad=='blank_output': rows[-1]['output']='  '
    if bad=='old_revision': rows[-1]['revision']=-1
    if bad=='old_hash': rows[-1]['confirmation_hash']='stale'
    if bad=='duplicate': rows.append(rows[0])
    if bad=='not_started': t['status']='pending'; rows=items(p,n)
    if bad=='dependency': t['input_task_ids']=[n['tasks'][0]['id']]; rows=items(p,n)
    before=deepcopy(ws)
    with pytest.raises(HTTPException): apply_action(ws,user,body(p,n,'task_batch_complete',{'items':rows}))
    assert ws==before

def test_new_task_and_both_node_assignment_routes_use_same_inheritance(setup):
    ws,p,n,user=setup; pm=next(u for u in ws['users'] if u['id']=='u-pm')
    overridden=n['tasks'][1]; overridden['owner_inherited']=False
    done=n['tasks'][2]; done['status']='completed'
    apply_operation(ws,pm,body(p,n,'project_roles',{'owner_id':'u-agent'}),True)
    assert n['tasks'][0]['owner_id']=='u-agent' and overridden['owner_id']==done['owner_id']=='u-control'
    apply_action(ws,pm,body(p,n,'participants_update',{'nodes':[{'node_id':n['id'],'owner_id':'u-map','collaborator_ids':[]}]}))
    assert n['tasks'][0]['owner_id']=='u-map' and overridden['owner_id']==done['owner_id']=='u-control'
    apply_action(ws,pm,body(p,n,'task_add',{'title':'新增本人SOP'}))
    added=n['tasks'][-1]; assert added['owner_id']=='u-map' and added['owner_inherited']
    assert n['tasks'][0]['assignment_history'][-1]['before']['owner_id']=='u-agent'
    from .sources import new_task
    sourced=new_task('native','來源工項',None); n['tasks'].append(sourced); inherit_new_task(ws,p,n,sourced)
    assert sourced['owner_id']=='u-map' and sourced['assignment_history'][-1]['after']['owner_inherited']

def prepared(setup):
    ws,p,n,user=setup
    for t in n['tasks']: t.update(status='completed',output='已交付')
    for r in n['requirements']: p['evidence'].append(dict(id=r['key'],node_id=n['id'],key=r['key'],status='accepted'))
    return ws,p,n,user

def test_technical_reviewer_seats_cannot_be_the_same_person(setup):
    ws,p,n,user=prepared(setup); n['supervisor_id']=n['owner_id']
    with pytest.raises(HTTPException,match='不同人'): submit_review(ws,user,p,n)

def test_delegate_cannot_supply_both_review_votes(setup):
    ws,p,n,user=prepared(setup); cycle=submit_review(ws,user,p,n)
    ws['delegations']=[dict(id='d1',principal_id='u-manager',delegate_id='u-control',project_id=p['id'],seat='supervisor',scope='review',start_date='2020-01-01',end_date='2099-12-31',status='active',source='supervisor',qualified=True,qualification_evidence='主管資格證明')]
    vote(ws,user,p,n,dict(cycle_id=cycle['id'],seat='owner',result='approved'))
    with pytest.raises(HTTPException,match='兼投兩票'): vote(ws,user,p,n,dict(cycle_id=cycle['id'],seat='supervisor',result='approved'))
    assert n['status']!='completed'

def test_review_hash_ignores_unrelated_revision_or_schedule_but_tracks_actual_delivery(setup):
    ws,p,n,user=prepared(setup); original=review_hash(p,n)
    p['revision']+=1; n['tasks'][0]['due_date']='2026-12-31'
    assert review_hash(p,n)==original
    n['tasks'][0]['output']='修改成果'
    assert review_hash(p,n)!=original

def test_settlement_cannot_skip_earlier_nodes_and_reopens_on_rework(setup):
    ws,p,n,user=setup
    settlement=next(x for x in p['nodes'] if x['key']=='settlement')
    assert any('報價、派工' in x for x in missing(p,settlement,ws))
    for node in p['nodes']: node['status']='completed'
    p['payment_reconciliation']={'confirmed':True}; p['execution_status']='completed'
    next(x for x in p['nodes'] if x['key']=='pricing')['status']='rework'
    refresh_project_state(p,ws)
    assert settlement['status']=='rework' and p['execution_status']!='completed'

def test_intake_without_field_node_does_not_stop_company_scheduler(setup):
    ws,p,n,user=setup; p['case_type']='intake'; p['nodes']=p['nodes'][:1]
    schedule(ws,'2026-09-28T08:00:00+08:00')
    assert not any(r['project_id']==p['id'] for r in ws['recurring'])

def test_personnel_partial_update_never_restores_disabled_or_clears_department(setup):
    ws,p,n,user=setup; manager=next(u for u in ws['users'] if u['role']=='manager')
    user.update(active=False,default_workspace='production'); department=user['department']
    apply_operation(ws,manager,{'action':'admin_person','payload':{'id':user['id'],'name':'新姓名'}},True)
    assert user['active'] is False and user['department']==department and user['default_workspace']=='production'

def test_personnel_delegate_cannot_demote_manager_or_create_formal_unverified_id(setup):
    ws,p,n,user=setup; manager=next(u for u in ws['users'] if u['role']=='manager'); user['capabilities']=['manage_people']
    with pytest.raises(HTTPException,match='最高管理員'):
        apply_operation(ws,user,{'action':'admin_person','payload':{'id':manager['id'],'role':'member','active':False}},True)
    with pytest.raises(HTTPException,match='名冊'):
        apply_operation(ws,manager,{'action':'admin_person','payload':{'id':'invented','name':'同名但非真帳號'}},False)
    assert not any(u['id']=='invented' for u in ws['users'])

@pytest.mark.parametrize('action',['finance_propose','finance_approve','finance_allocate','finance_allocation_approve','finance_attest','payment_create','payment_approve','payment_record','payment_reconcile','payment_revise'])
def test_formal_ledger_mutations_require_native_financial_process(setup,action):
    ws,p,n,user=setup; manager=next(u for u in ws['users'] if u['role']=='manager')
    before=deepcopy(ws)
    with pytest.raises(HTTPException) as error: apply_operation(ws,manager,body(p,n,action),False)
    assert error.value.status_code==403 and ws==before

def test_formal_automation_requires_verified_roster_identity(setup):
    ws,p,n,user=setup; ws['environment']='production'; ws['people_directory_status']={'app_id':'app1'}
    p['execution_system']='workbench'
    assert n['tasks'][0]['id'] not in activate_scheduled(ws,'2026-09-28T10:00:00+08:00')
    user.update(identity_app_id='app1',directory_status='employed',directory_source={'app_id':'app1','record_id':'recPerson'})
    assert n['tasks'][0]['id'] in activate_scheduled(ws,'2026-09-28T10:00:01+08:00')

def test_disabled_assessment_preserves_history_but_never_schedules_notifications(setup):
    ws,p,n,user=setup
    ws['recurring']=[dict(id='old-assessment',kind='monthly',project_id=p['id'],owner_id=user['id'],status='active',due_date='2026-09-01',history=[{'evidence':'舊考評歷史'}])]
    schedule(ws,'2026-09-29T10:00:00+08:00')
    record=next(r for r in ws['recurring'] if r['id']=='old-assessment')
    assert record['status']=='disabled' and record['history']==[{'evidence':'舊考評歷史'}]
    assert not any('月考評' in job['payload'].get('text','') for job in ws['jobs'])


def test_recurring_midnight_attendance_escalates_only_after_actual_shift_end(setup):
    ws,p,n,user=setup;ws['settings']['digest_time']='00:00'
    ws['work_schedules']=[{'id':'night-shift','user_id':user['id'],'day':'2026-09-28','active':True,'basis':'attendance_schedule',
                           'status':'ready','normal_off_at':'2026-09-29T02:00:00+08:00','off_day_offset':1,'end_time':'02:00','version':1}]
    routine={'id':'night-task','project_id':p['id'],'kind':'correction','title':'成果補正','owner_id':user['id'],
             'supervisor_id':'u-manager','status':'active','due_date':'2026-09-28','history':[]}
    ws['recurring']=[routine]
    schedule(ws,'2026-09-29T01:59:00+08:00')
    assert routine['overdue'] is False and routine['deadline']['at']=='2026-09-29T02:00:00+08:00'
    assert not any('成果補正檢查' in j['payload'].get('text','') and 'u-manager' in j['payload'].get('recipients',[]) for j in ws['jobs'])
    ws['jobs']=[];schedule(ws,'2026-09-29T02:01:00+08:00')
    assert routine['overdue'] is True
    assert any('成果補正檢查' in j['payload'].get('text','') and 'u-manager' in j['payload'].get('recipients',[]) for j in ws['jobs'])

def test_freeze_change_is_attempt_only_idempotent_and_preserves_work(setup):
    from .workflow import freeze_change
    ws,p,n,user=setup; target=n['tasks'][0]; target.update(status='in_progress',output='尚在整理中的成果')
    request={'id':'change1','type':'change','project_id':p['id'],'task_ids':[target['id']],'reason':'需求異動','frozen':False}
    ws['approvals'].append(request); original=deepcopy(target)
    assert not request['frozen'] and target['status']=='in_progress'
    freeze_change(ws,p,request,user); events=len(ws['events']); freeze_change(ws,p,request,user)
    assert target['status']=='paused' and target['output']==original['output'] and target['started_at']==original['started_at']
    assert request['previous_statuses'][target['id']]=='in_progress' and len(ws['events'])==events

def test_sop_upgrade_uses_stable_definition_keys_and_inherits_new_task_owner(setup):
    ws,p,n,user=setup; manager=next(u for u in ws['users'] if u['role']=='manager')
    source=ws['sop_templates'][0]; definitions=deepcopy(source['nodes'])
    target=next(d for d in definitions if d['key']=='control')
    # Distinct SOP definitions may legitimately share a display title.
    target['tasks']+=['獨立核對','獨立核對']
    target['task_definitions'] += [{'key':'control_check_a','title':'獨立核對'},{'key':'control_check_b','title':'獨立核對'}]
    apply_operation(ws,manager,{'action':'sop_draft','payload':{'source_id':source['id'],'nodes':definitions}},True)
    version=ws['sop_templates'][-1]
    apply_operation(ws,manager,{'action':'sop_publish','payload':{'id':version['id']}},True)
    for _ in range(2):
        apply_operation(ws,manager,body(p,n,'sop_request',{'id':version['id'],'reason':'已核定SOP版本'}),True)
        request=ws['sop_requests'][-1]
        apply_operation(ws,manager,body(p,n,'sop_apply',{'id':request['id']}),True)
    tasks=[t for t in n['tasks'] if t.get('sop_task_key') in ('control_check_a','control_check_b')]
    assert len(tasks)==2 and all(t['owner_id']==n['owner_id'] and t['owner_inherited'] for t in tasks)

def test_declared_sop_coverage_never_claims_unread_meegle_library_is_complete():
    from .policy import template
    value=template()
    assert value['coverage_status']=='partial_inventory'
    for n in value['nodes']:
        assert [t['title'] for t in n['task_definitions']]==n['tasks']
        assert len({t['key'] for t in n['task_definitions']})==len(n['tasks'])


def test_title_only_sop_editor_preserves_unique_keys_and_creates_new_identity(setup):
    ws,p,n,user=setup; manager=next(u for u in ws['users'] if u['role']=='manager')
    source=ws['sop_templates'][0]; nodes=deepcopy(source['nodes'])
    original=deepcopy(nodes[0]['task_definitions'])
    for node in nodes: node.pop('task_definitions')
    nodes[0]['tasks'].append('新補件步驟')
    apply_operation(ws,manager,{'action':'sop_draft','payload':{'source_id':source['id'],'nodes':nodes}},True)
    defs=ws['sop_templates'][-1]['nodes'][0]['task_definitions']
    assert defs[:-1]==original and defs[-1]['title']=='新補件步驟'
    assert defs[-1]['key'] not in {d['key'] for d in original}


def test_source_closed_does_not_block_authorized_manual_reconciliation_or_auto_restart(setup):
    ws,p,n,user=setup;p['source_lifecycle']={'canonical':'已結案','state':'mapped'};t=n['tasks'][0]
    assert any('來源標示結案' in reason for reason in activation_reasons(ws,p,n,t,'2026-09-28T09:00:00+08:00'))
    assert t['id'] not in activate_scheduled(ws,'2026-09-28T09:00:00+08:00')
    apply_action(ws,user,body(p,n,'task_start',t=t),True)
    assert t['status']=='in_progress' and t['started_at']
    assert p['execution_status']!='completed'


def test_link_attachment_versions_keep_group_and_immutable_history(setup):
    ws,p,n,user=setup;manager=next(u for u in ws['users'] if u['role']=='manager')
    p['pm_id']=manager['id']
    payload={'direction':'output','category_id':'other','name':'成果','url':'https://example.com/v1','version':'999'}
    apply_action(ws,manager,body(p,n,'file_link',payload),True)
    first=deepcopy(p['files'][-1]);assert first['version']=='1'
    apply_action(ws,manager,body(p,n,'file_link',{**payload,'file_key':first['file_key'],'url':'https://example.com/v2','version':'999'}),True)
    second=p['files'][-1]
    assert p['files'][-2]==first and second['version']=='2' and second['file_key']==first['file_key'] and second['id']!=first['id']
    for invalid in ({'file_key':'unknown'},{'file_key':first['file_key'],'direction':'input'}):
        with pytest.raises(HTTPException):apply_action(ws,manager,body(p,n,'file_link',{**payload,**invalid}),True)
    other=next(node for node in p['nodes'] if node['id']!=n['id'])
    with pytest.raises(HTTPException):apply_action(ws,manager,body(p,other,'file_link',{**payload,'file_key':first['file_key']}),True)


def test_formal_financial_local_votes_cannot_replace_native_receipt(setup):
    ws,p,_,user=setup; ws['environment']='production'
    n=next(n for n in p['nodes'] if n['key']=='pricing'); n['requirements']=[]
    for task in n['tasks']: task.update(status='completed',output='交付')
    assert any('Lark 原生財務' in reason for reason in missing(p,n,ws))
    manager=next(u for u in ws['users'] if u['role']=='manager')
    with pytest.raises(HTTPException,match='Lark 原生共同核准'): submit_review(ws,manager,p,n)
    n['status']='completed'; refresh_project_state(p,ws)
    assert n['status']=='rework'


def test_financial_receipt_is_exact_node_and_completed_refresh_uses_historical_validity(setup,monkeypatch):
    from .operations import financial_confirmation
    ws,p,n,user=setup; ws['environment']='production'
    n=next(n for n in p['nodes'] if n['key']=='pricing')
    calls=[]
    def valid(_ws,_p,_n,item,require_fresh=True):
        calls.append(require_fresh); return not require_fresh
    monkeypatch.setattr('backend.native_requests.receipt_valid',valid)
    item={'id':'financial1','project_id':p['id'],'node_id':'other','status':'approved'}
    ws['financial_requests']=[item]
    assert financial_confirmation(ws,p,n,False) is None and not calls
    item['node_id']=n['id']
    assert financial_confirmation(ws,p,n) is None
    assert financial_confirmation(ws,p,n,False) is item
    n['status']='completed'; refresh_project_state(p,ws)
    assert n['status']=='completed' and calls[-1] is False


def test_raw_source_status_and_unverified_lifecycle_do_not_infer_closure(setup):
    ws,p,n,user=setup;t=n['tasks'][0];clock='2026-09-28T09:00:00+08:00'
    p['source_status']='已結案'
    assert not any('來源標示結案' in r or '來源案件狀態待核對' in r for r in activation_reasons(ws,p,n,t,clock))
    p['source_status']='執行中';p['source_lifecycle']={'canonical':None,'state':'needs_verification','reasons':['blank']}
    reasons=activation_reasons(ws,p,n,t,clock)
    assert any('來源案件狀態待核對' in r for r in reasons) and not any('來源標示結案' in r for r in reasons)
    assert t['id'] not in activate_scheduled(ws,clock)
