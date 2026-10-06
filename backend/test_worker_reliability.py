"""Fresh authority and uncertain remote results must fail closed."""
from copy import deepcopy
from datetime import datetime,timezone
from types import SimpleNamespace
import pytest
from . import storage, jobs, learning_sources
from .jobs import Worker
from .learning_sources import approval_is_fresh, approval_in_period, leave_refresh_due, LEAVE_DEFINITION, DELEGATE_FIELD
from .lark_adapter import RemoteFailure
from .source_case_policy import SOURCE_REFERENCE_POLICY, identity
from .test_source_sync import harness


def approval(verified='2026-09-27T09:59:00+08:00',status='APPROVED'):
    return {'id':'instance123','approval_code':LEAVE_DEFINITION,'principal_id':'ou_principal','delegate_id':'ou_delegate','status':status,'verified_at':verified,'from':'2026-09-27T10:00:00+08:00','to':'2026-09-27T17:00:00+08:00'}


@pytest.mark.parametrize('verified,valid',[
    ('2026-09-27T09:55:00+08:00',True),
    ('2026-09-27T09:54:59+08:00',False),
    ('2026-09-27T10:00:01+08:00',False),
    ('2026-09-27T10:00:00',False),
    ('broken',False),(None,False),
])
def test_approval_cache_has_five_minute_maximum_and_rejects_bad_clocks(verified,valid):
    assert approval_is_fresh(approval(verified),'2026-09-27T10:00:00+08:00') is valid


@pytest.mark.parametrize('status',['UNKNOWN','CANCELED','REJECTED','DELETED','PENDING'])
def test_nonapproved_status_never_authorizes_even_with_recent_server_check(status):
    assert not approval_is_fresh(approval(status=status),'2026-09-27T10:00:00+08:00')


def test_actual_leave_time_is_not_expanded_to_entire_calendar_day():
    item=approval('2026-09-27T09:55:00+08:00')
    assert not approval_in_period(item,'2026-09-27T09:59:00+08:00')
    assert approval_in_period(item,'2026-09-27T10:00:00+08:00')
    item['verified_at']='2026-09-27T17:00:00+08:00'
    assert not approval_in_period(item,'2026-09-27T17:00:01+08:00')


def save(h,state):
    with h.sessions.begin() as db:
        row=db.get(h.W,h.wid); row.data=storage.save(db,h.B,h.wid,state); row.version=state['version']


def test_production_worker_never_sends_for_stale_directory_actor(harness,tmp_path):
    from .operations import queue
    h=harness;state,_=h.read();state['environment']='production'
    state['settings']['external_enabled']=True
    for project in state['projects']:project['execution_system']='workbench'
    actor=state['users'][0]
    actor.update(active=True,identity_app_id=h.cfg['LARK_APP_ID'],directory_status='employed',
        directory_source={'app_id':h.cfg['LARK_APP_ID'],'record_id':'native-record'},
        directory_last_seen_at='2000-01-01T00:00:00+00:00')
    job=queue(state,'digest',actor,{'recipients':[actor['id']],'text':'must not send'},'stale-directory-test')
    save(h,state);calls=[]
    cfg={**h.cfg,'APP_ENV':'production'}
    worker=Worker(h.sessions,h.W,h.B,h.P,cfg,tmp_path,lambda config:calls.append(config))
    worker.run_one(h.wid)
    after,_=h.read();result=next(x for x in after['jobs'] if x['id']==job['id'])
    assert result['status']=='blocked' and not calls


def worker_with_approval(h,tmp_path,monkeypatch,factory):
    monkeypatch.setattr(jobs,'now',lambda:h.clock[0]); monkeypatch.setattr(learning_sources,'now',lambda:h.clock[0])
    state,_=h.read(); state['approved_leave_delegations']=[approval('2026-09-27T09:55:00+08:00')]
    state['delegations']=[{'id':'d1','source':'approval','status':'active','approval_instance_id':'instance123','end_date':'2026-09-28'}]
    save(h,state)
    return Worker(h.sessions,h.W,h.B,h.P,h.cfg,tmp_path,adapter_factory=factory)


