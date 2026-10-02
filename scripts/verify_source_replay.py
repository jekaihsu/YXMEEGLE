"""Read real configured sources, replay locally, and save aggregate evidence only."""
import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.lark_adapter import application_adapter
from backend.sources import fetch_sources,import_sources,configuration
from backend.seed import seed
from backend.policy import upgrade


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--saved-config',required=True); parser.add_argument('--output',default='.runtime/source-replay-20260927.json'); parser.add_argument('--snapshot-cache',help='Private local snapshot cache; contains source records and must not be published'); args=parser.parse_args()
    config_path=Path(args.saved_config).resolve(); output_path=Path(args.output).resolve()
    if output_path in (config_path,Path(__file__).resolve(),ROOT/'deployment/source-tables.json'): raise SystemExit('Output must not overwrite configuration or source files')
    raw=json.loads(config_path.read_text(encoding='utf-8-sig'))
    if not isinstance(raw,dict): raise SystemExit('Saved configuration must be an object')
    variables=raw.get('variables',{})
    candidate=variables.get('data',raw) if isinstance(variables,dict) else raw
    if not isinstance(candidate,dict): raise SystemExit('Saved configuration data must be an object')
    cfg=candidate.copy()
    cfg['LARK_SOURCE_TABLES_JSON']=(ROOT/'deployment/source-tables.json').read_text(encoding='utf-8-sig')
    cfg['LARK_WORKER_IDENTITY']='application'
    tenants=[v.strip() for v in cfg.get('LARK_ALLOWED_TENANTS','').split(',') if v.strip()]
    if len(tenants)!=1: raise SystemExit('Expected one explicitly configured company')
    cfg['LARK_WORKER_ORGANIZATION']=tenants[0]
    cache_path=Path(args.snapshot_cache).resolve() if args.snapshot_cache else None
    if cache_path in (config_path,output_path,Path(__file__).resolve(),ROOT/'deployment/source-tables.json'): raise SystemExit('Snapshot cache must use a separate private path')
    cached=bool(cache_path and cache_path.exists())
    if cached:
        snapshot=json.loads(cache_path.read_text(encoding='utf-8-sig'))
    else:
        adapter=application_adapter(cfg)
        try: snapshot=fetch_sources(adapter.token,cfg=cfg)
        finally: adapter.client.close()
        if cache_path:
            cache_path.parent.mkdir(parents=True,exist_ok=True)
            cache_path.write_text(json.dumps(snapshot,ensure_ascii=False),encoding='utf-8')
    def write_report(result):
        output_path.parent.mkdir(parents=True,exist_ok=True)
        output_path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False))
    expected={(t['base_token'],t['table_id'],t['kind']) for t in configuration(cfg)}
    complete=snapshot.get('status')=='ready' and len(snapshot.get('tables',[]))==len(expected) and all(t.get('status')=='ready' for t in snapshot.get('tables',[])) and all((r['base_token'],r['table_id'],r['kind']) in expected for r in snapshot.get('records',[]))
    if not complete:
        write_report({'identity':'application','remote_writes':False,'source_status':snapshot.get('status'),'replay_performed':False,'checks_passed':False,'reason':'Complete source snapshot required; no local replay was applied'})
        raise SystemExit(2)
    state=upgrade(seed(True)); state['environment']='verification'
    mapping=import_sources(state,snapshot['records'])
    def identities():
        # Preserve multiplicity and ownership: sets would hide duplicate source tasks.
        cases=sorted((p['id'],p['code'],p.get('case_type')) for p in state['projects'])
        tasks=sorted((p['id'],n['key'],t['id']) for p in state['projects'] for n in p['nodes'] for t in n['tasks'])
        return cases,tasks
    before,tasks_before=identities()
    import_sources(state,snapshot['records'])
    repeat_stable=(before,tasks_before)==identities()
    after,tasks_after=identities()
    edited=deepcopy(snapshot['records']); quote=next((r for r in edited if r['kind']=='quote'),None)
    if quote:
        quote['fields']['備註']='LOCAL REPLAY VERIFICATION — never written to Lark'
        import_sources(state,edited)
    update_stable=(before,tasks_before)==identities() if quote else None
    result={'identity':'application','remote_writes':False,'source_status':snapshot['status'],'last_sync':snapshot['last_sync'],'tables':[{'kind':t['kind'],'table_id':t['table_id'],'status':t['status'],'count':t.get('count')} for t in snapshot['tables']],'records':len(snapshot['records']),'records_by_kind':dict(Counter(r['kind'] for r in snapshot['records'])),'projects':len(state['projects']),'formal_cases':sum(p.get('case_type')=='formal' for p in state['projects']),'intake_records':sum(p.get('case_type')=='intake' for p in state['projects']),'multiple_quote_cases':sum(len(p.get('quotes',[]))>1 for p in state['projects']),'repeated_sync_preserves_case_and_task_ids':repeat_stable,'local_quote_update_creates_no_case':update_stable,'daily_unmatched':len(state.get('daily_unmatched',[])),'identity_conflicts':len(state.get('source_identity_conflicts',[])),'case_source_conflicts':sum(bool(p.get('source_conflicts')) for p in state['projects'])}
    result.update(replay_performed=True,local_quote_update_tested=quote is not None,task_count=len(identities()[1]),daily_imported=mapping['daily_imported'],daily_missing_date=mapping['daily_missing_date'],daily_conflicting_dates=mapping['daily_conflicting_dates'],daily_missing_department=mapping['daily_missing_department'],daily_provisional=mapping['daily_provisional'],confirmations_missing_code=mapping['confirmations_missing_code'],checks_passed=bool(repeat_stable and update_stable))
    result.update(snapshot_read='private_cache' if cached else 'application_get',first_import_project_count=len(before),second_import_project_count=len(after),first_import_task_count=len(tasks_before),second_import_task_count=len(tasks_after))
    # Identity stability alone cannot certify the requested daily-report wiring.
    # Preserve the strict identity assertions and expose a separate coverage gate.
    daily_present=any(r['kind']=='daily' for r in snapshot['records'])
    mapping_validated=not daily_present or mapping['daily_imported']>0
    result.update(identity_checks_passed=bool(repeat_stable and update_stable),daily_mapping_validated=mapping_validated,mapping_review_required=bool(mapping['daily_unmatched'] or mapping['confirmations_missing_code']))
    result['daily_unmatched_by_reason']={key.removeprefix('daily_unmatched_'):value for key,value in mapping.items() if key.startswith('daily_unmatched_')}
    result['checks_passed']=bool(repeat_stable and update_stable and mapping_validated)
    write_report(result)
    if not result['checks_passed']: raise SystemExit(1)

if __name__=='__main__': main()
