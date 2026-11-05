"""Report cold waits must leave the application's worker pool available."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import anyio
from fastapi import FastAPI, HTTPException
import httpx
import pytest

from backend.reports import compute
from backend.reports.reader import FixtureReader
from backend.reports.routes import register
from backend.reports.snapshot import SnapshotStore
from backend.test_reports_compute import FIXTURES


class BlockingReader:
    def __init__(self):
        self.started=Event();self.release=Event();self.calls=0

    def read(self):
        self.calls+=1;self.started.set()
        assert self.release.wait(5)
        return FixtureReader(FIXTURES).read()


@pytest.mark.parametrize('endpoint',['sales','home'])
def test_cold_reports_do_not_starve_sync_case_details(endpoint):
    async def scenario():
        reader=BlockingReader();app=FastAPI();entered=[]
        def identity(_):
            entered.append(True)
            return {'wid':'company','mode':'lark'},{}
        store=register(app,identity,
                       {'REPORTS_COLD_WAIT_SECONDS':'3'},reader=reader)
        @app.get('/case-detail')
        def detail(): return {'ok':True}
        tasks=[]
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://offline') as client:
                # More cold readers than Starlette's default 40 worker tokens.
                tasks=[asyncio.create_task(client.get('/api/reports/'+endpoint)) for _ in range(48)]
                for _ in range(200):
                    if reader.started.is_set() and len(entered)==48: break
                    await asyncio.sleep(.005)
                assert reader.started.is_set()
                assert len(entered)==48
                response=await asyncio.wait_for(client.get('/case-detail'),.5)
                assert response.json()=={'ok':True}
                assert not any(task.done() for task in tasks)
                assert anyio.to_thread.current_default_thread_limiter().borrowed_tokens==0
                reader.release.set()
                responses=await asyncio.gather(*tasks)
                assert all(r.status_code==200 for r in responses)
                assert len({r.json()['meta']['snapshot'] for r in responses})==1
                assert reader.calls==1
        finally:
            reader.release.set()
            await asyncio.gather(*tasks,return_exceptions=True)
            store.close()
    asyncio.run(scenario())


def test_async_cold_timeout_and_cancellation_keep_shared_build_alive():
    async def scenario():
        reader=BlockingReader();store=SnapshotStore(reader,{'REPORTS_COLD_WAIT_SECONDS':'.01'})
        try:
            with pytest.raises(HTTPException) as error: await store.aget()
            assert error.value.status_code==503
            assert error.value.detail['warming'] is True
            assert error.value.headers=={'Retry-After':'5'}
            assert not store._future.done()
            store.budget=2
            cancelled=asyncio.create_task(store.aget())
            survivor=asyncio.create_task(store.aget())
            await asyncio.sleep(0)
            cancelled.cancel()
            with pytest.raises(asyncio.CancelledError): await cancelled
            assert not store._future.cancelled()
            reader.release.set()
            snapshot=await survivor
            assert await store.aget() is snapshot
            assert reader.calls==1
        finally:
            reader.release.set();store.close()
    asyncio.run(scenario())


def test_async_stale_revalidation_reuses_unchanged_data_and_failure_keeps_cache():
    async def scenario():
        reader=BlockingReader();reader.release.set();clock=[0]
        store=SnapshotStore(reader,{'REPORTS_TTL_SECONDS':'1'},clock=lambda:clock[0])
        try:
            first=await store.aget();store.result('sales',{},snapshot=first)
            reader.release.clear();reader.started.clear();clock[0]=2
            assert await store.aget() is first
            assert store.meta(first)['stale'] is True
            reader.release.set()
            second=await asyncio.wrap_future(store.start())
            assert second['data'] is first['data']
            assert second['cache'] is first['cache']
            class Failing:
                def read(self): raise RuntimeError('offline failure')
            store.reader=Failing();clock[0]=4
            assert await store.aget() is second
            with pytest.raises(RuntimeError): await asyncio.wrap_future(store.start())
            assert (await store.aget()) is second
            assert store.result('sales',{},snapshot=second)['meta']['refresh_error'] is True
        finally:
            reader.release.set();store.close()
    asyncio.run(scenario())


def test_async_failure_is_not_misreported_as_warming():
    async def scenario():
        class Failing:
            def read(self): raise RuntimeError('offline failure')
        store=SnapshotStore(Failing())
        try:
            for _ in range(2):
                with pytest.raises(HTTPException) as error: await store.aget()
                assert error.value.status_code==503
                assert error.value.detail['warming'] is False
        finally: store.close()
    asyncio.run(scenario())


def test_asset_dates_are_normalized_once_per_snapshot(monkeypatch):
    raw=FixtureReader(FIXTURES).read()
    raw['field_cost']['records'].extend([
        {'record_id':'cost2','fields':{'工作日期':'2026-10-13T00:00:00+08:00'}},
        {'record_id':'missing','fields':{'工作日期':'invalid'}},
    ])
    raw['vehicle']['records'][0]['fields']['第二台車紀錄']=[{'record_ids':['cost2','cost2','missing']}]
    data=compute.normalize(raw)
    monkeypatch.setattr(compute,'day',lambda _:pytest.fail('queries must reuse snapshot dates'))
    for end,uses,coverage in [('2026-10-12',1,1),('2026-10-13',2,1)]:
        result=compute.assets(data,kind='vehicle',**{'from':'2026-10-12','to':end})
        assert result['items'][0]['uses']==uses
        assert result['kpi']['coverage']==coverage


def test_group_normalization_preserves_filtered_review_results():
    data=compute.normalize(FixtureReader(FIXTURES).read())
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda g:compute.review(data,group=g,week='2026-10-12'),['水深A','水深A組']*2))
    assert all(result==results[0] for result in results)


def test_spawn_normalization_experiment_roundtrips_snapshot_data_and_gaps():
    from concurrent.futures import ProcessPoolExecutor
    import multiprocessing
    from backend.reports.benchmark_normalization import normalize

    reader = FixtureReader(FIXTURES)
    store = SnapshotStore(reader)
    try:
        expected = store.get()
        with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context('spawn')) as pool:
            data, gaps, measured = pool.submit(normalize, reader.read()).result(timeout=10)
        assert data == expected['data']
        assert gaps == expected['gaps']
        assert measured['ended'] >= measured['started']
        assert measured['peak_rss_mib'] > 0
    finally:
        store.close()


def test_process_worker_preserves_complete_snapshot_and_refresh_reuses_data():
    from backend.reports.reader import FixtureReader
    from backend.test_reports_compute import FIXTURES
    inline=SnapshotStore(FixtureReader(FIXTURES))
    isolated=SnapshotStore(FixtureReader(FIXTURES),{'REPORTS_WORKER_PROCESS':'true'})
    try:
        expected=inline.get()
        first=isolated.get()
        assert (first['data'],first['gaps'],first['fingerprint'])==(expected['data'],expected['gaps'],expected['fingerprint'])
        assert isolated._process is not None
        second=isolated.start().result(timeout=10)
        assert second['data'] is first['data'] and second['gaps'] is first['gaps']
    finally:
        inline.close()
        isolated.close()
