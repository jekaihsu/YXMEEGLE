"""Independent-review defects of dispatch publish, each reproduced against the fake V4 Bitable."""
import threading
from datetime import date

import httpx
from sqlalchemy import select

from .dispatch_board.config import SOURCES
from .models import DispatchCommandRow, DispatchDraftRow
from .test_dispatch_publish import (  # noqa: F401
    EXPECTED_ROW, PROPOSAL, ROLES, T0, approve, call, commit, h, ms, preview, published, seed)
from .test_dispatch_publish_fake import PEOPLE, SCHEDULE, TASKS, FakeLark, timeout_after, timeout_before

CMD = '0d15ea5e-0000-4000-8000-0000000000{:02d}'.format
NODES = SOURCES['nodes'].table_id
NO_SEATS = {'DISPATCH_SEAT_GROUP_LEADER': '', 'DISPATCH_SEAT_MANAGER_REVIEW': '', 'DISPATCH_SEAT_PM_FINAL': ''}
REASSIGN = {'primary_owner': 'recP2', 'crew': ['recP2'], 'start': '2026-10-20T13:00+08:00',
            'end': '2026-10-20T17:00+08:00', 'verifications': {'person:recP2': '主管核實 L2 資格'}}


def puts(h):
    return [r for r in h.fake.requests if r[0] == 'PUT']


def stored_command(h, command_id):
    with h.sessions() as db:
        return db.scalars(select(DispatchCommandRow).where(DispatchCommandRow.command_id == command_id)).first()


def test_command_id_must_be_a_uuid4_and_is_sent_unchanged_as_client_token(h):
    pid = preview(h)['preview_id']
    approve(h, pid)
    h.fake.requests.clear()
    for bad in ('cmd-publish-0001', CMD(1).upper(), '0d15ea5e-0000-1000-8000-000000000001'):
        response = commit(h, bad, pid)
        assert (response.status_code, response.json()['code'], response.json()['field']) == (422, 'invalid', 'command_id')
    assert h.fake.requests == []
    assert commit(h, CMD(1), pid).status_code == 200
    assert [q['client_token'] for _, _, q in h.fake.creates()] == [CMD(1)]


def test_two_workers_that_assessed_revision_1_cannot_both_commit_revision_2(h):
    _, first = published(h)
    rid = first['command']['task_id']
    h.clock[0] += 61
    winner = preview(h, task_id=rid, **REASSIGN)
    loser = preview(h, task_id=rid, **{**REASSIGN, 'primary_owner': 'recP1', 'crew': ['recP1'],
                                       'start': '2026-10-20T14:00+08:00', 'end': '2026-10-20T15:00+08:00',
                                       'verifications': {'person:recP1': 'ok'}})
    approve(h, winner['preview_id'])
    approve(h, loser['preview_id'])
    assessed, released = threading.Event(), threading.Event()

    def pause(request, proceed):
        assessed.set()
        assert released.wait(10)
        return proceed()
    h.fake.on('GET', f'/{NODES}/records', pause)
    other = h.build()
    h.who[0] = 'ou_pm'
    result = {}
    worker = threading.Thread(target=lambda: result.setdefault('loser', other.post(
        '/api/v2/dispatch/commits', json={'command_id': CMD(9), 'preview_id': loser['preview_id']})))
    worker.start()
    assert assessed.wait(10)
    assert commit(h, CMD(8), winner['preview_id']).json()['command']['revision'] == 2
    released.set()
    worker.join(10)
    assert (result['loser'].status_code, result['loser'].json()['code']) == (409, 'stale_revision')
    assert (h.fake.task_rows()[rid]['排程版本'], h.fake.task_rows()[rid]['命令編號']) == (2, CMD(8))
    assert len(puts(h)) == 1


def test_a_changed_content_or_remapped_account_after_preview_forces_re_preview(h):
    _, first = published(h)
    rid = first['command']['task_id']
    h.clock[0] += 61
    pid = preview(h, task_id=rid, **REASSIGN)['preview_id']
    approve(h, pid)
    h.fake.tables[TASKS][rid]['內容'] = '現場改寫的內容'
    response = commit(h, CMD(2), pid)
    assert (response.status_code, response.json()['code']) == (409, 'preview_stale')

    fresh = preview(h, title='新工作', start='2026-10-27T08:00+08:00', end='2026-10-27T12:00+08:00')
    approve(h, fresh['preview_id'])
    h.fake.tables[PEOPLE]['recP2']['Lark帳號'] = [{'id': 'ou_yi_new'}]
    response = commit(h, CMD(3), fresh['preview_id'])
    assert (response.status_code, response.json()['code']) == (409, 'preview_stale')
    assert puts(h) == [] and len(h.fake.creates()) == 1


