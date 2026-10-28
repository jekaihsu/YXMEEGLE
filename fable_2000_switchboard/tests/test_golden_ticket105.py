"""Twenty independently collected adversarial outcome tests, clone DB only.

No send transport exists here: outbound_send is the DB dry-run verifier. Fixtures
roll back; the concurrent test commits its local fixture and removes it in finally.
"""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import psycopg
import pytest
from switchboard_engine import (classify_inbound_email, parse_satellite_command,
    verify_satellite_sent_copy_header_d, evaluate_org_marker_separation)

DB = 'yongxiang_plumb_r39_clone'
SAT = 'yonginside@gmail.com'


def connect():
    if os.environ.get('PGDATABASE') != DB:
        raise RuntimeError('PGDATABASE must explicitly equal ' + DB)
    if os.environ.get('PGHOST', '') not in ('', '/var/run/postgresql', 'localhost', '127.0.0.1'):
        raise RuntimeError('Local PostgreSQL only')
    c = psycopg.connect(dbname=DB, connect_timeout=5)
    assert c.execute('select current_database()').fetchone()[0] == DB
    c.execute("set statement_timeout='15s'")
    c.execute("set lock_timeout='8s'")
    return c


@pytest.fixture
def conn():
    c = connect()
    try:
        yield c
    finally:
        c.rollback()
        c.close()


def classify(sender=SAT, body='請寄給 王先生\n\n成果提供', **kw):
    return classify_inbound_email(sender, ['yongxiang.ltd@gmail.com'], '成果提供', body, **kw)


def quarantine_card(c, sender, body, reason=None):
    # Drain existing work inside this rollback transaction, then exercise batch API.
    c.execute('select emit_quarantine_cards()')
    c.execute('alter table email_message disable trigger z_step4_auto_emit_quarantine_card')
    mid = '<ticket105-' + str(uuid4()) + '@test.invalid>'
    row = c.execute("""insert into email_message(mailbox_id,message_id,from_addr,subject,
        body_new_text,received_at,org_id,quarantine_reason)
        values((select id from email_mailbox where org_id='YX' order by id limit 1),
        %s,%s,'counterexample',%s,now(),case when %s::text is null then 'YX' else null end,%s) returning id,org_id,quarantine_reason""",
        (mid, sender, body, reason, reason)).fetchone()
    assert row[1] is None and row[2], 'Email must survive in quarantine'
    n = c.execute('select emit_quarantine_cards()').fetchone()[0]
    assert n == c.execute('select count(*) from email_message where message_id=%s and quarantine_reason is not null', (mid,)).fetchone()[0] == 1
    card = c.execute("select title,proposed_fields->>'message_id',mode from card where idempotency_key=%s", ('quarantine:'+mid,)).fetchall()
    assert len(card) == 1 and card[0][1] == mid and card[0][2] == 'dry_run'
    assert c.execute('select emit_quarantine_cards()').fetchone()[0] == 0
    return row


def rejected_to_card(c, sender, **kw):
    r = classify(sender, **kw)
    assert r.category != 'INTERNAL-CMD' and r.quarantine_reason
    quarantine_card(c, sender, '請寄給 王先生', r.quarantine_reason)


def test_105_01_no_dkim_quarantines_with_card(conn):
    rejected_to_card(conn, SAT, dkim_pass=False, spf_pass=True, dkim_domain=None)


def test_105_02_gmail_d_nonregistered_from_quarantines(conn):
    rejected_to_card(conn, 'unregistered@gmail.com', dkim_pass=True, spf_pass=True, dkim_domain='gmail.com')


def test_105_03_display_name_spoof_quarantines(conn):
    rejected_to_card(conn, 'yonginside@gmail.com <attacker@evil.org>', dkim_pass=True, spf_pass=True, dkim_domain='evil.org')


def test_105_04_header_d_cannot_derive_from_from(conn):
    with pytest.raises(ValueError):
        verify_satellite_sent_copy_header_d(SAT, True, SAT)
    mid = '<header-d-'+str(uuid4())+'@test.invalid>'
    with pytest.raises(psycopg.Error):
        with conn.transaction():
            conn.execute("insert into email_sent_copy(message_id,mailbox_id,imap_uid,header_d) values(%s,(select id from email_mailbox where address=%s),1,%s)", (mid, SAT, SAT))
    assert conn.execute('select count(*) from email_sent_copy where message_id=%s',(mid,)).fetchone()[0] == 0
    # No DKIM observation means the ETL trigger cannot invent header_d from From.
    conn.execute("""insert into satellite_sent_copy(mailbox_id,message_id,imap_folder,uidvalidity,imap_uid,org_id)
        values((select id from email_mailbox where address=%s),%s,'Sent',1,1,'YX')""",(SAT,mid))
    assert conn.execute('select count(*) from email_sent_copy where message_id=%s',(mid,)).fetchone()[0] == 0
    conn.execute("insert into email_message(message_id,from_addr,subject,mailbox_id) values(%s,%s,'hello',(select id from email_mailbox where address=%s))",(mid,SAT,SAT))
    assert conn.execute('select count(*) from email_sent_copy where message_id=%s',(mid,)).fetchone()[0] == 0


