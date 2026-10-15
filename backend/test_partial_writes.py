"""A partial write must leave the database exactly as the full write does.

Every converted action runs on one world through both paths (PARTIAL_WRITES_ENABLED off
and on, the latter strict so a footprint mistake fails instead of falling back). The
tests compare the HTTP answer and every table a write can touch: business_records,
workspaces, receipts, action_audit, project_index, task_index and workspace_counters.
"""
import pytest

from . import index_reads, index_tables, write_footprint
from .app import BusinessRow
from .models import WorkspaceRow
from .partial_testing import Pinned, Rig, first_difference
from .write_footprint import Rule, CASE_RECORDS
from .write_world import WID, build_world, scenarios

PROJECTS = 40


@pytest.fixture
def pair(tmp_path, monkeypatch):
    Pinned(monkeypatch)
    full = Rig(tmp_path, 'full', partial=False, projects=PROJECTS)
    partial = Rig(tmp_path, 'partial', partial=True, projects=PROJECTS, world=full.world)
    yield full, partial
    full.close(); partial.close()


def same(full, partial, label=''):
    difference = first_difference(full.dump(), partial.dump())
    assert difference is None, f'{label}: {difference}'


def both(full, partial, *args, **kwargs):
    a = full.act(*args, **kwargs); b = partial.act(*args, **kwargs)
    assert (a.status_code, a.json()) == (b.status_code, b.json())
    return a, b


def stored_version(rig):
    return rig.version()


CONVERTED = list(scenarios(build_world(PROJECTS), 1))


@pytest.mark.parametrize('action', CONVERTED)
def test_converted_action_stores_what_the_full_path_stores(pair, action):
    full, partial = pair
    user, fields = scenarios(full.world, 3)[action][1]
    a, b = both(full, partial, user, action, **fields)
    assert a.status_code == 200, a.text
    same(full, partial, action)
    assert partial.app.state.partial_writes == {'committed': 1, 'declined': 0}, 'the action did not take the partial path'
    assert partial.version() == 2


def test_a_run_of_different_actions_stays_identical(pair):
    full, partial = pair
    plan = scenarios(full.world, 6)
    for step, name in enumerate(['task_start', 'comment_add', 'task_complete', 'evidence_submit', 'task_add', 'file_link', 'task_start',
                                 'task_update', 'participants_update', 'task_return', 'evidence_approve', 'node_complete']):
        user, fields = plan[name][step % 4]
        a, b = both(full, partial, user, name, **fields)
        assert a.status_code == 200, (name, a.text)
        same(full, partial, f'after {name}')
    assert partial.app.state.partial_writes['declined'] == 0


def test_review_vote_after_node_complete_matches(pair):
    full, partial = pair
    user, fields = scenarios(full.world, 1)['node_complete'][0]
    a, b = both(full, partial, user, 'node_complete', **fields)
    node = next(n for p in b.json()['projects'] if p['id'] == fields['project_id'] for n in p['nodes'] if n['id'] == fields['node_id'])
    cycle = node['review_cycles'][-1]
    a, b = both(full, partial, user, 'review_vote', **fields, payload={'cycle_id': cycle['id'], 'seat': 'owner', 'result': 'approved'})
    assert a.status_code == 200, a.text
    same(full, partial, 'review_vote')
    assert partial.app.state.partial_writes['declined'] == 0


def test_replaying_a_request_id_changes_nothing_and_answers_the_same(pair):
    full, partial = pair
    user, fields = scenarios(full.world, 1)['comment_add'][0]
    both(full, partial, user, 'comment_add', request_id='once', **fields)
    before = partial.dump()
    a, b = both(full, partial, user, 'comment_add', request_id='once', version=1, **fields)
    assert b.status_code == 200
    assert partial.dump() == before
    same(full, partial, 'replay')
    other = dict(fields, payload={'body': '不同內容'})
    a, b = both(full, partial, user, 'comment_add', request_id='once', **other)
    assert b.status_code == 409


