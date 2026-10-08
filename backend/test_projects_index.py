"""VCC-98 P3-3: /api/projects served from project_index equals the legacy full-state path byte for byte."""
import pytest
from sqlalchemy import event, select
from . import index_reads, storage, workspace_environment
from .models import BusinessRow, WorkspaceRow
from .policy import upgrade
from .test_perf_budget import scaled_client

ON = dict(upgraded=True, INDEX_TABLES_ENABLED='true')
USERS = ('u-manager', 'u-pm', 'ou_020')
QUERIES = ['', '?limit=5', '?offset=3&limit=4', '?offset=500', '?q=a', '?q=%E7%AC%AC1', '?q=C1150', '?q=%25', '?q=_', '?q=%E5%AE%A2%E6%88%B6%E5%96%AE%E4%BD%8D1',
           '?q=ZZZ-none', '?q=C115001%20%E7%AC%AC', '?status=in_progress', '?status=completed&limit=7', '?status=nope', '?owner=u-pm', '?owner=ou_006&limit=2',
           '?q=a&status=in_progress&owner=u-pm&offset=1&limit=3', '?limit=100', '?q=%C3%89', '?q=Stra%C3%9Fe']


def reshape(app):
    """Vary due dates, source status and visibility so sorting, null mapping and visibility are exercised."""
    with app.state.sessions.begin() as db:
        row = db.get(WorkspaceRow, db.scalars(select(WorkspaceRow.id)).first()); state = upgrade(storage.load(db, BusinessRow, row)); state['version'] = row.version + 1
        for i, p in enumerate(state['projects']):
            if i % 7 == 0: p['due_date'] = None
            if i % 11 == 0: p.pop('due_date')
            if i % 5 == 0: p.pop('source_status', None)
            p['case_visibility'] = ('new_case', 'source_reference', 'excluded_history', 'new_case')[i % 4]
            p['status'] = ('in_progress', 'completed', 'paused')[i % 3]
            if i % 6 == 0: p['name'] = p['name'] + ' Alpha_100%'
        row.data = storage.save(db, BusinessRow, row.id, state); row.version = state['version']


def both(client, monkeypatch, path):
    current = client.get('/api/projects' + path)
    with monkeypatch.context() as m:
        m.setattr(index_reads, 'ready', lambda *a: False)
        legacy = client.get('/api/projects' + path)
    return legacy, current


@pytest.mark.parametrize('environment', ['demo', 'production'])
def test_index_page_is_byte_identical_to_legacy(tmp_path, monkeypatch, environment):
    with scaled_client(tmp_path, 40, **ON) as (app, client):
        reshape(app)
        if environment == 'production':
            monkeypatch.setattr(workspace_environment, 'normalize_environment', lambda state, wid, cfg: state.update(environment='production') or state)
        served = []
        for uid in USERS:
            assert client.post('/api/demo/session', json={'user_id': uid}).status_code == 200
            for query in QUERIES:
                legacy, current = both(client, monkeypatch, query)
                assert current.status_code == legacy.status_code == 200, query
                assert current.content == legacy.content, (uid, query)
                served.append(current.json()['total'])
        assert len(set(served)) > 3
        if environment == 'production':
            full = client.get('/api/projects?limit=100').json()
            assert full['total'] < 40 and full['total'] == sum(1 for i in range(40) if i % 4 != 2)


def test_index_pages_reject_bad_paging_like_legacy(tmp_path):
    with scaled_client(tmp_path, 5, **ON) as (app, client):
        assert client.get('/api/projects?limit=0').status_code == 422 and client.get('/api/projects?offset=-1').status_code == 422


