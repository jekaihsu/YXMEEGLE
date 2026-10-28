#!/usr/bin/env python3
"""Live R29 six-guard verification. Synthetic fixtures, dry-run only; no transport calls.
Run with Python + psycopg2 (or the project .venv-r29). Failure always yields a false report.
"""
from pathlib import Path
import argparse, concurrent.futures, datetime, hashlib, json, os, re, socket, subprocess, sys, time, uuid
try:
    import psycopg2
except ImportError:
    local = Path(__file__).parent / '.venv-r29/bin/python'
    if local.exists() and str(Path(sys.executable).absolute()) != str(local.absolute()):
        os.execv(str(local), [str(local), __file__, *sys.argv[1:]])
    raise SystemExit('Install psycopg2-binary or use .venv-r29/bin/python')
ROOT=Path(__file__).resolve().parents[1]
SQL=Path(__file__).resolve().parent/'sql/r29_hardlocks.sql'
OUT=Path(__file__).resolve().parent/'formal/r29'
checks=[]

def check(guard,name,fn):
    try:
        detail=fn(); checks.append(dict(guard=guard,name=name,passed=True,detail=detail))
        print('PASS',guard,name,flush=True)
    except Exception as e:
        checks.append(dict(guard=guard,name=name,passed=False,error=str(e)))
        print('FAIL',guard,name,str(e),flush=True)

def uid(): return str(uuid.uuid4())
def execute(c,sql,args=()):
    with c.cursor() as q:
        q.execute(sql,args)
        return q.fetchall() if q.description else []
def scalar(c,sql,args=()): return execute(c,sql,args)[0][0]
def require(value,msg='assertion failed'):
    if not value: raise AssertionError(msg)
def reject(c,sql,args=(),state='P0001',match=None):
    execute(c,'SAVEPOINT negative_case')
    try:
        execute(c,sql,args)
    except psycopg2.Error as e:
        execute(c,'ROLLBACK TO SAVEPOINT negative_case')
        require(e.pgcode==state,f'expected {state}, got {e.pgcode}: {e}')
        require(match is None or match in str(e),str(e))
    else:
        execute(c,'ROLLBACK TO SAVEPOINT negative_case')
        raise AssertionError('unsafe write was accepted')
    finally: execute(c,'RELEASE SAVEPOINT negative_case')

def fixture(c):
    f={k:uid() for k in ['cust','emp','case','contact','invoice','out','intake','dv','gate','pi','mb_yx','mb_sj']}
    execute(c,"SAVEPOINT r48_pause_sp")
    try:
        execute(c,"INSERT INTO etl_pause_state(org_id,paused,reason,changed_by) VALUES ('YX',false,'R29 synthetic test','A'),('SJ',false,'R29 synthetic test','A') ON CONFLICT(org_id) DO UPDATE SET paused=false")
    except Exception:
        execute(c,"ROLLBACK TO SAVEPOINT r48_pause_sp")
    execute(c,"INSERT INTO email_mailbox(id,address,role,org_id) VALUES(%s,%s,'switchboard','YX'),(%s,%s,'switchboard','SJ')",(f['mb_yx'],'r29-yx-'+f['mb_yx']+'@example.test',f['mb_sj'],'r29-sj-'+f['mb_sj']+'@example.test'))
    execute(c,"INSERT INTO customer(id,org_id,name) VALUES(%s,'YX','R29 synthetic customer')",(f['cust'],))
    execute(c,"INSERT INTO employee(id,org_id,full_name,identity_confirmed,lark_open_id) VALUES(%s,'YX','R29 synthetic employee',true,'ou_r29_synthetic_employee')",(f['emp'],))
    execute(c,'INSERT INTO "case"(id,org_id,title,customer_id) VALUES(%s,\'YX\',\'R29 synthetic case\',%s)',(f['case'],f['cust']))
    execute(c,"INSERT INTO customer_contact(id,customer_id,full_name) VALUES(%s,%s,'R29 synthetic recipient')",(f['contact'],f['cust']))
    # total_amount is GENERATED ALWAYS; fixtures supply its inputs only.
    execute(c,"INSERT INTO invoice(id,org_id,case_id,customer_id,amount_due,subtotal_amount,tax_amount) VALUES(%s,'YX',%s,%s,100,100,0)",(f['invoice'],f['case'],f['cust']))
    require(scalar(c,'SELECT total_amount FROM invoice WHERE id=%s',(f['invoice'],))==100,
            'invoice fixture generated total must equal the payment under test')
    execute(c,"INSERT INTO switchboard_intake(id,source_key,serial_no,channel,occurred_at,evidence_kind,payload,is_synthetic) VALUES(%s,%s,%s,'staff_request',clock_timestamp(),'synthetic_test','{}',true)",(f['intake'],'r29-'+f['intake'],int(uuid.uuid4().int%1000000000000)+1000000000000))
    execute(c,"INSERT INTO outbound_message(id,intake_id,to_contact_id,case_id,org_id,draft_body,final_body,approved_by,approved_at,gate_results,action_card,release_gate_checked) VALUES(%s,%s,%s,%s,'YX','您好，附件供查照。','您好，附件供查照。',%s,clock_timestamp(),'{}','{}',true)",(f['out'],f['intake'],f['contact'],f['case'],f['emp']))
    execute(c,"INSERT INTO deliverable_version(id,case_id,org_id,status,sha256) VALUES(%s,%s,'YX','核定','synthetic-r29-sha')",(f['dv'],f['case']))
    execute(c,"INSERT INTO outbound_attachment(outbound_id,deliverable_version_id,deliverable_status) VALUES(%s,%s,'核定')",(f['out'],f['dv']))
    execute(c,"INSERT INTO deliverable_release_gate(id,case_id,org_id,milestone,deliverable_class,invoice_id) VALUES(%s,%s,'YX','FINAL','sealed',%s)",(f['gate'],f['case'],f['invoice']))
    return f

