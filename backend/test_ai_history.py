from sqlalchemy import select
from .test_ai_database import app, client, ai_database_url
from .test_ai_api import BODY, Fake, events
from .test_backend import role
from .ai.ledger import AiUsageRow, AiExchangeRow


def ask(app, client, ident, question='第一題'):
    app.state.ai_providers = {'claude':Fake()}
    return events(client.post('/api/ai/chat',json={**BODY,'conversation_id':ident,
        'messages':[{'role':'user','content':question}]}))[0]['usage_id']


def test_history_resume_pagination_and_delete(app,client):
    first = ask(app,client,'a','  第一題\n  問題 ')
    ask(app,client,'a','第二題')
    ask(app,client,'b')
    page = client.get('/api/ai/conversations?limit=1').json()
    assert page['history_available'] and page['items'][0]['id']=='b'
    assert page['next_cursor']
    second = client.get('/api/ai/conversations',params={'limit':1,'before':page['next_cursor']}).json()
    assert second['items'][0]['id']=='a' and second['items'][0]['turns']==2
    assert second['items'][0]['title']=='第一題 問題'
    detail = client.get('/api/ai/conversations/a').json()
    assert [m['role'] for m in detail['messages']]==['user','assistant','user','assistant']
    assert detail['messages'][0]['usage_id']==first
    assert client.get('/api/ai/conversations?before=bad').status_code==422
    for _ in range(2):
        assert client.delete('/api/ai/conversations/a').status_code==204
    assert client.get('/api/ai/conversations/a').status_code==404
    with app.state.sessions() as db:
        assert db.get(AiUsageRow,first) is not None
        assert db.get(AiExchangeRow,first) is None


def test_history_actor_workspace_disabled_retention(app,client):
    from datetime import datetime,timedelta,timezone
    original_id = client.get('/api/session').json()['user']['id']
    uid = ask(app,client,'private')
    role(client,'u-manager')
    assert client.get('/api/ai/conversations').json()['items']==[]
    assert client.get('/api/ai/conversations/private').status_code==404
    assert client.delete('/api/ai/conversations/private').status_code==204
    with app.state.sessions.begin() as db:
        row = db.get(AiExchangeRow,uid)
        assert row is not None
        row.workspace_id='other'
    role(client,original_id)
    assert client.get('/api/ai/conversations/private').status_code==404
    with app.state.sessions.begin() as db:
        row=db.get(AiExchangeRow,uid)
        row.workspace_id=db.get(AiUsageRow,uid).workspace_id
        row.created_at=datetime.now(timezone.utc)-timedelta(days=91)
    assert client.get('/api/ai/conversations').json()['items']==[]
    ask(app,client,'visible')
    app.state.ai_store_content=False
    assert client.get('/api/ai/conversations').json()==dict(history_available=False,items=[],next_cursor=None)
    assert client.get('/api/ai/conversations/visible').status_code==404
    assert client.delete('/api/ai/conversations/visible').status_code==204


def test_history_scope_conflict(app,client):
    ask(app,client,'global')
    response=client.post('/api/ai/chat',json={**BODY,'conversation_id':'global','project_id':'p1'})
    assert response.status_code==422


def test_delete_blocks_delayed_turn_content(app, client, monkeypatch):
    from .ai import ledger
    original = ledger.record
    def delayed(sessions, **values):
        ledger.delete_conversation(sessions, values['workspace_id'], values['actor_id'], values['conversation_id'])
        original(sessions, **values)
    monkeypatch.setattr(ledger, 'record', delayed)
    uid = ask(app, client, 'deleted-in-flight')
    with app.state.sessions() as db:
        assert db.get(AiUsageRow, uid) is not None
        assert db.get(AiExchangeRow, uid) is None
    assert client.get('/api/ai/conversations/deleted-in-flight').status_code == 404


def test_done_follows_delayed_queryable_write(app, client, monkeypatch):
    import time
    from .ai.agent import ChatRun
    from .ai import ledger
    original = ledger.record
    def delayed(*args, **kwargs):
        time.sleep(.03)
        original(*args, **kwargs)
    monkeypatch.setattr(ledger, 'record', delayed)
    original_stream = ChatRun.stream
    async def checked(run):
        async for event in original_stream(run):
            if '"type": "done"' in event:
                with app.state.sessions() as db:
                    assert db.get(AiExchangeRow, run.usage_id) is not None
            yield event
    monkeypatch.setattr(ChatRun, 'stream', checked)
    ask(app, client, 'done-visible')
