"""Refresh coordination against real SQLite leases and fake dataset readers."""
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier, Event, Lock
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .live_read.coordinator import RefreshCoordinator
from .models import Base, CacheRow, WorkspaceRow


class SynchronousExecutor:
    def submit(self, fn, *args):
        future = Future()
        try:
            future.set_result(fn(*args))
        except Exception as exc:
            future.set_exception(exc)
        return future


@pytest.fixture
def harness(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path / "leases.db"}',
                           connect_args={'check_same_thread': False, 'timeout': 10})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    clock = [datetime.fromisoformat('2026-10-07T10:00:00+08:00')]
    cfg = {'LARK_LIVE_READ_ENABLED': 'true', 'LARK_WORKER_IDENTITY': 'application'}
    readers, calls = {}, []
    def read(wid):
        calls.append(wid)
        return {'fingerprint': 'sha256:first', 'lark': {'calls': 0, 'retries': 0, 'duration_ms': 0}}
    readers.update(sources=read, roster=read, attendance=read)
    executors = []
    coordinators = []
    def coordinator(executor=None, Session=None):
        executor = executor or SynchronousExecutor()
        executors.append(executor)
        instance = RefreshCoordinator(Session or sessions, CacheRow, readers, cfg,
                                      executor=executor, clock=lambda: clock[0])
        coordinators.append(instance)
        return instance
    yield SimpleNamespace(engine=engine, sessions=sessions, clock=clock, cfg=cfg,
                          readers=readers, calls=calls, make=coordinator, wid='lark-tenant')
    for executor in executors:
        if hasattr(executor, 'shutdown'):
            executor.shutdown(wait=True)
    for instance in coordinators:
        if instance.roster_executor is not instance.executor:
            instance.roster_executor.shutdown(wait=True)
    engine.dispose()


def test_freshness_snapshot_and_ttl(harness):
    h = harness
    c = h.make()
    assert c.ensure(h.wid, 'sources')['status'] == 'fresh'
    assert c.status(h.wid) == {
        'server_time': '2026-10-07T10:00:00+08:00', 'enabled': True,
        'datasets': {
            'sources': {'as_of': '2026-10-07T10:00:00+08:00',
                        'fetched_at': '2026-10-07T10:00:00+08:00',
                        'age_seconds': 0, 'ttl_seconds': 60, 'status': 'fresh',
                        'fingerprint': 'sha256:first', 'changed_at': '2026-10-07T10:00:00+08:00',
                        'last_error': None, 'lark': {'calls': 0, 'retries': 0, 'duration_ms': 0}},
            'roster': {'as_of': None, 'fetched_at': None, 'age_seconds': None,
                       'ttl_seconds': 60, 'status': 'never', 'fingerprint': None,
                       'changed_at': None, 'last_error': None,
                       'lark': {'calls': 0, 'retries': 0, 'duration_ms': 0}, 'hard_max_age_seconds': 900},
            'attendance': {'as_of': None, 'fetched_at': None, 'age_seconds': None,
                           'ttl_seconds': 300, 'status': 'never', 'fingerprint': None,
                           'changed_at': None, 'last_error': None,
                           'lark': {'calls': 0, 'retries': 0, 'duration_ms': 0}}}}
    c.ensure(h.wid, 'sources')
    assert h.calls == [h.wid]
    h.clock[0] += timedelta(seconds=60)
    assert c.status(h.wid)['datasets']['sources']['status'] == 'stale'
    c.ensure(h.wid, 'sources')
    assert len(h.calls) == 2
    assert c.status(h.wid)['datasets']['sources']['changed_at'] == '2026-10-07T10:00:00+08:00'


def test_as_of_is_read_start_and_changed_at_advances_only_on_change(harness):
    h = harness
    def read(wid):
        h.clock[0] += timedelta(seconds=2)
        return {'fingerprint': 'new', 'lark': {'calls': 3, 'retries': 1, 'duration_ms': 2000}}
    h.readers['sources'] = read
    c = h.make()
    result = c.ensure(h.wid, 'sources', wait=True)
    assert result['as_of'] == '2026-10-07T10:00:00+08:00'
    assert result['fetched_at'] == result['changed_at'] == '2026-10-07T10:00:02+08:00'
    assert result['lark'] == {'calls': 3, 'retries': 1, 'duration_ms': 2000}
    h.readers['sources'] = lambda wid: {'fingerprint': 'changed'}
    h.clock[0] += timedelta(seconds=1)
    assert c.ensure(h.wid, 'sources', force=True)['changed_at'] == '2026-10-07T10:00:03+08:00'


