"""Time sources sync on a staging-sized workspace: a failed attempt, an unchanged snapshot and a changed one.

The workspace is built the way production builds it, by importing source records, so the
same code that applies a snapshot meets realistic project trees. `lock_held` is the time
the workspace write transaction (which takes the row lock first) stayed open.
Usage: python scripts/benchmark_source_sync.py --db sqlite --label before
"""
import argparse
import json
import statistics
import sys
import tempfile
import time
import uuid
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text, select, func  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from backend import source_sync, storage  # noqa: E402
from backend.models import Base, AuthRow, BusinessRow, CacheRow, PersonRow, WorkspaceRow  # noqa: E402
from backend.policy import upgrade  # noqa: E402
from backend.seed import seed, USERS  # noqa: E402
from backend.source_sync import SourceSyncService  # noqa: E402
from backend.sources import import_sources  # noqa: E402

WID = 'lark-tenant'
WRAPPED = ('load', 'save', 'load_partial', 'save_collections')


def make_database(target):
    if target == 'sqlite':
        return 'sqlite:///' + tempfile.mkdtemp() + '/sources.db', lambda: None
    admin = create_engine(target.replace('postgres://', 'postgresql+psycopg://'), isolation_level='AUTOCOMMIT')
    name = 'bench_' + uuid.uuid4().hex[:10]
    with admin.connect() as c: c.execute(text(f'create database {name}'))
    url = urlsplit(target.replace('postgres://', 'postgresql+psycopg://'))._replace(path='/' + name).geturl()
    def drop():
        with admin.connect() as c: c.execute(text(f'drop database {name} with (force)'))
    return url, drop


def source_records(projects, dailies_per_project, status='執行中'):
    def record(kind, rid, fields): return dict(base_token='v4', table_id=kind, record_id=rid, kind=kind, fields=fields)
    rows = [record('confirmation', f'rec{i}', {'工程確認單編號': f'C11{5000 + i}', '狀態': status if i == 0 else '執行中'}) for i in range(projects)]
    rows += [record('daily', f'recD{i}', {'工程編號': f'C11{5000 + i % projects}', '日期': '2026-09-27', '組別': '控制'}) for i in range(projects * dailies_per_project)]
    return rows


