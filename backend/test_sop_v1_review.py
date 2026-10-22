from copy import deepcopy

import pytest
from sqlalchemy import select

from .models import BusinessRow
from .sop_import.catalog import load_catalog
from .sop_import.domain import Failure, Lifecycle
from .sop_import.models import LocalTask, TaskEvent
from .sop_import.service import completion_policy
from .test_sop_import import URL, apply, change, h, overview, post, preview  # noqa: F401
from .test_sop_task_views import by_row, prove_sales


def imported(h, number=59):
    key = f'meegle-v137:A:{number}'
    decisions = {key: {'value': 'applicable', 'reason': 'Applicable'}} if number in {7, 20, 54} else {}
    apply(h, preview(h, row_keys=[key], participant_bindings={key: {'executor': 'member', 'checker': 'pm'}},
                     applicability_decisions=decisions), rid=f'v1-{number}')
    return by_row(h, number)


def proof(h, version='1'):
    file = {'id': 'file-' + version, 'file_key': 'delivery', 'version': version, 'sha256': version * 64,
            'storage': 'local', 'direction': 'output', 'size': 100, 'uploaded_by': 'member', 'node_id': None}
    with h.sessions.begin() as db:
        row = db.get(BusinessRow, ('w', 'projects', 'p1'))
        row.data = {**row.data, 'files': row.data.get('files', []) + [file]}
    return {'kind': 'file', **{k: file[k] for k in ('version', 'sha256')}, 'file_id': file['id']}


def transition(h, task, **extra):
    return {'expected_revision': task['revision'], 'action': 'complete', **extra}


def review(h, task, action, status=200, **extra):
    return post(h, f"{URL}/sop-tasks/{task['id']}/{action}",
                {'expected_revision': task['revision'], 'request_id': action, **extra}, status)


def test_ordinary_assignee_self_completes_without_upload_and_retry_is_one_event(h):
    task = imported(h)
    h.who[0] = 'other'
    path = f"{URL}/sop-tasks/{task['id']}/transition"
    assert post(h, path, transition(h, task), 403)['code'] == 'sop_import_forbidden'
    h.who[0] = 'member'
    first = post(h, path, transition(h, task))
    retry = post(h, path, transition(h, task))
    assert first['state'] == retry['state'] == 'done'
    assert first['revision'] == retry['revision'] == 2
    assert retry['replayed'] is True
    assert overview(h)['counts']['done'] == 1
    counts = h.service.read_counts('w', h.users['member'], ['p1'], own=True)
    assert counts['counts']['done'] == counts['projects']['p1']['done'] == 1
    with h.sessions() as db:
        assert len(list(db.scalars(select(TaskEvent).where(TaskEvent.kind == 'transition')))) == 1


def test_routine_file_proof_is_typed_current_and_no_review_needed(h):
    task = imported(h, 20)
    assert 'complete' in task['allowed_actions']
    h.who[0] = 'member'
    path = f"{URL}/sop-tasks/{task['id']}/transition"
    assert post(h, path, transition(h, task), 422)['code'] == 'completion_evidence_missing'
    ref = proof(h)
    bad = {**ref, 'sha256': '0' * 64}
    assert post(h, path, transition(h, task, evidence_refs=[bad]), 422)['code'] == 'invalid_file_proof'
    newer = proof(h, '2')
    assert post(h, path, transition(h, task, evidence_refs=[ref]), 409)['code'] == 'stale_file_proof'
    assert post(h, path, transition(h, task, evidence_refs=[newer]))['state'] == 'done'


