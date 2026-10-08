"""VCC-98 P3-1: GET /api/workspace?scope=shell is index-backed, slim, and strictly opt-in."""
import gzip
import json
from datetime import date, timedelta
import pytest
from . import app as backend_app
from .test_perf_budget import scaled_client, count_queries
from .models import WorkspaceRow

ON = dict(upgraded=True, WORKSPACE_SHELL_ENABLED='true', INDEX_TABLES_ENABLED='true')


def switch(client, uid):
    assert client.post('/api/demo/session', json={'user_id': uid}).status_code == 200


def test_shell_flag_off_changes_nothing(tmp_path):
    with scaled_client(tmp_path, 6, upgraded=True, INDEX_TABLES_ENABLED='true') as (app, client):
        assert 'features' not in client.get('/api/session').json()
        full = client.get('/api/workspace').json()
        shellish = client.get('/api/workspace?scope=shell').json()
        assert shellish.get('scope') is None and len(shellish['projects'][0]['nodes']) > 0
        assert set(full) == set(shellish) and len(full['projects']) == len(shellish['projects'])


def test_shell_advertised_and_scope_absent_is_full(tmp_path):
    with scaled_client(tmp_path, 6, **ON) as (app, client):
        assert client.get('/api/session').json()['features'] == {'workspace_shell': True}
        assert client.get('/api/workspace').json().get('scope') is None


def test_shell_shape_counts_and_no_trees(tmp_path):
    with scaled_client(tmp_path, 12, **ON) as (app, client):
        switch(client, 'u-manager')
        full = client.get('/api/workspace').json()
        shell = client.get('/api/workspace?scope=shell').json()
        assert shell['scope'] == 'shell' and shell['version'] == full['version'] and shell['environment'] == 'demo'
        assert shell['approvals'] == [] and shell['events'] == []
        assert [p['id'] for p in shell['projects']] == [p['id'] for p in full['projects']]
        for card, p in zip(shell['projects'], full['projects']):
            assert not {'nodes', 'files', 'comments', 'daily_reports'} & set(card)
            assert card['progress'] == next(s for s in full['policy_summary'] if s['project_id'] == p['id'])['progress']
            tasks = [t for n in p['nodes'] for t in n['tasks']]
            late = lambda t: bool(t['due_date']) and t['due_date'][:10] < shell['as_of'] and t['status'] not in ('completed', 'superseded')
            assert card['overdue_tasks'] == sum(map(late, tasks))
            assert card['active_tasks'] == sum(t['status'] not in ('completed', 'superseded') for t in tasks)
            for key in ('execution_system', 'execution_allowed', 'concurrency_version', 'pm_id', 'status', 'due_date'):
                assert card[key] == p[key]
        assert shell['users'] == full['users']
        for key in ('calendar', 'source_status', 'file_categories', 'approval_connection'):
            assert shell[key] == full[key]


@pytest.mark.parametrize('uid', ['u-manager', 'u-pm', 'ou_020', 'ou_030'])
def test_shell_my_counts_equal_legacy_can_execute(tmp_path, uid):
    with scaled_client(tmp_path, 12, **ON) as (app, client):
        switch(client, uid)
        full = client.get('/api/workspace').json(); shell = client.get('/api/workspace?scope=shell').json()
        rows = [t for p in full['projects'] for n in p['nodes'] for t in n['tasks'] if t['can_execute']]
        late = lambda t: bool(t['due_date']) and t['due_date'][:10] < shell['as_of'] and t['status'] not in ('completed', 'superseded')
        assert shell['counts']['my_overdue_tasks'] == sum(map(late, rows))
        assert shell['counts']['my_active_tasks'] == sum(t['status'] not in ('completed', 'superseded') for t in rows)
        assert shell['counts']['approvals_pending'] == sum(a['status'] == 'pending' for a in full['approvals'])
        assert shell['counts']['daily_unmatched'] == len(full['daily_unmatched'])
        # the attention list is the dashboard's, not the user's own: see test_shell_dashboard_equivalence.py
        assert all(a['task_id'] for a in shell['attention']) and len(shell['attention']) <= 5


def test_shell_overdue_uses_taipei_today(tmp_path, monkeypatch):
    with scaled_client(tmp_path, 6, **ON) as (app, client):
        switch(client, 'u-pm')
        before = client.get('/api/workspace?scope=shell').json()['counts']['my_overdue_tasks']
        monkeypatch.setattr(backend_app, 'now', lambda: '2030-01-01T00:00:00+08:00')
        after = client.get('/api/workspace?scope=shell').json()
        assert after['as_of'] == '2026-10-07' or after['as_of'] == '2030-01-01'
        assert after['counts']['my_overdue_tasks'] >= before


