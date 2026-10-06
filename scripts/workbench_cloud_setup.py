"""Scoped operator for the workbench's independent Zeabur staging services.

No arbitrary query/command/file arguments. Never modifies an existing formal
service. Credentials and cloud receipts stay in ignored .runtime/cloud-staging.
"""
import argparse
import hashlib
import json
import re
from datetime import datetime,timezone
from pathlib import Path
import secrets
import subprocess
import sys
import httpx
try:
    from .stage_inventory import verify_stage_inventory
except ImportError:
    from stage_inventory import verify_stage_inventory
import yaml

ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'.runtime/cloud-staging'
PROJECT='6ab61680a4c05a5bcb57ace9'
ENV='6ab6168036d2a6cac409f0c6'
FORMAL={'6ab61834a4c05a5bcb57ad69','6ab6182fa4c05a5bcb57ad63'}
APP='yx-workbench-staging'
PG='yx-workbench-staging-db'


def save(name,value):
    STATE.mkdir(parents=True,exist_ok=True)
    (STATE/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def query(document,variables=None):
    settings=yaml.safe_load((Path.home()/'.config/zeabur/cli.yaml').read_text(encoding='utf-8'))
    token=settings.get('token')
    if not token:raise RuntimeError('Zeabur authentication required')
    with httpx.Client(timeout=60) as client:
        response=client.post('https://api.zeabur.com/graphql',headers={'Authorization':'Bearer '+token},
                             json={'query':document,'variables':variables or {}})
    result=response.json();save('last-response.json',result)
    if response.status_code!=200 or result.get('errors'):raise RuntimeError('Cloud request failed; private receipt saved')
    return result['data']


def inventory():
    schema=query('query{__type(name:"ServiceConnection"){fields{name type{kind name ofType{kind name}}}}}')
    names={f['name'] for f in schema['__type']['fields']}
    shape='edges{node{_id name dnsName}}' if 'edges' in names else 'nodes{_id name dnsName}'
    data=query('query($p:ObjectID!){services(projectID:$p,limit:100){'+shape+'}}',{'p':PROJECT})['services']
    rows=[e['node'] for e in data['edges']] if 'edges' in data else data['nodes']
    save('inventory.json',[r for r in rows if r['name'] in (APP,PG)])
    return rows


def exact(rows,name):
    matches=[r for r in rows if r['name']==name]
    if len(matches)>1:raise RuntimeError('Duplicate staging service names; stop for reconciliation')
    if matches and matches[0]['_id'] in FORMAL:raise RuntimeError('Formal service cannot be used for staging')
    return matches[0] if matches else None


def create():
    rows=inventory();credentials=STATE/'secrets.json'
    if credentials.exists():values=json.loads(credentials.read_text(encoding='utf-8'))
    else:
        values={'database_password':secrets.token_urlsafe(36),'session_secret':secrets.token_urlsafe(48)}
        save('secrets.json',values)
    for name in (PG,APP):
        if exact(rows,name):continue
        marker=STATE/(name+'-attempt.json')
        if marker.exists():raise RuntimeError('Prior creation outcome unresolved; inspect only, do not recreate')
        save(marker.name,{'attempted':True,'name':name})
        if name==PG:
            schema={'name':PG,'source':{'image':'postgres:17-alpine'},
                    'ports':[{'id':'postgres','port':5432,'type':'TCP'}],
                    'volumes':[{'id':'data','dir':'/var/lib/postgresql/data'}],
                    'portForwarding':{'enabled':False},'env':[{'key':k,'default':v} for k,v in
                    {'POSTGRES_USER':'workspace','POSTGRES_PASSWORD':values['database_password'],'POSTGRES_DB':'workspace'}.items()]}
            result=query('mutation($p:ObjectID!,$s:ServiceSpecSchemaInput!){service:createPrebuiltService(projectID:$p,schema:$s){_id name}}',{'p':PROJECT,'s':schema})
        else:
            result=query('mutation($p:ObjectID!){service:createService(projectID:$p,name:"yx-workbench-staging",template:GIT){_id name}}',{'p':PROJECT})
        save(name+'-created.json',result)
    return inventory()


def configure(rows):
    app,pg=exact(rows,APP),exact(rows,PG)
    if not app or not pg:raise RuntimeError('Staging services missing')
    values=json.loads((STATE/'secrets.json').read_text(encoding='utf-8'))
    config={'APP_ENV':'production','DEMO_MODE':'false','ALLOW_CLOUD_DEMO':'false',
            'DATABASE_URL':'postgresql://workspace:'+values['database_password']+'@'+pg['dnsName']+'.zeabur.internal:5432/workspace',
            'SESSION_SECRET':values['session_secret'],'UPLOAD_DIR':'/data/uploads','PORT':'8080',
            'PUBLIC_ORIGIN':'https://yongxiang-workbench-staging.zeabur.app',
            'LARK_NATIVE_APPROVAL_SUBMIT_ENABLED':'false','FEATURE_LEARNING':'false',
            'BACKUP_OFFSITE_ENABLED':'false','LARK_SOURCE_TABLES_JSON':'[]'}
    # Fresh complete staging config; deliberately contains no company credentials.
    result=query('mutation($s:ObjectID!,$e:ObjectID!,$d:Map!){updateEnvironmentVariable(serviceID:$s,environmentID:$e,data:$d)}',{'s':app['_id'],'e':ENV,'d':config})
    save('configured.json',{'service_id':app['_id'],'keys':sorted(config),'result':result})
    if not (STATE/'domain.json').exists():
        result=query('mutation($s:ObjectID!,$e:ObjectID!){addDomain(serviceID:$s,environmentID:$e,domain:"yongxiang-workbench-staging",isGenerated:true){__typename}}',{'s':app['_id'],'e':ENV})
        save('domain.json',result)


def deploy(rows):
    app=exact(rows,APP)
    if not app:raise RuntimeError('Staging application missing')
    manifest=json.loads((ROOT/'.runtime/zeabur-stage-manifest.json').read_text(encoding='utf-8'))
    stage=Path(manifest['directory']).resolve()
    if not stage.is_relative_to((ROOT/'.runtime').resolve()) or not stage.name.startswith('zeabur-stage-'):
        raise RuntimeError('Unapproved deployment directory')
    inventory_hash=verify_stage_inventory(stage,manifest['files'])
    receipt=json.loads((ROOT/'.runtime'/(stage.name+'-smoke.json')).read_text(encoding='utf-8'))
    if not receipt.get('ok') or receipt.get('inventory_sha256')!=inventory_hash:
        raise RuntimeError('Package smoke missing, stale, or bound to a different inventory')
    command=['zeabur.cmd','deploy','--project-id',PROJECT,'--environment-id',ENV,'--service-id',app['_id'],'--interactive=false']
    result=subprocess.run(command,cwd=stage,capture_output=True,text=True,encoding='utf-8',errors='replace')
    save('deployment.json',{'stage':stage.name,'service_id':app['_id'],'exit_code':result.returncode})
    if result.returncode:raise RuntimeError('Staging deployment failed')


def status(rows):
    result=[]
    for name in (APP,PG):
        service=exact(rows,name)
        if not service:continue
        current=query('query($id:ObjectID!,$env:ObjectID!){service(_id:$id){_id name status(environmentID:$env)}}',
                      {'id':service['_id'],'env':ENV})['service']
        result.append(current)
    save('status.json',result)
    return result


def verify():
    origin='https://yongxiang-workbench-staging.zeabur.app'
    checks={};details={}
    with httpx.Client(timeout=30,headers={'Origin':origin}) as client:
        for route in ('health','session','workspace','projects','daily-reports','sources','company-dashboard'):
            response=client.get(origin+'/api/'+route)
            if route not in ('health','session'):
                assert response.status_code==401
                checks[route+'_anonymous_denied']=True
                continue
            response.raise_for_status();value=response.json()
            if route=='health':assert value['status']=='ok' and value['database']=='postgresql' and value['mode']=='lark'
            elif route=='session':assert value['mode']=='lark' and value['user'] is None and value['auth_configured'] is False
            checks[route]=True
        page=client.get(origin+'/');page.raise_for_status()
        pattern=r'(?:src|href)="(/assets/[^\"]+)"'
        expected=sorted(re.findall(pattern,(ROOT/'frontend/dist/index.html').read_text(encoding='utf-8')))
        assets=sorted(re.findall(pattern,page.text))
        if assets!=expected or not assets:
            raise RuntimeError('Staging frontend asset names differ from local build: '+json.dumps({'expected':expected,'actual':assets}))
        for asset in assets:
            response=client.get(origin+asset);response.raise_for_status()
            local=ROOT/'frontend/dist'/asset.lstrip('/')
            assert hashlib.sha256(response.content).hexdigest()==hashlib.sha256(local.read_bytes()).hexdigest()
        checks['frontend_asset_bytes']=True;details['assets']=assets
        assert client.post(origin+'/api/sources/sync').status_code==401
        checks['formal_source_sync_denied']=True
    receipt={'at':datetime.now(timezone.utc).isoformat(),'origin':origin,'checks':checks,**details,
             'real_lark_verified':False,'formal_modified':False}
    save('verification.json',receipt)
    return receipt


def main():
    parser=argparse.ArgumentParser();parser.add_argument('step',choices=['inspect','prepare','deploy','status','verify'])
    args=parser.parse_args()
    rows=create() if args.step=='prepare' else inventory()
    if args.step=='prepare':configure(rows)
    if args.step=='deploy':deploy(rows)
    states=status(rows) if args.step=='status' else None
    verification=verify() if args.step=='verify' else None
    print(json.dumps({'ok':True,'step':args.step,'services':[{'id':r['_id'],'name':r['name']} for r in rows if r['name'] in (APP,PG)],'states':states,'verification':verification,'formal_modified':False}))


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'ok':False,'error':str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__,'formal_modified':False}))
        sys.exit(1)
