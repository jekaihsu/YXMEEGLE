from fastapi.testclient import TestClient
from .app import create_app


def test_unrelated_case_write_does_not_reject_valid_case_revision(tmp_path):
    app=create_app({'DATABASE_URL':f'sqlite:///{tmp_path}/versions.db','UPLOAD_DIR':str(tmp_path/'files'),'DEMO_MODE':'true'})
    c=TestClient(app); c.get('/api/session'); ws=c.get('/api/workspace').json()
    a,b=ws['projects'][:2]
    def comment(p,request):
        return c.post('/api/actions',json={'action':'comment_add','project_id':p['id'],
            'version':ws['version'],'request_id':request,'project_versions':{p['id']:p['concurrency_version']},
            'payload':{'body':'Concurrency acceptance','mentions':[]}})
    first=comment(b,'b'); assert first.status_code==200,first.text
    second=comment(a,'a'); assert second.status_code==200,second.text
    assert comment(a,'same-a-stale').status_code==409
    assert comment(a,'a').status_code==200  # same receipt is safe after version advances


def test_global_mutation_cannot_use_unrelated_case_revision(tmp_path):
    app=create_app({'DATABASE_URL':f'sqlite:///{tmp_path}/global.db','UPLOAD_DIR':str(tmp_path/'files'),'DEMO_MODE':'true'})
    c=TestClient(app); c.get('/api/session'); c.post('/api/demo/session',json={'user_id':'u-manager'})
    ws=c.get('/api/workspace').json(); p=ws['projects'][0]
    body={'action':'file_category_save','version':ws['version'],'request_id':'one','payload':{'id':'cad','name':'CAD'}}
    assert c.post('/api/actions',json=body).status_code==200
    body.update(request_id='two',project_id=p['id'],project_versions={p['id']:p['concurrency_version']})
    assert c.post('/api/actions',json=body).status_code==409
