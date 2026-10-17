"""T1 expected contracts: synthetic HTTP only; no production patch."""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from .lark_pilot import routes
from .lark_pilot.sample import CAPS, PilotReader
from .live_read.rate_limit import BudgetExceeded, TokenBucket
from .live_read.token_cache import TenantTokenCache
from .test_lark_pilot_integrated import integrated, profile, PATH
from .test_lark_pilot_sample import run, fixtures
from .test_live_read_client import CFG, Clock as RetryClock


@pytest.fixture
def isolated(monkeypatch):
    """Route guard tests separate from the earlier general admission guard."""
    now = datetime.now(timezone.utc)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now
    monkeypatch.setattr(routes, 'datetime', Clock)
    cfg = {**CFG, 'LARK_PILOT_READONLY_ENABLED': 'true'}
    user = {'id': 'ou_SYN', 'directory_last_seen_at': now.isoformat()}
    identity = Mock(return_value=({'wid': 'lark-SYN', 'mode': 'lark'}, user))
    authorize = Mock()
    calls = []
    def transport(request):
        calls.append(request)
        if '/auth/' in request.url.path:
            return httpx.Response(200, json={'code': 0, 'tenant_access_token': 'SYN_token', 'expire': 7200})
        assert request.method == 'GET' and request.url.path.endswith('/tables') or request.method == 'POST' and request.url.path.endswith('/records/search')
        return httpx.Response(200, json={'code': 0, 'data': {'items': []}})
    reader = Mock(side_effect=lambda config: PilotReader(config, transport=httpx.MockTransport(transport), token_cache=TenantTokenCache()))
    monkeypatch.setattr(routes, 'PilotReader', reader)
    app = FastAPI()
    routes.register(app, identity=identity, authorize=authorize, cfg=cfg)
    with TestClient(app) as client:
        yield client, cfg, user, now, authorize, reader, calls, identity


@pytest.mark.parametrize('age,ttl,code,ceiling', [
    (61, '60', 'pilot_roster_stale', 60), (60.001, '60', 'pilot_roster_stale', 60),
    (30.001, '30', 'pilot_roster_stale', 30), (61, '600', 'pilot_roster_stale', 60),
    (None, '60', 'pilot_roster_missing', None), ('invalid', '60', 'pilot_roster_missing', None),
    ('naive', '60', 'pilot_roster_missing', None), (0, 'nan', 'pilot_config_invalid', None),
    (0, 'inf', 'pilot_config_invalid', None), (0, 'invalid', 'pilot_config_invalid', None),
])
def test_A1_A2_A3_A8_evidence_codes(isolated, age, ttl, code, ceiling):
    client, cfg, user, now, authorize, reader, calls, _ = isolated
    user['directory_last_seen_at'] = (now-timedelta(seconds=age)).isoformat() if isinstance(age, (int, float)) else now.replace(tzinfo=None).isoformat() if age == 'naive' else age
    cfg['LARK_LIVE_READ_ROSTER_TTL_SECONDS'] = ttl
    response = client.get(PATH)
    assert response.status_code == 403
    assert calls == [] and authorize.call_count == 0 and reader.call_count == 0
    expected_keys = {'detail', 'code'} | ({'ceiling_seconds'} if ceiling else set())
    assert set(response.json()) == expected_keys, response.text
    assert response.json()['code'] == code
    if ceiling:
        assert response.json()['ceiling_seconds'] == ceiling
    assert not any(marker in response.text for marker in ('ou_SYN', 'SYN_token', CFG['LARK_APP_SECRET'], 'Traceback'))


@pytest.mark.parametrize('age,ttl', [(60, '60'), (30, '30')])
def test_A2_A5_exact_boundary_preserves_reader(isolated, age, ttl):
    client, cfg, user, now, authorize, reader, calls, _ = isolated
    cfg['LARK_LIVE_READ_ROSTER_TTL_SECONDS'] = ttl
    user['directory_last_seen_at'] = (now-timedelta(seconds=age)).isoformat()
    response = client.get(PATH)
    assert response.status_code == 200
    assert len(calls) == 4 and authorize.call_count == reader.call_count == 1
    assert response.json()['source'] == 'mock'


def test_A4_A8_source_denial(isolated):
    client, _, _, _, authorize, reader, calls, _ = isolated
    authorize.side_effect = HTTPException(403, '來源同步操作者已無權限')
    response = client.get(PATH)
    assert response.status_code == 403
    assert calls == [] and reader.call_count == 0 and authorize.call_count == 1
    assert response.json() == {'detail': '來源同步操作者已無權限', 'code': 'source_authorization_denied'}


