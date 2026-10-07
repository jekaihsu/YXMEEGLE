"""Synthetic Lark boundary tests; no credentials or outbound requests."""
import concurrent.futures

import httpx
import pytest

from backend.live_read.config import LiveReadConfig
from backend.live_read.rate_limit import BudgetExceeded, RetryPolicy, TokenBucket


class Clock:
    def __init__(self):
        self.now = 0
        self.waits = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.now += seconds


def test_config_defaults_and_clamps():
    assert LiveReadConfig.from_env({}) == LiveReadConfig()
    cfg = LiveReadConfig.from_env({
        'LARK_LIVE_READ_ENABLED': 'true', 'LARK_LIVE_READ_SOURCE_TTL_SECONDS': '1',
        'LARK_LIVE_READ_ROSTER_TTL_SECONDS': '-1',
        'LARK_LIVE_READ_ATTENDANCE_TTL_SECONDS': '20', 'LARK_LIVE_READ_MAX_RPS': '30',
        'LARK_BITABLE_RECORDS_API': 'search',
    })
    assert (cfg.enabled, cfg.source_ttl_seconds, cfg.roster_ttl_seconds,
            cfg.attendance_ttl_seconds, cfg.max_rps, cfg.records_api) == (True, 30, 30, 60, 10, 'search')
    for value in ('nan', 'inf', 'bad'):
        assert LiveReadConfig.from_env({'LARK_LIVE_READ_MAX_RPS': value}).max_rps == 5
    assert LiveReadConfig.from_env({'LARK_BITABLE_RECORDS_API': 'unknown'}).records_api == 'list'


def test_retry_header_precedence_and_fallback():
    assert RetryPolicy.after(httpx.Response(429, headers={
        'x-ogw-ratelimit-reset': '7', 'Retry-After': '19'})) == 7
    assert RetryPolicy.after(httpx.Response(429, headers={
        'x-ogw-ratelimit-reset': 'invalid', 'Retry-After': '3'})) == 3
    for attempt, delay in ((1, 1), (2, 2), (3, 4), (9, 30)):
        assert RetryPolicy.after(httpx.Response(429), attempt) == delay


def test_bucket_serializes_concurrent_callers_and_enforces_budget():
    clock = Clock()
    bucket = TokenBucket(5, clock=clock, sleep=clock.sleep)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: bucket.acquire(45), range(20)))
    assert clock.now == pytest.approx(19 / 5)
    assert all(delay == pytest.approx(.2) for delay in clock.waits)
    with pytest.raises(BudgetExceeded):
        bucket.acquire(clock.now + .1)

from backend import capability_write_policy
from backend.live_read.client import LiveLarkClient, ReadBlocked, ReadFailure
from backend.live_read.token_cache import TenantTokenCache

CFG = {'LARK_APP_ID': 'fake-app', 'LARK_APP_SECRET': 'fake-secret',
       'LARK_WORKER_ORGANIZATION': 'fake-tenant', 'LARK_WORKER_IDENTITY': 'application'}
PATH = '/bitable/v1/apps/fake-base/tables/fake-table/records'


def make_client(handler, clock=None, cache=None, **kwargs):
    clock = clock or Clock()
    return LiveLarkClient(CFG, httpx.MockTransport(handler), clock=clock, sleep=clock.sleep,
                          bucket=TokenBucket(5, clock=clock, sleep=clock.sleep),
                          token_cache=cache or TenantTokenCache(clock=clock), **kwargs)


def responses(sequence):
    calls = []
    def handler(request):
        calls.append(request)
        if '/auth/' in request.url.path:
            return httpx.Response(200, json={'code': 0, 'tenant_access_token': 'fake-token', 'expire': 7200})
        return sequence.pop(0)
    return calls, handler


