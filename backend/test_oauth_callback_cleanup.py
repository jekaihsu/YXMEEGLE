"""Every OAuth callback response clears state, including unexpected failures."""
import pytest
from fastapi.testclient import TestClient

from .test_auth_callback_roster import begin, finish, HTML, JSON
from .test_production_access import company


@pytest.mark.parametrize('headers', [HTML, JSON])
@pytest.mark.parametrize('failure', [ValueError, RuntimeError])
def test_unexpected_callback_failure_clears_cookie_without_leaking_detail(tmp_path, monkeypatch, headers, failure):
    app, _ = company(tmp_path)
    client = TestClient(app, raise_server_exceptions=False)
    state = begin(client)
    class Provider:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, *args, **kwargs): raise failure('PRIVATE_PROVIDER_BODY')
    monkeypatch.setattr('backend.app.httpx.Client', Provider)
    response = client.get('/api/auth/lark/callback', params={'state': state, 'code': 'synthetic'},
                          headers=headers, follow_redirects=False)
    assert 'lark_oauth_state' not in client.cookies
    assert 'meegle_session' not in client.cookies
    assert 'PRIVATE_PROVIDER_BODY' not in response.text
    if headers == HTML:
        assert response.status_code == 303 and response.headers['location'] == '/?auth_error=provider_unavailable'
    else:
        assert response.status_code == 503
        assert response.json() == {'code': 'provider_unavailable', 'detail': 'Lark 登入暫時無法完成，請稍後重新登入'}
