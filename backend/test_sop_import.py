from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, event
from sqlalchemy.orm import sessionmaker

from .models import Base, BusinessRow, WorkspaceRow
from .sop_import.catalog import load_catalog, stage, publish
from .sop_import.domain import NODE_MAP
from .sop_import.models import LocalTask, TaskNodeLink, ImportRun, TaskEvent, Preview, CaseState, Version
from .sop_import.routes import register
from .source_case_policy import visible_project

URL = '/api/projects/p1'
CAPS = ['sop_task_read', 'sop_task_import', 'sop_task_work', 'sop_task_read_source', 'sop_template_publish']


@pytest.fixture
def h(tmp_path, monkeypatch):
    engine = create_engine(f'sqlite:///{tmp_path}/sop.db', connect_args={'check_same_thread': False, 'timeout': 20})

    @event.listens_for(engine, 'connect')
    def foreign_keys(connection, record):
        connection.execute('PRAGMA foreign_keys=ON')

    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    users = {'pm': {'id': 'pm', 'name': '林育寬', 'role': 'pm', 'active': True, 'capabilities': CAPS[:]},
             'other': {'id': 'other', 'name': '吳柏頤', 'role': 'pm', 'active': True, 'capabilities': CAPS[:]},
             'member': {'id': 'member', 'name': '陳柏翰', 'role': 'member', 'active': True,
                        'capabilities': ['sop_task_work', 'sop_task_read']},
             'manager': {'id': 'manager', 'name': '張智偉', 'role': 'manager', 'active': True, 'capabilities': []}}
    with sessions.begin() as db:
        for wid in ('w', 'other-w'):
            db.add(WorkspaceRow(id=wid, version=1, data={}))
        db.flush()
        for pid in ('p1', 'p2'):
            db.add(BusinessRow(workspace_id='w', kind='projects', entity_id=pid, parent_id='', ordinal=0,
                               data={'id': pid, 'pm_id': 'pm', 'collaborator_ids': ['member'], 'case_visibility': 'source_reference'}))
            for i, key in enumerate(NODE_MAP.values()):
                db.add(BusinessRow(workspace_id='w', kind='nodes', entity_id=f'real-{pid}-{i}', parent_id=pid,
                                   ordinal=8-i, data={'id': f'real-{pid}-{i}', 'key': key, 'title': 'unreliable', 'tasks': []}))
        v = stage(db, 'w', 'r1', load_catalog(), source_verified=True)
        publish(db, v, 'publisher', 100)
        vid = v.id
    who, wid, hidden, extra = ['pm'], ['w'], set(), {}
    cfg = {'SOP_TASK_WRITES_ENABLED': 'true'}

    def identity(request):
        if who[0] == 'expired':
            raise HTTPException(401)
        return {'wid': wid[0], 'mode': 'lark'}, users[who[0]]

    def load_case(data, user, project_id):
        with sessions() as db:
            row = db.get(BusinessRow, (data['wid'], 'projects', project_id))
            state = {'users': list(users.values()), 'source_case_policy_revision': 'all-authorized-lark-cases-20260930',
                     **deepcopy(extra)}
            if row is None or project_id in hidden or not visible_project(state, row.data):
                raise HTTPException(404)
            return state, deepcopy(row.data)

    app = FastAPI()
    service = register(app, identity=identity, load_case=load_case, sessions=sessions, cfg=cfg)
    service.clock = lambda: 1000
    writes = []

    def no_outbound(*args, **kwargs):
        writes.append(1)
        raise AssertionError('outbound network is forbidden')
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', no_outbound)
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, sessions=sessions, engine=engine, vid=vid, who=who, wid=wid,
                              users=users, hidden=hidden, cfg=cfg, service=service, writes=writes, extra=extra)
    assert writes == []
    engine.dispose()


def post(h, path, body, status=200):
    response = h.client.post(path, json=body)
    assert response.status_code == status, response.text
    return response.json()


def preview(h, *, url=URL, **extra):
    return post(h, url + '/sop-import/preview', {'template_version_id': h.vid, **extra})


def apply(h, plan=None, rid='r1', *, url=URL, status=200):
    plan = plan or preview(h, url=url)
    return post(h, url + '/sop-import/apply', {'preview_id': plan['preview_id'], 'request_id': rid}, status)


