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


def test_portfolio_first_screen_uses_persisted_cards_not_bulk_projection(tmp_path, monkeypatch):
    with scaled_client(tmp_path, 6, **ON) as (app, client):
        def unexpected(*args, **kwargs):
            raise AssertionError('portfolio first screen must not construct Lark assignment chains')
        monkeypatch.setattr(app.state.home_panels, 'portfolio_statuses', unexpected)
        first = client.get('/api/projects?view=portfolio')
        assert first.status_code == 200
        assert first.json()['total'] == 6
        assert first.json()['basis'] == 'persisted_workspace'
        assert all(n['status_source'] == 'persisted' for p in first.json()['items'] for n in p['portfolio_nodes'])
        second = client.get('/api/projects?view=portfolio')
        assert second.json() == first.json()
        assert second.headers['x-read-snapshot'] == 'hit'
