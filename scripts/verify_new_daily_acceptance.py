"""Read-only application acceptance for explicitly created, separately journaled V4 test rows.
No remote record writes. Uses the production source reader, isolated memory state,
and private snapshots. Report omits business records and credentials.
"""
import argparse,json,sys
sys.stdout.reconfigure(encoding='utf-8')
from copy import deepcopy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.lark_adapter import application_adapter
from backend.sources import fetch_sources,import_sources,source_id
from backend.seed import seed

def main():
 p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--phase',required=True);p.add_argument('--record-id');p.add_argument('--only-test-table',action='store_true');args=p.parse_args()
 raw=json.loads(Path(args.config).read_text(encoding='utf-8-sig'));cfg=raw.get('variables',{}).get('data',raw).copy();cfg['LARK_SOURCE_TABLES_JSON']=(ROOT/'deployment/source-tables.json').read_text(encoding='utf-8-sig');cfg['LARK_WORKER_IDENTITY']='application';tenants=[v.strip() for v in cfg.get('LARK_ALLOWED_TENANTS','').split(',') if v.strip()];assert len(tenants)==1;cfg['LARK_WORKER_ORGANIZATION']=tenants[0]
 if args.only_test_table:cfg['LARK_SOURCE_TABLES_JSON']=json.dumps([t for t in json.loads(cfg['LARK_SOURCE_TABLES_JSON']) if t['table_id']=='tbl5zPLS0ExWNEty'])
 adapter=application_adapter(cfg)
 try:snapshot=fetch_sources(adapter.token,cfg=cfg)
 finally:adapter.client.close()
 assert snapshot.get('status')=='ready','Complete requested source snapshot required'
 if args.only_test_table:
  baseline=json.loads((ROOT/'.runtime/new-daily-app-before-private.json').read_text(encoding='utf-8'));snapshot['records']=[r for r in baseline['records'] if r['table_id']!='tbl5zPLS0ExWNEty']+snapshot['records']
 private=ROOT/'.runtime';path=private/f'new-daily-app-{args.phase}-private.json';path.write_text(json.dumps(snapshot,ensure_ascii=False),encoding='utf-8')
 state_path=private/'new-daily-baseline-state-private.json';baseline_path=private/'new-daily-baseline-shape-private.json'
 def shape(w):return [(p['id'],p['code'],[(n['id'],n['status'],[(t['id'],t['status'],t.get('output')) for t in n['tasks']]) for n in p['nodes']]) for p in w['projects']]
 if args.phase=='before':
  state=seed(True);stats=import_sources(state,snapshot['records'],complete_tables=snapshot.get('tables',[]));state_path.write_text(json.dumps(state,ensure_ascii=False),encoding='utf-8');baseline_path.write_text(json.dumps(shape(state),ensure_ascii=False),encoding='utf-8')
 else:
  working=private/'new-daily-working-state-private.json';state=json.loads((working if working.exists() else state_path).read_text(encoding='utf-8'));stats=import_sources(state,snapshot['records'],complete_tables=snapshot.get('tables',[]))
 checks={'read_scope':'fresh_application_daily_table_with_baseline_case_context' if args.only_test_table else 'fresh_application_all_configured_tables','phase':args.phase,'source_status':snapshot['status'],'application_read':True,'remote_writes_by_script':0,'source_rows':len(snapshot['records']),'formal_cases':sum(x.get('case_type')=='formal' for x in state['projects']),'intakes':sum(x.get('case_type')=='intake' for x in state['projects']),'daily_total':sum(x.get('kind')=='daily' for x in snapshot['records']),'daily_imported':stats['daily_imported'],'daily_unmatched':stats['daily_unmatched'],'old_migration_scope':'Existing 535 rows are historic migration cohort per user; not the new-daily pass criterion'}
 original=json.loads(baseline_path.read_text(encoding='utf-8'));checks['case_and_task_identity_status_output_unchanged']=json.loads(json.dumps(shape(state)))==original
 if args.record_id:
  records=[r for r in snapshot['records'] if r['record_id']==args.record_id and r['kind']=='daily'];checks['test_source_rows']=len(records)
  if not records:
   ident=source_id({'base_token':'H7W6b0PFWaVF1BsgqXJj3pQ9pXb','table_id':'tbl5zPLS0ExWNEty','record_id':args.record_id});checks['deleted_source_still_active']=sum(d['id']==ident for p in state['projects'] for d in p['daily_reports'])+sum(d['id']==ident and not d.get('source_missing') for d in state['daily_unmatched']);checks['deleted_source_preserved_as_missing_history']=sum(d['id']==ident and bool(d.get('source_missing')) for d in state['daily_unmatched'])
  if records:
   ident=source_id(records[0]);matched=[(p,d) for p in state['projects'] for d in p['daily_reports'] if d['id']==ident];unmatched=[d for d in state['daily_unmatched'] if d['id']==ident];checks.update(test_record_id=args.record_id,test_daily_id=ident,test_matched=len(matched),test_unmatched=len(unmatched),test_case_code=matched[0][0]['code'] if matched else None,test_case_mapping_status=(matched[0][1] if matched else unmatched[0]).get('case_mapping_status') if matched or unmatched else None,test_mapping_status=(matched[0][1] if matched else unmatched[0]).get('mapping_status') if matched or unmatched else None,test_description=(matched[0][1] if matched else unmatched[0]).get('description') if matched or unmatched else None,test_actor_ids=(matched[0][1] if matched else unmatched[0]).get('source_actor_ids') if matched or unmatched else None,test_review_status=(matched[0][1] if matched else unmatched[0]).get('review',{}).get('status') if matched or unmatched else None)
   before=deepcopy(state);import_sources(state,snapshot['records'],complete_tables=snapshot.get('tables',[]));checks['repeat_same_project_task_state']=shape(before)==shape(state);checks['repeat_test_daily_count']=sum(d['id']==ident for p in state['projects'] for d in p['daily_reports'])+sum(d['id']==ident for d in state['daily_unmatched'])
 (private/'new-daily-working-state-private.json').write_text(json.dumps(state,ensure_ascii=False),encoding='utf-8')
 report=private/f'new-daily-app-{args.phase}-report.json';report.write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(checks,ensure_ascii=False))
if __name__=='__main__':main()

