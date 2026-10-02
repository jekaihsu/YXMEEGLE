"""Task authority is computed by the server; roster changes do not rewrite history."""
from copy import deepcopy
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from .seed import seed
from .policy import upgrade
from .workflow import apply_action, now
from .workspace_projection import public_copy, filter_private_workspace


@pytest.fixture
def ws():
    return upgrade(seed())


def task(state, ident='p1-control-t1'):
    return next(t for p in state['projects'] for n in p['nodes'] for t in n['tasks'] if t['id']==ident)


def user(state, ident):
    return next(u for u in state['users'] if u['id']==ident)


def project(state, ident):
    return filter_private_workspace(public_copy(state),user(state,ident))


def delegate(state):
    clock=datetime.fromisoformat(now()); start=(clock-timedelta(days=1)).isoformat(); end=(clock+timedelta(days=1)).isoformat()
    state['approved_leave_delegations']=[{'id':'leave','principal_id':'u-control','delegate_id':'u-agent',
        'status':'APPROVED','from':start,'to':end,'verified_at':clock.isoformat()}]
    state['delegations']=[{'id':'delegation','principal_id':'u-control','delegate_id':'u-agent','project_id':'p1',
        'seat':'owner','scope':'tasks','task_ids':['p1-control-t1'],'start_date':start[:10],'end_date':end[:10],
        'status':'active','source':'approval','approval_instance_id':'leave','qualified':True,'qualification_evidence':'核實技能'}]


def test_actual_delegate_gets_capability_without_proxy_and_only_for_scoped_task(ws):
    delegate(ws); task(ws).pop('proxy',None)
    public=project(ws,'u-agent')
    assert task(public)['can_execute']
    assert not task(public,'p1-control-t2')['can_execute']
    assert not task(public,'p2-control-t1')['can_execute']
    assert public['task_capabilities_checked_at']
    assert 'can_execute' not in task(ws)
    apply_action(ws,user(ws,'u-agent'),{'action':'task_complete','project_id':'p1',
        'task_id':'p1-control-t1','payload':{'output':'有效代理人交付'}},True)
    assert task(ws)['status']=='completed'


@pytest.mark.parametrize('change',['stale','revoked','unknown','outside_period','inactive_delegate','inactive_owner','unqualified'])
def test_stale_revoked_or_invalid_delegation_is_not_executable(ws,change):
    delegate(ws); approval=ws['approved_leave_delegations'][0]
    if change=='stale': approval['verified_at']=(datetime.fromisoformat(now())-timedelta(minutes=6)).isoformat()
    elif change=='revoked': approval['status']='CANCELED'
    elif change=='unknown': approval['status']='UNKNOWN'
    elif change=='outside_period': approval['to']=(datetime.fromisoformat(now())-timedelta(hours=1)).isoformat()
    elif change=='inactive_delegate': user(ws,'u-agent')['active']=False
    elif change=='inactive_owner': user(ws,'u-control')['active']=False
    else: ws['delegations'][0]['qualified']=False
    # Legacy proxy fields and client/stored booleans are not authority.
    task(ws)['proxy']={'user_id':'u-agent','start_date':'2000-01-01','end_date':'2099-01-01'}
    task(ws)['can_execute']=True
    assert not task(project(ws,'u-agent'))['can_execute']
    with pytest.raises(HTTPException) as exc:
        apply_action(ws,user(ws,'u-agent'),{'action':'task_complete','project_id':'p1',
            'task_id':'p1-control-t1','payload':{'output':'無效代理嘗試','can_execute':True}},True)
    assert exc.value.status_code==403


def test_pm_manager_not_automatically_owner_and_client_flag_cannot_execute(ws):
    assert task(project(ws,'u-control'))['can_execute']
    for ident in ('u-pm','u-manager'):
        assert not task(project(ws,ident))['can_execute']
        with pytest.raises(HTTPException) as exc:
            apply_action(ws,user(ws,ident),{'action':'task_complete','project_id':'p1',
                'task_id':'p1-control-t1','payload':{'can_execute':True,'output':'forged'}},True)
        assert exc.value.status_code==403


def test_unknown_actor_is_fail_closed(ws):
    public=filter_private_workspace(public_copy(ws),{'id':'not-a-member','role':'manager'})
    assert not any(t['can_execute'] for p in public['projects'] for n in p['nodes'] for t in n['tasks'])


@pytest.mark.parametrize('action',['task_update','task_add'])
def test_reassign_or_create_with_inactive_owner_rejected_without_changing_history(ws,action):
    user(ws,'u-agent')['active']=False; before=deepcopy(ws['projects'][0])
    with pytest.raises(HTTPException) as exc:
        apply_action(ws,user(ws,'u-pm'),{'action':action,'project_id':'p1','node_id':'p1-control',
            'task_id':'p1-control-t1' if action=='task_update' else None,
            'payload':{'title':'新工作','owner_id':'u-agent'}},True)
    assert exc.value.status_code==409 and ws['projects'][0]==before


def test_participant_update_validates_all_nodes_and_collaborators_before_mutation(ws):
    user(ws,'u-agent')['active']=False; before=deepcopy(ws['projects'][0])
    for items in ([{'node_id':'p1-control','owner_id':'u-pm'}, {'node_id':'p1-mapping','owner_id':'u-agent'}],
                  [{'node_id':'p1-control','owner_id':'u-control','collaborator_ids':['u-agent']}]):
        with pytest.raises(HTTPException):
            apply_action(ws,user(ws,'u-pm'),{'action':'participants_update','project_id':'p1','payload':{'nodes':items}},True)
        assert ws['projects'][0]==before


def test_existing_disabled_assignment_is_preserved_until_explicit_valid_reassignment(ws):
    user(ws,'u-control')['active']=False
    assert task(ws)['owner_id']=='u-control' and not task(project(ws,'u-control'))['can_execute']
    task(ws,'p1-control-t2')['status']='completed'
    apply_action(ws,user(ws,'u-pm'),{'action':'participants_update','project_id':'p1','payload':{
        'nodes':[{'node_id':'p1-control','owner_id':'u-agent','collaborator_ids':[]}]}},True)
    assert task(ws)['owner_id']=='u-agent'
    assert task(ws,'p1-control-t2')['owner_id']=='u-control'