def native_reply(status='APPROVED'):
    return {'approval_code':LEAVE_DEFINITION,'instance_code':'instance123','open_id':'ou_principal','status':status,'form':[
        {'id':DELEGATE_FIELD,'value':{'open_ids':['ou_delegate']}},
        {'id':'widgetLeaveGroupStartTime','value':'2026-09-27T10:00:00+08:00'},
        {'id':'widgetLeaveGroupEndTime','value':'2026-09-27T17:00:00+08:00'},
    ]}


@pytest.mark.parametrize('status',['APPROVED','CANCELED'])
def test_worker_readonly_refresh_uses_tenant_endpoint_and_observes_revocation(harness,tmp_path,monkeypatch,status):
    h=harness; calls=[]
    def request(method,path,**kwargs): calls.append((method,path)); return native_reply(status)
    adapter=SimpleNamespace(request=request,client=SimpleNamespace(close=lambda:None))
    worker=worker_with_approval(h,tmp_path,monkeypatch,lambda cfg:adapter)
    worker.refresh_delegations(h.wid)
    state,_=h.read(); cached=state['approved_leave_delegations'][0]
    assert calls==[('GET','/approval/v4/instances/instance123')]
    assert cached['verified_at']==h.clock[0] and cached['status']==status
    assert approval_is_fresh(cached,h.clock[0]) is (status=='APPROVED')
    worker.refresh_delegations(h.wid); assert len(calls)==1


def test_application_permission_failure_immediately_removes_cached_authority(harness,tmp_path,monkeypatch):
    h=harness; calls=[]
    def factory(cfg): calls.append(True); raise RemoteFailure('Lark 拒絕請求（99991672）','blocked')
    worker=worker_with_approval(h,tmp_path,monkeypatch,factory)
    worker.refresh_delegations(h.wid); state,_=h.read(); cached=state['approved_leave_delegations'][0]
    assert cached['status']=='UNKNOWN' and cached['verified_at'] is None
    assert cached['last_verified_at']=='2026-09-27T09:55:00+08:00'
    assert not approval_is_fresh(cached,h.clock[0])
    h.clock[0]='2026-09-27T10:00:30+08:00'; worker.refresh_delegations(h.wid); assert len(calls)==1
    h.clock[0]='2026-09-27T10:01:00+08:00'; worker.refresh_delegations(h.wid); assert len(calls)==2


def test_broken_form_or_wrong_definition_cannot_keep_previous_approved_cache(harness,tmp_path,monkeypatch):
    h=harness
    adapter=SimpleNamespace(request=lambda *a,**k:{**native_reply(),'approval_code':'wrong'},client=SimpleNamespace(close=lambda:None))
    worker=worker_with_approval(h,tmp_path,monkeypatch,lambda cfg:adapter); worker.refresh_delegations(h.wid)
    assert h.read()[0]['approved_leave_delegations'][0]['status']=='UNKNOWN'


def test_test_environment_never_refreshes_real_approvals(harness,tmp_path,monkeypatch):
    h=harness
    worker=worker_with_approval(h,tmp_path,monkeypatch,lambda cfg:pytest.fail('Test workspace requested a tenant token'))
    state,_=h.read(); state['environment']='test'; save(h,state)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:worker.refresh_delegations(h.wid)
    assert error.value.status_code==409
    assert h.read()[0]['approved_leave_delegations'][0]['verified_at']=='2026-09-27T09:55:00+08:00'


def test_background_refresh_does_not_overwrite_newer_manual_revocation(harness,tmp_path,monkeypatch):
    h=harness
    def request(*args,**kwargs):
        state,_=h.read(); state['approved_leave_delegations'][0].update(status='CANCELED',verified_at='2026-09-27T10:00:01+08:00'); save(h,state)
        return native_reply()
    adapter=SimpleNamespace(request=request,client=SimpleNamespace(close=lambda:None))
    worker=worker_with_approval(h,tmp_path,monkeypatch,lambda cfg:adapter); worker.refresh_delegations(h.wid)
    assert h.read()[0]['approved_leave_delegations'][0]['status']=='CANCELED'


