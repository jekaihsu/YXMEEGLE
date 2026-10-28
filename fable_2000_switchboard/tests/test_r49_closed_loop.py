"""Clone integration tests; CLI calls either mocked or unconditionally dry-run."""
import concurrent.futures
import json
import uuid
from unittest.mock import patch
import pytest
import lark_cli_watcher_daemon as r


def draft():
    return r.push(dict(case_code='C114109',target_employee_name='吳柏頤',client_name='台塑',proposed_subject='R49 verification '+str(uuid.uuid4()),proposed_recipient='sandbox@example.invalid',proposed_body='本週量測進度已整理，請核准。'))


def test_end_to_end_and_idempotent_concurrent_final():
    q = draft()
    assert '--dry-run' in q['lark_cli_command']
    with pytest.raises(ValueError,match='approval required'):
        r.execute_final_send_and_sync_pm_db(q['approval_id'])
    edited = r.ingest(q['approval_id'],'改：現場量測完成，成果仍待檢核。','test-'+str(uuid.uuid4()))
    assert edited['proposed_body']=='現場量測完成，成果仍待檢核。'
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        results=list(pool.map(r.execute_final_send_and_sync_pm_db,[q['approval_id']]*2))
    assert len({x['final_correspondence_serial'] for x in results})==1
    count=r.rows("SELECT count(*) AS n FROM public.lark_agent_colleague_usage_log WHERE approval_id="+r.literal(q['approval_id'])+" AND action_type='final_outbound_sent'")[0]['n']
    assert count==1
    assert any(x['approval_id']==q['approval_id'] for x in json.loads(r.PM_PATH.read_text())['records'])
    assert r.rows("SELECT * FROM public.audit_event WHERE table_name='lark_colleague_approval_queue' AND record_id="+r.literal(q['approval_id']))


@pytest.mark.parametrize('text',['發','OK','可以發','緩'])
def test_reply_variants_and_replay(text):
    q=draft();mid='test-'+str(uuid.uuid4())
    reply=r.ingest(q['approval_id'],text,mid)
    assert r.ingest(q['approval_id'],text,mid)==reply
    if text=='緩':
        with pytest.raises(ValueError,match='approval required'):
            r.execute_final_send_and_sync_pm_db(q['approval_id'])


def test_watcher_correlation_sender_and_duplicate():
    q=draft();mid='test-'+str(uuid.uuid4())
    def message(sender):
        return {'sender':{'id':sender},'message_id':mid,'body':{'content':json.dumps({'text':f"[R49:{q['approval_id']}] OK"})}}
    with patch.object(r,'cli',return_value=({'data':{'items':[message('wrong-person')]}},'--dry-run')):
        assert r.poll_once()['processed']==0
    with patch.object(r,'cli',return_value=({'data':{'items':[message(q['target_lark_open_id'])]}},'--dry-run')):
        assert r.poll_once()['processed']==1
        assert r.poll_once()['processed']==0


def test_cli_always_dry_run():
    with patch.object(r.subprocess,'run') as run:
        run.return_value.returncode=0;run.return_value.stdout='{}'
        for cmd,text in [('+messages-send','safe'),('+chat-messages-list',None)]:
            r.cli(cmd,'ou_test',text)
            assert '--dry-run' in run.call_args.args[0]


def test_roster_and_assertions():
    assert len(r.dashboard()['colleagues'])==67
    assert all(v=='PASS' for v in json.loads(r.sql('SELECT public.r49_assert_all();')).values())
