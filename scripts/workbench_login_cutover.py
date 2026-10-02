"""Disable public demo entry on exactly the company workbench and staging.

Each update merges a fresh complete environment; never changes Lark credentials,
database settings, roles, approval configuration or business records.
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit,parse_qs
import httpx
from workbench_cloud_setup import query,ENV
from release_env_guard import validate_environment

ROOT=Path(__file__).resolve().parents[1]
DIRECTORY=ROOT/'.runtime/login-cutover'
TARGETS={
 'company':('6ab61834a4c05a5bcb57ad69','https://yongxiang-projects-20260925.zeabur.app'),
 'staging':('6abc0821454b8f31a5ef614a','https://yongxiang-workbench-staging.zeabur.app'),
}

def save(name,data):
    DIRECTORY.mkdir(parents=True,exist_ok=True)
    (DIRECTORY/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')

def environment(service):
    rows=query('query($s:ObjectID!,$e:ObjectID!){service(_id:$s){variables(environmentID:$e){key value}}}',
               {'s':service,'e':ENV})['service']['variables']
    result={}
    for row in rows:
        key,value=row['key'],row['value']
        if not isinstance(value,str) or key in result and result[key]!=value:
            raise RuntimeError('Environment is incomplete or ambiguous')
        # Zeabur can expose the same inherited service variable twice. Only
        # identical values may collapse; conflicting definitions still stop.
        result[key]=value
    return result

def apply(target):
    service,origin=TARGETS[target];before=environment(service)
    if target=='company':validate_environment(before)
    required={'DATABASE_URL','SESSION_SECRET','PUBLIC_ORIGIN','APP_ENV'}
    if not required.issubset(before) or before['PUBLIC_ORIGIN']!=origin:
        raise RuntimeError('Service configuration identity mismatch')
    intended={**before,'DEMO_MODE':'false','ALLOW_CLOUD_DEMO':'false'}
    if target=='company':validate_environment(intended)
    save(target+'-before-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json',before)
    changed=[k for k in intended if intended[k]!=before.get(k)]
    if changed:
        if environment(service)!=before:raise RuntimeError('Environment changed concurrently; inspect before updating')
        save(target+'-intended.json',intended)
        query('mutation($s:ObjectID!,$e:ObjectID!,$data:Map!){updateEnvironmentVariable(serviceID:$s,environmentID:$e,data:$data)}',
              {'s':service,'e':ENV,'data':intended})
    after=environment(service)
    if after!=intended:raise RuntimeError('Complete environment readback differs; private recovery copy retained')
    receipt={'target':target,'changed_keys':changed,'key_count':len(after),'verified_complete_map':True,
             'at':datetime.now(timezone.utc).isoformat()}
    save(target+'-applied.json',receipt);return receipt

def verify(target):
    _,origin=TARGETS[target];checks={}
    with httpx.Client(timeout=30,headers={'Origin':origin}) as client:
        response=client.get(origin+'/api/health');response.raise_for_status()
        assert response.json()['mode']=='lark'
        session=client.get(origin+'/api/session');session.raise_for_status();data=session.json()
        assert data['user'] is None and data['mode']=='lark'
        checks['no_automatic_demo']=True
        assert client.get(origin+'/api/workspace').status_code==401
        assert client.get(origin+'/api/projects').status_code==401
        checks['anonymous_business_denied']=True
        if target=='company':
            assert data['auth_configured'] is True
            response=client.get(origin+'/api/auth/lark/login',follow_redirects=False)
            assert response.status_code in (302,307)
            location=urlsplit(response.headers['location']);args=parse_qs(location.query)
            assert location.hostname=='accounts.larksuite.com' and args['app_id']==['cli_aa3cab98b2789e17']
            assert args['redirect_uri']==[origin+'/api/auth/lark/callback']
            checks['company_lark_login_configured']=True
    receipt={'target':target,'origin':origin,'checks':checks,'at':datetime.now(timezone.utc).isoformat()}
    save(target+'-verified.json',receipt);return receipt

def restart(target):
    service,_=TARGETS[target];current=environment(service)
    if any(current.get(key)!='false' for key in ('DEMO_MODE','ALLOW_CLOUD_DEMO')):
        raise RuntimeError('Login-only environment must be verified before restarting')
    marker=DIRECTORY/(target+'-restart-attempt.json')
    if marker.exists():raise RuntimeError('Restart already requested; verify existing service before another restart')
    save(marker.name,{'at':datetime.now(timezone.utc).isoformat(),'service_id':service})
    result=query('mutation($s:ObjectID!,$e:ObjectID!){restartService(serviceID:$s,environmentID:$e)}',{'s':service,'e':ENV})
    receipt={'target':target,'restart_accepted':result.get('restartService') is True}
    save(target+'-restart.json',receipt);return receipt

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('step',choices=['apply','verify','restart']);parser.add_argument('target',choices=sorted(TARGETS))
    args=parser.parse_args()
    print(json.dumps({'ok':True,**{'apply':apply,'verify':verify,'restart':restart}[args.step](args.target)}))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'ok':False,'error':str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__}))
        sys.exit(1)
