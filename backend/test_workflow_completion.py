"""Acceptance boundaries for delivered work, verified money and scoped deputies."""
from copy import deepcopy

import pytest
from fastapi import HTTPException

from .seed import seed, USERS
from .sources import import_sources
from .operations import apply_operation, missing, refresh_project_state
from .workflow import is_owner, apply_action, now


@pytest.fixture
def state():
    ws=seed(True); ws['users']=deepcopy(USERS)
    import_sources(ws,[dict(kind='confirmation',base_token='v4',table_id='c',record_id='rec1',fields={'工程確認單編號':'C1','工程名稱':'驗收案','狀態':'執行中'})])
    p=ws['projects'][0]; p.update(pm_id='u-pm',admin_id='u-manager',supervisor_id='u-manager',execution_system='workbench')
    for node in p['nodes']:
        node.update(owner_id='u-pm',supervisor_id='u-manager')
        for task in node['tasks']: task['owner_id']='u-pm'
    return ws


def action(ws,name,data=None,user='u-manager',key=None):
    p=ws['projects'][0]; n=next((n for n in p['nodes'] if n['key']==key),None)
    return apply_operation(ws,next(u for u in ws['users'] if u['id']==user),dict(action=name,payload=data or {},project_id=p['id'],node_id=n['id'] if n else None),True)


def prepared(ws,key):
    p=ws['projects'][0]; n=next(n for n in p['nodes'] if n['key']==key)
    for task in n['tasks']: task.update(status='completed',output='已交付成果')
    for rule in n['requirements']:
        p['evidence'].append(dict(id=f"{key}-{rule['key']}-{len(p['evidence'])}",node_id=n['id'],key=rule['key'],status='accepted',note='已核定',url='https://example.com/proof'))
    return p,n


def pair(ws,item,category,batch_id=None):
    for seat,user in [('pm','u-pm'),('admin','u-manager')]:
        action(ws,'finance_attest',dict(category=category,id=item['id'],batch_id=batch_id,seat=seat,evidence='核對原始憑證'),user=user)


def delivery(ws,replaces=None):
    p,n=prepared(ws,'control')
    evidence=next(e for e in reversed(p['evidence']) if e['node_id']==n['id'] and e['key']=='deliverable')
    action(ws,'delivery_submit',dict(work_item_ids=[n['tasks'][0]['id']],quantity='10',unit='點',evidence_ids=[evidence['id']],replaces_id=replaces,reason='更新成果' if replaces else ''))
    item=p['delivery_batches'][-1]
    action(ws,'delivery_review',dict(id=item['id'],result='approved'))
    return item


def payment(ws,item=None,amount='100'):
    action(ws,'payment_create',dict(kind='receivable',phase='progress' if item else 'advance',amount=amount,contract_evidence='回簽合約約定本期可請款',claim_evidence='請款單',delivery_batch_ids=[item['id']] if item else []))
    batch=ws['projects'][0]['payment_batches'][-1]
    pair(ws,batch,'batch'); action(ws,'payment_approve',{'id':batch['id']})
    return batch


def test_engineering_pending_prevents_settlement_even_with_zero_balance(state):
    p,n=prepared(state,'settlement')
    action(state,'finance_propose',dict(contract_amount='0',budget='0',evidence='零元內部案核定'))
    pair(state,p['finance_versions'][-1],'baseline'); action(state,'finance_approve',{'id':p['finance_versions'][-1]['id']})
    action(state,'payment_reconcile',dict(evidence='無未清收付款',all_payables_declared=True))
    assert '適用工程交付尚未全部完成' in missing(p,n,state)
    with pytest.raises(HTTPException,match='適用工程交付'):
        action(state,'review_submit',key='settlement')
    assert p['execution_status']!='completed'


