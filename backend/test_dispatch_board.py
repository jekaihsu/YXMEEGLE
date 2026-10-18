"""Synthetic dispatch acceptance cases. No live Lark requests."""
from copy import deepcopy
from datetime import date, datetime
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import httpx
import pytest

from .dispatch_board.config import TABLES
from .dispatch_board.domain import BoardInput, TZ, Window, build_board
from .dispatch_board.lark_table import DispatchReader
from .dispatch_board.routes import register, parameters, URL
from .dispatch_board.service import DispatchBoardService
from .live_read.client import ReadBlocked, ReadFailure
from .live_read.token_cache import TenantTokenCache
from scripts.verify_dispatch_sources import main as verify_main, verify


AT = '2026-07-27T00:00:00+00:00'
WINDOW = Window(date(2026, 7, 27), date(2026, 7, 28))


def row(rid, **fields):
    return {'record_id': rid, 'fields': fields}


def work(rid, start='2026-07-27', end=None, **fields):
    return row(rid, **{'條類型': '出工', '開始日期': start, '結束日期': end or start,
                      '組別': '水深A組', '業別': '外業', '案件': ['recCase'], '人員': ['recActive'],
                      '儀器': ['recInstrument'], **fields})


def source(schedule):
    return BoardInput(schedule=schedule,
                      people=[row('recActive', 姓名='合成人員', 在職=True), row('recInactive', 姓名='離職人員', 在職=False)],
                      instruments=[row('recInstrument', 儀器名稱='合成儀器', 啟用=True, 狀態='正常'),
                                   row('recRepair', 儀器名稱='送修儀器', 啟用=True, 狀態='送修-損壞')],
                      vehicles=[row('recVehicle', 車牌='SYNTHETIC', 啟用=False)],
                      cases=[row('recCase', 工程確認單編號='SYN-001', 工程名稱='Synthetic dispatch demonstration')],
                      fetched_at=AT)


def acceptance_source():
    return source([
        work('recUnassigned', 人員=[], 案件=[], 儀器=[]),
        work('recTimedA', '2026-07-27T09:00:00+08:00', '2026-07-27T11:00:00+08:00', 儀器=[]),
        work('recTimedB', '2026-07-27T10:00:00+08:00', '2026-07-27T12:00:00+08:00', 儀器=[]),
        work('recDateA', '2026-07-28', 人員=['recDatePerson'], 儀器=[]),
        work('recDateB', '2026-07-28', 人員=['recDatePerson'], 儀器=[]),
        work('recUnavailable', '2026-07-28', 人員=['recInactive'], 儀器=['recRepair'], 車輛=['recVehicle']),
    ])


def by_id(board, rid):
    return next(slot for slot in board['slots'] if slot['record_id'] == rid)


def test_multiday_window_and_group_filter_preserve_source_interval():
    data = source([work('recSpan', '2026-07-24', '2026-07-29'), work('recPast', '2026-07-26'),
                   work('recFuture', '2026-07-29'), work('recOther', 組別='其他組')])
    board = build_board(data, Window(WINDOW.start, WINDOW.end, '水深A組'))
    assert [slot['record_id'] for slot in board['slots']] == ['recSpan']
    assert board['slots'][0]['interval'] == {'start': '2026-07-24', 'end': '2026-07-29', 'precision': 'date'}
    assert board['source']['latest_booking_date'] == '2026-07-29'
    assert board['capacity']['people'][0]['days'] == {
        '2026-07-27': {'booked_slots': 2, 'state': 'overbooked_unknown'},
        '2026-07-28': {'booked_slots': 1, 'state': 'booked'}}


def test_unassigned_missing_requirements_and_leave_is_not_an_unassigned_work_slot():
    data = source([work('recMissing', 人員=[], 案件=[], 儀器=[]),
                   row('recLeave', **{'條類型': '休假', '開始日期': '2026-07-28', '人員': ['recActive']})])
    board = build_board(data, WINDOW)
    assert by_id(board, 'recMissing')['gaps'] == ['no_crew', 'no_case', 'no_instrument_for_field_work']
    assert by_id(board, 'recLeave')['planning_status'] == 'confirmed'
    assert board['unassigned_queue'] == ['v4:tblZz6Mkhv9gHrB2:recMissing']
    assert board['kpi'] == {'slots': 2, 'unassigned': 1, 'unknown_overlap': 0, 'conflict': 0}


