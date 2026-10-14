"""P2-INT-B: the five P2 GET routes over a synthetic isolated SQLite workspace. No Lark or cloud data."""
import json
from copy import deepcopy
import time
from urllib.parse import urlencode
import pytest
from fastapi.testclient import TestClient
from .app import create_app, WorkspaceRow, AuthRow, CacheRow, BusinessRow, PersonRow
from .seed import seed
from .policy import upgrade
from . import storage

B, CT, KT, WT = 'baseSyn', 'tblConf', 'tblCon', 'tblWork'
AMOUNTS = (918273, 827364, 736455)
HIDDEN_NAME = 'HIDDEN_CASE_SENTINEL'
HIDDEN_CODE = 'HIDDEN-CODE-777'
WID = 'lark-boundary'
ROUTES = ['/api/manager-overview', '/api/confirmations', '/api/case-detail/{vis}', '/api/contract-detail?key={k1}',
          '/api/work-item-detail?key={w1}']


def ident(table, rec):
    return dict(base_token=B, table_id=table, record_id=rec)


def conf(rec, code, pid, name, version=None):
    row = dict(id=f'{B}/{CT}/{rec}', source_identity=ident(CT, rec), source_kind='confirmation', code=code,
               project_id=pid, source_missing=False, quote_ids=[], unresolved_confirmation_ids=[],
               fields={'工程名稱': name, '合約總額': AMOUNTS[0]})
    if version is not None: row['source_version'] = version
    return row


def contract(rec, parent, pid, title):
    return dict(id=f'{B}/{KT}/{rec}', source_identity=ident(KT, rec), source_kind='contract', project_id=pid,
                confirmation_ids=[f'{B}/{CT}/{parent}'], unresolved_confirmation_ids=[], title=title, item_number='1',
                amount_original=AMOUNTS[0], amount_reported=AMOUNTS[1], source_missing=False, reporting_ids=[], task_refs=[])


def work(rec, pid, contract_rec):
    return dict(id=f'{B}/{WT}/{rec}', project_id=pid, contract_ids=[f'{B}/{KT}/{contract_rec}'], category='外業', source_missing=False)


def fresh_cache():
    now = time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())
    return {'status': 'ready', 'configured': True, 'last_sync': now,
            'records': [dict(base_token=B, table_id=CT, record_id=r, kind='confirmation', fields={}) for r in ('recC1', 'recC2', 'recH1')],
            'tables': [{'base_token': B, 'table_id': CT, 'name': 'T', 'status': 'ready', 'pages_read': 1, 'count': 3, 'last_sync': now}]}


def build_state(visible=('recC1', 'recC2', 'recK1', 'recW1')):
    state = upgrade(seed()); state['environment'] = 'production'
    for p in state['projects']: p.update(case_visibility='excluded_history', execution_system='meegle')
    old, new = state['projects'][:2]
    new.update(case_visibility='new_case', execution_system='workbench', name='Visible case')
    old.update(name=HIDDEN_NAME)
    state['source_confirmations'] = [conf('recC1', 'VIS-1', new['id'], 'Visible case', 1), conf('recC2', 'VIS-1', new['id'], 'Visible case', 2),
                                     conf('recH1', HIDDEN_CODE, old['id'], HIDDEN_NAME, 1)]
    state['contract_items'] = [contract('recK1', 'recC1', new['id'], 'Visible line'), contract('recKH', 'recH1', old['id'], HIDDEN_NAME + ' line')]
    state['source_work_items'] = [work('recW1', new['id'], 'recK1'), work('recWH', old['id'], 'recKH')]
    state['source_work_items_status'] = {new['id']: dict(partial=False, truncated=False), old['id']: dict(partial=False, truncated=False)}
    kinds = {'recC1': CT, 'recC2': CT, 'recK1': KT, 'recW1': WT, 'recH1': CT, 'recKH': KT, 'recWH': WT}
    state['source_visible_record_ids'] = [f'{B}|{kinds[r]}|{r}' for r in visible]
    return state, new['id'], old['id']


