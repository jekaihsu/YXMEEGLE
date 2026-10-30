"""Issue #39: rejected actions commit safe audits without changing workspace state.

Set ACTION_AUDIT_TEST_POSTGRES_URL to a disposable PostgreSQL database to run
against its real varchar/JSON constraints. Each case uses an isolated schema.
"""
import os
import secrets

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url

from .app import AuditRow, Receipt, WorkspaceRow, create_app
from .test_backend import workspace


@pytest.fixture(params=['sqlite', 'postgresql'])
def audit_database(request, tmp_path):
    if request.param == 'sqlite':
        yield f'sqlite:///{tmp_path}/audit.db'
        return
    configured = os.environ.get('ACTION_AUDIT_TEST_POSTGRES_URL')
    if not configured:
        pytest.skip('ACTION_AUDIT_TEST_POSTGRES_URL is not configured')
    url = make_url(configured).set(drivername='postgresql+psycopg')
    schema = 'audit_test_' + secrets.token_hex(8)
    engine = create_engine(url)
    with engine.begin() as db:
        db.exec_driver_sql(f'CREATE SCHEMA {schema}')
    try:
        yield url.update_query_dict({'options': f'-csearch_path={schema}'}).render_as_string(hide_password=False)
    finally:
        with engine.begin() as db:
            db.exec_driver_sql(f'DROP SCHEMA {schema} CASCADE')
        engine.dispose()


@pytest.mark.parametrize('action,status', [
    ('x'*120, 404), ('x'*121, 422), ('x'*10000, 422),
    ('unknown_action', 404), ('task_add\x00evil', 422), ('', 422),
])
def test_rejected_action_commits_audit_and_preserves_workspace(audit_database, tmp_path, action, status):
    app = create_app({'DATABASE_URL': audit_database, 'UPLOAD_DIR': str(tmp_path/'u'),
                      'SESSION_SECRET': 'test-secret'*5, 'APP_ENV': 'development', 'DEMO_MODE': 'true'})
    try:
        with TestClient(app) as client:
            client.get('/api/session')
            before = workspace(client)
            with app.state.sessions() as db:
                stored_before = [(r.id, r.version, r.data) for r in db.scalars(select(WorkspaceRow))]
            response = client.post('/api/actions', json={
                'action': action, 'version': before['version'],
                'request_id': 'rejected-request', 'payload': {},
            })
            assert response.status_code == status
            assert workspace(client)['version'] == before['version']
            with app.state.sessions() as db:
                assert [(r.id, r.version, r.data) for r in db.scalars(select(WorkspaceRow))] == stored_before
                rows = list(db.scalars(select(AuditRow).where(AuditRow.action != 'login')))
                assert len(rows) == 1
                row = rows[0]
                assert len(row.action) <= AuditRow.action.type.length
                assert row.data['result'] == 'denied' and row.data['status'] == status
                if len(action) > 120 or '\x00' in action or not action:
                    assert row.action.startswith('rejected_action:')
                    assert row.data['action_length'] == len(action)
                else:
                    assert row.action == action
                assert list(db.scalars(select(Receipt))) == []
    finally:
        app.state.engine.dispose()
