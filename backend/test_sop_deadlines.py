"""PDF offsets, evidenced anchors, immutable versions and protected schedules."""
from copy import deepcopy

import pytest
from fastapi import HTTPException

from .seed import seed, USERS
from .sources import import_sources
from .operations import apply_operation, add_workdays, missing
from .workflow import apply_action


@pytest.fixture
def state():
    ws=seed(True); ws['users']=deepcopy(USERS)
    import_sources(ws,[dict(kind='confirmation',base_token='v4',table_id='c',record_id='rec1',fields={'工程確認單編號':'C1','狀態':'執行中'})])
    p=ws['projects'][0]; p.update(execution_system='workbench',pm_id='u-pm',admin_id='u-manager',supervisor_id='u-manager',quotation_id='u-field',assistant_id='u-report')
    for n in p['nodes']: n.update(owner_id='u-pm',supervisor_id='u-manager')
    ws['calendar']={'holidays':['2026-09-28'],'workdays':['2026-09-26']}
    return ws


def act(ws,action,payload,user='u-manager'):
    return apply_operation(ws,next(u for u in ws['users'] if u['id']==user),dict(action=action,project_id=ws['projects'][0]['id'],payload=payload))


def anchor(ws,kind='inquiry_received',**changes):
    payload=dict(event_type=kind,scope_key='first-batch',date='2026-09-25',evidence_url='https://example.com/source')
    payload.update(changes); act(ws,'sop_event_record',payload)
    return ws['projects'][0]['sop_events'][-1],payload


def task_for(ws,rule):
    return next(t for n in ws['projects'][0]['nodes'] for t in n['tasks'] if t.get('sop_rule_id')==rule)


@pytest.mark.parametrize('kind,node,expected',[
    ('inquiry_received',None,{'quote_number':'2026-09-25','inquiry_contact':'2026-09-26','quote_provide':'2026-09-30'}),
    ('quote_issued',None,{'quote_followup':'2026-10-09'}),
    ('contract_signed',None,{'case_register':'2026-09-26','signed_contact':'2026-09-29','confirmation_send':'2026-10-02'}),
    ('dispatch_scheduled',None,{'dispatch_date_contact':'2026-09-22','dispatch_detail_contact':'2026-09-22'}),
    ('field_stage_completed',None,{'field_completion_notice':'2026-09-29'}),
    ('confirmation_received','mapping',{'group_register':'2026-09-26'}),
    ('work_completed','control',{'completion_confirmation':'2026-09-30'}),
    ('billing_eligible',None,{'pricing_submit':'2026-09-30'}),
    ('delivery_submitted',None,{'delivery_notice':'2026-09-25'}),
])
def test_all_pdf_relative_offsets_use_holidays_and_makeup_workdays(state,kind,node,expected):
    record,_=anchor(state,kind,node_key=node)
    for rule,due in expected.items():
        task=task_for(state,rule)
        assert task['due_date']==due and task['sop_due_provenance']['event_id']==record['id']
        assert task['sop_due_provenance']['calendar_snapshot']==state['calendar']


def test_backward_workday_calculation_does_not_loop_or_skip_makeup_day(state):
    assert add_workdays('2026-10-01',-3,state['calendar'])=='2026-09-26'
    assert add_workdays('2026-09-27',0,state['calendar'])=='2026-09-27'
    assert add_workdays('2027-01-04',-1,{'holidays':['2027-01-01'],'workdays':[]})=='2026-12-31'


def test_event_requires_actual_date_proof_authority_and_scope(state):
    with pytest.raises(HTTPException,match='同步時間'):
        anchor(state,evidence_url=None)
    with pytest.raises(HTTPException,match='有效|YYYY|必須是文字'):
        anchor(state,date=None)
    with pytest.raises(HTTPException,match='事件範圍'):
        anchor(state,scope_key='')
    with pytest.raises(HTTPException,match='PM、行政或主管'):
        act(state,'sop_event_record',dict(event_type='contract_signed',scope_key='case',date='2026-09-25',evidence_url='https://example.com/signed'),user='u-field')
    assert not state['projects'][0]['sop_events']


