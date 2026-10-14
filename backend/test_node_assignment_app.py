from fastapi.testclient import TestClient

from .app import create_app

URL = '/api/projects/p1/node-assignments'


def build(tmp_path, enabled):
    return create_app({'DATABASE_URL': f'sqlite:///{tmp_path}/na.db', 'UPLOAD_DIR': str(tmp_path / 'uploads'),
                       'SESSION_SECRET': 'test-secret' * 5, 'APP_ENV': 'development', 'DEMO_MODE': 'true',
                       'NODE_ASSIGNMENT_ENABLED': 'true' if enabled else 'false', 'LARK_LIVE_READ_TRANSPORT': 'deny'})


def test_flag_off_is_404_in_the_real_app(tmp_path):
    client = TestClient(build(tmp_path, False))
    client.get('/api/session')
    response = client.get(URL)
    assert (response.status_code, response.json()) == (404, {'detail': '節點指派功能尚未啟用', 'code': 'disabled'})


def test_flag_on_requires_a_session_and_a_same_origin_request(tmp_path):
    client = TestClient(build(tmp_path, True))
    assert client.get(URL).json() == {'detail': '請先登入'}
    client.get('/api/session')
    cross = client.post(URL + '/nodes/sales/claim', json={'request_id': 'x'}, headers={'origin': 'https://evil.example'})
    assert (cross.status_code, cross.json()) == (403, {'detail': '跨站請求已拒絕'})


def test_demo_workspace_never_reaches_lark(tmp_path):
    client = TestClient(build(tmp_path, True))
    client.get('/api/session')
    for response in (client.get(URL), client.post(URL + '/nodes/sales/claim', json={'request_id': 'x'})):
        assert (response.status_code, response.json()['code'], response.json()['detail']) == (
            404, 'disabled', '節點指派僅限公司正式工作區')
