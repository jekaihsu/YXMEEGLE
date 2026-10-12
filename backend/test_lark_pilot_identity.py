"""Pilot identity regression through the existing, unmodified auth helper.

Until the approved router is registered, expose that helper at the exact pilot
path in this synthetic app. This isolates the roster-hook bug without bypassing
cookie, session, admission or production-access guards.
"""
from datetime import datetime, timedelta, timezone
from inspect import getclosurevars

import pytest
from fastapi import Request
from sqlalchemy import event

from .app import AuthRow, PersonRow
from .test_live_read_routes import production_client

PATH = '/api/lark-pilot/shadow'


@pytest.fixture
def pilot_identity(tmp_path):
    app, client = production_client(tmp_path)
    status = next(r.endpoint for r in app.routes if r.path == '/api/live/status')
    identity = getclosurevars(status).nonlocals['identity']

    @app.get(PATH)
    def probe(request: Request):
        data, user = identity(request)
        return {'wid': data['wid'], 'actor': user['id']}

    # Build output installs a SPA catch-all. Keep this synthetic probe before it.
    app.router.routes.insert(0, app.router.routes.pop())

    # Settle existing one-time identity maintenance before recording mutations.
    assert client.get('/api/live/status').status_code == 200
    refreshes, mutations = [], []

    def refresh(wid):
        refreshes.append(wid)
        return {'fingerprint': 'SYN_roster'}

    app.state.live_read.refreshers['roster'] = refresh
    engine = app.state.sessions.kw['bind']

    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().split()[0].upper() in {'INSERT', 'UPDATE', 'DELETE'}:
            mutations.append(statement.split(' VALUES')[0].split(' SET')[0])

    event.listen(engine, 'before_cursor_execute', record)
    yield app, client, refreshes, mutations
    event.remove(engine, 'before_cursor_execute', record)
    client.close()
    engine.dispose()


def age_person(app, seconds, **changes):
    with app.state.sessions.begin() as db:
        row = db.get(PersonRow, ('lark-company', 'u-manager'))
        row.data = {**row.data, 'directory_last_seen_at': (
            datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat(), **changes}


@pytest.mark.parametrize('age,expected', [(90, 200), (901, 403)])
def test_E19_pilot_does_not_refresh_and_stale_access_fails_closed(pilot_identity, age, expected):
    app, client, refreshes, mutations = pilot_identity
    age_person(app, age, role='member', bootstrap_admin=False)
    mutations.clear()
    response = client.get(PATH)
    assert response.status_code == expected, response.text
    assert refreshes == [], 'pilot GET caused a bulk roster read'
    assert mutations == [], 'settled identity pilot GET caused persistence'


def test_E19_adjacent_formal_route_still_refreshes(pilot_identity):
    app, client, refreshes, _ = pilot_identity
    age_person(app, 90)
    assert client.get('/api/session').status_code == 200
    assert refreshes == ['lark-company']


@pytest.mark.parametrize('path', [PATH + '/x', '/api/lark-pilot', '/api/Lark-Pilot/shadow'])
def test_E20_exemption_is_exact_path(path):
    from .app import NO_ROSTER_REFRESH_PATHS
    assert PATH in NO_ROSTER_REFRESH_PATHS
    assert '/api/live/status' in NO_ROSTER_REFRESH_PATHS
    assert path not in NO_ROSTER_REFRESH_PATHS


def test_E13_settled_identity_has_zero_sql_mutations(pilot_identity):
    _, client, refreshes, mutations = pilot_identity
    response = client.get(PATH)
    assert response.status_code == 200, response.text
    assert refreshes == []
    assert mutations == []


@pytest.mark.parametrize('kind,expected', [('absent_cookie', 401), ('expired', 401),
                                         ('wrong_app', 403), ('unadmitted', 403)])
def test_E21_identity_guards_remain_enforced(pilot_identity, kind, expected):
    app, client, refreshes, mutations = pilot_identity
    if kind == 'absent_cookie':
        client.cookies.clear()
    elif kind == 'expired':
        with app.state.sessions.begin() as db:
            row = db.get(AuthRow, 'sid')
            row.data = {**row.data, 'expires': 0}
    else:
        age_person(app, 0, **({'identity_app_id': 'other-SYN-app'} if kind == 'wrong_app'
                            else {'directory_status': 'unknown', 'bootstrap_admin': False}))
    mutations.clear()
    response = client.get(PATH)
    assert response.status_code == expected, response.text
    assert refreshes == []
    assert mutations == []
