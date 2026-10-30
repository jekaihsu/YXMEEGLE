"""Approval consumption -> engine dispatch binding (mock/local only; isolated files, synthetic data, no network).

Authorization comes from a consumed, matching, unused domain approval record, never from `approval_ref` being present.
SQLite only; PostgreSQL is UNTESTED. Machine power loss is UNTESTED (kill -9 of a process is not power loss).
"""
import dataclasses
import os
import subprocess
import sys
from pathlib import Path

import pytest

from .ops_sync import adapter as A
from .ops_sync import approval_binding as AB
from .ops_sync import values as V
from .ops_sync.deadlines import DeadlineService
from .ops_sync.engine import OpsEngine
from .ops_sync.store import JsonFileStore
from .ops_sync.testing import STORE_BARRIERS, STORE_LANDED, env, open_store, ws_path
from .test_ops_sync_domain import ADMIN, CASE, NODE, PM1, SUP1, SUP2, Rig as DomainRig

ROOT = Path(__file__).resolve().parent.parent
D1, D2 = V.SetValue('2026-10-20'), V.SetValue('2026-10-25')
FIELDS = {'case.deadline'}


class Rig(DomainRig):
    """Domain service and delivery engine on ONE store, exactly as the feature path wires them."""

    def __init__(self, tmp_path, kind):
        self.kind, self.tmp = kind, tmp_path
        self.ws, self.lark = ws_path(tmp_path, kind), tmp_path / 'lark.json'
        super().__init__(open_store(kind, self.ws))
        self.seat_pm()
        self.reopen()
        self.engine.observe(CASE)

    def reopen(self):
        """A fresh process on the same files."""
        self.store = open_store(self.kind, self.ws)
        self.build()
        self.adapter = A.MockLarkAdapter(JsonFileStore(self.lark, namespace='mock_lark'))
        self.engine = OpsEngine(self.store, self.adapter, self.clock, approval_required=FIELDS)
        return self.engine

    def consume(self, proposal='d1', receipt='r1'):
        assert self.propose(proposal)['status'] == 'waiting_approval'
        assert self.approve(proposal, receipt)['status'] == 'confirmed'
        assert self.dl.consumed_receipt(CASE, proposal) == receipt

    def command(self, cid, ref=None, **kw):
        return self.engine.submit(env(cid, entity=CASE, approval_ref=ref, **kw))

    def bindings(self):
        return self.engine.snapshot()['approval_bindings']


@pytest.fixture
def rig(tmp_path, store_kind):
    return Rig(tmp_path, store_kind)


# -- authorization comes from the consumed record ------------------------------------------------------------------
def test_forged_or_unconsumed_reference_never_authorizes_dispatch(rig):
    sub = rig.command('c1', 'forged-receipt')
    assert (sub['status'], sub['reason']) == ('failed', 'approval_not_consumed')
    rig.command('c2')
    assert rig.engine.grant_approval('c2', 'forged-receipt') == 'waiting_approval'
    assert rig.engine.status('c2')['reason'] == 'approval_not_consumed'
    assert rig.engine.run_once() == [] and rig.adapter.write_count == 0 and rig.bindings() == {}


@pytest.mark.parametrize('how', ['pending', 'withdrawn', 'rejected', 'expired', 'stale_scope'])
def test_proposal_that_was_never_consumed_cannot_authorize(rig, how):
    assert rig.propose('d1')['status'] == 'waiting_approval'
    receipt = rig.dl.build_receipt(CASE, 'd1', (SUP1, SUP2), 'r1')
    if how == 'withdrawn':
        rig.dl.withdraw(CASE, 'd1', ADMIN)
    elif how == 'rejected':
        rig.dl.reject(CASE, 'd1', SUP1)
    elif how == 'expired':
        rig.clock.advance(86401)
        rig.dl.expire_due()
        receipt = dataclasses.replace(receipt, issued_at=rig.d.now())
    elif how == 'stale_scope':
        receipt = dataclasses.replace(receipt, intended={'t': 'set', 'v': '2030-01-01'})
    if how != 'pending':
        assert rig.dl.approve(receipt)['status'] != 'confirmed'
    assert rig.dl.consumed_receipt(CASE, 'd1') is None
    rig.command('c1')
    assert rig.engine.grant_approval('c1', 'r1') == 'waiting_approval'
    assert rig.command('c2', 'r1')['reason'] == 'approval_not_consumed'
    assert rig.engine.run_once() == [] and rig.adapter.write_count == 0 and rig.bindings() == {}


