import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from ..models import WorkspaceRow, BusinessRow
from .catalog import digest, publish
from .case_stage import start_node
from .domain import (Applicability, Lifecycle, Disposition, TRANSITIONS, NODE_MAP, SUBCONTRACT,
                     CONDITIONAL, PARTICIPANT_ROLES, require)
from .models import Family, Version, TemplateRow, CaseState, LocalTask, TaskNodeLink, Preview, ImportRun, TaskEvent


@dataclass
class Context:
    wid: str
    user: dict
    state: dict
    project: dict
    refresh: object


def explicitly_granted(user, capability):
    return user.get('active', True) and capability in user.get('capabilities', [])


def can_manage(ctx):
    return explicitly_granted(ctx.user, 'sop_task_import') and (
        ctx.user.get('role') == 'manager' or ctx.user['id'] == ctx.project.get('pm_id')
        or ctx.user['id'] in ctx.project.get('sop_task_delegate_ids', []))


def authorize(ctx, write=False):
    require(ctx.user.get('active', True), 'sop_import_forbidden', 403)
    require(any(explicitly_granted(ctx.user, c) for c in ('sop_task_read', 'sop_task_import', 'sop_task_work')),
            'sop_import_forbidden', 403)
    if write:
        require(can_manage(ctx), 'sop_import_forbidden', 403)


def text(value, maximum=20000, *, empty=True):
    require(isinstance(value, str) and len(value) <= maximum and (empty or value.strip()), 'invalid_request')
    return value


def identifier(value):
    return text(value, 120, empty=False)


def fields(body, allowed):
    require(isinstance(body, dict) and not set(body) - set(allowed), 'invalid_request')


def row_keys(value):
    require(isinstance(value, list) and len(value) <= 62 and all(isinstance(k, str) for k in value), 'invalid_request')
    require(len(value) == len(set(value)), 'invalid_request')
    return value