@pytest.mark.parametrize('wid,enabled,identity', [
    ('demo-user', 'true', 'application'), ('test-lark-tenant', 'true', 'application'),
    ('lark-tenant', 'false', 'application'), ('lark-tenant', 'true', 'user')])
def test_isolated_or_disabled_workspaces_never_call_readers(harness, wid, enabled, identity):
    h = harness
    h.cfg.update(LARK_LIVE_READ_ENABLED=enabled, LARK_WORKER_IDENTITY=identity)
    with h.sessions.begin() as db:
        db.add(WorkspaceRow(id=wid, version=1, data={'as_of': '2026-10-07T09:00:00+08:00'}))
    c = h.make()
    for dataset in h.readers:
        assert c.ensure(wid, dataset, wait=True, force=True)['status'] == 'unconfigured'
    block = c.status(wid)
    assert block['enabled'] is False
    assert {r['as_of'] for r in block['datasets'].values()} == {'2026-10-07T09:00:00+08:00'}
    assert h.calls == []
    with h.sessions() as db:
        assert db.query(CacheRow).count() == 0


def test_concurrent_ensure_coalesces_to_one_threaded_refresh(harness):
    h = harness
    entered, release = Event(), Event()
    def read(wid):
        h.calls.append(wid)
        entered.set()
        assert release.wait(5)
        return {'fingerprint': 'one'}
    h.readers['sources'] = read
    c = h.make(ThreadPoolExecutor(max_workers=2))
    try:
        with ThreadPoolExecutor(max_workers=20) as callers:
            results = list(callers.map(lambda _: c.ensure(h.wid, 'sources'), range(20)))
        assert entered.wait(1)
        assert all(r['status'] == 'refreshing' for r in results)
        assert h.calls == [h.wid]
        assert c.queue_depth == 1
    finally:
        release.set()
    assert c.ensure(h.wid, 'sources', wait=True)['status'] == 'fresh'


def test_two_sessionmakers_race_for_one_lease(harness):
    h = harness
    entered, release, race = Event(), Event(), Barrier(2)
    def read(wid):
        h.calls.append(wid)
        entered.set()
        assert release.wait(5)
        return {'fingerprint': 'one'}
    h.readers['sources'] = read
    other_engine = create_engine(h.engine.url, connect_args={'check_same_thread': False})
    a = h.make(ThreadPoolExecutor(max_workers=2))
    b = h.make(ThreadPoolExecutor(max_workers=2), sessionmaker(other_engine))
    def call(c):
        race.wait()
        return c.ensure(h.wid, 'sources')
    try:
        with ThreadPoolExecutor(max_workers=2) as callers:
            results = list(callers.map(call, [a, b]))
        assert entered.wait(1)
        assert [r['status'] for r in results] == ['refreshing', 'refreshing']
        assert h.calls == [h.wid]
    finally:
        release.set()
    assert b.ensure(h.wid, 'sources', wait=True)['status'] == 'fresh'
    other_engine.dispose()


def test_lease_expiry_and_late_owner_is_fenced(harness):
    h = harness
    entered, release = Event(), Event()
    def slow(wid):
        entered.set()
        assert release.wait(5)
        return {'fingerprint': 'expired-owner'}
    h.readers['sources'] = slow
    a = h.make(ThreadPoolExecutor(max_workers=2))
    try:
        a.ensure(h.wid, 'sources')
        assert entered.wait(1)
        h.clock[0] += timedelta(seconds=119)
        b = h.make()
        assert b.ensure(h.wid, 'sources')['status'] == 'refreshing'
        h.clock[0] += timedelta(seconds=1)
        h.readers['sources'] = lambda wid: {'fingerprint': 'new-owner'}
        assert b.ensure(h.wid, 'sources', wait=True)['fingerprint'] == 'new-owner'
    finally:
        release.set()
    a._futures[a._key(h.wid, 'sources')].result(timeout=2)
    assert a.status(h.wid)['datasets']['sources']['fingerprint'] == 'new-owner'


def test_wait_timeout_local_and_foreign_lease(harness):
    h = harness
    release = Event()
    h.cfg['LARK_LIVE_READ_BLOCKING_TIMEOUT_SECONDS'] = '.03'
    def slow(wid):
        assert release.wait(5)
        return {'fingerprint': 'late'}
    h.readers['sources'] = slow
    a = h.make(ThreadPoolExecutor(max_workers=2))
    try:
        with pytest.raises(TimeoutError):
            a.ensure(h.wid, 'sources', wait=True)
        with pytest.raises(TimeoutError):
            h.make().ensure(h.wid, 'sources', wait=True)
        assert a.status(h.wid)['datasets']['sources']['status'] == 'refreshing'
    finally:
        release.set()
    a._futures[a._key(h.wid, 'sources')].result(timeout=2)


