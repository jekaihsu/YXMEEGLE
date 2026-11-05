from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, delete, event, inspect, select

from .models import BusinessRow
from .sop_import.cleanup_migration import audit_history_detached, migrate
from .sop_import.domain import Failure
from .sop_import.models import LocalTask, TaskNodeLink, TaskEvent
from .test_sop_import import URL, apply, h, overview, post, preview  # noqa: F401
from .test_action_audit_database import audit_database  # noqa: F401


@pytest.fixture
def m(h):
    """The harness acting as a workspace manager, the operator test cleanup is for."""
    h.who[0] = 'manager'
    return h


def manual(h, **extra):
    return post(h, URL + '/sop-tasks', {'title': 'Test task', 'node_keys': ['pm'], **extra})['task']


def fixture(h):
    return manual(h, is_test=True)


def tag(h, task, status=200, **extra):
    return post(h, URL + f"/sop-tasks/{task['id']}/test-tag", {
        'expected_revision': task['revision'], 'is_test': True, 'reason': 'Explicit test fixture', **extra}, status)


def clean(h, task, status=200, url=URL):
    return post(h, url + f"/sop-tasks/{task['id']}/cleanup-test", {
        'expected_revision': task['revision'], 'reason': 'Remove test fixture'}, status)


def transition(h, task, action, **extra):
    return post(h, URL + f"/sop-tasks/{task['id']}/transition", {
        'expected_revision': task['revision'], 'action': action, 'reason': 'test', **extra})['task']


def events(h):
    with h.sessions() as db:
        return {e.id: (e.task_id, e.kind, e.revision, e.changes) for e in db.scalars(select(TaskEvent))}


def stored(h, task_id):
    with h.sessions() as db:
        return db.get(LocalTask, ('w', task_id))


def set_local(h, task_id, **values):
    with h.sessions.begin() as db:
        row = db.get(LocalTask, ('w', task_id))
        row.local = {**row.local, **values}


def imported_shared_task(h):
    apply(h)
    return next(t for t in overview(h)['tasks'] if len(t['node_keys']) == 3)


def grant(h, **data):
    """Reshape the case row so the next request resolves a different case authority."""
    with h.sessions.begin() as db:
        row = db.get(BusinessRow, ('w', 'projects', 'p1'))
        row.data = {**row.data, **data}


CASE_AUTHORITY = {'pm': ('pm', {}), 'delegate': ('member', {'sop_task_delegate_ids': ['member']}),
                  'intake': ('other', {'case_type': 'intake', 'pm_id': None})}


def test_explicit_test_creation_records_immutable_provenance(m):
    assert post(m, URL + '/sop-tasks', {'title': 'x', 'node_keys': ['pm'], 'is_test': 'true'}, 422)['code'] == 'invalid_request'
    task = fixture(m)
    assert task['local']['is_test'] is True and task['origin']['template_family_id'] == 'manual'
    assert [value for value in events(m).values() if value[1] == 'created'] == [(task['id'], 'created', 1, {'is_test': True})]
    plain = manual(m, is_test=False)
    assert 'is_test' not in plain['local']
    with pytest.raises(Failure, match='immutable_task_origin'):
        with m.sessions.begin() as db:
            db.get(LocalTask, ('w', plain['id'])).snapshot = {'test_fixture': True}


def test_untagged_task_is_refused_even_when_named_test(m):
    task = manual(m)
    before = events(m)
    assert clean(m, task, 409)['code'] == 'test_task_required'
    assert tag(m, task, 409)['code'] == 'test_task_required'
    assert overview(m)['tasks'][0]['id'] == task['id']
    assert events(m) == before


@pytest.mark.parametrize('origin', ['manual', 'imported'])
def test_legacy_flag_never_makes_an_ordinary_task_disposable(m, origin):
    task = manual(m) if origin == 'manual' else imported_shared_task(m)
    assert tag(m, task, 409)['code'] == 'test_task_required'
    set_local(m, task['id'], is_test=True)
    before, listing = events(m), overview(m)
    assert clean(m, task, 409)['code'] == 'test_task_required'
    assert tag(m, task, 409, is_test=False)['code'] == 'test_task_required'
    assert stored(m, task['id']) is not None
    assert overview(m) == listing and events(m) == before


@pytest.mark.parametrize('proof', ['result', 'evidence_basis', 'attestations'])
def test_completed_fixture_with_proof_is_protected_until_reopened(m, proof):
    task = fixture(m)
    if proof == 'result':
        done = transition(m, task, 'complete', result_note='checked')
    else:
        done = transition(m, task, 'complete')
        set_local(m, task['id'], **{proof: {'tier': 'proof'} if proof == 'evidence_basis' else {'pm': 'signed'}})
    assert tag(m, done, 409)['code'] == 'task_reopen_required'
    assert clean(m, done, 409)['code'] == 'task_reopen_required'
    archived = transition(m, done, 'archive')
    assert clean(m, archived, 409)['code'] == 'task_reopen_required'
    assert stored(m, task['id']) is not None
    reopened = transition(m, transition(m, archived, 'restore'), 'reopen')
    assert reopened['state'] == 'in_progress'
    assert clean(m, reopened)['removed'] is True


