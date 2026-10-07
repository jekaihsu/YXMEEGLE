"""Read-only HTTP boundary with a shared token cache and bounded retries."""
import os
import re
import time
from urllib.parse import urlsplit

import httpx

from .. import capability_write_policy
from ..sources import API
from .config import LiveReadConfig
from .rate_limit import BudgetExceeded, RETRY_CODES, RetryPolicy, process_bucket
from .token_cache import TokenError, process_token_cache

ALLOWED_POSTS = (r'/bitable/v1/apps/[^/]+/tables/[^/]+/records/search',)


class ReadFailure(RuntimeError):
    status = 'failed'


class ReadBlocked(ReadFailure):
    status = 'blocked'


class LiveLarkClient:
    def __init__(self, cfg, transport=None, *, clock=time.monotonic, sleep=time.sleep,
                 token_cache=None, bucket=None, allowed_posts=ALLOWED_POSTS):
        self.cfg = cfg
        self.config = LiveReadConfig.from_env(cfg)
        self.clock, self.sleep = clock, sleep
        self.token_cache = token_cache or process_token_cache
        self.bucket = bucket or process_bucket(self.config.max_rps)
        self.allowed_posts = allowed_posts
        self.client = httpx.Client(transport=transport, follow_redirects=False)
        self.started = clock()
        self.deadline = self.started + RetryPolicy.budget_seconds
        self.calls = self.retries = 0
        self.duration_ms = 0
        self.deny_network = transport is None and cfg.get(
            'LARK_LIVE_READ_TRANSPORT', os.environ.get('LARK_LIVE_READ_TRANSPORT')) == 'deny'

    @property
    def metrics(self):
        return dict(calls=self.calls, retries=self.retries, duration_ms=self.duration_ms)

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def request(self, method, path, **kwargs):
        if 'auth' in kwargs:
            raise ReadBlocked('Lark reads require the application token')
        method = method.upper()
        url = urlsplit(path)
        # Accept the absolute API URLs used by legacy fetchers, but no other host.
        if url.scheme or url.netloc:
            if not path.startswith(API + '/'):
                raise ReadBlocked('Lark read URL is outside the API origin')
            path = path[len(API):]
        clean_path = urlsplit(path).path
        protected = capability_write_policy.protected_request(method, path)
        if (protected or not clean_path.startswith('/') or
                (method != 'GET' and not (method == 'POST' and any(
                    re.fullmatch(pattern, clean_path) for pattern in self.allowed_posts)))):
            raise ReadBlocked('Lark request is outside the read allowlist')
        if self.deny_network:
            raise ReadBlocked('Real Lark transport is disabled')
        if self.cfg.get('LARK_WORKER_IDENTITY') != 'application':
            raise ReadBlocked('Lark application identity is required')
        try:
            return self._request(method, path, **kwargs)
        except TokenError as exc:
            raise ReadBlocked(str(exc)) from None
        finally:
            self.duration_ms = max(0, int((self.clock() - self.started) * 1000))

    def _token(self):
        return self.token_cache.get(self.cfg, lambda credentials: self._request(
            'POST', '/auth/v3/tenant_access_token/internal', auth=False, json=credentials).json())

    def _request(self, method, path, *, auth=True, **kwargs):
        renewed = False
        for attempt in range(1, RetryPolicy.max_attempts + 1):
            headers = httpx.Headers(kwargs.get('headers', {}))
            if auth:
                headers['Authorization'] = 'Bearer ' + self._token()
            self.bucket.acquire(self.deadline)
            remaining = self.deadline - self.clock()
            if remaining <= 0:
                raise BudgetExceeded('Lark read budget exhausted')
            options = dict(kwargs, headers=headers, timeout=min(25, remaining), follow_redirects=False)
            self.calls += 1
            try:
                response = self.client.request(method, API + path, **options)
            except httpx.HTTPError:
                raise ReadFailure('Lark read transport failed') from None
            if self.clock() >= self.deadline:
                raise BudgetExceeded('Lark read budget exhausted')
            try:
                body = response.json()
            except ValueError:
                body = {}
            code = body.get('code', 0) if isinstance(body, dict) else None
            if type(code) is not int:
                code = None
            if response.status_code in (401, 403) or code == 1254302:
                raise ReadBlocked('Lark authorization or resource access denied')
            invalid_token = code in (99991663, 99991677)
            retryable = response.status_code == 429 or response.status_code >= 500 or code in RETRY_CODES
            if auth and invalid_token and not renewed and attempt < RetryPolicy.max_attempts:
                self.token_cache.invalidate(self.cfg)
                renewed = True
                self.retries += 1
                continue
            if retryable and attempt < RetryPolicy.max_attempts:
                delay = RetryPolicy.after(response, attempt)
                if self.clock() + delay >= self.deadline:
                    raise BudgetExceeded('Lark read budget exhausted')
                self.retries += 1
                self.sleep(delay)
                continue
            if retryable or invalid_token:
                raise ReadFailure('Lark read attempts exhausted')
            if response.status_code >= 400 or code != 0:
                raise ReadFailure('Lark read rejected')
            if not isinstance(body, dict) or not body:
                raise ReadFailure('Lark response is incomplete')
            return response
