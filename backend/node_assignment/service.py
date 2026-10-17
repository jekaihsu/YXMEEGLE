"""Reads and verified writes of node assignments, one node key at a time.

Every write runs under a per-指派鍵 lock, re-checks the session and the roster
inside the lock, plans against a fresh Lark read, records a pending receipt
before the first remote write, verifies by reading back, and leaves an audit row.
A replay with the same request_id returns the stored result or reconciles a
pending one by reading; an uncertain create is never blindly re-sent.
"""
import hashlib
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from collections import deque
from collections.abc import Callable
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from .. import audit
from ..business_policy import can_business_override, can_manage_roles
from ..sources import normalized_case
from .cache import Cached, StaleCache
from .config import NodeAssignmentConfig
from .domain import NODE_LABELS, Actor, Denied, IllegalTransition, NodeKey, derive_chain, task_counts
from .errors import Failure
from .lark_table import (
    NODE_FIELDS, TASK_FIELDS, BitableClient, CaseSnapshot, Table, assignment_key, check_schema, mismatches,
    parse_node, parse_task, read_case, wire)
from .operations import Plan, Situation, facts_of, mirror
from .roster import Roster, fetch_roster
from .views import case_view, node_detail

logger = logging.getLogger(__name__)
TAIPEI = timezone(timedelta(hours=8))
UNCERTAIN = frozenset({'outcome_unknown', 'readback_mismatch'})
SCHEMA_RECHECK_SECONDS = 600


@dataclass(frozen=True)
class Context:
    wid: str
    user: dict
    state: dict
    project: dict
    authorize: Callable[[], dict]
    # Re-reads the session user, the state and the project, for a run that spans several writes.
    refresh: Callable[[], 'Context'] | None = None


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def create_token(receipt, assignment, purpose):
    raw = hashlib.sha256(f'{receipt}\0{assignment}\0{purpose}'.encode()).digest()[:16]
    return str(UUID(bytes=raw, version=4))


def case_code(project):
    code = normalized_case(project.get('code'))
    if not code or '|' in code or len(code) > 120 or project.get('case_type') == 'intake':
        raise Failure('not_found', '此案件沒有工程確認單編號，無法使用節點指派')
    return code


def confirmation_record(project, config: NodeAssignmentConfig):
    found = set()
    for record in project.get('source_records') or []:
        if not isinstance(record, dict) or record.get('kind') != 'confirmation':
            continue
        url = urlsplit(str(record.get('url') or ''))
        query = parse_qs(url.query)
        rid = (query.get('record') or [''])[0]
        if url.path.rstrip('/').endswith('/' + config.base) and query.get('table') == [config.confirmation_table] \
                and rid.startswith('rec'):
            found.add(rid)
    return next(iter(found)) if len(found) == 1 else None


def actor_for(user, roster: Roster | None) -> Actor:
    return Actor(roster.person(user['id']) if roster else None, user['id'], can_business_override(user) or can_manage_roles(user))


class KeyedLocks:
    """The web service runs as one process (scripts/run_service.py), so a process lock serializes a key."""

    def __init__(self):
        self._locks, self._guard = {}, threading.Lock()

    @contextmanager
    def hold(self, key, timeout):
        with self._guard:
            lock = self._locks.setdefault(key, threading.Lock())
        if not lock.acquire(timeout=timeout):
            raise Failure('busy', '另一位同事正在更新此節點，請稍後再試')
        try:
            yield
        finally:
            lock.release()


class RateLimit:
    """Per-process sliding window, for the same single web process as KeyedLocks."""

    def __init__(self, per_actor=30, per_workspace=300, window=60, clock=time.monotonic):
        self.per_actor, self.per_workspace, self.window, self.clock = per_actor, per_workspace, window, clock
        self._events, self._lock = deque(), threading.Lock()

    def take(self, wid, actor_id):
        with self._lock:
            now = self.clock()
            while self._events and self._events[0][0] <= now - self.window:
                self._events.popleft()
            mine = sum(1 for _, w, a in self._events if w == wid and a == actor_id)
            company = sum(1 for _, w, _ in self._events if w == wid)
            if mine >= self.per_actor or company >= self.per_workspace:
                raise Failure('rate_limited', '節點指派操作過於頻繁，請一分鐘後再試')
            self._events.append((now, wid, actor_id))


