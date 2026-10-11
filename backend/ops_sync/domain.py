"""OperationalCase header + NodeRecord linked model, PM seat and node responsibility (mock/local only).

State lives in the `domain` key of the injected `OpsStore` namespace, so every change is one atomic,
version-checked transaction. Existing project/node/task IDs are preserved verbatim and never regenerated.
Case PM assignment never changes task owners. Eligibility, application authorization and the per-case
seat are three separate answers (see eligibility.py).
"""
import copy

from . import values as V
from .eligibility import (ELIGIBLE, INELIGIBLE, PersonIdentity, evaluate)
from .engine import IdentityCollision

SEAT_EMPTY, SEAT_ASSIGNED = 'empty', 'assigned'
SEAT_BLOCKED_INELIGIBLE, SEAT_BLOCKED_UNKNOWN = 'blocked_ineligible', 'blocked_unknown'
BLOCKED = (SEAT_BLOCKED_INELIGIBLE, SEAT_BLOCKED_UNKNOWN)
SCHEMA_BINDING = 'mock-binding-v1'


class DomainError(V.OpsError):
    code = 'domain_error'


def new_deadline():
    return {'original': None, 'contract_revisions': [], 'effective': {'value': {'t': 'clear'}, 'revision': 0},
            'effective_history': [], 'proposals': {}, 'proposal_seq': 0, 'derived': [], 'receipts': {}}


def new_slot():
    return {'person': None, 'revision': 0, 'history': [], 'conflicts': [], 'open_conflicts': []}


def _dom(ns):
    dom = ns.setdefault('domain', {})
    for key in ('cases', 'nodes', 'ledger', 'project_index', 'derived_conflicts'):
        dom.setdefault(key, {})
    return dom


