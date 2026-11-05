import pytest
from fastapi.testclient import TestClient

from .app import create_app
from .test_backend import act, role, workspace


@pytest.fixture
def client(tmp_path):
    app = create_app({'DATABASE_URL': f'sqlite:///{tmp_path}/c.db', 'UPLOAD_DIR': str(tmp_path / 'u'),
                      'SESSION_SECRET': 'test-secret' * 5, 'APP_ENV': 'development', 'DEMO_MODE': 'true'})
    with TestClient(app) as c:
        c.get('/api/session')
        role(c, 'u-manager')
        yield c


def person(c, ident):
    return next(u for u in workspace(c)['users'] if u['id'] == ident)


def test_a_person_edit_survives_unrelated_workspace_writes(client):
    stale = workspace(client)['version']
    token = person(client, 'u-control').get('authz_version', 0)
    assert act(client, 'admin_person', {'id': 'u-field', 'department': '外業'}).status_code == 200
    assert workspace(client)['version'] > stale
    saved = act(client, 'admin_person', {'id': 'u-control', 'name': '控制組新名', 'expected_authz_version': token}, version=stale)
    assert saved.status_code == 200, saved.text
    assert person(client, 'u-control')['name'] == '控制組新名'


def test_without_the_person_token_a_stale_workspace_version_still_conflicts(client):
    stale = workspace(client)['version']
    assert act(client, 'admin_person', {'id': 'u-field', 'department': '外業'}).status_code == 200
    assert act(client, 'admin_person', {'id': 'u-control', 'name': 'x'}, version=stale).status_code == 409


def test_a_stale_person_token_conflicts_with_a_clear_message(client):
    token = person(client, 'u-control').get('authz_version', 0)
    assert act(client, 'admin_person', {'id': 'u-control', 'name': 'first', 'expected_authz_version': token}).status_code == 200
    late = act(client, 'admin_person', {'id': 'u-control', 'name': 'second', 'expected_authz_version': token})
    assert late.status_code == 409 and '剛被其他人更新' in late.text
    assert person(client, 'u-control')['name'] == 'first'
