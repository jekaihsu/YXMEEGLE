"""啟動 SOP over the node-assignment service: a read-only preview and a resumable seeding run.

Each seed node is one `service.mutate` call under that node's lock, so it reuses
the fresh-read planning, duplicate protection, read-back and pending-receipt
reconciliation of every other write. The run itself holds a receipt that binds
the request_id to the reviewed preview hash.
"""
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace

from .. import audit
from .domain import Denied, NodeKey, TaskStatus
from .errors import Failure
from .lark_table import assignment_key, date_millis, read_case
from .operations import Plan, StartSopCommand
from .service import NodeAssignmentService, actor_for, digest
from .start_sop import (
    BLOCKER_MESSAGES, SEED_NODES, SOP_RULE_VERSION, BlockerCode, Outcome, PlannedNode, marker, observe, plan_start,
    preview_body, start_denial)

ACTION = 'start_sop'
LEDGER_FINGERPRINT = 'start-sop-seed-ledger'
# Retrying the next node would fail the same way, so a run stops at the first of these.
SYSTEMIC = frozenset({'lark_permission', 'lark_unconfigured', 'lark_unavailable', 'rate_limited', 'roster_unavailable',
                      'writes_disabled', 'preview_stale'})
STALE_MESSAGE = '計畫數量或期限已變更，請重新檢視預覽後再啟動'
KINDS = ('task_create', 'node')


@dataclass(frozen=True)
class NodeResult:
    key: NodeKey
    node: Outcome
    task: Outcome
    failure: Failure | None = None

    def public(self):
        return {'key': self.key.value, 'node': self.node.value, 'task': self.task.value,
                'error': self.failure.code if self.failure else None}

    @classmethod
    def restore(cls, key: str, stored: dict):
        return cls(NodeKey(key), Outcome(stored['node']), Outcome(stored['task']))


def failed(key: NodeKey, failure: Failure, node: Outcome = Outcome.FAILED) -> NodeResult:
    return NodeResult(key, node, Outcome.FAILED, failure)