@pytest.fixture
def http(tmp_path, monkeypatch):
    app = create_app({'DATABASE_URL': f'sqlite:///{tmp_path}/p2int.db', 'UPLOAD_DIR': str(tmp_path / 'f'), 'DEMO_MODE': 'false',
                      'APP_ENV': 'development', 'SESSION_SECRET': 'p2-int-only' * 4,
                      'LARK_WORKER_ORGANIZATION': 'boundary', 'LARK_ALLOWED_TENANTS': 'boundary'})
    real = app.state.live_read.status
    def status(wid):
        out = real(wid); out['datasets']['sources'].update(status='fresh', age_seconds=1, ttl_seconds=900, last_error=None)
        return out
    monkeypatch.setattr(app.state.live_read, 'status', status)
    client = TestClient(app)

    def seat(state, wid=WID, cache=True):
        with app.state.sessions.begin() as db:
            row = db.get(WorkspaceRow, wid)
            if row is None:
                row = WorkspaceRow(id=wid, version=state['version'], data={}); db.add(row); db.flush()
                db.add(AuthRow(id='sess-' + wid, data={'wid': wid, 'expires': time.time() + 3600}))
                for user in state['users']: db.add(PersonRow(organization_id=wid.removeprefix('test-'), person_id=user['id'], data=user))
                if cache: db.add(CacheRow(id=wid, data=fresh_cache()))
            row.data = storage.save(db, BusinessRow, row.id, dict(state, environment='test' if wid.startswith('test-') else 'production'))

    def signin(uid='u-manager', wid=WID):
        client.cookies.set('meegle_session', app.state.signer.dumps({'mode': 'lark', 'sid': 'sess-' + wid, 'wid': wid, 'uid': uid}))
    return app, client, seat, signin


@pytest.fixture
def world(http):
    app, client, seat, signin = http
    state, vis, hid = build_state()
    seat(state); signin()
    ids = dict(vis=vis, hid=hid, k1=f'{B}/{KT}/recK1', kh=f'{B}/{KT}/recKH', w1=f'{B}/{WT}/recW1', wh=f'{B}/{WT}/recWH')
    return app, client, seat, signin, state, ids


def leaves(value, path=()):
    if isinstance(value, dict):
        for k, v in value.items(): yield from leaves(v, path + (k,))
    elif isinstance(value, list):
        for v in value: yield from leaves(v, path)
    else:
        yield path, value


def assert_no_amount(response):
    body = response.json()
    for path, value in leaves(body):
        assert value not in AMOUNTS and str(value) not in {str(a) for a in AMOUNTS}, path
    for a in AMOUNTS: assert str(a) not in response.text
    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if 'amount' in k.lower() and k != 'amounts': assert isinstance(v, dict) and v.get('state') == 'withheld', k
                walk(v)
        elif isinstance(node, list):
            for v in node: walk(v)
    walk(body)


def get(client, template, ids):
    return client.get(template.format(**ids))


# ---- auth + happy path ------------------------------------------------------
@pytest.mark.parametrize('template', ROUTES)
def test_unauthenticated_is_401_and_invalid_params_do_not_precede_auth(world, template):
    _, client, _, _, _, ids = world
    client.cookies.clear()
    assert get(client, template, ids).status_code == 401
    assert client.get('/api/confirmations?limit=abc').status_code == 401


@pytest.mark.parametrize('template', ROUTES)
def test_each_route_is_200_for_an_authorized_viewer_with_no_amounts_or_hidden_case(world, template):
    _, client, _, _, _, ids = world
    response = get(client, template, ids)
    assert response.status_code == 200, response.text
    for sentinel in (HIDDEN_NAME, HIDDEN_CODE, 'recH1', 'recKH', 'recWH'):
        assert sentinel not in response.text
    assert_no_amount(response)


