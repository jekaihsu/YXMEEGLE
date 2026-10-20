"""Durable, one-way projection of local SOP tasks into the dedicated V4 table."""
import argparse
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import tempfile
import threading
import time
from urllib.parse import quote
from uuid import UUID, uuid4

from sqlalchemy import create_engine, select, update, text as sql_text
from sqlalchemy.orm import sessionmaker

from ..models import BusinessRow, WorkspaceRow
from ..remote_policy import formal_write_allowed
from ..source_case_policy import visible_project
from ..node_assignment.config import NodeAssignmentConfig
from ..node_assignment.errors import Failure
from ..node_assignment.lark_table import BitableClient, Table, Kind, canon, LARK_TYPES
from ..node_assignment.roster import fetch_roster
from .. import storage
from .models import LocalTask, TaskNodeLink, TaskEvent, LarkOutbox, LarkReconcile
from .outbox import latest, enqueue_all
from .domain import NODE_MAP
from .quote_facts import case_facts

BASE = 'H7W6b0PFWaVF1BsgqXJj3pQ9pXb'
TABLE = 'tbl28TBWLqd2Stg0'
APP_ID = 'cli_aa3cab98b2789e17'
# IDs record the approved schema discovery. Requests use names so renames fail closed.
FIELDS = {
    '同步鍵': ('fldsnvG5du', Kind.TEXT), '專案編號': ('fld5nnQyvx', Kind.TEXT),
    '案件名稱': ('fldsDgBjYG', Kind.TEXT), '確認單編號': ('fldTgZSbMb', Kind.TEXT),
    '報價編號': ('fldCOPbfbM', Kind.TEXT), '標題': ('fld47ey1sI', Kind.TEXT),
    '節點': ('fld6r92CNw', Kind.MULTI), '共用': ('fldcabXKv3', Kind.CHECKBOX),
    '狀態': ('fldFL4jpZl', Kind.SELECT), '適用性': ('fldaBQ09I9', Kind.SELECT),
    '負責人': ('fldnZIoDBn', Kind.USERS), '參與者': ('fldHXdjDsm', Kind.USERS),
    '截止日': ('fldnI6Mypa', Kind.DATE), '來源列': ('fldNFr7iWD', Kind.TEXT),
    '本地版本': ('fld8Prfsf2', Kind.NUMBER), '投影指紋': ('fldqZs5sWv', Kind.TEXT),
    '投影時間': ('fldaa9AthX', Kind.DATE), '開啟連結': ('fldQVN3UVV', Kind.TEXT),
}
NODE_LABELS = dict(zip(NODE_MAP.values(), ('報價', 'PM 派工', '確認單', '外業', '控制', '圖資', '報告', '計價請款', '入帳結算')))
STATES = dict(zip(('pending', 'in_progress', 'blocked', 'done', 'archived'), ('待處理', '進行中', '受阻', '已完成', '已封存')))
APPLICABILITY = dict(zip(('applicable', 'not_applicable', 'unresolved'), ('適用', '不適用', '待確認')))
log = logging.getLogger(__name__)


def excluded(state, project):
    return not visible_project(state, project)


def gates(cfg, wid, state):
    org = cfg.get('LARK_WORKER_ORGANIZATION')
    return (str(cfg.get('SOP_LARK_PROJECTION_ENABLED', 'false')).lower() == 'true'
            and state.get('settings', {}).get('external_enabled') is True
            and bool(org) and wid == 'lark-' + org and state.get('environment') == 'production'
            and cfg.get('LARK_APP_ID') == APP_ID and bool(cfg.get('LARK_APP_SECRET'))
            and cfg.get('LARK_WORKER_IDENTITY') == 'application'
            and formal_write_allowed(BASE, TABLE))


def sync_key(pid, tid, generation):
    return f'sop1|{pid}|{tid}|g{generation}'