def test_crewed_work_without_case_or_instrument_is_not_unassigned_and_admin_needs_no_case():
    board = build_board(source([work('recField', 案件=[], 儀器=[]), work('recAdmin', 業別='行政', 案件=[], 儀器=[])]), WINDOW)
    assert by_id(board, 'recField')['gaps'] == ['no_case', 'no_instrument_for_field_work']
    assert by_id(board, 'recAdmin')['gaps'] == []
    assert board['unassigned_queue'] == []
    assert board['kpi'] == {'slots': 2, 'unassigned': 0, 'unknown_overlap': 2, 'conflict': 0}


def test_timed_conflict_date_only_unknown_unavailable_and_literal_kpis():
    board = build_board(acceptance_source(), WINDOW)
    assert board['kpi'] == {'slots': 6, 'unassigned': 1, 'unknown_overlap': 2, 'conflict': 2}
    timed = by_id(board, 'recTimedA')
    assert timed['crew'][0] == {'person_ref': 'recActive', 'name': '合成人員', 'active': True,
                               'feasibility': 'conflict', 'reasons': ['no_leave_source', 'no_capability_source', 'timed_overlap']}
    assert timed['issues'] == ['v4:tblZz6Mkhv9gHrB2:recTimedB']
    unknown = by_id(board, 'recDateA')
    assert unknown['crew'][0]['feasibility'] == 'unknown'
    assert unknown['crew'][0]['active'] is None
    assert unknown['crew'][0]['reasons'] == ['no_leave_source', 'no_capability_source', 'same_day_other_slot']
    unavailable = by_id(board, 'recUnavailable')
    assert unavailable['crew'][0]['feasibility'] == 'unavailable'
    assert unavailable['crew'][0]['reasons'] == ['inactive', 'no_leave_source', 'no_capability_source']
    assert unavailable['resources'] == [
        {'kind': 'instrument', 'ref': 'recRepair', 'label': '送修儀器', 'feasibility': 'unavailable', 'reasons': ['repair']},
        {'kind': 'vehicle', 'ref': 'recVehicle', 'label': 'SYNTHETIC', 'feasibility': 'unavailable', 'reasons': ['inactive']}]
    assert board['source']['joins']['people'] == 'partial'
    assert len(board['slots']) == board['kpi']['slots']
    assert [slot['slot_id'] for slot in board['slots'] if slot['planning_status'] == 'unassigned'] == board['unassigned_queue']
    assert len(board['unassigned_queue']) == board['kpi']['unassigned']
    assert sum(any('timed_overlap' in member['reasons'] for member in slot['crew'] + slot['resources']) for slot in board['slots']) == board['kpi']['conflict']
    assert sum(any('same_day_other_slot' in member['reasons'] for member in slot['crew'] + slot['resources']) for slot in board['slots']) == board['kpi']['unknown_overlap']


def test_disjoint_timed_intervals_and_midnight_date_precision():
    board = build_board(source([
        work('recA', '2026-07-27T09:00:00+08:00', '2026-07-27T10:00:00+08:00', 儀器=[]),
        work('recB', '2026-07-27T10:00:00+08:00', '2026-07-27T11:00:00+08:00', 儀器=[]),
    ]), WINDOW)
    assert board['kpi'] == {'slots': 2, 'unassigned': 0, 'unknown_overlap': 0, 'conflict': 0}
    assert board['slots'][0]['crew'][0]['feasibility'] == 'unknown'
    ms = int(datetime(2026, 7, 27, tzinfo=TZ).timestamp() * 1000)
    board = build_board(source([work('recMs', ms)]), WINDOW)
    assert board['slots'][0]['interval'] == {'start': '2026-07-27', 'end': '2026-07-27', 'precision': 'date'}


def test_resource_only_overlap_is_counted_and_unavailable_wins():
    board = build_board(source([work('recA', 人員=['recActive'], 儀器=['recRepair']),
                                work('recB', 人員=['recInactive'], 儀器=['recRepair'])]), WINDOW)
    assert board['kpi'] == {'slots': 2, 'unassigned': 0, 'unknown_overlap': 2, 'conflict': 0}
    assert board['slots'][0]['resources'][0] == {'kind': 'instrument', 'ref': 'recRepair', 'label': '送修儀器',
                                                'feasibility': 'unavailable', 'reasons': ['repair', 'same_day_other_slot']}


