"""Deadline kinds and approval handling for case/node deadlines (mock/local only).

Date kinds are held apart and never coerced into each other:
  original            immutable contract evidence (amendments append revisions)
  approved_effective  the confirmed operational deadline; changed ONLY by `DeadlineService.approve`
  proposed            requested changes awaiting a bound approval
  derived             workday calculations from an effective anchor; never a formal deadline
Rejected, withdrawn, expired, stale and duplicate approvals never change the effective date.
"""
import copy
from dataclasses import dataclass

from . import values as V
from .domain import SCHEMA_BINDING, DomainError
from .eligibility import PersonIdentity
from .engine import IdentityCollision

ORIGINAL, APPROVED_EFFECTIVE, PROPOSED, DERIVED = 'original', 'approved_effective', 'proposed', 'derived'
DATE_KINDS = (ORIGINAL, APPROVED_EFFECTIVE, PROPOSED, DERIVED)
WAITING, CONFIRMED, FAILED, CONFLICT = 'waiting_approval', 'confirmed', 'failed', 'conflict'
DEADLINE_FIELDS = ('case.deadline', 'node.deadline')
RECEIPT_MAX_AGE = 300       # contract: provisional mock receipt validity is at most 300 seconds
POLICY_VERSION = 'mock-approval-v1'


@dataclass(frozen=True)
class MockReceipt:
    """Mock approval proof. Distinguishable from production native-approval receipts by `mock=True`."""
    receipt_id: str
    command_id: str
    entity_id: str
    field_id: str
    expected: dict
    expected_revision: int
    intended: dict
    proposal_version: int
    project_id: str
    node_id: str
    schema_binding_version: str
    eligibility_revision: int
    assignment_revision: int
    approvers: tuple
    policy_version: str
    issued_at: object
    mock: bool = True

    def payload(self):
        return {'receipt_id': self.receipt_id, 'command_id': self.command_id, 'entity_id': self.entity_id,
                'field_id': self.field_id, 'expected': self.expected, 'expected_revision': self.expected_revision,
                'intended': self.intended, 'proposal_version': self.proposal_version, 'project_id': self.project_id,
                'node_id': self.node_id, 'schema_binding_version': self.schema_binding_version,
                'eligibility_revision': self.eligibility_revision, 'assignment_revision': self.assignment_revision,
                'approvers': sorted(self.approvers), 'policy_version': self.policy_version,
                'issued_at': V.to_utc_iso(self.issued_at, 'issued_at') if self.issued_at is not None else None,
                'mock': self.mock}


