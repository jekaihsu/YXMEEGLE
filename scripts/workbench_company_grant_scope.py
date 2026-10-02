"""Apply only the explicitly approved ordinary-business backup grant scope."""
import json
import os
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from workbench_login_cutover import environment
from workbench_cloud_setup import query,ENV
from workbench_formal_environment_check import SERVICE,APP,ORIGIN
STATE=ROOT/'.runtime/company-grant-scope'
KEY='LARK_COMPANY_ADMIN_GRANTS_JSON'
SCOPE='company:ordinary_business_backup'
OPEN_ID='ou_4ce899b9b868cc34e5ce3d379679f342'

def intended(before):
    if (before.get('LARK_APP_ID')!=APP or before.get('PUBLIC_ORIGIN')!=ORIGIN
        or any(before.get(k)!='false' for k in ('DEMO_MODE','ALLOW_CLOUD_DEMO'))
        or before.get('LARK_NATIVE_APPROVAL_SUBMIT_ENABLED','false').lower()!='false'):
        raise ValueError('Formal environment identity or disabled gates differ')
    tenant=before.get('LARK_WORKER_ORGANIZATION')
    if not tenant or tenant not in before.get('LARK_ALLOWED_TENANTS','').split(','):raise ValueError('Tenant mismatch')
    grants=json.loads(before.get(KEY,'[]'))
    if not isinstance(grants,list):raise ValueError('Grant list required')
    matches=[g for g in grants if isinstance(g,dict) and g.get('app_id')==APP and g.get('tenant')==tenant and g.get('open_id')==OPEN_ID]
    if len(matches)!=1:raise ValueError('Exactly one existing authorized grant required')
    grant=matches[0]
    if grant.get('enabled') is not True or grant.get('role')!='manager' or not all(grant.get(k) for k in ('grant_id','authorized_at','authorized_by','decision_ref','reason')):
        raise ValueError('Existing explicit authorization incomplete')
    scopes=grant.get('scopes',[])
    if not isinstance(scopes,list) or not all(isinstance(x,str) for x in scopes):raise ValueError('Invalid scopes')
    if SCOPE in scopes:return deepcopy(before)
    grant['scopes']=[*scopes,SCOPE]
    return {**before,KEY:json.dumps(grants,ensure_ascii=False,separators=(',',':'))}

def save(name,data,exclusive=False):
    STATE.mkdir(parents=True,exist_ok=True)
    with (STATE/name).open('x' if exclusive else 'w',encoding='utf-8') as out:
        json.dump(data,out,ensure_ascii=False,indent=2);out.flush();os.fsync(out.fileno())

def run():
    fresh=environment(SERVICE)
    if (STATE/'attempt.json').exists():
        expected=json.loads((STATE/'intended-private.json').read_text(encoding='utf-8'))
        if fresh!=expected:raise ValueError('Prior mutation outcome unverified; no retry')
        return {'ok':True,'verified_complete_map':True,'replayed_readback':True,'changed_keys':[KEY]}
    expected=intended(fresh)
    if fresh==expected:return {'ok':True,'already_present':True,'changed_keys':[]}
    save('before-private.json',fresh);save('intended-private.json',expected)
    if environment(SERVICE)!=fresh:raise ValueError('Concurrent environment change; stopped before mutation')
    save('attempt.json',{'service_id':SERVICE,'at':datetime.now(timezone.utc).isoformat(),
        'decision_ref':'docs/EXECUTION_TRACKER_20260930.md#latest-decisions'},True)
    query('mutation($s:ObjectID!,$e:ObjectID!,$data:Map!){updateEnvironmentVariable(serviceID:$s,environmentID:$e,data:$data)}',
          {'s':SERVICE,'e':ENV,'data':expected})
    if environment(SERVICE)!=expected:raise ValueError('Complete map readback differs; do not retry')
    receipt={'ok':True,'verified_complete_map':True,'service_id':SERVICE,'changed_keys':[KEY],
        'native_submit_unchanged':True,'database_and_secrets_unchanged':True,'at':datetime.now(timezone.utc).isoformat()}
    save('verified.json',receipt);return receipt

if __name__=='__main__':
    try:print(json.dumps(run()))
    except Exception as exc:print(json.dumps({'ok':False,'error_type':type(exc).__name__}));sys.exit(1)
