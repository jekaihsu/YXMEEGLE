"""Version-CAS `OpsStore` over the existing `workspaces` row (id, version, data JSON). No new schema.

`transact(fn)` reads `(version, data)`, runs `fn` on a private copy of the `ops_sync` namespace only, and writes the
row back with `UPDATE ... WHERE id=? AND version=?`, bumping `version` exactly like `app.persist_mutation` does (and
mirroring it into `data['version']`, which the app serves to clients). A CAS miss means another writer committed first:
the row is re-read and `fn` is re-run, a bounded number of times, then the store fails closed with `StorageBusy`.

Why this is safe against the app's writers: they use the same `WHERE version=?` CAS, so an ops commit between their read
and their UPDATE makes them miss (their existing 409 path) instead of overwriting `ops_sync`, and an app commit between
ours makes us re-read instead of overwriting their state. Every other key of `data` is carried over untouched.

Proven on SQLite only. PostgreSQL is UNTESTED (no PostgreSQL in the verification environment).
"""
import copy
import json
import random
import time

from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError

from .store import NAMESPACE, StorageBlocked, StorageBusy

BARRIERS = ('before_update', 'updated', 'committed')


class WorkspaceStore:
    durable = True

    def __init__(self, sessions, wid, namespace=NAMESPACE, model=None, hook=None, max_attempts=8, backoff=0.005):
        if model is None:
            from ..models import WorkspaceRow as model
        self.sessions, self.wid, self.namespace, self.model = sessions, wid, namespace, model
        self.hook, self.max_attempts, self.backoff = hook, max_attempts, backoff

    def _barrier(self, name):
        if self.hook:
            self.hook(name)

    # -- committed row ---------------------------------------------------------------------------------------------
    def _read(self, db):
        m = self.model
        try:
            row = db.execute(select(m.version, m.data).where(m.id == self.wid)).one_or_none()
        except ValueError:                     # undecodable JSON text in the column
            raise StorageBlocked('workspace data is not valid JSON; refusing to reset') from None
        if row is None:
            raise StorageBlocked(f'workspace {self.wid!r} does not exist; the ops store never creates it')
        version, data = row
        if isinstance(version, bool) or not isinstance(version, int):
            raise StorageBlocked('workspace row version is not an integer; refusing to write')
        if not isinstance(data, dict):
            raise StorageBlocked('workspace data is not an object; refusing to reset')
        ns = data.get(self.namespace, {})
        if not isinstance(ns, dict):
            raise StorageBlocked(f'namespace {self.namespace!r} is not an object')
        return version, data, ns

    # -- public API ------------------------------------------------------------------------------------------------
    def snapshot(self):
        with self.sessions() as db:
            return copy.deepcopy(self._read(db)[2])

    def snapshot_raw(self):
        with self.sessions() as db:
            return copy.deepcopy(self._read(db)[1])

    def transact(self, fn):
        for attempt in range(1, self.max_attempts + 1):
            try:
                done, result = self._attempt(fn)
            except OperationalError as exc:       # SQLite writer lock held past its timeout: treat as a CAS miss
                if 'locked' not in str(exc).lower() and 'busy' not in str(exc).lower():
                    raise
                done = False
            if done:
                return result
            if attempt < self.max_attempts and self.backoff:
                time.sleep(random.uniform(0, self.backoff * attempt))
        raise StorageBusy(f'workspace {self.wid!r} changed under {self.max_attempts} consecutive attempts')

    def _attempt(self, fn):
        with self.sessions.begin() as db:
            version, data, ns = self._read(db)
            work = copy.deepcopy(ns)
            result = fn(work)
            if work == ns:
                return True, result                # nothing to persist: no write, no version bump
            work['_commit_seq'] = ns.get('_commit_seq', 0) + 1
            new = dict(data)
            new[self.namespace] = work
            if 'version' in new:
                new['version'] = version + 1       # the app serves data['version'] and checks it against row.version
            json.dumps(new, ensure_ascii=False)    # unserialisable state raises here, before any write
            self._barrier('before_update')
            m = self.model
            hit = db.execute(update(m).where(m.id == self.wid, m.version == version).values(version=version + 1, data=new)).rowcount
            if hit != 1:
                return False, None                 # CAS miss: nothing was written; the caller re-reads
            self._barrier('updated')               # UPDATE executed, COMMIT not yet issued
        self._barrier('committed')
        return True, result


def ops_store_factory(flags, sessions, **kw):
    """The store the local feature path uses. Returns None unless FEATURE_LARK_AUTHORITATIVE_OPS is on (default off)."""
    if not flags.lark_authoritative_ops:
        return None
    return lambda wid: WorkspaceStore(sessions, wid, **kw)
