"""Offline contracts only; no claim of real Lark validation before staging."""
import json
from copy import deepcopy

import httpx
import pytest

from scripts import record_lark_fixtures as recorder
from backend.live_read.client import LiveLarkClient
from backend.live_read.token_cache import TenantTokenCache


RECORD = {'record_id': 'str', 'created_time': 'int', 'last_modified_time': 'int',
          'fields': {'工程名稱': 'str', '所屬成本單': ['str']}}
FIELD_ITEMS = [
    {'field_id': 'str', 'field_name': 'str', 'type': 'int'},
    {'field_id': 'str', 'field_name': 'str', 'type': 'int', 'property': {'table_id': 'str'}},
]
# The missing tables/attendance fixtures are intentionally synthetic and frozen
# here within T10's write scope; staging recordings must match these contracts.
SYNTHETIC = {
    'tables': {'code': 0, 'data': {'items': [{'table_id': 'tblSynthetic', 'name': 'Synthetic', 'revision': 1}], 'has_more': False}},
    'shifts_query': {'code': 0, 'data': {'user_daily_shifts': [{'user_id': 'employee-synthetic', 'month': 202610, 'day_no': 7, 'shift_id': 'shift-synthetic', 'group_id': 'group-synthetic'}]}},
    'shift_get': {'code': 0, 'data': {'shift_id': 'shift-synthetic', 'is_flexible': False, 'punch_time_rule': [{'on_time': '09:00', 'off_time': '18:00'}]}},
}


def envelope(data):
    return {'code': 'int', 'data': data}


@pytest.mark.parametrize('api', ['list', 'search'])
def test_source_fixture_contract(api):
    fixture = json.loads((recorder.ROOT / f'backend/fixtures/lark/sources_{api}.json').read_text())
    assert recorder.shape(fixture['pages'][0]) == envelope({'items': [RECORD], 'has_more': 'bool', 'page_token': 'str'})
    assert recorder.shape(fixture['pages'][1]) == envelope({'items': [RECORD], 'has_more': 'bool'})
    expected_fields = sorted(FIELD_ITEMS, key=lambda item: json.dumps(item, sort_keys=True))
    assert recorder.shape(fixture['fields']) == envelope({'items': expected_fields, 'has_more': 'bool'})
    for page in fixture['pages'] + [fixture['fields']]:
        assert recorder.shape(recorder.sanitise(page)) == recorder.shape(page)


@pytest.mark.parametrize('name,expected', [
    ('tables', envelope({'items': [{'table_id': 'str', 'name': 'str', 'revision': 'int'}], 'has_more': 'bool'})),
    ('shifts_query', envelope({'user_daily_shifts': [{'user_id': 'str', 'month': 'int', 'day_no': 'int', 'shift_id': 'str', 'group_id': 'str'}]})),
    ('shift_get', envelope({'shift_id': 'str', 'is_flexible': 'bool', 'punch_time_rule': [{'on_time': 'str', 'off_time': 'str'}]})),
])
def test_synthetic_attendance_and_tables_contract(name, expected):
    assert recorder.shape(SYNTHETIC[name]) == expected
    assert recorder.shape(recorder.baselines()[name][0]) == expected


def test_compare_detects_keys_types_and_cursor_presence():
    recording = recorder.baselines()
    assert recorder.compare(recording) == ''
    for key in ('has_more', 'page_token'):
        changed = deepcopy(recording)
        del changed['list'][0]['data'][key]
        assert key in recorder.compare(changed)
    changed = deepcopy(recording)
    changed['search'][0]['data']['has_more'] = {'type': 'str', 'length': 4}
    assert recorder.compare(changed)
    changed = deepcopy(recording)
    changed['list'][0]['data']['items'].reverse()
    changed['list'][0]['data']['items'][0]['record_id']['length'] = 100
    assert recorder.compare(changed) == ''


@pytest.mark.parametrize('path', ['fixtures.json', 'backend/fixtures/lark/real.json', '.runtime/../leak.json'])
def test_recorder_refuses_paths_outside_runtime_before_network(monkeypatch, tmp_path, path):
    monkeypatch.setattr(recorder, 'ROOT', tmp_path)
    def forbidden(*args, **kwargs):
        pytest.fail('Invalid output must be rejected before constructing a client')
    monkeypatch.setattr(recorder, 'LiveLarkClient', forbidden)
    assert recorder.main(['--output', str(tmp_path / path)]) == 2
    assert not (tmp_path / path).exists()


def test_recorder_refuses_symlink_escape(monkeypatch, tmp_path):
    monkeypatch.setattr(recorder, 'ROOT', tmp_path)
    outside = tmp_path / 'outside'
    outside.mkdir()
    runtime = tmp_path / '.runtime'
    runtime.mkdir()
    (runtime / 'link').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        recorder.runtime_path(runtime / 'link/fixture.json')
    (runtime / 'link').unlink()
    runtime.rmdir()
    runtime.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        recorder.runtime_path(runtime / 'fixture.json')


