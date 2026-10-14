"""Read-cache contracts and a rerunnable mock Lark latency comparison."""
import concurrent.futures
import json
import subprocess
import threading
import time
import types
from dataclasses import replace

import httpx
import pytest

from .live_read.client import LiveLarkClient, ReadBlocked
from .live_read.config import LiveReadConfig
from .live_read.rate_limit import BudgetExceeded, RetryPolicy, TokenBucket
from .live_read.token_cache import TenantTokenCache
from .node_assignment.cache import ReadScope, StaleCache
from .node_assignment.config import NodeAssignmentConfig
from .node_assignment.errors import Failure
from .node_assignment.lark_table import BitableClient, Table
from .sources import fetch_sources
from .test_live_read_client import Clock, CFG
from .test_live_read_coordinator import harness


def test_ten_callers_share_one_cold_read():
    cache = StaleCache(60, 900)
    started, release = threading.Event(), threading.Event()
    calls = []
    def load():
        calls.append(1)
        started.set()
        assert release.wait(2)
        return {'complete': True, 'records': ['r1', 'r2']}
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(cache.get, 'same-query', load) for _ in range(10)]
        assert started.wait(1)
        release.set()
        assert [f.result().value for f in futures] == [{'complete': True, 'records': ['r1', 'r2']}] * 10
    assert calls == [1]


def test_scope_version_projection_filter_sort_and_view_isolate_snapshots():
    cache = StaleCache(60, 900)
    scope = ReadScope('tenant', 'app', 'user-a', 'workspace', 'v1')
    scopes = [scope, replace(scope, identity='user-b'), replace(scope, tenant='tenant-b'),
              replace(scope, app='app-b'), replace(scope, workspace='workspace-b'),
              replace(scope, authz_version='v2')]
    keys = [s.key('table', projection=['name'], filter={'owner': 'a'}) for s in scopes]
    keys += [scope.key('table', projection=['salary']), scope.key('table', filter={'owner': 'b'}),
             scope.key('table', sort=[{'field_name': 'name', 'desc': True}]), scope.key('table', view='view-b')]
    for i, key in enumerate(keys):
        cache.put(key, i)
    assert [cache.get(key, lambda: -1).value for key in keys] == list(range(10))
    assert scope.key('t', projection=['b', 'a']) == scope.key('t', projection=['a', 'b'])


def test_partial_never_replaces_complete_last_good():
    clock = Clock()
    cache = StaleCache(60, 900, clock)
    cache.put('query', {'complete': True, 'records': ['r1', 'r2']})
    clock.now = 61
    partial = cache.get('query', lambda: {'status': 'partial', 'records': ['r1']})
    assert (partial.read_state, partial.complete, partial.value['records']) == ('partial', False, ['r1'])
    def offline():
        raise RuntimeError('offline')
    stale = cache.get('query', offline)
    assert (stale.value['records'], stale.stale, stale.complete) == (['r1', 'r2'], True, True)


@pytest.mark.parametrize('failure', [Failure('lark_permission', 'denied'), ReadBlocked('denied')])
def test_permission_denial_drops_last_good_without_stale_fallback(failure):
    clock = Clock()
    cache = StaleCache(60, 900, clock)
    cache.put('private', ['sensitive'])
    clock.now = 61
    def denied():
        raise failure
    with pytest.raises(type(failure)):
        cache.get('private', denied)
    assert cache.get('private', lambda: ['new']).value == ['new']


def test_429_honours_retry_after_and_penalizes_shared_budget(monkeypatch):
    clock = Clock()
    cfg = dict(CFG, LARK_LIVE_READ_ENABLED='true')
    calls = []
    def handler(request):
        if '/auth/' in request.url.path:
            return httpx.Response(200, json={'tenant_access_token': 'fake', 'expire': 7200})
        calls.append(clock.now)
        if len(calls) == 1:
            return httpx.Response(429, headers={'Retry-After': '3', 'x-ogw-ratelimit-reset': '1'}, json={'code': 99991400})
        return httpx.Response(200, json={'code': 0, 'data': {}})
    bucket = TokenBucket(5, clock=clock, sleep=clock.sleep)
    with LiveLarkClient(cfg, httpx.MockTransport(handler), clock=clock, sleep=clock.sleep,
                        bucket=bucket, token_cache=TenantTokenCache(clock=clock)) as client:
        client.request('GET', '/bitable/v1/apps/base/tables/table/records')
        assert (client.calls, client.retries) == (3, 1)
    assert calls == [.2, 3.2]
    monkeypatch.setattr('backend.live_read.rate_limit.random.uniform', lambda low, high: high)
    assert RetryPolicy.after(httpx.Response(429), 2, jitter=True) == 2.5


