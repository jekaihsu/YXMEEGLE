"""P1-INT: GET /api/source-health and GET /api/my-work. Synthetic isolated SQLite only; no Lark or cloud data."""
import json
import time
import pytest
from fastapi.testclient import TestClient
from .app import create_app, WorkspaceRow, AuthRow, CacheRow, BusinessRow, PersonRow
from .seed import seed
from .policy import upgrade
from . import storage

BASE, TABLE = 'BASE_TOKEN_SENTINEL', 'TABLE_ID_SENTINEL'


def fresh_cache(**table):
    now = time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())
    tables = [{'base_token': BASE, 'table_id': TABLE, 'name': 'NAME_SENTINEL', 'status': 'ready', 'pages_read': 1,
               'count': 1, 'last_sync': now, **table}]
    return {'status': 'ready', 'configured': True, 'last_sync': now, 'tables': tables,
            'records': [{'base_token': BASE, 'table_id': TABLE, 'record_id': 'recNew', 'kind': 'quote', 'fields': {'工程名稱': 'Current case'}},
                        {'base_token': BASE, 'table_id': TABLE, 'record_id': 'recOld', 'kind': 'quote', 'fields': {'工程名稱': 'OLD_CASE_SENTINEL'}}]}


@pytest.fixture
def http(tmp_path):
    app = create_app({'DATABASE_URL': f'sqlite:///{tmp_path}/p1int.db', 'UPLOAD_DIR': str(tmp_path / 'files'),
                      'DEMO_MODE': 'false', 'APP_ENV': 'development', 'SESSION_SECRET': 'p1-int-only' * 4,
                      'LARK_WORKER_ORGANIZATION': 'boundary', 'LARK_ALLOWED_TENANTS': 'boundary'})
    state = upgrade(seed()); state['environment'] = 'production'
    for project in state.get('projects', []): project['source_kind']='lark'
    for p in state['projects']: p.update(case_visibility='excluded_history', execution_system='meegle')
    old, new = state['projects'][:2]
    old['name'] = 'OLD_CASE_SENTINEL'; old['nodes'][0]['tasks'][0].update(status='in_progress', title='OLD_CASE_SENTINEL task')
    new.update(case_visibility='new_case', execution_system='workbench', name='Current case')
    new['nodes'][0]['tasks'][0].update(status='in_progress', title='Current task')
    state['source_visible_record_ids'] = [f'{BASE}|{TABLE}|recNew']

    def seat(wid='lark-boundary', cache=None, profiles=()):
        with app.state.sessions.begin() as db:
            row = WorkspaceRow(id=wid, version=state['version'], data={}); db.add(row); db.flush()
            row.data = storage.save(db, BusinessRow, row.id, dict(state, environment='test' if wid.startswith('test-') else 'production'))
            if profiles:
                for user in state['users']:
                    if user['id'] in profiles: db.add(PersonRow(organization_id=wid.removeprefix('test-'), person_id=user['id'], data=user))
            db.add(AuthRow(id='sess-' + wid, data={'wid': wid, 'expires': time.time() + 3600}))
            if cache is not None: db.add(CacheRow(id=wid, data=cache))
    client = TestClient(app)

    def signin(uid, wid='lark-boundary'):
        client.cookies.set('meegle_session', app.state.signer.dumps({'mode': 'lark', 'sid': 'sess-' + wid, 'wid': wid, 'uid': uid}))
    return app, client, seat, signin, state


def make_fresh(app, monkeypatch):
    real = app.state.live_read.status
    def status(wid):
        out = real(wid); out['datasets']['sources'].update(status='fresh', age_seconds=1, ttl_seconds=900, last_error=None)
        return out
    monkeypatch.setattr(app.state.live_read, 'status', status)


# ---- auth ------------------------------------------------------------------
@pytest.mark.parametrize('path', ['/api/source-health', '/api/my-work'])
def test_unauthenticated_is_401(http, path):
    _, client, seat, _, _ = http
    seat(cache=fresh_cache())
    assert client.get(path).status_code == 401


@pytest.mark.parametrize('path', ['/api/source-health', '/api/my-work'])
def test_unadmitted_production_identity_is_forbidden(tmp_path, path):
    from .test_company_admin_admission import fixtures
    cfg, person, _ = fixtures()
    person['oauth_identity'].pop('open_id')  # no verified identity: require_access refuses (same as every other route)
    cfg.update(DATABASE_URL=f'sqlite:///{tmp_path}/f.db', UPLOAD_DIR=str(tmp_path / 'u'), APP_ENV='development', DEMO_MODE='false',
               SESSION_SECRET='p1-int-forbid' * 4, LARK_APP_SECRET='x', LARK_REDIRECT_URI='https://example.test/cb')
    app = create_app(cfg)
    state = upgrade(seed()); state.update(environment='production', users=[person])
    with app.state.sessions.begin() as db:
        row = WorkspaceRow(id='lark-tenant', version=state['version'], data={}); db.add(row); db.flush()
        row.data = storage.save(db, BusinessRow, row.id, state)
        db.add(PersonRow(organization_id='lark-tenant', person_id=person['id'], data=person))
        db.add(AuthRow(id='a', data={'wid': 'lark-tenant', 'expires': time.time() + 3600}))
        db.add(CacheRow(id='lark-tenant', data=fresh_cache()))
    client = TestClient(app)
    client.cookies.set('meegle_session', app.state.signer.dumps({'mode': 'lark', 'sid': 'a', 'wid': 'lark-tenant', 'uid': person['id']}))
    response = client.get(path)
    assert response.status_code == 403, response.text
    assert 'SENTINEL' not in response.text


