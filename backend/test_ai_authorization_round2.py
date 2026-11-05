"""Ordinary data and bounded dependency regressions from review round two."""
from datetime import datetime,timedelta,timezone
import pytest
from sqlalchemy import select,delete,func,event
from .test_ai_database import app,client,ai_database_url
from .test_ai_api import BODY,Fake,events,rows,wid,dataset_call
from .test_ai_project import project
from .test_ai_authorization_review import ask,hide
from .test_backend import WorkspaceRow,BusinessRow,storage,role
from .ai import ledger


def test_report_workspace_policy_preserves_earlier_turns(app,client,monkeypatch):
    import httpx
    pid=project(client)
    with app.state.sessions() as db: code=db.get(BusinessRow,(wid(app,client),'projects',pid)).data['code']
    _,response=ask(app,client,'report-conversation');events(response)
    hide(app,client,pid)
    original=httpx.AsyncClient.get
    async def report(self,path,**kwargs):
        if path=='/api/reports/sales':
            return httpx.Response(200,json={'items':[dict(code=code,name='Historic report case'),dict(code='',name='Unnumbered case'),dict(code='C-NOT-IMPORTED',name='External case')],'total':3},request=httpx.Request('GET','http://ai.internal'+path))
        return await original(self,path,**kwargs)
    monkeypatch.setattr(httpx.AsyncClient,'get',report)
    fake,response=ask(app,client,'report-conversation',calls=[dataset_call('report','report_sales',{})])
    result=events(response)
    assert result[-1]['type']=='done' and len(fake.inputs)==2
    uid=result[0]['usage_id']
    with app.state.sessions() as db:
        assert db.scalars(select(ledger.AiCaseRead).where(ledger.AiCaseRead.usage_id==uid)).all()==[]
        assert db.scalars(select(ledger.AiWorkspaceRead.marker).where(ledger.AiWorkspaceRead.usage_id==uid)).all()==['report:sales']
    assert client.get('/api/ai/conversations/report-conversation').status_code==200


def test_denied_turn_never_poison_earlier_turns(app,client):
    _,response=ask(app,client,'kept');uid=events(response)[0]['usage_id']
    with app.state.sessions() as db:
        row=db.get(ledger.AiUsageRow,uid)
        values={c.name:getattr(row,c.name) for c in ledger.AiUsageRow.__table__.columns}
    values.update(id='denied-turn',error_code='ai_forbidden',status='error')
    ledger.record(app.state.sessions,case_reads=[('denied-tool','hidden')],**{k:v for k,v in values.items() if k not in ('created_at','day')})
    assert client.get('/api/ai/conversations/kept').status_code==200


def test_search_is_one_workspace_marker_and_not_inherited_case_copies(app,client):
    pid=project(client)
    _,response=ask(app,client,'search',calls=[dataset_call('search','search_cases',{'query':'','status':'all','owner':'anyone','overdue':False})])
    assert events(response)[-1]['type']=='done'
    _,response=ask(app,client,'search');events(response)
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(ledger.AiCaseRead))==0
        assert db.scalars(select(ledger.AiWorkspaceRead.marker)).all()==['portfolio']
    hide(app,client,pid)
    assert client.get('/api/ai/conversations/search').status_code==200


def test_explicit_case_dependency_survives_later_turns_until_content_purged(app,client,monkeypatch):
    pid=project(client)
    _,response=ask(app,client,'specific',calls=[dataset_call('case','case_progress',{'case_id':pid})]);first=events(response)[0]['usage_id']
    _,response=ask(app,client,'specific');events(response)
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(ledger.AiCaseRead))==1
        assert db.scalar(select(func.count()).select_from(ledger.AiConversationCaseRead))==1
    with app.state.sessions.begin() as db: db.get(ledger.AiExchangeRow,first).created_at=datetime.now(timezone.utc)-timedelta(days=91)
    monkeypatch.setattr(ledger,'_last_cleanup',None);ledger.cleanup_content(app.state.sessions,90)
    hide(app,client,pid)
    assert client.get('/api/ai/conversations/specific').status_code==403
    assert client.delete('/api/ai/conversations/specific').status_code==204
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(ledger.AiCaseRead))==0
        assert db.scalar(select(func.count()).select_from(ledger.AiConversationCaseRead))==0
        assert db.scalar(select(func.count()).select_from(ledger.AiUsageRow))==2


