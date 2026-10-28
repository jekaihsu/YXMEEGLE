from datetime import datetime, timezone
import pytest
from temporal_router import predict_from_history
from test_golden_ticket105 import connect, quarantine_card


def test_equal_and_future_evidence_cannot_leak():
    m=dict(message_id='<in@test>', references=['<root@test>'],from_addr='client@ctci.com',subject='請確認',body_new_text='',received_at='2026-10-20T00:00:00+00:00')
    future=dict(message_id='<root@test>',received_at='2026-10-20T00:00:01+00:00',subject='C115777 成果提供')
    same=dict(future,received_at=m['received_at'])
    assert predict_from_history(m,[future,same])['case_ref'] is None
    prior=dict(future,received_at='2026-10-19T23:59:59+00:00')
    assert predict_from_history(m,[prior,future,same])['case_ref']=='C115777'


def test_unknown_received_time_fails_closed():
    with pytest.raises(ValueError):predict_from_history(dict(received_at=None),[])


def test_database_cutoff_and_known_leak_canary():
    from uuid import uuid4
    from router import classify_as_of
    c=connect();key='<canary-'+str(uuid4())+'@test.invalid>'
    try:
        m=dict(message_id='<current@test.invalid>', references=[key],from_addr='client@ctci.com',subject='請確認',body_new_text='',received_at='2030-01-01T00:00:00+00:00')
        c.execute("insert into email_message(message_id,from_addr,subject,received_at,mailbox_id) values(%s,'client@ctci.com','C115777 成果提供','2030-01-02',(select id from email_mailbox where org_id='YX' limit 1))",(key,))
        r=classify_as_of(c,m)
        assert r['case_ref'] is None and key not in r['related_history_ids']
        leaky=dict(m,received_at='2030-01-03T00:00:00+00:00')
        assert classify_as_of(c,leaky)['case_ref']=='C115777'
    finally:c.rollback();c.close()


def test_normal_auto_quarantine_trigger_emits_exactly_one():
    from uuid import uuid4
    c=connect();mid='<auto-'+str(uuid4())+'@test.invalid>'
    try:
        c.execute("insert into email_message(message_id,from_addr,body_new_text,mailbox_id) values(%s,'client@ctci.com','上準精密 83100099',(select id from email_mailbox where org_id='YX' limit 1))",(mid,))
        assert c.execute('select org_id is null and quarantine_reason is not null from email_message where message_id=%s',(mid,)).fetchone()[0]
        assert c.execute('select count(*) from card where idempotency_key=%s',('quarantine:'+mid,)).fetchone()[0]==1
        assert c.execute('select emit_quarantine_cards()').fetchone()[0]==0
    finally:c.rollback();c.close()
