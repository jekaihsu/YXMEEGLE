"""Daily list coverage must state the rows its authorized query can actually return."""
import pytest

from . import storage
from .app import BusinessRow, WorkspaceRow
from .source_projection import daily_index
from .test_backend import app, client
from .test_public_case_http_boundaries import isolated_http


def save_state(app, wid, change):
    with app.state.sessions.begin() as db:
        row = db.get(WorkspaceRow, wid)
        state = storage.load(db, BusinessRow, row)
        change(state)
        row.data = storage.save(db, BusinessRow, wid, state)


def test_daily_index_coverage_is_query_scope_not_global_mapping():
    state = {'projects': [{'id': 'p', 'code': 'C1', 'daily_reports': [{'id': 'matched'}]}],
             'daily_unmatched': [{'id': 'orphan'}],
             'source_status': {'mapping': {'daily_unmatched': 535}}}
    all_rows = daily_index(state)
    assert all_rows['total'] == 2
    assert all_rows['coverage'] == {'scope': 'workspace', 'project_only': False, 'unmatched_available': True}
    case = daily_index(state, project_id='p')
    assert case['total'] == 1 and case['summary']['unmatched'] == 0
    assert case['coverage'] == {'scope': 'workspace', 'project_only': True, 'unmatched_available': False}
    with pytest.raises(ValueError, match='coverage scope'):
        daily_index(state, coverage_scope='unverified')


def test_demo_daily_endpoint_includes_unmatched_and_labels_coverage(app, client):
    wid = app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
    save_state(app, wid, lambda state: state['daily_unmatched'].append(
        {'id': 'demo-orphan', 'date': '2026-10-01', 'description': 'Unmatched demo report'}))
    result = client.get('/api/daily-reports', params={'status': 'unmatched'}).json()
    assert result['coverage'] == {'scope': 'workspace', 'project_only': False, 'unmatched_available': True}
    assert [row['id'] for row in result['items']] == ['demo-orphan']
    case = client.get('/api/daily-reports', params={'project_id': 'p1'}).json()
    assert case['coverage']['project_only'] and not case['coverage']['unmatched_available']
    assert 'demo-orphan' not in {row['id'] for row in case['items']}


def test_production_daily_endpoint_is_visible_case_only(isolated_http):
    app, client, _, signin = isolated_http

    def add_reports(state):
        old, current = state['projects'][:2]
        old['daily_reports'].append({'id': 'hidden-match', 'date': '2026-10-01',
                                     'description': 'OLD_CASE_SENTINEL'})
        current['daily_reports'].append({'id': 'visible-match', 'date': '2026-10-01',
                                         'description': 'Visible matched report'})
        state['source_visible_record_ids'].append('base|table|recDaily')
        state['daily_unmatched'].append({'id': 'authorized-orphan', 'date': '2026-10-01',
                                         'description': 'Unassigned source report',
                                         'source_identity': {'base_token': 'base', 'table_id': 'table',
                                                             'record_id': 'recDaily'}})

    save_state(app, 'lark-boundary', add_reports)
    for uid in ('u-manager', 'u-pm'):
        signin(uid)
        response = client.get('/api/daily-reports')
        assert response.status_code == 200
        result = response.json()
        assert result['coverage'] == {'scope': 'visible_cases', 'project_only': False,
                                      'unmatched_available': False}
        ids = {row['id'] for row in result['items']}
        assert 'visible-match' in ids
        assert 'hidden-match' not in ids and 'authorized-orphan' not in ids
        assert result['summary']['unmatched'] == 0
        assert 'OLD_CASE_SENTINEL' not in response.text
        unmatched = client.get('/api/daily-reports', params={'status': 'unmatched'}).json()
        assert unmatched['total'] == 0 and not unmatched['coverage']['unmatched_available']
        case = client.get('/api/daily-reports', params={'project_id': 'p2'}).json()
        assert case['coverage']['project_only'] and not case['coverage']['unmatched_available']
        assert 'visible-match' in {row['id'] for row in case['items']}
