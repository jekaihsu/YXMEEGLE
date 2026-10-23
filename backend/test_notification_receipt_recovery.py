"""Issue #37: verified receipts and expired leases survive Worker restarts."""
import pytest
from fastapi import HTTPException
from .jobs import now
from .operations import apply_operation
from .test_source_sync import harness
from .test_worker_reliability import (
    notification_job, notification_worker, save, saved_job,
)


@pytest.mark.parametrize('kind', ['digest', 'confirmation'])
def test_verified_lost_receipt_resumes_only_unsent_recipients(harness, tmp_path, monkeypatch, kind):
    h = harness
    job, actor, recipients = notification_job(h, kind)
    state, _ = h.read()
    third = next(u['id'] for u in state['users'] if u['active'] and u['id'] not in recipients)
    recipients.append(third)
    target = next(j for j in state['jobs'] if j['id'] == job['id'])
    target['payload']['recipients'] = recipients
    if kind == 'confirmation':
        issue = next(i for p in state['projects'] for i in p['confirmation_issues']
                     if i['id'] == job['payload']['issue_id'])
        issue['recipients'] = recipients
    save(h, state)
    sent, remote_receipts = [], {}

    def message(recipient, *_):
        sent.append(recipient)
        remote_receipts[recipient] = {'message_id': 'msg-' + recipient}
        return remote_receipts[recipient]

    worker = notification_worker(h, tmp_path, message)
    checkpoint = worker.checkpoint
    failed = False

    def lose_second_receipt(*args, **kwargs):
        nonlocal failed
        if len(sent) == 2 and not failed:
            failed = True
            raise RuntimeError('DB failed after second recipient accepted')
        return checkpoint(*args, **kwargs)

    monkeypatch.setattr(worker, 'checkpoint', lose_second_receipt)
    worker.run_one(h.wid)
    state, _ = h.read()
    target = next(j for j in state['jobs'] if j['id'] == job['id'])
    assert target['status'] == 'outcome_unknown'
    assert [s['key'] for s in target['steps']] == recipients[:1]
    with pytest.raises(HTTPException) as error:
        apply_operation(state, actor, {'action': 'job_retry', 'payload': {'id': job['id']}}, False)
    assert error.value.status_code == 409
    notification_worker(h, tmp_path, message).run_one(h.wid)
    assert sent == recipients[:2]

    # Model an operator's DB repair after independently verifying the remote
    # receipt. There is no notification-reconciliation API in this baseline.
    target['steps'].append({'key': recipients[1], 'receipt': remote_receipts[recipients[1]], 'at': now()})
    target.update(status='blocked', error=None)
    apply_operation(state, actor, {'action': 'job_retry', 'payload': {'id': job['id']}}, False)
    save(h, state)
    notification_worker(h, tmp_path, message).run_one(h.wid)
    result = saved_job(h, job)
    assert sent == recipients
    assert result['status'] == 'succeeded'
    assert [s['key'] for s in result['steps']] == recipients
    assert [s['receipt'] for s in result['steps']] == [remote_receipts[r] for r in recipients]
    if kind == 'confirmation':
        issue = next(i for p in h.read()[0]['projects'] for i in p['confirmation_issues']
                     if i['id'] == job['payload']['issue_id'])
        assert issue['status'] == 'issued' and issue['receipts'] == result['steps']


@pytest.mark.parametrize('kind', ['digest', 'confirmation'])
def test_restart_quarantines_expired_notification_lease(harness, tmp_path, kind):
    h = harness
    job, actor, recipients = notification_job(h, kind)
    state, _ = h.read()
    target = next(j for j in state['jobs'] if j['id'] == job['id'])
    target.update(status='running', lease_token='interrupted-worker',
                  lease_until='2000-01-01T00:00:00+00:00')
    target['steps'].append({'key': recipients[0], 'receipt': {'message_id': 'already-saved'}, 'at': now()})
    save(h, state)
    worker = notification_worker(h, tmp_path, lambda *_: pytest.fail('Expired lease resent a notification'))
    assert worker.run_one(h.wid) is None
    assert worker.run_one(h.wid) is None
    result = saved_job(h, job)
    assert result['status'] == 'outcome_unknown' and result['steps'] == target['steps']
    state, _ = h.read()
    with pytest.raises(HTTPException) as error:
        apply_operation(state, actor, {'action': 'job_retry', 'payload': {'id': job['id']}}, False)
    assert error.value.status_code == 409
