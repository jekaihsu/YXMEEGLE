"""Synthetic local vertical flow API: server-side gates, proposals vs granted receipts, mock decisions, dispatch recovery.

All data is synthetic fixture data; the adapter is the in-workspace mock wired through the WorkspaceRow OpsStore.
"""
import pytest

from .ops_sync.adapter import MockLarkAdapter
from .ops_sync.routes import ADAPTER_NAMESPACE
from .ops_sync.workspace_store import WorkspaceStore
from .test_ops_sync_routes import as_user, make

CASE, NODE = 'case:p1', 'node:p1:p1-pm'
PM = lambda pid: f'synthetic|yxs-local|{pid}'
URL = '/api/ops-sync/flow'


@pytest.fixture
def rig(tmp_path):
    app, client = make(tmp_path, 'true')
    return app, client


def writes(app):
    return MockLarkAdapter(WorkspaceStore(app.state.sessions, 'demo-ops', namespace=ADAPTER_NAMESPACE)).write_count


def entity(flow, entity_id):
    return next(e for e in flow['entities'] if e['entity_id'] == entity_id)


def assign(client, cid, entity_id=CASE, people=('u-pm',), **extra):
    return client.post(f'{URL}/assign', json={'command_id': cid, 'entity_id': entity_id, 'person_ids': list(people), **extra})


def propose(client, cid, value='2026-10-20', entity_id=CASE, expected=None, rev=0, **extra):
    body = {'command_id': cid, 'entity_id': entity_id, 'intended': value, 'expected_revision': rev,
            'occurred_at': '2026-10-11T00:00:00+00:00', **extra}
    if expected:
        body['expected'] = expected
    return client.post(f'{URL}/propose', json=body)


def decide(client, cid, decision, entity_id=CASE, **extra):
    return client.post(f'{URL}/decide', json={'command_id': cid, 'entity_id': entity_id, 'decision': decision, **extra})


def command(out, cid):
    return next(c for c in out['commands'] if c['command_id'] == cid)


def test_flow_lists_only_led_entities_with_unconfirmed_mapping_notice(rig):
    app, pm = rig
    flow = pm.get(URL).json()
    assert {e['entity_id'] for e in flow['entities']} >= {CASE, NODE} and flow['live'] is False
    assert '未確認' in flow['mapping_notice'] and '模擬' in flow['mapping_notice']
    assert {r['person_id'] for r in flow['roster']} >= {'u-pm', 'u-revoked', 'u-norecord', 'u-inactive'}
    assert as_user(app, 'u-field').get(URL).json()['entities'] == []


def test_assign_pm_is_confirmed_only_after_readback_and_is_idempotent(rig):
    app, pm = rig
    out = assign(pm, 'a1').json()
    assert command(out, 'a1')['state'] == 'confirmed' and entity(out, CASE)['seat']['person_id'] == 'u-pm'
    assert writes(app) == 1
    again = assign(pm, 'a1').json()
    assert again['outcome']['duplicate'] and writes(app) == 1 and len([c for c in again['commands'] if c['command_id'] == 'a1']) == 1
    assert assign(pm, 'a1', people=('u-manager',)).status_code == 409                          # same id, different payload


@pytest.mark.parametrize('person,fragment', [('u-revoked', '不具 PM 資格'), ('u-norecord', '無法確認'), ('u-inactive', '已啟用')])
def test_ineligible_unknown_or_inactive_pm_is_rejected_server_side(rig, person, fragment):
    app, pm = rig
    res = assign(pm, 'bad', people=(person,))
    assert res.status_code == 422 and fragment in res.text
    flow = pm.get(URL).json()
    assert entity(flow, CASE)['seat']['person_id'] is None and flow['commands'] == [] and writes(app) == 0


def test_multiple_assignees_rejected_and_prior_value_kept(rig):
    app, pm = rig
    assert command(assign(pm, 'a1').json(), 'a1')['state'] == 'confirmed'
    res = assign(pm, 'multi', people=('u-pm', 'u-manager'))
    assert res.status_code == 422 and '一次只能指派一位' in res.text
    seat = entity(pm.get(URL).json(), CASE)['seat']
    assert seat['person_id'] == 'u-pm' and seat['open_conflicts'] == ['assign:multi'] and writes(app) == 1


