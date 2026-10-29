"""Bounded encoded read snapshots with single-flight and stale-while-revalidate."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar, copy_context
from threading import Lock
from time import monotonic, thread_time
import logging

capture = ContextVar('case_snapshot_capture', default=None)


class ReadSnapshots:
    def __init__(self, *, fresh=15, stale=120, max_bytes=8_000_000, clock=monotonic):
        self.fresh, self.stale, self.max_bytes, self.clock = fresh, stale, max_bytes, clock
        self.entries = OrderedDict()
        self.flights = {}
        self.lock = Lock()
        self.generation = 0
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='read-snapshot')

    def invalidate(self):
        with self.lock:
            self.generation += 1
            self.entries.clear()

    def _build(self, key, generation, build, revision):
        from .request_timing import _current
        cpu = thread_time()
        try:
            value = build()
        finally:
            timing = _current.get()
            if timing:
                timing.add("snapshotcpu", thread_time() - cpu)
        with self.lock:
            if generation == self.generation and len(value) <= self.max_bytes:
                self.entries[key] = (self.clock(), value, revision)
                self.entries.move_to_end(key)
                while len(self.entries) > 32 or sum(len(v[1]) for v in self.entries.values()) > self.max_bytes:
                    self.entries.popitem(last=False)
        return value

    def get(self, key, build, *, revision=None):
        with self.lock:
            generation = self.generation
            flight_key = (generation, key, revision)
            entry = self.entries.get(key)
            age = self.clock() - entry[0] if entry else float('inf')
            if entry and entry[2] != revision:
                age = max(age, self.fresh)
            if age < self.fresh:
                return entry[1], 'hit'
            flight = self.flights.get(flight_key)
            if flight is None:
                flight = self.executor.submit(copy_context().run, self._build, key, generation, build, revision)
                self.flights[flight_key] = flight
                def done(future):
                    with self.lock:
                        self.flights.pop(flight_key, None)
                    if future.exception():
                        logging.getLogger(__name__).warning('read_snapshot_refresh_failed', exc_info=future.exception())
                # Register outside the lock: already-complete futures invoke callbacks inline.
                register = True
            else:
                register = False
        if register:
            flight.add_done_callback(done)
        if entry and age < self.stale:
            return entry[1], 'stale'
        return flight.result(), 'miss'

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=True)
