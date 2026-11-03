"""Final review: live report grants, daily-note scope and safe startup work."""
import pytest
import httpx
from sqlalchemy import select,event,create_engine,text,delete,inspect
from sqlalchemy.exc import DBAPIError,OperationalError
from .test_ai_database import app,client,ai_database_url
from .test_ai_api import BODY,Fake,events,wid,dataset_call
from .test_ai_project import project
from .test_ai_authorization_review import ask,hide
from .test_backend import WorkspaceRow,BusinessRow,storage
from .ai import ledger


def set_report_member(app,client,department):
    actor=client.get('/api/session').json()['user']['id']
    with app.state.sessions.begin() as db:
        root=db.get(WorkspaceRow,wid(app,client));state=storage.load(db,BusinessRow,root)
        next(u for u in state['users'] if u['id']==actor).update(role='member',department=department,capabilities=[])
        root.data=storage.save(db,BusinessRow,root.id,state)


def report_response(monkeypatch):
    original=httpx.AsyncClient.get
    async def read(self,path,**kwargs):
        if path=='/api/reports/sales':
            return httpx.Response(200,json={'items':[dict(code='HISTORIC',name='Report case')],'total':1},request=httpx.Request('GET','http://ai.internal'+path))
        return await original(self,path,**kwargs)
    monkeypatch.setattr(httpx.AsyncClient,'get',read)


def test_report_grant_loss_denies_list_open_resume_without_affecting_ordinary_history(app,client,monkeypatch):
    report_response(monkeypatch);set_report_member(app,client,'工務助理')
    _,response=ask(app,client,'ordinary');events(response)
    _,response=ask(app,client,'report-access',calls=[dataset_call('report','report_sales',{})]);assert events(response)[-1]['type']=='done'
    assert client.get('/api/ai/conversations/report-access').status_code==200
    set_report_member(app,client,'其他部門')
    assert [item['id'] for item in client.get('/api/ai/conversations').json()['items']]==['ordinary']
    denied=client.get('/api/ai/conversations/report-access')
    assert denied.status_code==403 and denied.json()['denial_scope']=='conversation'
    fake,response=ask(app,client,'report-access')
    assert response.status_code==403 and fake.inputs==[]
    assert client.get('/api/ai/conversations/ordinary').status_code==200


def test_report_grant_loss_stops_stream_at_revocation_bound(app,client,monkeypatch):
    from .ai import routes
    report_response(monkeypatch);set_report_member(app,client,'工務助理')
    clock=[routes.monotonic()];monkeypatch.setattr(routes,'monotonic',lambda:clock[0])
    class Moving(Fake):
        async def stream(self,*args):
            if len(self.inputs)==1:
                set_report_member(app,client,'其他部門')
                clock[0]+=routes.STREAM_REVOCATION_BOUND_SECONDS+0.01
            async for value in super().stream(*args): yield value
    app.state.ai_providers={'claude':Moving(calls=[dataset_call('report','report_sales',{})])}
    result=events(client.post('/api/ai/chat',json={**BODY,'conversation_id':'report-stream'}))
    assert result[-1]=={'type':'error','code':'ai_forbidden','denial_scope':'conversation'}
    assert not any(e['type'] in ('text','done') for e in result)


def test_daily_report_case_code_search_records_the_returned_case(app,client):
    pid=project(client)
    with app.state.sessions() as db: code=db.get(BusinessRow,(wid(app,client),'projects',pid)).data['code']
    _,response=ask(app,client,'daily-note',calls=[dataset_call('daily','daily_reports',{'q':code})]);uid=events(response)[0]['usage_id']
    with app.state.sessions() as db:
        assert pid in db.scalars(select(ledger.AiCaseRead.project_id).where(ledger.AiCaseRead.usage_id==uid)).all()
    hide(app,client,pid)
    assert client.get('/api/ai/conversations/daily-note').status_code==403