def test_changed_evidence_reopens_completed_case_and_settlement(state):
    p,n=prepared(state,'control')
    for node in p['nodes']: node['status']='completed'
    p.update(execution_status='completed',payment_reconciliation={'confirmed':True})
    action(state,'evidence_submit',dict(key='deliverable',note='重新交付',url='https://example.com/revision'),user='u-pm',key='control')
    assert n['status']=='rework' and p['execution_status']=='in_progress'
    assert next(node for node in p['nodes'] if node['key']=='settlement')['status']=='rework'


def test_progress_payment_requires_approved_delivery_not_free_text(state):
    with pytest.raises(HTTPException,match='交付批次'):
        action(state,'payment_create',dict(kind='receivable',phase='progress',amount='100',contract_evidence='合約',claim_evidence='文字'))
    item=delivery(state); batch=payment(state,item)
    assert batch['delivery_references']==[dict(id=item['id'],version=item['version'],content_hash=item['content_hash'])]
    with pytest.raises(HTTPException,match='重複請款'):
        payment(state,item)


def test_delivery_reassignment_requires_current_supervisor_review(state):
    p,n=prepared(state,'control')
    n['supervisor_id']='u-control'
    evidence=next(e for e in reversed(p['evidence']) if e['node_id']==n['id'] and e['key']=='deliverable')
    action(state,'delivery_submit',dict(work_item_ids=[n['tasks'][0]['id']],quantity='10',unit='點',evidence_ids=[evidence['id']]))
    item=p['delivery_batches'][-1]
    assert item['required_reviewer_ids']==['u-control']

    action(state,'project_roles',{'node_supervisor_id':'u-field'},user='u-manager',key='control')
    with pytest.raises(HTTPException,match='現任交付組主管'):
        action(state,'delivery_review',dict(id=item['id'],result='approved'),user='u-control')
    action(state,'delivery_review',dict(id=item['id'],result='approved'),user='u-field')
    from .operations import delivery_current
    assert item['required_reviewer_ids']==['u-field']
    assert [vote['actor_id'] for vote in item['approvals']]==['u-field']
    assert delivery_current(p,item,state)


def test_supervisor_handover_updates_only_matching_node_review_seats(state):
    p,n=prepared(state,'control')
    unrelated=next(node for node in p['nodes'] if node['key']=='field')
    unrelated['supervisor_id']='u-control'
    action(state,'review_submit',{},user='u-pm',key='control')
    prior_cycle=n['review_cycles'][-1]
    assert prior_cycle['seats']['supervisor']=='u-manager'

    action(state,'handover_request',{'from_id':'u-manager','to_id':'u-field','reason':'主管交接'},user='u-manager')
    handover=state['handover_requests'][-1]
    action(state,'handover_approve',{'id':handover['id']},user='u-manager')
    action(state,'handover_accept',{'id':handover['id']},user='u-field')

    assert p['supervisor_id']=='u-field' and n['supervisor_id']=='u-field'
    assert unrelated['supervisor_id']=='u-control'
    assert prior_cycle['seats']['supervisor']=='u-field'
    action(state,'review_submit',{},user='u-pm',key='control')
    assert prior_cycle['status']=='invalidated'
    assert n['review_cycles'][-1]['content_hash']!=prior_cycle['content_hash']


def test_one_delivery_can_be_billed_while_other_is_returned(state):
    first=delivery(state); second=delivery(state)
    second['status']='returned'
    batch=payment(state,first)
    assert batch['status']=='approved'
    with pytest.raises(HTTPException,match='尚未核定'):
        payment(state,second)