@pytest.mark.parametrize('decision', ['approve', 'return'])
def test_important_submit_review_exact_revision_and_retry(h, decision):
    task = imported(h, 19)
    ref = proof(h)
    h.who[0] = 'member'
    submitted = review(h, task, 'submit-for-review', evidence_refs=[ref], note='Ready')['task']
    replay = review(h, task, 'submit-for-review', evidence_refs=[ref], note='Ready')
    assert replay['replayed'] and replay['task'] == submitted
    assert submitted['state'] == 'pending'
    assert submitted['local']['submission']['revision'] == 1
    history = h.client.get(f"{URL}/sop-tasks/{task['id']}/history").json()['events']
    submission_event = next(e for e in history if e['kind'] == 'submit_for_review')
    assert submission_event['changes']['submission'] == submitted['local']['submission']
    assert 'response' not in submission_event['changes']
    assert overview(h)['counts']['done'] == 0
    assert h.client.get(URL + '/sop-tasks/reviewer-queue').json()['total'] == 0
    h.who[0] = 'other'
    assert h.client.get(URL + '/sop-tasks/reviewer-queue').json()['tasks'] == []
    assert review(h, submitted, decision, 403, submission_revision=1)['code'] == 'sop_import_forbidden'
    h.who[0] = 'pm'
    assert h.client.get(URL + '/sop-tasks/reviewer-queue').json()['total'] == 1
    assert review(h, submitted, decision, 409, submission_revision=0)['code'] == 'stale_submission'
    if decision == 'return':
        assert review(h, submitted, decision, 422, submission_revision=1)['code'] == 'invalid_request'
    args = {'submission_revision': 1, **({'reason': 'Fix the output'} if decision == 'return' else {})}
    result = review(h, submitted, decision, **args)
    assert review(h, submitted, decision, **args)['replayed'] is True
    assert result['state'] == ('done' if decision == 'approve' else 'in_progress')
    assert h.client.get(URL + '/sop-tasks/reviewer-queue').json()['total'] == 0
    if decision == 'return':
        h.who[0] = 'member'
        assert by_row(h, 19)['local']['return_reason'] == 'Fix the output'
        second = review(h, result['task'], 'submit-for-review', request_id='second', evidence_refs=[ref])['task']
        assert second['local']['submission']['revision'] == 2
        h.who[0] = 'pm'
        assert review(h, second, 'approve', 409, submission_revision=1)['code'] == 'stale_submission'
    else:
        assert review(h, result['task'], 'return', 409, submission_revision=1, reason='Too late')['code'] == 'terminal_task'
    with h.sessions() as db:
        submissions = list(db.scalars(select(TaskEvent).where(TaskEvent.kind == 'submit_for_review')))
        assert submissions[0].changes['submission']['snapshot']['note'] == 'Ready'
    with pytest.raises(Failure, match='immutable_task_event'):
        with h.sessions.begin() as db:
            event = db.scalar(select(TaskEvent).where(TaskEvent.kind == 'submit_for_review'))
            event.changes = {}


def test_assignment_change_conflicts_and_queue_uses_current_authority(h):
    task = imported(h, 19)
    ref = proof(h)
    h.who[0] = 'member'
    submitted = review(h, task, 'submit-for-review', evidence_refs=[ref])['task']
    h.who[0] = 'pm'
    changed = change(h, submitted, {'participants': {'executor': 'other', 'checker': 'member'}})['task']
    assert review(h, changed, 'approve', 409, submission_revision=1)['code'] == 'review_assignment_changed'
    assert h.client.get(URL + '/sop-tasks/reviewer-queue').json()['total'] == 0
    h.who[0] = 'other'
    resubmitted = review(h, changed, 'submit-for-review', request_id='reassigned', evidence_refs=[ref])['task']
    h.users['member']['capabilities'] = []
    h.who[0] = 'member'
    assert h.client.get(URL + '/sop-tasks/reviewer-queue').json()['total'] == 1
    assert review(h, resubmitted, 'approve', submission_revision=2)['state'] == 'done'


@pytest.mark.parametrize('number,code', [(8, 'review_required'), (7, 'formal_external_required')])
def test_direct_suggestion_bulk_and_close_cannot_bypass_policy(h, number, code):
    task = imported(h, number)
    path = f"{URL}/sop-tasks/{task['id']}"
    assert post(h, path + '/transition', transition(h, task), 422)['code'] == code
    item = {'task_id': task['id'], 'expected_revision': 1, 'facts_hash': '0' * 64}
    assert post(h, path + '/suggestion', {'action': 'accept_suggestion', **{k:v for k,v in item.items() if k != 'task_id'}}, 422)['code'] == code
    assert post(h, URL + '/sop-tasks/suggestions/accept', {'tasks': [item], 'confirm': True, 'reason': 'Old source proof'}, 422)['code'] == code
    prove_sales(h)
    assert post(h, URL + '/sop-tasks/close-node', {'node_key': 'sales'}, 422)['code'] == code
    assert by_row(h, number)['state'] == 'pending'


