"""Thread-safe tenant-token cache, isolated by application and organization."""
import math
import threading
import time


class TokenError(RuntimeError):
    pass


class TenantTokenCache:
    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self._entries = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(cfg):
        return tuple(cfg.get(k, '') for k in (
            'LARK_APP_ID', 'LARK_APP_SECRET', 'LARK_WORKER_ORGANIZATION'))

    def get(self, cfg, mint):
        """Mint receives credentials and returns the token endpoint JSON body."""
        key = self._key(cfg)
        if not all(key):
            raise TokenError('Lark application credentials are unconfigured')
        with self._lock:
            token, expires_at = self._entries.get(key, (None, 0))
            if token and expires_at - self.clock() >= 35 * 60:
                return token
            started = self.clock()
            body = mint({'app_id': key[0], 'app_secret': key[1]})
            token, expire = body.get('tenant_access_token'), body.get('expire')
            if (not isinstance(token, str) or not token or type(expire) not in (int, float)
                    or not math.isfinite(expire) or expire <= 0):
                raise TokenError('Lark token response is incomplete')
            self._entries[key] = (token, started + expire)
            return token

    def invalidate(self, cfg=None):
        with self._lock:
            if cfg is None:
                self._entries.clear()
            else:
                self._entries.pop(self._key(cfg), None)


process_token_cache = TenantTokenCache()