def test_error_preserves_good_data_and_cooldown_blocks_background(harness):
    h = harness
    c = h.make()
    c.ensure(h.wid, 'sources')
    h.clock[0] += timedelta(seconds=60)
    failures = []
    def fail(wid):
        failures.append(wid)
        raise OSError('sensitive transport detail')
    h.readers['sources'] = fail
    result = c.ensure(h.wid, 'sources')
    assert result['status'] == 'error'
    assert result['fingerprint'] == 'sha256:first'
    assert result['as_of'] == '2026-10-07T10:00:00+08:00'
    assert result['last_error'] == 'Lark refresh failed'
    c.ensure(h.wid, 'sources')
    with pytest.raises(RuntimeError, match='Lark refresh failed'):
        c.ensure(h.wid, 'sources', wait=True)
    assert len(failures) == 1
    h.clock[0] += timedelta(seconds=30)
    with pytest.raises(OSError):
        c.ensure(h.wid, 'sources', wait=True)
    assert len(failures) == 2


def test_executor_has_two_slots_and_no_unbounded_queue(harness):
    h = harness
    release, lock = Event(), Lock()
    def slow(wid):
        with lock:
            h.calls.append(wid)
        assert release.wait(5)
        return {'fingerprint': 'done'}
    h.readers.update({dataset: slow for dataset in h.readers})
    c = RefreshCoordinator(h.sessions, CacheRow, h.readers, h.cfg, clock=lambda: h.clock[0])
    try:
        c.ensure(h.wid, 'sources')
        c.ensure('lark-second', 'sources')
        assert c.ensure(h.wid, 'attendance')['status'] == 'busy'
        assert c.queue_depth == 2
        assert c._read(c._key(h.wid, 'attendance')) == {}
    finally:
        release.set()
        c.close()
    assert len(h.calls) == 2


def test_ttls_clamped_and_status_is_a_read_only_projection(harness):
    h = harness
    h.cfg.update(LARK_LIVE_READ_SOURCE_TTL_SECONDS='1', LARK_LIVE_READ_ROSTER_TTL_SECONDS='1',
                 LARK_LIVE_READ_ATTENDANCE_TTL_SECONDS='1')
    block = h.make().status(h.wid)
    assert [r['ttl_seconds'] for r in block['datasets'].values()] == [30, 30, 60]
    assert h.calls == []


@pytest.mark.parametrize('failed', [False, True])
def test_claim_rechecks_freshness_and_cooldown_after_other_owner_finishes(harness, failed):
    h = harness
    if failed:
        def fail(wid):
            h.calls.append(wid)
            raise OSError('offline')
        h.readers['sources'] = fail
    other = h.make()
    class RacedCoordinator(RefreshCoordinator):
        def _claim(self, key, now, dataset, force):
            other.ensure(h.wid, dataset)
            return super()._claim(key, now, dataset, force)
    c = RacedCoordinator(h.sessions, CacheRow, h.readers, h.cfg,
                         executor=SynchronousExecutor(), clock=lambda: h.clock[0])
    assert c.ensure(h.wid, 'sources')['status'] == ('error' if failed else 'fresh')
    assert h.calls == [h.wid]


def test_rejected_executor_records_error_and_releases_capacity(harness):
    h = harness
    class RejectedExecutor:
        def submit(self, *args):
            raise RuntimeError('executor unavailable')
    c = h.make(RejectedExecutor())
    assert c.ensure(h.wid, 'sources')['status'] == 'error'
    assert c.status(h.wid)['datasets']['sources']['last_error'] == 'Lark refresh failed'
    assert c.ensure(h.wid, 'roster')['status'] == 'error'
    assert c.ensure(h.wid, 'attendance')['status'] == 'error'
    assert h.calls == []


@pytest.mark.parametrize('value,expected', [('60.5', 60.5), ('abc', 60), ('nan', 60), ('inf', 60)])
def test_config_is_sanitized_before_status_and_ensure(harness, value, expected):
    h = harness
    h.cfg.update(LARK_LIVE_READ_SOURCE_TTL_SECONDS=value,
                 LARK_LIVE_READ_BLOCKING_TIMEOUT_SECONDS=value,
                 LARK_LIVE_READ_LEASE_SECONDS=value)
    c = h.make()
    assert c.status(h.wid)['datasets']['sources']['ttl_seconds'] == expected
    assert c.ensure(h.wid, 'sources', wait=True)['status'] == 'fresh'


