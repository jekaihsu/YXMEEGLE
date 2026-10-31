import asyncio
import json

from .test_backend import app, client, role
from .test_ai_api import live_server
from .ai.tools import execute
from .ai.project_context import build


def cookie(client):
    return '; '.join(f'{k}={v}' for k, v in client.cookies.items())


def test_status_only_real_demo(app, client):
    result, error = asyncio.run(execute(app, cookie(client), 'search_cases',
        dict(query='', status='in_progress', owner='anyone', overdue=False, offset=0)))
    assert not error, result
    data = json.loads(result)
    assert data['matched_total'] == data['total'] == 7
    assert all(p['state'] == '進行中' for p in data['cases'])


def test_completed_work_real_demo(app, client):
    data = json.loads(asyncio.run(build(app, cookie(client), 'p1')).json)
    assert data['nodes']['completed_nodes'] == {'done': 4, 'total': 9}
    assert data['nodes']['completed_tasks']['done'] == 9
    assert next(n for n in data['nodes']['rows'] if n['label'] == '外業')['tasks_done'] == 3
    assert all(t['status'] != 'completed' for t in data['unfinished_tasks']['rows'])


def test_unknown_status_and_foreign_owner_are_rejected(app, client):
    for key, value in [('status', 'invented'), ('owner', 'u-manager')]:
        args = dict(query='', status='all', owner='anyone', overdue=False, offset=0)
        args[key] = value
        result, error = asyncio.run(execute(app, cookie(client), 'search_cases', args))
        assert error and key in json.loads(result)['error']


def test_portfolio_visibility_and_composed_filters(tmp_path):
    from fastapi.testclient import TestClient
    from .app import create_app
    from .ai.tools import today, project_state, CASE_STATUS
    a = create_app(dict(DATABASE_URL=f'sqlite:///{tmp_path}/portfolio.db', UPLOAD_DIR=str(tmp_path),
        SESSION_SECRET='test-secret' * 5, APP_ENV='development', DEMO_MODE='true',
        WORKSPACE_SHELL_ENABLED='true', INDEX_TABLES_ENABLED='true'))
    with TestClient(a) as c:
        c.get('/api/session')
        for user in ('u-control', 'u-manager', 'u-pm'):
            role(c, user)
            page = c.get('/api/projects?view=portfolio&page=1').json()
            ui = page['items']
            assert page['total'] == 7
            for status, query, owner, late in [(None, None, None, None), ('in_progress', None, None, None),
                    (None, '進行中', None, None), ('in_progress', '捷運', None, None),
                    ('in_progress', None, 'me', None), (None, None, None, True)]:
                args = dict(query=query or '', status=status or 'all', owner=owner or 'anyone', overdue=bool(late), offset=0)
                result, error = asyncio.run(execute(a, cookie(c), 'search_cases', args))
                assert not error, result
                data = json.loads(result)
                expected = [p for p in ui if (not status or project_state(p, today())['state'] == CASE_STATUS[status])
                    and (not query or query in ' '.join(p.get(k, '') for k in ('code', 'name', 'client')))
                    and (not owner or p['pm_id'] == user)
                    and (not late or project_state(p, today())['overdue'])]
                expected.sort(key=lambda p: (p.get('due_date') or '9999', p['id']))
                assert data['matched_total'] == len(expected)
                assert [p['id'] for p in data['cases']] == [p['id'] for p in expected[:8]]
                assert sum(data['status_counts'].values()) == data['total']

        from .test_backend import WorkspaceRow, BusinessRow, storage
        wid = a.state.signer.loads(c.cookies.get('meegle_session'))['wid']
        with a.state.sessions.begin() as db:
            root = db.get(WorkspaceRow, wid)
            state = storage.load(db, BusinessRow, root)
            cases = {p['id']: p for p in state['projects']}
            cases['p2']['code'] = cases['p1']['code']
            cases['p4']['case_type'] = 'intake'
            cases['p5'].update(case_type='intake', source_removed_at='2026-10-30T00:00:00Z')
            cases['p7'].update(planning_origin='local', case_visibility='local_planning')
            root.version += 1
            state['version'] = root.version
            root.data = storage.save(db, BusinessRow, wid, state)
        for user in ('u-control', 'u-manager'):
            role(c, user)
            ui = c.get('/api/projects?view=portfolio&page=1').json()
            result, error = asyncio.run(execute(a, cookie(c), 'search_cases',
                dict(query='', status='all', owner='anyone', overdue=False, offset=0)))
            assert not error, result
            data = json.loads(result)
            assert data['total'] == ui['total'] == 4
            assert {p['id'] for p in data['cases']} == {p['id'] for p in ui['items']} == {'p1', 'p3', 'p4', 'p6'}
            legacy = c.get('/api/projects?limit=100').json()
            assert legacy['total'] == 6


