"""Cross-process snapshot truth; all writes use an isolated SQLite fixture."""
from sqlalchemy import select

from . import storage
from .app import create_app
from .models import BusinessRow, WorkspaceRow
from .test_perf_budget import scaled_client
from .test_shell import ON


def test_snapshot_explicit_reload_after_other_app_write(tmp_path):
    with scaled_client(tmp_path, 2, **ON) as (app_a, client):
        writer = create_app(dict(DATABASE_URL=f'sqlite:///{tmp_path}/perf.db',
            UPLOAD_DIR=str(tmp_path / 'writer-uploads'), SESSION_SECRET='writer-secret',
            APP_ENV='development', DEMO_MODE='true', LARK_LIVE_READ_ENABLED='false',
            LARK_APP_ID='', LARK_APP_SECRET='', INDEX_TABLES_ENABLED='true'))
        try:
            with app_a.state.sessions() as db:
                root = db.scalars(select(WorkspaceRow)).first()
                pid = storage.load(db, BusinessRow, root)['projects'][0]['id']
            url = f'/api/projects/{pid}/first-screen'
            first = client.get(url)
            assert first.status_code == 200
            with writer.state.sessions.begin() as db:
                root = db.scalars(select(WorkspaceRow)).first()
                state = storage.load(db, BusinessRow, root)
                next(p for p in state['projects'] if p['id'] == pid)['name'] = 'Worker B new name'
                root.version += 1
                state['version'] = root.version
                root.data = storage.save(db, BusinessRow, root.id, state)
            refreshed = client.get(url, headers={'Cache-Control': 'no-cache',
                                                 'If-None-Match': first.headers['etag']})
            assert refreshed.status_code == 200, '304 must not mask a changed generation'
            assert refreshed.json()['project']['project']['name'] == 'Worker B new name'
            assert refreshed.headers['x-read-snapshot'] != 'stale'
            metadata = refreshed.json()['snapshot']
            assert metadata['local_revision'] == state['version']
            assert metadata['verified_at'] and metadata['snapshot_id']
            assert metadata['completeness'] == 'partial'
            assert refreshed.json()['tasks']['snapshot']['local_revision'] == state['version']
        finally:
            writer.state.engine.dispose()


def test_snapshot_requested_revision_waits_and_force_joins_same_flight():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, Lock
    from .read_snapshots import ReadSnapshots
    cache = ReadSnapshots()
    started, release, second_waiting = Event(), Event(), Event()
    waiters, waiter_lock = [], Lock()
    calls = []
    try:
        cache.get('case', lambda: b'old', revision=1)
        def build():
            calls.append(1)
            started.set()
            assert release.wait(5)
            return b'new'
        original_submit = cache.executor.submit
        def observe_submit(*args, **kwargs):
            flight = original_submit(*args, **kwargs)
            original_result = flight.result
            def observe_wait(*args, **kwargs):
                with waiter_lock:
                    waiters.append(1)
                    if len(waiters) == 2:
                        second_waiting.set()
                return original_result(*args, **kwargs)
            flight.result = observe_wait
            return flight
        cache.executor.submit = observe_submit
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(cache.get, 'case', build, revision=2)
            assert started.wait(2)
            second = pool.submit(cache.get, 'case', build, revision=2, force=True)
            assert second_waiting.wait(2)
            assert not first.done()  # old data cannot terminate the authorized read
            release.set()
            assert first.result(5) == (b'new', 'miss')
            # The active force joins the requested generation.
            assert second.result(5)[0] == b'new'
        assert calls == [1]
        assert cache.get('case', lambda: b'wrong', revision=2)[0] == b'new'
    finally:
        release.set()
        cache.close()


def test_snapshot_delayed_old_revision_cannot_publish_or_return_as_current():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from fastapi import HTTPException
    import pytest
    from .read_snapshots import ReadSnapshots
    cache = ReadSnapshots()
    started, release, newer_requested = Event(), Event(), Event()
    try:
        def old():
            started.set()
            assert release.wait(5)
            return b'old'
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = pool.submit(cache.get, 'case', old, revision=1)
            assert started.wait(2)
            # Use submission of the newer builder as a deterministic synchronization point.
            submit = cache.executor.submit
            def observe(*args, **kwargs):
                future = submit(*args, **kwargs)
                newer_requested.set()
                return future
            cache.executor.submit = observe
            new = pool.submit(cache.get, 'case', lambda: b'new', revision=2)
            assert newer_requested.wait(2)
            release.set()
            value, status = pending.result(5)
            assert (value, status) in ((b'old', 'stale'), (b'new', 'hit'))
            assert new.result(5) == (b'new', 'miss')
        assert cache.get('case', lambda: b'wrong', revision=2) == (b'new', 'hit')
    finally:
        release.set()
        cache.close()


