"""Domain tests: PM eligibility/assignment, case+node model, deadline kinds and approval handling (mock/local only)."""
import copy
import dataclasses
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from . import people_directory
from .ops_sync import values as V
from .ops_sync.clock import FakeClock
from .ops_sync.deadlines import APPROVED_EFFECTIVE, DATE_KINDS, DERIVED, ORIGINAL, PROPOSED, DeadlineService
from .ops_sync.derived import DerivedService
from .ops_sync.domain import DomainError, DomainService
from .ops_sync.eligibility import (ELIGIBLE, INELIGIBLE, Eligibility, MockAppPolicy, MockDirectory, MockEligibilitySource,
                                   PersonIdentity, evaluate)
from .ops_sync.engine import IdentityCollision
from .ops_sync.flags import OpsFlags, resolve_flags
from .ops_sync.projection import case_entity_id, node_entity_id, project_headers, sync_headers
from .ops_sync.store import JsonFileStore, MemoryStore
from .ops_sync.testing import open_store, seed_workspace, ws_path

ROOT = Path(__file__).resolve().parent.parent
BASE_SHA = 'f1455b1671859cbe3b09ace82baee0903b33d0bc'
T, A = 't_test', 'app_test'


def who(person_id, tenant=T, app=A):
    return PersonIdentity(tenant, app, person_id)


PM1, PM2, SUP1, SUP2, ADMIN, ROLE_ONLY = (who('ou_test_pm_1'), who('ou_test_pm_2'), who('ou_test_sup_1'),
                                          who('ou_test_sup_2'), who('ou_test_admin'), who('ou_test_role_only'))
CASE, NODE = 'case:p-1', 'node:p-1:n-1'


class Rig:
    def __init__(self, store=None):
        self.clock = FakeClock()
        self.store = store or MemoryStore()
        self.elig = MockEligibilitySource(T, A)
        self.policy = MockAppPolicy()
        self.directory = MockDirectory()
        self.build()
        for person in (PM1, PM2, SUP1, SUP2, ADMIN, ROLE_ONLY):
            self.directory.admit(person, 'Same Name')           # display names deliberately collide
        for person in (PM1, PM2):
            self.elig.set(person, ELIGIBLE, self.clock.now())
        for action in ('assign_pm', 'clear_pm', 'assign_responsible', 'submit_deadline', 'record_contract'):
            self.policy.grant(ADMIN, action)
        for approver in (SUP1, SUP2):
            self.policy.grant(approver, 'approve_deadline')
        self.policy.grant(SUP1, 'resolve_conflict')
        self.d.register_case(CASE, 'p-1')
        self.d.register_node(NODE, 'n-1', CASE, ['t-1', 't-2'])

    def build(self):
        self.d = DomainService(self.store, self.clock, self.elig, self.policy, self.directory, T, A)
        self.dl = DeadlineService(self.d)
        self.dv = DerivedService(self.d, self.dl)

    def restart(self):
        self.build()

    def seat_pm(self, person=PM1, cid='seat-1'):
        assert self.d.assign_pm(cid, CASE, ADMIN, [person])['status'] == 'assigned'

    def propose(self, cid, value='2026-10-20', expected=V.CLEAR, revision=0, entity=CASE, actor=ADMIN):
        intended = V.CLEAR if value is V.CLEAR else V.SetValue(value)
        return self.dl.submit_change(cid, entity, intended, expected, revision, actor)

    def approve(self, cid, rid, entity=CASE, approvers=(SUP1, SUP2), **changes):
        receipt = dataclasses.replace(self.dl.build_receipt(entity, cid, approvers, rid), **changes)
        return self.dl.approve(receipt)

    def effective(self, entity=CASE):
        return self.dl.dates(entity)[APPROVED_EFFECTIVE]


@pytest.fixture
def rig():
    return Rig()


# -- identity / eligibility / authorization / assignment ----------------------------------------------------------

def test_ineligible_pm_assignment_denied(rig):
    rig.elig.set(PM2, INELIGIBLE, rig.clock.now())
    result = rig.d.assign_pm('a1', CASE, ADMIN, [PM2])
    assert result['status'] == 'denied' and result['reason'] == 'ineligible'
    pm = rig.d.view(CASE)['pm']
    assert pm['person'] is None and pm['history'] == [] and pm['state'] == 'empty'