def test_policy_fallback_uses_immutable_origin_and_old_proof_cannot_bypass(h):
    row = deepcopy(next(r for r in load_catalog()['case_sop_rows'] if r['raw']['meegle_id'] == 8))
    row.pop('completion_policy')
    task = LocalTask(snapshot={'row': row}, local={'completion_rule_status': 'no_typed_obligations'},
                     applicability='applicable', state=Lifecycle.PENDING)
    assert completion_policy(task) == {'version': 1, 'value': 'reviewer_required'}
    assert h.service.completion_failure(task, {'tier': 'proof'}) == 'review_required'


def test_real_app_routine_counters_follow_completion(tmp_path, monkeypatch):
    from .test_sop_quotes import harness
    import httpx

    def no_outbound(*args, **kwargs):
        raise AssertionError('outbound network is forbidden')
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', no_outbound)
    app, client, signin, ids = harness(tmp_path)
    try:
        url = '/api/projects/' + ids['formal']
        key = 'meegle-v137:A:59'
        plan = client.post(url + '/sop-import/preview', json={'template_version_id': ids['version'],
                           'row_keys': [key], 'participant_bindings': {key: {'executor': 'u-field'}}})
        assert plan.status_code == 200, plan.text
        applied = client.post(url + '/sop-import/apply', json={'preview_id': plan.json()['preview_id'], 'request_id': 'routine'})
        assert applied.status_code == 200, applied.text
        task_id = applied.json()['created_task_ids'][0]
        signin('u-field')
        before = client.get('/api/my-work')
        assert before.status_code == 200, before.text
        assert before.json()['sop_counts']['done'] == 0
        response = client.post(f'{url}/sop-tasks/{task_id}/transition', json={'expected_revision': 1, 'action': 'complete'})
        assert response.status_code == 200, response.text
        assert client.get('/api/my-work').json()['sop_counts']['done'] == 1
        for path in ('/api/my-work', '/api/my-work?panel=assigned&scope=mine'):
            payload = client.get(path)
            assert payload.status_code == 200, payload.text
            work = payload.json()['sop_work']
            assert work['signals'] == {'routine_completed': 1, 'important_submitted': 0, 'important_returned': 0}
            assert [t['task_id'] for t in work['items'] if t['signal'] == 'routine_completed'] == [task_id]
            assert work['reviewer_items'] == []
        dashboard = client.get('/api/company-dashboard').json()
        assert dashboard['sop_counts']['done'] == 1
        assert dashboard['sop_signals']['routine_completed'] == 1
        assert len([t for t in dashboard['sop_items'] if t['signal'] == 'routine_completed']) == 1
        assert next(p for p in dashboard['cases'] if p['id'] == ids['formal'])['sop_counts']['done'] == 1
        progress = client.get(url + '/progress')
        assert progress.status_code == 200, progress.text
        assert progress.json()['sop_counts']['done'] == 1
        assert progress.json()['sop_signals']['routine_completed'] == 1
        assert len([t for t in progress.json()['sop_items'] if t['signal'] == 'routine_completed']) == 1
        signin('u-report')
        assert client.get('/api/my-work').json()['sop_counts']['total'] == 0
    finally:
        app.state.engine.dispose()


def test_routine_write_gate_stays_off(h):
    task = imported(h, 59)
    h.cfg['SOP_TASK_WRITES_ENABLED'] = 'false'
    h.who[0] = 'member'
    path = f"{URL}/sop-tasks/{task['id']}/transition"
    assert post(h, path, transition(h, task), 503)['code'] == 'import_unavailable'


def test_important_no_upload_and_existing_self_reviewer_rule(h):
    task = imported(h, 24)
    changed = change(h, task, {'participants': {'executor': 'member', 'checker': 'member'}})['task']
    h.who[0] = 'member'
    submitted = review(h, changed, 'submit-for-review', note='Confirmed')['task']
    assert submitted['local']['submission']['snapshot']['evidence'] == []
    assert review(h, submitted, 'approve', submission_revision=1)['state'] == 'done'


def test_review_replay_respects_revoked_source_grant(h):
    task = imported(h, 24)
    h.who[0] = 'member'
    submitted = review(h, task, 'submit-for-review')['task']
    h.who[0] = 'pm'
    first = review(h, submitted, 'approve', submission_revision=1)
    assert first['task']['source_snapshot'] is not None
    h.users['pm']['capabilities'].remove('sop_task_read_source')
    retry = review(h, submitted, 'approve', submission_revision=1)
    assert retry['replayed'] and retry['task']['source_snapshot'] is None
    assert retry['task']['instructions'] is None


