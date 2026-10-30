"""Local assignment and result workflow. All transports are blocked by the local fixture."""
import json

from sqlalchemy import select

from .models import BusinessRow
from .sop_import.models import LocalTask, TaskEvent
from .test_sop_local_case import local, create, call, FORM  # noqa: F401
from .test_sop_quotes import WID


def imported(local):
    app, client, signin, _ = local
    _, receipt = create(client, FORM)
    path = f"/api/projects/{receipt['project_id']}/sop-tasks"
    signin('u-manager')
    tasks = call(client, 'GET', path)['tasks']
    ordinary = next(t for t in tasks if t['origin']['source_row_key'].endswith(':19'))
    other = next(t for t in tasks if t['origin']['source_row_key'].endswith(':59'))
    mine = call(client, 'PATCH', path + '/' + ordinary['id'],
                {'expected_revision': ordinary['revision'], 'participants': {'executor': 'u-map', 'checker': 'u-report'}})['task']
    call(client, 'PATCH', path + '/' + other['id'],
         {'expected_revision': other['revision'], 'participants': {'executor': 'u-control'}})
    return app, client, signin, path, mine, other


def transition(client, path, task, action, status=200, **extra):
    return call(client, 'POST', f"{path}/{task['id']}/transition",
                {'expected_revision': task['revision'], 'action': action, **extra}, status)


def test_assigned_only_local_planning_reads_minimal_header_and_own_tasks(local):
    app, client, signin, path, mine, other = imported(local)
    signin('u-map')
    view = call(client, 'GET', path)
    assert [t['id'] for t in view['tasks']] == [mine['id']]
    assert set(view['case']) == {'id', 'code', 'name'}
    assert view['case']['name'] == FORM['name']
    assert view['node_done'] == {}
    assert view['case_counts']['total'] == 1
    assert view['allowed_actions']['manage'] is False
    assert other['id'] not in json.dumps(view)
    assert FORM['description'] not in json.dumps(view)
    assert client.get(path.replace('/sop-tasks', '')).status_code == 404
    started = transition(client, path, mine, 'start')['task']
    assert started['state'] == 'in_progress'
    signin('u-agent')
    assert client.get(path).status_code == 404
    assert transition(client, path, started, 'complete', 404, result_note='越權')['code'] == 'case_not_found'


def test_completion_note_actor_time_durable_event_stale_empty_and_reopen(local):
    app, client, signin, path, mine, _ = imported(local)
    signin('u-map')
    for note in ('', '   '):
        denied = transition(client, path, mine, 'complete', 422, result_note=note)
        assert denied == {'code': 'result_note_required', 'detail': '請填寫結果說明'}
    started = transition(client, path, mine, 'start')['task']
    assert transition(client, path, mine, 'complete', 409, result_note='已核對')['code'] == 'task_revision_conflict'
    done = transition(client, path, started, 'complete', result_note='  已完成確認並通知相關人員。  ')['task']
    assert done['state'] == 'done'
    result = done['result']
    assert result['note'] == '已完成確認並通知相關人員。'
    assert result['actor_id'] == 'u-map' and result['actor_name']
    assert result['at'] > 0
    with app.state.sessions() as db:
        saved = db.get(LocalTask, (WID, done['id']))
        assert saved.local['result'] == result
        events = list(db.scalars(select(TaskEvent).where(TaskEvent.workspace_id == WID, TaskEvent.task_id == done['id'])))
        assert any(e.actor_id == 'u-map' and e.revision == done['revision'] and e.changes.get('result') == result for e in events)
    for who in ('u-pm', 'u-manager', 'u-map'):
        signin(who)
        assert next(t for t in call(client, 'GET', path)['tasks'] if t['id'] == done['id'])['result'] == result
    reopened = transition(client, path, done, 'reopen', reason='補充核對')['task']
    assert reopened['state'] == 'in_progress' and reopened['result'] is None
    signin('u-manager')
    assigned = call(client, 'PATCH', path + '/' + reopened['id'],
                    {'expected_revision': reopened['revision'], 'participants': {'executor': 'u-control'}})['task']
    assert assigned['local']['attestations'] == {} and assigned['result'] is None
    signin('u-map')
    assert client.get(path).status_code == 404


def test_system_admin_assigns_and_completes_but_proof_obligation_stays_gated(local):
    app, client, signin, path, mine, _ = imported(local)
    done = transition(client, path, mine, 'complete', result_note='管理員已核對。')['task']
    assert done['result']['actor_id'] == 'u-manager'
    task = next(t for t in call(client, 'GET', path)['tasks'] if t['origin']['source_row_key'].endswith(':37'))
    assert task['completion_policy'] == 'proof_required'
    denied = transition(client, path, task, 'complete', 422, result_note='不能略過成果佐證')
    assert denied['code'] == 'completion_evidence_missing'
    assert 'complete' not in task['allowed_actions']
    signin('u-field')
    transition(client, path, task, 'complete', 403, result_note='非執行人')