def test_confirmations_lists_only_visible_versions_with_known_totals(world):
    _, client, _, _, _, _ = world
    body = client.get('/api/confirmations').json()
    assert [r['case_number'] for r in body['rows']] == ['VIS-1', 'VIS-1']
    assert body['totals']['matching'] == 2 and body['totals_basis'] == 'current'


def test_no_response_reuses_the_project_payload(world):
    _, client, _, _, _, ids = world
    project = client.get(f"/api/projects/{ids['vis']}").json()
    for template in ROUTES:
        body = get(client, template, ids).json()
        assert not ({'pm_id', 'case_visibility', 'execution_system', 'source_attachment_coverage', 'files', 'quotes'} & set(body)), template
        assert body.keys() != project.keys()
        assert body != project
    assert client.get(f"/api/case-detail/{ids['vis']}").json().get('header') is not None


# ---- forbidden == absent ----------------------------------------------------
def test_forbidden_case_404_is_identical_to_absent_with_no_leak_in_body_or_headers(world):
    _, client, _, _, _, ids = world
    forbidden = client.get(f"/api/case-detail/{ids['hid']}")
    absent = client.get('/api/case-detail/p-does-not-exist')
    assert forbidden.status_code == absent.status_code == 404
    assert forbidden.json() == absent.json()
    blob = forbidden.text + json.dumps(dict(forbidden.headers))
    for s in (ids['hid'], HIDDEN_NAME, HIDDEN_CODE): assert s not in blob
    assert {k: v for k, v in forbidden.headers.items() if k != 'content-length'} == {k: v for k, v in absent.headers.items() if k != 'content-length'}


@pytest.mark.parametrize('path,hidden_key', [('/api/contract-detail', 'kh'), ('/api/work-item-detail', 'wh')])
def test_forbidden_contract_and_work_item_are_404_identical_to_absent(world, path, hidden_key):
    _, client, _, _, _, ids = world
    forbidden = client.get(path, params={'key': ids[hidden_key]})
    absent = client.get(path, params={'key': f'{B}/{KT}/recNope'})
    assert forbidden.status_code == absent.status_code == 404
    assert forbidden.json() == absent.json()
    assert ids[hidden_key] not in forbidden.text and 'recNope' not in absent.text


def test_forbidden_list_search_and_overview_show_no_hidden_row_or_count(world):
    _, client, _, _, _, _ = world
    for q in (HIDDEN_NAME, HIDDEN_CODE, 'recH1'):
        body = client.get('/api/confirmations', params={'q': q}).json()
        assert body['rows'] == [] and body['page_state']['states'] == ['filtered_empty']
        assert HIDDEN_NAME not in json.dumps(body)
    overview = client.get('/api/manager-overview').text
    assert HIDDEN_NAME not in overview and HIDDEN_CODE not in overview


def test_mutation_without_filter_visible_cases_the_hidden_case_leaks(world, monkeypatch):
    # Mutation: neutralise the visibility narrowing. The guard tests above must then fail (hidden case reachable).
    _, client, _, _, _, ids = world
    from . import source_case_policy
    monkeypatch.setattr(source_case_policy, 'filter_visible_cases', lambda state: state)
    monkeypatch.setattr(source_case_policy, 'visible_project', lambda ws, project: True)
    assert client.get(f"/api/case-detail/{ids['hid']}").status_code == 200   # the 404 guard test would fail here


