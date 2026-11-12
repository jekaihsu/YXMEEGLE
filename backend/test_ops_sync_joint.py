"""Same-row route acceptance, rollback and CAS retries over the wired WorkspaceRow store."""
import copy
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from . import test_ops_sync_flow as T
from .ops_sync import values as V
from .ops_sync.adapter import MockLarkAdapter, Observation, PermissionDenied
from .ops_sync.domain import DomainService
from .ops_sync.engine import OpsEngine
from .ops_sync.routes import ADAPTER_NAMESPACE
from .ops_sync.workspace_store import WorkspaceStore
from .test_ops_sync_routes import as_user
from .test_ops_sync_single_path import assert_one_record

rig = T.rig


def store(app):
    return app.state.ops_store_for('demo-ops')


def mock(app):
    return MockLarkAdapter(WorkspaceStore(app.state.sessions, 'demo-ops', namespace=ADAPTER_NAMESPACE))


def seat(app):
    return store(app).snapshot()['domain']['cases'][T.CASE]['pm']


def conflict(client, person='u-pm'):
    out = T.assign(client, 'original', people=(person,), mock_outcome='concurrent_edit')
    assert out.status_code == 200, out.text
    return out.json()['conflicts'][0]


def resolve(client, item, cid, mode='keep_current'):
    return client.post(T.URL + '/resolve-conflict', json={
        'command_id': cid, 'conflict_id': item['conflict_id'], 'resolution': mode,
        'expected': {'t': 'set', 'v': item['current']['value']},
        'expected_revision': item['current']['revision']})


@pytest.mark.parametrize('loser,winner', [('apply_intended', 'keep_current'), ('keep_current', 'keep_current'),
                                         ('keep_current', 'apply_intended'), ('apply_intended', 'apply_intended')])
def test_f4_losing_resolver_preserves_winner_revision_history(rig, monkeypatch, loser, winner):
    app, client = rig
    item = conflict(client)
    paused, release = Event(), Event()
    original = DomainService._assign

    def barrier(self, dom, slot, entity_id, field_id, action, command_id, *args):
        if command_id == 'resolver-a' and not paused.is_set():
            paused.set()
            assert release.wait(10), 'resolver B did not release A'
        return original(self, dom, slot, entity_id, field_id, action, command_id, *args)

    monkeypatch.setattr(DomainService, '_assign', barrier)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(resolve, as_user(app, 'u-pm'), item, 'resolver-a', loser)
        try:
            assert paused.wait(10), 'A did not pass baseline and reach domain assignment'
            out = resolve(client, item, 'resolver-b', winner)
            assert out.status_code == 200, out.text
            winning_seat = copy.deepcopy(seat(app))
        finally:
            release.set()
        out = future.result(timeout=10)
    assert out.status_code == 409, out.text
    assert seat(app) == winning_seat, 'losing resolver changed the winner domain slot/revision/history'
    snap = store(app).snapshot()
    assert 'resolver-a' not in snap['domain']['ledger'] and 'resolver-a' not in snap['commands']
    assert_one_record(app, 'losing resolver')


@pytest.mark.parametrize('route', ['assign', 'propose', 'resolve'])
@pytest.mark.parametrize('failure', ['unavailable', 'incomplete', 'missing_value', 'missing_revision', 'wrong_binding'])
def test_failed_baseline_records_no_domain_mutation(rig, monkeypatch, route, failure):
    app, client = rig
    item = conflict(client) if route == 'resolve' else None
    client.get(T.URL)
    before = store(app).snapshot()['domain']

    def broken(self, entity_id, fields):
        if failure == 'unavailable':
            raise PermissionDenied('test unavailable')
        if failure == 'incomplete':
            return Observation(False, reason='test partial')
        if failure == 'missing_value':
            return Observation(True, {}, {fields[0]: 0})
        if failure == 'missing_revision':
            return Observation(True, {fields[0]: V.CLEAR}, {})
        return Observation(True, {fields[0]: V.CLEAR}, {fields[0]: 0}, 'wrong-binding')

    monkeypatch.setattr(MockLarkAdapter, 'read', broken)
    if route == 'assign':
        out = T.assign(client, 'bad-read')
    elif route == 'propose':
        out = T.propose(client, 'bad-read')
    else:
        out = resolve(client, item, 'bad-read')
    assert out.status_code == 409, out.text
    assert store(app).snapshot()['domain'] == before
    assert 'bad-read' not in store(app).snapshot().get('commands', {})


