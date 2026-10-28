import uuid
import psycopg
import pytest
from psycopg.types.json import Jsonb
from conftest import arm_org


def uid():
    return uuid.uuid4()


def scalar(c, sql, args=()):
    return c.execute(sql, args).fetchone()[0]


def reject(c, sql, args=()):
    c.execute("SAVEPOINT r32_neg")
    try:
        c.execute(sql, args)
    except psycopg.Error as exc:
        c.execute("ROLLBACK TO SAVEPOINT r32_neg")
        return exc
    else:
        raise AssertionError("unsafe SQL was accepted")
    finally:
        c.execute("RELEASE SAVEPOINT r32_neg")


def arm_org_live(c, org='YX'):
    """R41-6: card_promote_dry_run now requires the org to be LIVE-ready (tax_id + domain markers + a
    serial_cutover_log row). Arm it inside the test transaction only (rolled back by the conn fixture)."""
    c.execute("INSERT INTO org_marker(org_code,kind,value,verified_by) SELECT %s,'tax_id','pytest-'||%s||'-taxid','pytest' WHERE NOT EXISTS (SELECT 1 FROM org_marker WHERE org_code=%s AND kind='tax_id')", (org, org, org))
    c.execute("INSERT INTO org_marker(org_code,kind,value,verified_by) SELECT %s,'domain','pytest-'||lower(%s)||'.invalid','pytest' WHERE NOT EXISTS (SELECT 1 FROM org_marker WHERE org_code=%s AND kind='domain')", (org, org, org))
    if not scalar(c, "SELECT EXISTS (SELECT 1 FROM serial_cutover_log WHERE org_id=%s)", (org,)):
        scalar(c, "SELECT cutover_reconcile_serial(%s, (SELECT greatest(next_serial-1, 12105) FROM serial_allocator WHERE org_id=%s))", (org, org))


def test_r32_1_and_2_serial_allocator_shadow_and_cutover_reconcile(conn):
    # 1.1: No pg_advisory_xact_lock(1943,12084) in assign_serial; SECURITY DEFINER; next_serial > max(serial_no)
    fn_def = scalar(conn, "SELECT pg_get_functiondef('public.assign_serial(text,text,text)'::regprocedure)")
    assert "pg_advisory_xact_lock" not in fn_def
    assert "SECURITY DEFINER" in fn_def

    # 1.2: Dry-run allocates negative shadow serials (-12085, -12086...) without touching live next_serial
    live_before = scalar(conn, "SELECT next_serial FROM serial_allocator WHERE org_id='YX'")
    fp_dry_1 = "r32-dry-1:" + str(uid())
    fp_dry_2 = "r32-dry-2:" + str(uid())
    s1 = scalar(conn, "SELECT assign_serial('YX', %s, 'dry_run')", (fp_dry_1,))
    s2 = scalar(conn, "SELECT assign_serial('YX', %s, 'dry_run')", (fp_dry_2,))
    assert s1 <= -12085 and s2 == s1 - 1
    assert scalar(conn, "SELECT assign_serial('YX', %s, 'dry_run')", (fp_dry_1,)) == s1
    assert scalar(conn, "SELECT next_serial FROM serial_allocator WHERE org_id='YX'") == live_before

    # Cutover reconciliation advances next_serial to >= sheet_max + 1 and voids dry_run serials
    reconciled = scalar(conn, "SELECT cutover_reconcile_serial('YX', %s)", (max(live_before, 12105),))
    assert reconciled >= 12106
    assert scalar(conn, "SELECT voided_by_cutover FROM serial_assignment WHERE org_id='YX' AND fingerprint=%s", (fp_dry_1,)) is True

    # SW-SER-01 & SW-SER-02 assertions pass
    res = scalar(conn, "SELECT r32_assert_all()")
    assert res["SW-SER-01"] == "PASS" and res["SW-SER-02"] == "PASS"