def test_withdrawn_after_consumption_is_not_possible_and_stays_authoritative(rig):
    rig.consume()
    rig.dl.withdraw(CASE, 'd1', ADMIN)                       # too late: the approval was already applied
    assert rig.dl.consumed_receipt(CASE, 'd1') == 'r1'
    rig.command('c1')
    assert rig.engine.grant_approval('c1', 'r1') == 'queued'


def test_approval_for_another_value_or_entity_does_not_authorize(rig):
    rig.consume()
    assert rig.command('c1', 'r1', intended=D2)['reason'] == 'approval_mismatch'
    rig.command('c2', intended=D2)
    assert rig.engine.grant_approval('c2', 'r1') == 'waiting_approval'
    assert rig.engine.status('c2')['reason'] == 'approval_mismatch'
    other = rig.engine.submit(env('c3', entity=NODE, field='case.deadline', approval_ref='r1'))
    assert other['reason'] == 'approval_not_consumed'
    assert rig.engine.run_once() == [] and rig.adapter.write_count == 0 and rig.bindings() == {}


def test_consumed_approval_dispatches_once_and_replays_are_idempotent(rig):
    rig.consume()
    assert rig.approve('d1', 'r1')['duplicate'] is True               # replayed consume: no second effect
    assert rig.command('c1')['status'] == 'waiting_approval'
    assert rig.engine.grant_approval('c1', 'r1') == 'queued'
    assert rig.engine.grant_approval('c1', 'r1') == 'queued'          # replayed grant
    assert rig.reopen().grant_approval('c1', 'r1') == 'queued'        # ... after a restart
    assert rig.command('c1')['duplicate'] is True
    assert rig.engine.run_once() == ['c1'] and rig.engine.run_once() == []
    assert rig.engine.status('c1')['state'] == 'confirmed' and rig.adapter.write_count == 1
    assert rig.bindings() == {'r1': 'c1'}
    assert rig.engine.grant_approval('c1', 'r1') == 'confirmed'
    assert len(rig.d.view(CASE)['deadline']['effective_history']) == 1


def test_submit_with_a_consumed_reference_binds_in_the_same_transaction(rig):
    rig.consume()
    assert rig.command('c1', 'r1')['status'] == 'queued' and rig.bindings() == {'r1': 'c1'}
    assert rig.engine.run_once() == ['c1'] and rig.adapter.write_count == 1


def test_one_approval_authorizes_exactly_one_command(rig):
    rig.consume()
    rig.command('c1')
    rig.command('c2')
    assert rig.engine.grant_approval('c1', 'r1') == 'queued'
    assert rig.engine.grant_approval('c2', 'r1') == 'waiting_approval'
    assert rig.engine.status('c2')['reason'] == 'approval_already_bound'
    assert rig.command('c3', 'r1')['reason'] == 'approval_already_bound'
    rig.engine.run_once()
    assert rig.adapter.write_count == 1 and rig.engine.status('c1')['state'] == 'confirmed'
    assert rig.engine.status('c2')['state'] == 'waiting_approval'


def test_binding_is_rechecked_at_dispatch_not_trusted_from_queueing(rig):
    rig.consume()
    rig.command('c1', 'r1')
    rig.store.transact(lambda ns: ns['approval_bindings'].clear())     # corrupted / lost binding record
    rig.engine.run_once()
    assert rig.engine.status('c1')['reason'] == 'approval_not_bound' and rig.adapter.write_count == 0


