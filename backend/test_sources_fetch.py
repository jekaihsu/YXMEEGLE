"""Synthetic Lark contracts; no credentials or network are used."""
import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException

from .live_read.fingerprint import fingerprint
from .sources import fetch_sources


def fixture(api):
    return json.loads((Path(__file__).parent / 'fixtures' / 'lark' / f'sources_{api}.json').read_text())


def config(api='list', max_pages=50):
    return {
        'LARK_V4_BASE_TOKEN': 'synthetic-base',
        'LARK_SOURCE_TABLES_JSON': json.dumps([{
            'base_token': 'synthetic-base', 'table_id': 'tblSynthetic',
            'kind': 'confirmation', 'field_names': ['工程名稱', '所屬成本單', '不存在'],
        }]),
        'LARK_BITABLE_RECORDS_API': api,
        'LARK_SOURCE_MAX_PAGES': str(max_pages),
    }


def replay(api, payload, max_pages=50):
    calls = []
    pages = iter(payload['pages'])

    def respond(request):
        calls.append(request)
        value = payload['fields'] if request.url.path.endswith('/fields') else next(pages)
        return httpx.Response(200, json=value)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        class RequestOnlyClient:
            request = client.request
        result = fetch_sources('synthetic-token', config(api, max_pages), RequestOnlyClient())
    return result, calls


@pytest.mark.parametrize('api', ['list', 'search'])
def test_fixture_contract_projection_pagination_and_request_boundary(api):
    result, calls = replay(api, fixture(api))
    assert result['status'] == 'ready'
    assert result['tables'][0]['count'] == 3
    assert result['tables'][0]['pages_read'] == 2
    assert calls[0].method == 'GET' and calls[0].url.params['page_size'] == '100'
    for request in calls[1:]:
        assert request.headers['Authorization'] == 'Bearer synthetic-token'
        assert request.url.params['user_id_type'] == 'open_id'
        if api == 'search':
            assert request.method == 'POST' and request.url.path.endswith('/records/search')
            assert request.url.params['page_size'] == '500'
            assert json.loads(request.content) == {'field_names': ['工程名稱', '所屬成本單'], 'automatic_fields': True}
            assert 'field_names' not in request.url.params
        else:
            assert request.method == 'GET' and request.url.path.endswith('/records')
            assert dict(request.url.params) == {
                'page_size': '200', 'user_id_type': 'open_id',
                'field_names': '["工程名稱", "所屬成本單"]', 'automatic_fields': 'true',
                **({'page_token': 'synthetic-next'} if request is calls[-1] else {}),
            }
    assert calls[-1].url.params['page_token'] == 'synthetic-next'
    for record in result['records']:
        assert record['last_modified_time'] > record['created_time']
        assert record['cost_table_id'] == 'tblSyntheticCost'
    assert fingerprint(result) == fingerprint(replay('search' if api == 'list' else 'list', fixture(api))[0])


@pytest.mark.parametrize('api', ['list', 'search'])
@pytest.mark.parametrize('bad', ['duplicate_in_page', 'duplicate_across_pages', 'cursor_loop', 'missing_cursor', 'has_more', 'missing_items', 'missing_data'])
def test_incomplete_or_duplicate_response_fails_closed(api, bad):
    payload = fixture(api)
    first, second = (page['data'] for page in payload['pages'])
    if bad == 'duplicate_in_page': first['items'].append(deepcopy(first['items'][0]))
    elif bad == 'duplicate_across_pages': second['items'] = [deepcopy(first['items'][0])]
    elif bad == 'cursor_loop': second.update(has_more=True, page_token=first['page_token'])
    elif bad == 'missing_cursor': del first['page_token']
    elif bad == 'has_more': first['has_more'] = 'false'
    elif bad == 'missing_items': del first['items']
    elif bad == 'missing_data': del payload['pages'][0]['data']
    with pytest.raises(HTTPException) as exc:
        replay(api, payload)
    assert exc.value.status_code == 502


@pytest.mark.parametrize('api', ['list', 'search'])
def test_page_limit_returns_explicit_partial_snapshot(api):
    result, calls = replay(api, fixture(api), max_pages=1)
    assert result['status'] == result['tables'][0]['status'] == 'partial'
    assert result['tables'][0]['record_limit'] == (500 if api == 'search' else 200)
    assert len(result['records']) == 2 and len(calls) == 2


@pytest.mark.parametrize('api', ['list', 'search'])
@pytest.mark.parametrize('endpoint', ['fields', 'records'])
def test_resource_permission_code_maps_to_403(api, endpoint):
    payload = fixture(api)
    if endpoint == 'fields': payload['fields'] = {'code': 1254302}
    else: payload['pages'][0] = {'code': 1254302}
    with pytest.raises(HTTPException) as exc:
        replay(api, payload)
    assert exc.value.status_code == 403 and '1254302' in exc.value.detail


