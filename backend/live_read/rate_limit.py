"""Shared retry classification and a process-wide paced token bucket."""
import math
import threading
import time

RETRY_CODES = frozenset({99991400, 1254290, 1254607})


class BudgetExceeded(RuntimeError):
    pass


class RetryPolicy:
    max_attempts = 3
    budget_seconds = 45

    @staticmethod
    def after(response, attempt=1):
        for name in ('x-ogw-ratelimit-reset', 'Retry-After'):
            try:
                value = float(response.headers[name])
                if math.isfinite(value) and value >= 0:
                    return max(1, value) if response.status_code == 429 else value
            except (KeyError, TypeError, ValueError):
                pass
        return min(30, 2 ** (attempt - 1))


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
