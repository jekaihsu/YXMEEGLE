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
            for sort in ('due', 'name', 'progress'):
                for direction in ('asc', 'desc'):
                    first, items = everything(client, tab=tab, sort=sort, dir=direction)
                    assert first['facets'] == {'all': 30, 'formal': sum(p['case_type'] != 'intake' for p in cards.values()),
                                               'intake': sum(p['case_type'] == 'intake' for p in cards.values())}
                    assert len(items) == first['total'] == len({i['id'] for i in items})
                    for item in items: assert all(item[k] == v for k, v in cards[item['id']].items()), (tab, sort)
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


def test_overview_first_page_reads_ten_cards_only(tmp_path):
    with scaled_client(tmp_path, 60, **ON) as (app, client):
        statements = []
        listener = lambda conn, cur, st, params, ctx, many: statements.append((st, params))
        event.listen(app.state.engine, 'before_cursor_execute', listener)
        try: body = client.get('/api/projects?view=overview&limit=10').json()
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
            hidden_amounts = [f['contract_amount'] for f in db.scalars(select(ProjectIndex.shell_facts).where(ProjectIndex.project_id.in_(ids)))]
            db.execute(update(ProjectIndex).where(ProjectIndex.project_id.in_(ids)).values(case_visibility='excluded_history'))
            db.execute(update(ProjectIndex).where(ProjectIndex.project_id == ids[0]).values(case_visibility='source_review'))
        monkeypatch.setattr(workspace_environment, 'normalize_environment', lambda state, wid, cfg: state.update(environment='production') or state)
        body = client.get('/api/projects?view=overview&tab=all&limit=100').json()
        assert body['total'] == 5 == body['facets']['all'] and not {i['id'] for i in body['items']} & set(ids)
        assert not {i['contract_amount'] for i in body['items']} & set(hidden_amounts)


def edit_workspace(app, client, edit):
    from . import storage
    from .models import BusinessRow
    from .policy import upgrade
    wid = app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
    with app.state.sessions.begin() as db:
        row = db.get(WorkspaceRow, wid)
        state = upgrade(storage.load(db, BusinessRow, row))
        edit(state)
        state['version'] = row.version + 1
        row.data = storage.save(db, BusinessRow, wid, state); row.version = state['version']


@pytest.mark.parametrize('uid', ['u-manager', 'ou_020'])
def test_overview_facts_match_full_workspace_for_manager_and_member(tmp_path, uid):
    with scaled_client(tmp_path, 3, **ON) as (app, client):
        def seed(state):
            for i, p in enumerate(state['projects'][:2]):
                p['source_lifecycle'] = {'relationship': '已關聯確認單', 'state': 'mapped' if i == 0 else 'needs_verification',
                                         'canonical': '執行中' if i == 0 else None, 'reasons': [] if i == 0 else ['conflict'],
                                         'lifecycle_sources': [{'source_id': 'private-source-id'}],
                                         'blank_sources': ['private-source-id'], 'quote_workflow': [{'source_id': 'private-quote-id'}]}
            demo = state['projects'][2]; demo['source_kind'] = 'demo'; demo.pop('source_lifecycle', None)
            demo['contract_amount'] = None
            node = state['projects'][0]['nodes'][1]; node['status'] = 'paused'
            tasks = [t for p in state['projects'] for n in p['nodes'] for t in n['tasks']]
            for t in tasks: t['status'] = 'completed'
            node['tasks'][0].update(status='paused', due_date=None)
            node['tasks'][1].update(status='blocked', due_date='2099-01-01')
        edit_workspace(app, client, seed)
        switch(client, uid)
        full = {p['id']: p for p in client.get('/api/workspace').json()['projects']}
        overview = client.get('/api/projects?view=overview&tab=all&limit=100').json()['items']
        assert len(overview) == 3
        for item in overview:
            p = full[item['id']]
            assert item['contract_amount'] == p['contract_amount']
            assert item['current_nodes'] == [{'key': n['key'], 'name': n['name'], 'status': n['status']}
                                             for n in p['nodes'] if n['status'] in ('in_progress', 'paused')]
            assert item['blocked_tasks'] == sum(t['status'] in ('paused', 'blocked') for n in p['nodes'] for t in n['tasks'])
            if 'source_lifecycle' in p:
                assert item['source_lifecycle'] == {k: p['source_lifecycle'][k] for k in ('relationship', 'state', 'canonical', 'reasons')}
            else:
                assert 'source_lifecycle' not in item
        assert next(i for i in overview if i['id'] == 'p001')['blocked_tasks'] == 2
        assert next(i for i in overview if i['id'] == 'p003')['contract_amount'] is None
        shell = client.get('/api/workspace?scope=shell').json()
        assert all(not {'contract_amount', 'source_lifecycle', 'current_nodes', 'blocked_tasks'} & set(p) for p in shell['projects'])