def test_unknown_pm_eligibility_denies_without_role_inference(rig):
    cases = {'no_evidence': ROLE_ONLY}                      # legacy role label / directory membership is not evidence
    for n, person in enumerate(cases.values()):
        assert rig.d.assign_pm(f'u{n}', CASE, ADMIN, [person])['reason'] == 'eligibility_unknown'
    rig.elig.set(PM2, ELIGIBLE, rig.clock.now(), valid_seconds=60)
    rig.clock.advance(61)                                    # stale evidence
    assert rig.d.assign_pm('stale', CASE, ADMIN, [PM2])['reason'] == 'eligibility_unknown'
    other_app = who('ou_test_pm_1', app='other_app')
    foreign = evaluate(MockEligibilitySource(T, 'other_app'), PM1, rig.clock.now())
    assert foreign.status == 'unknown' and foreign.reason == 'wrong_application'
    with pytest.raises(V.ValidationError):
        rig.d.assign_pm('wrong-app', CASE, ADMIN, [other_app])
    assert rig.d.view(CASE)['pm']['person'] is None


@pytest.mark.parametrize('evidence', [
    None, 'eligible', Eligibility('maybe', 1, None, None), Eligibility('eligible', 1, None, None),
    Eligibility('eligible', 1, datetime(2026, 10, 11), datetime(2027, 1, 1, tzinfo=timezone.utc)),
    Eligibility('eligible', True, datetime(2026, 10, 11, tzinfo=timezone.utc), datetime(2027, 1, 1, tzinfo=timezone.utc)),
    Eligibility('eligible', 1, datetime(2030, 1, 1, tzinfo=timezone.utc), datetime(2031, 1, 1, tzinfo=timezone.utc))])
def test_malformed_or_partial_evidence_is_unknown(evidence):
    class Source:
        def lookup(self, identity, at):
            return evidence
    assert evaluate(Source(), PM1, datetime(2026, 10, 11, tzinfo=timezone.utc)).status == 'unknown'


def test_source_failure_is_unknown_not_eligible():
    class Broken:
        def lookup(self, identity, at):
            raise RuntimeError('forbidden')
    assert evaluate(Broken(), PM1, datetime(2026, 10, 11, tzinfo=timezone.utc)).status == 'unknown'


def test_same_name_different_id_is_not_matched(rig):
    # PM1 and PM2 and ROLE_ONLY all display as 'Same Name'; only the stable ID carries eligibility.
    assert rig.directory.display_name(PM1) == rig.directory.display_name(ROLE_ONLY) == 'Same Name'
    assert rig.d.assign_pm('a1', CASE, ADMIN, [ROLE_ONLY])['status'] == 'denied'
    assert rig.d.assign_pm('a2', CASE, ADMIN, [PM1])['status'] == 'assigned'
    assert rig.d.view(CASE)['pm']['person'] == PM1.key
    with pytest.raises(V.ValidationError):              # a display name is not an identity
        who('Same Name').validated()
    with pytest.raises(V.ValidationError):
        who('王 小明').validated()


def test_eligible_person_has_no_implicit_application_permission(rig):
    rig.seat_pm()
    assert rig.d.assign_pm('x1', CASE, PM1, [PM2])['reason'] == 'not_authorized'
    assert rig.dl.submit_change('x2', CASE, V.SetValue('2026-10-20'), V.CLEAR, 0, PM1)['reason'] == 'not_authorized'
    assert rig.dl.reject(CASE, 'x2', PM1)['reason'] == 'not_authorized'
    rig.propose('d1')
    assert rig.approve('d1', 'r0', approvers=(PM1, SUP1))['reason'] == 'approver_not_authorized'   # eligibility != approval right
    # and application permission alone gives no eligibility:
    assert rig.d.assign_pm('x3', CASE, ADMIN, [ADMIN])['reason'] == 'eligibility_unknown'


def test_revoked_pm_blocks_pending_action_preserves_assignment(rig):
    rig.seat_pm()
    rig.propose('d1')
    receipt = rig.dl.build_receipt(CASE, 'd1', (SUP1, SUP2), 'r1')
    rig.clock.advance(5)
    rig.elig.set(PM1, INELIGIBLE, rig.clock.now())
    result = rig.dl.approve(receipt)
    assert result['status'] == 'denied' and result['reason'] == 'pm_seat_blocked_ineligible'
    view = rig.d.view(CASE)
    assert view['pm']['person'] == PM1.key and view['pm']['state'] == 'blocked_ineligible'
    assert [h['new'] for h in view['pm']['history']] == [PM1.key]
    assert rig.effective()['value'] is V.CLEAR
    assert rig.d.view(NODE)['task_ids'] == ['t-1', 't-2']
    rig.elig.drop(PM1)                                   # evidence disappears: blocked_unknown, still not cleared
    assert rig.d.refresh_pm_seat(CASE) == 'blocked_unknown'
    assert rig.d.view(CASE)['pm']['person'] == PM1.key
    assert rig.d.assign_pm('re', CASE, ADMIN, [PM1])['reason'] == 'eligibility_unknown'


