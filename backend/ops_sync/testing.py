"""Synthetic fixtures for ops_sync tests (no real people or production data)."""
import os
from datetime import datetime, timezone

from . import values as V
from .adapter import BINDING
from .commands import CommandEnvelope

NOW = datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc)


def env(command_id, field='case.deadline', expected=V.CLEAR, expected_revision=0, intended=V.SetValue('2026-10-20'),
        entity='case_test_1', actor='ou_test_pm_1', binding=BINDING, **extra):
    return CommandEnvelope(command_id, entity, field, expected, expected_revision, intended, actor, 'app', NOW, binding, **extra)


# -- store factories: the same suites run against every real durable OpsStore ---------------------------------
WID = 'test-ws-1'
STORE_KINDS = ('file', 'workspace')
STORE_BARRIERS = {'file': ('before_tmp_write', 'tmp_partial', 'tmp_written', 'tmp_fsynced', 'renamed', 'dir_fsynced'),
                  'workspace': ('before_update', 'updated', 'committed')}
STORE_LANDED = {'file': ('renamed', 'dir_fsynced'), 'workspace': ('committed',)}
COMMIT_START = ('before_tmp_write', 'before_update')       # first barrier of every commit attempt


def ws_path(directory, kind):
    return os.path.join(os.fspath(directory), 'ws.db' if kind == 'workspace' else 'ws.json')


def sqlite_sessions(path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    engine = create_engine(f'sqlite:///{path}', connect_args={'check_same_thread': False, 'timeout': 20})
    return sessionmaker(engine, expire_on_commit=False)


def seed_workspace(path, data=None, version=1, wid=WID):
    """Create the isolated SQLite file with the real `workspaces` table and one row (synthetic data only)."""
    from ..models import WorkspaceRow
    sessions = sqlite_sessions(path)
    WorkspaceRow.__table__.create(sessions.kw['bind'], checkfirst=True)
    with sessions.begin() as db:
        db.add(WorkspaceRow(id=wid, version=version, data={'version': version} if data is None else data))
    sessions.kw['bind'].dispose()


def open_store(kind, path, hook=None, **kw):
    if kind == 'workspace':
        from .workspace_store import WorkspaceStore
        if not os.path.exists(path):
            seed_workspace(path)
        return WorkspaceStore(sqlite_sessions(path), WID, hook=hook, **kw)
    from .store import JsonFileStore
    return JsonFileStore(path, hook=hook, **kw)


def app_style_write(sessions, mutate, wid=WID, retries=200, before_cas=None):
    """Mirror of app.persist_mutation's WorkspaceRow protocol (read version+data, mutate, UPDATE ... WHERE version=?
    with version+1 and the mirrored data['version']); a CAS miss is the app's 409, retried here. Returns attempts."""
    import copy

    from sqlalchemy import select, update

    from ..models import WorkspaceRow
    for attempt in range(1, retries + 1):
        with sessions.begin() as db:
            version, data = db.execute(select(WorkspaceRow.version, WorkspaceRow.data).where(WorkspaceRow.id == wid)).one()
            data = copy.deepcopy(data)
            mutate(data)
            data['version'] = version + 1
            if before_cas:
                before_cas(attempt)
            hit = db.execute(update(WorkspaceRow).where(WorkspaceRow.id == wid, WorkspaceRow.version == version)
                             .values(version=version + 1, data=data)).rowcount
        if hit == 1:
            return attempt
    raise AssertionError('app-style writer starved')


def raw_row(path, wid=WID):
    """(version, data-text) straight from sqlite3, bypassing SQLAlchemy and the store."""
    import sqlite3
    with sqlite3.connect(path) as conn:
        return conn.execute('select version, data from workspaces where id=?', (wid,)).fetchone()
