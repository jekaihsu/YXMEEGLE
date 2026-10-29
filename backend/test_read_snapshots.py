from threading import Event

from .read_snapshots import ReadSnapshots
from .test_perf_budget import scaled_client
from .models import WorkspaceRow
from .test_shell import ON, switch
from sqlalchemy import select


def test_single_flight_stale_refresh_and_write_fence():
    clock = [0]
    cache = ReadSnapshots(clock=lambda: clock[0], fresh=1, stale=10)
    entered, release = Event(), Event()
    calls = []
    def build():
        calls.append(1)
        entered.set()
        assert release.wait(2)
        return b'new'
    try:
        assert cache.get('case', lambda: b'old') == (b'old', 'miss')
        clock[0] = 2
        assert cache.get('case', build) == (b'old', 'stale')
        assert entered.wait(2)
        assert cache.get('case', build) == (b'old', 'stale')
        cache.invalidate()
        release.set()
        # The invalidated background read cannot reinsert its pre-write data.
        assert cache.get('case', lambda: b'after-write') == (b'after-write', 'miss')
        assert cache.get('case', build) == (b'after-write', 'hit')
        assert len(calls) == 1
    finally:
        release.set()
        cache.close()


def test_failed_and_oversized_reads_do_not_poison_cache():
    cache = ReadSnapshots(max_bytes=3)
    try:
        import pytest
        with pytest.raises(ValueError):
            cache.get('a', lambda: (_ for _ in ()).throw(ValueError('failed')))
        assert cache.get('a', lambda: b'ok') == (b'ok', 'miss')
        assert cache.get('b', lambda: b'large') == (b'large', 'miss')
        assert cache.get('b', lambda: b'new') == (b'new', 'miss')
    finally:
        cache.close()


def test_first_screen_matches_individual_readers_and_invalidates(tmp_path):
    with scaled_client(tmp_path, 3, **ON) as (app, client):
        with app.state.sessions() as db:
            from . import storage
            from .models import BusinessRow
            root = db.scalars(select(WorkspaceRow)).first()
            pid = storage.load(db, BusinessRow, root)['projects'][0]['id']
        base = '/api/projects/' + pid
        first = client.get(base + '/first-screen')
        assert first.status_code == 200, first.text
        body = first.json()
        expected = client.get(base + '?overview=true').json()
        for value in (body['project'], expected):
            value.pop('task_capabilities_checked_at', None)
        assert body['project'] == expected
        for name, suffix in [('tasks', '/sop-tasks'), ('assignments', '/node-assignments'),
                             ('start', '/node-assignments/start-sop'), ('progress', '/progress')]:
            response = client.get(base + suffix)
            assert body[name]['status'] == response.status_code
            assert body[name]['body'] == response.json()
        assert client.get(base + '/first-screen').headers['x-read-snapshot'] == 'hit'
        switch(client, 'u-pm')
        assert client.get(base + '/first-screen').headers['x-read-snapshot'] == 'miss'
        switch(client, 'u-manager')
        assert client.get(base + '/first-screen').headers['x-read-snapshot'] == 'miss'
        assert client.get('/api/projects/absent/first-screen').status_code == 404
        assert client.get(base + '/first-screen?invalid=1').status_code == 422


def test_portfolio_cached_response_does_not_repeat_bulk_projection(tmp_path, monkeypatch):
    with scaled_client(tmp_path, 6, **ON) as (app, client):
        calls = []
        monkeypatch.setattr(app.state.home_panels, 'assignment_unavailable', lambda *_: False)
        monkeypatch.setattr(app.state.home_panels, 'portfolio_statuses', lambda *_: calls.append(1) or {})
        first = client.get('/api/projects?view=portfolio')
        assert first.status_code == 200
        assert first.json()['total'] == 6
        assert first.json()['basis'] == 'persisted_workspace'
        assert all(n['status_source'] == 'persisted' for p in first.json()['items'] for n in p['portfolio_nodes'])
        second = client.get('/api/projects?view=portfolio')
        assert second.json() == first.json()
        assert second.headers['x-read-snapshot'] == 'hit'
        assert calls == [1]


def test_background_revision_revalidates_last_good_without_blocking():
    cache = ReadSnapshots()
    entered, release = Event(), Event()
    try:
        assert cache.get('case', lambda: b'v1', revision=1) == (b'v1', 'miss')
        def next_revision():
            entered.set()
            assert release.wait(2)
            return b'v2'
        assert cache.get('case', next_revision, revision=2) == (b'v1', 'stale')
        assert entered.wait(2)
        assert cache.get('case', next_revision, revision=2) == (b'v1', 'stale')
        release.set()
        cache.close()
        assert cache.get('case', lambda: b'unexpected', revision=2) == (b'v2', 'hit')
    finally:
        release.set()
        cache.close()


def test_changed_authority_cannot_publish_under_previous_viewer_key(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from .models import BusinessRow
    from . import storage
    with scaled_client(tmp_path, 2, **ON) as (app, client):
        with app.state.sessions() as db:
            root = db.scalars(select(WorkspaceRow)).first()
            pid = storage.load(db, BusinessRow, root)['projects'][0]['id']
        blocker_started, release, lookup = Event(), Event(), Event()
        def block():
            blocker_started.set()
            assert release.wait(5)
        app.state.read_snapshots.executor.submit(block)
        assert blocker_started.wait(2)
        original = app.state.read_snapshots.get
        def get(*args, **kwargs):
            lookup.set()
            return original(*args, **kwargs)
        monkeypatch.setattr(app.state.read_snapshots, 'get', get)
        with ThreadPoolExecutor(max_workers=1) as requests:
            pending = requests.submit(client.get, '/api/projects/' + pid + '/first-screen')
            try:
                assert lookup.wait(2)
                with app.state.sessions.begin() as db:
                    person = db.scalars(select(BusinessRow).where(BusinessRow.kind == 'users', BusinessRow.entity_id == 'u-manager')).one()
                    person.data = dict(person.data, role='member')
            finally:
                release.set()
            assert pending.result(timeout=5).status_code == 409
        assert not app.state.read_snapshots.entries


def test_hidden_case_is_not_served_from_last_good_snapshot(tmp_path, monkeypatch):
    from . import storage, workspace_environment
    from .models import BusinessRow
    with scaled_client(tmp_path, 2, **ON) as (app, client):
        monkeypatch.setattr(workspace_environment, 'normalize_environment',
            lambda state, *_: state.update(environment='production') or state)
        with app.state.sessions() as db:
            root = db.scalars(select(WorkspaceRow)).first()
            pid = storage.load(db, BusinessRow, root)['projects'][0]['id']
        url = '/api/projects/' + pid + '/first-screen'
        assert client.get(url).status_code == 200
        assert client.get(url).headers['x-read-snapshot'] == 'hit'
        # Model a background source write, outside the HTTP invalidation middleware.
        with app.state.sessions.begin() as db:
            root = db.scalars(select(WorkspaceRow)).first()
            state = storage.load(db, BusinessRow, root)
            next(p for p in state['projects'] if p['id'] == pid)['case_visibility'] = 'excluded_history'
            root.version += 1
            state['version'] = root.version
            root.data = storage.save(db, BusinessRow, root.id, state)
        assert client.get(url).status_code == 404
