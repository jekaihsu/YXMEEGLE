"""Review regressions: access provenance, permission epochs and bounded streaming."""
import time
import pytest
from sqlalchemy import select
from .test_ai_database import app, client, ai_database_url
from .test_ai_api import BODY, Fake, events, rows, wid, dataset_call
from .test_ai_project import project
from .test_backend import WorkspaceRow, BusinessRow, storage, role
from .ai.providers import Event
from .ai import ledger


def hide(app, client, pid):
    with app.state.sessions.begin() as db:
        root = db.get(WorkspaceRow, wid(app, client))
        state = storage.load(db, BusinessRow, root)
        next(p for p in state['projects'] if p['id'] == pid)['planning_origin'] = 'local'
        root.data = storage.save(db, BusinessRow, root.id, state)


def ask(app, client, ident, *, pid=None, calls=()):
    fake = Fake(calls=calls)
    app.state.ai_providers = {'claude':fake}
    response = client.post('/api/ai/chat', json={**BODY, 'conversation_id':ident, **({'project_id':pid} if pid else {})})
    return fake, response


def test_warm_context_revoke_new_conversation_never_bills(app, client):
    pid = project(client)
    _, response = ask(app, client, 'warm', pid=pid)
    assert events(response)[-1]['type'] == 'done'
    hide(app, client, pid)
    fake, response = ask(app, client, 'new-after-revoke', pid=pid)
    assert response.status_code == 403 and response.json()['code'] == 'ai_forbidden'
    assert fake.inputs == []
    assert [r.conversation_id for r in rows(app)] == ['warm']


def test_global_tool_case_reads_revoke_list_open_resume(app, client):
    pid = project(client)
    fake, response = ask(app, client, 'global-case', calls=[dataset_call('case-call','case_progress',{'case_id':pid})])
    uid = events(response)[0]['usage_id']
    assert len(fake.inputs) == 2
    assert client.get('/api/ai/conversations/global-case').status_code == 200
    with app.state.sessions() as db:
        refs = db.execute(select(ledger.AiCaseRead.project_id, ledger.AiCaseRead.tool_call_id).where(ledger.AiCaseRead.usage_id == uid)).all()
        assert (pid, 'case-call') in refs
    _, resumed = ask(app, client, 'global-case')
    resumed_uid = events(resumed)[0]['usage_id']
    with app.state.sessions() as db:
        assert pid in db.scalars(select(ledger.AiCaseRead.project_id).where(ledger.AiCaseRead.usage_id == resumed_uid)).all()
    hide(app, client, pid)
    assert client.get('/api/ai/conversations').json()['items'] == []
    assert client.get('/api/ai/conversations/global-case').status_code == 403
    fake, response = ask(app, client, 'global-case')
    assert response.status_code == 403 and fake.inputs == []


def test_permission_downgrade_denies_history_and_changes_context_key(app, client):
    pid = project(client)
    _, response = ask(app, client, 'privileged', pid=pid)
    uid = events(response)[0]['usage_id']
    with app.state.sessions() as db:
        assert db.get(ledger.AiUsageRow, uid).authz_version == 0
        assert db.get(ledger.AiUsageRow, uid).permission_key is not None
    actor = client.get('/api/session').json()['user']['id']
    with app.state.sessions.begin() as db:
        root = db.get(WorkspaceRow, wid(app, client))
        state = storage.load(db, BusinessRow, root)
        user = next(u for u in state['users'] if u['id'] == actor)
        user.update(role='member', authz_version=user.get('authz_version',0)+1)
        root.data = storage.save(db, BusinessRow, root.id, state)
    assert client.get('/api/ai/conversations',params={'scope':'project','project_id':pid}).json()['items'] == []
    assert client.get('/api/ai/conversations/privileged').status_code == 403
    _, response = ask(app, client, 'new-permissions', pid=pid)
    assert events(response)[-1]['type'] == 'done'
    assert len(app.state.ai_project_contexts.entries) == 2


@pytest.mark.parametrize('global_tool',[False,True])
def test_manager_hidden_content_redacted_in_audit_and_search(app, client, global_tool):
    role(client,'u-manager')
    pid = project(client)
    _, response = ask(app, client, 'audit-hidden', **(dict(calls=[dataset_call('audit-read','case_progress',{'case_id':pid})]) if global_tool else dict(pid=pid)))
    uid = events(response)[0]['usage_id']
    hide(app, client, pid)
    result = client.get('/api/ai/usage').json()
    assert result['totals']['questions'] == 1
    assert result['recent'][0]['question_preview'] is None
    detail = client.get(f'/api/ai/usage/{uid}/exchange').json()
    assert detail['question'] is None and detail['answer'] is None and detail['project_id'] is None
    export = client.get('/api/ai/usage/export').text
    assert '查詢公司資料' not in export and '查詢完成' not in export
    assert client.get('/api/ai/usage',params={'q':'查詢公司資料'}).json()['totals']['questions'] == 0


