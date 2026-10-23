"""A failing roster refresh must not lock out people the last good roster admitted.

With live reads the roster is refreshed in the background on demand, so a refresh that
keeps failing used to deny everyone 15 minutes after the last success. The admission
window is now a configurable grace (default 24 h) that applies only to live reads;
explicit departures, unknown people and company-admin grants behave as before.
"""
import json
import time
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from .production_access import access_mode, require_access
from .test_production_access import company

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
HOUR = 3600
LIVE = {'LARK_LIVE_READ_ENABLED': 'true', 'LARK_WORKER_IDENTITY': 'application', 'LARK_APP_ID': 'app',
        'LARK_WORKER_ORGANIZATION': 'tenant', 'LARK_ALLOWED_TENANTS': 'tenant'}


def person(age=60, **changes):
    value = {'id': 'ou_member', 'active': True, 'role': 'member', 'identity_app_id': 'app',
             'directory_status': 'employed', 'directory_missing': False,
             'directory_source': {'app_id': 'app', 'record_id': 'rec1'}}
    if age is not None:
        value['directory_last_seen_at'] = (NOW - timedelta(seconds=age)).isoformat()
    value.update(changes)
    return value


@pytest.mark.parametrize('age,mode', [(60, 'normal'), (900, 'normal'), (901, 'normal'), (3 * HOUR, 'normal'),
                                      (24 * HOUR, 'normal'), (24 * HOUR + 1, 'denied')])
def test_live_reads_keep_admitting_the_last_good_roster_for_the_grace_window(age, mode):
    assert access_mode(person(age), 'app', now=NOW, cfg=LIVE) == mode


@pytest.mark.parametrize('age,mode', [(900, 'normal'), (901, 'denied'), (3 * HOUR, 'denied')])
def test_without_live_reads_the_fifteen_minute_window_is_unchanged(age, mode):
    legacy = dict(LIVE, LARK_LIVE_READ_ENABLED='false')
    assert access_mode(person(age), 'app', now=NOW, cfg=legacy) == mode
    assert access_mode(person(age), 'app', now=NOW) == mode


def test_the_grace_window_is_configurable_and_never_below_fifteen_minutes():
    tight = dict(LIVE, LARK_LIVE_READ_ROSTER_GRACE_SECONDS='1')
    assert access_mode(person(900), 'app', now=NOW, cfg=tight) == 'normal'
    assert access_mode(person(901), 'app', now=NOW, cfg=tight) == 'denied'
    wide = dict(LIVE, LARK_LIVE_READ_ROSTER_GRACE_SECONDS=str(10 ** 9))
    assert access_mode(person(8 * 24 * HOUR), 'app', now=NOW, cfg=wide) == 'denied'
    assert access_mode(person(6 * 24 * HOUR), 'app', now=NOW, cfg=wide) == 'normal'


@pytest.mark.parametrize('changes', [
    dict(directory_status='left', active=False),
    dict(directory_status='left'),
    dict(directory_missing=True),
    dict(directory_status='unknown'),
    dict(active=False),
    dict(identity_app_id='other'),
    dict(directory_source={'app_id': 'other', 'record_id': 'rec1'}),
    dict(directory_source={'app_id': 'app'}),
], ids=['left-inactive', 'left-still-active', 'missing-from-roster', 'status-unknown', 'disabled',
        'foreign-identity', 'foreign-roster', 'no-record'])
def test_a_person_the_last_good_roster_did_not_admit_stays_denied_inside_the_grace(changes):
    assert access_mode(person(3 * HOUR, **changes), 'app', now=NOW, cfg=LIVE) == 'denied'
    assert access_mode(person(60, **changes), 'app', now=NOW, cfg=LIVE) == 'denied'


@pytest.mark.parametrize('stamp', [None, '', 'invalid', '2026-10-15T11:00:00', '2026-10-15T12:00:01+00:00'])
def test_missing_naive_or_future_roster_proof_is_never_trusted(stamp):
    value = person(None)
    if stamp is not None:
        value['directory_last_seen_at'] = stamp
    assert access_mode(value, 'app', now=NOW, cfg=LIVE) == 'denied'


