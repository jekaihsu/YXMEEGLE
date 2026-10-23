from sqlalchemy import select
from .test_perf_budget import scaled_client
from .models import BusinessRow, WorkspaceRow
from . import storage
from .sop_import.models import CasePolicy


def test_portfolio_is_complete_compact_and_policy_aware(tmp_path):
    with scaled_client(tmp_path, 14, upgraded=True, INDEX_TABLES_ENABLED='true', WORKSPACE_SHELL_ENABLED='true') as (app, client):
        with app.state.sessions.begin() as db:
            row=db.scalars(select(WorkspaceRow)).first()
            state=storage.load(db,BusinessRow,row)
            pid=state['projects'][0]['id']
            db.merge(CasePolicy(workspace_id=row.id,project_id=pid,policy='managed',revision=1,
                decided_by='fixture',decided_at=0,reason='test',facts={},node_keys=['sales']))
        response=client.get('/api/projects?view=portfolio')
        assert response.status_code==200,response.text
        body=response.json()
        assert body['total']==14==len(body['items'])
        first=next(p for p in body['items'] if p['id']==pid)
        assert first['sop_summary']==dict(policy='managed',imported_tasks=False)
        assert len(first['portfolio_nodes'])==9
        assert {'key','status','owner_id','collaborator_ids'}==set(first['portfolio_nodes'][0])
        assert not {'nodes','files','daily_reports','contract_amount','estimated_points'} & set(first)
        assert body['basis']=='persisted_workspace'


def test_portfolio_applies_visibility_and_does_not_load_task_trees(tmp_path,monkeypatch):
    from . import storage as store,index_reads
    from . import workspace_environment
    with scaled_client(tmp_path, 8, upgraded=True, INDEX_TABLES_ENABLED='true', WORKSPACE_SHELL_ENABLED='true') as (app,client):
        with app.state.sessions.begin() as db:
            row=db.scalars(select(WorkspaceRow)).first();state=store.load(db,BusinessRow,row)
            for i,p in enumerate(state['projects']):p['case_visibility']='new_case' if i%2 else 'excluded_history'
            state['version']=row.version+1;row.version=state['version'];row.data=store.save(db,BusinessRow,row.id,state)
        monkeypatch.setattr(workspace_environment,'normalize_environment',lambda state,wid,cfg:state.update(environment='production') or state)
        original=store.load_partial
        def bounded(*args,**kwargs):
            assert not kwargs.get('project_ids'),'portfolio must not load a case tree per row'
            return original(*args,**kwargs)
        monkeypatch.setattr(store,'load_partial',bounded)
        response=client.get('/api/projects?view=portfolio')
        assert response.status_code==200,response.text
        assert response.json()['total']==4
        monkeypatch.setattr(index_reads,'ready',lambda *args:False)
        assert client.get('/api/projects?view=portfolio').status_code==503


def test_portfolio_recognizes_imported_tasks_without_managed_policy(tmp_path):
    from .sop_import.models import CaseState, LocalTask
    from .sop_import.domain import Applicability, Lifecycle
    with scaled_client(tmp_path, 2, upgraded=True, INDEX_TABLES_ENABLED='true', WORKSPACE_SHELL_ENABLED='true') as (app,client):
        with app.state.sessions.begin() as db:
            row=db.scalars(select(WorkspaceRow)).first();pid=storage.load(db,BusinessRow,row)['projects'][0]['id']
            db.add(CaseState(workspace_id=row.id,project_id=pid));db.flush()
            db.add(LocalTask(workspace_id=row.id,id='imported-task',project_id=pid,template_family_id='family',
                source_row_key='row-1',instance_scope='case',imported_version_id='v1',snapshot={},title='Imported task',
                instructions='',participants=[],applicability=Applicability.APPLICABLE,state=Lifecycle.PENDING,local={}))
        first=next(p for p in client.get('/api/projects?view=portfolio').json()['items'] if p['id']==pid)
        assert first['sop_summary']==dict(policy=None,imported_tasks=True)
