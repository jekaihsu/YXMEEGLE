"""Writers that share one workspace keep today's version semantics when each write is partial.

The workspace row lock still serializes commits; what changes is that it now covers a few
rows. These tests start real threads against one database (PostgreSQL when
PARTIAL_WRITES_TEST_POSTGRES_URL is set, otherwise SQLite, whose file lock is coarser).
"""
import threading
import uuid
from time import monotonic

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from . import index_tables, storage
from .app import BusinessRow
from .models import WorkspaceRow
from .partial_testing import POSTGRES, Rig
from .policy import upgrade
from .write_world import WID, scenarios


@pytest.fixture
def rig(tmp_path):
    rig = Rig(tmp_path, 'threads', partial=True, projects=24)
    yield rig
    rig.close()


def post_together(rig, requests):
    """Send every (user, body) from its own client at the same moment; returns responses in order."""
    gate = threading.Barrier(len(requests)); results = [None] * len(requests)
    def send(i, user, body):
        client = TestClient(rig.app)
        client.cookies.set('meegle_session', rig.app.state.signer.dumps({'mode': 'demo', 'uid': user, 'wid': WID}))
        gate.wait()
        results[i] = client.post('/api/actions', json=body)
    threads = [threading.Thread(target=send, args=(i, user, body)) for i, (user, body) in enumerate(requests)]
    for t in threads: t.start()
    for t in threads: t.join(60)
    return results


def comment(fields, version, project_versions=None):
    body = {'action': 'comment_add', 'version': version, 'request_id': uuid.uuid4().hex, 'project_id': fields['project_id'],
            'node_id': fields.get('node_id'), 'task_id': fields.get('task_id'), 'payload': fields.get('payload', {})}
    if project_versions is not None: body['project_versions'] = project_versions
    return body


@pytest.mark.skipif(not POSTGRES, reason='SQLite has no row lock: concurrent writers race on the version check, before and after this change')
def test_writers_on_different_cases_all_commit_with_their_own_versions(rig):
    targets = scenarios(rig.world, 4)['comment_add'][:4]
    start = {f['project_id']: rig.project_version(f['project_id']) for _, f in targets}
    answers = post_together(rig, [(u, comment(f, 1, {f['project_id']: start[f['project_id']]})) for u, f in targets])
    assert [a.status_code for a in answers] == [200] * 4, [a.text[:120] for a in answers]
    assert rig.version() == 5
    assert {pid: rig.project_version(pid) for pid in start} == {pid: v + 1 for pid, v in start.items()}
    assert rig.app.state.partial_writes == {'committed': 4, 'declined': 0}
    with rig.app.state.sessions() as db:
        state = upgrade(storage.load(db, BusinessRow, db.get(WorkspaceRow, WID))); state['version'] = 5
        for _, f in targets:
            project = next(p for p in state['projects'] if p['id'] == f['project_id'])
            assert [c['body'] for n in project['nodes'] for t in n['tasks'] for c in t['comments'] if c['body'] == '請確認'] == ['請確認']
        assert index_tables.reconcile(db, BusinessRow, WID, state)['healthy']


def test_two_writers_on_one_case_with_the_same_project_version_conflict(rig):
    (user, fields), = scenarios(rig.world, 1)['comment_add']
    version = rig.project_version(fields['project_id'])
    answers = post_together(rig, [(user, comment(fields, 1, {fields['project_id']: version})) for _ in range(2)])
    assert sorted(a.status_code for a in answers) == [200, 409]
    assert rig.project_version(fields['project_id']) == version + 1 and rig.version() == 2


def test_two_writers_without_project_versions_conflict_on_the_workspace_version(rig):
    plan = scenarios(rig.world, 2)['comment_add']
    answers = post_together(rig, [(u, comment(f, 1)) for u, f in plan])
    assert sorted(a.status_code for a in answers) == [200, 409]
    assert rig.version() == 2


@pytest.mark.skipif(not POSTGRES, reason='needs the row lock')
def test_a_partial_writer_queues_behind_a_full_path_writer_and_sees_its_version(rig):
    """calendar_update stays on the full path and rewrites every case, so the queued comment's case version is stale."""
    (user, fields), = scenarios(rig.world, 1)['comment_add']
    version = rig.project_version(fields['project_id'])
    calendar = {'action': 'calendar_update', 'version': 1, 'request_id': uuid.uuid4().hex, 'payload': {'holidays': ['2026-12-25'], 'workdays': []}}
    locked, release, attempted = threading.Event(), threading.Event(), threading.Event()
    answers, errors, partial_pid = {}, [], []
    def before_query(connection, cursor, statement, parameters, context, executemany):
        if 'FROM workspaces' in statement and 'FOR UPDATE' in statement and locked.is_set() and not release.is_set():
            partial_pid.append(cursor.connection.info.backend_pid)
            attempted.set()
    def after_query(connection, cursor, statement, parameters, context, executemany):
        if 'FROM workspaces' in statement and 'FOR UPDATE' in statement and not locked.is_set():
            locked.set()
            assert release.wait(15), 'the test did not release the full writer'
    def send(name, actor, body):
        try:
            with TestClient(rig.app) as client:
                client.cookies.set('meegle_session', rig.app.state.signer.dumps({'mode': 'demo', 'uid': actor, 'wid': WID}))
                answers[name] = client.post('/api/actions', json=body)
        except BaseException as exc:
            errors.append(exc)
    event.listen(rig.app.state.engine, 'before_cursor_execute', before_query)
    event.listen(rig.app.state.engine, 'after_cursor_execute', after_query)
    full = threading.Thread(name='full-writer', target=send, args=('full', 'u-manager', calendar))
    partial = threading.Thread(name='partial-writer', target=send,
                               args=('partial', user, comment(fields, 1, {fields['project_id']: version})))
    try:
        full.start()
        assert locked.wait(10), errors
        partial.start()
        assert attempted.wait(10), errors
        deadline = monotonic() + 5
        blockers = []
        with rig.app.state.engine.connect() as connection:
            while monotonic() < deadline:
                blockers = connection.scalar(text('SELECT pg_blocking_pids(:pid)'), {'pid': partial_pid[0]})
                if blockers: break
                release.wait(0.01)
        assert blockers, 'the partial writer never waited on the full writer row lock'
        assert 'partial' not in answers
    finally:
        release.set()
        full.join(20)
        if partial.ident is not None: partial.join(20)
        event.remove(rig.app.state.engine, 'before_cursor_execute', before_query)
        event.remove(rig.app.state.engine, 'after_cursor_execute', after_query)
    assert not full.is_alive() and not partial.is_alive() and not errors
    assert answers['full'].status_code == 200, answers['full'].text
    assert answers['partial'].status_code == 409, answers['partial'].text
    assert rig.version() == 2
