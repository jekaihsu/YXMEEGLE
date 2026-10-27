"""Offline thread/spawn comparison; never starts a worker in the application.

python -B -m backend.reports.benchmark_normalization --output /tmp/report-cpu.json
Includes IPC in wall time; samples a real sync HTTP route during normalization.
"""
import argparse
import asyncio
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import json
import multiprocessing
import pickle
import resource
import statistics
import sys
import tempfile
import time

from fastapi import FastAPI
import httpx

from . import compute
from .benchmark import fictional_export
from .reader import FixtureReader


def normalize(raw):
    started = time.perf_counter()
    data = compute.normalize(raw)
    gaps = {(endpoint, dept): compute.report_gaps(data, endpoint, dept)
            for endpoint in ('sources', 'review', 'review/rows', 'sales', 'assets', 'progress', 'progress/case')
            for dept in ('field', 'office', 'control')}
    ended = time.perf_counter()
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return data, gaps, dict(started=started, ended=ended,
                            peak_rss_mib=rss / (1024**2 if sys.platform == 'darwin' else 1024))


async def sample(executor, raw, expected):
    app = FastAPI()
    @app.get('/detail')
    def detail(): return {'ok': True}
    timings = []
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://offline') as client:
        await client.get('/detail')  # Warm the shared request worker before timing.
        started = time.perf_counter()
        future = executor.submit(normalize, raw)
        while not future.done():
            before = time.perf_counter()
            response = await client.get('/detail')
            after = time.perf_counter()
            assert response.json() == {'ok': True}
            timings.append((before, after))
            await asyncio.sleep(.001)
        data, gaps, worker = future.result()
        elapsed = (time.perf_counter() - started) * 1000
        assert (data, gaps) == expected
    overlapping = [(end - start) * 1000 for start, end in timings
                   if start < worker['ended'] and end > worker['started']]
    return dict(wall_ms=elapsed, worker_ms=(worker['ended']-worker['started'])*1000,
                peak_rss_mib=worker['peak_rss_mib'], detail_ms=overlapping)


def summarize(samples):
    details = sorted(value for sample in samples for value in sample['detail_ms'])
    return dict(wall_ms=statistics.median(s['wall_ms'] for s in samples),
                worker_ms=statistics.median(s['worker_ms'] for s in samples),
                peak_rss_mib=max(s['peak_rss_mib'] for s in samples),
                detail_samples=len(details),
                detail_p50_ms=statistics.median(details) if details else None,
                detail_p95_ms=details[min(len(details)-1, int(len(details)*.95))] if details else None,
                samples=samples)


def benchmark(raw):
    data, gaps, _ = normalize(raw)
    expected = data, gaps
    with ThreadPoolExecutor(max_workers=1) as executor:
        thread = [asyncio.run(sample(executor, raw, expected)) for _ in range(5)]
    # Spawn avoids forking a running server's threads/connections; also exposes
    # startup/import costs that fork-only local experiments hide.
    with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context('spawn')) as executor:
        cold = asyncio.run(sample(executor, raw, expected))
        warm = [asyncio.run(sample(executor, raw, expected)) for _ in range(5)]
    return dict(records=sum(len(t['records']) for t in raw.values()),
                raw_pickle_bytes=len(pickle.dumps(raw)), result_pickle_bytes=len(pickle.dumps(expected)),
                thread=summarize(thread), spawn_cold=summarize([cold]), spawn_warm=summarize(warm))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='reports-cpu-') as directory:
        fictional_export(directory)
        result = benchmark(FixtureReader(directory).read())
    with open(args.output, 'w') as output:
        json.dump(result, output, indent=2)
    print(json.dumps({k: {name: value for name, value in v.items() if name != 'samples'}
                     if isinstance(v, dict) else v for k, v in result.items()}, indent=2))
