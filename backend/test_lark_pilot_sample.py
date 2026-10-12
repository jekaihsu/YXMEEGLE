"""Read-only pilot acceptance with synthetic HTTP and no production identity."""
import ast
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from .test_live_read_client import CFG, Clock
from .live_read.rate_limit import TokenBucket
from .live_read.token_cache import TenantTokenCache


def run(items=None, failure=None, cfg=None, has_more=True):
    from .lark_pilot.sample import PilotReader, CASES, WORK, PEOPLE
    clock = Clock()
    calls = []
    def handler(request):
        calls.append(request)
        if '/auth/' in request.url.path:
            return httpx.Response(200, json={'code': 0, 'tenant_access_token': 'SYN_token', 'expire': 7200})
        if failure and failure[0] in request.url.path:
            if isinstance(failure[1], Exception):
                raise failure[1]
            return httpx.Response(failure[1], json={'code': 1254302})
        table = next((t for t in (CASES, WORK, PEOPLE) if t in request.url.path), None)
        from .lark_pilot.sample import NAMES
        named = [{**x, 'fields': {NAMES.get(k, k): v for k, v in x['fields'].items()}} for x in (items or {}).get(table, [])]
        return httpx.Response(200, json={'code': 0, 'data': {'items': named, 'has_more': has_more}})
    with PilotReader(cfg or CFG, transport=httpx.MockTransport(handler), clock=clock,
                     sleep=clock.sleep, bucket=TokenBucket(10, clock=clock, sleep=clock.sleep),
                     token_cache=TenantTokenCache(clock=clock)) as reader:
        result = reader.read()
    return result, calls


def fixtures(n=1):
    from .lark_pilot.sample import CASES, WORK, PEOPLE
    return {CASES: [{'record_id': f'rec_SYN_c{i:02}', 'fields': {'fldgZDflpb': None,
             'flddfFq9zI': [f'rec_SYN_w{x:02}' for x in range(n)]}} for i in reversed(range(n))],
            WORK: [{'record_id': f'rec_SYN_w{i:02}', 'fields': {'fldjfxJIMb': '',
             'fldlqnGoTh': [f'rec_SYN_p{x:02}' for x in range(n)]}} for i in range(n)],
            PEOPLE: [{'record_id': f'rec_SYN_p{i:02}', 'fields': {'fldCTLvsWG': [{'id': f'ou_SYN_{i}'}]}} for i in range(n)]}


def test_E01_E08_E09_E16_E17_sanitized_capped_deterministic_reads():
    first, calls = run(fixtures(40))
    second, _ = run(fixtures(40))
    assert {k: [r["record_id"] for r in v] for k, v in first["records"].items()} == {k: [r["record_id"] for r in v] for k, v in second["records"].items()}
    assert first['source'] == 'mock'
    assert first['receipt']['identity_category'] == 'application'
    assert len(first['records']['cases']) == 3
    assert len(first['records']['work_orders']) == 10
    assert len(first['records']['people']) == 10
    assert first['counts']['cases']['omitted'] == 37
    assert first['counts']['cases']['has_more'] is True
    assert first['sampling_rule']
    searches = [json.loads(r.content) for r in calls if r.url.path.endswith('/records/search')]
    assert [s['page_size'] for s in searches] == [1, 3, 10, 10]
    assert all('page_token' not in str(r.url) for r in calls)
    assert not any(f.startswith('fld') for s in searches for f in s['field_names'])
    assert all(r.method == 'GET' or r.url.path.endswith(('/records/search', '/tenant_access_token/internal')) for r in calls)
    output = json.dumps(first)
    assert not any(secret in output for secret in ['Bearer', 'tenant_access_token', 'app_secret', 'SYN_token', CFG['LARK_APP_SECRET']])


@pytest.mark.parametrize('changes,category', [({'LARK_WORKER_IDENTITY': 'user'}, 'not_application'),
                                             ({'LARK_APP_SECRET': ''}, 'missing')])
def test_E02_missing_or_wrong_identity_never_calls_http(changes, category):
    result, calls = run(cfg={**CFG, **changes})
    assert result['status'] == 'unconfigured'
    assert result['receipt']['identity_category'] == category
    assert calls == []


def test_E03_denied_preflight_stops_without_retry():
    result, calls = run(failure=('/tables', 403))
    assert result['status'] == 'blocked'
    assert result['receipt']['outcome'] == 'denied'
    assert result['receipt']['endpoint'] == '/bitable/v1/apps/{base}/tables'
    assert result['receipt']['permission_needed']
    assert len([r for r in calls if '/tables' in r.url.path]) == 1


