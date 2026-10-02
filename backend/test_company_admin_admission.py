import json
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from urllib.parse import parse_qs,urlparse
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from .production_access import company_admin_grant,access_mode,set_company_admin_authority,business_admitted,test_profile as overlay_profile
from .test_source_sync import harness


def fixtures():
    stamp=(datetime.now(timezone.utc)-timedelta(seconds=10)).isoformat()
    grant={'grant_id':'owner-approved','open_id':'ou_admin','app_id':'app','tenant':'tenant','role':'manager',
        'enabled':True,'authorized_at':stamp,'authorized_by':'owner','reason':'Explicit independent company administrator',
        'decision_ref':'owner-decision'}
    cfg={'LARK_APP_ID':'app','LARK_WORKER_ORGANIZATION':'tenant','LARK_ALLOWED_TENANTS':'tenant',
         'LARK_COMPANY_ADMIN_GRANTS_JSON':json.dumps([grant])}
    person={'id':'ou_admin','active':True,'role':'manager','bootstrap_admin':True,'identity_app_id':'app',
        'oauth_identity':{'source':'oauth_user_info','app_id':'app','tenant':'tenant','open_id':'ou_admin','verified_at':stamp}}
    return cfg,person,grant


def test_exact_owner_grant_and_business_role_revoke_on_config_removal():
    cfg,p,g=fixtures()
    assert access_mode(p,'app',cfg=cfg)=='normal'
    state={'users':[p],'native_approval_authority':{'app_id':'app','tenant':'tenant'}}
    set_company_admin_authority(state,cfg)
    assert business_admitted(p,'app',state['native_approval_authority'])
    cfg['LARK_COMPANY_ADMIN_GRANTS_JSON']='[]';set_company_admin_authority(state,cfg)
    assert access_mode(p,'app',cfg=cfg)=='recovery'
    assert not business_admitted(p,'app',state['native_approval_authority'])


@pytest.mark.parametrize('change',['person_id','app','tenant','oauth_missing','oauth_wrong_id','inactive','revoked','role','disabled_grant','duplicate','expired','future','missing_reason'])
def test_no_role_name_or_bootstrap_bypass(change):
    cfg,p,g=fixtures()
    if change=='person_id':p['id']='ou_other'
    elif change=='app':cfg['LARK_APP_ID']='other'
    elif change=='tenant':cfg['LARK_WORKER_ORGANIZATION']='other'
    elif change=='oauth_missing':p.pop('oauth_identity')
    elif change=='oauth_wrong_id':p['oauth_identity']['open_id']='ou_other'
    elif change=='inactive':p['active']=False
    elif change=='revoked':p['manager_revoked']=True
    elif change=='role':p['role']='member'
    elif change=='disabled_grant':g['enabled']=False
    elif change=='expired':g['expires_at']=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
    elif change=='future':g['authorized_at']=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
    elif change=='missing_reason':g.pop('reason')
    cfg['LARK_COMPANY_ADMIN_GRANTS_JSON']=json.dumps([g,g] if change=='duplicate' else [g])
    assert company_admin_grant(p,cfg) is None
    assert access_mode(p,cfg['LARK_APP_ID'],cfg=cfg)!='normal'


def test_formal_revocation_cannot_be_overridden_by_test_profile():
    _,person,_=fixtures();person['manager_revoked']=True
    assert overlay_profile(person,{'manager_revoked':False})['manager_revoked'] is True


def test_independent_admin_setting_does_not_relax_other_staff_freshness_or_left_status():
    cfg,_,_=fixtures();clock=datetime.now(timezone.utc)
    member={'id':'ou_other','active':True,'role':'member','identity_app_id':'app',
        'directory_source':{'app_id':'app','record_id':'roster'},'directory_status':'employed',
        'directory_last_seen_at':(clock-timedelta(seconds=900)).isoformat()}
    assert access_mode(member,'app',cfg=cfg,now=clock)=='normal'
    member['directory_last_seen_at']=(clock-timedelta(seconds=901)).isoformat()
    assert access_mode(member,'app',cfg=cfg,now=clock)=='denied'
    member['directory_last_seen_at']=clock.isoformat();member['directory_status']='left'
    assert access_mode(member,'app',cfg=cfg,now=clock)=='denied'


def test_forged_profile_authorization_alone_never_replaces_private_server_grant():
    cfg,p,g=fixtures();cfg['LARK_COMPANY_ADMIN_GRANTS_JSON']='[]'
    p['company_admin_authorization']=g
    assert access_mode(p,'app',cfg=cfg)=='recovery'
    # Simulated-person overlays may not write either piece of server evidence.
    clean=deepcopy(p);clean.pop('oauth_identity')
    patched=overlay_profile(clean,{'oauth_identity':p['oauth_identity'],'company_admin_authorization':g})
    assert 'oauth_identity' not in patched


