"""Sources sync stores the same rows whether or not it uses the cheaper partial paths.

Two identical workspaces take the same sequence of failures, scheduled attempts and
syncs, one with PARTIAL_WRITES_ENABLED off. After every step the workspace root, every
business row and the source cache must be equal.
"""
import itertools
from contextlib import ExitStack
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from . import audit, source_sync, storage, workflow
from .partial_testing import Pinned, PinnedDatetime
from .test_source_sync import built_harness, snapshot, records


@pytest.fixture
def twins(monkeypatch):
    monkeypatch.setattr(workflow, 'uuid4', lambda: __import__('uuid').UUID(int=next(Pinned.active.uuids)))
    monkeypatch.setattr(workflow, 'datetime', PinnedDatetime)
    with ExitStack() as stack:
        sides = []
        for partial in (False, True):
            Pinned.active = SimpleNamespace(uuids=itertools.count(10 ** 6), audits=itertools.count(1))
            sides.append(stack.enter_context(built_harness(monkeypatch, partial=partial)))
        for side in sides: side.pin = SimpleNamespace(uuids=itertools.count(1), audits=itertools.count(1))
        yield tuple(sides)


def dump(h):
    with h.sessions() as db:
        rows = lambda model, *cols: sorted(([getattr(r, c) for c in cols] for r in db.scalars(select(model))), key=str)
        return {'workspace': rows(h.W, 'id', 'version', 'data'), 'records': rows(h.B, 'kind', 'entity_id', 'parent_id', 'ordinal', 'data'),
                'cache': rows(h.C, 'id', 'data')}


def run(full, partial, step):
    outcomes = []
    for side in (full, partial):
        Pinned.active = side.pin
        try: outcomes.append(('ok', step(side)))
        except HTTPException as exc: outcomes.append(('http', exc.status_code, exc.detail))
    assert outcomes[0] == outcomes[1]
    a, b = dump(full), dump(partial)
    for table in a: assert a[table] == b[table], table
    return outcomes[0]


def advance(full, partial, clock):
    for side in (full, partial): side.clock[0] = clock


def test_a_failed_attempt_is_stored_identically(twins, monkeypatch):
    full, partial = twins
    advance(full, partial, '2026-09-27T10:05:00+08:00')
    calls = []
    for name in ('save', 'save_collections', 'load'):
        original = getattr(storage, name)
        monkeypatch.setattr(storage, name, lambda *a, _o=original, _n=name, **k: (calls.append(_n), _o(*a, **k))[1])
    run(full, partial, lambda h: h.service.failure(h.wid, 'Lark 暫時無法連線'))
    # full side: load + save; partial side: root-only save_collections and no whole-workspace load
    assert sorted(calls) == ['load', 'save', 'save_collections']
    run(full, partial, lambda h: h.service.failure(h.wid, '過期的嘗試', expected_generation=7))


def test_a_scheduled_attempt_and_the_syncs_it_starts_are_stored_identically(twins):
    full, partial = twins
    for clock in ('2026-09-27T10:02:00+08:00', '2026-09-27T10:10:00+08:00'):
        advance(full, partial, clock)
        for side in (full, partial): side.cfg['LARK_LIVE_READ_SOURCE_TTL_SECONDS'] = '120'
        run(full, partial, lambda h: (h.service.run_due(h.wid) or {}).get('status'))


@pytest.mark.parametrize('skip_unchanged', [False, True])
def test_unchanged_and_changed_snapshots_are_stored_identically(twins, skip_unchanged):
    full, partial = twins
    changed = records()
    changed[0]['fields']['狀態'] = '已結案'
    for clock, rows in (('2026-09-27T10:05:00+08:00', records()), ('2026-09-27T10:10:00+08:00', records()),
                        ('2026-09-27T10:15:00+08:00', changed), ('2026-09-27T10:20:00+08:00', changed)):
        advance(full, partial, clock)
        for side in (full, partial): side.service.fetcher = lambda token, c=clock, r=rows: snapshot(c, deepcopy(r))
        run(full, partial, lambda h: sorted(h.service.sync(h.wid, 'u-manager', 'fake', skip_unchanged=skip_unchanged))[:0])


