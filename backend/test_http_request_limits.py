import pytest
from .test_backend import app,client,workspace


def test_json_limit_rejects_before_action_and_has_no_side_effect(client):
    initial=workspace(client)
    response=client.post('/api/actions',content=b'{"payload":"'+b'x'*(513*1024)+b'"}',headers={'Content-Type':'application/json'})
    assert response.status_code==413
    assert workspace(client)['version']==initial['version']


def test_object_task_title_returns_422_without_poisoning_workspace(client):
    initial=workspace(client);p=initial['projects'][0];n=p['nodes'][0]
    response=client.post('/api/actions',json={'action':'task_add','version':initial['version'],
        'request_id':'invalid-title','project_id':p['id'],'node_id':n['id'],
        'payload':{'title':{'children':'crash'},'owner_id':'u-pm'}})
    assert response.status_code==422
    assert workspace(client)['version']==initial['version']


def test_upload_hash_is_stable_before_remote_job(client):
    import hashlib
    initial=workspace(client);p=initial['projects'][0];n=p['nodes'][0]
    response=client.post('/api/files',data={'project_id':p['id'],'node_id':n['id'],
        'direction':'input','version':initial['version'],'category_id':'evidence'},
        files={'file':('survey.txt',b'bytes for immutable scope','text/plain')})
    assert response.status_code==200,response.text
    project=next(x for x in response.json()['projects'] if x['id']==p['id'])
    document=project['files'][-1]
    assert document['sha256']==hashlib.sha256(b'bytes for immutable scope').hexdigest()
    assert document['remote_status']=='queued'
