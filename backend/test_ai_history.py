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


def test_history_latest_200_messages(app, client):
    from datetime import timedelta
    uid = ask(app, client, 'long')
    with app.state.sessions.begin() as db:
        usage = db.get(AiUsageRow, uid)
        content = db.get(AiExchangeRow, uid)
        for i in range(1, 105):
            values = {c.name:getattr(usage, c.name) for c in AiUsageRow.__table__.columns}
            values.update(id=f'long-{i:03}', created_at=usage.created_at+timedelta(seconds=i))
            db.add(AiUsageRow(**values))
            db.add(AiExchangeRow(usage_id=values['id'], workspace_id=usage.workspace_id,
                actor_id=usage.actor_id, question=f'q{i}', answer=f'a{i}', tool_names='[]', created_at=values['created_at']))
    result = client.get('/api/ai/conversations/long').json()
    assert len(result['messages']) == 200 and result['truncated']
    assert result['messages'][0]['content'] == 'q5'
    assert result['messages'][-1]['content'] == 'a104'


def test_generation_failure_releases_slot_and_runs_in_worker(app, client, monkeypatch):
    import threading
    from .ai import ledger
    from .ai.agent import ChatRun
    original = ledger.conversation_generation
    event_threads = []
    async def stream(run):
        event_threads.append(threading.get_ident())
        async for item in original_stream(run):
            yield item
    original_stream = ChatRun.stream
    monkeypatch.setattr(ChatRun, 'stream', stream)
    workers = []
    def failing(*args):
        workers.append(threading.get_ident())
        if len(workers) <= 2:
            raise RuntimeError('database locked')
        return original(*args)
    monkeypatch.setattr(ledger, 'conversation_generation', failing)
    app.state.ai_providers = {'claude': Fake()}
    for _ in range(2):
        with __import__('pytest').raises(RuntimeError, match='database locked'):
            client.post('/api/ai/chat', json=BODY)
    assert events(client.post('/api/ai/chat', json=BODY))[-1]['type'] == 'done'
    assert event_threads[0] not in workers


def test_unknown_delete_does_not_create_generations(app, client):
    from .ai.ledger import AiConversationGeneration
    for i in range(5):
        assert client.delete(f'/api/ai/conversations/unknown-{i}').status_code == 204
    with app.state.sessions() as db:
        assert db.scalars(select(AiConversationGeneration)).all() == []


def test_cleanup_preserves_active_fence_then_prunes(app, client, monkeypatch):
    from .ai import ledger
    uid = ask(app, client, 'expired')
    with app.state.sessions() as db:
        usage = db.get(AiUsageRow, uid)
        key = (usage.workspace_id, usage.actor_id, usage.conversation_id)
    generation = ledger.conversation_generation(app.state.sessions, *key)
    ledger.delete_conversation(app.state.sessions, *key)
    monkeypatch.setattr(ledger, '_last_cleanup', None)
    ledger.cleanup_content(app.state.sessions, 0)
    with app.state.sessions() as db:
        row = db.get(ledger.AiConversationGeneration, key)
        assert row.generation != generation and row.active_runs == 1
    ledger.release_conversation(app.state.sessions, *key)
    from datetime import datetime, timedelta, timezone
    with app.state.sessions.begin() as db:
        db.get(ledger.AiConversationGeneration, key).last_activity_at = datetime.now(timezone.utc) - timedelta(minutes=11)
    monkeypatch.setattr(ledger, '_last_cleanup', None)
    ledger.cleanup_content(app.state.sessions, 0)
    with app.state.sessions() as db:
        assert db.get(ledger.AiConversationGeneration, key) is None


