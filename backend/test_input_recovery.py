"""Synthetic #11 coverage: error mapping, unknown recovery, paging, rate limits, idempotency.

HTTP level via httpx.MockTransport; no Lark, credentials, .env or production data.
"""
import json
from copy import deepcopy
from uuid import uuid4
import httpx
import pytest
from fastapi import HTTPException
from .input_registration import FIELD_NAMES,RegistrationAdapter,make_plan
from .lark_adapter import LarkAdapter,RemoteFailure
from .test_input_registration import fixture
from .test_input_registration_endpoint import setup,submit,read_raw  # noqa: F401 (fixture)
from . import storage,integration_routes
from .app import AuditRow,BusinessRow,WorkspaceRow
from .test_backend import workspace
from sqlalchemy import select

KEY=FIELD_NAMES['registration_key']


class Lark:
    """Records every request; faults are keyed by (method, path-suffix) with a queue of outcomes."""
    def __init__(self,plan,*,field_pages=1,noise_rows=0,page_size=100):
        self.plan=plan;self.requests=[];self.rows=[];self.faults={};self.field_pages=field_pages
        self.noise_rows=noise_rows;self.created_on_fault=True;self.endless=False;self.repeat_token=False
        fields=[dict(f,type=1) for f in plan['destination']['fields'].values()]
        pad=[{'field_id':f'pad{i}','field_name':f'pad{i}','type':1} for i in range((field_pages-1)*100)]
        self.fields=pad+fields
        self.client=httpx.Client(transport=httpx.MockTransport(self.handle))
    def fault(self,method,suffix,*outcomes):self.faults[(method,suffix)]=list(outcomes)
    @property
    def writes(self):return [r for r in self.requests if r[0]=='POST' and not r[1].endswith('/search')]
    def handle(self,request):
        path=request.url.path.split('/open-apis',1)[1];method=request.method
        params=dict(request.url.params);body=json.loads(request.content) if request.content else None
        self.requests.append((method,path,params,body))
        suffix='/search' if path.endswith('/search') else '/records' if path.endswith('/records') else '/fields'
        queue=self.faults.get((method,suffix))
        outcome=queue.pop(0) if queue else None
        if outcome is not None:
            if method=='POST' and suffix=='/records' and self.created_on_fault:
                self.rows.append({'record_id':'recLost','fields':deepcopy(body['fields'])})
            if isinstance(outcome,Exception):raise outcome
            return httpx.Response(outcome,json={'code':99,'msg':'x'},headers={'Retry-After':'7'} if outcome==429 else {})
        if suffix=='/fields':return self.page(self.fields,params)
        if suffix=='/search':
            key=body['filter']['conditions'][0]['value'][0]
            rows=[r for r in self.rows if r['fields'].get(KEY)==key]
            return self.page(rows,params)
        row={'record_id':'recNew','fields':deepcopy(body['fields'])};self.rows.append(row)
        return httpx.Response(200,json={'code':0,'data':{'record':{'record_id':'recNew'}}})
    def page(self,items,params):
        if self.endless:
            n=len(self.requests)
            return httpx.Response(200,json={'code':0,'data':{'items':[],'has_more':True,'page_token':'same' if self.repeat_token else str(n)}}) 
        size=int(params['page_size']);start=int(params.get('page_token') or 0);chunk=items[start:start+size]
        more=start+size<len(items)
        data={'items':chunk,'has_more':more,'total':len(items)}
        if more:data['page_token']=str(start+size)
        if not items:data.pop('items');data['total']=0
        return httpx.Response(200,json={'code':0,'data':data})
    def adapter(self):return RegistrationAdapter(LarkAdapter('t',client=self.client))


def policy_plan():
    plan,policy=fixture();return plan,policy


# (1) every HTTP error class on the create POST is mapped, never resent in-run
@pytest.mark.parametrize('outcome,status,created',[
    (403,'blocked',False),(422,'blocked',False),(400,'blocked',False),(429,'retry',False),
    (500,'outcome_unknown',True),(503,'outcome_unknown',False),
    (httpx.ReadTimeout('t'),'outcome_unknown',True),(httpx.ConnectError('c'),'outcome_unknown',False)])
