"""Literal read-volume budgets; wall times are measured separately on PostgreSQL."""
import json
import os
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from .models import Base, CacheRow
from .source_health import load_source_metadata
from .test_perf_budget import scaled_client


@pytest.mark.parametrize('dialect', ['sqlite', 'postgres'])
def test_source_health_metadata_never_returns_source_values(tmp_path, dialect):
    url = os.getenv('PERF2_POSTGRES_URL') if dialect == 'postgres' else f'sqlite:///{tmp_path}/health.db'
    if not url: pytest.skip('PERF2_POSTGRES_URL needs a disposable PostgreSQL database')
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    wid = 'perf2-health-'+tmp_path.name
    try:
        with Session(engine) as db:
            db.add(CacheRow(id=wid, data={'status':'ready','authorized':True,'tables':[],
                'records':[{'record_id':'r1','base_token':'b','table_id':'t','fields':{'private_blob':'x'*100_000}},
                           {'record_id':'r2','base_token':'b','table_id':'t'}]}))
            db.commit()
        with Session(engine) as db:
            body = load_source_metadata(db, CacheRow, wid)
            assert body['records'] == [{'record_id':'r1','base_token':'b','table_id':'t'},
                                       {'record_id':'r2','base_token':'b','table_id':'t'}]
            assert len(json.dumps(body)) < 500, 'health needs identities, never raw source fields'
            assert load_source_metadata(db, CacheRow, wid+'-missing') is None
    finally:
        with Session(engine) as db:
            row=db.get(CacheRow,wid)
            if row: db.delete(row);db.commit()
        engine.dispose()


def test_first_screen_single_root_decode_budget(tmp_path):
    with scaled_client(tmp_path, 2, WORKSPACE_SHELL_ENABLED='true', INDEX_TABLES_ENABLED='true') as (app, client):
        wide=[]
        def observe(conn,cur,statement,*_):
            if 'workspaces.data \n' in statement: wide.append(statement)
        event.listen(app.state.engine,'before_cursor_execute',observe)
        try:
            for _ in range(2):
                wide.clear()
                response=client.get('/api/projects/p001/first-screen')
                assert response.status_code == 200
                assert len(wide) <= 1, 'one root decode per captured version per request'
        finally:event.remove(app.state.engine,'before_cursor_execute',observe)


def test_assigned_input_row_budget_and_parity(tmp_path):
    from .benchmark_case_home import fixture, offline_assignments
    from . import storage
    from .models import BusinessRow, WorkspaceRow
    from .policy import upgrade
    from . import workspace_read_rows
    with scaled_client(tmp_path, 12, upgraded=True, mutate=fixture) as (app, client):
        offline_assignments(app)
        client.post('/api/demo/session', json={'user_id':'ou_015'})
        user=client.get('/api/session').json()['user']
        wid=app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
        with app.state.sessions() as db:
            state=upgrade(storage.load(db,BusinessRow,db.get(WorkspaceRow,wid)))
        state['features']={'routines':False,'change_extension':False}
        params={'panel':'assigned','limit':'100'}
        expected=app.state.home_panels.query(state,{'wid':wid,'mode':'demo'},user,params)
        kinds=[]
        original=workspace_read_rows.read_rows
        def rows(*args,**kwargs):
            for row in original(*args,**kwargs):
                kinds.append(row[0]);yield row
        with patch.object(workspace_read_rows,'read_rows',rows):
            response=client.get('/api/home-panels',params=params)
        assert response.status_code == 200
        assert response.json() == expected
        assert kinds and len(kinds) < 1500
        assert not set(kinds)&{'source_work_items','source_quotes','events','jobs','financial_requests'}, 'assigned must not materialize unrelated feeds'


def test_case_metadata_copies_only_selected_plan_without_mutating_root():
    from .case_metadata_reads import root_metadata
    class UnrelatedPlan(dict):
        def __deepcopy__(self,memo):
            raise AssertionError('a single-case read copied another case plan')
    root={'derived_plan':{'p1':{'items':[{'known':True}]},'p2':UnrelatedPlan(items=[])},
          'source_work_items_status':{'p1':{'partial':True},'p2':{'partial':False}},
          'source_visible_record_ids':['b|t|r1','b|t|r2']}
    result=root_metadata(root,['p1'],scoped=True)
    assert set(result['derived_plan']) == {'p1'}
    assert result['source_visible_record_ids'] == root['source_visible_record_ids']
    result['derived_plan']['p1']['items'][0]['known']=False
    assert root['derived_plan']['p1']['items'][0]['known'] is True


