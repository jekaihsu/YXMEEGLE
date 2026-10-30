"""Unchanged refreshes use a revision proof; writes always invalidate that proof."""
import os
from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from . import source_sync, storage
from .source_sync import SourceSyncService
from .sources import normalized_case
from .test_source_sync import harness as sqlite_harness  # noqa: F401


@pytest.fixture(params=['sqlite', 'postgresql'])
def harness(request, sqlite_harness):
    h = sqlite_harness
    if request.param == 'sqlite':
        yield h
        return
    url = os.environ.get('ACTION_AUDIT_TEST_POSTGRES_URL')
    if not url:
        pytest.skip('set ACTION_AUDIT_TEST_POSTGRES_URL to an isolated PostgreSQL test database')
    schema = 'source_refresh_' + uuid4().hex
    engine = create_engine(url, execution_options={'schema_translate_map': {None: schema}})
    try:
        with engine.begin() as db:
            db.execute(CreateSchema(schema))
        h.W.metadata.create_all(engine)
        with h.sessions() as source, engine.begin() as target:
            for table in h.W.metadata.sorted_tables:
                rows = [dict(row) for row in source.execute(select(table)).mappings()]
                if rows:
                    target.execute(table.insert(), rows)
        h.sessions = sessionmaker(engine, expire_on_commit=False)
        h.service = SourceSyncService(h.sessions, h.W, h.B, h.P, h.A, h.C, h.cfg,
                                      fetcher=h.service.fetcher)

        def read():
            with h.sessions() as db:
                return storage.load(db, h.B, db.get(h.W, h.wid)), deepcopy(db.get(h.C, h.wid).data)

        h.read = read
        yield h
    finally:
        with engine.begin() as db:
            db.execute(DropSchema(schema, cascade=True))
        engine.dispose()


def sync(h):
    return h.service.sync(h.wid, 'u-manager', skip_unchanged=True)


def test_unchanged_refresh_reads_only_users_and_templates(harness, monkeypatch):
    h = harness
    sync(h)
    before, _ = h.read()
    h.clock[0] = '2026-09-27T10:01:00+08:00'

    def forbidden(*args, **kwargs):
        raise AssertionError('unchanged refresh must not load, save or re-import the workspace')

    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if 'business_records' in statement:
            statements.append((statement, parameters))

    with monkeypatch.context() as patch:
        patch.setattr(storage, 'load', forbidden)
        patch.setattr(storage, 'save', forbidden)
        patch.setattr(h.service, '_import', forbidden)
        event.listen(h.sessions.kw['bind'], 'before_cursor_execute', capture)
        try:
            sync(h)
            h.clock[0] = '2026-09-27T10:02:00+08:00'
            sync(h)
        finally:
            event.remove(h.sessions.kw['bind'], 'before_cursor_execute', capture)
    after, cache = h.read()
    assert after['projects'] == before['projects']
    assert after['approvals'] == before['approvals']
    assert after['events'] == before['events']
    assert after['version'] == before['version'] + 2
    assert after['source_status']['sync_revision'] == before['source_status']['sync_revision']
    assert after['source_status']['last_sync'] == cache['last_sync'] == h.clock[0]
    assert statements
    assert all(statement.lstrip().startswith('SELECT') and 'kind IN' in statement
               and set(parameters.values() if isinstance(parameters, dict) else parameters) <=
               {h.wid, '', 'users', 'sop_templates'}
               for statement, parameters in statements)


@pytest.mark.parametrize('mode', ['full', 'collections', 'scoped'])
def test_every_storage_writer_invalidates_the_projection_revision(harness, mode):
    h = harness
    sync(h)
    pid = h.read()[0]['projects'][0]['id']
    with h.sessions.begin() as db:
        row = db.get(h.W, h.wid)
        assert row.data['source_status']['projection_workspace_version'] == row.version
        if mode == 'full':
            state = storage.load(db, h.B, row)
            root = storage.save(db, h.B, h.wid, state)
        elif mode == 'collections':
            state = storage.load_partial(db, h.B, row, collections=('users',))
            root = storage.save_collections(db, h.B, h.wid, state, ('users',))
        else:
            state, order = storage.load_scoped(db, h.B, row, collections=(), project_ids=(pid,))
            root = storage.save_partial(db, h.B, h.wid, state, (), (pid,), order)
        assert 'projection_workspace_version' not in root['source_status']
        # Saving must not mutate the caller's original status or its ORM JSON.
        assert state['source_status']['projection_workspace_version'] == row.version


