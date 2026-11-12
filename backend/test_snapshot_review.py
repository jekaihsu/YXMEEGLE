from concurrent.futures import ThreadPoolExecutor
from threading import Event
from copy import deepcopy
import pytest
from sqlalchemy import event, select
from .read_snapshots import ReadSnapshots
from .snapshot_contract import attach_first_screen, source_metadata
from .test_perf_budget import scaled_client
from .test_shell import ON
from .models import WorkspaceRow, BusinessRow
from . import storage


def test_invalidation_does_not_fail_inflight_reader():
    cache = ReadSnapshots()
    def build():
        cache.invalidate()
        return b'consistent'
    try:
        assert cache.get('case', build) == (b'consistent', 'stale')
        assert cache.peek('case') is None
    finally:
        cache.close()


def test_late_older_revision_joins_newer_build():
    cache = ReadSnapshots()
    entered, release, joined = Event(), Event(), Event()
    def build():
        entered.set()
        assert release.wait(5)
        return b'v2'
    try:
        with ThreadPoolExecutor(2) as pool:
            newer = pool.submit(cache.get, 'case', build, revision=2)
            assert entered.wait(2)
            # Observe the waiter without relying on sleeps.
            with cache.lock:
                flight = next(iter(cache.flights.values()))
            result = flight.result
            def wait(*a, **kw):
                joined.set()
                return result(*a, **kw)
            flight.result = wait
            older = pool.submit(cache.get, 'case', lambda: b'v1', revision=1)
            try:
                assert joined.wait(2)
            finally:
                release.set()
            assert newer.result(5)[0] == b'v2'
            assert older.result(5)[0] == b'v2'
        assert cache.entries['case'][2] == 2
    finally:
        release.set()
        cache.close()


def test_continuous_supersession_returns_bounded_stale():
    cache = ReadSnapshots()
    def build():
        # Model a new version arriving on every capture, with no quiet period.
        with cache.lock:
            cache.requested['case'] = (2, cache.sequence + 1)
        return b'consistent'
    try:
        assert cache.get('case', build, revision=1) == (b'consistent', 'stale')
    finally:
        cache.close()


@pytest.mark.parametrize('status', ['error', 'refreshing', 'blocked', 'needs-permission', 'never', 'disabled', 'ready'])
def test_age_not_status_controls_stale(status):
    meta = source_metadata(dict(status=status, as_of='2020-01-01T00:00:00+00:00', ttl_seconds=60), revision=1)
    assert meta['stale'] is True
    assert meta['status'] == status


def result():
    return dict(project={}, **{n: dict(status=200, body={}) for n in ('tasks', 'assignments', 'start', 'progress')})


def test_disabled_source_age_has_no_assumed_live_read_cadence():
    body = attach_first_screen(result(), dict(version=1, source_status=dict(last_sync='2020-01-01T00:00:00+00:00')),
                               (1,), dict(enabled=False, datasets=dict(sources=dict(ttl_seconds=300))))
    assert body['snapshot']['stale'] is None
    project = body['snapshot']['resources']['project']
    assert project['age_seconds'] > 300
    assert project['ttl_seconds'] is None


def test_identity_excludes_verification_clock():
    a = attach_first_screen(result(), dict(version=1), (1,), dict(enabled=False))
    b = attach_first_screen(result(), dict(version=1), (1,), dict(enabled=False))
    assert a['snapshot']['snapshot_id'] == b['snapshot']['snapshot_id']


def test_same_revision_age_stale_is_default_but_changed_revision_blocks():
    now = [0]
    cache = ReadSnapshots(clock=lambda: now[0], fresh=1)
    entered, release = Event(), Event()
    def build():
        entered.set()
        assert release.wait(5)
        return b'new'
    try:
        cache.get('case', lambda: b'old', revision=1)
        now[0] = 2
        # Release on timeout so the original blocking implementation fails promptly.
        from threading import Timer
        timer = Timer(.2, release.set)
        timer.start()
        assert cache.get('case', build, revision=1) == (b'old', 'stale')
        release.set()
        cache.close()
    finally:
        release.set()
        cache.close()