def test_lark_warm_case_keys_do_not_decode_workspace(tmp_path):
    from datetime import datetime, timezone
    from .models import AuthRow, PersonRow
    with scaled_client(tmp_path,2,WORKSPACE_SHELL_ENABLED='true',INDEX_TABLES_ENABLED='true') as (app,client):
        data=app.state.signer.loads(client.cookies.get('meegle_session'))
        user=client.get('/api/session').json()['user']
        data.update(mode='lark',sid='perf2-session',organization=data['wid'])
        with app.state.sessions.begin() as db:
            db.add(AuthRow(id=data['sid'],data={'wid':data['wid'],'expires':datetime.now(timezone.utc).timestamp()+3600}))
            db.add(PersonRow(organization_id=data['wid'],person_id=user['id'],data=user))
        client.cookies.clear()
        client.cookies.set('meegle_session',app.state.signer.dumps(data))
        assert client.get('/api/projects/p001/first-screen').status_code == 200
        wide=[]
        def observe(conn,cur,statement,*_):
            if 'workspaces.data \n' in statement:wide.append(statement)
        event.listen(app.state.engine,'before_cursor_execute',observe)
        try:
            response=client.get('/api/projects/p001/first-screen')
            assert response.status_code == 200
            assert len(wide) == 0, 'warm Lark admission/key validation must read person and scalars only'
        finally:event.remove(app.state.engine,'before_cursor_execute',observe)


def test_progress_generation_source_document_parse_budget(tmp_path):
    with scaled_client(tmp_path,2,WORKSPACE_SHELL_ENABLED='true',INDEX_TABLES_ENABLED='true') as (app,client):
        assert client.get('/api/projects/p001/progress').status_code == 200
        reads=[]
        def observe(conn,cur,statement,*_):
            if 'source_caches.data' in statement:
                reads.append(statement)
        event.listen(app.state.engine,'before_cursor_execute',observe)
        try:
            assert client.get('/api/projects/p001/progress').status_code == 200
            for statement in reads:
                extracts=statement.count('JSON_EXTRACT(source_caches.data')+statement.count('source_caches.data ->')
                assert extracts <= 1, 'generation checks must not parse the same source document four times'
        finally:event.remove(app.state.engine,'before_cursor_execute',observe)


def test_unassigned_home_does_not_derive_other_peoples_cases(tmp_path):
    from .benchmark_case_home import fixture,offline_assignments
    from .node_assignment import bulk
    with scaled_client(tmp_path,12,upgraded=True,mutate=fixture) as (app,client):
        offline_assignments(app)
        # The manager owns none of these 319 source groups.
        with patch.object(bulk,'derive_chain',wraps=bulk.derive_chain) as derive:
            response=client.get('/api/home-panels?panel=assigned&scope=mine&limit=100')
        assert response.status_code == 200
        assert response.json()['items'] == []
        assert derive.call_count == 0, 'mine/assigned must not derive unassigned case chains'


from .test_ux_home_panels import home, node, task  # noqa: E402,F401


def test_assigned_candidate_filter_preserves_full_source_result(home):
    from . import home_assignment_candidates as candidates
    mine=node(home)
    # A different relation/code holding the same key must still block mine as
    # a global duplicate, even though that row belongs to someone else.
    node(home,owner='ou_depth',**{'確認單編號':'C999999','工程確認單':['recOTHER']})
    predecessor=node(home,label='業務',owner='ou_depth')
    task(home,predecessor,owner='ou_depth')
    task(home,mine,owner='ou_member')
    task(home,mine,owner='ou_depth')
    task(home,None,owner='ou_member')
    task(home,'missing-parent',owner='ou_member')
    unrelated=node(home,owner='ou_depth',**{'指派鍵':'C888888|外業','確認單編號':'C888888','工程確認單':['recUNRELATED']})
    task(home,unrelated,owner='ou_depth')
    with patch.object(candidates,'assigned_rows',lambda n,t,_:(n,t)):
        full=home.read(panel='assigned')
    narrowed=home.read(panel='assigned')
    assert narrowed == full
    assert any(i.get('assignment_state') == 'duplicate' for i in narrowed['items'])
    assert home.fake.writes() == []


def test_assigned_candidate_inputs_validate_all_envelopes():
    from .home_assignment_candidates import assigned_rows
    from .node_assignment.errors import Failure
    with pytest.raises(Failure):
        assigned_rows([{'record_id':'bad','fields':None}],[], 'ou_viewer')


@pytest.mark.parametrize('dialect', ['sqlite','postgres'])
def test_generation_projection_preserves_json_values(tmp_path,dialect):
    from .source_metadata_reads import read_generation
    url=os.getenv('PERF2_POSTGRES_URL') if dialect=='postgres' else f'sqlite:///{tmp_path}/fence.db'
    if not url:pytest.skip('PERF2_POSTGRES_URL needs a disposable PostgreSQL database')
    engine=create_engine(url);Base.metadata.create_all(engine)
    wid='perf2-fence-'+tmp_path.name
    values=(False,{'nested':[1,None,True]},'null',0)
    try:
        with Session(engine) as db:
            db.add(CacheRow(id=wid,data=dict(zip(('status','last_attempt_at','last_sync','as_of'),values))))
            db.commit()
            assert read_generation(db,CacheRow,wid) == values
            assert read_generation(db,CacheRow,wid+'-missing') == (None,None,None,None)
    finally:
        with Session(engine) as db:
            row=db.get(CacheRow,wid)
            if row:db.delete(row);db.commit()
        engine.dispose()