def test_replay_does_not_duplicate_and_revision_preserves_original_dates_and_owner(state):
    first,payload=anchor(state); original=task_for(state,'quote_provide'); original_id=original['id']; original_owner=original['owner_id']
    act(state,'sop_event_record',payload)
    assert len(state['projects'][0]['sop_events'])==1 and len(first['task_ids'])==3
    with pytest.raises(HTTPException,match='目前版本'):
        anchor(state,date='2026-09-29')
    second,_=anchor(state,date='2026-09-29',replaces_id=first['id'],reason='業主更正需求日期',assignees={'quote_provide':'u-report'})
    revised=task_for(state,'quote_provide')
    assert second['version']==2 and first['superseded_by']==second['id']
    assert revised['id']==original_id and revised['original_due_date']=='2026-09-30' and revised['due_date']=='2026-10-02'
    assert revised['owner_id']==original_owner


def test_unknown_quotation_role_stays_unassigned_instead_of_guessing_sales(state):
    p=state['projects'][0]; p.pop('quotation_id'); p['sales_id']='u-control'
    anchor(state)
    task=task_for(state,'quote_provide')
    assert task['owner_id']=='' and task['assignment_status']=='pending_assignment'
    assert task_for(state,'inquiry_contact')['owner_id']=='u-pm'


def test_started_task_keeps_schedule_until_formal_change_and_conflict_review(state):
    first,_=anchor(state); task=task_for(state,'quote_provide')
    task.update(status='in_progress',started_at='2026-09-26T09:00:00+08:00')
    anchor(state,date='2026-09-29',replaces_id=first['id'],reason='更正日期')
    p=state['projects'][0]; conflict=p['sop_deadline_conflicts'][0]
    assert conflict['reason']=='work_started' and task['due_date']=='2026-09-30'
    node=next(n for n in p['nodes'] if n['id']==conflict['node_id'])
    assert 'SOP 期限異動尚待主管核對' in missing(p,node,state)
    with pytest.raises(HTTPException,match='正式變更'):
        act(state,'sop_deadline_resolve',dict(id=conflict['id'],resolution='apply_proposed',reason='直接改'))
    act(state,'sop_deadline_resolve',dict(id=conflict['id'],resolution='keep_existing',reason='依原排程執行，另評估正式展延'))
    assert task['due_date']=='2026-09-30' and conflict['status']=='resolved'


def test_fixed_contract_date_is_never_replaced_by_computed_deadline(state):
    p=state['projects'][0]; node=next(n for n in p['nodes'] if n['key']=='sales'); task=node['tasks'][0]
    task.update(due_date='2026-11-01',contract_due_date='2026-11-01')
    first,_=anchor(state,'contract_signed',task_bindings={'case_register':task['id']})
    conflict=p['sop_deadline_conflicts'][0]
    assert task['due_date']=='2026-11-01' and conflict['reason']=='contract_fixed'
    with pytest.raises(HTTPException,match='契約固定'):
        act(state,'sop_deadline_resolve',dict(id=conflict['id'],resolution='apply_proposed',reason='比照SOP'))
    count=len(node['tasks'])
    second,_=anchor(state,'contract_signed',date='2026-09-29',replaces_id=first['id'],reason='更正回簽日期')
    assert second['task_bindings']==first['task_bindings'] and len(node['tasks'])==count
    assert task['due_date']=='2026-11-01'


def test_manual_unstarted_schedule_needs_manager_review(state):
    p=state['projects'][0]; node=next(n for n in p['nodes'] if n['key']=='sales'); task=node['tasks'][0]
    task.update(due_date='2026-11-01',manual_updated=True)
    anchor(state,'contract_signed',task_bindings={'case_register':task['id']})
    conflict=p['sop_deadline_conflicts'][0]
    assert task['due_date']=='2026-11-01' and conflict['reason']=='existing_manual_date'
    with pytest.raises(HTTPException,match='主管'):
        act(state,'sop_deadline_resolve',dict(id=conflict['id'],resolution='apply_proposed',reason='核對'),user='u-pm')
    act(state,'sop_deadline_resolve',dict(id=conflict['id'],resolution='apply_proposed',reason='確認尚未開工，採有佐證的SOP期限'))
    assert task['due_date']=='2026-09-26'


def test_calendar_change_recalculates_unstarted_work_from_saved_anchor(state):
    anchor(state)
    task=task_for(state,'inquiry_contact'); assert task['due_date']=='2026-09-26'
    manager=next(u for u in state['users'] if u['id']=='u-manager')
    apply_action(state,manager,dict(action='calendar_update',payload={'holidays':['2026-09-28'],'workdays':[]}))
    assert task['due_date']=='2026-09-29' and task['original_due_date']=='2026-09-26'
    assert len(state['projects'][0]['sop_events'])==1