def test_unknown_people_are_denied():
    assert access_mode(None, 'app', now=NOW, cfg=LIVE) == 'denied'
    assert access_mode({'id': 'ou_unknown', 'active': True}, 'app', now=NOW, cfg=LIVE) == 'denied'


def test_bootstrap_admins_only_repair_after_the_grace_and_company_grants_are_unchanged():
    admin = person(25 * HOUR, role='manager', bootstrap_admin=True)
    assert access_mode(admin, 'app', now=NOW, cfg=LIVE) == 'recovery'
    admin = person(3 * HOUR, role='manager', bootstrap_admin=True)
    assert access_mode(admin, 'app', now=NOW, cfg=LIVE) == 'normal'
    grant = {'grant_id': 'g', 'open_id': 'ou_admin', 'app_id': 'app', 'tenant': 'tenant', 'role': 'manager',
             'enabled': True, 'authorized_at': (NOW - timedelta(days=1)).isoformat(), 'authorized_by': 'owner',
             'reason': 'explicit', 'decision_ref': 'ref'}
    holder = person(None, id='ou_admin', role='manager', bootstrap_admin=True, directory_status='employed',
                    oauth_identity={'source': 'oauth_user_info', 'app_id': 'app', 'tenant': 'tenant',
                                    'open_id': 'ou_admin', 'verified_at': NOW.isoformat()})
    cfg = dict(LIVE, LARK_COMPANY_ADMIN_GRANTS_JSON=json.dumps([grant]))
    assert access_mode(holder, 'app', now=NOW, cfg=cfg) == 'normal'
    revoked = dict(cfg, LARK_COMPANY_ADMIN_GRANTS_JSON='[]')
    assert access_mode(holder, 'app', now=NOW, cfg=revoked) == 'recovery'


def test_expiry_message_distinguishes_a_stale_roster_from_an_unknown_person():
    with pytest.raises(HTTPException) as stale:
        require_access(person(25 * HOUR), 'app', now=NOW, cfg=LIVE)
    assert stale.value.code == 'access_roster_expired'
    with pytest.raises(HTTPException) as unknown:
        require_access(person(60, directory_status='left'), 'app', now=NOW, cfg=LIVE)
    assert unknown.value.code == 'access_not_admitted'


def failing_company(tmp_path, ages):
    app, client = company(tmp_path, dict(LIVE, LARK_LIVE_READ_ENABLED='true', LARK_APP_ID='app1',
                                         LARK_WORKER_ORGANIZATION='company', LARK_ALLOWED_TENANTS='company'))
    from .models import AuthRow, PersonRow
    stamp = lambda age: (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat()
    with app.state.sessions.begin() as db:
        db.add(AuthRow(id='live', data={'wid': 'lark-company', 'expires': time.time() + 3600, 'access_token': 'x'}))
        for ident, (age, changes) in ages.items():
            profile = db.get(PersonRow, ('lark-company', ident))
            profile.data = {**profile.data, 'directory_last_seen_at': stamp(age), **changes}

    def failing(wid, **_):
        raise HTTPException(502, '公司名冊讀取失敗')

    app.state.live_read.refreshers = {'sources': failing, 'roster': failing, 'attendance': failing}

    def as_user(ident):
        client.cookies.set('meegle_session', app.state.signer.dumps(
            {'mode': 'lark', 'sid': 'live', 'wid': 'lark-company', 'organization': 'lark-company', 'uid': ident}))
        return client

    return app, as_user


def test_pages_load_while_the_roster_refresh_keeps_failing(tmp_path):
    app, as_user = failing_company(tmp_path, {
        'u-manager': (2 * HOUR, {}),
        'u-pm': (2 * HOUR, {}),
        'u-field': (2 * HOUR, {'directory_status': 'left', 'active': False}),
        'u-control': (30 * HOUR, {}),
    })
    try:
        assert as_user('u-pm').get('/api/session').json()['user']['id'] == 'u-pm'
        assert as_user('u-pm').get('/api/workspace').status_code == 200
        assert as_user('u-field').get('/api/workspace').status_code == 403
        expired = as_user('u-control').get('/api/workspace')
        assert expired.status_code == 403
    finally:
        app.state.live_read.close()