def test_zero_completed_real_demo_case(app, client):
    from .test_backend import WorkspaceRow, BusinessRow, storage
    wid = app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
    with app.state.sessions.begin() as db:
        root = db.get(WorkspaceRow, wid)
        state = storage.load(db, BusinessRow, root)
        p = next(p for p in state['projects'] if p['id'] == 'p1')
        for n in p['nodes']:
            n['status'] = 'pending'
            for t in n['tasks']:
                t['status'] = 'pending'
        root.data = storage.save(db, BusinessRow, wid, state)
    data = json.loads(asyncio.run(build(app, cookie(client), 'p1')).json)
    assert data['nodes']['completed_nodes']['done'] == 0
    assert data['nodes']['completed_tasks']['done'] == 0
    assert '均為 0' in data['nodes']['completion_note']


def test_global_progress_includes_completed_nodes_and_display(app, client):
    from .ai.tools import displays
    result, error = asyncio.run(execute(app, cookie(client), 'case_progress', dict(case_id='p1')))
    assert not error, result
    data = json.loads(result)
    assert data['workflow_summary']['completed_nodes'] == dict(done=4, total=9)
    table = displays('case_progress', result)[1]
    field = next(n for n in table['rows'] if n['label'] == '外業')
    assert field['status'] == '已完成' and field['tasks_done'] == 3
    assert len(table['rows']) == 9


def test_status_question_real_socket(app, client, live_server):
    import subprocess
    from .test_ai_api import Fake, BODY
    from .ai.providers import ToolCall
    args = dict(query='', status='in_progress', owner='anyone', overdue=False, offset=0)
    app.state.ai_providers = {'claude': Fake(calls=[ToolCall('status', 'search_cases', args)])}
    response = subprocess.run(['curl', '-sS', '-N', '--max-time', '10', '-b', cookie(client),
        '-H', 'Content-Type: application/json', '--data', json.dumps(dict(BODY, messages=[dict(role='user', content='哪些案件進行中？')])),
        live_server + '/api/ai/chat'], capture_output=True, text=True, check=True)
    events = [json.loads(line[6:]) for line in response.stdout.splitlines() if line.startswith('data: ')]
    assert events[-1]['type'] == 'done', events
    table = next(e['displays'][0] for e in events if e['type'] == 'tool' and e['status'] == 'done')
    assert len(table['rows']) == 7
    assert all(row['status_label'] == '進行中' for row in table['rows'])


def test_completed_sop_work_from_real_demo_routes(app, client):
    app.state.cfg['SOP_TASK_WRITES_ENABLED'] = 'true'
    role(client, 'u-pm')
    response = client.post('/api/projects/p1/sop-tasks', json=dict(title='完成控制成果核對', node_keys=['control']))
    assert response.status_code == 200, response.text
    task = response.json()['task']
    response = client.post('/api/projects/p1/sop-tasks/' + task['id'] + '/transition',
        json=dict(expected_revision=task['revision'], action='complete', result_note='已核對控制成果'))
    assert response.status_code == 200, response.text
    context = json.loads(asyncio.run(build(app, cookie(client), 'p1')).json)
    assert context['nodes']['sop_tasks']['case_counts']['done'] == 1
    control = next(n for n in context['nodes']['rows'] if n['node_key'] == 'control')
    assert control['sop_tasks_done'] == control['sop_tasks_total'] == 1
    result, error = asyncio.run(execute(app, cookie(client), 'case_progress', dict(case_id='p1')))
    assert not error, result
    assert json.loads(result)['workflow_summary']['sop_tasks']['case_counts']['done'] == 1