def message(c,**kw):
    data=dict(id=uid(),message_id='<'+uid()+'@r29.test>',from_addr='r29-satellite@example.test',org_id='YX',subject='e-GNSS 驗證碼',body_new_text='驗證碼 123456',category='CAT-01',sent_copy_verified=True,dkim_pass=True,spf_pass=True,dkim_domain='example.test')
    data.update(kw)
    if 'mailbox_id' not in data and (data.get('from_addr') != 'r29-satellite@example.test' or data.get('org_id') == 'SJ'):
        mb_rows = execute(c, "SELECT id FROM email_mailbox WHERE org_id=%s AND role='switchboard' LIMIT 1", (data.get('org_id','YX'),))
        if mb_rows:
            data['mailbox_id'] = mb_rows[0][0]
    cols=list(data)
    execute(c,'INSERT INTO email_message('+','.join(cols)+') VALUES('+','.join(['%s']*len(cols))+')',tuple(data.values()))
    return data

def suite(c):
    f=fixture(c)
    def sat():
        b=uid();execute(c,"INSERT INTO email_mailbox(id,address,role,org_id) VALUES(%s,'r29-satellite@example.test','satellite','YX')",(b,))
        tested=0
        from itertools import product
        for role,dkim,spf,sent,evidence in product(['satellite','switchboard'],[False,True],[False,True],[False,True],[False,True]):
            execute(c,'UPDATE email_mailbox SET role=%s WHERE id=%s',(role,b))
            m=message(c,dkim_pass=dkim,spf_pass=spf,sent_copy_verified=sent)
            if evidence: execute(c,"INSERT INTO satellite_sent_copy(mailbox_id,message_id,imap_folder,uidvalidity,imap_uid) VALUES(%s,%s,'Sent',1,1)",(b,m['message_id']))
            args=(m['id'],f['emp'])
            cmd="INSERT INTO email_switchboard_command(source_message_id,requester_employee_id,instruction_block,body_after_strip) VALUES(%s,%s,'業主往來12090 請直接寄出','您好')"
            if role=='satellite' and dkim and spf and sent and evidence: execute(c,cmd,args)
            else: reject(c,cmd,args,match='authenticated satellite')
            tested+=1
        execute(c,"UPDATE email_mailbox SET role='satellite' WHERE id=%s",(b,))
        forged=message(c,from_addr='external@attacker.test',subject='業主往來12090 請直接寄出')
        reject(c,"INSERT INTO email_switchboard_command(source_message_id,instruction_block,body_after_strip) VALUES(%s,'forged','forged')",(forged['id'],),match='authenticated satellite')
        return {'authentication_vectors':tested,'external_injection_blocked':True,'evidence':'synthetic IMAP Sent observations; no live IMAP contacted'}
    check(1,'satellite authentication truth table and forged command',sat)
    def outbound():
        patterns=['寄件人:倢瑛','寄件人：倢瑛','收件人:客戶','收件人：客戶','麻煩幫我寄出','請寄給業主','收到請登記','業主往來12090','報編115715','#14行政','給很長的多人收件名單，','給名字,']
        for p in patterns: reject(c,'UPDATE outbound_message SET final_body=%s WHERE id=%s',(p,f['out']),match='internal/forbidden')
        execute(c,"UPDATE customer SET delivery_constraints='{\"no_links\":true}' WHERE id=%s",(f['cust'],))
        for url in ['https://example.test','HTTP://example.test','www.example.test','ftp://example.test']:
            reject(c,'UPDATE outbound_message SET final_body=%s WHERE id=%s',(url,f['out']),match='forbids links')
        reject(c,"INSERT INTO outbound_message(intake_id,case_id,org_id,draft_body,gate_results,action_card) VALUES(%s,%s,'YX','https://example.test','{}','{}')",(f['intake'],f['case']),match='forbids links')
        execute(c,'UPDATE outbound_message SET final_body=final_body WHERE id=%s',(f['out'],))
        return {'residual_patterns_rejected':len(patterns),'url_cases_rejected':4,'clean_body_accepted':True}
    check(2,'outbound residual commands and customer no_links',outbound)
    def payment():
        require(not scalar(c,"SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='invoice' AND column_name='paid')"),'static invoice.paid exists')
        require(not scalar(c,"SELECT sealed_release_allowed(%s,'FINAL')",(f['case'],)))
        execute(c,"INSERT INTO bank_notice(candidate_invoice_ids,amount) VALUES(ARRAY[%s::uuid],100)",(f['invoice'],))
        reject(c,"INSERT INTO bank_notice(status,amount) VALUES('allocated',100)",match='only creates a candidate')
        require(not scalar(c,'SELECT paid FROM invoice_paid_v WHERE id=%s',(f['invoice'],)))
        execute(c,"INSERT INTO payment_instrument(id,org_id,instrument_type,amount) VALUES(%s,'YX','check',100)",(f['pi'],))
        reject(c,'INSERT INTO receipt_allocation(invoice_id,instrument_id,amount) VALUES(%s,%s,100)',(f['invoice'],f['pi']),match='cleared')
        execute(c,"UPDATE payment_instrument SET status='cleared' WHERE id=%s",(f['pi'],))
        a=scalar(c,'INSERT INTO receipt_allocation(invoice_id,instrument_id,amount) VALUES(%s,%s,100) RETURNING id',(f['invoice'],f['pi']))
        require(scalar(c,'SELECT paid FROM invoice_paid_v WHERE id=%s',(f['invoice'],)))
        # Two reversals exercise aggregate fan-out (100 - 100 + 10 + 20 = 30).
        for amount in [10,20]: execute(c,'INSERT INTO receipt_reversal(allocation_id,amount) VALUES(%s,%s)',(a,amount))
        require(scalar(c,'SELECT unpaid_amount FROM invoice_paid_v WHERE id=%s',(f['invoice'],))==30,'reversal fan-out corrupted total')
        reject(c,'SELECT outbound_send(%s,%s)',(f['out'],f['emp']),match='hold_until_paid')
        execute(c,'DELETE FROM receipt_reversal WHERE allocation_id=%s',(a,))
        execute(c,"UPDATE payment_instrument SET status='received_uncleared' WHERE id=%s",(f['pi'],))
        require(not scalar(c,'SELECT paid FROM invoice_paid_v WHERE id=%s',(f['invoice'],)))
        execute(c,"UPDATE payment_instrument SET status='cleared' WHERE id=%s",(f['pi'],))
        execute(c,'SELECT outbound_send(%s,%s)',(f['out'],f['emp']))
        reject(c,'SELECT outbound_send(%s,%s)',(f['out'],f['emp']),match='already verified')
        require(scalar(c,"SELECT actual_sends=0 AND sent_at IS NULL AND status='DRY_RUN' FROM outbound_message WHERE id=%s",(f['out'],)))
        return {'candidate_only':True,'uncleared_excluded':True,'two_reversal_balance':30,'reversal_blocks_send':True,'clearance_recomputed':True,'actual_sends':0}
    check(3,'dynamic cleared totals, reversal fan-out and send recheck',payment)
    def org_serial():
        scoped=['quote','customer','case','employee','invoice','expense_line','client_communication',
                'client_commitment','outbound_message','email_mailbox','email_message','email_thread',
                'email_link','email_attachment','email_switchboard_command','email_template','email_rag_chunk',
                'bank_notice','deliverable_release_gate','deliverable_version','outbound_recipient',
                'outbound_attachment','payment_instrument','receipt_allocation','receipt_reversal','permit',
                'client_playbook_rule','case_settlement','otp_forward_rule','otp_request','otp_private_delivery',
                'satellite_sent_copy','serial_allocator','serial_assignment','quote_version','customer_contact']
        for table in scoped:
            if table == 'email_message':
                require(scalar(c,"SELECT EXISTS(SELECT 1 FROM pg_attribute WHERE attrelid='public.email_message'::regclass AND attname='org_id' AND NOT attisdropped)"),table+' missing org_id')
            else:
                require(scalar(c,"SELECT EXISTS(SELECT 1 FROM pg_attribute WHERE attrelid=%s::regclass AND attname='org_id' AND attnotnull AND NOT attisdropped)",('public.'+('"case"' if table=='case' else table),)),table+' missing NOT NULL org_id')
            require(scalar(c,"SELECT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid=%s::regclass AND conname='r29_org_fk' AND convalidated)",('public.'+('"case"' if table=='case' else table),)),table+' missing validated org FK')
        reject(c,"INSERT INTO invoice(org_id,case_id,subtotal_amount) VALUES('SJ',%s,100)",(f['case'],),state='23503')
        reject(c,"UPDATE outbound_message SET org_id='SJ' WHERE id=%s",(f['out'],),state='23503')
        reject(c,"INSERT INTO expense_line(org_id,case_id,employee_id,kind,vendor,billing_period_month,original_currency,original_amount,fx_rate_to_twd,receipt_ref,receipt_file_uri) VALUES('SJ',%s,%s,'general','R29 synthetic',date_trunc('month',CURRENT_DATE)::date,'TWD',1,1,'r29-synthetic','r29://synthetic')",(f['case'],f['emp']),state='23503')
        for table in ['quote','invoice','expense_line','client_communication','outbound_message','email_message','email_thread','email_rag_chunk','permit','case_settlement','client_commitment','deliverable_release_gate','deliverable_version','outbound_recipient']:
            require(scalar(c,"SELECT count(*)>0 FROM pg_constraint WHERE conrelid=%s::regclass AND contype='f' AND pg_get_constraintdef(oid) LIKE 'FOREIGN KEY (case_id, org_id)%%'",('public.'+table,)),table)
        org='R29-'+uid();execute(c,"INSERT INTO org(id,name) VALUES(%s,%s)",(org,org))
        execute(c,'INSERT INTO serial_allocator(org_id) VALUES(%s)',(org,))
        org_emp=uid()
        execute(c,"INSERT INTO org_marker(org_code,kind,value,verified_by) VALUES(%s,'tax_id',%s,'R29_TEST'),(%s,'domain',%s,'R29_TEST')",(org,'99'+org[-6:],org,org.lower()+'.example.test'))
        execute(c,"INSERT INTO serial_cutover_log(org_id,sheet_max,new_next,voided_dry_run,done_by) VALUES(%s,12084,12085,0,'R29_TEST')",(org,))
        execute(c,"INSERT INTO employee(id,org_id,full_name,employment_status,identity_confirmed) VALUES(%s,%s,'R29 org admin','active',true)",(org_emp,org))
        execute(c,"INSERT INTO employee_role_map(employee_id,role_code,assigned_by) VALUES(%s,'admin','R29_TEST')",(org_emp,))
        first=scalar(c,"SELECT assign_serial(%s,'same')",(org,))
        require(first==12085 and scalar(c,"SELECT assign_serial(%s,'same')",(org,))==first)
        execute(c,'SAVEPOINT serial_rollback')
        require(scalar(c,"SELECT assign_serial(%s,'rollback')",(org,))==12086)
        execute(c,'ROLLBACK TO SAVEPOINT serial_rollback')
        require(scalar(c,"SELECT assign_serial(%s,'next')",(org,))==12086)
        pi=scalar(c,"INSERT INTO payment_instrument(org_id,instrument_type,amount,status) VALUES('SJ','wire',100,'cleared') RETURNING id")
        reject(c,'INSERT INTO receipt_allocation(invoice_id,instrument_id,amount) VALUES(%s,%s,100)',(f['invoice'],pi),state='23503')
        mx=message(c);ms=message(c,org_id='SJ')
        reject(c,"INSERT INTO email_link(message_id,original_message_id,link_rule) VALUES(%s,%s,'references')",(mx['id'],ms['id']),state='23503')
        reject(c,"INSERT INTO bank_notice(email_message_id,org_id) VALUES(%s,'SJ')",(mx['id'],),state='23503')
        reject(c,"INSERT INTO customer_contact(customer_id,org_id,full_name) VALUES(%s,'SJ','synthetic mismatch')",(f['cust'],),state='23503')
        require(scalar(c,'INSERT INTO quote(customer_id,quote_no) VALUES(%s,%s) RETURNING org_id',(f['cust'],'R29-'+uid()))=='YX',
                'pre-case quote must derive customer org')
        return {'org_tables_verified':len(scoped),'cross_org_indirect_relationships_rejected':True,'cross_org_instrument_rejected':True,'YX_SJ_composite_fk':True,'first':first,'idempotent':True,'rollback_gapless':True}
    check(4,'org isolation and serial idempotency/rollback',org_serial)
    def otp():
        rid=scalar(c,"INSERT INTO otp_forward_rule(account_label,sender_exact,subject_regex,code_regex,org_id) VALUES('R29 e-GNSS','r29-otp@example.test','e-GNSS|EBCS','[0-9]{6}','YX') RETURNING id")
        def otpmsg(**kw): return message(c,**dict(dict(from_addr='r29-otp@example.test',category='CAT-10'),**kw))
        m=otpmsg(); require(scalar(c,'SELECT otp_deliver(%s)',(m['id'],)) is None)
        req=scalar(c,"INSERT INTO otp_request(rule_id,requester_employee_id,org_id,requested_at) VALUES(%s,%s,'YX',clock_timestamp()-interval '6 minutes') RETURNING id",(rid,f['emp']))
        require(scalar(c,'SELECT otp_deliver(%s)',(m['id'],)) is None)
        execute(c,'DELETE FROM otp_request WHERE id=%s',(req,))
        req=scalar(c,"INSERT INTO otp_request(rule_id,requester_employee_id,org_id,requested_at) VALUES(%s,%s,'YX',clock_timestamp()-interval '1 second') RETURNING id",(rid,f['emp']))
        reject(c,"INSERT INTO otp_request(rule_id,requester_employee_id,org_id) VALUES(%s,%s,'YX')",(rid,f['emp']),match='rate limit')
        exclusions=['password','reset','密碼','銀行','google']
        for term in exclusions:
            for field in ['subject','body_new_text']:
                m=otpmsg(**{field:('e-GNSS '+term+' 123456')})
                require(scalar(c,'SELECT otp_deliver(%s)',(m['id'],)) is None,term)
        for kw in [dict(dkim_pass=False),dict(spf_pass=False),dict(dkim_domain='attacker.test'),dict(body_new_text='no code'),dict(org_id='SJ')]:
            m=otpmsg(**kw); require(scalar(c,'SELECT otp_deliver(%s)',(m['id'],)) is None,str(kw))
        m=otpmsg(subject='EBCS 驗證碼')
        require(str(scalar(c,'SELECT otp_deliver(%s)',(m['id'],)))==f['emp'])
        require(scalar(c,'SELECT otp_deliver(%s)',(m['id'],)) is None,'replay accepted')
        require(scalar(c,"SELECT count(*)=1 AND bool_and(channel='private_dm' AND NOT is_group AND transport_status='DRY_RUN') FROM otp_private_delivery WHERE request_id=%s",(req,)))
        reject(c,"UPDATE otp_private_delivery SET is_group=true WHERE request_id=%s",(req,),state='23514')
        reject(c,"UPDATE otp_private_delivery SET recipient_employee_id=gen_random_uuid() WHERE request_id=%s",(req,),match='requesting employee')
        return {'excluded_subject_and_body_vectors':10,'unrequested_expired_forged_replay_blocked':True,'private_requester_only':True,'group_broadcasts':0}
    check(5,'OTP pull/TTL/authentication/exclusions/private target',otp)
    def rag():
        for cat in ['CAT-09','CAT-10']:
            reject(c,"INSERT INTO email_rag_chunk(org_id,category,chunk_no,chunk_text,content_hash) VALUES('YX',%s,1,'synthetic','synthetic')",(cat,),state='23514')
            m=message(c,category=cat)
            reject(c,"INSERT INTO email_rag_chunk(message_id,org_id,category,chunk_no,chunk_text,content_hash) VALUES(%s,'YX','CAT-01',1,'synthetic','synthetic')",(m['id'],),match='private')
        m=message(c,category='CAT-01')
        chunk=scalar(c,"INSERT INTO email_rag_chunk(message_id,org_id,category,chunk_no,chunk_text,content_hash) VALUES(%s,'YX','CAT-01',1,'synthetic','synthetic') RETURNING id",(m['id'],))
        reject(c,"UPDATE email_rag_chunk SET category='CAT-09' WHERE id=%s",(chunk,),match='private')
        reject(c,"UPDATE email_message SET category='CAT-01' WHERE id=%s",(m['id'],),match='append-only')
        return {'private_categories_rejected':2,'source_relabel_bypass_rejected':True,'public_chunk_accepted':True}
    check(6,'RAG privacy CHECK and source relabel defense',rag)
    c.rollback()