def node_outcome(landed: list[Plan]) -> Outcome:
    """What a failed write already did to the node row, read from the plans it pinned before failing."""
    if not any(p.record_id or 'node' in p.changes for p in landed):
        return Outcome.FAILED
    return Outcome.CREATED if any(p.created_node for p in landed) else Outcome.EXISTING


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

    def preview(self, ctx) -> dict:
        svc = self.svc
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
                    roster_future = pool.submit(svc._roster, fresh=False)
                    case_future = pool.submit(svc._case, ctx, code)
                    roster, cached = roster_future.result(), case_future.result()
                skipped = svc.skipped(ctx)
                states = {n.key: observe(cached.value, skipped, n.key,
                                         frozenset(self.ledger.ids(ctx.wid, ctx.project['id'], n.key)))
                          for n in plan.nodes}
                denials = self._denials(ctx, [n.key for n in plan.nodes] or SEED_NODES, roster)
                can_start = any(reason is None for reason in denials.values())
                if not can_start:
                    blockers.append((BlockerCode.FORBIDDEN, BLOCKER_MESSAGES[BlockerCode.FORBIDDEN]))
            except Failure as exc:
                blockers.append((BlockerCode.LARK_UNAVAILABLE, exc.message))
        return preview_body(plan, states, blockers, can_start)

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
                              'body': {'preview_hash': command.preview_hash}})
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
            self._deny(ctx, request_id, refused)
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
                results.append(self._seed(ctx, request_id, node, code))
                if results[-1].failure and results[-1].failure.code in SYSTEMIC:
                    halt = results[-1].failure
                elif not results[-1].failure:
                    finished[node.key.value] = results[-1]
                    svc.receipts.save(receipt, fingerprint, {'state': 'pending',
                                                             'results': {k: r.public() for k, r in finished.items()}})
        failures = [r.failure for r in results if r.failure]
        started = any(Outcome.CREATED in (r.node, r.task) for r in results)
        if len(failures) == len(results) and not started:
            raise failures[0]
        body = {'started': started, 'complete': not failures,
                'results': [r.public() for r in results], 'overview': self._overview(ctx, code)}
        if not failures:
            svc.receipts.save(receipt, fingerprint, {'state': 'done', 'status': 200, 'body': body})
        return 200, body, False

    def _deny(self, ctx, request_id, keys):
        svc = self.svc
        with svc.sessions.begin() as db:
            db.add(audit.record(svc.Audit, ctx.wid, ctx.user['id'], 'node_assignment.' + ACTION, result='denied',
                                request_id=request_id, details={'project_id': ctx.project['id'],
                                                                'nodes': [k.value for k in keys]}))

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

    def _receipt_id(self, ctx, key: NodeKey, seq: int, kind: str):
        """Identity of one seed attempt: the work (which seed of which node), never the request or the person."""
        return self.svc.receipts.scoped('start-sop-node', ctx.wid, ctx.project['id'], key.value, SOP_RULE_VERSION,
                                        str(seq), kind)

    def _pending(self, ctx, key: NodeKey, seq: int):
        """An earlier attempt at this node's seed that is still unconfirmed, newest sequence first."""
        for number in range(seq, -1, -1):
            for kind in KINDS:
                rid = self._receipt_id(ctx, key, number, kind)
                stored = self.svc.receipts.peek(rid)
                if stored and stored['state'] == 'pending':
                    return rid, number, kind
        return None

    def _seed(self, ctx, request_id, node: PlannedNode, code) -> NodeResult:
        svc, key = self.svc, node.key
        try:
            ctx = self._revalidated(ctx, node, code)
            with svc.locks.hold(('start-sop', ctx.wid, assignment_key(code, key)), svc.config.lock_timeout_seconds):
                return self._seed_locked(ctx, request_id, node, code)
        except Failure as exc:
            return failed(key, exc)

    def _seed_locked(self, ctx, request_id, node: PlannedNode, code) -> NodeResult:
        """One node's seed under the run lock, so a second press observes what the first one left behind."""
        svc, key, wid, pid = self.svc, node.key, ctx.wid, ctx.project['id']
        with svc.client() as client:
            snapshot = read_case(client, code)
        carried = {t.record_id for t in snapshot.node_tasks(key) if marker(key) in t.detail}
        self.ledger.add(wid, pid, key, *sorted(carried))
        known = frozenset(self.ledger.ids(wid, pid, key)) | carried
        state = observe(snapshot, svc.skipped(ctx), key, known)
        seq = len(known)
        pending = self._pending(ctx, key, seq)
        if pending is None and not (state.will_create_node or state.will_create_task):
            return NodeResult(key, Outcome.EXISTING, Outcome.EXISTING if state.seed_task_exists else Outcome.SKIPPED)
        receipt_id, number, kind = pending or (
            self._receipt_id(ctx, key, seq, 'task_create' if state.will_create_task else 'node'), seq,
            'task_create' if state.will_create_task else 'node')
        observed, landed = {'state': state}, []

        def plan_fn(s, resumed):
            if (reason := start_denial(s.actor, ctx.project, key)):
                raise Denied(reason)
            current = observed['state'] = observe(s.snapshot, s.skipped, key, known)
            if current.will_create_task:
                if resumed is not None and resumed.kind == 'task_create':
                    return Plan('task_create', None, None, resumed.changes)
                return Plan('task_create', None, None, {
                    'title': node.title, 'detail': node.detail, 'assignee': None, 'assigned_by': [s.actor.open_id],
                    'department': node.department, 'deadline': date_millis(node.deadline) if node.deadline else None,
                    'status': TaskStatus.TODO.value})
            return Plan('node', None, None, {}) if current.will_create_node else None

        def finish(fin_ctx, fin_client, fin_code, fin_key, plan, _roster, fin_receipt, fingerprint, record):
            body = {'node': (Outcome.CREATED if plan.created_node else Outcome.EXISTING).value,
                    'task': (Outcome.CREATED if plan.kind == 'task_create' else Outcome.SKIPPED).value}
            if plan.kind == 'task_create':
                self.ledger.add(wid, pid, fin_key, plan.record_id)
            svc._converge(fin_ctx, fin_client, fin_code, fin_key, plan)
            svc.receipts.save(fin_receipt, fingerprint, {'state': 'done', 'status': 200, 'body': body})
            record('success', record_id=plan.record_id,
                   changes=svc._changes(fin_ctx, assignment_key(fin_code, fin_key), plan))
            return 200, body, False

        try:
            _, body, _ = svc.mutate(ctx, key, ACTION, f'start-sop:{request_id}:{key.value}',
                                    {'sop_rule_version': SOP_RULE_VERSION, 'sequence': number, 'kind': kind},
                                    plan_fn, finish=finish, landed=landed, receipt_id=receipt_id,
                                    charge_per_write=True)
        except Failure as exc:
            return failed(key, exc, node_outcome(landed))
        if body is None:
            final = observed['state']
            return NodeResult(key, Outcome.EXISTING, Outcome.EXISTING if final.seed_task_exists else Outcome.SKIPPED)
        return NodeResult(key, Outcome(body['node']), Outcome(body['task']))
