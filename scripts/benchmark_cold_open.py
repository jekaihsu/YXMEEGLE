"""Time the case-open reads against a workspace at roughly staging scale (local sqlite, synthetic filler).

Run from a repository root (base or branch): PYTHONPATH=. python scripts/benchmark_cold_open.py [iterations]
COLD runs clear every in-process cache that exists in that checkout (the shared collection reads and any
functools caches under backend.*) before each measurement. WARM runs follow a priming pass and clear nothing.
The same script runs on a base checkout that has no shared cache, where cold and warm coincide.
Not reset: SQLite's page cache and the OS file cache, so "cold" is a cold process cache over a hot database.
Absolute times are this machine's; compare base against branch on the same machine, never against staging.
"""
import json, sys, time, threading, pathlib, shutil, tempfile, statistics
from copy import deepcopy
from sqlalchemy import select, text
from backend.test_sop_local_case import CAPS
from backend.test_sop_quotes import harness, WID
from backend import storage
from backend.app import BusinessRow, WorkspaceRow
def dense(size):
    out = []; n = 0; i = 0
    while n < size:
        item = {'id': f'r{i}', 'name': f'名稱 {i}', 'n': i, 'f': i / 7, 'ok': bool(i % 2), 'none': None, 'tags': ['a', 'b', i], 'sub': {'k': i, 'v': f'val{i}', 'z': [i, i + 1]}}
        out.append(item); n += len(json.dumps(item, ensure_ascii=False)); i += 1
    return out
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
ws = None
signin('u-manager')
ITERATIONS = int(sys.argv[1]) if len(sys.argv) > 1 else 7
FLOW = [f'/api/projects/{PID}', f'/api/projects/{PID}/progress', f'/api/projects/{PID}/sop-tasks', f'/api/projects/{PID}/sop-assignees', '/api/home-panels?panel=assigned&scope=mine&limit=25']
NAME = {FLOW[0]: 'project', FLOW[1]: 'progress', FLOW[2]: 'sop-tasks', FLOW[3]: 'sop-assignees', FLOW[4]: 'home-panels'}


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


def timed(path):
    t = time.perf_counter(); r = client.get(path); assert r.status_code == 200, (path, r.status_code)
    return round((time.perf_counter() - t) * 1000)


def burst():
    out = {}
    def run(p): out[p] = timed(p)
    t0 = time.perf_counter(); threads = [threading.Thread(target=run, args=(p,)) for p in FLOW]
    [t.start() for t in threads]; [t.join() for t in threads]
    return round((time.perf_counter() - t0) * 1000), out


def spread(values):
    return {'min': min(values), 'median': statistics.median(values), 'max': max(values), 'n': len(values)}


cleared = reset_caches()
for path in FLOW: timed(path)
res = {'iterations': ITERATIONS, 'caches_cleared_per_cold_run': cleared}
res['cold_serial_ms'] = {NAME[p]: spread([(reset_caches(), timed(p))[1] for _ in range(ITERATIONS)]) for p in FLOW}
for path in FLOW: timed(path)
res['warm_serial_ms'] = {NAME[p]: spread([timed(p) for _ in range(ITERATIONS)]) for p in FLOW}
cold = []
for _ in range(ITERATIONS):
    reset_caches(); cold.append(burst())
res['cold_burst_wall_ms'] = spread([w for w, _ in cold])
res['cold_burst_slowest_read_ms'] = spread([max(per.values()) for _, per in cold])
burst()
warm = [burst() for _ in range(ITERATIONS)]
res['warm_burst_wall_ms'] = spread([w for w, _ in warm])
res['warm_burst_slowest_read_ms'] = spread([max(per.values()) for _, per in warm])
print('COLD_OPEN', json.dumps(res, ensure_ascii=False))
for path in FLOW[:4]:
    reset_caches(); r = client.get(path)
    print('COLD_PHASES', NAME[path], r.headers.get('server-timing'))
