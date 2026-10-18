from fastapi.testclient import TestClient

from .app import create_app


def build(tmp_path, **flags):
    return TestClient(create_app({'DATABASE_URL': f'sqlite:///{tmp_path}/dp.db', 'UPLOAD_DIR': str(tmp_path / 'uploads'),
                                  'SESSION_SECRET': 'test-secret' * 5, 'APP_ENV': 'development', 'DEMO_MODE': 'true',
                                  'WORKSPACE_SHELL_ENABLED': 'false', 'LARK_LIVE_READ_TRANSPORT': 'deny', **flags}))


def test_session_exposes_dispatch_write_only_when_enabled(tmp_path):
    assert 'dispatch_write' not in build(tmp_path).get('/api/session').json()['features']
    assert build(tmp_path, DISPATCH_WRITE_ENABLED='true').get('/api/session').json()['features']['dispatch_write'] is True


def test_real_app_routes_are_absent_when_off_and_formal_only_when_on(tmp_path):
    off = build(tmp_path)
    off.get('/api/session')
    assert off.post('/api/v2/dispatch/previews', json={}).status_code == 404
    on = build(tmp_path, DISPATCH_WRITE_ENABLED='true')
    assert on.get('/api/v2/dispatch/work').json() == {'detail': '請先登入'}
    on.get('/api/session')
    response = on.get('/api/v2/dispatch/work')
    assert (response.status_code, response.json()['code']) == (403, 'forbidden')