@pytest.mark.parametrize('route', ['assign', 'propose', 'resolve', 'approved', 'rejected', 'stale_conflict'])
def test_engine_failure_rolls_back_domain_and_receipts(rig, monkeypatch, route):
    app, client = rig
    item = conflict(client) if route == 'resolve' else None
    if route in ('approved', 'rejected', 'stale_conflict'):
        T.propose(client, 'proposal')
        if route == 'stale_conflict':
            # Another approved proposal changes the effective baseline.
            T.propose(client, 'winner', value='2026-11-01')
            assert T.decide(client, 'winner', 'approved').status_code == 200
    client.get(T.URL)
    before = store(app).snapshot()['domain']

    def fail(*args, **kwargs):
        raise RuntimeError('test engine persistence failure')

    method = '_submit_in_txn' if route in ('assign', 'propose', 'resolve') else (
        'grant_approval' if route == 'approved' else 'reject_approval')
    # Cover both the committing baseline API and its non-committing replacement.
    monkeypatch.setattr(OpsEngine, method, fail)
    if hasattr(OpsEngine, method + '_in_txn'):
        monkeypatch.setattr(OpsEngine, method + '_in_txn', fail)
    with pytest.raises(RuntimeError, match='test engine persistence failure'):
        if route == 'assign':
            T.assign(client, 'failed')
        elif route == 'propose':
            T.propose(client, 'failed')
        elif route == 'resolve':
            resolve(client, item, 'failed')
        else:
            T.decide(client, 'proposal', 'rejected' if route == 'rejected' else 'approved')
    assert store(app).snapshot()['domain'] == before, 'engine failure persisted its domain half'
    assert_one_record(app, 'rollback')


def test_expiry_and_engine_rejection_commit_together_even_on_denied_decision(rig):
    app, client = rig
    T.propose(client, 'expired')
    T.propose(client, 'also-expired', entity_id=T.NODE)
    def age(ns):
        for rec in list(ns['domain']['cases'].values()) + list(ns['domain']['nodes'].values()):
            for prop in rec['deadline']['proposals'].values():
                prop['expires_at'] = '2000-01-01T00:00:00+00:00'
    store(app).transact(age)
    assert T.decide(client, 'expired', 'approved').status_code == 422
    snap = store(app).snapshot()
    for eid, cid in ((T.CASE, 'expired'), (T.NODE, 'also-expired')):
        rec = snap['domain']['cases'].get(eid) or snap['domain']['nodes'][eid]
        assert rec['deadline']['proposals'][cid]['reason'] == 'expired'
        assert snap['commands'][cid]['state'] == 'failed'
        assert snap['commands'][cid]['reason'] == 'expired'
        assert rec['deadline']['effective']['revision'] == 0


@pytest.mark.parametrize('boundary', ['before_update', 'updated', 'committed'])
@pytest.mark.parametrize('route', ['assign', 'propose', 'approved', 'rejected', 'resolve'])
def test_restart_at_commit_boundary_never_leaves_a_split_record(rig, monkeypatch, boundary, route):
    app, client = rig
    item = conflict(client) if route == 'resolve' else None
    if route in ('approved', 'rejected'):
        T.propose(client, 'proposal')
    client.get(T.URL)
    before = store(app).snapshot()['domain']
    factory = app.state.ops_store_for
    original_tx = WorkspaceStore.transact
    armed = False

    def tracked(self, fn):
        def apply(ns):
            nonlocal armed
            prior = copy.deepcopy(ns.get('domain'))
            result = fn(ns)
            if self.namespace == 'ops_sync' and ns.get('domain') != prior:
                armed = True
            return result
        return original_tx(self, apply)

    def crash(name):
        if armed and name == boundary:
            raise RuntimeError('test process interruption')

    monkeypatch.setattr(WorkspaceStore, 'transact', tracked)
    app.state.ops_store_for = lambda wid: WorkspaceStore(app.state.sessions, wid, hook=crash)
    with pytest.raises(RuntimeError, match='test process interruption'):
        if route == 'assign':
            T.assign(client, 'interrupted')
        elif route == 'propose':
            T.propose(client, 'interrupted')
        elif route == 'resolve':
            resolve(client, item, 'interrupted')
        else:
            T.decide(client, 'proposal', route)
    app.state.ops_store_for = factory
    reopened = WorkspaceStore(app.state.sessions, 'demo-ops').snapshot()
    if boundary != 'committed':
        assert reopened['domain'] == before
    else:
        cid = 'proposal' if route in ('approved', 'rejected') else 'interrupted'
        assert cid in reopened['commands'], 'domain committed without command'
        expected = 'failed' if route == 'rejected' else 'waiting_approval' if route == 'propose' else (
            'queued')
        assert reopened['commands'][cid]['state'] == expected
    assert_one_record(app, 'reopened after interruption')


