import concurrent.futures,hashlib,json,uuid
from decimal import Decimal
from pathlib import Path
import psycopg
import pytest
from psycopg.types.json import Jsonb
from fastapi.testclient import TestClient
from api import create_app,ROLE_COLUMNS
from card_renderers import lark,plumb
import switchboard_engine as E
from conftest import arm_org
from contextlib import contextmanager
from threading import RLock
from types import SimpleNamespace


def uid():return uuid.uuid4()
def scalar(c,sql,args=()):return c.execute(sql,args).fetchone()[0]
def reject(c,sql,args=()):
    c.execute('SAVEPOINT neg')
    try:
        c.execute(sql,args)
    except psycopg.Error as exc:
        c.execute('ROLLBACK TO SAVEPOINT neg')
        return exc
    else: raise AssertionError('unsafe SQL was accepted')
    finally:c.execute('RELEASE SAVEPOINT neg')

def fixture(c):
    f={k:uid() for k in ('emp','other','cust','case','invoice','intake','out')}
    c.execute("INSERT INTO customer(id,org_id,name) VALUES(%s,'YX','R31B synthetic customer')",(f['cust'],))
    for key in ('emp','other'):
        c.execute("INSERT INTO employee(id,org_id,full_name,identity_confirmed,department_name,work_phone) VALUES(%s,'YX',%s,true,'財務','[MASKED_PHONE]')",(f[key],f'R31B test {key}'))
    c.execute('INSERT INTO "case"(id,org_id,case_code,title,status,customer_id,pm_employee_id) VALUES(%s,\'YX\',\'C\'||lpad((random()*999999)::int::text,6,\'0\')||\'-\'||upper(substr(md5(random()::text),1,3)),\'R31B synthetic case\',\'completed\',%s,%s)',(f['case'],f['cust'],f['emp']))
    c.execute("INSERT INTO invoice(id,org_id,case_id,customer_id,subtotal_amount,tax_amount,amount_due) VALUES(%s,'YX',%s,%s,850000,0,850000)",(f['invoice'],f['case'],f['cust']))
    c.execute("INSERT INTO switchboard_intake(id,source_key,serial_no,channel,occurred_at,evidence_kind,payload) VALUES(%s,%s,%s,'staff_request',now(),'synthetic_test','{}')",(f['intake'],str(f['intake']),int(f['intake'].int%1000000000000)+2000000000000))
    c.execute("INSERT INTO outbound_message(id,intake_id,case_id,draft_body,gate_results,action_card) VALUES(%s,%s,%s,'成果如附件','{}','{}')",(f['out'],f['intake'],f['case']))
    return f

def card(c,f,kind='confirm',cc=None):
    arm_org(c)
    # R40-6: named parameters only (8-arg signature; positional #6 is now p_evidence).
    # Non-case kinds must bring caller evidence; we bind the registered case evidence explicitly.
    return scalar(c,"SELECT enqueue_card(p_org=>'YX',p_case=>%s,p_assignee=>%s,p_kind=>%s,p_key=>%s,"
                    "p_evidence=>CASE WHEN %s IN ('case','review','settlement') THEN NULL ELSE card_evidence(%s) END,"
                    "p_proposed=>%s,p_cc=>%s)",
                  (f['case'],f['emp'],kind,'r31b:'+str(uid()),kind,f['case'],Jsonb({'quantity':200,'due_date':'10/31'}),cc))

def test_single_card_and_notification_copy(conn):
    f=fixture(conn);key='r31b:'+str(uid());args=(f['case'],f['emp'],key,f['other'])
    sql="SELECT enqueue_card(p_org=>'YX',p_case=>%s,p_assignee=>%s,p_kind=>'review',p_key=>%s,p_evidence=>NULL,p_proposed=>'{}',p_cc=>%s)"
    first=scalar(conn,sql,args);assert scalar(conn,sql,args)==first
    assert scalar(conn,'SELECT count(*) FROM card WHERE idempotency_key=%s',(key,))==1
    assert scalar(conn,"SELECT count(*) FROM notification_outbox WHERE dedupe_key=%s",('copy:'+str(first)+':'+str(f['other']),))==1
    assert reject(conn,"UPDATE card SET assignee_employee_id=NULL WHERE id=%s",(first,))
    assert reject(conn,sql,(f['case'],f['other'],key,f['emp'])).sqlstate=='23505'