def overview(h, url=URL, query=''):
    response = h.client.get(url + '/sop-tasks' + query)
    assert response.status_code == 200, response.text
    return response.json()


def change(h, task, body, status=200):
    response = h.client.patch(URL + '/sop-tasks/' + task['id'], json={'expected_revision': task['revision'], **body})
    assert response.status_code == status, response.text
    return response.json()


def test_at02_at03_node_ids_are_persisted_keys_not_order_or_title(h):
    plan = preview(h, node_keys=['confirmation'])
    assert plan['nodes'] == [{'node_key': 'confirmation', 'node_id': 'real-p1-2'}]
    assert [(o['source_row_key'], o['node_keys']) for o in plan['outcomes']] == [
        (f'meegle-v137:A:{i}', ['confirmation']) for i in (19, 59, 60, 61, 22)]
    routine = [(o['source_row_key'], o['disposition'], o['node_keys']) for o in preview(h)['outcomes'] if not o['node_keys']]
    assert routine == [('meegle-v137:A:27', 'routine_excluded', []), ('meegle-v137:A:57', 'routine_excluded', []),
                       ('meegle-v137:A:28', 'disabled_excluded', []), ('meegle-v137:A:58', 'disabled_excluded', [])]
    receipt = apply(h, plan)
    assert len(receipt['created_task_ids']) == 5
    assert overview(h)['counts'] == {'done': 0, 'total': 4, 'unresolved': 1, 'not_applicable': 0, 'archived': 0}
    with h.sessions.begin() as db:
        db.delete(db.get(BusinessRow, ('w', 'nodes', 'real-p1-2')))
    assert post(h, URL + '/sop-import/preview', {'template_version_id': h.vid, 'node_keys': ['confirmation']}, 422) == {
        'code': 'node_mapping_invalid', 'detail': 'node_mapping_invalid', 'node_key': 'confirmation'}


def test_preview_errors_name_the_offending_row_or_node(h):
    body = {'template_version_id': h.vid, 'node_keys': ['sales']}
    assert post(h, URL + '/sop-import/preview', {**body, 'node_keys': ['sales', 'N02']}, 422)['node_key'] == 'N02'
    assert post(h, URL + '/sop-import/preview', {**body, 'node_keys': []}, 422) == {
        'code': 'node_mapping_invalid', 'detail': 'node_mapping_invalid'}
    foreign = post(h, URL + '/sop-import/preview', {**body, 'row_keys': ['meegle-v137:A:1', 'meegle-v137:A:19']}, 422)
    assert (foreign['code'], foreign['source_row_key']) == ('row_not_importable', 'meegle-v137:A:19')
    unresolved = post(h, URL + '/sop-import/preview', {'template_version_id': h.vid, 'node_keys': ['sales'],
                                                      'row_keys': ['meegle-v137:A:1', 'meegle-v137:A:7']}, 422)
    assert (unresolved['code'], unresolved['source_row_key']) == ('applicability_unresolved', 'meegle-v137:A:7')


def test_at04_at05_case_isolation_repeat_preserves_local_edits_and_template(h):
    first = apply(h)
    apply(h, rid='case-b', url='/api/projects/p2')
    before = overview(h)
    task = before['tasks'][0]
    change(h, task, {'title': 'Local title', 'instructions': 'Local procedure'})
    repeat = apply(h, rid='r2')
    assert repeat['created_task_ids'] == [] and repeat['added_links'] == []
    assert set(repeat['existing_task_ids']) == set(first['created_task_ids'])
    assert overview(h)['tasks'][0]['title'] == 'Local title'
    assert overview(h, '/api/projects/p2')['tasks'][0]['title'] == task['title']
    catalog = h.client.get('/api/sop-templates/' + h.vid).json()
    assert catalog['rows'][1]['raw']['title'] == task['title']
    assert len(first['created_task_ids']) == 38
    assert len(first['added_links']) == 42
    assert before['checklist_revision'] == 1
    assert overview(h)['checklist_revision'] == 2


