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
        assert client.get('/api/session').json()['features'] == {'change_extension':False,'routines':False,'mock_ui':False,'local_case_creation':False,'sop_task_writes':False}
        full = client.get('/api/workspace').json()
        shellish = client.get('/api/workspace?scope=shell').json()
        assert shellish.get('scope') is None and len(shellish['projects'][0]['nodes']) > 0
        assert set(full) == set(shellish) and len(full['projects']) == len(shellish['projects'])


def test_shell_advertised_and_scope_absent_is_full(tmp_path):
    with scaled_client(tmp_path, 6, **ON) as (app, client):
        assert client.get('/api/session').json()['features'] == {'workspace_shell':True,'change_extension':False,'routines':False,'mock_ui':False,'local_case_creation':False,'sop_task_writes':False}
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
def test_shell_my_counts_equal_ready_assigned_tasks(tmp_path, uid):
    with scaled_client(tmp_path, 12, **ON) as (app, client):
        switch(client, uid)
        full = client.get('/api/workspace').json(); shell = client.get('/api/workspace?scope=shell').json()
        from .test_shell_dashboard_equivalence import actionable
        rows = [(p, t) for p in full['projects'] for n in p['nodes'] for t in n['tasks'] if actionable(full, p, t, uid)]
        late = [(p, t) for p, t in rows if t.get('due_date') and t['due_date'][:10] < shell['as_of']]
        due_today = [(p, t) for p, t in rows if (t.get('due_date') or '')[:10] == shell['as_of']]
        assert shell['counts']['my_overdue_tasks'] == shell['counts']['overdue_tasks'] == len(late)
        assert shell['counts']['my_active_tasks'] == len(rows)
        assert shell['counts']['due_today_tasks'] == len(due_today)
        assert shell['counts']['approvals_pending'] == sum(a['status'] == 'pending' for a in full['approvals'])
        assert shell['counts']['daily_unmatched'] == len(full['daily_unmatched'])
        # Attention contains only ready, assigned tasks with due dates.
        assert all(a['task_id'] for a in shell['attention']) and len(shell['attention']) <= 5


def test_shell_counts_ready_assignment_but_not_missing_prerequisite(tmp_path, monkeypatch):
    monkeypatch.setattr(backend_app, 'now', lambda: '2026-10-07T09:00:00+08:00')
    def ready_and_blocked(state):
        for project in state['projects']:
            project['execution_status'] = 'paused'
        project = state['projects'][0]
        project['source_lifecycle'] = dict(state='mapped', reasons=[], canonical='執行中', relationship='已關聯確認單')
        project['execution_status'] = 'in_progress'
        for node in project['nodes']:
            node['status'] = 'pending'
            for task in node['tasks']: task['status'] = 'completed'
        ready, blocked = project['nodes'][0]['tasks'][:2]
        ready.update(status='in_progress', due_date='2026-10-01', start_date='2026-09-21')
        blocked.update(status='pending', due_date='2026-10-01', start_date='2026-09-21',
                       input_task_ids=['missing-prerequisite'])
    with scaled_client(tmp_path, 3, mutate=ready_and_blocked, **ON) as (app, client):
        switch(client, 'ou_015')
        full = client.get('/api/workspace').json(); shell = client.get('/api/workspace?scope=shell').json()
        ready, blocked = full['projects'][0]['nodes'][0]['tasks'][:2]
        assert ready['can_execute'] is True and not ready['execution_blockers']
        assert blocked['can_execute'] is True and blocked['activation_blockers']
        assert shell['counts']['my_active_tasks'] == shell['counts']['my_overdue_tasks'] == 1
        assert [item['task_id'] for item in shell['attention']] == [ready['id']]
        assert blocked['id'] not in {item['task_id'] for item in shell['attention']}


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
    def ready_first(state):
        project = state['projects'][0]
        project['source_lifecycle'] = dict(state='mapped', reasons=[], canonical='執行中', relationship='已關聯確認單')
        project['execution_status'] = 'in_progress'
        project['nodes'][0]['status'] = 'pending'
    with scaled_client(tmp_path, 8, mutate=ready_first, **ON) as (app, client):
        switch(client, 'ou_015')
        everything = client.get('/api/workspace?scope=shell').json()
        assert everything['counts']['my_active_tasks'] > 0
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
        # The visibility fence and snapshot builder add two queries.
        # Queries include ~14 from live-read ensure()/status and identity that are outside the shell itself (11: two more load the pending approvals the dashboard lists).
        assert stats['queries'] <= 28 and raw <= 165_000 and int(response.headers['content-length']) <= 30_000