def test_new_batch_evidence_preserves_approved_delivery_but_revision_invalidates(state):
    from .operations import delivery_current
    first=delivery(state);p=state['projects'][0];n=next(n for n in p['nodes'] if n['key']=='control')
    prior_proof=next(e for e in p['evidence'] if e['id']==first['evidence_ids'][0])
    n['status']='completed';n['review_cycles']=[{'id':'previous','status':'approved'}]
    action(state,'evidence_submit',{'key':'deliverable','note':'第二批成果','url':'https://example.com/batch2','new_batch':True},user='u-pm',key='control')
    assert delivery_current(p,first,state) and first['status']=='approved'
    assert prior_proof['superseded_for_current'] and not prior_proof.get('withdrawn')
    assert n['review_cycles'][0]['status']=='approved' and n['review_cycles'][0]['historical_scope']
    assert n['status']=='in_progress'
    action(state,'evidence_submit',{'key':'deliverable','note':'修訂第二批，不影響第一批','url':'https://example.com/correction2'},user='u-pm',key='control')
    assert delivery_current(p,first,state)
    action(state,'evidence_submit',{'key':'deliverable','note':'第一批原成果有誤，明確修訂','url':'https://example.com/correction1','replaces_evidence_id':prior_proof['id']},user='u-pm',key='control')
    assert not delivery_current(p,first,state) and first['status']=='invalidated'


def test_delivery_revision_requires_fresh_pair_and_preserves_history(state):
    original=delivery(state); batch=payment(state,original)
    revised=delivery(state,replaces=original['id'])
    assert batch['status']=='needs_review'
    with pytest.raises(HTTPException,match='重複請款'):
        payment(state,revised)
    action(state,'payment_revise',dict(id=batch['id'],delivery_batch_ids=[revised['id']],reason='成果核定換版'))
    assert batch['status']=='draft' and not batch['attestations']
    assert batch['revision_history'][0]['attestations']
    with pytest.raises(HTTPException,match='兩位不同操作者'):
        action(state,'payment_approve',{'id':batch['id']})
    pair(state,batch,'batch'); action(state,'payment_approve',{'id':batch['id']})
    assert batch['status']=='approved'


def test_receipt_only_counts_paid_after_two_distinct_confirmers(state):
    batch=payment(state)
    action(state,'payment_record',dict(id=batch['id'],amount='100',date='2026-09-27',evidence='匯款憑證'))
    receipt=batch['receipts'][0]
    assert batch['status']=='approved' and receipt['status']=='pending' and not receipt['verified']
    action(state,'finance_attest',dict(category='receipt',id=receipt['id'],batch_id=batch['id'],seat='pm',evidence='PM核對'),user='u-pm')
    assert batch['status']=='approved'
    action(state,'finance_attest',dict(category='receipt',id=receipt['id'],batch_id=batch['id'],seat='admin',evidence='行政核對'))
    assert batch['status']=='paid' and receipt['verified'] and batch['verified_amount']=='100'


def test_legacy_paid_without_binding_or_verified_receipt_needs_review(state):
    p=state['projects'][0]
    p['payment_batches'].append(dict(id='legacy',kind='receivable',phase='progress',amount='100',status='paid',receipts=[dict(id='old-receipt',amount='100',evidence='old')]))
    refresh_project_state(p,state)
    assert p['payment_batches'][0]['status']=='needs_review'
    assert not p['payment_batches'][0]['receipts'][0]['verified']


def delegation(ws,task_ids,**extras):
    return dict(principal_id='u-pm',delegate_id='u-field',seat='owner',scope='tasks',source='supervisor',task_ids=task_ids,start_date='2026-09-01',end_date='2026-12-31',qualified=True,qualification_note='主管核對代理資格',qualification_evidence='能力認定紀錄',**extras)


def test_task_proxy_is_limited_to_explicit_tasks_and_records_principal(state,monkeypatch):
    monkeypatch.setattr('backend.workflow.now',lambda:'2026-09-27T10:00:00+08:00')
    p,n=prepared(state,'field'); first,second=n['tasks'][:2]
    first['status']='pending'; second['status']='pending'
    action(state,'delegation_set',delegation(state,[first['id']]))
    delegate=next(u for u in state['users'] if u['id']=='u-field')
    assert is_owner(delegate,first,state) and not is_owner(delegate,second,state)
    apply_action(state,delegate,dict(action='task_start',project_id=p['id'],node_id=n['id'],task_id=first['id'],payload={}))
    assert state['events'][0]['actor_id']=='u-field' and state['events'][0]['principal_id']=='u-pm'