def test_concurrent_approval_retries_append_one_decision(h):
    from concurrent.futures import ThreadPoolExecutor

    task = imported(h, 24)
    h.who[0] = 'member'
    submitted = review(h, task, 'submit-for-review')['task']
    h.who[0] = 'pm'
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: review(h, submitted, 'approve', submission_revision=1), range(2)))
    assert sorted(r['replayed'] for r in replies) == [False, True]
    assert {r['revision'] for r in replies} == {3}
    with h.sessions() as db:
        assert len(list(db.scalars(select(TaskEvent).where(TaskEvent.kind == 'approve')))) == 1


def test_changed_project_pm_requires_a_fresh_submission(h):
    task = imported(h, 24)
    h.who[0] = 'member'
    submitted = review(h, task, 'submit-for-review')['task']
    with h.sessions.begin() as db:
        project = db.get(BusinessRow, ('w', 'projects', 'p1'))
        project.data = {**project.data, 'pm_id': 'other'}
    h.who[0] = 'other'
    assert review(h, submitted, 'approve', 409, submission_revision=1)['code'] == 'review_assignment_changed'
    h.who[0] = 'member'
    assert 'submit_for_review' in by_row(h, 24)['allowed_actions']
    second = review(h, submitted, 'submit-for-review', request_id='new-pm')['task']
    h.who[0] = 'other'
    assert review(h, second, 'approve', submission_revision=2)['state'] == 'done'


def test_v1_signals_drilldowns_and_reviewer_permissions(h):
    from .my_work import sop_projection
    from .company_dashboard import add_sop_progress as dashboard
    from .project_progress import add_sop_progress as progress
    routine = imported(h, 59)
    important = imported(h, 24)
    formal = imported(h, 7)
    h.who[0] = 'member'
    post(h, f"{URL}/sop-tasks/{routine['id']}/transition", transition(h, routine))
    submitted = review(h, important, 'submit-for-review')['task']
    projection = h.service.read_counts('w', h.users['member'], ['p1'], own=True)
    assert projection['signals'] == {'routine_completed': 1, 'important_submitted': 1, 'important_returned': 0}
    assert len(projection['items']) == 3
    assert all(t['id'] == f"sop_local:p1:{t['task_id']}" for t in projection['items'])
    for key, count in projection['signals'].items():
        assert len([t for t in projection['items'] if t['signal'] == key]) == count
    assert next(t for t in projection['items'] if t['task_id'] == formal['id'])['signal'] is None
    assert h.service.read_counts('w', h.users['other'], ['p1'], own=True)['items'] == []
    with h.sessions() as db:
        project = deepcopy(db.get(BusinessRow, ('w', 'projects', 'p1')).data)
    state = {'users': list(h.users.values())}
    assert h.service.read_work('w', h.users['member'], state, [project])['reviewer_items'] == []
    assert len(h.service.read_work('w', h.users['pm'], state, [project])['reviewer_items']) == 1
    assert h.service.read_work('w', h.users['other'], state, [project])['reviewer_items'] == []
    h.users['pm']['capabilities'] = []
    assert len(h.service.read_work('w', h.users['pm'], state, [project])['reviewer_items']) == 1
    h.who[0] = 'pm'
    review(h, submitted, 'return', submission_revision=1, reason='補齊成果')
    returned = h.service.read_counts('w', h.users['member'], ['p1'], own=True)
    assert returned['signals'] == {'routine_completed': 1, 'important_submitted': 0, 'important_returned': 1}
    assert h.service.read_work('w', h.users['pm'], state, [project])['reviewer_items'] == []
    item = next(t for t in returned['items'] if t['signal'] == 'important_returned')
    assert item['return_reason'] == '補齊成果'
    for attach in (dashboard, progress):
        result = {'cases': [{'id': 'p1'}]}
        attach(result, returned)
        assert result['sop_signals'] == returned['signals']
        assert result['sop_items'] == returned['items']
    assert result['sop_counts']['done'] == 1
    assert sop_projection([]) == {'signals': {'routine_completed': 0, 'important_submitted': 0, 'important_returned': 0}, 'items': []}
