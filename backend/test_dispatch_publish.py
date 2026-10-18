"""Dispatch publish against a fake V4 Bitable. No live Lark requests."""
from datetime import date, datetime
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from .dispatch_board.config import SOURCES
from .dispatch_board.domain import TZ
from .dispatch_publish.routes import register
from .live_read.token_cache import TenantTokenCache
from .models import AuditRow, Base, DispatchReservationRow
from .test_dispatch_publish_fake import (
    PEOPLE, SCHEDULE, TASKS, Crash, FakeLark, crash_after, rejected, timeout_after, timeout_before)

T0 = datetime(2026, 10, 19, 10, 0, tzinfo=TZ).timestamp()
SEATS = {'DISPATCH_SEAT_GROUP_LEADER': 'ou_lead', 'DISPATCH_SEAT_MANAGER_REVIEW': 'ou_mgr', 'DISPATCH_SEAT_PM_FINAL': 'ou_pmf'}
CFG = {'DISPATCH_WRITE_ENABLED': 'true', 'LARK_WORKER_IDENTITY': 'application', 'LARK_APP_ID': 'app-dispatch',
       'LARK_APP_SECRET': 'synthetic', 'LARK_WORKER_ORGANIZATION': 'company', **SEATS}
ROLES = {'ou_pm': 'pm', 'ou_lead': 'member', 'ou_mgr': 'manager', 'ou_pmf': 'pm', 'ou_staff': 'member', 'ou_pm2': 'pm'}
PROPOSAL = {'project_ref': 'DEMO-01', 'case_ref': 'recCase1', 'title': 'B 區外業', 'content': 'B 區水深測量',
            'kind': 'execution', 'phase': 'formal', 'department': '外業', 'primary_owner': 'recP3',
            'crew': ['recP3', 'recP2'], 'start': '2026-10-20T08:00+08:00', 'end': '2026-10-20T12:00+08:00',
            'instruments': ['recI1'],
            'verifications': {'person:recP3': '主管核實 L2 資格', 'person:recP2': '主管核實 L2 資格'}}
APPROVERS = [('ou_lead', 'group_leader_confirmed'), ('ou_mgr', 'manager_review'), ('ou_pmf', 'pm_final')]


def ms(text):
    return int(datetime.fromisoformat(text).timestamp() * 1000)


class NoBucket:
    def acquire(self, deadline):
        pass

    def penalize(self, until):
        pass


def seed(fake):
    for rid, name, ident, active in [('recP1', '甲', 'ou_jia', True), ('recP2', '乙', 'ou_yi', True),
                                     ('recP3', '丙', 'ou_bing', True), ('recP4', '離職', 'ou_gone', False),
                                     ('recP5', '無帳號', None, True)]:
        fake.add(PEOPLE, rid, {'姓名': name, '在職': active, 'Lark帳號': [{'id': ident}] if ident else None})
    fake.add(SOURCES['instruments'].table_id, 'recI1', {'儀器名稱': 'GNSS-01', '啟用': True, '狀態': '正常'})
    fake.add(SOURCES['instruments'].table_id, 'recI2', {'儀器名稱': 'GNSS-02', '啟用': True, '狀態': '送修-損壞'})
    fake.add(SOURCES['vehicles'].table_id, 'recV1', {'車牌': 'SYN-001', '啟用': True})
    fake.add(SOURCES['cases'].table_id, 'recCase1', {'工程確認單編號': 'SYN-001', '工程名稱': '合成示範案'})
    fake.add(SCHEDULE, 'recS1', {'條類型': '出工', '組別': '水深A組', '業別': '外業', '人員': ['recP1'],
                                 '開始日期': ms('2026-10-20T08:00+08:00'), '結束日期': ms('2026-10-20T12:00+08:00'),
                                 '工作內容': 'A 區外業'})
    fake.add(SCHEDULE, 'recS2', {'條類型': '出工', '人員': ['recP1'], '開始日期': ms('2026-10-21T00:00+08:00'),
                                 '結束日期': ms('2026-10-21T00:00+08:00')})
    fake.add(SOURCES['nodes'].table_id, 'recN1', {'節點': '外業', '確認單編號': 'SYN-001'})
    fake.add(TASKS, 'recLegacy', {'標題': '外業：待指派', '狀態': '待處理', '節點指派': ['recN1'],
                                  '指派人': [{'id': 'ou_pm'}], '部門': '外業', '截止日': ms('2026-10-25T00:00+08:00')})


