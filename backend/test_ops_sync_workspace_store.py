"""Evidence for the version-CAS OpsStore over the real `workspaces` row (isolated SQLite files, synthetic data).

SQLite only. PostgreSQL is UNTESTED here: there is no PostgreSQL in this environment, and no claim is made for it.
"""
import json
import os
import signal
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from . import app as app_module
from .ops_sync import adapter as A
from .ops_sync import values as V
from .ops_sync.clock import FakeClock
from .ops_sync.engine import OpsEngine
from .ops_sync.store import JsonFileStore
from .ops_sync.flags import OpsFlags
from .ops_sync.store import StorageBlocked, StorageBusy
from .ops_sync.testing import (STORE_BARRIERS, STORE_LANDED, WID, app_style_write, env, raw_row, seed_workspace,
                               sqlite_sessions)
from .ops_sync.workspace_store import BARRIERS, WorkspaceStore, ops_store_factory

ROOT = Path(__file__).resolve().parent.parent
E = 'case_test_1'


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / 'ws.db')
    seed_workspace(path, {'version': 1, 'users': [{'id': 'u1'}], 'storage_schema': 2, 'sentinel': {'keep': '日本語 🚀'}})
    return path


def store_for(path, **kw):
    return WorkspaceStore(sqlite_sessions(path), WID, **kw)


def version_of(path, wid=WID):
    return raw_row(path, wid)[0]


def data_of(path):
    return json.loads(raw_row(path)[1])


def competing_write(path, key='rival'):
    return lambda attempt: None if attempt != 1 else app_style_write(sqlite_sessions(path), lambda d: d.__setitem__(key, attempt))


# -- fail closed first -----------------------------------------------------------------------------------------
def test_flag_off_has_no_store_and_flag_on_builds_one(db):
    assert BARRIERS == STORE_BARRIERS['workspace'] and WorkspaceStore.durable is True
    sessions = sqlite_sessions(db)
    assert ops_store_factory(OpsFlags(), sessions) is None
    assert ops_store_factory(OpsFlags(ops_sync=True, mock_ui=True), sessions) is None      # only the authoritative flag counts
    factory = ops_store_factory(OpsFlags(lark_authoritative_ops=True), sessions)
    store = factory(WID)
    assert isinstance(store, WorkspaceStore) and store.durable and store.wid == WID


def test_fn_exception_commits_nothing_and_keeps_the_version(db):
    store = store_for(db)
    store.transact(lambda ns: ns.update(a=1))
    before = raw_row(db)

    def boom(ns):
        ns['a'] = 2
        ns['b'] = 3
        raise RuntimeError('boom')
    with pytest.raises(RuntimeError):
        store.transact(boom)
    assert raw_row(db) == before and store.snapshot()['a'] == 1 and 'b' not in store.snapshot()


@pytest.mark.parametrize('barrier', BARRIERS)
def test_injected_failure_mid_transaction_is_commit_or_nothing(db, barrier):
    store = store_for(db)
    store.transact(lambda ns: ns.update(a=1))
    before, committed = raw_row(db), barrier == 'committed'

    def explode(name):
        if name == barrier:
            raise OSError('disk full')
    failing = store_for(db, hook=explode)
    with pytest.raises(OSError):
        failing.transact(lambda ns: ns.update(a=2, b=[1, 2]))
    if committed:                      # the failure came after COMMIT: the write is durable though never acknowledged
        assert version_of(db) == before[0] + 1 and store.snapshot()['a'] == 2
    else:
        assert raw_row(db) == before and store.snapshot() == {'a': 1, '_commit_seq': 1}
    assert data_of(db)['sentinel'] == {'keep': '日本語 🚀'} and data_of(db)['users'] == [{'id': 'u1'}]


