"""Last good values with opt-in, single-flight stale-while-revalidate reads."""
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

from .errors import Failure


@dataclass(frozen=True)
class Cached:
    value: Any
    stale: bool
    fetched_at: float
    stale_reason: str | None = None


class StaleCache:
    def __init__(self, ttl, stale_max, clock=time.time):
        self.ttl, self.stale_max, self.clock = ttl, stale_max, clock
        self._entries = {}
        self._lock = threading.Lock()
        self._refreshing = set()
        self._versions = {}

    def get(self, key, load, *, max_age=None, allow_stale=True, revalidate=False) -> Cached:
        with self._lock:
            entry = self._entries.get(key)
            version = self._versions.get(key, 0)
        now = self.clock()
        window = self.ttl if max_age is None else max_age
        if entry and now - entry.fetched_at <= window:
            return entry
        if revalidate and entry and now - entry.fetched_at <= self.stale_max:
            with self._lock:
                if key not in self._refreshing:
                    self._refreshing.add(key)
                    def refresh():
                        try:
                            value = load()
                            with self._lock:
                                if self._versions.get(key, 0) == version:
                                    self._entries[key] = Cached(value, False, self.clock())
                        except Exception as exc:
                            logging.getLogger(__name__).warning('node_assignment background refresh failed code=%s',
                                                                       getattr(exc, 'code', type(exc).__name__))
                        finally:
                            with self._lock:
                                self._refreshing.discard(key)
                    threading.Thread(target=refresh, daemon=True).start()
            return Cached(entry.value, True, entry.fetched_at, 'refreshing')
        try:
            value = load()
        except Failure as exc:
            if allow_stale and entry and now - entry.fetched_at <= self.stale_max:
                return Cached(entry.value, True, entry.fetched_at, exc.code)
            raise
        fresh = Cached(value, False, self.clock())
        with self._lock:
            if self._versions.get(key, 0) == version:
                self._versions[key] = version + 1
                self._entries[key] = fresh
        return fresh

    def put(self, key, value):
        with self._lock:
            self._versions[key] = self._versions.get(key, 0) + 1
            self._entries[key] = Cached(value, False, self.clock())

    def drop(self, key):
        with self._lock:
            self._versions[key] = self._versions.get(key, 0) + 1
            self._entries.pop(key, None)
