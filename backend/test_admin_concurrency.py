from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from . import storage
from .app import AuditRow, BusinessRow, WorkspaceRow, create_app


@pytest.fixture
def admin(tmp_path):
    app=create_app({'DATABASE_URL':f'sqlite:///{tmp_path}/admin.db','UPLOAD_DIR':str(tmp_path/'files'),'DEMO_MODE':'true'})
    client=TestClient(app)
    client.get('/api/session')
    client.post('/api/demo/session',json={'user_id':'u-manager'})
    yield app,client
    app.state.engine.dispose()


def bump(app):
    with app.state.sessions.begin() as db:
        row=db.scalar(select(WorkspaceRow))
        state=storage.load(db,BusinessRow,row)
        state['background_tick']=state.get('background_tick',0)+1
        state['version']=row.version+1
        root=storage.save(db,BusinessRow,row.id,state)
        db.execute(update(WorkspaceRow).where(WorkspaceRow.id==row.id,WorkspaceRow.version==row.version).values(version=state['version'],data=root))


def command(ws,action,payload,request_id='save'):
    revisions=ws.get('admin_revisions',{})
    expected={'person':revisions.get('people',{}).get(payload['id'],'missing')} if action=='admin_person' else {k:revisions.get('settings',{}).get(k,'missing') for k in payload}
    return dict(action=action,payload=payload,version=ws['version'],request_id=request_id,entity_versions=expected)


@pytest.mark.parametrize('action,payload',[
    ('admin_person',{'id':'u-field','capabilities':['sop_task_import','create_local_case','sop_template_publish']}),
    ('admin_settings',{'external_enabled':True}),
])
def test_background_bump_reload_and_receipt(admin,action,payload):
    app,c=admin
    ws=c.get('/api/workspace').json()
    body=command(ws,action,payload)
    bump(app)
    response=c.post('/api/actions',json=body)
    assert response.status_code==200,response.text
    assert response.json()['version']==ws['version']+2
    replay=c.post('/api/actions',json=body)
    assert replay.status_code==200,replay.text
    assert replay.json()['version']==response.json()['version']
    with app.state.sessions() as db:
        rows=list(db.scalars(select(AuditRow).where(AuditRow.action==action)))
        assert len(rows)==1
        state=storage.load(db,BusinessRow,db.scalar(select(WorkspaceRow)))
        assert len([e for e in state['events'] if e['action']==action])==1
        if action=='admin_person':
            assert next(u for u in state['users'] if u['id']=='u-field')['capabilities']==payload['capabilities']
        else:
            assert state['settings']['external_enabled'] is True
    fresh=c.get('/api/workspace').json()
    bump(app)
    body=command(fresh,action,payload,'after-reload')
    assert c.post('/api/actions',json=body).status_code==200


def test_two_managers_same_person_conflict_even_after_refresh(admin):
    _,c=admin
    ws=c.get('/api/workspace').json()
    first=command(ws,'admin_person',{'id':'u-field','name':'First manager'})
    second=command(ws,'admin_person',{'id':'u-field','name':'Second manager'},'second')
    assert c.post('/api/actions',json=first).status_code==200
    second['version']=c.get('/api/workspace').json()['version']
    response=c.post('/api/actions',json=second)
    assert response.status_code==409,response.text
    assert next(u for u in c.get('/api/workspace').json()['users'] if u['id']=='u-field')['name']=='First manager'


def test_settings_conflict_only_on_submitted_keys(admin):
    _,c=admin
    ws=c.get('/api/workspace').json()
    first=command(ws,'admin_settings',{'external_enabled':True})
    unrelated=command(ws,'admin_settings',{'drive_root':'local-only'},'unrelated')
    conflict=command(ws,'admin_settings',{'external_enabled':False},'conflict')
    assert c.post('/api/actions',json=first).status_code==200
    assert c.post('/api/actions',json=unrelated).status_code==200
    assert c.post('/api/actions',json=conflict).status_code==409


def test_legacy_and_unrelated_actions_remain_strict(admin):
    app,c=admin
    ws=c.get('/api/workspace').json()
    bump(app)
    body=command(ws,'admin_person',{'id':'u-field','name':'Legacy'})
    body.pop('entity_versions')
    assert c.post('/api/actions',json=body).status_code==409
    body.update(action='file_category_save',payload={'id':'cad','name':'CAD'},entity_versions={'person':'fake'})
    assert c.post('/api/actions',json=body).status_code==409


def test_authority_rechecked_and_receipt_fingerprint_ignores_revision(admin):
    app,c=admin
    ws=c.get('/api/workspace').json()
    body=command(ws,'admin_person',{'id':'u-field','name':'Saved'})
    assert c.post('/api/actions',json=body).status_code==200
    refreshed=c.get('/api/workspace').json()
    retry=command(refreshed,'admin_person',body['payload'])
    assert c.post('/api/actions',json=retry).status_code==200
    c.post('/api/demo/session',json={'user_id':'u-field'})
    denied=command(refreshed,'admin_person',{'id':'u-field','capabilities':['manage_people']},'denied')
    denied['entity_versions']={'person':'fake'}
    assert c.post('/api/actions',json=denied).status_code in (403,409)