def test_attendance_deadline_caps_each_http_timeout_and_total_wait():
    clock = Clock()
    timeouts = []
    def handler(request):
        timeouts.append(request.extensions['timeout']['read'])
        if '/auth/' in request.url.path:
            return httpx.Response(200, json={'tenant_access_token': 'fake', 'expire': 7200})
        clock.now += 9
        return httpx.Response(200, json={'code': 0, 'data': {}})
    with LiveLarkClient(CFG, httpx.MockTransport(handler), clock=clock, sleep=clock.sleep,
                        bucket=TokenBucket(5, clock=clock, sleep=clock.sleep),
                        token_cache=TenantTokenCache(clock=clock)) as client:
        with pytest.raises(BudgetExceeded):
            for _ in range(10):
                client.request('GET', '/attendance/v1/shifts/shift')
        assert client.deadline == 40
        assert client.calls == 6
    assert timeouts == [10, 10, 10, 10, 10, pytest.approx(3.8)]
    config = LiveReadConfig.from_env({})
    assert [config.dataset_budget(d) for d in ('sources', 'roster', 'attendance')] == [60, 30, 40]


def test_batch_get_missing_or_forbidden_records_cannot_be_complete():
    for payload, expected in [({'records': [], 'absent_record_ids': ['r1']}, 'lark_error'),
                              ({'records': [], 'forbidden_record_ids': ['r1']}, 'lark_permission'),
                              ({'records': []}, 'lark_error')]:
        def handler(request):
            if '/auth/' in request.url.path:
                return httpx.Response(200, json={'tenant_access_token': 'fake', 'expire': 7200})
            return httpx.Response(200, json={'code': 0, 'data': payload})
        clock = Clock()
        with BitableClient(CFG, NodeAssignmentConfig(), httpx.MockTransport(handler), clock=clock,
                           sleep=clock.sleep, bucket=TokenBucket(5, clock=clock, sleep=clock.sleep),
                           token_cache=TenantTokenCache(clock=clock)) as client:
            with pytest.raises(Failure) as error:
                client.batch_get(Table.TASKS, ['r1'])
            assert error.value.code == expected



def test_projected_source_query_coalesces_and_schema_ttl_survives_refresh(monkeypatch):
    from . import sources
    clock = Clock()
    monkeypatch.setattr(sources, '_source_cache', StaleCache(60, 900, clock))
    monkeypatch.setattr(sources, '_schema_cache', StaleCache(1800, 1800, clock))
    scope = ReadScope('tenant', 'app', 'viewer', 'workspace', 'v1')
    table = {'base_token': 'mock', 'table_id': 'table', 'kind': 'confirmation', 'field_names': ['工程名稱'],
             'filter': {'conjunction': 'and', 'conditions': [{'field_name': '工程名稱', 'operator': 'is', 'value': ['case']}]},
             'sort': [{'field_name': '工程名稱', 'desc': False}], 'view_id': 'view'}
    cfg = {'LARK_V4_BASE_TOKEN': 'mock', 'LARK_SOURCE_TABLES_JSON': json.dumps([table]),
           'LARK_LIVE_READ_ENABLED': 'true', 'LARK_BITABLE_RECORDS_API': 'search'}
    requests = []
    entered, release = threading.Event(), threading.Event()
    def handler(request):
        requests.append(request)
        if request.url.path.endswith('/fields'):
            entered.set()
            assert release.wait(2)
            data = {'items': [{'field_name': '工程名稱', 'type': 1}], 'has_more': False}
        else:
            assert dict(request.url.params) == {'page_size': '500', 'user_id_type': 'open_id'}
            assert json.loads(request.content) == {'field_names': ['工程名稱'], 'automatic_fields': True,
                                                   'filter': table['filter'], 'sort': table['sort'], 'view_id': 'view'}
            data = {'items': [{'record_id': 'r1', 'fields': {'工程名稱': 'case'}}], 'has_more': False, 'total': 1}
        return httpx.Response(200, json={'code': 0, 'data': data})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(fetch_sources, 'fake', cfg, client, scope=scope) for _ in range(10)]
            assert entered.wait(1)
            release.set()
            results = [f.result() for f in futures]
        assert [(r['complete'], r['readState'], len(r['records'])) for r in results] == [(True, 'complete', 1)] * 10
        assert len(requests) == 2
        clock.now = 61
        assert fetch_sources('fake', cfg, client, scope=scope)['records'][0]['record_id'] == 'r1'
        assert [r.url.path.rsplit('/', 1)[-1] for r in requests] == ['fields', 'search', 'search']
        fetch_sources('fake', cfg, client, scope=replace(scope, authz_version='v2'))
        assert len(requests) == 5