def test_reconcile_never_overwrites_a_row_edited_after_the_command(h):
    _, first = published(h)
    rid = first['command']['task_id']
    h.clock[0] += 61
    pid = preview(h, task_id=rid, **REASSIGN)['preview_id']
    approve(h, pid)
    h.fake.on('PUT', f'/records/{rid}', timeout_before)
    assert commit(h, CMD(2), pid).json()['command']['state'] == 'outcome_unknown'
    h.fake.tables[TASKS][rid]['內容'] = '現場改寫的內容'
    body = call(h, 'ou_mgr', 'post', f'/api/v2/commands/{CMD(2)}/reconcile').json()
    assert (body['command']['state'], body['receipt']['changed_since_commit']) == ('reconciliation_required', ['內容'])
    assert h.fake.task_rows()[rid]['內容'] == '現場改寫的內容'
    assert len(puts(h)) == 1


def test_reconcile_resends_an_update_when_the_row_is_still_the_pre_command_snapshot(h):
    _, first = published(h)
    rid = first['command']['task_id']
    h.clock[0] += 61
    pid = preview(h, task_id=rid, **REASSIGN)['preview_id']
    approve(h, pid)
    h.fake.on('PUT', f'/records/{rid}', timeout_before)
    assert commit(h, CMD(2), pid).json()['command']['state'] == 'outcome_unknown'
    body = call(h, 'ou_mgr', 'post', f'/api/v2/commands/{CMD(2)}/reconcile').json()
    assert (body['command']['state'], body['command']['revision']) == ('committed', 2)
    assert (h.fake.task_rows()[rid]['命令編號'], len(puts(h))) == (CMD(2), 2)
    assert 'base' not in body['receipt']


def test_a_date_only_overlap_makes_an_instrument_unknown_until_verified(h):
    h.fake.add(SCHEDULE, 'recS3', {'條類型': '出工', '儀器': ['recI1'], '開始日期': ms('2026-10-20T00:00+08:00'),
                                   '結束日期': ms('2026-10-20T00:00+08:00')})
    body = preview(h)
    assert body['resources'] == [{'kind': 'instrument', 'ref': 'recI1', 'label': 'GNSS-01', 'feasibility': 'unknown',
                                  'reasons': ['same_day_other_slot'], 'verification': None}]
    assert body['blockers'][0] == 'unknown:instrument:recI1'
    assert body['can_commit'] is False
    verified = preview(h, verifications={**PROPOSAL['verifications'], 'instrument:recI1': '同日上午不同時段，已核實'})
    assert [b for b in verified['blockers'] if b.startswith('unknown:')] == []


def test_a_landed_create_whose_response_timed_out_is_one_work_row(h):
    pid = preview(h)['preview_id']
    approve(h, pid)
    h.fake.on('POST', f'/{TASKS}/records', timeout_after)
    assert commit(h, CMD(1), pid).json()['command']['state'] == 'outcome_unknown'
    h.clock[0] += 120
    body = call(h, 'ou_mgr', 'get', '/api/v2/dispatch/work').json()
    assert [(r['source'], r['task_id'], r['command']['state'], r['planning_status'])
            for r in body['rows'] if r['title'] == 'B 區外業'] == [('v4_task', 'recTask0001', 'outcome_unknown', 'publishing')]
    assert body['progress']['total'] == 2
    assert body['progress']['planning_status'] == {'publishing': 1, 'unassigned': 1}


def test_commit_requires_exactly_one_row_with_the_command_id(h):
    pid = preview(h)['preview_id']
    approve(h, pid)

    def duplicated(request, proceed):
        response = proceed()
        h.fake.add(TASKS, 'recDuplicate', dict(h.fake.task_rows()['recTask0001']))
        return response
    h.fake.on('POST', f'/{TASKS}/records', duplicated)
    response = commit(h, CMD(1), pid)
    body = response.json()
    assert (response.status_code, body['command']['state'], body['receipt']['duplicates']) == (
        202, 'reconciliation_required', ['recDuplicate', 'recTask0001'])
    assert {r['state'] for r in body['reservations']} == {'held'}


def test_read_back_compares_timestamps_to_the_millisecond(h):
    pid = preview(h)['preview_id']
    approve(h, pid)

    def shifted(request, proceed):
        response = proceed()
        record = response.json()['data']['record']
        record['fields']['讀回時間'] += 30_000
        return httpx.Response(200, json={'code': 0, 'data': {'record': record}})
    h.fake.on('GET', '/records/recTask0001', shifted)
    body = commit(h, CMD(1), pid).json()
    assert (body['command']['state'], body['receipt']['mismatches']) == ('reconciliation_required', ['讀回時間'])


