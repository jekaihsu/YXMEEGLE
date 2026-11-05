"""Time real /api/actions writes on a staging-sized workspace (SQLite or PostgreSQL).

Each scenario sends distinct, valid requests, checks every response and that the
workspace version advanced by exactly one, then reports the median over the runs.
Usage:
  python scripts/benchmark_write_paths.py --db sqlite --label before
  python scripts/benchmark_write_paths.py --db postgres://postgres@/postgres?host=/tmp/yxpg/sock&port=54329
"""
import argparse
import json
import statistics
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text, select, func  # noqa: E402

from backend import storage  # noqa: E402
from backend.app import create_app, WorkspaceRow, BusinessRow  # noqa: E402
from backend.write_world import WID, build_world, scenarios  # noqa: E402

WRAPPED = ('load', 'save', 'load_partial', 'save_partial', 'save_collections')
# Needs a control task still in progress, which the task_return scenario ends on the same cases.
SKIPPED = ('delivery_submit',)


def server_timing(response):
    parts = {}
    for item in response.headers.get('server-timing', '').split(','):
        name, _, duration = item.strip().partition(';dur=')
        if duration: parts[name] = float(duration)
    return parts


def make_database(target):
    if target == 'sqlite':
        return 'sqlite:///' + tempfile.mkdtemp() + '/bench.db', lambda: None
    admin = create_engine(target.replace('postgres://', 'postgresql+psycopg://'), isolation_level='AUTOCOMMIT')
    name = 'bench_' + uuid.uuid4().hex[:10]
    with admin.connect() as c: c.execute(text(f'create database {name}'))
    url = urlsplit(target.replace('postgres://', 'postgresql+psycopg://'))
    url = url._replace(path='/' + name).geturl()
    def drop():
        with admin.connect() as c: c.execute(text(f'drop database {name} with (force)'))
    return url, drop


def run(target, projects, repeats, label, only=()):
    url, drop = make_database(target)
    try:
        app = create_app({'DATABASE_URL': url, 'UPLOAD_DIR': tempfile.mkdtemp(), 'SESSION_SECRET': 'x' * 40, 'APP_ENV': 'development',
                          'DEMO_MODE': 'true', 'INDEX_TABLES_ENABLED': 'true', 'WORKSPACE_SHELL_ENABLED': 'true', 'FEATURE_CHANGE_EXTENSION': 'true'})
        world = build_world(projects)
        with app.state.sessions.begin() as db:
            from backend.models import WorkspaceRow as W
            row = W(id=WID, version=1, data=world); db.add(row); db.flush()
            row.data = storage.save(db, BusinessRow, WID, world)
            rows = db.scalar(select(func.count()).select_from(BusinessRow))
        client = TestClient(app)
        spent = {}
        for name in WRAPPED:
            original = getattr(storage, name, None)
            if original is None: continue
            def wrapper(*a, _o=original, _n=name, **k):
                started = time.perf_counter()
                try: return _o(*a, **k)
                finally: spent[_n] = spent.get(_n, 0) + time.perf_counter() - started
            setattr(storage, name, wrapper)
        held_transactions = []
        begin = app.state.sessions.begin
        class Timed:
            def __init__(self): self.context = begin()
            def __enter__(self): self.started = time.perf_counter(); return self.context.__enter__()
            def __exit__(self, *a):
                try: return self.context.__exit__(*a)
                finally: held_transactions.append(time.perf_counter() - self.started)
        app.state.sessions.begin = lambda *a, **k: Timed()
        report = {'label': label, 'database': 'sqlite' if target == 'sqlite' else 'postgresql', 'projects': projects, 'business_rows': rows, 'runs': repeats, 'scenarios': {}}
        for name, targets in scenarios(world, repeats).items():
            if name in SKIPPED or (only and name not in only): continue
            samples = []
            for user, fields in targets[:repeats]:
                client.cookies.set('meegle_session', app.state.signer.dumps({'mode': 'demo', 'uid': user, 'wid': WID}))
                with app.state.sessions() as db: version = db.get(WorkspaceRow, WID).version
                spent.clear(); held_transactions.clear()
                started = time.perf_counter()
                response = client.post('/api/actions', json={'action': name, 'version': version, 'request_id': uuid.uuid4().hex,
                                                             'project_id': fields.get('project_id'), 'node_id': fields.get('node_id'),
                                                             'task_id': fields.get('task_id'), 'payload': fields.get('payload', {})})
                total = time.perf_counter() - started
                assert response.status_code == 200, f'{name} failed: {response.status_code} {response.text[:200]}'
                with app.state.sessions() as db: assert db.get(WorkspaceRow, WID).version == version + 1, 'version did not advance by one'
                timing = server_timing(response)
                samples.append({'total_ms': total * 1000, 'mutate_ms': timing.get('mutate', 0), 'lock_held_ms': max(held_transactions) * 1000,
                                'partial': getattr(app.state, 'last_write', {}).get('path') == 'partial', 'bytes': len(response.content),
                                **{k + '_ms': v * 1000 for k, v in spent.items()}})
            paths = sorted({'partial' if s.pop('partial') else 'full' for s in samples})
            keys = sorted({k for s in samples for k in s})
            report['scenarios'][name] = {'paths': paths, **{k: {'median': round(statistics.median(s.get(k, 0) for s in samples), 1),
                                             'min': round(min(s.get(k, 0) for s in samples), 1),
                                             'max': round(max(s.get(k, 0) for s in samples), 1)} for k in keys}}
        return report
    finally:
        drop()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default='sqlite', help="'sqlite' or a PostgreSQL URL of a server where databases may be created")
    parser.add_argument('--projects', type=int, default=420)
    parser.add_argument('--repeats', type=int, default=7)
    parser.add_argument('--label', default='run')
    parser.add_argument('--only', default='', help='comma separated scenario names')
    parser.add_argument('--out')
    args = parser.parse_args()
    report = run(args.db, args.projects, args.repeats, args.label, tuple(x for x in args.only.split(',') if x))
    if args.out: Path(args.out).write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(f"{report['label']} {report['database']} projects={report['projects']} rows={report['business_rows']} runs={report['runs']} (median ms)")
    columns = ('total_ms', 'mutate_ms', 'lock_held_ms', 'load_ms', 'save_ms', 'load_partial_ms', 'save_partial_ms')
    print(f"{'scenario':16}" + ''.join(f'{c[:-3]:>14}' for c in columns))
    for name, stats in report['scenarios'].items():
        print(f'{name:16}' + ''.join(f"{stats.get(c, {}).get('median', 0):14.1f}" for c in columns) + '  ' + '+'.join(stats['paths']))


if __name__ == '__main__':
    main()
