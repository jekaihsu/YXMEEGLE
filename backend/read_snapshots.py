"""Bounded encoded read snapshots with single-flight and explicit initial stale paint."""
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
    volatile: bool = False

    def __len__(self):
        return len(self.body) + len(self.compressed)

    @classmethod
    def encode(cls, body, *, as_of=None, volatile=False, identity=None):
        from .request_timing import measure
        with measure('snapshotcompress'):
            compressed = gzip.compress(body, compresslevel=1, mtime=0)
        return cls(body, compressed, 'W/"' + (identity or hashlib.sha256(body).hexdigest()) + '"', as_of, volatile)

    def response(self, request, status):
        # Always reauthorize before conditional validation. Browser freshness must
        # not extend admission; stale-while-revalidate lives in ReadSnapshots.
        request.scope['read_snapshot_response'] = True
        headers = {'ETag': self.etag, 'Cache-Control': 'private, max-age=0, must-revalidate',
                   'Vary': 'Accept-Encoding, Cookie', 'X-Read-Snapshot': status}
        if self.as_of:
            headers['X-Data-As-Of'] = self.as_of
        tags = request.headers.get('if-none-match', '').split(',')
        if status != 'stale' and any(tag.strip().removeprefix('W/') in ('*', self.etag.removeprefix('W/')) for tag in tags):
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
        self.workspace_generations = {}
        self.requested = {}
        self.sequence = 0
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='read-snapshot')

    def invalidate(self, workspace=None):
        with self.lock:
            if workspace is None:
                self.generation += 1
                self.workspace_generations.clear()
            else:
                self.workspace_generations[workspace] = self.workspace_generations.get(workspace, 0) + 1
            # Workspace keys always carry wid in position 1; page keys nest it.
            def affected(key):
                if workspace is None:
                    return True
                return isinstance(key, tuple) and len(key) > 1 and (key[1] == workspace or affected(key[1]))
            for key in list(self.entries):
                if affected(key):
                    self.entries.pop(key, None)
            for key in list(self.requested):
                if affected(key):
                    self.requested.pop(key, None)

            # Detach affected flights so a same-revision read after a write builds
            # again. Running readers retain their Future and publication ticket.
            for flight_key in list(self.flights):
                if affected(flight_key[0]):
                    self.flights.pop(flight_key, None)

    def fence(self, workspace=None):
        with self.lock:
            return self.generation, self.workspace_generations.get(workspace, 0)

    def peek(self, key):
        with self.lock:
            entry = self.entries.get(key)
            return entry[1] if entry and self.clock()-entry[0] < self.stale else None

    def _store(self, key, value, revision):
        if len(value) <= self.max_bytes and not getattr(value, 'volatile', False):
            self.entries[key] = (self.clock(), value, revision)
            self.entries.move_to_end(key)
            while len(self.entries) > 32 or sum(len(v[1]) for v in self.entries.values()) > self.max_bytes:
                evicted, _ = self.entries.popitem(last=False)
                if not any(flight[0] == evicted for flight in self.flights):
                    self.requested.pop(evicted, None)

    def retain(self, key, value, generation, *, workspace=None):
        with self.lock:
            if generation == (self.generation, self.workspace_generations.get(workspace, 0)) and key not in self.entries:
                self._store(key, value, None)

    def _build(self, key, build, revision, ticket):
        from .request_timing import _current
        cpu = thread_time()
        try:
            value = build()
        finally:
            timing = _current.get()
            if timing:
                timing.add("snapshotcpu", thread_time() - cpu)
        with self.lock:
            if self.requested.get(key) == (revision, ticket):
                self._store(key, value, revision)
                return value, True
        return value, False

    def get(self, key, build, *, revision=None, force=False, allow_stale=True):
        """Await a consistent revision; age-only staleness may rebuild in background.

        A delayed older request joins the highest requested revision. Superseded
        captures never publish, but may return as stale: waiting for every newer
        flight would starve readers during sustained writes. No retries are needed
        here; first-screen authority/generation checks belong to the caller.
        """
        with self.lock:
            flight_key = (key, revision)
            entry = self.entries.get(key)
            age = self.clock() - entry[0] if entry else float('inf')
            same_revision = bool(entry and entry[2] == revision)
            if entry and revision is not None and entry[2] is not None and entry[2] > revision:
                return entry[1], 'hit' if age < self.fresh else 'stale'
            if not same_revision:
                age = max(age, self.fresh)
            highest = self.requested.get(key)
            if revision is not None and highest is not None and highest[0] is not None and highest[0] > revision:
                newer_key = next((k for k in self.flights if k[0] == key and k[1] == highest[0]), None)
                if newer_key is not None:
                    revision = highest[0]
                    flight_key = newer_key
                    same_revision = False
                    age = max(age, self.fresh)
            if age < self.fresh and not force:
                return entry[1], 'hit'
            flight = self.flights.get(flight_key)
            if flight is None:
                self.sequence += 1
                ticket = self.sequence
                self.requested[key] = (revision, ticket)
                flight = self.executor.submit(copy_context().run, self._build, key, build, revision, ticket)
                self.flights[flight_key] = flight
                def done(future):
                    with self.lock:
                        if self.flights.get(flight_key) is future:
                            self.flights.pop(flight_key, None)
                        if key not in self.entries and self.requested.get(key) == (revision, ticket):
                            self.requested.pop(key, None)
                    if not future.cancelled() and future.exception():
                        logging.getLogger(__name__).warning('read_snapshot_refresh_failed', exc_info=future.exception())
                # Register outside the lock: already-complete futures invoke callbacks inline.
                register = True
            else:
                register = False
        if register:
            flight.add_done_callback(done)
        if allow_stale and not force and same_revision and age < self.stale:
            return entry[1], 'stale'
        value, valid = flight.result()
        with self.lock:
            current = self.entries.get(key)
            if current and revision is not None and current[2] is not None and current[2] > revision:
                return current[1], 'hit'
        return value, 'miss' if valid else 'stale'

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=True)