class DeadlineService:
    def __init__(self, domain, policy_version=POLICY_VERSION, required_votes=2, proposal_ttl=86400):
        self.d = domain
        self.policy_version, self.required_votes, self.proposal_ttl = policy_version, required_votes, proposal_ttl

    # -- helpers -------------------------------------------------------------------------
    @staticmethod
    def _field(rec):
        return 'case.deadline' if rec['kind'] == 'case' else 'node.deadline'

    @staticmethod
    def _case(dom, rec):
        return rec if rec['kind'] == 'case' else dom['cases'][rec['case_id']]

    def _history(self, dl, **entry):
        dl['effective_history'].append(dict(entry, at=self.d.now_iso(), mock=True))

    def dates(self, entity_id):
        """The four date kinds, kept separate."""
        rec = self.d.view(entity_id)
        dl = rec['deadline']
        return {ORIGINAL: dl['original'],
                APPROVED_EFFECTIVE: {'value': V.decode(dl['effective']['value']), 'revision': dl['effective']['revision']},
                PROPOSED: [p for p in dl['proposals'].values() if p['state'] == WAITING],
                DERIVED: dl['derived']}

    def proposal(self, entity_id, command_id):
        return self.d.view(entity_id)['deadline']['proposals'].get(command_id)

    def consumed_receipt(self, entity_id, command_id):
        """Receipt id to hand to the delivery engine as `approval_ref`, only once the approval was applied."""
        prop = self.proposal(entity_id, command_id)
        return prop['receipt_id'] if prop and prop['state'] == CONFIRMED else None

    # -- original / contract evidence ----------------------------------------------------
    def record_contract(self, command_id, entity_id, value, actor, reason='', source='app'):
        value = V.normalize_date(value)
        payload = {'op': 'record_contract', 'entity_id': entity_id, 'value': value, 'actor': actor.key, 'source': source}

        def apply(dom):
            rec = self.d.entity(dom, entity_id)

            def run():
                if not self.d.policy.allows(self.d.in_scope(actor).key, 'record_contract', entity_id):
                    return {'status': 'denied', 'reason': 'not_authorized'}
                dl = rec['deadline']
                if dl['contract_revisions'] and dl['contract_revisions'][-1]['value'] == value:
                    return {'status': 'unchanged'}
                entry = {'seq': len(dl['contract_revisions']) + 1, 'value': value, 'actor': actor.key, 'source': source,
                         'reason': reason, 'command_id': command_id, 'at': self.d.now_iso()}
                dl['contract_revisions'].append(entry)
                if dl['original'] is None:
                    dl['original'] = {'value': value, 'command_id': command_id, 'at': entry['at']}   # never rewritten
                return {'status': 'recorded', 'seq': entry['seq']}
            return self.d.ledgered(dom, command_id, payload, run)
        return self.d.tx(apply)

    # -- proposals -----------------------------------------------------------------------
    def submit_change(self, command_id, entity_id, intended, expected_value, expected_revision, actor,
                      source='app', occurred_at=None, schema_binding_version=SCHEMA_BINDING):
        return self.d.tx(lambda dom: self.submit_change_in_txn(
            dom, command_id, entity_id, intended, expected_value, expected_revision, actor, source, occurred_at,
            schema_binding_version))

    def submit_change_in_txn(self, dom, command_id, entity_id, intended, expected_value, expected_revision, actor,
                             source='app', occurred_at=None, schema_binding_version=SCHEMA_BINDING):
        occurred = V.to_utc_iso(occurred_at if occurred_at is not None else self.d.now(), 'occurred_at')
        if source not in ('app', 'lark'):
            raise V.ValidationError('source must be app or lark', 'invalid_source')
        if expected_value is V.UNKNOWN or expected_value is V.OMITTED:
            raise V.ValidationError('expected baseline must be known', 'unknown_baseline')
        if intended is V.UNKNOWN or intended is V.OMITTED:
            raise V.ValidationError('OMITTED/UNKNOWN cannot request a mutation', 'no_mutation_requested')
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0:
            raise V.ValidationError('expected_revision must be a non-negative int', 'invalid_revision')

        def apply(dom):
            rec = self.d.entity(dom, entity_id)
            field_id = self._field(rec)
            exp = V.encode(V.coerce(field_id, expected_value))
            new = V.encode(V.coerce(field_id, intended))
            payload = {'op': 'propose', 'entity_id': entity_id, 'field_id': field_id, 'expected': exp,
                       'expected_revision': expected_revision, 'intended': new, 'actor': actor.key, 'source': source,
                       'occurred_at': occurred, 'schema': schema_binding_version}

            def run():
                if not self.d.policy.allows(self.d.in_scope(actor).key, 'submit_deadline', entity_id):
                    return {'status': 'denied', 'reason': 'not_authorized'}
                dl = rec['deadline']
                state, reason = WAITING, None
                if schema_binding_version != rec['schema_binding_version']:
                    state, reason = FAILED, 'schema_binding_mismatch'
                elif exp != dl['effective']['value'] or expected_revision != dl['effective']['revision']:
                    state, reason = CONFLICT, 'baseline_changed'
                dl['proposal_seq'] += 1
                dl['proposals'][command_id] = {
                    'proposal_id': command_id, 'version': dl['proposal_seq'], 'state': state, 'reason': reason,
                    'entity_id': entity_id, 'field_id': field_id, 'expected': exp, 'expected_revision': expected_revision,
                    'intended': new, 'actor': actor.key, 'source': source, 'occurred_at': occurred,
                    'schema_binding_version': schema_binding_version, 'created_at': self.d.now_iso(),
                    'expires_at': V.add_seconds(self.d.now_iso(), self.proposal_ttl), 'receipt_id': None}
                return {'status': state, 'reason': reason, 'proposal_id': command_id}
            return self.d.ledgered(dom, command_id, payload, run)
        return apply(dom)

    def _terminate(self, prop, reason, state=FAILED):
        prop['state'], prop['reason'], prop['closed_at'] = state, reason, self.d.now_iso()

    def withdraw(self, entity_id, command_id, actor):
        def apply(dom):
            prop = self.d.entity(dom, entity_id)['deadline']['proposals'].get(command_id)
            if prop is None:
                raise DomainError('unknown proposal', 'unknown_proposal')
            if prop['actor'] != actor.key:
                return {'status': 'denied', 'reason': 'only_proposer_may_withdraw'}
            if prop['state'] == WAITING:
                self._terminate(prop, 'withdrawn')
            return {'status': prop['state'], 'reason': prop['reason']}
        return self.d.tx(apply)

    def reject(self, entity_id, command_id, actor, reason='rejected'):
        return self.d.tx(lambda dom: self.reject_in_txn(dom, entity_id, command_id, actor, reason))

    def reject_in_txn(self, dom, entity_id, command_id, actor, reason='rejected'):
        def apply(dom):
            if not self.d.policy.allows(self.d.in_scope(actor).key, 'approve_deadline', entity_id):
                return {'status': 'denied', 'reason': 'not_authorized'}
            prop = self.d.entity(dom, entity_id)['deadline']['proposals'].get(command_id)
            if prop is None:
                raise DomainError('unknown proposal', 'unknown_proposal')
            if prop['state'] == WAITING:
                self._terminate(prop, 'rejected')
                prop['rejection_note'], prop['rejected_by'] = reason, actor.key
            return {'status': prop['state'], 'reason': prop['reason']}
        return apply(dom)

    def expire_due(self):
        return self.d.tx(lambda dom: self.expire_due_in_txn(dom))

    def expire_due_in_txn(self, dom):
        def apply(dom):
            expired = []
            for rec in list(dom['cases'].values()) + list(dom['nodes'].values()):
                for prop in rec['deadline']['proposals'].values():
                    if prop['state'] == WAITING and prop['expires_at'] <= self.d.now_iso():
                        self._terminate(prop, 'expired')
                        expired.append(prop['proposal_id'])
            return expired
        return apply(dom)

    # -- receipts ------------------------------------------------------------------------
    def build_receipt(self, entity_id, command_id, approvers, receipt_id, issued_at=None):
        """Mock-only helper: a correct receipt for the proposal as it stands now."""
        dom = self.d.snapshot()
        rec = self.d.entity(dom, entity_id)
        prop = rec['deadline']['proposals'][command_id]
        case = self._case(dom, rec)
        return MockReceipt(
            receipt_id, command_id, entity_id, prop['field_id'], prop['expected'], prop['expected_revision'], prop['intended'],
            prop['version'], rec['project_id'], rec.get('node_id'), prop['schema_binding_version'],
            case['pm']['eligibility_revision'], case['pm']['revision'], tuple(a.key for a in approvers), self.policy_version,
            issued_at if issued_at is not None else self.d.now())

    def approve(self, receipt):
        return self.d.tx(lambda dom: self.approve_in_txn(dom, receipt))

    def approve_in_txn(self, dom, receipt):
        """Verify a receipt and, only if every binding still holds, apply the effective change exactly once."""
        if not isinstance(receipt, MockReceipt):
            raise V.ValidationError('receipt must be a MockReceipt', 'invalid_receipt')
        try:
            payload = receipt.payload()
        except V.OpsError:
            return {'status': 'denied', 'reason': 'invalid_issued_at', 'duplicate': False}

        def apply(dom):
            rec = self.d.entity(dom, receipt.entity_id)
            dl = rec['deadline']
            seen = dl['receipts'].get(receipt.receipt_id)
            if seen:
                if seen['fingerprint'] != V.fingerprint(payload):
                    raise IdentityCollision('receipt id reused with a different payload')
                return dict(copy.deepcopy(seen['result']), duplicate=True)
            prop = dl['proposals'].get(receipt.command_id)

            def deny(reason):
                return {'status': 'denied', 'reason': reason, 'duplicate': False}
            if prop is None:
                return deny('unknown_proposal')
            if prop['state'] != WAITING:
                return deny('proposal_' + prop['state'])
            now = self.d.now()
            if prop['expires_at'] <= V.to_utc_iso(now):
                self._terminate(prop, 'expired')
                return {'status': FAILED, 'reason': 'expired', 'duplicate': False}
            if receipt.mock is not True:
                return deny('not_a_mock_receipt')
            try:
                issued = V.require_aware(receipt.issued_at, 'issued_at')
            except V.OpsError:
                return deny('invalid_issued_at')
            if issued > now:
                return deny('receipt_from_future')
            if (now - issued).total_seconds() > RECEIPT_MAX_AGE:
                return deny('receipt_expired')
            case = self._case(dom, rec)
            bound = (receipt.entity_id, receipt.field_id, receipt.expected, receipt.expected_revision, receipt.intended,
                     receipt.proposal_version, receipt.project_id, receipt.node_id, receipt.schema_binding_version,
                     receipt.policy_version)
            actual = (rec['entity_id'], prop['field_id'], prop['expected'], prop['expected_revision'], prop['intended'],
                      prop['version'], rec['project_id'], rec.get('node_id'), rec['schema_binding_version'],
                      self.policy_version)
            if bound != actual:
                return deny('stale_scope')
            gate = self.d.pm_gate(dom, case)
            if gate:
                return deny(gate)
            if (receipt.eligibility_revision, receipt.assignment_revision) != (case['pm']['eligibility_revision'], case['pm']['revision']):
                return deny('stale_seat_revision')
            voters = []
            for key in receipt.approvers:
                try:
                    ident = self.d.in_scope(PersonIdentity.from_key(key))
                except (V.OpsError, ValueError):
                    return deny('invalid_approver')
                if key == prop['actor'] or not self.d.directory.is_active(ident) \
                        or not self.d.policy.allows(key, 'approve_deadline', receipt.entity_id):
                    return deny('approver_not_authorized')
                if key not in voters:
                    voters.append(key)
            if len(voters) < self.required_votes:
                return deny('insufficient_distinct_approvers')
            if prop['expected'] != dl['effective']['value'] or prop['expected_revision'] != dl['effective']['revision']:
                prop['state'], prop['reason'] = CONFLICT, 'baseline_changed'
                result = {'status': CONFLICT, 'reason': 'baseline_changed', 'duplicate': False}
                return result
            prior = dl['effective']
            dl['effective'] = {'value': prop['intended'], 'revision': prior['revision'] + 1}
            self._history(dl, kind='approved_effective', prior=prior['value'], new=prop['intended'], prior_revision=prior['revision'],
                          new_revision=prior['revision'] + 1, command_id=prop['proposal_id'], receipt_id=receipt.receipt_id,
                          approvers=voters, actor=prop['actor'], source=prop['source'])
            prop['state'], prop['reason'], prop['receipt_id'], prop['closed_at'] = CONFIRMED, None, receipt.receipt_id, self.d.now_iso()
            result = {'status': CONFIRMED, 'reason': None, 'revision': prior['revision'] + 1, 'duplicate': False}
            dl['receipts'][receipt.receipt_id] = {'fingerprint': V.fingerprint(payload), 'result': copy.deepcopy(result)}
            return result
        return apply(dom)

    # -- derived -------------------------------------------------------------------------
    def record_derived(self, entity_id, entry):
        def apply(dom):
            self.d.entity(dom, entity_id)['deadline']['derived'].append(dict(entry, at=self.d.now_iso()))
        return self.d.tx(apply)