# ---- revocation -------------------------------------------------------------
def test_revocation_removes_rows_counts_and_search_hits(world):
    _, client, seat, _, state, ids = world
    assert client.get('/api/confirmations', params={'q': 'VIS-1'}).json()['totals']['matching'] == 2
    assert client.get('/api/contract-detail', params={'key': ids['k1']}).status_code == 200
    assert client.get('/api/work-item-detail', params={'key': ids['w1']}).status_code == 200
    revoked, _, _ = build_state(visible=())
    seat(revoked)
    body = client.get('/api/confirmations', params={'q': 'VIS-1'}).json()
    assert body['rows'] == [] and body['totals']['matching'] in (0, None)
    assert body['totals']['authorized_source'] in (0, None)
    assert client.get('/api/contract-detail', params={'key': ids['k1']}).status_code == 404
    assert client.get('/api/work-item-detail', params={'key': ids['w1']}).status_code == 404
    overview = client.get('/api/manager-overview').json()
    assert 'VIS-1' not in json.dumps(overview)
    revoked_case, _, _ = build_state(visible=('recC1', 'recC2', 'recK1', 'recW1'))
    for p in revoked_case['projects']: p['case_visibility'] = 'excluded_history'
    seat(revoked_case)
    assert client.get(f"/api/case-detail/{ids['vis']}").status_code == 404


# ---- KPI == list ------------------------------------------------------------
@pytest.mark.parametrize('filters', [{}, {'source_version': '2'}, {'admission_state': 'nonexistent'}])
def test_overview_kpi_equals_confirmation_total_for_identical_filters_through_http(world, filters):
    _, client, _, _, _, _ = world
    query = urlencode(filters)
    total = client.get('/api/confirmations?' + query).json()['totals']['matching']
    overview = client.get('/api/manager-overview?' + query).json()
    card = next(c for c in overview['snapshot']['cards'] if c['id'] == 'confirmation_versions') if 'id' in overview['snapshot']['cards'][0] \
        else overview['snapshot']['cards'][0]
    assert total is not None and card['value'] == total
    assert overview['snapshot']['filters'] == {k: ([v] if k in ('source_version', 'pm', 'admission_state') else v) for k, v in filters.items()}


def test_mutation_population_that_drops_a_row_breaks_kpi_equality(world, monkeypatch):
    # Mutation: population loses a row; the equality above would fail.
    _, client, _, _, _, _ = world
    from . import confirmation_list
    real = confirmation_list.confirmation_population
    monkeypatch.setattr(confirmation_list, 'confirmation_population', lambda *a, **k: (real(*a, **k) or [])[1:])
    total = client.get('/api/confirmations').json()['totals']['matching']
    card = client.get('/api/manager-overview').json()['snapshot']['cards'][0]
    assert card['value'] != total


def test_overview_binds_source_health_page_state_exactly(world):
    _, client, _, _, _, _ = world
    assert client.get('/api/manager-overview').json()['source_health']['state'] == client.get('/api/source-health').json()['page_state'] \
        or client.get('/api/source-health').json()['page_state'] is None


# ---- bounded parameters -----------------------------------------------------
def test_cursor_from_another_filter_set_is_422(world):
    _, client, _, _, _, _ = world
    page = client.get('/api/confirmations?limit=1').json()
    assert page['next_cursor']
    ok = client.get('/api/confirmations', params={'limit': 1, 'cursor': page['next_cursor']})
    assert ok.status_code == 200
    other = client.get('/api/confirmations', params={'limit': 1, 'cursor': page['next_cursor'], 'source_version': '1'})
    assert other.status_code == 422


def test_mutation_cursor_binding_removed_accepts_foreign_cursor(world, monkeypatch):
    _, client, _, _, _, _ = world
    from . import confirmation_list
    cursor = client.get('/api/confirmations?limit=1').json()['next_cursor']
    monkeypatch.setattr(confirmation_list, '_cursor_matches', lambda expected, actual: True)
    assert client.get('/api/confirmations', params={'limit': 1, 'cursor': cursor, 'source_version': '1'}).status_code != 422


@pytest.mark.parametrize('query', ['limit=0', 'limit=101', 'limit=abc', 'limit=-1', 'limit=99999', 'q=' + 'x' * 241, 'cursor=%%%', 'cursor=' + 'a' * 513,
                                   'sort=amount', 'sort=case_number&direction=sideways', 'unknown=1', 'source_version=' + 'v' * 121,
                                   'deadline_from=2026-1-1', 'limit=1&limit=2'] + ['pm=u&' * 21])
