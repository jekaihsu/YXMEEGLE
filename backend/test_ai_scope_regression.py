import asyncio
import json

from .test_backend import app, client, role
from .ai.tools import execute
from .ai.project_context import build


def cookie(client):
    return '; '.join(f'{k}={v}' for k, v in client.cookies.items())


def test_status_only_real_demo(app, client):
    result, error = asyncio.run(execute(app, cookie(client), 'search_cases',
        dict(query=None, status='in_progress', owner=None, overdue=None)))
    assert not error, result
    data = json.loads(result)
    assert data['total'] == 6
    assert all(p['status'] == 'in_progress' for p in data['cases'])


def test_completed_work_real_demo(app, client):
    data = json.loads(asyncio.run(build(app, cookie(client), 'p1')).json)
    assert data['nodes']['completed_nodes'] == {'done': 4, 'total': 9}
    assert data['nodes']['completed_tasks']['done'] == 9
    assert next(n for n in data['nodes']['rows'] if n['label'] == '外業')['tasks_done'] == 3
    assert all(t['status'] != 'completed' for t in data['unfinished_tasks']['rows'])
