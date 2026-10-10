"""Synthetic cross-surface proof: pending -> manager assignment -> eligibility.

No production data. Admission/gates are the shared backend ones; this only
asserts every surface agrees before and after one audited manager decision.
"""
from copy import deepcopy
from datetime import datetime,timezone
import pytest
from fastapi import HTTPException
from .case_cutover import assign_execution,execution_allowed,require_execution
from .company_dashboard import overview
from .jobs import schedule
from .workflow_rules import activate_scheduled
from .test_workflow_automation import setup  # noqa: F401  (synthetic seeded fixture)

NOW='2026-09-28T09:00:00+08:00'


@pytest.fixture
def pending(setup):
    ws,p,n,user=setup
    ws['environment']='production'
    p.update(source_kind='lark',case_type='formal',case_visibility='source_reference',execution_system='pending')
    ws['people_directory_status']={'app_id':'app1'}
    user.update(active=True,identity_app_id='app1',directory_status='employed',
        directory_source={'app_id':'app1','record_id':'synthetic'},directory_last_seen_at='2026-09-28T08:00:00+08:00')
    p['source_lifecycle']={'state':'mapped','canonical':'執行中','reasons':[],'relationship':'已關聯確認單','quote_workflow':[]}
    from .case_cutover import project_execution_view
    p.update(project_execution_view(ws,p))
    manager=next(u for u in ws['users'] if u['role']=='manager')
    return ws,p,n,manager


def surfaces(ws,p,n):
    """Every execution-sensitive surface, evaluated from stored state only."""
    before=len(ws['recurring']);jobs=len(ws['jobs'])
    activated=activate_scheduled(ws,NOW)
    schedule(ws,NOW)
    created=[r for r in ws['recurring'][before:] if r['project_id']==p['id']]
    try:require_execution(ws,p);outbound=True
    except HTTPException as error:outbound=error.status_code
    return {'activated':[t for t in activated if t in {x['id'] for x in n['tasks']}],'routines':created,
            'outbound':outbound,'allowed':execution_allowed(ws,p),'new_jobs':len(ws['jobs'])-jobs}


def test_pending_source_case_blocks_every_surface_and_is_explained(pending):
    ws,p,n,_=pending
    result=surfaces(ws,p,n)
    assert result['activated']==[] and result['routines']==[] and result['new_jobs']==0
    assert result['outbound']==409 and result['allowed'] is False
    assert all(t['status']=='pending' for t in n['tasks'])
    row=overview(ws,clock=datetime(2026,9,28,tzinfo=timezone.utc))['cases'][0]
    assert row['execution_system']=='pending' and row['execution_readonly_reason']=='等待管理員核定案件歸屬'
    assert row['case_visibility']=='source_reference' and row['workbench_execution_enabled'] is False


@pytest.mark.parametrize('role',['pm','member','supervisor'])
def test_non_manager_cannot_assign_and_surfaces_stay_blocked(pending,role):
    ws,p,n,manager=pending
    actor=deepcopy(manager);actor['role']=role
    with pytest.raises(HTTPException) as error:assign_execution(ws,actor,p['id'],'workbench','不應生效')
    assert error.value.status_code==403 and p['execution_system']=='pending'
    assert 'execution_assignment_history' not in p
    result=surfaces(ws,p,n)
    assert result['activated']==[] and result['outbound']==409


def test_manager_single_case_assignment_is_audited_and_enables_all_surfaces_together(pending):
    ws,p,n,manager=pending
    other=deepcopy(p);other.update(id='syn-other',code='SYN-OTHER');ws['projects'].append(other)
    assert surfaces(ws,p,n)['outbound']==409
    assign_execution(ws,manager,p['id'],'workbench','合成測試：核定由工作台執行')
    from .case_cutover import project_execution_view
    p.update(project_execution_view(ws,p))
    result=surfaces(ws,p,n)
    # Eligibility: activation, schedule routines and outbound all open on the same decision.
    assert result['allowed'] is True and result['outbound'] is True
    assert {t['id'] for t in n['tasks']}<=set(result['activated'])
    assert result['routines']
    assert ws['events'][-1]['action']=='case_execution_assign' or any(e['action']=='case_execution_assign' for e in ws['events'])
    assert p['execution_assignment']['recorded_by']==manager['id']
    assert len(p['execution_assignment_history'])==1
    # Single-case path: a sibling pending case is untouched and still blocked everywhere.
    assert other['execution_system']=='pending' and not execution_allowed(ws,other)
    with pytest.raises(HTTPException):require_execution(ws,other)
    row={r['id']:r for r in overview(ws,clock=datetime(2026,9,28,tzinfo=timezone.utc))['cases']}
    assert row[p['id']]['execution_system']=='workbench' and row[p['id']]['execution_readonly_reason'] is None
    assert row['syn-other']['execution_system']=='pending'


def test_assignment_cannot_revive_isolated_history(pending):
    ws,p,n,manager=pending
    p['case_visibility']='excluded_history'
    with pytest.raises(HTTPException) as error:assign_execution(ws,manager,p['id'],'workbench','合成測試')
    assert error.value.status_code==409
    assert surfaces(ws,p,n)['allowed'] is False


def test_assignment_does_not_override_unverified_source_lifecycle(pending):
    """#6: admission and verified lifecycle are independent gates; both must pass."""
    ws,p,n,manager=pending
    p['source_lifecycle']={'state':'needs_verification','canonical':None,'reasons':['blank'],'quote_workflow':[]}
    assign_execution(ws,manager,p['id'],'workbench','合成測試：核定由工作台執行')
    assert execution_allowed(ws,p)
    result=surfaces(ws,p,n)
    assert result['activated']==[] and result['routines']==[]