def test_daily_report_observer_bounds_returned_page_to_one_hundred():
    from .ai.read_provenance import case_reads,workspace_reads,observed
    refs=set();markers=set();a=case_reads.set(refs.add);b=workspace_reads.set(markers.add)
    try: observed('/api/daily-reports',{'items':[{'project_id':f'p{i}'} for i in range(120)]})
    finally: case_reads.reset(a);workspace_reads.reset(b)
    assert refs=={f'p{i}' for i in range(100)} and markers=={'daily_reports'}


def test_manager_revoked_changes_permission_key_without_display_fields():
    from .ai.history_authorization import permission_key
    user=dict(role='manager',capabilities=['manage_people'],active=True,permission_version=4)
    assert permission_key(user)=='650cecf9583944005eef4e2e30851ce9af99756022732436f3e0a5324eb3fc7f'
    assert permission_key(user)!=permission_key({**user,'manager_revoked':True})
    assert permission_key(user)==permission_key({**user,'manager_revoked':False,'name':'Updated','department':'Other'})


def test_backfill_does_not_scan_audit_rows_after_completion(tmp_path):
    engine=create_engine('sqlite:///'+str(tmp_path/'once.db'));ledger.ensure_schema(engine)
    statements=[]
    def record(conn,cursor,sql,*args): statements.append(sql.lower())
    event.listen(engine,'before_cursor_execute',record)
    try: ledger.ensure_schema(engine)
    finally: event.remove(engine,'before_cursor_execute',record)
    assert not any('from ai_case_read' in sql or 'join ai_case_read' in sql for sql in statements)
    engine.dispose()


def test_postgres_invalid_usage_index_is_repaired_nonfatally(app,client):
    engine=app.state.sessions.kw['bind']
    if engine.dialect.name!='postgresql': pytest.skip('PostgreSQL concurrent indexes')
    from .test_ai_history_queries import seed_turn
    seed_turn(app.state.sessions,'dup-one','same');seed_turn(app.state.sessions,'dup-two','same')
    with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as db:
        db.exec_driver_sql('DROP INDEX CONCURRENTLY IF EXISTS ix_ai_usage_conversation')
        with pytest.raises(DBAPIError): db.exec_driver_sql('CREATE UNIQUE INDEX CONCURRENTLY ix_ai_usage_conversation ON ai_usage (conversation_id)')
        assert db.scalar(text("SELECT indisvalid FROM pg_index WHERE indexrelid=to_regclass('ix_ai_usage_conversation')")) is False
    statements=[]
    def record(conn,cursor,sql,*args): statements.append((sql,conn.get_isolation_level(),conn.get_execution_options()))
    event.listen(engine,'before_cursor_execute',record)
    try: ledger.ensure_schema(engine)
    finally: event.remove(engine,'before_cursor_execute',record)
    with engine.connect() as db:
        assert db.scalar(text("SELECT indisvalid FROM pg_index WHERE indexrelid=to_regclass('ix_ai_usage_conversation')")) is True
    concurrent=[options for sql,_,options in statements if sql.startswith(('CREATE INDEX CONCURRENTLY','DROP INDEX CONCURRENTLY'))]
    assert concurrent and all(options.get('isolation_level')=='AUTOCOMMIT' for options in concurrent)


def test_postgres_usage_index_failure_does_not_crash_startup_and_retries(app,client):
    engine=app.state.sessions.kw['bind']
    if engine.dialect.name!='postgresql': pytest.skip('PostgreSQL concurrent indexes')
    with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as db: db.exec_driver_sql('DROP INDEX CONCURRENTLY IF EXISTS ix_ai_usage_conversation')
    attempted=[]
    def fail(conn,cursor,sql,*args):
        if sql.startswith('CREATE INDEX CONCURRENTLY'):
            attempted.append(sql)
            raise OperationalError('synthetic failure',{},Exception('retry'))
    event.listen(engine,'before_cursor_execute',fail)
    try: ledger.ensure_schema(engine)
    finally: event.remove(engine,'before_cursor_execute',fail)
    assert len(attempted)==1
    assert not any(i['name']=='ix_ai_usage_conversation' for i in inspect(engine).get_indexes('ai_usage'))
    ledger.ensure_schema(engine)
    assert any(i['name']=='ix_ai_usage_conversation' for i in inspect(engine).get_indexes('ai_usage'))


