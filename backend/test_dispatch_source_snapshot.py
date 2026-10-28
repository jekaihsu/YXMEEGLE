"""Request-local dispatch reads and deterministic slow-source comparison."""
from collections import Counter
from copy import deepcopy
from threading import Lock
import time

import pytest

from .dispatch_board.config import SOURCES
from .dispatch_board.lark_table import read_source, source_snapshot
from .dispatch_board.service import DispatchBoardService
from .dispatch_publish.domain import Sources
from .dispatch_publish.service import Context, DispatchPublishService, KEYS, WORK_KEYS
from .live_read.client import ReadBlocked, ReadFailure
from .models import AuditRow
from .test_dispatch_publish import CFG, T0, USERS, h  # noqa: F401


class SlowReader:
    def __init__(self, fake, delay=0.04, errors=None):
        self.rows = {key: [{'record_id': rid, 'fields': deepcopy(fields)}
                           for rid, fields in fake.tables.get(table.table_id, {}).items()]
                     for key, table in SOURCES.items()}
        self.delay, self.errors = delay, errors or {}
        self.calls, self.active, self.peak = Counter(), 0, 0
        self.lock = Lock()

    def read_table(self, key):
        with self.lock:
            self.calls[key] += 1
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep(self.delay)
            if key in self.errors:
                raise self.errors[key]
            return deepcopy(self.rows[key])
        finally:
            with self.lock:
                self.active -= 1


class SerialService(DispatchPublishService):
    def _work_sources(self, wid):
        entries, rows, failed = {}, {}, []
        for key in WORK_KEYS:
            try:
                entries[key] = self._cached(wid, key)
                rows[key] = entries[key].value
            except Exception:
                if key == 'tasks':
                    raise
                failed.append(key)
                rows[key] = None
        return Sources(schedule=None, **{key: rows.get(key) for key in KEYS if key != 'schedule'}), entries, failed


def service(h, cls=DispatchPublishService, **reader_options):
    return cls(CFG, sessions=h.sessions, audit_model=AuditRow, clock=lambda: T0,
               reader=SlowReader(h.fake, **reader_options))


def context(actor='ou_pm'):
    return Context('lark-company', next(u for u in USERS if u['id'] == actor),
                   {'users': USERS}, True)


def test_slow_source_benchmark(h):
    timings, bodies, peaks = {}, {}, {}
    for name, cls in [('serial', SerialService), ('current', DispatchPublishService)]:
        svc = service(h, cls)
        start = time.perf_counter()
        bodies[name] = svc.work(context())
        timings[name] = round((time.perf_counter() - start) * 1000, 1)
        peaks[name] = svc.reader.peak
        assert svc.reader.calls == Counter(WORK_KEYS)
    assert bodies['serial'] == bodies['current']
    assert peaks == {'serial': 1, 'current': 3}
    print(f'\nslow sources (40 ms each): {timings}; peak concurrent reads: {peaks}')


@pytest.mark.parametrize('key', WORK_KEYS)
@pytest.mark.parametrize('error', [ReadFailure('offline'), ReadBlocked('revoked')])
@pytest.mark.parametrize('warm', [False, True])
def test_work_failure_and_stale_contract_matches_serial(h, key, error, warm):
    bodies = []
    for cls in (SerialService, DispatchPublishService):
        svc = service(h, cls, delay=0)
        if warm:
            svc.work(context())
            svc.cache.clock = lambda: T0 + 61
            svc.clock = lambda: T0 + 61
        svc.reader.errors[key] = error
        bodies.append(svc.work(context()))
        if not warm and key == 'tasks':
            assert svc.reader.calls == Counter({'tasks': 1})
    assert bodies[0] == bodies[1]


