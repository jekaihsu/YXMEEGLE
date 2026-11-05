"""Concurrent case-scoped reads share one fetch of the global collections, never across workspaces, writes or versions."""
import threading
from copy import deepcopy

import pytest
from sqlalchemy import event, select, update

from . import storage
from .app import BusinessRow, WorkspaceRow
from .test_sop_quotes import WID, harness

TOP = ('source_quotes',)


@pytest.fixture
def world(tmp_path):
    app, client, signin, ids = harness(tmp_path, {'u-manager': ['sop_task_read']})
    storage.invalidate_shared_reads(None)
    yield app, client, signin, ids
    storage.invalidate_shared_reads(None)
    app.state.engine.dispose()


def counted(app):
    seen = []

    @event.listens_for(app.state.engine, 'before_cursor_execute')
    def record(conn, cursor, statement, params, context, many):
        if 'business_records' in statement and 'source_quotes' in repr(params):
            seen.append(statement)
    return seen


def read(app, wid=WID, project=None):
    with app.state.sessions() as db:
        row = db.get(WorkspaceRow, wid)
        return storage.load_partial(db, BusinessRow, row, collections=storage.CASE_COLLECTIONS,
                                    project_ids=[project] if project else None, filter_project_rows=bool(project))


def test_concurrent_case_reads_fetch_the_global_collections_once(world):
    app, client, signin, ids = world
    seen = counted(app)
    barrier = threading.Barrier(6)
    results = []

    def go():
        barrier.wait()
        results.append(read(app, project=ids['intake']))
    threads = [threading.Thread(target=go) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(results) == 6 and all(r['source_quotes'] == results[0]['source_quotes'] for r in results)
    assert len(seen) == 1


def test_each_read_gets_its_own_copy(world):
    app, client, signin, ids = world
    first = read(app, project=ids['intake'])
    first['source_quotes'][0]['tampered'] = True
    first['source_quotes'].pop()
    second = read(app, project=ids['intake'])
    assert 'tampered' not in second['source_quotes'][0]
    assert len(second['source_quotes']) == len(first['source_quotes']) + 1


def test_a_version_bumped_write_is_visible_to_the_next_read(world):
    app, client, signin, ids = world
    before = read(app, project=ids['intake'])
    with app.state.sessions.begin() as db:
        quote = db.scalars(select(BusinessRow).where(BusinessRow.workspace_id == WID, BusinessRow.kind == 'source_quotes')).first()
        data = deepcopy(quote.data)
        data['marker'] = 'after-write'
        quote.data = data
        db.execute(update(WorkspaceRow).where(WorkspaceRow.id == WID).values(version=WorkspaceRow.version + 1))
    after = read(app, project=ids['intake'])
    assert not any('marker' in q for q in before['source_quotes'])
    assert any(q.get('marker') == 'after-write' for q in after['source_quotes'])


def test_a_storage_save_invalidates_even_without_a_version_change(world):
    app, client, signin, ids = world
    read(app, project=ids['intake'])
    with app.state.sessions.begin() as db:
        row = db.get(WorkspaceRow, WID)
        state = storage.load(db, BusinessRow, row)
        state['source_quotes'][0]['marker'] = 'saved'
        storage.save(db, BusinessRow, WID, state)
    assert any(q.get('marker') == 'saved' for q in read(app, project=ids['intake'])['source_quotes'])


def test_workspaces_never_share_cached_rows(world):
    app, client, signin, ids = world
    mine = read(app, project=ids['intake'])
    other = 'lark-other'
    with app.state.sessions.begin() as db:
        db.add(WorkspaceRow(id=other, version=1, data={'storage_schema': 2}))
        db.flush()
        db.add(BusinessRow(workspace_id=other, kind='source_quotes', entity_id='only-other', parent_id='', ordinal=0, data={'id': 'only-other'}))
    theirs = read(app, wid=other)
    again = read(app, project=ids['intake'])
    assert [q['id'] for q in theirs['source_quotes']] == ['only-other']
    assert 'only-other' not in repr(again['source_quotes']) and again['source_quotes'] == mine['source_quotes']


def test_a_warm_cache_does_not_widen_what_another_user_may_see(world):
    app, client, signin, ids = world
    signin('u-manager')
    assert client.get(f"/api/projects/{ids['intake']}/sop-tasks").status_code == 200
    signin('u-agent')
    assert client.get(f"/api/projects/{ids['intake']}/sop-tasks").status_code in (403, 404)
    signin('u-manager')
    assert client.get(f"/api/projects/{ids['intake']}/sop-tasks").status_code == 200


def test_authority_bearing_rows_are_never_served_from_the_shared_read(world):
    app, client, signin, ids = world
    read(app, project=ids['intake'])
    with app.state.sessions.begin() as db:
        user = db.scalars(select(BusinessRow).where(BusinessRow.workspace_id == WID, BusinessRow.kind == 'users')).first()
        data = deepcopy(user.data)
        data['capabilities'] = ['edited-without-a-version-bump']
        user.data = data
        edited = user.entity_id
    users = {u['id']: u for u in read(app, project=ids['intake'])['users']}
    assert users[edited]['capabilities'] == ['edited-without-a-version-bump']


def test_a_reader_refill_inside_a_writers_open_transaction_never_survives_the_commit(world):
    app, client, signin, ids = world
    read(app, project=ids['intake'])
    saved, commit = threading.Event(), threading.Event()
    failure = []

    def writer():
        try:
            with app.state.sessions.begin() as db:
                state = storage.load(db, BusinessRow, db.get(WorkspaceRow, WID))
                state['source_quotes'][0]['marker'] = 'committed'
                storage.save(db, BusinessRow, WID, state)
                saved.set()
                assert commit.wait(10)
        except BaseException as error:
            failure.append(error)
            saved.set()
    thread = threading.Thread(target=writer)
    thread.start()
    assert saved.wait(10)
    during = read(app, project=ids['intake'])
    assert not any('marker' in q for q in during['source_quotes']), 'an open transaction is not visible to readers'
    commit.set()
    thread.join(10)
    assert not failure, failure
    assert any(q.get('marker') == 'committed' for q in read(app, project=ids['intake'])['source_quotes'])


def test_a_fetch_that_straddles_an_invalidation_is_not_stored():
    from . import shared_reads
    shared_reads.invalidate(None)
    key = ('w', 1, ('k',), None)
    started, release = threading.Event(), threading.Event()

    def slow():
        started.set()
        release.wait(10)
        return [('k', '"old"')]
    thread = threading.Thread(target=lambda: shared_reads.rows(key, slow))
    thread.start()
    assert started.wait(10)
    shared_reads.invalidate('w')
    release.set()
    thread.join(10)
    fetched = []
    assert shared_reads.rows(key, lambda: fetched.append(1) or [('k', '"new"')]) == [('k', '"new"')]
    assert fetched == [1]
    shared_reads.invalidate(None)


def test_a_writer_reading_back_inside_its_own_transaction_sees_its_write_not_the_cache(world):
    app, client, signin, ids = world
    read(app, project=ids['intake'])
    with app.state.sessions.begin() as db:
        row = db.get(WorkspaceRow, WID)
        state = storage.load(db, BusinessRow, row)
        state['source_quotes'][0]['marker'] = 'mine'
        storage.save(db, BusinessRow, WID, state)
        inside = storage.load_partial(db, BusinessRow, row, collections=storage.CASE_COLLECTIONS,
                                      project_ids=[ids['intake']], filter_project_rows=True)
        assert any(q.get('marker') == 'mine' for q in inside['source_quotes'])


def test_shared_cache_counts_utf8_bytes_and_rejects_oversized_entries(monkeypatch):
    from . import shared_reads
    monkeypatch.setattr(shared_reads, 'MAX_BYTES', 5)
    shared_reads.invalidate(None)
    assert shared_reads.rows(('w', 1), lambda: [('k', '中文')]) == [('k', '中文')]
    assert not shared_reads._entries
    assert not shared_reads._flights


def test_shared_cache_bounds_small_entries_and_cleans_failed_flights(monkeypatch):
    from . import shared_reads
    monkeypatch.setattr(shared_reads, 'MAX_ENTRIES', 2)
    shared_reads.invalidate(None)
    for version in range(4):
        shared_reads.rows(('w', version), lambda: [('k', 'x')])
    assert len(shared_reads._entries) == 2
    def fail():
        raise RuntimeError('upstream unavailable')
    with pytest.raises(RuntimeError):
        shared_reads.rows(('w', 5), fail)
    assert not shared_reads._flights
    shared_reads.invalidate(None)


def test_case_projection_fetch_is_shared_across_projects_and_sop_read_shapes(world):
    app, _, _, ids = world
    seen = counted(app)
    def compact(pid, mode):
        with app.state.sessions() as db:
            return storage.load_partial(db, BusinessRow, db.get(WorkspaceRow, WID),
                collections=storage.CASE_COLLECTIONS, project_ids=[pid],
                filter_project_rows=True, case_sources=mode)
    first = compact(ids['intake'], True)
    tasks = compact(ids['intake'], 'sop')
    other = compact('another-project', True)
    assert len(seen) == 1
    assert first['source_quotes'] and tasks['source_quotes']
    assert not other['projects']
    assert all('history' not in quote for state in (first, tasks, other) for quote in state['source_quotes'])
    # A response copy cannot poison the version-wide cached projection.
    tasks['source_quotes'][0]['fields']['poison'] = True
    assert all('poison' not in quote['fields'] for quote in compact(ids['intake'], 'sop')['source_quotes'])
