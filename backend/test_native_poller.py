from copy import deepcopy
import pytest
from .test_native_routes import api,operate
from .test_source_sync import harness
from .native_poller import NativeApprovalPoller
from . import native_poller,storage


def test_independent_admin_grant_revocation_keeps_polling_but_blocks_business(api,monkeypatch):
    import json
    from datetime import datetime,timezone,timedelta
    poller,clock=make(api,monkeypatch);stamp=(datetime.now(timezone.utc)-timedelta(seconds=10)).isoformat()
    grant={'grant_id':'independent','open_id':'ou_pm','app_id':'app1','tenant':'tenant','role':'manager',
           'enabled':True,'authorized_at':stamp,'authorized_by':'owner','reason':'Explicit approval','decision_ref':'approved'}
    api.h.cfg['LARK_COMPANY_ADMIN_GRANTS_JSON']=json.dumps([grant])
    def make_independent(state):
        p=next(u for u in state['users'] if u['id']=='ou_pm')
        p.pop('directory_source');p.pop('directory_status')
        p.update(role='manager',bootstrap_admin=True,oauth_identity={'source':'oauth_user_info',
            'open_id':'ou_pm','app_id':'app1','tenant':'tenant','verified_at':stamp})
    mutate(api,make_independent);api.external[0]='APPROVED'
    poller.run_due(api.h.wid)
    assert api.h.read()[0]['approvals'][0]['native_receipt']['applicable'] is True
    api.h.cfg['LARK_COMPANY_ADMIN_GRANTS_JSON']='[]';clock[0]='2026-09-28T12:05:00+08:00';before=len(api.calls)
    poller.run_due(api.h.wid)
    item=api.h.read()[0]['approvals'][0]
    assert item['native_observation']['external_status']=='APPROVED' and not item['native_receipt']['applicable']
    assert api.calls[before:] and all(method=='GET' for method,_ in api.calls[before:])


def make(api,monkeypatch):
    assert operate(api,'prepare').status_code==200
    assert operate(api,'submit').status_code==200
    clock=['2026-09-28T12:00:00+08:00'];monkeypatch.setattr(native_poller,'now',lambda:clock[0])
    h=api.h
    return NativeApprovalPoller(h.sessions,h.W,h.B,h.P,h.cfg,api.adapter_factory),clock


def mutate(api,callback):
    h=api.h
    with h.sessions.begin() as db:
        row=db.get(h.W,h.wid);state=storage.load(db,h.B,row);callback(state);row.data=storage.save(db,h.B,h.wid,state)


def test_background_poll_only_gets_and_throttles_and_observes_cancellation(api,monkeypatch):
    poller,clock=make(api,monkeypatch);start=len(api.calls);api.external[0]='APPROVED'
    assert poller.run_due(api.h.wid)==[{'id':'request','status':'observed'}]
    state,_=api.h.read();item=state['approvals'][0]
    assert item['native_receipt']['approved'] and item['native_observation']['external_status']=='APPROVED'
    assert poller.run_due(api.h.wid)==[]
    clock[0]='2026-09-28T12:05:00+08:00';api.external[0]='CANCELED'
    poller.run_due(api.h.wid);item=api.h.read()[0]['approvals'][0]
    assert item['status']=='withdrawn' and not item['native_receipt']['approved']
    assert all(method=='GET' for method,_ in api.calls[start:])


@pytest.mark.parametrize('changed',['disabled','scope'])
def test_disabled_applicant_or_new_scope_still_observes_original_without_authorizing(api,monkeypatch,changed):
    poller,_=make(api,monkeypatch);api.external[0]='APPROVED';start=len(api.calls)
    def change(state):
        if changed=='disabled':state['users'][0]['active']=False
        else:state['projects'][0]['revision']+=1
    mutate(api,change)
    poller.run_due(api.h.wid);state,_=api.h.read();item=state['approvals'][0]
    assert item['native_observation']['external_status']=='APPROVED'
    assert item['native_receipt']['applicable'] is False
    assert all(method=='GET' for method,_ in api.calls[start:])


def test_current_cfg_authority_rotation_blocks_old_company_reads(api,monkeypatch):
    poller,_=make(api,monkeypatch);start=len(api.calls)
    api.h.cfg['LARK_APP_ID']='new-app'
    result=poller.run_due(api.h.wid);state,_=api.h.read()
    assert result[0]['status']=='error' and api.calls[start:]==[]
    assert state['native_approval_authority']['app_id']=='new-app'
    assert not state['approvals'][0]['native_receipt']['approved']


def test_no_prepared_or_test_workspace_request_can_be_submitted_by_worker(api,monkeypatch):
    assert operate(api,'prepare').status_code==200
    h=api.h;poller=NativeApprovalPoller(h.sessions,h.W,h.B,h.P,h.cfg,api.adapter_factory)
    start=len(api.calls)
    assert poller.run_due(h.wid)==[] and poller.run_due('test-'+h.wid)==[]
    assert api.calls[start:]==[]


def test_temporary_poll_failure_preserves_historical_receipt_without_refreshing_it(api,monkeypatch):
    poller,clock=make(api,monkeypatch);api.external[0]='APPROVED'
    assert poller.run_due(api.h.wid)==[{'id':'request','status':'observed'}]
    before=deepcopy(api.h.read()[0]['approvals'][0]['native_receipt'])
    clock[0]='2026-09-28T12:05:00+08:00'
    def unavailable(cfg):raise TimeoutError('network unavailable')
    poller.adapter_factory=unavailable
    assert poller.run_due(api.h.wid)==[{'id':'request','status':'error'}]
    item=api.h.read()[0]['approvals'][0]
    assert item['native_receipt']==before
    assert item['native_binding']['verification_failed_at']==clock[0]
    assert item['native_poll_status']['status']=='error'
    assert item['status']=='approved'
    from .native_requests import receipt_valid
    state,_=api.h.read();p=next(p for p in state['projects'] if p['id']==item['project_id'])
    n=next(n for n in p['nodes'] if n['id']==item['node_id'])
    assert not receipt_valid(state,p,n,item,require_fresh=True)


def test_batch_overflow_polls_every_attempted_request_in_bounded_rounds(api,monkeypatch):
    poller,clock=make(api,monkeypatch)
    def clone(state):
        base=state['approvals'][0]
        for n in range(1,13):state['approvals'].append(dict(deepcopy(base),id='extra%d'%n))
    mutate(api,clone);seen=set()
    for n in range(3):
        clock[0]='2026-09-28T12:%02d:00+08:00'%(n*5)
        got=poller.run_due(api.h.wid);assert len(got)<=10
        seen.update(r['id'] for r in got)
    assert seen=={'request'}|{'extra%d'%n for n in range(1,13)}
