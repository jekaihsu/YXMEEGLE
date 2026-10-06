from copy import deepcopy
import uuid
import pytest
from .test_backend import app, client, workspace, role
from .app import WorkspaceRow, BusinessRow
from . import storage


def change(app,client,fn):
    wid=app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
    with app.state.sessions.begin() as db:
        row=db.get(WorkspaceRow,wid); state=storage.load(db,BusinessRow,row)
        fn(state); state['version']=row.version+1
        row.data=storage.save(db,BusinessRow,wid,state);row.version+=1


def request(client,ws,action,payload=None,pid=None,node=None):
    project=next(p for p in ws['projects'] if p['id']==(pid or 'p1'))
    return client.post('/api/actions',json={'action':action,'payload':payload or {},'project_id':project['id'],
        'node_id':node,'version':ws['version'],'project_versions':{project['id']:project['concurrency_version']},'request_id':uuid.uuid4().hex})


def heartbeat(state):
    state['source_status']={'last_attempt_at':'later','sync_revision':44}
    state['people_directory_status']={'last_success_at':'later'}
    for user in state['users']:user['directory_last_seen_at']='later'


@pytest.mark.parametrize('action,payload',[
    ('project_roles',{'quotation_id':'u-pm'}),
    ('approval_create',{'type':'change','reason':'scope','task_ids':['p1-control-t1']}),
])
def test_background_only_updates_do_not_reject_case_mutations(app,client,action,payload):
    ws=workspace(client);change(app,client,heartbeat)
    response=request(client,ws,action,payload)
    assert response.status_code==200,response.text


def test_same_case_business_change_still_rejects_roles(app,client):
    ws=workspace(client)
    change(app,client,lambda s:s['projects'][0].update(name='Changed case'))
    assert request(client,ws,'project_roles',{'quotation_id':'u-pm'}).status_code==409


@pytest.mark.parametrize('collection',['approvals','sop_requests','financial_requests','node_skip_requests'])
def test_root_case_business_records_advance_project_version(app,client,collection):
    ws=workspace(client)
    change(app,client,lambda s:s.setdefault(collection,[]).append({'id':'scope-record','project_id':'p1','status':'draft'}))
    assert request(client,ws,'project_roles',{'quotation_id':'u-pm'}).status_code==409


def test_approval_draft_can_withdraw_after_background_sync(app,client):
    ws=workspace(client)
    created=request(client,ws,'approval_create',{'type':'change','reason':'scope','task_ids':['p1-control-t1']})
    assert created.status_code==200,created.text
    ws=created.json();aid=ws['approvals'][0]['id'];change(app,client,heartbeat)
    response=request(client,ws,'approval_withdraw',{'approval_id':aid})
    assert response.status_code==200,response.text


def test_approval_cannot_borrow_another_case_version(app,client):
    ws=workspace(client)
    created=request(client,ws,'approval_create',{'type':'change','reason':'scope','task_ids':['p1-control-t1']})
    ws=created.json()
    assert request(client,ws,'approval_withdraw',{'approval_id':ws['approvals'][0]['id']},pid='p2').status_code==422


def test_sop_apply_cannot_borrow_another_case_version(app,client):
    change(app,client,lambda s:s['sop_requests'].append({'id':'req','project_id':'p1','status':'pending'}))
    ws=workspace(client)
    assert request(client,ws,'sop_apply',{'id':'req'},pid='p2').status_code==422


def test_global_sop_publish_retains_global_cas(app,client):
    role(client,'u-manager');ws=workspace(client);change(app,client,heartbeat)
    assert request(client,ws,'sop_publish',{'id':'none'}).status_code==409


def test_actor_business_role_is_rechecked_after_sync(app,client):
    ws=workspace(client)
    def revoke(state):
        heartbeat(state)
        for p in state['projects']:
            if p['id']=='p1':p['pm_id']='u-control'
    change(app,client,revoke)
    # Use fresh case version: permission still cannot be recovered by a valid CAS.
    fresh=workspace(client)
    response=request(client,fresh,'project_roles',{'quotation_id':'u-pm'})
    assert response.status_code==403,response.text