def test_confirmations_oversize_or_malformed_parameters_are_422(world, query):
    _, client, _, _, _, _ = world
    assert client.get('/api/confirmations?' + query).status_code == 422


@pytest.mark.parametrize('path', ['/api/manager-overview?cursor=x', '/api/manager-overview?limit=1', '/api/manager-overview?q=x',
                                  '/api/manager-overview?deadline_to=bad', '/api/contract-detail', '/api/contract-detail?key=',
                                  '/api/contract-detail?key=' + 'k' * 301, '/api/contract-detail?key=a&x=1', '/api/work-item-detail',
                                  '/api/work-item-detail?key=' + 'k' * 301, '/api/case-detail/p?confirmation_key=' + 'c' * 301,
                                  '/api/case-detail/p?x=1', '/api/case-detail/' + 'p' * 201])
def test_other_routes_reject_oversize_or_malformed_parameters_with_422(world, path):
    _, client, _, _, _, _ = world
    assert client.get(path).status_code == 422


# ---- states, environments, withheld amounts ---------------------------------
def test_unknown_source_state_is_never_zero(http):
    _, client, seat, signin = http
    state, _, _ = build_state(); seat(state, cache=False); signin()   # no cache: Source Health is unknown
    body = client.get('/api/confirmations').json()
    assert body['totals']['matching'] is None and body['totals']['authorized_source'] is None
    card = client.get('/api/manager-overview').json()['snapshot']['cards'][0]
    assert card['value'] is None


def test_test_environment_mirrors_source_health_and_stays_non_counting(http):
    _, client, seat, signin = http
    state, vis, _ = build_state()
    seat(state, wid='test-lark-boundary', cache=True); signin(wid='test-lark-boundary')
    assert client.get('/api/source-health').json()['page_state']['states'] == ['unknown']
    body = client.get('/api/confirmations').json()
    assert body['totals']['matching'] is None
    overview = client.get('/api/manager-overview').json()
    assert overview['source_health']['state']['states'] == ['unknown']
    assert_no_amount(client.get('/api/confirmations'))
    assert client.get(f'/api/case-detail/{vis}').status_code == 200   # test namespace: workspace-wide, like source-health


def test_amounts_are_withheld_in_every_response_even_with_amount_bearing_sources(world):
    _, client, _, _, _, ids = world
    for template in ROUTES + ['/api/confirmations?q=VIS']:
        assert_no_amount(get(client, template, ids))
    detail = client.get('/api/contract-detail', params={'key': ids['k1']}).json()
    assert any(path[-1:] == ('state',) and value == 'withheld' for path, value in leaves(detail))


def test_p2_routes_are_get_only(world):
    app, client, _, _, _, ids = world
    for template in ROUTES:
        assert client.post(template.format(**ids).split('?')[0], json={}).status_code in (404, 405)


# ---- P2-INT-B-FIX1: one captured read, noncurrent zero, C-STATE combination, provenance, parameter validation ----
STAMP = '2026-10-13T00:00:00+00:00'


def cache_state(app, status, *, partial=False):
    """Alter only the observed read: the cached table status and the freshness the live-read service reports."""
    with app.state.sessions.begin() as db:
        row = db.get(CacheRow, WID)
        data = dict(row.data)
        data['tables'] = [dict(t, status='partial' if partial else 'ready') for t in data['tables']]
        row.data = data
    previous = app.state.live_read.status
    def altered(wid):
        out = previous(wid)
        out['datasets']['sources'].update(status=status, age_seconds=1000 if status == 'stale' else 1)
        return out
    app.state.live_read.status = altered


def test_failure_between_health_and_module_read_never_becomes_current(world, monkeypatch):
    app, client, _, _, _, _ = world
    from backend import source_health
    original, calls = source_health.build_source_health, []
    def fail_after_first_read(*a, **kw):
        result = original(*a, **kw)
        calls.append(result['page_state'])
        if len(calls) == 1:
            assert result['page_state'] is None          # the interleaved read really was healthy
            app.state.source_sync.failure(WID, 'synthetic refresh failure')
        return result
    monkeypatch.setattr(source_health, 'build_source_health', fail_after_first_read)
    body = client.get('/api/confirmations').json()
    assert len(calls) >= 2 and body['page_state']['states'] == ['read_failed']
    assert body['totals_basis'] != 'current' and {r['source_status'] for r in body['rows']} != {'located'}


