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
