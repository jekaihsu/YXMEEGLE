"""啟動 SOP over the node-assignment service: a read-only preview and a resumable run.

By default the run only creates the missing 節點指派 rows, as Lark's own button does; progress comes from the case's
data. With `seed_tasks` it also seeds one planned task per node, under the protections below.

A seed is identified by one Lark client token derived from (workspace, project, node, rule version, seed
sequence), never from content, actor, request or attempt. Every try at the same intended seed carries that token,
so Lark answers a repeat with the record it already made. The run decides by reading: the seeds it recognises are
the ledger's record ids and tasks still carrying the marker, and a node with a live seed is seeded.
"""
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace

from .. import audit
from .domain import NodeKey, TaskStatus
from .errors import Failure
from .evidence import signals
from .lark_table import TASK_FIELDS, Table, assignment_key, mismatches, parse_task, read_case, wire
from .operations import Plan, Situation, StartSopCommand
from .service import SYNC_FAILED, NodeAssignmentService, actor_for, confirmation_record, create_token, digest
from .start_sop import (
    BLOCKER_MESSAGES, SEED_NODES, SOP_RULE_VERSION, BlockerCode, Outcome, PlannedNode, WarningCode, observe, plan_start,
    preview_body, start_denial)

ACTION = 'start_sop'
LEDGER_FINGERPRINT = 'start-sop-seed-ledger'
RECEIPT_FINGERPRINT = 'start-sop-seed-receipt'
# Retrying the next node would fail the same way, so a run stops at the first of these.
SYSTEMIC = frozenset({'lark_permission', 'lark_unconfigured', 'lark_unavailable', 'rate_limited', 'roster_unavailable',
                      'writes_disabled', 'preview_stale'})
CONTENT_DIFFERS = 'content_differs'
STALE_MESSAGE = '計畫數量或期限已變更，請重新檢視預覽後再啟動'
UNKNOWN_MESSAGE = '上次建立結果不確定，請稍後再試'
RECORD_NOT_FOUND = 1254043


@dataclass(frozen=True)
class NodeResult:
    key: NodeKey
    node: Outcome
    task: Outcome
    failure: Failure | None = None
    # 'failed' only when the seed landed but the 進度/開始時間 mirror write did not.
    sync: str = 'ok'
    # `content_differs`: the seed is an earlier attempt that no longer matches the confirmed plan.
    # `duplicate_seed`: the node has more than one live seed, the extra record ids being `duplicates`.
    warning: str | None = None
    duplicates: tuple[str, ...] = ()

    def public(self):
        return {'key': self.key.value, 'node': self.node.value, 'task': self.task.value,
                'error': self.failure.code if self.failure else None, 'sync': self.sync,
                **({'warning': self.warning} if self.warning else {}),
                **({'duplicates': list(self.duplicates)} if self.duplicates else {})}

    @property
    def finished(self):
        return not self.failure and self.sync == 'ok'

    @classmethod
    def restore(cls, key: str, stored: dict):
        return cls(NodeKey(key), Outcome(stored['node']), Outcome(stored['task']), sync=stored.get('sync', 'ok'),
                   warning=stored.get('warning'), duplicates=tuple(stored.get('duplicates', ())))


def failed(key: NodeKey, failure: Failure, node: Outcome = Outcome.FAILED) -> NodeResult:
    return NodeResult(key, node, Outcome.FAILED, failure)