def test_restoration_needs_fresh_evidence_and_replaces_stale_receipts(rig):
    rig.seat_pm()
    rig.propose('d1')
    receipt = rig.dl.build_receipt(CASE, 'd1', (SUP1, SUP2), 'r1')
    rig.elig.set(PM1, INELIGIBLE, rig.clock.now())
    rig.d.refresh_pm_seat(CASE)
    rig.elig.set(PM1, ELIGIBLE, rig.clock.now())          # restored with a new evidence revision
    assert rig.d.refresh_pm_seat(CASE) == 'assigned'
    assert rig.dl.approve(receipt)['reason'] == 'stale_seat_revision'    # receipt predates the eligibility change
    assert rig.approve('d1', 'r2')['status'] == 'confirmed'


def test_explicit_replacement_of_blocked_pm_keeps_history(rig):
    rig.seat_pm()
    rig.elig.set(PM1, INELIGIBLE, rig.clock.now())
    rig.d.refresh_pm_seat(CASE)
    assert rig.d.assign_pm('swap', CASE, ADMIN, [PM2], reason='replacement')['status'] == 'assigned'
    pm = rig.d.view(CASE)['pm']
    assert pm['person'] == PM2.key and pm['state'] == 'assigned'
    assert [(h['prior'], h['new']) for h in pm['history']] == [(None, PM1.key), (PM1.key, PM2.key)]
    assert all(h['actor'] == ADMIN.key and h['command_id'] and h['at'] for h in pm['history'])


def test_multiple_pm_assignees_record_conflict_without_first_choice(rig):
    rig.seat_pm()
    result = rig.d.assign_pm('multi', CASE, ADMIN, [PM2, PM1, PM2.__class__(T, A, 'ou_test_pm_3')])
    assert result['status'] == 'conflict'
    pm = rig.d.view(CASE)['pm']
    assert pm['person'] == PM1.key                                      # prior confirmed seat retained
    assert sorted(pm['conflicts'][0]['candidates']) == sorted([PM1.key, PM2.key, 't_test|app_test|ou_test_pm_3'])
    assert len(pm['history']) == 1
    rig.propose('d1')
    assert rig.approve('d1', 'r1')['reason'] == 'assignment_ambiguous'   # dependent actions disabled while ambiguous
    assert rig.d.assign_pm('fix', CASE, ADMIN, [PM1])['status'] in ('unchanged', 'assigned')
    assert rig.d.view(CASE)['pm']['open_conflicts'] == []
    assert rig.approve('d1', 'r2')['status'] == 'confirmed'


def test_clear_requires_its_own_permission_and_is_recorded(rig):
    rig.seat_pm()
    rig.policy.revoke(ADMIN, 'clear_pm')
    assert rig.d.assign_pm('c1', CASE, ADMIN, V.CLEAR)['reason'] == 'not_authorized'
    rig.policy.grant(ADMIN, 'clear_pm')
    assert rig.d.assign_pm('c2', CASE, ADMIN, V.CLEAR)['status'] == 'cleared'
    pm = rig.d.view(CASE)['pm']
    assert pm['person'] is None and pm['state'] == 'empty' and pm['history'][-1]['new'] is None


def test_assignment_replay_is_idempotent_and_payload_collision_rejected(rig):
    first = rig.d.assign_pm('same', CASE, ADMIN, [PM1])
    again = rig.d.assign_pm('same', CASE, ADMIN, [PM1])
    assert first['status'] == again['status'] == 'assigned' and again['duplicate']
    assert len(rig.d.view(CASE)['pm']['history']) == 1
    with pytest.raises(IdentityCollision):
        rig.d.assign_pm('same', CASE, ADMIN, [PM2])


def test_node_responsible_zero_or_one_active_identity(rig):
    assert rig.d.assign_responsible('n1', NODE, ADMIN, [SUP1])['status'] == 'assigned'   # no PM eligibility needed
    rig.directory.deactivate(SUP2)
    assert rig.d.assign_responsible('n2', NODE, ADMIN, [SUP2])['reason'] == 'not_active'
    multi = rig.d.assign_responsible('n3', NODE, ADMIN, [SUP1, ADMIN])
    node = rig.d.view(NODE)
    assert multi['status'] == 'conflict' and node['responsible']['person'] == SUP1.key
    assert len(node['responsible']['conflicts'][0]['candidates']) == 2
    assert rig.d.assign_responsible('n4', NODE, ADMIN, V.CLEAR)['status'] == 'cleared'
    assert [h['new'] for h in rig.d.view(NODE)['responsible']['history']] == [SUP1.key, None]


def test_node_responsible_who_holds_pm_seat_must_be_eligible(rig):
    rig.seat_pm()
    rig.elig.set(PM1, INELIGIBLE, rig.clock.now())
    assert rig.d.assign_responsible('n1', NODE, ADMIN, [PM1])['reason'] == 'pm_seat_holder_not_eligible'
    assert rig.d.assign_responsible('n2', NODE, ADMIN, [PM2])['status'] == 'assigned'   # not a seat holder here


