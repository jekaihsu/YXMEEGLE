import pytest

from .ops_sync import adapter as A
from .ops_sync import values as V
from .ops_sync.clock import FakeClock
from .ops_sync.engine import IdentityCollision, OpsEngine
from .ops_sync.store import JsonFileStore
from .ops_sync.testing import env, open_store, ws_path

E = 'case_test_1'
D1, D2 = V.SetValue('2026-10-20'), V.SetValue('2026-10-25')


class Rig:
    """Persistent stores + injectable clock; `restart()` simulates a fresh process on the same files."""

    def __init__(self, tmp_path, kind='file'):
        self.kind = kind
        self.ws = ws_path(tmp_path, kind)
        self.lark = tmp_path / 'lark.json'
        self.clock = FakeClock()
        self.adapter = A.MockLarkAdapter(JsonFileStore(self.lark, namespace='mock_lark'))
        self.engine = self.make()

    def make(self, **kw):
        return OpsEngine(open_store(self.kind, self.ws), self.adapter, self.clock, **kw)

    def restart(self, **kw):
        self.adapter = A.MockLarkAdapter(JsonFileStore(self.lark, namespace='mock_lark'))
        self.engine = self.make(**kw)
        return self.engine

    def history(self, command_id):
        return [h for h in self.engine.snapshot()['history'] if h.get('command_id') == command_id]


@pytest.fixture
def rig(tmp_path, store_kind):
    r = Rig(tmp_path, store_kind)
    assert r.engine.observe(E)['complete']
    return r


def drive(rig, *ids):
    attempts = [rig.engine.begin_dispatch(i) for i in ids]
    return [rig.engine.dispatch(a) for a in attempts if a]


def test_submit_is_durable_and_replay_is_idempotent(rig):
    first = rig.engine.submit(env('c1'))
    assert first['status'] == 'queued' and not first['duplicate']
    again = rig.restart().submit(env('c1'))
    assert again['duplicate'] and again['status'] == 'queued'
    assert rig.engine.snapshot()['outbox'] == ['c1']
    with pytest.raises(IdentityCollision):
        rig.engine.submit(env('c1', intended=D2))
    assert len(rig.engine.snapshot()['commands']) == 1


def test_confirmed_write_updates_projection_and_history_once(rig):
    rig.engine.submit(env('c1'))
    assert rig.engine.run_once() == ['c1']
    assert rig.engine.status('c1')['state'] == 'confirmed'
    assert rig.engine.projection(E, 'case.deadline') == (D1, 1)
    assert len(rig.history('c1')) == 1
    assert rig.engine.run_once() == []
    assert rig.adapter.write_count == 1
    assert rig.engine.snapshot()['outbox'] == []


def test_same_field_race_conflicts_without_overwrite(rig):
    rig.engine.submit(env('a', intended=D1))
    rig.engine.submit(env('b', intended=D2))
    rig.engine.run_once()
    assert rig.engine.status('a')['state'] == 'confirmed'
    assert rig.engine.status('b')['state'] == 'conflict'
    conflict = rig.engine.snapshot()['conflicts']['conflict:b']
    assert conflict['expected'] == {'value': {'t': 'clear'}, 'revision': 0}
    assert conflict['current'] == {'value': {'t': 'set', 'v': '2026-10-20'}, 'revision': 1}
    assert conflict['intended'] == {'t': 'set', 'v': '2026-10-25'}
    assert rig.engine.projection(E, 'case.deadline') == (D1, 1)
    assert rig.adapter.write_count == 1


def test_adapter_cas_catches_direct_edit_between_check_and_write(rig):
    rig.engine.submit(env('a', intended=D1))
    attempt = rig.engine.begin_dispatch('a')
    rig.adapter.direct_edit(E, 'case.deadline', D2)   # direct Lark editor wins the race after our check
    rig.engine.dispatch(attempt)
    assert rig.engine.status('a')['state'] == 'conflict'
    assert rig.engine.snapshot()['conflicts']['conflict:a']['current']['value'] == {'t': 'set', 'v': '2026-10-25'}
    assert rig.adapter.read(E, ['case.deadline']).values['case.deadline'] == D2


def test_different_field_race_merges_field_patches(rig):
    rig.engine.submit(env('a', field='case.deadline', intended=D1))
    rig.engine.submit(env('b', field='case.pm', intended=V.SetValue('ou_test_pm_2')))
    rig.engine.run_once()
    assert [rig.engine.status(c)['state'] for c in 'ab'] == ['confirmed', 'confirmed']
    obs = rig.adapter.read(E, ['case.deadline', 'case.pm'])
    assert obs.values == {'case.deadline': D1, 'case.pm': V.SetValue('ou_test_pm_2')}
    assert len(rig.history('a')) == len(rig.history('b')) == 1