def test_missing_row_fails_closed_and_creates_nothing(tmp_path):
    path = str(tmp_path / 'empty.db')
    seed_workspace(path, wid='some-other-workspace')
    store = store_for(path)
    with pytest.raises(StorageBlocked):
        store.transact(lambda ns: ns.update(a=1))
    with pytest.raises(StorageBlocked):
        store.snapshot()
    with sqlite3.connect(path) as conn:
        assert [r[0] for r in conn.execute('select id from workspaces')] == ['some-other-workspace']


@pytest.mark.parametrize('damaged', ['null', '[]', '"text"', '7', '{"ops_sync": []}', '{"ops_sync": "x"}', '{"ops_sync": null}',
                                     '{not json', ''])
def test_corrupt_row_data_fails_closed_without_reset(db, damaged):
    with sqlite3.connect(db) as conn:
        conn.execute('update workspaces set data=?', (damaged,))
    before = raw_row(db)
    store = store_for(db)
    called = []
    with pytest.raises(StorageBlocked):
        store.transact(lambda ns: called.append(1) or ns.update(a=1))
    with pytest.raises(StorageBlocked):
        store.snapshot()
    assert raw_row(db) == before and not called                 # evidence preserved, fn never ran against garbage


@pytest.mark.parametrize('bad_version', ['1.5', "'x'"])
def test_non_integer_row_version_fails_closed(db, bad_version):
    with sqlite3.connect(db) as conn:
        conn.execute(f'update workspaces set version={bad_version}')
    before = raw_row(db)
    with pytest.raises(StorageBlocked):
        store_for(db).transact(lambda ns: ns.update(a=1))
    assert raw_row(db) == before


def test_unserialisable_state_commits_nothing(db):
    before = raw_row(db)
    with pytest.raises(TypeError):
        store_for(db).transact(lambda ns: ns.update(raw_marker=V.CLEAR))     # markers must be tag-encoded, never raw
    assert raw_row(db) == before


# -- CAS ----------------------------------------------------------------------------------------------------------
def test_unchanged_transaction_writes_nothing_and_does_not_bump_the_version(db):
    before = raw_row(db)
    store = store_for(db)
    assert store.transact(lambda ns: ns.get('missing', 'dflt')) == 'dflt'
    assert store.snapshot() == {} and raw_row(db) == before and 'ops_sync' not in data_of(db)


def test_commit_bumps_version_and_mirrors_it_into_data_and_preserves_every_other_key(db):
    start = version_of(db)
    before = data_of(db)
    store_for(db).transact(lambda ns: ns.update(commands={'c1': {'state': 'queued'}}))
    after = data_of(db)
    assert version_of(db) == start + 1 and after['version'] == start + 1          # the app serves data['version'] to clients
    assert {k: v for k, v in after.items() if k not in ('ops_sync', 'version')} == {k: v for k, v in before.items() if k != 'version'}
    assert after['ops_sync']['commands'] == {'c1': {'state': 'queued'}} and after['ops_sync']['_commit_seq'] == 1


def test_cas_miss_reruns_fn_against_the_fresh_state_and_loses_nothing(db):
    calls = []

    def fn(ns):
        calls.append(dict(ns.get('seen', {})))
        ns.setdefault('seen', {})['n'] = len(calls)
    store = store_for(db, hook=lambda name: competing_write(db)(len(calls)) if name == 'before_update' else None)
    start = version_of(db)
    store.transact(fn)
    assert len(calls) == 2 and data_of(db)['rival'] == 1 and data_of(db)['ops_sync']['seen'] == {'n': 2}
    assert version_of(db) == start + 2 and data_of(db)['version'] == start + 2


def test_cas_exhaustion_is_storage_busy_and_commits_nothing(db):
    rivals = []

    def hook(name):
        if name == 'before_update':
            app_style_write(sqlite_sessions(db), lambda d: d.__setitem__(f'rival_{len(rivals)}', 1))
            rivals.append(1)
    calls = []
    store = store_for(db, hook=hook, max_attempts=4, backoff=0)
    with pytest.raises(StorageBusy):
        store.transact(lambda ns: calls.append(1) or ns.update(a=1))
    assert len(calls) == 4 and len(rivals) == 4
    data = data_of(db)
    assert 'ops_sync' not in data and all(f'rival_{i}' in data for i in range(4))      # the rivals are intact