def test_inner_proxy_requires_server_verified_matching_leave(state):
    p,n=prepared(state,'control'); payload=delegation(state,[n['tasks'][0]['id']])
    with pytest.raises(HTTPException,match='請假審批'):
        action(state,'delegation_set',payload)
    payload.update(source='approval',approval_instance_id='leave-1')
    with pytest.raises(HTTPException,match='尚未核實'):
        action(state,'delegation_set',payload)
    state['approved_leave_delegations']=[dict(id='leave-1',principal_id='u-pm',delegate_id='u-field',status='APPROVED',verified_at=now(),**{'from':'2026-09-01T00:00:00+08:00','to':'2026-12-31T23:59:59+08:00'})]
    action(state,'delegation_set',payload)
    state['approved_leave_delegations'][0]['status']='CANCELED'
    delegate=next(u for u in state['users'] if u['id']=='u-field')
    assert not is_owner(delegate,n['tasks'][0],state)


def test_boolean_or_unqualified_financial_proxy_cannot_grant_approval(state):
    payload=delegation(state,[]); payload.update(principal_id='u-manager',seat='admin',scope='review')
    with pytest.raises(HTTPException,match='已有財務確認權'):
        action(state,'delegation_set',payload)
    next(u for u in state['users'] if u['id']=='u-field')['capabilities']=['finance_approve']
    payload['qualification_evidence']=''
    with pytest.raises(HTTPException,match='資格審查'):
        action(state,'delegation_set',payload)


def test_approval_proxy_enforces_exact_hours_and_recent_server_verification(state,monkeypatch):
    clock=['2026-09-27T12:00:00+08:00']
    monkeypatch.setattr('backend.operations.now',lambda:clock[0]); monkeypatch.setattr('backend.workflow.now',lambda:clock[0])
    p,n=prepared(state,'control'); task=n['tasks'][0]
    payload=delegation(state,[task['id']]); payload.update(source='approval',approval_instance_id='afternoon',start_date='2026-09-27',end_date='2026-09-27')
    approval=dict(id='afternoon',principal_id='u-pm',delegate_id='u-field',status='APPROVED',verified_at=clock[0],**{'from':'2026-09-27T13:00:00+08:00','to':'2026-09-27T17:00:00+08:00'})
    state['approved_leave_delegations']=[approval]
    action(state,'delegation_set',payload)
    delegate=next(u for u in state['users'] if u['id']=='u-field')
    assert not is_owner(delegate,task,state)  # Approval exists, leave has not begun.
    clock[0]='2026-09-27T13:00:00+08:00'; approval['verified_at']=clock[0]
    assert is_owner(delegate,task,state)
    clock[0]='2026-09-27T13:05:01+08:00'
    assert not is_owner(delegate,task,state)  # Stale verification fails closed.
    clock[0]='2026-09-27T17:00:01+08:00'; approval['verified_at']=clock[0]
    assert not is_owner(delegate,task,state)  # Same calendar day, but leave ended.


def test_daily_reporter_identity_uses_source_id_not_display_name(state):
    p=state['projects'][0]
    state['daily_unmatched']=[dict(id='daily1',person='u-field',source_actor_ids=[])]
    with pytest.raises(HTTPException,match='填報人'):
        action(state,'daily_propose',dict(daily_id='daily1',reason='本人補充'),user='u-field')
    state['daily_unmatched'][0]['source_actor_ids']=['u-field']
    action(state,'daily_propose',dict(daily_id='daily1',reason='本人補充'),user='u-field')
    assert state['daily_reviews'][0]['status']=='pending'


@pytest.mark.parametrize('change',['source_changed','removed','duplicate'])
def test_daily_mapping_approval_rejects_stale_or_missing_source(state,change):
    state['daily_unmatched']=[dict(id='daily1',source_fields={'original':'v1'},date='2026-09-27',case_mapping_status='missing_reference')]
    action(state,'daily_propose',dict(daily_id='daily1',reason='核對來源'))
    review=state['daily_reviews'][-1]
    if change=='source_changed': state['daily_unmatched'][0]['source_fields']['original']='v2'
    elif change=='removed': state['daily_unmatched']=[]
    else: state['daily_unmatched'].append(deepcopy(state['daily_unmatched'][0]))
    before=deepcopy(state)
    with pytest.raises(HTTPException) as exc: action(state,'daily_approve',dict(id=review['id']))
    assert exc.value.status_code==409 and state==before


