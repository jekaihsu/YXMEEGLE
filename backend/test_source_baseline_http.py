import time
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from .app import create_app, WorkspaceRow, AuthRow, CacheRow, PersonRow, AuditRow
from .seed import seed
from .test_company_admin_admission import fixtures


@pytest.fixture
def baseline_api(tmp_path):
    cfg, person, _ = fixtures()
    cfg.update(DATABASE_URL=f'sqlite:///{tmp_path}/baseline.db', UPLOAD_DIR=str(tmp_path/'uploads'),
               APP_ENV='development', DEMO_MODE='false', SESSION_SECRET='baseline-test'*4,
               LARK_APP_SECRET='test', LARK_REDIRECT_URI='https://example.test/api/auth/lark/callback')
    app=create_app(cfg)
    state=seed(); state.update(environment='production', version=1, users=[person],
                              source_status={'sync_revision':3,'last_sync':'2026-09-30T10:00:00+08:00'})
    snapshot={'status':'ready','last_sync':state['source_status']['last_sync'],
              'tables':[{'base_token':'base','table_id':'table','status':'ready'}],
              'records':[{'base_token':'base','table_id':'table','record_id':'old', 'kind':'confirmation','fields':{}}]}
    with app.state.sessions.begin() as db:
        db.add(WorkspaceRow(id='lark-tenant',version=1,data=state))
        db.add(PersonRow(organization_id='lark-tenant',person_id=person['id'],data=person))
        db.add(AuthRow(id='auth',data={'wid':'lark-tenant','expires':time.time()+3600,'access_token':'unused'}))
        db.add(CacheRow(id='lark-tenant',data=snapshot))
    client=TestClient(app)
    client.cookies.set('meegle_session', app.state.signer.dumps({'mode':'lark','uid':person['id'],'wid':'lark-tenant','sid':'auth'}))
    return app,client


def post(client, **changes):
    return client.post('/api/sources/cutover-baseline',json={'version':1,'sync_revision':3,'reason':'Company cutover approved',**changes})


def unchanged(app):
    with app.state.sessions() as db:
        assert db.get(WorkspaceRow,'lark-tenant').version==1
        assert not list(db.scalars(select(AuditRow).where(AuditRow.action=='source_case_baseline')))


@pytest.mark.parametrize('body',[
    {'version':1,'sync_revision':3,'reason':'obsolete cutover'},
    {'version':2,'sync_revision':4,'reason':'stale'},
    {},None,
])
def test_retired_baseline_returns_gone_without_business_writes(baseline_api,body):
    app,client=baseline_api
    with app.state.sessions() as db:
        before=deepcopy(db.get(WorkspaceRow,'lark-tenant').data)
        cache=deepcopy(db.get(CacheRow,'lark-tenant').data)
    response=client.post('/api/sources/cutover-baseline',json=body)
    assert response.status_code==410,response.text
    unchanged(app)
    with app.state.sessions() as db:
        assert db.get(WorkspaceRow,'lark-tenant').data==before
        assert db.get(CacheRow,'lark-tenant').data==cache


@pytest.mark.parametrize('raw',[b'{',b'\xff',b'null',b'[]'])
def test_retired_baseline_does_not_parse_obsolete_payload(baseline_api,raw):
    app,client=baseline_api
    assert client.post('/api/sources/cutover-baseline',content=raw,
                       headers={'Content-Type':'application/json'}).status_code==410
    unchanged(app)


def test_retired_baseline_requires_login(baseline_api):
    app,client=baseline_api;client.cookies.clear()
    assert post(client).status_code==401
    unchanged(app)


def test_retired_baseline_rejects_nonmanager(baseline_api):
    app,client=baseline_api
    with app.state.sessions.begin() as db:
        row=db.get(PersonRow,('lark-tenant','ou_admin'))
        row.data={**row.data,'role':'member'}
    assert post(client).status_code==403
    unchanged(app)


def test_retired_baseline_rejects_test_workspace(baseline_api):
    app,client=baseline_api
    with app.state.sessions.begin() as db:
        state=deepcopy(db.get(WorkspaceRow,'lark-tenant').data)
        state['environment']='test'
        db.add(WorkspaceRow(id='test-lark-tenant',version=1,data=state))
        auth=db.get(AuthRow,'auth');auth.data={**auth.data,'wid':'test-lark-tenant'}
    client.cookies.set('meegle_session',app.state.signer.dumps(
        {'mode':'lark','uid':'ou_admin','wid':'test-lark-tenant','sid':'auth'}))
    assert post(client).status_code==403
    unchanged(app)


def test_baseline_cross_tenant_session_is_rejected(baseline_api):
    app,client=baseline_api
    client.cookies.set('meegle_session',app.state.signer.dumps({'mode':'lark','uid':'ou_admin','wid':'lark-other','sid':'auth'}))
    assert post(client).status_code==401
    unchanged(app)