def concurrent_checks(dsn):
    # Only disposable non-email fixtures are committed for visibility across sessions.
    c=psycopg2.connect(dsn);c.autocommit=False
    f=fixture(c)
    a=scalar(c,'INSERT INTO receipt_allocation(invoice_id,amount) VALUES(%s,100) RETURNING id',(f['invoice'],))
    org='R29-'+uid();org_emp=uid();execute(c,'INSERT INTO org(id,name) VALUES(%s,%s)',(org,org))
    execute(c,'INSERT INTO serial_allocator(org_id) VALUES(%s)',(org,))
    execute(c,"INSERT INTO org_marker(org_code,kind,value,verified_by) VALUES(%s,'tax_id',%s,'R29_TEST'),(%s,'domain',%s,'R29_TEST')",(org,'98'+org[-6:],org,org.lower()+'.example.test'))
    execute(c,"INSERT INTO serial_cutover_log(org_id,sheet_max,new_next,voided_dry_run,done_by) VALUES(%s,12084,12085,0,'R29_TEST')",(org,))
    execute(c,"INSERT INTO employee(id,org_id,full_name,employment_status,identity_confirmed) VALUES(%s,%s,'R29 concurrent admin','active',true)",(org_emp,org))
    execute(c,"INSERT INTO employee_role_map(employee_id,role_code,assigned_by) VALUES(%s,'admin','R29_TEST')",(org_emp,));c.commit()
    def connection():
        q=psycopg2.connect(dsn);execute(q,"SET statement_timeout='8s'");return q
    def await_lock(pid):
        deadline=time.monotonic()+4
        while time.monotonic()<deadline:
            if scalar(c,"SELECT coalesce(wait_event_type='Lock',false) FROM pg_stat_activity WHERE pid=%s",(pid,)):
                c.commit(); return
            c.commit(); time.sleep(.025)
        raise AssertionError('second connection did not wait on the expected database lock')
    try:
        def serial():
            one,two=connection(),connection()
            try:
                first=scalar(one,"SELECT assign_serial(%s,'same')",(org,))
                pid=scalar(two,'SELECT pg_backend_pid()')
                with concurrent.futures.ThreadPoolExecutor(1) as pool:
                    fut=pool.submit(scalar,two,"SELECT assign_serial(%s,'same')",(org,))
                    await_lock(pid);one.commit();second=fut.result(timeout=8);two.commit()
                require(first==second==12085,'concurrent duplicate got different numbers')
                def alloc(fp):
                    q=connection()
                    try:
                        n=scalar(q,'SELECT assign_serial(%s,%s)',(org,fp));q.commit();return n
                    finally:q.close()
                with concurrent.futures.ThreadPoolExecutor(2) as pool:
                    nums=list(pool.map(alloc,['next-1','next-2']))
                require(sorted(nums)==[12086,12087])
                return {'duplicate_serials':[first,second],'distinct_serials':sorted(nums),'lock_wait_observed':True}
            finally:one.close();two.close()
        check(4,'two-connection duplicate and distinct serial race',serial)
        def reversal_race():
            one,two=connection(),connection()
            try:
                execute(one,'INSERT INTO receipt_reversal(allocation_id,amount) VALUES(%s,100)',(a,))
                pid=scalar(two,'SELECT pg_backend_pid()')
                with concurrent.futures.ThreadPoolExecutor(1) as pool:
                    fut=pool.submit(execute,two,'SELECT outbound_send(%s,%s)',(f['out'],f['emp']))
                    await_lock(pid);one.commit()
                    try:fut.result(timeout=8)
                    except psycopg2.Error as e:require(e.pgcode=='P0001' and 'hold_until_paid' in str(e))
                    else:raise AssertionError('send passed a committed reversal after waiting')
                two.rollback()
                return {'send_waited_for_reversal':True,'rechecked_after_commit':True,'send_rejected':True}
            finally:one.close();two.close()
        check(3,'two-connection reversal versus outbound_send race',reversal_race)
        def double_send():
            execute(c,'DELETE FROM receipt_reversal WHERE allocation_id=%s',(a,));c.commit()
            one,two=connection(),connection()
            try:
                execute(one,'SELECT outbound_send(%s,%s)',(f['out'],f['emp']))
                pid=scalar(two,'SELECT pg_backend_pid()')
                with concurrent.futures.ThreadPoolExecutor(1) as pool:
                    fut=pool.submit(execute,two,'SELECT outbound_send(%s,%s)',(f['out'],f['emp']))
                    await_lock(pid);one.commit()
                    try:fut.result(timeout=8)
                    except psycopg2.Error as e:require(e.pgcode=='P0001' and 'already verified' in str(e))
                    else:raise AssertionError('second send gate transition accepted')
                two.rollback()
                return {'successful_gate_transitions':1,'duplicate_blocked':1,'actual_sends':0}
            finally:one.close();two.close()
        check(3,'two-connection double send verifies exactly once',double_send)
    finally:
        c.rollback()
        for sql,args in [
            ('DELETE FROM outbound_attachment WHERE outbound_id=%s',(f['out'],)),
            ('DELETE FROM outbound_message WHERE id=%s',(f['out'],)),
            ('DELETE FROM switchboard_intake WHERE id=%s',(f['intake'],)),
            ('DELETE FROM receipt_reversal WHERE allocation_id=%s',(a,)),
            ('DELETE FROM receipt_allocation WHERE id=%s',(a,)),
            ('DELETE FROM deliverable_release_gate WHERE id=%s',(f['gate'],)),
            ('DELETE FROM deliverable_version WHERE id=%s',(f['dv'],)),
            ('DELETE FROM invoice WHERE id=%s',(f['invoice'],)),
            ('DELETE FROM "case" WHERE id=%s',(f['case'],)),
            ('DELETE FROM customer_contact WHERE id=%s',(f['contact'],)),
            ('DELETE FROM employee WHERE id=%s',(f['emp'],)),
            ('DELETE FROM customer WHERE id=%s',(f['cust'],)),
            ('DELETE FROM email_mailbox WHERE id IN (%s,%s)',(f['mb_yx'],f['mb_sj'])),
            ('ALTER TABLE serial_cutover_log DISABLE TRIGGER serial_cutover_log_append_only',()),
            ('DELETE FROM serial_cutover_log WHERE org_id=%s',(org,)),
            ('ALTER TABLE serial_cutover_log ENABLE TRIGGER serial_cutover_log_append_only',()),
            ('DELETE FROM org_marker WHERE org_code=%s',(org,)),
            ('DELETE FROM employee_role_map WHERE employee_id=%s',(org_emp,)),
            ('DELETE FROM employee WHERE id=%s',(org_emp,)),
            ('DELETE FROM serial_assignment WHERE org_id=%s',(org,)),
            ('DELETE FROM serial_allocator WHERE org_id=%s',(org,)),
            ('DELETE FROM org WHERE id=%s',(org,))]:execute(c,sql,args)
        c.commit();c.close()

