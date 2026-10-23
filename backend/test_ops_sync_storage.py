"""Deliberate-failure evidence for the durable ops_sync store (real files, independent OS processes)."""
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from .ops_sync import adapter as A
from .ops_sync import values as V
from .ops_sync.clock import FakeClock
from .ops_sync.engine import OpsEngine
from .ops_sync.store import JsonFileStore, MemoryStore, StorageBlocked
from .ops_sync.testing import (STORE_BARRIERS, STORE_KINDS, STORE_LANDED, env, open_store, seed_workspace, sqlite_sessions,
                               ws_path)

ROOT = Path(__file__).resolve().parent.parent
E = 'case_test_1'


def cmd(tmp_path, kind, *args):
    return [sys.executable, '-m', 'backend.ops_sync.testing_worker', args[0], ws_path(tmp_path, kind), str(tmp_path / 'lark.json'), *args[1:]]


def worker(tmp_path, kind, *args, check=True):
    return subprocess.run(cmd(tmp_path, kind, *args), cwd=ROOT, capture_output=True, text=True, timeout=60,
                          env={**os.environ, 'OPS_TEST_STORE': kind})


def spawn(tmp_path, kind, *args):
    return subprocess.Popen(cmd(tmp_path, kind, *args), cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            env={**os.environ, 'OPS_TEST_STORE': kind})


def reopen(tmp_path, kind, clock=None):
    adapter = A.MockLarkAdapter(JsonFileStore(tmp_path / 'lark.json', namespace='mock_lark'))
    return OpsEngine(open_store(kind, ws_path(tmp_path, kind)), adapter, clock or FakeClock()), adapter


KIND_BARRIER = [(kind, barrier) for kind in STORE_KINDS for barrier in STORE_BARRIERS[kind]]
# the same crash points, named per store: (commit number, barrier) for the file store -> workspace store equivalents
CRASH = {'file': {'before_tmp_write': 'before_tmp_write', 'tmp_written': 'tmp_written', 'renamed': 'renamed', 'tmp_fsynced': 'tmp_fsynced'},
         'workspace': {'before_tmp_write': 'before_update', 'tmp_written': 'updated', 'renamed': 'committed', 'tmp_fsynced': 'updated'}}


def test_store_rolls_back_when_the_transaction_raises(tmp_path, store_kind):
    for store in (MemoryStore(), open_store(store_kind, ws_path(tmp_path, store_kind))):
        store.transact(lambda ns: ns.update(a=1))

        def boom(ns):
            ns['a'] = 2
            ns['b'] = 3
            raise RuntimeError('boom')
        with pytest.raises(RuntimeError):
            store.transact(boom)
        assert store.snapshot()['a'] == 1 and 'b' not in store.snapshot()


@pytest.mark.parametrize('kind,barrier', KIND_BARRIER)
def test_storage_kill_mid_write_recovers_complete_transaction(tmp_path, kind, barrier):
    assert worker(tmp_path, kind, 'submit', 'base').stdout.strip() == 'ack'          # acknowledged before the crash
    victim = worker(tmp_path, kind, 'submit', 'victim', barrier)
    assert victim.returncode == 9 and 'ack' not in victim.stdout               # killed: never acknowledged
    engine, _ = reopen(tmp_path, kind)
    snap = engine.snapshot()
    assert 'base' in snap['commands'] and 'base' in snap['outbox']             # acknowledged commit survives
    landed = barrier in STORE_LANDED[kind]
    assert ('victim' in snap['commands']) == landed                            # complete old OR complete new snapshot
    assert ('victim' in snap['outbox']) == landed                              # command and outbox never split
    if landed:
        assert snap['commands']['victim']['state'] == 'queued'
        assert snap['commands']['victim']['envelope']['command_id'] == 'victim'
    assert engine.submit(env('victim'))['duplicate'] is landed                 # replay is safe either way
    assert [c for c in engine.snapshot()['commands']] .count('victim') == 1
    assert len(engine.snapshot()['outbox']) == len(set(engine.snapshot()['outbox'])) == 2