def test_enqueue_card_six_positional_args_fails(conn):
    # R40-6: the old call shape (6th positional = proposed payload) must not silently work;
    # it lands in p_evidence and card_guard rejects it.
    f=fixture(conn)
    exc=reject(conn,"SELECT enqueue_card('YX',%s,%s,'confirm',%s,%s)",(f['case'],f['emp'],'r31b:'+str(uid()),Jsonb({'quantity':200,'due_date':'10/31'})))
    assert exc is not None
    assert scalar(conn,"SELECT to_regprocedure('public.enqueue_card(text,uuid,uuid,text,text,jsonb,uuid)') IS NULL")

def test_followup_only_after_first_action(conn):
    f=fixture(conn);cid=card(conn,f)
    conn.execute("INSERT INTO card_transition VALUES(%s,%s,'return_work','return_work')",(cid,f['other']))
    assert scalar(conn,"SELECT count(*) FROM card WHERE idempotency_key LIKE %s",('after:'+str(cid)+'%',))==0
    for key in ('lark','plumb'):
        scalar(conn,"SELECT card_act(p_id=>%s,p_actor=>%s,p_action=>'return_work',p_key=>%s)",(cid,f['emp'],key+str(cid)))
    assert scalar(conn,"SELECT count(*) FROM card WHERE idempotency_key=%s",('after:'+str(cid)+':return_work',))==1
    assert scalar(conn,"SELECT count(*) FROM audit_event WHERE table_name='card' AND record_id=%s",(str(cid),))==1

def test_sql_evidence_cannot_use_agent_numbers(conn):
    f=fixture(conn);cid=card(conn,f)
    assert 'evidence must bind evidence_sql' in str(reject(conn,'UPDATE card SET evidence_numbers=%s,evidence_sql_ids=ARRAY[\'fake\'] WHERE id=%s',(Jsonb([{'value':200}]),cid)))
    row=conn.execute('SELECT proposed_fields,evidence_numbers,evidence_sql_ids FROM card WHERE id=%s',(cid,)).fetchone()
    assert row[0]['quantity']==200
    assert len(row[1])==3 and all(e['sql_id'] in row[2] for e in row[1])
    assert row[1][0]['value']==0 and row[1][2]['value']==48

def test_gm_settlement_before_cash_and_cash_bonus_blocked(conn):
    f=fixture(conn)
    conn.execute("INSERT INTO case_settlement(case_id,status) VALUES(%s,'gm_signed')",(f['case'],))
    assert not scalar(conn,'SELECT paid FROM invoice_paid_v WHERE id=%s',(f['invoice'],))
    exc=reject(conn,"INSERT INTO hr_private.bonus_line(invoice_id,employee_id,points,amount_twd,idempotency_key) VALUES(%s,%s,10,100,%s)",(f['invoice'],f['emp'],str(uid())))
    assert 'fully paid' in str(exc)
    conn.execute('INSERT INTO receipt_allocation(invoice_id,amount,allocated_by) VALUES(%s,850000,%s)',(f['invoice'],f['emp']))
    conn.execute("INSERT INTO hr_private.bonus_line(invoice_id,employee_id,points,amount_twd,idempotency_key) VALUES(%s,%s,10,100,%s)",(f['invoice'],f['emp'],str(uid())))
    assert not scalar(conn,'SELECT case_closed(%s)',(f['case'],))
    conn.execute('UPDATE "case" SET retention_released=true WHERE id=%s',(f['case'],))
    assert scalar(conn,'SELECT case_closed(%s)',(f['case'],))
    assert scalar(conn,"SELECT count(*) FROM audit_event WHERE table_name='bonus_line'")==0
    assert not scalar(conn,"SELECT has_schema_privilege('sales_role','hr_private','USAGE')")
    assert not scalar(conn,"SELECT has_table_privilege('pm_sales_finance_role','hr_private.bonus_line','SELECT')")