def test_normal_oauth_applies_audited_grant_without_salary_roster_and_revokes_live(tmp_path,monkeypatch):
    from .app import create_app,PersonRow,AuditRow
    cfg,_,_=fixtures()
    cfg.update(DATABASE_URL=f'sqlite:///{tmp_path}/app.db',UPLOAD_DIR=str(tmp_path/'uploads'),APP_ENV='development',
        DEMO_MODE='false',SESSION_SECRET='company-admin-test'*4,LARK_APP_SECRET='test',
        LARK_REDIRECT_URI='https://example.test/api/auth/lark/callback',LARK_ROLE_MAP_JSON=json.dumps({'ou_admin':'manager'}))
    class OAuth:
        oid='ou_admin'
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,**kwargs):return httpx.Response(200,json={'access_token':'test','expires_in':3600},request=httpx.Request('POST',url))
        def get(self,url,**kwargs):return httpx.Response(200,json={'data':{'open_id':self.oid,'name':'Company account','tenant_key':'tenant'}},request=httpx.Request('GET',url))
    monkeypatch.setattr('backend.app.httpx.Client',OAuth)
    app=create_app(cfg);client=TestClient(app)
    response=client.get('/api/auth/lark/login',follow_redirects=False)
    nonce=parse_qs(urlparse(response.headers['location']).query)['state'][0]
    assert client.get('/api/auth/lark/callback',params={'state':nonce,'code':'verified'},follow_redirects=False).status_code==307
    assert client.get('/api/session').json()['access_mode']=='normal'
    assert client.get('/api/workspace').status_code==200
    ws=client.get('/api/workspace').json()
    attempted={'action':'admin_person','version':ws['version'],'request_id':'reject-client-proof',
        'payload':{'id':'ou_admin','oauth_identity':{'tenant':'forged'},'company_admin_authorization':{'grant_id':'forged'}}}
    assert client.post('/api/actions',json=attempted).status_code==422
    with app.state.sessions() as db:
        person=db.get(PersonRow,('lark-tenant','ou_admin')).data
        assert person['oauth_identity']['tenant']=='tenant'
        assert not person.get('directory_source') and person['company_admin_authorization']['grant_id']=='owner-approved'
        assert any(row.action=='company_admin_authorization' for row in db.scalars(select(AuditRow)))
    assert 'oauth_identity' not in client.get('/api/session').text
    # A normal staff account does not receive another person's private grant audit.
    with app.state.sessions.begin() as db:
        db.add(PersonRow(organization_id='lark-tenant',person_id='ou_staff',data={
            'id':'ou_staff','name':'Staff','active':True,'role':'member','identity_app_id':'app',
            'directory_status':'employed','directory_last_seen_at':datetime.now(timezone.utc).isoformat(),
            'directory_source':{'app_id':'app','record_id':'staff-record'},'default_workspace':'production'}))
    OAuth.oid='ou_staff';staff=TestClient(app)
    login=staff.get('/api/auth/lark/login',follow_redirects=False)
    nonce=parse_qs(urlparse(login.headers['location']).query)['state'][0]
    assert staff.get('/api/auth/lark/callback',params={'state':nonce,'code':'verified'},follow_redirects=False).status_code==307
    staff_audit=staff.get('/api/audit')
    assert staff_audit.status_code==200
    assert all(not row['action'].startswith('company_admin_') for row in staff_audit.json()['items'])
    app.state.cfg['LARK_COMPANY_ADMIN_GRANTS_JSON']='[]'
    assert client.get('/api/workspace').status_code==403
    assert client.get('/api/session').json()['access_mode']=='recovery'
    with app.state.sessions() as db:
        assert any(row.action=='company_admin_authorization_revoked' for row in db.scalars(select(AuditRow)))


@pytest.mark.parametrize('environment',['development','production'])
@pytest.mark.parametrize('revoked',[False,True])
def test_worker_rechecks_independent_grant_before_remote_delivery(harness,tmp_path,revoked,environment):
    from .test_mention_notifications import arrange,save,worker
    state=arrange(harness);_,_,grant=fixtures()
    grant.update(open_id='u-manager',app_id='app1')
    person=next(p for p in state['users'] if p['id']=='u-manager')
    person.pop('directory_source');person.pop('directory_status');person['bootstrap_admin']=True
    person['oauth_identity']={'source':'oauth_user_info','open_id':'u-manager','app_id':'app1','tenant':'tenant','verified_at':grant['authorized_at']}
    save(harness,state)
    harness.cfg['LARK_COMPANY_ADMIN_GRANTS_JSON']=json.dumps([] if revoked else [grant]);harness.cfg['APP_ENV']=environment;calls=[]
    def sent(*args):calls.append(True);return {'message_id':'message','recipient':'u-pm'}
    worker(harness,tmp_path,sent).run_one(harness.wid)
    job=harness.read()[0]['jobs'][0]
    assert job['status']==('blocked' if revoked else 'succeeded')
    assert len(calls)==(0 if revoked else 1)
