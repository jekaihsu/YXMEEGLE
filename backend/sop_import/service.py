import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime
from uuid import uuid4, uuid5, NAMESPACE_URL
from zoneinfo import ZoneInfo

from sqlalchemy import select, update, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from ..models import WorkspaceRow, BusinessRow
from ..source_case_policy import local_viewer
from ..sources import normalized_case
from ..workflow import now
from .catalog import digest, publish
from .case_stage import stage, start_node
from .cleanup_migration import audit_history_detached
from . import local_case, quotes, suggestions, local_nodes
from .enrollment import EnrollmentService
from .enrollment_policy import identity_key
from .domain import (Applicability, Lifecycle, Disposition, TRANSITIONS, NODE_MAP, SUBCONTRACT,
                     CONDITIONAL, PARTICIPANT_ROLES, Failure, require)
from .models import (Family, Version, TemplateRow, CaseState, LocalTask, TaskNodeLink, Preview, ImportRun, TaskEvent,
                     LocalCaseRun)
from .quote_facts import case_facts
from ..node_assignment.evidence import evidence_for
from ..node_skip import valid_waiver


@dataclass
class Context:
    wid: str
    user: dict
    state: dict
    project: dict
    refresh: object
    # Participants without broader case access read only their assigned tasks. Execution still requires the executor role.
    assigned_only: bool = False


def administrator(user):
    return user.get('active', True) and user.get('role') in {'manager', 'admin'}


def explicitly_granted(user, capability):
    return administrator(user) or (user.get('active', True) and capability in user.get('capabilities', []))


def can_manage(ctx):
    return administrator(ctx.user) or ctx.user.get('active', True) and (
        ctx.user['id'] == ctx.project.get('pm_id')
        or ctx.user['id'] in ctx.project.get('sop_task_delegate_ids', [])
        or (ctx.project.get('case_type') == 'intake' and not ctx.project.get('pm_id')
            and explicitly_granted(ctx.user, 'sop_task_import')))


READER_GRANTS = ('sop_task_read', 'sop_task_import', 'sop_task_work')


def has_reader_grant(user):
    return any(explicitly_granted(user, c) for c in READER_GRANTS)


def authorize_reader(user):
    require(user.get('active', True), 'sop_import_forbidden', 403)
    require(has_reader_grant(user), 'sop_import_forbidden', 403)


def holds_task(task, user_id):
    return user_id in task.participants.values()


def created_as_test(task):
    """Only a manual task created as a test fixture may be tagged or removed; the marker lives in the immutable origin."""
    return task.template_family_id == 'manual' and task.snapshot.get('test_fixture') is True


def completed_with_proof(task):
    return (Lifecycle.DONE in {task.state, task.previous_state}
            and any(task.local.get(key) for key in ('result', 'evidence_basis', 'attestations')))


def disposable(task):
    require(created_as_test(task), 'test_task_required', 409)
    require(not completed_with_proof(task), 'task_reopen_required', 409)


def authorize_test_operator(ctx):
    """Test fixtures are created, tagged and removed by workspace managers only, never by a case's PM or delegates."""
    require(administrator(ctx.user), 'sop_import_forbidden', 403)


def authorize(ctx, write=False):
    if ctx.assigned_only:
        require(ctx.user.get('active', True), 'sop_import_forbidden', 403)
    elif not can_manage(ctx):
        authorize_reader(ctx.user)
    if write:
        require(can_manage(ctx), 'sop_import_forbidden', 403)


def completion_policy(task):
    proposal = task.snapshot.get('row', {}).get('proposed_import', {})
    policy = proposal.get('completion_policy')
    if policy is None and task.snapshot.get('row', {}).get('raw', {}).get('meegle_id') in {37,38,30,41,43,44,54,55,56,51,52}:
        return 'proof_required'
    if policy in {'delivery', 'financial', 'proof_required'} or proposal.get('proof_required') is True:
        return 'proof_required'
    if task.local.get('completion_rule_status') not in {None, 'unresolved', 'no_typed_obligations', 'result_note'}:
        return 'proof_required'
    return 'result_note'


def text(value, maximum=20000, *, empty=True):
    require(isinstance(value, str) and len(value) <= maximum and (empty or value.strip()), 'invalid_request')
    return value


def identifier(value):
    return text(value, 120, empty=False)


def fields(body, allowed):
    require(isinstance(body, dict) and not set(body) - set(allowed), 'invalid_request')


LOCAL_FORM = frozenset({'name', 'pm_id', 'client', 'description', 'official_quote_no', 'import_tasks'})
LOCAL_SELECTION = frozenset({'template_version_id', 'node_keys', 'row_keys', 'participant_bindings',
                             'applicability_decisions', 'exclusion_reasons'})


CASE_ROLES = ('pm', 'admin', 'supervisor', 'delegate', 'collaborator', 'manager')


def case_roles(person, project):
    """The roles that make an active person assignable to this case's tasks, in display order."""
    if not person.get('active', True):
        return []
    ident = person['id']
    held = {'pm': ident == project.get('pm_id'), 'admin': ident == project.get('admin_id'),
            'supervisor': ident == project.get('supervisor_id'),
            'delegate': ident in project.get('sop_task_delegate_ids', []),
            'collaborator': ident in project.get('collaborator_ids', []), 'manager': person.get('role') == 'manager'}
    return [role for role in CASE_ROLES if held[role]]


def canonical_node_keys(keys):
    require(bool(keys), 'node_mapping_invalid')
    unknown = next((key for key in keys if key not in NODE_MAP.values()), None)
    require(unknown is None, 'node_mapping_invalid', node_key=unknown)
    return keys


def row_keys(value):
    require(isinstance(value, list) and len(value) <= 62 and all(isinstance(k, str) for k in value), 'invalid_request')
    require(len(value) == len(set(value)), 'invalid_request')
    return value


