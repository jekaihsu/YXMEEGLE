"""Workbench-owned dispatch facts: previews, drafts, append-only decisions, commands and reservations.

Every write that must see a consistent set of commands and reservations runs inside `exclusive`, which
first updates the workspace's lock row. On SQLite that write takes the database RESERVED lock (the same
lock BEGIN IMMEDIATE takes); on PostgreSQL it takes a row lock. Either way a second process waits until
the first commits, so the overlap query and the insert that follows it cannot interleave.
"""
import secrets
import time
from contextlib import contextmanager
from copy import deepcopy

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from .. import audit
from ..models import (DispatchCommandRow, DispatchDecisionRow, DispatchDraftRow, DispatchLockRow, DispatchPreviewRow,
                      DispatchReservationRow)
from .domain import IN_FLIGHT, LIVE, CommandResult, Overlay, Refusal, from_millis

HISTORY_SECONDS = 30 * 86400


def duplicate(command_id, state):
    return Refusal('duplicate_command', '這份預覽已有發布命令', command_id=command_id, state=state)


def _command(row: DispatchCommandRow):
    return {'command_id': row.command_id, 'preview_id': row.preview_id, 'preview_hash': row.preview_hash,
            'action': row.action, 'task_id': row.task_id, 'actor_id': row.actor_id, 'state': row.state,
            'revision': row.revision, 'attempt': row.attempt, 'payload': deepcopy(row.payload),
            'receipt': deepcopy(row.receipt), 'created_at': row.created_at, 'updated_at': row.updated_at}


def _preview(row: DispatchPreviewRow):
    return {'preview_id': row.id, 'preview_hash': row.preview_hash, 'task_id': row.task_id, 'draft_id': row.draft_id,
            'actor_id': row.actor_id, 'created_at': row.created_at, 'expires_at': row.expires_at, **deepcopy(row.data)}


def _decision(row: DispatchDecisionRow):
    return {'seat': row.seat, 'actor_id': row.actor_id, 'decision': row.decision, 'reason': row.reason,
            'at': row.at, 'preview_id': row.preview_id}


def _reservation(row: DispatchReservationRow):
    return {'resource_kind': row.resource_kind, 'ref': row.ref, 'start_ms': row.start_ms, 'end_ms': row.end_ms,
            'command_id': row.command_id, 'task_id': row.task_id, 'state': row.state}


def _draft(row: DispatchDraftRow):
    return {'id': row.id, 'actor_id': row.actor_id, 'task_id': row.task_id, 'version': row.version,
            'updated_at': row.updated_at, 'proposal': deepcopy(row.data)}