def test_retention_purges_dependency_metadata_with_last_exchange(app,client,monkeypatch):
    pid=project(client)
    _,response=ask(app,client,'expire',calls=[dataset_call('case','case_progress',{'case_id':pid})]);events(response)
    monkeypatch.setattr(ledger,'_last_cleanup',None);ledger.cleanup_content(app.state.sessions,0)
    with app.state.sessions() as db:
        for model in (ledger.AiCaseRead,ledger.AiWorkspaceRead,ledger.AiConversationCaseRead):
            assert db.scalar(select(func.count()).select_from(model))==0


def test_display_edits_preserve_permission_epoch_and_history(app,client):
    from .operations import apply_operation
    from .ai.history_authorization import permission_key
    _,response=ask(app,client,'name-edit');events(response)
    actor=client.get('/api/session').json()['user']['id']
    with app.state.sessions.begin() as db:
        root=db.get(WorkspaceRow,wid(app,client));state=storage.load(db,BusinessRow,root)
        target=next(u for u in state['users'] if u['id']==actor);manager=next(u for u in state['users'] if u['id']=='u-manager')
        before=permission_key(target)
        apply_operation(state,manager,{'action':'admin_person','payload':{'id':actor,'name':'Corrected name','department':'Corrected department'}},True)
        assert permission_key(target)==before
        assert target['permission_version']==0 and target['authz_version']==1
        root.data=storage.save(db,BusinessRow,root.id,state)
    assert client.get('/api/ai/conversations/name-edit').status_code==200


def test_manager_audit_does_not_use_producer_role_overrides(app,client):
    _,response=ask(app,client,'audit');uid=events(response)[0]['usage_id']
    actor=client.get('/api/session').json()['user']['id']
    role(client,'u-manager')
    with app.state.sessions.begin() as db:
        root=db.get(WorkspaceRow,wid(app,client));state=storage.load(db,BusinessRow,root)
        next(u for u in state['users'] if u['id']==actor).update(role='member',active=False,authz_version=10)
        root.data=storage.save(db,BusinessRow,root.id,state)
    assert client.get(f'/api/ai/usage/{uid}/exchange').json()['answer']=='截至目前，查詢完成'


def test_empty_global_list_does_not_materialize_cases(app,client,monkeypatch):
    from .ai import routes
    def forbidden(*args,**kwargs): pytest.fail('whole-workspace case load')
    monkeypatch.setattr(routes,'visible_cases',forbidden,raising=False)
    assert client.get('/api/ai/conversations').json()['items']==[]


def test_legacy_case_check_falls_back_safely(app,client):
    from .ai.history_authorization import require_case
    from .ai.ledger import AiUsageRow
    pid=project(client);workspace=wid(app,client)
    _,response=ask(app,client,'legacy-visible',pid=pid);events(response)
    with app.state.sessions.begin() as db:
        root=db.get(WorkspaceRow,workspace);state=storage.load(db,BusinessRow,root)
        state.pop('storage_schema',None);root.data=state
        db.query(BusinessRow).filter(BusinessRow.workspace_id==workspace).delete()
    require_case(app.state.sessions,workspace,pid,app.state.cfg)
    assert client.get('/api/ai/conversations/legacy-visible').status_code==200


def test_stream_revocation_bound_seconds_is_named_and_enforced(app,client,monkeypatch):
    from .ai import routes
    assert routes.STREAM_REVOCATION_BOUND_SECONDS==2.0
    from .test_ai_history import test_inflight_case_revocation_blocks_later_events_and_keeps_usage
    test_inflight_case_revocation_blocks_later_events_and_keeps_usage(app,client,monkeypatch)


def test_display_edit_does_not_cut_an_active_stream(app,client,monkeypatch):
    from .operations import apply_operation
    from .ai import routes
    from .ai.providers import Event
    actor=client.get('/api/session').json()['user']['id']
    workspace=wid(app,client);clock=[routes.monotonic()]
    monkeypatch.setattr(routes,'monotonic',lambda:clock[0])
    class Editing(Fake):
        async def stream(self,*args):
            yield Event('text','Before edit')
            with app.state.sessions.begin() as db:
                root=db.get(WorkspaceRow,workspace);state=storage.load(db,BusinessRow,root)
                manager=next(u for u in state['users'] if u['id']=='u-manager')
                apply_operation(state,manager,{'action':'admin_person','payload':{'id':actor,'name':'Updated name','department':'Updated department'}},True)
                root.data=storage.save(db,BusinessRow,root.id,state)
            clock[0]+=routes.STREAM_REVOCATION_BOUND_SECONDS+0.01
            yield Event('text','After edit')
            yield Event('stop',[{'type':'text','text':'After edit'}])
    app.state.ai_providers={'claude':Editing()}
    result=events(client.post('/api/ai/chat',json={**BODY,'conversation_id':'active-display-edit'}))
    assert [e['type'] for e in result]==['start','text','text','done']
    assert client.get('/api/ai/conversations/active-display-edit').status_code==200


