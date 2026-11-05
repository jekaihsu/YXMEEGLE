"""The two WorkspaceRow writers that used to bypass the version CAS (startup migration, index_health_run) run for real
against concurrent ops_sync writes. Isolated SQLite files, synthetic data. PostgreSQL is UNTESTED.
"""
import json
import threading
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update

from . import storage
from .app import create_app
from .models import BusinessRow, ProjectIndex, WorkspaceRow
from .ops_sync.workspace_store import WorkspaceStore
from .perf_fixture import build_scaled_workspace
from .policy import upgrade
from .workspace_migration import WorkspaceMigrationBusy, migrate_workspaces

WID = 'demo-w'
OPS = {'ops_sync': {'commands': {'c0': {'state': 'confirmed'}}, '_commit_seq': 1}}


def legacy_db(tmp_path, extra=None, version=7):
    """A pre-storage-schema-2 workspace row carrying ops_sync state and an unrelated sentinel key."""
    app = create_app({'DATABASE_URL': f'sqlite:///{tmp_path}/m.db', 'UPLOAD_DIR': str(tmp_path / 'u'), 'SESSION_SECRET': 'x' * 40,
                      'APP_ENV': 'development', 'DEMO_MODE': 'true', 'LARK_APP_ID': '', 'LARK_APP_SECRET': '', 'LARK_ALLOWED_TENANTS': ''})
    sessions = app.state.sessions
    data = {k: v for k, v in upgrade(build_scaled_workspace(3)).items()}
    data.pop('storage_schema', None)
    data.update(deepcopy(OPS), sentinel={'keep': '日本語 🚀'}, version=version, **(extra or {}))
    with sessions.begin() as db:
        for row in db.scalars(select(WorkspaceRow)):
            db.delete(row)
    with sessions.begin() as db:
        db.execute(delete(BusinessRow))
        db.add(WorkspaceRow(id=WID, version=version, data=data))
    return app, sessions, data


def ops_bump(sessions, label):
    WorkspaceStore(sessions, WID).transact(lambda ns: ns.setdefault('log', []).append(label))


def row(sessions):
    with sessions() as db:
        r = db.get(WorkspaceRow, WID)
        return r.version, deepcopy(r.data)


def test_startup_migration_cas_bumps_version_and_keeps_ops_and_unrelated_keys(tmp_path):
    app, sessions, _ = legacy_db(tmp_path)
    assert migrate_workspaces(sessions, WorkspaceRow, BusinessRow, upgrade, storage) == [WID]
    version, data = row(sessions)
    assert version == 8 and data['version'] == 8 and data['storage_schema'] == 2
    assert data['ops_sync'] == OPS['ops_sync'] and data['sentinel'] == {'keep': '日本語 🚀'}
    assert migrate_workspaces(sessions, WorkspaceRow, BusinessRow, upgrade, storage) == []      # idempotent: no write, no bump
    assert row(sessions)[0] == 8
    app.state.engine.dispose()


def test_ops_write_landing_between_migration_read_and_update_is_not_clobbered(tmp_path):
    app, sessions, _ = legacy_db(tmp_path)
    fired = []

    def hook(name):
        if name == 'after_read' and not fired:
            fired.append(1)
            ops_bump(sessions, 'raced')                    # a real ops_sync commit between the migration's read and its UPDATE
    assert migrate_workspaces(sessions, WorkspaceRow, BusinessRow, upgrade, storage, hook=hook) == [WID]
    version, data = row(sessions)
    assert data['ops_sync']['log'] == ['raced'] and data['ops_sync']['commands'] == OPS['ops_sync']['commands']
    assert data['storage_schema'] == 2 and data['sentinel'] == {'keep': '日本語 🚀'}
    assert version == 9 and data['version'] == 9           # raced ops commit (8) + the migration's re-read-and-retry (9)
    app.state.engine.dispose()


def test_migration_failing_closed_when_the_row_never_stops_changing(tmp_path):
    app, sessions, _ = legacy_db(tmp_path)
    with pytest.raises(WorkspaceMigrationBusy):
        migrate_workspaces(sessions, WorkspaceRow, BusinessRow, upgrade, storage, max_attempts=3, hook=lambda name: ops_bump(sessions, 'x') if name == 'after_read' else None)
    version, data = row(sessions)
    assert data.get('storage_schema') != 2 and len(data['ops_sync']['log']) == 3     # nothing half-migrated, nothing lost
    app.state.engine.dispose()


def test_migration_clears_leftover_archive_rows_with_cas_too(tmp_path):
    app, sessions, _ = legacy_db(tmp_path)
    migrate_workspaces(sessions, WorkspaceRow, BusinessRow, upgrade, storage)
    with sessions.begin() as db:                           # simulate a row that still carries an inline migration_archive
        r = db.get(WorkspaceRow, WID)
        data = deepcopy(r.data)
        data['migration_archive'] = {'old': True}
        db.execute(update(WorkspaceRow).where(WorkspaceRow.id == WID).values(data=data))
    fired = []

    def hook(name):
        if name == 'after_read' and not fired:
            fired.append(1)
            ops_bump(sessions, 'raced')
    assert migrate_workspaces(sessions, WorkspaceRow, BusinessRow, upgrade, storage, hook=hook) == [WID]
    _, data = row(sessions)
    assert 'migration_archive' not in data and data['ops_sync']['log'] == ['raced']
    app.state.engine.dispose()