def test_a_superseded_commit_does_not_block_publishing_the_same_content_again(h):
    _, first = published(h)
    rid = first['command']['task_id']
    other = {**REASSIGN, 'primary_owner': 'recP1', 'crew': ['recP1'], 'start': '2026-10-22T08:00+08:00',
             'end': '2026-10-22T12:00+08:00', 'verifications': {'person:recP1': 'ok'}}
    for step, change in enumerate([REASSIGN, other, REASSIGN], start=2):
        h.clock[0] += 61
        found = preview(h, task_id=rid, **change)
        approve(h, found['preview_id']) if step < 4 else None
        response = commit(h, CMD(step), found['preview_id'])
        assert (response.status_code, response.json()['command']['revision']) == (200, step), response.text
    assert h.fake.task_rows()[rid]['排程版本'] == 4


def test_board_quality_is_partial_when_published_tasks_or_accounts_are_unavailable():
    from .dispatch_board.domain import BoardInput, Window, build_board
    fake = FakeLark()
    seed(fake)
    rows = lambda table, names=None: [fake.render(table, rid, 'list', names) for rid in sorted(fake.tables[table])]
    base = dict(schedule=rows(SCHEDULE), people=rows(PEOPLE, {'姓名', '在職'}),
                instruments=rows(SOURCES['instruments'].table_id), vehicles=rows(SOURCES['vehicles'].table_id),
                cases=rows(SOURCES['cases'].table_id), fetched_at='2026-10-19T02:00:00+00:00', published=True)
    window = Window(date(2026, 10, 20), date(2026, 10, 20))
    healthy = build_board(BoardInput(**base, tasks=rows(TASKS), accounts=rows(PEOPLE, {'Lark帳號'})), window)
    assert healthy['source']['quality'] == {'states': ['complete'], 'reason': None}
    for tasks, accounts, joins in ((None, rows(PEOPLE, {'Lark帳號'}), {'v4_tasks': 'unavailable', 'accounts': 'ok'}),
                                   (rows(TASKS), None, {'v4_tasks': 'ok', 'accounts': 'unavailable'})):
        board = build_board(BoardInput(**base, tasks=tasks, accounts=accounts), window)
        assert board['source']['quality'] == {'states': ['partial'], 'reason': 'incomplete_source_or_joins'}
        assert {k: board['source'][k] for k in joins} == joins


def test_drafts_are_type_checked_and_a_bad_stored_draft_never_breaks_the_queue(h):
    bad = call(h, 'ou_pm', 'put', '/api/v2/dispatch/drafts/draft-0001', {'proposal': {'crew': 1}})
    assert (bad.status_code, bad.json()['code'], bad.json()['field']) == (422, 'invalid', 'crew')
    partial = call(h, 'ou_pm', 'put', '/api/v2/dispatch/drafts/draft-0001',
                   {'proposal': {'title': '半成品', 'start': '2026-10-20T08:00+08:00'}})
    assert partial.status_code == 200
    with h.sessions.begin() as db:
        db.add(DispatchDraftRow(workspace_id='lark-company', id='draft-legacy-1', actor_id='ou_pm', task_id=None,
                                version=1, updated_at=T0, data={'title': '舊草稿', 'crew': 1}))
    response = call(h, 'ou_pm', 'get', '/api/v2/dispatch/work')
    assert response.status_code == 200
    body = response.json()
    assert [(r['source'], r['draft_id'], r['title']) for r in body['rows'] if r['source'] == 'workbench_draft'] == [
        ('workbench_draft', 'draft-0001', '半成品')]
    assert body['gaps'] == [{'code': 'invalid_draft', 'draft_id': 'draft-legacy-1', 'field': 'crew'}]