def test_home_my_work_shape_filter_counts_pagination_and_checker_flags(local):
    app, client, signin, path, mine, other = imported(local)
    signin('u-map')
    for endpoint in ('/api/home-panels', '/api/my-work'):
        body = call(client, 'GET', endpoint + '?panel=assigned&kinds=sop_task&limit=1')
        assert body['counts']['sop_tasks'] == 1
        assert body['complete'] and body['total_count'] == 1
        assert body['next_cursor'] is None and body['has_more'] is False
        item = body['items'][0]
        assert item['kind'] == 'sop_task' and item['id'] == 'sop_task/' + mine['id']
        assert item['assignment_roles'] == ['executor']
        assert item['case']['name'] == FORM['name']
        assert item['node_keys'] == ['confirmation'] and item['status'] == 'todo'
        assert item['deadline'] is None and item['can_execute']
        assert item['target']['task'] == mine['id'] and item['target']['task_source'] == 'sop_local'
        assert item['target']['section'] == 'assigned-sop'
        assert other['id'] not in json.dumps(body)
    legacy = call(client, 'GET', '/api/my-work')
    assert [(r['id'], r['kind']) for r in legacy['rows'] if r.get('kind') == 'sop_task'] == [('sop_task/' + mine['id'], 'sop_task')]
    signin('u-report')
    assert call(client, 'GET', '/api/home-panels?panel=assigned&kinds=sop_task')['items'] == []
    review = call(client, 'GET', '/api/home-panels?panel=confirmation&kinds=sop_task')
    assert review['items'][0]['assignment_roles'] == ['checker']
    assert review['items'][0]['can_execute'] is False
    assert call(client, 'GET', path)['tasks'][0]['allowed_actions'] == []
    transition(client, path, mine, 'complete', 403, result_note='檢核不可執行')


def test_home_item_for_a_case_reader_opens_the_full_case_at_the_task(local):
    app, client, signin, path, mine, other = imported(local)
    signin('u-manager')
    tasks = call(client, 'GET', path)['tasks']
    spare = next(t for t in tasks if t['id'] not in {mine['id'], other['id']})
    call(client, 'PATCH', path + '/' + spare['id'],
         {'expected_revision': spare['revision'], 'participants': {'executor': 'u-manager'}})
    items = call(client, 'GET', '/api/home-panels?panel=assigned&kinds=sop_task')['items']
    target = next(i for i in items if i['id'] == 'sop_task/' + spare['id'])['target']
    assert 'section' not in target
    assert target['task'] == spare['id'] and target['task_source'] == 'sop_local' and target['node']


def test_personal_query_cursor_expires_after_transition_and_writes_flag(local):
    app, client, signin, path, mine, other = imported(local)
    call(client, 'PATCH', path + '/' + other['id'], {'expected_revision': other['revision'] + 1, 'participants': {'executor': 'u-map'}})
    signin('u-map')
    first = call(client, 'GET', '/api/my-work?panel=assigned&kinds=sop_task&limit=1')
    assert first['counts']['sop_tasks'] == 2 and first['has_more']
    second = call(client, 'GET', '/api/my-work?panel=assigned&kinds=sop_task&limit=1&cursor=' + first['next_cursor'])
    assert second['items'][0]['id'] != first['items'][0]['id']
    transition(client, path, mine, 'complete', result_note='完成')
    call(client, 'GET', '/api/my-work?panel=assigned&kinds=sop_task&limit=1&cursor=' + first['next_cursor'], status=409)
    done = call(client, 'GET', '/api/my-work?panel=completed&kinds=sop_task')
    assert done['items'][0]['result']['note'] == '完成'
    app.state.cfg['SOP_TASK_WRITES_ENABLED'] = 'false'
    current = call(client, 'GET', path)['tasks'][0]
    assert current['allowed_actions'] == []
    transition(client, path, current, 'start', 503)


def test_delegated_case_sop_manager_assigns_without_full_local_case_access(local):
    app, client, signin, path, mine, _ = imported(local)
    pid = path.split('/')[3]
    with app.state.sessions.begin() as db:
        row = db.get(BusinessRow, (WID, 'projects', pid))
        row.data = {**row.data, 'sop_task_delegate_ids': ['u-agent']}
    signin('u-agent')
    tasks = call(client, 'GET', path)
    assert tasks['allowed_actions']['manage']
    changed = call(client, 'PATCH', path + '/' + mine['id'],
                   {'expected_revision': mine['revision'], 'participants': {'executor': 'u-report'}})['task']
    assert changed['participants'] == {'executor': 'u-report'}
    assert client.get(path.replace('/sop-tasks', '')).status_code == 404
    app.state.cfg['SOP_TASK_WRITES_ENABLED'] = 'false'
    assert call(client, 'GET', path)['allowed_actions']['manage'] is False


def test_personal_due_date_search_and_inapplicable_tasks(local):
    app, client, signin, path, mine, _ = imported(local)
    updated = call(client, 'PATCH', path + '/' + mine['id'],
                   {'expected_revision': mine['revision'], 'due_date': '2026-12-01', 'reason': '排定期限'})['task']
    signin('u-map')
    query = '/api/my-work?panel=assigned&kinds=sop_task'
    item = call(client, 'GET', query + '&q=' + FORM['name'])['items'][0]
    assert item['deadline'] == '2026-12-01'
    assert call(client, 'GET', query + '&deadline=unscheduled')['counts']['sop_tasks'] == 0
    assert call(client, 'GET', query + '&q=不存在')['items'] == []
    signin('u-manager')
    transition(client, path, updated, 'set_applicability', applicability='not_applicable', reason='不需執行')
    signin('u-map')
    assert call(client, 'GET', query)['items'] == []
    assert not any(r.get('kind') == 'sop_task' for r in call(client, 'GET', '/api/my-work')['rows'])
