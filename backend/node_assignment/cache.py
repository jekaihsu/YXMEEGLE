"""Last good value per key: fresh within the TTL, served stale on error up to a ceiling."""
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

    def get(self, key, load, *, max_age=None, allow_stale=True) -> Cached:
        with self._lock:
            entry = self._entries.get(key)
        now = self.clock()
        window = self.ttl if max_age is None else max_age
        if entry and now - entry.fetched_at <= window:
            return entry
        try:
            value = load()
        except Failure as exc:
            if allow_stale and entry and now - entry.fetched_at <= self.stale_max:
                return Cached(entry.value, True, entry.fetched_at, exc.code)
            raise
        fresh = Cached(value, False, now)
        with self._lock:
            self._entries[key] = fresh
        return fresh

    def put(self, key, value):
        with self._lock:
            self._entries[key] = Cached(value, False, self.clock())

    def drop(self, key):
        with self._lock:
            self._entries.pop(key, None)