class DomainService:
    def __init__(self, store, clock, eligibility, policy, directory, tenant, app_id):
        self.store, self.clock = store, clock
        self.eligibility, self.policy, self.directory = eligibility, policy, directory
        self.tenant, self.app_id = tenant, app_id

    # -- plumbing ------------------------------------------------------------------------
    def now(self):
        return V.require_aware(self.clock.now())

    def now_iso(self):
        return V.to_utc_iso(self.now())

    def tx(self, fn):
        return self.store.transact(lambda ns: fn(_dom(ns)))

    def view(self, entity_id):
        dom = _dom(self.store.snapshot())
        rec = dom['cases'].get(entity_id) or dom['nodes'].get(entity_id)
        if rec is None:
            raise DomainError('unknown entity', 'unknown_entity')
        return copy.deepcopy(rec)

    def snapshot(self):
        return copy.deepcopy(_dom(self.store.snapshot()))

    @staticmethod
    def entity(dom, entity_id):
        rec = dom['cases'].get(entity_id) or dom['nodes'].get(entity_id)
        if rec is None:
            raise DomainError('unknown entity', 'unknown_entity')
        return rec

    def in_scope(self, identity):
        identity.validated()
        if (identity.tenant, identity.app_id) != (self.tenant, self.app_id):
            raise V.ValidationError('identity belongs to a different tenant/application', 'wrong_application')
        return identity

    def ledgered(self, dom, command_id, payload, fn):
        """Same id + same payload replays the stored result; same id + different payload is a collision."""
        if not isinstance(command_id, str) or not command_id.strip():
            raise V.ValidationError('command_id is required', 'missing_command_id')
        digest = V.fingerprint(payload)
        entry = dom['ledger'].get(command_id)
        if entry:
            if entry['fingerprint'] != digest:
                raise IdentityCollision('command id reused with a different payload')
            return dict(copy.deepcopy(entry['result']), duplicate=True)
        result = fn()
        dom['ledger'][command_id] = {'fingerprint': digest, 'result': copy.deepcopy(result)}
        return dict(result, duplicate=False)

    # -- registration (idempotent, IDs preserved) ----------------------------------------
    def register_case(self, entity_id, project_id, source_binding=None, schema_binding_version=SCHEMA_BINDING):
        for name, value in (('entity_id', entity_id), ('project_id', project_id)):
            if not isinstance(value, str) or not value.strip():
                raise V.ValidationError(f'{name} is required', 'missing_' + name)

        def apply(dom):
            known = dom['cases'].get(entity_id)
            owner = dom['project_index'].get(project_id)
            if known:
                if known['project_id'] != project_id:
                    raise DomainError('entity already bound to another project', 'entity_project_mismatch')
                return False
            if owner:
                raise DomainError('project already has a case header', 'duplicate_case_for_project')
            dom['cases'][entity_id] = {
                'kind': 'case', 'entity_id': entity_id, 'project_id': project_id, 'source_binding': source_binding,
                'schema_binding_version': schema_binding_version, 'node_ids': [], 'pm': dict(new_slot(), state=SEAT_EMPTY,
                eligibility_revision=0, seat_events=[]), 'deadline': new_deadline()}
            dom['project_index'][project_id] = entity_id
            return True
        return self.tx(apply)

    def register_node(self, entity_id, node_id, case_entity_id, task_ids=(), source_binding=None):
        for name, value in (('entity_id', entity_id), ('node_id', node_id)):
            if not isinstance(value, str) or not value.strip():
                raise V.ValidationError(f'{name} is required', 'missing_' + name)
        task_ids = list(task_ids)
        if len(set(task_ids)) != len(task_ids) or any(not isinstance(t, str) or not t for t in task_ids):
            raise V.ValidationError('task_ids must be unique opaque strings', 'invalid_task_ids')

        def apply(dom):
            case = dom['cases'].get(case_entity_id)
            if case is None:
                raise DomainError('parent case is not registered', 'unknown_parent_case')
            for other in dom['nodes'].values():
                if other['entity_id'] != entity_id and other['project_id'] == case['project_id'] and other['node_id'] == node_id:
                    raise DomainError('node already registered under another entity', 'duplicate_node')
                if other['entity_id'] != entity_id:
                    clash = set(task_ids) & set(other['task_ids'])
                    if clash:
                        raise DomainError('task already linked to another node', 'task_linked_elsewhere')
            node = dom['nodes'].get(entity_id)
            if node:
                if (node['node_id'], node['case_id'], node['project_id']) != (node_id, case_entity_id, case['project_id']):
                    raise DomainError('entity already bound to a different node', 'entity_node_mismatch')
                added = [t for t in task_ids if t not in node['task_ids']]
                node['task_ids'].extend(added)      # union only: an import never drops linked tasks
                return bool(added)
            dom['nodes'][entity_id] = {'kind': 'node', 'entity_id': entity_id, 'node_id': node_id, 'case_id': case_entity_id,
                                       'project_id': case['project_id'], 'task_ids': task_ids, 'source_binding': source_binding,
                                       'schema_binding_version': case['schema_binding_version'],
                                       'responsible': new_slot(), 'deadline': new_deadline()}
            case['node_ids'].append(entity_id)
            return True
        return self.tx(apply)

    # -- seat evaluation -----------------------------------------------------------------
    def _refresh_seat(self, dom, case):
        """Re-read eligibility for the recorded PM. Never clears or replaces the person."""
        pm = case['pm']
        if pm['person'] is None:
            return pm['state']
        ev = evaluate(self.eligibility, PersonIdentity.from_key(pm['person']), self.now())
        state = SEAT_ASSIGNED if ev.status == ELIGIBLE else SEAT_BLOCKED_INELIGIBLE if ev.status == INELIGIBLE else SEAT_BLOCKED_UNKNOWN
        revision = pm['eligibility_revision'] if ev.status == 'unknown' else ev.revision
        if state != pm['state'] or revision != pm['eligibility_revision']:
            pm['seat_events'].append({'from': pm['state'], 'to': state, 'eligibility_revision': revision,
                                      'reason': ev.reason or ev.status, 'at': self.now_iso()})
            pm['state'], pm['eligibility_revision'] = state, revision
            pm['revision'] += 1
        return pm['state']

    def refresh_pm_seat(self, entity_id):
        return self.tx(lambda dom: self._refresh_seat(dom, self.entity(dom, entity_id)))

    def pm_gate(self, dom, case):
        """Reason PM-dependent actions are denied right now, or None. Re-reads eligibility first."""
        self._refresh_seat(dom, case)
        pm = case['pm']
        if pm['state'] in BLOCKED:
            return 'pm_seat_' + pm['state']
        if pm['open_conflicts']:
            return 'assignment_ambiguous'
        return None

    # -- assignment ----------------------------------------------------------------------
    def _assign(self, dom, slot, entity_id, field_id, action, command_id, actor, source, candidates, reason, check_person):
        if not self.policy.allows(self.in_scope(actor).key, action, entity_id):
            return {'status': 'denied', 'reason': 'not_authorized'}
        if candidates is V.CLEAR:
            keys = []
        else:
            if not isinstance(candidates, (list, tuple)) or not candidates:
                raise V.ValidationError('candidates must be a non-empty list or CLEAR', 'invalid_candidates')
            keys = []
            for cand in candidates:
                key = self.in_scope(cand).key
                if key not in keys:
                    keys.append(key)
        at = self.now_iso()
        if len(keys) > 1:
            conflict_id = 'assign:' + command_id
            slot['conflicts'].append({'conflict_id': conflict_id, 'candidates': keys, 'retained': slot['person'],
                                      'actor': actor.key, 'source': source, 'command_id': command_id, 'at': at})
            slot['open_conflicts'].append(conflict_id)
            return {'status': 'conflict', 'reason': 'multiple_assignees', 'conflict_id': conflict_id}
        if keys:
            ident = PersonIdentity.from_key(keys[0])
            if not self.directory.is_active(ident):
                return {'status': 'denied', 'reason': 'not_active'}
            denied = check_person(ident)
            if denied:
                return {'status': 'denied', 'reason': denied}
        new = keys[0] if keys else None
        for cid in slot['open_conflicts']:
            for c in slot['conflicts']:
                if c['conflict_id'] == cid:
                    c['resolved_by'] = command_id
        slot['open_conflicts'] = []
        if new == slot['person']:
            return {'status': 'unchanged'}
        slot['history'].append({'prior': slot['person'], 'new': new, 'actor': actor.key, 'source': source,
                                'command_id': command_id, 'reason': reason, 'at': at, 'field_id': field_id})
        slot['person'] = new
        slot['revision'] += 1
        return {'status': 'assigned' if new else 'cleared'}

    def assign_pm(self, command_id, entity_id, actor, candidates, reason='', source='app'):
        return self.tx(lambda dom: self.assign_pm_in_txn(dom, command_id, entity_id, actor, candidates, reason, source))

    def assign_pm_in_txn(self, dom, command_id, entity_id, actor, candidates, reason='', source='app'):
        payload = {'op': 'assign_pm', 'entity_id': entity_id, 'actor': actor.key,
                   'candidates': 'CLEAR' if candidates is V.CLEAR else sorted(c.key for c in candidates), 'source': source}

        def apply(dom):
            case = self.entity(dom, entity_id)
            if case['kind'] != 'case':
                raise DomainError('PM seats belong to cases', 'not_a_case')

            def run():
                self._refresh_seat(dom, case)

                def check(ident):
                    ev = evaluate(self.eligibility, ident, self.now())
                    if ev.status == INELIGIBLE:
                        return 'ineligible'
                    if ev.status != ELIGIBLE:
                        return 'eligibility_unknown'
                    return None
                result = self._assign(dom, case['pm'], entity_id, 'case.pm', 'clear_pm' if candidates is V.CLEAR else 'assign_pm',
                                      command_id, actor, source, candidates, reason, check)
                if result['status'] in ('assigned', 'cleared'):
                    pm = case['pm']
                    pm['state'] = SEAT_ASSIGNED if pm['person'] else SEAT_EMPTY
                    if pm['person']:
                        ev = evaluate(self.eligibility, PersonIdentity.from_key(pm['person']), self.now())
                        pm['eligibility_revision'] = ev.revision
                return result
            return self.ledgered(dom, command_id, payload, run)
        return apply(dom)

    def assign_responsible(self, command_id, node_entity_id, actor, candidates, reason='', source='app'):
        return self.tx(lambda dom: self.assign_responsible_in_txn(
            dom, command_id, node_entity_id, actor, candidates, reason, source))

    def assign_responsible_in_txn(self, dom, command_id, node_entity_id, actor, candidates, reason='', source='app'):
        payload = {'op': 'assign_responsible', 'entity_id': node_entity_id, 'actor': actor.key,
                   'candidates': 'CLEAR' if candidates is V.CLEAR else sorted(c.key for c in candidates), 'source': source}

        def apply(dom):
            node = self.entity(dom, node_entity_id)
            if node['kind'] != 'node':
                raise DomainError('responsibility belongs to nodes', 'not_a_node')
            case = dom['cases'][node['case_id']]

            def check(ident):
                if case['pm']['person'] == ident.key:       # PM eligibility only matters if they also hold the PM seat
                    ev = evaluate(self.eligibility, ident, self.now())
                    if ev.status != ELIGIBLE:
                        return 'pm_seat_holder_not_eligible'
                return None
            return self.ledgered(dom, command_id, payload, lambda: self._assign(
                dom, node['responsible'], node_entity_id, 'node.responsible', 'assign_responsible', command_id, actor, source,
                candidates, reason, check))
        return apply(dom)
