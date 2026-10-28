"""009d4 behavior on the R43 clones; every write belongs to conn's rollback.

F1/F2 from /workspace/fable/r43/CODEX_FINDINGS.md are fixed in 009d4 and asserted as enforced:
empty app.env is fail-closed, and a synthetic write in the arming transaction is caught.
"""
from uuid import uuid4
from decimal import Decimal

import psycopg
import pytest

from conftest import arm_org


def scalar(conn, sql, args=()):
    return conn.execute(sql, args).fetchone()[0]


def refused(conn, sql, args=(), *, match):
    # A savepoint recovers from the server error without losing the test fixture.
    with pytest.raises(psycopg.Error, match=match) as error:
        with conn.transaction():
            conn.execute(sql, args)
    return error.value


def admin(conn, name=None):
    return scalar(conn, """SELECT id FROM employee WHERE org_id='YX'
        AND r43_has_role(id,ARRAY['admin']) AND (%s::text IS NULL OR full_name=%s)
        ORDER BY id LIMIT 1""", (name, name))


def review_card(conn, actor):
    case = scalar(conn, "SELECT id FROM \"case\" WHERE org_id='YX' AND status='active' LIMIT 1")
    return scalar(conn, "SELECT enqueue_card('YX',%s,%s,'review',%s,NULL)",
                  (case, actor, 'r43:' + str(uuid4())))


def quarantine_card(conn):
    conn.execute("DELETE FROM org_marker WHERE org_code='SJ'")
    message_id = '<r43-' + str(uuid4()) + '@invalid>'
    mail = scalar(conn, """INSERT INTO email_message(message_id,from_addr,subject)
        VALUES(%s,'stranger@unknown.invalid','r43 quarantine') RETURNING id""", (message_id,))
    scalar(conn, 'SELECT emit_quarantine_cards()')
    card, actor = conn.execute("""SELECT id,assignee_employee_id FROM card
        WHERE idempotency_key=%s""", ('quarantine:' + message_id,)).fetchone()
    return mail, card, actor


def test_live_gates_and_readiness_badges(conn):
    actor = admin(conn)
    conn.execute("DELETE FROM org_marker WHERE org_code='YX'")
    state = scalar(conn, "SELECT org_live_ready('YX')")
    assert {'admin', 'missing', 'badge'} <= state.keys()
    assert state['badge'] == 'YX 試運轉（缺：統編、網域、對帳）'
    refused(conn, "SELECT assign_serial('YX',%s,'live')", ('r43:' + str(uuid4()),), match='SW-ORG-02')
    card = review_card(conn, actor)
    assert scalar(conn, 'SELECT mode FROM card WHERE id=%s', (card,)) == 'dry_run'
    refused(conn, "SELECT card_act(%s,%s,'confirm','r43:dry-act')", (card, actor), match='dry_run card cannot be acted')
    outbound = scalar(conn, "SELECT id FROM outbound_message WHERE org_id='YX' LIMIT 1")
    refused(conn, 'SELECT outbound_send_live(%s,%s)', (outbound, actor), match='SW-ORG-02')
    arm_org(conn)
    assert scalar(conn, "SELECT org_live_ready('YX')->>'badge'") == 'YX 已上線'
    assert scalar(conn, "SELECT assign_serial('YX',%s,'live')", ('r43:' + str(uuid4()),)) >= 12085
    live = review_card(conn, actor)
    assert scalar(conn, 'SELECT mode FROM card WHERE id=%s', (live,)) == 'live'
    refused(conn, 'SELECT outbound_send_live(%s,%s)', (outbound, actor), match='real transport not enabled')
    conn.execute("DELETE FROM employee_role_map WHERE role_code='admin' AND employee_id IN (SELECT id FROM employee WHERE org_id='YX')")
    state = scalar(conn, "SELECT org_live_ready('YX')")
    assert not state['ready'] and '行政' in state['missing']


