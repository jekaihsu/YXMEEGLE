"""Run the same requests through the full and the partial write path and compare every stored row.

Used by the equivalence tests and available to anyone adding an action to the registry.
Both apps start from one deterministic world; ids, clocks and audit ids are pinned so any
difference in what the two paths store (or answer) is a real difference.
"""
import itertools
import os
import tempfile
import uuid
from datetime import datetime, timezone, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text

from . import audit, mention_notifications, storage, workflow
from .app import create_app
from .models import (AuditRow, BusinessRow, Receipt, WorkspaceRow, ProjectIndex, TaskIndex, WorkspaceCounter)
from .write_world import WID, build_world

POSTGRES = os.environ.get('PARTIAL_WRITES_TEST_POSTGRES_URL') or os.environ.get('ACTION_AUDIT_TEST_POSTGRES_URL')
CLOCK = datetime(2026, 10, 15, 8, 0, 0, tzinfo=timezone(timedelta(hours=8)))


class PinnedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return CLOCK if tz is None else CLOCK.astimezone(tz)


class Pinned:
    """Ids and clocks that depend only on how many times the active rig asked for them."""
    active = None

    def __init__(self, monkeypatch):
        monkeypatch.setattr(workflow, 'uuid4', lambda: uuid.UUID(int=next(Pinned.active.uuids)))
        monkeypatch.setattr(workflow, 'datetime', PinnedDatetime)
        monkeypatch.setattr(audit, 'datetime', PinnedDatetime)
        monkeypatch.setattr(mention_notifications, 'datetime', PinnedDatetime)
        monkeypatch.setattr(audit.secrets, 'token_hex', lambda n=16: f'audit{next(Pinned.active.audits):027d}')


def database_url(tmp_path, name):
    if not POSTGRES: return f'sqlite:///{tmp_path}/{name}.db', lambda: None
    admin = create_engine(POSTGRES, isolation_level='AUTOCOMMIT')
    database = f'pw_{name}_{uuid.uuid4().hex[:8]}'
    with admin.connect() as c: c.execute(text(f'create database {database}'))
    url = create_engine(POSTGRES).url.set(database=database)
    def drop():
        with admin.connect() as c: c.execute(text(f'drop database {database} with (force)'))
    return url.render_as_string(hide_password=False), drop


class Rig:
    """One app on one database holding the world, driven through HTTP."""

    def __init__(self, tmp_path, name, *, partial, projects=40, extra=None, world=None):
        self.url, self.drop = database_url(tmp_path, name)
        cfg = {'DATABASE_URL': self.url, 'UPLOAD_DIR': tempfile.mkdtemp(), 'SESSION_SECRET': 'x' * 40, 'APP_ENV': 'development',
               'DEMO_MODE': 'true', 'INDEX_TABLES_ENABLED': 'true', 'WORKSPACE_SHELL_ENABLED': 'true', 'FEATURE_CHANGE_EXTENSION': 'true',
               'PARTIAL_WRITES_ENABLED': 'true' if partial else 'false', 'PARTIAL_WRITES_STRICT': 'true', **(extra or {})}
        self.app = create_app(cfg)
        self.world = world or build_world(projects)
        with self.app.state.sessions.begin() as db:
            row = WorkspaceRow(id=WID, version=1, data=self.world); db.add(row); db.flush()
            row.data = storage.save(db, BusinessRow, WID, self.world)
        self.client = TestClient(self.app, raise_server_exceptions=True)
        self.counter = itertools.count(1)
        self.uuids = itertools.count(1); self.audits = itertools.count(1)
        Pinned.active = self

    def version(self):
        with self.app.state.sessions() as db: return db.get(WorkspaceRow, WID).version

    def as_user(self, uid):
        Pinned.active = self
        self.client.cookies.set('meegle_session', self.app.state.signer.dumps({'mode': 'demo', 'uid': uid, 'wid': WID}))

    def act(self, user, action, *, version=None, request_id=None, project_versions=None, **fields):
        self.as_user(user)
        body = {'action': action, 'version': self.version() if version is None else version,
                'request_id': request_id or f'req-{next(self.counter)}', 'project_id': fields.get('project_id'),
                'node_id': fields.get('node_id'), 'task_id': fields.get('task_id'), 'payload': fields.get('payload', {})}
        if project_versions is not None: body['project_versions'] = project_versions
        return self.client.post('/api/actions', json=body)

    def get(self, user, path):
        self.as_user(user)
        return self.client.get(path)

    def project_version(self, pid):
        with self.app.state.sessions() as db:
            return db.get(BusinessRow, (WID, 'projects', pid)).data.get('concurrency_version', 0)

    def dump(self):
        """Every table a write may touch, as sorted plain data."""
        with self.app.state.sessions() as db:
            def rows(model, *keys):
                return sorted(([getattr(r, c.name) for c in model.__table__.columns] for r in db.scalars(select(model))), key=lambda v: [str(v[i]) for i in range(len(keys))])
            return {'workspaces': rows(WorkspaceRow, 'id'), 'business_records': rows(BusinessRow, 'workspace_id', 'kind', 'entity_id'),
                    'receipts': rows(Receipt, 'id'), 'action_audit': rows(AuditRow, 'id'),
                    'project_index': rows(ProjectIndex, 'workspace_id', 'project_id'), 'task_index': rows(TaskIndex, 'workspace_id', 'task_id'),
                    'workspace_counters': rows(WorkspaceCounter, 'workspace_id', 'key', 'subject_id')}

    def close(self):
        self.client.close(); self.app.state.engine.dispose(); self.drop()


def first_difference(full, partial):
    for table in full:
        if full[table] == partial[table]: continue
        left, right = full[table], partial[table]
        if len(left) != len(right): return f'{table}: {len(left)} rows on the full path, {len(partial[table])} on the partial path'
        for a, b in zip(left, right):
            if a != b:
                names = [c.name for c in {'workspaces': WorkspaceRow, 'business_records': BusinessRow, 'receipts': Receipt, 'action_audit': AuditRow,
                                         'project_index': ProjectIndex, 'task_index': TaskIndex, 'workspace_counters': WorkspaceCounter}[table].__table__.columns]
                columns = [n for n, x, y in zip(names, a, b) if x != y]
                return f'{table} {a[:3]}: columns {columns} differ\n  full:    {[x for n, x in zip(names, a) if n in columns]}\n  partial: {[y for n, y in zip(names, b) if n in columns]}'
    return None