class Receipts:
    def __init__(self, sessions, model):
        self.sessions, self.model = sessions, model

    @staticmethod
    def key(wid, actor_id, request_id):
        return 'node-assignment:' + hashlib.sha256(f'{wid}\0{actor_id}\0{request_id}'.encode()).hexdigest()

    @staticmethod
    def scoped(scope, *parts):
        """A key in its own namespace, for durable facts that are not tied to one request."""
        return f'{scope}:' + hashlib.sha256('\0'.join(parts).encode()).hexdigest()

    def load(self, key, fingerprint):
        with self.sessions() as db:
            row = db.get(self.model, key)
            if row is None:
                return None
            if row.fingerprint != fingerprint:
                raise Failure('idempotency_conflict', 'request_id 已用於不同操作，請產生新的 request_id')
            return deepcopy(row.result)

    def save(self, key, fingerprint, result):
        try:
            with self.sessions.begin() as db:
                row = db.get(self.model, key)
                if row is None:
                    db.add(self.model(id=key, fingerprint=fingerprint, result=result))
                elif row.fingerprint != fingerprint:
                    raise Failure('idempotency_conflict', 'request_id 已用於不同操作，請產生新的 request_id')
                else:
                    row.result = deepcopy(result)
        except IntegrityError:
            self.load(key, fingerprint)
            raise Failure('busy', '相同 request_id 正在處理中，請稍後再試') from None

    def drop(self, key):
        with self.sessions.begin() as db:
            row = db.get(self.model, key)
            if row is not None:
                db.delete(row)


