from copy import deepcopy
import pytest
from fastapi import HTTPException
from .case_cutover import (assign_execution,execution_allowed,execution_system,
    initialize_execution_system,project_execution_view,require_execution)
from .seed import seed,USERS
from .sources import import_sources
from .test_source_sync import harness,records,snapshot


def formal():
    state=seed();state['environment']='production';state['users']=deepcopy(USERS)
    return state


def manager(state):return next(u for u in state['users'] if u['role']=='manager')


@pytest.mark.parametrize('action,collection,key',[
    ('input_mapping_disable','input_mappings','id'),('input_draft','input_mappings','mapping_id'),
    ('input_submit','input_revisions','id'),('sop_apply','sop_requests','id'),
    ('delegation_revoke','delegations','id'),('recurring_complete','recurring','id'),
    ('recurring_review','recurring','id'),('daily_approve','daily_reviews','id'),
    ('handover_approve','handover_requests','id'),('handover_accept','handover_requests','id'),
    ('approval_withdraw','approvals','approval_id'),('change_resume','approvals','approval_id'),
    ('node_skip_withdraw','node_skip_requests','id'),('node_skip_apply','node_skip_requests','id')])
def test_indirect_action_resolves_real_case_and_rejects_forged_case(action,collection,key):
    from .case_cutover import resolve_action_projects
    state=formal();p=state['projects'][0];other=state['projects'][1]
    state[collection]=[{'id':'indirect','project_id':p['id']}]
    body={'action':action,'payload':{key:'indirect'}}
    assert resolve_action_projects(state,body)==[p]
    p['execution_system']='meegle'
    with pytest.raises(HTTPException):require_execution(state,resolve_action_projects(state,body)[0])
    body['project_id']=other['id']
    with pytest.raises(HTTPException):resolve_action_projects(state,body)


def test_retry_resolves_job_payload_and_missing_ownership_fails_closed():
    from .case_cutover import resolve_action_projects
    state=formal();p=state['projects'][0]
    state['jobs']=[{'id':'job','kind':'input','payload':{'project_id':p['id']}}]
    body={'action':'job_retry','payload':{'id':'job'}}
    assert resolve_action_projects(state,body)==[p]
    state['jobs'][0]['payload']={}
    with pytest.raises(HTTPException):resolve_action_projects(state,body)


def test_formal_existing_cases_require_decision_without_losing_results():
    state=formal();p=state['projects'][0];p['nodes'][0]['tasks'][0].update(status='completed',output='既有成果')
    before=deepcopy(p)
    initialized=initialize_execution_system(state)
    assert p['id'] in initialized and not execution_allowed(state,p)
    assert p['nodes']==before['nodes'] and p['files']==before['files']
    snapshot_state=deepcopy(state)
    assert initialize_execution_system(state)==[] and state==snapshot_state
    with pytest.raises(HTTPException):require_execution(state,p)


def test_admin_decision_audited_and_meegle_is_readonly_then_can_be_explicitly_reassigned():
    state=formal();p=state['projects'][0];before=deepcopy(p['nodes'])
    assign_execution(state,manager(state),p['id'],'meegle','此案在 Meegle 完成')
    assert not execution_allowed(state,p) and p['nodes']==before
    assert state['events'][0]['action']=='case_execution_assign'
    assert p['execution_assignment_history'][-1]['to']=='meegle'
    assign_execution(state,manager(state),p['id'],'workbench','已核定新案由工作台處理')
    require_execution(state,p)
    assert p['nodes']==before and len(p['execution_assignment_history'])==2
    assert project_execution_view(state,p)['execution_allowed'] is True


@pytest.mark.parametrize('bad',['member','inactive','invalid_target','no_reason'])
def test_assignment_never_uses_business_pm_privilege_or_invalid_request(bad):
    state=formal();p=state['projects'][0];actor=deepcopy(manager(state));target='workbench';reason='核定'
    if bad=='member':actor['role']='pm'
    if bad=='inactive':actor['active']=False
    if bad=='invalid_target':target='auto'
    if bad=='no_reason':reason=' '
    before=deepcopy(state)
    with pytest.raises(HTTPException):assign_execution(state,actor,p['id'],target,reason)
    assert state==before