def test_r32_3_card_promote_dry_run_skips_acted_and_prevents_duplicates(conn):
    emp = scalar(conn, "INSERT INTO employee(org_id,full_name,identity_confirmed,employment_status,department_name) VALUES('YX','R32 Emp',true,'active','工程') RETURNING id")
    cust = scalar(conn, "INSERT INTO customer(org_id,name) VALUES('YX','R32 Cust') RETURNING id")
    case_id = scalar(conn, "INSERT INTO \"case\"(org_id,case_code,title,status,customer_id,pm_employee_id) VALUES('YX','C980001','R32 Case','completed',%s,%s) RETURNING id", (cust, emp))

    ev_open = "YX:CAT-01:" + str(uid()) + ":v1"
    ev_acted = "YX:CAT-01:" + str(uid()) + ":v1"
    c_open = scalar(
        conn,
        "INSERT INTO card(org_id,case_id,assignee_employee_id,kind,idempotency_key,source_event_key,mode,status,state) VALUES('YX',%s,%s,'confirm',%s,%s,'dry_run','open','open') RETURNING id",
        (case_id, emp, "card:" + ev_open, ev_open),
    )
    c_acted = scalar(
        conn,
        "INSERT INTO card(org_id,case_id,assignee_employee_id,kind,idempotency_key,source_event_key,mode,status,state,acted_at,acted_by,action,action_key) VALUES('YX',%s,%s,'confirm',%s,%s,'dry_run','acted','acted',now(),%s,'confirm',%s) RETURNING id",
        (case_id, emp, "card:" + ev_acted, ev_acted, emp, "act:" + ev_acted),
    )

    arm_org_live(conn)
    promoted = scalar(conn, "SELECT card_promote_dry_run('YX')")
    assert promoted >= 1
    assert scalar(conn, "SELECT mode FROM card WHERE id=%s", (c_open,)) == "live"
    assert scalar(conn, "SELECT mode FROM card WHERE id=%s", (c_acted,)) == "dry_run"

    # Re-scanning same source_event_key in live mode cannot create a duplicate open live card
    assert reject(
        conn,
        "INSERT INTO card(org_id,case_id,assignee_employee_id,kind,idempotency_key,source_event_key,mode,status,state) VALUES('YX',%s,%s,'confirm',%s,%s,'live','open','open')",
        (case_id, emp, "card:dup:" + str(uid()), ev_open),
    ).sqlstate == "23505"


def test_r32_4_email_sent_copy_and_header_d_domain_verification(conn):
    emp = scalar(conn, "SELECT id FROM employee WHERE org_id='YX' AND full_name='羅薇' AND employment_status='active' AND identity_confirmed")
    mailbox = scalar(conn, "SELECT id FROM email_mailbox WHERE address='yonginside@gmail.com'")
    mid = "<" + str(uid()) + "@r32.test>"
    mail = scalar(
        conn,
        "INSERT INTO email_message(message_id,from_addr,subject,body_new_text,sent_copy_verified,dkim_pass,spf_pass,dkim_domain) VALUES(%s,'yonginside@gmail.com','R32 cmd','body',true,true,true,'gmail.com') RETURNING id",
        (mid,),
    )
    # Without email_sent_copy row, satcmd_guard rejects even when sent_copy_verified=true
    assert "authenticated satellite" in str(
        reject(
            conn,
            "INSERT INTO email_switchboard_command(source_message_id,requester_employee_id,instruction_block,body_after_strip) VALUES(%s,%s,'請寄出','body')",
            (mail, emp),
        )
    )
    # With mismatched header_d domain in email_sent_copy, satcmd_guard still rejects
    conn.execute("INSERT INTO email_sent_copy(message_id,mailbox_id,imap_uid,header_d) VALUES(%s,%s,99,'evil.example.com')", (mid, mailbox))
    conn.execute("INSERT INTO satellite_sent_copy(mailbox_id,message_id,imap_folder,uidvalidity,imap_uid,org_id,dkim_domain) VALUES(%s,%s,'Sent',1,99,'YX','evil.example.com')", (mailbox,mid))
    assert "authenticated satellite" in str(
        reject(
            conn,
            "INSERT INTO email_switchboard_command(source_message_id,requester_employee_id,instruction_block,body_after_strip) VALUES(%s,%s,'請寄出','body')",
            (mail, emp),
        )
    )
    # With matching header_d = gmail.com, satcmd_guard accepts
    conn.execute("UPDATE satellite_sent_copy SET dkim_domain='gmail.com' WHERE message_id=%s", (mid,))
    conn.execute("UPDATE email_sent_copy SET header_d='gmail.com' WHERE message_id=%s", (mid,))
    conn.execute(
        "INSERT INTO email_switchboard_command(source_message_id,requester_employee_id,instruction_block,body_after_strip) VALUES(%s,%s,'請寄出','body')",
        (mail, emp),
    )