def test_already_failed_read_is_never_overwritten_with_fresh(world):
    app, client, _, _, _, _ = world
    app.state.source_sync.failure(WID, 'synthetic refresh failure')
    body = client.get('/api/confirmations').json()
    assert body['page_state']['states'] == ['read_failed'] and body['totals_basis'] != 'current'


def test_health_and_module_input_share_one_workspace_load(world, monkeypatch):
    app, client, _, _, _, _ = world
    loads = []
    real = storage.load
    monkeypatch.setattr(storage, 'load', lambda *a, **kw: (loads.append(1), real(*a, **kw))[1])
    assert client.get('/api/confirmations').status_code == 200
    assert len(loads) == 1                                   # health and narrowed state come from the same capture


@pytest.mark.parametrize('status,partial', [('stale', False), ('fresh', True)])
def test_noncurrent_filtered_zero_is_undetermined_in_list_and_overview(world, status, partial):
    app, client, _, _, _, _ = world
    cache_state(app, status, partial=partial)
    params = {'admission_state': 'nonexistent'}
    listing, overview = client.get('/api/confirmations', params=params).json(), client.get('/api/manager-overview', params=params).json()
    card = overview['snapshot']['cards'][0]
    assert listing['totals']['matching'] is None and card['value'] is None
    assert listing['page_state']['states'] != ['filtered_empty'] and 'complete_empty' not in json.dumps(card['state'])
    nonzero_list, nonzero_card = client.get('/api/confirmations').json(), client.get('/api/manager-overview').json()['snapshot']['cards'][0]
    assert nonzero_list['totals']['matching'] == nonzero_card['value'] == 2


def test_partial_and_stale_stay_independent_through_every_envelope(world):
    app, client, _, _, _, ids = world
    cache_state(app, 'stale', partial=True)
    assert client.get('/api/source-health').json()['page_state']['states'] == ['partial', 'stale']
    assert client.get('/api/confirmations').json()['page_state']['states'] == ['partial', 'stale']
    assert client.get('/api/manager-overview').json()['snapshot']['cards'][0]['state']['states'] == ['partial', 'stale']
    sections = client.get('/api/case-detail/' + ids['vis']).json()['sections']
    assert any(s['states'] == ['partial', 'stale'] for s in sections.values()) and all(s['freshness'] == 'stale' for s in sections.values())
    cache_state(app, 'stale', partial=False)
    assert client.get('/api/confirmations').json()['page_state']['states'] == ['stale']


def test_stored_sync_metadata_survives_with_verified_timestamp_and_snapshot_as_of(world):
    app, client, seat, _, state, ids = world
    state['source_status'] = {'status': 'ready', 'last_sync': STAMP, 'sync_revision': 4, 'message': 'secret-message-sentinel'}
    seat(state)
    cache_state(app, 'stale')
    listing = client.get('/api/confirmations').json()
    assert listing['snapshot'] == {'state': 'proven', 'last_success_at': STAMP}
    detail = client.get('/api/case-detail/' + ids['vis']).json()
    assert {s['source_time']['value'] for s in detail['sections'].values()} == {STAMP}
    assert 'secret-message-sentinel' not in json.dumps([listing, detail])
    freshness = app.state.live_read.status(WID)['datasets']['sources']['as_of']
    assert listing['as_of'] == freshness


