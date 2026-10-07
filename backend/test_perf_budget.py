"""First-load baseline; opt in with YX_RUN_PERF=1 pytest -m perf -s.

Budgets are ceilings so later optimizations can reuse the same fixture. Timings
are diagnostic, never assertions tied to a developer's machine. Measurements
use local SQLite in demo mode with live reads and the shell flag disabled.
"""
import os
from contextlib import contextmanager
from time import perf_counter

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from . import storage
from .app import BusinessRow, WorkspaceRow, create_app
from .perf_fixture import build_scaled_workspace


@contextmanager
def count_queries(engine):
    """Count only SQL executed inside the measured request, excluding setup."""
    stats = {'queries': 0, 'sql_seconds': 0.0}

    def before(conn, cursor, statement, parameters, context, executemany):
        context.perf_started = perf_counter()

    def after(conn, cursor, statement, parameters, context, executemany):
        stats['queries'] += 1
        stats['sql_seconds'] += perf_counter() - context.perf_started

    event.listen(engine, 'before_cursor_execute', before)
    event.listen(engine, 'after_cursor_execute', after)
    try:
        yield stats
    finally:
        event.remove(engine, 'before_cursor_execute', before)
        event.remove(engine, 'after_cursor_execute', after)


@contextmanager
def scaled_client(tmp_path, n_projects):
    app = create_app({
        'DATABASE_URL': f'sqlite:///{tmp_path}/perf.db',
        'UPLOAD_DIR': str(tmp_path / 'uploads'),
        'SESSION_SECRET': 'fictional-perf-secret' * 3,
        'APP_ENV': 'development', 'DEMO_MODE': 'true',
        'LARK_LIVE_READ_ENABLED': 'false', 'WORKSPACE_SHELL_ENABLED': 'false',
        'LARK_APP_ID': '', 'LARK_APP_SECRET': '', 'LARK_ALLOWED_TENANTS': '',
    })
    try:
        with TestClient(app) as client:
            assert client.get('/api/session').status_code == 200
            wid = app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
            with app.state.sessions.begin() as db:
                row = db.get(WorkspaceRow, wid)
                row.data = storage.save(db, BusinessRow, wid,
                                        build_scaled_workspace(n_projects))
            assert client.post('/api/demo/session', json={'user_id': 'u-manager'}).status_code == 200
            yield app, client
    finally:
        app.state.engine.dispose()


def test_scaled_fixture_counts_and_determinism():
    state = build_scaled_workspace()
    assert len(state['users']) == 65
    assert len(state['projects']) == 319
    assert sum(len(p['nodes']) for p in state['projects']) == 2871
    assert sum(len(n['tasks']) for p in state['projects'] for n in p['nodes']) == 7018
    for collection, count in {'events': 7915, 'work_schedules': 1441,
                              'contract_items': 573, 'recurring': 550,
                              'daily_unmatched': 535, 'source_quotes': 322,
                              'source_confirmations': 212, 'approvals': 300}.items():
        assert len(state[collection]) == count
    for child, count in {'daily_reports': 9000, 'files': 1500, 'comments': 900}.items():
        assert sum(len(p[child]) for p in state['projects']) == count
    small = build_scaled_workspace(2)
    assert small == build_scaled_workspace(2)
    small['projects'][0]['nodes'][0]['tasks'][0]['title'] = 'changed'
    assert small != build_scaled_workspace(2)


@pytest.mark.parametrize('size', [0, -1, 1.5, True])
def test_scaled_fixture_rejects_invalid_size(size):
    with pytest.raises(ValueError, match='positive integer'):
        build_scaled_workspace(size)