def test_future_window_shows_last_source_date_and_unknown_free_capacity():
    board = build_board(source([work('recOld', '2026-08-19')]), Window(date(2026, 10, 18), date(2026, 10, 18)))
    assert board['source']['latest_booking_date'] == '2026-08-19'
    assert board['kpi'] == {'slots': 0, 'unassigned': 0, 'unknown_overlap': 0, 'conflict': 0}
    assert board['gaps'][-1] == {'code': 'no_bookings_after_2026-08-19', 'message': 'No bookings after 2026-08-19.', 'count': 0}
    assert board['capacity']['people'][0]['days'] == {'2026-10-18': {'booked_slots': 0, 'state': 'unknown'}}


def test_invalid_dates_remain_visible_as_source_gap_and_joins_degrade_independently():
    data = source([work('recGood'), work('recInvalid', 'bad'), work('recReverse', '2026-07-28', '2026-07-27')])
    data = BoardInput(data.schedule, None, data.instruments, data.vehicles, [], AT)
    board = build_board(data, WINDOW)
    assert board['source']['joins'] == {'people': 'unavailable', 'instruments': 'ok', 'vehicles': 'ok', 'cases': 'partial'}
    assert board['source']['quality'] == {'states': ['partial'], 'reason': 'incomplete_source_or_joins'}
    assert board['slots'][0]['crew'][0]['name'] is None
    assert board['slots'][0]['case'] == {'ref': 'recCase', 'code': None, 'name': None}
    assert board['gaps'][-2] == {'code': 'invalid_schedule_interval', 'message': 'Schedule rows without a usable interval are excluded.', 'count': 2}
    assert board['gaps'][-1] == {'code': 'unresolved_case_links', 'message': 'Case links do not resolve to a V4 confirmation row.', 'count': 1}


def test_foreign_case_table_is_never_reinterpreted_as_v4():
    board = build_board(source([work('recForeign', 案件=[{'record_ids': ['recCase'], 'table_id': 'tblOther'}])]), WINDOW)
    assert board['slots'][0]['case'] == {'ref': 'recCase', 'code': None, 'name': None}
    assert board['source']['joins']['cases'] == 'partial'


class FakeReader:
    def __init__(self, data=None):
        data = data or source([work('recGood')])
        self.rows = {key: getattr(data, key) for key in TABLES}
        self.errors = {}
        self.calls = []

    def read_table(self, key):
        self.calls.append(key)
        if key in self.errors:
            raise self.errors[key]
        return deepcopy(self.rows[key])


def app_for(cfg=None, *, identity=None, allow=None, reader=None):
    app = FastAPI()
    service = DispatchBoardService(cfg or {}, reader=reader or FakeReader())
    register(app, cfg=cfg or {'DISPATCH_BOARD_ENABLED': 'true'}, identity=identity or (
        lambda _: ({'wid': 'company', 'mode': 'lark'}, {'role': 'pm'})),
        allow=allow or (lambda data, user: user['role'] in ('pm', 'manager')), service=service)
    return app, service


def test_routes_flag_off_auth_permission_and_no_count_leak():
    app, _ = app_for({'DISPATCH_BOARD_ENABLED': 'false'})
    assert TestClient(app).get(URL).status_code == 404
    reader = FakeReader()
    app, _ = app_for(allow=lambda *_: False, reader=reader)
    response = TestClient(app).get(URL)
    assert response.status_code == 403
    assert response.json() == {'detail': '需要 PM 或主管權限及公司正式工作區', 'source': {'quality': {'states': ['forbidden']}}}
    assert reader.calls == []
    def unauthenticated(_):
        raise HTTPException(401, '請先登入')
    app, _ = app_for(identity=unauthenticated)
    assert TestClient(app).get(URL).json() == {'detail': '請先登入'}
    app, _ = app_for(identity=lambda _: ({'wid': 'demo-one', 'mode': 'demo'}, {'role': 'manager'}))
    assert TestClient(app).get(URL).status_code == 403


@pytest.mark.parametrize('query', [
    'from=bad', 'from=2026-02-30', 'from=20260727', 'from=2026-07-28&to=2026-07-27',
    'from=2026-01-01&to=2026-03-04', 'from=2026-07-27T00:00:00', 'other=1', 'group=' + 'x' * 101,
])
def test_route_rejects_invalid_windows(query):
    app, _ = app_for()
    assert TestClient(app).get(URL + '?' + query).status_code == 422


