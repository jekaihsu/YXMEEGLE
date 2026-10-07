"""VCC-99 P4-3: GET /api/projects/{id} equals the legacy /api/workspace projection of that one project."""
from sqlalchemy import event
from .test_perf_budget import scaled_client
from .test_shell import ON, switch
from . import workspace_environment

SLICE = ('approvals', 'events', 'financial_requests', 'source_quotes', 'source_confirmations', 'contract_items', 'node_skip_requests')


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
                for key in SLICE:
                    assert body[key] == [i for i in full.get(key, []) if isinstance(i, dict) and i.get('project_id') == p['id']], (uid, key)


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