def test_r32_5_payment_instrument_status_regression_auto_reverses(conn):
    emp = scalar(conn, "SELECT id FROM employee WHERE org_id='YX' AND full_name='羅薇' AND employment_status='active' AND identity_confirmed")
    cust = scalar(conn, "INSERT INTO customer(org_id,name) VALUES('YX','R32 Check Cust') RETURNING id")
    case_id = scalar(conn, "INSERT INTO \"case\"(org_id,case_code,title,status,customer_id,pm_employee_id) VALUES('YX','C980002','R32 Check Case','completed',%s,%s) RETURNING id", (cust, emp))
    inv_id = scalar(conn, "INSERT INTO invoice(org_id,case_id,customer_id,subtotal_amount,tax_amount,amount_due) VALUES('YX',%s,%s,100000,0,100000) RETURNING id", (case_id, cust))
    inst_id = scalar(conn, "INSERT INTO payment_instrument(org_id,instrument_type,status,amount) VALUES('YX','check','cleared',100000) RETURNING id")
    alloc_id = scalar(conn, "INSERT INTO receipt_allocation(invoice_id,instrument_id,amount,allocated_by) VALUES(%s,%s,100000,%s) RETURNING id", (inv_id, inst_id, emp))

    assert scalar(conn, "SELECT paid FROM invoice_paid_v WHERE id=%s", (inv_id,)) is True
    # Regressing check status from 'cleared' to 'bounced' auto-inserts a receipt_reversal
    conn.execute("UPDATE payment_instrument SET status='bounced' WHERE id=%s", (inst_id,))
    assert scalar(conn, "SELECT count(*) FROM receipt_reversal WHERE allocation_id=%s", (alloc_id,)) == 1
    assert scalar(conn, "SELECT paid FROM invoice_paid_v WHERE id=%s", (inv_id,)) is False


