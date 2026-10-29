"""Request-local wall/CPU timings; no payloads, SQL text or upstream URLs."""
import asyncio
import gc
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import inspect
import logging
from threading import Lock
from time import perf_counter, thread_time
from uuid import uuid4
from fastapi.routing import APIRoute
from sqlalchemy import event

_current = ContextVar('request_timing', default=None)
_loop_lags = deque(maxlen=2400)
_gc_seconds = 0.0
_gc_started = 0.0


def _gc_timing(phase, info):
    global _gc_seconds, _gc_started
    if phase == 'start':
        _gc_started = perf_counter()
    else:
        _gc_seconds += perf_counter() - _gc_started


gc.callbacks.append(_gc_timing)
delivery_logger = logging.getLogger('backend.delivery')
delivery_logger.setLevel(logging.INFO)


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
                current = _current.get()
                if current:
                    current.add('queue', perf_counter() - current.started)
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
        super().__init__(path, endpoint, **kwargs)
        self.dependant.call = wrapped


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
        if not logging.getLogger().handlers and not delivery_logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter('%(levelname)s:     %(name)s %(message)s'))
            delivery_logger.addHandler(handler)

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        timing = Timings()
        timing.started = scope.get('request_received_at', timing.started)
        gc_before = _gc_seconds
        request_id = uuid4().hex
        token = _current.set(timing)
        scope['request_timing'] = timing
        status = 500
        body_bytes = chunks = 0
        headers_at = first_body_at = None
        send_seconds = 0
        async def timed_send(message):
            nonlocal status, body_bytes, chunks, headers_at, first_body_at, send_seconds
            if message['type'] == 'http.response.start':
                headers_at = perf_counter()
                status = message['status']
                timing.values['gc'] = _gc_seconds - gc_before
                timing.values['looplag'] = max((lag for at, lag in _loop_lags if at >= timing.started), default=0)
                values = {**scope.get('phases', {}), **timing.values}
                for key, value in message.get('headers', []):
                    if key.lower() == b'server-timing':
                        for entry in value.decode().split(','):
                            name, _, duration = entry.strip().partition(';dur=')
                            if duration and name != 'total':
                                values.setdefault(name, float(duration)/1000)
                for name in ('queue', 'identity', 'handler', 'encode'):
                    values.setdefault(name, 0)
                values['total'] = headers_at - timing.started
                timing.header_values = values
                entries = ', '.join(f'{k};dur={v*1000:.1f}' for k, v in values.items() if k != 'queries' and k != 'total')
                entries += f", total;dur={values['total']*1000:.1f}"
                headers = [(k, v) for k, v in message.get('headers', [])
                           if k.lower() not in (b'server-timing', b'x-request-id')]
                headers.extend([(b'server-timing', entries.encode()), (b'x-request-id', request_id.encode())])
                message['headers'] = headers
            if message['type'] == 'http.response.body':
                first_body_at = first_body_at or perf_counter()
                body_bytes += len(message.get('body', b''))
                chunks += 1
            started = perf_counter()
            await send(message)
            send_seconds += perf_counter() - started
        try:
            await self.app(scope, receive, timed_send)
        except Exception:
            if headers_at is None:
                await TimedJSONResponse({'detail': 'Internal Server Error'}, status_code=500)(scope, receive, timed_send)
            raise
        finally:
            elapsed = perf_counter() - timing.started
            if headers_at:
                delivery_logger.info(
                    'request_timing request_id=%s method=%s path=%s status=%s bytes=%s chunks=%s timings_ms=%s complete_ms=%.1f send_ms=%.1f',
                    request_id, scope['method'], scope['path'], status, body_bytes, chunks,
                    {k: round(v if k == 'queries' else v*1000, 1) for k, v in timing.header_values.items()},
                    elapsed*1000, send_seconds*1000)
            if elapsed > 3:
                logging.getLogger('backend.slow').warning(
                    'slow_request request_id=%s method=%s path=%s status=%s total_ms=%.0f timings=%s phases=%s',
                    request_id, scope['method'], scope['path'], status, elapsed*1000,
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


from starlette.responses import JSONResponse as StarletteJSONResponse


class TimedJSONResponse(StarletteJSONResponse):
    def render(self, content):
        with measure('encode'):
            return super().render(content)