class Service:
    def __init__(self, sessions, *, writes_enabled=lambda: False, clock=time.time):
        self.sessions, self.writes_enabled, self.clock = sessions, writes_enabled, clock

    def writable(self):
        require(self.writes_enabled(), 'import_unavailable', 503)

    @staticmethod
    def lock_workspace_row(db, wid):
        found = db.execute(update(WorkspaceRow).where(WorkspaceRow.id == wid).values(version=WorkspaceRow.version))
        require(found.rowcount == 1, 'case_not_found', 404)

    def lock(self, db, ctx, *, manager=True):
        self.lock_workspace_row(db, ctx.wid)
        fresh = ctx.refresh()
        require(fresh.wid == ctx.wid and fresh.user['id'] == ctx.user['id'], 'sop_import_forbidden', 403)
        authorize(fresh, manager)
        insert = sqlite_insert if db.bind.dialect.name == 'sqlite' else pg_insert
        db.execute(insert(CaseState).values(workspace_id=ctx.wid, project_id=ctx.project['id'],
                                          checklist_revision=0, identity_revision=0, lock_counter=0)
                   .on_conflict_do_nothing(index_elements=['workspace_id', 'project_id']))
        state = db.scalar(select(CaseState).where(CaseState.workspace_id == ctx.wid,
                                                 CaseState.project_id == ctx.project['id']).with_for_update())
        state.lock_counter += 1
        return fresh, state

    def nodes(self, db, ctx, keys):
        require(set(keys) <= set(NODE_MAP.values()) and bool(keys), 'node_mapping_invalid')
        rows = list(db.scalars(select(BusinessRow).where(BusinessRow.workspace_id == ctx.wid,
                                                        BusinessRow.kind == 'nodes',
                                                        BusinessRow.parent_id == ctx.project['id'])))
        result = []
        for key in NODE_MAP.values():
            if key not in keys:
                continue
            found = [r for r in rows if r.data.get('key') == key]
            require(len(found) == 1, 'node_mapping_invalid')
            result.append({'node_key': key, 'node_id': found[0].entity_id})
        return result

    @staticmethod
    def case_start_node(db, ctx):
        nodes = db.scalars(select(BusinessRow).where(BusinessRow.workspace_id == ctx.wid,
                                                    BusinessRow.kind == 'nodes',
                                                    BusinessRow.parent_id == ctx.project['id']))
        return start_node(ctx.project, [n.data for n in nodes])

    def version(self, db, wid, version_id):
        version = db.get(Version, (wid, identifier(version_id)))
        require(version is not None and version.status == 'published', 'template_unavailable', 409)
        family = db.get(Family, (wid, version.family_id))
        require(family.lifecycle == 'active', 'template_unavailable', 409)
        return version

    def templates(self, wid, user, version_id=None):
        require(any(explicitly_granted(user, c) for c in ('sop_task_read', 'sop_task_import', 'sop_template_publish')),
                'sop_import_forbidden', 403)
        with self.sessions() as db:
            if version_id:
                require(explicitly_granted(user, 'sop_task_read_source'), 'sop_import_forbidden', 403)
                version = self.version(db, wid, version_id)
                return {**self.version_json(version), 'rows': [self.catalog_row_json(r) for r in self.rows(db, version)]}
            versions = list(db.scalars(select(Version).where(Version.workspace_id == wid, Version.status == 'published')
                                       .order_by(Version.published_at, Version.id)))
            families = {f.id: f for f in db.scalars(select(Family).where(Family.workspace_id == wid, Family.lifecycle == 'active'))}
            latest = {v.family_id: v.id for v in versions}
            return {'templates': [{**self.version_json(v), 'name': families[v.family_id].name,
                                   'is_default': families[v.family_id].is_default and latest[v.family_id] == v.id}
                                  for v in versions if v.family_id in families]}

    @staticmethod
    def catalog_row_json(row):
        source = deepcopy(row.snapshot)
        interpretation = source['proposed_import'].pop('reason', None)
        source['provenance'] = {'interpretation_reason': interpretation}
        return source

    @staticmethod
    def version_json(v):
        return {'version_id': v.id, 'template_family_id': v.family_id, 'revision': v.revision,
                'mapping_revision': v.mapping_revision, 'content_hash': v.content_hash}

    @staticmethod
    def rows(db, version):
        return list(db.scalars(select(TemplateRow).where(TemplateRow.workspace_id == version.workspace_id,
                                                        TemplateRow.version_id == version.id).order_by(TemplateRow.ordinal)))

    def publish_version(self, wid, user, version_id):
        self.writable()
        require(explicitly_granted(user, 'sop_template_publish'), 'sop_import_forbidden', 403)
        with self.sessions.begin() as db:
            self.lock_workspace_row(db, wid)
            v = db.get(Version, (wid, identifier(version_id)))
            require(v is not None, 'template_not_found', 404)
            publish(db, v, user['id'], self.clock())
            return self.version_json(v)

    @staticmethod
    def tasks(db, ctx):
        return list(db.scalars(select(LocalTask).where(LocalTask.workspace_id == ctx.wid,
                                                      LocalTask.project_id == ctx.project['id'])))

    def participants(self, ctx, bindings):
        fields(bindings, PARTICIPANT_ROLES)
        result = {}
        for role, ident in bindings.items():
            identifier(ident)
            candidates = [u for u in ctx.state.get('users', []) if u['id'] == ident and u.get('active', True)
                          and explicitly_granted(u, 'sop_task_work')]
            require(len(candidates) == 1, 'participant_unresolved')
            person = candidates[0]
            permitted = (person.get('role') == 'manager' or ident in
                         {ctx.project.get('pm_id'), ctx.project.get('admin_id'), ctx.project.get('supervisor_id')}
                         or ident in ctx.project.get('sop_task_delegate_ids', [])
                         or ident in ctx.project.get('collaborator_ids', []))
            require(permitted, 'participant_unresolved')
            result[role] = ident
        return result

    def normalize(self, ctx, body, rows):
        fields(body, {'template_version_id', 'node_keys', 'row_keys', 'participant_bindings',
                      'applicability_decisions', 'exclusion_reasons'})
        keys = body.get('node_keys', list(NODE_MAP.values()))
        row_keys(keys)
        require(bool(keys) and set(keys) <= set(NODE_MAP.values()), 'node_mapping_invalid')
        eligible = {r.source_row_key: r for r in rows if r.disposition == Disposition.TASK
                    and set(r.snapshot['proposed_import']['target_branch_node_keys']) & set(keys)}
        decisions = body.get('applicability_decisions', {})
        fields(decisions, eligible)
        normalized_decisions = {}
        for key, decision in decisions.items():
            fields(decision, {'value', 'reason'})
            require(decision.get('value') in {a.value for a in Applicability}, 'invalid_request')
            normalized_decisions[key] = {'value': decision['value'], 'reason': text(decision.get('reason'), 1000, empty=False)}
        selected = body.get('row_keys', [key for key, r in eligible.items()
                                        if r.snapshot['raw']['meegle_id'] not in SUBCONTRACT
                                        or normalized_decisions.get(key, {}).get('value') == 'applicable'])
        row_keys(selected)
        require(set(selected) <= eligible.keys(), 'row_not_importable')
        for key in selected:
            if eligible[key].snapshot['raw']['meegle_id'] in SUBCONTRACT:
                require(normalized_decisions.get(key, {}).get('value') == 'applicable', 'applicability_unresolved')
        bindings = body.get('participant_bindings', {})
        fields(bindings, selected)
        bindings = {key: self.participants(ctx, value) for key, value in bindings.items()}
        exclusions = body.get('exclusion_reasons', {})
        fields(exclusions, eligible.keys() - set(selected))
        exclusions = {key: text(value, 1000, empty=False) for key, value in exclusions.items()}
        return {'template_version_id': body['template_version_id'], 'node_keys': [k for k in NODE_MAP.values() if k in keys],
                'row_keys': sorted(selected), 'participant_bindings': bindings,
                'applicability_decisions': normalized_decisions, 'exclusion_reasons': exclusions}

    def plan(self, db, ctx, state, version, normalized):
        nodes = self.nodes(db, ctx, normalized['node_keys'])
        by_node = {n['node_key']: n['node_id'] for n in nodes}
        existing = {(t.template_family_id, t.source_row_key, t.instance_scope): t for t in self.tasks(db, ctx)}
        links = list(db.scalars(select(TaskNodeLink).where(TaskNodeLink.workspace_id == ctx.wid,
                                                          TaskNodeLink.project_id == ctx.project['id'])))
        linked = {(l.task_id, l.node_key, l.node_id) for l in links}
        outcomes = []
        for row in self.rows(db, version):
            source, proposal = row.snapshot, row.snapshot['proposed_import']
            mapped = set(proposal['target_branch_node_keys']) & by_node.keys()
            if proposal['target_branch_node_keys'] and not mapped:
                continue
            selected = row.source_row_key in normalized['row_keys']
            old = existing.get((version.family_id, row.source_row_key, proposal['instance_scope']))
            app = normalized['applicability_decisions'].get(row.source_row_key, {}).get('value',
                   'unresolved' if source['raw']['meegle_id'] in CONDITIONAL else 'applicable')
            missing = []
            outcome = row.disposition.value
            if row.disposition == Disposition.TASK:
                outcome = 'excluded'
                if selected:
                    outcome = 'already_present' if old else 'new'
                    if old:
                        original = set(old.snapshot['row']['proposed_import']['target_branch_node_keys'])
                        require(mapped <= original, 'template_mapping_conflict', 409)
                    missing = [{'task_id': old.id if old else None, 'node_key': key, 'node_id': by_node[key]}
                               for key in NODE_MAP.values() if key in mapped
                               and (not old or (old.id, key, by_node[key]) not in linked)]
                    if old and missing:
                        outcome = 'link_addition'
            outcomes.append({'source_row_key': row.source_row_key, 'title': source['raw']['title'],
                             'disposition': row.disposition.value, 'selected': selected, 'outcome': outcome,
                             'existing_task_id': old.id if old else None,
                             'existing_state': old.state.value if old else None,
                             'existing_revision': old.revision if old else None,
                             'applicability': old.applicability.value if old else app,
                             'links_to_add': missing,
                             'reason_code': outcome,
                             'exclusion_reason': normalized['exclusion_reasons'].get(row.source_row_key)})
        unresolved = []
        tasks_by_id = {t.id: t for t in existing.values()}
        for outcome in outcomes:
            if not outcome['selected']:
                continue
            old = tasks_by_id.get(outcome['existing_task_id'])
            people = old.participants if old else normalized['participant_bindings'].get(outcome['source_row_key'], {})
            missing = []
            if outcome['applicability'] == 'unresolved':
                missing.append('applicability')
            if not PARTICIPANT_ROLES <= people.keys():
                missing.append('participants')
            if not old or not old.local.get('due_date'):
                missing.append('dates')
            if missing:
                unresolved.append({'source_row_key': outcome['source_row_key'], 'fields': missing})
        context = {'start_node': self.case_start_node(db, ctx), 'identity_revision': state.identity_revision, 'checklist_revision': state.checklist_revision,
                   'nodes': nodes, 'template': self.version_json(version), 'input': normalized, 'outcomes': outcomes}
        return {**context, 'context_hash': digest(context), 'outcomes': outcomes, 'unresolved_items': unresolved,
                'unresolved_counts': {key: sum(key in item['fields'] for item in unresolved)
                                      for key in ('applicability', 'participants', 'dates')},
                'counts': {'new_tasks': sum(o['outcome'] == 'new' for o in outcomes),
                           'existing_tasks': sum(o['selected'] and bool(o['existing_task_id']) for o in outcomes),
                           'added_links': sum(len(o['links_to_add']) for o in outcomes)}}

    def preview(self, ctx, body):
        self.writable()
        authorize(ctx, True)
        with self.sessions.begin() as db:
            ctx, state = self.lock(db, ctx)
            version = self.version(db, ctx.wid, body.get('template_version_id'))
            normalized = self.normalize(ctx, body, self.rows(db, version))
            plan = self.plan(db, ctx, state, version, normalized)
            ident, expires = str(uuid4()), self.clock() + 900
            db.add(Preview(workspace_id=ctx.wid, id=ident, project_id=ctx.project['id'], actor_id=ctx.user['id'],
                           expires_at=expires, context_hash=plan['context_hash'], data=plan))
            return self.preview_json(ident, expires, ctx.project['id'], plan)

    @staticmethod
    def preview_json(ident, expires, pid, plan):
        return {'preview_id': ident, 'expires_at': expires, 'project_id': pid,
                **{k: v for k, v in plan.items() if k != 'input'}, 'selection': plan['input']}

    def apply(self, ctx, body):
        fields(body, {'preview_id', 'request_id'})
        pid, rid = identifier(body.get('preview_id')), identifier(body.get('request_id'))
        authorize(ctx, True)
        with self.sessions.begin() as db:
            ctx, state = self.lock(db, ctx)
            run = db.get(ImportRun, (ctx.wid, ctx.project['id'], rid))
            fingerprint = digest({'preview_id': pid, 'actor_id': ctx.user['id']})
            if run:
                require(run.request_hash == fingerprint, 'idempotency_mismatch', 409)
                return {**run.receipt, 'replayed': True}
            self.writable()
            preview = db.get(Preview, (ctx.wid, pid))
            require(preview is not None and preview.project_id == ctx.project['id']
                    and preview.actor_id == ctx.user['id'], 'preview_not_found', 404)
            require(preview.expires_at > self.clock(), 'preview_stale', 409)
            plan = preview.data
            version = self.version(db, ctx.wid, plan['input']['template_version_id'])
            normalized = self.normalize(ctx, plan['input'], self.rows(db, version))
            live = self.plan(db, ctx, state, version, normalized)
            require(live['context_hash'] == preview.context_hash, 'preview_stale', 409)
            rows = {r.source_row_key: r for r in self.rows(db, version)}
            created, existing, added = [], [], []
            for outcome in plan['outcomes']:
                if not outcome['selected']:
                    continue
                key = outcome['source_row_key']
                row = rows[key]
                task = db.get(LocalTask, (ctx.wid, outcome['existing_task_id'])) if outcome['existing_task_id'] else None
                if task:
                    existing.append(task.id)
                else:
                    related = {30: [31], 41: [31, 47], 46: [47]}.get(row.snapshot['raw']['meegle_id'], [])
                    references = [r.snapshot for r in rows.values() if r.snapshot['raw']['meegle_id'] in related]
                    task = LocalTask(workspace_id=ctx.wid, id=str(uuid4()), project_id=ctx.project['id'],
                                     template_family_id=version.family_id, source_row_key=key,
                                     instance_scope=row.snapshot['proposed_import']['instance_scope'], imported_version_id=version.id,
                                     snapshot={'row': deepcopy(row.snapshot), 'template': self.version_json(version),
                                               'content_hash': digest(row.snapshot), 'related_references': references},
                                     title=row.snapshot['raw']['title'], instructions=row.snapshot['raw']['procedure_raw'] or '',
                                     participants=normalized['participant_bindings'].get(key, {}),
                                     applicability=Applicability(outcome['applicability']), state=Lifecycle.PENDING, revision=1,
                                     local={'due_date': None, 'timezone': 'Asia/Taipei', 'date_status': 'unresolved',
                                            'applicability_decision': normalized['applicability_decisions'].get(key),
                                            'completion_rule_status': 'unresolved', 'attestations': {}})
                    db.add(task)
                    db.flush()
                    created.append(task.id)
                    self.event(db, ctx, task, 'imported', {'template_version_id': version.id})
                for link in outcome['links_to_add']:
                    db.add(TaskNodeLink(workspace_id=ctx.wid, project_id=ctx.project['id'], task_id=task.id,
                                        node_id=link['node_id'], node_key=link['node_key'], ordinal=row.ordinal))
                    added.append({**link, 'task_id': task.id})
                    self.event(db, ctx, task, 'node_link_added', {'node_id': link['node_id'], 'node_key': link['node_key']})
            if created or added:
                state.checklist_revision += 1
            receipt = {'run_id': str(uuid4()), 'request_id': rid, 'project_id': ctx.project['id'],
                       'template_version_id': version.id, 'start_node': plan['start_node'], 'replayed': False, 'created_task_ids': created,
                       'existing_task_ids': existing, 'added_links': added,
                       'exclusions': [o for o in plan['outcomes'] if not o['selected']],
                       'unresolved_items': plan['unresolved_items'], 'unresolved_counts': plan['unresolved_counts'],
                       'checklist_revision': state.checklist_revision}
            db.add(ImportRun(workspace_id=ctx.wid, project_id=ctx.project['id'], request_id=rid, id=receipt['run_id'],
                             actor_id=ctx.user['id'], request_hash=fingerprint, receipt=receipt))
            return receipt

    def receipt(self, ctx, request_id):
        authorize(ctx)
        with self.sessions() as db:
            run = db.get(ImportRun, (ctx.wid, ctx.project['id'], identifier(request_id)))
            require(run is not None, 'run_not_found', 404)
            require(run.actor_id == ctx.user['id'] or can_manage(ctx), 'sop_import_forbidden', 403)
            return run.receipt

    def event(self, db, ctx, task, kind, changes):
        db.add(TaskEvent(workspace_id=ctx.wid, id=str(uuid4()), project_id=ctx.project['id'], task_id=task.id,
                         actor_id=ctx.user['id'], at=self.clock(), kind=kind, revision=task.revision, changes=changes))

    @staticmethod
    def counts(tasks):
        active = [t for t in tasks if t.state != Lifecycle.ARCHIVED]
        applicable = [t for t in active if t.applicability == Applicability.APPLICABLE]
        return {'done': sum(t.state == Lifecycle.DONE for t in applicable), 'total': len(applicable),
                'unresolved': sum(t.applicability == Applicability.UNRESOLVED for t in active),
                'not_applicable': sum(t.applicability == Applicability.NOT_APPLICABLE for t in active),
                'archived': len(tasks) - len(active)}

    def task_json(self, task, links, source=False):
        today = datetime.fromtimestamp(self.clock(), ZoneInfo('Asia/Taipei')).date().isoformat()
        return {'id': task.id, 'task_source': 'sop_local', 'project_id': task.project_id,
                'origin': {'template_family_id': task.template_family_id, 'source_row_key': task.source_row_key,
                           'instance_scope': task.instance_scope, 'imported_version_id': task.imported_version_id},
                'title': task.title, 'instructions': task.instructions if source or task.template_family_id == 'manual' else None,
                'participants': task.participants, 'applicability': task.applicability.value, 'state': task.state.value,
                'revision': task.revision, 'local': task.local,
                'overdue': bool(task.local.get('due_date') and task.local['due_date'] < today
                                and task.applicability == Applicability.APPLICABLE
                                and task.state not in {Lifecycle.DONE, Lifecycle.ARCHIVED}),
                'nodes': [{'node_key': l.node_key, 'node_id': l.node_id, 'order': l.ordinal} for l in links],
                'source_snapshot': task.snapshot if source else None,
                'source_restriction': None if source else 'sop_task_read_source_required'}

    def overview(self, ctx, node_key=None):
        authorize(ctx)
        require(node_key is None or node_key in NODE_MAP.values(), 'node_mapping_invalid')
        with self.sessions() as db:
            state = db.get(CaseState, (ctx.wid, ctx.project['id']))
            tasks = self.tasks(db, ctx)
            links = list(db.scalars(select(TaskNodeLink).where(TaskNodeLink.workspace_id == ctx.wid,
                                                              TaskNodeLink.project_id == ctx.project['id'])
                                    .order_by(TaskNodeLink.ordinal, TaskNodeLink.node_key)))
            by_task = {t.id: [l for l in links if l.task_id == t.id] for t in tasks}
            selected = [t for t in tasks if node_key is None or any(l.node_key == node_key for l in by_task[t.id])]
            selected.sort(key=lambda t: (t.template_family_id == 'manual', min((l.ordinal for l in by_task[t.id]), default=0), t.id))
            return {'project_id': ctx.project['id'], 'task_source': 'sop_local',
                    'start_node': self.case_start_node(db, ctx),
                    'checklist_revision': state.checklist_revision if state else 0,
                    'identity_revision': state.identity_revision if state else 0, 'scope': {'node_key': node_key},
                    'counts': self.counts(selected), 'case_counts': self.counts(tasks),
                    'node_counts': {key: self.counts([t for t in tasks if any(l.node_key == key for l in by_task[t.id])])
                                    for key in NODE_MAP.values()},
                    'tasks': [self.task_json(t, by_task[t.id], explicitly_granted(ctx.user, 'sop_task_read_source')) for t in selected],
                    'allowed_actions': {'import': can_manage(ctx) and self.writes_enabled(),
                                        'manage': can_manage(ctx) and self.writes_enabled(),
                                        'work': explicitly_granted(ctx.user, 'sop_task_work') and self.writes_enabled()}}

    def manual(self, ctx, body):
        fields(body, {'title', 'instructions', 'node_keys', 'participants'})
        self.writable()
        with self.sessions.begin() as db:
            ctx, state = self.lock(db, ctx)
            keys = row_keys(body.get('node_keys', []))
            nodes = self.nodes(db, ctx, keys)
            task = LocalTask(workspace_id=ctx.wid, id=str(uuid4()), project_id=ctx.project['id'],
                             template_family_id='manual', source_row_key=str(uuid4()), instance_scope='case', snapshot={},
                             title=text(body.get('title'), 500, empty=False), instructions=text(body.get('instructions', '')),
                             participants=self.participants(ctx, body.get('participants', {})),
                             applicability=Applicability.APPLICABLE, state=Lifecycle.PENDING, revision=1,
                             local={'due_date': None, 'timezone': 'Asia/Taipei', 'date_status': 'unresolved',
                                    'completion_rule_status': 'no_typed_obligations', 'attestations': {}})
            db.add(task)
            db.flush()
            for n in nodes:
                db.add(TaskNodeLink(workspace_id=ctx.wid, task_id=task.id, project_id=ctx.project['id'],
                                    node_id=n['node_id'], node_key=n['node_key'], ordinal=10000))
            self.event(db, ctx, task, 'created', {})
            state.checklist_revision += 1
            return {'task_id': task.id, 'revision': task.revision, 'checklist_revision': state.checklist_revision}

    def mutate(self, ctx, task_id, body, *, transition=False):
        self.writable()
        fields(body, {'expected_revision', 'action', 'reason', 'applicability'} if transition else
               {'expected_revision', 'title', 'instructions', 'participants', 'due_date', 'reason'})
        require(type(body.get('expected_revision')) is int, 'invalid_request')
        with self.sessions.begin() as db:
            ctx, state = self.lock(db, ctx, manager=not transition)
            task = db.get(LocalTask, (ctx.wid, task_id))
            require(task is not None and task.project_id == ctx.project['id'], 'task_not_found', 404)
            manager = can_manage(ctx)
            if transition:
                require(manager or (explicitly_granted(ctx.user, 'sop_task_work')
                                    and task.participants.get('executor') == ctx.user['id']), 'sop_import_forbidden', 403)
            require(task.revision == body['expected_revision'], 'task_revision_conflict', 409)
            if transition:
                self.transition(task, body, manager)
            else:
                require(task.state not in {Lifecycle.DONE, Lifecycle.ARCHIVED}, 'task_reopen_required', 409)
                for key in ('title', 'instructions'):
                    if key in body:
                        setattr(task, key, text(body[key], 500 if key == 'title' else 20000, empty=key != 'title'))
                if 'participants' in body:
                    task.participants = self.participants(ctx, body['participants'])
                    task.local = {**task.local, 'attestations': {}}
                if 'due_date' in body:
                    value = body['due_date']
                    require(value is None or isinstance(value, str), 'invalid_request')
                    try:
                        require(value is None or date.fromisoformat(value).isoformat() == value, 'invalid_request')
                    except ValueError:
                        require(False, 'invalid_request')
                    reason = text(body.get('reason'), 1000, empty=False)
                    task.local = {**task.local, 'due_date': value, 'date_status': 'manual' if value else 'unresolved',
                                  'date_reason': reason}
            task.revision += 1
            state.checklist_revision += 1
            self.event(db, ctx, task, 'transition' if transition else 'edited', deepcopy(body))
            return {'task_id': task.id, 'revision': task.revision, 'checklist_revision': state.checklist_revision,
                    'state': task.state.value, 'applicability': task.applicability.value}

    @staticmethod
    def completion(task):
        require(task.applicability == Applicability.APPLICABLE, 'applicability_unresolved')
        require(task.local.get('completion_rule_status') == 'no_typed_obligations', 'completion_evidence_missing')

    def transition(self, task, body, manager):
        action = body.get('action')
        if action == 'set_applicability':
            require(manager, 'sop_import_forbidden', 403)
            require(task.state not in {Lifecycle.DONE, Lifecycle.ARCHIVED}, 'task_reopen_required', 409)
            require(body.get('applicability') in {a.value for a in Applicability}, 'invalid_request')
            reason = text(body.get('reason'), 1000, empty=False)
            task.applicability = Applicability(body['applicability'])
            task.local = {**task.local, 'applicability_decision': {'value': body['applicability'], 'reason': reason,
                                                               'at': self.clock()}}
            return
        if action == 'restore':
            require(manager and task.state == Lifecycle.ARCHIVED, 'invalid_transition', 409)
            text(body.get('reason'), 1000, empty=False)
            if task.previous_state == Lifecycle.DONE:
                self.completion(task)
            task.state, task.previous_state = task.previous_state, None
            return
        require(action in TRANSITIONS, 'invalid_transition')
        origins, target, needs_reason = TRANSITIONS[action]
        require(task.state in origins, 'invalid_transition', 409)
        if needs_reason:
            text(body.get('reason'), 1000, empty=False)
        if action == 'archive':
            require(manager, 'sop_import_forbidden', 403)
            task.previous_state = task.state
        if target == Lifecycle.IN_PROGRESS:
            require(task.applicability == Applicability.APPLICABLE, 'applicability_unresolved')
        if target == Lifecycle.DONE:
            self.completion(task)
        task.state = target