def run(target, projects, repeats, label):
    url, drop = make_database(target)
    try:
        engine = create_engine(url)
        Base.metadata.create_all(engine)
        sessions = sessionmaker(engine, expire_on_commit=False, info={'index_tables': True})
        clock = ['2026-09-27T10:00:00+08:00']
        source_sync.now = lambda: clock[0]
        source_sync.application_adapter = lambda config: SimpleNamespace(token='application-token', client=SimpleNamespace(close=lambda: None))
        ws = seed(True); ws['users'] = deepcopy(USERS)
        initial = source_records(projects, 14)
        import_sources(ws, initial); upgrade(ws)
        ws['environment'] = 'production'
        ws['source_status'] = {'status': 'ready', 'last_sync': clock[0], 'last_attempt_at': clock[0], 'message': 'last good'}
        next(u for u in ws['users'] if u['id'] == 'u-manager').update(identity_app_id='app1', bootstrap_admin=True)
        ws['source_connection'] = {'enabled': True, 'actor_id': 'u-manager', 'interval_seconds': 300}
        def snapshot(rows): return {'configured': True, 'status': 'ready', 'last_sync': clock[0], 'message': 'success', 'tables': [{'table_id': 'confirmation', 'status': 'ready'}], 'records': deepcopy(rows)}
        with sessions.begin() as db:
            row = WorkspaceRow(id=WID, version=ws['version'], data={}); db.add(row); db.flush(); row.data = storage.save(db, BusinessRow, WID, ws)
            db.add(CacheRow(id=WID, data=snapshot(initial)))
            db.add(PersonRow(organization_id=WID, person_id='u-manager', data=deepcopy(next(u for u in ws['users'] if u['id'] == 'u-manager'))))
            rows = db.scalar(select(func.count()).select_from(BusinessRow))
        cfg = {'LARK_APP_ID': 'app1', 'LARK_WORKER_IDENTITY': 'application', 'LARK_WORKER_ORGANIZATION': 'tenant', 'LARK_ALLOWED_TENANTS': 'tenant'}
        current = {'rows': initial}
        service = SourceSyncService(sessions, WorkspaceRow, BusinessRow, PersonRow, AuthRow, CacheRow, cfg, fetcher=lambda token: snapshot(current['rows']))
        spent, held = {}, []
        for name in WRAPPED:
            original = getattr(storage, name)
            def wrapper(*a, _o=original, _n=name, **k):
                started = time.perf_counter()
                try: return _o(*a, **k)
                finally: spent[_n] = spent.get(_n, 0) + time.perf_counter() - started
            setattr(storage, name, wrapper)
        begin = sessions.begin
        class Timed:
            def __init__(self): self.context = begin()
            def __enter__(self): self.started = time.perf_counter(); return self.context.__enter__()
            def __exit__(self, *a):
                try: return self.context.__exit__(*a)
                finally: held.append(time.perf_counter() - self.started)
        sessions.begin = lambda *a, **k: Timed()

        def minutes(n): clock[0] = f'2026-09-27T{10 + n // 60:02d}:{n % 60:02d}:00+08:00'
        def measure(step, runs):
            samples = []
            for i in range(runs):
                spent.clear(); held.clear()
                started = time.perf_counter(); result = step(i); total = time.perf_counter() - started
                samples.append({'total_ms': total * 1000, 'lock_held_ms': max(held) * 1000 if held else 0,
                                **{k + '_ms': v * 1000 for k, v in spent.items()}, 'result': result})
            return samples
        minute = [1]
        def tick(): minute[0] += 1; minutes(minute[0])
        report = {'label': label, 'database': 'sqlite' if target == 'sqlite' else 'postgresql', 'projects': projects, 'business_rows': rows, 'runs': repeats, 'scenarios': {}}
        scenarios = {}
        tick(); service.sync(WID, None, skip_unchanged=True)  # first import is not measured
        def failure(i): tick(); service.failure(WID, 'Lark 暫時無法連線'); return 'failed'
        def unchanged(i):
            tick(); service.sync(WID, None, skip_unchanged=True)
            return 'ok'
        def changed(i):
            tick(); current['rows'] = source_records(projects, 14, status='已完工' if i % 2 == 0 else '執行中')
            service.sync(WID, None, skip_unchanged=True)
            with sessions() as db:
                return next(r.data.get('source_status') for r in db.scalars(select(BusinessRow).where(BusinessRow.kind == 'projects')) if r.data.get('code') == 'C115000')
        scenarios['failure'] = measure(failure, repeats)
        scenarios['apply_unchanged'] = measure(unchanged, repeats)
        scenarios['apply_changed'] = measure(changed, repeats)
        for name, samples in scenarios.items():
            if name == 'apply_changed': assert {s['result'] for s in samples} == {'已完工', '執行中'}, 'the changed snapshot was not applied'
            keys = sorted({k for s in samples for k in s if k != 'result'})
            report['scenarios'][name] = {k: {'median': round(statistics.median(s.get(k, 0) for s in samples), 1),
                                             'min': round(min(s.get(k, 0) for s in samples), 1), 'max': round(max(s.get(k, 0) for s in samples), 1)} for k in keys}
        return report
    finally:
        drop()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default='sqlite')
    parser.add_argument('--projects', type=int, default=420)
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--label', default='run')
    parser.add_argument('--out')
    args = parser.parse_args()
    report = run(args.db, args.projects, args.repeats, args.label)
    if args.out: Path(args.out).write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(f"{report['label']} {report['database']} projects={report['projects']} rows={report['business_rows']} runs={report['runs']} (median ms)")
    columns = ('total_ms', 'lock_held_ms', 'load_ms', 'save_ms', 'load_partial_ms', 'save_collections_ms')
    print(f"{'scenario':18}" + ''.join(f'{c[:-3]:>20}' for c in columns))
    for name, stats in report['scenarios'].items():
        print(f'{name:18}' + ''.join(f"{stats.get(c, {}).get('median', 0):20.1f}" for c in columns))


if __name__ == '__main__':
    main()