def test_offline_compare(monkeypatch, tmp_path, capsys):
    recording = recorder.baselines()
    monkeypatch.setattr(recorder, 'ROOT', tmp_path)
    monkeypatch.setattr(recorder, 'baselines', lambda: recording)
    runtime = tmp_path / '.runtime'
    runtime.mkdir()
    target = runtime / 'captured.json'
    target.write_text(json.dumps(recording))
    assert recorder.main(['--input', str(target), '--compare']) == 0
    assert 'No shape differences' in capsys.readouterr().out


def test_record_uses_real_client_app_token_and_redacts(monkeypatch, tmp_path):
    fixtures = json.loads((recorder.ROOT / 'backend/fixtures/lark/sources_list.json').read_text())
    secret = 'never-persist-this-value'
    fixtures['fields']['data']['items'].append({'field_id': 'fldSalary', 'field_name': '薪資', 'type': 2})
    for page in fixtures['pages']:
        for row in page['data']['items']:
            row['fields']['薪資'] = 123456789
            row['fields']['工程名稱'] = secret
    cfg = {'LARK_APP_ID': 'fake-app', 'LARK_APP_SECRET': 'fake-secret', 'LARK_WORKER_ORGANIZATION': 'fake-tenant',
           'LARK_WORKER_IDENTITY': 'application', 'LARK_FIXTURE_EMPLOYEE_ID': 'employee-synthetic',
           'LARK_SOURCE_TABLES_JSON': json.dumps([{'base_token': 'JoOqbggsVar0ATsVgbcjh6IIp1g', 'table_id': 'tblENZvYAya93Twa', 'kind': 'quote'}])}
    calls = []
    def transport(request):
        path = request.url.path
        if path.endswith('/tenant_access_token/internal'):
            assert request.method == 'POST'
            assert json.loads(request.content) == {'app_id': 'fake-app', 'app_secret': 'fake-secret'}
            return httpx.Response(200, json={'code': 0, 'tenant_access_token': 'fake-app-token', 'expire': 7200})
        assert request.headers['Authorization'] == 'Bearer fake-app-token'
        calls.append(request)
        if path.endswith('/tables'):
            response = SYNTHETIC['tables']
        elif path.endswith('/fields'):
            response = fixtures['fields']
        elif path.endswith(('/records', '/records/search')):
            if request.method == 'POST':
                assert json.loads(request.content)['field_names'] == list(recorder.SAFE_FIELDS)
                assert request.url.params['page_size'] == '500'
            else:
                assert json.loads(request.url.params['field_names']) == list(recorder.SAFE_FIELDS)
            response = fixtures['pages'][int('page_token' in request.url.params)]
        elif path.endswith('/query'):
            response = SYNTHETIC['shifts_query']
        else:
            assert path.endswith('/shifts/shift-synthetic')
            response = SYNTHETIC['shift_get']
        return httpx.Response(200, json=deepcopy(response))
    class Bucket:
        def acquire(self, deadline):
            pass
    with LiveLarkClient(cfg, transport=httpx.MockTransport(transport), token_cache=TenantTokenCache(), bucket=Bucket(),
                        allowed_posts=(r'/bitable/v1/apps/[^/]+/tables/[^/]+/records/search', recorder.QUERY_PATH)) as client:
        recorded = recorder.record(cfg, client)
    assert set(recorded) == {'list', 'search', 'fields', 'tables', 'shifts_query', 'shift_get'}
    serialized = json.dumps(recorded, ensure_ascii=False)
    for sensitive in ('薪資', '123456789', secret, 'fake-app-token', 'fake-secret', 'employee-synthetic'):
        assert sensitive not in serialized
    assert 'length' in serialized
    assert recorder.compare(recorded) == ''
    assert len(calls) == 8


def test_failed_record_does_not_write_or_print_sensitive_error(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(recorder, 'ROOT', tmp_path)
    class FakeClient:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr(recorder, 'LiveLarkClient', FakeClient)
    def fail(*args):
        raise ValueError('secret-token salary=9999')
    monkeypatch.setattr(recorder, 'record', fail)
    assert recorder.main([]) == 2
    assert not (tmp_path / '.runtime').exists()
    assert 'secret-token' not in capsys.readouterr().err


def test_successful_record_writes_only_runtime(monkeypatch, tmp_path, capsys):
    recording = recorder.baselines()
    monkeypatch.setattr(recorder, 'ROOT', tmp_path)
    class FakeClient:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr(recorder, 'LiveLarkClient', FakeClient)
    monkeypatch.setattr(recorder, 'record', lambda *args: recording)
    monkeypatch.setattr(recorder, 'baselines', lambda: recording)
    assert recorder.main(['--compare']) == 0
    target = tmp_path / '.runtime/lark-fixtures.json'
    assert json.loads(target.read_text()) == recording
    assert list(tmp_path.iterdir()) == [tmp_path / '.runtime']
    assert 'No shape differences' in capsys.readouterr().out
