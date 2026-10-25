"""Durable local enrollment. Every attempt is serialized with the existing workspace lock."""
from copy import deepcopy
from datetime import datetime, timezone
from sqlalchemy import select
from ..models import BusinessRow, WorkspaceRow
from .catalog import digest
from .domain import NODE_MAP, Failure, require
from .models import CasePolicy, SourceAdmission, Enrollment, CaseState
from .enrollment_policy import POLICY_VERSION, SYSTEM_ACTOR, decide_policy, identity_key, ambiguous, timestamp


class EnrollmentService:
    def auto_active(self):
        return self.auto_enabled() and timestamp(self.auto_since()) is not None

    def policy_json(self, row):
        return {'policy': row.policy, 'revision': row.revision, 'decided_by': row.decided_by,
                'decided_at': row.decided_at, 'reason': row.reason, 'facts': row.facts, 'node_keys': row.node_keys}

    def save_policy(self, db, wid, project, facts, *, actor=SYSTEM_ACTOR, nodes=None, reason=None, explicit=False):
        row = db.get(CasePolicy, (wid, project['id']))
        policy, explanation = decide_policy(facts, enabled=self.auto_enabled(), since=self.auto_since())
        if row and row.facts.get('identity_key') and row.facts['identity_key'] != facts.get('identity_key'):
            facts = {**facts, 'ambiguous': True}
            policy, explanation = decide_policy(facts)
        if row and not explicit:
            # An identity merge invalidates future automatic work without rewriting past tasks.
            if facts.get('ambiguous') and row.policy != 'needs_review':
                row.policy = 'needs_review'; row.revision += 1
                row.facts = facts; row.reason = explanation; row.decided_by = actor; row.decided_at = self.clock()
            return row
        if explicit:
            require(not facts.get('ambiguous') and facts.get('identity_verified'), 'case_identity_unresolved', 409)
            policy = 'managed'
        values = dict(policy=policy, revision=(row.revision + 1 if row else 1), decided_by=actor,
                      decided_at=self.clock(), reason=reason or explanation,
                      facts={**facts, 'policy_version': POLICY_VERSION},
                      node_keys=list(NODE_MAP.values()) if nodes is None else nodes)
        if row:
            for key, value in values.items():
                setattr(row, key, value)
        else:
            row = CasePolicy(workspace_id=wid, project_id=project['id'], **values); db.add(row)
        db.flush()
        return row

    def admit_snapshot(self, db, wid, state, previous, snapshot):
        """Called inside the source commit, with a complete authorized source snapshot."""
        before = {p['id']: p for p in previous}
        prior_identities = {identity_key(p) for p in previous} - {None}
        records = { '|'.join(r[k] for k in ('base_token','table_id','record_id')): r
                    for r in snapshot['records'] if r.get('kind') in {'confirmation','quote_confirmation','quote'} }
        baseline = state.get('source_case_baseline') or {}
        baseline_ids = set(baseline.get('record_ids', []))
        from ..sources import normalized_case
        baseline_codes = {normalized_case(code) for code in baseline.get('case_codes', [])}
        cutoff = timestamp(self.auto_since())
        present = {p['id'] for p in state.get('projects', [])}
        for old in previous:
            if old['id'] not in present:
                preserved = deepcopy(old)
                preserved['migration_review_required'] = True
                state['projects'].append(preserved)
        for project in state.get('projects', []):
            key = identity_key(project)
            admission = db.get(SourceAdmission, (wid, key)) if key else None
            verified = key in records
            if not admission and key and verified:
                from ..source_case_policy import _created_at
                created = _created_at(records[key])
                old_source = bool(cutoff and created and created < cutoff)
                facts = {'known_existing': project['id'] in before or key in prior_identities or old_source,
                         'source_baseline': key in baseline_ids or normalized_case(project.get('code')) in baseline_codes or any(rid in baseline_ids for rid in project.get('source_record_ids', [])),
                         'source_created_at': created.isoformat() if created else None,
                         'source_snapshot_at': snapshot['last_sync']}
                admission = SourceAdmission(workspace_id=wid, identity_key=key, project_id=project['id'],
                    first_seen_at=datetime.fromtimestamp(self.clock(), timezone.utc).isoformat(), facts=facts)
                db.add(admission); db.flush()
            facts = {**(admission.facts if admission else {}), 'identity_key': key,
                     'identity_verified': bool(key and (verified or admission)),
                     'first_seen_at': admission.first_seen_at if admission else None,
                     'ambiguous': ambiguous(project) or bool(admission and admission.project_id != project['id']),
                     'execution_assignment': deepcopy(project.get('execution_assignment'))}
            policy = self.save_policy(db, wid, project, facts)
            if project['id'] in before:
                prior = before[project['id']]
                allowed = set(policy.node_keys) if policy.policy == 'managed' else set()
                protected = {n['key']: n for n in prior['nodes'] if n['key'] not in allowed}
                project['nodes'] = [deepcopy(protected.get(n['key'], n)) for n in project['nodes']]
                if policy.policy != 'managed':
                    for field in ('status','execution_status','pm_id','admin_id','supervisor_id','started_at','completed_at'):
                        if field in prior:
                            project[field] = deepcopy(prior[field])
                        else:
                            project.pop(field, None)
            if project['id'] not in before:
                for node in project['nodes']:
                    node['tasks'] = []; node['sop_applicability_pending'] = []
            if policy.policy == 'managed' and policy.decided_by == SYSTEM_ACTOR:
                self.queue_enrollment(db, wid, project, policy, SYSTEM_ACTOR, policy.reason)

    def queue_enrollment(self, db, wid, project, policy, actor, reason, nodes=None, version=None):
        try:
            version = version or self.default_version(db, wid)
        except Failure as exc:
            if exc.code != 'template_unavailable':
                raise
        key = identity_key(project) or ('case:' + project['id'])
        ident = digest({'identity': key, 'template': version.id if version else 'awaiting-template'})
        if version:
            resolved = db.scalar(select(Enrollment).where(Enrollment.workspace_id == wid,
                Enrollment.identity_key == key, Enrollment.template_version_id == version.id,
                Enrollment.policy_revision == policy.revision))
            if resolved:
                return resolved
        row = db.get(Enrollment, (wid, ident))
        if row:
            return row
        row = Enrollment(workspace_id=wid, id=ident, project_id=project['id'], identity_key=key,
                         template_version_id=version.id if version else None, policy_revision=policy.revision,
                         node_keys=nodes if nodes is not None else policy.node_keys, actor_id=actor, reason=reason,
                         status='pending', attempts=0, created_at=self.clock(), updated_at=self.clock())
        db.add(row); db.flush()
        return row

    def enrollment_json(self, row):
        return {'id': row.id, 'project_id': row.project_id, 'status': row.status,
                'template_version_id': row.template_version_id, 'policy_revision': row.policy_revision,
                'attempts': row.attempts, 'last_error': row.last_error, 'next_attempt_at': row.next_attempt_at,
                'actor_id': row.actor_id, 'reason': row.reason, 'node_keys': row.node_keys,
                'receipt': row.receipt}

    def enrollment_status(self, db, ctx):
        policy = db.get(CasePolicy, (ctx.wid, ctx.project['id']))
        rows = list(db.scalars(select(Enrollment).where(Enrollment.workspace_id == ctx.wid,
            Enrollment.project_id == ctx.project['id']).order_by(Enrollment.created_at.desc(), Enrollment.id)))
        row = rows[0] if rows else None
        return {'policy': self.policy_json(policy) if policy else {'policy': 'legacy' if identity_key(ctx.project) else 'needs_review', 'revision': 0},
                'enrollment': self.enrollment_json(row) if row else None,
                'can_opt_in': self.manager_authorized(ctx) and bool(identity_key(ctx.project)) and not ambiguous(ctx.project) and (not policy or policy.policy == 'legacy'),
                'can_retry': self.manager_authorized(ctx),
                'nodes': [{'key': n['key'], 'name': n.get('name', n['key']), 'status': n.get('status', 'pending'),
                           'eligible': self.node_enrollable(n)} for n in ctx.project.get('nodes', [])]}

    @staticmethod
    def manager_authorized(ctx):
        from .service import can_manage
        return can_manage(ctx)

    @staticmethod
    def node_enrollable(node):
        return node.get('status', 'pending') not in {'done','completed','finished','approved','skipped','in_progress','in_review','running'} and not node.get('completed_at') and not node.get('started_at') and not node.get('source_declared_completed')

    def policy_write_reason(self, db, ctx, nodes=None):
        policy = db.get(CasePolicy, (ctx.wid, ctx.project['id']))
        if not ((policy is not None and policy.policy == 'managed') or (policy is None and not self.auto_active())):
            return 'legacy_case_requires_opt_in', '案件尚未啟用 SOP 管理'
        if policy and nodes and not set(nodes) <= set(policy.node_keys):
            return 'node_not_enrolled', '此節點尚未納入 SOP 管理'
        return None

    def check_policy_write(self, db, ctx, nodes=None):
        blocked = self.policy_write_reason(db, ctx, nodes)
        if blocked:
            require(False, blocked[0], 409, reason=blocked[1])

    def task_policy_writable(self, db, ctx, task_id):
        policy = db.get(CasePolicy, (ctx.wid, ctx.project['id']))
        if not policy:
            return True
        from .models import TaskNodeLink
        keys = set(db.scalars(select(TaskNodeLink.node_key).where(TaskNodeLink.workspace_id == ctx.wid,
                                                                  TaskNodeLink.task_id == task_id)))
        return policy.policy == 'managed' and keys <= set(policy.node_keys)

    def _enroll_case(self, db, ctx, state, version, normalized, rid, fingerprint, plan=None):
        """Single task-writing core, shared by confirmed manual import and enrollment."""
        self.writable()
        self.check_policy_write(db, ctx, normalized['node_keys'])
        live = self.plan(db, ctx, state, version, normalized)
        return self.commit_import(db, ctx, state, version, normalized, plan or live, live, rid, fingerprint)

    def enroll_case(self, wid, enrollment_id):
        from .service import Context
        with self.sessions.begin() as db:
            self.lock_workspace_row(db, wid)
            row = db.get(Enrollment, (wid, enrollment_id))
            require(row is not None, 'enrollment_not_found', 404)
            if row.status == 'succeeded':
                return self.enrollment_json(row)
            row.attempts += 1; row.updated_at = self.clock()
            try:
                with db.begin_nested():
                    project_row = db.get(BusinessRow, (wid, 'projects', row.project_id))
                    require(project_row is not None, 'case_not_found', 404)
                    project = deepcopy(project_row.data)
                    project['nodes'] = [deepcopy(n.data) for n in db.scalars(select(BusinessRow).where(
                        BusinessRow.workspace_id == wid, BusinessRow.kind == 'nodes', BusinessRow.parent_id == row.project_id))]
                    policy = db.get(CasePolicy, (wid, row.project_id))
                    require(policy and policy.policy == 'managed' and policy.revision == row.policy_revision,
                            'case_policy_changed', 409)
                    require(row.actor_id != SYSTEM_ACTOR or self.auto_active(), 'auto_enroll_disabled', 503)
                    self.writable()
                    version = self.version(db, wid, row.template_version_id) if row.template_version_id else self.default_version(db, wid)
                    ctx = Context(wid, {'id': row.actor_id, 'active': True}, {}, project, None)
                    keys = row.node_keys
                    if policy.decided_by != SYSTEM_ACTOR and not policy.facts.get('local_quote_creation'):
                        eligible = {n['key'] for n in project.get('nodes', []) if self.node_enrollable(n)}
                        require(set(keys) <= eligible, 'node_already_started_or_finished', 409)
                    self.ensure_case_state(db, ctx)
                    state = db.get(CaseState, (wid, row.project_id))
                    normalized = self.normalize(ctx, {'template_version_id': version.id, 'node_keys': keys}, self.rows(db, version))
                    receipt = self._enroll_case(db, ctx, state, version, normalized, 'enroll-' + row.id,
                                                digest({'enrollment': row.id}))
                    row.template_version_id = version.id
                    row.receipt = {**receipt, 'policy_revision': policy.revision, 'policy': policy.policy,
                                   'template_revision': version.revision, 'actor_id': row.actor_id, 'reason': row.reason,
                                   'enrollment_key': digest({'identity': row.identity_key, 'template': version.id})}
                    row.status = 'succeeded'; row.last_error = None; row.next_attempt_at = None
            except Exception as exc:
                code = exc.code if isinstance(exc, Failure) else type(exc).__name__
                row.status = 'pending' if code in {'template_unavailable','import_unavailable','auto_enroll_disabled'} else 'failed'
                row.last_error = code
                row.next_attempt_at = self.clock() + min(86400, 60 * 2 ** min(row.attempts, 10))
            db.flush()
            return self.enrollment_json(row)

    def ensure_case_state(self, db, ctx):
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        insert = sqlite_insert if db.bind.dialect.name == 'sqlite' else pg_insert
        db.execute(insert(CaseState).values(workspace_id=ctx.wid, project_id=ctx.project['id'],
            checklist_revision=0, identity_revision=0, lock_counter=0).on_conflict_do_nothing())

    def retry_enrollment(self, ctx, body):
        from .service import authorize, fields, identifier
        authorize(ctx, True)
        fields(body, {'enrollment_id'})
        ident = identifier(body.get('enrollment_id'))
        with self.sessions.begin() as db:
            ctx, _ = self.lock(db, ctx, enrollment=True)
            row = db.get(Enrollment, (ctx.wid, ident))
            require(row and row.project_id == ctx.project['id'], 'enrollment_not_found', 404)
        return self.enroll_case(ctx.wid, ident)

    def run_enrollments(self, wid, limit=20):
        with self.sessions() as db:
            ids = list(db.scalars(select(Enrollment.id).where(Enrollment.workspace_id == wid,
                Enrollment.status.in_(['pending','failed']),
                (Enrollment.next_attempt_at.is_(None) | (Enrollment.next_attempt_at <= self.clock())),
                Enrollment.attempts < 8).order_by(Enrollment.created_at).limit(limit)))
        for ident in ids:
            self.enroll_case(wid, ident)

    def opt_in(self, ctx, body):
        from .service import authorize, fields, canonical_node_keys, row_keys, text
        authorize(ctx, True)
        fields(body, {'node_keys','confirmed','reason'})
        require(body.get('confirmed') is True, 'confirmation_required', 422)
        reason = text(body.get('reason', '管理者確認套用至尚未開始的節點'), 2000, empty=False)
        with self.sessions.begin() as db:
            ctx, _ = self.lock(db, ctx, enrollment=True)
            require(not ambiguous(ctx.project), 'case_identity_unresolved', 409)
            eligible = [n['key'] for n in ctx.project.get('nodes', []) if self.node_enrollable(n)]
            keys = canonical_node_keys(row_keys(body.get('node_keys', eligible)))
            require(set(keys) <= set(eligible), 'node_already_started_or_finished', 409)
            old = db.get(CasePolicy, (ctx.wid, ctx.project['id']))
            require(not old or old.policy == 'legacy', 'case_already_managed', 409)
            key = identity_key(ctx.project)
            require(key, 'case_identity_unresolved', 409)
            policy = self.save_policy(db, ctx.wid, ctx.project,
                {**(old.facts if old else {}), 'identity_key': key, 'identity_verified': True, 'ambiguous': False},
                actor=ctx.user['id'], nodes=keys, reason=reason, explicit=True)
            row = self.queue_enrollment(db, ctx.wid, ctx.project, policy, ctx.user['id'], reason, keys)
            ident = row.id
        return self.enroll_case(ctx.wid, ident)

    def readiness(self, wid, user):
        require(user.get('active', True) and user.get('role') in {'manager','admin','pm'}, 'sop_import_forbidden', 403)
        from .service import Context, can_manage
        with self.sessions() as db:
            policies = {p.project_id: p for p in db.scalars(select(CasePolicy).where(CasePolicy.workspace_id == wid))}
            enrollments = list(db.scalars(select(Enrollment).where(Enrollment.workspace_id == wid).order_by(Enrollment.created_at.desc())))
            cases = list(db.scalars(select(BusinessRow).where(BusinessRow.workspace_id == wid, BusinessRow.kind == 'projects')))
            items = []
            for case in cases:
                ctx = Context(wid, user, {}, case.data, None)
                if not can_manage(ctx):
                    continue
                policy = policies.get(case.entity_id)
                items.append({'project_id': case.entity_id, 'code': case.data.get('code'), 'name': case.data.get('name'),
                    'policy': self.policy_json(policy) if policy else {'policy':'legacy' if identity_key(case.data) else 'needs_review','revision':0},
                    'enrollments': [self.enrollment_json(e) for e in enrollments if e.project_id == case.entity_id]})
            return {'items': items, 'auto_enroll_enabled': self.auto_active(), 'auto_enroll_since': self.auto_since()}
