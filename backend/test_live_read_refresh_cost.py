"""Staging showed roster and attendance refreshes taking 40 to 100 s against 30 and 40 s budgets.

Every Lark request ran a permission check that loaded the whole workspace, and the
apply step loaded and diffed it again. On staging (2 vCPU, 32k business rows) one full
load measured 2.0 s and one full save 10.9 s, so a refresh spent its read budget on
database CPU. The fixture below keeps those costs at 1/8 scale and the tests assert
that a refresh no longer pays them.
"""
from copy import deepcopy
from time import monotonic, sleep

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from . import people_directory as directory, storage
from .live_read.client import LiveLarkClient
from .live_read.coordinator import RefreshCoordinator
from .live_read.datasets.attendance import AttendanceRefresher
from .live_read.datasets.roster import RosterRefresher
from .live_read.token_cache import TenantTokenCache
from .models import Base, BusinessRow, WorkspaceCounter, WorkspaceRow
from .perf_fixture import build_scaled_workspace
from .people_directory import PeopleDirectoryService
from .test_attendance_service import make
from .test_source_sync import harness  # noqa: F401  (fixture)

FULL_LOAD_SECONDS, FULL_SAVE_SECONDS, LARK_SECONDS, BUDGET = .25, 1.25, .1, 2


class Bucket:
    def acquire(self, deadline): pass


@pytest.fixture
def full_workspace_cost(monkeypatch):
    """Counts and slows whole-workspace operations once armed; setup runs at full speed."""
    cost = {'armed': False, 'load': 0, 'save': 0}
    load, save = storage.load, storage.save

    def slow_load(*args, **kwargs):
        if cost['armed']:
            cost['load'] += 1
            sleep(FULL_LOAD_SECONDS)
        return load(*args, **kwargs)

    def slow_save(*args, **kwargs):
        if cost['armed']:
            cost['save'] += 1
            sleep(FULL_SAVE_SECONDS)
        return save(*args, **kwargs)

    monkeypatch.setattr(storage, 'load', slow_load)
    monkeypatch.setattr(storage, 'save', slow_save)
    return cost


def spent(cost):
    return cost['load'], cost['save']


def lark(h, respond):
    h.cfg.update(LARK_APP_SECRET='synthetic-secret', LARK_LIVE_READ_ENABLED='true',
                 LARK_LIVE_READ_ROSTER_BUDGET_SECONDS=str(BUDGET),
                 LARK_LIVE_READ_ATTENDANCE_BUDGET_SECONDS=str(BUDGET))
    cache = TenantTokenCache()

    def transport(request):
        sleep(LARK_SECONDS)
        if request.url.path.endswith('/tenant_access_token/internal'):
            return httpx.Response(200, json={'tenant_access_token': 'synthetic-token', 'expire': 7200})
        return httpx.Response(200, json={'code': 0, 'data': respond(request)})

    return lambda cfg, **kwargs: LiveLarkClient(cfg, transport=httpx.MockTransport(transport),
                                                token_cache=cache, bucket=Bucket(), **kwargs)


def roster_pages(request):
    path = request.url.path
    if path.endswith('/tables'):
        return {'items': [{'table_id': directory.TABLE_ID, 'name': directory.TABLE_NAME}], 'has_more': False}
    if path.endswith('/fields'):
        return {'items': [{'field_name': name, 'type': kind}
                          for name, kind in {'姓名': 1, '人員': 11, '在職': 7, '內外勤': 3}.items()],
                'has_more': False}
    people = [{'record_id': f'rec{i}', 'fields': {'姓名': f'同事{i}', '人員': [{'id': f'ou_{i:03d}', 'name': f'同事{i}'}],
                                                  '在職': True, '內外勤': '內勤'}} for i in range(65)]
    return {'items': people, 'has_more': False}


def attendance_pages(request):
    return {'user_daily_shifts': []} if request.method == 'POST' else {}


