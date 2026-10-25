"""Read-shape and query budgets, independent of developer-machine timings."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import event, select

from . import storage
from .benchmark_case_home import fixture, offline_assignments
from .models import AuditRow, BusinessRow, WorkspaceRow
from .node_assignment.lark_table import CaseSnapshot, parse_node
from .node_assignment.domain import NodeKey
from .node_assignment.service import Context
from .policy import upgrade
from .test_perf_budget import scaled_client


@pytest.mark.parametrize('panel', ['assigned', 'confirmation', 'delegated', 'proxy', 'local', 'completed'])
def test_projected_home_matches_full_workspace(tmp_path, panel):
    def prepare(state):
        fixture(state)
        task = state['projects'][0]['nodes'][0]['tasks'][0]
        task.update(owner_id='ou_015', owner_inherited=False, status='rework')
    with scaled_client(tmp_path, 5, upgraded=True, mutate=prepare) as (app, client):
        client.post('/api/demo/session', json={'user_id': 'ou_015'})
        user = client.get('/api/session').json()['user']
        wid = app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
        with app.state.sessions() as db:
            state = upgrade(storage.load(db, BusinessRow, db.get(WorkspaceRow, wid)))
        state['features'] = {'routines': False, 'change_extension': False}
        params = {'panel': panel, 'limit': '100'}
        expected = app.state.home_panels.query(state, {'wid': wid, 'mode': 'demo'}, user, params)
        response = client.get('/api/home-panels', params=params)
        assert response.status_code == 200, response.text
        assert response.json() == expected


def test_assigned_without_lark_never_loads_native_task_trees(tmp_path, monkeypatch):
    with scaled_client(tmp_path, 12, upgraded=True) as (_, client):
        def forbidden(*_, **__): raise AssertionError('assigned loaded entire workspace')
        monkeypatch.setattr(storage, 'load', forbidden)
        response = client.get('/api/home-panels?panel=assigned')
        assert response.status_code == 200
        assert response.json()['items'] == []
        assert response.json()['readState'] == 'disabled'


def test_mocked_assignments_match_full_load_and_batch_legacy_queries(tmp_path):
    with scaled_client(tmp_path, 319, upgraded=True, mutate=fixture,
                       INDEX_TABLES_ENABLED='true', WORKSPACE_SHELL_ENABLED='true') as (app, client):
        offline_assignments(app)
        client.post('/api/demo/session', json={'user_id': 'ou_015'})
        user = client.get('/api/session').json()['user']
        wid = app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
        with app.state.sessions() as db:
            state = upgrade(storage.load(db, BusinessRow, db.get(WorkspaceRow, wid)))
        state['features'] = {'routines': False, 'change_extension': False}
        params = {'panel': 'assigned', 'limit': '100'}
        expected = app.state.home_panels.query(state, {'wid': wid, 'mode': 'demo'}, user, params)
        assert expected['total_count'] == 319 * 6  # the three proven early nodes are already done
        audits = []
        def count(conn, cursor, statement, parameters, context, many):
            if 'FROM action_audit' in statement: audits.append(statement)
        event.listen(app.state.engine, 'before_cursor_execute', count)
        try:
            response = client.get('/api/home-panels', params=params)
            assert response.status_code == 200, response.text
            assert response.json() == expected
            assert len(audits) == 1
            audits.clear()
            response = client.get('/api/projects?view=portfolio')
            assert response.status_code == 200
            assert len(audits) == 1
        finally:
            event.remove(app.state.engine, 'before_cursor_execute', count)


@pytest.mark.parametrize('normalized', [True, False])
def test_omitted_reads_are_independent_and_cannot_be_saved(tmp_path, normalized):
    with scaled_client(tmp_path, 2, upgraded=True) as (app, client):
        with app.state.sessions() as db:
            row = db.scalars(select(WorkspaceRow)).first()
            full = storage.load(db, BusinessRow, row)
            source = row if normalized else SimpleNamespace(data={k: v for k, v in full.items() if k != 'storage_schema'}, id=row.id)
            before = deepcopy(source.data)
            omitted = ('tasks', 'project_comments', 'project_daily_reports', 'work_schedules')
            read = storage.load(db, BusinessRow, source, omit_kinds=omitted)
            assert source.data == before
            assert read['projects'] and read['users'] and read['events']
            assert not read['work_schedules']
            assert all(not p['comments'] and not p['daily_reports'] and all(not n['tasks'] for n in p['nodes']) for p in read['projects'])
            with pytest.raises(ValueError, match='read-only'):
                storage.save(db, BusinessRow, row.id, read)
            with pytest.raises(ValueError, match='unknown workspace kind'):
                storage.load(db, BusinessRow, row, omit_kinds=('typo',))


def test_batched_legacy_records_preserve_workspace_order_and_binding_checks(tmp_path):
    with scaled_client(tmp_path, 2) as (app, _):
        service = app.state.home_panels.nodes
        node = parse_node({'record_id': 'recNODE', 'fields': {'狀態': '已完成',
            '核准人': [{'id': 'ou_015'}], '核准時間': 1790000000000}})
        snap = CaseSnapshot('C115000', {NodeKey.FIELD: (node,)}, {})
        mark = {'record_id': node.record_id, 'approved_at': node.approved_at, 'actor': {'open_id': 'ou_015'}}
        with app.state.sessions.begin() as db:
            for ident, wid, pid, actor in [('a', 'w1', 'p1', 'ou_015'), ('b', 'w1', 'p1', 'ou_wrong'),
                                           ('c', 'w1', 'p2', 'ou_015'), ('d', 'w2', 'p1', 'ou_015')]:
                db.add(AuditRow(id=ident, workspace_id=wid, actor_id=actor, action='node_assignment.legacy_complete', created_at='2026-10-25',
                    data={'project_id': pid, 'node': 'field', 'result': 'success',
                          'legacy_completion': {**mark, 'actor': {'open_id': actor}, 'id': ident}}))
        records = service.legacy_completion_records('w1')
        assert set(records) == {'p1', 'p2'}
        ctx = Context('w1', {}, {}, {'id': 'p1'}, lambda: {})
        regular = service.legacy_completions(ctx, snap)
        assert service.legacy_completions(ctx, snap, records=records['p1']) == regular
        assert regular[NodeKey.FIELD]['id'] == 'a'
        assert service.legacy_completions(ctx, snap, records=[]) == {}