def test_token_reuse_expiry_and_thread_safety():
    clock = Clock()
    cache = TenantTokenCache(clock=clock)
    minted = []
    def mint(credentials):
        minted.append(credentials)
        return {'tenant_access_token': 'fake-token', 'expire': 7200}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(lambda _: cache.get(CFG, mint), range(20))) == ['fake-token'] * 20
    assert len(minted) == 1
    clock.now = 7200 - 2100
    cache.get(CFG, mint)
    assert len(minted) == 1
    clock.now += .1
    cache.get(CFG, mint)
    assert len(minted) == 2
    cache.get(dict(CFG, LARK_WORKER_ORGANIZATION='other'), mint)
    assert len(minted) == 3
    cache.invalidate(CFG)
    cache.get(CFG, mint)
    assert len(minted) == 4


def test_response_interface_metrics_and_cached_auth():
    calls, handler = responses([httpx.Response(200, json={'code': 0, 'data': {}})] * 2)
    with make_client(handler) as client:
        assert isinstance(client.request('GET', PATH), httpx.Response)
        client.request('GET', 'https://open.larksuite.com/open-apis' + PATH)
        assert client.metrics == {'calls': 3, 'retries': 0, 'duration_ms': 400}
    assert len([r for r in calls if '/auth/' in r.url.path]) == 1
    assert calls[-1].headers['Authorization'] == 'Bearer fake-token'


@pytest.mark.parametrize('status,code', [(429, 99991400), (200, 1254290), (200, 99991400),
                                         (200, 1254607), (503, 0)])
def test_retry_attempt_limit(status, code):
    calls, handler = responses([httpx.Response(status, json={'code': code})] * 3)
    with make_client(handler) as client:
        with pytest.raises(ReadFailure, match='attempts exhausted'):
            client.request('GET', PATH)
        assert client.retries == 2
    assert len(calls) == 4  # One token mint and exactly three reads.


def test_header_wait_and_success():
    clock = Clock()
    _, handler = responses([httpx.Response(429, headers={
        'x-ogw-ratelimit-reset': '7', 'Retry-After': '20'}, json={'code': 99991400}),
        httpx.Response(200, json={'code': 0, 'data': {}})])
    with make_client(handler, clock) as client:
        client.request('GET', PATH)
        assert 7 in clock.waits and 20 not in clock.waits
        assert client.retries == 1


@pytest.mark.parametrize('code', [99991663, 99991677])
def test_expired_token_reminted_once(code):
    calls, handler = responses([httpx.Response(200, json={'code': code})] * 2)
    with make_client(handler) as client:
        with pytest.raises(ReadFailure):
            client.request('GET', PATH)
        assert client.retries == 1
    assert len([r for r in calls if '/auth/' in r.url.path]) == 2
    assert len(calls) == 4


@pytest.mark.parametrize('status,code', [(401, 0), (403, 0), (200, 1254302)])
def test_access_denied_never_retried(status, code):
    calls, handler = responses([httpx.Response(status, json={'code': code})])
    with make_client(handler) as client:
        with pytest.raises(ReadBlocked):
            client.request('GET', PATH)
        assert client.retries == 0
    assert len(calls) == 2


def test_budget_covers_backoff_rate_wait_and_elapsed_http():
    calls, handler = responses([httpx.Response(429, headers={
        'x-ogw-ratelimit-reset': '45'}, json={'code': 99991400})])
    clock = Clock()
    with make_client(handler, clock) as client:
        with pytest.raises(BudgetExceeded):
            client.request('GET', PATH)
        assert len(calls) == 2
        clock.now = 46
        with pytest.raises(BudgetExceeded):
            client.request('GET', PATH)
        assert len(calls) == 2
    slow_clock = Clock()
    def slow(request):
        slow_clock.now += 46
        return httpx.Response(200, json={'code': 0})
    with make_client(slow, slow_clock) as client:
        with pytest.raises(BudgetExceeded):
            client.request('GET', PATH)