def test_a_stale_workspace_version_conflicts_without_writing(pair):
    full, partial = pair
    plan = scenarios(full.world, 3)
    both(full, partial, *[plan['comment_add'][0][0], 'comment_add'], **plan['comment_add'][0][1])
    user, fields = plan['task_start'][0]
    before = partial.dump()
    a, b = both(full, partial, user, 'task_start', version=1, **fields)
    assert b.status_code == 409
    same(full, partial, 'stale version')
    after = partial.dump()
    assert {k: v for k, v in after.items() if k != 'action_audit'} == {k: v for k, v in before.items() if k != 'action_audit'}


def test_project_versions_decide_conflicts_per_case_and_bump_only_that_case(pair):
    full, partial = pair
    plan = scenarios(full.world, 3)
    (user_a, fields_a), (user_b, fields_b) = plan['comment_add'][0], plan['comment_add'][1]
    a_id, b_id = fields_a['project_id'], fields_b['project_id']
    start = {a_id: partial.project_version(a_id), b_id: partial.project_version(b_id)}
    both(full, partial, user_a, 'comment_add', version=1, project_versions={a_id: start[a_id]}, **fields_a)
    assert partial.project_version(a_id) == start[a_id] + 1 and partial.project_version(b_id) == start[b_id]
    a, b = both(full, partial, user_b, 'comment_add', version=1, project_versions={b_id: start[b_id]}, **fields_b)
    assert b.status_code == 200, 'a write on another case must not be refused by the first one'
    a, b = both(full, partial, user_a, 'comment_add', version=3, project_versions={a_id: start[a_id]}, **fields_a)
    assert b.status_code == 409
    same(full, partial, 'per case versions')


@pytest.mark.parametrize('user,action,fields,status', [
    ('ou_040', 'task_start', None, 403),
    ('u-pm', 'task_start', {'project_id': 'p001', 'task_id': 'missing'}, 404),
    ('u-pm', 'task_start', {'project_id': 'no-such-case', 'task_id': 'x'}, 404),
    ('u-pm', 'comment_add', {'project_id': 'p001', 'payload': {'body': '   '}}, 400),
])
def test_rejected_requests_answer_and_audit_like_the_full_path(pair, user, action, fields, status):
    full, partial = pair
    if fields is None:
        _, fields = scenarios(full.world, 1)['task_start'][0]
    a, b = both(full, partial, user, action, **fields)
    assert b.status_code == status, b.text
    same(full, partial, 'rejection')


def test_the_index_stays_ready_and_serves_the_same_pages(pair):
    full, partial = pair
    plan = scenarios(full.world, 6)
    for name in ('task_start', 'task_complete', 'comment_add', 'node_complete', 'task_add'):
        user, fields = plan[name][2]
        both(full, partial, user, name, **fields)
    with partial.app.state.sessions() as db:
        row = db.get(WorkspaceRow, WID)
        assert index_reads.ready(db, BusinessRow, row)
        state = partial.app.state
    for path in ('/api/projects?view=overview', '/api/workspace?scope=shell', '/api/projects?limit=100'):
        a, b = full.get('u-manager', path), partial.get('u-manager', path)
        assert a.status_code == b.status_code == 200, path
        left, right = a.json(), b.json()
        left.pop('freshness', None); right.pop('freshness', None)
        assert {k: v for k, v in left.items() if v != right.get(k)} == {}, (path, [k for k in left if left[k] != right.get(k)])
    with partial.app.state.sessions() as db:
        from . import storage
        from .policy import upgrade
        row = db.get(WorkspaceRow, WID)
        stored = upgrade(storage.load(db, BusinessRow, row)); stored['version'] = row.version
        assert index_tables.reconcile(db, BusinessRow, WID, stored)['healthy']


def test_the_footprint_cut_is_the_work_the_lock_holds(pair, monkeypatch):
    """A one case write must not load or save the other cases."""
    from . import storage
    full, partial = pair
    seen = {'load': 0, 'save': 0}
    for name in ('load', 'save'):
        original = getattr(storage, name)
        monkeypatch.setattr(storage, name, lambda *a, _o=original, _n=name, **k: (seen.__setitem__(_n, seen[_n] + 1), _o(*a, **k))[1])
    user, fields = scenarios(partial.world, 1)['task_start'][0]
    partial.act(user, 'task_start', **fields)
    # The only full load left is the response read after the lock is released.
    assert seen == {'load': 1, 'save': 0}
    full.act(user, 'task_start', **fields)
    assert seen == {'load': 2, 'save': 1}