def test_route_guard_requires_domain_and_engine_in_same_commit(rig, monkeypatch):
    app, client = rig
    client.get(T.URL)
    original = WorkspaceStore.transact
    violations = []
    def guarded(self, fn):
        def apply(ns):
            prior = copy.deepcopy(ns)
            result = fn(ns)
            if self.namespace == 'ops_sync' and ns.get('domain') != prior.get('domain'):
                # Ignore idempotent header registration; every ledgered mutation has an engine half.
                dom = ns['domain']
                ids = set(dom['ledger']) - set(prior['domain']['ledger'])
                for cid in ids:
                    if dom['ledger'][cid]['result']['status'] in ('assigned', 'cleared', 'waiting_approval'):
                        if cid not in ns.get('commands', {}):
                            violations.append(cid)
                for eid, rec in dom['cases'].items():
                    for cid, prop in rec['deadline']['proposals'].items():
                        cmd = ns.get('commands', {}).get(cid)
                        if cmd and prop['state'] in ('confirmed', 'failed') and cmd['state'] == 'waiting_approval':
                            violations.append(cid)
            return result
        return original(self, apply)
    monkeypatch.setattr(WorkspaceStore, 'transact', guarded)
    T.assign(client, 'a1')
    T.propose(client, 'p1')
    T.decide(client, 'p1', 'approved')
    T.propose(client, 'p2', expected='2026-10-20', rev=1)
    T.decide(client, 'p2', 'rejected')
    item = conflict(client, 'u-control')
    resolve(client, item, 'resolver')
    assert violations == [], 'split committing operations: ' + str(violations)


@pytest.mark.parametrize('operation', ['assign', 'direct_edit'])
@pytest.mark.parametrize('mode', ['keep_current', 'apply_intended'])
def test_resolver_racing_another_writer_never_overwrites_or_falsely_confirms(rig, monkeypatch, operation, mode):
    app, client = rig
    item = conflict(client)
    paused, release = Event(), Event()
    original = DomainService._assign
    def barrier(self, dom, slot, entity_id, field_id, action, cid, *args):
        if cid == 'resolver' and not paused.is_set():
            paused.set()
            assert release.wait(10)
        return original(self, dom, slot, entity_id, field_id, action, cid, *args)
    monkeypatch.setattr(DomainService, '_assign', barrier)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(resolve, as_user(app, 'u-pm'), item, 'resolver', mode)
        try:
            assert paused.wait(10)
            if operation == 'assign':
                assert T.assign(client, 'winner', people=('u-control',)).status_code == 200
            else:
                mock(app).direct_edit(T.CASE, 'case.pm', V.SetValue(T.PM('u-control')))
            winning_seat = copy.deepcopy(seat(app))
        finally:
            release.set()
        out = future.result(timeout=10)
    if operation == 'assign':
        assert out.status_code == 409, out.text
        assert seat(app) == winning_seat
    elif out.status_code == 409:
        assert seat(app) == winning_seat, 'refused resolver persisted its domain half'
    else:
        assert out.status_code == 200, out.text
        assert T.command(out.json(), 'resolver')['state'] == 'conflict'
    assert mock(app).read(T.CASE, ['case.pm']).values['case.pm'] == V.SetValue(T.PM('u-control'))
    assert_one_record(app, 'concurrent writer')


def test_concurrent_assign_preserves_newer_domain_value(rig, monkeypatch):
    app, client = rig
    client.get(T.URL)
    paused, release = Event(), Event()
    original = DomainService._assign
    def barrier(self, dom, slot, entity_id, field_id, action, cid, *args):
        if cid == 'loser' and not paused.is_set():
            paused.set()
            assert release.wait(10)
        return original(self, dom, slot, entity_id, field_id, action, cid, *args)
    monkeypatch.setattr(DomainService, '_assign', barrier)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(T.assign, as_user(app, 'u-pm'), 'loser')
        try:
            assert paused.wait(10)
            assert T.assign(client, 'winner', people=('u-manager',)).status_code == 200
            winner = copy.deepcopy(seat(app))
        finally:
            release.set()
        assert future.result(timeout=10).status_code == 409
    assert seat(app) == winner
    assert 'loser' not in store(app).snapshot()['domain']['ledger']
    assert_one_record(app)