class Service(EnrollmentService):
    preview_limit = 20

    def prune_previews(self, db, wid, actor_id):
        db.execute(delete(Preview).where(Preview.workspace_id == wid, Preview.expires_at <= self.clock()))
        old = list(db.scalars(select(Preview).where(Preview.workspace_id == wid, Preview.actor_id == actor_id)
                              .order_by(Preview.expires_at.desc(), Preview.id.desc()).offset(self.preview_limit - 1)))
        for draft in old:
            db.delete(draft)

    def __init__(self, sessions, *, writes_enabled=lambda: False, local_cases_enabled=lambda: False, clock=time.time,
                 auto_enabled=lambda: False, auto_since=lambda: None):
        self.auto_enabled, self.auto_since = auto_enabled, auto_since
        self.projection = None
        self.sessions, self.writes_enabled, self.local_cases_enabled, self.clock = (
            sessions, writes_enabled, local_cases_enabled, clock)

    def writable(self):
        require(self.writes_enabled(), 'import_unavailable', 503)

    def creatable(self):
        require(self.local_cases_enabled(), 'local_case_unavailable', 503)

    @staticmethod
    def lock_workspace_row(db, wid):
        found = db.execute(update(WorkspaceRow).where(WorkspaceRow.id == wid).values(version=WorkspaceRow.version))
        require(found.rowcount == 1, 'case_not_found', 404)

    def lock(self, db, ctx, *, manager=True, enrollment=False):
        self.lock_workspace_row(db, ctx.wid)
        fresh = ctx.refresh()
        require(fresh.wid == ctx.wid and fresh.user['id'] == ctx.user['id'], 'sop_import_forbidden', 403)
        authorize(fresh, manager)
        if not enrollment:
            self.check_policy_write(db, fresh)
        insert = sqlite_insert if db.bind.dialect.name == 'sqlite' else pg_insert
        db.execute(insert(CaseState).values(workspace_id=ctx.wid, project_id=ctx.project['id'],
                                          checklist_revision=0, identity_revision=0, lock_counter=0)
                   .on_conflict_do_nothing(index_elements=['workspace_id', 'project_id']))
        state = db.scalar(select(CaseState).where(CaseState.workspace_id == ctx.wid,
                                                 CaseState.project_id == ctx.project['id']).with_for_update())
        state.lock_counter += 1
        return fresh, state

    def nodes(self, db, ctx, keys):
        canonical_node_keys(keys)
        rows = list(db.scalars(select(BusinessRow).where(BusinessRow.workspace_id == ctx.wid,
                                                        BusinessRow.kind == 'nodes',
                                                        BusinessRow.parent_id == ctx.project['id'])))
        result = []
        for key in NODE_MAP.values():
            if key not in keys:
                continue
            found = [r for r in rows if r.data.get('key') == key]
            require(len(found) == 1, 'node_mapping_invalid', node_key=key)
            result.append({'node_key': key, 'node_id': found[0].entity_id})
        return result

    def today(self):
        return datetime.fromtimestamp(self.clock(), ZoneInfo('Asia/Taipei')).date()

    def facts(self, ctx):
        return case_facts(ctx.project, ctx.state, self.today())

    def position(self, db, ctx, facts):
        nodes = db.scalars(select(BusinessRow).where(BusinessRow.workspace_id == ctx.wid,
                                                    BusinessRow.kind == 'nodes',
                                                    BusinessRow.parent_id == ctx.project['id']))
        return {'start_node': start_node(ctx.project, [n.data for n in nodes], facts), 'stage': stage(facts).value}

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

    def participants(self, ctx, bindings, **context):
        fields(bindings, PARTICIPANT_ROLES)
        result = {}
        for role, ident in bindings.items():
            identifier(ident)
            require(any(u['id'] == ident and u.get('active', True) for u in ctx.state.get('users', [])),
                    'participant_unresolved', role=role, **context)
            result[role] = ident
        return result

    def assignees(self, ctx, people_visible):
        """Everyone active may be assigned; people on the case come first. Assigning is what lets them work the task."""
        authorize(ctx)
        people = [(case_roles(u, ctx.project), u) for u in ctx.state.get('users', []) if u.get('active', True)]
        restricted = ctx.assigned_only or not (can_manage(ctx) or people_visible(ctx.user))
        if restricted:
            people = [(roles, u) for roles, u in people if u['id'] == ctx.user['id']]
        people.sort(key=lambda p: (CASE_ROLES.index(p[0][0]) if p[0] else len(CASE_ROLES), p[1].get('name') or '', p[1]['id']))
        return {'project_id': ctx.project['id'], 'restricted': restricted,
                'people': [{'id': u['id'], 'name': u.get('name'), 'case_roles': roles,
                            'department': u.get('department')} for roles, u in people]}

    def participates(self, wid, user_id, project_id):
        with self.sessions() as db:
            return any(holds_task(t, user_id) for t in db.scalars(
                select(LocalTask).where(LocalTask.workspace_id == wid, LocalTask.project_id == project_id)))

    def personal_items(self, state, wid, user):
        from ..home_details import build_sop_home_task
        from ..source_case_policy import visible_project, local_planning
        if not user.get('active', True):
            return []
        projects = {p['id']: p for p in state.get('projects', [])
                    if visible_project(state, p) or local_planning(p)}
        with self.sessions() as db:
            tasks = [t for t in db.scalars(select(LocalTask).where(LocalTask.workspace_id == wid))
                     if t.project_id in projects and holds_task(t, user['id'])]
            links = list(db.scalars(select(TaskNodeLink).where(TaskNodeLink.workspace_id == wid,
                                   TaskNodeLink.task_id.in_([t.id for t in tasks])).order_by(TaskNodeLink.ordinal, TaskNodeLink.node_key)))
            return [build_sop_home_task(projects[t.project_id], t, [l for l in links if l.task_id == t.id],
                                       user, state.get('users', []), self.writes_enabled()) for t in tasks]

    def normalize(self, ctx, body, rows):
        fields(body, {'template_version_id', 'node_keys', 'row_keys', 'participant_bindings',
                      'applicability_decisions', 'exclusion_reasons'})
        keys = canonical_node_keys(row_keys(body.get('node_keys', list(NODE_MAP.values()))))
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
        foreign = next((key for key in selected if key not in eligible), None)
        require(foreign is None, 'row_not_importable', source_row_key=foreign)
        for key in selected:
            if eligible[key].snapshot['raw']['meegle_id'] in SUBCONTRACT:
                require(normalized_decisions.get(key, {}).get('value') == 'applicable', 'applicability_unresolved',
                        source_row_key=key)
        bindings = body.get('participant_bindings', {})
        fields(bindings, selected)
        bindings = {key: self.participants(ctx, value, source_row_key=key) for key, value in bindings.items()}
        exclusions = body.get('exclusion_reasons', {})
        fields(exclusions, eligible.keys() - set(selected))
        exclusions = {key: text(value, 1000, empty=False) for key, value in exclusions.items()}
        return {'template_version_id': body['template_version_id'], 'node_keys': [k for k in NODE_MAP.values() if k in keys],
                'row_keys': sorted(selected), 'participant_bindings': bindings,
                'applicability_decisions': normalized_decisions, 'exclusion_reasons': exclusions}

    def completion_summary(self, db, ctx, task):
        if task is None or task.state != Lifecycle.DONE:
            return None
        history = db.scalars(select(TaskEvent).where(TaskEvent.workspace_id == ctx.wid,
                                                      TaskEvent.task_id == task.id)
                             .order_by(TaskEvent.revision.desc(), TaskEvent.at.desc(), TaskEvent.id.desc()))
        completed = next((event for event in history if event.changes.get('to_state') == 'done'
                          or (event.kind == 'transition' and event.changes.get('action') == 'complete')), None)
        actor = completed.actor_id if completed else None
        return {'state': task.state.value, 'actor_id': actor,
                'actor_name': next((u['name'] for u in ctx.state.get('users', []) if u['id'] == actor), actor),
                'at': completed.at if completed else None,
                'evidence_basis': task.local.get('evidence_basis'),
                'evidence_refs': task.local.get('evidence_refs', [])}

    def plan(self, db, ctx, state, version, normalized, nodes=None):
        nodes = self.nodes(db, ctx, normalized['node_keys']) if nodes is None else nodes
        by_node = {n['node_key']: n['node_id'] for n in nodes}
        existing = {(t.template_family_id, t.source_row_key, t.instance_scope): t for t in self.tasks(db, ctx)}
        links = list(db.scalars(select(TaskNodeLink).where(TaskNodeLink.workspace_id == ctx.wid,
                                                          TaskNodeLink.project_id == ctx.project['id'])))
        linked = {(l.task_id, l.node_key, l.node_id) for l in links}
        outcomes = []
        for row in self.rows(db, version):
            source, proposal = row.snapshot, row.snapshot['proposed_import']
            mapped = set(proposal['target_branch_node_keys']) & by_node.keys()
            # Node-less routine and disabled rows belong only to a case-wide preview.
            if not mapped and (proposal['target_branch_node_keys'] or by_node.keys() != set(NODE_MAP.values())):
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
                        require(mapped <= original, 'template_mapping_conflict', 409, source_row_key=row.source_row_key)
                    missing = [{'task_id': old.id if old else None, 'node_key': key, 'node_id': by_node[key]}
                               for key in NODE_MAP.values() if key in mapped
                               and (not old or (old.id, key, by_node[key]) not in linked)]
                    if old and missing:
                        outcome = 'link_addition'
            outcomes.append({'source_row_key': row.source_row_key, 'title': source['raw']['title'],
                             'node_keys': [key for key in NODE_MAP.values() if key in mapped],
                             'disposition': row.disposition.value, 'selected': selected, 'outcome': outcome,
                             'existing_task_id': old.id if old else None,
                             'existing_state': old.state.value if old else None,
                             'existing_revision': old.revision if old else None,
                             'completion': self.completion_summary(db, ctx, old),
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
        position = self.position(db, ctx, self.facts(ctx))
        context = {'start_node': position['start_node'], 'identity_revision': state.identity_revision, 'checklist_revision': state.checklist_revision,
                   'nodes': nodes, 'template': self.version_json(version), 'input': normalized, 'outcomes': outcomes}
        return {**context, 'context_hash': digest(context), 'stage': position['stage'], 'outcomes': outcomes, 'unresolved_items': unresolved,
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
            self.check_policy_write(db, ctx, normalized['node_keys'])
            plan = self.plan(db, ctx, state, version, normalized)
            self.prune_previews(db, ctx.wid, ctx.user['id'])
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
            require(preview is not None and preview.project_id == ctx.project['id'] and 'kind' not in preview.data
                    and preview.actor_id == ctx.user['id'], 'preview_not_found', 404)
            require(preview.expires_at > self.clock(), 'preview_stale', 409)
            plan = preview.data
            version = self.version(db, ctx.wid, plan['input']['template_version_id'])
            normalized = self.normalize(ctx, plan['input'], self.rows(db, version))
            live = self.plan(db, ctx, state, version, normalized)
            require(live['context_hash'] == preview.context_hash, 'preview_stale', 409)
            return self._enroll_case(db, ctx, state, version, normalized, rid, fingerprint, plan)

    def commit_import(self, db, ctx, state, version, normalized, plan, live, rid, fingerprint):
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
                task_id = str(uuid5(NAMESPACE_URL, digest([ctx.wid, identity_key(ctx.project) or ctx.project['id'], version.family_id, key, row.snapshot['proposed_import']['instance_scope']])))
                # Never reuse a cleaned identity: its audit and stale requests survive.
                if db.scalar(select(TaskEvent.id).where(TaskEvent.workspace_id == ctx.wid,
                                                       TaskEvent.task_id == task_id,
                                                       TaskEvent.kind == 'test_cleaned').limit(1)):
                    task_id = str(uuid4())
                task = LocalTask(workspace_id=ctx.wid, id=task_id, project_id=ctx.project['id'],
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
                   'template_version_id': version.id, 'start_node': plan['start_node'], 'stage': live['stage'],
                   'replayed': False, 'created_task_ids': created,
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
        today = self.today().isoformat()
        return {'id': task.id, 'task_source': 'sop_local', 'project_id': task.project_id,
                'origin': {'template_family_id': task.template_family_id, 'source_row_key': task.source_row_key,
                           'instance_scope': task.instance_scope, 'imported_version_id': task.imported_version_id},
                'title': task.title, 'instructions': task.instructions if source or task.template_family_id == 'manual' else None,
                'participants': task.participants, 'applicability': task.applicability.value, 'state': task.state.value,
                'revision': task.revision, 'local': task.local,
                'result': task.local.get('result'),
                'completion_policy': completion_policy(task),
                'overdue': bool(task.local.get('due_date') and task.local['due_date'] < today
                                and task.applicability == Applicability.APPLICABLE
                                and task.state not in {Lifecycle.DONE, Lifecycle.ARCHIVED}),
                'nodes': [{'node_key': l.node_key, 'node_id': l.node_id, 'order': l.ordinal} for l in links],
                'node_keys': [key for key in NODE_MAP.values() if key in {l.node_key for l in links}],
                'instance_scope': task.instance_scope,
                'is_shared': task.instance_scope != 'case' or len({l.node_key for l in links}) > 1,
                'is_conditional': task.snapshot.get('row', {}).get('raw', {}).get('meegle_id') in CONDITIONAL,
                'source_snapshot': task.snapshot if source else None,
                'source_restriction': None if source else 'sop_task_read_source_required'}

    def task_views(self, db, ctx, tasks, links=None):
        """Tasks as the list shows them to this actor: suggestion and the actions the actor may take now."""
        if links is None:
            rows = list(db.scalars(select(TaskNodeLink).where(TaskNodeLink.workspace_id == ctx.wid,
                                                             TaskNodeLink.task_id.in_([t.id for t in tasks]))
                                   .order_by(TaskNodeLink.ordinal, TaskNodeLink.node_key)))
            links = {t.id: [l for l in rows if l.task_id == t.id] for t in tasks}
        facts = self.facts(ctx)
        dismissed = self.decided(db, ctx, 'suggestion_dismissed')
        source = explicitly_granted(ctx.user, 'sop_task_read_source')
        views = []
        sync = self.projection.statuses(db, ctx, tasks) if self.projection else {}
        from .models import CasePolicy
        policy = db.get(CasePolicy, (ctx.wid, ctx.project['id']))
        for task in tasks:
            found = None if ctx.assigned_only else suggestions.current(task, facts)
            found = None if found and (task.id, found['facts_hash']) in dismissed else found
            views.append({**self.task_json(task, links[task.id], source), 'suggestion': found,
                          'lark_sync': sync[task.id] if self.projection else {'state': '未啟用', 'synced_at': None, 'record_id': None},
                          'completion_blocked_reason': self.completion_blocker(ctx, task),
                          'allowed_actions': self.task_actions(ctx, task, found) if (not policy or policy.policy == 'managed' and {l.node_key for l in links[task.id]} <= set(policy.node_keys)) else []})
        return views

    def completion_blocker(self, ctx, task):
        if not self.writes_enabled():
            return 'import_unavailable'
        if not (can_manage(ctx) or task.participants.get('executor') == ctx.user['id']):
            return 'sop_import_forbidden'
        if task.state not in TRANSITIONS['complete'][0]:
            return 'invalid_transition'
        return self.completion_failure(task)

    def task_actions(self, ctx, task, suggestion):
        if not self.writes_enabled():
            return []
        manager = can_manage(ctx)
        executor = task.participants.get('executor') == ctx.user['id']
        actions = [action for action, (origins, target, _) in TRANSITIONS.items()
                   if (manager or executor and action != 'archive') and task.state in origins
                   and self.reachable(task, target)]
        if manager:
            if task.state == Lifecycle.ARCHIVED and (task.previous_state != Lifecycle.DONE or self.reachable(
                    task, Lifecycle.DONE, task.local.get('evidence_basis'))):
                actions.append('restore')
            if task.state not in {Lifecycle.DONE, Lifecycle.ARCHIVED}:
                actions += ['set_applicability', 'edit']
            if suggestion:
                actions += ['accept_suggestion', 'dismiss_suggestion']
        return actions

    def reachable(self, task, target, evidence=None):
        if target == Lifecycle.IN_PROGRESS:
            return task.applicability == Applicability.APPLICABLE
        return target != Lifecycle.DONE or self.completion_failure(task, evidence) is None

    def overview(self, ctx, node_key=None):
        authorize(ctx)
        require(node_key is None or node_key in NODE_MAP.values(), 'node_mapping_invalid')
        if self.projection:
            self.projection.request_reconcile(ctx.wid, ctx.project['id'], ctx.state)
        with self.sessions() as db:
            state = db.get(CaseState, (ctx.wid, ctx.project['id']))
            tasks = self.tasks(db, ctx)
            if ctx.assigned_only:
                tasks = [t for t in tasks if holds_task(t, ctx.user['id'])]
            links = list(db.scalars(select(TaskNodeLink).where(TaskNodeLink.workspace_id == ctx.wid,
                                                              TaskNodeLink.project_id == ctx.project['id'])
                                    .order_by(TaskNodeLink.ordinal, TaskNodeLink.node_key)))
            by_task = {t.id: [l for l in links if l.task_id == t.id] for t in tasks}
            selected = [t for t in tasks if node_key is None or any(l.node_key == node_key for l in by_task[t.id])]
            selected.sort(key=lambda t: (t.template_family_id == 'manual', min((l.ordinal for l in by_task[t.id]), default=0), t.id))
            enrollment = self.enrollment_status(db, ctx) if not ctx.assigned_only else None
            policy_write = not enrollment or enrollment['policy']['policy'] == 'managed' or enrollment['policy']['revision'] == 0 and not self.auto_active()
            return {'local_nodes': local_nodes.projection(self, db, ctx), 'sop_enrollment': enrollment, 'project_id': ctx.project['id'], 'task_source': 'sop_local',
                    'case': {k: ctx.project.get(k) for k in ('id', 'code', 'name')},
                    **({'start_node': next((key for key in NODE_MAP.values() if any(l.node_key == key for t in tasks for l in by_task[t.id])), 'sales'),
                        'stage': None} if ctx.assigned_only else self.position(db, ctx, self.facts(ctx))),
                    'checklist_revision': state.checklist_revision if state else 0,
                    'identity_revision': state.identity_revision if state else 0, 'scope': {'node_key': node_key},
                    'counts': self.counts(selected), 'case_counts': self.counts(tasks),
                    'node_counts': {key: self.counts([t for t in tasks if any(l.node_key == key for l in by_task[t.id])])
                                    for key in NODE_MAP.values()},
                    'tasks': self.task_views(db, ctx, selected, by_task),
                    'node_done': {} if ctx.assigned_only else {key: auto.public() for key, auto in self.node_done(ctx).items()},
                    'allowed_actions': {'import': can_manage(ctx) and self.writes_enabled() and policy_write,
                                        'manage': can_manage(ctx) and self.writes_enabled() and policy_write,
                                        'work': (can_manage(ctx) or any(t.participants.get('executor') == ctx.user['id'] for t in tasks)) and self.writes_enabled() and policy_write,
                                        'decide_suggestions': can_manage(ctx) and self.writes_enabled() and policy_write}}

    def with_sop_counts(self, wid, items):
        ids = sorted({pid for item in items for pid in item['project_ids']})
        with self.sessions() as db:
            tasks = list(db.scalars(select(LocalTask).where(LocalTask.workspace_id == wid,
                                                          LocalTask.project_id.in_(ids)))) if ids else []
        for item in items:
            mine = [t for t in tasks if t.project_id in item['project_ids']]
            item['sop_counts'] = self.counts(mine) if mine else None
        return items

    def quote_list(self, wid, state, amounts, *, stage='', q='', offset=0, limit=30):
        require(not stage or stage in quotes.STAGES, 'invalid_request')
        require(offset >= 0 and 1 <= limit <= quotes.MAX_PAGE_SIZE and len(q) <= 240, 'invalid_request')
        items = [item for item in quotes.register(state, today=self.today(), amounts=amounts)
                 if (not stage or item['stage'] == stage) and (not q or quotes.matches(item, q))]
        return {'total': len(items), 'offset': offset, 'limit': limit, 'amount_restricted': not amounts,
                'items': self.with_sop_counts(wid, items[offset:offset + limit])}

    def quote_detail(self, wid, state, amounts, quote_no):
        found = quotes.find(state, normalized_case(text(quote_no, 120, empty=False)), today=self.today(), amounts=amounts)
        require(found is not None, 'quote_not_found', 404)
        return self.with_sop_counts(wid, [found])[0]

    def default_version(self, db, wid):
        family = db.scalar(select(Family).where(Family.workspace_id == wid, Family.is_default.is_(True),
                                                Family.lifecycle == 'active'))
        require(family is not None, 'template_unavailable', 409)
        version = db.scalar(select(Version).where(Version.workspace_id == wid, Version.family_id == family.id,
                                                  Version.status == 'published')
                            .order_by(Version.published_at.desc(), Version.id.desc()).limit(1))
        require(version is not None, 'template_unavailable', 409)
        return version

    def local_form(self, body, users):
        fields(body, LOCAL_FORM | LOCAL_SELECTION)
        require('pm_id' in body and (body['pm_id'] is None or isinstance(body['pm_id'], str)), 'invalid_request')
        pm_id = '' if body['pm_id'] is None else identifier(body['pm_id'])
        local_case.require_pm(pm_id, users)
        import_tasks = body.get('import_tasks', True)
        require(isinstance(import_tasks, bool), 'invalid_request')
        selection = {k: body[k] for k in LOCAL_SELECTION if k in body}
        require(import_tasks or not selection, 'invalid_request')
        return {'name': text(body.get('name'), 300, empty=False).strip(), 'pm_id': pm_id,
                'client': text(body.get('client', ''), 300).strip(),
                'description': text(body.get('description', ''), 2000).strip(),
                'official_quote_no': local_case.official_number(body.get('official_quote_no')),
                'import_tasks': import_tasks, 'selection': selection}

    @staticmethod
    def case_json(project):
        return {k: project[k] for k in ('local_reference', 'official_quote_no', 'name', 'client', 'description', 'pm_id',
                                        'planning_origin', 'case_type')}

    def local_preview(self, wid, user, workspace, body):
        self.creatable()
        require(explicitly_granted(user, 'create_local_case'), 'local_case_forbidden', 403)
        state = workspace(wid)
        form = self.local_form(body, state['users'])
        local_case.require_unused(form['official_quote_no'], state)
        pid = uuid4().hex
        project = local_case.project(pid, form, user['id'], local_case.published_template(state), None)
        ctx = Context(wid, user, {'users': state['users']}, project, None)
        with self.sessions.begin() as db:
            self.lock_workspace_row(db, wid)
            self.prune_previews(db, wid, user['id'])
            normalized = plan = None
            if form['import_tasks']:
                require(explicitly_granted(user, 'sop_task_import'), 'sop_import_forbidden', 403)
                try:
                    self.writable()
                    version = (self.version(db, wid, form['selection']['template_version_id'])
                               if 'template_version_id' in form['selection'] else self.default_version(db, wid))
                    normalized = self.normalize(ctx, {**form['selection'], 'template_version_id': version.id}, self.rows(db, version))
                    blank = CaseState(workspace_id=wid, project_id=pid, checklist_revision=0, identity_revision=0)
                    plan = self.plan(db, ctx, blank, version, normalized,
                                     nodes=[{'node_key': k, 'node_id': f'{pid}-{k}'} for k in normalized['node_keys']])
                except Failure as exc:
                    if exc.code not in {'template_unavailable', 'import_unavailable'}:
                        raise
            case = {'project_id': pid, **self.case_json(project), 'nodes': [{'node_key': n['key'], 'node_id': n['id']}
                                                                          for n in project['nodes']]}
            ident, expires = str(uuid4()), self.clock() + 900
            db.add(Preview(workspace_id=wid, id=ident, project_id=pid, actor_id=user['id'], expires_at=expires,
                           context_hash=digest({'case': case, 'plan': plan and plan['context_hash']}),
                           data={'kind': 'local_case', 'form': form, 'case': case, 'import': normalized, 'plan': plan}))
        imported = None if plan is None else {**{k: v for k, v in plan.items() if k != 'input'}, 'selection': plan['input']}
        return {'draft_id': ident, 'expires_at': expires, 'case': case, 'import': imported}

    def local_create(self, wid, user, persist, body, refresh):
        fields(body, {'draft_id', 'request_id'})
        draft_id, rid = identifier(body.get('draft_id')), identifier(body.get('request_id'))
        require(explicitly_granted(user, 'create_local_case'), 'local_case_forbidden', 403)
        fingerprint = digest({'draft_id': draft_id, 'actor_id': user['id']})
        with self.sessions.begin() as db:
            self.lock_workspace_row(db, wid)
            fresh_wid, fresh_user = refresh()
            require(fresh_wid == wid and fresh_user['id'] == user['id'], 'local_case_forbidden', 403)
            user = fresh_user
            require(explicitly_granted(user, 'create_local_case'), 'local_case_forbidden', 403)
            run = db.get(LocalCaseRun, (wid, rid))
            if run:
                require(run.request_hash == fingerprint, 'idempotency_mismatch', 409)
                require(self.local_case_visible(db, wid, user, run.project_id), 'local_case_forbidden', 403)
                return {**run.receipt, 'replayed': True}
            self.creatable()
            draft = db.get(Preview, (wid, draft_id))
            require(draft is not None and draft.data.get('kind') == 'local_case' and draft.actor_id == user['id'],
                    'preview_not_found', 404)
            require(draft.expires_at > self.clock(), 'preview_stale', 409)
            form, pid = draft.data['form'], draft.project_id
            built = {}

            def build(state):
                local_case.require_pm(form['pm_id'], state['users'])
                local_case.require_unused(form['official_quote_no'], state)
                built.update(users=state['users'], project=local_case.project(
                    pid, form, user['id'], local_case.published_template(state), now()))
                return built['project']
            persist(db, wid, user['id'], build)
            ctx = Context(wid, user, {'users': built['users']}, built['project'], None)
            policy = self.save_policy(db, wid, built['project'],
                {'local_quote_creation': True, 'identity_verified': True, 'identity_key': identity_key(built['project'])},
                actor=user['id'])
            enrollment = self.queue_enrollment(db, wid, built['project'], policy, user['id'], policy.reason) if form['import_tasks'] else None
            if enrollment and draft.data['import'] is None:
                enrollment.last_error = 'import_unavailable' if not self.writes_enabled() else 'template_unavailable'
                enrollment.next_attempt_at = self.clock() + 120
            imported = None
            if draft.data['import'] is not None:
                self.writable()
                require(explicitly_granted(user, 'sop_task_import'), 'sop_import_forbidden', 403)
                ctx = Context(wid, user, {'users': built['users']}, built['project'], None)
                state = CaseState(workspace_id=wid, project_id=pid, checklist_revision=0, identity_revision=0, lock_counter=1)
                db.add(state)
                db.flush()
                version = self.version(db, wid, draft.data['import']['template_version_id'])
                normalized = self.normalize(ctx, draft.data['import'], self.rows(db, version))
                live = self.plan(db, ctx, state, version, normalized)
                require(live['context_hash'] == draft.data['plan']['context_hash'], 'preview_stale', 409)
                imported = self._enroll_case(db, ctx, state, version, normalized, rid, fingerprint, draft.data['plan'])
                enrollment.template_version_id = version.id
                enrollment.node_keys = normalized['node_keys']
                enrollment.status = 'succeeded'; enrollment.attempts = 1
                enrollment.receipt = {**imported, 'policy': policy.policy, 'policy_revision': policy.revision,
                                      'template_revision': version.revision, 'actor_id': user['id'], 'reason': policy.reason}
            receipt = {'request_id': rid, 'project_id': pid, **self.case_json(built['project']), 'replayed': False,
                       'import': imported}
            db.add(LocalCaseRun(workspace_id=wid, request_id=rid, id=str(uuid4()), actor_id=user['id'],
                                request_hash=fingerprint, project_id=pid, receipt=receipt))
            db.delete(draft)
            return receipt

    @staticmethod
    def local_case_visible(db, wid, user, project_id):
        row = db.get(BusinessRow, (wid, 'projects', project_id))
        return row is not None and local_viewer(user, row.data)

    def local_receipt(self, wid, user, request_id):
        with self.sessions() as db:
            run = db.get(LocalCaseRun, (wid, identifier(request_id)))
            require(run is not None and (run.actor_id == user['id'] or self.local_case_visible(db, wid, user, run.project_id)),
                    'run_not_found', 404)
            return run.receipt

    def manual(self, ctx, body):
        fields(body, {'title', 'instructions', 'node_keys', 'participants', 'due_date', 'is_test'})
        is_test = body.get('is_test', False)
        require(type(is_test) is bool, 'invalid_request')
        self.writable()
        with self.sessions.begin() as db:
            ctx, state = self.lock(db, ctx)
            if is_test:
                authorize_test_operator(ctx)
            keys = row_keys(body.get('node_keys', []))
            self.check_policy_write(db, ctx, keys)
            nodes = self.nodes(db, ctx, keys)
            due = body.get('due_date')
            require(due is None or isinstance(due, str), 'invalid_request')
            try:
                require(due is None or date.fromisoformat(due).isoformat() == due, 'invalid_request')
            except ValueError:
                require(False, 'invalid_request')
            task = LocalTask(workspace_id=ctx.wid, id=str(uuid4()), project_id=ctx.project['id'],
                             template_family_id='manual', source_row_key=str(uuid4()), instance_scope='case',
                             snapshot={'test_fixture': True} if is_test else {},
                             title=text(body.get('title'), 500, empty=False), instructions=text(body.get('instructions', '')),
                             participants=self.participants(ctx, body.get('participants', {})),
                             applicability=Applicability.APPLICABLE, state=Lifecycle.PENDING, revision=1,
                             local={'due_date': due, 'timezone': 'Asia/Taipei', 'date_status': 'manual' if due else 'unresolved',
                                    'completion_rule_status': 'no_typed_obligations', 'attestations': {},
                                    **({'is_test': True} if is_test else {})})
            db.add(task)
            db.flush()
            for n in nodes:
                db.add(TaskNodeLink(workspace_id=ctx.wid, task_id=task.id, project_id=ctx.project['id'],
                                    node_id=n['node_id'], node_key=n['node_key'], ordinal=10000))
            self.event(db, ctx, task, 'created', {'is_test': True} if is_test else {})
            state.checklist_revision += 1
            return {'task_id': task.id, 'revision': task.revision, 'checklist_revision': state.checklist_revision,
                    'task': self.task_views(db, ctx, [task])[0]}

    def tag_test(self, ctx, task_id, body):
        fields(body, {'expected_revision', 'is_test', 'reason'})
        require(type(body.get('expected_revision')) is int and type(body.get('is_test')) is bool, 'invalid_request')
        reason = text(body.get('reason'), 1000, empty=False)
        self.writable()
        with self.sessions.begin() as db:
            ctx, state = self.lock(db, ctx)
            authorize_test_operator(ctx)
            task = self.task(db, ctx, task_id)
            disposable(task)
            require(task.revision == body['expected_revision'], 'task_revision_conflict', 409)
            before = task.local.get('is_test') is True
            task.local = {**task.local, 'is_test': body['is_test']}
            task.revision += 1
            state.checklist_revision += 1
            self.event(db, ctx, task, 'test_tagged', {'before': before, 'is_test': body['is_test'], 'reason': reason})
            return {'task': self.task_views(db, ctx, [task])[0], 'checklist_revision': state.checklist_revision}

    def cleanup_test(self, ctx, task_id, body):
        fields(body, {'expected_revision', 'reason'})
        require(type(body.get('expected_revision')) is int, 'invalid_request')
        reason = text(body.get('reason'), 1000, empty=False)
        task_id = identifier(task_id)
        self.writable()
        with self.sessions.begin() as db:
            ctx, state = self.lock(db, ctx)
            authorize_test_operator(ctx)
            task = db.get(LocalTask, (ctx.wid, task_id))
            if task is None:
                cleaned = db.scalar(select(TaskEvent.id).where(TaskEvent.workspace_id == ctx.wid,
                                    TaskEvent.project_id == ctx.project['id'], TaskEvent.task_id == task_id,
                                    TaskEvent.kind == 'test_cleaned').limit(1))
                require(cleaned is not None, 'task_not_found', 404)
                return {'task_id': task_id, 'removed': False, 'replayed': True,
                        'checklist_revision': state.checklist_revision}
            task = self.task(db, ctx, task_id)
            disposable(task)
            require(task.local.get('is_test') is True, 'test_task_required', 409)
            require(task.revision == body['expected_revision'], 'task_revision_conflict', 409)
            require(audit_history_detached(db.connection()), 'cleanup_migration_required', 503)
            links = list(db.scalars(select(TaskNodeLink).where(TaskNodeLink.workspace_id == ctx.wid,
                                   TaskNodeLink.project_id == ctx.project['id'], TaskNodeLink.task_id == task_id)))
            self.event(db, ctx, task, 'test_cleaned', {'reason': reason, 'is_test': True,
                       'origin': {'template_family_id': task.template_family_id, 'source_row_key': task.source_row_key,
                                  'instance_scope': task.instance_scope, 'imported_version_id': task.imported_version_id},
                       'node_links': [{'node_id': link.node_id, 'node_key': link.node_key} for link in links]})
            db.flush()
            db.execute(delete(TaskNodeLink).where(TaskNodeLink.workspace_id == ctx.wid,
                       TaskNodeLink.project_id == ctx.project['id'], TaskNodeLink.task_id == task_id))
            # The sole physical removal path; ORM origin/history guards stay intact.
            db.execute(delete(LocalTask).where(LocalTask.workspace_id == ctx.wid,
                       LocalTask.project_id == ctx.project['id'], LocalTask.id == task_id))
            state.checklist_revision += 1
            return {'task_id': task_id, 'removed': True, 'replayed': False,
                    'checklist_revision': state.checklist_revision}

    @staticmethod
    def node_done(ctx):
        """Nodes the case's own data proves finished, by node key, with the rule that proved them. A node skipped by a valid waiver is not."""
        skipped = {n.get('key') for n in ctx.project.get('nodes', []) if valid_waiver(ctx.state, ctx.project, n)}
        return {key.value: auto for key, auto in evidence_for(ctx.project, ctx.state).items() if key.value not in skipped}

    def close_node(self, ctx, body):
        """Complete the open tasks of a node the data proves done; a task shared with an unproven node stays open."""
        fields(body, {'node_key'})
        node_key = body.get('node_key')
        require(node_key in NODE_MAP.values(), 'node_mapping_invalid')
        authorize(ctx, True)
        self.writable()
        with self.sessions.begin() as db:
            ctx, state = self.lock(db, ctx)
            self.check_policy_write(db, ctx, [node_key])
            proven = self.node_done(ctx)
            require(node_key in proven, 'node_not_done_by_data', 409)
            tasks = self.tasks(db, ctx)
            links = list(db.scalars(select(TaskNodeLink).where(TaskNodeLink.workspace_id == ctx.wid,
                                                              TaskNodeLink.project_id == ctx.project['id'])))
            nodes_of = {t.id: {l.node_key for l in links if l.task_id == t.id} for t in tasks}
            open_states = TRANSITIONS['complete'][0]
            closed, shared, unresolved = [], 0, 0
            for task in tasks:
                if node_key not in nodes_of[task.id] or task.state not in open_states:
                    continue
                if task.applicability != Applicability.APPLICABLE:
                    unresolved += 1
                elif not nodes_of[task.id] <= proven.keys():
                    shared += 1
                else:
                    rule = proven[node_key]
                    basis = {'rule_id': f'node-evidence:{rule.rule}', 'rule_revision': 1, 'tier': 'proof',
                             'actor_id': ctx.user['id'], 'at': self.clock(), 'confirmed': True, 'reason': rule.reason_zh}
                    origin = task.state
                    self.transition(task, {'action': 'complete'}, True, evidence=basis)
                    task.local = {**task.local, 'evidence_basis': basis}
                    task.revision += 1
                    self.event(db, ctx, task, 'node_closed', {'node_key': node_key, 'rule': rule.rule,
                                                             'reason': rule.reason_zh, 'from_state': origin.value,
                                                             'to_state': Lifecycle.DONE.value})
                    closed.append(task.id)
            if closed:
                state.checklist_revision += 1
            return {'project_id': ctx.project['id'], 'node_key': node_key, 'closed': len(closed),
                    'left_open': {'shared': shared, 'unresolved': unresolved}, 'rule': proven[node_key].public(),
                    'checklist_revision': state.checklist_revision}

    def mutate(self, ctx, task_id, body, *, transition=False):
        self.writable()
        fields(body, {'expected_revision', 'action', 'reason', 'applicability', 'result_note'} if transition else
               {'expected_revision', 'title', 'instructions', 'participants', 'due_date', 'reason'})
        require(type(body.get('expected_revision')) is int, 'invalid_request')
        with self.sessions.begin() as db:
            ctx, state = self.lock(db, ctx, manager=not transition)
            task = self.task(db, ctx, task_id)
            manager = can_manage(ctx)
            if transition:
                require(manager or task.participants.get('executor') == ctx.user['id'], 'sop_import_forbidden', 403)
            require(task.revision == body['expected_revision'], 'task_revision_conflict', 409)
            if transition:
                note = None
                if body.get('action') == 'complete':
                    self.completion(task)
                if body.get('action') == 'complete' and completion_policy(task) == 'result_note' and (task.template_family_id != 'manual' or 'result_note' in body):
                    note = body.get('result_note')
                    require(isinstance(note, str) and bool(note.strip()), 'result_note_required')
                    note = text(note.strip(), empty=False)
                self.transition(task, body, manager)
                if note is not None:
                    task.local = {**task.local, 'result': {'note': note, 'actor_id': ctx.user['id'],
                                  'actor_name': ctx.user.get('name') or ctx.user['id'], 'at': self.clock()}}
                elif body.get('action') == 'reopen':
                    task.local = {**task.local, 'result': None, 'attestations': {}}
            else:
                require(task.state not in {Lifecycle.DONE, Lifecycle.ARCHIVED}, 'task_reopen_required', 409)
                for key in ('title', 'instructions'):
                    if key in body:
                        setattr(task, key, text(body[key], 500 if key == 'title' else 20000, empty=key != 'title'))
                if 'participants' in body:
                    task.participants = self.participants(ctx, body['participants'])
                    task.local = {**task.local, 'attestations': {}, 'result': None, 'evidence_basis': None}
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
            self.event(db, ctx, task, 'transition' if transition else 'edited',
                       {**deepcopy(body), **({'result': task.local['result']} if transition and body.get('action') == 'complete' and task.local.get('result') else {})})
            return {'task_id': task.id, 'revision': task.revision, 'checklist_revision': state.checklist_revision,
                    'state': task.state.value, 'applicability': task.applicability.value,
                    'task': self.task_views(db, ctx, [task])[0]}

    @staticmethod
    def completion_failure(task, evidence=None):
        if task.applicability != Applicability.APPLICABLE:
            return 'applicability_unresolved'
        if evidence is None and completion_policy(task) == 'proof_required':
            return 'completion_evidence_missing'
        return None

    def completion(self, task, evidence=None):
        failure = self.completion_failure(task, evidence)
        require(failure is None, failure)

    def transition(self, task, body, manager, evidence=None):
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
                self.completion(task, task.local.get('evidence_basis'))
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
            self.completion(task, evidence)
        task.state = target

    def task(self, db, ctx, task_id):
        task = db.get(LocalTask, (ctx.wid, identifier(task_id)))
        require(task is not None and task.project_id == ctx.project['id'], 'task_not_found', 404)
        require(self.task_policy_writable(db, ctx, task.id), 'node_not_enrolled', 409)
        return task

    @staticmethod
    def decided(db, ctx, kind):
        return {(e.task_id, e.changes.get('facts_hash')): e
                for e in db.scalars(select(TaskEvent).where(TaskEvent.workspace_id == ctx.wid,
                                                            TaskEvent.project_id == ctx.project['id'],
                                                            TaskEvent.kind == kind).order_by(TaskEvent.at, TaskEvent.id))}

    @staticmethod
    def decision_json(task, changes, replayed):
        return {'task_id': task.id, 'revision': task.revision, 'state': task.state.value,
                'applicability': task.applicability.value, 'replayed': replayed,
                'suggestion': {k: changes[k] for k in ('rule_id', 'rule_revision', 'tier', 'suggested_state', 'facts_hash')}}

    def decide_suggestion(self, ctx, task_id, body):
        action = body.get('action')
        if action == 'dismiss_suggestion':
            return self.dismiss(ctx, task_id, body)
        require(action == 'accept_suggestion', 'invalid_request')
        fields(body, {'action', 'facts_hash', 'expected_revision', 'confirm', 'reason'})
        item = {'task_id': task_id, **{k: body[k] for k in ('facts_hash', 'expected_revision') if k in body}}
        result = self.accept(ctx, [item], body)
        return {**result['results'][0], 'checklist_revision': result['checklist_revision']}

    def accept_suggestions(self, ctx, body):
        fields(body, {'tasks', 'confirm', 'reason', 'confirmed_task_ids'})
        items = body.get('tasks')
        require(isinstance(items, list) and 0 < len(items) <= 62, 'invalid_request')
        for item in items:
            fields(item, {'task_id', 'facts_hash', 'expected_revision'})
        require(len({identifier(i.get('task_id')) for i in items}) == len(items), 'invalid_request')
        confirmed = row_keys(body.get('confirmed_task_ids', []))
        require(set(confirmed) <= {i['task_id'] for i in items}, 'invalid_request')
        return self.accept(ctx, items, {**body, 'confirmed_task_ids': confirmed})

    def accept(self, ctx, items, body):
        confirm = body.get('confirm', False)
        require(isinstance(confirm, bool), 'invalid_request')
        reason = text(body['reason'], 1000, empty=False) if 'reason' in body else None
        for item in items:
            text(item.get('facts_hash'), 64, empty=False)
        authorize(ctx, True)
        with self.sessions.begin() as db:
            ctx, state = self.lock(db, ctx)
            facts = self.facts(ctx)
            accepted = self.decided(db, ctx, 'suggestion_accepted')
            results = []
            for item in items:
                try:
                    results.append(self.accept_one(db, ctx, item, facts, accepted,
                                                   confirm and ('tasks' not in body or item['task_id'] in body['confirmed_task_ids']), reason))
                except Failure as exc:
                    raise Failure(exc.code, exc.status, task_id=item['task_id']) from None
            if any(not r['replayed'] for r in results):
                state.checklist_revision += 1
            views = self.task_views(db, ctx, [self.task(db, ctx, r['task_id']) for r in results])
            return {'project_id': ctx.project['id'], 'checklist_revision': state.checklist_revision,
                    'results': [{**r, 'task': view} for r, view in zip(results, views)]}

    def accept_one(self, db, ctx, item, facts, accepted, confirm, reason):
        task = self.task(db, ctx, item['task_id'])
        require((task.id, item['facts_hash']) not in self.decided(db, ctx, 'suggestion_dismissed'),
                'suggestion_dismissed', 409)
        previous = accepted.get((task.id, item['facts_hash']))
        if previous and task.state.value == previous.changes['to_state']:
            return self.decision_json(task, previous.changes, True)
        self.writable()
        found = suggestions.current(task, facts)
        require(found is not None and found['facts_hash'] == item['facts_hash'], 'suggestion_stale', 409)
        require(type(item.get('expected_revision')) is int, 'invalid_request')
        require(task.revision == item['expected_revision'], 'task_revision_conflict', 409)
        if found['tier'] == suggestions.Tier.INDICATOR.value:
            require(confirm and reason is not None, 'suggestion_confirmation_required')
        target = Lifecycle(found['suggested_state'])
        origin = task.state
        basis = {'rule_id': found['rule_id'], 'rule_revision': found['rule_revision'], 'tier': found['tier'],
                 'facts_hash': found['facts_hash'], 'actor_id': ctx.user['id'], 'at': self.clock(), 'confirmed': confirm}
        self.transition(task, {'action': suggestions.ACTIONS[target]}, True, evidence=basis)
        task.local = {**task.local, 'evidence_basis': basis}
        task.revision += 1
        changes = {**{k: v for k, v in found.items() if k != 'task_id'}, 'transition': suggestions.ACTIONS[target],
                   'from_state': origin.value, 'to_state': target.value, 'confirm': confirm, 'reason': reason}
        self.event(db, ctx, task, 'suggestion_accepted', changes)
        return self.decision_json(task, changes, False)

    def dismiss(self, ctx, task_id, body):
        fields(body, {'action', 'facts_hash', 'reason'})
        facts_hash = text(body.get('facts_hash'), 64, empty=False)
        reason = text(body['reason'], 1000, empty=False) if 'reason' in body else None
        authorize(ctx, True)
        with self.sessions.begin() as db:
            ctx, _ = self.lock(db, ctx)
            task = self.task(db, ctx, task_id)
            previous = self.decided(db, ctx, 'suggestion_dismissed').get((task.id, facts_hash))
            if previous:
                changes = previous.changes
            else:
                self.writable()
                found = suggestions.current(task, self.facts(ctx))
                require(found is not None and found['facts_hash'] == facts_hash, 'suggestion_stale', 409)
                changes = {**{k: v for k, v in found.items() if k != 'task_id'}, 'reason': reason}
                self.event(db, ctx, task, 'suggestion_dismissed', changes)
            return {**self.decision_json(task, changes, bool(previous)), 'dismissed': True,
                    'task': self.task_views(db, ctx, [task])[0]}