@pytest.mark.parametrize('changes,code', [
    ({'directory_last_seen_at': '2020-01-01T00:00:00+00:00'}, 'access_roster_expired'),
    ({'directory_status': 'unknown', 'bootstrap_admin': False}, 'access_not_admitted'),
    ({'active': False}, 'access_not_admitted'),
])
def test_A6_A8_general_identity_denials(integrated, changes, code):
    app, client, calls, refreshes, _ = integrated
    profile(app, **changes)
    response = client.get(PATH)
    assert response.status_code == 403
    assert calls == [] and refreshes == []
    assert set(response.json()) == {'detail', 'code'}
    assert response.json()['code'] == code


@pytest.mark.parametrize('failure,expected_calls,code,status', [
    (403, 2, 'lark_permission_denied', 'blocked'),
    (503, 4, 'lark_read_failed', 'error'),
    (httpx.ReadTimeout('SYN_private_exception'), 2, 'lark_read_failed', 'error'),
    (BudgetExceeded('SYN_private_exception'), 2, 'lark_read_failed', 'error'),
])
def test_A7_A8_remote_failure_has_no_fabricated_counts(failure, expected_calls, code, status):
    calls = []
    clock = RetryClock()
    def transport(request):
        calls.append(request)
        if '/auth/' in request.url.path:
            return httpx.Response(200, json={'code': 0, 'tenant_access_token': 'SYN_token', 'expire': 7200})
        if isinstance(failure, Exception):
            raise failure
        return httpx.Response(failure, json={'code': 0})
    with PilotReader(CFG, transport=httpx.MockTransport(transport), clock=clock,
                     sleep=clock.sleep, bucket=TokenBucket(10, clock=clock, sleep=clock.sleep),
                     token_cache=TenantTokenCache(clock=clock)) as reader:
        result = reader.read()
    assert len(calls) == expected_calls
    assert result['status'] == status
    assert 'SYN_private_exception' not in json.dumps(result)
    assert result.get('code') == code
    assert all(result['counts'][name] is None for name in CAPS)


def test_A7_unread_tables_have_no_counts_or_fetch_time():
    result, calls = run()
    assert len(calls) == 4
    assert result['counts']['cases']['returned'] == 0
    for name in ('work_orders', 'people'):
        assert result['counts'][name] is None
        assert result['table_states'][name] == 'not_read'


def test_A9_caps_allowlist_and_table_fetch_times():
    result, calls = run(fixtures(40))
    assert len(calls) == 6
    assert {name: len(rows) for name, rows in result['records'].items()} == CAPS
    assert all(r.method == 'GET' or r.url.path.endswith(('/records/search', '/tenant_access_token/internal')) for r in calls)
    assert all(result['table_fetched_at'][name] is not None for name in CAPS)


def test_A9_disabled_and_method_guards(isolated):
    client, cfg, _, _, authorize, reader, calls, identity = isolated
    cfg['LARK_PILOT_READONLY_ENABLED'] = 'false'
    assert client.get(PATH).status_code == 404
    assert client.post(PATH).status_code == 405
    assert calls == [] and identity.call_count == authorize.call_count == reader.call_count == 0

@pytest.mark.parametrize('method,enabled,code', [
    ('GET', 'false', 'pilot_disabled'), ('POST', 'true', 'pilot_method_not_allowed'),
])
def test_pilot_non_200_has_message_and_code(integrated, method, enabled, code):
    app, client, _, _, _ = integrated
    app.state.cfg['LARK_PILOT_READONLY_ENABLED'] = enabled
    response = client.request(method, PATH)
    assert response.status_code in (404, 405)
    assert response.json()['code'] == code
    assert response.json()['detail']

def test_incomplete_sample_is_partial_and_oldest_table_sets_envelope(monkeypatch):
    from .lark_pilot import sample
    stamps = iter(datetime(2026, 10, 12, 0, 0, second, tzinfo=timezone.utc) for second in (1, 5, 9))
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return next(stamps)
    monkeypatch.setattr(sample, 'datetime', Clock)
    result, _ = run(fixtures(40))
    assert result['status'] == 'partial'
    assert result['fetched_at'] == result['table_fetched_at']['cases']
    assert result['table_fetched_at']['people'] > result['fetched_at']
    assert all(row['freshness'] == 'partial' for rows in result['records'].values() for row in rows)