def test_booting_the_real_app_on_a_legacy_row_preserves_ops_state(tmp_path):
    app, sessions, _ = legacy_db(tmp_path)
    url = f'sqlite:///{tmp_path}/m.db'
    app.state.engine.dispose()
    app2 = create_app({'DATABASE_URL': url, 'UPLOAD_DIR': str(tmp_path / 'u'), 'SESSION_SECRET': 'x' * 40, 'APP_ENV': 'development',
                       'DEMO_MODE': 'true', 'LARK_APP_ID': '', 'LARK_APP_SECRET': '', 'LARK_ALLOWED_TENANTS': ''})
    version, data = row(app2.state.sessions)
    assert version == 8 and data['ops_sync'] == OPS['ops_sync'] and data['sentinel'] == {'keep': '日本語 🚀'}
    app2.state.engine.dispose()


def test_deliberate_failure_the_old_unversioned_migration_loses_the_racing_ops_write(tmp_path):
    """Re-creates the removed loop (ORM `row.data = ...`, no version predicate). The racing-write test MUST fail against it."""
    app, sessions, _ = legacy_db(tmp_path)
    with sessions.begin() as db:
        for r in db.scalars(select(WorkspaceRow)):
            state = upgrade(deepcopy(r.data))
            state.setdefault('migration_archive', deepcopy(r.data))
            ops_bump(app.state.sessions, 'raced')          # lands after the read, before the flush: the old unprotected window
            r.data = storage.save(db, BusinessRow, r.id, state)
    _, data = row(sessions)
    assert 'log' not in data['ops_sync'], 'old writer was expected to clobber the ops commit'
    app.state.engine.dispose()


# -- index_health_run -----------------------------------------------------------------------------------------------
def booted(tmp_path):
    app = create_app({'DATABASE_URL': f'sqlite:///{tmp_path}/h.db', 'UPLOAD_DIR': str(tmp_path / 'u'), 'SESSION_SECRET': 'x' * 40,
                      'APP_ENV': 'development', 'DEMO_MODE': 'true', 'INDEX_TABLES_ENABLED': 'true', 'LARK_APP_ID': '',
                      'LARK_APP_SECRET': '', 'LARK_ALLOWED_TENANTS': ''})
    client = TestClient(app)
    client.__enter__()
    client.get('/api/session')
    wid = app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
    with app.state.sessions.begin() as db:
        r = db.get(WorkspaceRow, wid)
        state = upgrade(build_scaled_workspace(8))
        state.update(deepcopy(OPS), sentinel={'keep': '日本語 🚀'})
        state['version'] = r.version + 1
        r.version = state['version']
        r.data = storage.save(db, BusinessRow, wid, state)
    assert client.post('/api/demo/session', json={'user_id': 'u-manager'}).status_code == 200
    return app, client, wid


def test_index_health_check_and_repair_never_change_workspace_row_data(tmp_path):
    app, client, wid = booted(tmp_path)
    try:
        sessions = app.state.sessions
        before = row_of(sessions, wid)
        assert client.get('/api/admin/index-health').json()['healthy']
        assert row_of(sessions, wid) == before                                  # read-only check: row untouched
        with sessions.begin() as db:
            db.execute(update(ProjectIndex).where(ProjectIndex.project_id == 'p002').values(status='bogus'))
        assert client.post('/api/admin/index-health/repair').json()['repaired']
        after = row_of(sessions, wid)
        assert after[1] == before[1] and after[0] == before[0]                  # same data, same version: lock-only touch
        assert after[1]['ops_sync'] == OPS['ops_sync'] and after[1]['sentinel'] == {'keep': '日本語 🚀'}
    finally:
        client.__exit__(None, None, None)
        app.state.engine.dispose()


def row_of(sessions, wid):
    with sessions() as db:
        r = db.get(WorkspaceRow, wid)
        return r.version, json.loads(json.dumps(r.data))


def test_index_health_repair_racing_real_ops_writes_loses_nothing(tmp_path):
    app, client, wid = booted(tmp_path)
    errors, statuses = [], []
    try:
        sessions = app.state.sessions
        store = WorkspaceStore(sessions, wid, max_attempts=200)

        def ops_writer():
            try:
                for i in range(40):
                    store.transact(lambda ns, i=i: ns.setdefault('log', []).append(i))
            except BaseException as exc:   # noqa: BLE001 - surfaced below
                errors.append(exc)
        thread = threading.Thread(target=ops_writer)
        thread.start()
        for _ in range(25):
            with sessions.begin() as db:
                db.execute(update(ProjectIndex).where(ProjectIndex.project_id == 'p002').values(status='bogus'))
            statuses.append(client.post('/api/admin/index-health/repair').status_code)
        thread.join(120)
        assert not thread.is_alive() and not errors, errors
        assert set(statuses) <= {200, 409}
        version, data = row_of(sessions, wid)
        assert data['ops_sync']['log'] == list(range(40))                        # no ops write lost, none duplicated
        assert data['ops_sync']['commands'] == OPS['ops_sync']['commands'] and data['sentinel'] == {'keep': '日本語 🚀'}
        assert data['version'] == version
    finally:
        client.__exit__(None, None, None)
        app.state.engine.dispose()


def test_control_unversioned_stale_write_is_detected_by_the_same_assertions(tmp_path):
    """Control for the two tests above: a stale-read, unversioned `data` write (what a non-cooperating writer would do) IS caught."""
    app, client, wid = booted(tmp_path)
    try:
        sessions = app.state.sessions
        with sessions.begin() as db:
            r = db.get(WorkspaceRow, wid)
            stale = deepcopy(r.data)
        WorkspaceStore(sessions, wid).transact(lambda ns: ns.setdefault('log', []).append('raced'))
        with sessions.begin() as db:
            db.execute(update(WorkspaceRow).where(WorkspaceRow.id == wid).values(data=stale))   # unversioned write from stale read
        assert 'log' not in row_of(sessions, wid)[1]['ops_sync']
    finally:
        client.__exit__(None, None, None)
        app.state.engine.dispose()
