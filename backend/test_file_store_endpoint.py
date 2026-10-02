import pytest
from .test_backend import app,client,workspace
from .app import WorkspaceRow,BusinessRow
from . import storage


def upload(client):
    state=workspace(client);p=state['projects'][0];n=p['nodes'][0]
    response=client.post('/api/files',data={'project_id':p['id'],'node_id':n['id'],
        'direction':'input','version':state['version'],'category_id':'evidence'},
        files={'file':('evidence.txt',b'company evidence','text/plain')})
    assert response.status_code==200,response.text
    updated=next(item for item in response.json()['projects'] if item['id']==p['id'])
    return updated['files'][-1]['id']


def test_actual_endpoint_queues_once_and_never_relabels_existing_job(app,client):
    ident=upload(client)
    before=workspace(client)
    file=next(f for p in before['projects'] for f in p['files'] if f['id']==ident)
    assert file['auto_store_requested'] and file['remote_status']=='queued'
    assert len([j for j in before['jobs'] if j['key']=='file:'+ident])==1
    response=client.post('/api/files/'+ident+'/store-lark',json={'version':before['version']})
    assert response.status_code==409 and '背景工作' in response.json()['detail']
    after=workspace(client)
    assert after['version']==before['version'] and after['projects']==before['projects'] and after['jobs']==before['jobs']


@pytest.mark.parametrize('status,existing_job',[
    ('failed',True),('outcome_unknown',True),('blocked',True),('running',True),
    ('verified',True),('simulated',True),('failed',False),(None,True)])
def test_existing_remote_status_or_orphan_job_blocks_without_mutating_receipt(app,client,status,existing_job):
    ident=upload(client);wid=app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
    with app.state.sessions.begin() as db:
        row=db.get(WorkspaceRow,wid);state=storage.load(db,BusinessRow,row)
        p=next(p for p in state['projects'] if any(f['id']==ident for f in p['files']))
        f=next(f for f in p['files'] if f['id']==ident)
        state['jobs']=[j for j in state['jobs'] if j['key']!='file:'+ident]
        f.pop('remote_status',None)
        if status:f['remote_status']=status
        if existing_job:
            from .operations import queue
            job=queue(state,'file',state['users'][0],{'project_id':p['id'],'file_id':ident},'file:'+ident)
            job.update(status=status or 'outcome_unknown',error='原始結果待核對',steps=[{'key':'upload','receipt':{'file_token':'private-existing-token'}}])
        row.data=storage.save(db,BusinessRow,wid,state)
    before=workspace(client)
    response=client.post('/api/files/'+ident+'/store-lark',json={'version':before['version']})
    assert response.status_code==409 and '背景工作' in response.json()['detail']
    after=workspace(client)
    assert after['version']==before['version'] and after['projects']==before['projects'] and after['jobs']==before['jobs']