def test_same_value_new_revision_still_conflicts(rig):
    rig.adapter.direct_edit(E, 'case.pm', V.SetValue('ou_test_pm_1'))
    rig.adapter.direct_edit(E, 'case.pm', V.CLEAR)    # changed away and back to the baseline value
    rig.engine.submit(env('a', field='case.pm', expected=V.CLEAR, expected_revision=0, intended=V.SetValue('ou_test_pm_3')))
    rig.engine.observe(E)
    assert rig.engine.projection(E, 'case.pm') == (V.CLEAR, 2)
    rig.engine.run_once()
    assert rig.engine.status('a')['state'] == 'conflict'
    assert rig.adapter.write_count == 0


def test_timeout_after_commit_restart_reconciles_same_command_once(rig):
    rig.adapter.inject('timeout_after_commit')
    rig.engine.submit(env('c1'))
    rig.engine.run_once()
    state = rig.engine.status('c1')
    assert state['state'] == 'unknown' and state['reconcile']['phase'] == 'pending'
    assert rig.engine.projection(E, 'case.deadline') == (V.CLEAR, 0)   # effective value untouched until proven
    engine = rig.restart()
    assert engine.run_once() == ['c1']
    assert engine.status('c1')['state'] == 'confirmed'
    assert engine.projection(E, 'case.deadline') == (D1, 1)
    assert rig.adapter.write_count == 1
    assert len(rig.history('c1')) == 1
    assert set(engine.snapshot()['commands']) == {'c1'}
    assert engine.run_once() == [] and rig.adapter.write_count == 1


def test_unknown_requires_proven_noncommit_before_same_id_retry(rig):
    rig.adapter.inject('timeout_before_commit')
    rig.engine.submit(env('c1'))
    rig.engine.run_once()
    assert rig.engine.status('c1')['state'] == 'unknown'
    assert rig.adapter.write_count == 0
    # reads are partial -> no proof -> no retry, no write, still unknown
    rig.adapter.inject('partial_read')
    rig.engine.run_once()
    status = rig.engine.status('c1')
    assert status['state'] == 'unknown' and status['reason'] == 'partial_read' and rig.adapter.write_count == 0
    rig.clock.advance(1)
    rig.engine.run_once()                # ledger + complete read prove non-commit -> queued with SAME id
    assert rig.engine.status('c1')['state'] == 'queued'
    rig.engine.run_once()
    assert rig.engine.status('c1')['state'] == 'confirmed'
    assert rig.adapter.write_count == 1 and set(rig.engine.snapshot()['commands']) == {'c1'}


def test_unknown_with_changed_baseline_becomes_conflict_not_retry(rig):
    rig.adapter.inject('timeout_before_commit')
    rig.engine.submit(env('c1'))
    rig.engine.run_once()
    rig.adapter.direct_edit(E, 'case.deadline', D2)
    rig.engine.run_once()
    assert rig.engine.status('c1')['state'] == 'conflict'
    assert rig.adapter.write_count == 0


def test_equal_value_without_ledger_is_not_identity_proof(rig):
    rig.adapter.inject('timeout_before_commit')
    rig.engine.submit(env('c1', intended=D1))
    rig.engine.run_once()
    rig.adapter.direct_edit(E, 'case.deadline', D1)    # someone else set the same value
    rig.engine.run_once()
    assert rig.engine.status('c1')['state'] == 'conflict'
    assert rig.history('c1') == []


def test_retry_bound_and_backoff_with_injected_clock(rig):
    rig.adapter.inject('transient', times=5, retry_after=0)
    rig.engine.submit(env('c1'))
    waits = []
    for _ in range(5):
        before = rig.clock.now()
        rig.engine.run_once()
        due = rig.engine.snapshot()['commands']['c1']['next_attempt_at']
        waits.append(round((V.require_aware(due) - before).total_seconds()))
        assert rig.engine.run_once() == []             # not due yet: no busy loop
        rig.clock.advance(61)
    assert waits[:4] == [1, 2, 4, 8]
    status = rig.engine.status('c1')
    assert status['state'] == 'failed' and status['reason'] == 'retry_exhausted' and status['attempts'] == 5
    assert rig.adapter.write_count == 0


def test_retry_after_larger_than_backoff_is_respected(rig):
    rig.adapter.inject('transient', retry_after=45)
    rig.engine.submit(env('c1'))
    rig.engine.run_once()
    due = rig.engine.snapshot()['commands']['c1']['next_attempt_at']
    assert round((V.require_aware(due) - rig.clock.now()).total_seconds()) == 45