def test_shell_falls_back_to_full_when_index_missing_or_stale(tmp_path):
    with scaled_client(tmp_path, 6, upgraded=True, WORKSPACE_SHELL_ENABLED='true') as (app, client):  # index off
        assert client.get('/api/workspace?scope=shell').json().get('scope') is None
    with scaled_client(tmp_path / 'b', 6, **ON) as (app, client):
        assert client.get('/api/workspace?scope=shell').json()['scope'] == 'shell'
        with app.state.sessions.begin() as db:
            db.get(WorkspaceRow, client.get('/api/workspace').json()['workspace_id']).version += 1
        assert client.get('/api/workspace?scope=shell').json().get('scope') is None


def test_shell_hides_invisible_cases_from_cards_and_counts(tmp_path, monkeypatch):
    from . import workspace_environment
    from sqlalchemy import update
    from .models import ProjectIndex
    with scaled_client(tmp_path, 8, **ON) as (app, client):
        switch(client, 'ou_015')
        from .test_projects_overview import edit_workspace
        def pause(state):
            for p in state['projects']:
                for n in p['nodes']:
                    for t in n['tasks']: t['status'] = 'completed'
            for p in state['projects'][:2]: p['nodes'][0]['tasks'][0].update(status='paused', due_date=None)
        edit_workspace(app, client, pause)
        everything = client.get('/api/workspace?scope=shell').json()
        with app.state.sessions.begin() as db:
            db.execute(update(ProjectIndex).where(ProjectIndex.project_id == 'p001').values(case_visibility='excluded_history'))
        monkeypatch.setattr(workspace_environment, 'normalize_environment', lambda state, wid, cfg: state.update(environment='production') or state)
        shell = client.get('/api/workspace?scope=shell').json()
        assert shell['environment'] == 'production'
        assert 'p001' not in [p['id'] for p in shell['projects']] and len(shell['projects']) == 7
        assert shell['counts']['my_active_tasks'] < everything['counts']['my_active_tasks']
        assert not any(a['project_id'] == 'p001' for a in shell['attention'])
        assert everything['counts']['blocked_tasks'] == 2 and shell['counts']['blocked_tasks'] == 1
        assert [a['project_id'] for a in shell['blocked']] == ['p002']
        with app.state.sessions.begin() as db:
            db.execute(update(ProjectIndex).where(ProjectIndex.project_id == 'p002').values(case_visibility='source_review'))
        hidden = client.get('/api/workspace?scope=shell').json()
        assert hidden['counts']['blocked_tasks'] == 0 and hidden['blocked'] == []


def test_shell_budget_319(tmp_path):
    with scaled_client(tmp_path, 319, **ON) as (app, client):
        switch(client, 'u-pm')
        with count_queries(app.state.engine) as stats:
            response = client.get('/api/workspace?scope=shell', headers={'Accept-Encoding': 'gzip'})
        raw = len(response.content)
        print('shell', stats['queries'], 'queries', raw, 'raw', response.headers['content-length'], 'wire')
        assert response.json()['scope'] == 'shell' and 'server-timing' in response.headers
        # Fixture names are long CJK strings: 319 slim cards alone are ~148 KB. The 150 KB plan target needs P4-2 (server-paged cards).
        # Queries include ~14 from live-read ensure()/status and identity that are outside the shell itself (11: two more load the pending approvals the dashboard lists).
        assert stats['queries'] <= 26 and raw <= 165_000 and int(response.headers['content-length']) <= 30_000


def shell_get(client, tag=None):
    return client.get('/api/workspace?scope=shell', headers={'If-None-Match': tag} if tag else {})


def test_shell_etag_304_and_server_timing(tmp_path):
    with scaled_client(tmp_path, 6, **ON) as (app, client):
        switch(client, 'u-pm')
        first = shell_get(client); tag = first.headers['etag']
        assert first.status_code == 200 and tag.startswith('W/"shell-') and first.headers['cache-control'] == 'no-store'
        again = shell_get(client, tag)
        assert again.status_code == 304 and again.content == b'' and again.headers['etag'] == tag
        assert shell_get(client, 'W/"other", ' + tag).status_code == 304
        assert shell_get(client, 'W/"other"').status_code == 200
        assert 'server-timing' in first.headers and 'server-timing' in again.headers


def test_shell_etag_is_per_user_and_never_crosses_users_or_workspaces(tmp_path):
    with scaled_client(tmp_path, 6, **ON) as (app, client):
        switch(client, 'u-pm'); pm = shell_get(client).headers['etag']
        switch(client, 'ou_015'); member = shell_get(client)
        assert member.headers['etag'] != pm
        assert shell_get(client, pm).status_code == 200, "another user's ETag must not validate"
        assert shell_get(client, member.headers['etag']).status_code == 304
        switch(client, 'u-pm'); assert shell_get(client, member.headers['etag']).status_code == 200
        from fastapi.testclient import TestClient
        with TestClient(app) as other:  # a second demo workspace for the same user id
            other.get('/api/session'); other.post('/api/demo/session', json={'user_id': 'u-pm'})
            assert shell_get(other, pm).status_code == 200 and shell_get(other).headers['etag'] != pm


