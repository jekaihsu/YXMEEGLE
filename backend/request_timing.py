"""Request-local wall/CPU timings; no payloads, SQL text or upstream URLs."""
import asyncio
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import inspect
import logging
from threading import Lock
from time import perf_counter, thread_time
from fastapi.routing import APIRoute
from sqlalchemy import event

_current = ContextVar('request_timing', default=None)
_loop_lags = deque(maxlen=2400)


class Timings:
    def __init__(self):
        self.started = perf_counter()
        self.values = {}
        self.lock = Lock()

    def add(self, name, seconds):
        with self.lock:
            self.values[name] = self.values.get(name, 0) + seconds


@contextmanager
def measure(name):
    current = _current.get()
    if current is None:
        yield
        return
    started = perf_counter()
    try:
        yield
    finally:
        current.add(name, perf_counter() - started)


@contextmanager
def timed_lock(lock):
    with measure('lockwait'):
        lock.acquire()
    try:
        yield
    finally:
        lock.release()


class TimedRoute(APIRoute):
    def __init__(self, path, endpoint, **kwargs):
        if inspect.iscoroutinefunction(endpoint):
            @wraps(endpoint)
            async def wrapped(*args, **kw):
                with measure('handler'):
                    return await endpoint(*args, **kw)
        else:
            @wraps(endpoint)
            def wrapped(*args, **kw):
                current = _current.get()
                if current:
                    current.add('queue', perf_counter() - current.started)
                cpu = thread_time()
                try:
                    with measure('handler'):
                        return endpoint(*args, **kw)
                finally:
                    if current:
                        current.add('cpu', thread_time() - cpu)
        super().__init__(path, wrapped, **kwargs)


def instrument_database(engine):
    # _do_get includes pool contention, connection establishment and pre-ping.
    # Measure the pool's public connect boundary instead of timing SQL alone.
    connect = engine.pool.connect
    def timed_connect():
        with measure('dbpool'):
            return connect()
    engine.pool.connect = timed_connect

    @event.listens_for(engine, 'before_cursor_execute')
    def before(connection, cursor, statement, parameters, context, executemany):
        context._request_query_started = perf_counter()

    @event.listens_for(engine, 'after_cursor_execute')
    def after(connection, cursor, statement, parameters, context, executemany):
        current = _current.get()
        if current:
            current.add('db', perf_counter() - context._request_query_started)
            current.add('queries', 1)


class RequestTimingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not scope['path'].startswith('/api'):
            return await self.app(scope, receive, send)
        timing = Timings()
        token = _current.set(timing)
        scope['request_timing'] = timing
        status = 500
        async def timed_send(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
                timing.values['looplag'] = max((lag for at, lag in _loop_lags if at >= timing.started), default=0)
                values = dict(timing.values)
                if scope['path'] != '/api/health':
                    entries = ', '.join(f'{k};dur={v*1000:.1f}' for k, v in values.items() if k != 'queries')
                    headers = list(message.get('headers', []))
                    existing = next((v for k, v in headers if k.lower() == b'server-timing'), None)
                    headers = [(k, v) for k, v in headers if k.lower() != b'server-timing']
                    suffix = existing.decode() if existing else f'total;dur={(perf_counter()-timing.started)*1000:.1f}'
                    headers.append((b'server-timing', (entries+', '+suffix).encode()))
                    message['headers'] = headers
            await send(message)
        try:
            await self.app(scope, receive, timed_send)
        finally:
            elapsed = perf_counter() - timing.started
            if elapsed > 3:
                logging.getLogger('backend.slow').warning(
                    'slow_request method=%s path=%s status=%s total_ms=%.0f timings=%s phases=%s',
                    scope['method'], scope['path'], status, elapsed*1000,
                    {k: round(v if k == 'queries' else v*1000) for k, v in timing.values.items()},
                    {k: round(v*1000) for k, v in scope.get('phases', {}).items()})
            _current.reset(token)


async def monitor_loop():
    logger = logging.getLogger('backend.slow')
    while True:
        started = perf_counter()
        await asyncio.sleep(.25)
        lag = max(0, perf_counter() - started - .25)
        _loop_lags.append((perf_counter(), lag))
        if lag > .1:
            logger.warning('event_loop_lag lag_ms=%.0f', lag*1000)