def test_a_user_write_between_the_early_read_and_the_lock_forces_a_fresh_load(twins, monkeypatch):
    """The state read before the lock is used only when the version is still the one it was read at."""
    full, partial = twins
    advance(full, partial, '2026-09-27T10:05:00+08:00')
    for side in (full, partial): side.service.fetcher = lambda token: snapshot('2026-09-27T10:05:00+08:00', records())
    prepared = partial.service._prepare
    def prepare_then_write(*args, **kwargs):
        result = prepared(*args, **kwargs)
        with partial.sessions.begin() as db:
            row = db.get(partial.W, partial.wid); row.version += 1
        return result
    monkeypatch.setattr(partial.service, '_prepare', prepare_then_write)
    Pinned.active = partial.pin
    partial.service.sync(partial.wid, 'u-manager', 'fake')
    state, cache = partial.read()
    assert state['version'] == 3 and cache['status'] == 'ready' and state['source_status']['sync_revision'] == 1


def test_the_import_runs_before_the_lock_unless_the_version_moved(twins, monkeypatch):
    full, partial = twins
    advance(full, partial, '2026-09-27T10:05:00+08:00')
    inside, seen = [False], []
    for side in (full, partial):
        begin = side.sessions.begin
        class Locked:
            def __init__(self, context): self.context = context
            def __enter__(self): inside[0] = True; return self.context.__enter__()
            def __exit__(self, *a):
                inside[0] = False; return self.context.__exit__(*a)
        side.sessions.begin = lambda *a, _b=begin, **k: Locked(_b(*a, **k))
    original = source_sync.import_sources
    monkeypatch.setattr(source_sync, 'import_sources', lambda *a, **k: (seen.append(inside[0]), original(*a, **k))[1])
    for side in (full, partial): side.service.fetcher = lambda token: snapshot('2026-09-27T10:05:00+08:00', records())
    Pinned.active = full.pin; full.service.sync(full.wid, 'u-manager', 'fake')
    Pinned.active = partial.pin; partial.service.sync(partial.wid, 'u-manager', 'fake')
    assert seen == [True, False], 'the full path imports under the lock, the partial path before it'
    a, b = dump(full), dump(partial)
    assert a['records'] == b['records'] and a['workspace'] == b['workspace']


def test_the_first_sync_after_a_failed_attempt_also_imports_before_the_lock(twins, monkeypatch):
    """A failed attempt marks the cache as error, so an unchanged snapshot must be imported again; that work stays out of the lock."""
    full, partial = twins
    advance(full, partial, '2026-09-27T10:05:00+08:00')
    inside, seen = [False], []
    class Locked:
        def __init__(self, context): self.context = context
        def __enter__(self): inside[0] = True; return self.context.__enter__()
        def __exit__(self, *a):
            inside[0] = False; return self.context.__exit__(*a)
    for side in (full, partial):
        side.sessions.begin = lambda *a, _b=side.sessions.begin, **k: Locked(_b(*a, **k))
    original = source_sync.import_sources
    monkeypatch.setattr(source_sync, 'import_sources', lambda *a, **k: (seen.append(inside[0]), original(*a, **k))[1])
    for side in (full, partial): side.service.fetcher = lambda token: snapshot('2026-09-27T10:05:00+08:00', records())
    run(full, partial, lambda h: h.service.sync(h.wid, 'u-manager', 'fake', skip_unchanged=True) and None)
    advance(full, partial, '2026-09-27T10:10:00+08:00')
    run(full, partial, lambda h: h.service.failure(h.wid, 'Lark 暫時無法連線'))
    advance(full, partial, '2026-09-27T10:15:00+08:00')
    seen.clear()
    for side in (full, partial): side.service.fetcher = lambda token: snapshot('2026-09-27T10:15:00+08:00', records())
    run(full, partial, lambda h: h.service.sync(h.wid, 'u-manager', 'fake', skip_unchanged=True) and None)
    assert seen == [True, False]
