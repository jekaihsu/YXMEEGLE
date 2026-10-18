"""Scoped single-flight reads with progressive joins and last-good snapshots."""
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
import time

from ..data_state import data_state
from ..node_assignment.cache import Cached, ReadScope, StaleCache, permission_failure
from .config import DispatchBoardConfig, TABLES
from .domain import BoardInput, Window, build_board
from .lark_table import DispatchReader


@dataclass(frozen=True)
class JoinFlight:
    future: Future
    previous: tuple[Cached | None, str | None]


class DispatchBoardService:
    def __init__(self, cfg, *, reader=None, clock=time.time):
        self.cfg = dict(cfg)
        self.config = DispatchBoardConfig.from_env(cfg)
        self.reader = reader or DispatchReader(cfg)
        self.clock = clock
        self.cache = StaleCache(self.config.ttl_seconds, self.config.stale_max_seconds, clock=clock,
                                max_entries=128)
        self._errors = OrderedDict()
        self._lock = Lock()
        self._joins = OrderedDict()
        self._executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix='dispatch-joins')

    def close(self):
        self._executor.shutdown(wait=True)

    def _scope(self, wid, key='schedule'):
        return ReadScope(str(self.cfg.get('LARK_WORKER_ORGANIZATION', '')),
                         str(self.cfg.get('LARK_APP_ID', '')), str(self.cfg.get('LARK_WORKER_IDENTITY', '')),
                         wid, str(self.cfg.get('LARK_AUTHZ_VERSION', '0')) + ':' + key)

    def _cache_key(self, wid, key):
        table = TABLES[key]
        return self._scope(wid, key).key(self.config.base + '/' + table.table_id, projection=table.fields)

    def _read(self, wid, key):
        cache_key = self._cache_key(wid, key)

        def load():
            try:
                rows = self.reader.read_table(key)
            except Exception as exc:
                with self._lock:
                    self._errors[cache_key] = 'forbidden' if permission_failure(exc) else 'read_failed'
                    if len(self._errors) > 128:
                        self._errors.popitem(last=False)
                raise
            with self._lock:
                self._errors.pop(cache_key, None)
            return rows

        entry = self.cache.get(cache_key, load, revalidate=True)
        with self._lock:
            error = self._errors.get(cache_key)
        return entry, error

    def _join(self, wid, key):
        scope = (self._scope(wid), key)
        previous = (None, None)
        with self._lock:
            current = self._joins.get(scope)
            if current:
                self._joins.move_to_end(scope)
                if not current.future.done():
                    return current.previous
                previous = current.future.result()
                if previous[0] is None or previous[1] is not None:
                    del self._joins[scope]
        if previous[0] is not None and previous[1] is None:
            return self._load_join(wid, key)
        with self._lock:
            current = self._joins.get(scope)
            if current:
                return current.previous
            if len(self._joins) >= 128:
                completed = next((k for k, flight in self._joins.items() if flight.future.done()), None)
                if completed is None:
                    return previous
                del self._joins[completed]
            future = self._executor.submit(self._load_join, wid, key)
            self._joins[scope] = JoinFlight(future, previous)
        return previous

    def _load_join(self, wid, key):
        try:
            entry, error = self._read(wid, key)
            return entry, error
        except Exception:
            return None, 'read_failed'

    def board(self, wid: str, window: Window):
        schedule, failure = self._read(wid, 'schedule')
        if failure == 'forbidden':
            return 403, {'source': {'quality': data_state('forbidden')}}
        joined = {key: self._join(wid, key) for key in ('people', 'instruments', 'vehicles', 'cases')}
        with self._lock:
            joined = {key: (entry, self._errors.get(self._cache_key(wid, key), error))
                      for key, (entry, error) in joined.items()}
        rows = {key: entry.value if entry and not error else None for key, (entry, error) in joined.items()}
        fetched = datetime.fromtimestamp(schedule.fetched_at, timezone.utc).isoformat()
        body = build_board(BoardInput(schedule.value, **rows, fetched_at=fetched), window)
        quality = body['source']['quality']
        stale = schedule.stale or any(entry and entry.stale and not error for entry, error in joined.values())
        if failure:
            quality.update(states=['read_failed'], reason='schedule_refresh_failed')
        elif stale:
            quality['states'] = ['partial', 'stale'] if quality['states'] == ['partial'] else ['stale']
            quality['reason'] = 'refreshing_last_good_snapshot'
        if stale or failure:
            oldest = min([schedule.fetched_at] + [entry.fetched_at for entry, error in joined.values() if entry and not error])
            quality['age_seconds'] = max(0, int(self.clock() - oldest))
        return 200, body