def test_prod_guard_and_empty_env_fail_closed(conn):
    assert scalar(conn, "SELECT r32_assert_all()->>'SW-ENV-01'") == 'PASS:clone'
    conn.execute("SET LOCAL app.env='prod'")
    refused(conn, """INSERT INTO \"case\"(org_id,title,status,case_code)
        VALUES('YX','r43 reserved','preliminary','TEST_R43')""", match='BLOCK-SYNTHETIC-ON-PROD')
    refused(conn, "INSERT INTO customer_contact(org_id,full_name) VALUES('YX','TEST_r43')", match='BLOCK-SYNTHETIC-ON-PROD')
    conn.execute("INSERT INTO \"case\"(org_id,title,status) VALUES('YX','synthetic aperture survey','preliminary')")
    conn.execute("INSERT INTO customer_contact(org_id,full_name) VALUES('YX','測試科技')")
    assert scalar(conn, "SELECT set_config('app.env',NULL,true)") == 'clone'
    conn.execute("SET LOCAL app.env=''")
    assert scalar(conn, "SELECT current_setting('app.env',true)") == ''
    refused(conn, 'SELECT r32_assert_all()', match='SW-ENV-01')
    # F1 fixed: empty app.env is treated as prod by the INSERT guard as well
    refused(conn, "INSERT INTO customer_contact(org_id,full_name,is_synthetic) VALUES('YX','r43 empty-env repro',true)",
            match='BLOCK-SYNTHETIC-ON-PROD')
    conn.execute('RESET app.env')
    assert scalar(conn, "SELECT current_setting('app.env',true)") == 'clone'


def test_dkim_requires_observed_domain_and_guard_order(conn):
    err = refused(conn, """INSERT INTO email_message(message_id,from_addr,dkim_pass,dkim_domain)
        VALUES(%s,'yonginside@gmail.com',true,NULL)""", ('<r43-' + str(uuid4()) + '@invalid>',),
        match='em_dkim_domain_observed_chk')
    assert err.diag.constraint_name == 'em_dkim_domain_observed_chk'
    assert scalar(conn, "SELECT to_regprocedure('public.email_message_default_dkim_domain()') IS NULL")
    assert scalar(conn, "SELECT r32_assert_all()->>'SW-DKIM-01'") == 'PASS'
    names = scalar(conn, """SELECT array_agg(tgname::text ORDER BY tgname) FROM pg_trigger
        WHERE tgrelid='outbound_message'::regclass AND NOT tgisinternal
          AND tgtype & 2 = 2 AND tgtype & 4 = 4""")
    assert names == ['a00_block_synthetic_on_prod', 'a_guard_0_live_gate', 'a_guard_1_outbound',
                     'a_guard_2_r32_org_marker', 'a_guard_3_no_leak']


def test_disposition_acl_actor_and_release_semantics(conn):
    assert not scalar(conn, "SELECT has_table_privilege('public','email_message_disposition','INSERT')")
    with conn.transaction():
        conn.execute('SET LOCAL ROLE sales_role')
        refused(conn, """INSERT INTO email_message_disposition(message_id,disposition)
            VALUES('<r43-direct@invalid>','reject')""", match='permission denied')
        conn.execute('RESET ROLE')
    arm_org(conn)
    mail, card, actor = quarantine_card(conn)
    outsider = scalar(conn, """SELECT id FROM employee WHERE org_id='YX' AND employment_status='active'
        AND identity_confirmed AND NOT r43_has_role(id,ARRAY['admin','pm','vp','gm','owner']) LIMIT 1""")
    conn.execute('UPDATE card SET assignee_employee_id=%s WHERE id=%s', (outsider, card))
    refused(conn, "SELECT quarantine_release(%s,%s,'reject')", (card, outsider), match='not admin or pm')
    conn.execute('UPDATE card SET assignee_employee_id=%s WHERE id=%s', (actor, card))
    refused(conn, "SELECT quarantine_release(%s,%s,'reject')", (card, outsider), match='not the active assignee')
    refused(conn, "SELECT quarantine_release(%s,%s,'assign_org','SJ')", (card, actor), match='not armed')
    refused(conn, "SELECT quarantine_release(%s,%s,'assign_org','NO_SUCH_ORG')", (card, actor), match='existing org')
    scalar(conn, "SELECT quarantine_release(%s,%s,'release_hold')", (card, actor))
    assert scalar(conn, 'SELECT still_quarantined FROM email_message_effective_v WHERE id=%s', (mail,))
    scalar(conn, "SELECT quarantine_release(%s,%s,'reject')", (card, actor))
    assert not scalar(conn, 'SELECT still_quarantined FROM email_message_effective_v WHERE id=%s', (mail,))
    assert scalar(conn, 'SELECT status FROM card WHERE id=%s', (card,)) == 'acted'