def test_r32_6_to_12_structural_fixes(conn):
    emp1 = scalar(conn, "INSERT INTO employee(org_id,full_name,identity_confirmed,employment_status,department_name) VALUES('YX','R32 Emp1',true,'active','財務') RETURNING id")
    emp2 = scalar(conn, "INSERT INTO employee(org_id,full_name,identity_confirmed,employment_status,department_name) VALUES('YX','R32 Emp2',true,'active','測量') RETURNING id")
    cust = scalar(conn, "INSERT INTO customer(org_id,name,invoice_rules) VALUES('YX','R32 Tol Cust',%s) RETURNING id", (Jsonb({"short_pay_tolerance": 30}),))
    case_id = scalar(conn, "INSERT INTO \"case\"(org_id,case_code,title,status,customer_id,pm_employee_id) VALUES('YX','C980003','R32 Struct Case','completed',%s,%s) RETURNING id", (cust, emp1))

    # Fix #6: subcontractor commitment does NOT block client settlement
    comm = scalar(conn, "INSERT INTO client_communication(direction,channel,occurred_at,customer_id,our_employee_id,serial_no,body_text,is_synthetic) VALUES('outbound','email',now(),%s,%s,499999901,'下包',true) RETURNING id", (cust, emp1))
    conn.execute(
        "INSERT INTO client_commitment(source_comm_id,case_id,customer_id,party,kind,description,status,owner_employee_id) VALUES(%s,%s,%s,'subcontractor','deadline','下包交期','stated',%s)",
        (comm, case_id, cust, emp1),
    )
    conn.execute("INSERT INTO case_settlement(case_id,status) VALUES(%s,'gm_signed')", (case_id,))

    # Fix #7: email_rag_chunk quarantines NULL category at runtime without NotNullViolation (ACT-R37-06 / ACT-R38-01)
    conn.execute("INSERT INTO email_rag_chunk(org_id,category,chunk_no,chunk_text,content_hash) VALUES('YX',NULL,1,'null-cat','h1-r38-quarantine')")
    assert scalar(conn, "SELECT count(*) FROM email_rag_chunk WHERE content_hash='h1-r38-quarantine'") == 0
    assert scalar(conn, "SELECT count(*) FROM email_rag_chunk_quarantine WHERE content_hash='h1-r38-quarantine'") == 1

    # Fix #8: otp_deliver fails closed and emits an 'admin' conflict card when >1 pending requests exist within 5m
    rule_id = scalar(conn, "INSERT INTO otp_forward_rule(account_label,sender_exact,subject_regex,code_regex,org_id) VALUES('R32 Shared e-GNSS','r32-shared@nlsc.gov.tw','驗證碼','[0-9]{6}','YX') RETURNING id")
    conn.execute("INSERT INTO otp_request(rule_id,requester_employee_id,org_id,requested_at) VALUES(%s,%s,'YX',clock_timestamp()-interval '20 seconds')", (rule_id, emp1))
    conn.execute("INSERT INTO otp_request(rule_id,requester_employee_id,org_id,requested_at) VALUES(%s,%s,'YX',clock_timestamp()-interval '10 seconds')", (rule_id, emp2))
    otp_mid = scalar(
        conn,
        "INSERT INTO email_message(message_id,mailbox_id,from_addr,subject,body_new_text,category,org_id,dkim_pass,spf_pass,dkim_domain,sent_at) VALUES(%s,(SELECT id FROM email_mailbox WHERE org_id='YX' ORDER BY address LIMIT 1),'r32-shared@nlsc.gov.tw','e-GNSS 驗證碼','您的驗證碼 654321','CAT-10','YX',true,true,'nlsc.gov.tw',clock_timestamp()) RETURNING id",
        ("<" + str(uid()) + "@nlsc.gov.tw>",),
    )
    assert scalar(conn, "SELECT otp_deliver(%s)", (otp_mid,)) is None
    assert scalar(conn, "SELECT count(*) FROM card WHERE idempotency_key=%s AND kind='admin'", ("otp-conflict:" + str(otp_mid),)) == 1

    # Fix #10: inbound unlinked message carrying YX tax ID 28725008 with org_id='SJ' is quarantined non-destructively (org_id=NULL, quarantine_reason='R32-ORG-MARKER:...'), while outbound/communication is rejected
    q_mid = "<" + str(uid()) + "@r29.test>"
    q_row = conn.execute(
        "INSERT INTO email_message(message_id,from_addr,subject,body_new_text,org_id,case_id) VALUES(%s,'client@example.test','統編 28725008 報價','請提供詠翔測量報價','SJ',NULL) RETURNING org_id, quarantine_reason",
        (q_mid,),
    ).fetchone()
    # R40-4: while SJ markers are not armed, an unlinked mail without a known mailbox is quarantined
    # as ORG-MARKER-NOT-ARMED (org from mailbox only); once armed it is R32-ORG-MARKER:...
    assert q_row[0] is None and q_row[1] and (q_row[1].startswith("R32-ORG-MARKER:") or q_row[1] == "ORG-MARKER-NOT-ARMED")
    assert "R32-ORG-MARKER" in str(
        reject(
            conn,
            "INSERT INTO client_communication(direction,channel,occurred_at,customer_id,our_employee_id,serial_no,body_text,org_id,case_id) VALUES('outbound','email',now(),%s,%s,-999999,'統編 28725008 報價','SJ',NULL)",
            (cust, emp1),
        )
    )

    # Fix #11: customer short_pay_tolerance (NT$30) marks invoice paid and emits a finance card for the NT$30 diff
    inv_id = scalar(conn, "INSERT INTO invoice(org_id,case_id,customer_id,subtotal_amount,tax_amount,amount_due) VALUES('YX',%s,%s,50000,0,50000) RETURNING id", (case_id, cust))
    alloc_id = scalar(conn, "INSERT INTO receipt_allocation(invoice_id,amount,allocated_by) VALUES(%s,49970,%s) RETURNING id", (inv_id, emp1))
    assert scalar(conn, "SELECT paid FROM invoice_paid_v WHERE id=%s", (inv_id,)) is True
    assert scalar(conn, "SELECT unpaid_amount FROM invoice_paid_v WHERE id=%s", (inv_id,)) == 30
    assert scalar(conn, "SELECT count(*) FROM card WHERE idempotency_key=%s AND kind='finance'", (f"short-pay:{inv_id}:{alloc_id}",)) == 1