def test_create_post_errors_map_without_blind_resend(outcome,status,created):
    plan,policy=policy_plan();lark=Lark(plan);lark.created_on_fault=created
    lark.fault('POST','/records',outcome)
    if created:
        # Lost response after an actual write: only the read-back may confirm it.
        receipt=lark.adapter().submit(plan,policy);assert receipt['record_id']=='recLost'
    elif status=='outcome_unknown':
        with pytest.raises(RemoteFailure) as caught:lark.adapter().submit(plan,policy)
        assert caught.value.status=='outcome_unknown'
    else:
        with pytest.raises(RemoteFailure) as caught:lark.adapter().submit(plan,policy)
        assert caught.value.status==status
        if status=='retry':assert caught.value.retry_after==7
    assert len(lark.writes)==1


@pytest.mark.parametrize('outcome,status',[(500,'failed'),(httpx.ReadTimeout('t'),'failed'),(429,'retry'),(403,'blocked')])
def test_read_failures_before_create_never_write(outcome,status):
    plan,policy=policy_plan()
    for method,suffix in (('GET','/fields'),('POST','/search')):
        lark=Lark(plan);lark.fault(method,suffix,outcome)
        with pytest.raises(RemoteFailure) as caught:lark.adapter().submit(plan,policy)
        expected='failed' if method=='POST' and status=='outcome_unknown' else status
        assert caught.value.status==expected and not lark.writes


def test_search_5xx_on_post_search_is_read_failure_not_unknown_write():
    plan,policy=policy_plan();lark=Lark(plan);lark.fault('POST','/search',500)
    with pytest.raises(RemoteFailure) as caught:lark.adapter().submit(plan,policy)
    assert caught.value.status=='failed' and not lark.writes


def test_unreadable_readback_after_successful_post_stays_unknown_then_reconciles_by_read():
    plan,policy=policy_plan();lark=Lark(plan)
    lark.fault('POST','/search',None,500)  # pre-create search ok, read-back search 5xx
    with pytest.raises(RemoteFailure) as caught:lark.adapter().submit(plan,policy)
    assert caught.value.status=='outcome_unknown' and len(lark.writes)==1
    before=len(lark.writes)
    assert lark.adapter().reconcile(plan,policy)['verified'] and len(lark.writes)==before
    assert lark.adapter().submit(plan,policy)['record_id']=='recNew' and len(lark.writes)==before


def test_non_remote_error_after_post_issued_is_unknown_not_blocked():
    plan,policy=policy_plan();lark=Lark(plan)
    real=lark.client.request
    def guarded(method,url,**kwargs):
        if method=='POST' and url.endswith('/records'):
            real(method,url,**kwargs);raise HTTPException(403,'permission revoked mid-flight')
        return real(method,url,**kwargs)
    lark.client.request=guarded
    with pytest.raises(RemoteFailure) as caught:lark.adapter().submit(plan,policy)
    assert caught.value.status=='outcome_unknown' and len(lark.writes)==1
    assert lark.adapter().reconcile(plan,policy)['verified']


# (3) pagination, large data, rate limit
def test_field_schema_found_on_late_page_of_large_schema():
    plan,policy=policy_plan();lark=Lark(plan,field_pages=3)
    assert lark.adapter().submit(plan,policy)['verified']
    field_calls=[r for r in lark.requests if r[1].endswith('/fields')]
    assert len(field_calls)==6 and all(  # schema check runs for the submit and again for the read-back, 3 pages each
        r[2]['page_size']=='100' for r in field_calls)


def test_large_table_uses_filtered_search_not_full_scan():
    plan,policy=policy_plan();lark=Lark(plan,noise_rows=5000)
    lark.rows=[{'record_id':f'n{i}','fields':{KEY:f'other{i}'}} for i in range(5000)]
    assert lark.adapter().submit(plan,policy)['record_id']=='recNew'
    reads=[r for r in lark.requests if r[0]=='GET' and r[1].endswith('/records')]
    assert not reads and all(r[3]['filter']['conditions'][0]['value']==[plan['values']['registration_key']] for r in lark.requests if r[1].endswith('/search'))
    assert len(lark.requests)<=8


