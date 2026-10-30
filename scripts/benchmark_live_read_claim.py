"""Measure stale-while-revalidate calls while a real DB transaction holds the lease row.

Uses an isolated database and a fake refresher; never contacts Lark.
Usage: python -B scripts/benchmark_live_read_claim.py --db sqlite --repeats 5
"""
import argparse
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path
from threading import Event, Thread, Timer
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, update  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from backend.live_read.coordinator import RefreshCoordinator  # noqa: E402
from backend.models import Base, CacheRow  # noqa: E402
from scripts.benchmark_source_sync import make_database  # noqa: E402


def run(target, repeats=5, hold_ms=250):
    url, drop = make_database(target)
    engine = create_engine(url)
    coordinator = None
    try:
        Base.metadata.create_all(engine)
        sessions = sessionmaker(engine, expire_on_commit=False)
        calls = []

        def refresh(wid):
            calls.append(wid)
            return {'fingerprint': 'unchanged'}

        clock = datetime.fromisoformat('2026-10-07T10:00:00+08:00')
        coordinator = RefreshCoordinator(sessions, CacheRow, {'sources': refresh},
            {'LARK_LIVE_READ_ENABLED': 'true', 'LARK_WORKER_IDENTITY': 'application'}, clock=lambda: clock)
        samples = []
        for i in range(repeats):
            wid = f'lark-benchmark-{i}'
            key = coordinator._key(wid, 'sources')
            data = {'revision': 'initial', 'as_of': '2026-10-07T09:58:00+08:00',
                    'fingerprint': 'unchanged'}
            with sessions.begin() as db:
                db.add(CacheRow(id=key, data=data))
            locked, release = Event(), Event()

            def hold():
                with sessions.begin() as db:
                    db.execute(update(CacheRow).where(CacheRow.id == key).values(data=data))
                    locked.set()
                    if not release.wait(5):
                        raise RuntimeError('benchmark lease lock was not released')

            holder = Thread(target=hold)
            holder.start()
            timer = Timer(hold_ms / 1000, release.set)
            try:
                if not locked.wait(5):
                    raise RuntimeError('benchmark did not acquire the lease row')
                timer.start()
                start = perf_counter()
                result = coordinator.ensure(wid, 'sources')
                samples.append((perf_counter() - start) * 1000)
                assert result['as_of'] is not None, 'last-good data must remain usable'
            finally:
                release.set()
                holder.join()
                timer.cancel()
                if timer.ident is not None:
                    timer.join()
            assert coordinator.ensure(wid, 'sources', wait=True)['status'] == 'fresh'
        assert len(calls) == repeats, 'every stale dataset must refresh exactly once'
        return {'database': 'sqlite' if target == 'sqlite' else 'postgresql', 'runs': repeats,
                'lease_lock_ms': hold_ms, 'request_ms': {'median': round(statistics.median(samples), 1),
                'min': round(min(samples), 1), 'max': round(max(samples), 1)}, 'refresh_calls': len(calls)}
    finally:
        if coordinator is not None:
            coordinator.close()
        engine.dispose()
        drop()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default='sqlite')
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--hold-ms', type=float, default=250)
    parser.add_argument('--out')
    args = parser.parse_args()
    report = run(args.db, args.repeats, args.hold_ms)
    rendered = json.dumps(report, indent=2)
    if args.out:
        Path(args.out).write_text(rendered + '\n', encoding='utf-8')
    print(rendered)


if __name__ == '__main__':
    main()
