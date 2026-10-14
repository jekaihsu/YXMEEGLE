"""OAuth callback: a failed roster refresh is not reported as a missing person."""
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi.testclient import TestClient

from .app import PersonRow
from .test_live_read_routes import production_client

HTML = {'accept': 'text/html'}
JSON = {'accept': 'application/json'}


def stale(app, oid='u-manager', **fields):
    with app.state.sessions.begin() as db:
        p = db.get(PersonRow, ('lark-company', oid))
        p.data = {**p.data, 'directory_last_seen_at': (datetime.now(timezone.utc) - timedelta(seconds=901)).isoformat(), **fields}


def login(app, monkeypatch, open_id='u-manager', headers=HTML, refresh=None):
    class OAuth:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, **kwargs):
            return httpx.Response(200, json={'access_token': 'synthetic', 'expires_in': 3600}, request=httpx.Request('POST', url))
        def get(self, url, **kwargs):
            return httpx.Response(200, json={'data': {'open_id': open_id, 'name': 'Synthetic', 'tenant_key': 'company'}}, request=httpx.Request('GET', url))
    monkeypatch.setattr('backend.app.httpx.Client', OAuth)
    if refresh is not None: app.state.live_read.refreshers['roster'] = refresh
    client = TestClient(app)  # fresh jar: any cookie present afterwards came from this callback
    state = parse_qs(urlparse(client.get('/api/auth/lark/login', follow_redirects=False).headers['location']).query)['state'][0]
    client.cookies.pop('meegle_session', None)
    response = client.get('/api/auth/lark/callback', params={'state': state, 'code': 'synthetic'}, headers=headers, follow_redirects=False)
    return client, response


def unavailable(wid): raise RuntimeError('synthetic-failure')
def fresh_ok(wid): return {'fingerprint': 'synthetic'}


def code_of(response): return parse_qs(urlparse(response.headers['location']).query).get('auth_error', [None])[0]
def has_session(response): return 'meegle_session' in response.headers.get('set-cookie', '')


def test_refresh_unavailable_stale_person_reports_provider_unavailable(tmp_path, monkeypatch):
    app, _ = production_client(tmp_path); stale(app, role='member', authz_version=1)
    _, r = login(app, monkeypatch, refresh=unavailable)
    assert r.status_code == 303 and code_of(r) == 'provider_unavailable' and not has_session(r)
    assert 'synthetic-failure' not in r.text


def test_refresh_fresh_but_person_not_admitted_reports_unverified_directory(tmp_path, monkeypatch):
    app, _ = production_client(tmp_path)
    stale(app, role='member', authz_version=1, directory_status='left', directory_missing=True)
    _, r = login(app, monkeypatch, refresh=fresh_ok)
    assert r.status_code == 303 and code_of(r) == 'unverified_directory' and not has_session(r)


def test_refresh_fresh_present_and_active_logs_in(tmp_path, monkeypatch):
    app, _ = production_client(tmp_path); stale(app, role='member', authz_version=1)
    def refresh(wid):
        with app.state.sessions.begin() as db:
            p = db.get(PersonRow, ('lark-company', 'u-manager'))
            p.data = {**p.data, 'directory_last_seen_at': datetime.now(timezone.utc).isoformat()}
        return {'fingerprint': 'synthetic'}
    client, r = login(app, monkeypatch, refresh=refresh)
    assert r.status_code == 307 and has_session(r)
    assert client.get('/api/session').json()['access_mode'] == 'normal'


def test_refresh_unavailable_bootstrap_recovery_still_admitted(tmp_path, monkeypatch):
    app, _ = production_client(tmp_path); stale(app, role='manager', bootstrap_admin=True, authz_version=1)
    client, r = login(app, monkeypatch, refresh=unavailable)
    assert r.status_code == 307 and has_session(r)
    assert client.get('/api/session').json()['access_mode'] == 'recovery'


def test_refresh_unavailable_company_admin_grant_still_admitted(tmp_path, monkeypatch):
    app, _ = production_client(tmp_path); stale(app, role='manager', authz_version=1)
    app.state.cfg['LARK_COMPANY_ADMIN_GRANTS_JSON'] = json.dumps([{'open_id': 'u-manager', 'app_id': app.state.cfg['LARK_APP_ID'],
        'tenant': 'company', 'authorized_at': datetime.now(timezone.utc).isoformat(), 'enabled': True, 'role': 'manager',
        'grant_id': 'g', 'reason': 'synthetic', 'authorized_by': 'owner', 'decision_ref': 'd'}])
    client, r = login(app, monkeypatch, refresh=unavailable)
    assert r.status_code == 307 and client.get('/api/session').json()['access_mode'] == 'normal'


def test_refresh_unavailable_inactive_person_stays_inactive(tmp_path, monkeypatch):
    app, _ = production_client(tmp_path); stale(app, active=False)
    _, r = login(app, monkeypatch, refresh=unavailable)
    assert r.status_code == 303 and code_of(r) == 'inactive' and not has_session(r)


def test_refresh_unavailable_new_unknown_open_id_reports_provider_unavailable(tmp_path, monkeypatch):
    app, _ = production_client(tmp_path)
    _, r = login(app, monkeypatch, open_id='u-not-in-roster', refresh=unavailable)
    assert r.status_code == 303 and code_of(r) == 'provider_unavailable' and not has_session(r)


def test_json_callers_get_503_when_unavailable_and_403_when_fresh_absent(tmp_path, monkeypatch):
    app, _ = production_client(tmp_path); stale(app, role='member', authz_version=1)
    _, r = login(app, monkeypatch, headers=JSON, refresh=unavailable)
    assert r.status_code == 503 and 'synthetic-failure' not in r.text and not has_session(r)
    app2, _ = production_client(tmp_path / 'b'); stale(app2, role='member', authz_version=1, directory_status='left', directory_missing=True)
    _, r = login(app2, monkeypatch, headers=JSON, refresh=fresh_ok)
    assert r.status_code == 403 and '名冊' in r.json()['detail'] and not has_session(r)
    app3, _ = production_client(tmp_path / 'c'); stale(app3, active=False)
    _, r = login(app3, monkeypatch, headers=JSON, refresh=unavailable)
    assert r.status_code == 403 and '停權' in r.json()['detail']


def test_diagnostic_logs_are_identity_free(tmp_path, monkeypatch, caplog):
    import logging
    app, _ = production_client(tmp_path); stale(app, role='member', authz_version=1)
    with caplog.at_level(logging.INFO):
        _, response = login(app, monkeypatch, refresh=unavailable)
    assert response.status_code == 303
    records = [r for r in caplog.records if getattr(r, 'event', None)]
    wait = next(r for r in records if r.event == 'oauth_roster_wait')
    assert wait.result_class == 'RuntimeError' and wait.duration_ms >= 0
    assert next(r for r in records if r.event == 'access_denied').denial_code == 'access_roster_expired'
    assert 'u-manager' not in str([r.__dict__ for r in records])
    assert 'Synthetic' not in str([r.__dict__ for r in records])