def test_quarantine_pm_handoff(conn):
    arm_org(conn)
    mail, card, actor = quarantine_card(conn)
    conn.execute("DELETE FROM employee_role_map WHERE role_code='pm' AND employee_id IN (SELECT id FROM employee WHERE org_id='YX')")
    refused(conn, "SELECT quarantine_release(%s,%s,'handoff_pm')", (card, actor), match='no active pm')
    pm = scalar(conn, "SELECT id FROM employee WHERE org_id='YX' AND full_name='吳柏頤'")
    conn.execute("""INSERT INTO employee_role_map(employee_id,role_code) VALUES(%s,'pm')
        ON CONFLICT(employee_id) DO UPDATE SET role_code='pm'""", (pm,))
    result = scalar(conn, "SELECT quarantine_release(%s,%s,'handoff_pm')", (card, actor))
    assert result['handoff_to'] == str(pm)
    assert conn.execute('SELECT assignee_employee_id,handoff_pending,handoff_role FROM card WHERE id=%s', (card,)).fetchone() == (pm, True, 'pm')
    assert scalar(conn, 'SELECT still_quarantined FROM email_message_effective_v WHERE id=%s', (mail,))


def test_commitment_adjustment_overlay_is_append_only(conn):
    commitment, original = conn.execute("""SELECT id,to_jsonb(c) FROM client_commitment c
        WHERE amount_twd IS NOT NULL LIMIT 1""").fetchone()
    actor = admin(conn)
    outsider = scalar(conn, "SELECT id FROM employee WHERE NOT r43_has_role(id,ARRAY['admin','pm','vp','gm','owner']) LIMIT 1")
    sql = """INSERT INTO commitment_adjustment(commitment_id,field,new_value,reason,approved_by)
        VALUES(%s,%s,%s,'r43 missed amount',%s) RETURNING id"""
    adjustment = scalar(conn, sql, (commitment, 'amount_twd', '4321.25', actor))
    assert Decimal(scalar(conn, 'SELECT old_value FROM commitment_adjustment WHERE id=%s', (adjustment,))) == Decimal(str(original['amount_twd']))
    refused(conn, sql, (commitment, 'amount_twd', '1', outsider), match='approver .* active admin or pm')
    refused(conn, sql, (commitment, 'due_date', 'not-a-date', actor), match='invalid input syntax')
    refused(conn, "UPDATE commitment_adjustment SET reason='edit' WHERE id=%s", (adjustment,), match='append-only')
    refused(conn, 'DELETE FROM commitment_adjustment WHERE id=%s', (adjustment,), match='append-only')
    assert scalar(conn, 'SELECT effective_amount_twd=4321.25 AND has_adjustment FROM client_commitment_effective_v WHERE id=%s', (commitment,))
    assert scalar(conn, 'SELECT to_jsonb(c) FROM client_commitment c WHERE id=%s', (commitment,)) == original


