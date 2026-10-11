"""Delivery state machine, durable outbox/inbox, conflicts and reconciliation (mock/local only).

All state lives in the `ops_sync` namespace of an injected `OpsStore`. Every state change is one
store transaction; adapter calls happen between transactions and are fenced by per-entity leases.
PM eligibility and derived-date recalculation belong to later tasks. `approval_required` fields dispatch only on a
consumed, matching domain approval that is bound to the command (see approval_binding.py), never on a bare reference.
"""
from dataclasses import dataclass
from datetime import timezone

from . import adapter as A
from . import approval_binding as AB
from . import values as V
from .clock import SystemClock
from .commands import CommandEnvelope, payload_fingerprint

WAITING, QUEUED, UNKNOWN_S, CONFIRMED, CONFLICT, FAILED = 'waiting_approval', 'queued', 'unknown', 'confirmed', 'conflict', 'failed'
TERMINAL = (CONFIRMED, CONFLICT, FAILED)
MAX_ATTEMPTS = 5
MAX_READS = 5
LEASE_TTL = 30


class IdentityCollision(V.OpsError):
    code = 'identity_collision'


@dataclass
class Attempt:
    command_id: str
    number: int
    fence: int
    entity_id: str
    field_id: str
    expected_revision: int
    intended: object
    binding: str


def _ns(ns):
    for key in ('commands', 'inbox', 'checkpoints', 'projection', 'conflicts', 'fence', 'entity_leases',
                'suspended', 'recovery_needed', 'proposals', 'approval_bindings'):
        ns.setdefault(key, {})
    for key in ('history', 'outbox', 'integrity'):
        ns.setdefault(key, [])
    return ns