def test_backoff_budget_and_unknown_exhaustion_are_visible(rig):
    rig.adapter.inject('timeout_after_commit')
    rig.engine.submit(env('c1'))
    rig.engine.run_once()
    rig.adapter.inject('forbidden_read', times=5)
    for _ in range(5):
        rig.clock.advance(120)
        rig.engine.run_once()
    status = rig.engine.status('c1')
    assert status['state'] == 'unknown' and status['reconcile']['phase'] == 'exhausted'
    assert status['reconcile']['reads'] == 5 and status['reason'] == 'permission_denied'
    rig.clock.advance(3600)
    assert rig.engine.run_once() == []                  # automatic dispatch disabled until explicit recovery
    rig.engine.request_recovery('c1')
    rig.engine.run_once()
    assert rig.engine.status('c1')['state'] == 'confirmed' and rig.adapter.write_count == 1


def test_permission_loss_fails_closed_without_clear(rig):
    rig.engine.submit(env('c1'))
    rig.engine.submit(env('c2', field='case.pm', intended=V.SetValue('ou_test_pm_2')))
    rig.adapter.inject('permission_lost')
    rig.engine.run_once()
    assert rig.engine.status('c1') ['reason'] == 'permission_denied' and rig.engine.status('c1')['state'] == 'failed'
    assert rig.engine.status('c2')['state'] == 'queued'     # dispatch suspended
    assert rig.adapter.write_count == 0
    assert rig.engine.projection(E, 'case.deadline') == (V.CLEAR, 0)
    rig.engine.resume_dispatch('permission_denied')
    rig.engine.run_once()
    assert rig.engine.status('c2')['state'] == 'confirmed'


def test_permission_loss_after_possible_commit_stays_unknown(rig):
    rig.adapter.inject('timeout_after_commit')
    rig.engine.submit(env('c1'))
    rig.engine.run_once()
    rig.adapter.inject('forbidden_read')
    rig.clock.advance(1)
    rig.engine.run_once()
    status = rig.engine.status('c1')
    assert status['state'] == 'unknown' and status['reason'] == 'permission_denied'


def test_schema_binding_mismatch_fails_closed(rig):
    rig.engine.submit(env('c1'))
    rig.adapter.set_binding('mock-binding-v2')                # drift on the Lark side
    rig.engine.run_once()
    assert rig.engine.status('c1')['state'] == 'failed'
    assert rig.engine.status('c1')['reason'] in ('schema_binding_mismatch',)
    assert rig.adapter.write_count == 0
    submitted = rig.engine.submit(env('c2', binding='mock-binding-v0'))   # stale binding on the command
    assert submitted['status'] == 'failed' and submitted['reason'] == 'schema_binding_mismatch'
    assert rig.adapter.write_count == 0


def test_stale_worker_is_fenced_after_lease_expiry(rig):
    rig.engine.submit(env('c1'))
    stale = rig.engine.begin_dispatch('c1')
    rig.clock.advance(31)                                     # worker A stalls past its lease
    assert rig.engine.recover_leases() == ['c1']
    rig.engine.run_once()                                     # reconcile proves non-commit, seals entity
    rig.engine.run_once()                                     # fresh worker dispatches with a higher fence
    assert rig.engine.status('c1')['state'] == 'confirmed'
    outcome = rig.engine.dispatch(stale)                      # old worker wakes up
    assert outcome.get('ignored') == 'stale_worker'
    assert rig.adapter.write_count == 1 and len(rig.history('c1')) == 1


def test_stale_worker_cannot_write_after_seal(rig):
    rig.engine.submit(env('c1'))
    stale = rig.engine.begin_dispatch('c1')
    rig.adapter.seal(E, stale.fence + 5)
    with pytest.raises(A.StaleFence):
        rig.adapter.write('c1', E, 'case.deadline', 0, D1, A.BINDING, stale.fence)
    assert rig.adapter.write_count == 0


def test_restart_recovers_outbox_inbox_and_fences_old_worker(rig):
    rig.engine.submit(env('c1'))
    rig.engine.process_event({'scope': 'lark', 'event_id': 'e1', 'entity_id': E, 'field_id': 'case.pm', 'revision': 1,
                              'value': V.SetValue('ou_test_pm_2')})
    attempt = rig.engine.begin_dispatch('c1')                 # crash right after the lease was persisted
    engine = rig.restart()
    assert engine.snapshot()['outbox'] == ['c1']
    assert engine.process_event({'scope': 'lark', 'event_id': 'e1', 'entity_id': E, 'field_id': 'case.pm', 'revision': 1,
                                 'value': V.SetValue('ou_test_pm_2')}) == 'duplicate'
    assert engine.run_once() == []                            # lease still live: no second dispatcher
    rig.clock.advance(31)
    engine.run_once(); engine.run_once()
    assert engine.status('c1')['state'] == 'confirmed' and rig.adapter.write_count == 1
    assert engine.dispatch(attempt).get('ignored') == 'stale_worker'