def test_first_screen_scans_project_index_once(tmp_path):
    with scaled_client(tmp_path, 2, **ON) as (app, client):
        with app.state.sessions() as db:
            root = db.scalars(select(WorkspaceRow)).first()
            pid = storage.load(db, BusinessRow, root)['projects'][0]['id']
        statements = []
        def record(conn, cursor, sql, *args):
            if 'project_index.project_id, project_index.case_visibility' in sql:
                statements.append(sql)
        event.listen(app.state.engine, 'before_cursor_execute', record)
        try:
            assert client.get(f'/api/projects/{pid}/first-screen').status_code == 200
        finally:
            event.remove(app.state.engine, 'before_cursor_execute', record)
        assert len(statements) == 1


def test_force_rebuilds_fresh_same_revision_and_keeps_etag(tmp_path, monkeypatch):
    with scaled_client(tmp_path, 2, **ON) as (app, client):
        pid = client.get('/api/workspace').json()['projects'][0]['id']
        url = f'/api/projects/{pid}/first-screen'
        calls = []
        from . import snapshot_contract
        original = snapshot_contract.attach_first_screen
        def attach(*args, **kwargs):
            calls.append(1)
            return original(*args, **kwargs)
        monkeypatch.setattr(snapshot_contract, 'attach_first_screen', attach)
        first = client.get(url)
        assert client.get(url).headers['x-read-snapshot'] == 'hit'
        forced = client.get(url, headers={'Cache-Control': 'no-cache'})
        assert forced.headers['x-read-snapshot'] == 'miss'
        assert calls == [1, 1]
        assert first.json()['snapshot']['snapshot_id'] == forced.json()['snapshot']['snapshot_id']
        assert first.headers['etag'] == forced.headers['etag']


@pytest.mark.parametrize('route', ['case', 'shell', 'portfolio'])
def test_other_workspace_post_does_not_interrupt_read(tmp_path, monkeypatch, route):
    from starlette.testclient import TestClient
    from .models import WorkspaceRow
    with scaled_client(tmp_path, 40, **ON) as (app, client):
        pid = client.get('/api/workspace').json()['projects'][0]['id']
        cookie = app.state.signer.loads(client.cookies.get('meegle_session'))
        with app.state.sessions.begin() as db:
            root = db.get(WorkspaceRow, cookie['wid'])
            state = storage.load(db, BusinessRow, root)
            other = WorkspaceRow(id='demo-other', version=root.version, data={})
            db.add(other)
            other.data = storage.save(db, BusinessRow, other.id, state)
        entered, release, requested = Event(), Event(), Event()
        def block():
            entered.set()
            assert release.wait(5)
        app.state.read_snapshots.executor.submit(block)
        assert entered.wait(2)
        original = app.state.read_snapshots.get
        def get(*args, **kwargs):
            requested.set()
            return original(*args, **kwargs)
        monkeypatch.setattr(app.state.read_snapshots, 'get', get)
        url = dict(case=f'/api/projects/{pid}/first-screen', shell='/api/workspace?scope=shell', portfolio='/api/projects?view=portfolio&page=1')[route]
        with ThreadPoolExecutor(1) as pool, TestClient(app) as writer:
            writer.cookies.set('meegle_session', app.state.signer.dumps(dict(cookie, wid='demo-other')))
            pending = pool.submit(client.get, url)
            try:
                assert requested.wait(2)
                # Authenticated POST in Y; no company or external write.
                assert writer.post('/api/demo/session', json={'user_id': 'u-pm'}).status_code == 200
            finally:
                release.set()
            response = pending.result(10)
            assert response.status_code == 200
            assert response.headers['x-read-snapshot'] == 'miss'
            if route == 'case':
                assert response.json()['snapshot']['stale'] is not True
            if route == 'portfolio':
                page2 = client.get('/api/projects', params={'view': 'portfolio', 'page': 2, 'snapshot': response.json()['snapshot']})
                assert page2.status_code == 200
                assert page2.json()['page'] == 2
                assert len(page2.json()['items']) > 0


