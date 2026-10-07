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
                    return value
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
        self._lock = threading.Lock()

    def acquire(self, deadline):
        with self._lock:
            now = self.clock()
            delay = max(0, self._next - now)
            if now + delay >= deadline:
                raise BudgetExceeded('Lark read budget exhausted')
            if delay:
                self.sleep(delay)
            self._next = self.clock() + self.interval


_buckets = {}
_lock = threading.Lock()


def process_bucket(max_rps):
    with _lock:
        return _buckets.setdefault(max_rps, TokenBucket(max_rps))
