"""Time the case-open reads against a workspace at roughly staging scale (local sqlite, synthetic filler).

Run from the repository root: PYTHONPATH=. python scripts/benchmark_cold_open.py
Prints each read serially (first and warm), then the five reads of a cold case open fired at once, then the
server-side phase timings of each case read. Absolute times are this machine's; compare runs on the same machine.
"""
import json, sys, time, threading, pathlib, shutil, tempfile
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
from sqlalchemy import event
rowsread = {'n': 0}
@event.listens_for(app.state.engine, 'before_cursor_execute')
def _c(conn, cur, st, params, ctx, many):
    if 'business_records' in st: rowsread['n'] += 1
with app.state.sessions() as db:
    print('DBROWS', {k: db.execute(text("select count(*), sum(length(data)) from business_records where kind=:k"), {'k': k}).fetchone() for k in ('source_quotes','contract_items','source_confirmations','projects')}, 'schema', db.get(WorkspaceRow, WID).data.get('storage_schema'), file=sys.stderr)
r0 = client.get(f'/api/projects/{PID}/sop-tasks'); print('SOP', r0.status_code, len(r0.content), 'br_queries', rowsread['n'], file=sys.stderr)
def timed(path):
    t = time.perf_counter(); r = client.get(path); return round((time.perf_counter() - t) * 1000), r.status_code
flow = [f'/api/projects/{PID}', f'/api/projects/{PID}/progress', f'/api/projects/{PID}/sop-tasks', f'/api/projects/{PID}/sop-assignees', '/api/home-panels?panel=assigned&scope=mine&limit=25']
res = {'serial_first': {p.split(PID)[-1] or '/project': timed(p) for p in flow}}
res['serial_warm'] = {p.split(PID)[-1] or '/project': timed(p) for p in flow}
out = {}
def run(p): out[p] = timed(p)
t0 = time.perf_counter(); th = [threading.Thread(target=run, args=(p,)) for p in flow]
[t.start() for t in th]; [t.join() for t in th]
res['cold_burst'] = {'wall_ms': round((time.perf_counter() - t0) * 1000), 'per': {p.split(PID)[-1] or '/project': v for p, v in out.items()}}
print('COLD_OPEN', json.dumps(res, ensure_ascii=False))

for path in flow[:4]:
    client.get(path); r = client.get(path)
    print('PHASES', path.split(PID)[-1] or '/project', r.headers.get('server-timing'))
