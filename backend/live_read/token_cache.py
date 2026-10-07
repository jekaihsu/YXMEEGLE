"""Thread-safe tenant-token cache, isolated by application and organization."""
import math
import threading
import time

from .rate_limit import BudgetExceeded


class TokenError(RuntimeError):
    pass


class TenantTokenCache:
    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self._entries = {}
        self._lock = threading.Lock()
        self._key_locks = {}
        self._next_mint = {}

    @staticmethod
    def _key(cfg):
        return tuple(cfg.get(k, '') for k in (
            'LARK_APP_ID', 'LARK_APP_SECRET', 'LARK_WORKER_ORGANIZATION'))

    def get(self, cfg, mint, *, deadline=None):
        """Mint receives credentials and returns the token endpoint JSON body."""
        key = self._key(cfg)
        if not all(key):
            raise TokenError('Lark application credentials are unconfigured')
        with self._lock:
            guard = self._key_locks.setdefault(key, threading.Lock())
        timeout = -1 if deadline is None else max(0, deadline - self.clock())
        if not guard.acquire(timeout=timeout):
            raise BudgetExceeded('Lark read budget exhausted')
        try:
            with self._lock:
                token, expires_at = self._entries.get(key, (None, 0))
                now = self.clock()
                if token and expires_at > now and (expires_at - now >= 35 * 60
                                                  or now < self._next_mint.get(key, 0)):
                    return token
            started = self.clock()
            body = mint({'app_id': key[0], 'app_secret': key[1]})
            token, expire = body.get('tenant_access_token'), body.get('expire')
            if (not isinstance(token, str) or not token or type(expire) not in (int, float)
                    or not math.isfinite(expire) or expire <= 0):
                raise TokenError('Lark token response is incomplete')
            with self._lock:
                self._entries[key] = (token, started + expire)
                # Lark can return the same token with <35 minutes remaining.
                self._next_mint[key] = min(started + expire, started + 60)
            return token
        finally:
            guard.release()

    def invalidate(self, cfg=None, *, token=None):
        with self._lock:
            if cfg is None:
                self._entries.clear()
                self._next_mint.clear()
            else:
                key = self._key(cfg)
                if token is None or self._entries.get(key, (None, 0))[0] == token:
                    self._entries.pop(key, None)
                    self._next_mint.pop(key, None)


process_token_cache = TenantTokenCache()
