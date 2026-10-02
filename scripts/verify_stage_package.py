"""Offline smoke test of a staging directory, with no repository import fallback.

Runs staged code in an isolated interpreter, a temporary working directory and
a credential-free environment. SQLite/uploads exist only in that directory.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import site
import sys
import tempfile


PROBE = r'''
import asyncio, json, os, socket, sys
from pathlib import Path
stage = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(stage))
# Windows developer installations commonly put dependencies in the user site.
# Add that package directory only; do not execute its .pth files or add cwd.
user_site = sys.argv[2]
if user_site not in sys.path:
    sys.path.insert(1, user_site)

# Windows event-loop initialization needs a local socket pair; create it before
# blocking connections. All application imports and requests follow the block.
loop = asyncio.new_event_loop()
def reject_network(*args, **kwargs):
    raise RuntimeError('Outbound network is disabled in the staging smoke test')
socket.socket.connect = reject_network
socket.socket.connect_ex = reject_network
socket.create_connection = reject_network
socket.getaddrinfo = reject_network

from backend.sop_contracts import catalog, VERSION, CATALOG_VERSION
from backend.policy import template
source = catalog()
assert source['version'] == CATALOG_VERSION and source['templates'], 'Missing source catalog'
policy = template()
assert policy['contract_version'] == VERSION and policy['nodes'], 'Missing SOP template'
assert any(n['task_definitions'] for n in policy['nodes']), 'Empty SOP task definitions'

from backend.app import app
import httpx
checks = {'catalog': True, 'policy_template': True}
async def probe():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
        for route in ('health', 'session', 'workspace', 'projects', 'daily-reports', 'sources'):
            response = await client.get('/api/' + route)
            assert response.status_code == 200, route + ' did not return 200'
            data = response.json()
            if route == 'health':
                assert data['status'] == 'ok' and data['database'] == 'sqlite'
            elif route == 'session':
                assert data['mode'] == 'demo' and not data['auth_configured']
            elif route == 'workspace':
                assert data['projects'] and data['sop_templates']
                assert all(p.get('source_kind') == 'demo' for p in data['projects'])
            elif route in ('projects', 'daily-reports'):
                assert isinstance(data['items'], list)
            elif route == 'sources':
                assert data['status'] == 'requires_login' and not data['records']
            checks[route] = True
try:
    loop.run_until_complete(probe())
    for name, module in tuple(sys.modules.items()):
        if name == 'backend' or name.startswith('backend.'):
            filename = getattr(module, '__file__', None)
            if filename:
                assert Path(filename).resolve().is_relative_to(stage), 'Repository import fallback'
            for location in getattr(module, '__path__', []):
                assert Path(location).resolve().is_relative_to(stage), 'Repository namespace fallback'
    checks['staged_imports_only'] = True
finally:
    app.state.engine.dispose()
    loop.close()
print(json.dumps({'ok': True, 'checks': checks, 'catalog_version': VERSION}))
'''


def verify_stage(stage, timeout=120):
    stage = Path(stage).resolve(strict=True)
    if not (stage / 'backend' / 'app.py').is_file():
        raise ValueError('Stage must contain backend/app.py')
    # Allow only interpreter/OS essentials. Never inherit DATABASE_URL, Lark,
    # cloud tokens, PYTHONPATH, or the caller's application's configuration.
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() in {'SYSTEMROOT', 'WINDIR', 'PATH', 'TEMP', 'TMP', 'TMPDIR'}}
    with tempfile.TemporaryDirectory(prefix='yx-stage-smoke-') as temporary:
        root = Path(temporary)
        environment.update(APP_ENV='development', DEMO_MODE='true',
                           DATABASE_URL='sqlite:///' + (root / 'workspace.db').as_posix(),
                           UPLOAD_DIR=str(root / 'uploads'),
                           SESSION_SECRET='isolated-stage-smoke-local-only-secret',
                           FRONTEND_DIST=str(root / 'absent-frontend'))
        process = subprocess.run([sys.executable, '-I', '-B', '-c', PROBE, str(stage), site.getusersitepackages()],
                                 cwd=root, env=environment, capture_output=True,
                                 text=True, encoding='utf-8', timeout=timeout)
    if process.returncode:
        # No application data or arbitrary traceback is included in the receipt.
        missing = not (stage / 'backend' / 'sop_source_contracts.json').is_file()
        return {'ok': False, 'reason': 'missing_sop_source_contracts' if missing else 'isolated_probe_failed',
                'returncode': process.returncode}
    try:
        return json.loads(process.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {'ok': False, 'reason': 'invalid_probe_result'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', type=Path)
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    result = verify_stage(args.stage)
    result['stage'] = str(args.stage.resolve())
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))
    raise SystemExit(0 if result['ok'] else 1)


if __name__ == '__main__':
    main()
