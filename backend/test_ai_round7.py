import asyncio
import copy
import json
import subprocess
from pathlib import Path

import pytest
from .test_backend import app, client
from .test_ai_attendance import attendance_route, call
from .test_ai_tools import tool
from .ai.tools import ATTENDANCE_LABELS


@pytest.mark.parametrize('attendance_route', ['mixed'], indirect=True)
def test_explained_independent_punches(attendance_route):
    a, c = attendance_route
    a.state.attendance_fixture_punches.append(dict(user_id='employee-0', day=20261012,
        records=[dict(check_in_result='Late', check_out_result='Normal', check_out_result_supplement='Leave')]))
    source = c.get('/api/people/attendance?week=2026-10-12').json()
    assert set(source['people'][0]['attendance'][0].split('、')) == {'遲到', '請假'}
    data = call(attendance_route, dict(range='today', date='2026-10-12'))
    assert data['counts']['late'] == 2
    assert data['counts']['on_leave'] == 2
    for key in ATTENDANCE_LABELS:
        assert data['counts'][key] == len(data[key])
        if key != 'unaccounted':
            assert not {p['id'] for p in data[key]} & {p['id'] for p in data['unaccounted']}
    week = call(attendance_route, dict(range='week', date='2026-10-12'))
    assert week['summary']['late'] == dict(people=2, person_days=6)
    assert next(p for p in week['people'] if p['id'] == 'ou_0')['days']['late'] == ['2026-10-12']
    from .ai.tools import display_attendance
    assert next(r for r in display_attendance(data)[1]['rows'] if r['name'] == '同事0')['state'] == '遲到、請假'


def test_completion_conflict_real_workflow(app, client):
    from .ai.work_summary import summarize
    detail = client.get('/api/case-detail/p1').json()
    assignments = dict(nodes=[dict(key=n['node_id'].rsplit('-', 1)[-1], label=n['label'],
        derived_status='未開始', tasks=dict(done=0, total=0)) for n in detail['sections']['workflow_nodes']['rows']])
    result = summarize(detail, assignments)
    assert result['workflow_completed_tasks']['done'] == 9
    assert sum(n['workflow_evidence']['completed'] for n in result['rows']) == 4
    assert 'completion_conflict' in result
    assert '工作流程' in result['completion_conflict'] and '9' in result['completion_conflict']
    assert '均為 0' not in result.get('completion_note', '')


@pytest.mark.parametrize('status', ['略過', 'skipped', 'not_applicable'])
def test_skipped_denominator_real_workflow(app, client, status):
    from .ai.work_summary import summarize
    detail = client.get('/api/case-detail/p1').json()
    for n in detail['sections']['workflow_nodes']['rows']:
        n['status'] = 'completed'
    detail['sections']['workflow_nodes']['rows'][-1]['status'] = status
    result = summarize(detail)
    assert result['completed_nodes'] == dict(done=8, total=8)
    assert result['skipped_nodes'] == 1


def test_schema_field_errors(app):
    from .ai.tools import execute
    base = dict(query='', status='all', owner='anyone', overdue=False, offset=0)
    for key, value in [('query', None), ('status', None), ('offset', True), ('offset', '0'), ('query', 'x'*241), ('offset', -1), ('overdue', None), ('owner', 'stranger')]:
        raw, error = asyncio.run(execute(app, '', 'search_cases', {**base, key: value}))
        assert error and key in json.loads(raw)['error']
        assert key == 'status' or 'status' not in json.loads(raw)['error']


def test_prompt_question_specific_headline():
    from .ai.prompts import system_prompt
    text = system_prompt()
    for rule in ['僅限詢問沒打卡／沒到', '遲到、請假或其他問題', 'evaluated=false', '不評估', '不可說「0 人」', '不得向使用者重複內部欄位名稱', 'as_of 只提一次', '不要描述操作過程', '不得使用「缺席」']:
        assert rule in text


def test_paging_and_counts_real_workspace(app, client):
    from .test_backend import WorkspaceRow, BusinessRow, storage
    wid = app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
    with app.state.sessions.begin() as db:
        root = db.get(WorkspaceRow, wid)
        state = storage.load(db, BusinessRow, root)
        template = copy.deepcopy(state['projects'][0])
        for key, value in list(template.items()):
            if isinstance(value, list) and key != 'nodes':
                template[key] = []
        state['projects'] = [{**copy.deepcopy(template), 'id': f'page{i}', 'code': f'PAGE{i}', 'due_date': None} for i in range(19)]
        for project in state['projects']:
            for node in project['nodes']:
                node['id'] = project['id'] + '-' + node['key']
                for task in node['tasks']:
                    task['id'] = project['id'] + '-' + task['id']
        root.data = storage.save(db, BusinessRow, wid, state)
    base = dict(query='PAGE', status='all', owner='anyone', overdue=False, offset=0)
    first = tool(app, client, 'search_cases', base)
    second = tool(app, client, 'search_cases', {**base, 'offset': 8})
    third = tool(app, client, 'search_cases', {**base, 'offset': 16})
    assert [len(p['cases']) for p in [first, second, third]] == [8, 8, 3]
    assert len({p['id'] for page in [first, second, third] for p in page['cases']}) == 19
    assert first['population_total'] == sum(first['status_counts'].values()) == 19
    filtered = tool(app, client, 'search_cases', {**base, 'status': 'completed'})
    assert filtered['matched_total'] == 0 and sum(filtered['status_counts'].values()) == 19


