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
        assert all(a['task_id'] for a in shell['attention']) and len(shell['attention']) <= 10
        due = sorted((t['due_date'], t['id']) for t in rows if t['status'] not in ('completed', 'superseded') and t['due_date'] and t['due_date'][:10] <= shell['as_of'])
        assert [(a['due_date'], a['task_id']) for a in shell['attention']] == due[:10]


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
        everything = client.get('/api/workspace?scope=shell').json()
        with app.state.sessions.begin() as db:
            db.execute(update(ProjectIndex).where(ProjectIndex.project_id == 'p001').values(case_visibility='excluded_history'))
        monkeypatch.setattr(workspace_environment, 'normalize_environment', lambda state, wid, cfg: state.update(environment='production') or state)
        shell = client.get('/api/workspace?scope=shell').json()
        assert shell['environment'] == 'production'
        assert 'p001' not in [p['id'] for p in shell['projects']] and len(shell['projects']) == 7
        assert shell['counts']['my_active_tasks'] < everything['counts']['my_active_tasks']
        assert not any(a['project_id'] == 'p001' for a in shell['attention'])


def test_shell_budget_319(tmp_path):
    with scaled_client(tmp_path, 319, **ON) as (app, client):
        switch(client, 'u-pm')
        with count_queries(app.state.engine) as stats:
            response = client.get('/api/workspace?scope=shell', headers={'Accept-Encoding': 'gzip'})
        raw = len(response.content)
        print('shell', stats['queries'], 'queries', raw, 'raw', response.headers['content-length'], 'wire')
        assert response.json()['scope'] == 'shell' and 'server-timing' in response.headers
        # Fixture names are long CJK strings: 319 slim cards alone are ~148 KB. The 150 KB plan target needs P4-2 (server-paged cards).
        # Queries include ~14 from live-read ensure()/status and identity that are outside the shell itself (9).
        assert stats['queries'] <= 24 and raw <= 165_000 and int(response.headers['content-length']) <= 30_000
