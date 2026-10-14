"""OAuth origins require explicit production config and normalize proxy lists."""
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from .test_auth_callback_roster import oauth, begin, finish
from .test_production_access import company


@pytest.mark.parametrize('app_url', ['', 'https://app.example'])
def test_production_login_requires_app_url_before_creating_state(tmp_path, monkeypatch, app_url):
    def local_engine(url, **kwargs):
        return create_engine(f'sqlite:///{tmp_path}/production.db', connect_args={'check_same_thread': False})
    monkeypatch.setattr('backend.app.create_engine', local_engine)
    app, _ = company(tmp_path, {'APP_ENV': 'production', 'DATABASE_URL': 'postgresql://unused/origin-test',
                               'SESSION_SECRET': 'test-secret' * 4, 'APP_URL': app_url})
    client = TestClient(app, base_url='https://internal')
    response = client.get('/api/auth/lark/login', headers={'x-forwarded-host': 'attacker.example',
                          'x-forwarded-proto': 'https'}, follow_redirects=False)
    from .app import AuthRow
    from sqlalchemy import select
    with app.state.sessions() as db:
        nonces = list(db.scalars(select(AuthRow).where(AuthRow.id.like('oauth-%'))))
    if not app_url:
        assert response.status_code == 503 and 'APP_URL' in response.json()['detail']
        assert 'lark_oauth_state' not in client.cookies and nonces == []
    else:
        assert response.status_code == 307 and len(nonces) == 1
        oauth(monkeypatch)
        state = parse_qs(urlparse(response.headers['location']).query)['state'][0]
        response = finish(client, state)
        assert response.headers['location'] == 'https://app.example/'
        assert 'Secure' in response.headers['set-cookie']


def test_development_proxy_origin_uses_first_host_and_proto(tmp_path, monkeypatch):
    app, _ = company(tmp_path, {'APP_URL': ''})
    oauth(monkeypatch)
    client = TestClient(app, base_url='https://internal')
    headers = {'x-forwarded-host': ' public.example , internal.example', 'x-forwarded-proto': ' https , http'}
    state = begin(client, headers=headers)
    response = client.get('/api/auth/lark/callback', params={'state': state, 'code': 'synthetic'},
                          headers=headers, follow_redirects=False)
    assert response.status_code == 307
    assert response.headers['location'] == 'https://public.example/'