@pytest.mark.parametrize('authority_change', [False, True])
def test_first_screen_continuous_writes_retry_once_then_stale(tmp_path, monkeypatch, authority_change):
    from . import snapshot_contract
    with scaled_client(tmp_path, 2, **ON) as (app, client):
        pid = client.get('/api/workspace').json()['projects'][0]['id']
        calls = []
        attach = snapshot_contract.attach_first_screen
        def ongoing(*args, **kwargs):
            calls.append(1)
            body = attach(*args, **kwargs)
            with app.state.sessions.begin() as db:
                root = db.scalars(select(WorkspaceRow)).first()
                state = storage.load(db, BusinessRow, root)
                root.version += 1
                state['version'] = root.version
                if authority_change and len(calls) == 2:
                    next(u for u in state['users'] if u['id'] == 'u-manager')['role'] = 'member'
                root.data = storage.save(db, BusinessRow, root.id, state)
            return body
        monkeypatch.setattr(snapshot_contract, 'attach_first_screen', ongoing)
        response = client.get(f'/api/projects/{pid}/first-screen')
        if authority_change:
            assert response.status_code == 409
            assert calls == [1, 1]
            return
        assert response.status_code == 200
        assert calls == [1, 1]
        assert response.headers['x-read-snapshot'] == 'stale'
        assert response.json()['snapshot']['stale'] is True
        assert not app.state.read_snapshots.entries


def test_changed_revision_never_serves_stale_while_rebuilding():
    cache = ReadSnapshots()
    entered, release = Event(), Event()
    def build():
        entered.set()
        assert release.wait(5)
        return b'v2'
    try:
        cache.get('case', lambda: b'v1', revision=1)
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(cache.get, 'case', build, revision=2)
            try:
                assert entered.wait(2)
                assert not future.done()
            finally:
                release.set()
            assert future.result(5) == (b'v2', 'miss')
    finally:
        release.set()
        cache.close()


def test_newer_cached_revision_keeps_its_age_when_an_older_reader_arrives():
    now = [0]
    cache = ReadSnapshots(clock=lambda: now[0], fresh=1)
    try:
        cache.get('case', lambda: b'v2', revision=2)
        now[0] = 2
        assert cache.get('case', lambda: b'v1', revision=1) == (b'v2', 'stale')
    finally:
        cache.close()


def test_other_workspace_write_keeps_two_readers_on_one_flight():
    cache = ReadSnapshots()
    entered, release, joined = Event(), Event(), Event()
    calls = []
    key = ('case', 'X', 'same-session')
    def build():
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return b'current-X'
    try:
        with ThreadPoolExecutor(2) as pool:
            first = pool.submit(cache.get, key, build, revision=1)
            assert entered.wait(2)
            with cache.lock:
                flight = next(iter(cache.flights.values()))
            original = flight.result
            def wait(*a, **kw):
                joined.set()
                return original(*a, **kw)
            flight.result = wait
            cache.invalidate('Y')
            second = pool.submit(cache.get, key, build, revision=1)
            try:
                assert joined.wait(2), 'second tab must join the original X flight'
            finally:
                release.set()
            assert first.result(5) == (b'current-X', 'miss')
            assert second.result(5) == (b'current-X', 'miss')
        assert calls == [1]
    finally:
        release.set()
        cache.close()


def test_retry_joining_strict_flight_twice_has_bounded_fallback(tmp_path, monkeypatch):
    from .snapshot_contract import SnapshotRevisionChanged
    with scaled_client(tmp_path, 2, **ON) as (app, client):
        pid = client.get('/api/workspace').json()['projects'][0]['id']
        calls = []
        def strict_flight(*a, **kw):
            calls.append(1)
            # Both attempts can inherit the same strict creator's exception.
            raise SnapshotRevisionChanged()
        monkeypatch.setattr(app.state.read_snapshots, 'get', strict_flight)
        response = client.get(f'/api/projects/{pid}/first-screen')
        assert response.status_code == 200
        assert response.headers['x-read-snapshot'] == 'stale'
        assert response.json()['snapshot']['stale'] is True
        assert calls == [1, 1]
        assert not app.state.read_snapshots.entries


def test_own_workspace_post_clears_own_cache(tmp_path):
    with scaled_client(tmp_path, 2, **ON) as (app, client):
        pid = client.get('/api/workspace').json()['projects'][0]['id']
        url = f'/api/projects/{pid}/first-screen'
        assert client.get(url).headers['x-read-snapshot'] == 'miss'
        assert client.get(url).headers['x-read-snapshot'] == 'hit'
        assert client.post('/api/demo/session', json={'user_id': 'u-manager'}).status_code == 200
        assert not app.state.read_snapshots.entries
        assert client.get(url).headers['x-read-snapshot'] == 'miss'