@pytest.mark.parametrize('grant', [dict(role='pm'), dict(role='manager'), dict(role='工務助理'),
    dict(department='工務助理'), dict(name='郭倢瑛'), dict(display_name='朱雅琪'),
    dict(group='林瑩瑄'), dict(capabilities=['manage_sources'])])
def test_shared_reports_allowed_preserves_existing_grants(grant):
    from .production_access import reports_allowed
    user=dict(role='member', capabilities=[], **{k:v for k,v in grant.items() if k not in ('role','capabilities')})
    user.update(grant)
    assert reports_allowed(user)
    assert not reports_allowed({**user,'active':False})
    assert not reports_allowed(dict(role='member',department='其他部門'))


def test_report_endpoint_uses_shared_reports_allowed(tmp_path,monkeypatch):
    import importlib
    from .test_production_access import company
    application,client=company(tmp_path)
    assert client.post('/api/workspace/switch',json={'environment':'production'}).status_code==200
    calls=[]
    def denied(user):
        calls.append(user['id'])
        return False
    monkeypatch.setattr(importlib.import_module('backend.app'),'reports_allowed',denied)
    async def unexpected(*args,**kwargs): raise AssertionError('denial must precede source read')
    monkeypatch.setattr(application.state.reports,'aget',unexpected)
    try:
        assert client.get('/api/reports/sales').status_code==403
        assert calls==['u-manager']
    finally:
        client.close();application.state.sessions.kw['bind'].dispose()


def test_backfill_failure_rolls_back_marker_and_retries(tmp_path):
    engine=create_engine('sqlite:///'+str(tmp_path/'retry.db'))
    ledger.ensure_schema(engine)
    with engine.begin() as db: db.execute(delete(ledger.AiSchemaMigration))
    def fail(conn,cursor,sql,*args):
        if sql.startswith('INSERT INTO ai_conversation_workspace_read'):
            raise OperationalError('synthetic failure',{},Exception('retry'))
    event.listen(engine,'before_cursor_execute',fail)
    try:
        with pytest.raises(OperationalError): ledger.backfill_conversation_reads(engine)
    finally: event.remove(engine,'before_cursor_execute',fail)
    with engine.connect() as db: assert db.scalar(select(ledger.AiSchemaMigration.name)) is None
    ledger.ensure_schema(engine)
    with engine.connect() as db: assert db.scalar(select(ledger.AiSchemaMigration.name))==ledger.CONVERSATION_READ_BACKFILL
    engine.dispose()


def test_postgres_index_disconnect_does_not_crash_startup_and_retries(app,client):
    engine=app.state.sessions.kw['bind']
    if engine.dialect.name!='postgresql': pytest.skip('PostgreSQL concurrent indexes')
    with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as db:
        db.exec_driver_sql('DROP INDEX CONCURRENTLY IF EXISTS ix_ai_usage_conversation')
    attempted=[]
    def disconnect(conn,cursor,sql,*args):
        if sql.startswith('CREATE INDEX CONCURRENTLY'):
            attempted.append(sql)
            conn.invalidate()
            raise OperationalError('synthetic disconnect',{},Exception('disconnect'),connection_invalidated=True)
    event.listen(engine,'before_cursor_execute',disconnect)
    try: ledger.ensure_schema(engine)
    finally: event.remove(engine,'before_cursor_execute',disconnect)
    assert len(attempted)==1
    ledger.ensure_schema(engine)
    with engine.connect() as db:
        assert db.scalar(text("SELECT indisvalid FROM pg_index WHERE indexrelid=to_regclass('ix_ai_usage_conversation')")) is True