def test_duplicate_event_is_noop_and_payload_collision_rejected(rig):
    ev = {'scope': 'lark', 'event_id': 'e1', 'entity_id': E, 'field_id': 'case.pm', 'revision': 1, 'value': V.SetValue('ou_test_pm_2')}
    assert rig.engine.process_event(ev) == 'applied'
    assert rig.engine.process_event(ev) == 'duplicate'
    assert len([h for h in rig.engine.snapshot()['history'] if h.get('event_id') == 'e1']) == 1
    assert rig.engine.process_event(dict(ev, value=V.SetValue('ou_test_pm_9'))) == 'integrity_conflict'
    assert rig.engine.projection(E, 'case.pm') == (V.SetValue('ou_test_pm_2'), 1)
    assert rig.engine.snapshot()['integrity'][0]['kind'] == 'event_id_collision'
    assert rig.engine.process_event(dict(ev, scope='other')) == 'stale_ignored'   # dedup is per scope


def test_out_of_order_event_cannot_roll_back_projection(rig):
    base = {'scope': 'lark', 'entity_id': E, 'field_id': 'case.pm'}
    assert rig.engine.process_event(dict(base, event_id='e1', revision=1, value=V.SetValue('ou_test_pm_2'))) == 'applied'
    assert rig.engine.process_event(dict(base, event_id='e2', revision=2, value=V.CLEAR)) == 'applied'
    assert rig.engine.process_event(dict(base, event_id='e0', revision=1, value=V.SetValue('ou_test_pm_7'))) == 'stale_ignored'
    assert rig.engine.projection(E, 'case.pm') == (V.CLEAR, 2)
    assert rig.engine.process_event(dict(base, event_id='e2b', revision=2, value=V.SetValue('ou_test_pm_8'))) == 'integrity_conflict'
    assert rig.engine.projection(E, 'case.pm') == (V.CLEAR, 2)


def test_missing_revision_requires_complete_read_recovery(rig):
    base = {'scope': 'lark', 'entity_id': E, 'field_id': 'case.pm'}
    rig.adapter.direct_edit(E, 'case.pm', V.SetValue('ou_test_pm_2'))
    rig.adapter.direct_edit(E, 'case.pm', V.SetValue('ou_test_pm_3'))
    assert rig.engine.process_event(dict(base, event_id='e2', revision=2, value=V.SetValue('ou_test_pm_3'))) == 'recovery_scheduled'
    assert rig.engine.projection(E, 'case.pm') == (V.CLEAR, 0)
    assert E in rig.engine.snapshot()['recovery_needed']
    assert rig.engine.process_event(dict(base, event_id='eu', revision=None, value=V.CLEAR)) == 'recovery_scheduled'
    rig.adapter.inject('partial_read')
    assert not rig.engine.recover_entity(E)['complete']       # partial read: baseline and flag preserved
    assert rig.engine.projection(E, 'case.pm') == (V.CLEAR, 0) and E in rig.engine.snapshot()['recovery_needed']
    assert rig.engine.recover_entity(E)['complete']
    assert rig.engine.projection(E, 'case.pm') == (V.SetValue('ou_test_pm_3'), 2)
    assert E not in rig.engine.snapshot()['recovery_needed']


def test_incomplete_event_observation_preserves_value(rig):
    rig.adapter.direct_edit(E, 'case.pm', V.SetValue('ou_test_pm_2'))
    rig.engine.observe(E)
    status = rig.engine.process_event({'scope': 'lark', 'event_id': 'e1', 'entity_id': E, 'field_id': 'case.pm', 'revision': 2,
                                       'value': V.UNKNOWN})
    assert status == 'incomplete_ignored'
    assert rig.engine.projection(E, 'case.pm') == (V.SetValue('ou_test_pm_2'), 1)