def test_route_read_response_and_window_boundary():
    app, _ = app_for()
    response = TestClient(app).get(URL + '?from=2026-07-27&to=2026-07-28&group=水深A組')
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['kpi'] == {'slots': 1, 'unassigned': 0, 'unknown_overlap': 0, 'conflict': 0}
    assert parameters({'from': '2026-01-01', 'to': '2026-03-03'}).days()[-1] == '2026-03-03'
    assert parameters({}, today=date(2026, 10, 18)) == Window(date(2026, 10, 18), date(2026, 10, 24))


def test_schedule_read_failed_and_forbidden_have_no_counts():
    for error, status, states in ((ReadFailure('down'), 503, ['read_failed']), (ReadBlocked('denied'), 403, ['forbidden'])):
        reader = FakeReader()
        reader.errors['schedule'] = error
        app, _ = app_for(reader=reader)
        response = TestClient(app).get(URL)
        assert response.status_code == status
        assert response.json()['source']['quality']['states'] == states
        assert set(response.json()) == {'source'}
        assert reader.calls == ['schedule']


def test_failed_join_keeps_the_board_and_nulls_only_the_join():
    reader = FakeReader()
    reader.errors['people'] = ReadBlocked('people denied')
    app, service = app_for(reader=reader)
    client = TestClient(app)
    client.get(URL + '?from=2026-07-27&to=2026-07-28')
    for flight in list(service._joins.values()):
        flight.future.result(timeout=1)
    response = client.get(URL + '?from=2026-07-27&to=2026-07-28')
    assert response.status_code == 200
    body = response.json()
    assert body['source']['joins'] == {'people': 'unavailable', 'instruments': 'ok', 'vehicles': 'ok', 'cases': 'ok'}
    assert body['slots'][0]['crew'][0]['name'] is None
    assert body['slots'][0]['resources'][0]['label'] == '合成儀器'
    assert body['kpi']['slots'] == 1


def test_stale_returns_immediately_coalesces_and_keeps_last_good_on_refresh_failure():
    started, release, finished = Event(), Event(), Event()
    class Blocking(FakeReader):
        block = False
        def read_table(self, key):
            if self.block and key == 'schedule':
                self.calls.append(key)
                started.set()
                release.wait(3)
                finished.set()
                raise ReadFailure('down')
            return super().read_table(key)
    reader = Blocking()
    now = [100.0]
    service = DispatchBoardService({}, reader=reader, clock=lambda: now[0])
    assert service.board('company', WINDOW)[1]['kpi']['slots'] == 1
    for flight in list(service._joins.values()):
        flight.future.result(timeout=1)
    now[0] = 161.0
    reader.block = True
    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(lambda _: service.board('company', WINDOW), range(6)))
    assert started.wait(1)
    assert reader.calls.count('schedule') == 2
    assert responses[0][1]['source']['quality'] == {'states': ['stale'], 'reason': 'refreshing_last_good_snapshot', 'age_seconds': 61}
    cache_key = service._scope('company').key(service.config.base + '/' + TABLES['schedule'].table_id,
                                            projection=TABLES['schedule'].fields)
    future = service.cache._flights[cache_key]
    release.set()
    with pytest.raises(ReadFailure):
        future.result(timeout=1)
    status, body = service.board('company', WINDOW)
    assert status == 200
    assert body['kpi'] == {'slots': 1, 'unassigned': 0, 'unknown_overlap': 0, 'conflict': 0}
    assert body['source']['quality'] == {'states': ['read_failed'], 'reason': 'schedule_refresh_failed', 'age_seconds': 61}


def test_real_app_flag_absent_default_and_enabled_auth(tmp_path):
    from .app import create_app
    cfg = {'DATABASE_URL': f'sqlite:///{tmp_path}/dispatch.db', 'UPLOAD_DIR': str(tmp_path / 'uploads'),
           'SESSION_SECRET': 'test-secret' * 5, 'APP_ENV': 'development', 'DEMO_MODE': 'true',
           'LARK_LIVE_READ_TRANSPORT': 'deny'}
    client = TestClient(create_app(cfg))
    assert client.get(URL).status_code == 404
    app = create_app({**cfg, 'DISPATCH_BOARD_ENABLED': 'true'})
    client = TestClient(app)
    assert client.get(URL).status_code == 401
    assert client.get('/api/session').json()['features']['dispatch_board'] is True
    assert 'dispatch_board' not in TestClient(create_app(cfg)).get('/api/session').json().get('features', {})
    response = client.get(URL)
    assert response.status_code == 403
    assert response.json()['source']['quality'] == {'states': ['forbidden']}