class DispatchStore:
    def __init__(self, sessions, audit_model, clock=time.time):
        self.sessions, self.Audit, self.clock = sessions, audit_model, clock

    @contextmanager
    def exclusive(self, wid):
        with self.sessions() as db:
            missing = db.get(DispatchLockRow, wid) is None
        if missing:
            try:
                with self.sessions.begin() as db:
                    db.add(DispatchLockRow(workspace_id=wid, counter=0))
            except IntegrityError:
                pass
        with self.sessions.begin() as db:
            db.execute(update(DispatchLockRow).where(DispatchLockRow.workspace_id == wid)
                       .values(counter=DispatchLockRow.counter + 1))
            yield db

    def audit(self, db, wid, actor, action, **details):
        db.add(audit.record(self.Audit, wid, actor, action, details=details))

    # Previews

    def save_preview(self, wid, actor, preview, ttl):
        """Identical proposal content within the TTL keeps its preview_id; the assessment is refreshed."""
        now = self.clock()
        with self.exclusive(wid) as db:
            row = db.scalars(select(DispatchPreviewRow).where(
                DispatchPreviewRow.workspace_id == wid, DispatchPreviewRow.preview_hash == preview['preview_hash'],
                DispatchPreviewRow.expires_at > now).order_by(DispatchPreviewRow.created_at.desc())).first()
            data = {k: preview[k] for k in ('proposal', 'assessment', 'source_vector')}
            if row is None:
                row = DispatchPreviewRow(id='pv_' + secrets.token_hex(12), workspace_id=wid,
                                         preview_hash=preview['preview_hash'], task_id=preview['proposal']['task_id'],
                                         draft_id=preview.get('draft_id'), actor_id=actor, created_at=now,
                                         expires_at=now + ttl, data=data)
                db.add(row)
            else:
                row.data = data
                row.draft_id = preview.get('draft_id') or row.draft_id
            self.audit(db, wid, actor, 'dispatch.preview', preview_id=row.id, preview_hash=row.preview_hash,
                       task_id=row.task_id, blockers=data['assessment']['blockers'])
            db.flush()
            return _preview(row)

    def preview(self, wid, preview_id):
        with self.sessions() as db:
            row = db.get(DispatchPreviewRow, preview_id)
            return _preview(row) if row is not None and row.workspace_id == wid else None

    # Decisions

    def decisions(self, wid, preview_hash):
        with self.sessions() as db:
            return [_decision(r) for r in db.scalars(select(DispatchDecisionRow).where(
                DispatchDecisionRow.workspace_id == wid, DispatchDecisionRow.preview_hash == preview_hash)
                .order_by(DispatchDecisionRow.at, DispatchDecisionRow.id))]

    def decide(self, wid, preview, seat, actor, decision, reason, refuse):
        """refuse(current decisions) -> refusal code or None, evaluated under the workspace lock."""
        with self.exclusive(wid) as db:
            current = [_decision(r) for r in db.scalars(select(DispatchDecisionRow).where(
                DispatchDecisionRow.workspace_id == wid, DispatchDecisionRow.preview_hash == preview['preview_hash']))]
            code = refuse(current)
            if code is not None:
                raise Refusal('seat_conflict', '此席次目前不能由你決定', reason=code)
            db.add(DispatchDecisionRow(id=secrets.token_hex(16), workspace_id=wid, preview_hash=preview['preview_hash'],
                                       preview_id=preview['preview_id'], seat=seat, actor_id=actor, decision=decision,
                                       reason=reason, at=self.clock()))
            self.audit(db, wid, actor, 'dispatch.decision', preview_id=preview['preview_id'],
                       preview_hash=preview['preview_hash'], seat=seat, decision=decision)

    # Commands and reservations

    def command(self, wid, command_id):
        with self.sessions() as db:
            row = db.get(DispatchCommandRow, (wid, command_id))
            return _command(row) if row is not None else None

    def live_for_hash(self, wid, preview_hash):
        with self.sessions() as db:
            row = db.scalars(select(DispatchCommandRow).where(
                DispatchCommandRow.workspace_id == wid, DispatchCommandRow.preview_hash == preview_hash,
                DispatchCommandRow.state.in_([s.value for s in LIVE]))).first()
            return _command(row) if row is not None else None

    def held(self, wid):
        with self.sessions() as db:
            return [_reservation(r) for r in db.scalars(select(DispatchReservationRow).where(
                DispatchReservationRow.workspace_id == wid, DispatchReservationRow.state == 'held'))]

    def reservations(self, wid, command_id):
        with self.sessions() as db:
            return [_reservation(r) for r in db.scalars(select(DispatchReservationRow).where(
                DispatchReservationRow.workspace_id == wid, DispatchReservationRow.command_id == command_id)
                .order_by(DispatchReservationRow.resource_kind, DispatchReservationRow.ref))]

    def open_command(self, wid, command, items, start_ms, end_ms):
        """Persist the command as pending with its reservations, or refuse. Returns (created, command)."""
        now = self.clock()
        with self.exclusive(wid) as db:
            existing = db.get(DispatchCommandRow, (wid, command['command_id']))
            if existing is not None:
                return False, _command(existing)
            live = db.scalars(select(DispatchCommandRow).where(
                DispatchCommandRow.workspace_id == wid, DispatchCommandRow.preview_hash == command['preview_hash'],
                DispatchCommandRow.state.in_([s.value for s in LIVE]))).first()
            if live is not None:
                raise duplicate(live.command_id, live.state)
            if command['task_id']:
                busy = db.scalars(select(DispatchCommandRow).where(
                    DispatchCommandRow.workspace_id == wid, DispatchCommandRow.task_id == command['task_id'],
                    DispatchCommandRow.state.in_([s.value for s in IN_FLIGHT]))).first()
                if busy is not None:
                    raise Refusal('busy', '此任務仍有處理中的發布命令', command_id=busy.command_id, state=busy.state)
            query = select(DispatchReservationRow).where(
                DispatchReservationRow.workspace_id == wid, DispatchReservationRow.state == 'held',
                DispatchReservationRow.ref.in_([ref for _, ref in items]),
                DispatchReservationRow.start_ms < end_ms, DispatchReservationRow.end_ms > start_ms)
            if command['task_id']:
                query = query.where(or_(DispatchReservationRow.task_id.is_(None),
                                        DispatchReservationRow.task_id != command['task_id']))
            wanted = {(kind.value, ref) for kind, ref in items}
            clashes = [_reservation(r) for r in db.scalars(query) if (r.resource_kind, r.ref) in wanted]
            if clashes:
                titles = {}
                for other in db.scalars(select(DispatchCommandRow).where(
                        DispatchCommandRow.workspace_id == wid,
                        DispatchCommandRow.command_id.in_({c['command_id'] for c in clashes}))):
                    found = db.get(DispatchPreviewRow, other.preview_id)
                    titles[other.command_id] = found.data['proposal']['title'] if found else None
                raise Refusal('reservation_conflict', '同一時段的人員或資源已被其他發布佔用；草稿已保留',
                              conflicts=[{'kind': c['resource_kind'], 'ref': c['ref'], 'task_id': c['task_id'],
                                          'command_id': c['command_id'], 'title': titles.get(c['command_id']),
                                          'interval': {'start': from_millis(c['start_ms']).isoformat(timespec='minutes'),
                                                       'end': from_millis(c['end_ms']).isoformat(timespec='minutes'),
                                                       'precision': 'datetime'}} for c in clashes])
            row = DispatchCommandRow(workspace_id=wid, command_id=command['command_id'], preview_id=command['preview_id'],
                                     preview_hash=command['preview_hash'], action=command['action'],
                                     task_id=command['task_id'], actor_id=command['actor_id'],
                                     state=CommandResult.PENDING.value, revision=command['revision'], attempt=1,
                                     payload=command['payload'], receipt=None, created_at=now, updated_at=now)
            db.add(row)
            for kind, ref in items:
                db.add(DispatchReservationRow(id=secrets.token_hex(16), workspace_id=wid, resource_kind=kind.value,
                                              ref=ref, start_ms=start_ms, end_ms=end_ms,
                                              command_id=command['command_id'], task_id=command['task_id'], state='held'))
            self.audit(db, wid, command['actor_id'], 'dispatch.command.pending', command_id=command['command_id'],
                       preview_hash=command['preview_hash'], task_id=command['task_id'], revision=command['revision'],
                       reserved=[f'{kind.value}:{ref}' for kind, ref in items])
            db.flush()
            return True, _command(row)

    def claim(self, wid, command_id, actor, grace_before):
        """Take over a command for reconciliation; a pending one only after its worker's grace period."""
        with self.exclusive(wid) as db:
            row = db.get(DispatchCommandRow, (wid, command_id))
            if row is None or row.state not in {s.value for s in IN_FLIGHT}:
                return None
            if row.state == CommandResult.PENDING and row.updated_at > grace_before:
                raise Refusal('busy', '發布命令仍在處理中，請稍後再對帳')
            row.attempt += 1
            row.updated_at = self.clock()
            self.audit(db, wid, actor, 'dispatch.command.reconcile', command_id=command_id, attempt=row.attempt)
            db.flush()
            return _command(row)

    def finish(self, wid, command_id, attempt, state: CommandResult, receipt, actor, task_id=None):
        """Record a result unless another attempt has taken the command over; returns the stored command."""
        with self.exclusive(wid) as db:
            row = db.get(DispatchCommandRow, (wid, command_id))
            if row.attempt != attempt:
                return _command(row)
            row.state, row.receipt, row.updated_at = state.value, receipt, self.clock()
            if task_id:
                row.task_id = task_id
            mine = (DispatchReservationRow.workspace_id == wid) & (DispatchReservationRow.command_id == command_id)
            if state is CommandResult.FAILED:
                db.execute(update(DispatchReservationRow).where(mine).values(state='released'))
            if state is CommandResult.COMMITTED:
                db.execute(update(DispatchReservationRow).where(mine).values(task_id=row.task_id))
                # A reassignment releases the previous revision only now that the new one has read back.
                db.execute(update(DispatchReservationRow).where(
                    DispatchReservationRow.workspace_id == wid, DispatchReservationRow.task_id == row.task_id,
                    DispatchReservationRow.command_id != command_id, DispatchReservationRow.state == 'held')
                    .values(state='released'))
            self.audit(db, wid, actor, f'dispatch.command.{state.value}', command_id=command_id,
                       task_id=row.task_id, revision=row.revision, preview_hash=row.preview_hash)
            db.flush()
            return _command(row)

    # Drafts

    def put_draft(self, wid, actor, draft_id, task_id, proposal, expected_version):
        with self.exclusive(wid) as db:
            row = db.get(DispatchDraftRow, (wid, draft_id))
            if row is not None and row.actor_id != actor:
                raise Refusal('forbidden', '只能修改自己的草稿')
            if expected_version is not None and (row.version if row else 0) != expected_version:
                raise Refusal('version_conflict', '草稿已在其他地方更新，請重新載入', version=row.version if row else 0)
            if row is None:
                row = DispatchDraftRow(workspace_id=wid, id=draft_id, actor_id=actor, version=0)
                db.add(row)
            row.task_id, row.data, row.version, row.updated_at = task_id, proposal, row.version + 1, self.clock()
            self.audit(db, wid, actor, 'dispatch.draft.saved', draft_id=draft_id, task_id=task_id, version=row.version)
            db.flush()
            return _draft(row)

    def draft(self, wid, draft_id):
        with self.sessions() as db:
            row = db.get(DispatchDraftRow, (wid, draft_id))
            return _draft(row) if row is not None else None

    def drafts(self, wid, actor):
        with self.sessions() as db:
            return [_draft(r) for r in db.scalars(select(DispatchDraftRow).where(
                DispatchDraftRow.workspace_id == wid, DispatchDraftRow.actor_id == actor)
                .order_by(DispatchDraftRow.updated_at.desc()))]

    def delete_draft(self, wid, actor, draft_id):
        with self.exclusive(wid) as db:
            row = db.get(DispatchDraftRow, (wid, draft_id))
            if row is None:
                raise Refusal('not_found', '找不到這份草稿')
            if row.actor_id != actor:
                raise Refusal('forbidden', '只能刪除自己的草稿')
            db.delete(row)
            self.audit(db, wid, actor, 'dispatch.draft.deleted', draft_id=draft_id, task_id=row.task_id)

    # Work-queue overlay

    def overlay(self, wid, viewer_id) -> Overlay:
        since = self.clock() - HISTORY_SECONDS
        with self.sessions() as db:
            commands = list(db.scalars(select(DispatchCommandRow).where(
                DispatchCommandRow.workspace_id == wid,
                or_(DispatchCommandRow.created_at >= since, DispatchCommandRow.state.in_([s.value for s in IN_FLIGHT])))))
            previews = {r.id: r for r in db.scalars(select(DispatchPreviewRow).where(
                DispatchPreviewRow.workspace_id == wid, DispatchPreviewRow.created_at >= since))}
            for command in commands:
                if command.preview_id not in previews:
                    found = db.get(DispatchPreviewRow, command.preview_id)
                    if found is not None:
                        previews[found.id] = found
            published = {c.preview_hash for c in commands if c.state in {s.value for s in LIVE}}
            latest = {}
            for row in sorted(previews.values(), key=lambda r: r.created_at):
                latest[row.preview_hash] = row
            hashes = [h for h in latest if h not in published]
            decided = {}
            if hashes:
                for row in db.scalars(select(DispatchDecisionRow).where(
                        DispatchDecisionRow.workspace_id == wid, DispatchDecisionRow.preview_hash.in_(hashes))):
                    decided.setdefault(row.preview_hash, []).append(_decision(row))
            # An expired preview nobody decided on is abandoned; one with decisions stays until it is published.
            now = self.clock()
            approvals = [{'preview_id': row.id, 'preview_hash': h, 'task_id': row.task_id, 'draft_id': row.draft_id,
                          'actor_id': row.actor_id, 'created_at': row.created_at,
                          'proposal': deepcopy(row.data['proposal']), 'blockers': list(row.data['assessment']['blockers']),
                          'decisions': decided.get(h, [])} for h, row in latest.items()
                         if h in hashes and (decided.get(h) or row.expires_at > now)]
            drafts = [_draft(r) for r in db.scalars(select(DispatchDraftRow).where(
                DispatchDraftRow.workspace_id == wid, DispatchDraftRow.actor_id == viewer_id))]
            command_rows = [{**_command(c), 'proposal': deepcopy(previews[c.preview_id].data['proposal'])
                             if c.preview_id in previews else {}} for c in commands]
        return Overlay(command_rows, approvals, drafts)