@pytest.mark.parametrize('party',['client','us'])
def test_any_open_commitment_blocks_settlement(conn,party):
    f=fixture(conn)
    comm=scalar(conn,"INSERT INTO client_communication(direction,channel,occurred_at,customer_id,our_employee_id,serial_no,body_text,is_synthetic) VALUES('inbound','email',now(),%s,%s,4126789012345,'承諾測試',true) RETURNING id",(f['cust'],f['emp']))
    conn.execute("INSERT INTO client_commitment(source_comm_id,case_id,customer_id,party,kind,description,status,owner_employee_id) VALUES(%s,%s,%s,%s,'deadline','測試','stated',%s)",(comm,f['case'],f['cust'],party,f['emp']))
    assert 'commitments' in str(reject(conn,"INSERT INTO case_settlement(case_id,status) VALUES(%s,'gm_signed')",(f['case'],)))


def test_performed_provisional_blocks_settlement(conn):
    f=fixture(conn)
    item=scalar(conn,"INSERT INTO contract_item(case_id,item_code,item_name,item_status,unit,quantity,unit_price,performed_quantity) VALUES(%s,'SYN','synthetic','preliminary','m',200,10,1) RETURNING id",(f['case'],))
    assert 'provisional' in str(reject(conn,"INSERT INTO case_settlement(case_id,status) VALUES(%s,'gm_signed')",(f['case'],)))
    conn.execute("UPDATE contract_item SET item_status='formal' WHERE id=%s",(item,))
    conn.execute("INSERT INTO case_settlement(case_id,status) VALUES(%s,'gm_signed')",(f['case'],))

@pytest.mark.parametrize('fee',[30,100])
def test_finance_fee_recognition_unlocks_only_after_confirmation(conn,fee):
    f=fixture(conn)
    conn.execute("INSERT INTO deliverable_release_gate(case_id,milestone,deliverable_class,invoice_id) VALUES(%s,'FINAL','sealed',%s)",(f['case'],f['invoice']))
    allocation=scalar(conn,'INSERT INTO receipt_allocation(invoice_id,amount,allocated_by) VALUES(%s,%s,%s) RETURNING id',(f['invoice'],850000-fee,f['emp']))
    assert scalar(conn,'SELECT unpaid_amount FROM invoice_paid_v WHERE id=%s',(f['invoice'],))==fee
    assert not scalar(conn,"SELECT sealed_release_allowed(%s,'FINAL')",(f['case'],))
    conn.execute('INSERT INTO invoice_fee_adjustment(invoice_id,allocation_id,amount,confirmed_by,idempotency_key) VALUES(%s,%s,%s,%s,%s)',(f['invoice'],allocation,fee,f['emp'],str(uid())))
    assert scalar(conn,"SELECT sealed_release_allowed(%s,'FINAL')",(f['case'],))
    assert scalar(conn,'SELECT unpaid FROM canvas_v3_release_and_receipt WHERE invoice_id=%s',(f['invoice'],))==0
    conn.execute('INSERT INTO receipt_reversal(allocation_id,amount) VALUES(%s,1)',(allocation,))
    assert not scalar(conn,"SELECT sealed_release_allowed(%s,'FINAL')",(f['case'],))


def test_fee_over_tolerance_or_non_finance_denied(conn):
    f=fixture(conn);a=scalar(conn,'INSERT INTO receipt_allocation(invoice_id,amount,allocated_by) VALUES(%s,849899,%s) RETURNING id',(f['invoice'],f['emp']))
    assert reject(conn,'INSERT INTO invoice_fee_adjustment(invoice_id,allocation_id,amount,confirmed_by,idempotency_key) VALUES(%s,%s,101,%s,%s)',(f['invoice'],a,f['emp'],str(uid())))
    conn.execute("UPDATE employee SET department_name='外業' WHERE id=%s",(f['emp'],))
    assert 'finance' in str(reject(conn,'INSERT INTO invoice_fee_adjustment(invoice_id,allocation_id,amount,confirmed_by,idempotency_key) VALUES(%s,%s,100,%s,%s)',(f['invoice'],a,f['emp'],str(uid()))))