@pytest.fixture
def h(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path}/dispatch.db', connect_args={'check_same_thread': False, 'timeout': 20})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    fake = FakeLark()
    seed(fake)
    clock, who = [T0], ['ou_pm']
    workspace = {'settings': {'external_enabled': True}, 'environment': 'production'}

    def identity(_request):
        return {'mode': 'lark', 'wid': 'lark-company'}, {'id': who[0], 'role': ROLES[who[0]], 'active': True}

    def build(overrides=None, store=None):
        app = FastAPI()
        register(app, identity=identity, allow=lambda _d, user: user['role'] in ('pm', 'manager'),
                 cfg={**CFG, **(overrides or {})}, sessions=store or sessions, audit_model=AuditRow,
                 workspace=lambda _wid: workspace, transport=httpx.MockTransport(fake),
                 client_options={'token_cache': TenantTokenCache(), 'bucket': NoBucket(), 'sleep': lambda _s: None},
                 clock=lambda: clock[0])
        return TestClient(app)

    def audits():
        with sessions() as db:
            return [r.action for r in db.scalars(select(AuditRow).order_by(AuditRow.created_at, AuditRow.id))]

    def held():
        with sessions() as db:
            return sorted((r.resource_kind, r.ref, r.state, r.command_id, r.task_id)
                          for r in db.scalars(select(DispatchReservationRow)))

    yield SimpleNamespace(client=build(), build=build, fake=fake, clock=clock, who=who, workspace=workspace,
                          audits=audits, held=held, sessions=sessions, url=f'sqlite:///{tmp_path}/dispatch.db')
    engine.dispose()


def call(h, who, method, path, body=None, client=None):
    h.who[0] = who
    return getattr(client or h.client, method)(path, **({'json': body} if body is not None else {}))


def preview(h, client=None, **changes):
    response = call(h, 'ou_pm', 'post', '/api/v2/dispatch/previews', {**PROPOSAL, **changes}, client)
    assert response.status_code == 200, response.text
    return response.json()


def approve(h, preview_id, client=None):
    for who, seat in APPROVERS:
        response = call(h, who, 'post', f'/api/v2/dispatch/previews/{preview_id}/decisions',
                        {'seat': seat, 'decision': 'accepted'}, client)
        assert response.status_code == 200, response.text
    return response.json()


def commit(h, command_id, preview_id, client=None):
    return call(h, 'ou_pm', 'post', '/api/v2/dispatch/commits', {'command_id': command_id, 'preview_id': preview_id}, client)


def published(h, command_id='cmd-publish-0001', **changes):
    found = preview(h, **changes)
    approve(h, found['preview_id'])
    response = commit(h, command_id, found['preview_id'])
    assert response.status_code == 200, response.text
    return found, response.json()


EXPECTED_ROW = {
    '標題': 'B 區外業', '內容': 'B 區水深測量', '負責人': [{'id': 'ou_bing'}], '指派人': [{'id': 'ou_pm'}],
    '部門': '外業', '專案編號': 'DEMO-01', '工程確認單': ['recCase1'], '任務階段': '正式', '任務種類': '執行',
    '預定開始': ms('2026-10-20T08:00+08:00'), '預定結束': ms('2026-10-20T12:00+08:00'), '預估人時': 8.0,
    '組員': [{'id': 'ou_yi'}], '使用儀器': ['recI1'], '排程狀態': '已確認', '排程版本': 1,
    '命令編號': 'cmd-publish-0001', '讀回時間': int(T0 * 1000), '狀態': '待處理'}


def test_flag_off_answers_404_on_every_route_and_reads_nothing(h):
    client = h.build({'DISPATCH_WRITE_ENABLED': 'false'})
    paths = [('post', '/api/v2/dispatch/previews'), ('get', '/api/v2/dispatch/previews/pv_x'),
             ('post', '/api/v2/dispatch/previews/pv_x/decisions'), ('post', '/api/v2/dispatch/commits'),
             ('get', '/api/v2/commands/cmd-x'), ('post', '/api/v2/commands/cmd-x/reconcile'),
             ('get', '/api/v2/dispatch/work'), ('put', '/api/v2/dispatch/drafts/draft-0001'),
             ('get', '/api/v2/dispatch/options')]
    assert [getattr(client, m)(p).status_code for m, p in paths] == [404] * len(paths)
    board_only = h.build({'DISPATCH_WRITE_ENABLED': 'false', 'DISPATCH_BOARD_ENABLED': 'true'})
    assert board_only.post('/api/v2/dispatch/previews', json=PROPOSAL).status_code == 404
    assert board_only.get('/api/v2/dispatch/work').status_code == 200
    assert h.fake.writes() == []


