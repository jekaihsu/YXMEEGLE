"""Shared retry classification and a process-wide paced token bucket."""
import math
import random
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import threading
import time

RETRY_CODES = frozenset({99991400, 1254290, 1254607})


class BudgetExceeded(RuntimeError):
    pass


class RetryPolicy:
    max_attempts = 3

    @staticmethod
    def after(response, attempt=1, *, jitter=False):
        names = ('Retry-After', 'x-ogw-ratelimit-reset') if jitter else ('x-ogw-ratelimit-reset', 'Retry-After')
        for name in names:
            try:
                value = float(response.headers[name])
                if math.isfinite(value) and value >= 0:
                    return max(1, value) if response.status_code == 429 else value
            except (KeyError, TypeError, ValueError):
                pass
        try:
            until = parsedate_to_datetime(response.headers['Retry-After'])
            return max(0, (until - datetime.now(timezone.utc)).total_seconds())
        except (KeyError, TypeError, ValueError, OverflowError):
            pass
        delay = min(30, 2 ** (attempt - 1))
        return delay + random.uniform(0, delay * .25) if jitter else delay


class TokenBucket:
    """Capacity one: no initial burst beyond the configured request rate."""
    def __init__(self, max_rps=5, *, clock=time.monotonic, sleep=time.sleep):
        if not math.isfinite(max_rps) or max_rps <= 0:
            raise ValueError('max_rps must be positive and finite')
        self.interval = 1 / min(max_rps, 10)
        self.clock, self.sleep = clock, sleep
        self._next = 0
        self._penalty = 0
        self._lock = threading.Lock()

    def acquire(self, deadline):
        with self._lock:
            now = self.clock()
            reserved = max(now, self._next, self._penalty)
            if reserved >= deadline:
                raise BudgetExceeded('Lark read budget exhausted')
            self._next = reserved + self.interval
        while True:
            delay = max(0, reserved - self.clock())
            if delay:
                self.sleep(delay)
            with self._lock:
                if self.clock() >= deadline:
                    raise BudgetExceeded('Lark read budget exhausted')
                if self._penalty <= reserved:
                    return
                reserved = max(self.clock(), self._next, self._penalty)
                if reserved >= deadline:
                    raise BudgetExceeded('Lark read budget exhausted')
                self._next = reserved + self.interval

    def penalize(self, until):
        with self._lock:
            self._penalty = max(self._penalty, until)
            self._next = max(self._next, until)

    def set_rate(self, max_rps):
        if not math.isfinite(max_rps) or max_rps <= 0:
            raise ValueError('max_rps must be positive and finite')
        with self._lock:
            self.interval = 1 / min(max_rps, 10)


_bucket = None
_lock = threading.Lock()


def process_bucket(max_rps):
    global _bucket
    with _lock:
        if _bucket is None:
            _bucket = TokenBucket(max_rps)
        else:
            _bucket.set_rate(max_rps)
        return _bucket

_table_buckets = {}


def table_bucket(cfg, path, max_rps=2):
    parts = path.split('/')
    if len(parts) < 8 or parts[1:4] != ['bitable', 'v1', 'apps'] or parts[5] != 'tables':
        return None
    key = (cfg.get('LARK_APP_ID'), cfg.get('LARK_WORKER_ORGANIZATION'), parts[4], parts[6])
    with _lock:
        if key not in _table_buckets:
            _table_buckets[key] = TokenBucket(max_rps)
        return _table_buckets[key]

read_slots = threading.BoundedSemaphore(3)
