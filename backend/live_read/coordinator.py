"""Demand-driven refreshes with bounded execution and database lease fencing."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timedelta
from contextvars import ContextVar
from inspect import signature
from threading import Lock, BoundedSemaphore
from time import monotonic, sleep
from uuid import uuid4
import logging

from fastapi import HTTPException

from sqlalchemy import update, event
from sqlalchemy.orm import Session as SQLAlchemySession
from sqlalchemy.exc import IntegrityError

from .client import ReadBlocked
from .config import LiveReadConfig
from .status import DATASETS, TAIPEI, freshness, timestamp, ttl_seconds


logger = logging.getLogger(__name__)
_active_fence = ContextVar('live_read_transaction_fence', default=None)


class LeaseLost(RuntimeError):
    pass


@event.listens_for(SQLAlchemySession, 'before_commit')
def _fence_refresh_transaction(db):
    # Existing services use both ORM flushes and bulk SQL writes. Fencing the
    # commit protects both without changing their callable or service APIs.
    fence = _active_fence.get()
    if fence is not None:
        fence(db)



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
        self._pending = set()

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
        return self._status(wid, DATASETS)

    def _status(self, wid, datasets):
        rows = {}
        for dataset in datasets:
            try:
                rows[dataset] = self._read(self._key(wid, dataset))
            except Exception:
                rows[dataset] = {'last_error': 'Lark refresh failed'}
        workspace_as_of = None
        if not self._enabled(wid):
            from ..models import WorkspaceRow
            with self.Session() as db:
                workspace = db.get(WorkspaceRow, wid)
                workspace_as_of = (workspace.data or {}).get('as_of') if workspace else None
        result = freshness(rows, self.config, self._now(), self._enabled(wid), workspace_as_of)
        for dataset in DATASETS:
            # Snapshot fingerprints and internal exception classes are not public.
            for field in ('fingerprint', 'error_code'):
                result['datasets'][dataset].pop(field, None)
            if dataset not in self.refreshers:
                result['datasets'][dataset]['status'] = 'unconfigured'
        return result

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
        if not force and row.get('error_at') and (now-timestamp(row['error_at'])).total_seconds() < 30:
            return None
        if (not force and not row.get('last_error') and row.get('as_of')
                and (now-timestamp(row['as_of'])).total_seconds() < ttl_seconds(self.config, dataset)):
            return None
        revision = str(uuid4())
        claimed = dict(row, revision=revision,
                       lease_until=(now + timedelta(seconds=self.config.lease_seconds)).isoformat())
        return claimed if self._replace(key, row.get('revision'), claimed) else None

    def _fence(self, db, key, claimed):
        now = self._now()
        stmt = update(self.CacheRow).where(
            self.CacheRow.id == key,
            self.CacheRow.data['revision'].as_string() == claimed['revision'],
            self.CacheRow.data['lease_until'].as_string() > now.isoformat(),
        ).values(data=dict(claimed, lease_until=(now + timedelta(
            seconds=self.config.lease_seconds)).isoformat()))
        # The update takes the lease-row write lock through the apply commit;
        # another owner cannot claim between the fence and workspace commit.
        with db.no_autoflush:
            if db.execute(stmt).rowcount != 1:
                raise LeaseLost('Live-read lease ownership lost')

    def _refresh(self, wid, dataset, key, claimed, started):
        began = monotonic()
        try:
            refresher = self.refreshers[dataset]
            fence = lambda db: self._fence(db, key, claimed)
            context = _active_fence.set(fence)
            try:
                options = {'fence': fence} if 'fence' in signature(refresher).parameters else {}
                result = refresher(wid, **options)
            finally:
                _active_fence.reset(context)
            finished = self._now().isoformat()
            fingerprint = result['fingerprint']
            changed = fingerprint != claimed.get('fingerprint')
            data = dict(claimed, as_of=started.isoformat(), fetched_at=result.get('fetched_at', finished),
                        fingerprint=fingerprint, changed_at=finished if changed else claimed.get('changed_at'),
                        lark=result.get('lark') or dict(calls=0, retries=0, duration_ms=int((monotonic()-began)*1000)),
                        last_error=None, error_at=None, error_code=None, lease_until=None, revision=str(uuid4()))
            if not self._replace(key, claimed['revision'], data):
                raise LeaseLost('Live-read lease ownership lost')
        except Exception as exc:
            blocked = isinstance(exc, ReadBlocked) or (isinstance(exc, HTTPException) and exc.status_code == 403)
            error_code = 'ReadBlocked' if blocked else type(exc).__name__
            detail = exc.detail if isinstance(exc, HTTPException) and isinstance(exc.detail, str) else ''
            logger.warning('Live-read refresh failed: dataset=%s %s status=%s detail=%s duration_ms=%d',
                           dataset, error_code, getattr(exc, 'status_code', None), detail[:160],
                           int((monotonic()-began)*1000))
            if not isinstance(exc, LeaseLost):
                if not self._replace(key, claimed['revision'], dict(claimed, lease_until=None,
                                    revision=str(uuid4()), last_error='Lark refresh failed',
                                    error_code=error_code, error_at=self._now().isoformat())):
                    logger.warning('Live-read lease ownership lost while recording failure')
            raise

    def close(self):
        self.executor.shutdown(wait=True)
        if self.roster_executor is not self.executor:
            self.roster_executor.shutdown(wait=True)

    def ensure(self, wid, dataset, *, wait=False, force=False):
        if dataset not in DATASETS:
            raise ValueError('Unknown live-read dataset')
        deadline = monotonic() + self.config.blocking_timeout_seconds
        while True:
            try:
                result = self._ensure_once(wid, dataset, wait=wait, force=force, deadline=deadline)
            except Exception:
                if wait:
                    raise
                return dict(status='error', last_error='Lark refresh failed')
            if not wait or result['status'] != 'busy':
                return result
            # A pending claimant owns this attempt; retries join its result.
            force = False
            if monotonic() >= deadline:
                raise TimeoutError('Live-read refresh timed out')
            sleep(min(.02, max(0, deadline - monotonic())))

    def _ensure_once(self, wid, dataset, *, wait, force, deadline):
        if dataset not in DATASETS:
            raise ValueError('Unknown live-read dataset')
        if not self._enabled(wid) or dataset not in self.refreshers:
            return dict(self._status(wid, (dataset,))['datasets'][dataset], status='unconfigured')
        slots = self._roster_slots if dataset == 'roster' else self._slots
        executor = self.roster_executor if dataset == 'roster' else self.executor
        key = self._key(wid, dataset)
        row = self._read(key)
        current = self._dataset_status(dataset, row)
        if current['status'] == 'fresh' and not force:
            return current
        now = self._now()
        if force and not wait and current['status'] == 'refreshing':
            return dict(current, status='already_running')
        cooldown = not force and row.get('error_at') and (now-timestamp(row['error_at'])).total_seconds() < 30
        with self._lock:
            future = self._futures.get(key)
            if future is not None and future.done():
                future = None
            pending = key in self._pending
            start = not pending and future is None and current['status'] != 'refreshing' and not cooldown
            if start:
                self._pending.add(key)
        if force and not wait and (pending or future is not None):
            return dict(current, status='already_running')
        if pending:
            # The other local caller is claiming/submitting outside the map lock.
            return dict(current, status='busy' if wait else 'refreshing')
        if start:
            try:
                if not slots.acquire(blocking=False):
                    return dict(current, status='busy')
                try:
                    now = self._now()
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
                        with self._lock:
                            self._futures[key] = future
                    except Exception:
                        slots.release()
                        self._replace(key, claimed['revision'], dict(row, revision=str(uuid4()),
                                      last_error='Lark refresh failed', error_at=now.isoformat()))
                        if wait:
                            raise
                else:
                    slots.release()
            finally:
                with self._lock:
                    self._pending.discard(key)
        if wait:
            timeout = max(0, deadline - monotonic())
            if future:
                try:
                    future.result(timeout=timeout)
                except FutureTimeout as exc:
                    raise TimeoutError('Live-read refresh timed out') from exc
            else:
                while self._dataset_status(dataset, self._read(key))['status'] == 'refreshing':
                    if monotonic() >= deadline:
                        raise TimeoutError('Live-read refresh timed out')
                    sleep(min(0.2, max(0, deadline-monotonic())))
            final = self._dataset_status(dataset, self._read(key))
            if final['status'] == 'blocked':
                raise ReadBlocked('Lark authorization or resource access denied')
            if final['status'] == 'error':
                raise RuntimeError('Lark refresh failed')
        return self._dataset_status(dataset, self._read(key))

    def _dataset_status(self, dataset, row):
        return freshness({dataset: row}, self.config, self._now(), True)['datasets'][dataset]