def test_app_style_writer_is_not_clobbered_by_an_ops_write_and_vice_versa(db):
    sessions = sqlite_sessions(db)
    store = store_for(db)
    store.transact(lambda ns: ns.update(commands={'c1': 1}))
    # direction 1: the app read before the ops commit; its CAS must miss (its 409) rather than erase ops_sync

    def interleave(attempt):
        if attempt == 1:
            store.transact(lambda ns: ns['commands'].update(c2=2))
    attempts = app_style_write(sessions, lambda d: d.__setitem__('app_key', 1), before_cas=interleave)
    assert attempts == 2                                                   # first attempt lost the CAS, second re-read
    data = data_of(db)
    assert data['app_key'] == 1 and data['ops_sync']['commands'] == {'c1': 1, 'c2': 2}
    # direction 2: ops read first; the app commits in between; the ops write retries over the app's state
    fired = []

    def rival(name):
        if name == 'before_update' and not fired:
            fired.append(1)
            app_style_write(sessions, lambda d: d.__setitem__('app_key', 2))
    store2 = store_for(db, hook=rival)
    store2.transact(lambda ns: ns['commands'].update(c3=3))
    data = data_of(db)
    assert data['app_key'] == 2 and data['ops_sync']['commands'] == {'c1': 1, 'c2': 2, 'c3': 3}
    assert data['version'] == version_of(db)


def test_ops_namespace_survives_real_app_writes_and_stale_app_clients_get_a_409(tmp_path):
    from fastapi.testclient import TestClient
    app = app_module.create_app({'DATABASE_URL': f'sqlite:///{tmp_path}/app.db', 'UPLOAD_DIR': str(tmp_path / 'files'), 'DEMO_MODE': 'true'})
    c = TestClient(app)
    c.get('/api/session')
    ws = c.get('/api/workspace').json()
    p = ws['projects'][0]
    wid = [r[0] for r in sqlite3.connect(tmp_path / 'app.db').execute('select id from workspaces')][0]

    def comment(version, request):
        return c.post('/api/actions', json={'action': 'comment_add', 'project_id': p['id'], 'version': version, 'request_id': request,
                                            'payload': {'body': '中文 comment', 'mentions': []}})
    sessions = sqlite_sessions(tmp_path / 'app.db')
    store = WorkspaceStore(sessions, wid)
    store.transact(lambda ns: ns.update(commands={'c1': {'state': 'queued', 'v': V.encode(V.CLEAR)}}))
    assert comment(ws['version'], 'stale').status_code == 409                    # the app's own protocol detects the ops commit
    fresh = c.get('/api/workspace').json()
    assert fresh['version'] == version_of(tmp_path / 'app.db', wid)                  # mirrored data['version'] == row.version
    assert comment(fresh['version'], 'fresh').status_code == 200
    root = json.loads(raw_row(tmp_path / 'app.db', wid)[1])
    assert root['ops_sync']['commands'] == {'c1': {'state': 'queued', 'v': {'t': 'clear'}}}     # app write kept ops_sync
    store.transact(lambda ns: ns['commands'].update(c2={'state': 'queued'}))
    after = c.get('/api/workspace').json()
    assert after['version'] == version_of(tmp_path / 'app.db', wid) and set(store.snapshot()['commands']) == {'c1', 'c2'}


