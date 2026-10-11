"""Independent-OS-process worker used by the storage failure-injection tests. Synthetic data only."""
import os
import sys
import time

from . import adapter as A
from . import values as V
from .clock import FakeClock
from .engine import OpsEngine
from .store import JsonFileStore
from .testing import COMMIT_START, app_style_write, env, open_store, sqlite_sessions


def killer(barrier, commit_no):
    state = {'commit': 0}

    def hook(name):
        if name in COMMIT_START:
            state['commit'] += 1
        if barrier and name == barrier and state['commit'] >= commit_no:
            os._exit(9)           # simulate SIGKILL: no cleanup, no ack
    return hook


def engine_for(ws, lark, hook=None):
    adapter = A.MockLarkAdapter(JsonFileStore(lark, namespace='mock_lark'))
    kind = os.environ.get('OPS_TEST_STORE', 'file')           # which real durable OpsStore the worker drives
    return OpsEngine(open_store(kind, ws, hook=hook), adapter, FakeClock()), adapter


def wait_for(path, timeout=20):
    deadline = time.monotonic() + timeout
    while not os.path.exists(path):
        if time.monotonic() > deadline:
            raise SystemExit('barrier timeout')
        time.sleep(0.005)


def main(argv):
    cmd, ws, lark = argv[:3]
    args = argv[3:]
    if cmd == 'submit':          # submit CID [BARRIER [COMMIT_NO]]
        barrier = args[1] if len(args) > 1 else None
        engine, _ = engine_for(ws, lark, killer(barrier, int(args[2]) if len(args) > 2 else 1))
        engine.submit(env(args[0]))
        print('ack', flush=True)
    elif cmd == 'run':           # run CID BARRIER COMMIT_NO: observe, submit, drive with a kill point
        engine, _ = engine_for(ws, lark)
        engine.observe('case_test_1')
        engine, _ = engine_for(ws, lark, killer(args[1], int(args[2])))
        engine.submit(env(args[0]))
        engine.run_once()
        print('done', flush=True)
    elif cmd == 'many':          # many PREFIX N
        engine, _ = engine_for(ws, lark)
        for i in range(int(args[1])):
            engine.submit(env(f'{args[0]}-{i}', field='case.pm', intended=V.SetValue(f'ou_test_{args[0]}_{i}')))
        print('ack', flush=True)
    elif cmd == 'unrelated':     # unrelated PREFIX N: a non-ops writer sharing the file
        if os.environ.get('OPS_TEST_STORE') == 'workspace':   # app.persist_mutation-style CAS writer
            sessions = sqlite_sessions(ws)
            for i in range(int(args[1])):
                app_style_write(sessions, lambda data, i=i: data.__setitem__(f'{args[0]}_{i}', {'value': i}))
        else:
            store = JsonFileStore(ws)
            for i in range(int(args[1])):
                store.transact_raw(lambda doc, i=i: doc.__setitem__(f'{args[0]}_{i}', {'value': i}))
        print('ack', flush=True)
    elif cmd == 'stream':        # stream PREFIX N: acknowledge every accepted command on stdout (for external SIGKILL)
        engine, _ = engine_for(ws, lark)
        for i in range(int(args[1])):
            engine.submit(env(f'{args[0]}-{i}', field='case.pm', intended=V.SetValue(f'ou_test_{args[0]}_{i}')))
            print(f'ack {args[0]}-{i}', flush=True)
    elif cmd == 'compete':       # compete CID VALUE READY_DIR: same baseline, then race
        engine, _ = engine_for(ws, lark)
        engine.observe('case_test_1')
        open(os.path.join(args[2], args[0]), 'w').close()
        wait_for(os.path.join(args[2], 'go'))
        engine.submit(env(args[0], intended=V.SetValue(args[1])))
        engine.run_once()
        print(engine.status(args[0])['state'], flush=True)
    elif cmd == 'lease_then_die':  # take a lease and die holding it
        engine, _ = engine_for(ws, lark)
        engine.observe('case_test_1')
        engine.submit(env(args[0]))
        engine.begin_dispatch(args[0])
        os._exit(9)
    else:
        raise SystemExit('unknown command')


if __name__ == '__main__':
    main(sys.argv[1:])