def test_preview_reports_conflict_unknown_and_eight_person_hours(h):
    body = preview(h, crew=['recP3', 'recP2', 'recP1'], verifications={})
    assert body['hours'] == 4.0
    assert body['booked_person_hours'] == 12.0
    assert [(c['person_ref'], c['feasibility'], c['reasons']) for c in body['crew']] == [
        ('recP3', 'unknown', ['no_leave_source', 'no_capability_source']),
        ('recP2', 'unknown', ['no_leave_source', 'no_capability_source']),
        ('recP1', 'conflict', ['no_leave_source', 'no_capability_source', 'timed_overlap'])]
    assert body['conflicts'] == [{'kind': 'person', 'ref': 'recP1', 'feasibility': 'conflict',
                                  'other': {'source': 'schedule', 'id': 'recS1', 'task_id': None, 'title': 'A 區外業'},
                                  'interval': {'start': '2026-10-20T08:00:00+08:00', 'end': '2026-10-20T12:00:00+08:00',
                                               'precision': 'datetime'}}]
    assert body['resources'] == [{'kind': 'instrument', 'ref': 'recI1', 'label': 'GNSS-01', 'feasibility': 'feasible',
                                  'reasons': [], 'verification': None}]
    assert body['blockers'] == ['unknown:person:recP3', 'unknown:person:recP2', 'conflict:person:recP1',
                                'approval_missing:group_leader_confirmed', 'approval_missing:manager_review',
                                'approval_missing:pm_final']
    assert body['can_commit'] is False
    fixed = preview(h)
    assert fixed['booked_person_hours'] == 8.0
    assert [c['verification'] for c in fixed['crew']] == ['主管核實 L2 資格', '主管核實 L2 資格']
    assert fixed['blockers'] == ['approval_missing:group_leader_confirmed', 'approval_missing:manager_review',
                                 'approval_missing:pm_final']


def test_unavailable_people_and_resources_and_missing_accounts_block(h):
    body = preview(h, crew=['recP3', 'recP4', 'recP5'], instruments=['recI2'], verifications={
        'person:recP3': 'ok', 'person:recP5': 'ok'})
    assert body['blockers'][:4] == ['unavailable:person:recP4', 'person_without_lark_account:recP5',
                                    'unavailable:instrument:recI2', 'approval_missing:group_leader_confirmed']


def test_same_content_reuses_preview_and_a_changed_field_voids_decisions(h):
    first = preview(h)
    assert preview(h)['preview_id'] == first['preview_id']
    response = call(h, 'ou_lead', 'post', f"/api/v2/dispatch/previews/{first['preview_id']}/decisions",
                    {'seat': 'group_leader_confirmed', 'decision': 'accepted'})
    assert response.json()['required_seats'][0] | {'at': None} == {
        'seat': 'group_leader_confirmed', 'holders': ['ou_lead'], 'decision': 'accepted', 'actor': 'ou_lead',
        'reason': None, 'at': None}
    changed = preview(h, end='2026-10-20T12:15+08:00')
    assert changed['preview_hash'] != first['preview_hash']
    assert [s['decision'] for s in changed['required_seats']] == [None, None, None]
    assert [s['decision'] for s in preview(h)['required_seats']] == ['accepted', None, None]


def test_seat_rules_holder_order_one_seat_per_person_and_return(h):
    client = h.build({'DISPATCH_SEAT_MANAGER_REVIEW': 'ou_lead,ou_mgr'})
    pid = preview(h, client)['preview_id']
    url = f'/api/v2/dispatch/previews/{pid}/decisions'
    refused = lambda who, seat: call(h, who, 'post', url, {'seat': seat, 'decision': 'accepted'}, client).json()['reason']
    assert refused('ou_pmf', 'group_leader_confirmed') == 'not_seat_holder'
    assert refused('ou_mgr', 'manager_review') == 'earlier_seat_pending'
    assert call(h, 'ou_lead', 'post', url, {'seat': 'group_leader_confirmed', 'decision': 'accepted'}, client).status_code == 200
    assert refused('ou_lead', 'manager_review') == 'actor_holds_another_seat'
    assert call(h, 'ou_mgr', 'post', url, {'seat': 'manager_review', 'decision': 'returned'}, client).status_code == 422
    returned = call(h, 'ou_mgr', 'post', url, {'seat': 'manager_review', 'decision': 'returned', 'reason': '時段太早'}, client)
    assert returned.json()['blockers'] == ['approval_returned', 'approval_missing:manager_review', 'approval_missing:pm_final']
    assert refused('ou_pmf', 'pm_final') == 'hash_returned'
    assert call(h, 'ou_staff', 'get', f'/api/v2/dispatch/previews/{pid}', client=client).status_code == 403


def test_commit_publishes_one_task_row_after_read_back(h):
    found, body = published(h)
    rid = body['command']['task_id']
    assert h.fake.task_rows()[rid] == EXPECTED_ROW
    assert body['command'] | {'created_at': None, 'updated_at': None} == {
        'command_id': 'cmd-publish-0001', 'preview_id': found['preview_id'], 'preview_hash': found['preview_hash'],
        'action': 'create', 'task_id': rid, 'actor_id': 'ou_pm', 'state': 'committed', 'label': '已確認',
        'planning_status': 'confirmed', 'revision': 1, 'created_at': None, 'updated_at': None}
    assert body['receipt'] == {'record_id': rid, 'read_back_at': '2026-10-19T02:00:00+00:00', 'mismatches': [], 'revision': 1}
    assert body['next_action'] == 'none'
    assert [(r['resource_kind'], r['ref'], r['state'], r['task_id']) for r in body['reservations']] == [
        ('instrument', 'recI1', 'held', rid), ('person', 'recP2', 'held', rid), ('person', 'recP3', 'held', rid)]
    assert [q['client_token'] for _, _, q in h.fake.creates()] == ['cmd-publish-0001']
    assert h.audits() == ['dispatch.preview', 'dispatch.decision', 'dispatch.decision', 'dispatch.decision',
                          'dispatch.command.pending', 'dispatch.command.committed']


