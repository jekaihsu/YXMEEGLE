"""Startup normalisation of `workspaces` rows, written with the same version-CAS protocol as `persist_mutation`.

The original loop assigned `row.data` and let the ORM flush an UPDATE with no version predicate, so a concurrent
committed writer (another process starting up, or the ops_sync store) between this read and that flush was silently
overwritten, and the version never moved, so an in-flight client could not detect it either. Each row is now rewritten
with `UPDATE ... WHERE id=? AND version=?` and `version+1` (mirrored into `data['version']`, which clients are served).
A CAS miss rolls the whole attempt back (entity rows included), re-reads and recomputes, a bounded number of times,
then fails closed with `WorkspaceMigrationBusy` so the process refuses to start rather than overwrite.

Rows that are already normalised are left untouched (no write, no version bump). PostgreSQL is UNTESTED.
"""
from copy import deepcopy

from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError


class WorkspaceMigrationBusy(RuntimeError):
    pass


def needs_migration(data):
    return data.get('storage_schema') != 2 or 'migration_archive' in data


def migrate_workspaces(sessions, model, business_model, upgrade, storage, max_attempts=8, hook=None):
    """Normalise every workspace row; returns the ids actually rewritten. `hook(name)` is a test seam."""
    with sessions() as db:
        wids = list(db.scalars(select(model.id)))
    return [wid for wid in wids if _migrate_one(sessions, model, business_model, upgrade, storage, wid, max_attempts, hook)]


def _migrate_one(sessions, model, business_model, upgrade, storage, wid, max_attempts, hook):
    for _ in range(max_attempts):
        try:
            with sessions.begin() as db:
                row = db.get(model, wid)
                if row is None or not needs_migration(row.data):
                    return False
                version, data = row.version, row.data
                if hook:
                    hook('after_read')                     # SQLite: no write lock is held yet, so a real writer can commit here
                if data.get('storage_schema') != 2:
                    state = upgrade(deepcopy(data))
                    state.setdefault('migration_archive', deepcopy(data))
                else:
                    state = upgrade(storage.load(db, business_model, row))
                root = storage.save(db, business_model, wid, state)
                if 'version' in root:
                    root['version'] = version + 1          # the app serves data['version'] and checks it against row.version
                if hook:
                    hook('before_update')                  # (SQLite: our entity-row writes hold the lock by now)
                hit = db.execute(update(model).where(model.id == wid, model.version == version)
                                 .values(version=version + 1, data=root)).rowcount
                if hit != 1:
                    db.rollback()                          # someone committed first: discard entity-row changes too
                    continue
            return True
        except OperationalError as exc:                    # SQLite writer lock held past its timeout: same as a CAS miss
            if 'locked' not in str(exc).lower() and 'busy' not in str(exc).lower():
                raise
    raise WorkspaceMigrationBusy(f'workspace {wid!r} changed under {max_attempts} consecutive migration attempts')
