"""Whitelist-only real directory read; reconciliation stays entirely in memory."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.lark_adapter import application_adapter
from backend.people_directory import fetch_directory, merge_directory


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--saved-config',required=True)
    parser.add_argument('--output',default='.runtime/people-directory-verification-20260927.json')
    args=parser.parse_args()
    source=Path(args.saved_config).resolve(); target=Path(args.output).resolve()
    if source==target: raise SystemExit('Output must not overwrite configuration')
    raw=json.loads(source.read_text(encoding='utf-8-sig'))
    cfg=raw.get('variables',{}).get('data',raw).copy()
    tenants=[t.strip() for t in cfg.get('LARK_ALLOWED_TENANTS','').split(',') if t.strip()]
    if len(tenants)!=1: raise SystemExit('Expected one configured company')
    cfg.update(LARK_WORKER_IDENTITY='application',LARK_WORKER_ORGANIZATION=tenants[0])
    adapter=application_adapter(cfg)
    try: snapshot=fetch_directory(adapter,cfg['LARK_APP_ID'])
    finally: adapter.client.close()
    users,stats=merge_directory([],snapshot)
    repeated,again=merge_directory(users,snapshot)
    ids_stable={u['id'] for u in users}=={u['id'] for u in repeated} and len(users)==len(repeated)
    disabled_preserved=True
    if users:
        local=deepcopy(users); local[0].update(active=False,role='manager',capabilities=['manage_people'])
        after,_=merge_directory(local,snapshot)
        check=next(u for u in after if u['id']==local[0]['id'])
        disabled_preserved=check['active'] is False and check['role']=='manager' and check['capabilities']==['manage_people']
    report={'at':datetime.now(timezone.utc).isoformat(),'identity':'application',
        'remote_writes':False,'production_database_access':False,'record_fields_requested':snapshot['selected_fields'],
        'source_count':snapshot['source_count'],'valid_people':len(snapshot['people']),
        'issues_by_reason':{r:sum(i['reason']==r for i in snapshot['issues']) for r in sorted({i['reason'] for i in snapshot['issues']})},
        'field_warnings':snapshot['field_warnings'],'employment_status_counts':{status:sum(u['directory_status']==status for u in users) for status in ('employed','left','unknown')},
        'repeated_sync_preserves_ids':ids_stable,'disabled_and_privileges_preserved':disabled_preserved,
        'new_users_have_no_privileges':all(u['role']=='member' and u['capabilities']==[] for u in users),
        'scope':'Real whitelist-only read; local in-memory merge, not deployed DB synchronization'}
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__': main()