def test_same_command_id_replays_the_stored_result_without_a_second_write(h):
    found, first = published(h)
    again = commit(h, 'cmd-publish-0001', found['preview_id'])
    assert (again.status_code, again.headers['Idempotent-Replayed'], again.json()) == (200, 'true', first)
    assert len(h.fake.creates()) == 1
    other = commit(h, 'cmd-publish-0002', found['preview_id'])
    assert (other.status_code, other.json()['code'], other.json()['command_id']) == (409, 'duplicate_command', 'cmd-publish-0001')
    reused = commit(h, 'cmd-publish-0001', 'pv_other')
    assert (reused.status_code, reused.json()['code']) == (409, 'idempotency_conflict')


def test_external_connection_off_blocks_commit_before_any_remote_call(h):
    pid = preview(h)['preview_id']
    approve(h, pid)
    h.fake.requests.clear()
    h.workspace['settings']['external_enabled'] = False
    response = commit(h, 'cmd-publish-0001', pid)
    assert (response.status_code, response.json()['code']) == (403, 'writes_disabled')
    assert h.fake.requests == []
    assert preview(h)['can_commit'] is False


def test_unknown_blocks_by_default_and_allow_unknown_relaxes_it(h):
    pid = preview(h, verifications={})['preview_id']
    approve(h, pid)
    response = commit(h, 'cmd-publish-0001', pid)
    assert (response.status_code, response.json()['blockers']) == (422, ['unknown:person:recP3', 'unknown:person:recP2'])
    assert h.fake.writes() == []
    relaxed = h.build({'DISPATCH_ALLOW_UNKNOWN': 'true'})
    body = preview(h, relaxed, verifications={})
    assert body['warnings'] == ['no_capability_source', 'no_leave_source', 'unverified_unknown:person:recP3',
                                'unverified_unknown:person:recP2']
    assert commit(h, 'cmd-publish-0002', body['preview_id'], relaxed).status_code == 200


def test_missing_seat_holders_and_direct_policy(h):
    unconfigured = h.build({'DISPATCH_SEAT_PM_FINAL': ''})
    pid = preview(h, unconfigured)['preview_id']
    response = commit(h, 'cmd-publish-0001', pid, unconfigured)
    assert (response.status_code, response.json()['code']) == (422, 'approval_not_configured')
    direct = h.build({'DISPATCH_APPROVAL_POLICY': 'direct'})
    body = preview(h, direct)
    assert (body['required_seats'], body['blockers'], body['can_commit']) == ([], [], True)
    assert commit(h, 'cmd-publish-0002', body['preview_id'], direct).json()['command']['state'] == 'committed'


def test_timeout_after_remote_success_then_reconcile_commits_one_row(h):
    pid = preview(h)['preview_id']
    approve(h, pid)
    h.fake.on('POST', f'/{TASKS}/records', timeout_after)
    response = commit(h, 'cmd-publish-0001', pid)
    body = response.json()
    assert (response.status_code, body['command']['state'], body['command']['planning_status'], body['command']['label']) == (
        202, 'outcome_unknown', 'publishing', '結果未知')
    assert {r['state'] for r in body['reservations']} == {'held'}
    assert call(h, 'ou_pm', 'get', '/api/v2/commands/cmd-publish-0001').json()['next_action'] == 'none'
    assert call(h, 'ou_mgr', 'get', '/api/v2/commands/cmd-publish-0001').json()['next_action'] == 'reconcile'
    assert call(h, 'ou_pm', 'post', '/api/v2/commands/cmd-publish-0001/reconcile').status_code == 403
    resolved = call(h, 'ou_mgr', 'post', '/api/v2/commands/cmd-publish-0001/reconcile')
    assert (resolved.status_code, resolved.json()['command']['state']) == (200, 'committed')
    rows = h.fake.task_rows()
    assert [rid for rid, f in rows.items() if f.get('命令編號') == 'cmd-publish-0001'] == [resolved.json()['command']['task_id']]
    assert len(h.fake.creates()) == 1


def test_nothing_landed_reconcile_resends_with_the_same_client_token(h):
    pid = preview(h)['preview_id']
    approve(h, pid)
    h.fake.on('POST', f'/{TASKS}/records', timeout_before)
    assert commit(h, 'cmd-publish-0001', pid).json()['command']['state'] == 'outcome_unknown'
    resolved = call(h, 'ou_mgr', 'post', '/api/v2/commands/cmd-publish-0001/reconcile')
    assert resolved.json()['command']['state'] == 'committed'
    assert [q['client_token'] for _, _, q in h.fake.creates()] == ['cmd-publish-0001', 'cmd-publish-0001']
    assert len([f for f in h.fake.task_rows().values() if f.get('命令編號')]) == 1