def test_case_constraint_uses_requested_pattern(conn):
    f=fixture(conn)
    for code in ['A000001','M999999','V126001','X126001-Z','Z999999-ABC']:
        conn.execute('INSERT INTO "case"(org_id,title,status,case_code) VALUES(\'YX\',\'R31B synthetic\',\'contracted\',%s)',(code,))
    for code in ['N126001','C126001-ABCD','C126001\n','C126001a']:
        assert reject(conn,'INSERT INTO "case"(org_id,title,status,case_code) VALUES(\'YX\',\'R31B synthetic\',\'contracted\',%s)',(code,))
    assert E.extract_case_code('C126001-ABCD 成果') is None


def test_serial_and_fingerprint_independently_unique(conn):
    f=fixture(conn)
    sql="INSERT INTO client_communication(direction,channel,occurred_at,customer_id,our_employee_id,body_text,org_id,serial_no,thread_fingerprint,is_synthetic) VALUES('inbound','email',now(),%s,%s,'測試','YX',%s,%s,true)"
    serial=int(uid().int%1000000000000)+3000000000000
    conn.execute(sql,(f['cust'],f['emp'],serial,'r31b-fp:'+str(serial)))
    assert reject(conn,sql,(f['cust'],f['emp'],serial,'r31b-diff:'+str(serial))).sqlstate=='23505'
    assert reject(conn,sql,(f['cust'],f['emp'],serial+1,'r31b-fp:'+str(serial))).sqlstate=='23505'


def test_alias_mapping_and_unknown_routes_to_admin(conn):
    f=fixture(conn);alias='R31B-'+str(uid())
    conn.execute('INSERT INTO employee_alias VALUES(\'YX\',%s,%s)',(alias,f['other']))
    mid=scalar(conn,"INSERT INTO email_message(message_id,from_addr,subject,body_new_text,dkim_pass,spf_pass,dkim_domain) VALUES(%s,'yongxiang.ltd@gmail.com','forward','給名字',true,true,'gmail.com') RETURNING id",('<'+str(uid())+'@r31b.test>',))
    cid=scalar(conn,'SELECT forward_register_card(%s,%s,%s)',(mid,alias,f['emp']))
    assert scalar(conn,'SELECT assignee_employee_id FROM card WHERE id=%s',(cid,))==f['other']
    unknown=scalar(conn,'SELECT forward_register_card(%s,%s,%s)',(mid,'unknown-'+alias,f['emp']))
    assert scalar(conn,'SELECT kind FROM card WHERE id=%s',(unknown,))=='admin'
    assert scalar(conn,'SELECT count(*) FROM backfill_quarantine WHERE payload->>\'message_id\'=%s',(str(mid),))==1
    assert reject(conn,'INSERT INTO employee_alias VALUES(\'YX\',%s,%s)',(alias,f['emp'])).sqlstate=='23505'


def test_sent_copy_verification_remains_database_gate(conn):
    f=fixture(conn)
    for sent in (False,True):
        mid='<'+str(uid())+'@r31b.test>'
        mail=scalar(conn,"INSERT INTO email_message(message_id,from_addr,subject,body_new_text,sent_copy_verified,dkim_pass,spf_pass,dkim_domain) VALUES(%s,'yonginside@gmail.com','測試','您好',%s,true,true,'gmail.com') RETURNING id",(mid,sent))
        mailbox=scalar(conn,"SELECT id FROM email_mailbox WHERE address='yonginside@gmail.com'")
        conn.execute("INSERT INTO satellite_sent_copy(mailbox_id,message_id,imap_folder,uidvalidity,imap_uid) VALUES(%s,%s,'Sent',1,1)",(mailbox,mid))
        sql="INSERT INTO email_switchboard_command(source_message_id,requester_employee_id,instruction_block,body_after_strip) VALUES(%s,%s,'請寄給業主','您好')"
        if sent:conn.execute(sql,(mail,f['emp']))
        else: assert 'authenticated satellite' in str(reject(conn,sql,(mail,f['emp'])))


