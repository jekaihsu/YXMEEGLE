import asyncio
import copy
import json

import pytest

from .test_ai_database import app, client, ai_database_url
from .test_backend import WorkspaceRow, BusinessRow, storage
from .test_ai_tools import tool
from .test_ai_attendance import attendance_route, call
from .ai.tools import project_state, displays

BASE = dict(query='', status='all', owner='anyone', overdue=False, offset=0)


def seed_cases(app, client, count=19, name=None):
    wid = app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
    with app.state.sessions.begin() as db:
        root = db.get(WorkspaceRow, wid)
        state = storage.load(db, BusinessRow, root)
        template = copy.deepcopy(state['projects'][0])
        for key, value in list(template.items()):
            if isinstance(value, list) and key != 'nodes':
                template[key] = []
        state['projects'] = []
        for i in range(count):
            p = copy.deepcopy(template)
            p.update(id=f'r8-{i:02}', code=f'R8-{i:02}', due_date=None)
            if name:
                p['name'] = name
            for n in p['nodes']:
                n['id'] = p['id'] + '-' + n['key']
                for t in n['tasks']:
                    t['id'] = p['id'] + '-' + t['id']
            state['projects'].append(p)
        root.data = storage.save(db, BusinessRow, wid, state)


def test_last_search_page(app, client):
    seed_cases(app, client)
    result = tool(app, client, 'search_cases', {**BASE, 'offset': 16})
    assert result['next_offset'] is None
    assert not result.get('truncated', False)
    assert result['population_total'] == result['matched_total'] == 19
    assert all('status' not in p for p in result['cases'])
    print('Final 19-case last page ' + json.dumps(result, ensure_ascii=False))


def test_size_trim_contiguous_search(app, client):
    seed_cases(app, client, name='長案名' * 500)
    offset, ids = 0, []
    while offset is not None:
        page = tool(app, client, 'search_cases', {**BASE, 'offset': offset})
        assert len(json.dumps(page, ensure_ascii=False)) <= 6000
        assert page['cases']
        ids += [p['id'] for p in page['cases']]
        following = page['next_offset']
        assert following is None or following == offset + len(page['cases'])
        offset = following
    assert ids == [f'r8-{i:02}' for i in range(19)]


@pytest.mark.parametrize('done,total', [(1, 2), (None, None), (0, 12)])
def test_different_task_populations_not_conflict(app, client, done, total):
    from .ai.work_summary import summarize
    detail = client.get('/api/case-detail/p1').json()
    rows = detail['sections']['workflow_nodes']['rows']
    for n in rows:
        n['status'] = 'pending'
        n['tasks'] = []
    assignments = dict(nodes=[dict(key=n['node_id'].rsplit('-', 1)[-1], label=n['label'],
        derived_status='pending', tasks=dict(done=done, total=total)) for n in rows])
    summary = summarize(detail, assignments)
    assert 'completion_conflict' not in summary
    assert summary['workflow_completed_tasks'] == dict(done=0, total=0)
    assert summary['rows'][0]['tasks_done'] == done


def test_workflow_task_completion_conflicts_with_assignment_zero(app, client):
    from .ai.work_summary import summarize
    detail = client.get('/api/case-detail/p1').json()
    rows = detail['sections']['workflow_nodes']['rows']
    for n in rows:
        n['status'] = 'pending'
    assignments = dict(nodes=[dict(key=n['node_id'].rsplit('-', 1)[-1], label=n['label'],
        derived_status='pending', tasks=dict(done=0, total=20)) for n in rows])
    assert 'completion_conflict' in summarize(detail, assignments)


def test_display_chinese_and_unevaluated_days(attendance_route, app, client):
    week = call(attendance_route, dict(range='week', date='2026-10-12'))
    rendered = displays('attendance_today', json.dumps(week))
    excluded = [d['date'] for d in week['days'] if not d['evaluated']]
    assert excluded
    assert not set(excluded) & {p['label'] for p in rendered[1]['points']}
    assert all(d + ' 不評估' in rendered[1]['note'] for d in excluded)
    for row in rendered[0]['rows']:
        assert all(row[d] == '不評估' for d in excluded)
    progress = tool(app, client, 'case_progress', dict(case_id='p1'))
    rendered += displays('case_progress', json.dumps(progress))
    def texts(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, list):
            for v in value:
                yield from texts(v)
        elif isinstance(value, dict):
            for k, v in value.items():
                if k not in {'key'}:
                    yield from texts(v)
    text = ' '.join(texts(rendered))
    for forbidden in ('as_of', 'unaccounted', 'evaluated', 'derived_status', 'workflow_nodes', 'node_assignments', 'basis'):
        assert forbidden not in text


@pytest.mark.parametrize('project', [dict(nodes=[{}, None, dict(key='field', tasks=[{}, None, dict(due_date=123)])]),
    dict(nodes=None, due_date={}), dict(portfolio_nodes=[{}, dict(key='pm', status=[])], overdue_tasks='bad'),
    dict(nodes=[dict(key='field', tasks=None)], due_date=True)])
def test_malformed_project_state(project):
    assert project_state(project, '2026-10-13') == dict(state='待核對', overdue=False)


def test_completion_prompt_rules():
    from .ai.prompts import system_prompt, project_system_prompt
    from types import SimpleNamespace
    for prompt in (system_prompt(), project_system_prompt(SimpleNamespace(json='{}'))):
        for field in ('completion_conflict', 'workflow_completed_nodes', 'skipped_nodes'):
            assert field in prompt
    assert 'population_total' in system_prompt() and 'matched_total' in system_prompt()


def test_25_node_caps_real_routes(app, client):
    from .ai.project_context import build
    wid = app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
    with app.state.sessions.begin() as db:
        root = db.get(WorkspaceRow, wid)
        state = storage.load(db, BusinessRow, root)
        p = state['projects'][0]
        template = copy.deepcopy(p['nodes'][0])
        for i in range(16):
            n = copy.deepcopy(template)
            n.update(id=f'p1-extra{i}', key=f'extra{i}', name='額外節點' * 60)
            for t in n['tasks']:
                t.update(id=f'extra{i}-' + t['id'], title='詳細任務' * 60)
            p['nodes'].append(n)
        root.data = storage.save(db, BusinessRow, wid, state)
    assert len(client.get('/api/case-detail/p1').json()['sections']['workflow_nodes']['rows']) == 25
    result = tool(app, client, 'case_progress', dict(case_id='p1'))
    assert len(json.dumps(result, ensure_ascii=False)) <= 6000
    assert result['workflow_summary']['truncated']
    cookie = '; '.join(f'{k}={v}' for k, v in client.cookies.items())
    context = asyncio.run(build(app, cookie, 'p1')).json
    assert len(context) <= 12000
    assert json.loads(context)['truncated']


def test_null_attendance_date_rejected(app):
    from .ai.tools import execute
    raw, error = asyncio.run(execute(app, '', 'attendance_today', dict(range='today', date=None)))
    assert error and 'date' in json.loads(raw)['error']
