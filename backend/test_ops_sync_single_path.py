"""One logical record, one write path (YXS-51 / F1).

After EVERY exposed ops-sync mutation the domain record (seat / effective deadline + history), the engine projection and
the mock adapter must tell the same story. When they legitimately differ (undelivered, unknown, failed or conflicted
delivery) the difference must be carried by a visible non-confirmed command, and every engine command must have a domain
counterpart (no orphan). The raw engine-only write routes must not exist, so the split cannot be reintroduced by a client.
"""
import pytest

from . import test_ops_sync_flow as T
from .ops_sync import values as V
from .ops_sync.adapter import MockLarkAdapter
from .ops_sync.domain import DomainService
from .ops_sync.flow import Fixtures
from .ops_sync.routes import ADAPTER_NAMESPACE
from .ops_sync.workspace_store import WorkspaceStore
from .test_ops_sync_routes import as_user, make

CASE, NODE, URL, PM = T.CASE, T.NODE, T.URL, T.PM
FIELDS = ((CASE, 'case.pm'), (NODE, 'node.responsible'), (CASE, 'case.deadline'), (NODE, 'node.deadline'))
rig = T.rig


def _domain_value(dom, entity_id, field_id):
    rec = dom['cases'].get(entity_id) or dom['nodes'].get(entity_id)
    if field_id.endswith('.deadline'):
        return V.decode(rec['deadline']['effective']['value'])
    slot = rec['pm'] if field_id == 'case.pm' else rec['responsible']
    return V.SetValue(slot['person']) if slot['person'] else V.CLEAR


def _domain_has(dom, entity_id, command_id, field_id):
    rec = dom['cases'].get(entity_id) or dom['nodes'].get(entity_id)
    if field_id.endswith('.deadline'):
        return command_id in rec['deadline']['proposals'] or any(
            p['proposal_id'] == command_id for p in rec['deadline']['proposals'].values())
    slot = rec['pm'] if field_id == 'case.pm' else rec['responsible']
    return any(h['command_id'] == command_id for h in slot['history']) or command_id in dom['ledger']


def assert_one_record(app, label=''):
    """domain == engine projection == mock for every field with no outstanding delivery; no orphan commands."""
    sessions = app.state.sessions
    store = app.state.ops_store_for('demo-ops')
    mock = MockLarkAdapter(WorkspaceStore(sessions, 'demo-ops', namespace=ADAPTER_NAMESPACE))
    snap = store.snapshot()
    dom = snap.get('domain', {'cases': {}, 'nodes': {}, 'ledger': {}})
    commands = list(snap.get('commands', {}).values())
    conflicts = list(snap.get('conflicts', {}).values())
    for cmd in commands:
        env = cmd['envelope']
        assert _domain_has(dom, env['entity_id'], env['command_id'], env['field_id']), (
            f'{label}: orphan engine command {env["command_id"]} ({env["field_id"]}) has no domain record')
    for entity_id, field_id in FIELDS:
        if entity_id not in dom['cases'] and entity_id not in dom['nodes']:
            continue
        domain = _domain_value(dom, entity_id, field_id)
        proj = snap.get('projection', {}).get(f'{entity_id}|{field_id}')
        engine = V.decode(proj['value']) if proj else V.CLEAR
        read = mock.read(entity_id, [field_id]).values[field_id]
        mine = [c for c in commands if c['envelope']['entity_id'] == entity_id and c['envelope']['field_id'] == field_id]
        resolved = {k['command_id'] for k in conflicts if k['resolution']}          # a resolved conflict is closed by its own command
        outstanding = [c for c in mine if c['state'] != 'confirmed' and c['envelope']['command_id'] not in resolved]
        if outstanding:
            states = {c['state'] for c in outstanding}
            if 'conflict' in states:
                assert any(not k['resolution'] for k in conflicts if k['entity_id'] == entity_id and k['field_id'] == field_id), label
            continue
        assert domain == engine == read, f'{label}: {entity_id} {field_id} domain={domain} engine={engine} mock={read}'


def _hit_all(app, steps):
    for name, fn in steps:
        fn()
        assert_one_record(app, name)