def test_template_pm_is_authoritative_and_version_pinned(conn):
    f=fixture(conn)
    params=Jsonb({'contact_title':'王先生','project_title':'測試工程','quote_no':'126001','pm_name':'FAKE','pm_phone':'FAKE'})
    conn.execute("SELECT pin_template_draft(%s,'quote_return_reply',%s)",(f['out'],params))
    row=conn.execute('SELECT template_version,template_params,draft_body FROM outbound_message WHERE id=%s',(f['out'],)).fetchone()
    assert row[0]==2 and row[1]['pm_name']=='R31B test emp' and 'FAKE' not in row[2]
    conn.execute('UPDATE outbound_message SET case_id=NULL WHERE id=%s',(f['out'],))
    assert 'select an active' in str(reject(conn,"SELECT pin_template_draft(%s,'quote_return_reply',%s)",(f['out'],params)))
    conn.execute("SELECT pin_template_draft(%s,'quote_return_reply',%s,%s)",(f['out'],params,f['other']))
    assert scalar(conn,'SELECT template_params->>\'pm_name\' FROM outbound_message WHERE id=%s',(f['out'],))=='R31B test other'


def test_sales_sql_privilege(conn):
    assert not scalar(conn,"SELECT has_column_privilege('sales_role','public.work_item_policy','standard_cost_price','SELECT')")
    assert scalar(conn,"SELECT has_column_privilege('sales_role','public.work_item_policy','floor_price','SELECT')")
    conn.execute('SET LOCAL ROLE sales_role')
    conn.execute('SELECT floor_price FROM work_item_policy LIMIT 1')
    assert reject(conn,'SELECT standard_cost_price FROM work_item_policy LIMIT 1').sqlstate=='42501'
    assert reject(conn,'SELECT * FROM hr_private.bonus_line LIMIT 1').sqlstate=='42501'


@pytest.fixture
def api_fixture(conn, monkeypatch):
    # The API workers use this transaction too: no committed setup or cleanup.
    f=fixture(conn);f['card']=card(conn,f);f['race_card']=card(conn,f)
    tokens={role:'r31b-'+str(uid()) for role in ('sales','pm','vp','other')}
    for role,token in tokens.items():
        conn.execute("INSERT INTO api_session VALUES(%s,%s,'YX',%s,now()+interval '1 hour')",(hashlib.sha256(token.encode()).hexdigest(),f['other'] if role=='other' else f['emp'],'sales' if role=='other' else role))
    f['policy']=scalar(conn,"INSERT INTO work_item_policy(org_id,name,floor_price,standard_cost_price,traffic_light) VALUES('YX','R31B synthetic policy',100,80,'green') RETURNING id")
    lock = RLock()

    @contextmanager
    def api_connect(database, **kwargs):
        # Serialize transaction contexts so concurrent HTTP requests cannot interleave
        # savepoints. All SQL, auth, renderers and action handlers remain real.
        with lock:
            previous = conn.row_factory
            conn.row_factory = kwargs.get('row_factory', psycopg.rows.tuple_row)
            try:
                with conn.transaction():
                    yield conn
            finally:
                conn.row_factory = previous

    import api
    monkeypatch.setattr(api, 'psycopg', SimpleNamespace(connect=api_connect, errors=psycopg.errors))
    yield f,tokens


def test_api_role_whitelist_and_no_spoofing(dsn,api_fixture):
    f,tokens=api_fixture;client=TestClient(create_app(dsn))
    assert client.get('/canvas/2').status_code==422
    assert client.get('/canvas/2',headers={'Authorization':'Bearer invalid'}).status_code==401
    for role in ('sales','pm','vp'):
        result=client.get('/canvas/2',headers={'Authorization':'Bearer '+tokens[role],'X-Role':'vp'})
        assert result.status_code==200
        for row in result.json():assert set(row)<=set(ROLE_COLUMNS[role])
        row=next(r for r in result.json() if r['id']==str(f['policy']))
        assert row['floor_price']==100
        assert ('standard_cost_price' in row)==(role!='sales')