def test_match_on_later_page_found_and_duplicates_across_pages_conflict():
    plan,policy=policy_plan();lark=Lark(plan)
    row={'record_id':'recA','fields':{FIELD_NAMES[k]:v for k,v in plan['values'].items()}}
    lark.rows=[deepcopy(row) for _ in range(150)]  # >1 page of identical keys
    start=len(lark.requests)
    with pytest.raises(RemoteFailure) as caught:lark.adapter().submit(plan,policy)
    assert caught.value.status=='conflict' and not lark.writes
    searches=[r for r in lark.requests[start:] if r[1].endswith('/search')]
    assert len(searches)==1  # stops at first page once a second match is seen


@pytest.mark.parametrize('mode',['endless','repeat'])
def test_runaway_or_looping_pages_block_without_write(mode):
    plan,policy=policy_plan();lark=Lark(plan);lark.endless=True;lark.repeat_token=mode=='repeat'
    with pytest.raises(RemoteFailure) as caught:lark.adapter().submit(plan,policy)
    assert caught.value.status=='blocked' and not lark.writes
    assert len(lark.requests)<=201


def test_rate_limit_mid_pagination_retries_without_write_then_succeeds_once():
    plan,policy=policy_plan();lark=Lark(plan,field_pages=3);lark.fault('GET','/fields',None,429)
    with pytest.raises(RemoteFailure) as caught:lark.adapter().submit(plan,policy)
    assert caught.value.status=='retry' and caught.value.retry_after==7 and not lark.writes
    assert lark.adapter().submit(plan,policy)['verified'] and len(lark.writes)==1


# (3) idempotency: same plan -> same client_token and key; different revisions -> different keys
def test_resubmission_reuses_token_and_never_duplicates_row():
    plan,policy=policy_plan();lark=Lark(plan);lark.fault('POST','/records',500)
    lark.created_on_fault=False
    with pytest.raises(RemoteFailure):lark.adapter().submit(plan,policy)
    assert lark.adapter().submit(plan,policy)['verified']
    tokens={r[2]['client_token'] for r in lark.writes}
    assert tokens=={plan['client_token']} and len(lark.writes)==2 and len(lark.rows)==1
    assert lark.adapter().submit(plan,policy)['verified'] and len(lark.writes)==2


def test_distinct_revisions_get_distinct_registration_keys():
    a,_=policy_plan()
    dest=a['destination']
    def plan_for(rid):return make_plan('lark-company',{'id':'p','code':'115001'},{'id':'n'},
        {'id':rid,'project_id':'p','node_id':'n','actor_id':'ou','created_at':'2026-09-29','mapping_id':'m','value':'v'},dest)
    one,two=plan_for('r1'),plan_for('r2')
    assert one['values']['registration_key']!=two['values']['registration_key'] and one['client_token']!=two['client_token']


# confirm_absent: read-only and never silently "absent" on failure
def test_confirm_absent_is_read_only_and_requires_a_complete_empty_search():
    plan,policy=policy_plan();lark=Lark(plan)
    assert lark.adapter().confirm_absent(plan,policy) is None and not lark.writes
    lark.fault('POST','/search',500)
    with pytest.raises(RemoteFailure) as caught:lark.adapter().confirm_absent(plan,policy)
    assert caught.value.status=='failed'
    lark.rows=[{'record_id':'r','fields':{FIELD_NAMES[k]:v for k,v in plan['values'].items()}}]
    with pytest.raises(RemoteFailure) as caught:lark.adapter().confirm_absent(plan,policy)
    assert caught.value.status=='conflict' and not lark.writes


# (2) endpoint: explicit disposal with audit; every other path leaves state untouched
def make_unknown(app,client):
    assert submit(client).status_code==200
    wid=app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
    with app.state.sessions.begin() as db:
        row=db.get(WorkspaceRow,wid);state=storage.load(db,BusinessRow,row)
        revision=state['input_revisions'][-1];revision['status']='outcome_unknown'
        next(j for j in state['jobs'] if j['key']=='input:'+revision['id'])['status']='outcome_unknown'
        plan=deepcopy(revision['registration_plan']);row.data=storage.save(db,BusinessRow,wid,state)
    return revision['id'],plan,wid


