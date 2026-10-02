"""Local-only baseline on copied evidence. Never opens the live database or Lark."""
import argparse
from collections import defaultdict, Counter
from copy import deepcopy
from datetime import datetime, timezone
import functools
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import statistics
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backup', required=True, help='Previously restored private SQLite backup')
    parser.add_argument('--source-cache', required=True)
    parser.add_argument('--runs', type=int, default=3)
    args = parser.parse_args()
    backup = Path(args.backup).resolve(); cache = Path(args.source_cache).resolve()
    runtime = (ROOT / '.runtime').resolve()
    if not backup.is_relative_to(runtime) or not cache.is_relative_to(runtime):
        raise SystemExit('Only private evidence under .runtime is accepted')
    if backup == (ROOT / 'backend/workspace.db').resolve():
        raise SystemExit('Live database is forbidden')
    evidence_hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in (backup, cache)}
    target = runtime / ('performance-baseline-' + uuid.uuid4().hex[:8]); target.mkdir()
    files = ['backend/app.py', 'backend/storage.py', 'backend/policy.py', 'backend/operations.py',
             'backend/jobs.py', 'backend/workflow.py', 'backend/node_skip.py',
             'backend/v4_sources.py', 'frontend/src/App.tsx', 'frontend/src/api.ts']
    code_hashes = {}
    for name in files:
        dest = target / 'code' / name; dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, dest)
        code_hashes[name] = hashlib.sha256(dest.read_bytes()).hexdigest()
    # Importing backend.app creates its default app; isolate even that bootstrap.
    for key in list(os.environ):
        if key.startswith('LARK_'): os.environ.pop(key)
    os.environ.update(DATABASE_URL='sqlite:///' + str(target / 'bootstrap.sqlite'),
        UPLOAD_DIR=str(target / 'uploads'), APP_ENV='development', DEMO_MODE='false',
        SESSION_SECRET='isolated-performance-measurement-only')
    import sys
    sys.path.insert(0, str(ROOT))
    mod = importlib.import_module('backend.app')
    from backend import storage
    from backend.policy import upgrade
    from backend.sources import import_sources
    from backend.seed import seed
    from fastapi.testclient import TestClient
    from sqlalchemy import select, event
    metrics = defaultdict(lambda: {'calls': 0, 'ms': 0.0})
    def wrap(label, fn):
        @functools.wraps(fn)
        def measured(*a, **kw):
            start = time.perf_counter()
            try: return fn(*a, **kw)
            finally:
                metrics[label]['calls'] += 1
                metrics[label]['ms'] += (time.perf_counter() - start) * 1000
        return measured
    storage.load = wrap('storage_load', storage.load)
    storage.save = wrap('storage_save', storage.save)
    for name in ('upgrade', 'project_summary', 'review_hash', 'apply_action', 'apply_operation'):
        setattr(mod, name, wrap(name, getattr(mod, name)))
    records = json.loads(cache.read_text(encoding='utf-8-sig'))['records']
    reports = []
    for profile in ('migrated_backup', 'source_replay_current', 'archive_detached_experiment'):
        dbfile = target / (profile + '.sqlite'); shutil.copy2(backup, dbfile)
        app = mod.create_app({'DATABASE_URL': 'sqlite:///' + str(dbfile)})
        cells = set()
        for route in app.routes:
            fn = getattr(route, 'endpoint', None)
            if not getattr(fn, '__closure__', None): continue
            for name, cell in zip(fn.__code__.co_freevars, fn.__closure__):
                if name in ('identity', 'load', 'public_ws', 'persist_mutation') and id(cell) not in cells:
                    cells.add(id(cell)); cell.cell_contents = wrap(name, cell.cell_contents)
        with app.state.sessions.begin() as db:
            candidates = [r for r in db.scalars(select(mod.WorkspaceRow)) if r.id.startswith('lark-')]
            row = max(candidates, key=lambda r: len(storage.load(db, mod.BusinessRow, r)['projects']))
            wid = row.id; state = upgrade(storage.load(db, mod.BusinessRow, row))
            users = deepcopy(state['users'])
            if profile == 'source_replay_current':
                state = upgrade(seed(True)); state['users'] = users
                import_sources(state, records)
            elif profile == 'archive_detached_experiment':
                state.pop('migration_archive', None)
            state['environment'] = 'production'
            actor = next(u for u in users if u.get('active', True))
            actor['role'] = 'manager'  # Local fixture only; exact preconditions recorded below.
            state['users'] = users
            p = next(p for p in state['projects'] if any(n['tasks'] for n in p['nodes']))
            p['pm_id'] = actor['id']
            n = next(n for n in p['nodes'] if any(t['status'] != 'superseded' for t in n['tasks']))
            task = next(t for t in n['tasks'] if t['status'] != 'superseded')
            scope = {'project_id': p['id'], 'node_id': n['id'], 'task_id': task['id']}
            state['version'] = row.version
            row.data = storage.save(db, mod.BusinessRow, wid, state)
            person = db.get(mod.PersonRow, (wid, actor['id']))
            if person: person.data = deepcopy(actor)
            else: db.add(mod.PersonRow(organization_id=wid, person_id=actor['id'], data=deepcopy(actor)))
            db.add(mod.AuthRow(id='benchmark-session', data={'wid': wid,
                'expires': time.time() + 3600, 'access_token': 'never-used'}))
            counts = {'projects': len(state['projects']), 'intakes': sum(p.get('case_type') == 'intake' for p in state['projects']),
                      'nodes': sum(len(p['nodes']) for p in state['projects']),
                      'tasks': sum(len(n['tasks']) for p in state['projects'] for n in p['nodes']),
                      'archive_json_bytes': len(json.dumps(state.get('migration_archive', {}), ensure_ascii=False).encode()),
                      'unmatched_daily': len(state.get('daily_unmatched', [])), 'users': len(users)}
        sql = Counter()
        def sql_call(conn, cursor, statement, params, context, many):
            sql[statement.lstrip().split(' ', 1)[0].upper()] += 1
        event.listen(app.state.engine, 'before_cursor_execute', sql_call)
        client = TestClient(app)
        client.cookies.set('meegle_session', app.state.signer.dumps(
            {'mode': 'lark', 'uid': actor['id'], 'wid': wid, 'sid': 'benchmark-session'}))
        # Warm caches and one-time identity initialization before the reported samples.
        warm = client.get('/api/workspace'); assert warm.status_code == 200
        version = warm.json()['version']; samples = []
        for operation in ('session', 'workspace', 'project_list', 'comment_add', 'task_update'):
            for repeat in range(args.runs):
                metrics.clear(); sql.clear(); start = time.perf_counter()
                if operation in ('comment_add', 'task_update'):
                    payload = {'body': 'LOCAL BENCHMARK ONLY'} if operation == 'comment_add' else {'description': 'LOCAL BENCHMARK ' + str(repeat)}
                    response = client.post('/api/actions', json={'action': operation, 'version': version,
                        'request_id': uuid.uuid4().hex, **scope, 'payload': payload})
                else:
                    response = client.get({'session': '/api/session', 'workspace': '/api/workspace',
                                           'project_list': '/api/projects?limit=30'}[operation])
                total = (time.perf_counter() - start) * 1000
                assert response.status_code == 200, (operation, response.status_code)
                parse_start = time.perf_counter(); body = response.json()
                parse_ms = (time.perf_counter() - parse_start) * 1000
                if 'version' in body: version = body['version']
                samples.append({'operation': operation, 'total_ms': round(total, 3),
                    'client_json_parse_ms': round(parse_ms, 3), 'response_bytes_decoded': len(response.content),
                    'response_bytes_compressed': int(response.headers.get('content-length', '0')),
                    'sql_calls': dict(sql), 'timers': deepcopy(dict(metrics))})
        aggregates = {}
        for operation in sorted({s['operation'] for s in samples}):
            selected = [s for s in samples if s['operation'] == operation]
            aggregates[operation] = {'median_ms': round(statistics.median(s['total_ms'] for s in selected), 2),
                'min_ms': round(min(s['total_ms'] for s in selected), 2),
                'max_ms': round(max(s['total_ms'] for s in selected), 2),
                'decoded_bytes': selected[-1]['response_bytes_decoded'],
                'compressed_bytes': selected[-1]['response_bytes_compressed'],
                'last_sql_calls': selected[-1]['sql_calls'],
                'median_timers': {k: {'calls': v['calls'], 'ms': round(statistics.median(s['timers'].get(k, {}).get('ms', 0) for s in selected), 2)}
                                  for k, v in selected[-1]['timers'].items()}}
        reports.append({'profile': profile, 'counts': counts, 'operations': aggregates, 'samples': samples})
        client.close(); app.state.engine.dispose()
    for path, expected in evidence_hashes.items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected
    report = {'at': datetime.now(timezone.utc).isoformat(), 'local_only': True, 'live_database_modified': False,
              'external_io': False, 'method': 'TestClient + copied SQLite; warm-cache sequential requests; inclusive overlapping component timers',
              'fixture_changes': 'Only clones: manager role + selected project PM; local auth receipt; source replay profile reconstructs data from cached sources.',
              'runs_per_operation': args.runs, 'evidence_hashes': evidence_hashes,
              'source_code_hashes': code_hashes, 'profiles': reports}
    output = target / 'report.json'; output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'report': str(output.relative_to(ROOT)), 'profiles': [
        {'profile': r['profile'], 'counts': r['counts'], 'operations': r['operations']} for r in reports]}, ensure_ascii=False))


if __name__ == '__main__': main()