def test_serial_sign_flip_whitelist(conn):
    customer = scalar(conn, "SELECT id FROM customer WHERE org_id='YX' LIMIT 1")
    actor = admin(conn)
    sql = """INSERT INTO client_communication(org_id,customer_id,our_employee_id,direction,channel,
        occurred_at,body_text,serial_no,thread_fingerprint)
        VALUES('YX',%s,%s,'outbound','email',now(),'r43 sign flip',%s,%s) RETURNING id"""
    positive = scalar(conn, sql, (customer, actor, 18000, 'r43:negate'))
    negative = scalar(conn, sql, (customer, actor, -18001, 'r43:restore'))
    refused(conn, 'UPDATE client_communication SET serial_no=18002 WHERE id=%s', (positive,), match='append-only')
    refused(conn, 'UPDATE client_communication SET dry_run_negated_at=now() WHERE id=%s', (positive,), match='append-only')
    conn.execute('UPDATE client_communication SET serial_no=-serial_no,dry_run_negated_at=now() WHERE id=%s', (positive,))
    conn.execute('UPDATE client_communication SET serial_no=abs(serial_no) WHERE id=%s', (negative,))
    assert conn.execute('SELECT serial_no,dry_run_negated_at IS NOT NULL FROM client_communication WHERE id=%s', (positive,)).fetchone() == (-18000, True)
    assert conn.execute('SELECT serial_no,dry_run_negated_at FROM client_communication WHERE id=%s', (negative,)).fetchone() == (18001, None)
    source = scalar(conn, "SELECT prosrc FROM pg_proc WHERE oid='r39_dry_run_serial_repair()'::regprocedure")
    assert 'DISABLE TRIGGER' not in source.upper()


def test_guard_arming_audit_application_name(conn):
    armed = scalar(conn, 'SELECT prod_guard_arm()')
    assert scalar(conn, 'SELECT prod_guard_arm()') == armed
    refused(conn, "UPDATE prod_guard_state SET v='edit' WHERE k='synthetic_guard_armed_at'", match='append-only')
    refused(conn, "DELETE FROM prod_guard_state WHERE k='synthetic_guard_armed_at'", match='append-only')
    # F2 fixed (occurred_at >= armed_at): a synthetic write in the arming transaction is caught
    with pytest.raises(psycopg.Error, match='SW-HYG-02'):
        with conn.transaction():
            conn.execute("SET LOCAL application_name='psql'")
            conn.execute("""INSERT INTO audit_event(table_name,record_id,op,after_val)
                VALUES('customer_contact','r43:same-tx','INSERT','{"is_synthetic":true}')""")
            assert scalar(conn, "SELECT occurred_at FROM audit_event WHERE record_id='r43:same-tx'") == armed
            scalar(conn, 'SELECT r32_assert_all()')
    audit = """INSERT INTO audit_event(table_name,record_id,op,after_val,occurred_at)
        VALUES('customer_contact','r43:audit','INSERT','{"is_synthetic":true}',clock_timestamp())"""
    with pytest.raises(psycopg.Error, match='SW-HYG-02'):
        with conn.transaction():
            conn.execute("SET LOCAL application_name='psql'")
            conn.execute(audit)
            scalar(conn, 'SELECT r32_assert_all()')
    conn.execute("SET LOCAL application_name='run_migration_once:x'")
    conn.execute(audit)
    assert scalar(conn, "SELECT application_name FROM audit_event WHERE record_id='r43:audit'") == 'run_migration_once:x'
    assert scalar(conn, "SELECT r32_assert_all()->>'SW-HYG-02'").startswith('PASS:armed_at=')


def test_case_code_resolution_abort_and_apply(conn):
    assert conn.execute('SELECT count(*),count(*) FILTER(WHERE collision),count(*) FILTER(WHERE resolution IS NULL) FROM case_code_rename').fetchone() == (20, 1, 20)
    assert scalar(conn, "SELECT collision FROM case_code_rename WHERE old_code='C110296C'")
    refused(conn, 'SELECT case_code_rename_apply()', match='aborted: .* no resolution')
    actor = admin(conn)
    refused(conn, """UPDATE case_code_rename SET resolution='merge_into',confirmed_by=%s,
        confirmed_at=now() WHERE old_code='C110296C'""", (actor,), match='ccr_merge_target_chk')
    refused(conn, "UPDATE case_code_rename SET resolution='rename',confirmed_at=now() WHERE old_code='C110296D'", match='ccr_confirmed_chk')
    raw = conn.execute('SELECT c.id,c.raw_case_code FROM "case" c JOIN case_code_rename r ON r.case_id=c.id ORDER BY c.id').fetchall()
    conn.execute("""UPDATE case_code_rename SET resolution=CASE WHEN collision THEN 'new_suffix' ELSE 'rename' END,
        new_code=CASE WHEN collision THEN 'C110296-R43' ELSE new_code END,confirmed_by=%s,confirmed_at=now()""", (actor,))
    assert scalar(conn, 'SELECT case_code_rename_apply()')['renamed'] == 20
    assert scalar(conn, 'SELECT bool_and(c.case_code=r.new_code AND c.legacy_case_code=r.old_code) FROM "case" c JOIN case_code_rename r ON r.case_id=c.id')
    assert conn.execute('SELECT c.id,c.raw_case_code FROM "case" c JOIN case_code_rename r ON r.case_id=c.id ORDER BY c.id').fetchall() == raw
    assert scalar(conn, 'SELECT case_code_rename_apply()')['renamed'] == 0