def reader_with_transport(respond):
    class Bucket:
        def acquire(self, *_):
            pass
    return DispatchReader({'LARK_APP_ID': 'dispatch-test', 'LARK_APP_SECRET': 'synthetic',
                           'LARK_WORKER_IDENTITY': 'application', 'LARK_WORKER_ORGANIZATION': 'synthetic', 'LARK_V4_BASE_TOKEN': 'configuredBase'},
                          transport=httpx.MockTransport(respond),
                          client_options={'bucket': Bucket(), 'token_cache': TenantTokenCache()})


def test_reader_projects_requests_and_responses_and_pages():
    requests = []
    def respond(request):
        if '/auth/' in request.url.path:
            return httpx.Response(200, json={'code': 0, 'tenant_access_token': 'synthetic', 'expire': 7200})
        requests.append(request)
        page = request.url.params.get('page_token')
        return httpx.Response(200, json={'code': 0, 'data': {
            'items': [row('recB' if page else 'recA', 姓名='合成人員', 在職=True, 薪資=999, 請假原因='private')],
            'has_more': not page, 'page_token': 'next' if not page else ''}})
    records = reader_with_transport(respond).read_table('people')
    assert records == [row('recA', 姓名='合成人員', 在職=True), row('recB', 姓名='合成人員', 在職=True)]
    assert [(r.method, r.url.path, json.loads(r.url.params['field_names'])) for r in requests] == [
        ('GET', '/open-apis/bitable/v1/apps/configuredBase/tables/tblfaCO2xPUNptQH/records', ['姓名', '在職']),
        ('GET', '/open-apis/bitable/v1/apps/configuredBase/tables/tblfaCO2xPUNptQH/records', ['姓名', '在職'])]


@pytest.mark.parametrize('data', [
    {'items': [row('recA'), row('recA')], 'has_more': False},
    {'items': [], 'has_more': True}, {'items': [], 'has_more': 'false'},
    {'items': [{'record_id': 'recA'}], 'has_more': False},
])
def test_reader_rejects_incomplete_results(data):
    def respond(request):
        if '/auth/' in request.url.path:
            return httpx.Response(200, json={'code': 0, 'tenant_access_token': 'synthetic', 'expire': 7200})
        return httpx.Response(200, json={'code': 0, 'data': data})
    with pytest.raises(ReadFailure):
        reader_with_transport(respond).read_table('schedule')


def test_manifest_reports_verified_missing_drift_and_cli_exit(tmp_path, capsys):
    snapshot = {TABLES['people'].table_id: {'data': {'items': [
        {'field_name': '姓名', 'type': 1, 'field_id': 'fldName'}, {'field_name': '在職', 'type': 1}]}}}
    results = [r for r in verify(snapshot) if r['table'] == 'people']
    assert results == [
        {'table': 'people', 'table_id': 'tblfaCO2xPUNptQH', 'field': '姓名', 'status': 'verified',
         'expected_types': [1], 'actual_type': 1, 'field_id': 'fldName'},
        {'table': 'people', 'table_id': 'tblfaCO2xPUNptQH', 'field': '在職', 'status': 'drift',
         'expected_types': [7], 'actual_type': 1, 'field_id': None}]
    assert verify(snapshot)[0]['status'] == 'missing'
    path = tmp_path / 'fields.json'
    path.write_text(json.dumps(snapshot))
    assert verify_main(['--snapshot', str(path)]) == 1
    assert '"status": "drift"' in capsys.readouterr().out


def test_progressive_joins_do_not_delay_schedule_and_fill_in_on_next_get():
    started, release = Event(), Event()
    class SlowJoins(FakeReader):
        def read_table(self, key):
            if key != 'schedule':
                started.set()
                release.wait(3)
            return super().read_table(key)
    service = DispatchBoardService({}, reader=SlowJoins())
    try:
        status, first = service.board('company', WINDOW)
        assert status == 200
        assert started.wait(1)
        assert first['kpi'] == {'slots': 1, 'unassigned': 0, 'unknown_overlap': 0, 'conflict': 0}
        assert first['slots'][0]['crew'][0]['name'] is None
        assert first['source']['joins'] == {'people': 'unavailable', 'instruments': 'unavailable', 'vehicles': 'unavailable', 'cases': 'unavailable'}
        release.set()
        for flight in list(service._joins.values()):
            flight.future.result(timeout=1)
        second = service.board('company', WINDOW)[1]
        assert second['slots'][0]['crew'][0]['name'] == '合成人員'
        assert second['source']['joins'] == {'people': 'ok', 'instruments': 'ok', 'vehicles': 'ok', 'cases': 'ok'}
        assert second['source']['quality'] == {'states': ['complete'], 'reason': None}
    finally:
        release.set()
        service.close()


