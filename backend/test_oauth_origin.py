"""OAuth origins require explicit production config and normalize proxy lists."""
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from .test_auth_callback_roster import oauth, begin, finish
from .test_production_access import company


@pytest.mark.parametrize(('app_url', 'public_origin', 'expected_origin'), [
    (None, 'https://public.example/', 'https://public.example'),
    ('', 'https://public.example/', 'https://public.example'),
    ('  ', '  https://public.example/  ', 'https://public.example'),
    ('https://app.example/', 'https://public.example/', 'https://app.example'),
    ('https://app.example/', None, 'https://app.example'),
    (None, None, None),
    ('', '', None),
    ('  ', '  ', None),
])
def test_production_login_requires_configured_origin_before_creating_state(
        tmp_path, monkeypatch, app_url, public_origin, expected_origin):
    monkeypatch.delenv('APP_URL', raising=False)
    monkeypatch.delenv('PUBLIC_ORIGIN', raising=False)
    def local_engine(url, **kwargs):
        return create_engine(f'sqlite:///{tmp_path}/production.db', connect_args={'check_same_thread': False})
    monkeypatch.setattr('backend.app.create_engine', local_engine)
    config = {'APP_ENV': 'production', 'DATABASE_URL': 'postgresql://unused/origin-test',
              'SESSION_SECRET': 'test-secret' * 4}
    if app_url is not None:
        config['APP_URL'] = app_url
    if public_origin is not None:
        config['PUBLIC_ORIGIN'] = public_origin
    app, _ = company(tmp_path, config)
    client = TestClient(app, base_url='https://internal')
    response = client.get('/api/auth/lark/login', headers={'x-forwarded-host': 'attacker.example',
                          'x-forwarded-proto': 'https'}, follow_redirects=False)
    from .app import AuthRow
    from sqlalchemy import select
    with app.state.sessions() as db:
        nonces = list(db.scalars(select(AuthRow).where(AuthRow.id.like('oauth-%'))))
    if expected_origin is None:
        assert response.status_code == 503
        assert response.json()['detail'] == 'Production Lark login requires APP_URL or PUBLIC_ORIGIN'
        assert 'set-cookie' not in response.headers
        assert 'lark_oauth_state' not in client.cookies and nonces == []
    else:
        assert response.status_code == 307 and len(nonces) == 1
        assert 'Secure' in response.headers['set-cookie']
        oauth(monkeypatch)
        state = parse_qs(urlparse(response.headers['location']).query)['state'][0]
        response = finish(client, state)
        assert response.status_code == 307
        assert response.headers['location'] == expected_origin + '/'
        assert 'Secure' in response.headers['set-cookie']


@pytest.mark.parametrize('proto', ['https', 'http'])
def test_development_proxy_origin_uses_first_host_and_proto(tmp_path, monkeypatch, proto):
    app, _ = company(tmp_path, {'APP_URL': '', 'PUBLIC_ORIGIN': ''})
    oauth(monkeypatch)
    client = TestClient(app, base_url='https://internal')
    headers = {'x-forwarded-host': ' public.example , internal.example', 'x-forwarded-proto': f' {proto} , http'}
    state = begin(client, headers=headers)
    response = client.get('/api/auth/lark/callback', params={'state': state, 'code': 'synthetic'},
                          headers=headers, follow_redirects=False)
    assert response.status_code == 307
    assert response.headers['location'] == f'{proto}://public.example/'
    assert ('Secure' in response.headers['set-cookie']) is (proto == 'https')
