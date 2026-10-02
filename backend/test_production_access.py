import time
from datetime import datetime, timezone
from copy import deepcopy
from fastapi.testclient import TestClient
from sqlalchemy import select
from .app import create_app, WorkspaceRow, PersonRow, AuthRow, AuditRow, BusinessRow
from .seed import seed
from .policy import upgrade
from . import storage
from .production_access import admitted


def company(tmp_path):
    app=create_app({'DATABASE_URL':f'sqlite:///{tmp_path}/company.db','UPLOAD_DIR':str(tmp_path/'uploads'),
                    'DEMO_MODE':'false','APP_ENV':'development','LARK_APP_ID':'app1','LARK_APP_SECRET':'unused',
                    'LARK_REDIRECT_URI':'https://example.test/api/auth/lark/callback','LARK_ALLOWED_TENANTS':'company',
                    'LARK_WORKER_ORGANIZATION':'company'})
    state=upgrade(seed()); state['environment']='production'
    for u in state['users']:
        u.update(identity_app_id='app1',directory_status='employed',directory_missing=False,directory_last_seen_at=datetime.now(timezone.utc).isoformat(),
                 directory_source={'app_id':'app1','record_id':'rec-'+u['id']})
    with app.state.sessions.begin() as db:
        for wid in ('lark-company','test-lark-company'):
            s=deepcopy(state); s['environment']='test' if wid.startswith('test-') else 'production'
            row=WorkspaceRow(id=wid,version=1,data=s); db.add(row); db.flush()
            row.data=storage.save(db,BusinessRow,wid,s)
        for u in state['users']: db.add(PersonRow(organization_id='lark-company',person_id=u['id'],data=u))
        db.add(AuthRow(id='sid',data={'wid':'test-lark-company','expires':time.time()+3600}))
    client=TestClient(app)
    client.cookies.set('meegle_session',app.state.signer.dumps({'mode':'lark','sid':'sid','wid':'test-lark-company','organization':'lark-company','uid':'u-manager'}))
    return app,client


def test_test_people_changes_never_mutate_formal_directory(tmp_path):
    app,c=company(tmp_path)
    ws=c.get('/api/workspace').json()
    r=c.post('/api/actions',json={'action':'admin_person','version':ws['version'],'request_id':'disable-test',
           'payload':{'id':'u-field','active':False}})
    assert r.status_code==200,r.text
    with app.state.sessions() as db:
        assert db.get(PersonRow,('lark-company','u-field')).data['active'] is True
        assert db.get(PersonRow,('test-lark-company','u-field')).data['active'] is False
    assert c.post('/api/workspace/switch',json={'environment':'production'}).status_code==200
    assert next(u for u in c.get('/api/workspace').json()['users'] if u['id']=='u-field')['active'] is True


def test_disabling_formal_identity_revokes_existing_test_session(tmp_path):
    app,c=company(tmp_path)
    with app.state.sessions.begin() as db:
        p=db.get(PersonRow,('lark-company','u-manager')); p.data={**p.data,'directory_missing':True}
    assert c.get('/api/workspace').status_code==403
    assert c.get('/api/session').json()['user'] is None


def test_session_hides_private_employee_data_without_deleting_it(tmp_path):
    app,c=company(tmp_path)
    with app.state.sessions.begin() as db:
        p=db.get(PersonRow,('lark-company','u-manager'))
        p.data={**p.data,'attendance_identity':{'employee_id':'PRIVATE_EMPLOYEE'},
                'salary_amount':'PRIVATE_SALARY','private_notes':'PRIVATE_NOTE'}
    response=c.get('/api/session')
    assert response.status_code==200
    for marker in ('PRIVATE_EMPLOYEE','PRIVATE_SALARY','PRIVATE_NOTE'):
        assert marker not in response.text
    with app.state.sessions() as db:
        assert db.get(PersonRow,('lark-company','u-manager')).data['attendance_identity']['employee_id']=='PRIVATE_EMPLOYEE'


def test_admission_rejects_unknown_left_wrong_app_and_missing():
    person={'active':True,'identity_app_id':'app1','directory_status':'employed',
            'directory_source':{'app_id':'app1','record_id':'r'}}
    assert admitted(person,'app1')
    assert not admitted({'active':True,'directory_status':'employed','directory_source':{'record_id':'r'}},None)
    for change in ({'active':False},{'directory_missing':True},{'directory_status':'unknown'},
                   {'directory_status':'left'},{'identity_app_id':'other'},{'directory_source':{}}):
        assert not admitted({**person,**change},'app1')


def test_audit_receipt_idempotent_and_denied_is_recorded(tmp_path):
    app,c=company(tmp_path)
    version=c.get('/api/workspace').json()['version']
    body={'action':'file_category_save','version':version,'request_id':'category1','payload':{'id':'cad','name':'CAD 圖檔','active':True}}
    assert c.post('/api/actions',json=body).status_code==200
    assert c.post('/api/actions',json=body).status_code==200
    body.update(request_id='bad',payload={'id':'other','name':'其他','active':False},version=version+1)
    assert c.post('/api/actions',json=body).status_code==422
    with app.state.sessions() as db:
        audits=list(db.scalars(select(AuditRow)))
        assert [a.data['result'] for a in audits].count('success')==1
        assert [a.data['result'] for a in audits].count('denied')==1


def test_event_history_is_append_only_and_old_ordinals_stay_stable(tmp_path):
    app,c=company(tmp_path)
    with app.state.sessions.begin() as db:
        row=db.get(WorkspaceRow,'lark-company'); s=storage.load(db,BusinessRow,row)
        old=list(db.scalars(select(BusinessRow).where(BusinessRow.workspace_id==row.id,BusinessRow.kind=='events')))
        ordinals={r.entity_id:r.ordinal for r in old}
        s['events']=[{'id':'new-event','action':'test'}]
        row.data=storage.save(db,BusinessRow,row.id,s)
    with app.state.sessions() as db:
        after={r.entity_id:r.ordinal for r in db.scalars(select(BusinessRow).where(BusinessRow.workspace_id=='lark-company',BusinessRow.kind=='events'))}
        assert all(after[k]==v for k,v in ordinals.items())
        assert after['new-event']<min(ordinals.values(),default=0)