def test_at06_concurrent_replay_and_stale_selection_converge(h):
    plan = preview(h)
    body = {'preview_id': plan['preview_id'], 'request_id': 'parallel'}
    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(executor.map(lambda _: h.client.post(URL + '/sop-import/apply', json=body), range(4)))
    assert [r.status_code for r in responses] == [200] * 4
    assert sum(not r.json()['replayed'] for r in responses) == 1
    assert len({tuple(r.json()['created_task_ids']) for r in responses}) == 1
    stale = plan
    assert apply(h, stale, 'different', status=409)['code'] == 'preview_stale'
    assert apply(h, rid='refreshed')['created_task_ids'] == []
    assert len(overview(h)['tasks']) == 38
    with h.sessions() as db:
        assert len(list(db.scalars(select(LocalTask)))) == 38
        assert len(list(db.scalars(select(TaskNodeLink)))) == 42
        assert len(list(db.scalars(select(ImportRun)))) == 2


def test_at07_at08_new_revision_only_adds_missing_origins_and_renames_do_not_merge(h):
    apply(h, preview(h, row_keys=['meegle-v137:A:1']))
    original = overview(h)['tasks'][0]
    change(h, original, {'title': 'Keep local'})
    catalog = deepcopy(load_catalog())
    catalog['case_sop_rows'][1]['raw']['title'] = 'New template title'
    with h.sessions.begin() as db:
        v = stage(db, 'w', 'r2', catalog, source_verified=True)
        publish(db, v, 'publisher', 1001)
        h.vid = v.id
    result = apply(h, rid='new-revision')
    assert len(result['created_task_ids']) == 37
    assert result['existing_task_ids'] == [original['id']]
    task = next(t for t in overview(h)['tasks'] if t['id'] == original['id'])
    assert task['title'] == 'Keep local'
    assert task['origin']['imported_version_id'] != h.vid
    assert task['source_snapshot']['row']['raw']['title'] == '業主提出報價需求'


def test_at09_at10_shared_reload_and_link_addition_preserve_state(h):
    first = apply(h, preview(h, node_keys=['control']))
    assert len(first['created_task_ids']) == 3
    shared = next(t for t in overview(h)['tasks'] if t['origin']['source_row_key'] == 'meegle-v137:A:36')
    post(h, URL + f"/sop-tasks/{shared['id']}/transition", {'expected_revision': 1, 'action': 'start'})
    plan = preview(h, node_keys=['mapping'])
    assert sum(o['outcome'] == 'link_addition' for o in plan['outcomes']) == 2
    result = apply(h, plan, 'mapping')
    assert len(result['created_task_ids']) == 1
    assert len(result['existing_task_ids']) == 2
    task = next(t for t in overview(h)['tasks'] if t['id'] == shared['id'])
    assert task['state'] == 'in_progress' and task['revision'] == 2
    assert {n['node_key'] for n in task['nodes']} == {'control', 'mapping'}
    assert len(overview(h)['tasks']) == 4
    assert len(overview(h, query='?node_key=mapping')['tasks']) == 3
    with h.sessions.begin() as db:
        node = db.get(BusinessRow, ('w', 'nodes', 'real-p1-4'))
        node.data = {**node.data, 'title': 'Refreshed', 'tasks': []}
    assert len(overview(h)['tasks']) == 4


def test_at11_at12_applicability_and_exclusions(h):
    plan = preview(h)
    assert len([o for o in plan['outcomes'] if o['disposition'] == 'routing_reference']) == 13
    assert next(o for o in plan['outcomes'] if o['source_row_key'].endswith(':42'))['selected'] is False
    assert len([o for o in plan['outcomes'] if o['selected']]) == 38
    for number in (7, 20, 49, 54, 55, 56, 27, 57, 28, 58, 42):
        assert not next(o for o in plan['outcomes'] if o['source_row_key'].endswith(f':{number}'))['selected']
    for number in (0, 27, 28, 42):
        post(h, URL + '/sop-import/preview', {'template_version_id': h.vid,
                                           'row_keys': [f'meegle-v137:A:{number}']}, 422)
    apply(h, plan)
    task = next(t for t in overview(h)['tasks'] if t['origin']['source_row_key'].endswith(':22'))
    assert task['applicability'] == 'unresolved'
    path = URL + f"/sop-tasks/{task['id']}/transition"
    assert post(h, path, {'expected_revision': 1, 'action': 'complete'}, 422)['code'] == 'applicability_unresolved'
    post(h, path, {'expected_revision': 1, 'action': 'set_applicability', 'applicability': 'not_applicable', 'reason': 'No correction'})
    post(h, path, {'expected_revision': 2, 'action': 'set_applicability', 'applicability': 'applicable', 'reason': 'New scope'})
    assert post(h, path, {'expected_revision': 3, 'action': 'complete'}, 422)['code'] == 'result_note_required'
    assert overview(h)['counts']['done'] == 0
    selected = preview(h, row_keys=['meegle-v137:A:7'], applicability_decisions={
        'meegle-v137:A:7': {'value': 'applicable', 'reason': 'Confirmed subcontract'}})
    assert apply(h, selected, 'subcontract')['created_task_ids']