def test_actual_upstream_permission_denial_clears_coordinator_snapshot(harness):
    h = harness
    c = h.make()
    h.readers['attendance'] = lambda wid: {'fingerprint': 'old', 'snapshot': {'people': ['private']}}
    c.ensure(h.wid, 'attendance')
    def denied(wid):
        raise ReadBlocked('denied', upstream_status=403, lark_code=1254302, kind='permission_denied')
    h.readers['attendance'] = denied
    c.ensure(h.wid, 'attendance', force=True)
    row = c._read(c._key(h.wid, 'attendance'))
    assert (row.get('snapshot'), row.get('fingerprint'), row['complete'], row['error_code']) == (None, None, False, 'ReadBlocked')


def benchmark():
    baseline = types.ModuleType('backend.ux_baseline_sources')
    baseline.__package__ = 'backend'
    exec(subprocess.check_output(['git', 'show', '151f19f:backend/sources.py'], text=True), baseline.__dict__)
    sizes = [106, 573, 701, 213, 187, 201, 348]
    for run in range(5):
        for label, fetch in [('before', baseline.fetch_sources), ('after', fetch_sources)]:
            base = f'mock{label}{run}'
            cfg = dict(CFG, LARK_LIVE_READ_ENABLED='true', LARK_BITABLE_RECORDS_API='search',
                       LARK_V4_BASE_TOKEN=base, LARK_SOURCE_TABLES_JSON=json.dumps([
                           {'base_token': base, 'table_id': f't{i}', 'kind': 'daily', 'field_names': ['日期']}
                           for i in range(7)]))
            calls = []
            active = [0, 0]
            lock = threading.Lock()
            def handler(request):
                with lock:
                    active[0] += 1
                    active[1] = max(active)
                    calls.append(request.url.path)
                time.sleep(.35)
                with lock:
                    active[0] -= 1
                if request.url.path.endswith('/fields'):
                    data = {'items': [{'field_name': '日期', 'type': 5}], 'has_more': False}
                else:
                    i = int(request.url.path.split('/tables/')[1].split('/')[0][1:])
                    start = int(request.url.params.get('page_token', '0'))
                    end = min(start + int(request.url.params['page_size']), sizes[i])
                    data = {'items': [{'record_id': f'r{j}', 'fields': {'日期': 1}} for j in range(start, end)],
                            'has_more': end < sizes[i], 'page_token': str(end), 'total': sizes[i]}
                return httpx.Response(200, json={'code': 0, 'data': data})
            tokens = TenantTokenCache()
            tokens.get(cfg, lambda _: {'tenant_access_token': 'fake', 'expire': 7200})
            with LiveLarkClient(cfg, httpx.MockTransport(handler), token_cache=tokens) as client:
                began = time.monotonic()
                scope = ReadScope('fake-tenant', 'fake-app', 'application', base, 'v1')
                snapshot = fetch('fake', cfg, client, **({'scope': scope} if label == 'after' else {}))
                elapsed = time.monotonic() - began
                assert len(snapshot['records']) == 2329 and snapshot['status'] == 'ready'
                assert sum(t['pages_read'] for t in snapshot['tables']) == 9
                print(json.dumps(dict(side=label, run=run, seconds=round(elapsed, 4),
                                      calls=len(calls), pages=9, records=2329, errors=0,
                                      max_concurrency=active[1])), flush=True)
                if label == 'after':
                    call_count = len(calls)
                    began = time.monotonic()
                    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
                        warm = list(pool.map(lambda _: fetch('fake', cfg, client, scope=scope), range(10)))
                    assert [len(s['records']) for s in warm] == [2329] * 10
                    print(json.dumps(dict(side='warm', run=run, seconds=round(time.monotonic() - began, 4),
                                          callers=10, calls=len(calls) - call_count, records_per_caller=2329, errors=0)), flush=True)


if __name__ == '__main__':
    benchmark()