def test_daily_mapping_approval_preserves_current_derived_metadata(state):
    state['daily_unmatched']=[dict(id='daily1',source_fields={'original':'v1'},date='2026-09-26',case_mapping_status='missing_reference')]
    action(state,'daily_propose',dict(daily_id='daily1',reason='核對來源'))
    review=state['daily_reviews'][-1]
    # A linked cost record refreshes derived metadata without changing case evidence.
    state['daily_unmatched'][0]['date']='2026-09-27'
    action(state,'daily_approve',dict(id=review['id']))
    assert not state['daily_unmatched'] and review['status']=='approved'
    report=state['projects'][0]['daily_reports'][-1]
    assert report['date']=='2026-09-27' and report['case_mapping_status']=='matched'


def test_project_and_node_supervisors_are_separate(state):
    p=state['projects'][0]; n=next(n for n in p['nodes'] if n['key']=='control')
    action(state,'project_roles',dict(supervisor_id='u-field',node_supervisor_id='u-report',sales_id='u-control'),key='control')
    assert p['supervisor_id']=='u-field' and n['supervisor_id']=='u-report' and p['sales_id']=='u-control'


def test_migration_review_blocks_finance_and_preserves_conflict_evidence(state):
    p,n=prepared(state,'pricing')
    p.update(migration_review_required=True,migration_conflicts={'finance':['兩案各有核定財務'],'pm_id':['prior','u-pm']})
    assert '來源案件合併尚待主管核對' in missing(p,n,state)
    action(state,'finance_propose',dict(contract_amount='100',budget='20',evidence='合併後有效回簽版本'))
    version=p['finance_versions'][-1]; pair(state,version,'baseline')
    with pytest.raises(HTTPException,match='來源案件合併'):
        action(state,'finance_approve',{'id':version['id']})
    with pytest.raises(HTTPException,match='案件主管'):
        action(state,'migration_review',dict(reason='已核對'),user='u-field')
    with pytest.raises(HTTPException,match='核對結果'):
        action(state,'migration_review',{})
    action(state,'migration_review',dict(reason='已核對人員和既有工作，財務另行共同核定'))
    assert not p['migration_review_required'] and not p['migration_conflicts']
    assert p['migration_review_history'][-1]['conflicts']['finance']==['兩案各有核定財務']
    assert p['migration_finance_reapproval_required'] and not version['attestations']
    assert len(version['attestation_history'])==2
    with pytest.raises(HTTPException,match='兩位不同操作者'):
        action(state,'finance_approve',{'id':version['id']})
    pair(state,version,'baseline'); action(state,'finance_approve',{'id':version['id']})
    assert not p['migration_finance_reapproval_required'] and p['contract_amount']==100


def test_settings_reject_unknown_test_modes_unapproved_sources_and_fixed_cutoff(state):
    from .policy import defaults
    before=deepcopy(state['settings'])
    with pytest.raises(HTTPException,match='連線模式'):
        action(state,'admin_settings',dict(test_connection_mode='production_bypass'))
    for key in ('v4_base','quote_base','capability_base'):
        with pytest.raises(HTTPException,match='已核定'):
            action(state,'admin_settings',{key:'arbitrary-base'})
    with pytest.raises(HTTPException,match='正常班表'):
        action(state,'admin_settings',dict(cutoff_time='17:00'))
    assert state['settings']==before
    action(state,'admin_settings',dict(test_connection_mode='isolated_live'))
    assert state['settings']['test_connection_mode']=='isolated_live'
    assert state['settings']['cutoff_time'] is None
    assert all(state['settings'][key]==defaults()[key] for key in ('v4_base','quote_base','capability_base'))
