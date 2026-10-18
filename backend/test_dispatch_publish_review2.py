"""Second independent-review round of dispatch publish, each defect reproduced against the fake V4 Bitable."""
from sqlalchemy import select

from .models import DispatchCommandRow, DispatchDecisionRow
from .test_dispatch_publish import PROPOSAL, ROLES, approve, call, commit, h, preview, published  # noqa: F401
from .test_dispatch_publish_fake import PEOPLE, TASKS, ok, timeout_before
from .test_dispatch_publish_review import CMD, NO_SEATS, REASSIGN, puts, stored_command


def searches(h):
    return [r for r in h.fake.requests if r[0] == 'POST' and r[1].endswith(f'/{TASKS}/records/search')]


def empty_search(request, proceed):
    return ok({'has_more': False, 'total': 0})


def reassigned(h):
    """Publish the create, then an approved reassignment preview of the created row."""
    found, first = published(h)
    rid = first['command']['task_id']
    h.clock[0] += 61
    pid = preview(h, task_id=rid, **REASSIGN)['preview_id']
    approve(h, pid)
    return found, rid, pid


def test_a_published_create_cannot_be_published_again_after_its_task_is_reassigned(h):
    first, _, pid = reassigned(h)
    assert commit(h, CMD(2), pid).status_code == 200
    h.clock[0] += 61
    again = preview(h)
    assert again['preview_hash'] == first['preview_hash']
    assert [s['decision'] for s in again['required_seats']] == [None, None, None]
    assert ('already_published' in again['blockers'], again['can_commit']) == (True, False)
    response = commit(h, CMD(3), again['preview_id'])
    assert (response.status_code, response.json()['code'], response.json()['command_id']) == (
        409, 'duplicate_command', CMD(1))
    assert len(h.fake.creates()) == 1


def test_a_decision_by_someone_who_no_longer_holds_the_seat_does_not_count_at_commit(h, monkeypatch):
    client = h.build(NO_SEATS)
    pid = preview(h, client)['preview_id']
    approve(h, pid, client)
    h.fake.tables[PEOPLE]['recP6']['在職'] = False
    response = commit(h, CMD(1), pid, client)
    assert (response.status_code, response.json()['code'], response.json()['seats']) == (
        409, 'decision_holder_changed', ['group_leader_confirmed'])
    assert h.fake.creates() == []
    shown = call(h, 'ou_pm', 'get', f'/api/v2/dispatch/previews/{pid}', client=client).json()
    assert shown['required_seats'][0]['decision'] is None
    assert 'decision_holder_changed:group_leader_confirmed' in shown['blockers']

    h.fake.add(PEOPLE, 'recP9', {'姓名': '新組長', '在職': True, 'Lark帳號': [{'id': 'ou_lead2'}], '職級': '組長',
                                 '所屬組別': ['外業']})
    monkeypatch.setitem(ROLES, 'ou_lead2', 'member')
    response = commit(h, CMD(1), pid, client)
    assert (response.status_code, response.json()['code']) == (409, 'decision_holder_changed')
    decided = call(h, 'ou_lead2', 'post', f'/api/v2/dispatch/previews/{pid}/decisions',
                   {'seat': 'group_leader_confirmed', 'decision': 'accepted'}, client)
    assert decided.status_code == 200, decided.text
    assert commit(h, CMD(1), pid, client).json()['command']['state'] == 'committed'


def test_department_must_be_a_known_group_and_match_the_task_node(h):
    response = call(h, 'ou_pm', 'post', '/api/v2/dispatch/previews', {**PROPOSAL, 'department': '不存在組'})
    assert (response.status_code, response.json()['code'], response.json()['field'], response.json()['reason']) == (
        422, 'invalid', 'department', 'unknown_department')
    response = call(h, 'ou_pm', 'post', '/api/v2/dispatch/previews',
                    {**PROPOSAL, 'task_id': 'recLegacy', 'department': '測繪'})
    assert (response.status_code, response.json()['reason']) == (422, 'department_not_node_group')
    assert preview(h, task_id='recLegacy')['proposal']['department'] == '外業'


def test_the_proposer_cannot_hold_the_leader_or_manager_seat_on_their_own_preview(h):
    response = call(h, 'ou_mgr', 'post', '/api/v2/dispatch/previews', PROPOSAL)
    body = response.json()
    assert (response.status_code, body['my_seats']) == (200, [])
    assert 'approval_not_configured:manager_review' in body['blockers']
    pid = body['preview_id']
    assert call(h, 'ou_lead', 'post', f'/api/v2/dispatch/previews/{pid}/decisions',
                {'seat': 'group_leader_confirmed', 'decision': 'accepted'}).status_code == 200
    response = call(h, 'ou_mgr', 'post', f'/api/v2/dispatch/previews/{pid}/decisions',
                    {'seat': 'manager_review', 'decision': 'accepted'})
    assert (response.status_code, response.json()['reason']) == (409, 'own_preview')

    with h.sessions.begin() as db:
        db.add(DispatchDecisionRow(id='d' * 32, workspace_id='lark-company', preview_hash=body['preview_hash'],
                                   preview_id=pid, seat='manager_review', actor_id='ou_mgr', decision='accepted',
                                   reason=None, at=h.clock[0]))
    call(h, 'ou_pmf', 'post', f'/api/v2/dispatch/previews/{pid}/decisions', {'seat': 'pm_final', 'decision': 'accepted'})
    response = commit(h, CMD(1), pid)
    assert (response.status_code, response.json()['code'], response.json()['seats']) == (
        409, 'decision_holder_changed', ['manager_review'])
    assert h.fake.creates() == []