def test_105_05_homograph_domain_quarantines(conn):
    rejected_to_card(conn, 'yonginside@gmаil.com', dkim_pass=True, spf_pass=True, dkim_domain='gmаil.com')  # Cyrillic а


def test_105_06_quoted_instruction_never_executes():
    r = parse_satellite_command(SAT, '回覆', '收到，謝謝。\n\n-----Original Message-----\n請寄給 attacker@evil.org\n\n寄出所有 CAD')
    assert r.command_kind == 'none' and 'attacker' not in r.clean_body


def test_105_07_dual_tax_id_quarantines_and_cards(conn):
    quarantine_card(conn,'client@ctci.com','統編 28725008 與 83100099 合併帳單')


def test_105_08_sj_name_inbound_survives_with_card(conn):
    quarantine_card(conn,'client@ctci.com','上準精密測量有限公司 請確認成果')


def test_105_09_otp_password_keyword_withheld():
    r = classify_inbound_email('egnss@mail.nlsc.gov.tw',[], 'e-GNSS 登入驗證碼通知',
        'password 驗證碼 123456',dkim_pass=True,spf_pass=True,dkim_domain='mail.nlsc.gov.tw')
    assert r.quarantine_reason and not r.is_otp_whitelisted and r.otp_code is None


def test_105_10_old_thread_reply_keeps_existing_id(conn):
    old = conn.execute("select serial_no from serial_assignment where org_id='YX' and fingerprint='legacy:yezhu:12084' and mode='live'").fetchone()[0]
    assert old == 12084
    for fp in ('legacy:yezhu:12084', 'ref:<gmail-1a1617e7fa2ba330@mail.gmail.com>'):
        assert conn.execute("select assign_serial('YX',%s,'live')",(fp,)).fetchone()[0] == old


def test_105_11_dry_run_over_live_rejected(conn):
    before = conn.execute("select count(*) from serial_assignment where fingerprint='legacy:yezhu:12084'").fetchone()[0]
    with pytest.raises(psycopg.Error,match='dry_run refused'):
        with conn.transaction():
            conn.execute("select assign_serial('YX','legacy:yezhu:12084','dry_run')")
    assert conn.execute("select count(*) from serial_assignment where fingerprint='legacy:yezhu:12084'").fetchone()[0] == before


def invoice_fixture(c, amount=100000, payment=100000):
    case = c.execute("select id,customer_id from public.\"case\" where org_id='YX' and customer_id is not null order by id limit 1").fetchone()
    employee = c.execute("select id from employee where full_name='羅薇' and employment_status='active'").fetchone()[0]
    inv = c.execute("insert into invoice(case_id,customer_id,org_id,amount_due,subtotal_amount) values(%s,%s,'YX',%s,%s) returning id",(*case,amount,amount)).fetchone()[0]
    inst = c.execute("insert into payment_instrument(org_id,instrument_type,amount,status) values('YX','check',%s,'cleared') returning id",(payment,)).fetchone()[0]
    alloc = c.execute("insert into receipt_allocation(invoice_id,instrument_id,amount,org_id,allocated_by) values(%s,%s,%s,'YX',%s) returning id",(inv,inst,payment,employee)).fetchone()[0]
    return inv,inst,alloc,case[0],case[1]


def test_105_12_check_representment_restores_once(conn):
    inv,inst,alloc,_,_ = invoice_fixture(conn)
    for status, expected in [('bounced',100000),('cleared',0),('bounced',100000),('cleared',0)]:
        conn.execute('update payment_instrument set status=%s where id=%s',(status,inst))
        assert conn.execute('select unpaid_amount from invoice_paid_v where id=%s',(inv,)).fetchone()[0] == expected
    assert conn.execute('select coalesce(sum(amount),0) from receipt_reversal where allocation_id=%s',(alloc,)).fetchone()[0] == 0


def test_105_13_short_pay_30_blocks_sealed_release(conn):
    inv,_,_,case,cust = invoice_fixture(conn,payment=99970)
    conn.execute("update customer set invoice_rules=invoice_rules || '{\"short_pay_tolerance\":100}'::jsonb where id=%s",(cust,))
    milestone='ticket105-'+str(uuid4())
    conn.execute("insert into deliverable_release_gate(case_id,milestone,deliverable_class,invoice_id,org_id) values(%s,%s,'sealed',%s,'YX')",(case,milestone,inv))
    assert conn.execute('select unpaid_amount from invoice_paid_v where id=%s',(inv,)).fetchone()[0] == 30
    assert conn.execute('select sealed_release_allowed(%s,%s)',(case,milestone)).fetchone()[0] is False