def roster(h):
    with h.sessions.begin() as db:
        row = db.get(h.W, h.wid)
        state = storage.load(db, h.B, row)
        state['people_directory_connection'] = deepcopy(state['source_connection'])
        row.data = storage.save(db, h.B, h.wid, state)
    return RosterRefresher(PeopleDirectoryService(h.sessions, h.W, h.B, h.P, h.cfg), lark(h, roster_pages))


def attendance(h):
    service, _ = make(h)
    with h.sessions.begin() as db:
        row = db.get(h.W, h.wid)
        state = storage.load(db, h.B, row)
        state['attendance_schedule_connection'] = deepcopy(state['source_connection'])
        row.data = storage.save(db, h.B, h.wid, state)
    return AttendanceRefresher(service, lark(h, attendance_pages))


def refresh(h, dataset, refresher):
    coordinator = RefreshCoordinator(h.sessions, h.C, {dataset: refresher}, h.cfg)
    try:
        started = monotonic()
        result = coordinator.ensure(h.wid, dataset, wait=True, force=True, timeout=30)
        return result, monotonic() - started
    finally:
        coordinator.close()


@pytest.mark.parametrize('dataset,build', [('roster', roster), ('attendance', attendance)])
def test_refresh_finishes_inside_its_budget_when_full_workspace_operations_are_slow(
        harness, full_workspace_cost, dataset, build):
    h = harness
    refresher = build(h)
    full_workspace_cost['armed'] = True
    result, elapsed = refresh(h, dataset, refresher)
    assert result['status'] == 'fresh'
    assert elapsed < BUDGET, f'{dataset} refresh took {elapsed:.2f}s against a {BUDGET}s budget'


@pytest.mark.parametrize('dataset,build', [('roster', roster), ('attendance', attendance)])
def test_refresh_never_loads_or_diffs_the_whole_workspace(harness, full_workspace_cost, dataset, build):
    h = harness
    refresher = build(h)
    full_workspace_cost['armed'] = True
    result, _ = refresh(h, dataset, refresher)
    assert result['status'] == 'fresh'
    assert spent(full_workspace_cost) == (0, 0)


@pytest.mark.parametrize('dataset,build,action', [('roster', roster, 'people_directory_sync'),
                                                  ('attendance', attendance, 'attendance_schedule_sync')])
def test_refresh_adds_exactly_its_own_audit_event(harness, dataset, build, action):
    h = harness
    refresher = build(h)
    before = h.read()[0]['events']
    refresh(h, dataset, refresher)
    added = h.read()[0]['events'][:-len(before)] if before else h.read()[0]['events']
    assert [event['action'] for event in added] == [action]


def test_failed_roster_refresh_records_its_error_without_the_whole_workspace(harness, full_workspace_cost):
    h = harness
    refresher = roster(h)
    refresher.service.fetcher = lambda adapter, app_id: (_ for _ in ()).throw(RuntimeError('lark down'))
    full_workspace_cost['armed'] = True
    coordinator = RefreshCoordinator(h.sessions, h.C, {'roster': refresher}, h.cfg)
    try:
        with pytest.raises(Exception):
            coordinator.ensure(h.wid, 'roster', wait=True, force=True, timeout=30)
    finally:
        coordinator.close()
    assert spent(full_workspace_cost) == (0, 0)
    with h.sessions() as db:
        status = db.get(h.W, h.wid).data['people_directory_status']
    assert status['status'] == 'error'


def test_attendance_failure_records_its_error_without_the_whole_workspace(harness, full_workspace_cost):
    h = harness
    refresher = attendance(h)

    def broken(*args, **kwargs):
        raise RuntimeError('lark down')

    refresher.service.adapter_factory = lambda cfg: type('A', (), {
        'request': staticmethod(broken), 'client': type('C', (), {'close': staticmethod(lambda: None)})()})()
    full_workspace_cost['armed'] = True
    with pytest.raises(HTTPException):
        refresher.service.sync(h.wid, None, '2026-09-28', '2026-09-28')
    assert spent(full_workspace_cost) == (0, 0)
    with h.sessions() as db:
        assert db.get(h.W, h.wid).data['attendance_schedule_status']['status'] == 'error'


