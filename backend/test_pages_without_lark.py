"""Project pages read the database only: Lark refreshes run beside the request, never inside it."""
import re
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from .live_read.client import LiveLarkClient
from .live_read.token_cache import TenantTokenCache
from . import storage
from .models import AuthRow, BusinessRow, PersonRow, ProjectIndex, TaskIndex, WorkspaceCounter, WorkspaceRow
from .perf_fixture import build_scaled_workspace
from .policy import upgrade
from .test_production_access import company
from .test_roster_grace import LIVE

LARK_SECONDS = 1.5


class Bucket:
    def acquire(self, deadline): pass


@pytest.fixture
def slow_lark(tmp_path):
    app, client = company(tmp_path, dict(
        LIVE, LARK_APP_ID='app1', LARK_WORKER_ORGANIZATION='company', LARK_ALLOWED_TENANTS='company',
        WORKSPACE_SHELL_ENABLED='true', INDEX_TABLES_ENABLED='true'))
    seen = []

    def transport(request):
        seen.append(threading.current_thread().name)
        time.sleep(LARK_SECONDS)
        return httpx.Response(403, json={'code': 1254302})

    cache = TenantTokenCache()
    for refresher in app.state.live_read.refreshers.values():
        refresher.client_factory = lambda cfg, **kw: LiveLarkClient(
            cfg, transport=httpx.MockTransport(transport), token_cache=cache, bucket=Bucket(), **kw)
    with app.state.sessions.begin() as db:
        db.add(AuthRow(id='live', data={'wid': 'lark-company', 'expires': time.time() + 3600, 'access_token': 'x'}))
        workspace = db.get(WorkspaceRow, 'lark-company')
        state = upgrade(build_scaled_workspace(5))
        state.update(environment='production', people_directory_connection={'enabled': True}, version=workspace.version)
        for table in (BusinessRow, ProjectIndex, TaskIndex, WorkspaceCounter):
            db.query(table).filter(table.workspace_id == 'lark-company').delete()
        workspace.data = storage.save(db, BusinessRow, 'lark-company', state)
        for person in db.query(PersonRow).filter(PersonRow.organization_id == 'lark-company'):
            person.data = {**person.data, 'directory_last_seen_at':
                           (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()}
    client.cookies.set('meegle_session', app.state.signer.dumps(
        {'mode': 'lark', 'sid': 'live', 'wid': 'lark-company', 'organization': 'lark-company', 'uid': 'u-manager'}))
    yield app, client, seen
    app.state.live_read.close()


def test_project_pages_return_at_database_speed_while_a_stale_roster_refreshes(slow_lark):
    app, client, seen = slow_lark
    listing = client.get('/api/projects?view=overview&limit=5')
    assert listing.status_code == 200, listing.text
    project_id = listing.json()['items'][0]['id']
    for path in ('/api/projects?view=overview&limit=5', f'/api/projects/{project_id}'):
        started = time.monotonic()
        response = client.get(path)
        assert response.status_code == 200, (path, response.text)
        assert time.monotonic() - started < LARK_SECONDS, path
    app.state.live_read.close()
    assert seen, 'the stale roster really was refreshed beside the requests'
    assert all(name.startswith('ThreadPoolExecutor') for name in seen), seen


def test_project_pages_expose_their_server_phases(slow_lark):
    _, client, _ = slow_lark
    project_id = client.get('/api/projects?view=overview&limit=5').json()['items'][0]['id']
    for path in ('/api/projects?view=overview&limit=5', f'/api/projects/{project_id}'):
        header = client.get(path).headers['server-timing']
        names = [entry.split(';')[0].strip() for entry in header.split(',')]
        assert {'identity', 'load', 'serialize', 'total'} <= set(names), (path, header)
        assert all(re.fullmatch(r'[a-z]+;dur=\d+(\.\d+)?', entry.strip()) for entry in header.split(','))