def test_role_gate_and_typed_person_binding_enforced_server_side(rig):
    app, pm = rig
    other = as_user(app, 'u-field')
    assert assign(other, 'x1').status_code == 403 and propose(other, 'x2').status_code == 403
    assert decide(other, 'x3', 'approved').status_code == 403
    assert assign(pm, 'x4', people=('林育寬',)).status_code == 422                              # a display name is not an identity
    assert assign(pm, 'x5', people=('ou_abc|x|y',)).status_code == 422
    assert assign(pm, 'x6', entity_id='case:nope').status_code == 404
    assert pm.get(URL).json()['commands'] == [] and writes(app) == 0


def test_raw_command_route_cannot_bypass_pm_eligibility(rig):
    app, pm = rig
    body = {'command_id': 'raw1', 'entity_id': CASE, 'field_id': 'case.pm', 'expected': {'t': 'clear'}, 'expected_revision': 0,
            'intended': {'t': 'set', 'v': PM('u-revoked')}, 'schema_binding_version': 'mock-binding-v1'}
    cmd = pm.post('/api/ops-sync/commands', json=body).json()['command']
    assert cmd['state'] == 'failed' and cmd['reason'] == 'ineligible' and writes(app) == 0
    free = pm.post('/api/ops-sync/commands', json={**body, 'command_id': 'raw2', 'intended': {'t': 'set', 'v': 'ou_free_string'}}).json()['command']
    assert free['state'] == 'failed' and free['reason'] == 'invalid_person'


def test_node_responsible_is_independent_of_the_case_pm(rig):
    app, pm = rig
    assert command(assign(pm, 'a1').json(), 'a1')['state'] == 'confirmed'
    out = assign(pm, 'n1', entity_id=NODE, people=('u-control',)).json()
    assert command(out, 'n1')['state'] == 'confirmed'
    assert entity(out, NODE)['seat']['person_id'] == 'u-control' and entity(out, CASE)['seat']['person_id'] == 'u-pm'
    assert assign(pm, 'n2', entity_id=NODE, people=('u-inactive',)).status_code == 422


def test_proposal_is_not_a_granted_receipt_and_leaves_effective_unchanged(rig):
    app, pm = rig
    out = propose(pm, 'p1').json()
    dl = entity(out, CASE)['deadline']
    assert dl['effective'] == {'value': None, 'revision': 0} and dl['proposals'][0]['state'] == 'waiting_approval'
    assert dl['proposals'][0]['receipt_id'] is None and dl['proposals'][0]['intended'] == '2026-10-20'
    assert command(out, 'p1')['state'] == 'waiting_approval' and writes(app) == 0
    assert propose(pm, 'p1').json()['outcome']['duplicate']


def test_stale_draft_is_a_409_that_records_nothing(rig):
    app, pm = rig
    propose(pm, 'p1'); decide(pm, 'p1', 'approved')
    stale = propose(pm, 'p2', value='2026-10-30')                                               # still expects the old baseline
    assert stale.status_code == 409
    flow = pm.get(URL).json()
    assert [p['proposal_id'] for p in entity(flow, CASE)['deadline']['proposals']] == ['p1']
    assert entity(flow, CASE)['deadline']['effective'] == {'value': '2026-10-20', 'revision': 1}
    ok = propose(pm, 'p2', value='2026-10-30', expected='2026-10-20', rev=1)
    assert ok.status_code == 200


def test_mock_approval_consumes_receipt_and_dispatches_the_same_command(rig):
    app, pm = rig
    propose(pm, 'p1')
    out = decide(pm, 'p1', 'approved').json()
    assert out['outcome']['mock'] is True and out['outcome']['status'] == 'confirmed'
    prop = entity(out, CASE)['deadline']['proposals'][0]
    assert prop['receipt_id'] == 'mock-receipt:p1' and prop['mock_receipt'] is True
    assert entity(out, CASE)['deadline']['effective'] == {'value': '2026-10-20', 'revision': 1}
    assert command(out, 'p1')['state'] == 'confirmed' and command(out, 'p1')['command_id'] == 'p1' and writes(app) == 1
    dup = decide(pm, 'p1', 'approved').json()
    assert dup['outcome']['duplicate'] and entity(dup, CASE)['deadline']['effective']['revision'] == 1 and writes(app) == 1