# -- JSON column round trip ----------------------------------------------------------------------------------------
def test_json_column_round_trip_keeps_markers_unicode_and_types(db):
    state = {'values': {'clear': V.encode(V.CLEAR), 'set': V.encode(V.SetValue('任務 – ünïcode 🚀 "q" \\ \n')),
                        'unknown_tag': {'t': 'unknown'}, 'unknown_null': None, 'omitted_is_absent': {}},
             'nested': [{'n': 1, 'f': 1.5, 'b': True, 'z': None, 's': ''}], 'big': 2 ** 53 + 1, 'k日本': ['x']}
    store_for(db).transact(lambda ns: ns.update(state))
    snap = store_for(db).snapshot()
    snap.pop('_commit_seq')
    assert snap == state
    assert V.decode(snap['values']['clear']) is V.CLEAR and V.decode(snap['values']['unknown_null']) is V.UNKNOWN
    assert V.decode(snap['values']['set']) == V.SetValue('任務 – ünïcode 🚀 "q" \\ \n')
    assert json.loads(raw_row(db)[1])['ops_sync']['values']['set']['v'].startswith('任務')


# -- independent OS processes --------------------------------------------------------------------------------------
def worker_cmd(path, tmp_path, *args):
    return [sys.executable, '-m', 'backend.ops_sync.testing_worker', args[0], str(path), str(tmp_path / 'lark.json'), *args[1:]]


def run_worker(path, tmp_path, *args):
    return subprocess.run(worker_cmd(path, tmp_path, *args), cwd=ROOT, capture_output=True, text=True, timeout=120,
                          env={**os.environ, 'OPS_TEST_STORE': 'workspace'})


def spawn(path, tmp_path, *args):
    return subprocess.Popen(worker_cmd(path, tmp_path, *args), cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            env={**os.environ, 'OPS_TEST_STORE': 'workspace'})


@pytest.mark.parametrize('barrier', STORE_BARRIERS['workspace'])
def test_kill_9_at_each_commit_barrier_recovers_a_complete_old_or_new_state(tmp_path, db, barrier):
    assert run_worker(db, tmp_path, 'submit', 'base').stdout.strip() == 'ack'
    victim = run_worker(db, tmp_path, 'submit', 'victim', barrier)
    assert victim.returncode == 9 and 'ack' not in victim.stdout
    with sqlite3.connect(db) as conn:
        assert conn.execute('pragma integrity_check').fetchone() == ('ok',)
    snap = store_for(db).snapshot()
    landed = barrier in STORE_LANDED['workspace']
    assert 'base' in snap['commands'] and ('victim' in snap['commands']) == landed == ('victim' in snap['outbox'])
    assert data_of(db)['sentinel'] == {'keep': '日本語 🚀'} and data_of(db)['version'] == version_of(db)
    again = run_worker(db, tmp_path, 'submit', 'victim')                   # restart + replay is safe either way
    assert again.stdout.strip() == 'ack'
    snap = store_for(db).snapshot()
    assert sorted(snap['commands']) == ['base', 'victim'] and sorted(snap['outbox']) == ['base', 'victim']


def test_external_sigkill_mid_stream_loses_no_acknowledged_command_and_never_splits_a_commit(tmp_path, db):
    proc = spawn(db, tmp_path, 'stream', 'k', '400')
    acked = []
    for line in proc.stdout:
        acked.append(line.split()[1])
        if len(acked) == 25:
            proc.send_signal(signal.SIGKILL)
            break
    proc.wait(timeout=30)
    assert proc.returncode == -signal.SIGKILL
    with sqlite3.connect(db) as conn:
        assert conn.execute('pragma integrity_check').fetchone() == ('ok',)
    snap = store_for(db).snapshot()
    assert set(acked) <= set(snap['commands']) and set(snap['commands']) == set(snap['outbox'])
    assert len(snap['outbox']) == len(set(snap['outbox'])) < 400
    assert data_of(db)['version'] == version_of(db)


