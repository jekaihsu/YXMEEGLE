import logging
import pytest
from . import storage
from .test_p2_int_routes import http, world  # noqa: F401

LIST_ROUTES = ('/api/confirmations', '/api/manager-overview', '/api/source-health')


def full_load_everywhere(monkeypatch):
    full = storage.load
    monkeypatch.setattr(storage, 'load_partial', lambda db, model, row, **_: full(db, model, row))


@pytest.mark.parametrize('route', LIST_ROUTES)
def test_list_read_equals_the_full_load_without_loading_the_whole_workspace(world, monkeypatch, route):
    _, client, _, _, _, _ = world
    with monkeypatch.context() as patched:
        full_load_everywhere(patched)
        expected = client.get(route)
    assert expected.status_code == 200, expected.text
    assert any(row['workflow_summary']['total'] > 0 for row in expected.json()['rows']) if route == '/api/confirmations' else True
    full_loads = []
    full = storage.load
    monkeypatch.setattr(storage, 'load', lambda *a, **kw: (full_loads.append(1), full(*a, **kw))[1])
    actual = client.get(route)
    assert actual.status_code == 200, actual.text
    assert actual.json() == expected.json()
    assert full_loads == []


def test_a_slow_timed_request_still_answers_and_logs_its_phases(world, caplog):
    app, client, _, _, _, _ = world
    app.state.cfg['SLOW_REQUEST_SECONDS'] = '0'
    with caplog.at_level(logging.WARNING, logger='backend.app'):
        response = client.get('/api/confirmations')
    assert response.status_code == 200, response.text
    assert response.headers['Server-Timing'].startswith('identity;dur=')
    slow = [record.getMessage() for record in caplog.records if record.getMessage().startswith('slow_request ')]
    assert slow and 'path=/api/confirmations status=200' in slow[0] and "'read': " in slow[0]
