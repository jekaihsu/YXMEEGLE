"""Home presentation uses verified authority, workflow blockers and stored facts."""
from copy import deepcopy

from . import home_details, workflow


AS_OF='2026-10-13'


def fixture():
    users=[dict(id='owner',name='Owner',active=True,role='member'),dict(id='viewer',name='Viewer',active=True,role='member')]
    task=dict(id='t1',title='Work',owner_id='owner',status='pending',start_date=AS_OF,
              due_date='2026-10-10',original_due_date='2026-10-09',input_task_ids=[],output='')
    node=dict(id='n1',key='sales',name='Sales',status='pending',tasks=[task])
    project=dict(id='p1',code='P1',source_kind='demo',case_type='formal',execution_status='in_progress',
                 nodes=[node],evidence=[],delivery_batches=[])
    ws=dict(environment='demo',users=users,projects=[project],delegations=[],approved_leave_delegations=[],
            approvals=[],events=[],calendar=dict(holidays=['2026-10-12'],workdays=['2026-10-10']))
    return ws,project,node,task,users[1]


def test_field_contact_uses_workflow_permit_exemption():
    ws,p,n,t,user=fixture(); t['owner_id']=user['id']; n['key']='field'; t['sop_rule_id']='dispatch_date_contact'
    result=home_details.build_home_task(ws,p,n,t,user,AS_OF)
    assert result['assigned'] and result['can_execute'] and result['detail']['actionable']
    assert result['execution_blockers']==[]
    t.pop('sop_rule_id')
    blocked=home_details.build_home_task(ws,p,n,t,user,AS_OF)
    assert not blocked['detail']['actionable']
    assert '行政公務證明尚未齊備' in blocked['execution_blockers']


def test_verified_proxy_uses_current_exact_delegation_even_on_historical_snapshot(monkeypatch):
    monkeypatch.setattr(home_details,'now',lambda:'2026-10-13T09:00:00+08:00')
    monkeypatch.setattr(workflow,'now',lambda:'2026-10-13T09:00:00+08:00')
    ws,p,n,t,user=fixture()
    def delegation(ident,start,end,basis,project='p1'):
        return dict(id=ident,project_id=project,principal_id='owner',delegate_id='viewer',seat='owner',scope='tasks',
                    task_ids=['t1'],status='active',start_date=start,end_date=end,qualified=True,
                    qualification_evidence='verified',source='supervisor',qualification_note=basis)
    ws['delegations']=[delegation('old','2026-08-01','2026-08-31','EXPIRED BASIS'),
                       delegation('other-project','2026-10-01','2026-10-31','WRONG PROJECT',project='p2'),
                       delegation('current','2026-10-01','2026-10-31','CURRENT BASIS')]
    result=home_details.build_home_task(ws,p,n,t,user,'2026-10-07')
    assert result['assigned'] and result['detail']['proxy']['delegation_id']=='current'
    assert result['detail']['proxy']['basis']=='主管核定代理'
    assert 'EXPIRED BASIS' not in str(result['detail'])
    t['status']='paused'
    paused=home_details.build_home_task(ws,p,n,t,user,'2026-10-07')
    assert paused['detail']['kind']=='paused' and paused['detail']['proxy']['delegation_id']=='current'
    ws['delegations'][-1]['qualified']=False
    revoked=home_details.build_home_task(ws,p,n,t,user,'2026-10-07')
    assert not revoked['assigned'] and revoked['detail'] is None


def test_unassigned_coworker_has_no_home_detail_even_with_override_authority():
    ws,p,n,t,user=fixture()
    result=home_details.build_home_task(ws,p,n,t,user,AS_OF)
    assert not result['assigned'] and result['detail'] is None


def test_paused_task_keeps_known_dates_and_labels_calendar_basis():
    ws,p,n,t,user=fixture(); t['owner_id']=user['id']; t['status']='paused'; t['original_due_date']=None
    p['source_lifecycle']=dict(state='needs_verification',canonical=None,reasons=['blank'])
    result=home_details.build_home_task(ws,p,n,t,user,AS_OF)['detail']
    assert result['kind']=='paused' and result['pause']['source']=='lifecycle_verification'
    assert result['risk']['original_due_date'] is None
    assert result['risk']['current_due_date']=='2026-10-10'
    assert result['risk']['estimated_due_date'] is None and result['risk']['pause_clock']=='unavailable'
    assert result['risk']['overdue_calendar_days']==3
    assert result['risk']['overdue_workdays']==1  # Monday holiday; Saturday is a configured workday but due day is excluded.
    ws.pop('calendar')
    assert home_details.build_home_task(ws,p,n,t,user,AS_OF)['detail']['risk']['workday_status']=='unavailable'


