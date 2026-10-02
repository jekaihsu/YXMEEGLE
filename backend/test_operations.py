"""Acceptance tests for quote/V4 workflow, isolation and recovery rules."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
import hashlib
import json
import pytest
import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select, create_engine
from .seed import seed, USERS
from .policy import upgrade
from .sources import import_sources, configuration, normalized_case
from .operations import apply_operation, missing, add_workdays, next_due, queue
from .jobs import schedule, Worker
from .lark_adapter import LarkAdapter, RemoteFailure
from .app import create_app, WorkspaceRow, BusinessRow, PersonRow
from . import storage

def record(kind,ident,fields): return dict(kind=kind,base_token='v4',table_id=kind,record_id=ident,fields=fields)

@pytest.fixture
def ws():
    state=seed(True); state['users']=deepcopy(USERS)
    state['environment']='demo'
    import_sources(state,[record('confirmation','rec1',{'工程確認單編號':'C001','工程名稱':'測試案件','狀態':'執行中','合約總額':100})])
    p=state['projects'][0]; p.update(execution_system='workbench',pm_id='u-pm',admin_id='u-manager',supervisor_id='u-manager',issuer_ids=['u-manager'])
    for n in p['nodes']: n.update(owner_id='u-pm',supervisor_id='u-manager')
    return state

def call(ws,action,data=None,user='u-manager',key=None,p=None):
    p=p or ws['projects'][0]; n=next((n for n in p['nodes'] if n['key']==key),None)
    return apply_operation(ws,next(u for u in ws['users'] if u['id']==user),dict(action=action,payload=data or {},project_id=p['id'],node_id=n['id'] if n else None),True)

def ready(ws,key):
    p=ws['projects'][0]; n=next(n for n in p['nodes'] if n['key']==key)
    for t in n['tasks']: t['status']='completed'; t['output']='驗收成果'
    for r in n['requirements']: p['evidence'].append(dict(id=r['key']+n['id'],node_id=n['id'],key=r['key'],status='accepted',note='測試佐證',url='https://example.com/evidence'))
    return p,n

def attest(ws,item,category,batch_id=None):
    for seat,user in [('pm','u-pm'),('admin','u-manager')]:
        call(ws,'finance_attest',dict(id=item['id'],category=category,batch_id=batch_id,seat=seat,evidence='核對憑證'),user=user)

def test_quotes_remain_intake_and_duplicate_confirmations_keep_work_items():
    w=seed(True)
    rows=[record('quote','q',{'工程編號':'Q1','工程名稱':'未確認接案'}),record('confirmation','c1',{'工程確認單編號':'C001','狀態':'執行中','合約總額':100}),record('confirmation','c2',{'工程確認單編號':' C001 ','狀態':'執行中','合約總額':200})]
    rows += [record('reporting',f'r{i}',{'所屬案件':'C001','工項類別':'控制','工項名稱':f'工項{i}','來源明細唯一鍵':'same'}) for i in range(2)]
    import_sources(w,rows); assert len(w['projects'])==2
    formal=[p for p in w['projects'] if p['case_type']=='formal']; intake=[p for p in w['projects'] if p['case_type']=='intake']
    assert len(formal)==len(intake)==1
    p=formal[0]; assert p['source_conflicts']['合約總額']==['100','200']; assert p['contract_amount'] is None
    n=next(n for n in p['nodes'] if n['key']=='control'); assert len([t for t in n['tasks'] if t.get('source_identity')])==2
    original=p['id']; rows[1]['fields']['工程确认單編號']='ignore'; import_sources(w,rows)
    assert next(p for p in w['projects'] if p['case_type']=='formal')['id']==original and len(w['projects'])==2
    assert normalized_case(' C001-01 ')=='C001-01'; assert normalized_case('C 001')!='C001'

@pytest.mark.parametrize('remote,status,complete',[('報價中','pending',False),('執行中','pending',False),('已完工','pending',False),('已結案','pending',False),('中止','paused',False),('內部','pending',False)])
def test_six_source_states_never_fabricate_votes(remote,status,complete):
    w=seed(True); import_sources(w,[record('confirmation','c',{'工程確認單編號':'C1','狀態':remote})]); p=w['projects'][0]
    assert p['source_status']==remote and p['status']==p['execution_status']==status; n=next(n for n in p['nodes'] if n['key']=='sales'); assert n['source_completed']==complete
    assert n['review_cycles']==[] and p['evidence']==[] and p['confirmation_issues']==[]
    n['status']='rework'; import_sources(w,[record('confirmation','c',{'工程確認單編號':'C1','狀態':'已結案'})]); assert n['status']=='rework'

def test_missing_documents_block_review_and_na_requires_supervisor(ws):
    p=ws['projects'][0]; n=next(n for n in p['nodes'] if n['key']=='sales')
    for t in n['tasks']: t['status']='completed'
    with pytest.raises(HTTPException,match='尚未完成'): call(ws,'review_submit',key='sales')
    call(ws,'evidence_submit',{'key':'signed','note':'未成交','not_applicable':True},user='u-pm',key='sales')
    e=p['evidence'][-1]
    with pytest.raises(HTTPException): call(ws,'evidence_approve',{'id':e['id']},user='u-field')
    call(ws,'evidence_approve',{'id':e['id']}); assert e['status']=='not_applicable'
    assert '回簽報價單或合約' not in missing(p,n,ws)

def test_two_distinct_financial_seats_and_handover_preserves_other_vote(ws):
    p,n=ready(ws,'pricing'); call(ws,'review_submit',key='pricing'); c=n['review_cycles'][-1]
    call(ws,'review_vote',{'cycle_id':c['id'],'seat':'pm','result':'approved'},user='u-pm',key='pricing')
    assert n['status']!='completed'
    call(ws,'project_roles',{'admin_id':'u-field'})
    assert c['seats']['admin']=='u-field'; assert not c['votes'][0].get('invalidated')
    call(ws,'review_vote',{'cycle_id':c['id'],'seat':'admin','result':'approved'},user='u-field',key='pricing')
    assert n['status']=='completed' and p['status']=='in_progress'
    with pytest.raises(HTTPException): call(ws,'project_roles',{'admin_id':'u-pm'})

def test_return_new_content_and_any_do_not_bypass_gates(ws):
    p,n=ready(ws,'sales'); n['reviewers']=['u-pm','u-field']; n['review_mode']='any'
    call(ws,'review_submit',key='sales'); c=n['review_cycles'][-1]
    call(ws,'review_vote',{'cycle_id':c['id'],'seat':'person:u-field','result':'returned','reason':'文件需修正'},user='u-field',key='sales')
    assert c['status']=='returned'
    with pytest.raises(HTTPException): call(ws,'review_vote',{'cycle_id':c['id'],'seat':'person:u-pm','result':'approved'},user='u-pm',key='sales')
    call(ws,'review_submit',key='sales'); current=n['review_cycles'][-1]
    call(ws,'evidence_submit',{'key':'demand','note':'換版','url':'https://example.com/new'},user='u-pm',key='sales')
    assert current['status']=='invalidated'
    call(ws,'review_submit',key='sales'); current=n['review_cycles'][-1]
    call(ws,'review_vote',{'cycle_id':current['id'],'seat':'person:u-pm','result':'approved'},user='u-pm',key='sales')
    assert n['status']=='completed'

def test_proxy_cannot_cast_both_sides_and_expired_vote_not_counted(ws,monkeypatch):
    monkeypatch.setattr('backend.operations.now',lambda:'2026-09-27T10:00:00+08:00')
    p,n=ready(ws,'pricing')
    for ident in ('u-pm','u-field'): next(u for u in ws['users'] if u['id']==ident)['capabilities']=['finance_approve']
    common=dict(principal_id='u-manager',seat='admin',source='supervisor',scope='review',start_date='2026-09-26',qualified=True,qualification_note='具資格',qualification_evidence='主管核定財務代理資格')
    call(ws,'delegation_set',dict(common,delegate_id='u-pm',end_date='2026-09-28'))
    call(ws,'review_submit',key='pricing'); c=n['review_cycles'][-1]
    call(ws,'review_vote',{'cycle_id':c['id'],'seat':'pm','result':'approved'},user='u-pm',key='pricing')
    with pytest.raises(HTTPException,match='不同實際操作者'): call(ws,'review_vote',{'cycle_id':c['id'],'seat':'admin','result':'approved'},user='u-pm',key='pricing')
    c['votes']=[]
    call(ws,'delegation_set',dict(common,delegate_id='u-field',end_date='2026-09-27'))
    call(ws,'review_vote',{'cycle_id':c['id'],'seat':'admin','result':'approved'},user='u-field',key='pricing')
    monkeypatch.setattr('backend.operations.now',lambda:'2026-09-28T10:00:00+08:00')
    call(ws,'review_vote',{'cycle_id':c['id'],'seat':'pm','result':'approved'},user='u-pm',key='pricing')
    assert n['status']!='completed'

def test_financial_reconciliation_checks_all_batches_and_decimal_totals(ws):
    p,n=ready(ws,'settlement')
    call(ws,'finance_propose',{'contract_amount':'100.30','budget':'60','evidence':'signed'})
    attest(ws,p['finance_versions'][-1],'baseline')
    call(ws,'finance_approve',{'id':p['finance_versions'][-1]['id']})
    _,control=ready(ws,'control')
    proof=next(e for e in p['evidence'] if e['node_id']==control['id'] and e['key']=='deliverable')
    for amount in ('50.10','50.20'):
        call(ws,'delivery_submit',dict(work_item_ids=[control['tasks'][0]['id']],quantity='1',unit='批',evidence_ids=[proof['id']]))
        delivery=p['delivery_batches'][-1]; call(ws,'delivery_review',dict(id=delivery['id'],result='approved'))
        call(ws,'payment_create',dict(kind='receivable',phase='progress',amount=amount,contract_evidence='signed',claim_evidence='invoice',delivery_batch_ids=[delivery['id']]))
        b=p['payment_batches'][-1]; attest(ws,b,'batch'); call(ws,'payment_approve',{'id':b['id']})
        call(ws,'payment_record',dict(id=b['id'],amount=amount,evidence='bank',date='2026-09-27'))
        attest(ws,b['receipts'][-1],'receipt',b['id'])
    call(ws,'payment_create',dict(kind='subcontract',phase='advance',amount='10',contract_evidence='signed',claim_evidence='invoice'))
    b=p['payment_batches'][-1]; attest(ws,b,'batch'); call(ws,'payment_approve',{'id':b['id']})
    with pytest.raises(HTTPException): call(ws,'payment_reconcile',{'evidence':'check','all_payables_declared':True})
    call(ws,'payment_record',dict(id=b['id'],amount='4',evidence='bank',date='2026-09-27')); assert b['status']=='approved'
    attest(ws,b['receipts'][0],'receipt',b['id']); assert b['status']=='partially_paid'
    with pytest.raises(HTTPException): call(ws,'payment_record',dict(id=b['id'],amount='7',evidence='bank',date='2026-09-27'))
    call(ws,'payment_record',dict(id=b['id'],amount='6',evidence='bank',date='2026-09-27'))
    for receipt in b['receipts']: attest(ws,receipt,'receipt',b['id'])
    call(ws,'payment_reconcile',{'evidence':'check','all_payables_declared':True})
    assert '適用工程交付尚未全部完成' in missing(p,n,ws)
    for node in p['nodes']:
        if node['key'] in ('field','control','mapping','report'): node['status']='completed'
    assert '報價、派工、確認單及計價節點尚未完成或核准不適用' in missing(p,n,ws)
    for node in p['nodes']:
        if node['key'] in ('sales','pm','confirmation','pricing'): node['status']='completed'
    assert not missing(p,n,ws)
    assert p['source_status']=='執行中'  # V4's declaration remains separate from local workflow completion.
    assert p['status']==p['execution_status'] and p['execution_status']!='completed'

def test_cost_total_conservation_and_duplicate_source_blocked(ws):
    p=ws['projects'][0]
    with pytest.raises(HTTPException): call(ws,'finance_allocate',dict(source_id='cost1',total='10.1',parts=[dict(project_id=p['id'],amount='10')],reason='hours'))
    call(ws,'finance_allocate',dict(source_id='cost1',total='10.1',parts=[dict(project_id=p['id'],amount='10.1')],reason='hours'))
    with pytest.raises(HTTPException): call(ws,'finance_allocate',dict(source_id='cost1',total='10.1',parts=[dict(project_id=p['id'],amount='10.1')],reason='duplicate'))

def test_workdays_holiday_makeup_and_monthly(ws):
    ws['calendar']={'holidays':['2026-09-28'],'workdays':['2026-09-26']}
    assert add_workdays('2026-09-25',5,ws['calendar'])=='2026-10-02'
    assert next_due('monthly','2026-09-27',ws)=='2026-10-07'
    assert next_due('field_schedule','2026-09-29',ws)=='2026-09-30'

def test_digest_once_daily_with_overdue_escalation_and_stop_rules(ws):
    p=ws['projects'][0]
    call(ws,'recurring_create',dict(kind='client_contact',owner_id='u-field',start_date='2026-09-01'))
    due=ws['recurring'][-1]['due_date']
    ws['work_schedules']=[dict(id='scheduled-cutoff',user_id='u-field',day=due,end_time='18:00',version=1,active=True)]
    schedule(ws,'2026-09-28T08:59:00+08:00'); assert not ws['jobs']
    schedule(ws,'2026-09-28T09:00:00+08:00'); first=len(ws['jobs']); assert first>0
    assert all(j['payload']['source_scope']=='case_digest_v1' and
               j['payload']['source_project_ids']==[p['id']] for j in ws['jobs'])
    schedule(ws,'2026-09-28T10:00:00+08:00'); assert len(ws['jobs'])==first
    assert any(j['payload']['recipients']==['u-manager'] for j in ws['jobs'])
    p['source_status']='中止'; ws['jobs']=[]
    schedule(ws,'2026-09-29T09:00:00+08:00'); assert not ws['jobs']
    call(ws,'recurring_create',dict(kind='receivable',owner_id='u-manager',start_date='2026-09-01'))
    schedule(ws,'2026-09-29T09:00:00+08:00'); assert ws['jobs']

def test_sop_published_is_immutable_and_active_case_requires_request(ws):
    p=ws['projects'][0]; original=p['sop_version']; source=ws['sop_templates'][0]
    nodes=deepcopy(source['nodes']); nodes[0]['tasks'].append('新增核對')
    nodes[0]['task_definitions'].append({'key':'new-check','title':'新增核對','source_scope':'local-draft'})
    call(ws,'sop_draft',{'source_id':source['id'],'nodes':nodes}); target=ws['sop_templates'][-1]
    call(ws,'sop_publish',{'id':target['id']}); assert p['sop_version']==original
    with pytest.raises(HTTPException): call(ws,'sop_publish',{'id':target['id']})
    call(ws,'sop_request',{'id':target['id'],'reason':'核定更新'},user='u-pm')
    call(ws,'sop_apply',{'id':ws['sop_requests'][-1]['id']}); assert p['sop_version']==target['id']
    assert any(t['title']=='新增核對' for t in p['nodes'][0]['tasks'])

def test_mapping_cannot_write_status_or_formula_and_unique_target(ws):
    p,n=ready(ws,'sales')
    mapping=dict(key='input1',label='需求',base_token='v4',table_id='t',field_id='f',field_name='狀態',record_id='rec1',type='text')
    with pytest.raises(HTTPException): call(ws,'input_mapping',mapping,key='sales')
    mapping.update(field_name='需求',type='formula')
    with pytest.raises(HTTPException): call(ws,'input_mapping',mapping,key='sales')
    mapping['type']='text'; call(ws,'input_mapping',mapping,key='sales')
    with pytest.raises(HTTPException): call(ws,'input_mapping',mapping,key='sales')
    call(ws,'input_draft',{'mapping_id':ws['input_mappings'][0]['id'],'value':'test'},key='sales')
    assert 'Input 尚未核實存回 Lark' in missing(p,n,ws)

@pytest.fixture
def api_app(tmp_path):
    app=create_app({'DATABASE_URL':f'sqlite:///{tmp_path}/app.db','UPLOAD_DIR':str(tmp_path/'uploads'),'SESSION_SECRET':'x'*40,'APP_ENV':'development','DEMO_MODE':'true'})
    client=TestClient(app); client.get('/api/session'); client.post('/api/demo/session',json={'user_id':'u-manager'})
    return app,client

def inject(api_app,ws):
    app,client=api_app; cookie=app.state.signer.loads(client.cookies.get('meegle_session')); wid=cookie['wid']
    with app.state.sessions.begin() as db:
        row=db.get(WorkspaceRow,wid); row.data=storage.save(db,BusinessRow,wid,ws); row.version=ws['version']
    return wid

def test_normalized_roundtrip_and_atomic_idempotency(api_app,ws):
    app,client=api_app; wid=inject(api_app,ws)
    p=ws['projects'][0]; body=dict(action='project_roles',payload={'admin_id':'u-field'},project_id=p['id'],version=ws['version'],request_id='one')
    first=client.post('/api/actions',json=body); assert first.status_code==200,first.text
    replay=client.post('/api/actions',json=body); assert replay.status_code==200 and replay.json()['version']==first.json()['version']
    body['payload']['admin_id']='u-report'; assert client.post('/api/actions',json=body).status_code==409
    with app.state.sessions() as db:
        row=db.get(WorkspaceRow,wid); assert 'projects' not in row.data
        assert storage.load(db,BusinessRow,row)['projects'][0]['admin_id']=='u-field'

def test_worker_test_workspace_never_calls_remote_and_issue_once(api_app,ws):
    app,client=api_app; p,n=ready(ws,'confirmation')
    call(ws,'confirmation_issue',{'version':'1','recipients':['u-field','u-control']})
    call(ws,'confirmation_issue',{'version':'1','recipients':['u-field','u-control']}); assert len(ws['jobs'])==1
    wid=inject(api_app,ws)
    app.state.worker.adapter_factory=lambda cfg:pytest.fail('Test workspace called remote')
    app.state.worker.run_one(wid)
    state=client.get('/api/workspace').json(); issue=state['projects'][0]['confirmation_issues'][0]
    assert issue['status']=='simulated'; assert len(issue['receipts'])==2; assert len(state['projects'][0]['handoffs'])==1
    app.state.worker.run_one(wid); state=client.get('/api/workspace').json(); assert len(state['projects'][0]['handoffs'])==1

def test_worker_recovers_only_failed_recipient_without_resend(api_app,ws):
    app,client=api_app; p,n=ready(ws,'confirmation'); call(ws,'confirmation_issue',{'version':'1','recipients':['u-field','u-control']})
    job=ws['jobs'][0]; job['steps']=[{'key':'u-field','receipt':{'message_id':'prior-success'}}]
    wid=inject(api_app,ws); app.state.worker.run_one(wid)
    state=client.get('/api/workspace').json(); receipts=state['projects'][0]['confirmation_issues'][0]['receipts']
    assert len(receipts)==2 and receipts[0]['receipt']['message_id']=='prior-success'

def test_worker_expired_lease_becomes_unknown_not_reexecuted(api_app,ws):
    app,client=api_app; p,n=ready(ws,'confirmation'); call(ws,'confirmation_issue',{'version':'1','recipients':['u-field']})
    ws['jobs'][0].update(status='running',lease_until='2020-01-01T00:00:00+08:00')
    wid=inject(api_app,ws); app.state.worker.run_one(wid)
    state=client.get('/api/workspace').json(); assert state['jobs'][0]['status']=='outcome_unknown'; assert not state['projects'][0]['handoffs']

def test_worker_rechecks_suspended_actor(api_app,ws):
    app,client=api_app; p,n=ready(ws,'confirmation'); call(ws,'confirmation_issue',{'version':'1','recipients':['u-field']})
    next(u for u in ws['users'] if u['id']=='u-manager')['active']=False
    wid=inject(api_app,ws); app.state.worker.run_one(wid)
    with app.state.sessions() as db: state=storage.load(db,BusinessRow,db.get(WorkspaceRow,wid))
    assert state['jobs'][0]['status']=='blocked'; assert not state['projects'][0]['handoffs']

def test_lark_three_way_conflict_and_readback_after_lost_response():
    remote={'value':'base','writes':0,'lose_response':True}
    def handler(request):
        if request.url.path.endswith('/fields'): return httpx.Response(200,json={'code':0,'data':{'items':[{'field_id':'f','field_name':'Input','type':1}],'has_more':False}})
        if request.method=='PUT':
            remote['writes']+=1; remote['value']=json.loads(request.content)['fields']['Input']
            if remote['lose_response']: raise httpx.ReadTimeout('lost')
        return httpx.Response(200,json={'code':0,'data':{'record':{'record_id':'rec1','fields':{'Input':remote['value']}}}})
    adapter=LarkAdapter('secret',httpx.Client(transport=httpx.MockTransport(handler)))
    mapping=dict(base_token='v4',table_id='t',record_id='rec1',field_id='f',field_name='Input',type='text')
    revision={'value':'local','base_value':'base'}
    receipt=adapter.write_input(mapping,revision); assert receipt['verified']; assert remote['writes']==1
    adapter.write_input(mapping,revision); assert remote['writes']==1
    remote['value']='changed elsewhere'
    with pytest.raises(RemoteFailure) as exc: adapter.write_input(mapping,revision)
    assert exc.value.status=='conflict'; assert remote['writes']==1

def test_schema_drift_refuses_write():
    requests=[]
    def handler(r):
        requests.append(r.method)
        return httpx.Response(200,json={'data':{'items':[{'field_id':'f','field_name':'renamed','type':1}]}})
    a=LarkAdapter('secret',httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(RemoteFailure): a.verify_mapping(dict(base_token='v4',table_id='t',record_id='rec1',field_id='f',field_name='original',type='text'))
    assert requests==['GET']

def test_backup_restore_normalized_rows_and_file_hash(api_app,ws,tmp_path):
    from scripts.backup_restore import backup, restore
    import hashlib
    ws['projects'][0]['pm_id']='u-manager'
    app,client=api_app; wid=inject(api_app,ws)
    p=ws['projects'][0]; node=next(n for n in p['nodes'] if n['key']=='control')
    response=client.post('/api/files',data={'project_id':p['id'],'node_id':node['id'],'direction':'input','version':client.get('/api/workspace').json()['version']},files={'file':('sample.txt',b'file proof','text/plain')})
    assert response.status_code==200,response.text
    uploaded=next(item for item in response.json()['projects'] if item['id']==p['id'])['files'][-1]
    relative=Path(hashlib.sha256(wid.encode()).hexdigest())/uploaded['id']
    (app.state.upload_dir/'uncommitted').write_bytes(b'partial upload')
    target=tmp_path/'backup.zip'; backup(app.state.engine,app.state.upload_dir,target)
    restored=create_engine(f'sqlite:///{tmp_path}/restore.db'); out=tmp_path/'restored-uploads'; restore(restored,out,target)
    assert (out/relative).read_bytes()==b'file proof'
    assert not (out/'uncommitted').exists()
    with restored.connect() as conn:
        assert conn.execute(select(BusinessRow).where(BusinessRow.kind=='projects')).first()
        assert conn.execute(select(WorkspaceRow)).first()
    with pytest.raises(ValueError): restore(restored,out,target)

def test_source_configuration_allows_two_sources_and_rejects_wrong_kinds(monkeypatch):
    monkeypatch.setenv('LARK_V4_BASE_TOKEN','v4')
    monkeypatch.setenv('LARK_QUOTE_BASE_TOKEN','quotes')
    permitted=[{'base_token':'v4','table_id':'t','kind':'confirmation'},{'base_token':'quotes','table_id':'q','kind':'quote'},{'base_token':'quotes','table_id':'qc','kind':'quote_confirmation'}]
    forbidden=[{'base_token':'v4','table_id':'q','kind':'quote'},{'base_token':'old','table_id':'old','kind':'confirmation'},{'base_token':'quotes','table_id':'bad','kind':'daily'}]
    monkeypatch.setenv('LARK_SOURCE_TABLES_JSON',json.dumps(permitted+forbidden))
    assert configuration()==permitted

def test_financial_baseline_requires_pair_and_resets_reconciliation(ws):
    p=ws['projects'][0]; call(ws,'finance_propose',dict(contract_amount='100',budget='60',evidence='signed'))
    v=p['finance_versions'][-1]
    with pytest.raises(HTTPException,match='兩位不同操作者'): call(ws,'finance_approve',{'id':v['id']})
    attest(ws,v,'baseline'); p['payment_reconciliation']={'confirmed':True}
    call(ws,'finance_approve',{'id':v['id']}); assert p['payment_reconciliation']=={'confirmed':False}

def test_technical_custom_reviewers_cannot_remove_supervisor(ws):
    p,n=ready(ws,'control'); n['reviewers']=['u-field']; n['review_mode']='any'
    call(ws,'review_submit',key='control'); cycle=n['review_cycles'][-1]
    assert cycle['seats']['supervisor']=='u-manager'
    call(ws,'review_vote',dict(cycle_id=cycle['id'],seat='person:u-field',result='approved'),user='u-field',key='control')
    assert n['status']!='completed'
    call(ws,'review_vote',dict(cycle_id=cycle['id'],seat='supervisor',result='approved'),key='control')
    assert n['status']=='completed'

def test_confirmation_requires_actual_recipient_acknowledgments(api_app,ws):
    app,client=api_app; p,n=ready(ws,'confirmation'); call(ws,'confirmation_issue',dict(version='1',recipients=['u-field','u-control']))
    wid=inject(api_app,ws); app.state.worker.run_one(wid); ws=client.get('/api/workspace').json(); p=ws['projects'][0]; n=next(n for n in p['nodes'] if n['key']=='confirmation'); issue=p['confirmation_issues'][0]
    assert '各組尚未確認此版本確認單' in missing(p,n,ws)
    with pytest.raises(HTTPException): call(ws,'confirmation_ack',dict(id=issue['id'],evidence='okay'))
    for u in ('u-field','u-control'): call(ws,'confirmation_ack',dict(id=issue['id'],evidence='本組確認'),user=u)
    assert not missing(p,n,ws)

def test_idle_worker_does_not_bump_version_and_serializes_leases(api_app,ws):
    app,client=api_app; ws['projects'][0]['source_status']='中止'; wid=inject(api_app,ws)
    before=client.get('/api/workspace').json()['version']; app.state.worker.run_one(wid)
    assert client.get('/api/workspace').json()['version']==before
    actor=ws['users'][0]; first=queue(ws,'digest',actor,dict(recipients=[actor['id']],text='one'),'one'); first.update(status='running',lease_until='2099-01-01T00:00:00+08:00')
    queue(ws,'digest',actor,dict(recipients=[actor['id']],text='two'),'two'); inject(api_app,ws)
    assert app.state.worker.run_one(wid) is None
    assert client.get('/api/workspace').json()['jobs'][-1]['status']=='queued'

def test_monthly_submission_waits_for_supervisor(ws):
    call(ws,'recurring_create',dict(kind='monthly',owner_id='u-field',start_date='2026-09-01'))
    r=ws['recurring'][-1]; due=r['due_date']; call(ws,'recurring_complete',dict(id=r['id'],evidence='月考評'),user='u-field')
    assert r['due_date']==due and r['history'][-1]['status']=='pending'
    with pytest.raises(HTTPException): call(ws,'recurring_review',dict(id=r['id'],entry_id=r['history'][-1]['id'],result='accepted',evidence='核准'),user='u-field')
    call(ws,'recurring_review',dict(id=r['id'],entry_id=r['history'][-1]['id'],result='accepted',evidence='核准'))
    assert r['history'][-1]['status']=='accepted'
