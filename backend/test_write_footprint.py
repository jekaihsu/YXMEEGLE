"""The footprint guard: a mutation outside its declaration must fail, never save a partial view."""
from copy import deepcopy

import pytest
from fastapi import HTTPException

from . import storage, write_footprint
from .models import Base, BusinessRow, WorkspaceRow
from .partial_testing import Pinned, Rig, first_difference
from .write_footprint import Footprint, Rule, UnloadedProject, WorkspaceView, resolve
from .write_world import WID, build_world, scenarios

Violation = storage.FootprintViolation


def view(allowed=('users',), loaded=('p001',), order=('p001', 'p002', 'p003')):
    raw = {'version': 4, 'settings': {'a': 1}, 'events': [], 'users': [{'id': 'u'}], 'approvals': [{'id': 'a1'}],
           'projects': [{'id': pid, 'nodes': [], 'name': pid} for pid in loaded]}
    return WorkspaceView(raw, allowed, order)


def test_a_collection_outside_the_footprint_cannot_be_read_written_or_probed():
    ws = view(('users',))
    assert ws['users'] == [{'id': 'u'}] and ws.get('users') and 'users' in ws
    for touch in (lambda: ws['approvals'], lambda: ws.get('approvals', []), lambda: 'approvals' in ws,
                  lambda: ws.setdefault('approvals', []), lambda: ws.__setitem__('approvals', []), lambda: ws.__delitem__('approvals')):
        with pytest.raises(Violation, match='approvals is outside the footprint'):
            touch()


def test_root_keys_are_open_and_the_whole_state_cannot_be_walked():
    ws = view()
    assert ws['version'] == 4 and ws.get('settings') == {'a': 1} and ws.setdefault('note', 'x') == 'x'
    ws['version'] = 5
    assert ws.raw['version'] == 5 and ws.already_upgraded and bool(ws)
    for walk in (lambda: list(ws), lambda: len(ws), lambda: dict(ws), lambda: list(ws.items()), lambda: ws.copy(), lambda: ws == {}):
        with pytest.raises(Violation, match='whole workspace'):
            walk()


def test_other_projects_are_ids_only_and_the_project_list_has_a_fixed_shape():
    ws = view(loaded=('p002',))
    projects = ws['projects']
    assert [p['id'] for p in projects] == ['p001', 'p002', 'p003']
    assert projects[1]['nodes'] == [] and projects[1] is ws.raw['projects'][0]
    stub = projects[0]
    assert isinstance(stub, UnloadedProject)
    for touch in (lambda: stub['nodes'], lambda: stub.get('name'), lambda: 'nodes' in stub, lambda: list(stub), lambda: stub.items(),
                  lambda: stub.__setitem__('name', 'x'), lambda: len(stub), lambda: deepcopy(stub)):
        with pytest.raises(Violation, match='project p001 is outside the footprint'):
            touch()
    for change in (lambda: projects.append({'id': 'p9'}), lambda: projects.pop(), lambda: projects.sort(), lambda: projects.__setitem__(0, {}),
                   lambda: ws.__setitem__('projects', [])):
        with pytest.raises(Violation):
            change()


def test_events_can_be_added_but_history_cannot_be_searched():
    ws = view()
    ws['events'].insert(0, {'id': 'new'})
    assert ws['events'][0] == {'id': 'new'} and ws.raw['events'].new() == [{'id': 'new'}]
    for read in (lambda: list(ws['events']), lambda: {'id': 'new'} in ws['events'], lambda: next(e for e in ws['events'])):
        with pytest.raises(Violation, match='write-only'):
            read()


def test_a_violation_is_not_swallowed_by_a_broad_except():
    ws = view(('users',))
    try:
        try: ws['approvals']
        except Exception: pytest.fail('FootprintViolation must not be an Exception')
    except Violation:
        pass


def test_the_registry_resolves_only_what_it_can_serve():
    assert resolve({'action': 'task_start', 'project_id': 'p001'}) == Footprint(write_footprint.CASE_RECORDS, ('p001',))
    assert resolve({'action': 'task_start', 'project_id': None}) is None
    assert resolve({'action': 'demo_reset', 'project_id': 'p001'}) is None
    assert resolve({'action': 'task_batch_complete', 'project_id': 'p001'}) is None
    assert resolve({}) is None


def narrow(monkeypatch, action, collections):
    monkeypatch.setitem(write_footprint.RULES, action, Rule(frozenset(collections)))