def test_at13_participants_are_explicit_active_and_authorized(h):
    apply(h, preview(h, node_keys=['confirmation']))
    assert all(t['participants'] == {} for t in overview(h)['tasks'])
    request = {'template_version_id': h.vid, 'row_keys': ['meegle-v137:A:1'],
               'participant_bindings': {'meegle-v137:A:1': {'executor': 'ghost'}}}
    assert post(h, URL + '/sop-import/preview', request, 422)['code'] == 'participant_unresolved'
    request['participant_bindings']['meegle-v137:A:1']['executor'] = 'member'
    plan = post(h, URL + '/sop-import/preview', request)
    apply(h, plan, 'bound')
    assert next(t for t in overview(h)['tasks'] if t['origin']['source_row_key'].endswith(':1'))['participants'] == {'executor': 'member'}
    h.users['member']['active'] = False
    post(h, URL + '/sop-import/preview', request, 422)


def test_at20_permissions_workspace_hidden_revoked_replay_and_publish(h):
    plan = preview(h)
    apply(h, plan)
    h.who[0] = 'manager'
    assert h.client.get(URL + '/sop-tasks').status_code == 200
    h.who[0] = 'other'
    post(h, URL + '/sop-import/preview', {'template_version_id': h.vid}, 403)
    h.who[0] = 'pm'
    h.hidden.add('p1')
    assert h.client.get(URL + '/sop-tasks').status_code == 404
    assert apply(h, plan, status=404)['code'] == 'case_not_found'
    h.hidden.clear()
    h.users['pm']['capabilities'].remove('sop_task_import')
    assert apply(h, plan)['replayed'] is True
    h.users['pm']['active'] = False
    assert apply(h, plan, status=403)['code'] == 'sop_import_forbidden'
    h.users['pm']['active'] = True
    h.wid[0] = 'other-w'
    assert h.client.get(URL + '/sop-tasks').status_code == 404
    h.wid[0] = 'w'
    h.who[0] = 'expired'
    assert h.client.get(URL + '/sop-tasks').json()['code'] == 'session_expired'
    h.who[0] = 'pm'
    h.users['pm']['capabilities'] = ['sop_task_read', 'publish_sop']
    assert h.client.post('/api/sop-templates/' + h.vid + '/publish').status_code == 403


def test_at22_at23_replay_before_expiry_or_live_revision_and_mismatch(h):
    plan = preview(h)
    first = apply(h, plan)
    h.service.clock = lambda: 99999
    replay = apply(h, plan)
    assert replay == {**first, 'replayed': True}
    assert h.client.get(URL + '/sop-import/runs/r1').json() == first
    newer = preview(h)
    assert apply(h, newer, status=409)['code'] == 'idempotency_mismatch'
    h.cfg['SOP_TASK_WRITES_ENABLED'] = 'false'
    assert apply(h, plan)['replayed'] is True
    assert h.client.get(URL + '/sop-import/runs/r1').status_code == 200
    assert h.client.get(URL + '/sop-tasks').status_code == 200
    post(h, URL + '/sop-import/preview', {'template_version_id': h.vid}, 503)


