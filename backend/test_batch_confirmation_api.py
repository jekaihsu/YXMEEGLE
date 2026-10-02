"""Real local API transaction + idempotency, not a mocked frontend route."""
from .test_backend import app,client,workspace,act,role


def item(ws,ident,output='已核對並交付本人項目'):
    p=next(p for p in ws['projects'] if p['id']=='p1'); n=next(n for n in p['nodes'] if n['id']=='p1-control'); t=next(t for t in n['tasks'] if t['id']==ident)
    return dict(project_id=p['id'],node_id=n['id'],task_id=t['id'],revision=t['revision'],confirmation_hash=t['confirmation_hash'],output=output)


def test_bulk_confirmation_api_replay_never_duplicates_task_confirmation(client):
    role(client,'u-control'); state=workspace(client)
    payload={'items':[item(state,'p1-control-t1')]}; before_version=state['version']
    first=act(client,'task_batch_complete',payload,request_id='batch-exactly-once')
    assert first.status_code==200,first.text
    replay=act(client,'task_batch_complete',payload,request_id='batch-exactly-once',version=before_version)
    assert replay.status_code==200,replay.text
    task=next(t for n in replay.json()['projects'][0]['nodes'] for t in n['tasks'] if t['id']=='p1-control-t1')
    assert task['status']=='completed' and len(task['confirmations'])==1
    assert replay.json()['version']==first.json()['version']
    assert act(client,'task_batch_complete',{'items':[item(state,'p1-control-t1','換一份成果')]},request_id='batch-exactly-once').status_code==409


def test_bulk_confirmation_api_rolls_back_valid_item_when_second_item_is_not_started(client):
    role(client,'u-control'); state=workspace(client)
    payload={'items':[item(state,'p1-control-t1'),item(state,'p1-control-t2')]}
    response=act(client,'task_batch_complete',payload)
    assert response.status_code==409,response.text
    after=workspace(client); task=next(t for n in after['projects'][0]['nodes'] for t in n['tasks'] if t['id']=='p1-control-t1')
    assert task['status']=='in_progress' and not task.get('confirmations')
