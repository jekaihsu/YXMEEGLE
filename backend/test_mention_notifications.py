"""Durable mention notifications; mock remote boundary, never sends real messages."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from . import storage
from .jobs import Worker
from .workflow import apply_action,now
from .operations import apply_operation
from .lark_adapter import RemoteFailure
from .test_source_sync import harness


def save(h,state):
    with h.sessions.begin() as db:
        row=db.get(h.W,h.wid); row.data=storage.save(db,h.B,h.wid,state); row.version=state['version']
        for user in state['users']:
            profile=db.get(h.P,(h.wid,user['id']))
            if profile: profile.data=deepcopy(user)


def arrange(h,test=False):
    state,_=h.read(); state['environment']='test' if test else 'production'; state['settings']['external_enabled']=True
    for user in state['users']: user.update(identity_app_id='app1',directory_status='employed',directory_last_seen_at=now(),directory_source={'app_id':'app1','record_id':'rec-'+user['id']},active=True)
    state['people_directory_status']={'app_id':'app1'}
    user=next(u for u in state['users'] if u['id']=='u-manager'); p=state['projects'][0]
    p['execution_system']='workbench'
    apply_action(state,user,dict(action='comment_add',project_id=p['id'],payload={'body':'請核對成果','mentions':['u-pm','u-pm']}),test)
    save(h,state); return state


def worker(h,tmp_path,send):
    cfg={**h.cfg,'LARK_REDIRECT_URI':'https://work.example/api/auth/lark/callback'}
    adapter=SimpleNamespace(message=send,client=SimpleNamespace(close=lambda:None))
    return Worker(h.sessions,h.W,h.B,h.P,cfg,tmp_path,adapter_factory=lambda _:adapter)


def test_formal_mention_one_recipient_one_receipt_and_deep_link(harness,tmp_path):
    h=harness; state=arrange(h); calls=[]
    def send(recipient,text,identifier): calls.append((recipient,text,identifier)); return {'message_id':'om_test','recipient':recipient}
    w=worker(h,tmp_path,send); w.run_one(h.wid); w.run_one(h.wid)
    after,_=h.read(); comment=after['projects'][0]['comments'][-1]
    assert len(calls)==1 and calls[0][0]=='u-pm'
    assert 'https://work.example/#view=project' in calls[0][1] and 'comment='+comment['id'] in calls[0][1]
    assert '/api/auth/' not in calls[0][1] and len(calls[0][2])==32
    assert comment['notifications'][0]['status']=='succeeded' and comment['notifications'][0]['message_id']=='om_test'
    assert comment['notifications'][0]['simulated'] is False


def test_isolated_mention_has_explicit_simulated_status_and_zero_adapter(harness,tmp_path):
    h=harness; arrange(h,True)
    test_wid='test-'+h.wid
    with h.sessions.begin() as db:
        state=storage.load(db,h.B,db.get(h.W,h.wid))
        row=h.W(id=test_wid,version=state['version'],data={});db.add(row);db.flush()
        row.data=storage.save(db,h.B,test_wid,state)
    w=Worker(h.sessions,h.W,h.B,h.P,h.cfg,tmp_path,adapter_factory=lambda _:pytest.fail('Test mention called real adapter'))
    w.run_one(test_wid)
    with h.sessions() as db:notice=storage.load(db,h.B,db.get(h.W,test_wid))['projects'][0]['comments'][-1]['notifications'][0]
    assert notice['status']=='simulated' and notice['simulated'] is True


@pytest.mark.parametrize('problem',['inactive','wrong_app','missing_directory','not_employed','actor_inactive'])
def test_worker_rechecks_identity_before_remote_io(harness,tmp_path,problem):
    h=harness; state=arrange(h); recipient=next(u for u in state['users'] if u['id']=='u-pm')
    if problem=='inactive': recipient['active']=False
    if problem=='wrong_app': recipient['identity_app_id']='another-app'
    if problem=='missing_directory': recipient['directory_missing']=True
    if problem=='not_employed': recipient['directory_status']='unknown'
    if problem=='actor_inactive': next(u for u in state['users'] if u['id']=='u-manager')['active']=False
    save(h,state)
    w=worker(h,tmp_path,lambda *_:pytest.fail('Unverified recipient was notified')); w.run_one(h.wid)
    after,_=h.read(); assert after['jobs'][0]['status']=='blocked'
    assert after['projects'][0]['comments'][-1]['notifications'][0]['status']=='blocked'


def test_uncertain_delivery_is_never_blindly_retried(harness,tmp_path):
    h=harness; arrange(h); calls=[]
    def send(*_): calls.append(True); raise RemoteFailure('已送出但回應遺失','outcome_unknown')
    w=worker(h,tmp_path,send); w.run_one(h.wid); w.run_one(h.wid)
    state,_=h.read(); assert len(calls)==1 and state['jobs'][0]['status']=='outcome_unknown'
    actor=next(u for u in state['users'] if u['id']=='u-manager')
    with pytest.raises(HTTPException): apply_operation(state,actor,{'action':'job_retry','payload':{'id':state['jobs'][0]['id']}},False)


def test_remote_receipt_then_checkpoint_conflict_is_unknown_not_retryable(harness,tmp_path,monkeypatch):
    h=harness; arrange(h); calls=[]
    def send(*_): calls.append(True); return {'message_id':'om_real'}
    w=worker(h,tmp_path,send); original=w.checkpoint; attempts=[]
    def checkpoint(*args):
        attempts.append(True)
        if len(attempts)==1: raise HTTPException(409,'version conflict after remote effect')
        return original(*args)
    monkeypatch.setattr(w,'checkpoint',checkpoint)
    w.run_one(h.wid); w.run_one(h.wid)
    state,_=h.read(); assert len(calls)==1 and state['jobs'][0]['status']=='outcome_unknown'
    assert state['projects'][0]['comments'][-1]['notifications'][0]['status']=='outcome_unknown'

def test_unparseable_remote_response_is_unknown_not_safe_to_retry(harness,tmp_path):
    h=harness; arrange(h); calls=[]
    def send(*_): calls.append(True); raise ValueError('invalid JSON after HTTP response')
    w=worker(h,tmp_path,send); w.run_one(h.wid); w.run_one(h.wid)
    assert calls==[True] and h.read()[0]['jobs'][0]['status']=='outcome_unknown'