def test_at22_rollback_has_no_tasks_links_events_or_success_receipt(h, monkeypatch):
    plan = preview(h)
    original = h.service.event

    def fail(*args):
        raise RuntimeError('injected failure')
    monkeypatch.setattr(h.service, 'event', fail)
    with pytest.raises(RuntimeError, match='injected failure'):
        apply(h, plan)
    with h.sessions() as db:
        for model in (LocalTask, TaskNodeLink, TaskEvent, ImportRun):
            assert list(db.scalars(select(model))) == []
        assert db.get(CaseState, ('w', 'p1')).checklist_revision == 0
    monkeypatch.setattr(h.service, 'event', original)
    assert len(apply(h, plan)['created_task_ids']) == 38


def test_at24_stale_edit_never_overwrites(h):
    apply(h)
    task = overview(h)['tasks'][0]
    change(h, task, {'title': 'First'})
    assert change(h, task, {'title': 'Stale'}, 409)['code'] == 'task_revision_conflict'
    assert overview(h)['tasks'][0]['title'] == 'First'
    assert change(h, {**task, 'revision': 2}, {'due_date': '2026-10-30', 'reason': 'PM agreed'})['revision'] == 3
    assert overview(h)['tasks'][0]['local']['date_status'] == 'manual'


def test_at28_manual_lifecycle_counts_are_two_of_four(h):
    for i in range(4):
        task = post(h, URL + '/sop-tasks', {'title': f'Manual {i}', 'node_keys': ['sales', 'pm']})
        path = URL + f"/sop-tasks/{task['task_id']}/transition"
        if i < 2:
            post(h, path, {'expected_revision': 1, 'action': 'complete'})
        elif i == 2:
            post(h, path, {'expected_revision': 1, 'action': 'block', 'reason': 'Waiting'})
    body = overview(h)
    assert body['counts'] == {'done': 2, 'total': 4, 'unresolved': 0, 'not_applicable': 0, 'archived': 0}
    assert body['node_counts']['sales'] == body['node_counts']['pm'] == body['counts']
    done = next(t for t in body['tasks'] if t['state'] == 'done')
    path = URL + f"/sop-tasks/{done['id']}/transition"
    post(h, path, {'expected_revision': 2, 'action': 'reopen', 'reason': 'More work'})
    post(h, path, {'expected_revision': 3, 'action': 'archive', 'reason': 'Removed'})
    post(h, path, {'expected_revision': 4, 'action': 'restore', 'reason': 'Restored'})
    assert overview(h)['counts']['done'] == 1


def test_at17_at21_local_only_and_restricted_source(h):
    apply(h)
    h.users['pm']['capabilities'].remove('sop_task_read_source')
    body = overview(h)
    assert all(t['source_snapshot'] is None and t['instructions'] is None for t in body['tasks'])
    assert h.client.get('/api/sop-templates/' + h.vid).status_code == 403
    assert h.writes == []
    with h.sessions() as db:
        assert all(r.data['tasks'] == [] for r in db.scalars(select(BusinessRow).where(BusinessRow.kind == 'nodes')))


def test_case_and_node_previews_converge_after_concurrent_staleness(h):
    whole, node = preview(h), preview(h, node_keys=['mapping'])
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda item: h.client.post(URL + '/sop-import/apply', json={
            'preview_id': item[0]['preview_id'], 'request_id': item[1]}), [(whole, 'whole'), (node, 'node')]))
    assert sorted(r.status_code for r in responses) == [200, 409]
    retry = apply(h, rid='fresh')
    assert len(overview(h)['tasks']) == 38
    assert len({(t['origin']['source_row_key'], t['origin']['instance_scope']) for t in overview(h)['tasks']}) == 38
    assert len(retry['existing_task_ids']) >= 3


def test_expired_actor_bound_preview_and_changed_mapping(h):
    plan = preview(h)
    h.who[0] = 'other'
    h.users['other']['role'] = 'manager'
    assert apply(h, plan, status=404)['code'] == 'preview_not_found'
    h.who[0] = 'pm'
    h.service.clock = lambda: 1900
    assert apply(h, plan, status=409)['code'] == 'preview_stale'
    plan = preview(h)
    with h.sessions.begin() as db:
        n = db.get(BusinessRow, ('w', 'nodes', 'real-p1-4'))
        n.data = {**n.data, 'key': 'mapping'}
    assert apply(h, plan, status=422)['code'] == 'node_mapping_invalid'