class SeedLedger:
    """The Lark record ids of the seed tasks this app created, in creation order, per workspace, project and node.

    The marker in 內容 is editable by anyone, the record id is not, so the id keeps a seed a seed.
    """

    def __init__(self, receipts):
        self.receipts, self._lock = receipts, threading.Lock()

    def _key(self, wid, project_id, key: NodeKey):
        return self.receipts.scoped('start-sop-seeds', wid, project_id, key.value)

    def ids(self, wid, project_id, key: NodeKey) -> tuple[str, ...]:
        stored = self.receipts.load(self._key(wid, project_id, key), LEDGER_FINGERPRINT)
        return tuple(stored['record_ids']) if stored else ()

    def add(self, wid, project_id, key: NodeKey, *record_ids):
        with self._lock:
            known = self.ids(wid, project_id, key)
            new = [r for r in dict.fromkeys(record_ids) if r not in known]
            if new:
                self.receipts.save(self._key(wid, project_id, key), LEDGER_FINGERPRINT,
                                   {'record_ids': [*known, *new]})


class StartSopRunner:
    def __init__(self, service: NodeAssignmentService):
        self.svc = service
        self.ledger = SeedLedger(service.receipts)

    def _code(self, ctx):
        try:
            return self.svc.open(ctx)
        except Failure as exc:
            if exc.code != 'not_found':
                raise
            return None

    def _denials(self, ctx, keys, roster):
        actor = actor_for(ctx.user, roster.value if roster else None)
        return {k: start_denial(actor, ctx.project, k) for k in keys}

    # Preview

    def preview(self, ctx, seed_tasks=False) -> dict:
        svc = self.svc
        for key in NodeKey:
            if reason := svc.enrollment_block(ctx, key):
                raise Failure('writes_disabled', reason)
        code = self._code(ctx)
        plan = plan_start(ctx.state, ctx.project, code)
        blockers = []
        if (reason := svc.write_block(ctx)):
            blockers.append((BlockerCode.WRITES_DISABLED, reason))
        if code is None:
            blockers.append((BlockerCode.NO_CONFIRMATION_CODE, BLOCKER_MESSAGES[BlockerCode.NO_CONFIRMATION_CODE]))
        if not plan.nodes:
            blockers.append((BlockerCode.NO_PLANNED_QUANTITY, BLOCKER_MESSAGES[BlockerCode.NO_PLANNED_QUANTITY]))
        states, can_start = None, False
        if code is not None:
            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    from contextvars import copy_context
                    roster_future = pool.submit(copy_context().run, svc._roster, fresh=False)
                    case_future = pool.submit(copy_context().run, svc._case, ctx, code)
                    roster, cached = roster_future.result(), case_future.result()
                skipped, evidence = svc.skipped(ctx), svc.evidence(ctx)
                states = {n.key: observe(cached.value, skipped, n.key, self.ledger.ids(ctx.wid, ctx.project['id'], n.key),
                                         evidence=evidence)
                          for n in plan.nodes}
                denials = self._denials(ctx, [n.key for n in plan.nodes] or SEED_NODES, roster)
                can_start = any(reason is None for reason in denials.values())
                if not can_start:
                    blockers.append((BlockerCode.FORBIDDEN, BLOCKER_MESSAGES[BlockerCode.FORBIDDEN]))
            except Failure as exc:
                blockers.append((BlockerCode.LARK_UNAVAILABLE, exc.message))
        return preview_body(plan, states, blockers, can_start, seed_tasks)

    # Run

    def run(self, ctx, request_id, command: StartSopCommand):
        """Returns (http_status, body, replayed)."""
        svc = self.svc
        code = self._code(ctx)
        if (reason := svc.write_block(ctx)):
            raise Failure('writes_disabled', reason)
        ctx = replace(ctx, user=ctx.authorize())
        plan = plan_start(ctx.state, ctx.project, code)
        receipt = svc.receipts.key(ctx.wid, ctx.user['id'], 'start-sop:' + request_id)
        fingerprint = digest({'action': ACTION, 'project_id': ctx.project['id'],
                              'body': {'preview_hash': command.preview_hash,
                                       **({'seed_tasks': True} if command.seed_tasks else {})}})
        stored = svc.receipts.load(receipt, fingerprint)
        if stored and stored['state'] == 'done':
            return stored['status'], stored['body'], True
        if code is None or not plan.nodes:
            missing = BlockerCode.NO_CONFIRMATION_CODE if code is None else BlockerCode.NO_PLANNED_QUANTITY
            raise Failure('nothing_to_start', BLOCKER_MESSAGES[missing],
                          blockers=[{'code': missing.value, 'message': BLOCKER_MESSAGES[missing]}])
        denials = self._denials(ctx, [n.key for n in plan.nodes], svc._roster(fresh=False))
        refused = [k for k, reason in denials.items() if reason]
        if refused:
            self._audit(ctx, request_id, 'denied', nodes=[k.value for k in refused])
        if len(refused) == len(denials):
            raise Failure('forbidden', denials[refused[0]])
        if plan.preview_hash != command.preview_hash:
            raise Failure('preview_stale', STALE_MESSAGE)
        finished = {k: NodeResult.restore(k, r) for k, r in ((stored or {}).get('results') or {}).items()}
        svc.receipts.save(receipt, fingerprint, {'state': 'pending', 'results': {k: r.public() for k, r in finished.items()}})

        results, halt = [], None
        for node in plan.nodes:
            if node.key.value in finished:
                results.append(finished[node.key.value])
            elif denials[node.key]:
                results.append(failed(node.key, Failure('forbidden', denials[node.key])))
            elif halt is not None:
                results.append(failed(node.key, halt))
            else:
                results.append(self._seed(ctx, request_id, node, code, command.seed_tasks))
                if results[-1].failure and results[-1].failure.code in SYSTEMIC:
                    halt = results[-1].failure
                elif results[-1].finished:
                    finished[node.key.value] = results[-1]
                    svc.receipts.save(receipt, fingerprint, {'state': 'pending',
                                                             'results': {k: r.public() for k, r in finished.items()}})
        failures = [r.failure for r in results if r.failure]
        started = any(Outcome.CREATED in (r.node, r.task) for r in results)
        if len(failures) == len(results) and not started:
            raise failures[0]
        body = {'started': started, 'complete': all(r.finished for r in results),
                'results': [r.public() for r in results], 'overview': self._overview(ctx, code)}
        if body['complete']:
            svc.receipts.save(receipt, fingerprint, {'state': 'done', 'status': 200, 'body': body})
        return 200, body, False

    def _audit(self, ctx, request_id, result, **details):
        svc = self.svc
        with svc.sessions.begin() as db:
            db.add(audit.record(svc.Audit, ctx.wid, ctx.user['id'], 'node_assignment.' + ACTION, result=result,
                                request_id=request_id, details={'project_id': ctx.project['id'], **details}))

    def _overview(self, ctx, code):
        svc = self.svc
        try:
            with svc.client() as client:
                svc.case_cache.put((ctx.wid, code), read_case(client, code))
        except Failure:
            pass
        return svc.overview(ctx)

    def _revalidated(self, ctx, node: PlannedNode, code):
        """The context and plan as they stand now. The confirmed preview only covers this node's reviewed content."""
        fresh = ctx.refresh()
        fresh_code = self._code(fresh)
        current = next((n for n in plan_start(fresh.state, fresh.project, fresh_code).nodes if n.key == node.key), None)
        if fresh_code != code or current is None or current.reviewed() != node.reviewed():
            raise Failure('preview_stale', STALE_MESSAGE)
        return fresh

    def _unlisted(self, client, snapshot, key: NodeKey, recorded):
        """Recorded seeds that exist but that the node's task link does not list yet, read by id."""
        row = snapshot.row(key)
        listed = {t.record_id for t in snapshot.node_tasks(key)}
        found = []
        for record_id in recorded:
            if row is None or record_id in listed:
                continue
            try:
                task = parse_task(client.get(Table.TASKS, record_id))
            except Failure as exc:
                if exc.extra.get('lark_code') != RECORD_NOT_FOUND:
                    raise
                continue
            if row.record_id in task.node_ids:
                found.append(task)
        return found

    def _mark(self, identity, state):
        """Record that the seed's create is `sent`, then `done`. A state never moves back, `at` is the first send."""
        receipts = self.svc.receipts
        stored = receipts.peek(identity) or {}
        at = stored.get('at') or self.svc.clock()
        if stored.get('state') != 'done':
            receipts.save(identity, RECEIPT_FINGERPRINT, {'state': state, 'at': at})
        return at

    def _node_only(self, ctx, client, request_id, code, key, snapshot, state, roster, user) -> NodeResult:
        """Create the node's row if Lark has none. A row Lark made is left exactly as it is. A row whose status the case
        evidence drives is written only where 狀態/進度/開始時間 differ, so a retry repairs a mirror that failed."""
        svc, akey = self.svc, assignment_key(code, key)
        if not state.will_create_node:
            if not (signal := signals(svc.evidence(ctx)).get(key)) or not signal.started:
                return NodeResult(key, Outcome.EXISTING, Outcome.SKIPPED)
            plan = Plan('node', snapshot.row(key).record_id, None, {})
            synced = svc._sync_node(client, ctx, snapshot, key, plan)
            if synced == 'unchanged':
                return NodeResult(key, Outcome.EXISTING, Outcome.SKIPPED)
            warnings = [SYNC_FAILED] if synced == 'failed' else []
            if synced == 'written':
                svc.case_cache.put((ctx.wid, code), read_case(client, code))
            self._audit(ctx, request_id, 'success', node=key.value, assignment_key=akey, record_id=plan.record_id,
                        changes=svc._changes(ctx, akey, plan), warnings=warnings)
            return NodeResult(key, Outcome.EXISTING, Outcome.SKIPPED, sync=sync_of(warnings))
        identity = svc.receipts.scoped('start-sop-seed', ctx.wid, ctx.project['id'], key.value, SOP_RULE_VERSION,
                                       str(len(state.seeds)))
        row, made = svc._node_row(client, Situation(
            key, code, actor_for(user, roster.value), roster.value, snapshot, svc.skipped(ctx), svc.now_ms(),
            confirmation_record(ctx.project, svc.config), svc.evidence(ctx)), identity)
        plan = Plan('node', row.record_id, None, {})
        _, warnings = svc._converge(ctx, client, code, key, plan)
        self._audit(ctx, request_id, 'success', node=key.value, assignment_key=akey, record_id=row.record_id,
                    changes=svc._changes(ctx, akey, plan), warnings=warnings)
        return NodeResult(key, Outcome.CREATED if made else Outcome.EXISTING, Outcome.SKIPPED, sync=sync_of(warnings))

    def _create(self, client, wid, pid, key: NodeKey, identity, fields):
        """Send the seed under the token of its identity and record the id Lark answers with. Returns the record."""
        at = self._mark(identity, 'sent')
        try:
            record_id = client.create(Table.TASKS, wire(TASK_FIELDS, fields), create_token(identity, key.value, 'task-create'))
        except Failure as exc:
            if exc.code != 'outcome_unknown':
                raise
            raise Failure('outcome_unknown', UNKNOWN_MESSAGE, first_sent_at=at) from None
        self.ledger.add(wid, pid, key, record_id)
        landed = client.get(Table.TASKS, record_id)
        self._mark(identity, 'done')
        return landed

    def _seed(self, ctx, request_id, node: PlannedNode, code, seed_tasks) -> NodeResult:
        svc, key = self.svc, node.key
        try:
            ctx = self._revalidated(ctx, node, code)
            with svc.locks.hold((ctx.wid, assignment_key(code, key)), svc.config.lock_timeout_seconds):
                return self._seed_locked(ctx, request_id, node, code, seed_tasks)
        except Failure as exc:
            return failed(key, exc)

    def _seed_locked(self, ctx, request_id, node: PlannedNode, code, seed_tasks) -> NodeResult:
        """One node under its lock. Nodes only: create the missing row. With seeds: keep the seed it has, else create the
        one its identity stands for."""
        svc, key, wid, pid = self.svc, node.key, ctx.wid, ctx.project['id']
        akey, node_row = assignment_key(code, key), Outcome.FAILED
        try:
            roster = svc._roster(fresh=True)

            def authorize(charge):
                user = ctx.authorize()
                if (reason := start_denial(actor_for(user, roster.value), ctx.project, key)):
                    raise Failure('forbidden', reason)
                if charge:
                    svc.rate.take(wid, user['id'])
                return user

            user = authorize(False)
            with svc.client(lambda: authorize(True)) as client:
                svc._ensure_schemas(client)
                for _ in range(2):  # a record Lark answers with may already be cancelled, which needs one more seed
                    snapshot = read_case(client, code)
                    recorded = self.ledger.ids(wid, pid, key)
                    state = observe(snapshot, svc.skipped(ctx), key, recorded,
                                    self._unlisted(client, snapshot, key, recorded), svc.evidence(ctx))
                    self.ledger.add(wid, pid, key, *state.seeds)
                    if not seed_tasks:
                        return self._node_only(ctx, client, request_id, code, key, snapshot, state, roster, user)
                    if state.live:
                        _, warnings = svc._converge(ctx, client, code, key, Plan('task_create', state.live[0], None, {}),
                                                    snapshot)
                        return NodeResult(key, Outcome.EXISTING, Outcome.EXISTING, sync=sync_of(warnings),
                                          warning=WarningCode.DUPLICATE_SEED.value if state.duplicates else None,
                                          duplicates=state.duplicates)
                    if not (state.will_create_node or state.will_create_task):
                        return NodeResult(key, Outcome.EXISTING, Outcome.SKIPPED)
                    identity = svc.receipts.scoped('start-sop-seed', wid, pid, key.value, SOP_RULE_VERSION,
                                                   str(len(state.seeds)))
                    row, made = svc._node_row(client, Situation(
                        key, code, actor_for(user, roster.value), roster.value, snapshot, svc.skipped(ctx), svc.now_ms(),
                        confirmation_record(ctx.project, svc.config), svc.evidence(ctx)), identity)
                    node_row = Outcome.CREATED if made or node_row is Outcome.CREATED else Outcome.EXISTING
                    fields = {**node.seed_fields, 'assignee': None, 'assigned_by': [user['id']],
                              'status': TaskStatus.TODO.value, 'node': [row.record_id]}
                    plan, task, differs = Plan('task_create', None, None, fields), Outcome.SKIPPED, False
                    if state.will_create_task:
                        landed = self._create(client, wid, pid, key, identity, fields)
                        if parse_task(landed).status is TaskStatus.CANCELLED:
                            continue
                        plan, differs = replace(plan, record_id=landed['record_id']), bool(
                            mismatches(TASK_FIELDS, wire(TASK_FIELDS, node.seed_fields), landed))
                        task = Outcome.EXISTING if differs else Outcome.CREATED
                    _, warnings = svc._converge(ctx, client, code, key, plan)
                    self._audit(ctx, request_id, 'success', node=key.value, assignment_key=akey, record_id=plan.record_id,
                                changes=svc._changes(ctx, akey, plan), warnings=warnings)
                    return NodeResult(key, node_row, task, sync=sync_of(warnings),
                                      warning=CONTENT_DIFFERS if differs else None)
                raise Failure('lark_error', '新建立的種子任務已被取消，請稍後再按一次')
        except Failure as exc:
            self._audit(ctx, request_id, 'denied' if exc.code == 'forbidden' else 'failed', node=key.value, code=exc.code)
            return failed(key, exc, node_row)


def sync_of(warnings) -> str:
    return 'failed' if SYNC_FAILED in warnings else 'ok'
