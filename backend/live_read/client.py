"""Read-only HTTP boundary with a shared token cache and bounded retries."""
import os
import re
import time
from contextvars import ContextVar
from threading import Lock
from urllib.parse import urlsplit, unquote

import httpx

from .. import capability_write_policy
from ..sources import API
from .config import LiveReadConfig
from .rate_limit import BudgetExceeded, RETRY_CODES, RetryPolicy, process_bucket, table_bucket, read_slots
from .token_cache import TokenError, process_token_cache

ALLOWED_POSTS = (r'/bitable/v1/apps/[^/]+/tables/[^/]+/records/search',
                 r'/bitable/v1/apps/[^/]+/tables/[^/]+/records/batch_get',
                 r'/attendance/v1/user_daily_shifts/query',
                 r'/attendance/v1/user_tasks/query', r'/attendance/v1/user_approvals/query')
ALLOWED_GETS = (r'/bitable/v1/apps/[^/]+(?:/.*)?',
                r'/contact/v3/users/batch', r'/attendance/v1/shifts/[^/]+',
                r'/attendance/v1/groups')


refresh_context = ContextVar('live_read_budget', default=None)


class ReadFailure(RuntimeError):
    status = 'failed'

    def __init__(self, message='', *, upstream_status=None, lark_code=None, kind=None):
        super().__init__(message)
        # Non-secret upstream diagnostics only: never headers, tokens or response bodies.
        self.upstream_status, self.lark_code, self.kind = upstream_status, lark_code, kind


class ReadBlocked(ReadFailure):
    status = 'blocked'


class ReadNeedsPermission(ReadBlocked):
    def __init__(self, scopes, **kwargs):
        super().__init__('Lark application needs permission', **kwargs)
        self.missing_scopes = sorted(set(scopes))