@pytest.mark.parametrize('commit_no,barrier', [(1, 'tmp_written'), (2, 'before_tmp_write'), (2, 'renamed'), (3, 'before_tmp_write'), (3, 'tmp_fsynced')])
def test_storage_restart_preserves_duplicate_suppression(tmp_path, store_kind, commit_no, barrier):
    """Crash around durable acceptance / after the adapter committed but before local confirmation."""
    dead = worker(tmp_path, store_kind, 'run', 'c1', CRASH[store_kind][barrier], str(commit_no))
    assert dead.returncode == 9
    if commit_no == 3:                                                         # adapter committed, local confirmation lost
        assert reopen(tmp_path, store_kind)[1].write_count == 1
    clock = FakeClock()
    clock.advance(40)                                                          # expired leases are reclaimable
    engine, adapter = reopen(tmp_path, store_kind, clock)
    engine.submit(env('c1'))                                                   # replay after restart: no new identity
    for _ in range(4):
        engine.run_once()
        clock.advance(5)
    assert engine.status('c1')['state'] == 'confirmed'
    assert adapter.write_count == 1                                            # exactly one adapter effect
    assert [h['command_id'] for h in engine.snapshot()['history']] == ['c1']   # exactly one history entry
    assert set(engine.snapshot()['commands']) == {'c1'}
    engine.run_once()
    engine.submit(env('c1'))
    assert adapter.write_count == 1 and len(engine.snapshot()['history']) == 1