def test_capabilities_are_registered_without_automatic_manager_grants():
    from .policy import CAPABILITIES, MANAGER_CAPABILITIES
    assert set(CAPS) <= set(CAPABILITIES)
    assert not set(CAPS) & set(MANAGER_CAPABILITIES)


def test_real_app_registration_restart_and_storage_save_preserve_checklist(tmp_path):
    from .app import create_app
    from . import storage
    config = {'DATABASE_URL': f'sqlite:///{tmp_path}/real.db', 'UPLOAD_DIR': str(tmp_path/'uploads'),
              'SESSION_SECRET': 'test-secret'*5, 'APP_ENV': 'development', 'DEMO_MODE': 'true',
              'SOP_TASK_WRITES_ENABLED': 'true'}
    app = create_app(config)
    with TestClient(app) as client:
        client.get('/api/session')
        assert client.post('/api/demo/session', json={'user_id': 'u-manager'}).status_code == 200
        assert client.get(URL + '/sop-tasks').status_code == 200
        with app.state.sessions.begin() as db:
            workspace = db.scalar(select(WorkspaceRow))
            wid = workspace.id
            user = db.get(BusinessRow, (wid, 'users', 'u-manager'))
            user.data = {**user.data, 'capabilities': user.data.get('capabilities', []) + CAPS}
            version = stage(db, wid, 'r1', load_catalog(), source_verified=True)
            publish(db, version, 'u-manager', 100)
            vid = version.id
        plan = client.post(URL + '/sop-import/preview', json={'template_version_id': vid, 'node_keys': ['confirmation']})
        assert plan.status_code == 200, plan.text
        result = client.post(URL + '/sop-import/apply', json={'preview_id': plan.json()['preview_id'], 'request_id': 'real'})
        assert result.status_code == 200, result.text
        ids = result.json()['created_task_ids']
        assert len(ids) == 5
        with app.state.sessions.begin() as db:
            workspace = db.get(WorkspaceRow, wid)
            state = storage.load(db, BusinessRow, workspace)
            state['projects'][0]['name'] = 'Source renamed'
            workspace.data = storage.save(db, BusinessRow, wid, state)
        assert {t['id'] for t in client.get(URL + '/sop-tasks').json()['tasks']} == set(ids)
    app.state.engine.dispose()
    restarted = create_app(config)
    with TestClient(restarted) as after_restart:
        after_restart.cookies.update(client.cookies)
        response = after_restart.get(URL + '/sop-tasks')
        assert response.status_code == 200, response.text
        assert {t['id'] for t in response.json()['tasks']} == set(ids)
    restarted.state.engine.dispose()


@pytest.mark.parametrize('raw', [b'[]', b'null', b'1', b'"x"', b'true', b'{bad', b'', b'\xff', b'{"x":' * 2000])
def test_invalid_body_never_mutates(h, raw):
    result = h.client.post(URL + '/sop-import/preview', content=raw, headers={'Content-Type': 'application/json'})
    assert result.status_code == 422
    assert overview(h)['tasks'] == []


@pytest.fixture
def intake(h):
    from .seed import seed
    from .v4_sources import import_v4
    from . import storage
    state = seed(True)
    state['projects'] = []
    record = {'kind': 'quote', 'base_token': 'quote-base', 'table_id': 'quote-table', 'record_id': 'quote-row',
              'fields': {'報價編號': '115588', '工程名稱': 'Quote only', '狀態': '', '案件編號': '',
                         '回傳單日期': None, '此案確認單': []}}
    import_v4(state, [record])
    case = state['projects'][0]
    assert case['case_type'] == 'intake'
    assert case['intake_status'] == 'awaiting_confirmation'
    case.update(case_visibility='source_reference', execution_system='pending')
    with h.sessions.begin() as db:
        workspace = db.get(WorkspaceRow, 'w')
        workspace.data = storage.save(db, BusinessRow, 'w', state)
    return h, '/api/projects/' + case['id'], case