def test_read_back_mismatch_requires_reconciliation_and_is_never_overwritten(h):
    pid = preview(h)['preview_id']
    approve(h, pid)

    def edited(request, proceed):
        response = proceed()
        record = response.json()['data']['record']
        record['fields']['預定結束'] = ms('2026-10-20T13:00+08:00')
        return httpx.Response(200, json={'code': 0, 'data': {'record': record}})
    h.fake.on('GET', '/records/recTask0001', edited)
    response = commit(h, 'cmd-publish-0001', pid)
    body = response.json()
    assert (response.status_code, body['command']['state'], body['command']['planning_status']) == (
        202, 'reconciliation_required', 'conflict')
    assert body['receipt']['mismatches'] == ['預定結束']
    assert {r['state'] for r in body['reservations']} == {'held'}
    rid = body['command']['task_id']
    h.fake.tables[TASKS][rid]['預定結束'] = ms('2026-10-20T13:00+08:00')
    writes = len(h.fake.writes())
    again = call(h, 'ou_mgr', 'post', '/api/v2/commands/cmd-publish-0001/reconcile')
    assert (again.json()['command']['state'], again.json()['receipt']['mismatches']) == ('reconciliation_required', ['預定結束'])
    assert len(h.fake.writes()) == writes


def test_partial_row_is_reconciliation_required(h):
    pid = preview(h)['preview_id']
    approve(h, pid)

    def partial(request, proceed):
        response = proceed()
        rid = response.json()['data']['record']['record_id']
        h.fake.tables[TASKS][rid].pop('組員')
        return response
    h.fake.on('POST', f'/{TASKS}/records', partial)
    body = commit(h, 'cmd-publish-0001', pid).json()
    assert (body['command']['state'], body['receipt']['mismatches']) == ('reconciliation_required', ['組員'])


def test_error_before_landing_fails_and_releases_reservations(h):
    pid = preview(h)['preview_id']
    approve(h, pid)
    h.fake.on('POST', f'/{TASKS}/records', rejected)
    response = commit(h, 'cmd-publish-0001', pid)
    assert (response.status_code, response.json()['command']['state'], response.json()['receipt']['error']) == (
        502, 'failed', 'lark_error')
    assert {r['state'] for r in response.json()['reservations']} == {'released'}
    assert h.fake.task_rows().keys() == {'recLegacy'}
    assert commit(h, 'cmd-publish-0002', pid).json()['command']['state'] == 'committed'


def test_duplicate_rows_for_one_command_require_reconciliation(h):
    pid = preview(h)['preview_id']
    approve(h, pid)
    h.fake.on('POST', f'/{TASKS}/records', timeout_after)
    commit(h, 'cmd-publish-0001', pid)
    h.fake.add(TASKS, 'recDuplicate', dict(next(f for f in h.fake.task_rows().values() if f.get('命令編號'))))
    body = call(h, 'ou_mgr', 'post', '/api/v2/commands/cmd-publish-0001/reconcile').json()
    assert (body['command']['state'], body['receipt']['duplicates']) == (
        'reconciliation_required', ['recDuplicate', 'recTask0001'])


def test_restart_mid_command_keeps_pending_until_reconciled(h):
    pid = preview(h)['preview_id']
    approve(h, pid)
    h.fake.on('POST', f'/{TASKS}/records', crash_after)
    with pytest.raises(Crash):
        commit(h, 'cmd-publish-0001', pid)
    restarted = h.build()
    view = call(h, 'ou_mgr', 'get', '/api/v2/commands/cmd-publish-0001', client=restarted).json()
    assert (view['command']['state'], view['command']['label'], view['next_action']) == ('pending', '處理中', 'none')
    early = call(h, 'ou_mgr', 'post', '/api/v2/commands/cmd-publish-0001/reconcile', client=restarted)
    assert (early.status_code, early.json()['code']) == (409, 'busy')
    h.clock[0] += 61
    resolved = call(h, 'ou_mgr', 'post', '/api/v2/commands/cmd-publish-0001/reconcile', client=restarted)
    assert (resolved.status_code, resolved.json()['command']['state']) == (200, 'committed')
    assert len(h.fake.creates()) == 1


