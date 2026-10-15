import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from .settings_overview import build_overview, register


def test_member_summary_is_own_and_restricted():
    result = build_overview({'mode': 'lark'}, {'name': '本人', 'role': 'member', 'id': 'me'},
                            {'environment': 'production', 'users': [{'name': 'PRIVATE'}]}, {'HR_VIEWERS': 'other'},
                            {'tables': [{'name': 'PRIVATE', 'count': 99}]})
    assert result['user'] == {'name': '本人', 'role': 'member', 'permissions': ['read_own_work']}
    assert result['directory'] == {'status': 'restricted', 'last_success_at': None}
    assert result['sources'] == []
    assert result['node_connection'] == []
    assert result['manager_details_available'] is False
    assert 'PRIVATE' not in json.dumps(result)


def test_manager_cached_evidence_and_secrets():
    result = build_overview({'mode': 'lark'}, {'name': '管理員', 'role': 'manager'},
        {'environment': 'production', 'people_directory_status': {'status': 'ready', 'source_count': 67, 'valid_people': 62}},
        {'NODE_ASSIGNMENT_ENABLED': 'true', 'LARK_WORKER_IDENTITY': 'application', 'LARK_APP_SECRET': 'SECRET_SENTINEL'},
        {'status': 'ready', 'tables': [
            {'base_token': 'secret-base', 'table_id': 'one', 'name': '工程確認單', 'status': 'ready', 'pages_read': 1, 'count': 5, 'last_sync': '2026-10-14T15:00:00Z'},
            {'base_token': 'secret-base', 'table_id': 'two', 'name': 'PRIVATE_TABLE', 'status': 'forbidden', 'count': 99}]},
        {'sources': {'status': 'fresh', 'last_error': None}, 'roster': {'status': 'error', 'last_error': 'TOKEN_SENTINEL'}})
    assert result['sources'][0]['loaded_count'] == 5
    assert result['sources'][0]['readState'] == 'complete'
    assert result['sources'][0]['source_as_of'] is None
    assert result['directory']['matched_accounts'] == 62
    assert result['features'] == {'node_assignment': True, 'change_extension': False, 'routines': False}
    assert result['identity_mode'] == 'application'
    assert result['manager_details_available'] is True
    assert result['datasets'][1]['last_error_code'] == 'read_failed'
    for secret in ('SECRET_SENTINEL', 'TOKEN_SENTINEL', 'secret-base', 'PRIVATE_TABLE'):
        assert secret not in json.dumps(result)


def test_demo_and_test_do_not_claim_live_connection():
    for mode, environment in [('demo', 'demo'), ('lark', 'test')]:
        result = build_overview({'mode': mode}, {'role': 'manager'}, {'environment': environment}, {},
                                {'tables': [{'name': 'NOT_LIVE', 'status': 'ready'}]})
        assert result['sources'] == []
        assert result['manager_details_available'] is False
        assert [row['status'] for row in result['node_connection']] == ['unknown', 'unknown', 'unknown']
        assert result['directory']['roster_size'] is None


def test_registered_endpoint_requires_identity():
    from fastapi import HTTPException
    app = FastAPI()
    def identity(request):
        raise HTTPException(401, '請先登入')
    register(app, identity, None, None, None, None, {})
    assert TestClient(app).get('/api/settings/overview').status_code == 401


def test_complete_empty_partial_stale_and_failed_sources():
    table = {'base_token': 'base', 'table_id': 'table', 'name': '任務', 'status': 'ready',
             'pages_read': 1, 'count': 0, 'last_sync': '2026-10-14T15:00:00Z'}
    for fresh, expected, complete in [('fresh', 'complete_empty', True), ('stale', 'stale', False), ('error', 'read_failed', False)]:
        result = build_overview({'mode': 'lark'}, {'role': 'manager'}, {'environment': 'production'}, {},
                                {'status': 'ready', 'tables': [table]}, {'sources': {'status': fresh}})
        assert result['sources'][0]['readState'] == expected
        assert result['sources'][0]['complete'] is complete
    result = build_overview({'mode': 'lark'}, {'role': 'manager'}, {'environment': 'production'}, {},
                            {'status': 'partial', 'tables': [{**table, 'status': 'partial', 'count': 2}]},
                            {'sources': {'status': 'fresh'}})
    assert result['sources'][0]['readState'] == 'partial'
    assert result['sources'][0]['loaded_count'] == 2
