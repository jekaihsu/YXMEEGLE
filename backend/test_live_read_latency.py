"""VCC-93: user pages never wait on a slow or failing Lark refresh (live read ON)."""
from threading import Event
from time import monotonic, time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from .app import create_app
from .models import AuthRow, WorkspaceRow
from .seed import seed


@pytest.mark.parametrize('failing', [False, True])
def test_pages_return_immediately_while_refresh_is_slow_or_failing(tmp_path, failing):
    app = create_app({'DATABASE_URL': f'sqlite:///{tmp_path}/lat.db', 'UPLOAD_DIR': str(tmp_path / 'u'),
                      'SESSION_SECRET': 'latency-secret' * 4, 'APP_ENV': 'development', 'DEMO_MODE': 'false',
                      'LARK_WORKER_ORGANIZATION': 'test', 'LARK_ALLOWED_TENANTS': 'test',
                      'LARK_LIVE_READ_ENABLED': 'true', 'LARK_WORKER_IDENTITY': 'application',
                      'LARK_APP_ID': 'a', 'LARK_APP_SECRET': 's'})
    live = seed()
    live['environment'] = 'production'
    with app.state.sessions.begin() as db:
        db.add(WorkspaceRow(id='lark-test', version=1, data=live))
        db.add(AuthRow(id='s1', data={'wid': 'lark-test', 'expires': time() + 3600, 'access_token': 'x'}))
    release, started = Event(), []

    def slow(wid, **_):
        started.append(wid)
        release.wait(10)
        if failing:
            raise HTTPException(502, 'Lark 讀取失敗')
        return {'fingerprint': 'late'}

    app.state.live_read.refreshers = {'sources': slow, 'roster': slow, 'attendance': slow}
    client = TestClient(app)
    client.cookies.set('meegle_session', app.state.signer.dumps(
        {'mode': 'lark', 'uid': 'u-pm', 'wid': 'lark-test', 'sid': 's1'}))
    try:
        for path in ('/api/session', '/api/workspace', '/api/workspace', '/api/session'):
            begun = monotonic()
            response = client.get(path)
            assert monotonic() - begun < 3, path
            assert response.status_code == 200, path
        assert started  # the refresh really is in flight while pages were served
        assert response.json()  # last-good data is served, freshness attached below
        assert 'freshness' in client.get('/api/workspace').json()
    finally:
        release.set()
        app.state.live_read.close()