def test_swapping_in_another_consumed_reference_after_queueing_stops_dispatch(rig):
    rig.consume()
    assert rig.propose('d2', value='2026-10-25', expected=D1, revision=1)['status'] == 'waiting_approval'
    assert rig.approve('d2', 'r2')['status'] == 'confirmed'
    rig.command('c4', 'r2', intended=D2, expected=D1, expected_revision=1)
    assert rig.bindings() == {'r2': 'c4'}

    def swap(ns):
        ns['commands']['c4']['envelope']['approval_ref'] = 'r1'
    rig.store.transact(swap)
    rig.engine.run_once()
    assert rig.engine.status('c4')['state'] == 'failed' and rig.engine.status('c4')['reason'] == 'approval_mismatch'
    assert rig.adapter.write_count == 0


def test_losing_the_approval_record_after_queueing_stops_dispatch(rig):
    rig.consume()
    rig.command('c1', 'r1')
    rig.store.transact(lambda ns: ns['domain']['cases'][CASE]['deadline']['receipts'].clear())
    rig.engine.run_once()
    assert rig.engine.status('c1')['reason'] == 'approval_not_consumed' and rig.adapter.write_count == 0


# -- deliberate failures: the tests above must bite when the guarantee is removed -----------------------------------
def test_deliberate_failure_presence_only_authorization_is_detected(rig, monkeypatch):
    """Reverts to the T2 gap (any non-empty approval_ref authorizes). The forged-reference scenario MUST then write."""
    monkeypatch.setattr(AB, 'verify', lambda ns, env, require_bound: None if env.get('approval_ref') else 'approval_missing')
    assert rig.command('c1', 'forged-receipt')['status'] == 'queued'
    rig.engine.run_once()
    assert rig.adapter.write_count == 1          # => test_forged_or_unconsumed_reference_never_authorizes_dispatch would fail


def test_deliberate_failure_without_single_use_binding_two_commands_both_write(rig, monkeypatch):
    rig.consume()
    monkeypatch.setattr(AB, 'bind', lambda ns, env: None)
    monkeypatch.setattr(AB, 'verify', lambda ns, env, require_bound: None if AB.consumed_proposal(ns, env['entity_id'], env['approval_ref']) else AB.NOT_CONSUMED)
    rig.command('c1', 'r1')
    rig.command('c2', 'r1', intended=D1, expected=D1, expected_revision=1)
    rig.engine.run_once()
    rig.engine.run_once()
    assert rig.engine.status('c1')['state'] == 'confirmed' and rig.engine.status('c2')['state'] == 'confirmed'
    # => test_one_approval_authorizes_exactly_one_command would fail


# -- crash / restart / concurrency in independent OS processes ------------------------------------------------------
def worker_cmd(rig, *args):
    return [sys.executable, '-m', 'backend.ops_sync.testing_worker', args[0], rig.ws, str(rig.lark), *args[1:]]


def run_worker(rig, *args):
    return subprocess.run(worker_cmd(rig, *args), cwd=ROOT, capture_output=True, text=True, timeout=60,
                          env={**os.environ, 'OPS_TEST_STORE': rig.kind})


@pytest.mark.parametrize('barrier', sorted(set(sum(STORE_BARRIERS.values(), ()))))
def test_consume_then_kill_9_during_grant_then_restart(tmp_path, store_kind, barrier):
    if barrier not in STORE_BARRIERS[store_kind]:
        pytest.skip('barrier belongs to the other store')
    rig = Rig(tmp_path, store_kind)
    rig.consume()
    rig.command('c1')
    victim = run_worker(rig, 'grant', 'c1', 'r1', CASE, barrier, '1')
    assert victim.returncode == 9 and 'granted' not in victim.stdout, victim.stderr
    landed = barrier in STORE_LANDED[store_kind]
    engine = rig.reopen()
    assert engine.status('c1')['state'] == ('queued' if landed else 'waiting_approval')
    assert rig.bindings() == ({'r1': 'c1'} if landed else {})
    assert engine.grant_approval('c1', 'r1') == 'queued'               # the retry after restart converges
    assert engine.run_once() == ['c1'] and engine.run_once() == []
    assert engine.status('c1')['state'] == 'confirmed' and rig.adapter.write_count == 1
    assert rig.bindings() == {'r1': 'c1'}


