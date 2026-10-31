"""Run from the worktree with PYTHONPATH=. /tmp/ai-backend-venv/bin/python docs/ai-bugfix-evidence.py."""
import asyncio
import json
import logging
from pathlib import Path
import tempfile

from fastapi.testclient import TestClient
from backend.app import create_app
from backend.ai.tools import execute
from backend.ai.project_context import build

logging.disable(logging.CRITICAL)
with tempfile.TemporaryDirectory() as directory:
    app = create_app(dict(DATABASE_URL=f'sqlite:///{directory}/evidence.db', UPLOAD_DIR=directory,
        SESSION_SECRET='test-secret' * 5, APP_ENV='development', DEMO_MODE='true',
        WORKSPACE_SHELL_ENABLED='true', INDEX_TABLES_ENABLED='true'))
    with TestClient(app) as client:
        client.get('/api/session')
        cookie = '; '.join(f'{k}={v}' for k, v in client.cookies.items())
        result, error = asyncio.run(execute(app, cookie, 'search_cases',
            dict(query=None, status='in_progress', owner=None, overdue=None)))
        assert not error, result
        context = json.loads(asyncio.run(build(app, cookie, 'p1')).json)
        trimmed = {k: context[k] for k in ('project', 'nodes', 'progress')}
        output = 'AFTER SEARCH ' + result + '\nAFTER CONTEXT ' + json.dumps(trimmed, ensure_ascii=False)[:2500]
        print(output)
        Path(__file__).with_name('ai-bugfix-runtime-after.txt').write_text(output + '\n')