def test_pm_change_does_not_touch_task_owners(rig):
    project = {'id': 'p-1', 'nodes': [{'id': 'n-1', 'key': 'sales', 'tasks': [{'id': 't-1', 'owner_id': 'u-a'}]}]}
    before = copy.deepcopy(project)
    rig.seat_pm()
    rig.d.assign_pm('swap', CASE, ADMIN, [PM2])
    assert project == before


# -- case / node model ---------------------------------------------------------------------------------------------

def test_case_and_node_registration_is_idempotent_and_validated(rig):
    assert rig.d.register_case(CASE, 'p-1') is False
    assert rig.d.register_node(NODE, 'n-1', CASE, ['t-1']) is False
    assert rig.d.register_node(NODE, 'n-1', CASE, ['t-1', 't-2', 't-3']) is True
    assert rig.d.view(NODE)['task_ids'] == ['t-1', 't-2', 't-3']
    assert rig.d.register_node(NODE, 'n-1', CASE, []) is False
    assert rig.d.view(NODE)['task_ids'] == ['t-1', 't-2', 't-3']        # an import never drops linked tasks
    for call in (lambda: rig.d.register_case(CASE, 'p-other'),
                 lambda: rig.d.register_case('case:dup', 'p-1'),
                 lambda: rig.d.register_node('node:dup', 'n-1', CASE, []),
                 lambda: rig.d.register_node('node:x', 'n-9', 'case:missing', []),
                 lambda: rig.d.register_node('node:y', 'n-2', CASE, ['t-1']),
                 lambda: rig.d.register_node('node:z', 'n-3', CASE, ['a', 'a'])):
        with pytest.raises((DomainError, V.ValidationError)):
            call()


# -- date kinds / approval handling ---------------------------------------------------------------------------------

def test_date_kinds_stay_separate(rig):
    rig.seat_pm()
    assert tuple(rig.dl.dates(CASE)) == DATE_KINDS
    rig.dl.record_contract('k1', CASE, '2026-10-15', ADMIN)
    rig.propose('d1')
    dates = rig.dl.dates(CASE)
    assert dates[ORIGINAL]['value'] == '2026-10-15'
    assert dates[APPROVED_EFFECTIVE]['value'] is V.CLEAR                 # a proposal is not an effective date
    assert [p['proposal_id'] for p in dates[PROPOSED]] == ['d1'] and dates[DERIVED] == []
    assert rig.approve('d1', 'r1')['status'] == 'confirmed'
    dates = rig.dl.dates(CASE)
    assert dates[APPROVED_EFFECTIVE]['value'] == V.SetValue('2026-10-20') and dates[PROPOSED] == []
    assert dates[ORIGINAL]['value'] == '2026-10-15'


def test_contract_amendment_appends_and_original_is_immutable(rig):
    rig.dl.record_contract('k1', CASE, '2026-10-15', ADMIN)
    rig.dl.record_contract('k2', CASE, '2026-11-01', ADMIN, reason='amendment')
    assert rig.dl.record_contract('k3', CASE, '2026-11-01', ADMIN)['status'] == 'unchanged'
    view = rig.d.view(CASE)['deadline']
    assert view['original']['value'] == '2026-10-15'
    assert [r['value'] for r in view['contract_revisions']] == ['2026-10-15', '2026-11-01']
    assert rig.dl.record_contract('k4', CASE, '2026-12-01', PM1)['reason'] == 'not_authorized'


def test_duplicate_approval_applies_effective_deadline_once(rig):
    rig.seat_pm()
    rig.propose('d1')
    receipt = rig.dl.build_receipt(CASE, 'd1', (SUP1, SUP2), 'r1')
    first = rig.dl.approve(receipt)
    again = rig.dl.approve(receipt)
    assert first['status'] == 'confirmed' and not first['duplicate'] and again['duplicate'] and again['status'] == 'confirmed'
    history = rig.d.view(CASE)['deadline']['effective_history']
    assert len(history) == 1 and rig.effective()['revision'] == 1
    other = dataclasses.replace(receipt, receipt_id='r-second')            # a second receipt for an applied proposal
    assert rig.dl.approve(other)['reason'] == 'proposal_confirmed'
    assert len(rig.d.view(CASE)['deadline']['effective_history']) == 1
    with pytest.raises(IdentityCollision):
        rig.dl.approve(dataclasses.replace(receipt, approvers=(SUP1.key, 'x|y|z')))
    assert rig.dl.consumed_receipt(CASE, 'd1') == 'r1'