def test_completed_fixture_without_proof_stays_disposable(m):
    done = transition(m, fixture(m), 'complete')
    assert done['state'] == 'done' and done['result'] is None
    assert clean(m, done)['removed'] is True


def test_cleanup_removes_task_links_counts_and_preserves_audit_idempotently(m):
    task = fixture(m)
    before, listing = events(m), overview(m)
    assert listing['counts']['total'] == listing['node_counts']['pm']['total'] == 1
    result = clean(m, task)
    assert result['removed'] is True and result['replayed'] is False
    after = overview(m)
    assert after['tasks'] == []
    assert after['counts']['total'] == after['node_counts']['pm']['total'] == 0
    assert after['checklist_revision'] == listing['checklist_revision'] + 1
    with m.sessions() as db:
        assert db.get(LocalTask, ('w', task['id'])) is None
        assert list(db.scalars(select(TaskNodeLink))) == []
    history = events(m)
    assert {key: history[key] for key in before} == before
    added = [value for key, value in history.items() if key not in before]
    assert len(added) == 1 and added[0][1] == 'test_cleaned'
    assert added[0][3]['node_links'] == [{'node_id': 'real-p1-1', 'node_key': 'pm'}]
    repeat = clean(m, task)
    assert repeat['removed'] is False and repeat['replayed'] is True
    assert repeat['checklist_revision'] == after['checklist_revision']
    assert events(m) == history


@pytest.mark.parametrize('actor', ['pm', 'delegate', 'intake', 'member', 'other', 'expired'])
def test_only_managers_create_tag_or_remove_test_fixtures(m, actor):
    task = fixture(m)
    user, case = CASE_AUTHORITY.get(actor, (actor, {}))
    grant(m, **case)
    m.who[0] = user
    status = 401 if actor == 'expired' else 403
    if actor in CASE_AUTHORITY:
        assert 'is_test' not in manual(m)['local']  # Case authority still creates ordinary tasks.
    before = events(m)
    assert post(m, URL + '/sop-tasks', {'title': 'x', 'node_keys': ['pm'], 'is_test': True}, status)
    assert tag(m, task, status)
    assert clean(m, task, status)
    assert stored(m, task['id']) is not None and events(m) == before
    m.who[0] = 'manager'
    clean(m, task)
    m.who[0] = user
    assert clean(m, task, status)  # Replay does not bypass authorization.


def test_manager_demoted_during_lock_is_refused_but_keeps_case_authority(m):
    task = fixture(m)
    grant(m, pm_id='manager')
    original = m.service.lock_workspace_row

    def demote_during_lock(db, wid):
        original(db, wid)
        m.users['manager']['role'] = 'pm'

    m.service.lock_workspace_row = demote_during_lock
    before = events(m)
    assert clean(m, task, 403)['code'] == 'sop_import_forbidden'
    assert tag(m, task, 403, is_test=False)['code'] == 'sop_import_forbidden'
    assert post(m, URL + '/sop-tasks', {'title': 'x', 'node_keys': ['pm'], 'is_test': True}, 403)['code'] == 'sop_import_forbidden'
    assert stored(m, task['id']) is not None and events(m) == before
    m.service.lock_workspace_row = original
    assert 'is_test' not in manual(m)['local']


def test_reimport_never_reuses_an_identity_cleaned_before_provenance_existed(m):
    original = imported_shared_task(m)
    before = overview(m)
    assert tag(m, original, 409)['code'] == 'test_task_required'
    stale_plan = preview(m)
    # An earlier release removed this imported task; only its audit trail remains.
    with m.sessions.begin() as db:
        db.add(TaskEvent(workspace_id='w', id='historical', project_id='p1', task_id=original['id'], actor_id='pm',
                         at=900, kind='test_cleaned', revision=original['revision'], changes={'reason': 'historical'}))
        db.execute(delete(TaskNodeLink).where(TaskNodeLink.task_id == original['id']))
        db.execute(delete(LocalTask).where(LocalTask.id == original['id']))
    prior_events, after = events(m), overview(m)
    for key in original['node_keys']:
        assert after['node_counts'][key]['total'] == before['node_counts'][key]['total'] - 1
    assert apply(m, stale_plan, 'stale', status=409)['code'] == 'preview_stale'
    imported = apply(m, rid='reimport')
    assert len(imported['created_task_ids']) == 1
    replacement = next(t for t in overview(m)['tasks'] if t['id'] in imported['created_task_ids'])
    assert replacement['origin'] == original['origin']
    assert replacement['id'] != original['id']
    assert replacement['local'].get('is_test') is not True
    assert replacement['node_keys'] == original['node_keys']
    assert clean(m, original)['replayed'] is True
    assert len(overview(m)['tasks']) == len(before['tasks'])
    assert clean(m, replacement, 409)['code'] == 'test_task_required'
    assert {key: events(m)[key] for key in prior_events} == prior_events