@pytest.mark.parametrize('kind',['training_record','capability'])
def test_expired_learning_lease_is_blocked_without_remote_retry(harness,tmp_path,kind):
    h=harness; state,_=h.read(); plan={'id':'plan1','version':1,'award_id':'award1','record_sync_status':'queued','remote_status':'queued'}
    state['training_plans']=[plan]
    state['capability_awards']=[{'id':'award1','training_id':'plan1','training_version':1,'remote_status':'queued'}]
    payload={'training_id':'plan1','version':1} if kind=='training_record' else {'award_id':'award1'}
    state['jobs']=[{'id':'job1','kind':kind,'payload':payload,'status':'running','lease_until':'2020-01-01T00:00:00+08:00'}]
    save(h,state); worker=Worker(h.sessions,h.W,h.B,h.P,h.cfg,tmp_path,adapter_factory=lambda cfg:pytest.fail('Expired job was retried'))
    assert worker.run_one(h.wid) is None
    state,_=h.read(); assert state['jobs'][0]['status']=='blocked'
    field='record_sync_status' if kind=='training_record' else 'remote_status'
    assert state['training_plans'][0][field]=='blocked'
    if kind=='capability': assert state['capability_awards'][0]['remote_status']=='blocked'


def test_old_training_or_award_failure_does_not_revert_newer_plan_status(harness,tmp_path):
    h=harness; state,_=h.read()
    state['training_plans']=[{'id':'plan1','version':2,'award_id':'award2','record_sync_status':'verified','remote_status':'verified'}]
    state['capability_awards']=[{'id':'award1','training_id':'plan1','training_version':1,'remote_status':'queued'}]
    state['jobs']=[{'id':'job1','kind':'training_record','payload':{'training_id':'plan1','version':1},'status':'running','lease_until':'2020-01-01T00:00:00+08:00'},
                   {'id':'job2','kind':'capability','payload':{'award_id':'award1'},'status':'running','lease_until':'2020-01-01T00:00:00+08:00'}]
    save(h,state); worker=Worker(h.sessions,h.W,h.B,h.P,h.cfg,tmp_path)
    worker.run_one(h.wid); state,_=h.read()
    assert all(j['status']=='blocked' for j in state['jobs'])
    assert state['training_plans'][0]['record_sync_status']==state['training_plans'][0]['remote_status']=='verified'


def notification_job(h,kind):
    from .operations import queue
    state,_=h.read();actor=next(u for u in state['users'] if u['id']=='u-manager')
    app_id=h.cfg['LARK_APP_ID']
    actor.update(identity_app_id=app_id,directory_status='employed',directory_missing=False,
        directory_source={'app_id':app_id,'record_id':'manager-roster'},
        directory_last_seen_at=datetime.now(timezone.utc).isoformat())
    state['settings']['external_enabled']=True
    p=state['projects'][0];p.update(execution_system='workbench',case_visibility='new_case')
    recipients=['u-manager','u-pm']
    if kind=='confirmation':
        p['issuer_ids']=[actor['id']]
        p['evidence'].append({'id':'confirmation-evidence','key':'confirmation','status':'accepted'})
        issue={'id':'issue-37','version':'1','status':'queued','pm_id':p['pm_id'],
            'evidence_id':'confirmation-evidence','recipients':recipients,'fingerprint':'fixture'}
        p['confirmation_issues'].append(issue)
        payload={'project_id':p['id'],'issue_id':issue['id'],'recipients':recipients,'text':'confirmation'}
    else:
        payload={'recipients':recipients,'text':'digest','source_project_ids':[p['id']],'source_scope':'case_digest_v1'}
    job=queue(state,kind,actor,payload,'issue-37:'+kind)
    with h.sessions.begin() as db:
        row=db.get(h.W,h.wid);row.data=storage.save(db,h.B,h.wid,state)
        db.get(h.P,(h.wid,actor['id'])).data=deepcopy(actor)
    return job,actor,recipients