def test_stale_scope_or_expired_receipt_cannot_change_effective_date(rig):
    rig.seat_pm()
    rig.propose('d1')
    good = rig.dl.build_receipt(CASE, 'd1', (SUP1, SUP2), 'r0')
    cases = {
        'stale_scope': [dict(intended={'t': 'set', 'v': '2030-01-01'}), dict(expected_revision=7), dict(proposal_version=9),
                        dict(project_id='p-other'), dict(node_id='n-9'), dict(field_id='node.deadline'),
                        dict(schema_binding_version='mock-binding-v2'), dict(policy_version='other')],
        'not_a_mock_receipt': [dict(mock=False)],
        'receipt_from_future': [dict(issued_at=rig.clock.now() + timedelta(seconds=1))],
        'receipt_expired': [dict(issued_at=rig.clock.now() - timedelta(seconds=301))],
        'invalid_issued_at': [dict(issued_at=datetime(2026, 10, 11))],
        'stale_seat_revision': [dict(eligibility_revision=99), dict(assignment_revision=99)],
        'insufficient_distinct_approvers': [dict(approvers=(SUP1.key,)), dict(approvers=(SUP1.key, SUP1.key))],
        'approver_not_authorized': [dict(approvers=(SUP1.key, ROLE_ONLY.key)), dict(approvers=(SUP1.key, ADMIN.key)),
                                    dict(approvers=(SUP1.key, 'bogus-id'))],
        'unknown_proposal': [dict(command_id='nope')],
    }
    n = 0
    for reason, variants in cases.items():
        for changes in variants:
            n += 1
            result = rig.dl.approve(dataclasses.replace(good, receipt_id=f'rx{n}', **changes))
            assert result['status'] == 'denied' and result['reason'] in (reason, 'invalid_approver'), (changes, result)
            assert rig.effective()['revision'] == 0 and rig.effective()['value'] is V.CLEAR
    with pytest.raises(DomainError):
        rig.dl.approve(dataclasses.replace(good, receipt_id='rz', entity_id='case:unknown'))
    assert rig.dl.approve(dataclasses.replace(good, receipt_id='r-ok'))['status'] == 'confirmed'    # denials consumed nothing


def test_proposer_cannot_approve_own_change(rig):
    rig.seat_pm()
    rig.policy.grant(ADMIN, 'approve_deadline')
    rig.propose('d1')
    assert rig.approve('d1', 'r1', approvers=(ADMIN, SUP1))['reason'] == 'approver_not_authorized'


def test_rejected_withdrawn_expired_proposal_preserves_effective_date(rig):
    rig.seat_pm()
    rig.propose('rej'); rig.propose('wd', '2026-10-21'); rig.propose('exp', '2026-10-22')
    assert rig.dl.reject(CASE, 'rej', SUP1)['reason'] == 'rejected'
    assert rig.dl.withdraw(CASE, 'wd', SUP1)['reason'] == 'only_proposer_may_withdraw'
    assert rig.dl.withdraw(CASE, 'wd', ADMIN)['reason'] == 'withdrawn'
    rig.clock.advance(86400 + 1)
    assert rig.dl.expire_due() == ['exp']
    for cid, reason in (('rej', 'proposal_failed'), ('wd', 'proposal_failed'), ('exp', 'proposal_failed')):
        rig.clock.advance(0)
        assert rig.dl.approve(rig.dl.build_receipt(CASE, cid, (SUP1, SUP2), 'r-' + cid))['reason'] == reason
    assert rig.effective()['revision'] == 0 and rig.d.view(CASE)['deadline']['effective_history'] == []
    assert {p['proposal_id']: p['reason'] for p in rig.d.view(CASE)['deadline']['proposals'].values()} == {
        'rej': 'rejected', 'wd': 'withdrawn', 'exp': 'expired'}


def test_expiry_is_enforced_at_approval_time(rig):
    rig.seat_pm()
    rig.propose('d1')
    rig.clock.advance(86400 + 1)
    receipt = rig.dl.build_receipt(CASE, 'd1', (SUP1, SUP2), 'r1')
    assert rig.dl.approve(receipt) == {'status': 'failed', 'reason': 'expired', 'duplicate': False}
    assert rig.effective()['revision'] == 0


def test_changed_baseline_becomes_conflict_not_overwrite(rig):
    rig.seat_pm()
    rig.propose('a'); rig.propose('b', '2026-10-30')               # two proposals, same baseline
    assert rig.approve('a', 'ra')['status'] == 'confirmed'
    assert rig.approve('b', 'rb') ['status'] == 'conflict'
    assert rig.effective()['value'] == V.SetValue('2026-10-20')
    stale = rig.propose('late', '2026-11-01')                     # submitted against an outdated baseline
    assert stale['status'] == 'conflict' and stale['reason'] == 'baseline_changed'


def test_clear_effective_deadline_needs_the_same_approval(rig):
    rig.seat_pm()
    rig.propose('set'); rig.approve('set', 'r1')
    result = rig.propose('clr', V.CLEAR, V.SetValue('2026-10-20'), 1)
    assert result['status'] == 'waiting_approval' and rig.effective()['value'] == V.SetValue('2026-10-20')
    assert rig.approve('clr', 'r2')['status'] == 'confirmed'
    assert rig.effective() == {'value': V.CLEAR, 'revision': 2}