def schema_hash(dsn,schemas=None):
    cmd=['pg_dump','--dbname',dsn,'--schema-only','--no-owner','--no-privileges']
    for schema in schemas or []:cmd.extend(['--schema',schema])
    r=subprocess.run(cmd,capture_output=True,text=True,check=True)
    # pg_dump 17 adds a random restrict token on each invocation.
    clean='\n'.join(x for x in r.stdout.splitlines() if not x.startswith(('\\restrict','\\unrestrict','-- Dumped')))
    return hashlib.sha256(clean.encode()).hexdigest()

def data_hash(c):
    tabs=execute(c,"SELECT tablename FROM pg_tables WHERE schemaname='public' AND (tablename LIKE 'email_%%' OR tablename LIKE 'otp_%%' OR tablename IN ('serial_allocator','serial_assignment','satellite_sent_copy','org','receipt_allocation','receipt_reversal','payment_instrument','deliverable_release_gate','outbound_message','client_communication')) ORDER BY tablename")
    return {t:scalar(c,'SELECT md5(coalesce(string_agg(j,\'\' ORDER BY j),\'\')) FROM (SELECT to_jsonb(t)::text AS j FROM public.'+t+' t) s') for (t,) in tabs}

def migrations(dsn):
    c=psycopg2.connect(dsn)
    current_db=scalar(c,'SELECT current_database()')
    assert current_db != 'yongxiang_plumb', f"FATAL: Test script forbidden from connecting to production DB yongxiang_plumb (got {current_db})"
    before_dim_fact=schema_hash(dsn,['dim','fact'])
    def apply(n):
        r=subprocess.run(['psql','-X','-v','ON_ERROR_STOP=1','--dbname',dsn,'-f',str(SQL)],capture_output=True,text=True)
        (OUT/f'migration_run{n}.log').write_text(r.stdout+r.stderr)
        require(r.returncode==0,f'migration {n} failed; see migration_run{n}.log')
        # Preserve the deployed convergence + R40 + shared guard overlays when rechecking the older R29 DDL.
        for ov_name in ('009_r31b_convergence.sql','009_r32_12_audit_fixes.sql','009b_r32_fixpack.sql','009c_r32_fixpack.sql','009d_r32_fixpack.sql','009d2_r40_fixpack.sql','010_guard_constants.sql'):
            overlay=SQL.parent/ov_name
            if overlay.exists():
                env_ov=dict(os.environ)
                if ov_name=='009d2_r40_fixpack.sql':
                    sha=hashlib.sha256(overlay.read_bytes()).hexdigest()
                    env_ov['PGOPTIONS']=f'-c app.migration_sha={sha}'
                r=subprocess.run(['psql','-X','-v','ON_ERROR_STOP=1','--dbname',dsn,'-f',str(overlay)],capture_output=True,text=True,env=env_ov)
                require(r.returncode==0,f'{ov_name} overlay failed: '+r.stderr[-500:])
    apply(1);s1=schema_hash(dsn);d1=data_hash(c);c.commit()
    apply(2);s2=schema_hash(dsn);d2=data_hash(c);c.commit()
    require(s1==s2,'schema changed on second migration')
    require(d1==d2,'R29 persistent data changed on second migration')
    require(before_dim_fact==schema_hash(dsn,['dim','fact']),'dim/fact schema changed')
    c.close()
    return {'applications':2,'schema_identical':True,'data_identical':True,'schema_sha256':s2,'dim_fact_unchanged':True}