def test_incomplete_resource_attributes_and_missing_duration_stay_unknown():
    data = source([work('recPoint', '2026-07-27T10:00:00+08:00'),
                   work('recTimed', '2026-07-27T09:00:00+08:00', '2026-07-27T11:00:00+08:00')])
    data = BoardInput(data.schedule, data.people, [row('recInstrument', 儀器名稱='Unknown condition')], data.vehicles, data.cases, AT)
    body = build_board(data, WINDOW)
    assert body['kpi'] == {'slots': 2, 'unassigned': 0, 'unknown_overlap': 2, 'conflict': 0}
    assert body['source']['joins']['instruments'] == 'partial'
    assert body['slots'][0]['resources'][0] == {'kind': 'instrument', 'ref': 'recInstrument', 'label': 'Unknown condition',
                                               'feasibility': 'unavailable', 'reasons': ['inactive', 'same_day_other_slot']}


def test_forbidden_refresh_discards_last_good_and_cache_is_workspace_scoped():
    reader = FakeReader()
    now = [100.0]
    service = DispatchBoardService({}, reader=reader, clock=lambda: now[0])
    try:
        assert service.board('company', WINDOW)[1]['kpi']['slots'] == 1
        assert service.board('another-company', WINDOW)[1]['kpi']['slots'] == 1
        assert reader.calls.count('schedule') == 2
        now[0] = 161.0
        reader.errors['schedule'] = ReadBlocked('revoked')
        service._read('company', 'schedule')
        cache_key = service._scope('company').key(service.config.base + '/' + TABLES['schedule'].table_id,
                                                projection=TABLES['schedule'].fields)
        with service.cache._lock:
            future = service.cache._flights.get(cache_key)
        if future:
            with pytest.raises(ReadBlocked):
                future.result(timeout=1)
        with pytest.raises(ReadBlocked):
            service.board('company', WINDOW)
    finally:
        service.close()


def test_synthetic_fixtures_are_plain_contract_responses_with_last_good_variants():
    root = Path(__file__).parent / 'fixtures'
    sample = json.loads((root / 'dispatch_board_sample.json').read_text())
    assert set(sample) == {'schema_version', 'window', 'source', 'kpi', 'unassigned_queue', 'slots', 'capacity', 'gaps'}
    assert sample['kpi'] == {'slots': 7, 'unassigned': 5, 'unknown_overlap': 2, 'conflict': 2}
    assert sample['slots'][0]['work_content'].startswith('SYNTHETIC')
    assert sample['source']['quality'] == {'states': ['complete'], 'reason': None}
    for variant, age in (('stale', 120), ('read_failed', 180)):
        body = json.loads((root / f'dispatch_board_{variant}_sample.json').read_text())
        assert body['source']['quality']['states'] == [variant]
        assert body['source']['quality']['age_seconds'] == age
        assert body['slots'] == sample['slots']
        assert body['kpi'] == sample['kpi']
        assert body['unassigned_queue'] == [slot['slot_id'] for slot in body['slots'] if slot['planning_status'] == 'unassigned']


def test_manifest_complete_recorded_metadata_is_verified(tmp_path, capsys):
    snapshot = {table.table_id: [{'field_name': name, 'type': kinds[0], 'field_id': f'fld{n}'}
                                for n, (name, kinds) in enumerate(table.fields.items())]
                for table in TABLES.values()}
    path = tmp_path / 'synthetic-fields.json'
    path.write_text(json.dumps(snapshot))
    assert verify_main(['--snapshot', str(path)]) == 0
    assert '"status": "verified"' in capsys.readouterr().out


@pytest.mark.parametrize('payload', [[], {'tblfaCO2xPUNptQH': {'data': {'items': [42]}}},
                                      {'tblfaCO2xPUNptQH': {'data': {'items': [], 'has_more': True}}}])
