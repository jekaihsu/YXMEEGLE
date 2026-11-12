"""Lease renewal behavior with synthetic slow readers and file-backed SQLite."""
from dataclasses import replace
from datetime import timedelta
from threading import Event, current_thread, enumerate as threads
from time import monotonic, sleep

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError, TimeoutError as PoolTimeout
from sqlalchemy.orm import sessionmaker

from .live_read.coordinator import LeaseLost, RefreshCoordinator
from .models import Base, CacheRow


@pytest.fixture
def coordinator(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path / "renewal.db"}',
                           connect_args={'check_same_thread': False, 'timeout': .2})
    Base.metadata.create_all(engine)
    c = RefreshCoordinator(sessionmaker(engine), CacheRow, {}, {})
    # Short synthetic durations; production config and its clamps are untouched.
    c.config = replace(c.config, lease_seconds=.3, budget_seconds=1.5)
    yield c
    c.close()
    engine.dispose()


def start(c, reader):
    c.refreshers['sources'] = reader
    now = c._now()
    key = c._key('synthetic-workspace', 'sources')
    claim = c._claim(key, now, 'sources', True)
    future = c.executor.submit(c._refresh, 'synthetic-workspace', 'sources', key, claim, now)
    return key, claim, future


def until(predicate):
    deadline = monotonic() + 3
    while not predicate():
        assert monotonic() < deadline, 'condition did not become true'
        sleep(.01)


def test_refresh_slower_than_lease_commits_successfully(coordinator):
    c = coordinator
    # 1:200 scale of the reported read (~100 s) + apply (~45 s), with the
    # existing defaults of lease 120 s and read budget 100 s.
    c.config = replace(c.config, lease_seconds=.6, budget_seconds=.5)
    def slow(wid):
        sleep(.5)  # read
        sleep(.225)  # apply/import before the first commit
        with c.Session.begin() as db:
            db.add(CacheRow(id='synthetic-result', data={'value': 'committed'}))
        return {'fingerprint': 'slow-success'}
    key, _, future = start(c, slow)
    future.result(timeout=3)
    assert c._read(key)['fingerprint'] == 'slow-success'
    assert c._read(key)['lease_until'] is None
    assert c._read('synthetic-result') == {'value': 'committed'}


def test_takeover_fences_old_owner_and_preserves_new_owner(coordinator):
    c = coordinator
    entered, release = Event(), Event()
    def slow(wid):
        entered.set()
        assert release.wait(3)
        with c.Session.begin() as db:
            db.add(CacheRow(id='forbidden-old-result', data={'value': 'old'}))
        return {'fingerprint': 'old'}
    key, claim, future = start(c, slow)
    try:
        assert entered.wait(1)
        until(lambda: c._read(key)['lease_until'] != claim['lease_until'])
        winner = dict(revision='new-owner', fingerprint='winner',
                      lease_until=(c._now() + timedelta(seconds=10)).isoformat())
        assert c._replace(key, claim['revision'], winner)
        sleep(.15)  # allow the periodic CAS to observe the takeover
    finally:
        release.set()
    with pytest.raises(LeaseLost):
        future.result(timeout=3)
    assert c._read(key) == winner
    assert c._read('forbidden-old-result') == {}


def test_lost_renewal_is_fatal_even_without_a_service_commit(coordinator, monkeypatch):
    c = coordinator
    entered, release, failed = Event(), Event(), Event()
    original = c._fence
    def database_failure(db, key, claim, **options):
        if current_thread().name.startswith('live-read-lease:'):
            failed.set()
            raise LeaseLost('synthetic ownership loss')
        return original(db, key, claim, **options)
    monkeypatch.setattr(c, '_fence', database_failure)
    def slow(wid):
        entered.set()
        assert release.wait(3)
        return {'fingerprint': 'must-not-publish'}
    key, claim, future = start(c, slow)
    try:
        assert entered.wait(1)
        assert failed.wait(1)
    finally:
        release.set()
    with pytest.raises(LeaseLost):
        future.result(timeout=3)
    assert c._read(key) == claim
    assert not any(t.name == f'live-read-lease:{key}' for t in threads())


def test_apply_write_lock_does_not_lose_valid_lease(coordinator, caplog):
    c = coordinator
    c.config = replace(c.config, lease_seconds=.6, budget_seconds=.5)
    def apply(wid):
        sleep(.02)
        with c.Session.begin() as db:
            db.add(CacheRow(id='synthetic-lock-result', data={'value': 'committed'}))
            db.flush()
            sleep(.52)  # hold the write lock across the first renewal tick
        return {'fingerprint': 'lock-success'}
    key, _, future = start(c, apply)
    future.result(timeout=3)
    assert c._read('synthetic-lock-result') == {'value': 'committed'}
    assert c._read(key)['fingerprint'] == 'lock-success'
    assert c._read(key)['lease_until'] is None
    assert [r.getMessage() for r in caplog.records] == ['OperationalError']