@pytest.fixture
def pair(tmp_path, monkeypatch):
    Pinned(monkeypatch)
    full = Rig(tmp_path, 'full', partial=False, projects=12)
    strict = Rig(tmp_path, 'strict', partial=True, projects=12, world=full.world)
    lenient = Rig(tmp_path, 'lenient', partial=True, projects=12, world=full.world, extra={'PARTIAL_WRITES_STRICT': 'false'})
    yield full, strict, lenient
    for rig in (full, strict, lenient): rig.close()


def leaves(error):
    return [y for z in error.exceptions for y in leaves(z)] if hasattr(error, 'exceptions') else [error]


def test_a_mutation_that_reads_an_undeclared_collection_raises_in_strict_mode_and_saves_nothing(pair, monkeypatch):
    _, strict, _ = pair
    narrow(monkeypatch, 'task_start', {'users'})
    user, fields = scenarios(strict.world, 1)['task_start'][0]
    before = strict.dump()
    with pytest.raises(BaseException) as raised:
        strict.act(user, 'task_start', **fields)
    assert any(isinstance(e, Violation) and 'outside the footprint' in str(e) for e in leaves(raised.value))
    assert strict.dump() == before and strict.version() == 1


def test_a_footprint_mistake_falls_back_to_the_full_path_with_identical_results(pair, monkeypatch):
    full, _, lenient = pair
    narrow(monkeypatch, 'task_start', {'users'})
    user, fields = scenarios(full.world, 1)['task_start'][0]
    a = full.act(user, 'task_start', **fields); b = lenient.act(user, 'task_start', **fields)
    assert a.status_code == b.status_code == 200 and a.json() == b.json()
    assert first_difference(full.dump(), lenient.dump()) is None
    assert lenient.app.state.partial_writes == {'committed': 0, 'declined': 1}


def test_a_case_missing_from_the_footprint_is_decided_by_the_full_path(pair):
    full, _, lenient = pair
    user, fields = scenarios(full.world, 2)['task_start'][1]
    elsewhere = dict(fields, task_id=scenarios(full.world, 2)['task_start'][0][1]['task_id'])
    a = full.act(user, 'task_start', **elsewhere); b = lenient.act(user, 'task_start', **elsewhere)
    assert a.status_code == b.status_code == 404 and a.json() == b.json()
    assert lenient.app.state.partial_writes['declined'] == 1
    assert first_difference(full.dump(), lenient.dump()) is None


def test_unregistered_actions_never_try_the_partial_path(pair):
    full, _, lenient = pair
    manager = 'u-manager'
    a = full.act(manager, 'calendar_update', payload={'holidays': ['2026-12-25'], 'workdays': []})
    b = lenient.act(manager, 'calendar_update', payload={'holidays': ['2026-12-25'], 'workdays': []})
    assert a.status_code == b.status_code == 200
    assert lenient.app.state.partial_writes == {'committed': 0, 'declined': 0}
    assert first_difference(full.dump(), lenient.dump()) is None


def test_the_switch_turns_the_partial_path_off(tmp_path, monkeypatch):
    Pinned(monkeypatch)
    rig = Rig(tmp_path, 'off', partial=False, projects=8)
    try:
        user, fields = scenarios(rig.world, 1)['comment_add'][0]
        assert rig.act(user, 'comment_add', **fields).status_code == 200
        assert rig.app.state.partial_writes == {'committed': 0, 'declined': 0}
    finally:
        rig.close()


def test_a_write_that_changes_another_case_is_refused_before_any_row_moves(pair):
    """A full save would bump the other case's version and rebuild its index row; only the full path can."""
    full, strict, _ = pair
    with strict.app.state.sessions.begin() as db:
        row = db.get(WorkspaceRow, WID)
        state, order = storage.load_scoped(db, BusinessRow, row, collections=['approvals'], project_ids=['p001'])
        state['version'] = row.version + 1
        foreign = next(a for a in state['approvals'] if a['project_id'] != 'p001')
        foreign['status'] = 'withdrawn'
        before = db.scalar(__import__('sqlalchemy').select(__import__('sqlalchemy').func.count()).select_from(BusinessRow))
        with pytest.raises(Violation, match='outside the footprint'):
            storage.save_partial(db, BusinessRow, WID, state, ['approvals'], ['p001'], order)
        db.rollback()