def client_token(wid, pid, tid, generation):
    raw = hashlib.sha256(json.dumps([wid, pid, tid, generation], separators=(',', ':')).encode()).digest()[:16]
    return str(UUID(bytes=raw, version=4))


def fingerprint(values):
    owned = {name: canon(kind, values.get(name)) for name, (_, kind) in FIELDS.items()
             if name not in {'投影時間', '投影指紋'}}
    return hashlib.sha256(json.dumps(owned, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def payload(task, links, project, state, generation, roster, cfg, clock):
    facts = case_facts(project, state, datetime.fromtimestamp(clock).date())
    def people(ids):
        return [{'id': ident} for ident in sorted(set(ids)) if roster.person(ident) is not None]
    keys = {link.node_key for link in links}
    due = task.local.get('due_date')
    values = {'同步鍵': sync_key(task.project_id, task.id, generation), '專案編號': task.project_id,
              '案件名稱': project.get('name') or '',
              '確認單編號': project.get('code') or '' if project.get('case_type') != 'intake' else '',
              '報價編號': '、'.join(facts.quote_nos), '標題': task.title,
              '節點': [label for key, label in NODE_LABELS.items() if key in keys],
              '共用': task.instance_scope != 'case' or len(keys) > 1,
              '狀態': STATES[task.state.value], '適用性': APPLICABILITY[task.applicability.value],
              '負責人': people([task.participants.get('executor', '')]),
              '參與者': people(task.participants.values()),
              '截止日': int(datetime.fromisoformat(due + 'T00:00:00+08:00').timestamp() * 1000) if due else None,
              '來源列': task.source_row_key, '本地版本': task.revision,
              '投影時間': int(clock * 1000),
              '開啟連結': str(cfg.get('PUBLIC_ORIGIN') or cfg.get('APP_URL') or '').rstrip('/') + '/#view=project&project=' + quote(task.project_id, safe='') + '&tab=flow'}
    values['投影指紋'] = fingerprint(values)
    return values


def check_schema(client):
    present = {}
    for field in client.fields(Table.TASKS):
        present.setdefault(field.get('field_name'), []).append(field)
    broken = []
    for name, (ident, kind) in FIELDS.items():
        found = present.get(name, [])
        if len(found) != 1 or found[0].get('field_id') != ident or found[0].get('type') not in LARK_TYPES[kind]:
            broken.append(name)
        elif name == '節點' and found[0]['type'] != 4:
            broken.append(name)
        elif kind is Kind.USERS and found[0].get('property', {}).get('multiple') is not True:
            broken.append(name)
    if broken:
        raise Failure('schema_drift', 'SOP任務欄位已改名或型別不符', fields=broken)


class ProjectionClient(BitableClient):
    def __init__(self, cfg, transport=None, **kwargs):
        super().__init__(cfg, replace(NodeAssignmentConfig(), task_table=TABLE), transport, **kwargs)

    def search_value(self, name, value):
        records = self.search(Table.TASKS, [{'field_name': name, 'operator': 'is', 'value': [value]}], field_names=FIELDS)
        if any(canon(Kind.TEXT, r.get('fields', {}).get(name)) != value for r in records):
            raise Failure('lark_error', 'SOP任務搜尋結果不符')
        return records

    def _writable(self, table):
        if table is not Table.TASKS:
            raise Failure('writes_disabled', 'SOP 投影僅能寫入 SOP任務')
        super()._writable(table)


@contextmanager
def drain_lock(engine):
    if engine.dialect.name == 'postgresql':
        with engine.connect() as connection:
            acquired = connection.execute(sql_text('SELECT pg_try_advisory_lock(1971412084)')).scalar()
            try:
                yield acquired
            finally:
                if acquired:
                    connection.execute(sql_text('SELECT pg_advisory_unlock(1971412084)'))
    else:
        digest = hashlib.sha256(str(engine.url).encode()).hexdigest()
        with open(Path(tempfile.gettempdir()) / ('sop-projection-' + digest + '.lock'), 'a') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            try:
                yield True
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


class Projection:
    def __init__(self, sessions, cfg, load_state, *, transport=None, client_factory=None, clock=time.time):
        self.sessions, self.cfg, self.load_state, self.clock = sessions, cfg, load_state, clock
        self.client_factory = client_factory or (lambda before: ProjectionClient(cfg, transport, before_write=before))
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = None
        self._case_retry = {}

    def state(self, wid):
        return self.load_state(wid)

    def allowed(self, wid):
        return gates(self.cfg, wid, self.state(wid))

    def before_write(self, wid, pid, state=None):
        state = self.state(wid) if state is None else state
        project = next((p for p in state.get('projects', []) if p['id'] == pid), None)
        if not gates(self.cfg, wid, state) or project is None or excluded(state, project):
            raise Failure('writes_disabled', 'SOP 投影未啟用')

    def status(self, db, ctx, task):
        row = latest(db, ctx.wid, task.project_id, task.id)
        enabled = gates(self.cfg, ctx.wid, ctx.state) and not excluded(ctx.state, ctx.project)
        state = ('未啟用' if not enabled else '同步失敗' if row and row.last_error else
                 'Lark 已變更' if row and row.drift else '已同步' if row and row.state == 'done' else '同步中')
        return {'state': state, 'synced_at': row.synced_at if row else None, 'record_id': row.record_id if row else None,
                'base_id': BASE, 'table_id': TABLE, 'error': row.last_error if row else None}

    def request_reconcile(self, wid, pid):
        with self.sessions() as db:
            row = db.get(LarkReconcile, (wid, pid))
            if row and row.checked_at > self.clock() - 600:
                return
        self._wake.set()

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name='sop-lark-projection', daemon=True)
            self._thread.start()

    def close(self):
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self):
        while not self._stop.is_set():
            try:
                self.drain()
            except Exception:
                log.error('sop_projection drain failed; retrying on next run')
            self._wake.wait(30)
            self._wake.clear()

    def drain(self, *, project_id=None, limit=50):
        engine = self.sessions.kw['bind']
        with drain_lock(engine) as acquired:
            if not acquired:
                return False
            with self.sessions() as db:
                query = select(LarkOutbox.workspace_id, LarkOutbox.project_id).distinct()
                if project_id:
                    query = query.where(LarkOutbox.project_id == project_id)
                cases = list(db.execute(query))
            states = {}
            for wid, pid in cases:
                if (str(self.cfg.get('SOP_LARK_PROJECTION_ENABLED', 'false')).lower() != 'true'
                        or not self.cfg.get('LARK_WORKER_ORGANIZATION')
                        or wid != 'lark-' + self.cfg['LARK_WORKER_ORGANIZATION']
                        or self._case_retry.get((wid, pid), (0, 0))[0] > self.clock()):
                    continue
                try:
                    if wid not in states:
                        states[wid] = self.state(wid)
                    state = states[wid]
                    if not gates(self.cfg, wid, state):
                        continue
                    project = next((p for p in state.get('projects', []) if p['id'] == pid), None)
                    if project is None:
                        with self.sessions.begin() as db:
                            for row in self.current_rows(db, wid, pid):
                                row.state, row.last_error = 'paused', 'case_not_found'
                        continue
                    if excluded(state, project):
                        continue
                    with self.sessions() as db:
                        rows = self.current_rows(db, wid, pid)
                        receipt = db.get(LarkReconcile, (wid, pid))
                        pending = any(r.state not in {'done', 'paused'} and r.retry_at <= self.clock() for r in rows)
                        if not pending and receipt and receipt.checked_at > self.clock() - 600:
                            continue
                    with self.client_factory(lambda: self.before_write(wid, pid, state)) as client:
                        check_schema(client)
                        roster = fetch_roster(client)
                        with self.sessions.begin() as db:
                            for row in self.current_rows(db, wid, pid):
                                if row.state == 'paused' and (row.last_error or '').startswith('schema_drift'):
                                    row.state, row.last_error = 'none', None
                    with self.sessions() as db:
                        eligible = [r for r in self.current_rows(db, wid, pid)
                                    if r.state not in {'done', 'paused'} and r.retry_at <= self.clock()]
                        pending = [r.task_id for r in sorted(eligible, key=lambda r: (r.synced_at is not None, r.attempts, r.task_id))][:min(limit, 50)]
                    for tid in pending:
                        if self._stop.is_set():
                            return True
                        with self.client_factory(lambda: self.before_write(wid, pid, state)) as client:
                            self.project_task(client, wid, pid, tid, project, state, roster)
                    with self.client_factory(lambda: self.before_write(wid, pid, state)) as client:
                        report = self.reconcile(client, wid, pid, project, state, roster)
                    remaining = max(0, min(limit, 50) - len(pending))
                    for issue in [i for i in report['issues'] if i['kind'] == 'lark_drift'][:remaining]:
                        with self.client_factory(lambda: self.before_write(wid, pid, state)) as client:
                            self.project_task(client, wid, pid, issue['task_id'], project, state, roster)
                    self._case_retry.pop((wid, pid), None)
                except Exception as exc:
                    code = exc.code if isinstance(exc, Failure) else 'case_error'
                    attempts = self._case_retry.get((wid, pid), (0, 0))[1] + 1
                    retry_at = self.clock() + 2 ** min(attempts, 9)
                    self._case_retry[(wid, pid)] = (retry_at, attempts)
                    with self.sessions.begin() as db:
                        for row in self.current_rows(db, wid, pid):
                            if row.state == 'done' or row.state == 'paused' and not (row.last_error or '').startswith('schema_drift'):
                                continue
                            row.last_error = code + (': ' + ','.join(exc.extra['fields']) if isinstance(exc, Failure) and 'fields' in exc.extra else '')
                            row.retry_at = retry_at
                            if code == 'schema_drift':
                                row.state = 'paused'
                    log.warning('sop_projection case deferred project=%s reason=%s', pid, code, exc_info=True)
            return True

    @staticmethod
    def current_rows(db, wid, pid):
        found = {}
        for row in db.scalars(select(LarkOutbox).where(LarkOutbox.workspace_id == wid, LarkOutbox.project_id == pid)
                              .order_by(LarkOutbox.generation)):
            found[row.task_id] = row
        return list(found.values())

    def values(self, db, wid, pid, tid, project, state, roster, generation):
        task = db.get(LocalTask, (wid, tid))
        links = list(db.scalars(select(TaskNodeLink).where(TaskNodeLink.workspace_id == wid, TaskNodeLink.task_id == tid)))
        return payload(task, links, project, state, generation, roster, self.cfg, self.clock())

    def project_task(self, client, wid, pid, tid, project, state, roster):
        with self.sessions.begin() as db:
            row = latest(db, wid, pid, tid)
            values = self.values(db, wid, pid, tid, project, state, roster, row.generation)
            row.target_revision = values['本地版本']
            generation, rid = row.generation, row.record_id
            stored_rid, stored_operation = rid, False
            if not rid:
                row.state = 'sent'
                row.first_sent_at = row.first_sent_at or self.clock()
            row.attempts += 1
        try:
            found = client.search_value('同步鍵', values['同步鍵'])
            if len(found) > 1:
                self.pause(wid, pid, tid, 'duplicate_sync_key')
                return
            if rid and found and found[0]['record_id'] != rid:
                self.pause(wid, pid, tid, 'record_id_conflict')
                return
            if not rid:
                rid = found[0]['record_id'] if found else client.create(Table.TASKS, values, client_token(wid, pid, tid, generation))
                with self.sessions.begin() as db:
                    latest(db, wid, pid, tid).record_id = rid
            else:
                stored_operation = True
                record = client.get(Table.TASKS, rid)
                with self.sessions.begin() as db:
                    self.record_drift(db, latest(db, wid, pid, tid), record)
            # An idempotent create can return an earlier payload after a concurrent local edit.
            client.update(Table.TASKS, rid, values)
            verified = client.get(Table.TASKS, rid)
            if fingerprint(verified['fields']) != values['投影指紋'] or canon(Kind.TEXT, verified['fields'].get('投影指紋')) != values['投影指紋']:
                raise Failure('readback_mismatch', 'SOP 投影讀回未確認')
            self.complete(wid, pid, tid, values)
        except Failure as exc:
            deleted = False
            if stored_operation and stored_rid and exc.extra.get('lark_code') == 1254043:
                try:
                    client.get(Table.TASKS, stored_rid)
                except Failure as confirm:
                    deleted = confirm.extra.get('lark_code') == 1254043
            if deleted:
                with self.sessions.begin() as db:
                    row = latest(db, wid, pid, tid)
                    row.state, row.last_error = 'done', 'lark_row_deleted'
                    db.add(LarkOutbox(workspace_id=wid, project_id=pid, task_id=tid, generation=generation + 1,
                                      target_revision=row.target_revision, state='none'))
                return
            if rid and exc.code == 'outcome_unknown':
                try:
                    record = client.get(Table.TASKS, rid)
                    if fingerprint(record['fields']) == values['投影指紋'] and canon(Kind.TEXT, record['fields'].get('投影指紋')) == values['投影指紋']:
                        self.complete(wid, pid, tid, values)
                        return
                except Failure:
                    pass
            with self.sessions.begin() as db:
                row = latest(db, wid, pid, tid)
                row.last_error = exc.code
                if exc.code == 'readback_mismatch' and row.attempts >= 3:
                    row.state = 'paused'
                row.retry_at = self.clock() + min(600, 2 ** min(row.attempts, 9))
            log.warning('sop_projection task deferred project=%s task=%s reason=%s', pid, tid, exc.code)

    def complete(self, wid, pid, tid, values):
        with self.sessions.begin() as db:
            row = latest(db, wid, pid, tid)
            task = db.get(LocalTask, (wid, tid))
            revision = values['本地版本']
            where = (LarkOutbox.workspace_id == wid, LarkOutbox.project_id == pid,
                     LarkOutbox.task_id == tid, LarkOutbox.generation == row.generation)
            metadata = {'synced_at': self.clock(), 'last_fingerprint': values['投影指紋']}
            result = db.execute(update(LarkOutbox).where(*where, LarkOutbox.target_revision == revision).values(
                **metadata, state='done' if task.revision == revision else 'none', last_error=None,
                retry_at=0, attempts=0).execution_options(synchronize_session=False))
            if not result.rowcount:
                db.execute(update(LarkOutbox).where(*where).values(**metadata).execution_options(synchronize_session=False))

    def pause(self, wid, pid, tid, reason):
        with self.sessions.begin() as db:
            row = latest(db, wid, pid, tid)
            row.state, row.last_error = 'paused', reason
        log.error('sop_projection task paused project=%s task=%s reason=%s', pid, tid, reason)

    @staticmethod
    def remote_changed(row, record):
        return bool(row.last_fingerprint) and (
            fingerprint(record['fields']) != row.last_fingerprint
            or canon(Kind.TEXT, record['fields'].get('投影指紋')) != row.last_fingerprint)

    def record_drift(self, db, row, record):
        if not self.remote_changed(row, record):
            return False
        db.add(TaskEvent(workspace_id=row.workspace_id, project_id=row.project_id, task_id=row.task_id,
                         id=str(uuid4()), actor_id='sop_projection', at=self.clock(), kind='lark_drift',
                         revision=row.target_revision, changes={'record_id': record['record_id'],
                         'lark_values': {name: record['fields'].get(name) for name in FIELDS}}))
        row.drift = True
        return True

    def reconcile(self, client, wid, pid, project, state, roster, *, readonly=False):
        records = client.search_value('專案編號', pid)
        grouped = {}
        for record in records:
            grouped.setdefault(canon(Kind.TEXT, record['fields'].get('同步鍵')), []).append(record)
        issues = []
        by_id = {record['record_id']: record for record in records}
        with self.sessions.begin() as db:
            rows = self.current_rows(db, wid, pid)
            known = {sync_key(pid, row.task_id, row.generation): row for row in rows}
            for key, found in grouped.items():
                if key not in known:
                    issues.append({'kind': 'unknown_sync_key', 'key': key, 'record_ids': [r['record_id'] for r in found]})
                if len(found) > 1:
                    issues.append({'kind': 'duplicate_sync_key', 'key': key, 'record_ids': [r['record_id'] for r in found]})
                    if key in known and not readonly:
                        known[key].state, known[key].last_error = 'paused', 'duplicate_sync_key'
            for key, row in known.items():
                found = grouped.get(key, [])
                if not found and row.record_id in by_id:
                    found = [by_id[row.record_id]]
                if not found:
                    issues.append({'kind': 'missing_row', 'key': key})
                    if row.state == 'done' and not readonly:
                        row.state = 'none'
                    continue
                if len(found) != 1 or row.state == 'paused':
                    continue
                record = found[0]
                values = self.values(db, wid, pid, row.task_id, project, state, roster, row.generation)
                if row.state == 'done' and self.remote_changed(row, record):
                    issues.append({'kind': 'lark_drift', 'key': key, 'task_id': row.task_id, 'record_id': record['record_id']})
                    if not readonly:
                        self.record_drift(db, row, record)
                        row.state = 'none'
                elif row.state == 'done' and values['投影指紋'] != row.last_fingerprint and not readonly:
                    row.state = 'none'
            if not readonly:
                receipt = db.get(LarkReconcile, (wid, pid))
                if receipt is None:
                    receipt = LarkReconcile(workspace_id=wid, project_id=pid)
                    db.add(receipt)
                receipt.checked_at, receipt.issues = self.clock(), issues
        return {'rows': records, 'issues': issues}