class NodeAssignmentService:
    def __init__(self, cfg, *, sessions, receipt_model, audit_model, skipped_nodes, transport=None,
                 clock=time.time, client_options=None):
        self.cfg = cfg
        self.config = NodeAssignmentConfig.from_env(cfg)
        self.sessions, self.Audit = sessions, audit_model
        self.receipts = Receipts(sessions, receipt_model)
        self.skipped_nodes = skipped_nodes
        self.transport, self.clock = transport, clock
        self.client_options = client_options or {}
        self.case_cache = StaleCache(self.config.read_ttl_seconds, self.config.stale_max_seconds, clock)
        self.roster_cache = StaleCache(self.config.roster_ttl_seconds, self.config.stale_max_seconds, clock)
        self.locks, self.rate = KeyedLocks(), RateLimit()
        self._schema_checked = {}
        self._schema_lock = threading.Lock()

    # Policy

    def write_block(self, ctx: Context):
        if ctx.state.get('settings', {}).get('external_enabled') is not True:
            return '正式外部連線未啟用，節點指派暫不可修改'
        return None

    def open(self, ctx: Context, *, write=False):
        org = self.cfg.get('LARK_WORKER_ORGANIZATION', '')
        if not org or ctx.wid != 'lark-' + org or ctx.state.get('environment') != 'production':
            raise Failure('disabled', '節點指派僅限公司正式工作區')
        if not self.config.writable:
            raise Failure('lark_unconfigured', '節點指派資料表不在核定的回寫白名單')
        if self.cfg.get('LARK_WORKER_IDENTITY') != 'application' or not all(
                self.cfg.get(k) for k in ('LARK_APP_ID', 'LARK_APP_SECRET')):
            raise Failure('lark_unconfigured', '公司應用身分尚未設定，無法讀寫節點指派')
        if write and (reason := self.write_block(ctx)):
            raise Failure('writes_disabled', reason)
        return case_code(ctx.project)

    def skipped(self, ctx: Context):
        values = {k.value for k in NodeKey}
        return frozenset(NodeKey(n['key']) for n in ctx.project.get('nodes', [])
                         if n.get('key') in values and self.skipped_nodes(ctx.state, ctx.project, n))

    def now_ms(self):
        return int(self.clock() * 1000)

    def client(self, before_write=None):
        return BitableClient(self.cfg, self.config, self.transport, before_write=before_write, **self.client_options)

    # Reads

    def _roster(self, *, fresh, calls=None):
        caller = threading.get_ident()
        def load():
            with self.client() as client:
                try:
                    return fetch_roster(client, self._check_roster_schema)
                finally:
                    if calls is not None and threading.get_ident() == caller:
                        calls.append(client.calls)
        try:
            return self.roster_cache.get('roster', load, allow_stale=not fresh, revalidate=not fresh)
        except Failure as exc:
            if fresh:
                raise Failure('roster_unavailable', '無法確認最新人員名單，暫停節點指派修改', reason=exc.code) from None
            logger.warning('node_assignment roster unavailable code=%s', exc.code)
            return None

    def _case(self, ctx: Context, code, calls=None):
        caller = threading.get_ident()
        def load():
            with self.client() as client:
                try:
                    return read_case(client, code)
                finally:
                    if calls is not None and threading.get_ident() == caller:
                        calls.append(client.calls)
        return self.case_cache.get((ctx.wid, code), load, revalidate=True)

    def _envelope(self, ctx, cached, roster, body):
        block = self.write_block(ctx)
        return {'project_id': ctx.project['id'], **body, 'stale': cached.stale, 'stale_reason': cached.stale_reason,
                'fetched_at': datetime.fromtimestamp(cached.fetched_at, TAIPEI).isoformat(timespec='seconds'),
                'roster': {'available': roster is not None, 'stale': bool(roster is None or roster.stale)},
                'writes_enabled': block is None, 'writes_disabled_reason': block}

    def _check_roster_schema(self, client, table):
        with self._schema_lock:
            if self.clock() - self._schema_checked.get(table, float('-inf')) > SCHEMA_RECHECK_SECONDS:
                check_schema(client, table)
                self._schema_checked[table] = self.clock()

    def _read(self, ctx, key=None):
        started, calls = time.monotonic(), []
        cache_status = 'miss'
        try:
            code = self.open(ctx)
            with ThreadPoolExecutor(max_workers=2) as pool:
                roster_future = pool.submit(self._roster, fresh=False, calls=calls)
                case_future = pool.submit(self._case, ctx, code, calls)
                roster, cached = roster_future.result(), case_future.result()
            cache_status = 'stale' if cached.stale else ('miss' if calls else 'hit')
            people = roster.value if roster else None
            actor = actor_for(ctx.user, people)
            skipped, enabled, now = self.skipped(ctx), self.write_block(ctx) is None, self.now_ms()
            if key is not None:
                body = node_detail(cached.value, skipped, actor, people, key, enabled, now)
            else:
                _, body = case_view(cached.value, skipped, actor, enabled, now)
                body['node_details'] = {}
                for node_key in NodeKey:
                    detail = node_detail(cached.value, skipped, actor, people, node_key, enabled, now)
                    body['node_details'][node_key.value] = {k: detail[k] for k in ('tasks', 'assignable_people')}
            return self._envelope(ctx, cached, roster, body)
        finally:
            logger.info('node_assignment read %s ms=%d cache=%s lark_calls=%d',
                        'detail' if key else 'overview', (time.monotonic() - started) * 1000,
                        cache_status, sum(calls))

    def overview(self, ctx: Context):
        return self._read(ctx)

    def detail(self, ctx: Context, key: NodeKey):
        return self._read(ctx, key)

    # Writes

    def mutate(self, ctx: Context, key: NodeKey, action: str, request_id, payload, plan_fn, *, finish=None,
               landed=None):
        """plan_fn(situation, resumed_plan) -> Plan, or None when there is nothing to write (body is then None).

        `finish` replaces the default node-detail response. `landed`, when given, collects every plan pinned before
        a failure so the caller can tell what already reached Lark. Returns (http_status, body, replayed).
        """
        finish = finish or self._finish
        code = self.open(ctx, write=True)
        receipt = self.receipts.key(ctx.wid, ctx.user['id'], request_id)
        fingerprint = digest({'action': action, 'project_id': ctx.project['id'], 'node': key.value, **payload})
        akey = assignment_key(code, key)

        def record(result, **details):
            with self.sessions.begin() as db:
                db.add(audit.record(self.Audit, ctx.wid, ctx.user['id'], 'node_assignment.' + action, result=result,
                                    request_id=request_id, details={'project_id': ctx.project['id'], 'node': key.value,
                                                                    'assignment_key': akey, **details}))

        with self.locks.hold((ctx.wid, akey), self.config.lock_timeout_seconds):
            ctx = replace(ctx, user=ctx.authorize())
            stored = self.receipts.load(receipt, fingerprint)
            if stored and stored['state'] == 'done':
                return stored['status'], stored['body'], True
            roster = self._roster(fresh=True)
            situation = None
            planned = None
            write_attempts = 0

            def authorize_write():
                nonlocal ctx, write_attempts
                try:
                    fresh_user = ctx.authorize()
                    if (actor_for(ctx.user, roster.value).override and not actor_for(fresh_user, roster.value).override
                            or fresh_user.get('department') != ctx.user.get('department')):
                        raise Failure('forbidden', '操作權限已變更，請重新整理後再操作')
                    ctx = replace(ctx, user=fresh_user)
                except Failure as exc:
                    if exc.code == 'forbidden' and write_attempts:
                        raise Failure('forbidden', '操作權限已變更，部分寫入可能已完成；請以同一 request_id 重送以核對結果',
                                      writes_started=True) from None
                    raise
                if situation is not None:
                    fresh = replace(situation, actor=actor_for(ctx.user, roster.value))
                    try:
                        checked = plan_fn(fresh, resumed)
                    except Denied as exc:
                        raise Failure('forbidden', str(exc), writes_started=bool(write_attempts)) from None
                    if planned is not None and (checked is None or checked.changes != planned.changes):
                        raise Failure('forbidden', '操作權限已變更，請重新整理後再操作',
                                      writes_started=bool(write_attempts))
                self.rate.take(ctx.wid, ctx.user['id'])
                write_attempts += 1

            with self.client(before_write=authorize_write) as client:
                self._ensure_schemas(client)
                snapshot = read_case(client, code)
                resumed = None
                if stored:
                    outcome, previous = self._reconcile(client, snapshot, key, Plan.from_json(stored['plan']))
                    if outcome == 'applied':
                        return finish(ctx, client, code, key, previous, roster, receipt, fingerprint, record)
                    if outcome == 'conflict':
                        failure = Failure('revision_conflict', '先前送出的結果無法確認，且資料已被他人更新；請重新整理後再操作')
                        self.receipts.save(receipt, fingerprint, {'state': 'done', 'status': failure.status,
                                                                  'body': failure.body()})
                        record('failed', code=failure.code)
                        raise failure
                    resumed = previous
                ctx = replace(ctx, user=ctx.authorize())
                situation = Situation(key, code, actor_for(ctx.user, roster.value), roster.value, snapshot, self.skipped(ctx),
                                      self.now_ms(), confirmation_record(ctx.project, self.config))
                try:
                    plan = plan_fn(situation, resumed)
                    if plan is None:
                        if stored:
                            self.receipts.drop(receipt)
                        return 200, None, False
                    planned = plan
                    if plan.kind == 'task_create':
                        plan = replace(plan, client_token=resumed.client_token if resumed else create_token(receipt, akey, 'task-create'),
                            pre_create_task_ids=resumed.pre_create_task_ids if resumed else None)
                except Denied as exc:
                    record('denied', reason=str(exc))
                    raise Failure('forbidden', str(exc)) from None
                except IllegalTransition as exc:
                    raise Failure('illegal_transition', str(exc)) from None
                self.receipts.save(receipt, fingerprint, {'state': 'pending', 'plan': plan.to_json()})
                pinned = landed if landed is not None else []
                try:
                    plan = self._execute(client, situation, plan, receipt, fingerprint, pinned)
                except Failure as exc:
                    # Preserve pinned writes unless task creation has not yet been attempted.
                    # Without a baseline, execution has not reached the task-create call.
                    before_task_create = plan.kind == 'task_create' and all(
                        saved.pre_create_task_ids is None for saved in pinned)
                    if exc.code not in UNCERTAIN and (not pinned or before_task_create) and not (
                            exc.code == 'forbidden' and write_attempts):
                        self.receipts.drop(receipt)
                    record('failed', code=exc.code, changes=self._changes(ctx, akey, plan))
                    raise
                return finish(ctx, client, code, key, plan, roster, receipt, fingerprint, record)

    def _ensure_schemas(self, client):
        for table in (Table.NODES, Table.TASKS):
            if self.clock() - self._schema_checked.get(table, float('-inf')) > SCHEMA_RECHECK_SECONDS:
                check_schema(client, table)
                self._schema_checked[table] = self.clock()

    def _rows_for(self, client, akey):
        rows = [parse_node(r) for r in client.search(
            Table.NODES, [{'field_name': NODE_FIELDS['assignment_key'][0], 'operator': 'is', 'value': [akey]}])]
        if any(r.assignment_key != akey for r in rows):
            raise Failure('lark_error', 'Lark 搜尋結果不符篩選條件；停止寫入')
        if len(rows) > 1:
            raise Failure('duplicate_assignment_key', f'「{akey}」在 Lark 有重複列，請管理員先合併',
                          record_ids=[r.record_id for r in rows])
        return rows

    def _node_row(self, client, s: Situation, receipt):
        """Search first, create once, then search again so a racing duplicate is reported, not picked.

        Returns the row and whether this request issued the create.
        """
        row = s.snapshot.row(s.key)
        if row is not None:
            return row, False
        akey = assignment_key(s.code, s.key)
        found = self._rows_for(client, akey)
        if found:
            return found[0], False
        status = derive_chain(facts_of(s.snapshot, s.skipped))[s.key]
        initial = {'assignment_key': akey, 'code': s.code, 'node': NODE_LABELS[s.key], 'status': status.value}
        if s.confirmation_record:
            initial['confirmation'] = [s.confirmation_record]
        try:
            client.create(Table.NODES, wire(NODE_FIELDS, initial), create_token(receipt, akey, 'node-create'))
        except Failure as exc:
            if exc.code != 'outcome_unknown':
                raise
        found = self._rows_for(client, akey)
        if not found:
            raise Failure('outcome_unknown', '節點指派列建立結果未知；請以同一 request_id 重送以核對結果')
        return found[0], True

    def _verify(self, client, table, spec, record_id, fields):
        wrong = mismatches(spec, fields, client.get(table, record_id))
        if wrong:
            raise Failure('readback_mismatch', '寫入後讀回內容不一致，可能有人同時修改；請重新整理核對', fields=wrong)

    def _execute(self, client, s: Situation, plan: Plan, receipt, fingerprint, pinned):
        def pin(updated):
            self.receipts.save(receipt, fingerprint, {'state': 'pending', 'plan': updated.to_json()})
            pinned.append(updated)
            return updated

        if plan.kind == 'node' and plan.record_id is None:
            row, created = self._node_row(client, s, receipt)
            plan = pin(replace(plan, record_id=row.record_id, base_revision=row.revision, created_node=created))
        if plan.kind == 'task_create':
            if 'node' not in plan.changes:
                row, created = self._node_row(client, s, receipt)
                plan = pin(replace(plan, changes={**plan.changes, 'node': [row.record_id]}, created_node=created))
            if plan.pre_create_task_ids is None:
                row = client.get(Table.NODES, plan.changes['node'][0])
                plan = pin(replace(plan, pre_create_task_ids=parse_node(row).task_ids))
            fields = wire(TASK_FIELDS, plan.changes)
            plan = pin(replace(plan, record_id=client.create(Table.TASKS, fields, plan.client_token)))
            self._verify(client, Table.TASKS, TASK_FIELDS, plan.record_id, fields)
            return plan
        table, spec = (Table.NODES, NODE_FIELDS) if plan.kind == 'node' else (Table.TASKS, TASK_FIELDS)
        if plan.changes:
            fields = wire(spec, plan.changes)
            client.update(table, plan.record_id, fields)
            self._verify(client, table, spec, plan.record_id, fields)
        return plan

    def _reconcile(self, client, snapshot: CaseSnapshot, key, plan: Plan):
        """Read-only: did a pending write land, provably not land, or is it now unknowable?"""
        if plan.kind == 'task_create':
            fields = wire(TASK_FIELDS, plan.changes)
            if plan.record_id:
                landed = not mismatches(TASK_FIELDS, fields, client.get(Table.TASKS, plan.record_id))
                return ('applied' if landed else 'conflict'), plan
            row = snapshot.row(key)
            if row is None or 'node' not in plan.changes:
                return 'not_applied', plan
            if plan.pre_create_task_ids is None:
                raise Failure('outcome_unknown', '先前任務建立結果無法安全核對；請重新整理確認')
            # Identical older tasks cannot be evidence that this request landed.
            new_ids = [rid for rid in row.task_ids if rid not in plan.pre_create_task_ids]
            matches = [r for r in client.batch_get(Table.TASKS, new_ids)
                       if not mismatches(TASK_FIELDS, fields, r)] if new_ids else []
            if len(matches) > 1:
                return 'conflict', plan
            if matches:
                return 'applied', replace(plan, record_id=matches[0]['record_id'])
            return 'not_applied', plan
        table, spec, parse = ((Table.NODES, NODE_FIELDS, parse_node) if plan.kind == 'node'
                              else (Table.TASKS, TASK_FIELDS, parse_task))
        record_id = plan.record_id
        if record_id is None:
            row = snapshot.row(key)
            if row is None:
                return 'not_applied', plan
            record_id = row.record_id
        current = client.get(table, record_id)
        if not mismatches(spec, wire(spec, plan.changes), current):
            return 'applied', replace(plan, record_id=record_id)
        return ('not_applied' if parse(current).revision == plan.base_revision else 'conflict'), plan

    def _sync_node(self, client, ctx, snapshot: CaseSnapshot, key, plan: Plan):
        """Converge Lark 狀態/進度/開始時間 with the derived status; a rework task clears a rejection."""
        row = snapshot.row(key)
        if row is None:
            return 'unchanged'
        facts = facts_of(snapshot, self.skipped(ctx))
        clear = plan.kind == 'task_update' and plan.changes.get('status') == '已完成' and row.rejected
        if clear:
            facts[key] = replace(facts[key], rejected=False)
        status = derive_chain(facts)[key]
        wanted = mirror(row, status, task_counts(facts[key].tasks), self.now_ms())
        if clear:
            wanted['reject_reason'] = None
        fields = wire(NODE_FIELDS, wanted)
        try:
            names = mismatches(NODE_FIELDS, fields, client.get(Table.NODES, row.record_id))
            if not names:
                return 'unchanged'
            fields = {name: fields[name] for name in names}
            client.update(Table.NODES, row.record_id, fields)
            self._verify(client, Table.NODES, NODE_FIELDS, row.record_id, fields)
            return 'written'
        except Failure as exc:
            if exc.code == 'forbidden':
                raise
            logger.warning('node_assignment status sync failed code=%s', exc.code)
            return 'failed'

    def _changes(self, ctx, akey, plan: Plan):
        kind = 'node_assignment' if plan.kind == 'node' else 'node_task'
        return [{'kind': kind, 'id': plan.record_id or akey, 'project_id': ctx.project['id'],
                 'before': plan.before, 'after': plan.changes}]

    def _converge(self, ctx, client, code, key, plan: Plan):
        """Read the case back, mirror the derived status onto the node row, and refresh the cache."""
        warnings = []
        snapshot = read_case(client, code)
        synced = self._sync_node(client, ctx, snapshot, key, plan)
        if synced == 'failed':
            warnings.append('node_status_sync_failed')
        elif synced == 'written':
            snapshot = read_case(client, code)
        self.case_cache.put((ctx.wid, code), snapshot)
        return snapshot, warnings

    def _finish(self, ctx, client, code, key, plan: Plan, roster: Cached, receipt, fingerprint, record):
        snapshot, warnings = self._converge(ctx, client, code, key, plan)
        warnings = list(plan.warnings) + warnings
        body = node_detail(snapshot, self.skipped(ctx), actor_for(ctx.user, roster.value), roster.value, key,
                           self.write_block(ctx) is None, self.now_ms())
        body['warnings'] += warnings
        body = {**self._envelope(ctx, Cached(snapshot, False, self.clock()), roster, body), 'record_id': plan.record_id}
        self.receipts.save(receipt, fingerprint, {'state': 'done', 'status': 200, 'body': body})
        record('success', record_id=plan.record_id, changes=self._changes(ctx, assignment_key(code, key), plan),
               warnings=warnings)
        return 200, body, False