def test_correction_prerequisite_and_batch_links_use_exact_stored_ids():
    ws,p,n,t,user=fixture(); t['owner_id']=user['id']; t['status']='rework'; t['input_task_ids']=['upstream','missing']
    n['tasks'].append(dict(id='upstream',title='Input',owner_id='owner',status='completed',output=''))
    ws['events']=[dict(id='wrong',action='task_return',project_id='p1',node_id='n1',task_id='other',message='WRONG',created_at='2026-10-12'),
                  dict(id='return',action='task_return',project_id='p1',node_id='n1',task_id='t1',message='Please correct scope',created_at='2026-10-13')]
    p['delivery_batches']=[dict(id='linked',status='submitted',task_snapshots=[dict(id='t1')]),
                            dict(id='unlinked',status='submitted',task_snapshots=[dict(id='other')])]
    result=home_details.build_home_task(ws,p,n,t,user,AS_OF)['detail']
    assert result['kind']=='correction' and result['correction']['reason']=='Please correct scope'
    assert not result['actionable'] and len(result['prerequisites'])==2
    assert result['prerequisites'][0]['title']=='Input' and result['prerequisites'][0]['owner_name']=='Owner'
    assert not result['prerequisites'][0]['ready'] and result['prerequisites'][1]['missing']
    assert result['delivery_links']==[dict(batch_id='linked',status='submitted',match_basis='task_snapshot_id')]


def test_unrecorded_pause_and_forecast_remain_unknown():
    ws,p,n,t,user=fixture(); t['owner_id']=user['id']; p['execution_status']='paused'; t['due_date']=None
    result=home_details.build_home_task(ws,p,n,t,user,AS_OF)['detail']
    assert result['kind']=='paused' and result['pause']['reason'] is None
    assert result['reason']=='暫停原因待核對'
    assert result['risk']['current_due_date'] is None and result['risk']['estimated_due_date'] is None
    assert result['risk']['overdue_calendar_days'] is None and result['risk']['delivery_impact']=='unavailable'


def test_exact_frozen_change_reason_and_node_scoped_review_reason():
    ws,p,n,t,user=fixture(); t['owner_id']=user['id']; t['status']='paused'
    ws['approvals']=[dict(id='wrong',project_id='p1',type='change',frozen=True,task_ids=['other'],reason='Wrong scope'),
                     dict(id='actual',project_id='p1',type='change',frozen=True,task_ids=['t1'],reason='Confirmed scope change')]
    paused=home_details.build_home_task(ws,p,n,t,user,AS_OF)['detail']
    assert paused['pause']['source']=='frozen_change_approval'
    assert paused['pause']['reason']=='Confirmed scope change'
    t['status']='rework'; ws['approvals']=[]; n['status']='rework'
    n['review_cycles']=[dict(id='cycle',status='returned',created_at=AS_OF,votes=[dict(result='returned',reason='Drawing revision required',created_at=AS_OF)])]
    returned=home_details.build_home_task(ws,p,n,t,user,AS_OF)['detail']
    assert returned['correction']['source']=='node_review_vote'
    assert returned['correction']['reason']=='節點審核退回：Drawing revision required'


def test_current_node_return_applies_to_pending_task_but_stale_vote_does_not():
    ws,p,n,t,user=fixture(); t['owner_id']=user['id']; n['status']='rework'
    n['review_cycles']=[dict(id='old',status='returned',created_at='2026-10-10',votes=[
        dict(result='returned',reason='Outdated reason',created_at='2026-10-10')]),
        dict(id='current',status='returned',created_at='2026-10-13',votes=[
        dict(result='returned',reason='Missing survey sheet',created_at='2026-10-13')])]
    current=home_details.build_home_task(ws,p,n,t,user,AS_OF)['detail']
    assert current['kind']=='correction'
    assert current['correction']['source']=='node_review_vote'
    assert current['correction']['reason']=='節點審核退回：Missing survey sheet'
    n['review_cycles'][-1]['status']='pending'
    stale=home_details.build_home_task(ws,p,n,t,user,AS_OF)['detail']
    assert stale['correction']['reason'] is None
    assert 'Outdated reason' not in str(stale)