@pytest.mark.parametrize('method,path', [('PUT', PATH), ('DELETE', PATH), ('HEAD', PATH),
    ('POST', PATH), ('POST', '/attendance/v1/user_daily_shifts/query'),
    ('PUT', '/bitable/v1/apps/' + capability_write_policy.CAPABILITY_BASE + '/tables/t/records/r'),
    ('GET', 'https://example.invalid/open-apis/records')])
def test_disallowed_requests_never_send(method, path):
    def forbidden(request):
        pytest.fail('Disallowed request sent')
    with make_client(forbidden) as client:
        with pytest.raises(ReadBlocked):
            client.request(method, path)
        assert client.calls == 0


def test_salary_search_allowed_and_write_policy_consulted(monkeypatch):
    calls, handler = responses([httpx.Response(200, json={'code': 0})])
    with make_client(handler) as client:
        client.request('POST', '/bitable/v1/apps/' + capability_write_policy.CAPABILITY_BASE +
                       '/tables/fake/records/search', json={})
        monkeypatch.setattr(capability_write_policy, 'protected_request', lambda *_: True)
        with pytest.raises(ReadBlocked):
            client.request('GET', PATH)
    assert len(calls) == 2


def test_deny_transport_never_mints_or_sends():
    with LiveLarkClient(dict(CFG, LARK_LIVE_READ_TRANSPORT='deny')) as client:
        with pytest.raises(ReadBlocked, match='disabled'):
            client.request('GET', PATH)
        assert client.calls == 0


def test_token_mint_is_retried_and_budgeted():
    attempts = []
    def handler(request):
        attempts.append(request)
        if len(attempts) == 1:
            return httpx.Response(503, json={'code': 0})
        if '/auth/' in request.url.path:
            return httpx.Response(200, json={'tenant_access_token': 'fake', 'expire': 7200})
        return httpx.Response(200, json={'code': 0})
    with make_client(handler) as client:
        client.request('GET', PATH)
        assert client.retries == 1 and client.calls == 3


def test_invalid_token_then_success_uses_new_authorization():
    minted = []
    reads = []
    def handler(request):
        if '/auth/' in request.url.path:
            minted.append(request)
            return httpx.Response(200, json={'tenant_access_token': f'fake-{len(minted)}', 'expire': 7200})
        reads.append(request.headers['Authorization'])
        return httpx.Response(200, json={'code': 99991663 if len(reads) == 1 else 0})
    with make_client(handler) as client:
        client.request('GET', PATH)
    assert reads == ['Bearer fake-1', 'Bearer fake-2']
    assert len(minted) == 2


@pytest.mark.parametrize('body', [{'code': []}, {'code': {}}, [], {'code': True}])
def test_malformed_response_fails_without_retry(body):
    calls, handler = responses([httpx.Response(200, json=body)])
    with make_client(handler) as client:
        with pytest.raises(ReadFailure):
            client.request('GET', PATH)
        assert client.retries == 0
    assert len(calls) == 2


def test_caller_cannot_override_application_auth():
    calls, handler = responses([httpx.Response(200, json={'code': 0})])
    with make_client(handler) as client:
        with pytest.raises(ReadBlocked):
            client.request('GET', PATH, auth=False, headers={'Authorization': 'Bearer fake-user'})
        assert not calls
        client.request('GET', PATH, headers={'Authorization': 'Bearer fake-user'})
    assert calls[-1].headers['Authorization'] == 'Bearer fake-token'


@pytest.mark.parametrize('status', [401, 403, 429, 503])
def test_http_status_handling_does_not_depend_on_body_shape(status):
    calls, handler = responses([httpx.Response(status, json={'code': []})] * 3)
    with make_client(handler) as client:
        with pytest.raises(ReadBlocked if status in (401, 403) else ReadFailure):
            client.request('GET', PATH)
        assert client.retries == (0 if status in (401, 403) else 2)
    assert len(calls) == (2 if status in (401, 403) else 4)
