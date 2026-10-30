"""Differential case captures over isolated importer data; no remote readers."""
from copy import deepcopy

import pytest
from sqlalchemy import select

from . import source_health, storage
from .app import BusinessRow, CacheRow, WorkspaceRow
from .case_universe import build_universe
from .test_p2_int_routes import http, WID  # noqa: F401


@pytest.fixture(autouse=True)
def enable_case_reads(monkeypatch):
    monkeypatch.setenv('WORKSPACE_SHELL_ENABLED','true')


@pytest.mark.parametrize('uid', ['u-manager', 'u-field', 'unauthorized', 'disabled', None])
@pytest.mark.parametrize('endpoint', ['progress', 'navigation'])
@pytest.mark.parametrize('environment', ['production', 'test'])
def test_compact_capture_matches_original_for_every_actor(http, monkeypatch, uid, endpoint, environment):
    app, client, seat, signin = http
    state, _, pid = build_universe()
    state['users'].append(dict(state['users'][0], id='disabled', active=False))
    wid = WID if environment == 'production' else 'test-' + WID
    seat(state, wid=wid)
    if uid is not None: signin(uid, wid=wid)
    app.state.cfg['REPORTS_ENABLED'] = 'false'
    paths = [f'/api/projects/{pid}/{endpoint}', f'/api/projects/missing/{endpoint}']
    actual = [client.get(path) for path in paths]

    original = storage.load_partial
    def full_rows(db, model, row, **kwargs):
        kwargs.pop('case_sources', None)
        return original(db, model, row, **kwargs)
    def full_cache(db, model, wid):
        cache = db.get(model, wid)
        return cache.data if cache else None
    monkeypatch.setattr(storage, 'load_partial', full_rows)
    monkeypatch.setattr(source_health, 'load_source_metadata', full_cache)
    expected = [client.get(path) for path in paths]
    for compact, legacy in zip(actual, expected):
        assert compact.status_code == legacy.status_code
        assert compact.json() == legacy.json()
    if uid in ('u-manager', 'u-field'):
        assert actual[0].status_code == 200
        assert actual[1].status_code == 404
    else:
        assert actual[0].status_code in (401, 403, 404)


def test_health_metadata_keeps_missing_identity_keys_and_table_evidence(http):
    app, _, seat, _ = http
    state, _, _ = build_universe()
    seat(state)
    with app.state.sessions.begin() as db:
        cache = db.get(CacheRow, WID)
        payload = deepcopy(cache.data)
        payload.update(authorized=True, status='partial')
        payload['records'] = [
            dict(base_token='b', table_id='t', record_id='r', fields={'large': ['private'] * 1000}),
            dict(base_token='b'), dict(base_token=None, record_id=''), {},
        ]
        cache.data = payload
    with app.state.sessions() as db:
        compact = source_health.load_source_metadata(db, CacheRow, WID)
        assert compact['records'] == [{k: v for k, v in row.items() if k != 'fields'} for row in payload['records']]
        assert compact['tables'] == payload['tables']
        assert compact['authorized'] is True
        assert source_health.load_source_metadata(db, CacheRow, 'missing') is None


def test_compact_sources_do_not_share_authority_or_hide_a_writers_own_updates(http):
    app, _, seat, _ = http
    state, _, pid = build_universe()
    seat(state)
    def read(db):
        return storage.load_partial(db, BusinessRow, db.get(WorkspaceRow, WID),
            collections=storage.CASE_COLLECTIONS, project_ids=[pid], filter_project_rows=True, case_sources=True)
    with app.state.sessions() as db:
        first = read(db)
        assert first['source_quotes']
        complete = storage.load_partial(db, BusinessRow, db.get(WorkspaceRow, WID),
            collections=storage.CASE_COLLECTIONS, project_ids=[pid], filter_project_rows=True)
        assert any('history' in q for q in complete['source_quotes'])
        assert all('history' not in q for q in first['source_quotes'])
    with app.state.sessions.begin() as db:
        user = db.scalars(select(BusinessRow).where(BusinessRow.workspace_id == WID, BusinessRow.kind == 'users')).first()
        user.data = dict(user.data, capabilities=['fresh-authority'])
    with app.state.sessions() as db:
        second = read(db)
        assert any(u.get('capabilities') == ['fresh-authority'] for u in second['users'])
    with app.state.sessions.begin() as db:
        root = db.get(WorkspaceRow, WID)
        saved = storage.load(db, BusinessRow, root)
        saved['source_quotes'][0]['code'] = 'fresh-source'
        root.data = storage.save(db, BusinessRow, WID, saved)
        assert any(q.get('code') == 'fresh-source' for q in read(db)['source_quotes'])
    with app.state.sessions() as db:
        assert any(q.get('code') == 'fresh-source' for q in read(db)['source_quotes'])


def test_progress_rejects_every_capture_when_metadata_generation_changes(http, monkeypatch):
    app, client, seat, signin = http
    state, _, pid = build_universe()
    seat(state)
    signin()
    original = source_health.load_source_metadata
    captures = []
    def changed(db, model, wid):
        snapshot = original(db, model, wid)
        captures.append(snapshot)
        with app.state.sessions.begin() as writer:
            writer.get(WorkspaceRow, wid).version += 1
        return snapshot
    monkeypatch.setattr(source_health, 'load_source_metadata', changed)
    response = client.get(f'/api/projects/{pid}/progress')
    assert len(captures) == 3
    assert response.status_code == 404
    assert 'recCaseA' not in response.text and 'C115901' not in response.text


@pytest.mark.parametrize('uid',['u-manager','u-field','unauthorized',None])
def test_overview_matches_full_case_controls_and_privacy(http,uid):
    app,client,seat,signin=http
    state,_,pid=build_universe()
    seat(state)
    if uid: signin(uid)
    compact=client.get(f'/api/projects/{pid}?overview=true')
    complete=client.get(f'/api/projects/{pid}')
    assert compact.status_code==complete.status_code
    if uid in ('u-manager','u-field'): assert complete.status_code==200
    if complete.status_code==200:
        for key in ('project','policy_summary','approvals','financial_requests'):
            assert compact.json().get(key)==complete.json().get(key)


def test_formal_case_read_never_materializes_global_events_or_unrelated_feeds(http):
    from types import SimpleNamespace
    app,_,seat,_=http
    state,_,pid=build_universe()
    state['environment']='production'
    state['events']=[{'id':f'global-{i}','message':'global event'} for i in range(500)]
    state['events'] += [{'id':'mine','project_id':pid,'message':'case event'},
                        {'id':'other','project_id':'another-case','message':'other case'}]
    seat(state)
    with app.state.sessions() as db:
        row=db.get(WorkspaceRow,WID)
        result=storage.load_partial(db,BusinessRow,row,collections=('events',),
                                    project_ids=[pid],filter_project_rows=True)
        assert [event['id'] for event in result['events']]==['mine']
        assert len(storage.load_partial(db,BusinessRow,row,collections=('events',))['events'])==502
        legacy=SimpleNamespace(id=WID,data=dict(state,storage_schema=1))
        result=storage.load_partial(db,BusinessRow,legacy,collections=('events',),
                                    project_ids=[pid],filter_project_rows=True)
        assert [event['id'] for event in result['events']]==['mine']
    assert not {'work_schedules','daily_unmatched'} & set(storage.CASE_DETAIL_COLLECTIONS)
    assert {'approvals','financial_requests','delegations','approved_leave_delegations'} <= set(storage.CASE_DETAIL_COLLECTIONS)
