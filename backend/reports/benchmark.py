"""Offline report benchmark: python -B -m backend.reports.benchmark.

Fictional 8,565-row workload; no credentials, database or network access needed.
The optional --data argument uses an existing read-only report export instead.
"""
import argparse
import asyncio
import cProfile
from datetime import date, timedelta
import json
from pathlib import Path
import pstats
import statistics
import tempfile
from threading import Event
import time

import httpx
from fastapi import FastAPI

from ..benchmark_reports import run
from . import compute
from .reader import FixtureReader
from .registry import TABLES
from .routes import register
from .snapshot import SnapshotStore


COUNTS = dict(field=3000, office=1500, field_cost=1500, office_cost=300,
              case=319, contract=573, plan=1200, vehicle=30, instrument=45,
              people=65, monthly=30, issue=3)


def fictional_export(directory):
    def text(value): return [{'text': str(value)}]
    def linked(*ids): return [{'record_ids': list(ids)}]
    def day(i): return date(2026, 7, 1) + timedelta(days=i % 105)
    for table in TABLES:
        rows = []
        for i in range(COUNTS[table.kind]):
            code = f'C{i % 319:04d}'
            group = f'第{i % 12}組'
            fields = {}
            if table.kind in ('field', 'office'):
                dt = day(i)
                fields = {'工作單號': text(i), '所屬成本單': linked(f'recCost{i % 1500}'),
                          '案件編號': text(code), '出工日期': dt.isoformat(),
                          '工作日期-營業額明細': dt.isoformat(), '營業額組別-明細': text(group),
                          '營業額人員-明細': text(f'人員{i % 65}'), '姓名': text(f'人員{i % 65}'),
                          '檢核狀態': ('已通過', '已退回', '待檢核', '')[i % 4],
                          '最終營業額點數': text(i % 20), '工項': text(f'測量{i % 8}'),
                          '備註': text('離線合成資料')}
                # The shared benchmark independently checks numeric Lark dates.
                fields['出工日期'] = (dt - date(1899, 12, 30)).days
            elif table.kind == 'field_cost':
                fields = {'組別': text(group), '工作日期': day(i).isoformat(),
                          '出發里程1': i * 100, '結束里程1': i * 100 + 40}
            elif table.kind == 'office_cost':
                fields = {'工作日期': day(i).isoformat(), '內業組別': group}
            elif table.kind == 'case':
                fields = {'案件編號': text(code), '案件名稱': text(f'合成案件{i}'),
                          'PM': text(f'PM{i % 12}'), '業主': text(f'客戶{i % 40}'),
                          '狀態': '執行中' if i % 3 else '已結案', '預期營業額點數': text(100),
                          '累計外業營業額點數': text(40), '預期合約金額': text(100000 + i * 1000)}
            elif table.kind == 'plan':
                fields = {'開始日期': day(i).isoformat(),
                          '結束日期': (day(i) + timedelta(days=i % 14)).isoformat(),
                          '業別': '外業' if i % 2 else '內業', '條類型': '出工',
                          '案件': text(code), '組別': text(group), '預估營業額點數': text(i % 20)}
            elif table.kind in ('vehicle', 'instrument'):
                fields = {'車牌': f'車{i}', '儀器名稱': f'儀器{i}', '啟用': True,
                          '第一台車紀錄': linked(*(f'recCost{j}' for j in range(i, 1500, 30))),
                          '使用此儀器的成本單': linked(*(f'recCost{j}' for j in range(i, 1500, 45)))}
            ident = f'recCost{i}' if table.kind == 'field_cost' else f'rec{table.kind}{i}'
            rows.append(dict(record_id=ident, fields={k: v for k, v in fields.items() if k in table.fields}))
        (Path(directory) / (table.name + '.json')).write_text(json.dumps(dict(records=rows), ensure_ascii=False))


async def cold_contention(directory):
    """48 cold reports compete with a normal sync detail route in one process."""
    release = Event()
    class DelayedReader:
        calls = 0
        def read(self):
            self.calls += 1
            assert release.wait(5)
            return FixtureReader(directory).read()
    reader = DelayedReader()
    app = FastAPI()
    store = register(app, lambda _: ({'wid': 'benchmark', 'mode': 'lark'}, {}),
                     {'REPORTS_COLD_WAIT_SECONDS': '1'}, reader=reader)
    @app.get('/detail')
    def detail(): return {'ok': True}
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://offline') as client:
            tasks = [asyncio.create_task(client.get('/api/reports/sales')) for _ in range(48)]
            await asyncio.sleep(.15)
            started = time.perf_counter()
            response = await client.get('/detail')
            elapsed = (time.perf_counter() - started) * 1000
            assert response.status_code == 200
            release.set()
            reports = await asyncio.gather(*tasks)
            return dict(detail_ms=elapsed, report_requests=len(reports), builds=reader.calls,
                        report_statuses=sorted({r.status_code for r in reports}))
    finally:
        release.set()
        store.close()


def benchmark(directory, requests, rounds):
    builds = []
    for _ in range(5):
        store = SnapshotStore(FixtureReader(directory))
        started = time.perf_counter()
        store.get()
        builds.append((time.perf_counter() - started) * 1000)
        store.close()
    profiler = cProfile.Profile()
    store = SnapshotStore(FixtureReader(directory))
    snapshot=profiler.runcall(store._build)
    store.close()
    print('Cold snapshot cProfile:')
    pstats.Stats(profiler).strip_dirs().sort_stats('cumulative').print_stats(18)
    profiler=cProfile.Profile()
    profiler.enable()
    for i in range(100):
        compute.assets(snapshot['data'],kind=('vehicle','instrument')[i%2],
                       **{'from':'2026-07-01','to':'2026-10-15'})
    profiler.disable()
    print('100 uncached asset queries cProfile:')
    pstats.Stats(profiler).strip_dirs().sort_stats('cumulative').print_stats(12)
    result = run(directory, requests=requests, rounds=rounds)
    result['build_ms'] = dict(median=statistics.median(builds), samples=builds)
    result['cold_contention'] = asyncio.run(cold_contention(directory))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data')
    parser.add_argument('--requests', type=int, default=30)
    parser.add_argument('--rounds', type=int, default=3)
    args = parser.parse_args()
    if args.data:
        benchmark(args.data, args.requests, args.rounds)
    else:
        with tempfile.TemporaryDirectory(prefix='reports-benchmark-') as directory:
            fictional_export(directory)
            benchmark(directory, args.requests, args.rounds)