def test_active_admin_floor_uses_role_map(conn):
    assert scalar(conn, "SELECT r32_assert_all()->'SW-PPL-01'->>'YX'") == 'PASS:admins=3'
    conn.execute("""DELETE FROM employee_role_map WHERE employee_id IN
        (SELECT e.id FROM employee e JOIN employee_role_map m ON m.employee_id=e.id
         WHERE e.org_id='YX' AND m.role_code='admin' ORDER BY e.id LIMIT 2)""")
    refused(conn, 'SELECT r32_assert_all()', match='SW-PPL-01')


def test_offboard_handoff_claim_and_gold_employee_names(conn):
    departing = admin(conn, '林瑩瑄')
    others = [row[0] for row in conn.execute("""SELECT id FROM employee WHERE org_id='YX'
        AND r43_has_role(id,ARRAY['admin']) AND id<>%s ORDER BY id""", (departing,))]
    second, third = others
    refused(conn, 'SELECT offboard_handoff(%s)', (departing,), match='not resigned')
    arm_org(conn)
    conn.execute("UPDATE card SET assignee_employee_id=%s WHERE assignee_employee_id=%s AND status='open' AND acted_at IS NULL", (second, departing))
    card = review_card(conn, departing)
    conn.execute("UPDATE card SET role='admin' WHERE id=%s", (card,))
    conn.execute("UPDATE employee SET employment_status='resigned' WHERE id=%s", (departing,))
    assert scalar(conn, 'SELECT identity_confirmed FROM employee WHERE id=%s', (departing,))
    recipient, strip, pending, source = conn.execute('SELECT assignee_employee_id,handoff_strip,handoff_pending,handoff_from FROM card WHERE id=%s', (card,)).fetchone()
    assert recipient in others and strip == '系統：離職移交' and pending and source == departing
    assert scalar(conn, 'SELECT label FROM card_handoff_pending_v WHERE handoff_from=%s', (departing,)) == '1 張待接手（林瑩瑄移交）'
    scalar(conn, 'SELECT card_claim_handoff(%s,%s)', (card, second))
    assert not scalar(conn, 'SELECT handoff_pending FROM card WHERE id=%s', (card,))
    refused(conn, 'SELECT card_claim_handoff(%s,%s)', (card, third), match='already claimed')
    mail = '<r43-' + str(uuid4()) + '@invalid>'
    conn.execute("INSERT INTO email_message(message_id,from_addr) VALUES(%s,'stranger@unknown.invalid')", (mail,))
    sql = """INSERT INTO switchboard_gold_label(sample_id,message_id,stratum,
        annotator_a_employee_id,annotator_b_employee_id,agreed)
        VALUES(%s,%s,'CAT-01',%s,%s,false)"""
    refused(conn, sql, ('R43-SAME', mail, second, second), match='gold_annotator_emp_chk')
    conn.execute(sql, ('R43-GOLD', mail, second, third))
    assert scalar(conn, """SELECT annotator_a=(SELECT full_name FROM employee WHERE id=%s)
        AND annotator_b=(SELECT full_name FROM employee WHERE id=%s)
        FROM switchboard_gold_label WHERE sample_id='R43-GOLD'""", (second, third))