def test_both_renderers_use_one_action_and_concurrent_exactly_once(dsn,api_fixture,conn):
    f,tokens=api_fixture;client=TestClient(create_app(dsn));headers={'Authorization':'Bearer '+tokens['sales']}
    data=client.get('/cards/'+str(f['card']),headers=headers).json()
    assert lark(data)['card']['action_url']==plumb(data)['card']['action_url']
    assert lark(data)['card']['proposed_fields_label']=='待確認'
    results=[]
    for channel in ('lark','plumb'):
        r=client.post('/cards/'+str(f['card'])+'/act',headers={**headers,'Idempotency-Key':channel+str(f['card']),'X-Channel':channel},json={'action':'confirm'})
        assert r.status_code==200,r.text
        results.append(r.json())
    assert results[0]==results[1]
    assert client.post('/cards/'+str(f['card'])+'/act',headers={**headers,'Idempotency-Key':'conflict'},json={'action':'reject'}).status_code==409
    assert client.post('/cards/'+str(f['card'])+'/act',headers={'Authorization':'Bearer '+tokens['other'],'Idempotency-Key':'wrong'},json={'action':'confirm'}).status_code==404
    def press(i):
        with TestClient(create_app(dsn)) as worker:
            r=worker.post('/cards/'+str(f['race_card'])+'/act',headers={**headers,'Idempotency-Key':'race'+str(f['race_card'])+str(i)},json={'action':'confirm'})
            assert r.status_code==200,r.text
            return r.json()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool: responses=list(pool.map(press,range(8)))
    assert all(x==responses[0] for x in responses)
    c=conn
    for cid in (f['card'],f['race_card']):
        assert scalar(c,"SELECT count(*) FROM audit_event WHERE table_name='card' AND record_id=%s",(str(cid),))==1
        assert scalar(c,'SELECT acted_at IS NOT NULL FROM card WHERE id=%s',(cid,))


def test_nested_canvas_whitelist_and_deployment_entry():
    from canvas_policy import project
    import inbox_canvas_api,api
    row={'case_id':'test','standard_cost_price':80,'unknown_secret':100,'quote_lines':[{'floor_price':100,'standard_cost_price':80,'salary':999,'points_to_salary_ratio':999,'traffic_light':'green'}]}
    sales=project(2,'sales',row);pm=project(2,'pm',row)
    assert sales['quote_lines']==[{'floor_price':100,'traffic_light':'green'}]
    assert pm['quote_lines'][0]['standard_cost_price']==80
    assert 'unknown_secret' not in pm
    assert inbox_canvas_api.app is api.app


def test_legacy_sql_action_signature_uses_same_idempotent_handler(conn):
    f=fixture(conn);cid=card(conn,f)
    conn.execute("SELECT * FROM card_act(%s,'confirm',%s,'sales','lark',%s,'{}')",(cid,f['emp'],'legacy-'+str(cid)))
    first=scalar(conn,'SELECT acted_at FROM card WHERE id=%s',(cid,))
    scalar(conn,"SELECT card_act(p_id=>%s,p_actor=>%s,p_action=>'confirm',p_key=>%s)",(cid,f['emp'],'plumb-'+str(cid)))
    assert scalar(conn,'SELECT acted_at FROM card WHERE id=%s',(cid,))==first
    assert scalar(conn,'SELECT state FROM card WHERE id=%s',(cid,))=='acted'
    assert scalar(conn,'SELECT count(*) FROM card_action_log WHERE card_id=%s',(cid,))==1
    assert scalar(conn,"SELECT count(*) FROM audit_event WHERE table_name='card' AND record_id=%s",(str(cid),))==1


def test_bank_fee_copy_is_pending_until_actual_sql_zero():
    assert E.sealed_release_message(30)=='待財務沖帳（差 NT$30，匯費容差內）'
    assert E.sealed_release_message(100)=='待財務沖帳（差 NT$100，匯費容差內）'
    assert E.sealed_release_message(0)=='已完成財務沖帳'
