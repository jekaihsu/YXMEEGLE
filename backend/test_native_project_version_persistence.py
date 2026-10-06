"""Issue #9: native approval operations use the real app.py project-scoped CAS."""
import json
import time
from copy import deepcopy
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from . import native_routes,storage
from .app import create_app, WorkspaceRow, AuthRow, BusinessRow
from .native_approval import NativeApprovalService
from .test_backend import proposal, workspace
from .test_native_approval import fixture
from .seed import seed

WID='lark-test'


@pytest.fixture
def live(tmp_path,monkeypatch):
    cfg={'DATABASE_URL':f'sqlite:///{tmp_path}/native.db','UPLOAD_DIR':str(tmp_path/'uploads'),
         'SESSION_SECRET':'native-test-secret'*3,'APP_ENV':'development','DEMO_MODE':'false',
         'LARK_APP_ID':'app1','LARK_WORKER_IDENTITY':'application','LARK_WORKER_ORGANIZATION':'test','LARK_ALLOWED_TENANTS':'test',
         'LARK_NATIVE_APPROVAL_SUBMIT_ENABLED':'true'}
    mapping,definition,*_=fixture();mapping['kind']='extension';mapping['nodes'][0]['seats']=['supervisor']
    cfg['LARK_NATIVE_APPROVAL_MAPPINGS_JSON']=json.dumps({'extension':mapping})
    calls=[]
    class Adapter:
        client=SimpleNamespace(close=lambda:None)
        def request(self,method,path,**kwargs):
            calls.append((method,path))
            if '/approvals/' in path:return deepcopy(definition)
            raise AssertionError('unexpected remote call '+method+' '+path)
    monkeypatch.setattr(native_routes,'NativeApprovalService',lambda c:NativeApprovalService(c,lambda _:Adapter()))
    app=create_app(cfg)
    data=seed();data['environment']='production'
    for project in data['projects']:
        project.update(source_kind='lark',execution_system='workbench',case_visibility='new_case',pm_id='ou_pm',supervisor_id='ou_sup')
    for old,new in (('u-pm','ou_pm'),('u-manager','ou_sup')):
        data['users'].append({**next(u for u in data['users'] if u['id']==old),'id':new,'name':new})
    for user in data['users']:
        user.update(identity_app_id='app1',directory_status='employed',directory_source={'app_id':'app1','record_id':'rec-'+user['id']})
    with app.state.sessions.begin() as db:
        db.add(WorkspaceRow(id=WID,version=1,data=data))
        db.add(AuthRow(id='native-session',data={'wid':WID,'expires':time.time()+3600,'access_token':'never-used'}))
    c=TestClient(app)
    c.cookies.set('meegle_session',app.state.signer.dumps({'mode':'lark','uid':'ou_pm','wid':WID,'sid':'native-session'}))
    aid=proposal(c,'extension',dates=[{'task_id':'p1-control-t1','due_date':'2026-09-30'}])
    return SimpleNamespace(app=app,client=c,aid=aid,calls=calls)


def snapshot(live):
    ws=workspace(live.client)
    return ws['version'],next(p for p in ws['projects'] if p['id']=='p1')['concurrency_version'],deepcopy(ws['approvals'])


def post(live,op,**body):
    return live.client.post(f'/api/native-approvals/extension/{live.aid}/{op}',json=body)


def test_current_project_version_persists_through_real_app_path(live):
    version,pv,_=snapshot(live)
    response=post(live,'prepare',project_version=pv)
    assert response.status_code==200,response.text
    new_version,new_pv,approvals=snapshot(live)
    assert new_version>version and new_pv>pv
    assert approvals[0]['native_binding']['payload']


def test_stale_project_version_conflicts_without_mutation_or_remote_call(live):
    _,pv,_=snapshot(live)
    assert post(live,'prepare',project_version=pv).status_code==200
    before=snapshot(live);calls=len(live.calls)
    response=post(live,'prepare',project_version=pv)
    assert response.status_code==409
    assert snapshot(live)==before and len(live.calls)==calls


def test_workspace_version_alone_is_rejected(live):
    before=snapshot(live)
    assert post(live,'prepare',version=before[0]).status_code==422
    assert snapshot(live)==before and live.calls==[]


def mutate_stored(live,callback):
    with live.app.state.sessions.begin() as db:
        row=db.get(WorkspaceRow,WID);state=storage.load(db,BusinessRow,row)
        callback(state);row.data=storage.save(db,BusinessRow,WID,state)


def test_project_version_race_before_persist_conflicts_without_mutation(live,monkeypatch):
    """The project changes after the route pre-check but before app.py's persist_mutation CAS."""
    def reject(state):
        item=state['approvals'][0];uuid='rejected-uuid'
        item['native_binding']={'payload':{'open_id':'ou_pm','uuid':uuid},'creation_outcome':'not_created',
            'not_created_proof':'documented_api_rejection',
            'creation_rejection':{'http_status':400,'api_code':1390001,'uuid':uuid}}
    mutate_stored(live,reject)
    _,pv,_=snapshot(live)
    real=native_routes.creation_not_performed
    def racing(binding):
        mutate_stored(live,lambda state:state['projects'][0].__setitem__('name','changed by another writer'))
        return real(binding)
    monkeypatch.setattr(native_routes,'creation_not_performed',racing)
    before=snapshot(live)
    response=post(live,'abandon',project_version=pv)
    monkeypatch.undo()
    assert response.status_code==409
    after=snapshot(live)
    assert after[2]==before[2] and after[2][0]['status']!='withdrawn' and live.calls==[]
    assert after[1]==before[1]+1  # only the competing writer advanced the project
    # Re-reading the new project version lets the same operation through the real persist path.
    assert post(live,'abandon',project_version=after[1]).status_code==200
    assert snapshot(live)[2][0]['status']=='withdrawn'