def test_r37_step4_009b_fixpack_and_200_stratified_backtest_gate(conn):
    arm_org(conn)
    # (1) assign_serial in dry_run refuses to overwrite an existing live serial
    fp_live = "r37-live-first:" + str(uid())
    s_live = scalar(conn, "SELECT assign_serial('YX', %s, 'live')", (fp_live,))
    assert s_live >= 12085
    assert "fingerprint already has live serial" in str(
        reject(conn, "SELECT assign_serial('YX', %s, 'dry_run')", (fp_live,))
    )

    # (2) cutover_reconcile_serial refuses if unvoided live serial > sheet_max exists
    assert "live serials beyond sheet_max exist" in str(
        reject(conn, "SELECT cutover_reconcile_serial('YX', 12084)")
    )

    # (3) card_promote_dry_run marks duplicate dry_run card as superseded_by_live when live card exists
    emp = scalar(conn, "INSERT INTO employee(org_id,full_name,identity_confirmed,employment_status,department_name) VALUES('YX','R37 Admin',true,'active','行政部') RETURNING id")
    cust = scalar(conn, "INSERT INTO customer(org_id,name) VALUES('YX','R37 Cust') RETURNING id")
    case_id = scalar(conn, "INSERT INTO \"case\"(org_id,case_code,title,status,customer_id,pm_employee_id) VALUES('YX','C980037','R37 Case','completed',%s,%s) RETURNING id", (cust, emp))
    ev_dup = "YX:CAT-02:" + str(uid()) + ":v1"
    # R43 INSERT derives mode from readiness; create the dry card before re-arming.
    conn.execute("DELETE FROM org_marker WHERE org_code='YX'")
    c_dry = scalar(
        conn,
        "INSERT INTO card(org_id,case_id,assignee_employee_id,kind,idempotency_key,source_event_key,mode,status,state) VALUES('YX',%s,%s,'confirm',%s,%s,'dry_run','open','dry_run') RETURNING id",
        (case_id, emp, "card:dry:" + ev_dup, ev_dup),
    )
    arm_org(conn)
    c_live = scalar(
        conn,
        "INSERT INTO card(org_id,case_id,assignee_employee_id,kind,idempotency_key,source_event_key,mode,status,state) VALUES('YX',%s,%s,'confirm',%s,%s,'live','open','open') RETURNING id",
        (case_id, emp, "card:live:" + ev_dup, ev_dup),
    )
    arm_org_live(conn)
    scalar(conn, "SELECT card_promote_dry_run('YX')")
    assert scalar(conn, "SELECT state FROM card WHERE id=%s", (c_dry,)) == "superseded_by_live"

    # (4) Bounced check -> cleared appends compensating negative reversal (no DELETE) and no double-counting in invoice_paid_v
    inv_id = scalar(conn, "INSERT INTO invoice(org_id,case_id,customer_id,subtotal_amount,tax_amount,amount_due) VALUES('YX',%s,%s,100,0,100) RETURNING id", (case_id, cust))
    inst_id = scalar(conn, "INSERT INTO payment_instrument(org_id,instrument_type,status,amount) VALUES('YX','check','cleared',100) RETURNING id")
    alloc_id = scalar(conn, "INSERT INTO receipt_allocation(invoice_id,instrument_id,amount,allocated_by) VALUES(%s,%s,100,%s) RETURNING id", (inv_id, inst_id, emp))
    conn.execute("UPDATE payment_instrument SET status='bounced' WHERE id=%s", (inst_id,))
    assert scalar(conn, "SELECT unpaid_amount FROM invoice_paid_v WHERE id=%s", (inv_id,)) == 100
    conn.execute("UPDATE payment_instrument SET status='cleared' WHERE id=%s", (inst_id,))
    assert scalar(conn, "SELECT count(*) FROM receipt_reversal WHERE allocation_id=%s", (alloc_id,)) == 2
    assert scalar(conn, "SELECT sum(amount) FROM receipt_reversal WHERE allocation_id=%s", (alloc_id,)) == 0
    assert scalar(conn, "SELECT unpaid_amount FROM invoice_paid_v WHERE id=%s", (inv_id,)) == 0

    # (5) Overtime stage skip (> OLD + 1) is blocked by guard_overtime_stage_before
    ot_id = scalar(conn, "INSERT INTO overtime_day(employee_id,work_date,day_type,approved_ot_hours,comp_mode,status,escalation_level) VALUES(%s,'2026-10-20','workday',2,'pay','pending',0) RETURNING id", (emp,))
    assert "stage skip forbidden" in str(
        reject(conn, "UPDATE overtime_day SET escalation_level=2 WHERE id=%s", (ot_id,))
    )

    # (6) R38 Step 5: synthetic 200 rows removed, backtest_gate & r32_assert_all() honestly return NOT_RUN before human double-blind labels
    assert scalar(conn, "SELECT count(*) FROM switchboard_gold_label WHERE message_id LIKE '<gold-%%'") == 0
    assert scalar(conn, "SELECT count(*) FROM switchboard_backtest_eval WHERE run_id = '00000000-0000-0000-0000-000000000370'::uuid") == 0
    assert reject(
        conn,
        "INSERT INTO switchboard_gold_label(sample_id,message_id,stratum,annotator_a_employee_id,annotator_b_employee_id,agreed) SELECT 'SYN-1','<gold-fake@yxsurvey.com.tw>','CAT-01',a.id,b.id,false FROM employee a CROSS JOIN employee b WHERE a.full_name='林瑩瑄' AND b.full_name='吳柏頤'",
    )
    bt_row = conn.execute("SELECT metric, pass, actual FROM backtest_gate(NULL::uuid)").fetchone()
    assert bt_row[0] == "BACKTEST-200" and bt_row[1] is False and bt_row[2].startswith("NOT_RUN")
    res = scalar(conn, "SELECT r32_assert_all()")
    for k in ("SW-SER-01", "SW-SER-02", "SW-CUT-01", "SW-HYG-01"):
        assert res[k] == "PASS"
    assert res["BACKTEST-200"] == "NOT_RUN"
    assert scalar(conn, "SELECT r43_active_role_count('YX','admin')") >= 2
    assert "SW-ORG-02" in str(reject(conn, "SELECT assign_serial('NO_SUCH_ORG', 'fp-1', 'live')"))