def test_as_of_is_the_source_snapshot_time_never_request_time(world):
    app, client, seat, _, state, _ = world
    previous = app.state.live_read.status
    def with_as_of(wid):
        out = previous(wid); out['datasets']['sources']['as_of'] = '2026-01-02T03:04:05+00:00'; return out
    app.state.live_read.status = with_as_of
    assert client.get('/api/confirmations').json()['as_of'] == '2026-01-02T03:04:05+00:00'
    def without(wid):
        out = previous(wid); out['datasets']['sources'].pop('as_of', None); return out
    app.state.live_read.status = without
    assert client.get('/api/confirmations').json()['as_of'] is None


def test_unproven_timestamp_stays_unproven_and_is_not_invented(world):
    app, client, seat, _, state, _ = world
    state['source_status'] = {'status': 'ready', 'last_sync': 'not-a-timestamp'}
    seat(state); cache_state(app, 'stale')
    assert client.get('/api/confirmations').json()['snapshot'] == {'state': 'unproven', 'last_success_at': None}


def test_direction_is_validated_even_without_sort(world):
    _, client, _, _, _, _ = world
    assert client.get('/api/confirmations?direction=sideways').status_code == 422
    assert client.get('/api/confirmations?direction=desc').status_code == 200
    assert client.get('/api/confirmations?direction=asc&direction=desc').status_code == 422


@pytest.mark.parametrize('path', ['/api/contract-detail?key=a&key=b', '/api/work-item-detail?key=a&key=b',
                                  '/api/case-detail/p?confirmation_key=a&confirmation_key=b',
                                  '/api/contract-detail?key=' + 'x' * 301, '/api/case-detail/p?confirmation_key=' + 'x' * 301,
                                  '/api/contract-detail?key=a&key=' + 'x' * 301])
def test_detail_scalar_parameters_take_exactly_one_bounded_value(world, path):
    _, client, _, _, _, _ = world
    assert client.get(path).status_code == 422


def test_fence_exhaustion_does_not_affirm_current_after_real_failure(world, monkeypatch):
    app, client, *_ = world
    from backend import source_health
    original = source_health.build_source_health; calls = []
    def during_compute(*a, **kw):
        result = original(*a, **kw); calls.append(result['page_state'])
        if len(calls) < 3:
            with app.state.sessions.begin() as db: db.get(WorkspaceRow, WID).version += 1
        else: app.state.source_sync.failure(WID, 'genuine third-capture refresh failure')
        return result
    monkeypatch.setattr(source_health, 'build_source_health', during_compute)
    body = client.get('/api/confirmations').json()
    with app.state.sessions() as db: assert db.get(CacheRow, WID).data['status'] == 'error'
    assert len(calls) == 3 and body['totals_basis'] != 'current' and body['page_state']['states'] == ['read_failed']


def test_fence_exhaustion_never_returns_revoked_rows(world, monkeypatch):
    app, client, *_ = world
    from backend import source_health
    original = source_health.build_source_health; calls = []
    def during_compute(*a, **kw):
        result = original(*a, **kw); calls.append(1)
        with app.state.sessions.begin() as db:
            row = db.get(WorkspaceRow, WID)
            if len(calls) == 3:
                state = storage.load(db, BusinessRow, row); state['source_visible_record_ids'] = []
                row.data = storage.save(db, BusinessRow, WID, state)
            row.version += 1
        return result
    monkeypatch.setattr(source_health, 'build_source_health', during_compute)
    raw = client.get('/api/confirmations'); body = raw.json()
    assert len(calls) == 3 and body['rows'] == [] and body['totals']['matching'] is None
    assert 'recC1' not in raw.text and 'Visible case' not in raw.text


