from uuid import uuid4
import pytest
from .test_input_registration_endpoint import setup, read_raw
from .test_backend import workspace
from .test_extended_project_concurrency import change, heartbeat
from . import integration_routes
from .input_registration import RegistrationAdapter


def payload(ws):
    p = next(p for p in ws['projects'] if p['id'] == 'p1')
    return dict(version=ws['version'], project_version=p['concurrency_version'],
                request_id=str(uuid4()), key='contact', label='Contact', value='Confirmed')


def test_input_survives_background_only_update(setup):
    app, client = setup
    body = payload(workspace(client))
    change(app, client, heartbeat)
    response = client.post('/api/projects/p1/nodes/p1-pm/inputs', json=body)
    assert response.status_code == 200, response.text
    assert len(read_raw(app, client)['input_revisions']) == 1


def test_input_rejects_changed_case_without_queueing(setup):
    app, client = setup
    body = payload(workspace(client))
    change(app, client, lambda s: next(p for p in s['projects'] if p['id']=='p1').update(name='Changed'))
    response = client.post('/api/projects/p1/nodes/p1-pm/inputs', json=body)
    assert response.status_code == 409
    assert not read_raw(app, client)['input_revisions']


@pytest.mark.parametrize('value', [True, -1, '0', None, 1.5])
def test_input_rejects_invalid_project_version(setup, value):
    _, client = setup
    body = payload(workspace(client)); body['project_version'] = value
    assert client.post('/api/projects/p1/nodes/p1-pm/inputs', json=body).status_code == 422


def test_legacy_input_retains_workspace_conflict_check(setup):
    app, client = setup
    body = payload(workspace(client)); body.pop('project_version')
    change(app, client, heartbeat)
    assert client.post('/api/projects/p1/nodes/p1-pm/inputs', json=body).status_code == 409


def test_readback_survives_background_sync_during_remote_read(setup, monkeypatch):
    app, client = setup
    response = client.post('/api/projects/p1/nodes/p1-pm/inputs', json=payload(workspace(client)))
    assert response.status_code == 200
    def unknown(state):
        state['input_revisions'][-1]['status'] = 'outcome_unknown'
        next(j for j in state['jobs'] if j['kind']=='input')['status'] = 'outcome_unknown'
    change(app, client, unknown)
    ws = workspace(client); body = payload(ws)
    ident = read_raw(app, client)['input_revisions'][-1]['id']
    class Client:
        def close(self): pass
    class Adapter:
        def __init__(self): self.client = Client()
    monkeypatch.setattr(integration_routes, 'application_adapter', lambda cfg: Adapter())
    def readback(self, plan, policy):
        change(app, client, heartbeat)
        return {'record_id': 'verified-original'}
    monkeypatch.setattr(RegistrationAdapter, 'reconcile', readback)
    result = client.post(f'/api/input-revisions/{ident}/reconcile', json={
        'version': body['version'], 'project_version': body['project_version']})
    assert result.status_code == 200, result.text
    revision = read_raw(app, client)['input_revisions'][-1]
    assert revision['status'] == 'succeeded'
    assert revision['receipt']['record_id'] == 'verified-original'