def test_negative_lease_has_safe_apply_allowance(harness):
    h = harness
    h.cfg['LARK_LIVE_READ_LEASE_SECONDS'] = '-5'
    c = h.make()
    now = c._now()
    claimed = c._claim(c._key(h.wid, 'sources'), now, 'sources', False)
    from .live_read.status import timestamp
    assert (timestamp(claimed['lease_until']) - now).total_seconds() >= 60


def test_roster_admission_has_capacity_when_background_lanes_are_full(harness):
    h = harness
    release = Event()
    def slow(wid):
        assert release.wait(5)
        return {'fingerprint': 'background'}
    h.readers.update(sources=slow, attendance=slow)
    c = RefreshCoordinator(h.sessions, CacheRow, h.readers, h.cfg, clock=lambda: h.clock[0])
    try:
        c.ensure(h.wid, 'sources')
        c.ensure(h.wid, 'attendance')
        assert c.ensure(h.wid, 'roster', wait=True)['status'] == 'fresh'
    finally:
        release.set()
        c.close()
        if hasattr(c, 'roster_executor'):
            c.roster_executor.shutdown(wait=True)


def test_waiting_caller_waits_for_capacity_without_permission_status(harness):
    h = harness
    release, waiting = Event(), Event()
    h.cfg['LARK_LIVE_READ_BLOCKING_TIMEOUT_SECONDS'] = '.2'
    def slow(wid):
        waiting.set()
        assert release.wait(5)
        return {'fingerprint': 'done'}
    h.readers['sources'] = slow
    c = h.make(ThreadPoolExecutor(max_workers=2))
    try:
        c.ensure('lark-one', 'sources')
        c.ensure('lark-two', 'sources')
        assert waiting.wait(1)
        assert c.ensure('lark-three', 'sources')['status'] == 'busy'
        with pytest.raises(TimeoutError):
            c.ensure('lark-three', 'sources', wait=True)
    finally:
        release.set()


def test_database_round_trips_never_hold_process_lock(harness):
    h = harness
    c = h.make()
    original_read, original_replace = c._read, c._replace
    def unlocked(operation):
        def run(*args):
            assert c._lock.acquire(blocking=False), 'DB call holds process lock'
            c._lock.release()
            return operation(*args)
        return run
    c._read, c._replace = unlocked(original_read), unlocked(original_replace)
    assert c.ensure(h.wid, 'sources', wait=True)['status'] == 'fresh'


def test_fresh_ensure_reads_only_its_dataset_without_lock(harness):
    h = harness
    c = h.make()
    c.ensure(h.wid, 'sources')
    keys = []
    original = c._read
    def read(key):
        keys.append(key)
        return original(key)
    c._read = read
    assert c.ensure(h.wid, 'sources')['status'] == 'fresh'
    assert keys == [c._key(h.wid, 'sources')]


def test_force_bypasses_error_cooldown(harness):
    h = harness
    def fail(wid):
        raise OSError('private detail')
    h.readers['sources'] = fail
    c = h.make()
    assert c.ensure(h.wid, 'sources')['status'] == 'error'
    h.readers['sources'] = lambda wid: {'fingerprint': 'recovered'}
    assert c.ensure(h.wid, 'sources', force=True, wait=True)['fingerprint'] == 'recovered'


def test_permission_failure_status_and_logs_are_sanitized(harness, caplog):
    from .live_read.client import ReadBlocked
    h = harness
    def denied(wid):
        raise ReadBlocked('secret-sensitive-details')
    h.readers['sources'] = denied
    c = h.make()
    result = c.ensure(h.wid, 'sources')
    assert result['status'] == 'blocked'
    assert result['error_code'] == 'ReadBlocked'
    assert 'ReadBlocked' in caplog.text
    assert 'secret-sensitive-details' not in caplog.text


def test_status_marks_missing_refresher_unconfigured(harness):
    h = harness
    del h.readers['roster']
    assert h.make().status(h.wid)['datasets']['roster']['status'] == 'unconfigured'


def test_force_reports_already_running(harness):
    h = harness
    release, entered = Event(), Event()
    def slow(wid):
        entered.set()
        assert release.wait(5)
        return {'fingerprint': 'running'}
    h.readers['sources'] = slow
    c = h.make(ThreadPoolExecutor(max_workers=2))
    try:
        c.ensure(h.wid, 'sources')
        assert entered.wait(1)
        assert c.ensure(h.wid, 'sources', force=True)['status'] == 'already_running'
    finally:
        release.set()