def test_source_refresh_preserves_decision_and_new_source_still_pending():
    state=formal();state['projects']=[]
    import_sources(state,records());p=state['projects'][0]
    assert execution_system(p)=='pending'
    assign_execution(state,manager(state),p['id'],'meegle','舊案')
    p['nodes'][0]['tasks'][0].update(status='completed',output='不可清除')
    pid=p['id'];task_id=p['nodes'][0]['tasks'][0]['id']
    rows=records()+[dict(base_token='v4',table_id='confirmation',record_id='newRecord',kind='confirmation',fields={'工程確認單編號':'C115999','狀態':'執行中'})]
    import_sources(state,rows)
    old=next(p for p in state['projects'] if p['id']==pid)
    new=next(p for p in state['projects'] if p['id']!=pid)
    assert old['execution_system']=='meegle' and new['execution_system']=='pending'
    assert next(t for n in old['nodes'] for t in n['tasks'] if t['id']==task_id)['output']=='不可清除'


def test_missing_environment_or_unknown_assignment_is_not_an_execution_bypass():
    assert not execution_allowed({}, {'id':'p','execution_system':'unknown'})
    for env in ('test','demo'):
        state={'environment':env,'projects':[{'id':'p'}]}
        assert initialize_execution_system(state)==[] and execution_allowed(state,state['projects'][0])


def test_mixed_source_identity_merge_cannot_inherit_workbench_permission():
    from .case_cutover import reconcile_merged_execution
    state=formal();primary,other=state['projects'][:2]
    primary['execution_system']='workbench';other['execution_system']='meegle'
    before=deepcopy(primary['nodes'])
    assert reconcile_merged_execution(state,primary,[primary,other])
    assert primary['execution_system']=='pending' and primary['nodes']==before
    assert primary['execution_assignment']['previous_decisions'][other['id']]=='meegle'


def test_background_source_sync_survives_last_operator_departure_but_not_disabled_connection(harness):
    from . import storage
    h=harness
    with h.sessions.begin() as db:
        row=db.get(h.W,h.wid);state=storage.load(db,h.B,row)
        next(u for u in state['users'] if u['id']=='u-manager')['active']=False
        row.data=storage.save(db,h.B,h.wid,state)
        db.get(h.P,(h.wid,'u-manager')).data=dict(db.get(h.P,(h.wid,'u-manager')).data,active=False)
    h.clock[0]='2026-09-27T10:10:00+08:00'
    assert h.service.run_due(h.wid)['status']=='ready'
    state,_=h.read()
    assert state['source_connection']['authorization']=='company_application_readonly'
    assert state['source_connection']['authorized_by']=='u-manager'
    assert state['events'][0]['actor_id']=='system:company-readonly'
    with h.sessions.begin() as db:
        row=db.get(h.W,h.wid);state=storage.load(db,h.B,row);state['source_connection']['enabled']=False
        row.data=storage.save(db,h.B,h.wid,state)
    before=len(h.fetched);h.clock[0]='2026-09-27T10:20:00+08:00'
    assert h.service.run_due(h.wid) is None and len(h.fetched)==before


def test_identical_source_snapshot_does_not_bump_case_revision_or_changed_at(harness,monkeypatch):
    from . import v4_sources,storage
    h=harness;monkeypatch.setattr(v4_sources,'now',lambda:h.clock[0])
    with h.sessions.begin() as db:
        row=db.get(h.W,h.wid);state=storage.load(db,h.B,row)
        state['source_case_baseline']={'version':1,'cutover_at':'2026-09-26T00:00:00+08:00',
            'snapshot_at':'2026-09-26T00:00:00+08:00','sync_revision':1,'source_tables':[['','confirmation']],
            'record_ids':[],'case_codes':[]}
        for project in state['projects']:project['case_visibility']='new_case'
        row.data=storage.save(db,h.B,h.wid,state)
    def fresh_rows():
        result=records()
        for r in result:r['created_time']='2026-09-27T09:00:00+08:00'
        return result
    h.service.fetcher=lambda _:snapshot(h.clock[0],fresh_rows())
    h.service.sync(h.wid,'u-manager');before=deepcopy(h.read()[0]['projects'][0])
    h.clock[0]='2026-09-27T10:06:00+08:00'
    h.service.sync(h.wid,'u-manager');after=h.read()[0]['projects'][0]
    assert after['source_changed_at']==before['source_changed_at']
    assert after['concurrency_version']==before['concurrency_version']
    rows=fresh_rows();rows[0]['fields']['工程名稱']='Changed source name'
    h.service.fetcher=lambda _:snapshot(h.clock[0],rows)
    h.service.sync(h.wid,'u-manager');changed=h.read()[0]['projects'][0]
    assert changed['source_changed_at']==h.clock[0]
    assert changed['concurrency_version']==after['concurrency_version']+1