def test_storage_torn_partial_file_fails_closed_without_reset(tmp_path):
    # File-store specific (temp-file promotion). The SQLite row analogue is test_corrupt_row_data_fails_closed_without_reset.
    assert worker(tmp_path, 'file', 'submit', 'base').stdout.strip() == 'ack'
    ws = tmp_path / 'ws.json'
    good = ws.read_bytes()
    # an incomplete temp file is never promoted
    (tmp_path / 'ws.json.tmp.1.0').write_bytes(good[: len(good) // 2])
    engine, _ = reopen(tmp_path, 'file')
    assert 'base' in engine.snapshot()['commands']
    engine.submit(env('later'))
    assert {'base', 'later'} <= set(reopen(tmp_path, 'file')[0].snapshot()['commands'])
    committed = ws.read_bytes()
    doc = json.loads(committed)
    tampered = dict(doc, state=dict(doc['state'], extra=1))                    # valid JSON, wrong checksum
    for damaged in (committed[: len(committed) // 2], b'', b'{"format":1}', json.dumps(tampered).encode(), b'[]'):
        ws.write_bytes(damaged)
        engine, _ = reopen(tmp_path, 'file')
        with pytest.raises(StorageBlocked):
            engine.submit(env('after'))
        with pytest.raises(StorageBlocked):
            engine.snapshot()
        with pytest.raises(StorageBlocked):
            JsonFileStore(ws).transact_raw(lambda d: d.update(x=1))
        assert ws.read_bytes() == damaged                                      # evidence preserved, never reset
    assert not any('after' in p.name for p in tmp_path.iterdir())
    ws.write_bytes(committed)                                                  # operator restores a good snapshot
    assert set(reopen(tmp_path, 'file')[0].snapshot()['commands']) == {'base', 'later'}


def test_storage_two_process_writers_serialize_and_fence(tmp_path, store_kind):
    ready = tmp_path / 'ready'
    ready.mkdir()
    reopen(tmp_path, store_kind)[0].observe(E)
    procs = [spawn(tmp_path, store_kind, 'compete', 'pa', '2026-10-20', str(ready)), spawn(tmp_path, store_kind, 'compete', 'pb', '2026-10-25', str(ready))]
    for name in ('pa', 'pb'):
        deadline = 0
        while not (ready / name).exists():
            deadline += 1
            assert deadline < 4000
            threading.Event().wait(0.005)
    (ready / 'go').touch()
    states = []
    for proc in procs:
        out, err = proc.communicate(timeout=60)
        assert proc.returncode == 0, err
        states.append(out.strip())
    assert sorted(states) == ['confirmed', 'conflict']                         # same-field competition conflicts
    engine, adapter = reopen(tmp_path, store_kind)
    assert adapter.write_count == 1
    winner = next(c for c in ('pa', 'pb') if engine.status(c)['state'] == 'confirmed')
    assert engine.projection(E, 'case.deadline')[0] == V.SetValue('2026-10-20' if winner == 'pa' else '2026-10-25')

    # different-field state written by two further processes survives, with no lost updates
    many = [spawn(tmp_path, store_kind, 'many', 'wa', '15'), spawn(tmp_path, store_kind, 'many', 'wb', '15')]
    for proc in many:
        out, err = proc.communicate(timeout=120)
        assert proc.returncode == 0 and out.strip() == 'ack', err
    snap = reopen(tmp_path, store_kind)[0].snapshot()
    assert len([c for c in snap['commands'] if c.startswith('w')]) == 30
    assert len(snap['outbox']) == len(set(snap['outbox'])) and len([c for c in snap['outbox'] if c.startswith('w')]) == 30
    assert snap['history'] and engine.projection(E, 'case.deadline')[1] == 1


def test_storage_process_death_releases_lock_and_lease_is_reclaimed(tmp_path, store_kind):
    reopen(tmp_path, store_kind)[0].observe(E)
    assert worker(tmp_path, store_kind, 'lease_then_die', 'c1').returncode == 9
    clock = FakeClock()
    engine, adapter = reopen(tmp_path, store_kind, clock)
    assert engine.snapshot()['commands']['c1']['lease'] is not None            # dead worker still holds the lease
    assert engine.run_once() == []                                             # nobody may dispatch around a live lease
    clock.advance(31)
    for _ in range(3):
        engine.run_once()
    assert engine.status('c1')['state'] == 'confirmed' and adapter.write_count == 1


def test_storage_ops_transaction_preserves_unrelated_workspace_keys(tmp_path, store_kind):
    ws = ws_path(tmp_path, store_kind)
    seeds = dict(users={'ou_test_1': {'name': 'Sentinel'}}, version=7, projects=[1, 2, 3])
    if store_kind == 'workspace':
        seed_workspace(ws, seeds, version=7)
        read_raw = lambda: open_store(store_kind, ws).snapshot_raw()
    else:
        JsonFileStore(ws).transact_raw(lambda doc: doc.update(seeds))
        read_raw = lambda: JsonFileStore(ws).snapshot_raw()
    sentinel = read_raw()

    # injected commit failure before the commit point: nothing partial, sentinels intact
    def explode(name):
        if name in ('tmp_written', 'updated'):
            raise OSError('disk full')
    store = open_store(store_kind, ws, hook=explode)
    adapter = A.MockLarkAdapter(JsonFileStore(tmp_path / 'lark.json', namespace='mock_lark'))
    engine = OpsEngine(store, adapter, FakeClock())
    with pytest.raises(OSError):
        engine.submit(env('c1'))
    assert read_raw() == sentinel and 'ops_sync' not in read_raw()
    # a concurrent non-ops writer process and an ops writer process race on the same store
    procs = [spawn(tmp_path, store_kind, 'unrelated', 'other', '25'), spawn(tmp_path, store_kind, 'many', 'ops', '25')]
    for proc in procs:
        out, err = proc.communicate(timeout=120)
        assert proc.returncode == 0, err
    raw = read_raw()
    assert {k: raw[k] for k in ('users', 'projects')} == {k: sentinel[k] for k in ('users', 'projects')}
    assert all(raw[f'other_{i}'] == {'value': i} for i in range(25))           # the other writer lost nothing either
    assert len([c for c in raw['ops_sync']['commands'] if c.startswith('ops')]) == 25
    if store_kind == 'file':
        assert raw['version'] == 7                                             # the file store never touches non-ops keys
    else:
        assert raw['version'] == open_store(store_kind, ws).snapshot_raw()['version'] > 7   # mirrors row.version
    # fresh-process reopen proves durability after commit
    code = ('import json,sys;d=json.load(open(sys.argv[1]))["state"];print(len(d["ops_sync"]["commands"]),d["version"])' if store_kind == 'file' else
            'import json,sqlite3,sys;d=json.loads(sqlite3.connect(sys.argv[1]).execute("select data from workspaces").fetchone()[0]);print(len(d["ops_sync"]["commands"]),d["version"]>7)')
    out = subprocess.run([sys.executable, '-c', code, str(ws)], capture_output=True, text=True)
    assert out.stdout.split() == (['25', '7'] if store_kind == 'file' else ['25', 'True'])


def test_process_race_and_commit_failure_preserve_atomic_ops_and_unrelated_state(tmp_path, store_kind):
    ws = ws_path(tmp_path, store_kind)
    if store_kind == 'workspace':
        seed_workspace(ws, {'version': 1, 'sentinel': 'keep'})
    else:
        JsonFileStore(ws).transact_raw(lambda doc: doc.update(sentinel='keep'))
    after_commit = STORE_LANDED[store_kind][0]
    store = open_store(store_kind, ws, hook=lambda name: (_ for _ in ()).throw(OSError('boom')) if name == after_commit else None)
    engine = OpsEngine(store, A.MockLarkAdapter(), FakeClock())
    with pytest.raises(OSError):                                               # fails after commit: commit is complete, not partial
        engine.submit(env('c1'))
    snap = open_store(store_kind, ws).snapshot_raw()
    assert snap['sentinel'] == 'keep'
    assert 'c1' in snap['ops_sync']['commands'] and snap['ops_sync']['outbox'] == ['c1']
