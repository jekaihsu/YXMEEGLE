"""Derived task dates calculated from a CONFIRMED effective deadline (mock/local only).

Reuses the existing workday calendar (`operations.add_workdays`) and the existing protection predicates in
`sop_deadlines` (`_fixed`, `_started`, `_manual`). Nothing here mutates project state: it returns a plan.
Protected (manual / contract-fixed / started / completed) tasks keep their dates; a conflict with provenance is
recorded instead. A derived date is never a formal effective deadline.
"""
import copy

from . import values as V
from .deadlines import DERIVED
from .domain import DomainError


class DerivedService:
    def __init__(self, domain, deadlines):
        self.d, self.dl = domain, deadlines

    @staticmethod
    def _tasks(project):
        found = {}
        for node in project.get('nodes', []):
            for task in node.get('tasks', []):
                found[task['id']] = (node, task)
        for task in project.get('sop_followups', []):
            found[task['id']] = ({'id': task.get('node_id')}, task)
        return found

    def _linked_task_ids(self, dom, rec):
        if rec['kind'] == 'node':
            return set(rec['task_ids'])
        return {t for n in rec['node_ids'] for t in dom['nodes'][n]['task_ids']}

    def recalculate(self, entity_id, project, calendar, rules):
        """rules: [{'task_id', 'rule_id', 'offset'}]. Returns {'status', 'updates', 'conflicts'}; project is untouched."""
        from ..operations import add_workdays, digest
        from ..sop_deadlines import RULE_VERSION, _fixed, _manual, _started
        snap = self.d.snapshot()
        rec = self.d.entity(snap, entity_id)
        effective = rec['deadline']['effective']
        anchor = V.decode(effective['value'])
        if not isinstance(anchor, V.SetValue) or effective['revision'] < 1:
            return {'status': 'no_effective_anchor', 'updates': [], 'conflicts': []}
        if project.get('id') != rec['project_id'] and project.get('project_id') != rec['project_id']:
            raise DomainError('project does not match the case', 'project_mismatch')
        linked = self._linked_task_ids(snap, rec)
        tasks = self._tasks(project)
        updates, conflicts, entries = [], [], []
        for rule in rules:
            task_id = rule['task_id']
            if task_id not in linked or task_id not in tasks:
                raise DomainError('task is not linked to this entity', 'task_not_linked')
            _, task = tasks[task_id]
            calculated = add_workdays(anchor.value, rule['offset'], calendar)
            provenance = {'anchor_entity_id': entity_id, 'anchor_revision': effective['revision'], 'anchor_date': anchor.value,
                          'rule_id': rule['rule_id'], 'rule_version': RULE_VERSION, 'workday_offset': rule['offset'],
                          'calculated_due': calculated, 'calendar_hash': digest(calendar), 'calendar_snapshot': copy.deepcopy(calendar)}
            entries.append({'task_id': task_id, 'rule_id': rule['rule_id'], 'anchor_revision': effective['revision'],
                            'calculated_due': calculated, 'calendar_hash': provenance['calendar_hash']})
            prior = task.get('sop_due_provenance')
            if task.get('due_date') == calculated:
                continue
            if _fixed(task) or _started(task) or _manual(task, prior):
                reason = 'contract_fixed' if _fixed(task) else 'work_started' if _started(task) else 'existing_manual_date'
                key = f"derived:{task_id}:{rule['rule_id']}:{effective['revision']}:{calculated}"
                conflicts.append({'conflict_id': key, 'entity_id': entity_id, 'task_id': task_id, 'current_due': task.get('due_date'),
                                  'proposed_due': calculated, 'provenance': provenance, 'reason': reason, 'status': 'pending'})
            else:
                updates.append({'task_id': task_id, 'due_date': calculated, 'provenance': provenance,
                                'set_original_due_date': not task.get('original_due_date')})

        def persist(dom):
            record = self.d.entity(dom, entity_id)
            for entry in entries:
                if entry not in [{k: e[k] for k in entry} for e in record['deadline']['derived']]:
                    record['deadline']['derived'].append(dict(entry, at=self.d.now_iso(), kind=DERIVED))
            for conflict in conflicts:
                dom['derived_conflicts'].setdefault(conflict['conflict_id'], dict(conflict, created_at=self.d.now_iso()))
        self.d.tx(persist)
        return {'status': 'planned', 'updates': updates, 'conflicts': conflicts}

    def resolve_conflict(self, command_id, conflict_id, mode, actor, project, reason):
        """Explicit, authorized resolution against a FRESH project baseline. Returns the adoption for the caller to apply."""
        from ..sop_deadlines import _fixed, _started
        if mode not in ('keep_current', 'apply_derived'):
            raise V.ValidationError('unknown resolution', 'invalid_resolution')
        if not isinstance(reason, str) or not reason.strip():
            raise V.ValidationError('a resolution reason is required', 'missing_reason')
        payload = {'op': 'resolve_derived', 'conflict_id': conflict_id, 'mode': mode, 'actor': actor.key}

        def apply(dom):
            def run():
                if not self.d.policy.allows(self.d.in_scope(actor).key, 'resolve_conflict', conflict_id):
                    return {'status': 'denied', 'reason': 'not_authorized'}
                conflict = dom['derived_conflicts'].get(conflict_id)
                if conflict is None:
                    return {'status': 'denied', 'reason': 'unknown_conflict'}
                if conflict['status'] != 'pending':
                    return {'status': 'denied', 'reason': 'already_resolved'}
                found = self._tasks(project).get(conflict['task_id'])
                if found is None or found[1].get('due_date') != conflict['current_due']:
                    return {'status': 'denied', 'reason': 'baseline_changed'}
                rec = self.d.entity(dom, conflict['entity_id'])
                if rec['deadline']['effective']['revision'] != conflict['provenance']['anchor_revision']:
                    return {'status': 'denied', 'reason': 'stale_anchor'}
                adopt = None
                if mode == 'apply_derived':
                    task = found[1]
                    if _fixed(task):
                        return {'status': 'denied', 'reason': 'contract_fixed'}
                    if _started(task):
                        return {'status': 'denied', 'reason': 'work_started_requires_formal_process'}
                    adopt = {'task_id': task['id'], 'due_date': conflict['proposed_due'], 'provenance': conflict['provenance']}
                conflict.update(status='resolved', resolution=mode, reason_note=reason, resolved_by=actor.key,
                                resolved_at=self.d.now_iso(), resolution_command=command_id)
                return {'status': 'resolved', 'mode': mode, 'adopt': adopt}
            return self.d.ledgered(dom, command_id, payload, run)
        return self.d.tx(apply)