def test_raw_engine_write_routes_do_not_exist(rig):
    app, pm = rig
    raw = {'command_id': 'raw1', 'entity_id': CASE, 'field_id': 'case.pm', 'expected': {'t': 'clear'}, 'expected_revision': 0,
           'intended': {'t': 'set', 'v': PM('u-pm')}, 'schema_binding_version': 'mock-binding-v1'}
    codes = [pm.post('/api/ops-sync/commands', json=raw).status_code,
             pm.post('/api/ops-sync/conflicts/x/resolve', json={}).status_code,
             pm.post('/api/ops-sync/reconcile', json={'command_id': 'x'}).status_code]
    assert all(code in (404, 405) for code in codes), codes
    assert_one_record(app, 'after rejected raw attempts')
    assert pm.get(URL).json()['commands'] == []


def test_raw_deadline_cannot_create_an_orphan_approval(rig):
    app, pm = rig
    pm.post('/api/ops-sync/commands', json={
        'command_id': 'raw-d', 'entity_id': CASE, 'field_id': 'case.deadline', 'expected': {'t': 'clear'}, 'expected_revision': 0,
        'intended': {'t': 'set', 'v': '2026-10-20'}, 'schema_binding_version': 'mock-binding-v1'})
    assert_one_record(app, 'raw deadline attempt')
    assert T.decide(pm, 'raw-d', 'approved').status_code == 404       # nothing to approve: no orphan command exists


def test_every_exposed_mutation_keeps_one_record(rig):
    app, pm = rig
    state = {}
    steps = [
        ('assign case pm', lambda: T.assign(pm, 'a1')),
        ('assign pm again (duplicate)', lambda: T.assign(pm, 'a1')),
        ('assign node responsible', lambda: T.assign(pm, 'n1', entity_id=NODE, people=('u-control',))),
        ('reassign pm', lambda: T.assign(pm, 'a2', people=('u-manager',))),
        ('rejected: ineligible pm', lambda: T.assign(pm, 'a3', people=('u-revoked',))),
        ('rejected: multiple assignees', lambda: T.assign(pm, 'a4', people=('u-pm', 'u-control'))),
        ('clear pm', lambda: T.assign(pm, 'a5', people=())),
        ('assign pm for deadlines', lambda: T.assign(pm, 'a6', people=('u-pm',))),
        ('propose', lambda: T.propose(pm, 'p1')),
        ('decide stale', lambda: T.decide(pm, 'p1', 'stale')),
        ('decide approved', lambda: T.decide(pm, 'p1', 'approved')),
        ('propose node deadline', lambda: T.propose(pm, 'p2', entity_id=NODE)),
        ('decide rejected', lambda: T.decide(pm, 'p2', 'rejected', entity_id=NODE)),
        ('propose again', lambda: T.propose(pm, 'p3', value='2026-10-30', expected='2026-10-20', rev=1)),
        ('decide approved with timeout', lambda: T.decide(pm, 'p3', 'approved', mock_outcome='timeout_after_commit')),
        ('reconcile', lambda: pm.post(f'{URL}/reconcile', json={'command_id': 'p3'})),
        ('assign with timeout', lambda: T.assign(pm, 'a7', people=('u-manager',), mock_outcome='timeout_after_commit')),
        ('reconcile seat', lambda: pm.post(f'{URL}/reconcile', json={'command_id': 'a7'})),
        ('assign with permission loss', lambda: T.assign(pm, 'a8', people=('u-pm',), mock_outcome='permission_lost')),
        ('resume dispatch', lambda: pm.post(f'{URL}/resume-dispatch', json={})),
        ('assign with concurrent edit', lambda: state.update(out=T.assign(pm, 'a9', people=('u-control',), mock_outcome='concurrent_edit').json())),
    ]
    _hit_all(app, steps)
    conflict = state['out']['conflicts'][0]
    assert conflict['open'] and conflict['field_id'] == 'case.pm'
    for mode, label in (('keep_current', 'resolve keep_current'),):
        out = pm.post(f'{URL}/resolve-conflict', json={
            'conflict_id': conflict['conflict_id'], 'command_id': 'r1', 'resolution': mode, 'reason': 'synthetic',
            'expected': {'t': conflict['current']['kind'], 'v': conflict['current']['value']},
            'expected_revision': conflict['current']['revision']})
        assert out.status_code == 200, out.text
        assert_one_record(app, label)
    final = pm.get(URL).json()
    assert T.entity(final, CASE)['seat']['person_id'] == 'u-manager'    # keep_current adopted the mock's value in the domain too