@pytest.mark.parametrize('api', ['list', 'search'])
@pytest.mark.parametrize('bad', ['has_more', 'cursor_loop', 'missing_cursor', 'missing_items'])
def test_field_schema_validation_is_shared(api, bad):
    payload = fixture(api)
    schema = payload['fields']['data']
    if bad == 'has_more': schema['has_more'] = 1
    elif bad == 'missing_items': del schema['items']
    else:
        schema['has_more'] = True
        if bad == 'cursor_loop': schema['page_token'] = 'repeat'
    with pytest.raises(HTTPException) as exc:
        replay(api, payload)
    assert exc.value.status_code == 502


def test_fingerprint_ignores_order_and_timestamps_but_detects_content_and_identity():
    result, _ = replay('list', fixture('list'))
    changed = deepcopy(result)
    changed['last_sync'] = 'different-read-time'
    changed['records'].reverse()
    for record in changed['records']:
        record['last_modified_time'] = 0
        record['fields'] = dict(reversed(list(record['fields'].items())))
    assert fingerprint(changed) == fingerprint(result)
    for key, value in [('fields', {'工程名稱': '公式重新計算'}), ('table_id', 'other-table'), ('record_id', 'other-record')]:
        changed = deepcopy(result)
        changed['records'][0][key] = value
        assert fingerprint(changed) != fingerprint(result)
    assert fingerprint({'records': []}).startswith('sha256:')


def test_unknown_records_api_is_configuration_error():
    with pytest.raises(HTTPException) as exc:
        fetch_sources('synthetic-token', config('invalid'), object())
    assert exc.value.status_code == 503


@pytest.mark.parametrize('api', ['list', 'search'])
@pytest.mark.parametrize('endpoint', ['fields', 'records'])
@pytest.mark.parametrize('failure,http_status', [('blocked', 403), ('rejected', 502), ('budget', 502)])
def test_real_live_client_errors_map_to_http(api, endpoint, failure, http_status):
    from .test_live_read_client import CFG, Clock, make_client
    clock = Clock()
    payload = fixture(api)
    def respond(request):
        if '/auth/' in request.url.path:
            return httpx.Response(200, json={'code': 0, 'tenant_access_token': 'fake-token', 'expire': 7200})
        if request.url.path.endswith('/fields') and endpoint == 'records':
            return httpx.Response(200, json=payload['fields'])
        if failure == 'budget':
            clock.now = 46
        return httpx.Response(200, json={'code': 1254302 if failure == 'blocked' else 12345})
    with make_client(respond, clock) as client:
        with pytest.raises(HTTPException) as exc:
            fetch_sources('unused', dict(config(api), **CFG), client)
    assert exc.value.status_code == http_status
    if failure == 'blocked':
        assert '1254302' in exc.value.detail


@pytest.mark.parametrize('target,key,value', [
    ('record', 'base_token', 'other-base'),
    ('record', 'department', 'other-department'),
    ('record', 'cost_table_id', 'other-cost'),
    ('record', 'linked_tables', {'link': 'other-table'}),
    ('table', 'department', 'other-department'),
    ('table', 'kind', 'quote'),
    ('table', 'status', 'partial'),
    ('table', 'count', 99),
    ('table', 'field_schema', [{'field_name': '工程名稱', 'type': 2}]),
])
def test_fingerprint_detects_configuration_schema_and_summary(target, key, value):
    original, _ = replay('list', fixture('list'))
    changed = deepcopy(original)
    changed['records' if target == 'record' else 'tables'][0][key] = value
    assert fingerprint(changed) != fingerprint(original)


def test_attachment_fingerprint_ignores_rotating_urls_but_preserves_file_identity():
    original = {'records': [{'base_token': 'base', 'table_id': 'table', 'record_id': 'record',
                            'attachment_fields': ['files'], 'fields': {'files': [
                                {'file_token': 'file-one', 'name': 'drawing.pdf',
                                 'tmp_url': 'https://files.example/temporary-one',
                                 'url': 'https://files.example/file?X-Amz-Signature=one&version=1'}]}}]}
    changed = deepcopy(original)
    attachment = changed['records'][0]['fields']['files'][0]
    attachment.update(tmp_url='https://files.example/temporary-two',
                      url='https://files.example/file?version=1&X-Amz-Signature=two')
    assert fingerprint(changed) == fingerprint(original)
    attachment['file_token'] = 'file-two'
    assert fingerprint(changed) != fingerprint(original)
