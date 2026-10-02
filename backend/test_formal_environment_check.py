import json
from scripts.workbench_formal_environment_check import assess,APP,ORIGIN

def test_check_never_exposes_secret_values():
    env={'LARK_APP_ID':APP,'PUBLIC_ORIGIN':ORIGIN,'LARK_REDIRECT_URI':ORIGIN+'/api/auth/lark/callback',
         'DEMO_MODE':'false','ALLOW_CLOUD_DEMO':'false','LARK_APP_SECRET':'private-value',
         'LARK_WORKER_ORGANIZATION':'tenant','LARK_COMPANY_ADMIN_GRANTS_JSON':json.dumps([{
             'open_id':'ou_4ce899b9b868cc34e5ce3d379679f342','app_id':APP,'tenant':'tenant',
             'enabled':True,'role':'manager','scopes':['company:ordinary_business_backup']}])}
    result=assess(env,{**env,'LARK_APP_SECRET':'older-value'})
    assert result['changed_keys']==['LARK_APP_SECRET'] and result['all_checks_passed']
    assert 'private-value' not in json.dumps(result) and 'older-value' not in json.dumps(result)
    env['LARK_COMPANY_ADMIN_GRANTS_JSON']='[]'
    assert not assess(env,env)['checks']['exact_ordinary_backup_scope']