def notification_worker(h,tmp_path,message):
    adapter=SimpleNamespace(message=message,client=SimpleNamespace(close=lambda:None))
    return Worker(h.sessions,h.W,h.B,h.P,h.cfg,tmp_path,adapter_factory=lambda _:adapter)


def saved_job(h,job):
    return next(j for j in h.read()[0]['jobs'] if j['id']==job['id'])


@pytest.mark.parametrize('kind',['digest','confirmation'])
def test_notification_receipt_checkpoint_failure_is_quarantined(harness,tmp_path,monkeypatch,kind):
    from .operations import apply_operation
    from fastapi import HTTPException
    h=harness;job,actor,recipients=notification_job(h,kind);sent=[]
    worker=notification_worker(h,tmp_path,lambda recipient,*_:sent.append(recipient) or {'message_id':'msg-'+recipient})
    original=worker.checkpoint;failed=[]
    def fail_after_remote(*args,**kwargs):
        if not failed:
            failed.append(True)
            raise RuntimeError('checkpoint failed after remote message accepted')
        return original(*args,**kwargs)
    monkeypatch.setattr(worker,'checkpoint',fail_after_remote)
    worker.run_one(h.wid)
    state,_=h.read();saved=saved_job(h,job)
    assert sent==[recipients[0]] and saved['status']=='outcome_unknown' and not saved['steps']
    with pytest.raises(HTTPException) as error:
        apply_operation(state,actor,{'action':'job_retry','payload':{'id':job['id']}},False)
    assert error.value.status_code==409
    # A restarted Worker finds nothing runnable and sends nothing.
    notification_worker(h,tmp_path,lambda recipient,*_:sent.append(recipient) or {}).run_one(h.wid)
    assert sent==[recipients[0]] and saved_job(h,job)['status']=='outcome_unknown'


@pytest.mark.parametrize('kind',['digest','confirmation'])
def test_notification_network_exception_after_attempt_is_quarantined(harness,tmp_path,kind):
    h=harness;job,_,recipients=notification_job(h,kind);calls=[]
    def message(recipient,*_):
        calls.append(recipient);raise RuntimeError('connection reset while sending')
    notification_worker(h,tmp_path,message).run_one(h.wid)
    saved=saved_job(h,job)
    assert calls==[recipients[0]] and saved['status']=='outcome_unknown' and not saved['steps'],saved
    notification_worker(h,tmp_path,message).run_one(h.wid)
    assert calls==[recipients[0]]


@pytest.mark.parametrize('kind',['digest','confirmation'])
def test_notification_retry_and_restart_resume_only_unreceipted_recipients(harness,tmp_path,kind):
    from .operations import apply_operation
    h=harness;job,actor,recipients=notification_job(h,kind);sent=[]
    def flaky(recipient,*_):
        if recipient==recipients[1] and sent.count(recipient)==0 and len(sent)==1:
            sent.append('refused:'+recipient);raise RemoteFailure('remote refused before accepting','failed')
        sent.append(recipient);return {'message_id':'msg-'+recipient}
    notification_worker(h,tmp_path,flaky).run_one(h.wid)
    state,_=h.read();saved=saved_job(h,job)
    assert saved['status']=='failed' and [s['key'] for s in saved['steps']]==[recipients[0]]
    apply_operation(state,actor,{'action':'job_retry','payload':{'id':job['id']}},False)
    with h.sessions.begin() as db:
        row=db.get(h.W,h.wid);row.data=storage.save(db,h.B,h.wid,state)
    notification_worker(h,tmp_path,flaky).run_one(h.wid)  # new Worker simulates a restart
    saved=saved_job(h,job)
    assert sent==[recipients[0],'refused:'+recipients[1],recipients[1]]
    assert saved['status']=='succeeded' and [s['key'] for s in saved['steps']]==recipients