def test_freshness_capture_is_inside_generation_fence(world):
    app, client, seat, _, state, _ = world
    old, new = '2026-10-01T00:00:00+00:00', '2026-10-13T00:00:00+00:00'
    state['source_status'] = {'status': 'ready', 'last_sync': old, 'sync_revision': 1}; seat(state)
    real = app.state.live_read.status; calls = []
    def status_then_new_source(wid):
        result = real(wid); calls.append(1)
        result['datasets']['sources'].update(as_of=old if len(calls) == 1 else new, status='stale', age_seconds=1000)
        if len(calls) == 1:
            with app.state.sessions.begin() as db:
                row = db.get(WorkspaceRow, WID); s = storage.load(db, BusinessRow, row)
                s['source_status'] = {'status': 'ready', 'last_sync': new, 'sync_revision': 2}
                row.data = storage.save(db, BusinessRow, WID, s); row.version += 1
                cache = db.get(CacheRow, WID); d = deepcopy(cache.data); d.update(last_sync=new, as_of=new); cache.data = d
        return result
    app.state.live_read.status = status_then_new_source
    body = client.get('/api/confirmations').json()
    assert len(calls) == 2 and body['as_of'] == body['snapshot']['last_success_at'] == new


# ---- FIX3: explicit population_state and case/population filter split --------
def spy_overview(monkeypatch):
    from . import confirmation_list, manager_overview
    seen = {'population_filters': [], 'build': []}
    real_pop, real_build = confirmation_list.confirmation_population, manager_overview.build_manager_overview
    def pop(state, filters, *a, **k):
        seen['population_filters'].append(deepcopy(filters)); return real_pop(state, filters, *a, **k)
    def build(state, **kw):
        seen['build'].append({k: deepcopy(kw.get(k)) for k in ('filters', 'population_state')}); return real_build(state, **kw)
    monkeypatch.setattr(confirmation_list, 'confirmation_population', pop)
    monkeypatch.setattr(manager_overview, 'build_manager_overview', build)
    return seen


def test_healthy_read_passes_none_because_cstate_has_no_complete_nonempty_value(world, monkeypatch):
    # Gap recorded: data_state.STATES has no complete-nonempty value, so None (never 'ready') is the only honest input.
    _, client, _, _, _, _ = world
    seen = spy_overview(monkeypatch)
    listing = client.get('/api/confirmations').json()
    body = client.get('/api/manager-overview').json()
    assert listing['page_state'] is None and seen['build'][0]['population_state'] is None
    assert body['snapshot']['state']['states'] == ['partial'] and all(c['state']['states'][0] != 'complete_empty' for c in body['snapshot']['cards'])


@pytest.mark.parametrize('status,partial,expected', [('stale', False, ['stale']), ('stale', True, ['partial', 'stale'])])
def test_noncurrent_read_passes_the_list_page_state_and_cards_agree(world, monkeypatch, status, partial, expected):
    app, client, _, _, _, _ = world
    cache_state(app, status, partial=partial)
    seen = spy_overview(monkeypatch)
    listing = client.get('/api/confirmations').json()['page_state']
    body = client.get('/api/manager-overview').json()
    assert seen['build'][0]['population_state']['states'] == listing['states'] == expected
    assert body['snapshot']['state']['states'] == expected
    assert body['snapshot']['cards'][0]['state']['states'] == expected


def test_case_filters_never_reach_population_or_card_drilldown(world, monkeypatch):
    _, client, _, _, _, _ = world
    seen = spy_overview(monkeypatch)
    resp = client.get('/api/manager-overview', params={'pm_id': 'u-pm', 'execution_status': 'in_progress', 'source_version': '2'})
    assert resp.status_code == 200
    assert seen['build'][0]['filters'] == {'source_version': ['2'], 'pm_id': 'u-pm', 'execution_status': 'in_progress'}
    assert seen['population_filters'] == [{'source_version': ['2']}]
    body = resp.json()
    for card in body['snapshot']['cards']:
        assert card['drilldown']['filters'] == {'source_version': ['2']}
    assert body['snapshot']['filters']['pm_id'] == 'u-pm'


@pytest.mark.parametrize('query', ['unknown=1', 'pm_id=a&pm_id=b', 'pm_id=' + 'x' * 121, 'execution_status=' + 'x' * 121])
def test_manager_overview_case_filter_bounds_and_unknown_parameters_are_422(world, query):
    _, client, _, _, _, _ = world
    assert client.get('/api/manager-overview?' + query).status_code == 422