def test_reassign_keeps_task_and_obligation_bumps_revision_and_releases_after_read_back(h):
    _, first = published(h)
    rid = first['command']['task_id']
    observed = []

    def read_back(request, proceed):
        observed.append(h.held())
        return proceed()
    h.fake.on('GET', f'/records/{rid}', read_back)
    _, second = published(h, 'cmd-reassign-0001', task_id=rid, primary_owner='recP2', crew=['recP2'],
                          start='2026-10-20T13:00+08:00', end='2026-10-20T17:00+08:00',
                          verifications={'person:recP2': '主管核實 L2 資格'})
    assert (second['command']['action'], second['command']['task_id'], second['command']['revision']) == ('update', rid, 2)
    row = h.fake.task_rows()[rid]
    assert (row['負責人'], row.get('組員'), row['排程版本'], row['命令編號'], row['狀態']) == (
        [{'id': 'ou_yi'}], None, 2, 'cmd-reassign-0001', '待處理')
    assert observed == [[('instrument', 'recI1', 'held', 'cmd-publish-0001', rid),
                         ('instrument', 'recI1', 'held', 'cmd-reassign-0001', rid),
                         ('person', 'recP2', 'held', 'cmd-publish-0001', rid),
                         ('person', 'recP2', 'held', 'cmd-reassign-0001', rid),
                         ('person', 'recP3', 'held', 'cmd-publish-0001', rid)]]
    assert h.held() == [('instrument', 'recI1', 'held', 'cmd-reassign-0001', rid),
                        ('instrument', 'recI1', 'released', 'cmd-publish-0001', rid),
                        ('person', 'recP2', 'held', 'cmd-reassign-0001', rid),
                        ('person', 'recP2', 'released', 'cmd-publish-0001', rid),
                        ('person', 'recP3', 'released', 'cmd-publish-0001', rid)]
    row = next(r for r in call(h, 'ou_pm', 'get', '/api/v2/dispatch/work').json()['rows'] if r['task_id'] == rid)
    assert (row['command']['command_id'], row['revision'], row['owner']['person_ref']) == ('cmd-reassign-0001', 2, 'recP2')
    moved = preview(h, task_id=rid, parent_task_ref='recLegacy')
    h.fake.tables[TASKS][rid]['父義務'] = ['recObligation']
    h.clock[0] += 61
    assert 'obligation_changed' in preview(h, task_id=rid, parent_task_ref='recLegacy')['blockers']
    assert 'obligation_changed' not in moved['blockers']


def test_published_task_occupies_the_interval_for_later_previews(h):
    _, first = published(h)
    later = preview(h, title='另一件', crew=['recP3'], verifications={'person:recP3': 'ok'})
    assert [(c['ref'], c['other']['source'], c['other']['task_id']) for c in later['conflicts']] == [
        ('recP3', 'v4_task', first['command']['task_id']), ('recI1', 'v4_task', first['command']['task_id'])]
    assert later['blockers'][:2] == ['conflict:person:recP3', 'conflict:instrument:recI1']


def test_drafts_persist_without_occupying_capacity(h):
    saved = call(h, 'ou_pm', 'put', '/api/v2/dispatch/drafts/draft-0001', {'proposal': {'title': '半成品', 'crew': ['recP3']}})
    assert saved.json() | {'updated_at': None} == {'id': 'draft-0001', 'actor_id': 'ou_pm', 'task_id': None, 'version': 1,
                                                   'updated_at': None, 'proposal': {'title': '半成品', 'crew': ['recP3']}}
    stale = call(h, 'ou_pm', 'put', '/api/v2/dispatch/drafts/draft-0001', {'proposal': {'title': 'x'}, 'version': 0})
    assert (stale.status_code, stale.json()['code']) == (409, 'version_conflict')
    assert call(h, 'ou_pm2', 'get', '/api/v2/dispatch/drafts/draft-0001').status_code == 404
    assert call(h, 'ou_pm', 'get', '/api/v2/dispatch/drafts').json()['drafts'][0]['id'] == 'draft-0001'
    assert preview(h)['conflicts'] == []
    assert call(h, 'ou_pm', 'delete', '/api/v2/dispatch/drafts/draft-0001').status_code == 200
    assert call(h, 'ou_pm', 'get', '/api/v2/dispatch/drafts/draft-0001').status_code == 404