def test_node_complete_accepts_same_case_after_metadata_sync(app,client):
    def ready(state):
        p=state['projects'][0];n=next(n for n in p['nodes'] if n['key']=='pm')
        n.update(requirements=[],tasks=[],reviewers=[],owner_id='u-pm',supervisor_id='u-manager',status='in_progress')
        p['supervisor_id']='u-manager'
    change(app,client,ready);ws=workspace(client)
    node=next(n for n in ws['projects'][0]['nodes'] if n['key']=='pm')
    change(app,client,heartbeat)
    response=request(client,ws,'node_complete',node=node['id'])
    assert response.status_code==200,response.text


def test_sop_apply_accepts_same_case_after_metadata_sync(app,client):
    def prepare(state):
        p=state['projects'][0]
        t=deepcopy(state['sop_templates'][0]);t.update(id='next-template',status='published')
        state['sop_templates'].append(t)
        state['sop_requests'].append({'id':'req','project_id':p['id'],'target_id':t['id'],'from_version':p['sop_version'],'status':'pending'})
    change(app,client,prepare);ws=workspace(client);change(app,client,heartbeat)
    response=request(client,ws,'sop_apply',{'id':'req'})
    assert response.status_code==200,response.text


def test_sop_template_change_invalidates_project_cas(app,client):
    ws=workspace(client)
    change(app,client,lambda s:s['sop_templates'][0].update(description='Changed obligations'))
    assert request(client,ws,'project_roles',{'quotation_id':'u-pm'}).status_code==409


def test_reassigned_root_record_invalidates_both_cases(app,client):
    change(app,client,lambda s:s['sop_requests'].append({'id':'req','project_id':'p1','status':'pending'}))
    ws=workspace(client)
    change(app,client,lambda s:s['sop_requests'][0].update(project_id='p2'))
    for pid in ('p1','p2'):
        assert request(client,ws,'project_roles',{'quotation_id':'u-pm'},pid=pid).status_code==409


def test_sop_apply_route_gates_on_case_version_then_applies(app,client):
    from sqlalchemy import select
    from .app import AuditRow
    def prepare(state):
        p=state['projects'][0]
        t=deepcopy(state['sop_templates'][0]);t.update(id='next-template',status='published')
        state['sop_templates'].append(t)
        state['sop_requests'].append({'id':'req','project_id':p['id'],'target_id':t['id'],'from_version':p['sop_version'],'status':'pending'})
    def snapshot():
        wid=app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
        with app.state.sessions.begin() as db:
            row=db.get(WorkspaceRow,wid);state=storage.load(db,BusinessRow,row)
            rows=db.execute(select(AuditRow).where(AuditRow.action=='sop_apply')).scalars().all()
            return deepcopy(state),row.version,[(r.id,r.data.get('result')) for r in rows]
    change(app,client,prepare);stale=workspace(client)
    change(app,client,lambda s:s['projects'][0].update(name='Changed case'))  # bumps this case's version
    before_state,before_version,before_audit=snapshot()
    response=request(client,stale,'sop_apply',{'id':'req'})
    assert response.status_code==409,response.text
    after_state,after_version,after_audit=snapshot()
    assert after_state==before_state and after_version==before_version
    assert after_state['sop_requests'][0]['status']=='pending'
    assert after_state['projects'][0]['sop_version']==before_state['projects'][0]['sop_version']
    assert [a for a in after_audit if a not in before_audit]==[(a[0],'denied') for a in after_audit if a not in before_audit]  # only denial recorded
    assert not [a for a in after_audit if a[1]!='denied']
    current=request(client,workspace(client),'sop_apply',{'id':'req'})
    assert current.status_code==200,current.text
    final,final_version,final_audit=snapshot()
    assert final['sop_requests'][0]['status']=='approved' and final['projects'][0]['sop_version']=='next-template'
    assert final_version==before_version+1 and len([a for a in final_audit if a[1]!='denied'])==1
