"""Read-only partial materialization and isolation from ORM JSON values."""
from copy import deepcopy

import pytest
from sqlalchemy import event, select

from . import storage
from .app import BusinessRow, WorkspaceRow
from .test_perf_budget import scaled_client, count_queries


@pytest.fixture
def workspace_db(tmp_path):
    with scaled_client(tmp_path, 2) as (app, client):
        wid = app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
        with app.state.sessions() as db:
            yield db, db.get(WorkspaceRow, wid)


def test_load_does_not_alias_orm_or_other_loads(workspace_db):
    db, row = workspace_db
    held = list(db.scalars(select(BusinessRow).where(BusinessRow.workspace_id == row.id)))
    before = [deepcopy(record.data) for record in held]
    root = deepcopy(row.data)
    state = storage.load(db, BusinessRow, row)
    expected = deepcopy(state)
    state['users'][0]['capabilities'].append('fictional-test-capability')
    state['projects'][0]['nodes'][0]['tasks'][0]['title'] = 'changed'
    state['calendar']['holidays'].append('2099-01-01')
    assert [record.data for record in held] == before
    assert row.data == root
    assert storage.load(db, BusinessRow, row) == expected


def test_save_refuses_partial_before_any_write(workspace_db):
    db, row = workspace_db
    with pytest.raises(ValueError, match='read-only'):
        storage.save(db, BusinessRow, row.id, {'_partial': {}})
    assert not db.new and not db.dirty and not db.deleted


@pytest.mark.parametrize('collection', [kind for kind in storage.COLLECTIONS if kind != 'projects'])
def test_partial_collection_matches_full_load(workspace_db, collection):
    db, row = workspace_db
    full = storage.load(db, BusinessRow, row)
    if not full[collection]:
        full[collection] = [{'id': 'fictional-' + collection, 'nested': {'values': [1, 2]}}]
        row.data = storage.save(db, BusinessRow, row.id, full)
        db.flush()
        full = storage.load(db, BusinessRow, row)
    partial = storage.load_partial(db, BusinessRow, row, collections=(collection,))
    assert partial[collection] == full[collection]
    assert all(partial[kind] == [] for kind in storage.COLLECTIONS if kind != collection)
    assert partial['_partial']['collections'] == [collection]
    partial[collection][0]['id'] = 'changed'
    assert storage.load(db, BusinessRow, row)[collection] == full[collection]


def test_demo_identity_reads_only_users(tmp_path):
    with scaled_client(tmp_path, 2) as (app, client):
        statements = []
        def capture(conn, cursor, statement, parameters, context, executemany):
            if 'FROM business_records' in statement:
                statements.append((statement, parameters))
        event.listen(app.state.engine, 'before_cursor_execute', capture)
        try:
            assert client.get('/api/projects?limit=30').status_code == 200
        finally:
            event.remove(app.state.engine, 'before_cursor_execute', capture)
        assert len(statements) == 2
        # The list endpoint reads only project headers, never the whole workspace.
        assert 'business_records.kind !=' not in statements[1][0]
        assert 'projects' in statements[1][1] and 'nodes' not in statements[1][1]
        assert 'business_records.kind IN' in statements[0][0]
        assert 'users' in statements[0][1]


def test_partial_empty_selection_skips_business_records(workspace_db):
    db, row = workspace_db
    with count_queries(db.get_bind()) as stats:
        partial = storage.load_partial(db, BusinessRow, row)
    assert stats['queries'] == 0
    assert all(partial[kind] == [] for kind in storage.COLLECTIONS)
    with pytest.raises(ValueError, match='read-only'):
        storage.save(db, BusinessRow, row.id, partial)


def test_partial_legacy_users_are_isolated(workspace_db):
    db, row = workspace_db
    row.data = storage.load(db, BusinessRow, row)
    row.data.pop('storage_schema')
    db.flush()
    expected = deepcopy(row.data)
    with count_queries(db.get_bind()) as stats:
        partial = storage.load_partial(db, BusinessRow, row, collections=('users',))
    assert stats['queries'] == 0
    assert partial['users'] == expected['users']
    assert partial['projects'] == []
    partial['users'][0]['capabilities'].append('fictional-test-capability')
    partial['calendar']['holidays'].append('2099-01-01')
    assert row.data == expected


def test_partial_rejects_unknown_collection(workspace_db):
    db, row = workspace_db
    with pytest.raises(ValueError, match='unknown workspace collection'):
        storage.load_partial(db, BusinessRow, row, collections=('migration_archive',))