@pytest.mark.parametrize('decision,reason', [('rejected', 'rejected'), ('stale', 'stale_scope')])
def test_rejected_and_stale_decisions_never_change_effective_date_or_write(rig, decision, reason):
    app, pm = rig
    propose(pm, 'p1')
    out = decide(pm, 'p1', decision).json()
    assert entity(out, CASE)['deadline']['effective'] == {'value': None, 'revision': 0} and writes(app) == 0
    if decision == 'rejected':
        assert out['outcome']['status'] == 'failed' and command(out, 'p1')['state'] == 'failed'
        assert decide(pm, 'p1', 'approved').status_code == 422                                  # a closed proposal cannot be approved
    else:
        assert out['outcome']['status'] == 'denied' and out['outcome']['reason'] == reason
        assert command(out, 'p1')['state'] == 'waiting_approval'
        assert decide(pm, 'p1', 'approved').json()['outcome']['status'] == 'confirmed'          # fresh mock approval still works


def test_decisions_cannot_be_forged_or_target_unknown_proposals(rig):
    app, pm = rig
    propose(pm, 'p1')
    assert decide(pm, 'p1', 'granted').status_code == 422
    assert decide(pm, 'nope', 'approved').status_code == 404
    forged = pm.post('/api/ops-sync/commands', json={
        'command_id': 'forge', 'entity_id': CASE, 'field_id': 'case.deadline', 'expected': {'t': 'clear'}, 'expected_revision': 0,
        'intended': {'t': 'set', 'v': '2026-10-20'}, 'approval_ref': 'made-up', 'schema_binding_version': 'mock-binding-v1'}).json()['command']
    assert forged['state'] == 'waiting_approval' and writes(app) == 0                            # approval_ref in the body is ignored
    assert entity(pm.get(URL).json(), CASE)['deadline']['effective']['revision'] == 0


def test_unknown_outcome_reconciles_the_same_operation_without_a_second_write(rig):
    app, pm = rig
    out = assign(pm, 'a1', mock_outcome='timeout_after_commit').json()
    cmd = command(out, 'a1')
    assert cmd['state'] == 'unknown' and entity(out, CASE)['seat']['person_id'] == 'u-pm' and cmd['attempts'] == 1
    done = pm.post('/api/ops-sync/reconcile', json={'command_id': 'a1'}).json()
    assert command(done, 'a1')['state'] == 'confirmed' and writes(app) == 1


def test_concurrent_edit_surfaces_a_conflict_and_keeps_intent(rig):
    app, pm = rig
    out = assign(pm, 'a1', mock_outcome='concurrent_edit').json()
    assert command(out, 'a1')['state'] == 'conflict'
    conflict = out['conflicts'][0]
    assert conflict['intended']['value'] == PM('u-pm') and conflict['current']['value'] == PM('u-manager') and conflict['open']


def test_permission_loss_suspends_dispatch_globally_until_resumed(rig):
    app, pm = rig
    out = assign(pm, 'a1', mock_outcome='permission_lost').json()
    assert command(out, 'a1')['state'] == 'failed' and command(out, 'a1')['reason'] == 'permission_denied'
    assert [s['reason'] for s in out['dispatch_denial']['suspended']] == ['permission_denied']
    later = assign(pm, 'a2', entity_id=NODE, people=('u-control',)).json()
    assert command(later, 'a2')['state'] == 'pending' and later['dispatch_denial']['held_commands'] == ['a2'] and writes(app) == 0
    assert as_user(app, 'u-field').post(f'{URL}/resume-dispatch', json={}).status_code == 403
    resumed = pm.post(f'{URL}/resume-dispatch', json={}).json()
    assert resumed['dispatch_denial']['suspended'] == [] and command(resumed, 'a2')['state'] == 'confirmed'


def test_flow_routes_do_not_exist_when_flag_is_off(tmp_path):
    app, client = make(tmp_path, None)
    assert client.get(URL).status_code == 404
