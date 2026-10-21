"""Read amplification and explicit SOP access regressions."""
from copy import deepcopy

from sqlalchemy import event, select
from . import storage
from .app import BusinessRow, WorkspaceRow
from .test_perf_budget import scaled_client
from .test_shell import ON


def test_settings_summary_never_reads_project_trees(tmp_path):
    with scaled_client(tmp_path, 40, **ON) as (app, client):
        statements = []
        def capture(conn, cursor, sql, parameters, context, many):
            if 'FROM business_records' in sql:
                statements.append((sql, parameters))
        event.listen(app.state.engine, 'before_cursor_execute', capture)
        try:
            response = client.get('/api/settings/overview')
        finally:
            event.remove(app.state.engine, 'before_cursor_execute', capture)
        assert response.status_code == 200
        assert len(response.content) < 3000
        assert len(statements) == 1  # identity's users, no summary business reads
        assert statements[0][1][-2:] == ('users', '')


def test_project_scopes_filter_sql_and_keep_shared_policy_inputs(tmp_path):
    with scaled_client(tmp_path, 4, **ON) as (app, client):
        wid = app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
        with app.state.sessions() as db:
            root = db.get(WorkspaceRow, wid)
            held = list(db.scalars(select(BusinessRow).where(BusinessRow.workspace_id == wid)))
            before = [deepcopy(r.data) for r in held]
            part = storage.load_partial(db, BusinessRow, root, collections=storage.DETAIL_COLLECTIONS,
                                        project_ids=['p001'], project_children=storage.PROJECT_CHILDREN, filter_project_rows=True)
            full = storage.load(db, BusinessRow, root)
            for kind in storage.READ_PROJECT_LINKED:
                assert part[kind] == [r for r in full[kind] if r.get('project_id') in (None, 'p001')]
            # Work schedules, leave grants and duplicate-number quotes are shared policy inputs.
            for kind in ('users', 'work_schedules', 'approved_leave_delegations', 'source_quotes', 'source_confirmations'):
                assert part[kind] == full[kind]
            part['projects'][0]['nodes'][0]['tasks'][0]['title'] = 'viewer-only mutation'
            assert [r.data for r in held] == before
            legacy = type('Root', (), {'id': wid, 'data': full})()
            legacy.data.pop('storage_schema', None)
            legacy_part = storage.load_partial(db, BusinessRow, legacy, collections=storage.DETAIL_COLLECTIONS,
                                               project_ids=['p001'], project_children=storage.PROJECT_CHILDREN, filter_project_rows=True)
            for kind in storage.READ_PROJECT_LINKED:
                assert legacy_part[kind] == [r for r in full[kind] if r.get('project_id') in (None, 'p001')]


def test_denied_sop_read_does_not_materialize_case_and_read_grants_work_without_writes(tmp_path):
    with scaled_client(tmp_path, 8, **ON, SOP_TASK_WRITES_ENABLED='false') as (app, client):
        wid = app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
        statements = []
        def capture(conn, cursor, sql, parameters, context, many):
            if 'FROM business_records' in sql:
                statements.append(parameters)
        event.listen(app.state.engine, 'before_cursor_execute', capture)
        try:
            for endpoint in ('sop-tasks', 'sop-assignees'):
                response = client.get('/api/projects/p001/' + endpoint)
                assert response.status_code == 403
                assert response.json()['code'] == 'sop_import_forbidden'
        finally:
            event.remove(app.state.engine, 'before_cursor_execute', capture)
        assert len(statements) == 2  # identity only, one users query per request
        assert all(p[-2:] == ('users', '') for p in statements)
        with app.state.sessions.begin() as db:
            user = db.get(BusinessRow, (wid, 'users', 'u-manager'))
            user.data = {**user.data, 'capabilities': [*user.data['capabilities'], 'sop_task_read']}
        for endpoint in ('sop-tasks', 'sop-assignees'):
            assert client.get('/api/projects/p001/' + endpoint).status_code == 200
            assert client.get('/api/projects/missing/' + endpoint).status_code == 404
        result = client.get('/api/projects/p001/sop-tasks').json()
        assert result['allowed_actions']['import'] is False


def test_formal_settings_reads_snapshot_summary_without_source_records(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from .models import CacheRow
    from .settings_overview import register
    with scaled_client(tmp_path, 2, **ON) as (app, client):
        with app.state.sessions.begin() as db:
            db.add(WorkspaceRow(id='formal', version=1, data={'environment': 'production'}))
            db.add(CacheRow(id='formal', data={'status': 'ready', 'last_sync': '2026-10-14T15:00:00Z',
                'tables': [{'base_token': 'base', 'table_id': 'table', 'name': 'summary evidence',
                            'status': 'ready', 'pages_read': 1, 'count': 5}],
                'records': [{'private': 'NEVER_DECODE_THIS_RECORD'}]}))
        api = FastAPI()
        register(api, lambda _: ({'wid': 'formal', 'mode': 'lark'}, {'role': 'manager', 'name': 'reader'}),
                 lambda *_: (_ for _ in ()).throw(AssertionError('no full load')),
                 app.state.sessions, WorkspaceRow, CacheRow, {})
        statements = []
        def capture(conn, cursor, sql, parameters, context, many):
            if 'FROM source_caches' in sql:
                statements.append((sql, parameters))
        event.listen(app.state.engine, 'before_cursor_execute', capture)
        try:
            result = TestClient(api).get('/api/settings/overview')
        finally:
            event.remove(app.state.engine, 'before_cursor_execute', capture)
        assert result.status_code == 200
        assert result.json()['sources'][0]['name'] == 'summary evidence'
        assert 'NEVER_DECODE' not in result.text
        assert len(statements) == 1
        assert 'JSON_EXTRACT' in statements[0][0]
        assert not any('records' in str(p) for p in statements[0][1])


def test_authorized_personnel_read_preserves_form_grants_without_widening_workspace(tmp_path):
    with scaled_client(tmp_path, 2, **ON) as (app, client):
        wid = app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
        caps = ['sop_task_read', 'sop_task_import', 'sop_task_work', 'create_local_case']
        with app.state.sessions.begin() as db:
            person = db.get(BusinessRow, (wid, 'users', 'ou_020'))
            person.data = {**person.data, 'capabilities': caps}
        ordinary = client.get('/api/workspace').json()
        assert 'capabilities' not in next(u for u in ordinary['users'] if u['id'] == 'ou_020')
        response = client.get('/api/settings/personnel')
        assert response.status_code == 200
        assert response.json()['version'] == ordinary['version']
        assert next(u for u in response.json()['users'] if u['id'] == 'ou_020')['capabilities'] == caps
        assert client.post('/api/demo/session', json={'user_id': 'ou_020'}).status_code == 200
        assert client.get('/api/settings/personnel').status_code == 403


def test_sop_identity_rejection_is_distinct_from_missing_capability():
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from .sop_import.routes import register
    api = FastAPI()
    def denied_identity(_):
        raise HTTPException(403, 'admission denied')
    def no_case(*_):
        raise AssertionError('identity failure must not load a case')
    register(api, identity=denied_identity, load_case=no_case, sessions=None, cfg={})
    with TestClient(api) as client:
        for path in ('sop-tasks', 'sop-assignees'):
            result = client.get('/api/projects/p001/' + path)
            assert result.status_code == 403
            assert result.json()['code'] == 'identity_forbidden'