@pytest.fixture
def complete_projects(workspace_db):
    db, row = workspace_db
    state = storage.load(db, BusinessRow, row)
    for project in state['projects']:
        for child in storage.PROJECT_CHILDREN:
            if not project[child]:
                project[child] = [{'id': project['id'] + '-' + child, 'values': [1, 2]}]
        for node in project['nodes']:
            node['review_cycles'] = [{'id': node['id'] + '-review', 'values': [1, 2]}]
    row.data = storage.save(db, BusinessRow, row.id, state)
    db.flush()
    return db, row, storage.load(db, BusinessRow, row)


@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('child', storage.PROJECT_CHILDREN)
def test_partial_project_parent_slices(complete_projects, legacy, child):
    db, row, full = complete_projects
    if legacy:
        row.data = deepcopy(full)
        row.data.pop('storage_schema')
        db.flush()
    project = full['projects'][1]
    partial = storage.load_partial(db, BusinessRow, row,
                                   project_ids=(project['id'],), project_children=(child,))
    expected = deepcopy(project)
    for omitted in storage.PROJECT_CHILDREN:
        if omitted != child:
            expected[omitted] = []
    assert partial['projects'] == [expected]
    assert partial['projects'][0]['nodes'][0]['review_cycles']
    assert all(partial[kind] == [] for kind in storage.COLLECTIONS if kind != 'projects')
    partial['projects'][0]['nodes'][0]['tasks'][0]['title'] = 'changed'
    assert storage.load(db, BusinessRow, row)['projects'] == full['projects']


@pytest.mark.parametrize('legacy', [False, True])
def test_partial_project_headers_and_multiple_ids(complete_projects, legacy):
    db, row, full = complete_projects
    if legacy:
        row.data = deepcopy(full)
        row.data.pop('storage_schema')
        db.flush()
    headers = storage.load_partial(db, BusinessRow, row, collections=('projects',))
    expected = deepcopy(full['projects'])
    for project in expected:
        project['nodes'] = []
        for child in storage.PROJECT_CHILDREN:
            project[child] = []
    assert headers['projects'] == expected
    ids = [p['id'] for p in reversed(full['projects'])]
    all_projects = storage.load_partial(db, BusinessRow, row, collections=('users',),
                                        project_ids=ids, project_children=storage.PROJECT_CHILDREN)
    assert all_projects['projects'] == full['projects']  # Persisted ordinal order.
    assert all_projects['users'] == full['users']
    for ids in ([], ['does-not-exist']):
        assert storage.load_partial(db, BusinessRow, row, collections=('projects',),
                                    project_ids=ids)['projects'] == []


def test_partial_project_does_not_read_other_workspace(complete_projects):
    db, row, full = complete_projects
    other = WorkspaceRow(id='fictional-other-workspace', version=1, data={})
    db.add(other)
    db.flush()
    different = deepcopy(full)
    different['projects'][0]['nodes'][0]['tasks'][0]['title'] = 'other workspace'
    other.data = storage.save(db, BusinessRow, other.id, different)
    db.flush()
    partial = storage.load_partial(db, BusinessRow, row,
                                   project_ids=(full['projects'][0]['id'],),
                                   project_children=storage.PROJECT_CHILDREN)
    assert partial['projects'] == full['projects'][:1]


def test_partial_rejects_unknown_project_child(workspace_db):
    db, row = workspace_db
    with pytest.raises(ValueError, match='unknown project child'):
        storage.load_partial(db, BusinessRow, row, project_children=('users',))


def test_partial_project_uses_only_selected_kinds_and_parents(complete_projects):
    db, row, full = complete_projects
    statements = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append((statement, parameters))
    event.listen(db.get_bind(), 'before_cursor_execute', capture)
    try:
        partial = storage.load_partial(db, BusinessRow, row,
                                       project_ids=(full['projects'][0]['id'],),
                                       project_children=('files',))
    finally:
        event.remove(db.get_bind(), 'before_cursor_execute', capture)
    assert len(statements) == 3
    assert all('business_records.workspace_id =' in query and
               'business_records.kind IN' in query for query, params in statements)
    assert 'business_records.entity_id IN' in statements[0][0]
    assert all('business_records.parent_id IN' in query for query, params in statements)
    assert not any('events' in params or 'project_comments' in params for query, params in statements)
    assert {key: value for key, value in partial.items()
            if key not in storage.COLLECTIONS and key != '_partial'} == {
                key: value for key, value in full.items() if key not in storage.COLLECTIONS}
