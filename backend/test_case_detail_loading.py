"""Case endpoints serve stored data while all external refreshers are stalled."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from .app import CacheRow
from .live_read.coordinator import RefreshCoordinator
from .reports.snapshot import SnapshotStore
from .test_p2_int_routes import http, build_state, WID


@pytest.mark.parametrize('endpoint', ['projects/{pid}', 'projects/{pid}/navigation',
                                     'projects/{pid}/progress', 'case-detail/{pid}'])
def test_case_reads_finish_before_slow_external_refresh(tmp_path, monkeypatch, endpoint):
    monkeypatch.setenv('WORKSPACE_SHELL_ENABLED', 'true')
    app, client, seat, signin = http.__wrapped__(tmp_path, monkeypatch)
    state, pid, _ = build_state()
    seat(state)
    signin()
    release, source_started, roster_started, reports_started = Event(), Event(), Event(), Event()

    def slow(started):
        def refresh(wid):
            started.set()
            assert release.wait(10)
            return {'fingerprint': 'fictional'}
        return refresh

    class SlowReports:
        def read(self):
            reports_started.set()
            assert release.wait(10)
            return {}

    coordinator = RefreshCoordinator(app.state.sessions, CacheRow,
        {'sources': slow(source_started), 'roster': slow(roster_started)},
        {'LARK_LIVE_READ_ENABLED': 'true', 'LARK_WORKER_IDENTITY': 'application'})
    reports = SnapshotStore(SlowReports())
    monkeypatch.setattr(app.state, 'live_read', coordinator)
    monkeypatch.setattr(app.state, 'reports', reports)
    try:
        coordinator.ensure(WID, 'sources', wait=False)
        assert source_started.wait(2)
        with ThreadPoolExecutor(max_workers=1) as executor:
            request = executor.submit(client.get, '/api/' + endpoint.format(pid=pid))
            try:
                response = request.result(timeout=2)
                assert response.status_code == 200
                assert roster_started.wait(2)
                if endpoint.endswith('/progress'): assert reports_started.wait(2)
                assert not release.is_set(), 'the response precedes every external result'
            finally:
                release.set()
    finally:
        release.set()
        reports.close()
        coordinator.close()
        app.state.engine.dispose()


@pytest.mark.parametrize('status', ['ready', 'partial', 'error', 'forbidden', 'loading'])
def test_scoped_health_matches_full_source_health_without_copying_record_values(http, monkeypatch, status):
    from copy import deepcopy
    from . import source_health
    app, client, seat, signin = http
    state, pid, _ = build_state()
    seat(state)
    signin()
    with app.state.sessions.begin() as db:
        row = db.get(CacheRow, WID)
        cache = deepcopy(row.data)
        cache['status'] = status
        for record in cache['records']:
            record['fields'] = {'large_private_payload': ['fictional'] * 1000}
        row.data = cache

    real = source_health.build_source_health
    captures = []
    def capture(snapshot, *args, **kwargs):
        result = real(snapshot, *args, **kwargs)
        captures.append((deepcopy(snapshot), result))
        return result
    monkeypatch.setattr(source_health, 'build_source_health', capture)
    reference = client.get('/api/source-health')
    assert reference.status_code == 200
    assert client.get(f'/api/case-detail/{pid}').status_code == 200
    assert len(captures) == 2
    assert captures[0][1]['page_state'] == captures[1][1]['page_state']
    assert captures[1][1]['sources'] == []
    assert reference.json()['sources'] == captures[0][1]['sources']
    assert captures[0][0]['tables'] == captures[1][0]['tables']
    assert captures[0][0]['records'] and 'records' not in captures[1][0]
    with app.state.sessions() as db:
        assert db.get(CacheRow, WID).data == cache
