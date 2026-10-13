"""VCC-99 P4-2: GET /api/projects?view=overview pages, filters, sorts and counts project cards in SQL."""
import pytest
from sqlalchemy import event, select, update
from .models import WorkspaceRow
from .test_perf_budget import scaled_client
from .test_shell import ON, switch

TABS = ['all', 'formal', 'intake', 'active', 'overdue', 'completed']


def everything(client, **query):
    """Walk every page of an overview query and return (first page, all items)."""
    items, first, offset = [], None, 0
    while True:
        page = client.get('/api/projects', params={'view': 'overview', 'limit': 7, 'offset': offset, **query}).json()
        first = first or page
        items += page['items']
        offset += 7
        if offset >= page['total']: return first, items


def test_overview_is_flag_gated_and_validated(tmp_path):
    with scaled_client(tmp_path, 4, upgraded=True, INDEX_TABLES_ENABLED='true') as (app, client):
        assert client.get('/api/projects?view=overview').status_code == 422  # shell flag off
    with scaled_client(tmp_path / 'b', 4, **ON) as (app, client):
        for bad in ('view=other', 'view=overview&tab=zzz', 'view=overview&sort=zzz', 'view=overview&dir=up', 'view=overview&limit=0'):
            assert client.get('/api/projects?' + bad).status_code == 422, bad
        assert client.get('/api/projects?limit=3').json().keys() == {'total', 'offset', 'limit', 'items'}  # legacy body untouched


def test_overview_pages_equal_shell_cards_for_every_tab_and_sort(tmp_path):
    with scaled_client(tmp_path, 30, **ON) as (app, client):
        switch(client, 'u-manager')
        shell = client.get('/api/workspace?scope=shell').json()
        cards = {p['id']: p for p in shell['projects']}
        for tab in TABS:
            for sort in ('due', 'name', 'progress', 'created'):
                for direction in ('asc', 'desc'):
                    first, items = everything(client, tab=tab, sort=sort, dir=direction)
                    assert first['facets'] == {'all': 30, 'formal': sum(p['case_type'] != 'intake' for p in cards.values()),
                                               'intake': sum(p['case_type'] == 'intake' for p in cards.values())}
                    assert len(items) == first['total'] == len({i['id'] for i in items})
                    for item in items:
                        # Shell omits the duplicate execution status; preserve
                        # semantic parity while comparing every other field.
                        card = cards[item['id']]
                        assert item['execution_status'] == card['status']
                        assert {key:value for key,value in item.items() if key!='execution_status'} == card, (tab, sort)
                    if sort == 'due':
                        keys = [(i['due_date'] or '9999', i['id']) for i in items]
                        assert keys == sorted(keys, reverse=direction == 'desc')
                    if sort == 'progress':
                        ratio = [i['progress']['completed_nodes'] / (i['progress']['total_nodes'] or 1) for i in items]
                        assert ratio == sorted(ratio, reverse=direction == 'desc')
        total = lambda **q: everything(client, **q)[0]['total']
        assert total(tab='overdue') == sum(p['overdue_tasks'] > 0 for p in cards.values())
        assert total(tab='completed') + total(tab='active') == 30
        assert total(tab='formal') + total(tab='intake') == 30


def test_overview_search_owner_status_filters(tmp_path):
    with scaled_client(tmp_path, 20, **ON) as (app, client):
        switch(client, 'u-manager')
        every = {p['id']: p for p in everything(client, tab='all')[1]}
        code = next(iter(every.values()))['code']
        _, hit = everything(client, tab='all', q=code.lower())
        assert hit and all(code.lower() in (p['code'] + p['name'] + p['client']).lower() for p in hit)
        assert everything(client, tab='all', q='%')[0]['total'] == 0  # wildcards are literal
        pm = next(iter(every.values()))['pm_id']
        _, mine = everything(client, tab='all', owner=pm)
        assert {p['id'] for p in mine} == {i for i, p in every.items() if p['pm_id'] == pm}
        assert everything(client, tab='all', status='nope')[0]['total'] == 0
        assert everything(client, tab='all', q=code)[0]['facets']['all'] == 20  # facets ignore filters


@pytest.mark.parametrize('sort', ['due', 'created'])
def test_overview_first_page_reads_ten_cards_only(tmp_path, sort):
    with scaled_client(tmp_path, 60, **ON) as (app, client):
        statements = []
        listener = lambda conn, cur, st, params, ctx, many: statements.append((st, params))
        event.listen(app.state.engine, 'before_cursor_execute', listener)
        try: body = client.get('/api/projects?view=overview&limit=10&sort=' + sort).json()
        finally: event.remove(app.state.engine, 'before_cursor_execute', listener)
        assert len(body['items']) == 10 and body['total'] == 60 and body['facets']['all'] == 60
        pages = [st for st, p in statements if 'FROM project_index' in st and 'LIMIT' in st]
        assert len(pages) == 1 and 'OFFSET' in pages[0]
        assert not any('FROM business_records' in st and 'tasks' in str(p) for st, p in statements)


def test_overview_requires_ready_index_and_hides_invisible_cases(tmp_path, monkeypatch):
    from . import workspace_environment
    with scaled_client(tmp_path, 8, **ON) as (app, client):
        with app.state.sessions.begin() as db:
            db.get(WorkspaceRow, client.get('/api/workspace').json()['workspace_id']).version += 1
        assert client.get('/api/projects?view=overview').status_code == 503
    with scaled_client(tmp_path / 'b', 8, **ON) as (app, client):
        from .models import ProjectIndex
        with app.state.sessions.begin() as db:
            ids = [r for r in db.scalars(select(ProjectIndex.project_id).limit(3))]
            db.execute(update(ProjectIndex).where(ProjectIndex.project_id.in_(ids)).values(case_visibility='excluded_history'))
        monkeypatch.setattr(workspace_environment, 'normalize_environment', lambda state, wid, cfg: state.update(environment='production') or state)
        body = client.get('/api/projects?view=overview&tab=all&limit=100').json()
        assert body['total'] == 5 == body['facets']['all'] and not {i['id'] for i in body['items']} & set(ids)


