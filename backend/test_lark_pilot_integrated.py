"""Registered candidate uses real admission/authorization, synthetic Lark only."""
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import event

from .app import AuditRow, PersonRow
from .lark_pilot import routes
from .lark_pilot.sample import PilotReader
from .live_read.token_cache import TenantTokenCache
from .test_production_access import company

PATH = '/api/lark-pilot/shadow'


@pytest.fixture
def integrated(tmp_path, monkeypatch):
    app, client = company(tmp_path, {'LARK_PILOT_READONLY_ENABLED': 'true',
        'LARK_LIVE_READ_ENABLED': 'true', 'LARK_WORKER_IDENTITY': 'application',
        'LARK_LIVE_READ_TRANSPORT': 'deny'})
    assert client.post('/api/workspace/switch', json={'environment': 'production'}).status_code == 200
    assert client.get('/api/live/status').status_code == 200
    calls, refreshes, mutations = [], [], []
    def transport(request):
        calls.append((request.method, request.url.path))
        data = {'code': 0, 'tenant_access_token': 'SYN_token', 'expire': 7200} if '/auth/' in request.url.path else {'code': 0, 'data': {'items': []}}
        return httpx.Response(200, json=data)
    monkeypatch.setattr(routes, 'PilotReader', lambda cfg: PilotReader(cfg,
        transport=httpx.MockTransport(transport), token_cache=TenantTokenCache()))
    app.state.live_read.refreshers['roster'] = lambda wid: refreshes.append(wid) or {'fingerprint': 'SYN'}
    engine = app.state.sessions.kw['bind']
    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().split()[0].upper() in {'INSERT', 'UPDATE', 'DELETE'}:
            mutations.append(statement)
    event.listen(engine, 'before_cursor_execute', record)
    yield app, client, calls, refreshes, mutations
    event.remove(engine, 'before_cursor_execute', record)
    client.close()
    app.state.live_read.close()
    engine.dispose()


def profile(app, **changes):
    with app.state.sessions.begin() as db:
        row = db.get(PersonRow, ('lark-company', 'u-manager'))
        row.data = {**row.data, **changes}


@pytest.mark.parametrize('changes,expected', [({}, 200),
    ({'directory_last_seen_at': (datetime.now(timezone.utc)-timedelta(seconds=901)).isoformat()}, 403),
    ({'directory_status': 'unknown', 'bootstrap_admin': False}, 403),
    ({'active': False}, 403), ({'directory_missing': True, 'bootstrap_admin': False}, 403),
    ({'identity_app_id': 'SYN_wrong_app'}, 403),
    ({'role': 'member', 'capabilities': [], 'bootstrap_admin': False}, 403),
    ({'role': 'member', 'capabilities': ['manage_sources'], 'bootstrap_admin': False}, 200)])
def test_registered_E19_E21_admission_and_source_authority(integrated, changes, expected):
    app, client, calls, refreshes, mutations = integrated
    profile(app, **changes)
    mutations.clear()
    response = client.get(PATH)
    assert response.status_code == expected, response.text
    assert refreshes == []
    assert mutations == []
    if expected == 403:
        assert calls == []
    else:
        assert response.headers['cache-control'] == 'no-store'
        assert response.json()['source'] == 'mock'
        assert len(calls) == 4  # Token, tables, one-record preflight, capped cases.


def test_registered_E13_preserves_one_time_identity_maintenance(integrated):
    app, client, _, refreshes, mutations = integrated
    profile(app, company_admin_authorization={'grant_id': 'SYN_removed'})
    mutations.clear()
    assert client.get(PATH).status_code == 200
    assert mutations
    assert all((PersonRow.__tablename__ in sql or AuditRow.__tablename__ in sql) for sql in mutations)
    assert refreshes == []
    mutations.clear()
    assert client.get(PATH).status_code == 200
    assert mutations == []