def shell_get(client, tag=None):
    return client.get('/api/workspace?scope=shell', headers={'If-None-Match': tag} if tag else {})


def test_shell_etag_304_and_server_timing(tmp_path):
    with scaled_client(tmp_path, 6, **ON) as (app, client):
        switch(client, 'u-pm')
        first = shell_get(client); tag = first.headers['etag']
        assert first.status_code == 200 and tag.startswith('W/"') and first.headers['cache-control'] == 'private, max-age=0, must-revalidate'
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


def test_shell_reuses_encoded_body_after_fresh_authority_checks(tmp_path, monkeypatch):
    from . import shell
    with scaled_client(tmp_path, 6, **ON) as (app, client):
        switch(client, 'u-pm')
        first = shell_get(client)
        tag = first.headers['etag']
        def unexpected(*args, **kwargs):
            raise AssertionError('warm shell must not rebuild its cards and counts')
        monkeypatch.setattr(shell, 'build', unexpected)
        again = shell_get(client)
        assert again.status_code == 200 and again.json() == first.json()
        assert again.headers['x-read-snapshot'] == 'hit'
        validated = shell_get(client, tag)
        assert validated.status_code == 304 and validated.content == b''
        assert validated.headers['vary'] == 'Accept-Encoding, Cookie'
        assert validated.headers['x-request-id'] != first.headers['x-request-id']


def test_shell_validator_survives_clock_aging_but_not_freshness_errors(tmp_path, monkeypatch):
    from copy import deepcopy
    from . import shell
    with scaled_client(tmp_path, 6, **ON) as (app, client):
        switch(client, 'u-pm')
        first = shell_get(client); tag = first.headers['etag']
        fresh = app.state.live_read.status
        def aged(wid):
            result = deepcopy(fresh(wid))
            result['server_time'] = '2099-01-01T00:00:00+00:00'
            for dataset in result['datasets'].values():
                if dataset['age_seconds'] is not None: dataset['age_seconds'] += 121
            return result
        monkeypatch.setattr(app.state.live_read, 'status', aged)
        clock = app.state.read_snapshots.clock
        monkeypatch.setattr(app.state.read_snapshots, 'clock', lambda: clock()+121)
        build = shell.build
        def unexpected(*args, **kw): raise AssertionError('clock-only revalidation must not rebuild')
        monkeypatch.setattr(shell, 'build', unexpected)
        validated = shell_get(client, tag)
        assert validated.status_code == 304 and validated.headers['etag'] == tag
        assert validated.content == b''
        def failed(wid):
            result = aged(wid)
            result['datasets']['sources'].update(status='error', last_error='read failed')
            return result
        monkeypatch.setattr(app.state.live_read, 'status', failed)
        monkeypatch.setattr(shell, 'build', build)
        changed = shell_get(client, tag)
        assert changed.status_code == 200 and changed.headers['etag'] != tag
        assert changed.json()['freshness']['datasets']['sources']['status'] == 'error'


def test_blocked_deferred_progress_does_not_queue_shell(tmp_path):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    entered, release = threading.Event(), threading.Event()
    with scaled_client(tmp_path, 6, **ON) as (app, client), ThreadPoolExecutor(max_workers=2) as pool:
        switch(client, 'u-pm')
        def blocked():
            entered.set()
            assert release.wait(5)
            return b'progress'
        work = pool.submit(app.state.progress_snapshots.get, ('slow-progress',), blocked)
        try:
            assert entered.wait(2)
            response = pool.submit(shell_get, client).result(timeout=2)
            assert response.status_code == 200
            assert not work.done()
        finally:
            release.set()
        assert work.result(timeout=2)[0] == b'progress'