def test_revision_flags_scope_write_gate_and_missing_task(m):
    task = fixture(m)
    assert tag(m, task, 422, is_test='true')['code'] == 'invalid_request'
    untagged = tag(m, task, is_test=False)['task']
    assert clean(m, untagged, 409)['code'] == 'test_task_required'
    tagged = tag(m, untagged)['task']
    assert clean(m, untagged, 409)['code'] == 'task_revision_conflict'
    assert clean(m, tagged, 404, '/api/projects/p2')['code'] == 'task_not_found'
    m.wid[0] = 'other-w'
    assert clean(m, tagged, 404)['code'] == 'case_not_found'
    m.wid[0] = 'w'
    m.cfg['SOP_TASK_WRITES_ENABLED'] = 'false'
    assert clean(m, tagged, 503)['code'] == 'import_unavailable'
    m.cfg['SOP_TASK_WRITES_ENABLED'] = 'true'
    assert clean(m, {**task, 'id': 'missing'}, 404)['code'] == 'task_not_found'
    assert clean(m, tagged)['removed'] is True


def test_concurrent_cleanup_only_appends_once(m):
    task = fixture(m)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: clean(m, task), range(3)))
    assert sum(r['removed'] for r in results) == 1
    assert sum(value[1] == 'test_cleaned' for value in events(m).values()) == 1


LEGACY_AUDIT_TABLE = '''CREATE TABLE sop_task_events (
    workspace_id VARCHAR(120) NOT NULL, id VARCHAR(64) NOT NULL,
    project_id VARCHAR(160) NOT NULL, task_id VARCHAR(64) NOT NULL,
    actor_id VARCHAR(120) NOT NULL, at FLOAT NOT NULL, kind VARCHAR(40) NOT NULL,
    revision INTEGER NOT NULL, changes JSON NOT NULL, PRIMARY KEY (workspace_id, id),
    FOREIGN KEY(workspace_id, project_id, task_id)
    REFERENCES sop_local_tasks (workspace_id, project_id, id))'''


@pytest.mark.parametrize('enforced', [True, False])
def test_unmigrated_audit_table_refuses_cleanup_before_any_write(m, enforced):
    # Recreate the exact pre-cleanup audit table before inserting history.
    with m.engine.begin() as db:
        db.exec_driver_sql('DROP TABLE sop_task_events')
        db.exec_driver_sql(LEGACY_AUDIT_TABLE)
        db.exec_driver_sql('CREATE INDEX ix_sop_task_events_project_id ON sop_task_events (project_id)')
    if not enforced:
        event.listen(m.engine, 'connect', lambda connection, record: connection.execute('PRAGMA foreign_keys=OFF'))
        m.engine.dispose()
    with m.engine.connect() as db:
        assert db.exec_driver_sql('PRAGMA foreign_keys').scalar() == int(enforced)
    task = fixture(m)
    before, listing = events(m), overview(m)
    assert clean(m, task, 503)['code'] == 'cleanup_migration_required'
    assert stored(m, task['id']) is not None
    assert overview(m) == listing and events(m) == before
    migrate(m.engine)
    migrate(m.engine)
    assert events(m) == before
    assert inspect(m.engine).get_foreign_keys('sop_task_events') == []
    assert clean(m, task)['removed'] is True
    assert {key: events(m)[key] for key in before} == before


def test_archived_fixture_and_inactive_or_revoked_authority(m):
    archived = transition(m, fixture(m), 'archive')
    m.users['manager']['active'] = False
    assert clean(m, archived, 403)['code'] == 'sop_import_forbidden'
    m.users['manager']['active'] = True
    original_refresh = m.service.lock_workspace_row

    def revoke_during_lock(db, wid):
        original_refresh(db, wid)
        m.who[0] = 'other'

    m.service.lock_workspace_row = revoke_during_lock
    assert clean(m, archived, 403)['code'] == 'sop_import_forbidden'
    m.service.lock_workspace_row = original_refresh
    m.who[0] = 'manager'
    clean(m, archived)