def test_scaled_fixture_normalized_round_trip(tmp_path):
    with scaled_client(tmp_path, 2) as (app, client):
        wid = app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
        expected = build_scaled_workspace(2)
        with app.state.sessions() as db:
            state = storage.load(db, BusinessRow, db.get(WorkspaceRow, wid))
        for collection in storage.COLLECTIONS:
            expected.setdefault(collection, [])
        for project in expected['projects']:
            project['concurrency_version'] = 1
            for child in storage.PROJECT_CHILDREN:
                project.setdefault(child, [])
        # storage.save preserves the demo's immutable seed event.
        assert len(state['events']) == len(expected['events']) + 1
        state['events'] = [e for e in state['events'] if e['id'] != 'seed-event']
        assert state == {**expected, 'storage_schema': 2}
        response = client.get('/api/workspace')
        assert response.status_code == 200
        assert len(response.json()['projects']) == 2
        # A query listener must not leak into subsequent requests.
        with count_queries(app.state.engine) as stats:
            client.get('/api/workspace')
        queries = stats['queries']
        client.get('/api/workspace')
        assert queries > 0 and stats['queries'] == queries


@pytest.mark.perf
@pytest.mark.skipif(os.environ.get('YX_RUN_PERF') != '1', reason='set YX_RUN_PERF=1 to run company-scale perf checks')
def test_workspace_first_load_budget(tmp_path):
    with scaled_client(tmp_path, 319) as (app, client):
        for encoding in ('identity', 'gzip'):
            with count_queries(app.state.engine) as stats:
                started = perf_counter()
                response = client.get('/api/workspace', headers={'Accept-Encoding': encoding})
                elapsed = perf_counter() - started
            assert response.status_code == 200
            raw_bytes = len(response.content)  # TestClient decodes gzip automatically.
            wire_bytes = int(response.headers['content-length'])
            print(f'workspace {encoding}: {elapsed * 1000:.0f} ms, '
                  f'{stats["sql_seconds"] * 1000:.0f} ms SQL, '
                  f'{stats["queries"]} queries, {raw_bytes} raw bytes, {wire_bytes} wire bytes')
            assert len(response.json()['projects']) == 319
            assert raw_bytes <= 15_000_000
            assert 0 < stats['queries'] <= 16
            if encoding == 'gzip':
                assert response.headers['content-encoding'] == 'gzip'
                assert wire_bytes <= 1_200_000
            else:
                assert 'content-encoding' not in response.headers
                assert wire_bytes == raw_bytes


# (queries, response bytes) ceilings. Measured: session 4 / 9.3 KB, projects 4 / 1.8 KB,
# comment_add 12 / 14.1 MB (whole workspace returned). Tighten as later phases land.
SESSION_MAX = (6, 10_500)
PROJECTS_MAX = (6, 2_200)
COMMENT_MAX = (16, 15_000_000)


@pytest.mark.perf
@pytest.mark.skipif(os.environ.get('YX_RUN_PERF') != '1', reason='set YX_RUN_PERF=1 to run company-scale perf checks')
def test_light_endpoints_budget(tmp_path):
    """Ceilings at today's full-load behaviour; later phases should tighten them."""
    with scaled_client(tmp_path, 319) as (app, client):
        version = client.get('/api/workspace').json()['version']
        requests = {
            'session': lambda: client.get('/api/session'),
            'projects': lambda: client.get('/api/projects?limit=10'),
            'comment_add': lambda: client.post('/api/actions', json={
                'action': 'comment_add', 'version': version, 'request_id': 'perf-comment-1',
                'project_id': build_scaled_workspace(1)['projects'][0]['id'], 'payload': {'body': 'perf'}}),
        }
        measured = {}
        for name, send in requests.items():
            with count_queries(app.state.engine) as stats:
                response = send()
            assert response.status_code == 200, (name, response.text[:200])
            measured[name] = (stats['queries'], len(response.content))
            print(f'{name}: {stats["queries"]} queries, {len(response.content)} bytes, '
                  f'{response.headers["server-timing"]}')
        assert len(client.get('/api/projects?limit=10').json()['items']) == 10
        assert 0 < measured['session'][0] <= SESSION_MAX[0] and measured['session'][1] <= SESSION_MAX[1]
        assert 0 < measured['projects'][0] <= PROJECTS_MAX[0] and measured['projects'][1] <= PROJECTS_MAX[1]
        assert 0 < measured['comment_add'][0] <= COMMENT_MAX[0] and measured['comment_add'][1] <= COMMENT_MAX[1]