def test_snapshot_stale_paint_cannot_validate_old_etag():
    from starlette.requests import Request
    from .read_snapshots import EncodedSnapshot
    old = EncodedSnapshot.encode(b'{}', as_of='2020-01-01T00:00:00+08:00')
    request = Request({'type': 'http', 'headers': [(b'if-none-match', old.etag.encode())]})
    response = old.response(request, 'stale')
    assert response.status_code == 200
    assert response.headers['x-data-as-of'] == old.as_of
    assert response.headers['x-read-snapshot'] == 'stale'


def test_snapshot_source_age_and_partial_truth_are_preserved():
    from .snapshot_contract import attach_first_screen
    stamp = '2020-01-01T00:00:00+08:00'
    result = {'project': {}, 'tasks': {'status': 200, 'body': {'stale': True, 'fetched_at': stamp}},
              'assignments': {'status': 403, 'body': {}}, 'start': {'status': 503, 'body': {}},
              'progress': {'status': 202, 'body': None}}
    attach_first_screen(result, {'version': 5}, (5,),
                        {'enabled': True, 'datasets': {'sources': {'as_of': stamp, 'status': 'stale'}}})
    snapshot = result['snapshot']
    assert snapshot['as_of'] == stamp and snapshot['stale'] is True
    assert snapshot['verified_at'] != stamp  # verification of local revision is separate
    assert snapshot['completeness'] == 'partial'
    assert snapshot['resources']['project']['as_of'] == stamp
    assert result['tasks']['snapshot']['as_of'] == stamp
    assert result['tasks']['snapshot']['stale'] is True
    assert result['assignments']['snapshot']['completeness'] == 'partial'
    assert result['assignments']['snapshot']['as_of'] is None
    assert all(meta['snapshot_id'] == snapshot['snapshot_id'] for meta in snapshot['resources'].values())


def test_snapshot_force_still_checks_auth_and_redaction(tmp_path):
    def private(state):
        state['delegations'] = [dict(id='private-delegation-marker', principal_id='ou_020', delegate_id='ou_030')]
    with scaled_client(tmp_path, 2, mutate=private, **ON) as (app, client):
        with app.state.sessions() as db:
            root = db.scalars(select(WorkspaceRow)).first()
            pid = storage.load(db, BusinessRow, root)['projects'][0]['id']
        url = f'/api/projects/{pid}/first-screen'
        manager = client.get(url)
        assert manager.status_code == 200
        assert 'private-delegation-marker' in manager.text
        from .test_shell import switch
        switch(client, 'u-pm')
        forced = client.get(url, headers={'Cache-Control': 'no-cache'})
        assert forced.status_code == 200
        assert 'private-delegation-marker' not in forced.text
        ordinary = client.get(f'/api/projects/{pid}?overview=true')
        assert 'private-delegation-marker' not in ordinary.text
        assert forced.headers['etag'] != manager.headers['etag']
        client.cookies.clear()
        assert client.get(url, headers={'Cache-Control': 'no-cache',
            'If-None-Match': forced.headers['etag']}).status_code == 401


def test_snapshot_other_app_write_while_builder_queued_rebuilds_once(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    with scaled_client(tmp_path, 2, **ON) as (app, client):
        with app.state.sessions() as db:
            root = db.scalars(select(WorkspaceRow)).first()
            pid = storage.load(db, BusinessRow, root)['projects'][0]['id']
        entered, release, requested = Event(), Event(), Event()
        def block():
            entered.set()
            assert release.wait(5)
        app.state.read_snapshots.executor.submit(block)
        assert entered.wait(2)
        original = app.state.read_snapshots.get
        def observe(*args, **kwargs):
            requested.set()
            return original(*args, **kwargs)
        monkeypatch.setattr(app.state.read_snapshots, 'get', observe)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(client.get, f'/api/projects/{pid}/first-screen')
            try:
                assert requested.wait(2)
                # A separate worker session commits without HTTP invalidation.
                with app.state.sessions.begin() as db:
                    root = db.scalars(select(WorkspaceRow)).first()
                    state = storage.load(db, BusinessRow, root)
                    state['projects'][0]['name'] = 'New worker generation'
                    root.version += 1
                    state['version'] = root.version
                    root.data = storage.save(db, BusinessRow, root.id, state)
            finally:
                release.set()
            rebuilt = pending.result(5)
            assert rebuilt.status_code == 200
            assert rebuilt.json()['project']['project']['name'] == 'New worker generation'
        fresh = client.get(f'/api/projects/{pid}/first-screen')
        assert fresh.json()['project']['project']['name'] == 'New worker generation'