def tlc():
    jar=Path(os.environ.get('TLA2TOOLS_JAR',str(Path.home()/'.local/share/tla2tools.jar')))
    require(jar.exists(),'TLC jar unavailable')
    cfg=Path('/workspace/pstack_verify/R29Verification.cfg')
    cmd=['java','-XX:+UseParallelGC','-Xmx1g','-cp',str(jar),'tlc2.TLC','-workers','2','-config',str(cfg),'-metadir',str(OUT/'tlc_states'),'R29Verification.tla']
    with (OUT/'tlc.log').open('w') as log:
        r=subprocess.run(cmd,cwd=cfg.parent,stdout=log,stderr=subprocess.STDOUT,timeout=180)
    text=(OUT/'tlc.log').read_text()
    require(r.returncode==0 and 'No error has been found' in text,'TLC failed; see tlc.log')
    m=re.search(r'([\d,]+) states generated, ([\d,]+) distinct states found',text)
    return {'engine':'TLC','exhaustive':True,'states_generated':int(m[1].replace(',','')) if m else None,'distinct_states':int(m[2].replace(',','')) if m else None,'invariants_checked':6,'violations':0,'source':'/workspace/pstack_verify/EmailSwitchboardHarmony.tla','source_sha256':hashlib.sha256(Path('/workspace/pstack_verify/EmailSwitchboardHarmony.tla').read_bytes()).hexdigest(),'config':str(cfg),'scope':'finite safety model: one message/fingerprint/case, both orgs, all five message kinds; authenticated OTP sender fixed; all enabled interleavings; payment reversal and all six SQL guards verified separately against PostgreSQL; no unbounded or liveness claim'}

