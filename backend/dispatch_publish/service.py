"""Dispatch publish orchestration: preview, approvals, commit, reconcile, drafts and the PM work queue.

A commit verifies the stored preview against fresh sources, persists the command as pending together with
its reservations, then writes 任務 once and reports success only after the read-back matches.
"""
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import cache

from ..dispatch_board.config import PUBLISH_TABLES
from ..dispatch_board.domain import resource_state
from ..dispatch_board.lark_table import DispatchReader, read_source
from ..node_assignment.cache import StaleCache, permission_failure
from ..node_assignment.config import NodeAssignmentConfig
from ..node_assignment.errors import Failure
from ..remote_policy import formal_write_allowed
from ..sources import link_ids, text
from .config import DispatchPublishConfig, Seat
from .domain import (
    ANY_DEPARTMENT, COMMAND_ID, COMMAND_LABEL, COMMAND_PLANNING, DRAFT_ID, CommandResult, Decision, Directory,
    PlanningStatus, Refusal, Sources, Viewer, assess, build_work, changed, check_draft, decision_refusal,
    department_problem, from_millis, millis, mismatches, parse_proposal, proposal_hash, resolve_seats, seat_board,
    snapshot, task_fields, task_interval, task_row, task_users)
from .lark_task import TaskTable
from .store import DispatchStore, duplicate

logger = logging.getLogger(__name__)
KEYS = ('schedule', 'tasks', 'people', 'accounts', 'instruments', 'vehicles', 'cases', 'nodes')
WORK_KEYS = ('tasks', 'nodes', 'people', 'accounts', 'instruments', 'vehicles', 'cases')
_work_reads = ThreadPoolExecutor(max_workers=3, thread_name_prefix='dispatch-work')
SEARCH_RETRY_SECONDS = 1
FORM_FIELDS = [
    ('title', '標題', True), ('content', '內容', True), ('case_ref', '工程確認單', True), ('project_ref', '專案編號', True),
    ('phase', '任務階段', True), ('kind', '任務種類', True), ('package_id', '工作包編號', True),
    ('parent_task_ref', '父義務', True), ('primary_owner', '負責人', True), ('crew', '組員', True),
    ('start', '預定開始', True), ('end', '預定結束', True), ('est_person_hours', '預估人時', True),
    ('instruments', '使用儀器', True), ('vehicles', '使用車輛', True), ('department', '部門', True),
    ('deadline', '截止日', True), ('scope_version', '範圍版本', False), ('rule_version', '規則版本', False),
    ('evidence_version', '證據版本', False), ('planning_status', '排程狀態', False), ('revision', '排程版本', False),
    ('command_id', '命令編號', False), ('readback_at', '讀回時間', False), ('acceptance_status', '成果接受狀態', False),
    ('acceptance_summary', '接受摘要', False),
]


@dataclass(frozen=True)
class Context:
    wid: str
    user: dict
    workspace: dict
    can_dispatch: bool
    # refresh(need) -> Context re-reads the session and workspace, or refuses; see DispatchPublishService.revalidated.
    refresh: object = field(default=None, compare=False, repr=False)

    @property
    def actor(self):
        return self.user['id']

    @property
    def viewer(self):
        return Viewer(self.actor, self.can_dispatch, self.user.get('role') == 'manager')


def _iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec='seconds')


