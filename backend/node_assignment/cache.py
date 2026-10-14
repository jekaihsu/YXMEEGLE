"""Scoped, single-flight reads with last-good stale snapshots."""
import hashlib
import json
import logging
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any


_background_slots = threading.BoundedSemaphore(3)


@dataclass(frozen=True)
class ReadScope:
    tenant: str
    app: str
    identity: str
    workspace: str
    authz_version: str

    def key(self, table, *, projection=(), filter=None, sort=(), view=None):
        query = json.dumps([table, sorted(projection), filter, sort, view],
                           sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        return (self, hashlib.sha256(query.encode()).hexdigest())


@dataclass(frozen=True)
class Cached:
    value: Any
    stale: bool
    fetched_at: float
    stale_reason: str | None = None

    @property
    def complete(self):
        if isinstance(self.value, dict):
            return self.value.get('complete', self.value.get('status') != 'partial') is True
        return True

    @property
    def read_state(self):
        return 'partial' if not self.complete else 'complete'


def permission_failure(exc):
    while exc.__cause__ is not None:
        exc = exc.__cause__
    return (getattr(exc, 'code', None) == 'lark_permission'
            or getattr(exc, 'status_code', None) in (401, 403)
            or getattr(exc, 'status', None) == 'blocked')


class StaleCache:
    def __init__(self, ttl, stale_max, clock=time.time):
        self.ttl, self.stale_max, self.clock = ttl, stale_max, clock
        self._entries = {}
        self._lock = threading.Lock()
        self._flights = {}
        self._versions = {}

    def get(self, key, load, *, max_age=None, allow_stale=True, revalidate=False) -> Cached:
        now = self.clock()
        window = self.ttl if max_age is None else max_age
        with self._lock:
            entry = self._entries.get(key)
            if entry and now - entry.fetched_at <= window:
                return entry
            stale = allow_stale and entry and now - entry.fetched_at <= self.stale_max
            future = self._flights.get(key)
            if future is not None and future.done():
                future = None
            owner = future is None
            background = bool(revalidate and stale)
            if owner:
                if background and not _background_slots.acquire(blocking=False):
                    return Cached(entry.value, True, entry.fetched_at, 'busy')
                future = Future()
                self._flights[key] = future
                version = self._versions.get(key, 0)

        def refresh():
            try:
                fresh = Cached(load(), False, self.clock())
                with self._lock:
                    if self._versions.get(key, 0) == version and fresh.complete:
                        self._entries[key] = fresh
                future.set_result(fresh)
            except Exception as exc:
                if permission_failure(exc):
                    self.drop_scope(key)
                future.set_exception(exc)
                if background:
                    logging.getLogger(__name__).warning('read cache refresh failed code=%s',
                                                        getattr(exc, 'code', type(exc).__name__))
            finally:
                with self._lock:
                    if self._flights.get(key) is future:
                        self._flights.pop(key, None)
                if background:
                    _background_slots.release()

        if owner:
            if background:
                threading.Thread(target=refresh, daemon=True).start()
            else:
                refresh()
        if background:
            return Cached(entry.value, True, entry.fetched_at, 'refreshing')
        try:
            return future.result()
        except Exception as exc:
            if not permission_failure(exc) and stale:
                return Cached(entry.value, True, entry.fetched_at, getattr(exc, 'code', type(exc).__name__))
            raise

    def put(self, key, value):
        with self._lock:
            self._versions[key] = self._versions.get(key, 0) + 1
            self._entries[key] = Cached(value, False, self.clock())

    def drop(self, key):
        with self._lock:
            self._versions[key] = self._versions.get(key, 0) + 1
            self._entries.pop(key, None)

    def drop_scope(self, key):
        if not isinstance(key, tuple) or not isinstance(key[0], ReadScope):
            self.drop(key)
            return
        with self._lock:
            keys = set(self._entries) | set(self._flights)
            for candidate in keys:
                if isinstance(candidate, tuple) and candidate[0] == key[0]:
                    self._versions[candidate] = self._versions.get(candidate, 0) + 1
                    self._entries.pop(candidate, None)