def test_two_tabs_retry_can_join_another_tabs_strict_build(tmp_path, monkeypatch):
    """Real shared Future propagates a strict creator's revision exception twice."""
    from inspect import getclosurevars
    from starlette.testclient import TestClient
    from . import snapshot_contract
    with scaled_client(tmp_path, 2, **ON) as (app, client):
        pid = client.get('/api/workspace').json()['projects'][0]['id']
        retry_ready, strict_entered, joined = Event(), Event(), Event()
        captures, retries = [], []
        attach = snapshot_contract.attach_first_screen
        original_get = app.state.read_snapshots.get
        def advance():
            with app.state.sessions.begin() as db:
                root = db.scalars(select(WorkspaceRow)).first()
                state = storage.load(db, BusinessRow, root)
                root.version += 1
                state['version'] = root.version
                root.data = storage.save(db, BusinessRow, root.id, state)
        def ongoing(*a, **kw):
            body = attach(*a, **kw)
            captures.append(1)
            if len(captures) == 2:
                strict_entered.set()
                assert joined.wait(5)
            if len(captures) <= 2:
                advance()
            return body
        def get(key, build, **kw):
            if getclosurevars(build).nonlocals['accept_stale'] and not retries:
                retries.append(1)
                retry_ready.set()
                assert strict_entered.wait(5)
                with app.state.read_snapshots.lock:
                    flight = next(iter(app.state.read_snapshots.flights.values()))
                original_result = flight.result
                def wait(*a, **kw):
                    joined.set()
                    return original_result(*a, **kw)
                flight.result = wait
            return original_get(key, build, **kw)
        monkeypatch.setattr(snapshot_contract, 'attach_first_screen', ongoing)
        monkeypatch.setattr(app.state.read_snapshots, 'get', get)
        with ThreadPoolExecutor(2) as pool, TestClient(app) as tab2:
            tab2.cookies.update(client.cookies)
            first = pool.submit(client.get, f'/api/projects/{pid}/first-screen')
            assert retry_ready.wait(5)
            second = pool.submit(tab2.get, f'/api/projects/{pid}/first-screen')
            a, b = first.result(15), second.result(15)
        assert a.status_code == 200
        assert b.status_code == 200
        assert a.headers['x-read-snapshot'] == 'stale'
        assert a.json()['snapshot']['stale'] is True
        assert joined.is_set()


def test_two_http_tabs_join_one_case_build_across_other_workspace_post(tmp_path, monkeypatch):
    from starlette.testclient import TestClient
    with scaled_client(tmp_path, 2, **ON) as (app, client):
        pid = client.get('/api/workspace').json()['projects'][0]['id']
        cookie = app.state.signer.loads(client.cookies.get('meegle_session'))
        with app.state.sessions.begin() as db:
            root = db.get(WorkspaceRow, cookie['wid'])
            state = storage.load(db, BusinessRow, root)
            other = WorkspaceRow(id='demo-other', version=root.version, data={})
            db.add(other)
            other.data = storage.save(db, BusinessRow, other.id, state)
        entered, release, waiting, joined = Event(), Event(), Event(), Event()
        calls, waiters = [], []
        submit = app.state.read_snapshots.executor.submit
        def observe(*a, **kw):
            calls.append(1)
            flight = submit(*a, **kw)
            result = flight.result
            def wait(*a, **kw):
                waiters.append(1)
                waiting.set()
                if len(waiters) == 2:
                    joined.set()
                return result(*a, **kw)
            flight.result = wait
            return flight
        from . import snapshot_contract
        attach = snapshot_contract.attach_first_screen
        def blocked(*a, **kw):
            entered.set()
            assert release.wait(5)
            return attach(*a, **kw)
        monkeypatch.setattr(app.state.read_snapshots.executor, 'submit', observe)
        monkeypatch.setattr(snapshot_contract, 'attach_first_screen', blocked)
        with TestClient(app) as writer, TestClient(app) as tab2, ThreadPoolExecutor(2) as pool:
            writer.cookies.set('meegle_session', app.state.signer.dumps(dict(cookie, wid='demo-other')))
            tab2.cookies.update(client.cookies)
            first = pool.submit(client.get, f'/api/projects/{pid}/first-screen')
            assert entered.wait(2) and waiting.wait(2)
            assert writer.post('/api/demo/session', json={'user_id': 'u-pm'}).status_code == 200
            second = pool.submit(tab2.get, f'/api/projects/{pid}/first-screen')
            try:
                assert joined.wait(2)
            finally:
                release.set()
            for response in (first.result(10), second.result(10)):
                assert response.status_code == 200
                assert response.headers['x-read-snapshot'] == 'miss'
                assert response.json()['snapshot']['stale'] is not True
        assert calls == [1]