def main():
    parser = argparse.ArgumentParser(description='Inspect SOP projection or enqueue local backfill. Never writes to Lark.')
    parser.add_argument('--database-url', default=os.environ.get('DATABASE_URL'), required=not os.environ.get('DATABASE_URL'))
    parser.add_argument('--workspace', default='lark-' + os.environ.get('LARK_WORKER_ORGANIZATION', ''))
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check', metavar='PROJECT_ID')
    action.add_argument('--enqueue-all', action='store_true')
    args = parser.parse_args()
    engine = create_engine(args.database_url)
    sessions = sessionmaker(engine, expire_on_commit=False)
    def load(wid):
        with sessions() as db:
            return storage.load(db, BusinessRow, db.get(WorkspaceRow, wid))
    projection = Projection(sessions, dict(os.environ), load)
    if args.enqueue_all:
        print(json.dumps({'enqueued': enqueue_all(sessions)}))
        return
    state = load(args.workspace)
    project = next(p for p in state['projects'] if p['id'] == args.check)
    with sessions() as db:
        outbox = [{'task_id': r.task_id, 'generation': r.generation, 'state': r.state, 'last_error': r.last_error,
                   'record_id': r.record_id} for r in projection.current_rows(db, args.workspace, args.check)]
    report = {'outbox': outbox, 'remote': 'disabled'}
    if gates(projection.cfg, args.workspace, state) and not excluded(state, project):
        with projection.client_factory(lambda: (_ for _ in ()).throw(RuntimeError('read only'))) as client:
            check_schema(client)
            report['remote'] = projection.reconcile(client, args.workspace, args.check, project, state, fetch_roster(client), readonly=True)
    print(json.dumps(report, ensure_ascii=False, default=str))


if __name__ == '__main__':
    main()
