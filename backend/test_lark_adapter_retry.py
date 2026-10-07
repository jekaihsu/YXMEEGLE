"""Adapter error classification with synthetic responses; no remote calls."""
import httpx
import pytest

from .lark_adapter import LarkAdapter, RemoteFailure


def request_response(response, method='GET'):
    requests = []

    def handle(request):
        requests.append(request)
        return response

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        adapter = LarkAdapter('fake-token', client)
        with pytest.raises(RemoteFailure) as caught:
            adapter.request(method, '/bitable/v1/apps/fake/tables/fake/records')
    assert len(requests) == 1  # The adapter reports retry eligibility, never resends.
    return caught.value


@pytest.mark.parametrize('headers,expected', [
    ({'x-ogw-ratelimit-reset': '12', 'Retry-After': '7'}, 12),
    ({'X-OGW-RATELIMIT-RESET': '9'}, 9),
    ({'Retry-After': '7'}, 7),
    ({}, 60),
    ({'Retry-After': 'invalid'}, 60),
    ({'x-ogw-ratelimit-reset': 'invalid'}, 60),
    ({'x-ogw-ratelimit-reset': '0'}, 1),
    ({'x-ogw-ratelimit-reset': '-3'}, 1),
])
def test_rate_limit_header_precedence_and_fallback(headers, expected):
    failure = request_response(httpx.Response(429, content=b'not-json', headers=headers))
    assert failure.status == 'retry'
    assert failure.retry_after == expected


@pytest.mark.parametrize('method', ['GET', 'POST'])
@pytest.mark.parametrize('status_code,code', [
    (200, 1254290), (200, 99991400), (200, 1254607), (400, 1254607),
])
def test_retryable_body_codes(method, status_code, code):
    failure = request_response(httpx.Response(
        status_code, json={'code': code},
        headers={'x-ogw-ratelimit-reset': '11', 'Retry-After': '3'},
    ), method)
    assert failure.status == 'retry'
    assert failure.retry_after == 11


@pytest.mark.parametrize('code', [1254302, 1254291, 99991663, 99991677, 99])
def test_other_body_codes_still_block(code):
    failure = request_response(httpx.Response(200, json={'code': code}))
    assert failure.status == 'blocked'
    assert failure.retry_after is None


@pytest.mark.parametrize('method', ['GET', 'POST'])
@pytest.mark.parametrize('status_code', [401, 403, 500, 503])
def test_http_authorization_and_server_error_precedence(method, status_code):
    failure = request_response(httpx.Response(status_code, json={'code': 99991400}), method)
    expected = 'blocked' if status_code < 500 else 'failed' if method == 'GET' else 'outcome_unknown'
    assert failure.status == expected
    assert failure.retry_after is None


@pytest.mark.parametrize('body', [b'not-json', b'[]', b'{"code":1254302}'])
def test_other_http_client_errors_still_block(body):
    failure = request_response(httpx.Response(400, content=body))
    assert failure.status == 'blocked'
    assert failure.retry_after is None


def test_success_response_unchanged():
    with httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={'code': 0, 'data': {'items': []}}),
    )) as client:
        assert LarkAdapter('fake-token', client).request('GET', '/bitable/v1/apps/fake/tables') == {'items': []}