def audits(app,wid,action):
    with app.state.sessions() as db:return [a for a in db.scalars(select(AuditRow)).all() if a.action==action]


def dispose(client,ident,**over):
    body={'version':workspace(client)['version'],'confirm_not_created':True,'reason':'人工核對 Lark 表確無此列'};body.update(over)
    return client.post(f'/api/input-revisions/{ident}/dispose-not-created',json=body)


def wire(monkeypatch,lark):
    lark.client.close=lambda:None
    monkeypatch.setattr(integration_routes,'application_adapter',lambda cfg:type('A',(),{'client':lark.client,'request':LarkAdapter('t',client=lark.client).request})())


def test_disposal_requires_confirmation_reason_and_changes_nothing_otherwise(setup,monkeypatch):
    app,client=setup;ident,plan,wid=make_unknown(app,client);lark=Lark(plan);wire(monkeypatch,lark)
    before=read_raw(app,client)
    for over in ({'confirm_not_created':False},{'confirm_not_created':'yes'},{'reason':''},{'reason':'x'*501},{'reason':None}):
        assert dispose(client,ident,**over).status_code==422
    assert read_raw(app,client)['input_revisions']==before['input_revisions'] and not lark.requests


def test_disposal_blocked_when_remote_row_exists_or_read_fails(setup,monkeypatch):
    app,client=setup;ident,plan,wid=make_unknown(app,client);lark=Lark(plan);wire(monkeypatch,lark)
    lark.rows=[{'record_id':'r','fields':{FIELD_NAMES[k]:v for k,v in plan['values'].items()}}]
    assert dispose(client,ident).status_code==409
    lark.rows=[];lark.fault('POST','/search',500)
    assert dispose(client,ident).status_code in (409,503)
    lark.fault('POST','/search',httpx.ReadTimeout('t'))
    assert dispose(client,ident).status_code in (409,503)
    state=read_raw(app,client);current=next(i for i in state['input_revisions'] if i['id']==ident)
    assert current['status']=='outcome_unknown' and not current.get('superseded') and 'disposal' not in current
    assert not lark.writes and not audits(app,wid,'input_registration_disposed_not_created')
    assert not any(e['action']=='input_registration_disposed_not_created' for e in state['events'])


def test_disposal_only_for_unknown_and_never_for_queued_or_succeeded(setup,monkeypatch):
    app,client=setup;assert submit(client).status_code==200
    state=read_raw(app,client);ident=state['input_revisions'][-1]['id']
    lark=Lark(state['input_revisions'][-1]['registration_plan']);wire(monkeypatch,lark)
    assert dispose(client,ident).status_code==409 and not lark.requests


def test_confirmed_disposal_is_audited_closes_job_and_never_writes(setup,monkeypatch):
    app,client=setup;ident,plan,wid=make_unknown(app,client);lark=Lark(plan);wire(monkeypatch,lark)
    response=dispose(client,ident);assert response.status_code==200,response.text
    state=read_raw(app,client);current=next(i for i in state['input_revisions'] if i['id']==ident)
    assert current['status']=='not_created' and current['superseded'] is True
    assert current['disposal']['basis']=='explicit_confirmation_and_fresh_readonly_absence' and current['disposal']['reason']
    job=next(j for j in state['jobs'] if j['key']=='input:'+ident);assert job['status']=='canceled'
    assert [e['action'] for e in state['events'] if e['action']=='input_registration_disposed_not_created']==['input_registration_disposed_not_created']
    assert len(audits(app,wid,'input_registration_disposed_not_created'))==1
    assert not lark.writes
    # Not a second disposal or a reconcile target any more; the original id stays idempotent.
    assert dispose(client,ident).status_code==409
    assert client.post(f'/api/input-revisions/{ident}/reconcile',json={'version':workspace(client)['version']}).status_code==409
    before=len(read_raw(app,client)['input_revisions'])
    assert submit(client,current['request_id']).status_code==200 and len(read_raw(app,client)['input_revisions'])==before
    assert submit(client).status_code==200 and len(read_raw(app,client)['input_revisions'])==before+1