def test_two_process_contention_has_no_lost_updates_and_conflicts_on_the_same_field(tmp_path, db):
    ready = tmp_path / 'ready'
    ready.mkdir()
    observer = OpsEngine(store_for(db), A.MockLarkAdapter(JsonFileStore(tmp_path / 'lark.json', namespace='mock_lark')), FakeClock())
    assert observer.observe(E)['complete']
    procs = [spawn(db, tmp_path, 'compete', 'pa', '2026-10-20', str(ready)), spawn(db, tmp_path, 'compete', 'pb', '2026-10-25', str(ready))]
    for name in ('pa', 'pb'):
        waited = 0
        while not (ready / name).exists():
            waited += 1
            assert waited < 4000
            threading.Event().wait(0.005)
    (ready / 'go').touch()
    states = []
    for proc in procs:
        out, err = proc.communicate(timeout=120)
        assert proc.returncode == 0, err
        states.append(out.strip())
    assert sorted(states) == ['confirmed', 'conflict']
    start = version_of(db)
    procs = [spawn(db, tmp_path, 'many', 'wa', '15'), spawn(db, tmp_path, 'many', 'wb', '15'), spawn(db, tmp_path, 'unrelated', 'app', '15')]
    for proc in procs:
        out, err = proc.communicate(timeout=180)
        assert proc.returncode == 0 and out.strip() == 'ack', err
    data = data_of(db)
    commands = data['ops_sync']['commands']
    assert len([c for c in commands if c.startswith('w')]) == 30
    assert all(data[f'app_{i}'] == {'value': i} for i in range(15))                      # the app-style writer lost nothing
    assert sorted(data['ops_sync']['outbox']) == sorted(set(data['ops_sync']['outbox']))
    assert data['sentinel'] == {'keep': '日本語 🚀'} and data['version'] == version_of(db) >= start + 45


def test_duplicate_command_and_event_suppression_survives_restart(tmp_path, db):
    assert run_worker(db, tmp_path, 'submit', 'dup').stdout.strip() == 'ack'
    first = data_of(db)['ops_sync']
    assert run_worker(db, tmp_path, 'submit', 'dup').stdout.strip() == 'ack'           # fresh process replays the same command
    again = data_of(db)['ops_sync']
    assert again['commands'] == first['commands'] and again['outbox'] == ['dup']
    assert version_of(db) == data_of(db)['version']


def test_app_wires_the_workspace_store_only_behind_the_default_off_flag(tmp_path):
    def build(**flags):
        return app_module.create_app({'DATABASE_URL': f'sqlite:///{tmp_path}/{len(flags)}.db', 'UPLOAD_DIR': str(tmp_path / 'f'),
                                      'DEMO_MODE': 'true', **flags})
    assert build().state.ops_store_for is None
    assert build(FEATURE_LARK_AUTHORITATIVE_OPS='false').state.ops_store_for is None
    assert build(FEATURE_LARK_AUTHORITATIVE_OPS='yes').state.ops_store_for is None
    on = build(FEATURE_LARK_AUTHORITATIVE_OPS='true')
    from fastapi.testclient import TestClient
    c = TestClient(on)
    c.get('/api/session')
    wid = [r[0] for r in sqlite3.connect(tmp_path / '1.db').execute('select id from workspaces')][0]
    store = on.state.ops_store_for(wid)
    assert isinstance(store, WorkspaceStore) and store.durable
    store.transact(lambda ns: ns.update(commands={'c1': 1}))
    assert store.snapshot()['commands'] == {'c1': 1}


def test_flag_off_app_does_not_import_ops_sync(tmp_path):
    code = ('import sys;from backend.app import create_app;'
            f'a=create_app({{"DATABASE_URL":"sqlite:///{tmp_path}/x.db","UPLOAD_DIR":"{tmp_path}/f","DEMO_MODE":"true"}});'
            'print(a.state.ops_store_for, any(m.startswith("backend.ops_sync") for m in sys.modules))')
    out = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True)
    assert out.stdout.split() == ['None', 'False'], out.stderr