def test_fable_step4_four_golden_counterexamples_and_recall_suite(conn):
    """Fable 5.1 High Step 4: 4 golden counterexamples + zero-manual-labeling recall & 12,084 ledger reconciliation."""
    ce = scalar(conn, "SELECT public.step4_verify_golden_counterexamples()")
    assert ce["GOLDEN-CE-01_legacy_reply"] == "PASS"
    assert ce["GOLDEN-CE-02_spoofed_satellite_from"] == "PASS"
    assert ce["GOLDEN-CE-03_inbound_sj_taxid_quarantined"] == "PASS"
    assert ce["GOLDEN-CE-04_bounced_check_no_double_count"] == "PASS"

    step4 = scalar(conn, "SELECT public.step4_assert_all()")
    assert step4["STEP4-SER-01"] == "PASS"
    assert step4["STEP4-DKIM-02"] == "PASS"
    assert step4["STEP4-ORG-03"] == "PASS"
    assert step4["STEP4-SEC-04"] == "PASS"
    assert step4["STEP4-RECALL-06"]["status"] == "PASS"
    assert float(step4["STEP4-RECALL-06"]["overall_card_recall"]) >= 0.92
    assert int(step4["STEP4-RECALL-06"]["otp_leak_count"]) == 0
    assert int(step4["STEP4-RECALL-06"]["spoofed_internal_cmd_count"]) == 0
    assert int(step4["STEP4-RECALL-06"]["client_inbound_dropped_count"]) == 0
    assert step4["STEP4-LEDGER-07"]["status"] == "PASS"
    assert float(step4["STEP4-LEDGER-07"]["reconciliation_rate"]) >= 0.95
    assert int(step4["STEP4-LEDGER-07"]["total_ledger_rows"]) == 12084
    assert int(step4["STEP4-LEDGER-07"]["gap_count_2025_plus"]) == 0