def test_first_page_reads_ten_rows_and_never_loads_projects(tmp_path):
    with scaled_client(tmp_path, 60, **ON) as (app, client):
        statements = []
        listener = lambda conn, cur, st, params, ctx, many: statements.append((st, params))
        event.listen(app.state.engine, 'before_cursor_execute', listener)
        try: body = client.get('/api/projects?limit=10').json()
        finally: event.remove(app.state.engine, 'before_cursor_execute', listener)
        assert len(body['items']) == 10 and body['total'] == 60
        pages = [(st, p) for st, p in statements if 'FROM project_index' in st and 'LIMIT' in st]
        assert len(pages) == 1 and 10 in pages[0][1] and 'OFFSET' in pages[0][0]
        assert 'summary' not in pages[0][0] and 'project_index.name' in pages[0][0]
        flat = [x for st, p in statements for x in (p if isinstance(p, (tuple, list)) else tuple(p.values()))]
        assert not {'projects', 'nodes', 'tasks'} & set(flat), 'no project/node/task business rows may be loaded'
        assert not any('FROM business_records' in st and 'tasks' in str(p) for st, p in statements)


def test_stale_or_missing_index_uses_legacy_path(tmp_path):
    with scaled_client(tmp_path, 10, upgraded=True) as (app, client):  # INDEX_TABLES_ENABLED off
        assert client.get('/api/projects?limit=3').json()['total'] == 10
    with scaled_client(tmp_path / 'b', 10, **ON) as (app, client):
        with app.state.sessions.begin() as db:
            db.get(WorkspaceRow, db.scalars(select(WorkspaceRow.id)).first()).version += 1
        assert client.get('/api/projects?limit=3').json()['total'] == 10


def test_null_shell_facts_falls_back_and_reconcile_detects_corruption(tmp_path):
    from sqlalchemy import null, update
    from . import index_tables
    from .models import ProjectIndex
    from .test_shell import ON as SHELL_ON
    from scripts.backfill_index import backfill

    with scaled_client(tmp_path, 2, **SHELL_ON) as (app, client):
        with app.state.sessions.begin() as db:
            db.execute(update(ProjectIndex).where(ProjectIndex.project_id == 'p001').values(shell_facts=null()))
        full = client.get('/api/workspace?scope=shell').json()
        assert full.get('scope') is None and len(full['projects'][0]['nodes']) == 9
        assert client.get('/api/projects?view=overview').status_code == 503
        backfill(app.state.engine)
        assert client.get('/api/workspace?scope=shell').json()['scope'] == 'shell'
        with app.state.sessions.begin() as db:
            db.execute(update(ProjectIndex).where(ProjectIndex.project_id == 'p001').values(shell_facts={'v': 1, 'contract_amount': -1}))
            row = db.get(WorkspaceRow, full['workspace_id'])
            report = index_tables.reconcile(db, BusinessRow, row.id, upgrade(storage.load(db, BusinessRow, row)))
        assert not report['healthy'] and report['projects']['stale'] == ['p001']


def test_shell_facts_use_refreshed_nodes_and_raw_fallback():
    from .index_tables import project_rows
    from .operations import project_summary
    from .perf_fixture import build_scaled_workspace
    from copy import deepcopy

    state = upgrade(build_scaled_workspace(1)); p = state['projects'][0]
    p['contract_amount'] = 123.5
    p['source_lifecycle'] = {'relationship': '待確認單', 'state': 'needs_verification', 'canonical': None,
                             'reasons': ['blank'], 'lifecycle_sources': [{'source_id': 'secret-id'}]}
    refreshed = project_summary(state, deepcopy(p))
    row = project_rows('w', state)[0][0]
    expected = [{'key': n['key'], 'name': s['name'], 'status': s['status']}
                for n, s in zip(p['nodes'], refreshed['nodes']) if s['status'] in ('in_progress', 'paused')]
    assert row['shell_facts'] == {'v': 1, 'contract_amount': 123.5, 'current_nodes': expected,
                                  'source_lifecycle': {'relationship': '待確認單', 'state': 'needs_verification',
                                                       'canonical': None, 'reasons': ['blank']}}
    # A malformed legacy node makes project_summary fail; facts still preserve raw stage status.
    p['nodes'][0].pop('key'); p['nodes'][0]['status'] = 'paused'
    fallback = project_rows('w', state)[0][0]
    assert fallback['summary'] is None
    assert fallback['shell_facts']['current_nodes'][0] == {'key': '', 'name': p['nodes'][0]['name'], 'status': 'paused'}
