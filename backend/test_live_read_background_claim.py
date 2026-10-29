"""Lease contention stays behind the coordinator's bounded background lanes."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from .live_read.coordinator import RefreshCoordinator
from .models import CacheRow
from .test_live_read_coordinator import harness  # noqa: F401


def test_nonblocking_refresh_returns_while_lease_claim_is_blocked(harness, monkeypatch):
    h = harness
    coordinator = RefreshCoordinator(h.sessions, CacheRow, h.readers, h.cfg)
    entered, release = Event(), Event()
    claim = coordinator._claim

    def blocked(*args):
        entered.set()
        assert release.wait(5)
        return claim(*args)

    monkeypatch.setattr(coordinator, '_claim', blocked)
    try:
        with ThreadPoolExecutor(max_workers=1) as requests:
            response = requests.submit(coordinator.ensure, h.wid, 'sources')
            assert entered.wait(2)
            try:
                result = response.result(timeout=1)
                assert result['status'] == 'refreshing'
                assert result['as_of'] is None
                assert coordinator.queue_depth == 1
                for _ in range(10):
                    assert coordinator.ensure(h.wid, 'sources')['status'] == 'refreshing'
                assert h.calls == []
            finally:
                release.set()
        assert coordinator.ensure(h.wid, 'sources', wait=True)['status'] == 'fresh'
        assert h.calls == [h.wid]
    finally:
        release.set()
        coordinator.close()


def test_waiting_refresh_includes_lease_claim_in_timeout(harness, monkeypatch):
    h = harness
    coordinator = RefreshCoordinator(h.sessions, CacheRow, h.readers, h.cfg)
    entered, release = Event(), Event()
    claim = coordinator._claim

    def blocked(*args):
        entered.set()
        assert release.wait(5)
        return claim(*args)

    monkeypatch.setattr(coordinator, '_claim', blocked)
    try:
        with pytest.raises(TimeoutError, match='timed out'):
            coordinator.ensure(h.wid, 'sources', wait=True, timeout=.05)
        assert entered.is_set() and h.calls == []
        release.set()
        assert coordinator.ensure(h.wid, 'sources', wait=True)['status'] == 'fresh'
        assert h.calls == [h.wid]
    finally:
        release.set()
        coordinator.close()


def test_failed_background_claim_releases_capacity_and_can_retry(harness, monkeypatch):
    h = harness
    coordinator = RefreshCoordinator(h.sessions, CacheRow, h.readers, h.cfg)
    claim = coordinator._claim

    def failed(*args):
        raise OSError('database unavailable')

    monkeypatch.setattr(coordinator, '_claim', failed)
    try:
        with pytest.raises(OSError, match='database unavailable'):
            coordinator.ensure(h.wid, 'sources', wait=True)
        monkeypatch.setattr(coordinator, '_claim', claim)
        assert coordinator.ensure(h.wid, 'sources', wait=True)['status'] == 'fresh'
        assert h.calls == [h.wid]
    finally:
        coordinator.close()


def test_immediate_claim_failure_returns_an_error_to_nonblocking_caller(harness, monkeypatch):
    h = harness
    coordinator = h.make()

    def failed(*args):
        raise OSError('database unavailable')

    monkeypatch.setattr(coordinator, '_claim', failed)
    result = coordinator.ensure(h.wid, 'sources')
    assert result['status'] == 'error'
    assert result['last_error'] == 'Lark refresh failed'
    assert h.calls == []


def test_completed_failure_releases_refresh_working_set(harness):
    import gc
    import weakref
    h = harness
    observed = []
    class WorkingSet:
        pass
    def fail(wid):
        working = WorkingSet()
        observed.append(weakref.ref(working))
        raise RuntimeError('failed bulk read')
    coordinator = RefreshCoordinator(h.sessions, CacheRow, {'sources': fail}, h.cfg)
    try:
        with pytest.raises(RuntimeError):
            coordinator.ensure(h.wid, 'sources', wait=True)
        gc.collect()
        assert observed and observed[0]() is None
    finally:
        coordinator.close()
