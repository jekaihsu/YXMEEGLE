"""Prepare (never apply) a full Zeabur environment merge from a fresh snapshot."""
import hashlib,json,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.release_env_guard import validate_environment,validate_request

def main():
    source=ROOT/'.runtime/input-release-fresh-env-response.json'
    if datetime.now(timezone.utc).timestamp()-source.stat().st_mtime>900:
        raise SystemExit('Fetch a fresh full environment snapshot before preparing')
    raw=json.loads(source.read_text(encoding='utf-8'))
    if raw.get('errors'):raise SystemExit('Environment query failed')
    entries=raw['data']['service']['variables'];current={}
    for row in entries:
        if row['key'] in current and current[row['key']]!=row['value']:
            raise SystemExit('Conflicting duplicate environment keys')
        current[row['key']]=row['value']
    validate_environment(current)
    if current.get('BACKUP_DIR') or current.get('BACKUP_OFFSITE_ENABLED','false').lower()=='true':
        raise SystemExit('Existing backup activation conflicts with the approved no-enable scope; review without replacing')
    private=ROOT/'.runtime/lark-input-cli'
    formal=json.loads((private/'formal-input-config.json').read_text(encoding='utf-8'))
    test=json.loads((private/'test-input-config.json').read_text(encoding='utf-8'))
    if any(item.get('status')!='schema_readback_verified_no_records' for item in (formal,test)):
        raise SystemExit('Input destinations lack successful schema readback')
    formal_env=formal['environment_variables'];test_env=test['environment_variables']
    if set(formal_env)!={'LARK_INPUT_BASE_TOKEN','LARK_INPUT_TABLE_ID','LARK_INPUT_REGISTRATION_FIELDS_JSON'}:
        raise SystemExit('Unexpected formal environment keys')
    if set(test_env)!={'LARK_TEST_BASE_TOKEN','LARK_TEST_INPUT_TABLE_ID','LARK_TEST_INPUT_REGISTRATION_FIELDS_JSON'}:
        raise SystemExit('Unexpected test environment keys')
    if formal_env['LARK_INPUT_BASE_TOKEN']==test_env['LARK_TEST_BASE_TOKEN'] or formal_env['LARK_INPUT_TABLE_ID']==test_env['LARK_TEST_INPUT_TABLE_ID']:
        raise SystemExit('Formal and isolated destinations overlap')
    if {v['field_id'] for v in formal['mapping'].values()} & {v['field_id'] for v in test['mapping'].values()}:
        raise SystemExit('Formal and test field identities overlap')
    drive=json.loads((private/'test-drive-checkpoint.json').read_text(encoding='utf-8'))
    formal_drive='VfuxfC18olPpE6dSsJkja70npNg'
    if drive.get('status')!='created' or not drive.get('folder_token') or drive['folder_token']==formal_drive:
        raise SystemExit('Isolated Drive root not established or overlaps formal')
    updates={**formal_env,**test_env,'LARK_ATTENDANCE_IDENTITY_RESOLUTION':'contact',
        'LARK_TEST_DRIVE_ROOT':drive['folder_token'],'LARK_DRIVE_ROOT':formal_drive,
        'LARK_NATIVE_APPROVAL_SUBMIT_ENABLED':'false'}
    grants=json.loads((ROOT/'.runtime/company-admin-env-fragment.json').read_text(encoding='utf-8'))
    if set(grants)!={'LARK_COMPANY_ADMIN_GRANTS_JSON'} or not isinstance(grants['LARK_COMPANY_ADMIN_GRANTS_JSON'],str):
        raise SystemExit('Unexpected company administrator environment fragment')
    approved=json.loads(grants['LARK_COMPANY_ADMIN_GRANTS_JSON'])
    if not isinstance(approved,list) or not approved:raise SystemExit('Company administrator grant fragment is empty')
    updates.update(grants)
    merged={**current,**updates};validate_environment(merged)
    request={'query':'mutation($s:ObjectID!,$e:ObjectID!,$data:Map!){updateEnvironmentVariable(serviceID:$s,environmentID:$e,data:$data)}',
        'variables':{'s':'6ab61834a4c05a5bcb57ad69','e':'6ab6168036d2a6cac409f0c6','data':merged}}
    validate_request(request)
    output=ROOT/'.runtime/input-release-full-env-request.json'
    output.write_text(json.dumps(request,ensure_ascii=False,indent=2),encoding='utf-8')
    receipt={'prepared_at':datetime.now(timezone.utc).isoformat(),
        'snapshot_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'request_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
        'original_key_count':len(current),'merged_key_count':len(merged),
        'retained_all_original_keys':set(current)<=set(merged),
        'preserved_unknown_values':all(merged[k]==v for k,v in current.items() if k not in updates),
        'changed_keys':sorted(k for k in updates if current.get(k)!=merged[k]),
        'identical_duplicate_entries':len(entries)-len(current),
        'backup_dir_added':False,'backup_enabled':False,'native_submission_enabled':False,
        'validated':True,'applied':False,'request_file':str(output.relative_to(ROOT))}
    (ROOT/'.runtime/input-release-env-preparation.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps(receipt))

if __name__=='__main__':main()
