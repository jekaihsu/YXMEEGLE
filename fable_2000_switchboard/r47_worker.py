#!/usr/bin/env python3
"""R47 local replay/outbox worker. No network delivery. Run --once or as a service."""
import argparse
import hashlib
import json
from pathlib import Path
import time
from r47_launch import connection, doorbell
from switchboard_engine import classify_inbound_email, strip_quoted_chain


def replay_one(conn):
    job=conn.execute("SELECT j.run_id,r.org_id FROM annotation_replay_job j JOIN annotation_run r ON r.id=j.run_id WHERE j.status='pending' ORDER BY j.created_at FOR UPDATE OF j SKIP LOCKED LIMIT 1").fetchone()
    if not job:return False
    run,org=job['run_id'],job['org_id']
    samples=conn.execute('''SELECT g.*,m.from_addr,m.to_addrs,m.subject,m.body_new_text,m.dkim_pass,m.spf_pass,m.dkim_domain
      FROM annotation_sample s JOIN switchboard_gold_label g USING(sample_id) JOIN email_message m ON m.message_id=g.message_id
      WHERE s.run_id=%s ORDER BY g.sample_id''',(run,)).fetchall()
    if len(samples)!=200 or any(g['gold_category'] is None for g in samples): raise RuntimeError('replay needs 200 finalized samples')
    fingerprint=hashlib.sha256(Path(__file__).with_name('switchboard_engine.py').read_bytes()).hexdigest()
    conn.execute("UPDATE annotation_replay_job SET status='running' WHERE run_id=%s",(run,))
    conn.execute('DELETE FROM switchboard_backtest_eval WHERE run_id=%s',(run,))
    for g in samples:
        start=time.monotonic()
        p=classify_inbound_email(g['from_addr'],g['to_addrs'] or [],g['subject'] or '',strip_quoted_chain(g['body_new_text'] or ''),dkim_pass=bool(g['dkim_pass']),spf_pass=bool(g['spf_pass']),dkim_domain=g['dkim_domain'])
        internal=p.category=='INTERNAL-CMD';filtered=p.category=='CAT-09';emit=not filtered and not internal and not p.is_otp_candidate and not p.quarantine_reason
        # The existing classifier does not extract commitments or validate numerical evidence.
        # Explicit false/NULL predictions keep those gates red rather than trusting gold/defaults.
        conn.execute('''INSERT INTO switchboard_backtest_eval(run_id,sample_id,category,expected_should_emit_card,actual_emitted_card,
          git_sha,rule_bundle_hash,prompt_version,rule_version,pred_category,pred_org_id,pred_case_code,predicted_category,predicted_org,predicted_should_filter,predicted_emit_card,
          predicted_case_code,predicted_is_internal_cmd,predicted_is_injection,predicted_is_otp,predicted_is_commitment,predicted_commitment_due,evidence_numbers_match,
          cat_match,org_match,case_match,assignee_match,commitment_match,latency_ms,confidence)
          VALUES(%s,%s,%s,%s,%s,%s,%s,'r47-existing-router','r47',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,false,NULL,false,%s,%s,%s,false,false,%s,NULL)''',
          (run,g['sample_id'],g['gold_category'],bool(g['gold_should_emit_card']),emit,fingerprint,fingerprint,p.category,p.org_id,p.case_ref,p.category,p.org_id,filtered,emit,p.case_ref,internal,p.injection_suspect,p.is_otp_candidate,p.category==g['gold_category'],p.org_id==g['gold_org_id'],p.case_ref==g['gold_case_code'],int((time.monotonic()-start)*1000)))
    gates=conn.execute('SELECT * FROM backtest_gate(%s)',(run,)).fetchall()
    failures=[g for g in gates if g['pass'] is False]
    conn.execute('UPDATE annotation_replay_job SET status=%s,gate_result=%s::jsonb WHERE run_id=%s',('failed' if failures else 'passed',json.dumps(gates,default=str),run))
    if failures:
        for it in conn.execute("SELECT id FROM employee WHERE org_id=%s AND role_code IN ('it','gm') AND employment_status='active' AND identity_confirmed ORDER BY (role_code='it') DESC LIMIT 1",(org,)).fetchall():
            conn.execute("SELECT set_config('app.current_employee_id',%s,true)",(str(it['id']),))
            conn.execute("SELECT enqueue_card(%s,NULL,%s,'admin',%s,jsonb_build_array(jsonb_build_object('label','兩人一致率 κ','value',(SELECT kappa FROM annotation_kappa_log WHERE run_id=%s),'sql_id','gold.kappa')),%s::jsonb)",(org,it['id'],'backtest-failed:'+str(run)+':'+str(it['id']),run,json.dumps({'label':'回測未達標：'+failures[0]['metric']+' '+failures[0]['actual'],'failures':failures})))
    return True


def queue_doorbells(conn):
    rows=conn.execute("""SELECT c.id FROM card c JOIN employee e ON e.id=c.assignee_employee_id WHERE c.state IN ('open','escalated','dry_run') AND c.case_id IS NOT NULL AND e.lark_open_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM notification_outbox n WHERE n.dedupe_key='lark:'||c.id||':'||e.lark_open_id) ORDER BY c.created_at LIMIT 100""").fetchall()
    for row in rows:doorbell(conn,row['id'])
    # Escalations are independent dedupe keys and stop while the employee is in field mode.
    escalations=conn.execute("""SELECT c.id,public.r47_work_hours(c.created_at,now()) hours
       FROM card c JOIN employee e ON e.id=c.assignee_employee_id
       WHERE c.state IN ('open','escalated','dry_run') AND c.case_id IS NOT NULL
       AND (e.field_mode_until IS NULL OR e.field_mode_until<now())
       AND public.r47_work_hours(c.created_at,now())>=4""").fetchall()
    for row in escalations:
        for tier,hours in [('4h',4),('8h',8),('1d',24)]:
            if row['hours']>=hours:doorbell(conn,row['id'],tier)
    return len(rows)


def tick():
    with connection() as conn:
        replay_one(conn)
        queue_doorbells(conn)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--once',action='store_true');args=parser.parse_args()
    while True:
        tick()
        if args.once:break
        time.sleep(15)