def test_consume_commit_survives_kill_9_before_any_grant(tmp_path, store_kind):
    rig = Rig(tmp_path, store_kind)
    rig.consume()
    rig.command('c1')
    engine = rig.reopen()                                               # "restart" with the consume already durable
    assert rig.dl.consumed_receipt(CASE, 'd1') == 'r1'
    assert engine.grant_approval('c1', 'r1') == 'queued'


def race(rig, tmp_path, *commands):
    ready = tmp_path / 'ready'
    ready.mkdir()
    procs = [subprocess.Popen(worker_cmd(rig, 'race', cid, 'r1', CASE, str(ready)), cwd=ROOT, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, env={**os.environ, 'OPS_TEST_STORE': rig.kind}) for cid in commands]
    import time
    deadline = time.monotonic() + 30
    while len(list(ready.iterdir())) < len(procs):
        assert time.monotonic() < deadline, 'workers never became ready'
        time.sleep(0.01)
    (ready / 'go').touch()
    outs = []
    for proc in procs:
        out, err = proc.communicate(timeout=60)           # a deadlock would hit this timeout
        assert proc.returncode == 0, err
        outs.append(out.strip())
    return outs


def test_two_processes_racing_for_one_approval_dispatch_only_one_command(tmp_path, store_kind):
    rig = Rig(tmp_path, store_kind)
    rig.consume()
    rig.command('c1')
    rig.command('c2')
    outs = race(rig, tmp_path, 'c1', 'c2')
    assert sorted(outs) == ['confirmed:None', 'waiting_approval:approval_already_bound']
    engine = rig.reopen()
    assert rig.adapter.write_count == 1
    assert list(rig.bindings().keys()) == ['r1']
    winner = rig.bindings()['r1']
    assert engine.status(winner)['state'] == 'confirmed'


def test_two_processes_dispatching_the_same_command_write_once(tmp_path, store_kind):
    rig = Rig(tmp_path, store_kind)
    rig.consume()
    rig.command('c1')
    outs = race(rig, tmp_path, 'c1', 'c1')
    assert set(outs) <= {'confirmed:None', 'queued:None'}
    rig.reopen().run_once()
    assert rig.reopen().status('c1')['state'] == 'confirmed' and rig.adapter.write_count == 1


def test_no_deadlock_with_domain_consume_and_unrelated_writer_in_other_processes(tmp_path, store_kind):
    """Single-lock design (one version-CAS row / one flock file): approval consume, grant and an app-style writer interleave."""
    import threading
    rig = Rig(tmp_path, store_kind)
    rig.consume()
    rig.command('c1')
    errors = []

    def consumes():                    # domain approvals keep being consumed in this process while others grant/dispatch
        try:
            for n in range(3):
                prior = '2026-10-20' if n == 0 else f'2026-11-0{n}'
                assert rig.propose(f'e{n}', value=f'2026-11-0{n + 1}', expected=V.SetValue(prior), revision=1 + n)['status'] == 'waiting_approval'
                assert rig.approve(f'e{n}', f'q{n}')['status'] == 'confirmed'
        except BaseException as exc:   # noqa: BLE001 - surfaced below
            errors.append(exc)
    noise = subprocess.Popen(worker_cmd(rig, 'unrelated', 'noise', '40'), cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, env={**os.environ, 'OPS_TEST_STORE': rig.kind})
    thread = threading.Thread(target=consumes)
    thread.start()
    race(rig, tmp_path, 'c1', 'c1')
    thread.join(60)
    out, err = noise.communicate(timeout=60)
    assert not thread.is_alive() and not errors and noise.returncode == 0, (errors, err)
    assert rig.reopen().status('c1')['state'] == 'confirmed' and rig.adapter.write_count == 1
