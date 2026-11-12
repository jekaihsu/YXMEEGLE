import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from .request_timing import RequestTimingMiddleware, TimedRoute, instrument_database, measure


def test_sync_worker_timings_include_database_and_upstream():
    engine = create_engine('sqlite://')
    instrument_database(engine)
    app = FastAPI()
    app.router.route_class = TimedRoute
    app.add_middleware(RequestTimingMiddleware)

    @app.get('/api/read')
    def read():
        with engine.connect() as connection:
            assert connection.scalar(text('SELECT 1')) == 1
        with measure('upstream'):
            pass
        return {'ok': True}

    @app.get('/api/hidden')
    def hidden():
        raise HTTPException(404, 'missing')

    assert next(route.endpoint for route in app.routes if route.path == '/api/read') is read
    with TestClient(app) as client:
        response = client.get('/api/read')
        denied = client.get('/api/hidden')
        assert denied.status_code == 404
        assert 'server-timing' in denied.headers
        assert denied.headers['x-request-id'] != response.headers['x-request-id']
    assert response.json() == {'ok': True}
    names = {entry.strip().split(';')[0] for entry in response.headers['server-timing'].split(',')}
    assert {'queue', 'handler', 'cpu', 'dbpool', 'db', 'upstream', 'looplag'} <= names


def test_threadpool_wait_is_measured_before_handler():
    import anyio.to_thread
    entered, release = threading.Event(), threading.Event()
    app = FastAPI()
    app.router.route_class = TimedRoute
    app.add_middleware(RequestTimingMiddleware)

    @app.get('/api/block')
    def block():
        entered.set()
        assert release.wait(5)
        return {'ok': True}

    @app.get('/api/read')
    def read():
        return {'ok': True}

    with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as pool:
        async def limit():
            anyio.to_thread.current_default_thread_limiter().total_tokens = 1
        client.portal.call(limit)
        first = pool.submit(client.get, '/api/block')
        assert entered.wait(5)
        second = pool.submit(client.get, '/api/read')
        # The first handler owns the sole worker. Release it from the event loop
        # after the second request has had a chance to queue.
        async def unblock():
            await asyncio.sleep(.08)
            release.set()
        client.portal.call(unblock)
        response = second.result(timeout=5)
        assert first.result(timeout=5).status_code == 200
    timings = dict((part.strip().split(';dur=')[0], float(part.split(';dur=')[1]))
                   for part in response.headers['server-timing'].split(','))
    assert timings['queue'] >= 40
    assert timings['handler'] < timings['queue']


def test_every_response_has_unique_id_and_transport_queue(caplog):
    from time import perf_counter
    from .request_timing import TimedJSONResponse
    app = FastAPI(default_response_class=TimedJSONResponse)
    app.router.route_class = TimedRoute
    app.add_middleware(RequestTimingMiddleware)

    @app.middleware('http')
    async def received(request, call_next):
        request.scope['request_received_at'] = perf_counter() - .05
        return await call_next(request)

    @app.get('/asset')
    def asset():
        return {'ok': True}

    @app.get('/api/health')
    async def health():
        return {'ok': True}

    with TestClient(app) as client:
        responses = [client.get('/asset'), client.get('/api/health'), client.get('/missing')]
    assert len({r.headers['x-request-id'] for r in responses}) == 3
    for response in responses:
        values = dict((part.strip().split(';dur=')[0], float(part.split(';dur=')[1]))
                      for part in response.headers['server-timing'].split(','))
        assert {'queue', 'identity', 'handler', 'encode', 'total'} <= values.keys()
        assert values['total'] >= 50
        assert response.headers['x-request-id'] in caplog.text
    assert values['handler'] == 0  # unmatched route
    assert 'encode;dur=' in responses[0].headers['server-timing']


def test_unhandled_error_still_has_correlation_headers():
    app = FastAPI()
    app.add_middleware(RequestTimingMiddleware)

    @app.get('/error')
    def error():
        raise ValueError('private exception')

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get('/error')
    assert response.status_code == 500
    assert response.headers['x-request-id']
    assert 'total;dur=' in response.headers['server-timing']
    assert 'private exception' not in response.text


def test_uvicorn_transport_records_first_message_timestamp():
    from .request_protocol import TimedHttpToolsProtocol
    # Exercise the real parser with a fragmented HTTP request, then another on
    # the same connection. No application or database startup is required.
    import logging
    import uvicorn
    from unittest.mock import Mock
    from uvicorn.server import ServerState
    from time import perf_counter

    async def run():
        config = uvicorn.Config(FastAPI(), log_config=None)
        config.load()
        protocol = TimedHttpToolsProtocol(config, ServerState(), {})
        protocol.transport = Mock()
        protocol.flow = Mock()
        protocol.server = ('127.0.0.1', 8000)
        protocol.client = ('127.0.0.1', 1234)
        protocol._start_asgi_task = Mock()
        began = perf_counter()
        protocol.data_received(b'GET /api/')
        stamp = protocol.scope['request_received_at']
        protocol.data_received(b'health HTTP/1.1\r\nHost: localhost\r\n\r\n')
        assert began <= stamp <= perf_counter()
        assert protocol.scope['request_received_at'] == stamp
        protocol.cycle.response_complete = True
        protocol.data_received(b'GET / HTTP/1.1\r\nHost: localhost\r\n\r\n')
        assert protocol.scope['request_received_at'] > stamp
        assert protocol._start_asgi_task.call_count == 2
    asyncio.run(run())