def test_work_queue_rows_progress_and_needs_me(h):
    _, done = published(h)
    pending = preview(h, title='C 區外業', crew=['recP2'], primary_owner='recP2', start='2026-10-22T08:00+08:00',
                      end='2026-10-22T12:00+08:00', verifications={'person:recP2': 'ok'}, draft_id='draft-0002')
    leader = call(h, 'ou_lead', 'get', '/api/v2/dispatch/work').json()
    assert leader['progress'] == {'total': 3, 'status': {'unknown': 1, '待處理': 2},
                                  'planning_status': {'pending_approval': 1, 'confirmed': 1, 'unassigned': 1}, 'needs_me': 1}
    queued = leader['needs_me'][0]
    assert (queued['source'], queued['preview_id'], queued['needs_me'], queued['allowed_actions']) == (
        'workbench_preview', pending['preview_id'], ['approve_seat:group_leader_confirmed'], ['approve', 'return'])
    pm = call(h, 'ou_pm', 'get', '/api/v2/dispatch/work').json()
    legacy = next(r for r in pm['rows'] if r['task_id'] == 'recLegacy')
    assert (legacy['needs_me'], legacy['allowed_actions'], legacy['node'], legacy['deadline']) == (
        ['confirm_assignment'], ['assign', 'edit_detail'], {'record_id': 'recN1', 'label': '外業'}, '2026-10-25')
    confirmed = next(r for r in pm['rows'] if r['task_id'] == done['command']['task_id'])
    assert {k: confirmed[k] for k in ('title', 'kind', 'phase', 'status', 'planning_status', 'revision', 'interval',
                                      'owner', 'crew', 'instruments', 'case', 'command', 'allowed_actions')} == {
        'title': 'B 區外業', 'kind': 'execution', 'phase': 'formal', 'status': '待處理', 'planning_status': 'confirmed',
        'revision': 1, 'interval': {'start': '2026-10-20T08:00:00+08:00', 'end': '2026-10-20T12:00:00+08:00',
                                    'precision': 'datetime'},
        'owner': {'person_ref': 'recP3', 'open_id': 'ou_bing', 'name': '丙'},
        'crew': [{'person_ref': 'recP3', 'open_id': 'ou_bing', 'name': '丙'},
                 {'person_ref': 'recP2', 'open_id': 'ou_yi', 'name': '乙'}],
        'instruments': [{'ref': 'recI1', 'label': 'GNSS-01'}],
        'case': {'ref': 'recCase1', 'code': 'SYN-001', 'name': '合成示範案', 'resolved': True},
        'command': {'command_id': 'cmd-publish-0001', 'state': 'committed', 'label': '已確認'},
        'allowed_actions': ['reassign', 'edit_detail']}
    assert len(pm['needs_me']) == sum(1 for r in pm['rows'] if r['needs_me'])
    assert call(h, 'ou_staff', 'get', '/api/v2/dispatch/work').status_code == 403


def test_work_queue_flags_unknown_commands_for_managers_and_keeps_last_good_on_failure(h):
    pid = preview(h)['preview_id']
    approve(h, pid)
    h.fake.on('POST', f'/{TASKS}/records', timeout_after)
    commit(h, 'cmd-publish-0001', pid)
    first = call(h, 'ou_mgr', 'get', '/api/v2/dispatch/work').json()
    unknown = next(r for r in first['rows'] if r['command'])
    assert (unknown['planning_status'], unknown['needs_me'], unknown['allowed_actions']) == (
        'publishing', ['reconcile_command'], ['reconcile'])
    h.clock[0] += 120
    h.fake.on('GET', f'/{TASKS}/records', lambda request, proceed: httpx.Response(500), times=10)
    stale = call(h, 'ou_mgr', 'get', '/api/v2/dispatch/work').json()
    assert stale['source']['quality'] == {'states': ['stale'], 'reason': 'refreshing_last_good_snapshot', 'age_seconds': 120}
    assert stale['rows'] == first['rows']


def test_work_queue_cold_read_failure_has_no_counts(h):
    h.fake.on('GET', f'/{TASKS}/records', lambda request, proceed: httpx.Response(500), times=10)
    response = call(h, 'ou_pm', 'get', '/api/v2/dispatch/work')
    assert (response.status_code, response.json()) == (503, {'source': {'quality': {'states': ['read_failed'],
                                                                                    'reason': 'tasks_read_failed'}}})


def test_task_form_prefills_the_21_fields_and_marks_system_fields_read_only(h):
    _, done = published(h)
    rid = done['command']['task_id']
    body = call(h, 'ou_pm', 'get', f'/api/v2/dispatch/tasks/{rid}').json()
    assert body['proposal'] == {**PROPOSAL, 'task_id': rid, 'package_id': None, 'parent_task_ref': None,
                                'start': '2026-10-20T08:00+08:00', 'end': '2026-10-20T12:00+08:00',
                                'est_person_hours': 8.0, 'vehicles': [], 'deadline': None, 'verifications': {}}
    assert body['system'] == {'scope_version': None, 'rule_version': None, 'evidence_version': None,
                              'planning_status': '已確認', 'revision': 1, 'command_id': 'cmd-publish-0001',
                              'readback_at': '2026-10-19T10:00+08:00', 'acceptance_status': None,
                              'acceptance_summary': None}
    assert [f['v4_field'] for f in body['form_fields'] if not f['editable']] == [
        '範圍版本', '規則版本', '證據版本', '排程狀態', '排程版本', '命令編號', '讀回時間', '成果接受狀態', '接受摘要']
    assert body['unmapped_people'] == []


def test_options_list_people_resources_and_cases(h):
    body = call(h, 'ou_pm', 'get', '/api/v2/dispatch/options').json()
    assert body['people'][3:] == [{'person_ref': 'recP4', 'name': '離職', 'active': False, 'has_lark_account': True},
                                  {'person_ref': 'recP5', 'name': '無帳號', 'active': True, 'has_lark_account': False}]
    assert body['instruments'] == [{'ref': 'recI1', 'label': 'GNSS-01', 'feasibility': 'feasible'},
                                   {'ref': 'recI2', 'label': 'GNSS-02', 'feasibility': 'unavailable'}]
    assert body['cases'] == [{'ref': 'recCase1', 'code': 'SYN-001', 'name': '合成示範案'}]