def test_node_deadline_uses_parent_case_seat(rig):
    rig.seat_pm()
    rig.propose('n1', entity=NODE)
    assert rig.approve('n1', 'r1', entity=NODE)['status'] == 'confirmed'
    assert rig.effective(NODE)['value'] == V.SetValue('2026-10-20') and rig.effective(CASE)['value'] is V.CLEAR


def test_null_date_and_timezone_inputs_rejected_before_any_state(rig):
    before = rig.d.snapshot()
    for bad in ('2026-02-30', '2026/10/20', '20261020', '2026-10-20T00:00:00Z', '', 5, True, datetime(2026, 10, 20)):
        with pytest.raises(V.ValidationError):
            rig.dl.submit_change('bad', CASE, V.SetValue(bad), V.CLEAR, 0, ADMIN)
    with pytest.raises(V.ValidationError):
        V.SetValue(None)
    for bad in (V.OMITTED, V.UNKNOWN):
        with pytest.raises(V.ValidationError):
            rig.dl.submit_change('bad', CASE, bad, V.CLEAR, 0, ADMIN)
        with pytest.raises(V.ValidationError):
            rig.dl.submit_change('bad', CASE, V.SetValue('2026-10-20'), bad, 0, ADMIN)
    with pytest.raises(V.ValidationError):
        rig.dl.submit_change('bad', CASE, V.SetValue('2026-10-20'), V.CLEAR, 0, ADMIN, occurred_at=datetime(2026, 10, 11))
    with pytest.raises(V.ValidationError):
        rig.dl.submit_change('bad', CASE, V.SetValue('2026-10-20'), V.CLEAR, 0, ADMIN, source='cli')
    assert rig.d.snapshot() == before
    # an aware instant crossing UTC midnight is normalised to UTC for audit and maps to the Taipei day for date-only wires
    local = datetime(2026, 10, 11, 8, 0, tzinfo=timezone(timedelta(hours=8)))
    assert V.to_utc_iso(local) == '2026-10-11T00:00:00+00:00'
    assert V.taipei_date_from_instant(datetime(2026, 10, 10, 16, 0, tzinfo=timezone.utc)) == '2026-10-11'
    assert rig.dl.submit_change('good', CASE, V.SetValue('2026-10-11'), V.CLEAR, 0, ADMIN, occurred_at=local)['status'] == 'waiting_approval'
    assert rig.dl.proposal(CASE, 'good')['occurred_at'] == '2026-10-11T00:00:00+00:00'


def test_schema_binding_mismatch_fails_closed(rig):
    result = rig.dl.submit_change('s', CASE, V.SetValue('2026-10-20'), V.CLEAR, 0, ADMIN, schema_binding_version='v-other')
    assert result == {'status': 'failed', 'reason': 'schema_binding_mismatch', 'proposal_id': 's', 'duplicate': False}


def test_submission_replay_and_collision(rig):
    first = rig.propose('d1')
    assert rig.propose('d1')['duplicate'] and first['status'] == 'waiting_approval'
    assert len(rig.d.view(CASE)['deadline']['proposals']) == 1
    with pytest.raises(IdentityCollision):
        rig.propose('d1', '2026-12-31')


# -- derived dates --------------------------------------------------------------------------------------------------

CAL = {'holidays': [], 'workdays': []}


def project_state():
    def task(tid, **kw):
        return dict({'id': tid, 'owner_id': 'u-' + tid, 'status': 'pending', 'due_date': None, 'original_due_date': None,
                     'started_at': None, 'completed_at': None}, **kw)
    return {'id': 'p-1', 'nodes': [{'id': 'n-1', 'key': 'sales', 'status': 'active', 'tasks': [
        task('t-1'), task('t-2', due_date='2026-10-01', original_due_date='2026-10-01'),
        task('t-3', contract_fixed_date='2026-10-05', due_date='2026-10-05'),
        task('t-4', status='in_progress', started_at='2026-10-02', due_date='2026-10-03'),
        task('t-5', status='completed', completed_at='2026-10-02', due_date='2026-10-02')]}]}


def effective_rig():
    rig = Rig()
    rig.d.register_node(NODE, 'n-1', CASE, ['t-1', 't-2', 't-3', 't-4', 't-5'])
    rig.seat_pm()
    rig.propose('d1', '2026-10-20')
    rig.approve('d1', 'r1')
    return rig


def test_derived_requires_confirmed_effective_anchor(rig):
    rig.seat_pm()
    rig.propose('d1')                                           # waiting only
    plan = rig.dv.recalculate(CASE, project_state(), CAL, [{'task_id': 't-1', 'rule_id': 'r', 'offset': 2}])
    assert plan == {'status': 'no_effective_anchor', 'updates': [], 'conflicts': []}
    assert rig.dl.dates(CASE)[DERIVED] == []


