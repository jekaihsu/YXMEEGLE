from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, select, inspect

from .sop_import.cleanup_migration import migrate
from .sop_import.models import LocalTask, TaskNodeLink, TaskEvent
from .test_sop_import import URL, apply, h, overview, post, preview  # noqa: F401
from .test_action_audit_database import audit_database  # noqa: F401


def manual(h):
    return post(h, URL + '/sop-tasks', {'title': 'Test task', 'node_keys': ['pm']})['task']


def tag(h, task, **extra):
    return post(h, URL + f"/sop-tasks/{task['id']}/test-tag", {
        'expected_revision': task['revision'], 'is_test': True, 'reason': 'Explicit test fixture', **extra})['task']


def clean(h, task, status=200, url=URL):
    return post(h, url + f"/sop-tasks/{task['id']}/cleanup-test", {
        'expected_revision': task['revision'], 'reason': 'Remove test fixture'}, status)


def events(h):
    with h.sessions() as db:
        return {e.id: (e.task_id, e.kind, e.revision, e.changes) for e in db.scalars(select(TaskEvent))}


def test_untagged_task_is_refused_even_when_named_test(h):
    task = manual(h)
    before = events(h)
    assert clean(h, task, 409)['code'] == 'test_task_required'
    assert overview(h)['tasks'][0]['id'] == task['id']
    assert events(h) == before


def test_cleanup_removes_task_links_counts_and_preserves_audit_idempotently(h):
    task = tag(h, manual(h))
    before, listing = events(h), overview(h)
    assert listing['counts']['total'] == listing['node_counts']['pm']['total'] == 1
    result = clean(h, task)
    assert result['removed'] is True and result['replayed'] is False
    after = overview(h)
    assert after['tasks'] == []
    assert after['counts']['total'] == after['node_counts']['pm']['total'] == 0
    assert after['checklist_revision'] == listing['checklist_revision'] + 1
    with h.sessions() as db:
        assert db.get(LocalTask, ('w', task['id'])) is None
        assert list(db.scalars(select(TaskNodeLink))) == []
    history = events(h)
    assert {key: history[key] for key in before} == before
    added = [value for key, value in history.items() if key not in before]
    assert len(added) == 1 and added[0][1] == 'test_cleaned'
    assert added[0][3]['node_links'] == [{'node_id': 'real-p1-1', 'node_key': 'pm'}]
    repeat = clean(h, task)
    assert repeat['removed'] is False and repeat['replayed'] is True
    assert repeat['checklist_revision'] == after['checklist_revision']
    assert events(h) == history


@pytest.mark.parametrize('actor', ['member', 'other', 'expired'])
def test_tag_and_cleanup_require_existing_manager_authority(h, actor):
    task = manual(h)
    h.who[0] = actor
    status = 401 if actor == 'expired' else 403
    assert post(h, URL + f"/sop-tasks/{task['id']}/test-tag", {
        'expected_revision': 1, 'is_test': True, 'reason': 'test'}, status)
    assert clean(h, task, status)
    h.who[0] = 'pm'
    tagged = tag(h, task)
    h.who[0] = actor
    assert clean(h, tagged, status)
    h.who[0] = 'pm'
    clean(h, tagged)
    h.who[0] = actor
    assert clean(h, tagged, status)  # Replay does not bypass authorization.


def test_imported_shared_task_frees_identity_and_reimport_cannot_be_cleaned_by_old_request(h):
    apply(h)
    before = overview(h)
    original = next(t for t in before['tasks'] if len(t['node_keys']) == 3)
    task = tag(h, original)
    prior_events = events(h)
    stale_plan = preview(h)
    clean(h, task)
    after = overview(h)
    for key in task['node_keys']:
        assert after['node_counts'][key]['total'] == before['node_counts'][key]['total'] - 1
    assert apply(h, stale_plan, 'stale', status=409)['code'] == 'preview_stale'
    imported = apply(h, rid='reimport')
    assert len(imported['created_task_ids']) == 1
    replacement = next(t for t in overview(h)['tasks'] if t['id'] in imported['created_task_ids'])
    assert replacement['origin'] == original['origin']
    assert replacement['id'] != original['id']
    assert replacement['local'].get('is_test') is not True
    assert replacement['node_keys'] == original['node_keys']
    assert clean(h, task)['replayed'] is True
    assert len(overview(h)['tasks']) == len(before['tasks'])
    assert clean(h, replacement, 409)['code'] == 'test_task_required'
    history = events(h)
    assert {key: history[key] for key in prior_events} == prior_events