def test_legacy_global_rows_have_explicit_workspace_marker(app, client):
    from .test_ai_history_queries import seed_turn
    actor = client.get('/api/session').json()['user']['id']
    seed_turn(app.state.sessions,'legacy','legacy',workspace=wid(app,client),actor=actor)
    assert client.get('/api/ai/conversations/legacy').json()['authorization_basis'] == 'legacy_workspace'
    assert client.get('/api/ai/conversations').json()['items'][0]['authorization_basis'] == 'legacy_workspace'


def test_four_hundred_chunks_have_bounded_authorization(app, client, monkeypatch):
    from .ai import routes
    pid = project(client)
    with app.state.sessions.begin() as db:
        root = db.get(WorkspaceRow, wid(app, client))
        state = storage.load(db, BusinessRow, root)
        from copy import deepcopy
        for i in range(31-len(state['projects'])):
            clone = deepcopy(state['projects'][0]);clone.update(id=f'bench-{i}', nodes=[])
            for child in storage.PROJECT_CHILDREN: clone[child]=[]
            state['projects'].append(clone)
        root.data = storage.save(db, BusinessRow, root.id, state)
    _, response = ask(app, client, 'warm-throughput', pid=pid)
    events(response)
    original = routes.require_case
    checks = []
    def counted(*args):
        checks.append(1)
        return original(*args)
    monkeypatch.setattr(routes,'require_case',counted)
    class Chunks(Fake):
        async def stream(self,*args):
            for _ in range(400): yield Event('text','a')
            yield Event('stop', [{'type':'text','text':'a'*400}])
    app.state.ai_providers = {'claude':Chunks()}
    started = time.perf_counter()
    result = events(client.post('/api/ai/chat',json={**BODY,'conversation_id':'chunks','project_id':pid}))
    elapsed = time.perf_counter()-started
    assert sum(e['type']=='text' for e in result) == 400
    assert len(checks) <= 3, f'{len(checks)} case checks for 400 deltas'
    print(f'400 chunks: {elapsed:.4f}s; case checks={len(checks)}')


def test_single_case_check_is_one_indexed_authoritative_lookup(app, client):
    from sqlalchemy import event
    from .ai.history_authorization import require_case
    pid = project(client)
    workspace = wid(app, client)
    captured = []
    engine = app.state.sessions.kw['bind']
    def capture(conn,cursor,sql,params,*args): captured.append((sql,params))
    event.listen(engine,'before_cursor_execute',capture)
    try:
        require_case(app.state.sessions,workspace,pid,app.state.cfg)
    finally:
        event.remove(engine,'before_cursor_execute',capture)
    assert len(captured) == 1
    assert 'business_records.entity_id IN' in captured[0][0]
    parameters = captured[0][1]
    assert pid in (parameters.values() if isinstance(parameters,dict) else parameters)


def test_session_expired_at_completion_starts_login_flow(app, client, monkeypatch):
    from fastapi import HTTPException
    from .ai.agent import ChatRun
    original = ChatRun.stream
    async def expire_at_done(run):
        authorize = run.authorize
        async def checked(force=False):
            if force and run.answer:
                raise HTTPException(401,'expired')
            await authorize(force=force)
        run.authorize = checked
        async for event in original(run): yield event
    monkeypatch.setattr(ChatRun,'stream',expire_at_done)
    _, response = ask(app,client,'expired-stream')
    result = events(response)
    assert result[0]['type'] == 'start'
    assert result[-1] == {'type':'error','code':'session_expired'}
    assert not any(e.get('code') == 'ai_forbidden' or e['type'] == 'done' for e in result)


def test_global_dependency_revoke_during_stream_is_checked_at_two_seconds(app, client, monkeypatch):
    from .ai import routes
    pid = project(client)
    clock = [routes.monotonic()]
    monkeypatch.setattr(routes,'monotonic',lambda:clock[0])
    class Revoking(Fake):
        async def stream(self,*args):
            if len(self.inputs) == 1:
                hide(app,client,pid)
                clock[0] += 2.01
            async for event in super().stream(*args): yield event
    app.state.ai_providers = {'claude':Revoking(calls=[dataset_call('read-case','case_progress',{'case_id':pid})])}
    result = events(client.post('/api/ai/chat',json={**BODY,'conversation_id':'revoke-tool-stream'}))
    assert result[-1] == {'type':'error','code':'ai_forbidden','denial_scope':'conversation'}
    assert not any(e['type'] == 'text' or e['type'] == 'done' for e in result)
