"""P2-INT-B: the five P2 GET routes over a synthetic isolated SQLite workspace. No Lark or cloud data."""
import json
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