def test_portfolio_frontend_parity(app, client, tmp_path):
    root = Path(__file__).resolve().parents[1]
    if not (root / 'frontend/node_modules/esbuild/lib/main.js').is_file():
        pytest.skip('Frontend parity requires esbuild. Run npm ci in frontend/')
    from .ai.tools import project_state
    from fastapi.testclient import TestClient
    from .app import create_app
    shell = create_app(dict(DATABASE_URL=f'sqlite:///{tmp_path}/parity.db', UPLOAD_DIR=str(tmp_path),
        SESSION_SECRET='parity-secret' * 5, APP_ENV='development', DEMO_MODE='true',
        WORKSPACE_SHELL_ENABLED='true', INDEX_TABLES_ENABLED='true'))
    with TestClient(shell) as c:
        c.get('/api/session')
        projects = c.get('/api/projects?view=portfolio').json()['items']
    projects += client.get('/api/workspace').json()['projects']
    keys = ['sales', 'pm', 'confirmation', 'field', 'control', 'mapping', 'report', 'pricing', 'settlement']
    for status in ['pending', 'in_progress', 'pending_review', 'awaiting_review', 'paused', 'completed', 'approved_skipped', 'skipped', 'not_applicable', 'mystery']:
        p = copy.deepcopy(projects[0])
        p['id'] = status
        p['portfolio_nodes'] = [dict(key=key, status=status, owner_id=None, collaborator_ids=[]) for key in keys]
        p.update(overdue_tasks=1, execution_status='engineering_complete')
        projects.append(p)
    for changes in [dict(field='mystery'), dict(sales='completed', pm='paused', field='pending_review'),
                    dict(sales='completed', pm='completed', control='mystery')]:
        overlay = [dict(key=k, status=changes.get(k, 'pending')) for k in keys]
        projects.append({**copy.deepcopy(projects[0]), 'portfolio_nodes': list(reversed(overlay))})
    projects.append({**copy.deepcopy(projects[0]), 'portfolio_nodes': [dict(status='completed'),
        dict(key='pm', status='paused'), dict(key='pm', status='completed')]})
    task_due = copy.deepcopy(next(p for p in projects if p.get('nodes')))
    task_due.pop('overdue_tasks', None)
    task_due.update(due_date=None, execution_status='in_progress')
    task_due['nodes'][0]['tasks'] = [dict(id='due', status='pending', due_date='2026-10-01')]
    projects.append(task_due)
    projects += [{**copy.deepcopy(projects[0]), 'portfolio_nodes': []},
                 {**copy.deepcopy(projects[0]), 'due_date': '2026-10-12T23:00:00Z', 'overdue_tasks': 0}]
    root = Path(__file__).resolve().parents[1]
    script = '''
import fs from 'node:fs';
const {build}=await import('./frontend/node_modules/esbuild/lib/main.js');
const bundle=await build({entryPoints:['frontend/src/projectsListModel.ts'],bundle:true,write:false,platform:'node',format:'esm',packages:'external',loader:{'.css':'empty'}});
const m=await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`);
const {projects,today}=JSON.parse(fs.readFileSync(0,'utf8'));
console.log(JSON.stringify(projects.map(p=>({state:m.caseRow(p,[],'',today).state,overdue:m.caseAttention(p,today).late}))));
'''
    result = subprocess.run(['node', '--input-type=module', '-e', script], cwd=root,
        input=json.dumps(dict(projects=projects, today='2026-10-13')), capture_output=True, text=True, check=True)
    expected = json.loads(result.stdout)
    assert [project_state(p, '2026-10-13') for p in projects] == expected


@pytest.mark.parametrize('result,supplement,group', [('Late', None, 'late'), ('Early', None, 'early_leave'),
    ('Lack', None, 'missing_punch'), ('Normal', 'CardReplacement', 'supplemented')])
def test_explanation_preserves_each_independent_evidence(attendance_route, result, supplement, group):
    a, _ = attendance_route
    a.state.attendance_fixture_punches.append(dict(user_id='employee-0', day=20261012,
        records=[dict(check_in_result=result, check_in_result_supplement=supplement,
                      check_out_result='Normal', check_out_result_supplement='Leave')]))
    data = call(attendance_route, dict(range='today', date='2026-10-12'))
    assert data[group] == [dict(id='ou_0', name='同事0')]
    assert dict(id='ou_0', name='同事0') in data['on_leave']
    assert dict(id='ou_0', name='同事0') not in data['unaccounted']


def test_sop_completion_prevents_zero_statement(app, client):
    from .test_backend import role, WorkspaceRow, BusinessRow, storage
    from .ai.project_context import build
    wid = app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
    with app.state.sessions.begin() as db:
        root = db.get(WorkspaceRow, wid)
        state = storage.load(db, BusinessRow, root)
        for n in state['projects'][0]['nodes']:
            n['status'] = 'pending'
            for t in n['tasks']:
                t['status'] = 'pending'
        root.data = storage.save(db, BusinessRow, wid, state)
    app.state.cfg['SOP_TASK_WRITES_ENABLED'] = 'true'
    role(client, 'u-pm')
    response = client.post('/api/projects/p1/sop-tasks', json=dict(title='核對成果', node_keys=['control']))
    assert response.status_code == 200, response.text
    task = response.json()['task']
    response = client.post('/api/projects/p1/sop-tasks/' + task['id'] + '/transition',
        json=dict(expected_revision=task['revision'], action='complete', result_note='完成'))
    assert response.status_code == 200, response.text
    cookie = '; '.join(f'{k}={v}' for k, v in client.cookies.items())
    nodes = json.loads(asyncio.run(build(app, cookie, 'p1')).json)['nodes']
    assert nodes['workflow_completed_tasks']['done'] == 0
    assert nodes['sop_tasks']['case_counts']['done'] == 1
    assert '均為 0' not in nodes.get('completion_note', '')