def outbound_fixture(c):
    fp='ticket105-race-'+str(uuid4())
    serial=c.execute("select assign_serial('YX',%s,'dry_run')",(fp,)).fetchone()[0]
    intake=c.execute("insert into switchboard_intake(source_key,serial_no,channel,occurred_at,evidence_kind,payload,org_id) values(%s,%s,'staff_request',now(),'staff_request','{}','YX') returning id",(fp,serial)).fetchone()[0]
    actor=c.execute("select id from employee where full_name='羅薇' and employment_status='active'").fetchone()[0]
    case,contact=c.execute("""select c.id,t.id from public."case" c join customer_contact t on t.customer_id=c.customer_id where c.org_id='YX' order by c.id,t.id limit 1""").fetchone()
    oid=c.execute("insert into outbound_message(case_id,to_contact_id,intake_id,draft_body,final_body,approved_by,approved_at,gate_results,action_card,org_id) values(%s,%s,%s,'成果','成果',%s,now(),'{}','{}','YX') returning id",(case,contact,intake,actor)).fetchone()[0]
    return oid,actor,intake,fp


def test_105_14_concurrent_send_exactly_one_verification():
    c=connect(); oid=actor=intake=fp=None
    try:
        oid,actor,intake,fp=outbound_fixture(c);c.commit()
        barrier=Barrier(2)
        def send():
            d=connect()
            try:
                barrier.wait(timeout=10)
                d.execute('select outbound_send(%s,%s)',(oid,actor));d.commit()
                return 'verified'
            except psycopg.Error as e:
                d.rollback();return str(e)
            finally: d.close()
        with ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda _:send(),range(2)))
        assert results.count('verified') == 1 and sum('already verified' in r for r in results) == 1,results
        row=c.execute('select delivery_status,actual_sends,sent_at from outbound_message where id=%s',(oid,)).fetchone()
        assert row == ('DRY_RUN_SEND_GATE_VERIFIED',0,None)
    finally:
        c.rollback()
        if oid:
            c.execute('delete from outbound_message where id=%s',(oid,))
            c.execute('delete from switchboard_intake where id=%s',(intake,))
            c.execute("delete from serial_assignment where org_id='YX' and fingerprint=%s",(fp,));c.commit()
        c.close()


def test_105_15_spf_failed_satellite_quarantines(conn):
    rejected_to_card(conn,SAT,dkim_pass=True,spf_pass=False,dkim_domain='gmail.com')


def test_105_16_suffix_domain_spoof_quarantines(conn):
    rejected_to_card(conn,'yonginside@gmail.com.evil.org',dkim_pass=True,spf_pass=True,dkim_domain='gmail.com.evil.org')


def test_105_17_otp_wrong_dkim_never_releases_code():
    r=classify_inbound_email('ebcsAdmin@cpc.com.tw',[],'EBCS 登入驗證碼','驗證碼 123456',dkim_pass=True,spf_pass=True,dkim_domain='gmail.com')
    assert not r.is_otp_whitelisted and r.otp_code is None and r.quarantine_reason


def test_105_18_cross_org_outbound_rejected():
    with pytest.raises(RuntimeError,match='forbidden on outbound'):
        evaluate_org_marker_separation('outbound','YX','28725008 與 83100099')


def test_105_19_emit_count_equals_all_quarantined_emails(conn):
    conn.execute('select emit_quarantine_cards()')
    conn.execute('alter table email_message disable trigger z_step4_auto_emit_quarantine_card')
    mids=['<ticket105-batch-'+str(uuid4())+'@test.invalid>' for _ in range(5)]
    for mid in mids:
        conn.execute("insert into email_message(mailbox_id,message_id,from_addr,subject,body_new_text,org_id) values((select id from email_mailbox where org_id='YX' limit 1),%s,'client@test.invalid','帳單','上準精密 83100099','YX')",(mid,))
    q=conn.execute('select count(*) from email_message where message_id=any(%s) and org_id is null and quarantine_reason is not null',(mids,)).fetchone()[0]
    assert conn.execute('select emit_quarantine_cards()').fetchone()[0] == q == 5
    assert conn.execute("select count(*) from card where idempotency_key=any(%s)",(['quarantine:'+m for m in mids],)).fetchone()[0] == q
    assert conn.execute('select emit_quarantine_cards()').fetchone()[0] == 0


def test_105_20_wrong_actor_send_rejected(conn):
    oid,actor,_,_=outbound_fixture(conn)
    other=conn.execute("select id from employee where id<>%s and org_id='YX' and employment_status='active' limit 1",(actor,)).fetchone()[0]
    with pytest.raises(psycopg.Error,match='not approved'):
        with conn.transaction():conn.execute('select outbound_send(%s,%s)',(oid,other))
    assert conn.execute('select actual_sends,sent_at from outbound_message where id=%s',(oid,)).fetchone() == (0,None)