def windows_probe():
    host=os.environ.get('R29_WINDOWS_HOST','LAPTOP-K8QN14GV'); result={'host':host,'database':'yongxiang_unified_r23','required_if_reachable':True,'attempts':[]}
    for port in [5432,22]:
        try:
            with socket.create_connection((host,port),3): pass
            result['attempts'].append({'port':port,'reachable':True})
        except OSError as e: result['attempts'].append({'port':port,'reachable':False,'error':str(e)})
    result['status']='reachable_requires_connection' if any(x['reachable'] for x in result['attempts']) else 'skipped_unreachable'
    return result

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dsn',default=os.environ.get('PG_DSN','dbname=yongxiang_plumb_r39_clone'));ap.add_argument('--skip-migration',action='store_true');ap.add_argument('--skip-model',action='store_true')
    ap.add_argument('--local-only',action='store_true',help='No laptop probe or remote database; local dry-run only')
    ap.add_argument('--output',type=Path,help='JSON evidence path; defaults to formal/r29/result.json')
    args=ap.parse_args();OUT.mkdir(parents=True,exist_ok=True)
    with psycopg2.connect(args.dsn) as _gconn:
        current_db=scalar(_gconn,'SELECT current_database()')
        assert current_db != 'yongxiang_plumb', f"FATAL: Test script forbidden from connecting to production DB yongxiang_plumb (got {current_db})" 
    if not args.skip_migration:check('migration','apply migration twice with schema/data hashes',lambda:migrations(args.dsn))
    try:
        c=psycopg2.connect(args.dsn)
        suite(c);c.close()
        concurrent_checks(args.dsn)
    except Exception as e:check('infrastructure','database fixtures and cleanup',lambda:(_ for _ in ()).throw(e))
    if not args.skip_model:check('model','TLC exhaustive finite safety check of EmailSwitchboardHarmony',tlc)
    windows={'status':'not_requested','note':'portable SQL only; laptop database not accessed'} if args.local_only else windows_probe()
    win_dsn=None if args.local_only else os.environ.get('R29_WINDOWS_DSN')
    if win_dsn:
        check('windows','Windows PostgreSQL migration and guards',lambda:verify_windows(win_dsn))
        windows['status']='verified' if checks[-1]['passed'] else 'failed'
    elif windows['status'] not in ('skipped_unreachable','not_requested'):
        check('windows','reachable Windows needs database connection',lambda:require(False,'Set R29_WINDOWS_DSN to the reachable mirror connection'))
    failed=sum(not x['passed'] for x in checks)
    report={'suite':'Fable 5.1 R29 + R29-PSTACK 6 Structural Guards','verified_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'passed':failed==0,'failed_count':failed,'guards_verified':sum(all(x['passed'] for x in checks if x['guard']==i) and any(x['guard']==i for x in checks) for i in range(1,7)),'checks_count':len(checks),'checks':checks,'box':{'database':current_db,'status':'verified' if failed==0 else 'failed'},'windows':windows,'migration_sha256':hashlib.sha256(SQL.read_bytes()).hexdigest(),'external_messages':0,'group_broadcasts':0,'scope_notes':['All email/OTP evidence is synthetic; live Gmail IMAP ingestion and real messaging transport are not tested.','outbound_send and otp_deliver record dry-run verification/outbox evidence; existing zero-send CHECK constraints remain enforced.','TLC proves only its documented finite safety configuration; SQL and race tests exercise the six database guards.']}
    (args.output or OUT/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ['passed','failed_count','guards_verified','checks_count']}),flush=True)
    return int(failed>0)

def verify_windows(dsn):
    migrations(dsn)
    c=psycopg2.connect(dsn)
    try:suite(c)
    finally:c.close()
    concurrent_checks(dsn)
    require(all(x['passed'] for x in checks),'Windows guards failed')
    return {'database':'yongxiang_unified_r23','verified':True}

if __name__=='__main__':sys.exit(main())