def test_intake_defaults_start_at_sales_and_include_all_nine_nodes(intake):
    h, url, case = intake
    plan = preview(h, url=url)
    assert plan['start_node'] == 'sales'
    assert plan['selection']['node_keys'] == list(NODE_MAP.values())
    assert [n['node_key'] for n in plan['nodes']] == list(NODE_MAP.values())
    assert plan['outcomes'][0]['source_row_key'] == 'meegle-v137:A:0'
    assert plan['outcomes'][1]['source_row_key'] == 'meegle-v137:A:1'
    result = apply(h, plan, url=url)
    assert result['start_node'] == 'sales'
    tasks = overview(h, url)
    assert tasks['start_node'] == 'sales'
    assert len(tasks['tasks']) == 38
    assert tasks['tasks'][0]['origin']['source_row_key'] == 'meegle-v137:A:1'
    assert {t['state'] for t in tasks['tasks']} == {'pending'}
    assert {n['node_key'] for t in tasks['tasks'] for n in t['nodes']} == set(NODE_MAP.values())
    assert case['case_type'] == 'intake' and case['execution_system'] == 'pending'
    assert case['pm_id'] == ''


def test_intake_sales_scoped_import_needs_no_case_number_or_confirmation(intake):
    h, url, case = intake
    plan = preview(h, url=url, node_keys=['sales'])
    assert plan['start_node'] == 'sales'
    assert plan['counts']['new_tasks'] == 9
    result = apply(h, plan, url=url)
    assert len(result['created_task_ids']) == 9
    tasks = overview(h, url)['tasks']
    assert [t['origin']['source_row_key'] for t in tasks] == [f'meegle-v137:A:{n}' for n in (1, 2, 3, 4, 8, 9, 10, 12, 15)]
    assert all(t['nodes'][0]['node_key'] == 'sales' and t['state'] == 'pending' for t in tasks)


@pytest.mark.parametrize('quote_fields,start,stage', [
    ({'狀態': '成案'}, 'sales', 'inquiry'),
    ({'狀態': ['成案'], '工程編號': 'A115001'}, 'pm', 'numbered'),
    ({'回傳單日期': '2026-10-20'}, 'pm', 'returned'),
    ({'回傳單日期': 1790208000000, '工程編號': 'C115243'}, 'pm', 'numbered'),
    ({'回傳單日期': '2026-10-20', '工程編號': '報編115588'}, 'pm', 'returned'),
    ({'此案確認單': [{'id': 'recConfirmed'}]}, 'sales', 'inquiry'),
    ({'此案確認單': {'record_ids': ['recConfirmed']}, '回傳單日期': '2026-10-20', '工程編號': 'B115001'},
     'confirmation', 'confirmation'),
    ({'報價日期': '2026-10-01', '報價期限': '2026-10-30'}, 'sales', 'quoted'),
    ({'狀態 (1)': 'B.外業執行中'}, 'field', 'field'),
    ({'狀態 (1)': 'C.內業執行中'}, 'control', 'office'),
    ({'狀態 (1)': 'E.已計價'}, 'pricing', 'pricing'),
    ({'狀態 (1)': 'G.已付款'}, 'settlement', 'paid'),
    ({'狀態 (1)': 'I.案件取消(母案)', '回傳單日期': '2026-10-20'}, 'pm', 'cancelled'),
    ({'案件編號': 'A115001-01'}, 'sales', 'inquiry'),
])
def test_intake_start_node_comes_from_persisted_quote_state(intake, quote_fields, start, stage):
    h, url, case = intake
    with h.sessions.begin() as db:
        row = db.get(BusinessRow, ('w', 'projects', case['id']))
        project = deepcopy(row.data)
        for quote in project['quotes'] + project['source_records']:
            quote['fields'].update(quote_fields)
        row.data = project
    plan = preview(h, url=url, node_keys=['sales'])
    assert (plan['start_node'], plan['stage']) == (start, stage)
    tasks = overview(h, url)
    assert (tasks['start_node'], tasks['stage']) == (start, stage)
    assert apply(h, plan, url=url)['stage'] == stage