def test_request_shares_sources_across_services_but_not_workspaces_or_requests(h):
    publish = service(h, delay=0)
    board = DispatchBoardService(CFG, reader=publish.reader, clock=lambda: T0)
    try:
        with source_snapshot():
            entry, error = board._read('lark-company', 'people')
            assert error is None
            assert publish._cached('lark-company', 'people').value == entry.value
            assert publish.reader.calls['people'] == 1
            publish._cached('another-workspace', 'people')
            assert publish.reader.calls['people'] == 2
        publish.cache.drop(('lark-company', 'people'))
        with source_snapshot():
            publish._cached('lark-company', 'people')
        assert publish.reader.calls['people'] == 3
    finally:
        board.close()


def test_failed_source_is_shared_only_within_request(h):
    svc = service(h, delay=0, errors={'people': ReadBlocked('revoked')})
    with source_snapshot():
        for _ in range(2):
            with pytest.raises(ReadBlocked):
                svc._cached('lark-company', 'people')
    assert svc.reader.calls['people'] == 1
    svc.reader.errors.clear()
    with source_snapshot():
        assert svc._cached('lark-company', 'people').value
    assert svc.reader.calls['people'] == 2


def test_fresh_publish_validation_bypasses_request_snapshot(h):
    svc = service(h, delay=0)
    with source_snapshot():
        first = svc.sources('lark-company', keys=('tasks',))[0].tasks
        svc.reader.rows['tasks'] = []
        fresh = svc.sources('lark-company', keys=('tasks',), fresh=True)[0].tasks
    assert first and fresh == []
    assert svc.reader.calls['tasks'] == 2


def test_concurrent_requests_do_not_share_snapshot_or_actor_overlay(h):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    svc = service(h, delay=0)
    barrier = Barrier(2)

    def run(actor):
        with source_snapshot():
            barrier.wait(timeout=2)
            read_source(svc.reader, svc.cfg, 'lark-company', 'people')
            return svc.work(context(actor), scope='mine')

    with ThreadPoolExecutor(max_workers=2) as pool:
        bodies = list(pool.map(run, ['ou_pm', 'ou_pm2']))
    # Raw source snapshots do not carry the actor's derived work queue.
    assert svc.reader.calls['people'] == 2
    assert bodies[0] == svc.work(context('ou_pm'), scope='mine')
    assert bodies[1] == svc.work(context('ou_pm2'), scope='mine')
    assert bodies[0] != bodies[1]


def test_authorization_and_work_share_snapshot_across_route_threadpool_calls(h):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from .dispatch_publish.routes import register

    reader = SlowReader(h.fake, delay=0)
    app = FastAPI()
    svc = register(app, identity=lambda _: ({'mode': 'lark', 'wid': 'lark-company'},
                                           {'id': 'ou_lead', 'role': 'member'}),
                   allow=lambda *_: False, cfg=CFG, sessions=h.sessions, audit_model=AuditRow,
                   workspace=lambda _: {'users': USERS}, reader=reader, clock=lambda: T0)
    svc.cache.ttl = -1
    with TestClient(app) as client:
        for count in (1, 2):
            response = client.get('/api/v2/dispatch/work')
            assert response.status_code == 200
            assert response.json()['source']['quality']['states'] == ['complete']
            assert reader.calls == Counter({key: count for key in WORK_KEYS})


def test_multiple_join_failures_keep_source_order(h):
    errors = {key: ReadFailure('offline') for key in WORK_KEYS if key != 'tasks'}
    serial = service(h, SerialService, delay=0, errors=errors)._work_sources('lark-company')
    concurrent = service(h, delay=0, errors=errors)._work_sources('lark-company')
    assert concurrent == serial
    assert concurrent[2] == list(WORK_KEYS[1:])


def test_snapshot_separates_authz_versions_and_projections(h):
    svc = service(h, delay=0)
    with source_snapshot():
        read_source(svc.reader, CFG, 'lark-company', 'people')
        read_source(svc.reader, {**CFG, 'LARK_AUTHZ_VERSION': '2'}, 'lark-company', 'people')
        read_source(svc.reader, CFG, 'lark-company', 'accounts')
    assert svc.reader.calls == Counter(people=2, accounts=1)
