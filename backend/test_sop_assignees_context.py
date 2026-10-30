"""Assignee reads retain the full case loader's permissions and roster, using isolated fixtures."""
from copy import deepcopy

import pytest
from sqlalchemy import event, select

from . import storage
from .models import BusinessRow, PersonRow, WorkspaceRow
from .test_sop_assignment_loop import imported
from .test_sop_local_case import local  # noqa: F401
from .test_sop_quotes import WID


def same_as_old(client, url, monkeypatch, status=200):
    current = client.get(url)
    original = storage.load_partial

    def old_case_load(*args, **kwargs):
        if kwargs.get('project_details') is False:
            kwargs.update(collections=storage.CASE_COLLECTIONS, project_details=True)
        return original(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(storage, 'load_partial', old_case_load)
        reference = client.get(url)
    assert current.status_code == reference.status_code == status, (current.text, reference.text)
    assert current.content == reference.content
    assert current.headers['cache-control'] == reference.headers['cache-control'] == 'no-store'
    return current.json()


def setup(local):
    app, client, signin, path, mine, _ = imported(local)
    pid = path.split('/')[3]
    with app.state.sessions.begin() as db:
        project = db.get(BusinessRow, (WID, 'projects', pid))
        project.data = {**project.data, 'admin_id': 'u-report', 'supervisor_id': 'u-map',
                        'collaborator_ids': ['u-control'], 'sop_task_delegate_ids': ['u-agent']}
        db.add(PersonRow(organization_id=WID, person_id='outsider', data={
            'id': 'outsider', 'name': '同名', 'role': 'member', 'capabilities': [], 'active': True}))
        db.add(PersonRow(organization_id=WID, person_id='inactive', data={
            'id': 'inactive', 'name': '同名', 'role': 'manager', 'active': False}))
    return app, client, signin, pid, mine


@pytest.mark.parametrize('legacy', [False, True], ids=['normalized', 'legacy'])
def test_every_actor_gets_the_old_status_and_exact_list(local, monkeypatch, legacy):
    app, client, signin, pid, _ = setup(local)
    formal = local[3]['formal']
    with app.state.sessions.begin() as db:
        hidden = next(r.entity_id for r in db.scalars(select(BusinessRow).where(
            BusinessRow.workspace_id == WID, BusinessRow.kind == 'projects'))
            if r.data.get('case_visibility') == 'excluded_history')
        if legacy:
            row = db.get(WorkspaceRow, WID)
            state = storage.load(db, BusinessRow, row)
            state.pop('storage_schema', None)
            row.data = state
        originals = {r.person_id: deepcopy(r.data) for r in db.scalars(select(PersonRow).where(
            PersonRow.organization_id == WID))}

    scenarios = [
        ('u-manager', {}, pid, 200, False),
        ('u-manager', {'role': 'admin', 'capabilities': []}, pid, 200, False),
        ('u-manager', {'capabilities': []}, pid, 200, False),
        ('u-pm', {'capabilities': []}, pid, 200, False),
        ('u-agent', {}, pid, 200, False),
        ('u-field', {}, pid, 200, False),
        ('u-control', {}, pid, 200, False),
        ('u-map', {}, pid, 200, True),
        ('u-report', {}, pid, 200, True),
        ('outsider', {}, pid, 404, None),
        ('outsider', {}, formal, 403, None),
        ('outsider', {'capabilities': ['sop_task_read']}, formal, 200, False),
        ('outsider', {'role': 'manager'}, formal, 200, False),
        ('u-pm', {'active': False}, pid, 403, None),
        ('u-manager', {}, hidden, 404, None),
        ('u-manager', {}, 'wrong-project', 404, None),
        ('outsider', {}, 'wrong-project', 404, None),
        (None, {}, pid, 401, None),
        (None, {}, 'wrong-project', 401, None),
    ]
    for actor, changes, project, status, restricted in scenarios:
        if actor:
            with app.state.sessions.begin() as db:
                profile = db.get(PersonRow, (WID, actor))
                profile.data = {**originals[actor], **changes}
            signin(actor)
        else:
            client.cookies.clear()
        body = same_as_old(client, f'/api/projects/{project}/sop-assignees', monkeypatch, status)
        if status == 200:
            assert body['restricted'] is restricted
            assert all(p['id'] != 'inactive' for p in body['people'])
            if restricted:
                assert [p['id'] for p in body['people']] == [actor]
        if actor:
            with app.state.sessions.begin() as db:
                db.get(PersonRow, (WID, actor)).data = originals[actor]

    app.state.cfg['HR_VIEWERS'] = 'u-manager'
    for actor, restricted in [('u-field', True), ('u-control', True), ('u-pm', False), ('u-agent', False)]:
        signin(actor)
        body = same_as_old(client, f'/api/projects/{pid}/sop-assignees', monkeypatch)
        assert body['restricted'] is restricted


def test_assignees_only_fetch_the_project_header_and_fresh_roster(local, monkeypatch):
    app, client, signin, pid, _ = setup(local)
    signin('u-manager')
    calls = []
    original = storage.load_partial

    def record(*args, **kwargs):
        state = original(*args, **kwargs)
        calls.append((kwargs, state))
        return state

    monkeypatch.setattr(storage, 'load_partial', record)
    sql = []

    def queries(conn, cursor, statement, params, context, many):
        if 'business_records' in statement:
            sql.append(repr(params))

    event.listen(app.state.engine, 'before_cursor_execute', queries)
    try:
        assert client.get(f'/api/projects/{pid}/sop-assignees').status_code == 200
    finally:
        event.remove(app.state.engine, 'before_cursor_execute', queries)
    cases = [(args, state) for args, state in calls if args.get('project_ids')]
    assert len(cases) == 1
    args, state = cases[0]
    assert args['collections'] == ('users',) and args['project_details'] is False
    assert [p['id'] for p in state['projects']] == [pid]
    assert state['projects'][0]['nodes'] == []
    assert all(state['projects'][0][key] == [] for key in storage.PROJECT_CHILDREN)
    forbidden = set(storage.CASE_COLLECTIONS) - {'users'} | {'nodes', 'tasks', 'review_cycles'}
    assert not any(repr(kind) in params for params in sql for kind in forbidden)


def test_warm_reads_recheck_roster_project_and_participation_without_version_bumps(local, monkeypatch):
    from .sop_import.models import LocalTask

    app, client, signin, pid, mine = setup(local)
    url = f'/api/projects/{pid}/sop-assignees?scope=all'
    signin('u-manager')
    before = same_as_old(client, url, monkeypatch)
    with app.state.sessions.begin() as db:
        profile = db.get(PersonRow, (WID, 'u-control'))
        profile.data = {**profile.data, 'name': '名冊已更新', 'department': '新部門', 'active': False}
        project = db.get(BusinessRow, (WID, 'projects', pid))
        project.data = {**project.data, 'pm_id': 'u-map'}
    after = same_as_old(client, url, monkeypatch)
    assert after != before and 'u-control' not in [p['id'] for p in after['people']]
    assert next(p for p in after['people'] if p['id'] == 'u-map')['case_roles'] == ['pm', 'supervisor']

    signin('u-map')
    assert same_as_old(client, url, monkeypatch)['restricted'] is False
    with app.state.sessions.begin() as db:
        project = db.get(BusinessRow, (WID, 'projects', pid))
        project.data = {**project.data, 'pm_id': 'u-pm'}
    assert same_as_old(client, url, monkeypatch)['restricted'] is True
    with app.state.sessions.begin() as db:
        task = db.get(LocalTask, (WID, mine['id']))
        task.participants = {'executor': 'u-pm'}
    same_as_old(client, url, monkeypatch, 404)

    signin('outsider')
    formal_url = f"/api/projects/{local[3]['formal']}/sop-assignees"
    with app.state.sessions.begin() as db:
        profile = db.get(PersonRow, (WID, 'outsider'))
        profile.data = {**profile.data, 'capabilities': ['sop_task_read']}
    same_as_old(client, formal_url, monkeypatch)
    with app.state.sessions.begin() as db:
        profile = db.get(PersonRow, (WID, 'outsider'))
        profile.data = {**profile.data, 'capabilities': []}
    same_as_old(client, formal_url, monkeypatch, 403)