def test_resolution_requires_fresh_baseline_and_current_approval(rig):
    rig.engine.submit(env('a', intended=D1))
    rig.engine.submit(env('b', intended=D2))
    rig.engine.run_once()
    assert rig.engine.status('b')['state'] == 'conflict'
    link = dict(resolves='conflict:b', resolution='apply_intended')
    with pytest.raises(V.ValidationError):     # reusing the original id is not a resolution
        rig.engine.resolve_conflict(env('b', expected=D1, expected_revision=1, intended=D2, **link), 'conflict:b', 'apply_intended')
    with pytest.raises(V.OpsError) as caught:  # stale baseline: another change happened
        rig.engine.resolve_conflict(env('r1', expected=V.CLEAR, expected_revision=0, intended=D2, **link), 'conflict:b', 'apply_intended')
    assert caught.value.code == 'baseline_changed'
    rig.adapter.direct_edit(E, 'case.deadline', V.SetValue('2026-11-01'))     # re-race after reading
    attempt_cmd = env('r2', expected=D1, expected_revision=1, intended=D2, **link)
    with pytest.raises(V.OpsError):
        rig.engine.resolve_conflict(attempt_cmd, 'conflict:b', 'apply_intended')
    rig.engine.observe(E)
    ok = env('r3', expected=V.SetValue('2026-11-01'), expected_revision=2, intended=D2, **link)
    assert rig.engine.resolve_conflict(ok, 'conflict:b', 'apply_intended')['status'] == 'queued'
    rig.engine.run_once()
    assert rig.engine.status('r3')['state'] == 'confirmed' and rig.engine.status('b')['state'] == 'conflict'
    assert rig.engine.snapshot()['conflicts']['conflict:b']['resolution']['command_id'] == 'r3'
    assert rig.adapter.read(E, ['case.deadline']).values['case.deadline'] == D2


def test_keep_current_resolution_writes_nothing(rig):
    rig.engine.submit(env('a', intended=D1))
    rig.engine.submit(env('b', intended=D2))
    rig.engine.run_once()
    keep = env('k1', expected=D1, expected_revision=1, intended=D1, resolves='conflict:b', resolution='keep_current')
    assert rig.engine.resolve_conflict(keep, 'conflict:b', 'keep_current')['status'] == 'confirmed'
    assert rig.adapter.write_count == 1
    assert rig.engine.snapshot()['conflicts']['conflict:b']['resolution']['mode'] == 'keep_current'


def test_approval_gate_blocks_dispatch_until_a_consumed_approval_is_granted(rig):
    """A bare reference never opens the gate; the consumed-approval flow is in test_ops_sync_approval_dispatch.py."""
    engine = rig.restart(approval_required={'case.deadline'})
    engine.observe(E)
    assert engine.submit(env('c1'))['status'] == 'waiting_approval'
    assert engine.run_once() == [] and rig.adapter.write_count == 0
    assert engine.grant_approval('c1', 'mock-receipt-1') == 'waiting_approval'
    assert engine.status('c1')['reason'] == 'approval_not_consumed'
    assert engine.run_once() == [] and rig.adapter.write_count == 0
    assert engine.submit(env('c2', intended=D2, approval_ref='mock-receipt-2'))['reason'] == 'approval_not_consumed'
    assert engine.submit(env('c3', intended=D2))['status'] == 'waiting_approval'
    engine.reject_approval('c3')
    assert engine.status('c3')['reason'] == 'approval_rejected'
    assert engine.projection(E, 'case.deadline') == (V.CLEAR, 0)


def test_authorizer_is_checked_at_submit_and_again_before_dispatch(rig):
    denied = set()
    engine = rig.restart(authorizer=lambda envelope, phase: 'actor_not_authorized' if envelope.actor in denied else None)
    engine.observe(E)
    engine.submit(env('c1'))
    denied.add('ou_test_pm_1')
    engine.run_once()
    assert engine.status('c1')['reason'] == 'actor_not_authorized' and rig.adapter.write_count == 0
    assert engine.submit(env('c2'))['reason'] == 'actor_not_authorized'


def test_malformed_response_goes_to_unknown_then_confirms(rig):
    rig.adapter.inject('malformed_after_commit')
    rig.engine.submit(env('c1'))
    rig.engine.run_once()
    assert rig.engine.status('c1')['state'] == 'unknown'
    rig.engine.run_once()
    assert rig.engine.status('c1')['state'] == 'confirmed' and rig.adapter.write_count == 1


def test_roundtrip_preserves_ids_and_histories(rig):
    rig.engine.submit(env('c1'))
    rig.engine.run_once()
    before = rig.engine.snapshot()
    engine = rig.restart()
    engine.submit(env('c1'))
    engine.observe(E)
    engine.run_once()
    after = engine.snapshot()
    assert after['history'] == before['history'] and set(after['commands']) == {'c1'}
    assert after['commands']['c1']['envelope'] == before['commands']['c1']['envelope']