def test_created_sort_order_filters_and_empty_last(tmp_path):
    from .models import ProjectIndex
    with scaled_client(tmp_path, 30, **ON) as (app, client):
        with app.state.sessions.begin() as db:
            rows = db.scalars(select(ProjectIndex).order_by(ProjectIndex.ordinal)).all()
            ids = [r.project_id for r in rows]
            for i, r in enumerate(rows):
                r.created_at = '' if i >= 27 else f'2026-10-{i // 3 + 1:02d}T09:00:00+08:00'
        for direction, expected in [('asc', ids), ('desc', ids[:27][::-1] + ids[27:][::-1])]:
            response = client.get('/api/projects?view=overview&sort=created&dir=' + direction)
            assert response.status_code == 200
            first, items = everything(client, tab='all', sort='created', dir=direction)
            assert [p['id'] for p in items] == expected
            assert len(items) == first['total'] == 30
            assert [p['id'] for p in everything(client, tab='all', sort='created', dir=direction)[1]] == expected
            # Reverse physical insertion; only domain keys may determine ties.
            with app.state.sessions.begin() as db:
                values = [dict(r) for r in db.execute(select(ProjectIndex.__table__)).mappings()]
                db.execute(ProjectIndex.__table__.delete())
                db.execute(ProjectIndex.__table__.insert(), values[::-1])
            assert [p['id'] for p in everything(client, tab='all', sort='created', dir=direction)[1]] == expected
            for filters in [dict(tab=t) for t in ('formal', 'intake', 'active')] + [dict(tab='all', q=items[0]['code']), dict(tab='all', owner=items[0]['pm_id'])]:
                baseline, selected = everything(client, sort='due', **filters)
                page, ordered = everything(client, sort='created', dir=direction, **filters)
                selected_ids = {p['id'] for p in selected}
                assert [p['id'] for p in ordered] == [pid for pid in expected if pid in selected_ids]
                assert (page['total'], page['facets']) == (baseline['total'], baseline['facets'])


def test_created_sort_id_tie_and_mixed_formats(tmp_path):
    from .models import ProjectIndex
    with scaled_client(tmp_path, 4, **ON) as (app, client):
        with app.state.sessions.begin() as db:
            rows = db.scalars(select(ProjectIndex).order_by(ProjectIndex.project_id)).all()
            ids = [r.project_id for r in rows]
            for r in rows:
                r.created_at = '2026-10-13T09:00:00+08:00'
                r.ordinal = 0
        for direction in ('asc', 'desc'):
            expected = ids if direction == 'asc' else ids[::-1]
            for _ in range(2):
                assert [p['id'] for p in everything(client, tab='all', sort='created', dir=direction)[1]] == expected
        with app.state.sessions.begin() as db:
            for pid, stamp in zip(ids, ['2026-10-13', '2026-10-13T01:00:00Z', '2026-10-13T09:00:00+08:00', '']):
                db.execute(update(ProjectIndex).where(ProjectIndex.project_id == pid).values(created_at=stamp))
        assert [p['id'] for p in everything(client, tab='all', sort='created', dir='asc')[1]] == ids
        assert [p['id'] for p in everything(client, tab='all', sort='created', dir='desc')[1]] == [ids[2], ids[1], ids[0], ids[3]]


def test_created_sort_missing_app_add_times_are_indexed_as_empty(tmp_path):
    def missing_dates(state):
        for p, stamp in zip(state['projects'], [None, '', '2026-10-01', '2026-10-13']):
            p['created_at'] = stamp
    with scaled_client(tmp_path, 4, mutate=missing_dates, **ON) as (app, client):
        ids = [p['id'] for p in client.get('/api/workspace').json()['projects']]
        assert [p['id'] for p in everything(client, tab='all', sort='created', dir='asc')[1]] == [ids[2], ids[3], ids[0], ids[1]]
        assert [p['id'] for p in everything(client, tab='all', sort='created', dir='desc')[1]] == [ids[3], ids[2], ids[1], ids[0]]


@pytest.mark.parametrize('direction, order', [
    ('asc', [1, 0, 2, 3, 4, 5]), ('desc', [3, 2, 0, 1, 5, 4]),
])
def test_added_sort_parses_instants_and_keeps_invalid_last(tmp_path, direction, order):
    from .models import ProjectIndex
    with scaled_client(tmp_path, 6, **ON) as (app, client):
        with app.state.sessions.begin() as db:
            rows = db.scalars(select(ProjectIndex).order_by(ProjectIndex.ordinal)).all()
            ids = [r.project_id for r in rows]
            # App add times: lexical order reverses 00:00Z and 01:00Z.
            stamps = ['2026-10-13T01:00:00+00:00', '2026-10-13T08:00:00+08:00',
                      '2026-10-13T09:00:00+08:00', '2026-10-13T02:00:00Z', 'invalid', '']
            for r, stamp in zip(rows, stamps):
                r.created_at = stamp
        assert [p['id'] for p in everything(client, tab='all', sort='created', dir=direction)[1]] == [ids[i] for i in order]