def test_recalculation_preserves_manual_fixed_started_completed_tasks():
    rig = effective_rig()
    project = project_state()
    before = copy.deepcopy(project)
    rules = [{'task_id': f't-{n}', 'rule_id': f'rule-{n}', 'offset': 3} for n in range(1, 6)]
    plan = rig.dv.recalculate(CASE, project, CAL, rules)
    assert project == before                                    # owners, ids, statuses, completed node: untouched
    assert [u['task_id'] for u in plan['updates']] == ['t-1']
    assert plan['updates'][0]['due_date'] == '2026-10-23' and plan['updates'][0]['set_original_due_date']
    reasons = {c['task_id']: c['reason'] for c in plan['conflicts']}
    assert reasons == {'t-2': 'existing_manual_date', 't-3': 'contract_fixed', 't-4': 'work_started', 't-5': 'work_started'}
    prov = plan['conflicts'][0]['provenance']
    assert prov['anchor_entity_id'] == CASE and prov['anchor_revision'] == 1 and prov['calendar_hash'] and prov['calendar_snapshot'] == CAL
    again = rig.dv.recalculate(CASE, project, CAL, rules)           # replay: no duplicates
    assert again['conflicts'] == plan['conflicts']
    assert len(rig.d.snapshot()['derived_conflicts']) == 4
    assert len(rig.d.view(CASE)['deadline']['derived']) == 5
    assert rig.effective()['value'] == V.SetValue('2026-10-20')       # derived never becomes the formal deadline
    with pytest.raises(DomainError):
        rig.dv.recalculate(CASE, project, CAL, [{'task_id': 'foreign', 'rule_id': 'x', 'offset': 1}])


def test_derived_uses_workday_calendar():
    rig = effective_rig()
    cal = {'holidays': ['2026-10-21'], 'workdays': []}
    plan = rig.dv.recalculate(CASE, project_state(), cal, [{'task_id': 't-1', 'rule_id': 'a', 'offset': 1},
                                                           {'task_id': 't-1', 'rule_id': 'b', 'offset': -1}])
    assert [u['due_date'] for u in plan['updates']] == ['2026-10-22', '2026-10-19']


def test_resolution_requires_fresh_baseline_and_current_approval():
    rig = effective_rig()
    project = project_state()
    plan = rig.dv.recalculate(CASE, project, CAL, [{'task_id': t, 'rule_id': 'r-' + t, 'offset': 3} for t in ('t-2', 't-3', 't-4')])
    ids = {c['task_id']: c['conflict_id'] for c in plan['conflicts']}
    res = lambda cid, conflict, mode='apply_derived', actor=SUP1, proj=None: rig.dv.resolve_conflict(
        cid, conflict, mode, actor, proj or project, 'reviewed')
    assert res('x0', ids['t-2'], actor=ADMIN)['reason'] == 'not_authorized'
    assert res('x1', ids['t-3'])['reason'] == 'contract_fixed'
    assert res('x2', ids['t-4'])['reason'] == 'work_started_requires_formal_process'
    moved = copy.deepcopy(project); moved['nodes'][0]['tasks'][1]['due_date'] = '2026-10-02'
    assert res('x3', ids['t-2'], proj=moved)['reason'] == 'baseline_changed'
    adopted = res('x4', ids['t-2'])
    assert adopted['status'] == 'resolved' and adopted['adopt']['due_date'] == '2026-10-23'
    assert res('x5', ids['t-2'])['reason'] == 'already_resolved'
    with pytest.raises(V.ValidationError):
        rig.dv.resolve_conflict('x6', ids['t-3'], 'apply_derived', SUP1, project, ' ')
    # the anchor changes: older derived proposals are stale
    rig.propose('d2', '2026-10-28', V.SetValue('2026-10-20'), 1); rig.approve('d2', 'r2')
    assert res('x7', ids['t-3'], 'keep_current')['reason'] == 'stale_anchor'
    kept = rig.dv.recalculate(CASE, project, CAL, [{'task_id': 't-2', 'rule_id': 'r-t-2', 'offset': 3}])
    assert res('x8', kept['conflicts'][0]['conflict_id'], 'keep_current')['adopt'] is None


# -- projection, persistence, flags, boundaries ---------------------------------------------------------------------

def workspace():
    return {'projects': [{'id': 'p-1', 'nodes': [{'id': 'n-1', 'key': 'sales', 'tasks': [{'id': 't-1'}, {'id': 't-2'}]},
                                                 {'id': 'n-2', 'key': 'pm', 'tasks': []}]},
                         {'id': 'p-2', 'nodes': []}]}


