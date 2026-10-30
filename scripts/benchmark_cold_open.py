"""Time the case-open reads against a workspace at roughly staging scale (local sqlite, synthetic filler).

Run from a repository root (base or branch): PYTHONPATH=. python scripts/benchmark_cold_open.py [iterations]
COLD runs clear every in-process cache that exists in that checkout (the shared collection reads and any
functools caches under backend.*) before each measurement. WARM runs follow a priming pass and clear nothing.
The same script runs on a base checkout that has no shared cache, where cold and warm coincide.
Not reset: SQLite's page cache and the OS file cache, so "cold" is a cold process cache over a hot database.
Absolute times are this machine's; compare base against branch on the same machine, never against staging.

The run FAILS (exit 1, "BENCHMARK FAILED: ...") if any of the five endpoints is missing, answers non-2xx or
raises, in a serial read or in any thread of a burst; a burst must return exactly the five expected endpoints.
"""
import json, statistics, sys, tempfile, threading, time
from copy import deepcopy
import pathlib

ENDPOINTS = ('project', 'progress', 'sop-tasks', 'sop-assignees', 'home-panels')


class BenchmarkFailure(Exception):
    pass


def flow_for(pid):
    return {'project': f'/api/projects/{pid}', 'progress': f'/api/projects/{pid}/progress',
            'sop-tasks': f'/api/projects/{pid}/sop-tasks', 'sop-assignees': f'/api/projects/{pid}/sop-assignees',
            'home-panels': '/api/home-panels?panel=assigned&scope=mine&limit=25'}


def require_flow(flow):
    if tuple(flow) != ENDPOINTS:
        raise BenchmarkFailure(f'the flow must be exactly {list(ENDPOINTS)}, got {list(flow)}')


def read(client, name, path):
    started = time.perf_counter()
    try:
        response = client.get(path)
    except Exception as error:
        raise BenchmarkFailure(f'{name} ({path}) raised {error!r}') from error
    if not 200 <= response.status_code < 300:
        raise BenchmarkFailure(f'{name} ({path}) answered HTTP {response.status_code}')
    return round((time.perf_counter() - started) * 1000), response


def burst(client, flow):
    require_flow(flow)
    results, failures = {}, []

    def run(name, path):
        try:
            results[name] = read(client, name, path)[0]
        except BaseException as error:
            failures.append(f'{name}: {error}')
    started = time.perf_counter()
    threads = [threading.Thread(target=run, args=item) for item in flow.items()]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    if failures:
        raise BenchmarkFailure('burst request failed: ' + '; '.join(sorted(failures)))
    if sorted(results) != sorted(ENDPOINTS):
        raise BenchmarkFailure(f'burst answered {sorted(results)}, expected {sorted(ENDPOINTS)}')
    return round((time.perf_counter() - started) * 1000), results


def spread(values):
    return {'min': min(values), 'median': statistics.median(values), 'max': max(values), 'n': len(values)}


def measure(client, flow, iterations, reset):
    require_flow(flow)
    cleared = reset()
    for name, path in flow.items(): read(client, name, path)
    result = {'iterations': iterations, 'caches_cleared_per_cold_run': cleared}
    result['cold_serial_ms'] = {name: spread([(reset(), read(client, name, path)[0])[1] for _ in range(iterations)]) for name, path in flow.items()}
    for name, path in flow.items(): read(client, name, path)
    result['warm_serial_ms'] = {name: spread([read(client, name, path)[0] for _ in range(iterations)]) for name, path in flow.items()}
    cold = []
    for _ in range(iterations):
        reset(); cold.append(burst(client, flow))
    result['cold_burst_wall_ms'] = spread([wall for wall, _ in cold])
    result['cold_burst_slowest_read_ms'] = spread([max(per.values()) for _, per in cold])
    burst(client, flow)
    warm = [burst(client, flow) for _ in range(iterations)]
    result['warm_burst_wall_ms'] = spread([wall for wall, _ in warm])
    result['warm_burst_slowest_read_ms'] = spread([max(per.values()) for _, per in warm])
    return result


