import json
from datetime import datetime,timezone
from copy import deepcopy
import pytest
from .test_source_sync import harness
from .test_input_registration import Fake,is_write
from .input_registration import make_plan,FIELD_NAMES
from .operations import queue
from .jobs import Worker
from . import storage


def prepared_input_job(h):
    """Queue one formal append_registration job in the harness; returns (revision,fields)."""
    state,_=h.read();p=state['projects'][0];n=p['nodes'][0];p['execution_system']='workbench'
    fields={k:{'field_id':'fld'+k,'field_name':v} for k,v in FIELD_NAMES.items()}
    destination={'base_token':'dedicated','table_id':'table','fields':fields}
    state['settings'].update(external_enabled=True,input_base='dedicated',input_table='table')
    revision={'id':'i','mapping_id':'m','project_id':p['id'],'node_id':n['id'],'actor_id':'u-manager',
              'created_at':'2026-09-29','value':'成果','status':'queued'}
    revision['registration_plan']=make_plan(h.wid,p,n,revision,destination)
    state['input_revisions']=[revision]
    state['input_mappings']=[dict(id='m',project_id=p['id'],node_id=n['id'],enabled=True,
        verified=False,mode='append_registration',**destination)]
    actor=next(u for u in state['users'] if u['id']=='u-manager')
    p['pm_id']=actor['id']; n['owner_id']=actor['id']
    actor.update(directory_status='employed',directory_missing=False,
        directory_source={'app_id':h.cfg['LARK_APP_ID'],'record_id':'input-worker-roster'},
        directory_last_seen_at=datetime.now(timezone.utc).isoformat())
    queue(state,'input',actor,{'input_id':'i','mapping_id':'m','project_id':p['id']},'input:i')
    with h.sessions.begin() as db:
        row=db.get(h.W,h.wid);row.data=storage.save(db,h.B,h.wid,state)
        db.get(h.P,(h.wid,actor['id'])).data=deepcopy(actor)
    h.cfg.update(LARK_INPUT_BASE_TOKEN='dedicated',LARK_INPUT_TABLE_ID='table',
                 LARK_INPUT_REGISTRATION_FIELDS_JSON=json.dumps(fields))
    return revision,fields


@pytest.mark.parametrize('unknown',[False,True])
def test_formal_worker_uses_append_registration_and_preserves_unknown(harness,tmp_path,unknown):
    h=harness;revision,fields=prepared_input_job(h)
    fake=Fake(revision['registration_plan']);fake.timeout=unknown;fake.lost=unknown
    class Client:
        def close(self):pass
    fake.client=Client()
    worker=Worker(h.sessions,h.W,h.B,h.P,h.cfg,tmp_path,adapter_factory=lambda cfg:fake)
    worker.run_one(h.wid)
    result=h.read()[0];saved=result['input_revisions'][0]
    assert saved['status']==('outcome_unknown' if unknown else 'succeeded')
    assert sum(map(is_write,fake.calls))==1 and all(c[0]!='PUT' for c in fake.calls)
    if not unknown:assert saved['receipt']['operation']=='append_registration'
    else:
        previous=deepcopy(fake.calls);worker.run_one(h.wid)
        assert fake.calls==previous


def http_worker(h,tmp_path,lark):
    import httpx
    from .lark_adapter import LarkAdapter
    # The worker closes its client after every run, so each run gets a fresh one on the shared simulator.
    return Worker(h.sessions,h.W,h.B,h.P,h.cfg,tmp_path,
                  adapter_factory=lambda cfg:LarkAdapter('t',client=httpx.Client(transport=httpx.MockTransport(lark.handle))))


def force_due(h):
    state,_=h.read()
    for j in state['jobs']:j['next_attempt_at']='2000-01-01T00:00:00+00:00'
    with h.sessions.begin() as db:
        row=db.get(h.W,h.wid);row.data=storage.save(db,h.B,h.wid,state)


def test_worker_rate_limit_requeues_with_backoff_then_writes_exactly_once(harness,tmp_path):
    from .test_input_recovery import Lark
    h=harness;revision,_=prepared_input_job(h);lark=Lark(revision['registration_plan'])
    lark.fault('POST','/records',429);lark.created_on_fault=False
    worker=http_worker(h,tmp_path,lark);worker.run_one(h.wid)
    state=h.read()[0];job=state['jobs'][0]
    assert job['status']=='queued' and job['attempts']==1 and state['input_revisions'][0]['status']=='queued'
    assert job['next_attempt_at']>datetime.now(timezone.utc).isoformat()[:19]
    count=len(lark.requests);worker.run_one(h.wid);assert len(lark.requests)==count  # not due yet: no resend
    force_due(h);worker.run_one(h.wid)
    state=h.read()[0]
    assert state['jobs'][0]['status']=='succeeded'
    assert state['input_revisions'][0]['status']=='succeeded' and len(lark.writes)==2 and len(lark.rows)==1
    assert {r[2]['client_token'] for r in lark.writes}=={revision['registration_plan']['client_token']}


def test_worker_rate_limit_is_bounded_and_ends_failed_without_extra_writes(harness,tmp_path):
    from .test_input_recovery import Lark
    h=harness;revision,_=prepared_input_job(h);lark=Lark(revision['registration_plan'])
    lark.fault('GET','/fields',*[429]*10)
    worker=http_worker(h,tmp_path,lark)
    for _ in range(8):
        worker.run_one(h.wid);force_due(h)
    state=h.read()[0]
    assert state['jobs'][0]['status']=='failed' and state['jobs'][0]['attempts']==5
    assert state['input_revisions'][0]['status']=='failed' and not lark.writes


@pytest.mark.parametrize('outcome,job_status',[(403,'blocked'),(422,'blocked'),(500,'succeeded'),(503,'outcome_unknown')])
def test_worker_http_errors_leave_record_state_recoverable(harness,tmp_path,outcome,job_status):
    from .test_input_recovery import Lark
    h=harness;revision,_=prepared_input_job(h);lark=Lark(revision['registration_plan'])
    lark.fault('POST','/records',outcome);lark.created_on_fault=outcome==500
    http_worker(h,tmp_path,lark).run_one(h.wid)
    state=h.read()[0]
    assert state['jobs'][0]['status']==job_status
    # 500 with a lost response but a real row: the read-back verifies it without a resend.
    assert state['input_revisions'][0]['status']==job_status
    assert len(lark.writes)==1


def test_local_receipt_save_failure_after_verified_write_becomes_unknown_not_blocked(harness,tmp_path):
    from .test_input_recovery import Lark
    h=harness;revision,_=prepared_input_job(h);lark=Lark(revision['registration_plan'])
    worker=http_worker(h,tmp_path,lark);real=worker.checkpoint
    def flaky(wid,jid,token,mutate):
        if len(lark.writes) and not getattr(flaky,'failed',False) and mutate.__name__=='finish':
            flaky.failed=True;raise RuntimeError('db down')
        return real(wid,jid,token,mutate)
    worker.checkpoint=flaky;worker.run_one(h.wid)
    state=h.read()[0]
    assert state['jobs'][0]['status']=='outcome_unknown' and state['input_revisions'][0]['status']=='outcome_unknown'
    count=len(lark.requests);worker.run_one(h.wid);assert len(lark.requests)==count and len(lark.writes)==1