def test_revision_flags_scope_write_gate_and_missing_task(h):
    task = manual(h)
    assert post(h, URL + f"/sop-tasks/{task['id']}/test-tag", {
        'expected_revision': 1, 'is_test': 'true', 'reason': 'test'}, 422)['code'] == 'invalid_request'
    tagged = tag(h, task)
    assert clean(h, task, 409)['code'] == 'task_revision_conflict'
    assert clean(h, tagged, 404, '/api/projects/p2')['code'] == 'task_not_found'
    h.wid[0] = 'other-w'
    assert clean(h, tagged, 404)['code'] == 'case_not_found'
    h.wid[0] = 'w'
    h.cfg['SOP_TASK_WRITES_ENABLED'] = 'false'
    assert clean(h, tagged, 503)['code'] == 'import_unavailable'
    h.cfg['SOP_TASK_WRITES_ENABLED'] = 'true'
    untagged = tag(h, tagged, is_test=False)
    assert clean(h, untagged, 409)['code'] == 'test_task_required'
    assert clean(h, {**task, 'id': 'missing'}, 404)['code'] == 'task_not_found'


def test_concurrent_cleanup_only_appends_once(h):
    task = tag(h, manual(h))
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: clean(h, task), range(3)))
    assert sum(r['removed'] for r in results) == 1
    assert sum(value[1] == 'test_cleaned' for value in events(h).values()) == 1


def test_legacy_foreign_key_migration_preserves_rows_and_is_repeatable(h):
    # Recreate the exact pre-cleanup audit table before inserting history.
    with h.engine.begin() as db:
        db.exec_driver_sql('DROP TABLE sop_task_events')
        db.exec_driver_sql('''CREATE TABLE sop_task_events (
            workspace_id VARCHAR(120) NOT NULL, id VARCHAR(64) NOT NULL,
            project_id VARCHAR(160) NOT NULL, task_id VARCHAR(64) NOT NULL,
            actor_id VARCHAR(120) NOT NULL, at FLOAT NOT NULL, kind VARCHAR(40) NOT NULL,
            revision INTEGER NOT NULL, changes JSON NOT NULL, PRIMARY KEY (workspace_id, id),
            FOREIGN KEY(workspace_id, project_id, task_id)
            REFERENCES sop_local_tasks (workspace_id, project_id, id))''')
        db.exec_driver_sql('CREATE INDEX ix_sop_task_events_project_id ON sop_task_events (project_id)')
    task = tag(h, manual(h))
    before = events(h)
    assert clean(h, task, 503)['code'] == 'import_unavailable'
    assert events(h) == before  # Failed deletion rolls back its cleanup event.
    migrate(h.engine)
    migrate(h.engine)
    assert events(h) == before
    assert inspect(h.engine).get_foreign_keys('sop_task_events') == []
    clean(h, task)
    assert {key: events(h)[key] for key in before} == before


def test_tagging_closed_tasks_and_inactive_or_revoked_authority(h):
    task = manual(h)
    archived = post(h, URL + f"/sop-tasks/{task['id']}/transition", {
        'expected_revision': 1, 'action': 'archive', 'reason': 'test'})['task']
    tagged = tag(h, archived)
    h.users['pm']['active'] = False
    assert clean(h, tagged, 403)['code'] == 'sop_import_forbidden'
    h.users['pm']['active'] = True
    original_refresh = h.service.lock_workspace_row

    def revoke_during_lock(db, wid):
        original_refresh(db, wid)
        h.who[0] = 'other'

    h.service.lock_workspace_row = revoke_during_lock
    assert clean(h, tagged, 403)['code'] == 'sop_import_forbidden'
    h.service.lock_workspace_row = original_refresh
    h.who[0] = 'pm'
    clean(h, tagged)


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
        migrate(engine)
        migrate(engine)
        with engine.begin() as db:
            db.exec_driver_sql('DELETE FROM sop_local_tasks')
            assert db.exec_driver_sql('SELECT * FROM sop_task_events').all() == before
        assert inspect(engine).get_foreign_keys('sop_task_events') == []
    finally:
        engine.dispose()


def test_cleanup_and_tag_honor_node_policy_and_case_visibility(h):
    from .sop_import.models import CasePolicy
    task = tag(h, manual(h))
    with h.sessions.begin() as db:
        db.add(CasePolicy(workspace_id='w', project_id='p1', policy='managed', revision=1,
                          decided_by='pm', decided_at=1000, reason='limited enrollment', facts={}, node_keys=['sales']))
    assert clean(h, task, 409)['code'] == 'node_not_enrolled'
    assert post(h, URL + f"/sop-tasks/{task['id']}/test-tag", {
        'expected_revision': task['revision'], 'is_test': False, 'reason': 'test'}, 409)['code'] == 'node_not_enrolled'
    h.hidden.add('p1')
    assert clean(h, task, 404)['code'] == 'case_not_found'


def test_prior_audit_is_still_immutable_after_cleanup(h):
    from .sop_import.domain import Failure
    task = tag(h, manual(h))
    clean(h, task)
    with pytest.raises(Failure, match='immutable_task_event'):
        with h.sessions.begin() as db:
            event = db.scalar(select(TaskEvent))
            event.changes = {'tampered': True}
    with pytest.raises(Failure, match='immutable_task_event'):
        with h.sessions.begin() as db:
            db.delete(db.scalar(select(TaskEvent)))