class DispatchPublishService:
    def __init__(self, cfg, *, sessions, audit_model, transport=None, client_options=None, clock=time.time,
                 sleep=time.sleep, reader=None):
        self.cfg = dict(cfg)
        self.config = DispatchPublishConfig.from_env(cfg)
        self.clock, self.sleep = clock, sleep
        self.store = DispatchStore(sessions, audit_model, clock)
        self.reader = reader or DispatchReader(cfg, transport=transport, client_options=client_options)
        self.tasks = TaskTable(cfg, self.config.base, transport, client_options)
        node = NodeAssignmentConfig.from_env(cfg)
        self.cache = StaleCache(node.read_ttl_seconds, node.stale_max_seconds, clock, max_entries=64)

    # Gates

    def remote_gate(self, ctx: Context):
        """Every path that may write 任務 passes here before any remote request."""
        if ctx.workspace.get('settings', {}).get('external_enabled') is not True:
            raise Refusal('writes_disabled', '正式外部連線未啟用，派工暫不可發布')
        org = self.cfg.get('LARK_WORKER_ORGANIZATION', '')
        if not org or ctx.wid != 'lark-' + org or ctx.workspace.get('environment') != 'production':
            raise Refusal('forbidden', '派工發布僅限公司正式工作區')
        if (self.cfg.get('LARK_WORKER_IDENTITY') != 'application' or not self.cfg.get('LARK_APP_ID')
                or not self.cfg.get('LARK_APP_SECRET')
                or not formal_write_allowed(self.config.base, PUBLISH_TABLES['tasks'].table_id)):
            raise Refusal('lark_unconfigured', '公司應用身分或任務表回寫白名單未設定')

    def revalidated(self, ctx: Context, need):
        """Re-read session, role and workspace gate right before a Lark write, as node_assignment does."""
        fresh = ctx.refresh(need) if ctx.refresh else ctx
        if fresh.wid != ctx.wid or fresh.actor != ctx.actor:
            raise Refusal('forbidden', '登入身分已變更，請重新整理後再操作')
        self.remote_gate(fresh)
        return fresh

    def writes_enabled(self, ctx: Context):
        try:
            self.remote_gate(ctx)
            return True
        except Refusal:
            return False

    # Sources

    def _cached(self, wid, key):
        return self.cache.get((wid, key), lambda: read_source(self.reader, self.cfg, wid, key))

    def sources(self, wid, *, fresh=False, keys=KEYS):
        rows, entries = {}, {}
        for key in keys:
            try:
                if fresh:
                    rows[key] = self.reader.read_table(key)
                    self.cache.put((wid, key), rows[key])
                else:
                    entries[key] = self._cached(wid, key)
                    rows[key] = entries[key].value
            except Exception as exc:
                if fresh and key in ('schedule', 'tasks'):
                    raise Refusal('sources_unavailable', '無法讀取最新排程或任務，暫停發布', source=key) from None
                logger.warning('dispatch source %s unavailable: %s', key, type(exc).__name__)
                rows[key] = None
        fetched = _iso(self.clock()) if fresh else None
        return Sources(**{key: rows.get(key) for key in KEYS}, fetched_at=fetched), entries

    def source_vector(self, entries):
        return {key: (_iso(entry.fetched_at) if entry else None) for key, entry in entries.items()} | {
            'schema_version': 1}

    # Seats

    def directory(self, wid):
        sources, _ = self.sources(wid, keys=('people', 'accounts'))
        return Directory.of(sources)

    def seats(self, ctx: Context, directory, department):
        return resolve_seats(self.config.required_seats, directory, department, ctx.workspace.get('users') or [],
                             self.config.seats)

    def preview_seats(self, ctx: Context, directory, preview):
        """Holders for one preview: its department's, without the people who proposed this hash on 組長 and 經理."""
        proposers = self.store.proposers(ctx.wid, preview['preview_hash'])
        return self.seats(ctx, directory, preview['proposal']['department']).excluding(proposers), proposers

    def holds_any_seat(self, ctx: Context):
        return bool(self.seats(ctx, self.directory(ctx.wid), ANY_DEPARTMENT).mine(ctx.actor))

    # Previews and decisions

    def _proposal_and_draft(self, raw):
        if not isinstance(raw, dict):
            raise Refusal('invalid', '提案內容須為 JSON 物件')
        raw = dict(raw)
        draft_id = raw.pop('draft_id', None)
        if draft_id is not None and not (isinstance(draft_id, str) and DRAFT_ID.fullmatch(draft_id)):
            raise Refusal('invalid', 'draft_id 格式不符', field='draft_id')
        return parse_proposal(raw), draft_id

    def preview(self, ctx: Context, raw):
        proposal, draft_id = self._proposal_and_draft(raw)
        sources, entries = self.sources(ctx.wid)
        problem = department_problem(proposal, sources, Directory.of(sources))
        if problem:
            raise Refusal('invalid', '部門須為已知的所屬組別，且須是任務節點所屬的組別', field='department', reason=problem)
        assessment = assess(proposal, sources, self.store.held(ctx.wid), allow_unknown=self.config.allow_unknown)
        stored = self.store.save_preview(ctx.wid, ctx.actor, {
            'preview_hash': proposal_hash(proposal), 'proposal': proposal.public(), 'assessment': assessment,
            'source_vector': self.source_vector(entries), 'draft_id': draft_id}, self.config.preview_ttl_seconds)
        return self.present_preview(ctx, stored)

    def get_preview(self, ctx: Context, preview_id):
        found = self.store.preview(ctx.wid, preview_id)
        if found is None:
            raise Refusal('not_found', '找不到這份派工預覽')
        return self.present_preview(ctx, found)

    def present_preview(self, ctx: Context, preview):
        decisions = self.store.decisions(ctx.wid, preview['preview_hash'])
        directory = self.directory(ctx.wid)
        holders, _ = self.preview_seats(ctx, directory, preview)
        seats, seat_blockers = seat_board(self.config.required_seats, holders, decisions, directory)
        assessment = preview['assessment']
        expired = preview['expires_at'] <= self.clock()
        published = self.store.live_for_hash(ctx.wid, preview['preview_hash']) is not None
        blockers = list(dict.fromkeys(assessment['blockers'] + seat_blockers + (['preview_expired'] if expired else [])
                                      + (['already_published'] if published else [])))
        enabled = self.writes_enabled(ctx)
        mine = holders.mine(ctx.actor)
        return {
            'preview_id': preview['preview_id'], 'preview_hash': preview['preview_hash'],
            'expires_at': _iso(preview['expires_at']), 'expired': expired, 'created_by': preview['actor_id'],
            'draft_id': preview['draft_id'], 'proposal': preview['proposal'], 'source_vector': preview['source_vector'],
            **{k: v for k, v in assessment.items() if k != 'digest'},
            'approval_policy': self.config.policy, 'required_seats': seats,
            'my_seats': sorted(seat.value for seat in mine), 'blockers': blockers,
            'can_commit': not blockers and enabled and ctx.can_dispatch, 'writes_enabled': enabled,
        }

    def decide(self, ctx: Context, preview_id, raw):
        found = self.store.preview(ctx.wid, preview_id)
        if found is None:
            raise Refusal('not_found', '找不到這份派工預覽')
        if not isinstance(raw, dict) or set(raw) - {'seat', 'decision', 'reason'}:
            raise Refusal('invalid', '決定內容只接受 seat、decision、reason')
        try:
            seat, decision = Seat(raw.get('seat')), Decision(raw.get('decision'))
        except ValueError:
            raise Refusal('invalid', 'seat 或 decision 不在允許值內') from None
        reason = raw.get('reason')
        if reason is not None and not (isinstance(reason, str) and len(reason.strip()) <= 500):
            raise Refusal('invalid', '理由須為 500 字以內', field='reason')
        reason = (reason or '').strip() or None
        if decision is Decision.RETURNED and not reason:
            raise Refusal('invalid', '退回須附理由', field='reason')
        live = self.store.live_for_hash(ctx.wid, found['preview_hash'])
        if live is not None:
            raise duplicate(live['command_id'], live['state'])
        required = self.config.required_seats
        holders, proposers = self.preview_seats(ctx, self.directory(ctx.wid), found)
        self.store.decide(ctx.wid, found, seat.value, ctx.actor, decision.value, reason,
                          lambda current: decision_refusal(seat, ctx.actor, required, holders, current, proposers))
        return self.present_preview(ctx, found)

    # Commands

    def commit(self, ctx: Context, raw):
        self.remote_gate(ctx)
        if not isinstance(raw, dict) or set(raw) != {'command_id', 'preview_id'}:
            raise Refusal('invalid', '發布需要 command_id 與 preview_id')
        command_id, preview_id = raw['command_id'], raw['preview_id']
        if not (isinstance(command_id, str) and COMMAND_ID.fullmatch(command_id)):
            raise Refusal('invalid', 'command_id 須為小寫 UUIDv4（例如 crypto.randomUUID()）', field='command_id')
        if not isinstance(preview_id, str):
            raise Refusal('invalid', 'preview_id 須為文字', field='preview_id')
        existing = self.store.command(ctx.wid, command_id)
        if existing is not None:
            if existing['preview_id'] != preview_id:
                raise Refusal('idempotency_conflict', 'command_id 已用於其他預覽，請產生新的 command_id')
            return existing
        preview = self.store.preview(ctx.wid, preview_id)
        if preview is None:
            raise Refusal('not_found', '找不到這份派工預覽')
        live = self.store.live_for_hash(ctx.wid, preview['preview_hash'])
        if live is not None:
            raise duplicate(live['command_id'], live['state'])
        if preview['expires_at'] <= self.clock():
            raise Refusal('preview_expired', '預覽已過期，請重新預覽（相同內容的核定仍有效）')
        proposal = parse_proposal(preview['proposal'])
        if proposal_hash(proposal) != preview['preview_hash']:
            raise Refusal('preview_stale', '預覽內容與其雜湊不符，請重新預覽')
        sources, _ = self.sources(ctx.wid, fresh=True)
        assessment = assess(proposal, sources, self.store.held(ctx.wid), allow_unknown=self.config.allow_unknown)
        decisions = self.store.decisions(ctx.wid, preview['preview_hash'])
        directory = Directory.of(sources)
        holders, _ = self.preview_seats(ctx, directory, preview)
        _, seat_blockers = seat_board(self.config.required_seats, holders, decisions, directory)
        lapsed = [b.split(':', 1)[1] for b in seat_blockers if b.startswith('decision_holder_changed:')]
        if lapsed:
            raise Refusal('decision_holder_changed', '核定人已不再擔任此席次，請由現任持有人重新核定',
                          seats=lapsed, blockers=seat_blockers)
        if 'approval_not_configured' in seat_blockers:
            raise Refusal('approval_not_configured', '核定席次尚無可核定的人，無法發布', blockers=seat_blockers,
                          seats=[b.split(':', 1)[1] for b in seat_blockers if b.startswith('approval_not_configured:')])
        blockers = assessment['blockers'] + seat_blockers
        if blockers:
            raise Refusal('blocked', '尚有未解除的發布條件', blockers=blockers, conflicts=assessment['conflicts'])
        if assessment['digest'] != preview['assessment']['digest']:
            raise Refusal('preview_stale', '排程、任務或人員帳號已變更，請重新預覽', conflicts=assessment['conflicts'])
        revision = assessment['base_revision'] + 1
        payload = task_fields(proposal, directory, actor_open_id=ctx.actor, command_id=command_id, revision=revision,
                              now_ms=int(self.clock() * 1000), create=proposal.task_id is None)
        base = snapshot(sources.index('tasks')[proposal.task_id]) if proposal.task_id else None

        def recheck():
            try:
                current = self.tasks.recheck(proposal.task_id)
            except Failure:
                raise Refusal('recheck_unavailable', '無法在發布前重新讀取任務，請稍後重試', retryable=True) from None
            if snapshot(current.get('fields') or {}) != base:
                raise Refusal('stale_revision', '任務已在預覽後變更，請重新預覽')
        created, command = self.store.open_command(ctx.wid, {
            'command_id': command_id, 'preview_id': preview_id, 'preview_hash': preview['preview_hash'],
            'action': 'update' if proposal.task_id else 'create', 'task_id': proposal.task_id, 'actor_id': ctx.actor,
            'revision': revision, 'payload': payload, 'base': base}, proposal.items(), millis(proposal.start),
            millis(proposal.end), recheck)
        if not created:
            if command['preview_id'] != preview_id:
                raise Refusal('idempotency_conflict', 'command_id 已用於其他預覽，請產生新的 command_id')
            return command
        try:
            ctx = self.revalidated(ctx, 'dispatch')
        except Exception as exc:
            self.store.abandon(ctx.wid, command_id, ctx.actor, getattr(exc, 'code', type(exc).__name__))
            raise
        return self._write(ctx, command)

    def _write(self, ctx: Context, command):
        try:
            if command['action'] == 'create':
                record_id = self.tasks.create(command['payload'], command['command_id'])
            else:
                record_id = command['task_id']
                self.tasks.update(record_id, command['payload'])
        except Failure as exc:
            state = CommandResult.OUTCOME_UNKNOWN if exc.code == 'outcome_unknown' else CommandResult.FAILED
            return self.store.finish(ctx.wid, command['command_id'], command['attempt'], state,
                                     {'error': exc.code, 'at': _iso(self.clock())}, ctx.actor)
        return self._read_back(ctx, command, record_id)

    def _read_back(self, ctx: Context, command, record_id, record=None, rows=None):
        """Committed only when the row reads back as written and it is the one row carrying the 命令編號."""
        def finish(state, **receipt):
            return self.store.finish(ctx.wid, command['command_id'], command['attempt'], state,
                                     {'record_id': record_id, **receipt}, ctx.actor, task_id=record_id)
        self.cache.drop((ctx.wid, 'tasks'))
        if record is None:
            try:
                record = self.tasks.get(record_id)
            except Failure as exc:
                return finish(CommandResult.OUTCOME_UNKNOWN, error='readback_' + exc.code, at=_iso(self.clock()))
        read = dict(read_back_at=_iso(self.clock()), revision=command['revision'])
        diff = mismatches(command['payload'], record.get('fields') or {})
        if command['action'] == 'update' and record_id != command['task_id']:
            diff = ['record_id']
        if diff:
            return finish(CommandResult.RECONCILIATION_REQUIRED, mismatches=diff, **read)
        try:
            if rows is None:
                rows = self.tasks.by_command(command['command_id'])
            if not rows:
                # The row already read back as written; Lark search can lag a fresh write, so ask once more.
                self.sleep(SEARCH_RETRY_SECONDS)
                rows = self.tasks.by_command(command['command_id'])
        except Failure as exc:
            return finish(CommandResult.OUTCOME_UNKNOWN, error='search_' + exc.code, at=_iso(self.clock()))
        carrying = sorted({r['record_id'] for r in rows} | {record_id})
        if len(carrying) > 1:
            return finish(CommandResult.RECONCILIATION_REQUIRED, mismatches=[], duplicates=carrying, **read)
        if not rows:
            return finish(CommandResult.OUTCOME_UNKNOWN, error='search_lag', at=_iso(self.clock()))
        return finish(CommandResult.COMMITTED, mismatches=[], **read)

    def reconcile(self, ctx: Context, command_id):
        if ctx.user.get('role') != 'manager':
            raise Refusal('forbidden', '只有主管可以對帳')
        self.remote_gate(ctx)
        command = self.store.command(ctx.wid, command_id)
        if command is None:
            raise Refusal('not_found', '找不到這個命令')
        claimed = self.store.claim(ctx.wid, command_id, ctx.actor, self.clock() - self.config.pending_grace_seconds)
        if claimed is None:
            return command
        try:
            rows = self.tasks.by_command(command_id)
        except Failure:
            raise Refusal('sources_unavailable', '無法讀取任務表以對帳，命令狀態未變') from None
        if len(rows) > 1:
            return self.store.finish(ctx.wid, command_id, claimed['attempt'], CommandResult.RECONCILIATION_REQUIRED,
                                     {'duplicates': sorted(r['record_id'] for r in rows), 'at': _iso(self.clock())},
                                     ctx.actor)
        if rows:
            return self._read_back(ctx, claimed, rows[0]['record_id'], rows[0], rows)
        if CommandResult(claimed['state']) is CommandResult.RECONCILIATION_REQUIRED:
            return self.store.finish(ctx.wid, command_id, claimed['attempt'], CommandResult.RECONCILIATION_REQUIRED,
                                     {**(claimed['receipt'] or {}), 'row_missing': True, 'at': _iso(self.clock())},
                                     ctx.actor)
        landed = (claimed['receipt'] or {}).get('record_id') if claimed['action'] == 'create' else None
        if landed:
            # The create returned its row; read that row back instead of sending the create again.
            try:
                current = self.tasks.get(landed)
            except Failure:
                raise Refusal('sources_unavailable', '無法讀取任務列以對帳，命令狀態未變') from None
            return self._read_back(ctx, claimed, landed, current, rows)
        if claimed['action'] == 'update':
            try:
                current = self.tasks.get(claimed['task_id'])
            except Failure:
                raise Refusal('sources_unavailable', '無法讀取任務列以對帳，命令狀態未變') from None
            fields = current.get('fields') or {}
            if not mismatches(claimed['payload'], fields):
                return self._read_back(ctx, claimed, claimed['task_id'], current, rows)
            if claimed['base'] is None:
                return self.store.finish(ctx.wid, command_id, claimed['attempt'], CommandResult.RECONCILIATION_REQUIRED,
                                         {'record_id': claimed['task_id'], 'reason': 'no_base_snapshot',
                                          'at': _iso(self.clock())}, ctx.actor)
            # Someone edited the row since the command was opened: report it, never overwrite it.
            moved = changed(claimed['base'], fields)
            if moved:
                return self.store.finish(ctx.wid, command_id, claimed['attempt'], CommandResult.RECONCILIATION_REQUIRED,
                                         {'record_id': claimed['task_id'], 'changed_since_commit': moved,
                                          'at': _iso(self.clock())}, ctx.actor)
        # Nothing landed under this command: send the identical payload again with the same client_token.
        return self._write(self.revalidated(ctx, 'manager'), claimed)

    def reconcilable(self, command):
        state = CommandResult(command['state'])
        return state in (CommandResult.OUTCOME_UNKNOWN, CommandResult.RECONCILIATION_REQUIRED) or (
            state is CommandResult.PENDING and command['updated_at'] <= self.clock() - self.config.pending_grace_seconds)

    def present_command(self, ctx: Context, command):
        state = CommandResult(command['state'])
        planning = COMMAND_PLANNING.get(state, PlanningStatus.PENDING_APPROVAL)
        return {'command': {
            'command_id': command['command_id'], 'preview_id': command['preview_id'],
            'preview_hash': command['preview_hash'], 'action': command['action'], 'task_id': command['task_id'],
            'actor_id': command['actor_id'], 'state': state.value, 'label': COMMAND_LABEL[state],
            'planning_status': planning.value, 'revision': command['revision'],
            'created_at': _iso(command['created_at']), 'updated_at': _iso(command['updated_at'])},
            'receipt': command['receipt'],
            'reservations': [{k: r[k] for k in ('resource_kind', 'ref', 'state', 'task_id')}
                             | {'start': from_millis(r['start_ms']).isoformat(timespec='minutes'),
                                'end': from_millis(r['end_ms']).isoformat(timespec='minutes')}
                             for r in self.store.reservations(ctx.wid, command['command_id'])],
            'next_action': 'reconcile' if ctx.user.get('role') == 'manager' and self.reconcilable(command) else 'none'}

    def get_command(self, ctx: Context, command_id):
        command = self.store.command(ctx.wid, command_id)
        if command is None:
            raise Refusal('not_found', '找不到這個命令')
        return command

    # Drafts

    def save_draft(self, ctx: Context, draft_id, raw):
        if not (isinstance(draft_id, str) and DRAFT_ID.fullmatch(draft_id)):
            raise Refusal('invalid', 'draft_id 須為 8 至 64 個英數字、底線或連字號')
        if not isinstance(raw, dict) or set(raw) - {'proposal', 'version'} or not isinstance(raw.get('proposal'), dict):
            raise Refusal('invalid', '草稿需要 proposal 物件')
        proposal, version = raw['proposal'], raw.get('version')
        check_draft(proposal)
        if version is not None and type(version) is not int:
            raise Refusal('invalid', 'version 須為整數', field='version')
        return self.store.put_draft(ctx.wid, ctx.actor, draft_id, proposal.get('task_id'), proposal, version)

    def get_draft(self, ctx: Context, draft_id):
        found = self.store.draft(ctx.wid, draft_id)
        if found is None or found['actor_id'] != ctx.actor:
            raise Refusal('not_found', '找不到這份草稿')
        return found

    # Reads for the PM

    def _work_sources(self, wid):
        # Fail the primary read before scheduling optional joins, including on permission revocation.
        tasks = self._cached(wid, 'tasks')
        entries, rows, failed = {'tasks': tasks}, {'tasks': tasks.value}, []
        futures = {key: _work_reads.submit(copy_context().run, self._cached, wid, key)
                   for key in WORK_KEYS if key != 'tasks'}
        for key, future in futures.items():
            try:
                entries[key] = future.result()
                rows[key] = entries[key].value
            except Exception as exc:
                failed.append(key)
                rows[key] = None
                logger.warning('dispatch work join %s unavailable: %s', key, type(exc).__name__)
        sources = Sources(schedule=None, **{key: rows.get(key) for key in KEYS if key != 'schedule'})
        return sources, entries, failed

    def work(self, ctx: Context, window=None, group=None, scope='all'):
        try:
            sources, entries, failed = self._work_sources(ctx.wid)
        except Exception as exc:
            denied = permission_failure(exc)
            return (403 if denied else 503), {'source': {'quality': {
                'states': ['forbidden' if denied else 'read_failed'],
                'reason': 'source_forbidden' if denied else 'tasks_read_failed'}}}
        overlay = self.store.overlay(ctx.wid, ctx.actor)
        seats_for = self._seats_for(ctx, Directory.of(sources))
        body = build_work(sources, overlay, ctx.viewer, required=self.config.required_seats, seats_for=seats_for,
                          allow_unknown=self.config.allow_unknown,
                          reconcilable={c['command_id'] for c in overlay.commands if self.reconcilable(c)},
                          window=window, group=group, scope=scope)
        tasks = entries['tasks']
        stale = [entry for entry in entries.values() if entry.stale]
        states = (['partial'] if failed else []) + (['stale'] if stale else []) or ['complete']
        quality = {'states': states, 'reason': 'refreshing_last_good_snapshot' if stale else
                   'incomplete_joins' if failed else None}
        if stale:
            quality['age_seconds'] = max(0, int(self.clock() - min(e.fetched_at for e in stale)))
        return 200, {'schema_version': 1,
                     'window': {'from': window[0].isoformat(), 'to': window[1].isoformat(), 'tz': 'Asia/Taipei'}
                     if window else None,
                     'scope': scope, 'group': group,
                     'source': {'registry_key': 'v4', 'table_id': PUBLISH_TABLES['tasks'].table_id,
                                'fetched_at': _iso(tasks.fetched_at), 'quality': quality,
                                'joins': {key: 'unavailable' if key in failed else 'ok' for key in WORK_KEYS if key != 'tasks'}},
                     'approval_policy': self.config.policy,
                     'my_seats': sorted(seat.value for seat in self.seats(
                         ctx, Directory.of(sources), ANY_DEPARTMENT).mine(ctx.actor)),
                     **body}

    def _seats_for(self, ctx: Context, directory):
        by_department = cache(lambda department: self.seats(ctx, directory, department))
        return lambda proposal: by_department(proposal.get('department'))

    def task_form(self, ctx: Context, task_id):
        sources, _, _ = self._work_sources(ctx.wid)
        record = next((r for r in sources.tasks if r['record_id'] == task_id), None)
        if record is None:
            raise Refusal('not_found', '找不到這筆任務')
        directory = Directory.of(sources)
        fields = record['fields']
        owners = [ident for ident, _ in task_users(fields, '負責人')]
        crew = [ident for ident, _ in task_users(fields, '組員')]
        refs = [directory.refs.get(ident) for ident in owners[:1] + crew]
        span = task_interval(fields)
        overlay = self.store.overlay(ctx.wid, ctx.actor)
        row = build_work(Sources(**{**sources.__dict__, 'tasks': [record]}), overlay, ctx.viewer,
                         required=self.config.required_seats, seats_for=self._seats_for(ctx, directory),
                         allow_unknown=self.config.allow_unknown, reconcilable=set())['rows'][0]
        base = task_row(record, sources, directory)
        phase = {'接案前': 'intake', '正式': 'formal'}.get(text(fields.get('任務階段')).strip())
        deadline = fields.get('截止日')
        return {
            'row': row,
            'proposal': {
                'task_id': task_id, 'project_ref': base['project_id'], 'case_ref': (base['case'] or {}).get('ref'),
                'title': base['title'], 'content': base['content'], 'kind': base['kind'] or 'execution', 'phase': phase,
                'package_id': base['package_id'], 'parent_task_ref': base['parent_task_ref'],
                'department': base['department'], 'primary_owner': refs[0] if owners else None,
                'crew': [ref for ref in refs if ref], 'start': span.start.isoformat(timespec='minutes') if span else None,
                'end': span.end.isoformat(timespec='minutes') if span else None,
                'est_person_hours': base['est_person_hours'], 'instruments': link_ids(fields.get('使用儀器')),
                'vehicles': link_ids(fields.get('使用車輛')),
                'deadline': from_millis(deadline).date().isoformat() if type(deadline) is int else None,
                'verifications': {}},
            'unmapped_people': [ident for ident in owners[:1] + crew if ident not in directory.refs],
            'system': {'scope_version': base['versions']['scope'], 'rule_version': base['versions']['rule'],
                       'evidence_version': base['versions']['evidence'],
                       'planning_status': text(fields.get('排程狀態')).strip() or None, 'revision': base['revision'],
                       'command_id': base['command_ref'], 'readback_at': base['readback_at'],
                       'acceptance_status': base['acceptance_status'], 'acceptance_summary': base['acceptance_summary']},
            'form_fields': [{'field': f, 'v4_field': v, 'editable': e} for f, v, e in FORM_FIELDS],
        }

    def options(self, ctx: Context):
        sources, _ = self.sources(ctx.wid, keys=('people', 'accounts', 'instruments', 'vehicles', 'cases', 'tasks'))
        directory = Directory.of(sources)

        def resources(key, kind, label):
            return [{'ref': rid, 'label': text(f.get(label)).strip() or None,
                     'feasibility': resource_state(kind, {'啟用': False, **f})[0].value}
                    for rid, f in sources.index(key).items()]
        return {
            'people': [{'person_ref': ref, 'name': name, 'active': directory.active.get(ref),
                        'has_lark_account': ref in directory.open_ids} for ref, name in directory.names.items()],
            'instruments': resources('instruments', 'instrument', '儀器名稱'),
            'vehicles': resources('vehicles', 'vehicle', '車牌'),
            'cases': [{'ref': rid, 'code': text(f.get('工程確認單編號')).strip() or None,
                       'name': text(f.get('工程名稱')).strip() or None} for rid, f in sources.index('cases').items()],
            'departments': sorted({text(f.get('部門')).strip() for f in sources.index('tasks').values()} - {''}),
            'joins': {key: 'unavailable' if getattr(sources, key) is None else 'ok'
                      for key in ('people', 'accounts', 'instruments', 'vehicles', 'cases')},
            'approval_policy': self.config.policy,
            'seats': self._seat_options(ctx, directory),
            'allow_unknown': self.config.allow_unknown,
        }

    def _seat_options(self, ctx: Context, directory):
        """Every seat with who could hold it; department-scoped seats also per 所屬組別."""
        anywhere = self.seats(ctx, directory, ANY_DEPARTMENT)
        departments = sorted(set().union(*directory.groups.values()))
        found = []
        for seat in self.config.required_seats:
            people = anywhere.people(seat, directory)
            entry = {'seat': seat.value, 'configured': bool(people), 'source': anywhere.origin[seat], 'holders': people}
            if seat is not Seat.PM_FINAL and anywhere.origin[seat] == 'roster':
                entry['by_department'] = {d: p for d in departments if (p := self.seats(ctx, directory, d).people(seat, directory))}
            found.append(entry)
        return found
