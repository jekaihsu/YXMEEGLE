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
from .ops_sync.store import BARRIERS, JsonFileStore, MemoryStore, StorageBlocked
from .ops_sync.testing import env

ROOT = Path(__file__).resolve().parent.parent
E = 'case_test_1'


def worker(tmp_path, *args, check=True):
    return subprocess.run([sys.executable, '-m', 'backend.ops_sync.testing_worker', args[0], str(tmp_path / 'ws.json'),
                           str(tmp_path / 'lark.json'), *args[1:]], cwd=ROOT, capture_output=True, text=True, timeout=60)


def spawn(tmp_path, *args):
    return subprocess.Popen([sys.executable, '-m', 'backend.ops_sync.testing_worker', args[0], str(tmp_path / 'ws.json'),
                             str(tmp_path / 'lark.json'), *args[1:]], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def reopen(tmp_path, clock=None):
    adapter = A.MockLarkAdapter(JsonFileStore(tmp_path / 'lark.json', namespace='mock_lark'))
    return OpsEngine(JsonFileStore(tmp_path / 'ws.json'), adapter, clock or FakeClock()), adapter


def test_store_rolls_back_when_the_transaction_raises(tmp_path):
    for store in (MemoryStore(), JsonFileStore(tmp_path / 'ws.json')):
        store.transact(lambda ns: ns.update(a=1))

        def boom(ns):
            ns['a'] = 2
            ns['b'] = 3
            raise RuntimeError('boom')
        with pytest.raises(RuntimeError):
            store.transact(boom)
        assert store.snapshot()['a'] == 1 and 'b' not in store.snapshot()


@pytest.mark.parametrize('barrier', BARRIERS)
def test_storage_kill_mid_write_recovers_complete_transaction(tmp_path, barrier):
    assert worker(tmp_path, 'submit', 'base').stdout.strip() == 'ack'          # acknowledged before the crash
    victim = worker(tmp_path, 'submit', 'victim', barrier)
    assert victim.returncode == 9 and 'ack' not in victim.stdout               # killed: never acknowledged
    engine, _ = reopen(tmp_path)
    snap = engine.snapshot()
    assert 'base' in snap['commands'] and 'base' in snap['outbox']             # acknowledged commit survives
    landed = barrier in ('renamed', 'dir_fsynced')
    assert ('victim' in snap['commands']) == landed                            # complete old OR complete new snapshot
    assert ('victim' in snap['outbox']) == landed                              # command and outbox never split
    if landed:
        assert snap['commands']['victim']['state'] == 'queued'
        assert snap['commands']['victim']['envelope']['command_id'] == 'victim'
    assert engine.submit(env('victim'))['duplicate'] is landed                 # replay is safe either way
    assert [c for c in engine.snapshot()['commands']] .count('victim') == 1
    assert len(engine.snapshot()['outbox']) == len(set(engine.snapshot()['outbox'])) == 2


@pytest.mark.parametrize('commit_no,barrier', [(1, 'tmp_written'), (2, 'before_tmp_write'), (2, 'renamed'), (3, 'before_tmp_write'), (3, 'tmp_fsynced')])
def test_storage_restart_preserves_duplicate_suppression(tmp_path, commit_no, barrier):
    """Crash around durable acceptance / after the adapter committed but before local confirmation."""
    dead = worker(tmp_path, 'run', 'c1', barrier, str(commit_no))
    assert dead.returncode == 9
    if commit_no == 3:                                                         # adapter committed, local confirmation lost
        assert reopen(tmp_path)[1].write_count == 1
    clock = FakeClock()
    clock.advance(40)                                                          # expired leases are reclaimable
    engine, adapter = reopen(tmp_path, clock)
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
    assert worker(tmp_path, 'submit', 'base').stdout.strip() == 'ack'
    ws = tmp_path / 'ws.json'
    good = ws.read_bytes()
    # an incomplete temp file is never promoted
    (tmp_path / 'ws.json.tmp.1.0').write_bytes(good[: len(good) // 2])
    engine, _ = reopen(tmp_path)
    assert 'base' in engine.snapshot()['commands']
    engine.submit(env('later'))
    assert {'base', 'later'} <= set(reopen(tmp_path)[0].snapshot()['commands'])
    committed = ws.read_bytes()
    doc = json.loads(committed)
    tampered = dict(doc, state=dict(doc['state'], extra=1))                    # valid JSON, wrong checksum
    for damaged in (committed[: len(committed) // 2], b'', b'{"format":1}', json.dumps(tampered).encode(), b'[]'):
        ws.write_bytes(damaged)
        engine, _ = reopen(tmp_path)
        with pytest.raises(StorageBlocked):
            engine.submit(env('after'))
        with pytest.raises(StorageBlocked):
            engine.snapshot()
        with pytest.raises(StorageBlocked):
            JsonFileStore(ws).transact_raw(lambda d: d.update(x=1))
        assert ws.read_bytes() == damaged                                      # evidence preserved, never reset
    assert not any('after' in p.name for p in tmp_path.iterdir())
    ws.write_bytes(committed)                                                  # operator restores a good snapshot
    assert set(reopen(tmp_path)[0].snapshot()['commands']) == {'base', 'later'}


def test_storage_two_process_writers_serialize_and_fence(tmp_path):
    ready = tmp_path / 'ready'
    ready.mkdir()
    reopen(tmp_path)[0].observe(E)
    procs = [spawn(tmp_path, 'compete', 'pa', '2026-10-20', str(ready)), spawn(tmp_path, 'compete', 'pb', '2026-10-25', str(ready))]
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
    engine, adapter = reopen(tmp_path)
    assert adapter.write_count == 1
    winner = next(c for c in ('pa', 'pb') if engine.status(c)['state'] == 'confirmed')
    assert engine.projection(E, 'case.deadline')[0] == V.SetValue('2026-10-20' if winner == 'pa' else '2026-10-25')

    # different-field state written by two further processes survives, with no lost updates
    many = [spawn(tmp_path, 'many', 'wa', '15'), spawn(tmp_path, 'many', 'wb', '15')]
    for proc in many:
        out, err = proc.communicate(timeout=120)
        assert proc.returncode == 0 and out.strip() == 'ack', err
    snap = reopen(tmp_path)[0].snapshot()
    assert len([c for c in snap['commands'] if c.startswith('w')]) == 30
    assert len(snap['outbox']) == len(set(snap['outbox'])) and len([c for c in snap['outbox'] if c.startswith('w')]) == 30
    assert snap['history'] and engine.projection(E, 'case.deadline')[1] == 1


def test_storage_process_death_releases_lock_and_lease_is_reclaimed(tmp_path):
    reopen(tmp_path)[0].observe(E)
    assert worker(tmp_path, 'lease_then_die', 'c1').returncode == 9
    clock = FakeClock()
    engine, adapter = reopen(tmp_path, clock)
    assert engine.snapshot()['commands']['c1']['lease'] is not None            # dead worker still holds the lease
    assert engine.run_once() == []                                             # nobody may dispatch around a live lease
    clock.advance(31)
    for _ in range(3):
        engine.run_once()
    assert engine.status('c1')['state'] == 'confirmed' and adapter.write_count == 1


def test_storage_ops_transaction_preserves_unrelated_workspace_keys(tmp_path):
    ws = tmp_path / 'ws.json'
    JsonFileStore(ws).transact_raw(lambda doc: doc.update(users={'ou_test_1': {'name': 'Sentinel'}}, version=7, projects=[1, 2, 3]))
    sentinel = JsonFileStore(ws).snapshot_raw()

    # injected commit failure before the rename: nothing partial, sentinels intact
    def explode(name):
        if name == 'tmp_written':
            raise OSError('disk full')
    store = JsonFileStore(ws, hook=explode)
    adapter = A.MockLarkAdapter(JsonFileStore(tmp_path / 'lark.json', namespace='mock_lark'))
    engine = OpsEngine(store, adapter, FakeClock())
    with pytest.raises(OSError):
        engine.submit(env('c1'))
    assert JsonFileStore(ws).snapshot_raw() == sentinel and 'ops_sync' not in JsonFileStore(ws).snapshot_raw()
    # a concurrent non-ops writer process and an ops writer process race on the same file
    procs = [spawn(tmp_path, 'unrelated', 'other', '25'), spawn(tmp_path, 'many', 'ops', '25')]
    for proc in procs:
        out, err = proc.communicate(timeout=120)
        assert proc.returncode == 0, err
    raw = JsonFileStore(ws).snapshot_raw()
    assert {k: raw[k] for k in ('users', 'version', 'projects')} == {k: sentinel[k] for k in ('users', 'version', 'projects')}
    assert all(raw[f'other_{i}'] == {'value': i} for i in range(25))           # the other writer lost nothing either
    assert len([c for c in raw['ops_sync']['commands'] if c.startswith('ops')]) == 25
    # fresh-process reopen proves durability after commit
    out = subprocess.run([sys.executable, '-c', 'import json,sys;d=json.load(open(sys.argv[1]));print(len(d["state"]["ops_sync"]["commands"]),d["state"]["version"])', str(ws)],
                         capture_output=True, text=True)
    assert out.stdout.split() == ['25', '7']


def test_process_race_and_commit_failure_preserve_atomic_ops_and_unrelated_state(tmp_path):
    ws = tmp_path / 'ws.json'
    JsonFileStore(ws).transact_raw(lambda doc: doc.update(sentinel='keep'))
    store = JsonFileStore(ws, hook=lambda name: (_ for _ in ()).throw(OSError('boom')) if name == 'renamed' else None)
    engine = OpsEngine(store, A.MockLarkAdapter(), FakeClock())
    with pytest.raises(OSError):                                               # fails after rename: commit is complete, not partial
        engine.submit(env('c1'))
    snap = JsonFileStore(ws).snapshot_raw()
    assert snap['sentinel'] == 'keep'
    assert 'c1' in snap['ops_sync']['commands'] and snap['ops_sync']['outbox'] == ['c1']