def test_migration_keeps_audit_after_physical_removal_on_each_database(audit_database):
    engine = create_engine(audit_database)
    try:
        with engine.begin() as db:
            db.exec_driver_sql('''CREATE TABLE sop_local_tasks (
                workspace_id VARCHAR(120) NOT NULL, project_id VARCHAR(160) NOT NULL,
                id VARCHAR(64) NOT NULL, PRIMARY KEY (workspace_id, project_id, id))''')
            db.exec_driver_sql('''CREATE TABLE sop_task_events (
                workspace_id VARCHAR(120) NOT NULL, id VARCHAR(64) NOT NULL,
                project_id VARCHAR(160) NOT NULL, task_id VARCHAR(64) NOT NULL,
                actor_id VARCHAR(120) NOT NULL, at FLOAT NOT NULL, kind VARCHAR(40) NOT NULL,
                revision INTEGER NOT NULL, changes JSON NOT NULL, PRIMARY KEY (workspace_id, id),
                FOREIGN KEY(workspace_id, project_id, task_id)
                REFERENCES sop_local_tasks (workspace_id, project_id, id))''')
            db.exec_driver_sql('CREATE INDEX ix_sop_task_events_project_id ON sop_task_events (project_id)')
            db.exec_driver_sql("INSERT INTO sop_local_tasks VALUES ('w', 'p', 't')")
            db.exec_driver_sql("INSERT INTO sop_task_events VALUES ('w', 'e', 'p', 't', 'actor', 100, 'created', 1, '{}')")
            before = db.exec_driver_sql('SELECT * FROM sop_task_events').all()
            assert audit_history_detached(db) is False
        migrate(engine)
        migrate(engine)
        with engine.begin() as db:
            assert audit_history_detached(db) is True
            db.exec_driver_sql('DELETE FROM sop_local_tasks')
            assert db.exec_driver_sql('SELECT * FROM sop_task_events').all() == before
        assert inspect(engine).get_foreign_keys('sop_task_events') == []
    finally:
        engine.dispose()


def test_cleanup_and_tag_honor_node_policy_and_case_visibility(m):
    from .sop_import.models import CasePolicy
    task = fixture(m)
    with m.sessions.begin() as db:
        db.add(CasePolicy(workspace_id='w', project_id='p1', policy='managed', revision=1,
                          decided_by='pm', decided_at=1000, reason='limited enrollment', facts={}, node_keys=['sales']))
    assert clean(m, task, 409)['code'] == 'node_not_enrolled'
    assert tag(m, task, 409, is_test=False)['code'] == 'node_not_enrolled'
    m.hidden.add('p1')
    assert clean(m, task, 404)['code'] == 'case_not_found'


def test_prior_audit_is_still_immutable_after_cleanup(m):
    task = fixture(m)
    clean(m, task)
    with pytest.raises(Failure, match='immutable_task_event'):
        with m.sessions.begin() as db:
            event = db.scalar(select(TaskEvent))
            event.changes = {'tampered': True}
    with pytest.raises(Failure, match='immutable_task_event'):
        with m.sessions.begin() as db:
            db.delete(db.scalar(select(TaskEvent)))


def test_test_origin_never_enqueues_on_create_edit_assign_or_backfill(m):
    from .sop_import.models import LarkOutbox
    from .sop_import.outbox import enqueue_all
    from .test_sop_import import change
    task = fixture(m)
    edited = change(m, task, {'title': 'Edited test', 'participants': {'executor': 'member'}})['task']
    tag(m, edited, is_test=False)
    assert enqueue_all(m.sessions) == 0
    with m.sessions() as db:
        assert list(db.scalars(select(LarkOutbox))) == []
    ordinary = manual(m)
    assert enqueue_all(m.sessions) == 1
    with m.sessions() as db:
        assert [r.task_id for r in db.scalars(select(LarkOutbox))] == [ordinary['id']]


@pytest.mark.parametrize('state,record_id', [('none', None), ('sent', None), ('done', 'rec-existing'), ('paused', 'rec-existing')])
def test_cleanup_refuses_any_projection_row_without_removing_local_data(m, state, record_id):
    from .sop_import.models import LarkOutbox
    task = fixture(m)
    before = events(m)
    with m.sessions.begin() as db:
        db.add(LarkOutbox(workspace_id='w', project_id='p1', task_id=task['id'], generation=2,
                         target_revision=1, state=state, record_id=record_id))
    assert clean(m, task, 409)['code'] == 'test_task_projection_exists'
    assert stored(m, task['id']) is not None
    assert events(m) == before
    with m.sessions() as db:
        assert db.scalar(select(TaskNodeLink).where(TaskNodeLink.task_id == task['id'])) is not None
        assert db.scalar(select(LarkOutbox).where(LarkOutbox.task_id == task['id'])).record_id == record_id