def test_projection_is_flag_gated_read_only_and_idempotent(tmp_path, store_kind):
    ws = workspace()
    before = copy.deepcopy(ws)
    rig = Rig(open_store(store_kind, ws_path(tmp_path, store_kind)))
    assert sync_headers(rig.d, ws, OpsFlags()) is None
    assert sync_headers(rig.d, ws, resolve_flags({'FEATURE_LARK_AUTHORITATIVE_OPS': 'true'})) is None
    assert 'p-2' not in rig.d.snapshot()['project_index']
    flags = resolve_flags({'FEATURE_LARK_AUTHORITATIVE_OPS': True})
    assert flags.lark_authoritative_ops and not flags.live_writes
    assert sync_headers(rig.d, ws, flags) == 2          # p-2 and n-2; p-1/n-1 were already registered by the rig
    assert sync_headers(rig.d, ws, flags) == 0
    assert ws == before
    assert rig.d.view(node_entity_id('p-1', 'n-1'))['task_ids'] == ['t-1', 't-2']
    assert project_headers(ws)[1][0]['entity_id'] == case_entity_id('p-2')


def test_roundtrip_preserves_project_node_task_ids_and_histories(tmp_path, store_kind):
    path = ws_path(tmp_path, store_kind)
    rig = Rig(open_store(store_kind, path))
    ws = workspace()
    flags = OpsFlags(lark_authoritative_ops=True)
    sync_headers(rig.d, ws, flags)
    rig.d.assign_pm('seat', case_entity_id('p-1'), ADMIN, [PM1])
    rig.d.assign_pm('swap', case_entity_id('p-1'), ADMIN, [PM2])
    rig.dl.record_contract('k1', case_entity_id('p-1'), '2026-10-15', ADMIN)
    rig.propose('d1', entity=case_entity_id('p-1'))
    rig.dl.approve(dataclasses.replace(rig.dl.build_receipt(case_entity_id('p-1'), 'd1', (SUP1, SUP2), 'r1')))
    before = rig.d.snapshot()
    rig.store = open_store(store_kind, path)
    rig.restart()                                           # fresh store handle and services over the same file
    assert sync_headers(rig.d, ws, flags) == 0              # re-import after restart mints nothing
    assert rig.d.assign_pm('swap', case_entity_id('p-1'), ADMIN, [PM2])['duplicate']
    after = rig.d.snapshot()
    assert after == before
    case = rig.d.view(case_entity_id('p-1'))
    assert case['project_id'] == 'p-1' and case['node_ids'] == [node_entity_id('p-1', 'n-1'), node_entity_id('p-1', 'n-2')]
    assert [h['new'] for h in case['pm']['history']] == [PM1.key, PM2.key]
    assert case['deadline']['original']['value'] == '2026-10-15' and case['deadline']['effective']['revision'] == 1
    assert open_store(store_kind, path).snapshot()['domain'] == before


def test_domain_state_preserves_unrelated_workspace_keys(tmp_path, store_kind):
    if store_kind == 'workspace':
        seed_workspace(ws_path(tmp_path, store_kind), {'version': 1, 'projects': [{'id': 'p-9'}], 'sentinel': {'keep': 1}})
    store = open_store(store_kind, ws_path(tmp_path, store_kind))
    if store_kind == 'file':
        store.transact_raw(lambda ws: ws.update(projects=[{'id': 'p-9'}], sentinel={'keep': 1}))
    rig = Rig(store)
    rig.seat_pm()
    raw = store.snapshot_raw()
    assert raw['sentinel'] == {'keep': 1} and raw['projects'] == [{'id': 'p-9'}] and 'domain' in raw['ops_sync']


def test_flag_default_off_and_personnel_whitelist_and_guard_untouched():
    from .ops_sync import flags
    assert flags.FEATURE_LARK_AUTHORITATIVE_OPS is False and OpsFlags().lark_authoritative_ops is False
    assert resolve_flags().lark_authoritative_ops is False
    # the approved four-column personnel reader supplies no PM capability/eligibility column
    assert set(people_directory.OPTIONAL) == {'name', 'department', 'employment'}
    assert not any('pm' in key.lower() or 'eligib' in key.lower() for key in people_directory.OPTIONAL)
    assert not any(('PM' in label or '資格' in label) for labels in people_directory.OPTIONAL.values() for label in labels)
    # being listed in the personnel directory confers neither eligibility nor any application permission
    rig = Rig()
    rig.directory.admit(who('ou_test_listed_only'))
    assert evaluate(rig.elig, who('ou_test_listed_only'), rig.clock.now()).status == 'unknown'
    assert rig.d.assign_pm('p1', CASE, ADMIN, [who('ou_test_listed_only')])['status'] == 'denied'
    assert not rig.policy.allows(who('ou_test_listed_only').key, 'assign_pm')
    diff = subprocess.run(['git', 'diff', '--name-only', BASE_SHA, '--', 'backend/capability_write_policy.py',
                           'backend/people_directory.py'], cwd=ROOT, capture_output=True, text=True)
    assert diff.returncode == 0 and diff.stdout.strip() == ''
