"""Fixed private PostgreSQL restore-drill provisioning; no restore or public exposure.

Only inspect / prepare. Credentials remain in ignored .runtime/cloud-restore.
A private service is NOT proof of an empty database or successful restoration.
No application or worker is installed. Public access remains blocked until a
TLS/tunnel mechanism is independently verified against actual provider schema.
"""
import argparse
import json
from pathlib import Path
import secrets
import sys
import httpx
import yaml

ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'.runtime/cloud-restore'
PROJECT='6ab61680a4c05a5bcb57ace9'
ENV='6ab6168036d2a6cac409f0c6'
NAME='yongxiang-workbench-restore-drill'
DENIED={'6ab61834a4c05a5bcb57ad69','6ab6182fa4c05a5bcb57ad63',
        '6abc081caa61051740e67fbd','6abc0821454b8f31a5ef614a'}
DATABASE='workbench_restore_drill'
BLOCKER='Public TLS or authenticated tunnel not verified; private-only service cannot yet be used from this computer.'


def save(name,value,exclusive=False):
    STATE.mkdir(parents=True,exist_ok=True)
    with (STATE/name).open('x' if exclusive else 'w',encoding='utf-8') as out:
        json.dump(value,out,ensure_ascii=False,indent=2)


def query(document,variables=None):
    settings=yaml.safe_load((Path.home()/'.config/zeabur/cli.yaml').read_text(encoding='utf-8'))
    token=settings.get('token')
    if not token:raise RuntimeError('Zeabur authentication required')
    with httpx.Client(timeout=60) as client:
        response=client.post('https://api.zeabur.com/graphql',headers={'Authorization':'Bearer '+token},
                             json={'query':document,'variables':variables or {}})
    result=response.json();save('last-response.json',result)
    if response.status_code!=200 or result.get('errors'):raise RuntimeError('Cloud request failed; private receipt retained')
    return result['data']


def inventory():
    schema=query('query{__type(name:"ServiceConnection"){fields{name}}}')
    fields={item['name'] for item in schema['__type']['fields']}
    if 'edges' in fields:shape='edges{node{_id name dnsName}}'
    elif 'nodes' in fields:shape='nodes{_id name dnsName}'
    else:raise RuntimeError('Unsupported service inventory schema')
    result=query('query($p:ObjectID!){services(projectID:$p,limit:100){'+shape+'}}',{'p':PROJECT})['services']
    rows=[item['node'] for item in result['edges']] if 'edges' in result else result['nodes']
    if len(rows)>=100:raise RuntimeError('Inventory may be truncated; reconcile before provisioning')
    return rows


def exact(rows):
    matches=[item for item in rows if item['name']==NAME]
    if len(matches)>1:raise RuntimeError('Duplicate restore service names; manual reconciliation required')
    service=matches[0] if matches else None
    if service and service['_id'] in DENIED:raise RuntimeError('Formal or staging service cannot be a restore target')
    return service


def manifest(password):
    return {'name':NAME,'source':{'image':'postgres:17-alpine'},
        'ports':[{'id':'postgres','port':5432,'type':'TCP'}],
        'volumes':[{'id':'data','dir':'/var/lib/postgresql/data'}],
        'portForwarding':{'enabled':False},
        'env':[{'key':key,'default':value} for key,value in {
            'POSTGRES_USER':'restore_drill','POSTGRES_PASSWORD':password,
            'POSTGRES_DB':DATABASE,'POSTGRES_INITDB_ARGS':'--auth-host=scram-sha-256'}.items()]}


def inspect():
    service=exact(inventory())
    # Only schema metadata; no speculative endpoint or mutation invocation.
    evidence=query('query{forwarding:__type(name:"ServiceSpecPortForwardingInput"){name inputFields{name type{kind name ofType{kind name}}}} service:__type(name:"Service"){name fields{name args{name type{kind name ofType{kind name}}} type{kind name ofType{kind name}}}}}')
    save('connection-schema-evidence.json',evidence)
    return receipt(service)


def receipt(service):
    return {'project_id':PROJECT,'environment_id':ENV,'service_id':service['_id'] if service else None,
        'service_name':NAME,'private_only':True,'restore_ready':False,'connection_blocker':BLOCKER,
        'formal_modified':False,'staging_modified':False,'database_empty_verified':False}


def prepare():
    service=exact(inventory())
    created=STATE/'created.json'
    if service:
        if not created.exists() or json.loads(created.read_text(encoding='utf-8')).get('service_id')!=service['_id']:
            raise RuntimeError('Existing service ownership or prior outcome unresolved; inspect and reconcile, never adopt blindly')
        return receipt(service)
    if created.exists() or (STATE/'create-attempt.json').exists():
        raise RuntimeError('Previous creation unresolved or target disappeared; never recreate automatically')
    # Exclusive claim prevents parallel commands from issuing duplicate creates.
    save('create-attempt.json',{'project_id':PROJECT,'environment_id':ENV,'name':NAME,'attempted':True},exclusive=True)
    password=secrets.token_urlsafe(40)
    save('secrets.json',{'database_user':'restore_drill','database_name':DATABASE,'database_password':password},exclusive=True)
    result=query('mutation($p:ObjectID!,$s:ServiceSpecSchemaInput!){service:createPrebuiltService(projectID:$p,schema:$s){_id name}}',
                 {'p':PROJECT,'s':manifest(password)})['service']
    if result.get('name')!=NAME or not result.get('_id') or result['_id'] in DENIED:
        raise RuntimeError('Unexpected creation identity; stop and reconcile')
    save('created.json',{'service_id':result['_id'],'project_id':PROJECT,'environment_id':ENV},exclusive=True)
    status=query('query($s:ObjectID!,$e:ObjectID!){service(_id:$s){_id name status(environmentID:$e)}}',{'s':result['_id'],'e':ENV})
    save('status.json',status)
    return receipt(result)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('step',choices=['inspect','prepare'])
    args=parser.parse_args();result=inspect() if args.step=='inspect' else prepare()
    save('receipt.json',result)
    print(json.dumps({'ok':True,'step':args.step,**result}))


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'ok':False,'error':str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__,
                          'formal_modified':False,'staging_modified':False,'restore_ready':False}))
        sys.exit(1)