def test_restart_keeps_one_record(rig, tmp_path):
    app, pm = rig
    T.assign(pm, 'a1')
    T.propose(pm, 'p1'); T.decide(pm, 'p1', 'approved')
    assert_one_record(app, 'before restart')
    from .app import create_app
    cfg = {'DATABASE_URL': f'sqlite:///{tmp_path}/ops.db', 'UPLOAD_DIR': str(tmp_path / 'up'), 'DEMO_MODE': 'true',
           'APP_ENV': 'development', 'SESSION_SECRET': 'ops-routes-tests' * 4, 'FEATURE_LARK_AUTHORITATIVE_OPS': 'true'}
    app2 = create_app(cfg)
    client2 = as_user(app2, 'u-pm')
    assert client2.get(URL).status_code == 200
    assert_one_record(app2, 'after restart')


def test_conflict_apply_intended_realigns_domain_and_mock(rig):
    app, pm = rig
    state = T.assign(pm, 'a1', mock_outcome='concurrent_edit').json()
    k = state['conflicts'][0]
    assert T.entity(state, CASE)['seat']['person_id'] == 'u-pm'
    out = pm.post(f'{URL}/resolve-conflict', json={
        'conflict_id': k['conflict_id'], 'command_id': 'r1', 'resolution': 'apply_intended', 'reason': 'synthetic',
        'expected': {'t': 'set', 'v': k['current']['value']}, 'expected_revision': k['current']['revision']})
    assert out.status_code == 200, out.text
    assert_one_record(app, 'apply_intended')
    assert T.command(out.json(), 'r1')['state'] == 'confirmed'
    stale = pm.post(f'{URL}/resolve-conflict', json={
        'conflict_id': k['conflict_id'], 'command_id': 'r2', 'resolution': 'apply_intended', 'reason': 'again',
        'expected': {'t': 'set', 'v': k['current']['value']}, 'expected_revision': k['current']['revision']})
    assert stale.status_code == 409
    assert_one_record(app, 'stale resolve')


def test_conflict_resolution_is_gated_by_the_domain(rig):
    app, pm = rig
    # concurrent edit leaves an ineligible person in the mock; keeping it would write the seat past the eligibility gate
    pm.post(f'{URL}/assign', json={'command_id': 'a1', 'entity_id': CASE, 'person_ids': ['u-pm'], 'mock_outcome': 'concurrent_edit'})
    flow = pm.get(URL).json()
    k = flow['conflicts'][0]
    app_store = app.state.ops_store_for('demo-ops')
    MockLarkAdapter(WorkspaceStore(app.state.sessions, 'demo-ops', namespace=ADAPTER_NAMESPACE)).direct_edit(
        CASE, 'case.pm', V.SetValue(PM('u-revoked')))
    out = pm.post(f'{URL}/resolve-conflict', json={
        'conflict_id': k['conflict_id'], 'command_id': 'r1', 'resolution': 'keep_current', 'reason': 'x',
        'expected': {'t': 'set', 'v': PM('u-revoked')}, 'expected_revision': 3})
    assert out.status_code in (409, 422)
    seat = T.entity(pm.get(URL).json(), CASE)['seat']
    assert seat['person_id'] == 'u-pm'                                    # domain seat untouched by the refused resolution
    assert app_store is not None


def test_deadline_conflicts_are_not_resolvable_outside_a_proposal(rig):
    app, pm = rig
    T.assign(pm, 'a1')
    T.propose(pm, 'p1')
    out = T.decide(pm, 'p1', 'approved', mock_outcome='concurrent_edit').json()
    k = out['conflicts'][0]
    assert k['field_id'] == 'case.deadline'
    res = pm.post(f'{URL}/resolve-conflict', json={
        'conflict_id': k['conflict_id'], 'command_id': 'r1', 'resolution': 'apply_intended', 'reason': 'x',
        'expected': {'t': 'set', 'v': k['current']['value']}, 'expected_revision': k['current']['revision']})
    assert res.status_code == 422
    assert_one_record(app, 'deadline conflict refused')


def test_non_lead_cannot_use_new_flow_mutations(rig):
    app, pm = rig
    T.assign(pm, 'a1', mock_outcome='concurrent_edit')
    k = pm.get(URL).json()['conflicts'][0]
    other = as_user(app, 'u-field')
    assert other.post(f'{URL}/resolve-conflict', json={'conflict_id': k['conflict_id'], 'command_id': 'r1', 'resolution': 'keep_current',
                                                     'expected': {'t': 'clear'}, 'expected_revision': 0}).status_code == 403
    assert other.post(f'{URL}/reconcile', json={'command_id': 'a1'}).status_code == 403
    assert_one_record(app, 'non-lead attempts')
