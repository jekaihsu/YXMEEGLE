"""One acceptance transaction for domain intent and its delivery state.

Read tokens and receipts are prepared before entering the CAS callback. Only namespace mutations happen inside;
a retry checks the captured domain revision and projection again. Dispatch remains outside this transaction,
with a durable queued command until adapter CAS/readback proves the result.
"""
from dataclasses import dataclass

from . import values as V
from .adapter import BINDING
from .commands import CommandEnvelope
from .domain import _dom
from .engine import QUEUED, IdentityCollision, _ns


@dataclass(frozen=True)
class Baseline:
    fresh: dict
    projection: object
    revision: int


class JointOperations:
    def __init__(self, domain, deadlines, engine):
        self.d, self.dates, self.e = domain, deadlines, engine

    def tx(self, fn):
        return self.e.store.transact(lambda ns: fn(_dom(ns), _ns(ns)))

    def slot(self, dom, entity_id, field_id):
        rec = self.d.entity(dom, entity_id)
        return rec['deadline']['effective'] if field_id.endswith('.deadline') else (
            rec['pm'] if field_id == 'case.pm' else rec['responsible'])

    def read(self, entity_id, field_id):
        snap = self.e.snapshot()
        revision = self.slot(_dom(snap), entity_id, field_id)['revision']
        projection = snap['projection'].get(f'{entity_id}|{field_id}')
        fresh = self.e._safe_read(entity_id, field_id)
        if not fresh['ok']:
            raise V.OpsError('complete baseline unavailable: ' + fresh['code'], 'baseline_unavailable')
        return Baseline(fresh, projection, revision)

    def check(self, dom, ns, envelope, base):
        key = f'{envelope.entity_id}|{envelope.field_id}'
        token = {'value': V.encode(base.fresh['value']), 'revision': base.fresh['revision']}
        slot = ns['projection'].get(key)
        if (self.slot(dom, envelope.entity_id, envelope.field_id)['revision'] != base.revision
                or slot != base.projection
                or slot and (slot['revision'] > token['revision'] or
                             slot['revision'] == token['revision'] and slot['value'] != token['value'])):
            raise V.OpsError('baseline changed; re-read and retry', 'baseline_changed')
        ns['projection'][key] = token

    def envelope(self, body, actor, entity_id, command_id, field_id, intended, base, **extra):
        return CommandEnvelope(command_id, entity_id, field_id, base.fresh['value'], base.fresh['revision'],
                               intended, actor, 'app', body.get('occurred_at') or self.e._now(), BINDING, **extra)

    def assign(self, envelope, base, actor, candidates, reason, conflict_id=None, mode=None):
        method = self.d.assign_pm_in_txn if envelope.field_id == 'case.pm' else self.d.assign_responsible_in_txn
        def apply(dom, ns):
            if conflict_id:
                conflict = ns['conflicts'].get(conflict_id)
                if not conflict or conflict['resolution']:
                    raise V.OpsError('no open conflict', 'conflict_not_open')
                if envelope.command_id in dom['ledger'] or envelope.command_id in ns['commands']:
                    raise IdentityCollision('resolution requires a new command id')
            if envelope.command_id not in dom['ledger']:
                self.check(dom, ns, envelope, base)
            result = method(dom, envelope.command_id, envelope.entity_id, actor, candidates, reason, 'app')
            if result['duplicate'] or result['status'] in ('denied', 'conflict'):
                return result
            if conflict_id:
                self.e.resolve_conflict_in_txn(ns, envelope, conflict_id, mode, base.fresh, confirm_current=False)
            elif result['status'] in ('assigned', 'cleared') or (
                    result['status'] == 'unchanged' and envelope.intended_value != base.fresh['value']):
                self.e._submit_in_txn(ns, envelope)
            return result
        return self.tx(apply)

    def propose(self, envelope, base, expected, expected_revision, actor):
        def apply(dom, ns):
            if envelope.command_id not in dom['ledger']:
                self.check(dom, ns, envelope, base)
                eff = self.slot(dom, envelope.entity_id, envelope.field_id)
                if eff['value'] != V.encode(expected) or eff['revision'] != expected_revision:
                    raise V.OpsError('draft baseline changed', 'baseline_changed')
            result = self.dates.submit_change_in_txn(
                dom, envelope.command_id, envelope.entity_id, envelope.intended_value, expected, expected_revision,
                actor, 'app', envelope.occurred_at)
            if result['status'] == 'waiting_approval' and not result['duplicate']:
                self.e._submit_in_txn(ns, envelope)
            return result
        return self.tx(apply)

    def decide(self, entity_id, command_id, decision, approver, receipt):
        def apply(dom, ns):
            for cid in self.dates.expire_due_in_txn(dom):
                self.e.reject_approval_in_txn(ns, cid, 'expired')
            prop = self.d.entity(dom, entity_id)['deadline']['proposals'].get(command_id)
            if prop is None:
                raise V.OpsError('unknown proposal', 'unknown_entity')
            if prop['state'] == 'confirmed' and decision != 'stale':
                return {'status': 'confirmed', 'reason': None, 'duplicate': True}
            if decision == 'rejected':
                result = self.dates.reject_in_txn(dom, entity_id, command_id, approver, 'mock rejected')
            else:
                result = self.dates.approve_in_txn(dom, receipt)
            if result['status'] == 'confirmed' and not result['duplicate']:
                state = self.e.grant_approval_in_txn(ns, command_id, receipt.receipt_id)
                if state != QUEUED:
                    raise V.OpsError('delivery approval did not bind', 'approval_binding_failed')
            elif result['status'] in ('failed', 'conflict'):
                reason = 'baseline_changed' if result['status'] == 'conflict' else (
                    'approval_rejected' if result.get('reason') == 'rejected' else result.get('reason'))
                self.e.reject_approval_in_txn(ns, command_id, reason)
            return dict(result, duplicate=result.get('duplicate', False))
        return self.tx(apply)
