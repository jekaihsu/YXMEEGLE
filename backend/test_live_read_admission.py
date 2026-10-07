"""Frozen-clock admission checks with real coordinator leases and fake Lark."""
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta
import json
from threading import Event
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .live_read.admission import ensure_roster_for_admission
from .live_read.client import LiveLarkClient
from .live_read.coordinator import RefreshCoordinator
from .live_read.rate_limit import TokenBucket
from .live_read.token_cache import TenantTokenCache
from .models import Base, CacheRow, PersonRow
from .production_access import access_mode, require_access, roster_age_seconds


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
    now = datetime.fromisoformat('2026-10-07T10:00:00+08:00')
    engine = create_engine(f'sqlite:///{tmp_path / "admission.db"}',
                           connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    cfg = {'LARK_LIVE_READ_ENABLED': 'true', 'LARK_WORKER_IDENTITY': 'application',
           'LARK_APP_ID': 'app1', 'LARK_APP_SECRET': 'fake',
           'LARK_WORKER_ORGANIZATION': 'tenant', 'LARK_ALLOWED_TENANTS': 'tenant'}
    person = {'id': 'employee', 'active': True, 'role': 'member',
              'identity_app_id': 'app1', 'directory_status': 'employed',
              'directory_source': {'app_id': 'app1', 'record_id': 'record1'}}
    calls = []

    def refresh(wid):
        calls.append(wid)
        with sessions.begin() as db:
            row = db.get(PersonRow, (wid, person['id']))
            row.data = {**row.data, 'directory_last_seen_at': now.isoformat()}
        return {'fingerprint': 'sha256:roster'}

    coordinator = RefreshCoordinator(sessions, CacheRow, {'roster': refresh}, cfg,
                                     executor=SynchronousExecutor(), clock=lambda: now)

    def store(age):
        value = dict(person)
        if age is not None:
            value['directory_last_seen_at'] = (now - timedelta(seconds=age)).isoformat()
        with sessions.begin() as db:
            db.merge(PersonRow(organization_id='lark-tenant', person_id=person['id'], data=value))
        return value

    def reload():
        with sessions() as db:
            return dict(db.get(PersonRow, ('lark-tenant', person['id'])).data)

    yield SimpleNamespace(now=now, cfg=cfg, person=person, calls=calls, store=store,
                          reload=reload, coordinator=coordinator, wid='lark-tenant')
    engine.dispose()


@pytest.mark.parametrize('age,wait', [(59, None), (60, False), (899, False),
                                    (900, False), (901, True), (None, True)])
def test_age_bands_refresh_then_reload_before_access(harness, age, wait):
    h = harness
    old = h.store(age)
    seen = []
    ensure = h.coordinator.ensure

    def record(*args, **kwargs):
        seen.append(kwargs)
        return ensure(*args, **kwargs)

    h.coordinator.ensure = record
    assert ensure_roster_for_admission(h.coordinator, h.wid, old, now=h.now)
    assert seen == ([] if wait is None else [{'wait': wait, 'force': wait and age is not None}])
    assert len(h.calls) == (0 if wait is None else 1)
    assert require_access(h.reload(), 'app1', now=h.now) == 'normal'
    if age is None or age > 900:
        assert access_mode(old, 'app1', now=h.now) == 'denied'


@pytest.mark.parametrize('stamp', [None, '', 'invalid', '2026-10-07T10:00:00',
                                 '2026-10-07T10:00:01+08:00', 42])
def test_invalid_roster_age_is_unknown(harness, stamp):
    assert roster_age_seconds({'directory_last_seen_at': stamp}, harness.now) is None


def fail_refresh(wid):
    raise OSError('fake outage')


@pytest.mark.parametrize('age', [60, 899, 900])
def test_nonblocking_failure_preserves_current_admission(harness, age):
    h = harness
    person = h.store(age)
    h.coordinator.refreshers['roster'] = fail_refresh
    assert ensure_roster_for_admission(h.coordinator, h.wid, person, now=h.now)
    assert require_access(h.reload(), 'app1', now=h.now) == 'normal'


def test_lark_429_blocking_failure_denies_stale_employee(harness):
    h = harness
    person = h.store(901)
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.path.endswith('/tenant_access_token/internal'):
            return httpx.Response(200, json={'code': 0, 'tenant_access_token': 'fake-token', 'expire': 7200})
        return httpx.Response(429, headers={'x-ogw-ratelimit-reset': '0'}, json={'code': 99991400})

    def refresh(wid):
        with LiveLarkClient(h.cfg, transport=httpx.MockTransport(respond),
                            clock=lambda: 0, sleep=lambda _: None,
                            token_cache=TenantTokenCache(clock=lambda: 0),
                            bucket=TokenBucket(clock=lambda: 0, sleep=lambda _: None)) as client:
            client.request('GET', '/bitable/v1/apps/fake/tables/roster/records')

    h.coordinator.refreshers['roster'] = refresh
    assert not ensure_roster_for_admission(h.coordinator, h.wid, person, now=h.now)
    assert len(requests) == 4  # One fake token call and three rate-limited reads.
    with pytest.raises(HTTPException) as error:
        require_access(h.reload(), 'app1', now=h.now)
    assert error.value.status_code == 403
    assert '15分鐘' in error.value.detail


def test_failed_blocking_read_keeps_bootstrap_recovery(harness):
    h = harness
    h.person.update(role='manager', bootstrap_admin=True)
    person = h.store(901)
    h.coordinator.refreshers['roster'] = fail_refresh
    assert ensure_roster_for_admission(h.coordinator, h.wid, person, now=h.now)
    assert require_access(h.reload(), 'app1', now=h.now, allow_recovery=True) == 'recovery'


def test_company_admin_grant_remains_normal_on_failed_read(harness):
    h = harness
    h.person.update(role='manager', bootstrap_admin=True, oauth_identity={
        'source': 'oauth_user_info', 'app_id': 'app1', 'tenant': 'tenant',
        'open_id': 'employee', 'verified_at': h.now.isoformat()})
    h.cfg['LARK_COMPANY_ADMIN_GRANTS_JSON'] = json.dumps([{
        'open_id': 'employee', 'app_id': 'app1', 'tenant': 'tenant',
        'authorized_at': h.now.isoformat(), 'enabled': True, 'role': 'manager',
        'grant_id': 'grant1', 'reason': 'test', 'authorized_by': 'owner', 'decision_ref': 'test1'}])
    person = h.store(901)
    h.coordinator.refreshers['roster'] = fail_refresh
    assert ensure_roster_for_admission(h.coordinator, h.wid, person, now=h.now)
    assert require_access(h.reload(), 'app1', now=h.now, cfg=h.cfg, tenant='tenant') == 'normal'


@pytest.mark.parametrize('age,expected_calls', [(59, 0), (60, 1)])
def test_callback_waits_at_soft_ttl_and_rejects_failed_read(harness, age, expected_calls):
    h = harness
    person = h.store(age)
    calls = []

    def fail(wid):
        calls.append(wid)
        raise OSError('fake outage')

    h.coordinator.refreshers['roster'] = fail
    assert ensure_roster_for_admission(h.coordinator, h.wid, person, now=h.now,
                                       callback=True) is (expected_calls == 0)
    assert len(calls) == expected_calls


def test_blocking_timeout_returns_failure(harness):
    h = harness
    person = h.store(901)
    release = Event()
    h.cfg['LARK_LIVE_READ_BLOCKING_TIMEOUT_SECONDS'] = '.01'

    def slow(wid):
        assert release.wait(5)
        return {'fingerprint': 'late'}

    with ThreadPoolExecutor(max_workers=2) as executor:
        h.coordinator.executor = executor
        h.coordinator.refreshers['roster'] = slow
        try:
            assert not ensure_roster_for_admission(h.coordinator, h.wid, person, now=h.now)
            assert access_mode(h.reload(), 'app1', now=h.now) == 'denied'
        finally:
            release.set()


def test_blocking_admission_reads_even_when_dataset_cache_is_fresh(harness):
    h = harness
    h.store(0)
    h.coordinator.ensure(h.wid, 'roster', wait=True)
    stale = h.store(901)
    assert ensure_roster_for_admission(h.coordinator, h.wid, stale, now=h.now)
    assert len(h.calls) == 2
    assert require_access(h.reload(), 'app1', now=h.now) == 'normal'


def test_callback_success_still_checks_reloaded_employment(harness):
    h = harness
    person = h.store(60)

    def offboard(wid):
        with h.coordinator.Session.begin() as db:
            row = db.get(PersonRow, (wid, person['id']))
            row.data = {**row.data, 'directory_status': 'left',
                        'directory_last_seen_at': h.now.isoformat()}
        return {'fingerprint': 'sha256:left'}

    h.coordinator.refreshers['roster'] = offboard
    assert ensure_roster_for_admission(h.coordinator, h.wid, person, now=h.now, callback=True)
    assert access_mode(h.reload(), 'app1', now=h.now) == 'denied'


def test_roster_ttl_respects_configured_minimum(harness):
    h = harness
    h.cfg['LARK_LIVE_READ_ROSTER_TTL_SECONDS'] = '1'
    assert ensure_roster_for_admission(h.coordinator, h.wid, h.store(29), now=h.now)
    assert h.calls == []
    assert ensure_roster_for_admission(h.coordinator, h.wid, h.store(30), now=h.now)
    assert h.calls == [h.wid]


@pytest.mark.parametrize('wid,enabled,identity', [
    ('demo-user', 'true', 'application'), ('test-lark-tenant', 'true', 'application'),
    ('lark-tenant', 'false', 'application'), ('lark-tenant', 'true', 'user')])
def test_disabled_or_isolated_admission_never_calls_coordinator(harness, wid, enabled, identity):
    h = harness
    h.cfg.update(LARK_LIVE_READ_ENABLED=enabled, LARK_WORKER_IDENTITY=identity)

    def unexpected(*args, **kwargs):
        pytest.fail('Admission must not start an isolated read')

    h.coordinator.ensure = unexpected
    assert ensure_roster_for_admission(h.coordinator, wid, {}, now=h.now, callback=True)


@pytest.mark.parametrize('status', ['blocked', 'unconfigured', 'refreshing', 'error'])
def test_incomplete_blocking_result_is_failure(harness, status):
    h = harness
    h.coordinator.ensure = lambda *args, **kwargs: {'status': status}
    assert not ensure_roster_for_admission(h.coordinator, h.wid, {}, now=h.now)


@pytest.mark.parametrize('fails', [False, True])
def test_unknown_age_reuses_roster_result_and_error_cooldown(harness, fails):
    h = harness
    person = h.store(None)
    calls = []
    def absent(wid):
        calls.append(wid)
        if fails:
            raise OSError('outage')
        return {'fingerprint': 'absent'}
    h.coordinator.refreshers['roster'] = absent
    for _ in range(5):
        ensure_roster_for_admission(h.coordinator, h.wid, person, now=h.now)
        assert access_mode(h.reload(), 'app1', now=h.now) == 'denied'
    assert calls == [h.wid]


def test_unknown_bootstrap_uses_nonblocking_refresh(harness):
    h = harness
    h.person.update(role='manager', bootstrap_admin=True)
    person = h.store(None)
    seen = []
    h.coordinator.ensure = lambda *args, **kwargs: seen.append(kwargs) or {'status': 'refreshing'}
    assert ensure_roster_for_admission(h.coordinator, h.wid, person, now=h.now)
    assert seen == [{'wait': False, 'force': False}]