def test_local_edits_without_a_version_bump_force_validation_and_survive(harness):
    h = harness
    sync(h)
    with h.sessions.begin() as db:
        row = db.get(h.W, h.wid)
        state = storage.load(db, h.B, row)
        project = state['projects'][0]
        task = project['nodes'][0]['tasks'][0]
        task['manual_updated'] = True
        task['comments'] = [{'id': 'local-comment', 'body': 'keep this note'}]
        project['comments'].append({'id': 'project-comment', 'body': 'keep project history'})
        state['approvals'].append({'id': 'local-approval', 'project_id': project['id'],
                                   'type': 'extension', 'status': 'draft', 'history': []})
        row.data = storage.save(db, h.B, h.wid, state)
    before, _ = h.read()
    h.clock[0] = '2026-09-27T10:01:00+08:00'
    sync(h)
    after, _ = h.read()
    assert after['projects'][0]['nodes'][0]['tasks'] == before['projects'][0]['nodes'][0]['tasks']
    assert after['projects'][0]['comments'] == before['projects'][0]['comments']
    assert after['approvals'] == before['approvals']
    assert after['source_status']['sync_revision'] == before['source_status']['sync_revision'] + 1


def test_cache_change_after_preparation_falls_back_to_complete_state(harness, monkeypatch):
    h = harness
    sync(h)
    before, _ = h.read()
    prepare = h.service._prepare

    def raced(*args, **kwargs):
        prepared = prepare(*args, **kwargs)
        assert '_partial' in prepared['state']
        with h.sessions.begin() as db:
            cache = db.get(h.C, h.wid)
            cache.data = dict(cache.data, status='error')
        return prepared

    monkeypatch.setattr(h.service, '_prepare', raced)
    h.clock[0] = '2026-09-27T10:01:00+08:00'
    sync(h)
    after, _ = h.read()
    assert after['projects'] == before['projects']
    assert after['source_status']['sync_revision'] == before['source_status']['sync_revision'] + 1


def test_new_root_policy_inputs_are_applied_even_when_source_content_is_equal(harness, monkeypatch):
    h = harness
    sync(h)
    before, _ = h.read()
    upgrade = source_sync.upgrade

    def upgraded(state):
        state = upgrade(state)
        state['settings']['new_source_input'] = 'new-default'
        return state

    monkeypatch.setattr(source_sync, 'upgrade', upgraded)
    h.clock[0] = '2026-09-27T10:01:00+08:00'
    sync(h)
    state, _ = h.read()
    assert state['settings']['new_source_input'] == 'new-default'
    assert state['source_status']['sync_revision'] == before['source_status']['sync_revision'] + 1


@pytest.mark.parametrize('bump_version', [False, True])
def test_local_write_after_preparation_invalidates_the_early_proof(harness, monkeypatch, bump_version):
    h = harness
    sync(h)
    prepare = h.service._prepare

    def raced(*args, **kwargs):
        prepared = prepare(*args, **kwargs)
        assert '_partial' in prepared['state']
        with h.sessions.begin() as db:
            row = db.get(h.W, h.wid)
            state = storage.load(db, h.B, row)
            state['projects'][0]['nodes'][0]['tasks'][0]['comments'].append(
                {'id': 'concurrent-note', 'body': 'retain this edit'})
            if bump_version:
                row.version += 1
                state['version'] = row.version
            row.data = storage.save(db, h.B, h.wid, state)
        return prepared

    monkeypatch.setattr(h.service, '_prepare', raced)
    h.clock[0] = '2026-09-27T10:01:00+08:00'
    sync(h)
    state, _ = h.read()
    assert state['projects'][0]['nodes'][0]['tasks'][0]['comments'] == [
        {'id': 'concurrent-note', 'body': 'retain this edit'}]


def test_normalized_case_caches_text_without_retaining_mutable_formula_values():
    formula = [{'text': '\u200b C115001-2 '}]
    assert normalized_case(formula) == 'C115001-2'
    formula[0]['text'] = '\u200b C115001-3 '
    assert normalized_case(formula) == 'C115001-3'
    assert normalized_case(None) == ''
    assert normalized_case({'name': ' C115001-3 '}) == 'C115001-3'
