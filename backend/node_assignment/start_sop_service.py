"""啟動 SOP over the node-assignment service: a read-only preview and a resumable seeding run.

Each seed node is one `service.mutate` call under that node's lock, so it reuses
the fresh-read planning, duplicate protection, read-back and pending-receipt
reconciliation of every other write. The run itself holds a receipt that binds
the request_id to the reviewed preview hash.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace

from .. import audit
from .domain import Denied, NodeKey, TaskStatus
from .errors import Failure
from .lark_table import assignment_key, date_millis, read_case
from .operations import Plan, StartSopCommand
from .service import NodeAssignmentService, actor_for, digest
from .start_sop import (
    BLOCKER_MESSAGES, SEED_NODES, BlockerCode, Outcome, PlannedNode, observe, plan_start, preview_body,
    start_denial)

ACTION = 'start_sop'
# Retrying the next node would fail the same way, so a run stops at the first of these.
SYSTEMIC = frozenset({'lark_permission', 'lark_unconfigured', 'lark_unavailable', 'rate_limited', 'roster_unavailable',
                      'writes_disabled'})
STALE_MESSAGE = '計畫數量或期限已變更，請重新檢視預覽後再啟動'


@dataclass(frozen=True)
class NodeResult:
    key: NodeKey
    node: Outcome
    task: Outcome
    failure: Failure | None = None

    def public(self):
        return {'key': self.key.value, 'node': self.node.value, 'task': self.task.value,
                'error': self.failure.code if self.failure else None}


def failed(key: NodeKey, failure: Failure, node: Outcome = Outcome.FAILED) -> NodeResult:
    return NodeResult(key, node, Outcome.FAILED, failure)


def node_outcome(landed: list[Plan]) -> Outcome:
    """What a failed write already did to the node row, read from the plans it pinned before failing."""
    if not any(p.record_id or 'node' in p.changes for p in landed):
        return Outcome.FAILED
    return Outcome.CREATED if any(p.created_node for p in landed) else Outcome.EXISTING


class StartSopRunner:
    def __init__(self, service: NodeAssignmentService):
        self.svc = service

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
                states = {n.key: observe(cached.value, skipped, n.key) for n in plan.nodes}
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
        svc.receipts.save(receipt, fingerprint, {'state': 'pending'})

        results, halt = [], None
        for node in plan.nodes:
            if denials[node.key]:
                results.append(failed(node.key, Failure('forbidden', denials[node.key])))
            elif halt is not None:
                results.append(failed(node.key, halt))
            else:
                results.append(self._seed(ctx, request_id, node, command.preview_hash))
                if results[-1].failure and results[-1].failure.code in SYSTEMIC:
                    halt = results[-1].failure
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

    def _seed(self, ctx, request_id, node: PlannedNode, preview_hash) -> NodeResult:
        svc, key = self.svc, node.key
        observed, landed = {}, []

        def plan_fn(s, _resumed):
            if (reason := start_denial(s.actor, ctx.project, key)):
                raise Denied(reason)
            state = observed['state'] = observe(s.snapshot, s.skipped, key)
            if state.will_create_task:
                return Plan('task_create', None, None, {
                    'title': node.title, 'detail': node.detail, 'assignee': None, 'assigned_by': [s.actor.open_id],
                    'department': node.department, 'deadline': date_millis(node.deadline) if node.deadline else None,
                    'status': TaskStatus.TODO.value})
            return Plan('node', None, None, {}) if state.will_create_node else None

        def finish(fin_ctx, client, fin_code, fin_key, plan, _roster, fin_receipt, fingerprint, record):
            body = {'node': (Outcome.CREATED if plan.created_node else Outcome.EXISTING).value,
                    'task': (Outcome.CREATED if plan.kind == 'task_create' else Outcome.SKIPPED).value}
            svc._converge(fin_ctx, client, fin_code, fin_key, plan)
            svc.receipts.save(fin_receipt, fingerprint, {'state': 'done', 'status': 200, 'body': body})
            record('success', record_id=plan.record_id,
                   changes=svc._changes(fin_ctx, assignment_key(fin_code, fin_key), plan))
            return 200, body, False

        try:
            _, body, _ = svc.mutate(ctx, key, ACTION, f'start-sop:{request_id}:{key.value}',
                                    {'body': {'preview_hash': preview_hash}}, plan_fn, finish=finish, landed=landed)
        except Failure as exc:
            return failed(key, exc, node_outcome(landed))
        if body is None:
            return NodeResult(key, Outcome.EXISTING, Outcome.EXISTING if observed['state'].seed_task_exists else Outcome.SKIPPED)
        return NodeResult(key, Outcome(body['node']), Outcome(body['task']))
