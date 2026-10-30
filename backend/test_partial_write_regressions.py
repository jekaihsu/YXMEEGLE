import pytest

from copy import deepcopy

from . import index_reads, source_sync, storage
from .models import BusinessRow, WorkspaceRow
from .partial_testing import Rig
from .test_source_sync import records, snapshot
from .write_world import scenarios


@pytest.fixture
def rig(tmp_path):
    rig = Rig(tmp_path, 'regressions', partial=True, projects=4, production=True)
    yield rig
    rig.close()


def assert_ready(rig):
    with rig.app.state.sessions() as db:
        assert index_reads.ready(db, BusinessRow, db.get(WorkspaceRow, rig.wid))
    response = rig.get('u-manager', '/api/projects?view=overview')
    assert response.status_code == 200, response.text


@pytest.mark.parametrize('attempt', ['unchanged', 'failure', 'scheduled', 'roster', 'attendance', 'migration', 'ops'])
def test_metadata_write_then_partial_comment_preserves_index_readiness(rig, monkeypatch, attempt):
    monkeypatch.setattr(source_sync, 'now', lambda: '2026-10-15T08:00:00+08:00')
    service = rig.app.state.source_sync
    policy = service._policy(rig.wid)
    def sync(clock):
        with rig.app.state.sessions() as db:
            generation = db.get(WorkspaceRow, rig.wid).data.get('source_status', {}).get('sync_revision', 0)
        return service.apply_snapshot(rig.wid, snapshot(clock, records()), 'u-manager',
                                      expected_policy=policy, expected_generation=generation, skip_unchanged=True)
    sync('2026-10-15T08:00:00+08:00')
    assert_ready(rig)
    if attempt == 'unchanged': sync('2026-10-15T08:05:00+08:00')
    elif attempt == 'failure': service.failure(rig.wid, 'temporary failure')
    elif attempt == 'scheduled':
        monkeypatch.setattr(source_sync, 'now', lambda: '2026-10-15T09:00:00+08:00')
        calls = []
        def scheduled_sync(*args):
            assert_ready(rig)
            calls.append(args)
        monkeypatch.setattr(service, 'sync', scheduled_sync)
        service.run_due(rig.wid)
        assert calls == [(rig.wid, None)]
    elif attempt in ('roster', 'attendance'):
        directory = rig.app.state.people_directory
        collections = ('users',) if attempt == 'roster' else ('users', 'work_schedules')
        with rig.app.state.sessions.begin() as db:
            row = db.get(WorkspaceRow, rig.wid)
            state = directory._state(db, row, collections)
            state['people_directory_status']['message'] = 'updated metadata'
            directory._save(db, row, state, collections)
    elif attempt == 'migration':
        from .workspace_migration import migrate_workspaces
        from .policy import upgrade
        with rig.app.state.sessions.begin() as db:
            row = db.get(WorkspaceRow, rig.wid)
            row.data = {**deepcopy(row.data), 'migration_archive': {}}
        assert migrate_workspaces(rig.app.state.sessions, WorkspaceRow, BusinessRow, upgrade, storage) == [rig.wid]
    else:
        from .ops_sync.workspace_store import WorkspaceStore
        WorkspaceStore(rig.app.state.sessions, rig.wid).transact(lambda state: state.update(local_edit=True))
    assert_ready(rig)
    user, fields = scenarios(rig.world, 1)['comment_add'][0]
    response = rig.act(user, 'comment_add', **fields)
    assert response.status_code == 200, response.text
    assert rig.app.state.last_write['path'] == 'partial'
    assert_ready(rig)


def test_partial_response_uses_one_snapshot_when_a_writer_commits_after_the_header(rig, monkeypatch):
    if rig.app.state.engine.dialect.name == 'sqlite':
        with rig.app.state.engine.connect() as connection:
            connection.exec_driver_sql('PRAGMA journal_mode=WAL')
    user, fields = scenarios(rig.world, 1)['comment_add'][0]
    original = storage.load
    interleaved = []
    def load_after_writer(db, model, row):
        if row.version == 2 and not interleaved:
            interleaved.append(True)
            with rig.app.state.sessions.begin() as writer:
                current = writer.get(WorkspaceRow, rig.wid)
                state = original(writer, model, current)
                project = next(p for p in state['projects'] if p['id'] == fields['project_id'])
                task = next(t for n in project['nodes'] for t in n['tasks'] if t['id'] == fields['task_id'])
                task['comments'].append({'id': 'later-comment', 'body': 'later writer', 'author_id': user,
                                         'created_at': '2026-10-15T08:01:00+08:00'})
                state['version'] = current.version + 1
                current.data = storage.save(writer, model, rig.wid, state)
                current.version = state['version']
        return original(db, model, row)
    monkeypatch.setattr(storage, 'load', load_after_writer)
    response = rig.act(user, 'comment_add', **fields)
    assert response.status_code == 200, response.text
    assert interleaved == [True] and rig.version() == 3
    state = response.json()
    project = next(p for p in state['projects'] if p['id'] == fields['project_id'])
    task = next(t for n in project['nodes'] for t in n['tasks'] if t['id'] == fields['task_id'])
    assert state['version'] == 2
    assert project['concurrency_version'] == 2
    assert [c['body'] for c in task['comments']] == ['請確認']
    with rig.app.state.sessions() as db:
        current = original(db, BusinessRow, db.get(WorkspaceRow, rig.wid))
        project = next(p for p in current['projects'] if p['id'] == fields['project_id'])
        task = next(t for n in project['nodes'] for t in n['tasks'] if t['id'] == fields['task_id'])
        assert [c['body'] for c in task['comments']] == ['請確認', 'later writer']
