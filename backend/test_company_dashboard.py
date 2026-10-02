from datetime import datetime,timezone
from copy import deepcopy
from .company_dashboard import overview
from .test_staff_oauth_acceptance import staff

def case(ident='p',status='進行中',runnable=True):
    return {'id':ident,'name':'Business','code':ident,'source_kind':'lark','case_type':'formal','source_status':status,
        'execution_status':'pending','execution_allowed':runnable,'contract_amount':999999,
        'nodes':[{'key':'field','review_cycles':[{'status':'pending'}], 'tasks':[
            {'status':'pending','due_date':'2026-09-29'}, {'status':'completed','due_date':'2026-09-28'},
            {'status':'paused','due_date':'bad'}, {'status':'superseded','due_date':'2000-01-01'}]}]}

def test_company_counts_closed_source_separately_from_execution_and_excludes_templates():
    closed=case('closed','已結案',False);active=case()
    legacy={**case('old'),'source_kind':'meegle'}
    result=overview({'projects':[closed,active,legacy]},clock=datetime(2026,9,30,tzinfo=timezone.utc))
    assert result['totals']['cases']==2 and result['totals']['source_status_counts']['已結案']==1
    assert result['totals']['execution_status_counts']=={'pending':2}
    assert result['totals']['tasks_total']==3 and result['totals']['tasks_completed']==1
    assert result['totals']['tasks_overdue']==1 and result['missing']['task_due_date']==1
    assert result['groups'][0]['cases']==1
    assert all('contract_amount' not in row for row in result['cases'])

def test_pagination_filters_before_slicing_and_aggregate_counts_all_cases():
    cases=[case(str(i),'已結案' if i%2 else '進行中',False) for i in range(290)]
    result=overview({'projects':cases},source_status='已結案',offset=100,limit=25)
    assert result['totals']['cases']==290 and result['pagination']['total']==145
    assert len(result['cases'])==25 and result['pagination']['has_more']


def test_quote_intakes_are_not_reported_as_confirmed_engineering_cases():
    formal=case('formal','已結案',False)
    intake={**case('quote','待確認單',False),'case_type':'intake','code':formal['code']}
    result=overview({'projects':[formal,intake]})
    assert result['totals']['cases']==2
    assert result['totals']['confirmed_cases']==1 and result['totals']['intake_records']==1
    assert {r['case_type'] for r in result['cases']}=={'formal','intake'}
    assert result['totals']['tasks_total']==0

def test_native_and_local_reviews_not_mixed():
    pending={'project_id':'p','native_binding':{'attempted':True,'instance_code':'instance'},
        'native_receipt':{'instance_code':'instance','binding_verified':True,'external_status':'PENDING'}}
    workspace={'projects':[case()], 'approvals':[pending,
        {'project_id':'p','native_receipt':{'external_status':'APPROVED'}},
        {'project_id':'p','native_receipt':{'external_status':'PENDING','simulated':True}}]}
    result=overview(workspace)
    assert result['totals']['pending_local_reviews']==1 and result['totals']['pending_native_reviews']==1


def test_native_pending_requires_real_current_binding_and_deduplicates_instances():
    from .company_dashboard import verified_native_pending
    valid={'project_id':'p','native_binding':{'attempted':True,'instance_code':'i','binding_hash':'h'},
        'native_receipt':{'external_status':'PENDING','instance_code':'i','binding_verified':True,'binding_hash':'h','simulated':False}}
    assert verified_native_pending(valid)
    for change in ('simulated','verification_failed','terminal_binding','wrong_instance','unverified','wrong_hash','not_attempted'):
        item=deepcopy(valid)
        if change=='simulated':item['simulated']=True
        elif change=='verification_failed':item['native_binding']['verification_failed_at']='now'
        elif change=='terminal_binding':item['native_binding']['receipt']={'external_status':'CANCELED'}
        elif change=='wrong_instance':item['native_binding']['instance_code']='other'
        elif change=='unverified':item['native_receipt']['binding_verified']=False
        elif change=='wrong_hash':item['native_receipt']['binding_hash']='old'
        else:item['native_binding']['attempted']=False
        assert not verified_native_pending(item),change
    result=overview({'projects':[case()],'approvals':[valid],'node_skip_requests':[deepcopy(valid)]})
    assert result['totals']['pending_native_reviews']==1

def test_real_dashboard_route_member_and_revoked_access(staff):
    app,client,login,change=staff
    assert client.get('/api/company-dashboard').status_code==401
    assert login().status_code==307
    reply=client.get('/api/company-dashboard')
    assert reply.status_code==200 and reply.json()['totals']['cases']==0
    assert client.get('/api/company-dashboard?limit=251').status_code==422
    change({'active':False})
    assert client.get('/api/company-dashboard').status_code==403

def test_real_route_includes_closed_lark_reference_without_template_progress(staff):
    from .app import WorkspaceRow,BusinessRow
    from .seed import seed
    from . import storage
    app,client,login,_=staff;assert login().status_code==307
    with app.state.sessions.begin() as db:
        row=db.get(WorkspaceRow,'lark-company');state=storage.load(db,BusinessRow,row)
        project=seed()['projects'][0]
        project.update(source_kind='lark',source_status='已結案',case_visibility='source_reference',execution_system='pending')
        old=deepcopy(project);old.update(id='old-meegle',source_kind='meegle',case_visibility='excluded_history')
        state['projects']=[project,old];row.data=storage.save(db,BusinessRow,row.id,state)
    reply=client.get('/api/company-dashboard').json()
    assert reply['totals']['cases']==1 and reply['totals']['source_status_counts']=={'已結案':1}
    assert reply['totals']['tasks_total']==reply['totals']['tasks_overdue']==0
    assert reply['cases'][0]['workbench_execution_enabled'] is False


def test_recovery_manager_cannot_read_company_dashboard(staff):
    app,client,login,change=staff
    change({'role':'manager','bootstrap_admin':True,'directory_last_seen_at':'2000-01-01T00:00:00Z'})
    assert login().status_code==307
    assert client.get('/api/session').json()['access_mode']=='recovery'
    assert client.get('/api/company-dashboard').status_code==403


def test_output_whitelist_excludes_person_salary_leave_and_financial_payloads():
    import json
    project=case();project.update(client_email='secret-email',salary='secret-salary',
        payment_batches=[{'account':'secret-bank'}],comments=[{'text':'secret-comment'}])
    result=overview({'projects':[project],'users':[{'email':'secret-user-email'}],
        'approved_leave_delegations':[{'reason':'secret-leave'}]})
    assert 'secret-' not in json.dumps(result)