def test_cleanup_reclaims_crashed_run_but_preserves_live_fence(app, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from .ai import ledger
    sessions = app.state.sessions
    crashed = ('w', 'a', 'crashed')
    live = ('w', 'a', 'live')
    old = datetime.now(timezone.utc) - timedelta(hours=25)
    ledger.conversation_generation(sessions, *crashed)
    ledger.conversation_generation(sessions, *live)
    with sessions.begin() as db:
        row = db.get(ledger.AiConversationGeneration, crashed)
        row.last_activity_at = old
    ledger.delete_conversation(sessions, *live)
    monkeypatch.setattr(ledger, '_last_cleanup', None)
    ledger.cleanup_content(sessions, 0)
    with sessions() as db:
        assert db.get(ledger.AiConversationGeneration, crashed) is None
        row = db.get(ledger.AiConversationGeneration, live)
        assert (row.generation, row.active_runs) == (1, 1)
    with sessions.begin() as db:
        db.get(ledger.AiConversationGeneration, live).last_activity_at = old
    ledger.conversation_generation(sessions, *live)
    ledger.release_conversation(sessions, *live)
    monkeypatch.setattr(ledger, '_last_cleanup', None)
    ledger.cleanup_content(sessions, 0)
    with sessions() as db:
        row = db.get(ledger.AiConversationGeneration, live)
        assert (row.generation, row.active_runs) == (1, 1)


def test_release_failure_does_not_change_completed_answer(app, client, monkeypatch, caplog):
    from .ai import ledger

    def fail_release(*args):
        raise RuntimeError('private database details')

    monkeypatch.setattr(ledger, 'release_conversation', fail_release)
    monkeypatch.setattr(ledger, 'schedule_cleanup', lambda *args: None)
    app.state.ai_providers = {'claude': Fake()}
    result = events(client.post('/api/ai/chat', json=BODY))
    assert [e['type'] for e in result] == ['start', 'text', 'text', 'done']
    uid = result[0]['usage_id']
    with app.state.sessions() as db:
        usage = db.get(AiUsageRow, uid)
        assert usage.status == 'ok'
        assert db.get(AiExchangeRow, uid).answer == '截至目前，查詢完成'
    assert 'ai_finish_write_failed' in caplog.text
    assert 'private database details' not in caplog.text
    result = events(client.post('/api/ai/chat', json={**BODY, 'conversation_id': 'next'}))
    assert result[-1]['type'] == 'done'


def test_cleanup_grace_protects_recent_and_legacy_worker_rows(app, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from .ai import ledger
    sessions = app.state.sessions
    recent, idle, legacy = [('w', 'a', name) for name in ('recent', 'idle', 'legacy')]
    for key in (recent, idle):
        ledger.conversation_generation(sessions, *key)
        ledger.release_conversation(sessions, *key)
    with sessions.begin() as db:
        db.get(ledger.AiConversationGeneration, recent).last_activity_at = datetime.now(timezone.utc) - timedelta(minutes=9)
        db.get(ledger.AiConversationGeneration, idle).last_activity_at = datetime.now(timezone.utc) - timedelta(minutes=11)
        db.connection().exec_driver_sql("INSERT INTO ai_conversation_generation (workspace_id, actor_id, conversation_id, generation, active_runs) VALUES ('w', 'a', 'legacy', 2, 0)")
    monkeypatch.setattr(ledger, '_last_cleanup', None)
    ledger.cleanup_content(sessions, 0)
    with sessions() as db:
        assert db.get(ledger.AiConversationGeneration, idle) is None
        assert db.get(ledger.AiConversationGeneration, recent).active_runs == 0
        assert db.get(ledger.AiConversationGeneration, legacy).generation == 2


def test_populated_history_api_bound_without_provider(app, client):
    from .test_ai_history_queries import seed_turn
    session = client.get('/api/session').json()
    workspace = app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
    actor = session['user']['id']
    class ForbiddenProvider:
        def stream(self, *args, **kwargs):
            raise AssertionError('history must never call a provider')
    app.state.ai_providers = {'claude': ForbiddenProvider(), 'gpt': ForbiddenProvider()}
    for i in range(101):
        seed_turn(app.state.sessions, f'history-{i:03}', f'history-{i:03}', workspace=workspace, actor=actor)
    response = client.get('/api/ai/conversations?limit=100')
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    page = response.json()
    assert len(page['items']) == 100 and page['next_cursor']
    rest = client.get('/api/ai/conversations', params={'limit':100, 'before':page['next_cursor']}).json()
    assert len(rest['items']) == 1 and rest['next_cursor'] is None
    assert client.get('/api/ai/conversations?limit=101').status_code == 422
    assert client.get('/api/ai/conversations?limit=0').status_code == 422
