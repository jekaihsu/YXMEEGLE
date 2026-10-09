"""Malformed upstream approval responses cannot crash or corrupt public state."""
import httpx
import pytest
from .test_staff_oauth_acceptance import staff
from .test_review_mutation_authority import prepare


@pytest.mark.parametrize('payload', [[], None, {'code': 0, 'data': []},
    {'code': 0, 'data': None}, {'code': False, 'data': {}},
    {'code': 0, 'data': {'status': {'unexpected': 'private-provider-detail'}}},
    {'code': 0, 'data': {'status': 'x'*10000}}, 'invalid-json'])
def test_approval_refresh_rejects_malformed_provider_response(staff, monkeypatch, payload):
    app, client = prepare(staff)
    class Provider:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, url, **kwargs):
            if payload == 'invalid-json':
                return httpx.Response(200, content=b'private-provider-detail', request=httpx.Request('GET', url))
            return httpx.Response(200, json=payload, request=httpx.Request('GET', url))
    monkeypatch.setattr('backend.app.httpx.Client', Provider)
    before = client.get('/api/workspace').json()
    reply = client.post('/api/approvals/approval/refresh', json={'version': before['version'],
                                                              'instance_code': 'instance-review'})
    assert reply.status_code == 502
    assert 'private-provider-detail' not in reply.text
    after = client.get('/api/workspace').json()
    assert after['version'] == before['version']
    assert after['approvals'] == before['approvals']