# ---- source health ---------------------------------------------------------
def test_source_health_exposes_page_state_only_and_no_source_or_hidden_value(http, monkeypatch):
    app, client, seat, signin, _ = http
    make_fresh(app, monkeypatch)
    seat(cache=fresh_cache()); signin('u-manager')
    response = client.get('/api/source-health')
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) <= {'page_state', 'sources', 'error'} and body['sources'] == []
    for sentinel in (BASE, TABLE, 'NAME_SENTINEL', 'OLD_CASE_SENTINEL', 'Current case', 'recOld', 'recNew', 'diagnostic'):
        assert sentinel not in response.text
    # None is derived from the cached snapshot, not from proof of a complete read of THIS request; the route adds no
    # healthy/clean/complete field, so the client must treat it as unknown.
    assert body['page_state'] is None
    assert not {'healthy', 'health', 'complete', 'clean', 'status', 'label'} & set(body)
    assert '資料正常' not in response.text


def test_source_health_unknown_is_not_zero_or_empty(http, monkeypatch):
    app, client, seat, signin, state = http
    make_fresh(app, monkeypatch)
    state['source_visible_record_ids'] = []  # admitted none: visible count becomes 0
    seat(cache=fresh_cache()); signin('u-manager')
    body = client.get('/api/source-health').json()
    # visible_source_snapshot narrows rows to admitted ids, so zero cannot prove complete_empty or a filter.
    assert body['page_state'] == {'states': ['unknown'], 'count': None}


def test_source_health_without_cache_or_in_test_workspace_is_unknown(http):
    _, client, seat, signin, _ = http
    seat(cache=None); signin('u-manager')
    assert client.get('/api/source-health').json()['page_state']['states'] == ['unknown']
    seat('test-lark-boundary', cache=fresh_cache()); signin('u-manager', 'test-lark-boundary')
    response = client.get('/api/source-health')  # test namespace: same branch as GET /api/sources
    assert response.status_code == 200 and response.json()['page_state']['states'] == ['unknown']
    assert BASE not in response.text and 'SENTINEL' not in response.text


def test_source_health_forbidden_source_and_failed_read_leak_nothing(http):
    _, client, seat, signin, _ = http
    seat(cache=fresh_cache(status='forbidden')); signin('u-manager')
    body = client.get('/api/source-health').json()
    assert body['sources'] == [] and 'NAME_SENTINEL' not in json.dumps(body)
    assert 'forbidden' not in (body['page_state'] or {}).get('states', []) or body['page_state'] == {'states': ['forbidden']}


@pytest.mark.parametrize('uid,expected', [('u-manager', True), ('u-pm', True), ('u-field', False)])
def test_source_health_passes_the_sync_predicate_and_closed_arguments(http, monkeypatch, uid, expected):
    _, client, seat, signin, _ = http
    seat(cache=fresh_cache()); signin(uid)
    seen = {}
    from . import source_health

    def spy(snapshot, freshness=None, **kwargs):
        seen.update(kwargs); seen['snapshot'] = snapshot
        return {'page_state': None, 'sources': []}
    monkeypatch.setattr(source_health, 'build_source_health', spy)
    assert client.get('/api/source-health').status_code == 200
    assert (seen['diagnostic'], seen['viewer_filtered'], seen['read_authorized']) == (False, None, expected)
    if not expected: assert client.post('/api/sources/sync').status_code == 403  # same refusal as the predicate's False
    assert [r['record_id'] for r in seen['snapshot']['records']] == ['recNew']  # hidden case rows narrowed before projection


# ---- my work ---------------------------------------------------------------
def test_my_work_shows_visible_tasks_and_hides_excluded_cases(http):
    _, client, seat, signin, _ = http
    seat(); signin('u-pm')
    response = client.get('/api/my-work')
    assert response.status_code == 200, response.text
    body = response.json()
    assert 'OLD_CASE_SENTINEL' not in response.text
    assert body['rows'] and all(r['id'].startswith('p2-') for r in body['rows'])  # p1 is the excluded case
    assert 'Current task' in [r['title'] for r in body['rows']]
    assert 'weeklyActivity' not in body


def test_my_work_other_viewer_gets_no_foreign_task_and_unknown_is_not_zero(http):
    _, client, seat, signin, _ = http
    seat(); signin('u-field')
    body = client.get('/api/my-work').json()
    assert 'Current task' not in json.dumps(body) and 'OLD_CASE_SENTINEL' not in json.dumps(body)
    assert all(r['id'].startswith('p2-') for r in body['rows'])  # only the viewer's own, visible tasks


def test_my_work_test_workspace_branch_and_routes_not_added(http):
    app, client, seat, signin, _ = http
    seat('test-lark-boundary'); signin('u-pm', 'test-lark-boundary')
    response = client.get('/api/my-work')
    assert response.status_code == 200 and response.json()['rows'] and response.json()['readState'] != 'forbidden'
    assert client.get('/api/my-work/activity').status_code == 404  # 126B2 is not built
    assert client.post('/api/my-work').status_code == 405 and client.post('/api/source-health').status_code == 405


def test_my_work_load_failure_is_read_failed_not_empty(http, monkeypatch):
    app, client, seat, signin, _ = http
    seat(profiles=('u-pm',)); signin('u-pm')
    monkeypatch.setattr(storage, 'load', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')))
    response = client.get('/api/my-work')
    assert response.status_code == 200 and response.json()['readState'] == {'states': ['read_failed'], 'count': None}
    assert response.json()['rows'] == [] and response.json()['assignment'] == 'unknown' and 'boom' not in response.text