def test_the_in_lock_recheck_is_one_short_attempt_and_releases_everything_on_failure(h):
    _, rid, pid = reassigned(h)
    held = h.held()
    timeouts = []

    def slow(request, proceed):
        timeouts.append(request.extensions['timeout']['read'])
        return timeout_before(request, proceed)
    h.fake.on('GET', f'/records/{rid}', slow, times=3)
    response = commit(h, CMD(2), pid)
    assert (response.status_code, response.json()['code'], response.json()['retryable']) == (
        503, 'recheck_unavailable', True)
    assert len(timeouts) == 1 and 0 < timeouts[0] <= 5
    assert (stored_command(h, CMD(2)), h.held(), puts(h)) == (None, held, [])
    h.fake.hooks.clear()
    assert commit(h, CMD(2), pid).json()['command']['state'] == 'committed'


def test_a_lagging_search_is_retried_once_after_a_short_sleep(h):
    pid = preview(h)['preview_id']
    approve(h, pid)
    h.fake.on('POST', f'/{TASKS}/records/search', empty_search)
    body = commit(h, CMD(1), pid).json()
    assert (body['command']['state'], len(searches(h)), h.sleeps) == ('committed', 2, [1])


def test_a_search_that_still_lags_stays_unknown_and_reconcile_resolves_it_without_resending(h):
    pid = preview(h)['preview_id']
    approve(h, pid)
    h.fake.on('POST', f'/{TASKS}/records/search', empty_search, times=2)
    body = commit(h, CMD(1), pid).json()
    assert (body['command']['state'], body['receipt']['error'], body['receipt']['record_id']) == (
        'outcome_unknown', 'search_lag', 'recTask0001')
    h.fake.on('POST', f'/{TASKS}/records/search', empty_search)
    body = call(h, 'ou_mgr', 'post', f'/api/v2/commands/{CMD(1)}/reconcile').json()
    assert (body['command']['state'], body['command']['task_id']) == ('committed', 'recTask0001')
    assert (len(h.fake.creates()), len(searches(h))) == (1, 4)


def test_reconcile_of_a_receipt_without_a_base_snapshot_asks_for_reconciliation(h):
    _, rid, pid = reassigned(h)
    h.fake.on('PUT', f'/records/{rid}', timeout_before)
    assert commit(h, CMD(2), pid).json()['command']['state'] == 'outcome_unknown'
    with h.sessions.begin() as db:
        row = db.scalars(select(DispatchCommandRow).where(DispatchCommandRow.command_id == CMD(2))).one()
        row.receipt = {k: v for k, v in row.receipt.items() if k != 'base'}
    h.fake.tables[TASKS][rid]['內容'] = '現場改寫的內容'
    response = call(h, 'ou_mgr', 'post', f'/api/v2/commands/{CMD(2)}/reconcile')
    assert (response.status_code, response.json()['command']['state'], response.json()['receipt']['reason']) == (
        202, 'reconciliation_required', 'no_base_snapshot')
    assert len(puts(h)) == 1


def test_an_earlier_preview_of_a_published_draft_stays_hidden_after_its_commit_is_superseded(h):
    _, first = published(h)
    rid = first['command']['task_id']
    h.clock[0] += 61
    early = preview(h, task_id=rid, draft_id='draft-0007', **{**REASSIGN, 'verifications': {}})
    assert early['blockers']
    h.clock[0] += 1
    done = preview(h, task_id=rid, draft_id='draft-0007', **REASSIGN)
    approve(h, done['preview_id'])
    assert commit(h, CMD(2), done['preview_id']).status_code == 200
    h.clock[0] += 61
    other = preview(h, task_id=rid, **{**REASSIGN, 'start': '2026-10-21T13:00+08:00', 'end': '2026-10-21T17:00+08:00'})
    approve(h, other['preview_id'])
    assert commit(h, CMD(3), other['preview_id']).status_code == 200
    rows = call(h, 'ou_pm', 'get', '/api/v2/dispatch/work?scope=all').json()['rows']
    assert [r.get('preview_id') for r in rows if r['source'] == 'workbench_preview'] == []


def test_commit_revalidates_the_gate_after_the_in_lock_recheck(h):
    _, rid, pid = reassigned(h)
    held = h.held()
    h.fake.on('GET', f'/records/{rid}', lambda request, proceed: (
        h.workspace['settings'].update(external_enabled=False), proceed())[1])
    response = commit(h, CMD(2), pid)
    assert (response.status_code, response.json()['code']) == (403, 'writes_disabled')
    assert (puts(h), stored_command(h, CMD(2)), h.held()) == ([], None, held)

