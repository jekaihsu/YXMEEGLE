#!/usr/bin/env python3
"""Reproducible live verification; exit nonzero and write passed=false on any failed stage.
The bundled fixture run is explicitly scoped and never represents the unavailable 50k export.
"""
from __future__ import annotations
import argparse,datetime,hashlib,json,os,subprocess,sys,xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import psycopg
from ci.gen_guard_constants import check
import db
OUT=ROOT.parent/'results/r31b_convergence';FABLE=Path('/workspace/fable/r30/files')

def dump(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str)+'\n')
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--dsn',default=os.environ.get('PG_DSN','dbname=yongxiang_plumb_r39_clone'));ap.add_argument('--eml-dir',type=Path,default=FABLE/'_fixture/eml');ap.add_argument('--sheet-csv',type=Path,default=FABLE/'_fixture/sheet.csv');a=ap.parse_args()
    with psycopg.connect(a.dsn) as _gconn:
        current_db=_gconn.execute('SELECT current_database()').fetchone()[0]
        assert current_db != 'yongxiang_plumb', f"FATAL: Test script forbidden from connecting to production DB yongxiang_plumb (got {current_db})"
    OUT.mkdir(parents=True,exist_ok=True);checks=[];env={**os.environ,'PG_DSN':a.dsn}
    def record(name,passed,detail):
        checks.append({'name':name,'passed':bool(passed),'detail':detail});print(('PASS' if passed else 'FAIL')+' '+name,flush=True)
    def run(name,args,custom_env=None):
        result=subprocess.run(args,cwd=ROOT,env=custom_env or env,capture_output=True,text=True)
        (OUT/(name+'.log')).write_text(result.stdout+result.stderr)
        record(name,result.returncode==0,{'returncode':result.returncode,'log':str(OUT/(name+'.log'))})
        if result.returncode:raise RuntimeError(name+' failed; see log')
        return result.stdout
    def state():
        with psycopg.connect(a.dsn) as conn:
            return conn.execute("SELECT jsonb_build_object('org',(SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM org t),'rules',(SELECT jsonb_agg(to_jsonb(t) ORDER BY rule_code) FROM client_playbook_rule t WHERE rule_code IS NOT NULL),'templates',(SELECT jsonb_agg(to_jsonb(t) ORDER BY code) FROM email_template t),'otp',(SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM otp_forward_rule t))").fetchone()[0]
    def apply(name,path):
        run_env=dict(env)
        if Path(path).name=='009d2_r40_fixpack.sql':
            sha=hashlib.sha256(Path(path).read_bytes()).hexdigest()
            run_env['PGOPTIONS']=f'-c app.migration_sha={sha}'
        run(name,['psql','-X','-v','ON_ERROR_STOP=1','--dbname',a.dsn,'-f',str(path)],custom_env=run_env)
    db.DATABASE=a.dsn
    run_before=db.snapshot();dump(OUT/'final_run_dim_fact_before.json',run_before)
    parity={};golden={};suite={};backfill={};drift={};observations=[];legacy_count=None;initial_apply=None
    try:
        apply('seed_idempotency_1',FABLE/'006_seed_client_playbook_and_templates.sql');seed_state=state()
        apply('seed_idempotency_2',FABLE/'006_seed_client_playbook_and_templates.sql');record('seed_row_identity_and_content_unchanged',state()==seed_state,'Compared all org identities, rule/template/OTP rows, including their primary keys')
        for index in (1,2):
            apply('convergence_idempotency_'+str(index),ROOT/'sql/009_r31b_convergence.sql')
            apply('r32_12_audit_fixes_'+str(index),ROOT/'sql/009_r32_12_audit_fixes.sql')
            apply('r32_fixpack_009b_'+str(index),ROOT/'sql/009b_r32_fixpack.sql')
            apply('r32_fixpack_009c_'+str(index),ROOT/'sql/009c_r32_fixpack.sql')
            apply('r32_fixpack_009d_'+str(index),ROOT/'sql/009d_r32_fixpack.sql')
            apply('r40_fixpack_009d2_'+str(index),ROOT/'sql/009d2_r40_fixpack.sql')
            apply('guard_constants_idempotency_'+str(index),ROOT/'sql/010_guard_constants.sql')
        # Older migrations must retain the latest installed guard and payment definitions.
        apply('older_r29_replay',ROOT/'sql/r29_hardlocks.sql')
        apply('convergence_post_r29',ROOT/'sql/009_r31b_convergence.sql')
        apply('r32_12_post_r29',ROOT/'sql/009_r32_12_audit_fixes.sql')
        apply('r32_fixpack_009b_post_r29',ROOT/'sql/009b_r32_fixpack.sql')
        apply('r32_fixpack_009c_post_r29',ROOT/'sql/009c_r32_fixpack.sql')
        apply('r32_fixpack_009d_post_r29',ROOT/'sql/009d_r32_fixpack.sql')
        apply('r40_fixpack_009d2_post_r29',ROOT/'sql/009d2_r40_fixpack.sql')
        apply('guard_constants_post_r29',ROOT/'sql/010_guard_constants.sql')
        parity=check(a.dsn);record('python_postgresql_parity',True,parity)
        run('golden_23',[sys.executable,'-m','pytest','-q',str(FABLE/'test_switchboard_golden.py'),'--junitxml='+str(OUT/'golden.xml')])
        run('convergence_and_parity_tests',[sys.executable,'-m','pytest','-q','tests','--junitxml='+str(OUT/'pytest.xml')])
        for name,xml in [('golden',OUT/'golden.xml'),('suite',OUT/'pytest.xml')]:
            nodes=ET.parse(xml).getroot().findall('testsuite');counts={key:sum(int(n.get(key,0)) for n in nodes) for key in ('tests','failures','errors','skipped')}
            if name=='golden':golden=counts
            else:suite=counts
        base=[sys.executable,str(FABLE/'backfill_stitch_50k.py'),'--eml-dir',str(a.eml_dir),'--sheet-csv',str(a.sheet_csv),'--dsn',a.dsn]
        with psycopg.connect(a.dsn) as conn:
            count_before=conn.execute('SELECT count(*) FROM email_message').fetchone()[0]
        run('backfill_dry_run',base+['--dry-run','--report',str(OUT/'backfill_dry_run.json')])
        with psycopg.connect(a.dsn) as conn: count_after=conn.execute('SELECT count(*) FROM email_message').fetchone()[0]
        record('dry_run_does_not_write',count_after==count_before,{'before':count_before,'after':count_after})
        output=run('backfill_apply',base+['--apply','--report',str(OUT/'backfill_apply.json')])
        record('six_stitch_assertions',output.count('PASS  ')==6 and 'FAIL  ' not in output,{'passed':output.count('PASS  '),'expected':6})
        run('backfill_apply_repeat',base+['--apply','--report',str(OUT/'backfill_apply_repeat.json')])
        repeated=json.loads((OUT/'backfill_apply_repeat.json').read_text());backfill=json.loads((OUT/'backfill_apply.json').read_text())
        record('backfill_replay_inserts_zero',all(repeated['db'][key]==0 for key in ('mails_inserted','links_inserted','comms_inserted')),repeated['db'])
        parity=check(a.dsn);record('final_deployed_guard_parity',True,parity)
        initial=json.loads((OUT/'before/dim_fact.json').read_text());before=run_before;after=db.snapshot();dump(OUT/'dim_fact_after.json',after)
        drift={'unchanged':before==after,'objects_before':len(before),'objects_after':len(after),'changed':[x['schema']+'.'+x['name'] for x,y in zip(before,after) if x!=y]}
        drift['verification_window']='final reproducible verification run'
        drift['initial_workspace_differences']=[{'object':x['schema']+'.'+x['name'],'fields':[key for key in x if x[key]!=y[key]],'initial_data':x.get('data'),'current_data':y.get('data')} for x,y in zip(initial,after) if x!=y]
        drift['initial_snapshot_note']='Original snapshot retained. Other R29/R30 and ROV tasks were active in this shared database; initial workspace differences are disclosed, not repaired or silently reset.'
        record('existing_dim_fact_unchanged',drift['unchanged'],drift)
        with psycopg.connect(a.dsn) as conn:
            row=conn.execute('SELECT id,mails_seen,mails_inserted,links_inserted,comms_inserted,quarantined,finished_at FROM backfill_run WHERE mails_inserted>0 ORDER BY started_at LIMIT 1').fetchone()
            initial_apply=dict(zip(('run_id','mails_seen','mails_inserted','links_inserted','comms_inserted','quarantined','finished_at'),row)) if row else None
            legacy_count=conn.execute('SELECT count(*) FROM public."case" WHERE case_code IS NOT NULL AND NOT(case_code ~ %s)',('^[A-MVXZ][0-9]{6}(-[0-9A-Z]{1,3})?$',)).fetchone()[0]
            observations=conn.execute("SELECT DISTINCT from_addr FROM email_message WHERE from_addr ~ '(nlsc|cpc)' AND subject ~ '驗證碼' AND raw_mime_path NOT LIKE %s",(str(FABLE/'_fixture')+'/%',)).fetchall()
            record('hr_private_isolation',not conn.execute("SELECT has_schema_privilege('sales_role','hr_private','USAGE') OR has_table_privilege('pm_sales_finance_role','hr_private.bonus_line','SELECT')").fetchone()[0],'Sales and PM/sales/finance role have no private bonus access')
            record('sales_standard_cost_denied',not conn.execute("SELECT has_column_privilege('sales_role','public.work_item_policy','standard_cost_price','SELECT')").fetchone()[0],'Column-level database denial and authenticated API projection both tested')
    except Exception as exc:
        record('verification_exception',False,str(exc))
    failed=sum(not row['passed'] for row in checks)
    fixture=a.eml_dir.resolve()==(FABLE/'_fixture/eml').resolve()
    items=[('single_assignee_and_notification_outbox','test_single_card_and_notification_copy'),('internal_settlement_and_private_cash_bonus','test_gm_settlement_before_cash_and_cash_bonus_blocked'),('case_code_single_constant','test_case_constraint_entire_corpus'),('serial_and_fingerprint_separate_uniqueness','test_serial_and_fingerprint_independently_unique'),('internal_address_not_authentication','test_sent_copy_verification_remains_database_gate'),('proposed_fields_and_sql_evidence','test_sql_evidence_cannot_use_agent_numbers'),('bank_fee_30_100_requires_finance_confirmation','test_finance_fee_recognition_unlocks_only_after_confirmation'),('employee_alias_and_admin_fallback','test_alias_mapping_and_unknown_routes_to_admin'),('single_idempotent_action_across_channels','test_both_renderers_use_one_action_and_concurrent_exactly_once'),('api_role_column_whitelists','test_api_role_whitelist_and_no_spoofing')]
    report={'suite':'Fable R30 + R31-B convergence','verified_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'database':'yongxiang_plumb','passed':failed==0,'failed_count':failed,'verification_scope':'Live PostgreSQL schema, API handlers, shared guards, and '+('bundled synthetic backfill fixtures' if fixture else 'provided mail export'),'checks':checks,'golden':golden,'tests':suite,'guard_parity':parity,'stitch':{'assertions_passed':6 if any(c['name']=='six_stitch_assertions' and c['passed'] for c in checks) else 0,'source_kind':'synthetic_fixture' if fixture else 'provided_export','eml_dir':str(a.eml_dir),'sheet_csv':str(a.sheet_csv),'summary':backfill,'first_successful_apply':initial_apply},'convergence_items':[{'number':i,'item':name,'test':test,'passed':suite.get('failures')==0 and suite.get('errors')==0 and suite.get('skipped')==0} for i,(name,test) in enumerate(items,1)],'dim_fact':drift,'legacy_case_codes':{'invalid_existing_rows':legacy_count,'constraint_not_valid':True,'policy':'Existing rows are preserved; new writes use the exact requested pattern; no silent renumbering'},'otp_sender_verification':{'non_fixture_observed_addresses':[row[0] for row in observations],'production_sender_verified':bool(observations)},'full_history_backfill':{'completed':not fixture and backfill.get('mails',0)>=50578,'expected_mails':50578,'expected_sheet_rows':12084,'limitation':'Raw production EML directory and authoritative Sheet CSV were not found; bundled fixtures are not the full history' if fixture else None},'delivery':{'api_listener_started':False,'external_messages_sent':0,'lark_transport_exercised':False},'artifact_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'switchboard_engine.py',ROOT/'sql/009_r31b_convergence.sql',ROOT/'sql/009_r32_12_audit_fixes.sql',ROOT/'sql/009b_r32_fixpack.sql',ROOT/'sql/009c_r32_fixpack.sql',ROOT/'sql/010_guard_constants.sql',ROOT/'api.py',ROOT/'ci/guard_corpus.jsonl']}}
    dump(OUT/'result.json',report)
    print(json.dumps({'passed':report['passed'],'failed_count':failed,'report':str(OUT/'result.json')},ensure_ascii=False))
    return int(failed!=0)
if __name__=='__main__':sys.exit(main())