def test_start_node_tracks_real_node_progress_and_invalidates_preview(intake):
    h, url, case = intake
    plan = preview(h, url=url)
    with h.sessions.begin() as db:
        row = db.scalar(select(BusinessRow).where(BusinessRow.workspace_id == 'w', BusinessRow.kind == 'nodes',
                                                  BusinessRow.parent_id == case['id']))
        key = row.data['key']
        row.data = {**row.data, 'status': 'in_progress'}
    assert overview(h, url)['start_node'] == key
    with h.sessions.begin() as db:
        row = db.scalar(select(BusinessRow).where(BusinessRow.workspace_id == 'w', BusinessRow.kind == 'nodes',
                                                  BusinessRow.parent_id == case['id'], BusinessRow.entity_id == case['id'] + '-report'))
        row.data = {**row.data, 'status': 'in_progress'}
    assert overview(h, url)['start_node'] == 'report'
    assert apply(h, plan, url=url, status=409)['code'] == 'preview_stale'


def test_display_payloads_contain_codes_not_catalog_helper_prose(h):
    plan = preview(h)
    for outcome in plan['outcomes']:
        assert 'reason' not in outcome
        assert outcome['reason_code'] == outcome['outcome']
        assert outcome['exclusion_reason'] is None
    receipt = apply(h, plan)
    assert all('reason' not in row for row in receipt['exclusions'])
    template = h.client.get('/api/sop-templates/' + h.vid).json()
    assert all('reason' not in row['proposed_import'] for row in template['rows'])
    assert all('interpretation_reason' in row['provenance'] for row in template['rows'])


@pytest.mark.parametrize('canonical,expected', [('執行中', 'field'), ('已完工', 'pricing'), ('已結案', 'settlement')])
def test_start_node_uses_verified_engineering_lifecycle(intake, canonical, expected):
    h, url, case = intake
    with h.sessions.begin() as db:
        row = db.get(BusinessRow, ('w', 'projects', case['id']))
        row.data = {**row.data, 'source_lifecycle': {'state': 'mapped', 'canonical': canonical, 'reasons': []}}
    assert overview(h, url)['start_node'] == expected
    with h.sessions.begin() as db:
        row = db.get(BusinessRow, ('w', 'projects', case['id']))
        row.data = {**row.data, 'source_lifecycle': {'state': 'needs_verification', 'canonical': canonical, 'reasons': ['conflict']}}
    assert overview(h, url)['start_node'] == 'sales'


def test_unassigned_intake_requires_visibility_and_explicit_local_task_grant(intake):
    h, url, case = intake
    assert case['pm_id'] == ''
    h.who[0] = 'member'
    post(h, url + '/sop-import/preview', {'template_version_id': h.vid}, 403)
    h.who[0] = 'other'
    assert preview(h, url=url)['start_node'] == 'sales'
    h.hidden.add(case['id'])
    assert h.client.get(url + '/sop-tasks').status_code == 404


def test_at07_published_revision_adds_one_genuinely_new_origin(h):
    first = apply(h)
    local = overview(h)['tasks'][0]
    change(h, local, {'title': 'Preserved local edit'})
    catalog = deepcopy(load_catalog())
    extra = deepcopy(catalog['case_sop_rows'][1])
    extra.update(source_row_key='meegle-v137:A:62', source_sheet_row=64,
                 source_locator='Reviewed revision / A64:U64')
    extra['raw'].update(meegle_id=62, title='New reviewed task', source_order=17)
    catalog['case_sop_rows'].append(extra)
    catalog['disposition_counts']['task'] += 1
    with h.sessions.begin() as db:
        version = stage(db, 'w', 'r2-with-new-origin', catalog, source_verified=True)
        publish(db, version, 'publisher', 1001)
        h.vid = version.id
    result = apply(h, rid='new-origin')
    assert len(result['created_task_ids']) == 1
    assert set(result['existing_task_ids']) == set(first['created_task_ids'])
    tasks = overview(h)['tasks']
    assert len(tasks) == 39
    assert next(t for t in tasks if t['id'] == local['id'])['title'] == 'Preserved local edit'
    assert next(t for t in tasks if t['id'] == result['created_task_ids'][0])['origin']['source_row_key'] == 'meegle-v137:A:62'


def test_template_list_shows_the_chinese_family_name(h):
    templates = h.client.get('/api/sop-templates').json()['templates']
    assert [(t['template_family_id'], t['name'], t['is_default']) for t in templates] == [('plumb-case-sop', '案件 SOP 預設任務', True)]