def test_permission_epoch_bumps_for_actual_role_change_only():
    from .test_person_event_privacy import workspace
    from .operations import apply_operation
    from .ai.history_authorization import permission_key
    state,manager,target=workspace();target['authz_version']=4
    initial=permission_key(target)
    apply_operation(state,manager,{'action':'admin_person','payload':{'id':target['id'],'name':'Name','department':'Department','default_workspace':'test'}},True)
    assert target['permission_version']==4 and target['authz_version']==5
    assert permission_key(target)==initial
    apply_operation(state,manager,{'action':'admin_person','payload':{'id':target['id'],'role':'pm' if target['role']!='pm' else 'member'}},True)
    assert target['permission_version']==5 and target['authz_version']==6
    assert permission_key(target)!=initial


def test_audit_hr_redaction_is_decided_by_viewer(app,client):
    _,response=ask(app,client,'hr-context');uid=events(response)[0]['usage_id']
    workspace=wid(app,client);actor=client.get('/api/session').json()['user']['id']
    with app.state.sessions.begin() as db:
        db.add(ledger.AiWorkspaceRead(usage_id=uid,marker='attendance'))
        db.add(ledger.AiConversationWorkspaceRead(workspace_id=workspace,actor_id=actor,conversation_id='hr-context',marker='attendance'))
    role(client,'u-manager');app.state.cfg['HR_VIEWERS']='other-viewer'
    assert client.get(f'/api/ai/usage/{uid}/exchange').json()['answer'] is None
    app.state.cfg['HR_VIEWERS']='u-manager'
    assert client.get(f'/api/ai/usage/{uid}/exchange').json()['answer']=='截至目前，查詢完成'


def test_audit_never_scans_producer_profiles(app,client,monkeypatch):
    from .ai import routes
    role(client,'u-manager')
    def forbidden(*args,**kwargs): pytest.fail('producer profile scan')
    monkeypatch.setattr(routes,'permission_keys',forbidden,raising=False)
    assert client.get('/api/ai/usage').status_code==200


def test_delete_fence_does_not_resurrect_dependencies_on_delayed_record(app,client,monkeypatch):
    pid=project(client);original=ledger.record
    def delayed(sessions,**values):
        ledger.delete_conversation(sessions,values['workspace_id'],values['actor_id'],values['conversation_id'])
        original(sessions,**values)
    monkeypatch.setattr(ledger,'record',delayed)
    _,response=ask(app,client,'deleted-dependencies',calls=[dataset_call('case','case_progress',{'case_id':pid})]);events(response)
    with app.state.sessions() as db:
        for model in (ledger.AiCaseRead,ledger.AiWorkspaceRead,ledger.AiConversationCaseRead,ledger.AiConversationWorkspaceRead):
            assert db.scalar(select(func.count()).select_from(model))==0
        assert db.scalar(select(func.count()).select_from(ledger.AiUsageRow))==1


def test_dependency_migration_deduplicates_and_excludes_denied_rows(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from .test_ai_history_queries import seed_turn
    engine=create_engine('sqlite:///'+str(tmp_path/'prior-dependencies.db'))
    ledger.ensure_schema(engine);sessions=sessionmaker(bind=engine)
    for ident in ('read','inherited','denied'):
        seed_turn(sessions,ident,'conversation')
    with sessions.begin() as db:
        db.execute(delete(ledger.AiSchemaMigration).where(ledger.AiSchemaMigration.name == ledger.CONVERSATION_READ_BACKFILL))
        db.get(ledger.AiUsageRow,'denied').error_code='ai_forbidden'
        db.add_all([ledger.AiCaseRead(usage_id='read',tool_call_id='tool',project_id='p1'),
                    ledger.AiCaseRead(usage_id='inherited',tool_call_id='conversation',project_id='p1'),
                    ledger.AiCaseRead(usage_id='denied',tool_call_id='tool',project_id='hidden')])
    ledger.ensure_schema(engine);ledger.ensure_schema(engine)
    with sessions() as db:
        assert db.scalars(select(ledger.AiConversationCaseRead.project_id)).all()==['p1']
    assert any(i['name']=='ix_ai_usage_conversation' for i in __import__('sqlalchemy').inspect(engine).get_indexes('ai_usage'))
    engine.dispose()
