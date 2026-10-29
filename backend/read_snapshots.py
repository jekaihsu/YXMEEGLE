"""Bounded encoded read snapshots with single-flight and stale-while-revalidate."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar, copy_context
from threading import Lock
from time import monotonic, thread_time
import logging
import gzip
import hashlib
from dataclasses import dataclass

from starlette.responses import Response


@dataclass(frozen=True)
class EncodedSnapshot:
    body: bytes
    compressed: bytes
    etag: str
    as_of: str | None = None

    def __len__(self):
        return len(self.body) + len(self.compressed)

    @classmethod
    def encode(cls, body, *, as_of=None):
        from .request_timing import measure
        with measure('snapshotcompress'):
            compressed = gzip.compress(body, compresslevel=1, mtime=0)
        return cls(body, compressed, 'W/"' + hashlib.sha256(body).hexdigest() + '"', as_of)

    def response(self, request, status):
        # Always reauthorize before conditional validation. Browser freshness must
        # not extend admission; stale-while-revalidate lives in ReadSnapshots.
        request.scope['read_snapshot_response'] = True
        headers = {'ETag': self.etag, 'Cache-Control': 'private, max-age=0, must-revalidate',
                   'Vary': 'Accept-Encoding, Cookie', 'X-Read-Snapshot': status}
        if self.as_of:
            headers['X-Data-As-Of'] = self.as_of
        tags = request.headers.get('if-none-match', '').split(',')
        if any(tag.strip().removeprefix('W/') in ('*', self.etag.removeprefix('W/')) for tag in tags):
            return Response(status_code=304, headers=headers)
        encodings = {}
        for entry in request.headers.get('accept-encoding', '').lower().split(','):
            name, *parameters = entry.strip().split(';')
            quality = 1.0
            for parameter in parameters:
                if parameter.strip().startswith('q='):
                    try:
                        quality = float(parameter.strip()[2:])
                    except ValueError:
                        quality = 0
            encodings[name] = quality
        if encodings.get('gzip', encodings.get('*', 0)) > 0:
            headers['Content-Encoding'] = 'gzip'
            return Response(self.compressed, media_type='application/json', headers=headers)
        # Prevent the outer middleware from recompressing a negotiated identity body.
        headers['Content-Encoding'] = 'identity'
        return Response(self.body, media_type='application/json', headers=headers)

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

    def peek(self, key):
        with self.lock:
            entry = self.entries.get(key)
            return entry[1] if entry and self.clock()-entry[0] < self.stale else None

    def _store(self, key, value, revision):
        if len(value) <= self.max_bytes:
            self.entries[key] = (self.clock(), value, revision)
            self.entries.move_to_end(key)
            while len(self.entries) > 32 or sum(len(v[1]) for v in self.entries.values()) > self.max_bytes:
                self.entries.popitem(last=False)

    def retain(self, key, value, generation):
        with self.lock:
            if generation == self.generation and key not in self.entries:
                self._store(key, value, None)

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
            if generation == self.generation:
                self._store(key, value, revision)
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
