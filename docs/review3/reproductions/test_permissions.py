from backend.test_public_case_http_boundaries import isolated_http
from backend.operations import apply_operation
from backend.policy import upgrade
from backend.seed import seed
from backend.app import WorkspaceRow,BusinessRow
from backend import storage
from backend.workflow import now
from backend.production_access import access_mode
import json


def test_deploy_assets_mismatch_returns_success_exit(monkeypatch,tmp_path):
    from scripts import deploy_verify
    (tmp_path/'frontend/dist').mkdir(parents=True)
    (tmp_path/'frontend/dist/index.html').write_text('<script src="/assets/new.js"></script>',encoding='utf-8')
    class Response:
        status_code=200
        text='<script src="/assets/old.js"></script>'
        def raise_for_status(self): pass
        def json(self): return {'database':'postgresql'}
    class Client:
        def __init__(self,*args,**kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def get(self,*args,**kwargs): return Response()
    monkeypatch.setattr(deploy_verify,'ROOT',tmp_path)
    monkeypatch.setattr(deploy_verify,'RUNTIME',tmp_path)
    monkeypatch.setattr(deploy_verify.httpx,'Client',Client)
    monkeypatch.setattr('sys.argv',['deploy_verify.py','assets'])
    assert deploy_verify.main() is None
    report=json.loads((tmp_path/'zeabur-verification-assets.json').read_text())
    assert report['checks']['latest_frontend_assets'] is False


def test_bootstrap_manager_demotion_denies_fresh_employed_member():
    state=upgrade(seed());state['environment']='demo'
    manager=next(u for u in state['users'] if u['id']=='u-manager')
    person=next(u for u in state['users'] if u['id']=='u-control')
    person.update(role='manager',bootstrap_admin=True,identity_app_id='synthetic-app',
        directory_status='employed',directory_missing=False,
        directory_source={'app_id':'synthetic-app','record_id':'synthetic-record'},
        directory_last_seen_at=now())
    assert access_mode(person,'synthetic-app')=='normal'
    apply_operation(state,manager,{'action':'admin_person','payload':{'id':person['id'],'role':'member','active':True}},True)
    assert person['active'] and person['directory_status']=='employed'
    assert access_mode(person,'synthetic-app')=='denied'
    ordinary=dict(person);ordinary.pop('bootstrap_admin')
    assert access_mode(ordinary,'synthetic-app')=='normal'


def test_quote_review_retains_vote_from_replaced_pm():
    state=upgrade(seed());state['environment']='demo'
    project=state['projects'][0]
    project.update(pm_id='u-pm',sales_id='u-field',quotes=[{'id':'synthetic-quote','amount':100}])
    def act(ident,action,payload):
        return apply_operation(state,next(u for u in state['users'] if u['id']==ident),
            {'action':action,'project_id':project['id'],'payload':payload},True)
    act('u-pm','quote_review',{'quote_id':'synthetic-quote','classification':'effective','seat':'pm'})
    act('u-manager','project_roles',{'pm_id':'u-control','reason':'synthetic PM change'})
    assert project['pm_id']=='u-control'
    act('u-field','quote_review',{'quote_id':'synthetic-quote','classification':'effective','seat':'sales'})
    review=project['quote_reviews'][0]
    assert review['status']=='approved'
    assert not any(v['actor_id']=='u-control' for v in review['votes'])
    assert any(v['actor_id']=='u-pm' and not v.get('invalidated') for v in review['votes'])


def test_pilot_copy_retains_local_file_metadata_but_missing_bytes(isolated_http):
    app,client,state,signin=isolated_http
    signin('u-pm')
    upload=client.post('/api/files',data={'project_id':'p2','direction':'evidence','version':state['version']},
        files={'file':('synthetic-pilot.txt',b'synthetic pilot attachment','text/plain')})
    assert upload.status_code==200,upload.text
    project=next(p for p in upload.json()['projects'] if p['id']=='p2')
    document=next(f for f in project['files'] if f['name']=='synthetic-pilot.txt')
    assert client.get(document['url']).status_code==200
    signin('u-manager')
    copy=client.post('/api/pilot/copy',json={'project_id':'p2'})
    assert copy.status_code==200,copy.text
    switch=client.post('/api/workspace/switch',json={'environment':'test'})
    assert switch.status_code==200,switch.text
    ws=client.get('/api/workspace').json()
    copied=next(p for p in ws['projects'] if p['id']=='p2')
    assert any(f['id']==document['id'] and f['storage']=='local' for f in copied['files'])
    download=client.get(document['url'])
    assert download.status_code==404,download.text