@pytest.mark.parametrize('error', [
    OSError('synthetic private database detail'),
    PoolTimeout('synthetic private pool detail'),
    OperationalError('synthetic private SQL', {}, Exception('private detail')),
], ids=['os-error', 'pool-timeout', 'operational-error'])
def test_transient_renewal_error_is_sanitized_and_retried(
        coordinator, monkeypatch, caplog, error):
    c = coordinator
    c.config = replace(c.config, lease_seconds=.9)
    original = c._fence
    failed, renewed, release = Event(), Event(), Event()
    def transient_failure(db, key, claim, **options):
        if current_thread().name.startswith('live-read-lease:'):
            if not failed.is_set():
                failed.set()
                raise error
            result = original(db, key, claim, **options)
            renewed.set()
            return result
        return original(db, key, claim, **options)
    monkeypatch.setattr(c, '_fence', transient_failure)
    def slow(wid):
        assert release.wait(3)
        with c.Session.begin() as db:
            db.add(CacheRow(id='retry-result', data={'value': 'committed'}))
        return {'fingerprint': 'retry-success'}
    key, _, future = start(c, slow)
    try:
        assert failed.wait(1)
        assert renewed.wait(1)
    finally:
        release.set()
    future.result(timeout=3)
    assert c._read('retry-result') == {'value': 'committed'}
    assert c._read(key)['fingerprint'] == 'retry-success'
    assert c._read(key)['lease_until'] is None
    assert [r.getMessage() for r in caplog.records] == [type(error).__name__]
    assert not any(t.name == f'live-read-lease:{key}' for t in threads())


def test_expired_claim_cannot_be_revived_without_a_takeover(coordinator):
    c = coordinator
    now = c._now()
    key = c._key('synthetic-workspace', 'sources')
    claim = c._claim(key, now, 'sources', True)
    c.clock = lambda: now + timedelta(seconds=1)
    def apply(wid):
        with c.Session.begin() as db:
            db.add(CacheRow(id='expired-result', data={'value': 'expired'}))
        return {'fingerprint': 'expired'}
    c.refreshers['sources'] = apply
    with pytest.raises(LeaseLost):
        c._refresh('synthetic-workspace', 'sources', key, claim, now)
    assert c._read(key) == claim
    assert c._read('expired-result') == {}


def test_commit_renewal_is_capped_at_the_claim_horizon(coordinator):
    c = coordinator
    c.config = replace(c.config, lease_seconds=.6, budget_seconds=.5)
    now = c._now()
    c.clock = lambda: now
    leases = []
    def apply(wid):
        c.clock = lambda: now + timedelta(seconds=.5)
        until(lambda: c._read(c._key(wid, 'sources'))['lease_until']
              == (now + timedelta(seconds=1.1)).isoformat())
        c.clock = lambda: now + timedelta(seconds=.9)
        with c.Session.begin() as db:
            db.add(CacheRow(id='bounded-commit', data={'value': 'applied'}))
        leases.append(c._read(c._key(wid, 'sources'))['lease_until'])
        return {'fingerprint': 'bounded-commit'}
    key, _, future = start(c, apply)
    future.result(timeout=3)
    assert leases == [(now + timedelta(seconds=1.1)).isoformat()]
    assert c._read('bounded-commit') == {'value': 'applied'}
    assert c._read(key)['lease_until'] is None


@pytest.mark.parametrize('failed', [False, True])
def test_renewal_stops_on_success_and_failure(coordinator, failed):
    c = coordinator
    entered, release = Event(), Event()
    def slow(wid):
        entered.set()
        assert release.wait(3)
        if failed:
            raise ValueError('synthetic failure')
        return {'fingerprint': 'finished'}
    key, claim, future = start(c, slow)
    try:
        assert entered.wait(1)
        until(lambda: c._read(key)['lease_until'] != claim['lease_until'])
    finally:
        release.set()
    if failed:
        with pytest.raises(ValueError):
            future.result(timeout=3)
    else:
        future.result(timeout=3)
    row = c._read(key)
    assert row['lease_until'] is None
    assert row.get('error_code') == ('ValueError' if failed else None)
    assert not any(t.name == f'live-read-lease:{key}' for t in threads())
    sleep(.15)
    assert c._read(key) == row


def test_hung_refresher_cannot_renew_or_commit_past_existing_budget(coordinator):
    c = coordinator
    c.config = replace(c.config, budget_seconds=.55)
    entered, release = Event(), Event()
    def hung(wid):
        entered.set()
        assert release.wait(3)
        with c.Session.begin() as db:
            db.add(CacheRow(id='late-result', data={'value': 'late'}))
        return {'fingerprint': 'late'}
    began = c._now()
    key, claim, future = start(c, hung)
    try:
        assert entered.wait(1)
        until(lambda: c._read(key)['lease_until'] != claim['lease_until'])
        sleep(1)  # claim + lease + budget = .85 s
        expired = c._read(key)
        assert c._now().isoformat() > expired['lease_until']
        assert expired['lease_until'] <= (began + timedelta(seconds=.9)).isoformat()
        assert not any(t.name == f'live-read-lease:{key}' for t in threads())
        sleep(.15)
        assert c._read(key) == expired
    finally:
        release.set()
    with pytest.raises(LeaseLost):
        future.result(timeout=3)
    assert c._read('late-result') == {}
    assert c._read(key) == expired