def reset_caches():
    from backend import storage
    if hasattr(storage, 'invalidate_shared_reads'): storage.invalidate_shared_reads(None)
    cleared = 0
    for name, module in list(sys.modules.items()):
        if name.startswith('backend.') and module is not None:
            for value in list(vars(module).values()):
                if callable(getattr(value, 'cache_clear', None)):
                    value.cache_clear(); cleared += 1
    return cleared


def dense(size):
    out = []; n = 0; i = 0
    while n < size:
        item = {'id': f'r{i}', 'name': f'名稱 {i}', 'n': i, 'f': i / 7, 'ok': bool(i % 2), 'none': None, 'tags': ['a', 'b', i], 'sub': {'k': i, 'v': f'val{i}', 'z': [i, i + 1]}}
        out.append(item); n += len(json.dumps(item, ensure_ascii=False)); i += 1
    return out

def build_fixture():
    from sqlalchemy import select
    from backend.test_sop_local_case import CAPS
    from backend.test_sop_quotes import harness, WID
    from backend.app import BusinessRow
    K = 3
    d = pathlib.Path(tempfile.mkdtemp(prefix='cold-open-')); (d/'files').mkdir()
    caps = {**CAPS, 'u-manager': ['sop_task_read', 'sop_task_import', 'sop_task_work']}
    app, client, signin, ids = harness(d, caps, LOCAL_CASE_CREATION_ENABLED='true', INDEX_TABLES_ENABLED='true', WORKSPACE_SHELL_ENABLED='true')
    PID = ids['intake']
    with app.state.sessions.begin() as db:
        rows = list(db.scalars(select(BusinessRow).where(BusinessRow.workspace_id == WID)))
        byk = {}
        for r in rows: byk.setdefault(r.kind, []).append(r)
        print('kinds', {k: len(v) for k, v in byk.items() if k in ('source_quotes', 'contract_items', 'source_confirmations', 'projects', 'users')}, file=sys.stderr)
        def clone(kind, n, size, mutate):
            base = byk[kind][0]
            for i in range(n):
                data = deepcopy(base.data); mutate(data, i); data['pad'] = dense(size * K)
                db.add(BusinessRow(workspace_id=WID, kind=kind, entity_id=f'scale-{kind}-{i}', parent_id='', ordinal=10000 + i, data=data))
        def q(data, i):
            data['id'] = f'scale-q-{i}'
            if isinstance(data.get('source_identity'), dict): data['source_identity'] = {**data['source_identity'], 'record_id': f'scale-q-{i}'}
        clone('source_quotes', 420, 21000, q)
        if 'contract_items' in byk: clone('contract_items', 560, 13000, lambda d, i: d.update(id=f'scale-ci-{i}', project_id=None))
        else:
            db.add_all([BusinessRow(workspace_id=WID, kind='contract_items', entity_id=f'scale-ci-{i}', parent_id='', ordinal=i, data={'id': f'scale-ci-{i}', 'project_id': None, 'pad': dense(13000 * K)}) for i in range(560)])
        db.add_all([BusinessRow(workspace_id=WID, kind='source_confirmations', entity_id=f'scale-sc-{i}', parent_id='', ordinal=i, data={'id': f'scale-sc-{i}', 'project_id': None, 'fields': {}, 'pad': dense(4000 * K)}) for i in range(210)])
        # one-hundred project headers with nodes so full-workspace loads cost something
        base = byk['projects'][0]
        for i in range(400):
            data = deepcopy(base.data); data['id'] = f'scale-p-{i}'; data['code'] = f'S{i}'; data['name'] = f'scale {i}'; data['pad'] = dense(9000 * K)
            db.add(BusinessRow(workspace_id=WID, kind='projects', entity_id=data['id'], parent_id='', ordinal=20000 + i, data=data))
    signin('u-manager')
    return client, PID


def main(argv=None, build=build_fixture):
    argv = sys.argv[1:] if argv is None else argv
    iterations = int(argv[0]) if argv else 7
    try:
        client, pid = build()
        flow = flow_for(pid)
        print('COLD_OPEN', json.dumps(measure(client, flow, iterations, reset_caches), ensure_ascii=False))
        for name in ('project', 'progress', 'sop-tasks', 'sop-assignees'):
            reset_caches()
            print('COLD_PHASES', name, read(client, name, flow[name])[1].headers.get('server-timing'))
    except BenchmarkFailure as failure:
        print(f'BENCHMARK FAILED: {failure}', file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
