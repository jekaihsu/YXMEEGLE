"""Live pagination must survive cold overlays and ordinary writes."""
import os
from uuid import uuid4
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy import select
from . import storage
from .models import WorkspaceRow, BusinessRow
from .test_perf_budget import scaled_client
from .test_shell import ON


@pytest.fixture(params=['sqlite', 'postgresql'])
def database(request):
    if request.param == 'sqlite':
        yield {}
        return
    url = os.environ.get('AI_TEST_POSTGRES_URL')
    if not url:
        pytest.skip('AI_TEST_POSTGRES_URL disposable PostgreSQL not configured')
    engine = create_engine(url)
    schema = 'live1_' + uuid4().hex
    with engine.begin() as db:
        db.execute(text(f'CREATE SCHEMA {schema}'))
    try:
        yield {'DATABASE_URL': str(make_url(url).update_query_dict({'options': f'-csearch_path={schema}'}))}
    finally:
        with engine.begin() as db:
            db.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        engine.dispose()


@pytest.mark.parametrize('scenario' , ['cold', 'write_during', 'write_after', 'cache_loss'])
def test_portfolio_sequence_survives_lost_retention(tmp_path, monkeypatch, scenario, database):
    with scaled_client(tmp_path, 65, **ON, **database) as (app, client):
        def change():
            with app.state.sessions.begin() as db:
                row = db.scalars(select(WorkspaceRow)).first()
                wid = row.id
                state = storage.load(db, BusinessRow, row)
                state['projects'][0]['name'] = 'Updated case'
                row.version += 1
                state['version'] = row.version
                row.data = storage.save(db, BusinessRow, row.id, state)
            app.state.read_snapshots.invalidate(wid)
        monkeypatch.setattr(app.state.home_panels, 'assignment_unavailable', lambda *_: False)
        calls = []
        def overlay(*_):
            calls.append(1)
            if scenario == 'write_during' and len(calls) == 1:
                change()
            return {}, scenario == 'cold'
        monkeypatch.setattr(app.state.home_panels, 'portfolio_overlay', overlay)
        response = client.get('/api/projects?view=portfolio&page=1')
        first = response.json()
        if scenario in ('cold', 'write_during'):
            assert first['stale'] is True
            assert response.headers['x-read-snapshot'] == 'stale'
        if scenario == 'write_after':
            change()
        if scenario == 'cache_loss':
            app.state.read_snapshots.invalidate()
            if hasattr(app.state, 'portfolio_captures'):
                app.state.portfolio_captures.clear()
        second = client.get('/api/projects', params=dict(view='portfolio', page=2, snapshot=first['snapshot']))
        assert second.status_code == 200
        body = second.json()
        if body.get('snapshot_replaced'):
            assert body['page'] == 1 and body['next_page'] is None
            assert len(body['items']) == body['total'] == 65
            assert body['stale'] is True
        else:
            assert body['snapshot'] == first['snapshot']
            assert not set(p['id'] for p in first['items']) & set(p['id'] for p in body['items'])
            third = client.get('/api/projects', params=dict(view='portfolio',page=3,snapshot=first['snapshot'])).json()
            assert len(first['items'] + body['items'] + third['items']) == 65
        if scenario != 'cold':
            assert second.headers['x-read-snapshot'] == 'stale'


def test_capture_bounds_expiry_and_authority_isolation():
    from .projects_portfolio import PortfolioCaptures
    from .read_snapshots import EncodedSnapshot
    clock = [0]
    captures = PortfolioCaptures(clock=lambda: clock[0], max_bytes=1000, ttl=5)
    body = EncodedSnapshot.encode(b'{"items":[]}', volatile=True)
    captures.put(('portfolio', 'X', 'manager'), body, 1)
    assert captures.get(('portfolio', 'X', 'manager'), body.etag) == (body, 1)
    assert captures.get(('portfolio', 'Y', 'manager'), body.etag) is None
    assert captures.get(('portfolio', 'X', 'member'), body.etag) is None
    clock[0] = 5
    assert captures.get(('portfolio', 'X', 'manager'), body.etag) is None
    captures.put('oversize', EncodedSnapshot.encode(b'x' * 2000), 1)
    assert not captures.entries


def test_portfolio_get_does_not_write_workspace(tmp_path):
    from sqlalchemy import event
    with scaled_client(tmp_path, 35, **ON) as (app, client):
        writes = []
        def observe(_conn, _cursor, statement, *_):
            if statement.lstrip().split()[0].upper() in ('UPDATE', 'INSERT', 'DELETE'):
                writes.append(statement.split()[0])
        event.listen(app.state.engine, 'before_cursor_execute', observe)
        try:
            first = client.get('/api/projects?view=portfolio&page=1').json()
            assert client.get('/api/projects', params=dict(view='portfolio', page=2, snapshot=first['snapshot'])).status_code == 200
            assert writes == []
        finally:
            event.remove(app.state.engine, 'before_cursor_execute', observe)
