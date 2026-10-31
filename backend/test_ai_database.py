"""Real database fixtures shared by AI regression suites."""
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from .app import create_app
from .test_backend import client


@pytest.fixture(params=['sqlite', 'postgresql'])
def ai_database_url(request, tmp_path):
    if request.param == 'sqlite':
        yield f'sqlite:///{tmp_path}/ai.db'
        return
    url = os.environ.get('AI_TEST_POSTGRES_URL')
    if not url:
        pytest.skip('PostgreSQL requires AI_TEST_POSTGRES_URL; run scripts/test_action_audit_postgres.py --ai')
    schema = 'ai_' + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as db:
        db.exec_driver_sql(f'CREATE SCHEMA {schema}')
    try:
        yield make_url(url).update_query_dict({'options': f'-csearch_path={schema} -ctimezone=Asia/Taipei'}).render_as_string(hide_password=False)
    finally:
        with admin.begin() as db:
            db.exec_driver_sql(f'DROP SCHEMA {schema} CASCADE')
        admin.dispose()


def app_config(url, tmp_path):
    return dict(FEATURE_CHANGE_EXTENSION='true', FEATURE_ROUTINES='true', DATABASE_URL=url,
                UPLOAD_DIR=str(tmp_path / 'uploads'), SESSION_SECRET='test-secret' * 5,
                APP_ENV='development', DEMO_MODE='true')


@pytest.fixture
def app(ai_database_url, tmp_path):
    application = create_app(app_config(ai_database_url, tmp_path))
    try:
        yield application
    finally:
        application.state.sessions.kw['bind'].dispose()
