"""Transactional stores for ops_sync state.

`OpsStore.transact(fn)` runs `fn(ns)` on a private copy of the `ops_sync` namespace and commits it
atomically only if `fn` returns normally. `JsonFileStore` is a real durable implementation:
cross-process flock around the whole read-modify-write, checksummed snapshot, temp file + fsync +
rename + directory fsync, fail-closed on torn/corrupt committed files, unrelated keys preserved.
"""
import copy
import fcntl
import hashlib
import itertools
import json
import os
import time

from .values import OpsError

NAMESPACE = 'ops_sync'
FORMAT = 1
BARRIERS = ('before_tmp_write', 'tmp_partial', 'tmp_written', 'tmp_fsynced', 'renamed', 'dir_fsynced')


class StorageBlocked(OpsError):
    """Committed storage is unreadable/corrupt. Operations stop; nothing is reset."""
    code = 'storage_blocked'


class StorageBusy(OpsError):
    code = 'storage_busy'


class MemoryStore:
    """Rollback-on-exception store for unit tests. NOT durable; never satisfies the durability criteria."""
    durable = False

    def __init__(self):
        self._ns = {}

    def transact(self, fn):
        work = copy.deepcopy(self._ns)
        result = fn(work)
        self._ns = work
        return result

    def snapshot(self):
        return copy.deepcopy(self._ns)


def _digest(state):
    return hashlib.sha256(json.dumps(state, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


class JsonFileStore:
    durable = True
    _tmp_counter = itertools.count()

    def __init__(self, path, namespace=NAMESPACE, hook=None, lock_timeout=30.0):
        self.path = os.fspath(path)
        self.lock_path = self.path + '.lock'
        self.namespace = namespace
        self.hook = hook
        self.lock_timeout = lock_timeout

    # -- locking -------------------------------------------------------------------------
    def _lock(self):
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        deadline = time.monotonic() + self.lock_timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return fd
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    os.close(fd)
                    raise StorageBusy('could not acquire the workspace lock') from None
                time.sleep(0.005)

    def _unlock(self, fd):
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    # -- committed snapshot --------------------------------------------------------------
    def _read(self):
        try:
            with open(self.path, 'rb') as handle:
                raw = handle.read()
        except FileNotFoundError:
            return {}
        try:
            doc = json.loads(raw)
            state, digest = doc['state'], doc['sha256']
        except (ValueError, KeyError, TypeError):
            raise StorageBlocked('committed workspace file is torn or not a valid snapshot; refusing to reset') from None
        if doc.get('format') != FORMAT or not isinstance(state, dict) or _digest(state) != digest:
            raise StorageBlocked('committed workspace file failed checksum validation; refusing to reset')
        return state

    def _barrier(self, name):
        if self.hook:
            self.hook(name)

    def _commit(self, state):
        self._barrier('before_tmp_write')
        payload = json.dumps({'format': FORMAT, 'sha256': _digest(state), 'state': state}, sort_keys=True,
                             ensure_ascii=False).encode()
        directory = os.path.dirname(os.path.abspath(self.path))
        tmp = f'{self.path}.tmp.{os.getpid()}.{next(self._tmp_counter)}'
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            half = len(payload) // 2
            os.write(fd, payload[:half])
            self._barrier('tmp_partial')
            os.write(fd, payload[half:])
            self._barrier('tmp_written')
            os.fsync(fd)
            self._barrier('tmp_fsynced')
        except BaseException:
            os.close(fd)
            raise
        os.close(fd)
        os.replace(tmp, self.path)
        self._barrier('renamed')
        dir_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        self._barrier('dir_fsynced')

    # -- public API ----------------------------------------------------------------------
    def transact_raw(self, fn):
        """Whole-workspace read-modify-write under the shared lock. Cooperating non-ops writers use this."""
        fd = self._lock()
        try:
            state = self._read()
            work = copy.deepcopy(state)
            result = fn(work)
            if work != state:
                self._commit(work)
            return result
        finally:
            self._unlock(fd)

    def transact(self, fn):
        def scoped(workspace):
            ns = workspace.setdefault(self.namespace, {})
            if not isinstance(ns, dict):
                raise StorageBlocked(f'namespace {self.namespace!r} is not an object')
            before = copy.deepcopy(ns)
            result = fn(ns)
            if ns != before:
                ns['_commit_seq'] = before.get('_commit_seq', 0) + 1
            elif not before:
                workspace.pop(self.namespace, None)
            return result
        return self.transact_raw(scoped)

    def snapshot(self):
        return copy.deepcopy(self.transact_raw(lambda ws: ws.get(self.namespace, {})))

    def snapshot_raw(self):
        return self.transact_raw(lambda ws: copy.deepcopy(ws))
