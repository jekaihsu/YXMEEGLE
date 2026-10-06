"""POST /api/sources/sync returns the GET public projection; the internal cache keeps raw fields."""
import json
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from . import source_sync
from .app import create_app, WorkspaceRow, AuthRow, CacheRow, PersonRow
from .seed import seed
from .test_company_admin_admission import fixtures

PRIVATE='SYNTHETIC_PRIVATE_PAYROLL'
ROLES={'pm':('pm',[]),'manager':('manager',[]),'manage_sources':('agent',['manage_sources'])}


def synthetic_snapshot():
    def row(kind,rid,fields): return dict(base_token='v4',table_id=kind,record_id=rid,kind=kind,fields=fields)
    return {'configured':True,'status':'ready','last_sync':datetime.now(timezone.utc).isoformat(),'message':'synthetic',
            'tables':[{'base_token':'v4','table_id':t,'kind':t,'status':'ready','count':1} for t in ('confirmation','daily')],
            'records':[row('confirmation','rec1',{'工程確認單編號':'C115001','狀態':'執行中'}),
                       row('daily','recD',{'工程編號':'C115001','日期':'2026-09-27','組別':'控制','工作日期-薪資':PRIVATE})]}


def person(pid,role,caps):
    stamp=datetime.now(timezone.utc).isoformat()
    return {'id':pid,'name':pid,'active':True,'role':role,'capabilities':caps,'identity_app_id':'app',
            'directory_status':'employed','directory_source':{'app_id':'app','record_id':'dir-'+pid},'directory_last_seen_at':stamp}


@pytest.fixture
def api(tmp_path,monkeypatch):
    cfg,_,_=fixtures()
    cfg.update(DATABASE_URL=f'sqlite:///{tmp_path}/post.db',UPLOAD_DIR=str(tmp_path/'uploads'),APP_ENV='development',DEMO_MODE='false',
               SESSION_SECRET='post-projection'*4,LARK_APP_SECRET='test',LARK_REDIRECT_URI='https://example.test/api/auth/lark/callback',
               LARK_WORKER_IDENTITY='application')
    app=create_app(cfg)
    monkeypatch.setattr(source_sync,'application_adapter',lambda config:SimpleNamespace(token='application-token',client=SimpleNamespace(close=lambda:None)))
    app.state.source_sync.fetcher=lambda token:synthetic_snapshot()
    state=seed(); state.update(environment='production',version=1,users=[person(k,*v) for k,v in ROLES.items()],source_status={'sync_revision':0})
    with app.state.sessions.begin() as db:
        db.add(WorkspaceRow(id='lark-tenant',version=1,data=state))
        for u in state['users']: db.add(PersonRow(organization_id='lark-tenant',person_id=u['id'],data=u))
        db.add(AuthRow(id='auth',data={'wid':'lark-tenant','expires':time.time()+3600,'access_token':'unused'}))
    def client(uid):
        c=TestClient(app); c.cookies.set('meegle_session',app.state.signer.dumps({'mode':'lark','uid':uid,'wid':'lark-tenant','sid':'auth'})); return c
    return app,client


@pytest.mark.parametrize('uid',list(ROLES))
def test_post_matches_get_projection_and_cache_keeps_raw_fields(api,uid):
    app,client=api; c=client(uid)
    posted=c.post('/api/sources/sync'); assert posted.status_code==200,posted.text
    fetched=c.get('/api/sources'); assert fetched.status_code==200
    assert PRIVATE not in posted.text and PRIVATE not in fetched.text
    assert posted.json()==fetched.json()
    assert {r['record_id'] for r in posted.json()['records']}=={'rec1','recD'}
    with app.state.sessions() as db: cache=db.get(CacheRow,'lark-tenant').data
    daily=next(r for r in cache['records'] if r['record_id']=='recD')
    assert daily['fields']['工作日期-薪資']==PRIVATE and daily['fields']['工程編號']=='C115001'
    assert PRIVATE in json.dumps(cache,ensure_ascii=False)


def test_post_applies_same_case_visibility_as_get(api):
    app,client=api; c=client('pm')
    snap=synthetic_snapshot(); snap['records'].append(dict(base_token='v4',table_id='daily',record_id='hidden',kind='daily',fields={'工程編號':'C999999','日期':'2026-09-27','工作日期-薪資':PRIVATE}))
    app.state.source_sync.fetcher=lambda token:snap
    posted=c.post('/api/sources/sync'); assert posted.status_code==200,posted.text
    assert posted.json()==c.get('/api/sources').json()
    with app.state.sessions() as db: cache=db.get(CacheRow,'lark-tenant').data
    assert len(cache['records'])==len(snap['records'])