class OpsEngine:
    def __init__(self, store, adapter, clock=None, binding=A.BINDING, authorizer=None, approval_required=(),
                 max_attempts=MAX_ATTEMPTS, max_reads=MAX_READS, lease_ttl=LEASE_TTL):
        self.store, self.adapter, self.clock = store, adapter, clock or SystemClock()
        self.binding = binding
        self.authorizer = authorizer or (lambda envelope, phase: None)
        self.approval_required = set(approval_required)
        self.max_attempts, self.max_reads, self.lease_ttl = max_attempts, max_reads, lease_ttl

    # -- helpers -------------------------------------------------------------------------
    def _now(self):
        return self.clock.now().astimezone(timezone.utc).isoformat()

    def _tx(self, fn):
        return self.store.transact(lambda ns: fn(_ns(ns)))

    @staticmethod
    def _sync_outbox(ns, cmd):
        pending = cmd['state'] in (QUEUED, UNKNOWN_S)
        cid = cmd['envelope']['command_id']
        if pending and cid not in ns['outbox']:
            ns['outbox'].append(cid)
        elif not pending and cid in ns['outbox']:
            ns['outbox'].remove(cid)

    def _set(self, ns, cmd, state, reason=None):
        cmd['state'], cmd['reason'] = state, reason
        cmd['lease'] = None
        env = cmd['envelope']
        if ns['entity_leases'].get(env['entity_id'], {}).get('command_id') == env['command_id']:
            del ns['entity_leases'][env['entity_id']]
        self._sync_outbox(ns, cmd)

    def _slot(self, ns, entity_id, field_id):
        return ns['projection'].get(f'{entity_id}|{field_id}')

    def _history(self, ns, **entry):
        ns['history'].append(dict(entry, at=self._now()))

    def status(self, command_id):
        cmd = self.store.snapshot().get('commands', {}).get(command_id)
        return cmd and {'state': cmd['state'], 'reason': cmd['reason'], 'attempts': len(cmd['attempts']),
                        'reconcile': cmd['reconcile'], 'result': cmd['result']}

    def snapshot(self):
        return _ns(self.store.snapshot())

    def projection(self, entity_id, field_id):
        slot = self.snapshot()['projection'].get(f'{entity_id}|{field_id}')
        return slot and (V.decode(slot['value']), slot['revision'])

    # -- submission ----------------------------------------------------------------------
    def _submit_in_txn(self, ns, envelope):
        payload = envelope.validated()
        digest = payload_fingerprint(payload)
        existing = ns['commands'].get(envelope.command_id)
        if existing:
            if existing['fingerprint'] != digest:
                raise IdentityCollision('command id reused with a different payload')
            return {'command_id': envelope.command_id, 'status': existing['state'], 'duplicate': True}
        state, reason = QUEUED, None
        if payload['schema_binding_version'] != self.binding:
            state, reason = FAILED, 'schema_binding_mismatch'
        else:
            denied = self.authorizer(envelope, 'submit')
            if denied:
                state, reason = FAILED, denied
            elif envelope.field_id in self.approval_required:
                if not envelope.approval_ref:
                    state, reason = WAITING, 'awaiting_approval'
                else:
                    state, reason = self._bind_approval(ns, payload)
        cmd = {'envelope': payload, 'fingerprint': digest, 'state': state, 'reason': reason, 'attempts': [],
               'next_attempt_at': self._now(), 'lease': None, 'reconcile': None, 'result': None,
               'created_at': self._now(), 'seq': len(ns['commands'])}
        ns['commands'][envelope.command_id] = cmd
        self._sync_outbox(ns, cmd)
        return {'command_id': envelope.command_id, 'status': state, 'duplicate': False, 'reason': reason}

    def submit(self, envelope):
        """Accept a command. Durable acceptance + outbox entry are one atomic transaction."""
        return self._tx(lambda ns: self._submit_in_txn(ns, envelope))

    @staticmethod
    def _bind_approval(ns, payload):
        """Verify the consumed approval and bind it to the command in this same transaction -> (state, reason)."""
        denied = AB.verify(ns, payload, require_bound=False)
        if denied:
            return FAILED, denied
        AB.bind(ns, payload)
        return QUEUED, None

    def grant_approval(self, command_id, approval_ref):
        """Hand a consumed domain approval to a waiting command. A ref that is not a consumed, matching, unused
        approval leaves the command waiting (reason says why); replaying the same grant is a no-op."""
        def apply(ns):
            cmd = ns['commands'][command_id]
            if cmd['state'] == WAITING:
                trial = dict(cmd['envelope'], approval_ref=approval_ref)
                denied = AB.verify(ns, trial, require_bound=False)
                if denied:
                    cmd['reason'] = denied
                    return cmd['state']
                AB.bind(ns, trial)
                cmd['envelope']['approval_ref'] = approval_ref
                self._set(ns, cmd, QUEUED)
                cmd['next_attempt_at'] = self._now()
            return cmd['state']
        return self._tx(apply)

    def reject_approval(self, command_id, reason='approval_rejected'):
        def apply(ns):
            cmd = ns['commands'][command_id]
            if cmd['state'] == WAITING:
                self._set(ns, cmd, FAILED, reason)
            return cmd['state']
        return self._tx(apply)

    def withdraw(self, command_id):
        def apply(ns):
            cmd = ns['commands'][command_id]
            if cmd['state'] in (WAITING, QUEUED) and not cmd['lease']:
                self._set(ns, cmd, FAILED, 'withdrawn')
            elif cmd['state'] not in TERMINAL:
                cmd['withdraw_requested'] = True   # in flight/uncertain: reconcile first, never pretend no write happened
            return cmd['state']
        return self._tx(apply)

    # -- dispatch ------------------------------------------------------------------------
    def _conflict(self, ns, cmd, current_value, current_revision, reason):
        env = cmd['envelope']
        cid = 'conflict:' + env['command_id']
        ns['conflicts'][cid] = {
            'conflict_id': cid, 'command_id': env['command_id'], 'entity_id': env['entity_id'], 'field_id': env['field_id'],
            'expected': {'value': env['expected'], 'revision': env['expected_revision']},
            'current': {'value': V.encode(current_value) if current_value is not V.UNKNOWN else {'t': 'unknown'}, 'revision': current_revision},
            'intended': env['intended'], 'actor': env['actor'], 'source': env['source'],
            'binding': env['schema_binding_version'], 'reason': reason, 'created_at': self._now(), 'resolution': None}
        self._set(ns, cmd, CONFLICT, reason)

    def _gates(self, ns, cmd):
        """Revalidate identity/authority/binding immediately before execution. Returns a failure reason or None."""
        env = cmd['envelope']
        if env['schema_binding_version'] != self.binding:
            return 'schema_binding_mismatch'
        if cmd.get('withdraw_requested') and cmd['state'] == QUEUED:
            return 'withdrawn'
        envelope = CommandEnvelope(env['command_id'], env['entity_id'], env['field_id'], V.decode(env['expected']),
                                   env['expected_revision'], V.decode(env['intended']), env['actor'], env['source'],
                                   env['occurred_at'], env['schema_binding_version'], env['approval_ref'])
        if env['field_id'] in self.approval_required:
            if not env['approval_ref']:
                return 'approval_missing'
            denied = AB.verify(ns, env, require_bound=True)
            if denied:
                return denied
        return self.authorizer(envelope, 'dispatch')

    def begin_dispatch(self, command_id):
        def apply(ns):
            cmd = ns['commands'].get(command_id)
            if not cmd or cmd['state'] != QUEUED or cmd['lease'] or cmd['next_attempt_at'] > self._now():
                return None
            env = cmd['envelope']
            if ns['suspended']:
                return None
            held = ns['entity_leases'].get(env['entity_id'])
            if held and held['expires_at'] > self._now():
                return None
            reason = self._gates(ns, cmd)
            if reason:
                self._set(ns, cmd, FAILED, reason)
                return None
            slot = self._slot(ns, env['entity_id'], env['field_id'])
            if slot is None:
                cmd['reason'] = 'baseline_unobserved'
                return None
            if slot['value'] != env['expected'] or slot['revision'] != env['expected_revision']:
                self._conflict(ns, cmd, V.decode(slot['value']), slot['revision'], 'baseline_changed')
                return None
            if len(cmd['attempts']) >= self.max_attempts:
                self._set(ns, cmd, FAILED, 'retry_exhausted')
                return None
            fence = ns['fence'].get(env['entity_id'], 0) + 1
            ns['fence'][env['entity_id']] = fence
            number = len(cmd['attempts']) + 1
            cmd['attempts'].append({'n': number, 'fence': fence, 'started_at': self._now(), 'outcome': None})
            expires = V.add_seconds(self._now(), self.lease_ttl)
            cmd['lease'] = {'token': fence, 'expires_at': expires}
            ns['entity_leases'][env['entity_id']] = {'command_id': command_id, 'token': fence, 'expires_at': expires}
            return Attempt(command_id, number, fence, env['entity_id'], env['field_id'], env['expected_revision'],
                           V.decode(env['intended']), env['schema_binding_version'])
        return self._tx(apply)

    def dispatch(self, attempt):
        """Perform the adapter call for a begun attempt, then record the outcome (fenced)."""
        outcome = {'kind': 'unknown', 'code': 'unclassified'}
        try:
            receipt = self.adapter.write(attempt.command_id, attempt.entity_id, attempt.field_id,
                                         attempt.expected_revision, attempt.intended, attempt.binding, attempt.fence)
            if (not isinstance(receipt, dict) or receipt.get('op_id') != attempt.command_id
                    or isinstance(receipt.get('revision'), bool) or not isinstance(receipt.get('revision'), int)):
                outcome = {'kind': 'unknown', 'code': 'malformed_response'}
            else:
                outcome = {'kind': 'receipt', 'receipt': receipt}
        except A.CasMismatch as exc:
            outcome = {'kind': 'cas', 'revision': exc.current_revision}
        except (A.TransientNoCommit, A.StaleFence) as exc:
            outcome = {'kind': 'transient', 'retry_after': getattr(exc, 'retry_after', 0), 'code': exc.code}
        except A.PermissionDenied:
            outcome = {'kind': 'denied', 'code': 'permission_denied'}
        except A.SchemaMismatch:
            outcome = {'kind': 'denied', 'code': 'schema_binding_mismatch'}
        except A.AdapterTimeout:
            outcome = {'kind': 'unknown', 'code': 'timeout'}
        except Exception as exc:  # any other failure after a write call is ambiguous
            outcome = {'kind': 'unknown', 'code': getattr(exc, 'code', 'adapter_exception')}
        read = None
        if outcome['kind'] in ('receipt', 'cas'):
            read = self._safe_read(attempt.entity_id, attempt.field_id)
        return self._finish(attempt, outcome, read)

    def _safe_read(self, entity_id, field_id):
        try:
            obs = self.adapter.read(entity_id, [field_id])
        except A.AdapterError as exc:
            return {'ok': False, 'code': exc.code}
        if not obs.complete or obs.values.get(field_id) is V.UNKNOWN or field_id not in obs.revisions:
            return {'ok': False, 'code': obs.reason or 'incomplete_read'}
        if obs.binding_version != self.binding:
            return {'ok': False, 'code': 'schema_binding_mismatch'}
        return {'ok': True, 'value': obs.values[field_id], 'revision': obs.revisions[field_id]}

    def _to_unknown(self, ns, cmd, code):
        self._set(ns, cmd, UNKNOWN_S, code)
        cmd['reconcile'] = {'phase': 'pending', 'reads': 0, 'next_read_at': self._now(), 'blocker': code, 'token': None}

    def _confirm(self, ns, cmd, receipt_revision, read):
        env = cmd['envelope']
        if cmd['state'] == CONFIRMED:
            return
        slot_key = f"{env['entity_id']}|{env['field_id']}"
        prior = ns['projection'].get(slot_key)
        if read['revision'] < receipt_revision:
            return self._to_unknown(ns, cmd, 'readback_behind_receipt')
        later = read['revision'] > receipt_revision
        if not later and V.encode(read['value']) != env['intended']:
            return self._conflict(ns, cmd, read['value'], read['revision'], 'readback_value_mismatch')
        ns['projection'][slot_key] = {'value': V.encode(read['value']), 'revision': read['revision']}
        self._set(ns, cmd, CONFIRMED, 'later_edit_observed' if later else None)
        cmd['result'] = {'op_id': env['command_id'], 'revision': receipt_revision}
        self._history(ns, kind='confirmed', command_id=env['command_id'], entity_id=env['entity_id'],
                      field_id=env['field_id'], prior=prior and prior['value'], new=env['intended'],
                      receipt_revision=receipt_revision, actor=env['actor'], source=env['source'],
                      mock=True)

    def _finish(self, attempt, outcome, read):
        def apply(ns):
            cmd = ns['commands'][attempt.command_id]
            lease = cmd['lease']
            if cmd['state'] != QUEUED or not lease or lease['token'] != attempt.fence:
                return {'state': cmd['state'], 'ignored': 'stale_worker'}
            record = cmd['attempts'][-1]
            kind = outcome['kind']
            record['outcome'] = outcome.get('code') or kind
            if kind == 'receipt':
                if read['ok']:
                    self._confirm(ns, cmd, outcome['receipt']['revision'], read)
                else:
                    cmd['result'] = {'op_id': attempt.command_id, 'revision': outcome['receipt']['revision']}
                    self._to_unknown(ns, cmd, read['code'])
            elif kind == 'cas':
                if read['ok']:
                    self._conflict(ns, cmd, read['value'], read['revision'], 'cas_mismatch')
                else:
                    self._conflict(ns, cmd, V.UNKNOWN, outcome['revision'], 'cas_mismatch')
            elif kind == 'transient':
                if attempt.number >= self.max_attempts:
                    self._set(ns, cmd, FAILED, 'retry_exhausted')
                else:
                    self._set(ns, cmd, QUEUED, outcome['code'])
                    cmd['next_attempt_at'] = V.add_seconds(self._now(), V.backoff_seconds(attempt.number, outcome['retry_after']))
            elif kind == 'denied':
                self._set(ns, cmd, FAILED, outcome['code'])
                ns['suspended'][outcome['code']] = {'since': self._now(), 'command_id': attempt.command_id}
            else:
                self._to_unknown(ns, cmd, outcome['code'])
            return {'state': cmd['state'], 'reason': cmd['reason']}
        return self._tx(apply)

    def resume_dispatch(self, reason=None):
        """Explicit recovery action after a permission/schema suspension has been fixed."""
        def apply(ns):
            if reason:
                ns['suspended'].pop(reason, None)
            else:
                ns['suspended'].clear()
        self._tx(apply)

    # -- recovery and reconciliation ----------------------------------------------------
    def recover_leases(self):
        """Expired in-flight leases may have reached the remote: they become unknown, never retried blindly."""
        def apply(ns):
            moved = []
            for cmd in ns['commands'].values():
                lease = cmd['lease']
                if cmd['state'] == QUEUED and lease and lease['expires_at'] <= self._now():
                    if cmd['attempts']:
                        cmd['attempts'][-1]['outcome'] = 'lease_expired'
                    self._to_unknown(ns, cmd, 'lease_expired')
                    moved.append(cmd['envelope']['command_id'])
            for entity, held in list(ns['entity_leases'].items()):
                if held['expires_at'] <= self._now():
                    del ns['entity_leases'][entity]
            return moved
        return self._tx(apply)

    def request_recovery(self, command_id):
        """Explicit action that schedules another read cycle after exhaustion."""
        def apply(ns):
            cmd = ns['commands'][command_id]
            rec = cmd['reconcile']
            if cmd['state'] == UNKNOWN_S and rec and rec['phase'] == 'exhausted':
                rec.update(phase='pending', reads=0, next_read_at=self._now())
            return cmd['state']
        return self._tx(apply)

    def reconcile(self, command_id):
        def begin(ns):
            cmd = ns['commands'].get(command_id)
            rec = cmd and cmd['reconcile']
            if not cmd or cmd['state'] != UNKNOWN_S or not rec or rec['phase'] != 'pending' or rec['next_read_at'] > self._now():
                return None
            env = cmd['envelope']
            fence = ns['fence'].get(env['entity_id'], 0) + 1
            ns['fence'][env['entity_id']] = fence
            rec.update(phase='reconciling', token=fence)
            return fence, env['entity_id'], env['field_id']
        started = self._tx(begin)
        if not started:
            return None
        fence, entity_id, field_id = started
        failure, ledger = None, None
        try:
            self.adapter.seal(entity_id, fence)
            ledger = self.adapter.ledger_lookup(command_id)
        except A.AdapterError as exc:
            failure = exc.code
        read = self._safe_read(entity_id, field_id) if not failure else {'ok': False, 'code': failure}
        if not read['ok'] and not failure:
            failure = read['code']

        def finish(ns):
            cmd = ns['commands'][command_id]
            rec = cmd['reconcile']
            if cmd['state'] != UNKNOWN_S or not rec or rec['phase'] != 'reconciling' or rec['token'] != fence:
                return cmd['state']
            env = cmd['envelope']
            if failure:
                rec['reads'] += 1
                rec['blocker'], cmd['reason'] = failure, failure
                if rec['reads'] >= self.max_reads:
                    rec['phase'] = 'exhausted'
                else:
                    rec.update(phase='pending', next_read_at=V.add_seconds(self._now(), V.backoff_seconds(rec['reads'])))
                return cmd['state']
            if ledger:
                if ledger.get('entity_id') != entity_id or ledger.get('field_id') != field_id:
                    return self._to_unknown(ns, cmd, 'ledger_identity_mismatch')
                cmd['reconcile'] = None
                self._confirm(ns, cmd, ledger['revision'], read)
                return cmd['state']
            # sealed + ledger proves this operation never committed
            if V.encode(read['value']) != env['expected'] or read['revision'] != env['expected_revision']:
                cmd['reconcile'] = None
                self._conflict(ns, cmd, read['value'], read['revision'], 'baseline_changed')
                return cmd['state']
            reason = self._gates(ns, cmd)
            cmd['reconcile'] = None
            if reason:
                self._set(ns, cmd, FAILED, reason)
            elif len(cmd['attempts']) >= self.max_attempts:
                self._set(ns, cmd, FAILED, 'retry_exhausted')
            else:
                self._set(ns, cmd, QUEUED, 'proven_noncommit_retry')
                cmd['next_attempt_at'] = self._now()
                ns['projection'][f'{entity_id}|{field_id}'] = {'value': V.encode(read['value']), 'revision': read['revision']}
            return cmd['state']
        return self._tx(finish)

    def run_once(self):
        """One scheduler pass: recover expired leases, reconcile due unknowns, dispatch due queued work."""
        self.recover_leases()
        snap = self.snapshot()
        order = sorted(snap['commands'].values(), key=lambda c: c['seq'])
        done = []
        for cmd in order:
            cid = cmd['envelope']['command_id']
            if cmd['state'] == UNKNOWN_S:
                if self.reconcile(cid):
                    done.append(cid)
            elif cmd['state'] == QUEUED:
                attempt = self.begin_dispatch(cid)
                if attempt:
                    self.dispatch(attempt)
                    done.append(cid)
        return done

    # -- observations and events ---------------------------------------------------------
    FIELDS = tuple(V.FIELD_TYPES)

    def observe(self, entity_id, field_ids=None):
        """Complete bound read that refreshes the confirmed projection. Partial reads change nothing."""
        field_ids = list(field_ids or self.FIELDS)
        try:
            obs = self.adapter.read(entity_id, field_ids)
        except A.AdapterError as exc:
            return {'complete': False, 'reason': exc.code}
        if not obs.complete or obs.binding_version != self.binding or any(obs.values.get(f) is V.UNKNOWN for f in field_ids):
            return {'complete': False, 'reason': obs.reason or 'incomplete_read'}

        def apply(ns):
            for field_id in field_ids:
                key = f'{entity_id}|{field_id}'
                slot = ns['projection'].get(key)
                if slot is None or obs.revisions[field_id] >= slot['revision']:
                    ns['projection'][key] = {'value': V.encode(obs.values[field_id]), 'revision': obs.revisions[field_id]}
                else:
                    ns['integrity'].append({'kind': 'read_behind_projection', 'key': key, 'at': self._now()})
            ns['recovery_needed'].pop(entity_id, None)
            ns['checkpoints'][f'read:{entity_id}'] = {'complete_at': self._now()}
        self._tx(apply)
        return {'complete': True}

    recover_entity = observe

    def process_event(self, event):
        """Inbox: dedup by (scope, event_id); never trust arrival order; only revision+1 advances a field."""
        value = event.get('value', V.UNKNOWN)
        encoded = V.encode(value) if value is not V.UNKNOWN else {'t': 'unknown'}
        body = {k: event.get(k) for k in ('scope', 'event_id', 'entity_id', 'field_id', 'revision', 'command_id')}
        body['value'] = encoded
        digest = payload_fingerprint(body)

        def apply(ns):
            key = f"{event['scope']}|{event['event_id']}"
            seen = ns['inbox'].get(key)
            if seen:
                if seen['fingerprint'] == digest:
                    return 'duplicate'
                ns['integrity'].append({'kind': 'event_id_collision', 'key': key, 'at': self._now()})
                return 'integrity_conflict'
            ns['inbox'][key] = {'fingerprint': digest, 'event': body, 'received_at': self._now(), 'status': None}
            entry = ns['inbox'][key]
            entity_id, field_id, revision = event['entity_id'], event['field_id'], event.get('revision')
            slot_key = f'{entity_id}|{field_id}'
            if revision is None or isinstance(revision, bool) or not isinstance(revision, int):
                ns['recovery_needed'][entity_id] = {'reason': 'unversioned_event', 'at': self._now()}
                entry['status'] = 'recovery_scheduled'
                return entry['status']
            if value is V.UNKNOWN:
                entry['status'] = 'incomplete_ignored'
                return entry['status']
            if field_id in self.approval_required:
                ns['proposals'][key] = {'entity_id': entity_id, 'field_id': field_id, 'value': encoded, 'revision': revision,
                                        'status': 'observed_proposal'}
                entry['status'] = 'proposal_recorded'
                return entry['status']
            slot = ns['projection'].get(slot_key)
            processed = slot['revision'] if slot else 0
            if revision < processed:
                entry['status'] = 'stale_ignored'
            elif revision == processed:
                if slot and slot['value'] != encoded:
                    ns['integrity'].append({'kind': 'equal_revision_different_content', 'key': key, 'at': self._now()})
                    entry['status'] = 'integrity_conflict'
                else:
                    entry['status'] = 'stale_ignored'
            elif revision == processed + 1:
                prior = slot and slot['value']
                ns['projection'][slot_key] = {'value': encoded, 'revision': revision}
                ns['checkpoints'][event['scope']] = {'revision_seen': max(revision, ns['checkpoints'].get(event['scope'], {}).get('revision_seen', 0)), 'at': self._now()}
                self._history(ns, kind='observed', event_id=event['event_id'], entity_id=entity_id, field_id=field_id,
                              prior=prior, new=encoded, revision=revision, command_id=event.get('command_id'))
                entry['status'] = 'applied'
            else:
                ns['recovery_needed'][entity_id] = {'reason': 'revision_gap', 'field_id': field_id, 'at': self._now()}
                entry['status'] = 'recovery_scheduled'
            return entry['status']
        return self._tx(apply)

    # -- conflict resolution ---------------------------------------------------------------
    def resolve_conflict(self, envelope, conflict_id, mode):
        """A resolution is a NEW linked command with a freshly read baseline; it never rewrites the original."""
        if envelope.resolves != conflict_id or envelope.resolution != mode:
            raise V.ValidationError('envelope must link the conflict and resolution mode', 'invalid_resolution')
        conflict = self.snapshot()['conflicts'].get(conflict_id)
        if not conflict or conflict['resolution']:
            raise V.OpsError('no open conflict', 'conflict_not_open')
        if envelope.command_id == conflict['command_id']:
            raise V.ValidationError('resolution needs a new command id', 'reused_command_id')
        if (envelope.entity_id, envelope.field_id) != (conflict['entity_id'], conflict['field_id']):
            raise V.ValidationError('resolution targets another field', 'invalid_resolution')
        if mode == 'apply_intended' and V.encode(V.coerce(envelope.field_id, envelope.intended_value)) != conflict['intended']:
            raise V.ValidationError('apply_intended must carry the original intended value', 'invalid_resolution')
        fresh = self._safe_read(envelope.entity_id, envelope.field_id)
        if not fresh['ok']:
            raise V.OpsError('fresh complete baseline unavailable: ' + fresh['code'], 'baseline_unavailable')
        if V.encode(V.coerce(envelope.field_id, envelope.expected_value)) != V.encode(fresh['value']) or envelope.expected_revision != fresh['revision']:
            raise V.OpsError('another change occurred; re-read and retry', 'baseline_changed')
        if mode == 'keep_current' and V.encode(V.coerce(envelope.field_id, envelope.intended_value)) != V.encode(fresh['value']):
            raise V.ValidationError('keep_current must not request a different value', 'invalid_resolution')

        def apply(ns):
            slot_key = f'{envelope.entity_id}|{envelope.field_id}'
            slot = ns['projection'].get(slot_key)
            if slot is None or fresh['revision'] >= slot['revision']:
                ns['projection'][slot_key] = {'value': V.encode(fresh['value']), 'revision': fresh['revision']}
            result = self._submit_in_txn(ns, envelope)
            cmd = ns['commands'][envelope.command_id]
            if result['duplicate']:
                return result
            if cmd['state'] != FAILED:
                ns['conflicts'][conflict_id]['resolution'] = {'mode': mode, 'command_id': envelope.command_id,
                                                              'actor': envelope.actor, 'at': self._now()}
            if mode == 'keep_current' and cmd['state'] == QUEUED:
                self._set(ns, cmd, CONFIRMED, 'resolved_keep_current')
                cmd['result'] = {'resolution': 'keep_current'}
                self._history(ns, kind='resolution_keep_current', command_id=envelope.command_id, conflict_id=conflict_id,
                              entity_id=envelope.entity_id, field_id=envelope.field_id, actor=envelope.actor)
                result['status'] = CONFIRMED
            return result
        return self._tx(apply)