def only(response, key='node_skip_requests'):
    return response.json()[key][-1]


def test_a_node_skip_runs_from_request_to_applied_identically(pair):
    full, partial = pair
    user, fields = scenarios(full.world, 1)['node_skip_create'][0]
    project, node = fields['project_id'], fields['node_id']
    a, b = both(full, partial, user, 'node_skip_create', **fields)
    request = only(b)['id']
    same(full, partial, 'node_skip_create')
    where = dict(project_id=project, node_id=node)
    both(full, partial, user, 'node_skip_submit', payload={'id': request}, **where)
    both(full, partial, user, 'node_skip_vote', payload={'id': request, 'seat': 'pm', 'result': 'approved'}, **where)
    both(full, partial, 'u-manager', 'node_skip_vote', payload={'id': request, 'seat': 'supervisor', 'result': 'approved'}, **where)
    a, b = both(full, partial, user, 'node_skip_apply', payload={'id': request}, **where)
    assert a.status_code == 200, a.text
    same(full, partial, 'node_skip_apply')
    assert partial.app.state.partial_writes['declined'] == 0


def test_a_withdrawn_node_skip_matches(pair):
    full, partial = pair
    user, fields = scenarios(full.world, 1)['node_skip_create'][0]
    a, b = both(full, partial, user, 'node_skip_create', **fields)
    where = dict(project_id=fields['project_id'], node_id=fields['node_id'])
    a, b = both(full, partial, user, 'node_skip_withdraw', payload={'id': only(b)['id'], 'reason': '客戶改變心意'}, **where)
    assert a.status_code == 200, a.text
    same(full, partial, 'node_skip_withdraw')


def test_delivery_is_submitted_and_reviewed_identically(pair):
    full, partial = pair
    user, fields = scenarios(full.world, 1)['delivery_submit'][0]
    a, b = both(full, partial, user, 'delivery_submit', **fields)
    batch = b.json()['projects']
    batch = next(p for p in batch if p['id'] == fields['project_id'])['delivery_batches'][-1]
    a, b = both(full, partial, 'u-manager', 'delivery_review', project_id=fields['project_id'], payload={'id': batch['id'], 'result': 'approved'})
    assert a.status_code == 200, a.text
    same(full, partial, 'delivery_review')
    assert partial.app.state.partial_writes['declined'] == 0


def test_a_returned_review_vote_matches(pair):
    full, partial = pair
    user, fields = scenarios(full.world, 1)['node_complete'][0]
    a, b = both(full, partial, user, 'node_complete', **fields)
    node = next(n for p in b.json()['projects'] if p['id'] == fields['project_id'] for n in p['nodes'] if n['id'] == fields['node_id'])
    a, b = both(full, partial, user, 'review_vote', **fields, payload={'cycle_id': node['review_cycles'][-1]['id'], 'seat': 'owner', 'result': 'returned', 'reason': '資料不足'})
    assert a.status_code == 200, a.text
    same(full, partial, 'returned vote')


def test_mentions_load_the_job_queue_and_still_match(pair):
    full, partial = pair
    user, fields = scenarios(full.world, 1)['comment_add'][0]
    fields = dict(fields, payload={'body': '請 @員工031 看', 'mentions': ['ou_031', 'ou_032']})
    a, b = both(full, partial, user, 'comment_add', **fields)
    assert a.status_code == 200, a.text
    same(full, partial, 'mentions')
    assert partial.app.state.partial_writes == {'committed': 1, 'declined': 0}


def test_every_registered_action_has_an_equivalence_test():
    covered = set(CONVERTED) | {'node_skip_submit', 'node_skip_vote', 'node_skip_apply', 'node_skip_withdraw', 'delivery_review', 'review_vote'}
    assert set(write_footprint.RULES) == covered
