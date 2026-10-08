"""VCC-99 P4-3: GET /api/projects/{id} equals the legacy /api/workspace projection of that one project."""
from sqlalchemy import event
from .test_perf_budget import scaled_client
from .test_shell import ON, switch
from . import workspace_environment

def test_detail_equals_legacy_projection_for_every_user_and_project(tmp_path):
    with scaled_client(tmp_path, 12, **ON) as (app, client):
        for uid in ('u-manager', 'u-pm', 'ou_020', 'ou_030'):
            switch(client, uid)
            full = client.get('/api/workspace').json()
            for p in full['projects']:
                got = client.get('/api/projects/' + p['id'])
                assert got.status_code == 200, (uid, p['id'])
                body = got.json()
                assert body['scope'] == 'project' and body['version'] == full['version']
                assert body['project'] == p, (uid, p['id'])
                assert body['policy_summary'] == [s for s in full['policy_summary'] if s['project_id'] == p['id']]
                skipped = {'projects', 'users', 'calendar', 'source_status', 'file_categories', 'approval_connection', 'freshness', 'environment',
                           'workspace_id', 'as_of', 'version', 'work_schedules', 'daily_unmatched'}
                assert set(body) == (set(full) - skipped) | {'scope', 'version', 'as_of', 'project'}
                for key in set(full) - skipped - {'policy_summary', 'task_capabilities_checked_at'}:
                    expected = [i for i in full[key] if not isinstance(i, dict) or i.get('project_id', p['id']) == p['id']] if isinstance(full[key], list) else full[key]
                    assert body[key] == expected, (uid, key)
                assert len(body['policy_summary']) == 1


def test_detail_is_gated_unknown_and_hides_invisible_cases(tmp_path, monkeypatch):
    with scaled_client(tmp_path, 4, upgraded=True, INDEX_TABLES_ENABLED='true') as (app, client):
        pid = client.get('/api/workspace').json()['projects'][0]['id']
        assert client.get('/api/projects/' + pid).status_code == 404  # shell flag off
    with scaled_client(tmp_path / 'b', 6, **ON) as (app, client):
        assert client.get('/api/projects/nope').status_code == 404
        from .test_projects_index import reshape
        reshape(app)  # case_visibility cycles new_case, source_reference, excluded_history, new_case
        monkeypatch.setattr(workspace_environment, 'normalize_environment', lambda state, wid, cfg: state.update(environment='production') or state)
        ids = [p['id'] for p in client.get('/api/workspace').json()['projects']]
        assert len(ids) == 5 and 'p003' not in ids  # index 2 is excluded_history
        assert all(client.get('/api/projects/' + i).status_code == 200 for i in ids)
        assert client.get('/api/projects/p003').status_code == 404


def test_detail_loads_one_project_tree_not_the_workspace(tmp_path):
    with scaled_client(tmp_path, 40, **ON) as (app, client):
        pid = client.get('/api/workspace').json()['projects'][5]['id']
        statements = []
        listener = lambda conn, cur, st, params, ctx, many: statements.append((st, params))
        event.listen(app.state.engine, 'before_cursor_execute', listener)
        try: assert client.get('/api/projects/' + pid).status_code == 200
        finally: event.remove(app.state.engine, 'before_cursor_execute', listener)
        flat = [x for st, p in statements for x in (p if isinstance(p, (tuple, list)) else tuple(p.values()))]
        assert pid in flat
        assert not any(isinstance(x, (tuple, list)) and len(x) > 12 for x in flat)


def test_shared_business_records_require_all_related_cases_visible(tmp_path, monkeypatch):
    from .source_case_policy import identity
    from .test_projects_overview import edit_workspace
    with scaled_client(tmp_path, 3, **ON) as (app, client):
        monkeypatch.setattr(workspace_environment, 'normalize_environment', lambda state, wid, cfg: state.update(environment='production') or state)
        source = {'base_token':'fixture', 'table_id':'table', 'record_id':'shared'}
        collections = ('source_quotes', 'source_confirmations', 'contract_items')
        def prepare(state):
            for p in state['projects']: p['case_visibility'] = 'new_case'
            state['source_visible_record_ids'] = [identity(source)]
            for key in collections:
                state[key] = [{'id':'shared', 'source_identity':source, 'project_id':'p002', 'project_ids':['p001','p002']},
                              {'id':'unrelated', 'source_identity':source, 'project_ids':['p003']}]
        edit_workspace(app, client, prepare)
        full = client.get('/api/workspace').json()
        detail = client.get('/api/projects/p001').json()
        for key in collections:
            assert [r['id'] for r in full[key]] == ['shared', 'unrelated']
            assert [r['id'] for r in detail[key]] == ['shared']
        edit_workspace(app, client, lambda state: state['projects'][1].update(case_visibility='excluded_history'))
        hidden = client.get('/api/projects/p001').json()
        full = client.get('/api/workspace').json()
        for key in collections:
            assert [r['id'] for r in full[key]] == ['unrelated']
            assert hidden[key] == []
        assert hidden['project']['id'] == 'p001'
        assert client.get('/api/projects/p002').status_code == 404
