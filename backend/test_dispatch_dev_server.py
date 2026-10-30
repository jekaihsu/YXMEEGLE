"""scripts/dev_dispatch_fake_server.py drives the full dispatch flow through the real app with no network."""
import importlib.util
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from .dispatch_board.domain import TZ

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'dev_dispatch_fake_server.py'
CMD = '0d15ea5e-0000-4000-8000-0000000000{:02d}'.format


@pytest.fixture
def dev(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('dev_dispatch_fake_server', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # build() exports its settings for the module-level app; monkeypatch restores them afterwards.
    for key, value in module.settings(tmp_path).items():
        monkeypatch.setenv(key, value)
    app, fake, _ = module.build(tmp_path)
    with TestClient(app) as client:
        yield client, fake


def login(client, alias):
    response = client.get(f'/api/dev/login?as={alias}', follow_redirects=False)
    assert response.status_code == 303


def proposal(day, title):
    start = datetime.combine(datetime.now(TZ).date() + timedelta(days=day), datetime.min.time(), TZ)
    return {'project_ref': 'SYN-001', 'case_ref': 'recCase1', 'title': title, 'content': '合成內容', 'kind': 'execution',
            'phase': 'formal', 'department': '外業', 'primary_owner': 'recP3', 'crew': ['recP3', 'recP2'],
            'start': (start + timedelta(hours=8)).isoformat(timespec='minutes'),
            'end': (start + timedelta(hours=12)).isoformat(timespec='minutes'), 'instruments': ['recI1'],
            'verifications': {'person:recP3': '主管核實', 'person:recP2': '主管核實'}}


def approve_all(client, preview_id):
    for alias, seat in (('lead', 'group_leader_confirmed'), ('manager', 'manager_review'), ('pmfinal', 'pm_final')):
        login(client, alias)
        response = client.post(f'/api/v2/dispatch/previews/{preview_id}/decisions', json={'seat': seat, 'decision': 'accepted'})
        assert response.status_code == 200, response.text


def test_dev_server_runs_preview_approval_commit_and_a_reconciled_fault(dev):
    client, fake = dev
    login(client, 'pm')
    session = client.get('/api/session').json()
    assert (session['user']['id'], session['features']['dispatch_write'], session['features']['dispatch_board']) == (
        'ou_pm', True, True)
    work = client.get('/api/v2/dispatch/work').json()
    assert sorted(r['title'] for r in work['rows']) == ['B 區外業', '外業：待指派', '控制測量：待排']
    assert client.get('/api/v2/dispatch/board').status_code == 200
    seats = client.get('/api/v2/dispatch/options').json()['seats']
    assert [(s['seat'], [p['name'] for p in s['holders']]) for s in seats] == [
        ('group_leader_confirmed', ['組長']), ('manager_review', ['經理']), ('pm_final', ['派工PM', '專案PM'])]

    found = client.post('/api/v2/dispatch/previews', json=proposal(4, 'D 區外業')).json()
    assert [s['names'] for s in found['required_seats']] == [['組長'], ['經理'], ['派工PM', '專案PM']]
    approve_all(client, found['preview_id'])
    login(client, 'pm')
    response = client.post('/api/v2/dispatch/commits', json={'command_id': CMD(1), 'preview_id': found['preview_id']})
    assert (response.status_code, response.json()['command']['state']) == (200, 'committed')
    assert [f['標題'] for f in fake.task_rows().values() if f.get('命令編號') == CMD(1)] == ['D 區外業']

    assert client.post('/api/dev/faults', json={'fault': 'timeout_after_success'}).json()['armed'] == 'timeout_after_success'
    found = client.post('/api/v2/dispatch/previews', json=proposal(5, 'E 區外業')).json()
    approve_all(client, found['preview_id'])
    login(client, 'pm')
    response = client.post('/api/v2/dispatch/commits', json={'command_id': CMD(2), 'preview_id': found['preview_id']})
    assert (response.status_code, response.json()['command']['state']) == (202, 'outcome_unknown')
    login(client, 'manager')
    response = client.post(f'/api/v2/commands/{CMD(2)}/reconcile')
    assert (response.status_code, response.json()['command']['state']) == (200, 'committed')
    assert len([f for f in fake.task_rows().values() if f.get('命令編號') == CMD(2)]) == 1


def test_dev_faults_endpoint_refuses_unknown_faults(dev):
    client, _ = dev
    response = client.post('/api/dev/faults', json={'fault': 'meteor'})
    assert (response.status_code, client.get('/api/dev/faults').json()['armed']) == (422, None)


def test_dev_faults_fail_before_landing_and_mismatch_on_read_back(dev):
    client, fake = dev
    for day, fault, command, expected in ((4, 'error_before_landing', CMD(3), (502, 'failed')),
                                          (5, 'mismatch', CMD(4), (202, 'reconciliation_required'))):
        login(client, 'pm')
        found = client.post('/api/v2/dispatch/previews', json=proposal(day, fault)).json()
        approve_all(client, found['preview_id'])
        login(client, 'pm')
        client.post('/api/dev/faults', json={'fault': fault})
        response = client.post('/api/v2/dispatch/commits', json={'command_id': command, 'preview_id': found['preview_id']})
        assert (response.status_code, response.json()['command']['state']) == expected
    assert [f['標題'] for f in fake.task_rows().values() if f.get('命令編號') in (CMD(3), CMD(4))] == ['mismatch']
    assert response.json()['receipt']['mismatches'] == ['預定結束']
