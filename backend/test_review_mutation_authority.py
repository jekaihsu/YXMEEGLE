"""Sensitive callbacks use authority reloaded after the request's initial identity."""
import json
import httpx
import pytest
from .test_staff_oauth_acceptance import staff
from .app import WorkspaceRow, BusinessRow
from .seed import seed
from . import storage
from .business_policy import ORDINARY_BACKUP_SCOPE


def prepare(staff):
    app, client, login, change = staff
    change({'role': 'manager'})
    app.state.cfg['LARK_COMPANY_ADMIN_GRANTS_JSON'] = json.dumps([{
        'open_id': 'ou_staff', 'app_id': 'staff-app', 'tenant': 'company', 'role': 'manager',
        'enabled': True, 'grant_id': 'review-grant', 'authorized_at': '2026-01-01T00:00:00Z',
        'authorized_by': 'owner', 'decision_ref': 'review', 'reason': 'ordinary backup',
        'scopes': [ORDINARY_BACKUP_SCOPE],
    }])
    assert login().status_code == 307
    with app.state.sessions.begin() as db:
        row = db.get(WorkspaceRow, 'lark-company')
        state = storage.load(db, BusinessRow, row)
        project = seed()['projects'][0]
        project.update(case_visibility='new_case', execution_system='workbench')
        project['files'] = [{'id': 'local-file', 'name': 'report.txt', 'node_id': 'p1-control',
                             'direction': 'output', 'version': '1', 'storage': 'local'}]
        state['projects'] = [project]
        state['approvals'] = [{'id': 'approval', 'project_id': 'p1', 'type': 'change',
                               'status': 'draft', 'history': []}]
        row.data = storage.save(db, BusinessRow, row.id, state)
    return app, client


@pytest.mark.parametrize('revoke', [False, True])
def test_file_store_uses_current_business_grant(staff, monkeypatch, revoke):
    app, client = prepare(staff)
    from . import integration_routes
    original = integration_routes.json_object
    async def body(request):
        result = await original(request)
        if revoke:
            app.state.cfg['LARK_COMPANY_ADMIN_GRANTS_JSON'] = '[]'
        return result
    monkeypatch.setattr(integration_routes, 'json_object', body)
    before = client.get('/api/workspace').json()
    reply = client.post('/api/files/local-file/store-lark', json={'version': before['version']})
    assert reply.status_code == (403 if revoke else 200)
    after = client.get('/api/workspace').json()
    if revoke:
        assert after['version'] == before['version']
        assert after['jobs'] == before['jobs']
        assert after['projects'][0]['files'] == before['projects'][0]['files']
    else:
        assert after['projects'][0]['files'][0]['remote_status'] == 'queued'
        assert [(j['kind'], j['actor_id']) for j in after['jobs']] == [('file', 'ou_staff')]


@pytest.mark.parametrize('revoke', [False, True])
def test_approval_refresh_rechecks_grant_after_provider_read(staff, monkeypatch, revoke):
    app, client = prepare(staff)
    class Provider:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, url, **kwargs):
            if revoke:
                app.state.cfg['LARK_COMPANY_ADMIN_GRANTS_JSON'] = '[]'
            return httpx.Response(200, json={'code': 0, 'data': {'status': 'PENDING'}},
                                  request=httpx.Request('GET', url))
    monkeypatch.setattr('backend.app.httpx.Client', Provider)
    before = client.get('/api/workspace').json()
    reply = client.post('/api/approvals/approval/refresh', json={'version': before['version'],
                                                              'instance_code': 'instance-review'})
    assert reply.status_code == (403 if revoke else 200)
    after = client.get('/api/workspace').json()
    if revoke:
        assert after['version'] == before['version']
        assert after['approvals'] == before['approvals']
    else:
        assert after['approvals'][0]['lark_external_status'] == 'PENDING'
        assert after['approvals'][0]['lark_binding_verified'] is False


# The existing isolated HTTP harness performs the real mapping read/verify path.
from .test_source_sync import harness
from .test_isolated_live import isolated, make_client


@pytest.mark.parametrize('revoke', [False, True])
def test_mapping_verify_rechecks_capability_after_readback(isolated, monkeypatch, revoke):
    x = isolated
    state = x.read()
    state['input_mappings'][0]['verified'] = False
    x.save(state)
    def revoke_capability():
        current = x.read()
        actor = next(u for u in current['users'] if u['id'] == 'u-manager')
        actor.update(role='member', capabilities=[])
        x.save(current)
    if revoke:
        x.remote['after_input_read'] = revoke_capability
    with make_client(x, monkeypatch) as client:
        reply = client.post('/api/input-mappings/map1/verify', json={'version': state['version']})
    assert reply.status_code == (403 if revoke else 200)
    assert x.read()['input_mappings'][0]['verified'] is (not revoke)


@pytest.mark.parametrize('revoke', [False, True])
def test_leave_verify_rechecks_capability_after_provider_read(staff, monkeypatch, revoke):
    from types import SimpleNamespace
    from .learning_sources import LEAVE_DEFINITION, DELEGATE_FIELD
    app, client, login, change = staff
    change({'capabilities': ['manage_handover']})
    assert login().status_code == 307
    class Provider:
        def __init__(self, token): self.client = SimpleNamespace(close=lambda: None)
        def request(self, *args, **kwargs):
            if revoke:
                change({'capabilities': []})
            return {'definition_code': LEAVE_DEFINITION, 'instance_code': 'leave-review',
                    'open_id': 'ou_staff', 'status': 'APPROVED', 'form': [
                        {'id': DELEGATE_FIELD, 'value': [{'id': 'ou_staff'}]},
                        {'id': 'widgetLeaveGroupStartTime', 'value': '2026-10-09T08:00:00+08:00'},
                        {'id': 'widgetLeaveGroupEndTime', 'value': '2026-10-09T17:00:00+08:00'},
                    ]}
    monkeypatch.setattr('backend.lark_adapter.LarkAdapter', Provider)
    before = client.get('/api/workspace').json()
    reply = client.post('/api/delegations/verify-approval', json={'version': before['version'],
                                                               'instance_code': 'leave-review'})
    assert reply.status_code == (403 if revoke else 200)
    after = client.get('/api/workspace').json()
    assert after['version'] == before['version'] + (0 if revoke else 1)
    assert [r['id'] for r in after['approved_leave_delegations']] == ([] if revoke else ['leave-review'])
