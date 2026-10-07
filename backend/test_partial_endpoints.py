"""Partial-load endpoints must return exactly what the legacy full load returned.

Legacy behaviour is reproduced by routing ``storage.load_partial`` to the full ``storage.load``.
"""
import pytest

from . import storage
from .test_perf_budget import scaled_client

USERS = ('u-manager', 'u-pm', 'ou_020')


def legacy_and_current(client, monkeypatch, path):
    current = client.get(path)
    with monkeypatch.context() as m:
        m.setattr(storage, 'load_partial', lambda db, model, row, **kw: storage.load(db, model, row))
        legacy = client.get(path)
    return legacy, current


def switch(client, uid):
    assert client.post('/api/demo/session', json={'user_id': uid}).status_code == 200


def test_session_matches_full_load(tmp_path, monkeypatch):
    with scaled_client(tmp_path, 12) as (app, client):
        for uid in USERS:
            switch(client, uid)
            legacy, current = legacy_and_current(client, monkeypatch, '/api/session')
            assert current.status_code == legacy.status_code == 200
            assert current.content == legacy.content
            assert current.json()['users']


PROJECT_QUERIES = ['', '?limit=5', '?offset=3&limit=4', '?offset=500', '?q=a', '?q=ZZZ-none',
                   '?status=in_progress', '?status=nope', '?owner=u-pm', '?owner=ou_006&limit=2',
                   '?q=a&status=in_progress&owner=u-pm&offset=1&limit=3']


@pytest.mark.parametrize('query', PROJECT_QUERIES)
def test_projects_matches_full_load(tmp_path, monkeypatch, query):
    with scaled_client(tmp_path, 12) as (app, client):
        for uid in USERS:
            switch(client, uid)
            legacy, current = legacy_and_current(client, monkeypatch, '/api/projects' + query)
            assert current.status_code == legacy.status_code == 200
            assert current.content == legacy.content
