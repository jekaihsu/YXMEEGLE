"""Freshness mitigation through the registered route, with no real HTTP."""
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from . import app as app_module, production_access
from .app import AuthRow, NO_ROSTER_REFRESH_PATHS, WorkspaceRow
from .lark_pilot import routes
from .test_lark_pilot_integrated import integrated, profile, PATH


@pytest.fixture
def clock(integrated, monkeypatch):
    now = datetime.now(timezone.utc)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz else now.replace(tzinfo=None)
    for module in (routes, app_module, production_access):
        monkeypatch.setattr(module, 'datetime', Clock, raising=False)
    return now


@pytest.mark.parametrize('age,ttl,expected', [
    (30, '60', 200), (60, '60', 200), (60.001, '60', 403),
    (61, '60', 403), (899, '60', 403), (901, '60', 403),
    (120, '600', 403), (30, '30', 200), (30.001, '30', 403),
    (30, 'invalid', 403), (30, 'nan', 403), (30, 'inf', 403),
])
def test_R_A_D_registered_freshness_ceiling(integrated, clock, monkeypatch, age, ttl, expected):
    app, client, calls, refreshes, _ = integrated
    app.state.cfg['LARK_LIVE_READ_ROSTER_TTL_SECONDS'] = ttl
    profile(app, directory_last_seen_at=(clock-timedelta(seconds=age)).isoformat())
    reader = Mock(wraps=routes.PilotReader)
    monkeypatch.setattr(routes, 'PilotReader', reader)
    endpoint = next(r.endpoint for r in app.routes if r.path == PATH)
    cell = dict(zip(endpoint.__code__.co_freevars, endpoint.__closure__))['authorize']
    authorize = Mock(wraps=cell.cell_contents)
    cell.cell_contents = authorize
    response = client.get(PATH)
    assert response.status_code == expected, response.text
    assert authorize.call_count == (0 if expected == 403 else 1)
    assert response.headers['cache-control'] == 'no-store'
    assert refreshes == []
    if expected == 403:
        if age <= 900:
            assert '唯讀試行期限' in response.text
        assert calls == [] and reader.call_count == 0
    else:
        assert response.json()['source'] == 'mock' and len(calls) == 4


@pytest.mark.parametrize('kind', ['missing', 'empty', 'garbage', 'naive', 'future1', 'futureday'])
def test_R_G_invalid_evidence(integrated, clock, monkeypatch, kind):
    app, client, calls, refreshes, _ = integrated
    stamp = {'missing': None, 'empty': '', 'garbage': 'SYN_invalid',
        'naive': clock.replace(tzinfo=None).isoformat(),
        'future1': (clock+timedelta(seconds=1)).isoformat(),
        'futureday': (clock+timedelta(days=1)).isoformat()}[kind]
    profile(app, directory_last_seen_at=stamp)
    reader = Mock(wraps=routes.PilotReader)
    monkeypatch.setattr(routes, 'PilotReader', reader)
    response = client.get(PATH)
    assert response.status_code == 403
    assert response.headers['cache-control'] == 'no-store'
    assert calls == [] and refreshes == [] and reader.call_count == 0


@pytest.mark.parametrize('kind,expected', [('no_session', 401), ('expired', 401),
    ('unknown', 403), ('inactive', 403), ('missing_roster', 403), ('left', 403),
    ('non_admin', 403), ('demo', 404), ('test', 404), ('non_lark', 404), ('off', 404)])
def test_R_E_F_I_existing_guards(integrated, clock, monkeypatch, kind, expected):
    app, client, calls, refreshes, _ = integrated
    if kind == 'no_session':
        client.cookies.clear()
    elif kind == 'expired':
        with app.state.sessions.begin() as db:
            row = db.get(AuthRow, 'sid')
            row.data = {**row.data, 'expires': 0}
    elif kind in {'demo', 'test', 'non_lark'}:
        data = {'mode': 'SYN_non_lark' if kind == 'non_lark' else 'lark',
                'wid': {'demo': 'demo-SYN', 'test': 'test-lark-company'}.get(kind, 'lark-company')}
        with app.state.sessions.begin() as db:
            row = db.get(AuthRow, 'sid')
            row.data = {**row.data, 'wid': data['wid']}
            if kind == 'demo':
                db.add(WorkspaceRow(id=data['wid'], version=1, data=db.get(WorkspaceRow, 'lark-company').data))
        client.cookies.clear()
        client.cookies.set('meegle_session', app.state.signer.dumps({**data, 'sid': 'sid',
            'organization': 'lark-company', 'uid': 'u-manager'}))
    elif kind == 'off':
        app.state.cfg['LARK_PILOT_READONLY_ENABLED'] = 'false'
    else:
        changes = {'unknown': {'directory_status': 'unknown'}, 'inactive': {'active': False},
            'missing_roster': {'directory_missing': True}, 'left': {'directory_status': 'left'},
            'non_admin': {'role': 'member', 'capabilities': []}}[kind]
        profile(app, bootstrap_admin=False, directory_last_seen_at=clock.isoformat(), **changes)
    reader = Mock(wraps=routes.PilotReader)
    monkeypatch.setattr(routes, 'PilotReader', reader)
    response = client.get(PATH)
    assert response.status_code == expected, response.text
    assert calls == [] and refreshes == [] and reader.call_count == 0
    if kind in {'unknown', 'inactive', 'missing_roster', 'left'}:
        assert '尚未核實' in response.text


def test_R_H_exemption_unchanged():
    assert NO_ROSTER_REFRESH_PATHS == {'/api/live/status', PATH}
    assert PATH+'/x' not in NO_ROSTER_REFRESH_PATHS


def test_R_H_registered_adjacent_route_refreshes(integrated, clock):
    app, client, calls, refreshes, _ = integrated
    profile(app, directory_last_seen_at=(clock-timedelta(seconds=90)).isoformat())
    assert client.get('/api/session').status_code == 200
    assert refreshes == ['lark-company'] and calls == []


def test_R_I_flag_off_precedes_identity(integrated):
    app, client, calls, refreshes, _ = integrated
    app.state.cfg['LARK_PILOT_READONLY_ENABLED'] = 'false'
    endpoint = next(r.endpoint for r in app.routes if r.path == PATH)
    cell = dict(zip(endpoint.__code__.co_freevars, endpoint.__closure__))['identity']
    original = cell.cell_contents
    identity = Mock(side_effect=AssertionError('identity called while disabled'))
    cell.cell_contents = identity
    try:
        assert client.get(PATH).status_code == 404
        assert identity.call_count == 0 and calls == [] and refreshes == []
    finally:
        cell.cell_contents = original
