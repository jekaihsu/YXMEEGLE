"""Read-only fixed formal environment check; report keys/booleans, never values."""
import json
from datetime import datetime,timezone
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
SERVICE='6ab61834a4c05a5bcb57ad69'
APP='cli_aa3cab98b2789e17'
ORIGIN='https://yongxiang-projects-20260925.zeabur.app'

def assess(current,intended):
    changed=sorted(k for k in current.keys()|intended.keys() if current.get(k)!=intended.get(k))
    try:
        grants=json.loads(current.get('LARK_COMPANY_ADMIN_GRANTS_JSON','[]'))
        matches=[g for g in grants if isinstance(g,dict) and g.get('open_id')=='ou_4ce899b9b868cc34e5ce3d379679f342'
            and g.get('app_id')==APP and g.get('tenant')==current.get('LARK_WORKER_ORGANIZATION')]
        backup=(len(matches)==1 and matches[0].get('enabled') is True and matches[0].get('role')=='manager'
            and matches[0].get('scopes')==['company:ordinary_business_backup'])
        grant_diagnostics={'exact_identity_match_count':len(matches),'scope_field_present':len(matches)==1 and 'scopes' in matches[0],
            'ordinary_backup_scope_present':len(matches)==1 and isinstance(matches[0].get('scopes'),list) and 'company:ordinary_business_backup' in matches[0]['scopes']}
    except (ValueError,TypeError):backup=False;grant_diagnostics={'invalid_grant_configuration':True}
    checks={'demo_disabled':current.get('DEMO_MODE')=='false','cloud_demo_disabled':current.get('ALLOW_CLOUD_DEMO')=='false',
        'learning_disabled':current.get('FEATURE_LEARNING','false').lower()=='false',
        'native_submit_disabled':current.get('LARK_NATIVE_APPROVAL_SUBMIT_ENABLED','false').lower()=='false',
        'company_app_matches':current.get('LARK_APP_ID')==APP,'origin_matches':current.get('PUBLIC_ORIGIN')==ORIGIN,
        'callback_matches':current.get('LARK_REDIRECT_URI')==ORIGIN+'/api/auth/lark/callback',
        'exact_ordinary_backup_scope':backup}
    return {'service_id':SERVICE,'observed_at':datetime.now(timezone.utc).isoformat(),'read_only':True,
        'key_count':len(current),'unchanged_key_count':len(current.keys()&intended.keys())-len([k for k in changed if k in current and k in intended]),
        'changed_keys':changed,'checks':checks,'grant_diagnostics':grant_diagnostics,'all_checks_passed':all(checks.values())}

def main():
    from workbench_login_cutover import environment
    current=environment(SERVICE)
    intended=json.loads((ROOT/'.runtime/login-cutover/company-intended.json').read_text(encoding='utf-8-sig'))
    receipt=assess(current,intended)
    target=ROOT/'.runtime/formal-environment-check.json'
    target.write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps(receipt))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'ok':False,'error_type':type(exc).__name__}));sys.exit(1)