def test_interleaved_non_ops_writer_retries_once_without_duplicate_history(rig, monkeypatch):
    app, client = rig
    client.get(T.URL)
    injected = False
    attempts = 0
    def interleave(name):
        nonlocal injected, attempts
        if name == 'before_update':
            attempts += 1
            if not injected:
                injected = True
                # Another namespace uses the same row version-CAS and must survive our retry.
                WorkspaceStore(app.state.sessions, 'demo-ops', namespace='non_ops_probe').transact(
                    lambda ns: ns.update(preserved='other writer'))
    app.state.ops_store_for = lambda wid: WorkspaceStore(app.state.sessions, wid, hook=interleave)
    out = T.assign(client, 'retried')
    assert out.status_code == 200, out.text
    assert attempts >= 2
    assert len([h for h in seat(app)['history'] if h['command_id'] == 'retried']) == 1
    assert len([c for c in store(app).snapshot()['commands'] if c == 'retried']) == 1
    assert store(app).snapshot_raw()['non_ops_probe'] == {'preserved': 'other writer', '_commit_seq': 1}
    assert T.assign(client, 'retried').json()['outcome']['duplicate']
    assert len(seat(app)['history']) == 1
    assert_one_record(app)


@pytest.mark.parametrize('route', ['reconcile', 'resume-dispatch'])
def test_engine_only_routes_do_not_mutate_domain(rig, route):
    app, client = rig
    T.assign(client, 'pending', mock_outcome='timeout_after_commit' if route == 'reconcile' else 'permission_lost')
    before = copy.deepcopy(store(app).snapshot()['domain'])
    out = client.post(T.URL + '/' + route, json={'command_id': 'pending'})
    assert out.status_code == 200, out.text
    assert store(app).snapshot()['domain'] == before
    assert_one_record(app)


def test_resolution_cannot_reuse_a_domain_command_id(rig):
    app, client = rig
    T.assign(client, 'existing', people=('u-manager',))
    item = conflict(client)
    before = copy.deepcopy(store(app).snapshot())
    out = resolve(client, item, 'existing')
    assert out.status_code == 409, out.text
    assert store(app).snapshot()['domain'] == before['domain']
    assert store(app).snapshot()['conflicts'] == before['conflicts']


@pytest.mark.parametrize('decision', ['approved', 'rejected'])
def test_replayed_stale_and_closed_decisions_do_not_change_effective_history(rig, decision):
    app, client = rig
    assert T.propose(client, 'p1').status_code == 200
    assert T.decide(client, 'p1', 'stale').json()['outcome']['reason'] == 'stale_scope'
    assert T.decide(client, 'p1', decision).status_code == 200
    before = copy.deepcopy(store(app).snapshot()['domain'])
    out = T.decide(client, 'p1', 'approved')
    assert out.status_code == (200 if decision == 'approved' else 422)
    assert store(app).snapshot()['domain'] == before
    assert_one_record(app)


def test_adapter_io_never_runs_inside_acceptance_transaction(rig, monkeypatch):
    app, client = rig
    original_tx, original_read = WorkspaceStore.transact, MockLarkAdapter.read
    active = False

    def tracked(self, fn):
        def apply(ns):
            nonlocal active
            active = True
            try:
                return fn(ns)
            finally:
                active = False
        return original_tx(self, apply)

    def read(self, *args):
        assert not active, 'adapter read inside a retryable namespace callback'
        return original_read(self, *args)

    monkeypatch.setattr(WorkspaceStore, 'transact', tracked)
    monkeypatch.setattr(MockLarkAdapter, 'read', read)
    assert T.assign(client, 'pm').status_code == 200
    assert T.assign(client, 'node', entity_id=T.NODE, people=('u-control',)).status_code == 200
    assert T.propose(client, 'date').status_code == 200
    assert T.decide(client, 'date', 'approved').status_code == 200
    item = conflict(client, 'u-control')
    assert resolve(client, item, 'resolver').status_code == 200
    assert_one_record(app, 'adapter I/O outside transactions')


def test_unchanged_assignment_without_delivery_does_not_run_adapter_side_effects(rig):
    app, client = rig
    assert T.assign(client, 'first').status_code == 200
    before = copy.deepcopy(mock(app).store.snapshot())
    out = T.assign(client, 'unchanged', mock_outcome='concurrent_edit')
    assert out.status_code == 200, out.text
    assert out.json()['outcome']['status'] == 'unchanged'
    assert out.json()['command'] is None
    assert mock(app).store.snapshot() == before
    assert_one_record(app, 'unchanged assignment')
