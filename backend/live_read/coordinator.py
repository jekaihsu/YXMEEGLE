"""Demand-driven refreshes with bounded execution and database lease fencing."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timedelta
from threading import Lock, BoundedSemaphore
from time import monotonic, sleep
from uuid import uuid4

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from .config import LiveReadConfig
from .status import DATASETS, TAIPEI, freshness, timestamp, ttl_seconds


class RefreshCoordinator:
    def __init__(self, Session, CacheRow, refreshers, cfg, executor=None, clock=None):
        self.Session, self.CacheRow = Session, CacheRow
        self.refreshers, self.cfg = refreshers, cfg
        self.config = LiveReadConfig.from_env(cfg)
        self.executor = executor if executor is not None else ThreadPoolExecutor(max_workers=2)
        self.roster_executor = (ThreadPoolExecutor(max_workers=1)
                                if executor is None or isinstance(executor, ThreadPoolExecutor)
                                else executor)
        self._roster_slots = BoundedSemaphore(1)
        self.clock = clock or (lambda: datetime.now(TAIPEI))
        self._lock, self._slots, self._futures = Lock(), BoundedSemaphore(2), {}

    def _enabled(self, wid):
        return (self.config.enabled
                and self.cfg.get('LARK_WORKER_IDENTITY') == 'application'
                and not wid.startswith(('demo-', 'test-')))

    def _now(self):
        return timestamp(self.clock())

    def _key(self, wid, dataset):
        return f'live:{wid}:{dataset}'

    def _read(self, key):
        with self.Session() as db:
            row = db.get(self.CacheRow, key)
            return dict(row.data or {}) if row else {}

    def status(self, wid):
        rows = {d: self._read(self._key(wid, d)) for d in DATASETS}
        workspace_as_of = None
        if not self._enabled(wid):
            from ..models import WorkspaceRow
            with self.Session() as db:
                workspace = db.get(WorkspaceRow, wid)
                workspace_as_of = (workspace.data or {}).get('as_of') if workspace else None
        return freshness(rows, self.config, self._now(), self._enabled(wid), workspace_as_of)

    @property
    def queue_depth(self):
        with self._lock:
            return sum(not future.done() for future in self._futures.values())

    def _replace(self, key, previous, data):
        """CAS the revision, including on completion, to fence expired owners."""
        with self.Session.begin() as db:
            stmt = update(self.CacheRow).where(self.CacheRow.id == key)
            revision = self.CacheRow.data['revision'].as_string()
            stmt = stmt.where(revision == previous) if previous else stmt.where(revision.is_(None))
            return db.execute(stmt.values(data=data)).rowcount == 1

    def _claim(self, key, now, dataset, force):
        row = self._read(key)
        if not row:
            try:
                with self.Session.begin() as db:
                    db.add(self.CacheRow(id=key, data={'revision': str(uuid4())}))
            except IntegrityError:
                pass
            row = self._read(key)
        if row.get('lease_until') and timestamp(row['lease_until']) > now:
            return None
        if row.get('error_at') and (now-timestamp(row['error_at'])).total_seconds() < 30:
            return None
        if (not force and not row.get('last_error') and row.get('as_of')
                and (now-timestamp(row['as_of'])).total_seconds() < ttl_seconds(self.config, dataset)):
            return None
        revision = str(uuid4())
        claimed = dict(row, revision=revision,
                       lease_until=(now + timedelta(seconds=self.config.lease_seconds)).isoformat())
        return claimed if self._replace(key, row.get('revision'), claimed) else None

    def _refresh(self, wid, dataset, key, claimed, started):
        began = monotonic()
        try:
            result = self.refreshers[dataset](wid)
            finished = self._now().isoformat()
            fingerprint = result['fingerprint']
            changed = fingerprint != claimed.get('fingerprint')
            data = dict(claimed, as_of=started.isoformat(), fetched_at=result.get('fetched_at', finished),
                        fingerprint=fingerprint, changed_at=finished if changed else claimed.get('changed_at'),
                        lark=result.get('lark') or dict(calls=0, retries=0, duration_ms=int((monotonic()-began)*1000)),
                        last_error=None, error_at=None, lease_until=None, revision=str(uuid4()))
            self._replace(key, claimed['revision'], data)
        except Exception:
            self._replace(key, claimed['revision'], dict(claimed, lease_until=None,
                          revision=str(uuid4()), last_error='Lark refresh failed', error_at=self._now().isoformat()))
            raise

    def close(self):
        self.executor.shutdown(wait=True)
        if self.roster_executor is not self.executor:
            self.roster_executor.shutdown(wait=True)

    def ensure(self, wid, dataset, *, wait=False, force=False):
        deadline = monotonic() + self.config.blocking_timeout_seconds
        while True:
            result = self._ensure_once(wid, dataset, wait=wait, force=force, deadline=deadline)
            if not wait or result['status'] != 'busy':
                return result
            if monotonic() >= deadline:
                raise TimeoutError('Live-read refresh timed out')
            sleep(min(.02, max(0, deadline - monotonic())))

    def _ensure_once(self, wid, dataset, *, wait, force, deadline):
        if dataset not in DATASETS:
            raise ValueError('Unknown live-read dataset')
        if not self._enabled(wid) or dataset not in self.refreshers:
            return dict(self.status(wid)['datasets'][dataset], status='unconfigured')
        slots = self._roster_slots if dataset == 'roster' else self._slots
        executor = self.roster_executor if dataset == 'roster' else self.executor
        key, now = self._key(wid, dataset), self._now()
        future = None
        with self._lock:
            row = self._read(key)
            current = self.status(wid)['datasets'][dataset]
            future = self._futures.get(key)
            if future is not None and future.done():
                future = None
            running = current['status'] == 'refreshing'
            cooldown = row.get('error_at') and (now-timestamp(row['error_at'])).total_seconds() < 30
            if not running and not cooldown and (force or current['status'] != 'fresh'):
                if not slots.acquire(blocking=False):
                    return dict(current, status='busy')
                try:
                    claimed = self._claim(key, now, dataset, force)
                except Exception:
                    slots.release()
                    if wait:
                        raise
                    return dict(current, status='error', last_error='Lark refresh failed')
                if claimed:
                    try:
                        future = executor.submit(self._refresh, wid, dataset, key, claimed, now)
                        future.add_done_callback(lambda _: slots.release())
                        self._futures[key] = future
                    except Exception:
                        slots.release()
                        self._replace(key, claimed['revision'], dict(row, revision=str(uuid4()),
                                      last_error='Lark refresh failed', error_at=now.isoformat()))
                        if wait:
                            raise
                else:
                    slots.release()
        if wait:
            timeout = max(0, deadline - monotonic())
            if future:
                try:
                    future.result(timeout=timeout)
                except FutureTimeout as exc:
                    raise TimeoutError('Live-read refresh timed out') from exc
            else:
                while self.status(wid)['datasets'][dataset]['status'] == 'refreshing':
                    if monotonic() >= deadline:
                        raise TimeoutError('Live-read refresh timed out')
                    sleep(min(0.02, max(0, deadline-monotonic())))
            if self.status(wid)['datasets'][dataset]['status'] == 'error':
                raise RuntimeError('Lark refresh failed')
        return self.status(wid)['datasets'][dataset]