def test_overview_facts_refresh_after_finance_node_and_pause_actions(tmp_path):
    with scaled_client(tmp_path, 2, **ON) as (app, client):
        def prepare(state):
            p = state['projects'][0]
            p.update(pm_id='u-pm', admin_id='u-manager', source_kind='demo')
            p.pop('source_lifecycle', None)
            for uid in ('u-pm', 'u-manager'):
                next(u for u in state['users'] if u['id'] == uid)['capabilities'] = ['finance_approve', 'finance_edit']
            n = p['nodes'][0]; n.update(status='pending', owner_id='u-pm', started_at=None)
            for t in n['tasks']: t.update(status='pending', owner_id='u-pm', input_task_ids=[], due_date=None)
            state['approvals'] = []
        edit_workspace(app, client, prepare)
        def action(name, payload, **ids):
            version = client.get('/api/workspace').json()['version']
            response = client.post('/api/actions', json={'action': name, 'version': version,
                                                        'request_id': f'{name}-{version}', 'project_id': 'p001', 'payload': payload, **ids})
            assert response.status_code == 200, response.text
            return response.json()
        def overview():
            return next(p for p in client.get('/api/projects?view=overview&tab=all').json()['items'] if p['id'] == 'p001')
        before = overview()
        p = action('finance_propose', {'contract_amount': '765.25', 'budget': '100', 'evidence': 'fixture signed'})['projects'][0]
        ident = p['finance_versions'][-1]['id']
        for uid, seat in [('u-pm', 'pm'), ('u-manager', 'admin')]:
            switch(client, uid)
            action('finance_attest', {'id': ident, 'category': 'baseline', 'seat': seat, 'evidence': 'fixture attestation'})
        action('finance_approve', {'id': ident})
        assert before['contract_amount'] != 765.25 and overview()['contract_amount'] == 765.25
        p = client.get('/api/workspace').json()['projects'][0]; n = p['nodes'][0]; t = n['tasks'][0]
        switch(client, 'u-pm')
        action('task_start', {}, node_id=n['id'], task_id=t['id'])
        assert {'key': n['key'], 'name': n['name'], 'status': 'in_progress'} in overview()['current_nodes']
        p = action('approval_create', {'type': 'change', 'title': 'fixture pause', 'reason': 'fixture change', 'task_ids': [t['id']]})
        approval = next(a for a in p['approvals'] if a['title'] == 'fixture pause')
        action('approval_submit', {'approval_id': approval['id']})
        assert overview()['blocked_tasks'] >= 1
        assert client.get('/api/workspace').json()['projects'][0]['nodes'][0]['tasks'][0]['status'] == 'paused'


def test_overview_query_count_does_not_grow_with_page_size(tmp_path):
    from .test_perf_budget import count_queries
    with scaled_client(tmp_path, 100, **ON) as (app, client):
        # Warm the route, then compare steady-state reads of actual pages.
        client.get('/api/projects?view=overview&tab=all&limit=10')
        counts = []
        for limit in (10, 100):
            with count_queries(app.state.engine) as stats:
                response = client.get('/api/projects', params={'view': 'overview', 'tab': 'all', 'limit': limit})
            assert response.status_code == 200 and len(response.json()['items']) == limit
            assert len(response.content) <= 120_000  # 100 CJK cards including compact facts
            counts.append(stats['queries'])
        assert counts[0] == counts[1] and counts[0] > 0