def test_E04_E05_partial_keeps_cases_and_marks_denied_links():
    from .lark_pilot.sample import WORK
    result, _ = run(fixtures(), (WORK, 403))
    assert result['status'] == 'partial'
    assert result['records']['cases'][0]['links']['flddfFq9zI']['state'] == 'denied'
    assert result['table_states']['work_orders'] == 'forbidden'
    assert result['table_states']['people'] == 'not_read'
    result, _ = run(fixtures(), (WORK, httpx.ReadTimeout('SYN_sensitive_error')))
    assert result['status'] == 'partial'
    assert result['records']['cases']
    assert result['last_error'] == 'Lark 資料暫時無法讀取'
    assert 'SYN_sensitive_error' not in json.dumps(result)


def test_E07_E10_E11_E12_projection_preserves_field_and_identity_states():
    from .lark_pilot.shadow import field, identities, link
    assert field({}, 'f')['state'] == 'omitted'
    assert field({'f': None}, 'f')['state'] == 'null'
    for value in ['', []]:
        assert field({'f': value}, 'f') == {'state': 'present', 'value': value}
    assert identities([{'name': 'SYN_same'}, {'en_name': 'SYN_same'}])['state'] == 'id_missing'
    matched = identities([{'id': 'ou_SYN_1', 'name': 'SYN_same'}, {'id': 'ou_SYN_2', 'name': 'SYN_same'}])
    assert matched == {'state': 'id_matched', 'ids': ['ou_SYN_1', 'ou_SYN_2']}
    for value, found, state, expected in [([], [], 'present', 'empty'),
        (['rec_SYN_1', 'rec_SYN_2'], ['rec_SYN_1'], 'present', 'dangling'),
        (['rec_SYN_1'], ['rec_SYN_1'], 'present', 'resolved'),
        (['rec_SYN_1'], [], 'forbidden', 'denied'), (['rec_SYN_1'], [], 'unmapped', 'unmapped')]:
        assert link(value, found, state)['state'] == expected
    result, _ = run(fixtures())
    assert 'deadline' not in json.dumps(result)
    assert 'pm_eligible' not in json.dumps(result)


@pytest.mark.parametrize('method,path', [('PUT', '/records'), ('PATCH', '/records'),
    ('DELETE', '/records'), ('POST', '/records'), ('POST', '/records/batch_create'),
    ('GET', '/bitable/v1/apps/VwAsbezz9app3YsramgjduLYp2U/tables/t/records')])
def test_E13_E14_no_write_or_salary_access(method, path):
    from .lark_pilot.sample import PilotReader
    from .live_read.client import ReadBlocked
    calls = []
    with PilotReader(CFG, transport=httpx.MockTransport(lambda r: calls.append(r))) as reader:
        with pytest.raises(ReadBlocked):
            reader.get_json(path) if method == 'GET' else reader.search_records(path, 1)
    assert calls == []


def test_E15_E21_router_disabled_before_identity_and_preserves_authorizer():
    from .lark_pilot.routes import register
    calls = []
    def identity(request):
        calls.append('identity')
        return {'wid': 'company', 'mode': 'lark'}, {'id': 'ou_SYN',
            'directory_last_seen_at': datetime.now(timezone.utc).isoformat()}
    def authorize(*args):
        calls.append('authorize')
        raise HTTPException(403, 'SYN_denied')
    cfg = {}
    app = FastAPI()
    register(app, identity=identity, authorize=authorize, cfg=cfg)
    with TestClient(app) as client:
        assert client.get('/api/lark-pilot/shadow').status_code == 404
        assert calls == []
        cfg['LARK_PILOT_READONLY_ENABLED'] = 'true'
        assert client.get('/api/lark-pilot/shadow').status_code == 403
        assert calls == ['identity', 'authorize']
        assert client.post('/api/lark-pilot/shadow').status_code == 405
    assert next(r.methods for r in app.routes if r.path == '/api/lark-pilot/shadow') == {'GET'}


def test_E22_no_database_coordinator_or_write_imports():
    folder = Path(__file__).parent / 'lark_pilot'
    forbidden = ('Session', 'sessionmaker', 'engine', 'coordinator', 'SourceSyncService',
                 'lark_adapter', 'ops_sync', 'input_registration', 'native_')
    for path in folder.glob('*.py'):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] + [getattr(node, 'module', '') or '']
                assert not any(f in name for f in forbidden for name in names)


def test_complete_small_tables_are_fresh():
    result, _ = run(fixtures(), has_more=False)
    assert result['counts']['cases']['returned'] < result['counts']['cases']['requested']
    assert result['status'] == 'fresh'
    assert result['receipt']['outcome'] == 'ok'
    assert all(row['freshness'] == 'fresh' for rows in result['records'].values() for row in rows)