def test_seat_holders_come_from_the_roster_and_session_without_env(h):
    client = h.build(NO_SEATS)
    body = preview(h, client)
    assert [{k: s[k] for k in ('seat', 'holders', 'names', 'configured', 'source')} for s in body['required_seats']] == [
        {'seat': 'group_leader_confirmed', 'holders': ['recP6'], 'names': ['組長'], 'configured': True, 'source': 'roster'},
        {'seat': 'manager_review', 'holders': ['recP7'], 'names': ['經理'], 'configured': True, 'source': 'roster'},
        {'seat': 'pm_final', 'holders': ['recP8'], 'names': ['派工PM', 'ou_pm2', '專案PM'], 'configured': True,
         'source': 'session'}]
    assert call(h, 'ou_lead', 'get', f"/api/v2/dispatch/previews/{body['preview_id']}", client=client).json()['my_seats'] == [
        'group_leader_confirmed']
    approve(h, body['preview_id'], client)
    assert commit(h, CMD(1), body['preview_id'], client).json()['command']['state'] == 'committed'

    nobody = preview(h, client, department='測繪', title='測繪工作', start='2026-10-28T08:00+08:00',
                     end='2026-10-28T12:00+08:00')
    assert nobody['blockers'][:2] == ['approval_not_configured', 'approval_not_configured:group_leader_confirmed']
    assert [s['names'] for s in nobody['required_seats'][:2]] == [[], ['經理']]
    response = commit(h, CMD(2), nobody['preview_id'], client)
    assert (response.status_code, response.json()['code'], response.json()['seats']) == (
        422, 'approval_not_configured', ['group_leader_confirmed'])

    seats = call(h, 'ou_pm', 'get', '/api/v2/dispatch/options', client=client).json()['seats']
    assert seats[0] == {'seat': 'group_leader_confirmed', 'configured': True, 'source': 'roster',
                        'holders': [{'person_ref': 'recP6', 'name': '組長'}],
                        'by_department': {'外業': [{'person_ref': 'recP6', 'name': '組長'}]}}
    override = h.build({**NO_SEATS, 'DISPATCH_SEAT_GROUP_LEADER': 'ou_jia'})
    assert [(s['holders'], s['source']) for s in preview(h, override)['required_seats']][0] == (['recP1'], 'env')


def test_commit_and_reconcile_revalidate_session_and_gate_right_before_the_write(h, monkeypatch):
    pid = preview(h)['preview_id']
    approve(h, pid)
    h.fake.on('GET', f'/{NODES}/records', lambda request, proceed: (
        h.workspace['settings'].update(external_enabled=False), proceed())[1])
    response = commit(h, CMD(1), pid)
    assert (response.status_code, response.json()['code']) == (403, 'writes_disabled')
    h.workspace['settings']['external_enabled'] = True
    h.fake.on('GET', f'/{NODES}/records', lambda request, proceed: (
        monkeypatch.setitem(ROLES, 'ou_pm', 'member'), proceed())[1])
    response = commit(h, CMD(1), pid)
    assert (response.status_code, response.json()['code']) == (403, 'forbidden')
    assert h.fake.creates() == [] and stored_command(h, CMD(1)) is None
    monkeypatch.setitem(ROLES, 'ou_pm', 'pm')

    h.fake.on('POST', f'/{TASKS}/records', timeout_before)
    assert commit(h, CMD(1), pid).json()['command']['state'] == 'outcome_unknown'
    h.fake.on('POST', f'/{TASKS}/records/search', lambda request, proceed: (
        monkeypatch.setitem(ROLES, 'ou_mgr', 'member'), proceed())[1])
    response = call(h, 'ou_mgr', 'post', f'/api/v2/commands/{CMD(1)}/reconcile')
    assert (response.status_code, response.json()['code']) == (403, 'forbidden')
    assert (stored_command(h, CMD(1)).state, len(h.fake.creates())) == ('outcome_unknown', 1)


def test_an_earlier_unknown_preview_of_a_published_draft_does_not_reappear_in_the_work_queue(h):
    blocked = preview(h, draft_id='draft-0009', title='先未核實', verifications={})
    assert blocked['blockers']
    h.clock[0] += 1
    later = preview(h, draft_id='draft-0009', title='先未核實')
    approve(h, later['preview_id'])
    assert commit(h, CMD(40), later['preview_id']).status_code == 200
    rows = call(h, 'ou_pm', 'get', '/api/v2/dispatch/work?scope=all').json()['rows']
    assert [(r['source'], r['title']) for r in rows if r['title'] == '先未核實'] == [('v4_task', '先未核實')]


def test_a_preview_made_after_the_draft_was_published_still_shows(h):
    first = preview(h, draft_id='draft-0008', title='發布後再改')
    approve(h, first['preview_id'])
    assert commit(h, CMD(41), first['preview_id']).status_code == 200
    h.clock[0] += 5
    again = preview(h, draft_id='draft-0008', title='發布後再改', crew=['recP1'], primary_owner='recP1',
                    verifications={'person:recP1': 'ok'})
    rows = call(h, 'ou_pm', 'get', '/api/v2/dispatch/work?scope=all').json()['rows']
    assert again['preview_id'] in [r.get('preview_id') for r in rows if r['source'] == 'workbench_preview']