def test_invalid_proposals_are_rejected_at_the_boundary(h):
    cases = [({'title': ''}, 'title'), ({'start': '2026-10-20T08:00'}, 'start'),
             ({'end': '2026-10-20T07:00+08:00'}, 'end'), ({'crew': ['not-a-ref']}, 'crew'),
             ({'verifications': {'person:recP9': 'x'}}, 'verifications'), ({'table_id': 'tblOther'}, 'table_id')]
    for change, field in cases:
        response = call(h, 'ou_pm', 'post', '/api/v2/dispatch/previews', {**PROPOSAL, **change})
        assert (response.status_code, response.json()['field']) == (422, field)
    assert call(h, 'ou_staff', 'post', '/api/v2/dispatch/previews', PROPOSAL).status_code == 403


def test_task_writer_refuses_fields_outside_the_allowlist():
    from .dispatch_publish.lark_task import TaskTable
    fake = FakeLark()
    table = TaskTable(CFG, 'H7W6b0PFWaVF1BsgqXJj3pQ9pXb', httpx.MockTransport(fake))
    with pytest.raises(ValueError, match='成果接受狀態'):
        table.create({'標題': 'x', '成果接受狀態': '已接受'}, 'cmd-allowlist-01')
    assert fake.requests == []


def test_board_shows_published_tasks_as_v4_task_slots_that_conflict_with_schedule_rows():
    from .dispatch_board.domain import BoardInput, Window, build_board
    fake = FakeLark()
    seed(fake)
    fake.add(TASKS, 'recPub', {**EXPECTED_ROW, '負責人': [{'id': 'ou_jia'}], '組員': None})
    fake.add(TASKS, 'recDraft', {**EXPECTED_ROW, '排程狀態': '草稿'})
    rows = lambda table, names=None: [fake.render(table, rid, 'list', names) for rid in sorted(fake.tables[table])]
    data = BoardInput(rows(SCHEDULE), rows(PEOPLE, {'姓名', '在職'}), rows(SOURCES['instruments'].table_id),
                      rows(SOURCES['vehicles'].table_id), rows(SOURCES['cases'].table_id), fetched_at='2026-10-19T02:00:00+00:00',
                      tasks=rows(TASKS), accounts=rows(PEOPLE, {'Lark帳號'}), published=True)
    board = build_board(data, Window(date(2026, 10, 20), date(2026, 10, 20)))
    published_slot = next(s for s in board['slots'] if s['provenance'] == 'v4_task')
    assert {k: published_slot[k] for k in ('slot_id', 'kind', 'planning_status', 'interval', 'group', 'case', 'work_content', 'issues')} == {
        'slot_id': 'v4:tblsoyGcC6K5AipF:recPub', 'kind': 'execution', 'planning_status': 'confirmed',
        'interval': {'start': '2026-10-20T08:00:00+08:00', 'end': '2026-10-20T12:00:00+08:00', 'precision': 'datetime'},
        'group': '外業', 'case': {'ref': 'recCase1', 'code': 'SYN-001', 'name': '合成示範案'}, 'work_content': 'B 區外業',
        'issues': ['v4:tblZz6Mkhv9gHrB2:recS1']}
    assert [(c['person_ref'], c['name'], c['feasibility']) for c in published_slot['crew']] == [('recP1', '甲', 'conflict')]
    assert [s['record_id'] for s in board['slots']] == ['recS1', 'recPub']
    assert board['kpi'] == {'slots': 2, 'unassigned': 0, 'unknown_overlap': 0, 'conflict': 2}
    assert board['source']['v4_tasks'] == 'ok'
    assert 'v4_tasks' not in build_board(BoardInput(rows(SCHEDULE), None, None, None, None, fetched_at=''),
                                         Window(date(2026, 10, 20), date(2026, 10, 20)))['source']


def test_work_queue_hides_abandoned_previews_and_asks_no_approval_of_blocked_ones(h):
    preview(h, title='未核實', verifications={})
    decided = preview(h, title='已有決定')
    call(h, 'ou_lead', 'post', f"/api/v2/dispatch/previews/{decided['preview_id']}/decisions",
         {'seat': 'group_leader_confirmed', 'decision': 'accepted'})
    rows = call(h, 'ou_lead', 'get', '/api/v2/dispatch/work').json()['rows']
    assert [(r['title'], r['needs_me']) for r in rows if r['source'] == 'workbench_preview'] == [
        ('已有決定', []), ('未核實', [])]
    h.clock[0] += 901
    rows = call(h, 'ou_mgr', 'get', '/api/v2/dispatch/work').json()['rows']
    assert [(r['title'], r['needs_me']) for r in rows if r['source'] == 'workbench_preview'] == [
        ('已有決定', ['approve_seat:manager_review'])]
