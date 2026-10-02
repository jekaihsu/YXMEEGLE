import json
import pytest
from scripts import deploy_prepare as deploy

@pytest.fixture
def prepared(tmp_path,monkeypatch):
    runtime=tmp_path/'runtime';runtime.mkdir()
    (tmp_path/'deployment').mkdir();(tmp_path/'deployment/source-tables.json').write_text('[]')
    monkeypatch.setattr(deploy,'ROOT',tmp_path);monkeypatch.setattr(deploy,'RUNTIME',runtime)
    def put(name,data):(runtime/name).write_text(json.dumps(data))
    put('zeabur-create-services-response.json',{'data':{'postgres':{'_id':'pg'},'app':{'_id':'app'}}})
    put('zeabur-deploy-secrets.json',{'postgres_password':'test','session_secret':'test'*20})
    put('zeabur-service-details.json',{'data':{'service':{'dnsName':'private'}}})
    return runtime,put

def test_initial_company_settings_never_open_demo_before_lark_config(prepared):
    runtime,_=prepared;deploy.prepare_settings()
    env=json.loads((runtime/'zeabur-settings-request.json').read_text())['variables']['data']
    assert env['APP_ENV']=='production'
    assert env['DEMO_MODE']==env['ALLOW_CLOUD_DEMO']=='false'
    assert not env.get('LARK_APP_SECRET')

def test_lark_step_closes_legacy_preview_flags(prepared):
    runtime,put=prepared;deploy.prepare_settings()
    path=runtime/'zeabur-settings-request.json';original=json.loads(path.read_text())
    original['variables']['data'].update(DEMO_MODE='true',ALLOW_CLOUD_DEMO='true')
    put(path.name,original)
    put('lark-new.json',{'LARK_APP_ID':'cli_aa3cab98b2789e17','LARK_APP_SECRET':'test-only','LARK_ALLOWED_TENANTS':'company'})
    deploy.prepare_lark()
    env=json.loads((runtime/'zeabur-lark-settings-request.json').read_text())['variables']['data']
    assert env['DEMO_MODE']==env['ALLOW_CLOUD_DEMO']=='false'
    assert env['DATABASE_URL']==original['variables']['data']['DATABASE_URL']

def test_missing_credentials_cannot_generate_lark_request(prepared):
    runtime,put=prepared;deploy.prepare_settings();put('lark-new.json',{})
    with pytest.raises(SystemExit):deploy.prepare_lark()
    assert not (runtime/'zeabur-lark-settings-request.json').exists()
