"""Tenant OAuth reaches only the reviewed read views; write authority stays closed."""
from urllib.parse import quote

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from . import storage
from .app import WorkspaceRow, BusinessRow, CacheRow
from .test_auth_callback_roster import oauth, begin, finish
from .test_production_access import company
from .test_p2_int_routes import build_state, fresh_cache, B, KT, WT, assert_no_amount, HIDDEN_NAME

READS = [
    '/api/projects', '/api/projects/{vis}/navigation',
    '/api/my-work', '/api/confirmations', '/api/case-detail/{vis}',
    '/api/contract-detail?key={contract}', '/api/work-item-detail?key={work}', '/api/daily-reports',
]


@pytest.fixture
def tenant_views(tmp_path, monkeypatch):
    # Exercise authorization even for features that are off by default.
    monkeypatch.setattr('backend.features.FEATURE_LEARNING', True)
    app, _ = company(tmp_path, {'WORKSPACE_SHELL_ENABLED': 'true', 'NODE_ASSIGNMENT_ENABLED': 'true'})
    state, vis, _ = build_state()
    with app.state.sessions.begin() as db:
        row = db.get(WorkspaceRow, 'lark-company')
        row.data = storage.save(db, BusinessRow, row.id, state)
        db.add(CacheRow(id=row.id, data=fresh_cache()))
    oauth(monkeypatch)
    client = TestClient(app)
    assert finish(client, begin(client)).status_code == 307
    return app, client, dict(vis=vis, contract=quote(f'{B}/{KT}/recK1', safe=''), work=quote(f'{B}/{WT}/recW1', safe=''))


def assert_privileged_routes_denied(app, client):
    # Exercise every registered write and admin/export/approval route, including
    # future additions. Logout deliberately needs no business authorization.
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith('/api/'):
            continue
        path = route.path
        for name in route.param_convertors:
            path = path.replace('{' + name + '}', {'operation': 'prepare', 'kind': 'financial'}.get(name, 'tenant-probe'))
        for method in route.methods:
            sensitive_read = method == 'GET' and (path.startswith('/api/admin/') or path == '/api/audit'
                or path.endswith(('/file-index.csv', '/download')) or 'approval' in path or 'grant' in path)
            if (method not in ('POST', 'PUT', 'PATCH', 'DELETE') and not sensitive_read) or path == '/api/logout':
                continue
            if path == '/api/files':
                response = client.post(path, data={'project_id': 'tenant-probe', 'version': '1', 'direction': 'input'},
                                       files={'file': ('test.txt', b'test', 'text/plain')})
            else:
                response = client.request(method, path, json={'version': 1, 'action': 'admin_person', 'request_id': 'tenant-probe', 'datasets': ['sources']})
            assert response.status_code == 403, (method, path, response.text)


@pytest.mark.parametrize('template', READS)
def test_tenant_only_view_and_all_privileged_routes(tenant_views, template):
    app, client, ids = tenant_views
    response = client.get(template.format(**ids))
    assert response.status_code == 200, response.text
    assert HIDDEN_NAME not in response.text
    if template.startswith(('/api/confirmations', '/api/case-detail', '/api/contract-detail', '/api/work-item-detail')):
        assert_no_amount(response)
    if template == '/api/my-work':
        assert response.json()['readState'] == 'ready'
        assert response.json()['assignment'] == 'unassigned'
    assert_privileged_routes_denied(app, client)


@pytest.mark.parametrize('path', [
    '/api/projects/id/extra', '/api/projects/id/navigation/extra', '/api/case-detail/id/extra',
    '/api/projects/', '/api/contract-detail/extra',
])
def test_tenant_patterns_do_not_accept_extra_segments(tenant_views, path):
    from .production_access import tenant_read_allowed
    from .app import PersonRow
    app, _, _ = tenant_views
    with app.state.sessions() as db:
        user = db.get(PersonRow, ('lark-company', 'u-tenant')).data
    assert not tenant_read_allowed(user, app.state.cfg, 'lark-company', 'GET', path)
    assert tenant_read_allowed(user, app.state.cfg, 'lark-company', 'GET', '/api/projects/id/navigation')
    assert not tenant_read_allowed(user, app.state.cfg, 'lark-company', 'POST', '/api/projects/id')


@pytest.mark.parametrize('template', ['/api/manager-overview', '/api/confirmations', '/api/case-detail/{vis}',
                                     '/api/contract-detail?key={contract}', '/api/work-item-detail?key={work}'])
def test_hr_viewers_controls_person_labels_in_p2_views(tenant_views, template):
    from .app import PersonRow
    app, client, ids = tenant_views
    with app.state.sessions.begin() as db:
        person = db.get(PersonRow, ('lark-company', 'u-pm'))
        person.data = {**person.data, 'name': 'HR_PRIVATE_PM_SENTINEL'}
        row = db.get(WorkspaceRow, 'lark-company')
        state = storage.load(db, BusinessRow, row)
        task = next(p for p in state['projects'] if p['id'] == ids['vis'])['nodes'][0]['tasks'][0]
        task.update(owner_id='u-pm', source_identity={'base_token': B, 'table_id': WT, 'record_id': 'recW1'})
        row.data = storage.save(db, BusinessRow, row.id, state)
    # Manager overview resolves the current stored PM name from users.
    full = client.get('/api/manager-overview')
    assert full.status_code == 200 and 'HR_PRIVATE_PM_SENTINEL' in full.text
    if template.startswith('/api/work-item-detail'):
        assert 'HR_PRIVATE_PM_SENTINEL' in client.get(template.format(**ids)).text
    app.state.cfg['HR_VIEWERS'] = 'someone-else'
    response = client.get(template.format(**ids))
    assert response.status_code == 200, response.text
    assert 'HR_PRIVATE_PM_SENTINEL' not in response.text
    assert_no_amount(response)
    if template == '/api/manager-overview':
        case = next(c for c in response.json()['snapshot']['cases'] if c['project_id'] == ids['vis'])
        assert case['responsible']['value'] is None
        assert case['details']['pm_id'] is None
    app.state.cfg['HR_VIEWERS'] = 'u-tenant'
    assert 'HR_PRIVATE_PM_SENTINEL' in client.get('/api/manager-overview').text


def test_legacy_project_detail_stays_denied_because_it_has_unredacted_amounts(tenant_views):
    app, client, ids = tenant_views
    response = client.get('/api/projects/' + ids['vis'])
    assert response.status_code == 403
    assert_no_amount(response)
    # The reviewed P2 case projection is usable and explicitly withholds amounts.
    response = client.get('/api/case-detail/' + ids['vis'])
    assert response.status_code == 200
    assert_no_amount(response)
    assert_privileged_routes_denied(app, client)
