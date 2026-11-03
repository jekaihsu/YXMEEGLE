"""Independent lifecycle pages, including cold and incomplete projections."""
import pytest
from sqlalchemy import select, update
from .test_portfolio_live import database
from .test_perf_budget import scaled_client
from .test_shell import ON
from .test_projects_portfolio import portfolio_case
from .test_ux_home_panels import home
from . import index_tables, storage
from .models import BusinessRow, WorkspaceRow


def test_sections_are_bounded_and_counts_cover_the_capture(tmp_path, database):
    with scaled_client(tmp_path, 65, **ON, **database) as (app, client):
        body = client.get('/api/projects?view=portfolio&page=1&sections=true').json()
        assert sum(s['total'] for s in body['sections'].values()) == body['total'] == 65
        assert len(body['items']) <= 4 * 25
        for key, section in body['sections'].items():
            assert sum(p['lifecycle_section'] == key for p in body['items']) == min(25, section['total'])
            if section['next_page']:
                more = client.get('/api/projects', params=dict(view='portfolio', sections='true', section=key,
                    page=section['next_page'], snapshot=body['snapshot'])).json()
                assert len(more['items']) <= 25
                assert all(p['lifecycle_section'] == key for p in more['items'])
                assert not {p['id'] for p in body['items']} & {p['id'] for p in more['items']}


def test_null_summary_is_unknown_for_only_that_case(tmp_path, database):
    with scaled_client(tmp_path, 4, **ON, **database) as (app, client):
        with app.state.sessions.begin() as db:
            root = db.scalars(select(WorkspaceRow)).first()
            pi, _, _ = index_tables.tables(BusinessRow)
            pid = db.scalar(select(pi.c.project_id).where(pi.c.workspace_id == root.id).limit(1))
            db.execute(update(pi).where(pi.c.workspace_id == root.id, pi.c.project_id == pid).values(summary=None))
        body = client.get('/api/projects?view=portfolio&page=1&sections=true').json()
        item = next(p for p in body['items'] if p['id'] == pid)
        assert item['lifecycle_state'] == '待核對'
        assert item['lifecycle_section'] == 'other'
        assert body['unknown_total'] == 1
        assert all(p['lifecycle_state'] != '待核對' for p in body['items'] if p['id'] != pid)


def test_filtered_sections_searches_the_entire_capture(tmp_path, database):
    import json
    with scaled_client(tmp_path, 65, **ON, **database) as (_, client):
        all_rows = client.get('/api/projects?view=portfolio').json()['items']
        last = all_rows[-1]
        result = client.get('/api/projects', params=dict(view='portfolio', sections='true', page=1,
            filters=json.dumps(dict(q=last['code'], sort='name')))).json()
        assert last['id'] in [p['id'] for p in result['items']]
        assert result['total'] == sum(s['total'] for s in result['sections'].values())
        assert result['workspace_total'] == 65


def test_cold_linked_placeholders_are_unknown_not_unstarted(portfolio_case):
    h = portfolio_case
    h.home.service.portfolio_overlay = lambda *_: ({}, True)
    body = h.read(warm=False)
    assert body['node_status_degraded']
    assert all(p['lifecycle_state'] == '待核對' for p in body['items'])
    assert all(p['lifecycle_section'] == 'other' for p in body['items'])
    assert all(n['status'] == 'unknown' for p in body['items'] for n in p['portfolio_nodes'])


def test_section_continuation_preserves_history_and_replaces_missing_capture(tmp_path, database):
    with scaled_client(tmp_path, 65, **ON, **database) as (app, client):
        first = client.get('/api/projects?view=portfolio&page=1&sections=true').json()
        key = next(k for k, v in first['sections'].items() if v['next_page'])
        params = dict(view='portfolio', sections='true', section=key, page=2, snapshot=first['snapshot'])
        with app.state.sessions.begin() as db:
            row = db.scalars(select(WorkspaceRow)).first()
            state = storage.load(db, BusinessRow, row)
            row.version += 1
            state['version'] = row.version
            row.data = storage.save(db, BusinessRow, row.id, state)
        second = client.get('/api/projects', params=params).json()
        assert second['stale']
        if second['snapshot_replaced']:
            assert len(second['items']) == second['total'] == 65
        else:
            assert second['snapshot'] == first['snapshot']
            assert not {p['id'] for p in first['items']} & {p['id'] for p in second['items']}
        app.state.portfolio_captures.clear()
        replacement = client.get('/api/projects', params=params).json()
        assert replacement['snapshot_replaced'] and replacement['stale']
        assert len(replacement['items']) == replacement['total'] == 65
        assert all(v['next_page'] is None for v in replacement['sections'].values())


def test_cold_overlay_does_not_decode_source_or_daily_evidence(portfolio_case, monkeypatch):
    from . import storage
    h = portfolio_case
    original = storage.load_partial
    def bounded(*args, **kwargs):
        assert not set(kwargs.get('collections', ())) & {'contract_items', 'source_confirmations', 'source_work_items'}
        return original(*args, **kwargs)
    monkeypatch.setattr(storage, 'load_partial', bounded)
    monkeypatch.setattr(h.home.service, 'portfolio_overlay', lambda *_: ({}, True))
    assert h.read(warm=False)['node_status_degraded']


@pytest.mark.parametrize('filters', ['[]', '{"sort":[]}', '{"q":123}', '{"direction":true}', '{"attention":"yes"}', '{broken'])
def test_malformed_section_filters_are_rejected(tmp_path, filters):
    with scaled_client(tmp_path, 2, **ON) as (_, client):
        assert client.get('/api/projects', params=dict(view='portfolio',sections='true',page=1,filters=filters)).status_code == 422
