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
        assert 'server-timing' not in denied.headers
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