def test_shell_etag_changes_with_version_authority_and_day(tmp_path, monkeypatch):
    with scaled_client(tmp_path, 6, **ON) as (app, client):
        switch(client, 'u-pm')
        tag = shell_get(client).headers['etag']; version = client.get('/api/workspace?scope=shell').json()['version']
        assert client.post('/api/actions', json={'action': 'comment_add', 'version': version, 'request_id': 'etag-1',
                                                 'project_id': 'p001', 'payload': {'body': 'x'}}).status_code == 200
        after = shell_get(client, tag); assert after.status_code == 200 and after.headers['etag'] != tag
        tag = after.headers['etag']
        from . import shell
        user = {'id': 'u', 'role': 'pm', 'capabilities': [], 'authz_version': 1}
        base = shell.etag('w', user, 1, '2026-10-08', [])
        assert shell.etag('w', {**user, 'authz_version': 2}, 1, '2026-10-08', []) != base
        assert shell.etag('w', {**user, 'capabilities': ['approve_capability']}, 1, '2026-10-08', []) != base
        assert shell.etag('w', {**user, 'active': False}, 1, '2026-10-08', []) != base
        assert shell.etag('w2', user, 1, '2026-10-08', []) != base and shell.etag('w', user, 1, '2026-10-09', []) != base
        monkeypatch.setattr(backend_app, 'now', lambda: '2030-01-01T00:00:00+08:00')
        assert shell_get(client, tag).status_code == 200


def test_shell_blocked_undated_future_and_closed_tasks(tmp_path):
    from .test_projects_overview import edit_workspace
    with scaled_client(tmp_path, 2, **ON) as (app, client):
        as_of = client.get('/api/workspace?scope=shell').json()['as_of']
        def prepare(state):
            for p in state['projects']:
                for n in p['nodes']:
                    for t in n['tasks']: t.update(status='completed', due_date=None)
            state['projects'][-1]['nodes'][-1]['tasks'][-1].update(status='pending', due_date=as_of)
        edit_workspace(app, client, prepare)
        before = client.get('/api/workspace?scope=shell').json()
        assert len(before['attention']) == 1 and before['counts']['blocked_tasks'] == 0 and before['blocked'] == []
        def pause(state):
            tasks = [t for p in state['projects'] for n in p['nodes'] for t in n['tasks']]
            tasks[0].update(status='paused', due_date=None)
            tasks[1].update(status='paused', due_date='2099-01-01')
            # Closed records and an unmet input dependency are not status-blocked.
            tasks[3].update(status='completed', paused=True)
            tasks[4].update(status='superseded', paused=True)
            tasks[5].update(status='pending', input_task_ids=[tasks[0]['id']])
        edit_workspace(app, client, pause)
        body = client.get('/api/workspace?scope=shell').json()
        assert body['attention'] == before['attention']
        assert body['counts']['blocked_tasks'] == 2
        assert [(a['task_id'], a['due_date'], a['status']) for a in body['blocked']] == [
            ('p001-sales-t1', '', 'paused'), ('p001-sales-t2', '2099-01-01', 'paused')]
        expected_keys = {'task_id', 'project_id', 'node_id', 'node_key', 'node_name', 'assignee_id', 'status', 'due_date',
                         'project_code', 'project_name', 'title'}
        assert set(body['attention'][0]) == expected_keys
        assert all(set(a) == expected_keys for a in body['blocked'])
        full = client.get('/api/workspace').json()
        titles = {t['id']: t['title'] for p in full['projects'] for n in p['nodes'] for t in n['tasks']}
        assert all(a['title'] == titles[a['task_id']] for a in body['blocked'] + body['attention'])


def test_shell_blocked_limit_and_workspace_order(tmp_path):
    from .test_projects_overview import edit_workspace
    with scaled_client(tmp_path, 3, **ON) as (app, client):
        def pause(state):
            for p in state['projects']:
                for n in p['nodes']:
                    for t in n['tasks']: t.update(status='completed', due_date=None)
            # Reverse project/node/task order to ensure the list follows ordinals, not IDs.
            state['projects'].reverse()
            for p in state['projects']:
                p['nodes'].reverse()
                for n in p['nodes']: n['tasks'].reverse()
            tasks = [t for p in state['projects'] for n in p['nodes'] for t in n['tasks']]
            for i, t in enumerate(tasks[:7]): t['status'] = 'paused' if i % 2 else 'blocked'
        edit_workspace(app, client, pause)
        full = client.get('/api/workspace').json()
        expected = [t['id'] for p in full['projects'] for n in p['nodes'] for t in n['tasks'] if t['status'] in ('paused', 'blocked')]
        shell = client.get('/api/workspace?scope=shell').json()
        assert shell['counts']['blocked_tasks'] == 7 and len(shell['blocked']) == 5
        assert [a['task_id'] for a in shell['blocked']] == expected[:5]
        assert shell['blocked'][0]['status'] == 'blocked'
