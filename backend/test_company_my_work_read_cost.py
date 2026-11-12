"""Read projections preserve full-route responses, authorization and storage state."""

import pytest

from . import storage, workspace_environment
from .benchmark_case_home import fixture
from .test_perf_budget import scaled_client
from .operations import review_hash, seats


def populated(state):
    fixture(state)
    from .policy import upgrade
    upgrade(state)
    state['source_status']={'status':'ready','last_sync':'2026-10-24T10:00:00+08:00'}
    for p in state['projects']:
        p.update(case_visibility='source_reference',execution_system='workbench')
    p=state['projects'][0]; n=p['nodes'][0]; t=n['tasks'][0]
    t.update(owner_id='ou_015',status='paused',owner_inherited=False)
    p['comments'].append({'id':'local-comment','body':'retain me'})
    p['case_policy']={'local':'retain me'}
    state['events'].insert(0,{'id':'pause-event','project_id':p['id'],'node_id':n['id'],
                            'task_id':t['id'],'action':'task_pause_for_change','message':'local pause reason'})
    # A real current review hash exercises the inputs that must remain complete.
    n.update(status='in_progress',reviewers=['ou_015'])
    n['review_cycles']=[{'id':'review-cycle','status':'pending','content_hash':review_hash(p,n),
                         'seats':seats(p,n),'votes':[]}]
    state['jobs'].append({'id':'unknown-job','status':'outcome_unknown','payload':{'project_id':p['id'],'task_id':t['id']}})
    state['handover_requests'].append({'id':'handover','project_id':p['id'],'status':'awaiting_acceptance','to_id':'ou_015'})
    state['projects'][-1]['case_visibility']='excluded_history'


@pytest.mark.parametrize('environment',['demo','production'])
@pytest.mark.parametrize('path',['/api/company-dashboard?limit=5','/api/my-work'])
def test_projected_routes_match_full_routes_and_leave_local_state_intact(tmp_path,monkeypatch,environment,path):
    with scaled_client(tmp_path,4,upgraded=True,mutate=populated) as (app,client):
        monkeypatch.setattr(workspace_environment,'normalize_environment',
                            lambda state,*_: state.update(environment=environment) or state)
        client.post('/api/demo/session',json={'user_id':'ou_015'})
        wid=app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
        from .models import BusinessRow, WorkspaceRow
        with app.state.sessions() as db:
            before=storage.load(db,BusinessRow,db.get(WorkspaceRow,wid))
        calls=[]; load=storage.load
        def capture(*args,**kwargs):
            calls.append(kwargs.get('omit_kinds',()))
            return load(*args,**kwargs)
        with monkeypatch.context() as patch:
            patch.setattr(storage,'load',capture)
            response=client.get(path)
        assert response.status_code==200,response.text
        actual=response.json()
        assert any('project_daily_reports' in omitted for omitted in calls)
        def full(*args,**kwargs):
            kwargs.pop('omit_kinds',None)
            return load(*args,**kwargs)
        with monkeypatch.context() as patch:
            patch.setattr(storage,'load',full)
            expected=client.get(path)
        assert expected.status_code==200,expected.text
        expected=expected.json()
        if 'dashboard' in path:
            actual.pop('checked_at'); expected.pop('checked_at')
            assert actual['complete'] is True
        else:
            assert actual['rows']
            assert any(row.get('operation_outcome')=='unknown' for row in actual['rows'])
        assert actual==expected
        with app.state.sessions() as db:
            after=storage.load(db,BusinessRow,db.get(WorkspaceRow,wid))
        assert after==before


def test_truncated_source_is_still_incomplete_with_a_complete_projection(tmp_path):
    def prepare(state):
        populated(state); state['source_status']['truncated']=True
    with scaled_client(tmp_path,2,upgraded=True,mutate=prepare) as (_,client):
        result=client.get('/api/company-dashboard').json()
        assert result['complete'] is False and result['total_count'] is None