def test_manifest_unusable_or_incomplete_snapshot_cannot_claim_verified(tmp_path, payload, capsys):
    path = tmp_path / 'invalid-fields.json'
    path.write_text(json.dumps(payload))
    assert verify_main(['--snapshot', str(path)]) == 2
    assert capsys.readouterr().err == 'Cannot verify dispatch sources (ValueError).\n'


def test_group_filter_keeps_cross_group_overlap_and_full_capacity():
    board = build_board(source([work('recA', 車輛=['recVehicle']),
                                work('recB', 組別='其他組', 車輛=['recVehicle'])]),
                        Window(WINDOW.start, WINDOW.end, '水深A組'))
    assert board['kpi'] == {'slots': 1, 'unassigned': 0, 'unknown_overlap': 1, 'conflict': 0}
    assert board['slots'][0]['issues'] == ['v4:tblZz6Mkhv9gHrB2:recB']
    assert board['slots'][0]['resources'][0]['feasibility'] == 'unknown'
    assert board['slots'][0]['resources'][1]['reasons'] == ['inactive', 'same_day_other_slot']
    assert board['capacity']['people'][0]['days']['2026-07-27'] == {'booked_slots': 2, 'state': 'overbooked_unknown'}


@pytest.mark.parametrize('start,end', [('2026-07-27T00:00:00+08:00', '2026-07-27T11:00:00+08:00'),
                                       ('2026-07-27T23:00:00+08:00', '2026-07-28T00:00:00+08:00')])
def test_either_midnight_bound_cannot_prove_conflict(start, end):
    board = build_board(source([work('recA', start, end),
                                work('recB', '2026-07-27T10:00:00+08:00', '2026-07-27T23:30:00+08:00')]), WINDOW)
    assert board['kpi'] == {'slots': 2, 'unassigned': 0, 'unknown_overlap': 2, 'conflict': 0}
    assert board['slots'][0]['interval']['precision'] == 'date'
    assert board['capacity']['people'][0]['days']['2026-07-28']['booked_slots'] == 0


def test_omitted_checkboxes_are_inactive_without_partial_join():
    data = source([work('recA', 車輛=['recVehicle'])])
    for key, field in [('people', '在職'), ('instruments', '啟用'), ('vehicles', '啟用')]:
        for item in getattr(data, key):
            item['fields'].pop(field, None)
    board = build_board(data, WINDOW)
    assert board['source']['joins'] == {'people': 'ok', 'instruments': 'ok', 'vehicles': 'ok', 'cases': 'ok'}
    assert board['slots'][0]['crew'][0]['active'] is False
    assert [r['feasibility'] for r in board['slots'][0]['resources']] == ['unavailable', 'unavailable']
    data.people[0]['fields'].pop('姓名')
    assert build_board(data, WINDOW)['source']['joins']['people'] == 'partial'
    assert build_board(BoardInput(data.schedule, [], [], [], [], AT), WINDOW)['slots'][0]['crew'][0]['active'] is None


def test_join_refresh_is_visible_on_next_request():
    now = [100.0]
    reader = FakeReader()
    service = DispatchBoardService({}, reader=reader, clock=lambda: now[0])
    try:
        service.board('company', WINDOW)
        for flight in list(service._joins.values()):
            flight.future.result(timeout=1)
        service.board('company', WINDOW)
        now[0] = 161.0
        reader.rows['people'][0]['fields']['姓名'] = '更新人員'
        service.board('company', WINDOW)
        for flight in list(service._joins.values()):
            flight.future.result(timeout=1)
        for future in list(service.cache._flights.values()):
            future.result(timeout=1)
        assert service.board('company', WINDOW)[1]['slots'][0]['crew'][0]['name'] == '更新人員'
    finally:
        service.close()


def test_people_permission_failure_preserves_schedule_last_good():
    reader = FakeReader()
    service = DispatchBoardService({}, reader=reader)
    try:
        assert service._read('company', 'schedule')[0].value[0]['record_id'] == 'recGood'
        reader.errors['people'] = HTTPException(403, 'people denied')
        service._load_join('company', 'people')
        reader.errors['schedule'] = ReadFailure('schedule down')
        assert service._read('company', 'schedule')[0].value[0]['record_id'] == 'recGood'
        assert reader.calls == ['schedule', 'people']
    finally:
        service.close()


def test_readme_defines_unassigned_as_no_crew_only():
    readme = (Path(__file__).parent / 'dispatch_board/README.md').read_text()
    assert 'A work slot is unassigned when it has no crew.' in readme