class LiveLarkClient:
    def __init__(self, cfg, transport=None, *, clock=time.monotonic, sleep=time.sleep,
                 token_cache=None, bucket=None, allowed_posts=ALLOWED_POSTS):
        self.cfg = cfg
        self.config = LiveReadConfig.from_env(cfg)
        self.clock, self.sleep = clock, sleep
        self.token_cache = token_cache or process_token_cache
        self.bucket = bucket or process_bucket(self.config.max_rps)
        self.allowed_posts = allowed_posts
        self._shared_limits = bucket is None
        self._metrics_lock = Lock()
        self.context = refresh_context.get()
        self.client = httpx.Client(transport=transport, follow_redirects=False)
        self.started = clock()
        self.deadline = self.started + min(self.config.budget_seconds, self.config.lease_seconds - 10)
        if self.context:
            self.deadline = min(self.deadline, self.context['deadline'])
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
        decoded = clean_path
        while unquote(decoded) != decoded:
            decoded = unquote(decoded)
        if '\\' in decoded or any(part in ('.', '..') for part in decoded.split('/')):
            raise ReadBlocked('Lark request is outside the read allowlist')
        protected = capability_write_policy.protected_request(method, path)
        if (protected or not clean_path.startswith('/') or
                (method == 'GET' and not any(re.fullmatch(pattern, clean_path) for pattern in ALLOWED_GETS)) or
                (method != 'GET' and not (method == 'POST'
                    and any(re.fullmatch(pattern, clean_path) for pattern in ALLOWED_POSTS)
                    and any(re.fullmatch(pattern, clean_path) for pattern in self.allowed_posts)))):
            raise ReadBlocked('Lark request is outside the read allowlist')
        if self.deny_network:
            raise ReadBlocked('Real Lark transport is disabled')
        if self.cfg.get('LARK_WORKER_IDENTITY') != 'application':
            raise ReadBlocked('Lark application identity is required')
        if clean_path.startswith('/attendance/'):
            self.deadline = min(self.deadline, self.started + self.config.dataset_budget('attendance'))
        try:
            return self._request(method, path, **kwargs)
        except TokenError as exc:
            raise ReadBlocked(str(exc)) from None
        finally:
            self.duration_ms = max(0, int((self.clock() - self.started) * 1000))

    def _token(self):
        return self.token_cache.get(self.cfg, lambda credentials: self._request(
            'POST', '/auth/v3/tenant_access_token/internal', auth=False, json=credentials).json(), deadline=self.deadline)

    def _request(self, method, path, *, auth=True, **kwargs):
        renewed = False
        for attempt in range(1, RetryPolicy.max_attempts + 1):
            headers = httpx.Headers(kwargs.get('headers', {}))
            if auth:
                token = self._token()
                headers['Authorization'] = 'Bearer ' + token
            local_bucket = table_bucket(self.cfg, path, self.config.table_rps) if self._shared_limits else None
            if local_bucket:
                local_bucket.acquire(self.deadline)
            self.bucket.acquire(self.deadline)
            remaining = self.deadline - self.clock()
            if remaining <= 0:
                raise BudgetExceeded('Lark read budget exhausted')
            options = dict(kwargs, headers=headers, timeout=min(self.config.request_timeout_seconds, remaining), follow_redirects=False)
            with self._metrics_lock:
                self.calls += 1
            if self.context:
                with self.context['lock']:
                    self.context['calls'] += 1
            if not read_slots.acquire(timeout=max(0, self.deadline - self.clock())):
                raise BudgetExceeded('Lark read budget exhausted')
            try:
                options['timeout'] = min(self.config.request_timeout_seconds, max(.001, self.deadline - self.clock()))
                response = self.client.request(method, API + path, **options)
            except httpx.HTTPError:
                raise ReadFailure('Lark read transport failed', kind='transient') from None
            finally:
                read_slots.release()
            if self.clock() >= self.deadline:
                raise BudgetExceeded('Lark read budget exhausted')
            try:
                body = response.json()
            except ValueError:
                body = {}
            code = body.get('code', 0) if isinstance(body, dict) else None
            if type(code) is not int:
                code = None
            invalid_token = code in (99991663, 99991677)
            retryable = response.status_code == 429 or response.status_code >= 500 or code in RETRY_CODES
            if auth and invalid_token and not renewed and attempt < RetryPolicy.max_attempts:
                self.token_cache.invalidate(self.cfg, token=token)
                renewed = True
                self.retries += 1
                continue
            if code == 99991672:
                violations=(body.get('error') or {}).get('permission_violations') or []
                candidates=[v.get('subject','') for v in violations if isinstance(v,dict)]
                candidates+=re.findall(r'[a-z][a-z0-9_.]*(?::[a-z][a-z0-9_.]*)+',str(body.get('msg','')))
                scopes=[v for v in candidates if isinstance(v,str) and re.fullmatch(
                    r'[a-z][a-z0-9_.]*(?::[a-z][a-z0-9_.]*)+',v)]
                if not scopes:
                    scopes=(['bitable:app:readonly'] if '/bitable/' in path else
                            ['contact:contact.base:readonly','contact:user.employee_id:readonly'] if '/contact/' in path else
                            ['attendance:rule:readonly' if '/shifts/' in path or path == '/attendance/v1/groups' else 'attendance:task:readonly'] if '/attendance/' in path else [])
                raise ReadNeedsPermission(scopes, upstream_status=response.status_code,
                                          lark_code=code, kind='needs-permission')
            if code == 1254302 or (response.status_code in (401, 403) and not invalid_token):
                raise ReadBlocked('Lark authorization or resource access denied', upstream_status=response.status_code,
                                  lark_code=code, kind='permission_denied')
            if retryable and attempt < RetryPolicy.max_attempts:
                delay = RetryPolicy.after(response, attempt, jitter=self.config.enabled)
                if response.status_code == 429 or code in RETRY_CODES:
                    delay = max(1, delay)
                    self.bucket.penalize(self.clock() + delay)
                if self.clock() + delay >= self.deadline:
                    raise BudgetExceeded('Lark read budget exhausted')
                self.retries += 1
                self.sleep(delay)
                continue
            if retryable or invalid_token:
                raise ReadFailure('Lark read attempts exhausted', upstream_status=response.status_code,
                                  lark_code=code, kind='transient')
            if response.status_code >= 400 or code != 0:
                raise ReadFailure('Lark read rejected', upstream_status=response.status_code, lark_code=code,
                                  kind='field_not_found' if code == 1254045 else 'rejected')
            if not isinstance(body, dict) or not body:
                raise ReadFailure('Lark response is incomplete')
            if self.context and isinstance(body.get('data'), dict) and (
                    '/records' in path or path.endswith('/query') or path == '/contact/v3/users/batch'):
                data = body['data']
                rows = data.get('items', data.get('records', data.get('user_daily_shifts', [])))
                with self.context['lock']:
                    if isinstance(rows, list):
                        self.context['pages'] += 1
                        self.context['records'] += len(rows)
            return response