def store(tmp_path, name, indexed=False):
    engine = create_engine(f'sqlite:///{tmp_path}/{name}.db')
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False, info={'index_tables': indexed})
    with sessions.begin() as db:
        row = WorkspaceRow(id='w', version=1, data={})
        db.add(row)
        db.flush()
        state = build_scaled_workspace(6)
        state['version'] = 1
        row.data = storage.save(db, BusinessRow, 'w', state)
    return engine, sessions


def rows(sessions):
    with sessions() as db:
        stored = sorted((r.kind, r.entity_id, r.parent_id, r.ordinal, repr(sorted(r.data.items())))
                        for r in db.scalars(select(BusinessRow)))
        row = db.get(WorkspaceRow, 'w')
        return stored, row.data, row.version


def write(sessions, mutate, collections=None):
    """One directory-style write: the whole workspace when collections is None, else only those."""
    with sessions.begin() as db:
        row = db.get(WorkspaceRow, 'w')
        state = (storage.load(db, BusinessRow, row) if collections is None
                 else storage.load_partial(db, BusinessRow, row, collections=('users',)))
        mutate(state)
        state['version'] = row.version + 1
        row.data = (storage.save(db, BusinessRow, 'w', state) if collections is None
                    else storage.save_collections(db, BusinessRow, 'w', state, collections))
        row.version = state['version']


def roster_change(state):
    state['users'][0]['name'] = '改名'
    state['users'].append(dict(id='ou_new', name='新同事', role='member', active=True, capabilities=[]))
    state['events'].insert(0, dict(id='ev-new', project_id=None, actor_id='u', action='x', message='m',
                                   created_at='2026-10-15T00:00:00+08:00'))
    state['people_directory_status'] = {'status': 'ready'}


def test_save_collections_stores_what_a_full_save_stores_for_those_collections(tmp_path):
    full_engine, full = store(tmp_path, 'full')
    lean_engine, lean = store(tmp_path, 'lean')
    write(full, roster_change)
    write(lean, roster_change, ('users', 'events'))
    assert rows(lean) == rows(full)
    assert any(r[1] == 'ev-new' and r[3] < 0 for r in rows(lean)[0])
    full_engine.dispose()
    lean_engine.dispose()


def test_save_collections_leaves_projects_and_other_collections_alone(tmp_path):
    engine, sessions = store(tmp_path, 'alone')
    before = [r for r in rows(sessions)[0] if r[0] not in ('users', 'events')]
    write(sessions, roster_change, ('users', 'events'))
    assert [r for r in rows(sessions)[0] if r[0] not in ('users', 'events')] == before
    engine.dispose()


def test_save_collections_refuses_projects_and_collections_that_were_not_loaded(tmp_path):
    engine, sessions = store(tmp_path, 'refuse')
    with sessions.begin() as db:
        row = db.get(WorkspaceRow, 'w')
        partial = storage.load_partial(db, BusinessRow, row, collections=('users',))
        for state, collections in ((partial, ('projects',)), (partial, ('work_schedules',)),
                                   (storage.load(db, BusinessRow, row), ('users',))):
            with pytest.raises(ValueError):
                storage.save_collections(db, BusinessRow, 'w', state, collections)
    engine.dispose()


def test_save_collections_keeps_the_project_index_ready_only_if_it_was_current(tmp_path):
    engine, sessions = store(tmp_path, 'index', indexed=True)

    def versions():
        with sessions() as db:
            return {r.source_version for r in db.scalars(select(WorkspaceCounter))}

    assert versions() == {1}
    write(sessions, roster_change, ('users', 'events'))
    assert versions() == {2}
    with sessions.begin() as db:
        for counter in db.scalars(select(WorkspaceCounter)):
            counter.source_version = 0
    write(sessions, lambda state: state['users'][0].update(name='again'), ('users',))
    assert versions() == {0}
    engine.dispose()
