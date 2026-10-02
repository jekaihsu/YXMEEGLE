"""Configuration and read access must never masquerade as native submission."""
import json
import time

import pytest
from fastapi.testclient import TestClient

from .approval_capabilities import approval_connection
from .app import create_app, WorkspaceRow, AuthRow
from .seed import seed


@pytest.mark.parametrize('simulate', [False, True])
def test_configured_definitions_and_tokens_do_not_enable_native_submission(simulate):
    cfg = {key: 'private-value' for key in (
        'LARK_CHANGE_APPROVAL_CODE', 'LARK_EXTENSION_APPROVAL_CODE',
        'LARK_NODE_SKIP_APPROVAL_CODE', 'LARK_FINANCIAL_APPROVAL_CODE', 'LARK_APP_SECRET', 'LARK_OAUTH_SCOPES')}
    result = approval_connection(cfg, simulation_available=simulate)
    assert not result['native_submit']['available']
    assert not result['trusted_result_binding']
    assert result['existing_instance_read']['verified'] is False
    assert 'private-value' not in json.dumps(result)
    for kind, value in result['native_submit']['by_type'].items():
        assert value['definition_configured'] and not value['available']
        assert value['simulation_available'] == simulate
        assert value['blockers'] == []


def test_missing_definition_is_distinct_from_unverified_configuration():
    result = approval_connection({'LARK_CHANGE_APPROVAL_CODE': '  '})
    assert all(v['blockers'][0]['code'] == 'definition_missing'
               for v in result['native_submit']['by_type'].values())


@pytest.mark.parametrize('mode,wid,simulate', [
    ('demo', 'demo-approval', True),
    ('lark', 'test-lark-approval', True),
    ('lark', 'lark-approval', False),
])
def test_workspace_and_mutation_capabilities_match_actual_submit_guard(tmp_path, mode, wid, simulate):
    app = create_app({'DATABASE_URL': f'sqlite:///{tmp_path}/capabilities.db',
                      'UPLOAD_DIR': str(tmp_path / 'uploads'), 'DEMO_MODE': 'true',
                          'APP_ENV': 'development', 'SESSION_SECRET': 'approval-tests' * 4,
                          'LARK_WORKER_ORGANIZATION':'approval','LARK_ALLOWED_TENANTS':'approval'})
    with app.state.sessions.begin() as db:
        state = seed()
        # A stored UI flag/environment is not a server capability.
        state['environment'] = 'demo' if mode=='demo' else ('test' if wid.startswith('test-') else 'production')
        if state['environment']=='production':
            for project in state['projects']:
                project['execution_system']='workbench';project['case_visibility']='new_case'
        state['approval_connection'] = {'native_submit': {'available': True}}
        state['native_definition_verification'] = {'checked_by': 'private-health-actor',
                                                  'mapping_set_hash': 'private-health-hash'}
        db.add(WorkspaceRow(id=wid, version=1, data=state))
        if mode == 'lark':
            db.add(AuthRow(id=wid, data={'wid': wid, 'expires': time.time() + 3600,
                                       'access_token': 'unused'}))
    client = TestClient(app)
    client.cookies.set('meegle_session', app.state.signer.dumps(
        {'mode': mode, 'uid': 'u-pm', 'wid': wid, 'sid': wid}))
    ws = client.get('/api/workspace').json()
    assert 'native_definition_verification' not in ws
    assert 'private-health-' not in json.dumps(ws)
    assert ws['approval_connection']['simulation_available'] == simulate
    assert not ws['approval_connection']['native_submit']['available']
    response = client.post('/api/actions', json={
        'action': 'approval_create', 'version': ws['version'], 'request_id': 'draft',
        'project_id': 'p1', 'payload': {'type': 'change', 'reason': '測試草稿',
            'title': '測試', 'task_ids': ['p1-control-t1']}})
    assert response.status_code == 200, response.text
    saved = response.json()
    assert 'native_definition_verification' not in saved
    assert 'private-health-' not in json.dumps(saved)
    assert saved['approval_connection'] == ws['approval_connection']
    response = client.post('/api/actions', json={
        'action': 'approval_submit', 'version': saved['version'], 'request_id': 'submit',
        'project_id': 'p1', 'payload': {'approval_id': saved['approvals'][0]['id']}})
    assert response.status_code == (200 if simulate else 503), response.text
    # The capability is derived on response, not trusted or persisted as authority.
    assert not client.get('/api/workspace').json()['approval_connection']['native_submit']['available']
