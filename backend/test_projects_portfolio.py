from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select
from .test_perf_budget import scaled_client
from .models import BusinessRow, WorkspaceRow
from . import storage
from .sop_import.models import CasePolicy
from .test_ux_home_panels import home
from .test_node_assignment_routes import NODES, TASKS, T0, project
from .projects_portfolio import portfolio


def test_portfolio_is_complete_compact_and_policy_aware(tmp_path):
    with scaled_client(tmp_path, 14, upgraded=True, INDEX_TABLES_ENABLED='true', WORKSPACE_SHELL_ENABLED='true') as (app, client):
        with app.state.sessions.begin() as db:
            row=db.scalars(select(WorkspaceRow)).first()
            state=storage.load(db,BusinessRow,row)
            pid=state['projects'][0]['id']
            db.merge(CasePolicy(workspace_id=row.id,project_id=pid,policy='managed',revision=1,
                decided_by='fixture',decided_at=0,reason='test',facts={},node_keys=['sales']))
        response=client.get('/api/projects?view=portfolio')
        assert response.status_code==200,response.text
        body=response.json()
        assert body['total']==14==len(body['items'])
        first=next(p for p in body['items'] if p['id']==pid)
        assert first['sop_summary']==dict(policy='managed',imported_tasks=False)
        assert len(first['portfolio_nodes'])==9
        assert {'key','status','status_source','owner_id','collaborator_ids'}==set(first['portfolio_nodes'][0])
        assert not {'nodes','files','daily_reports','contract_amount','estimated_points'} & set(first)
        assert body['basis']=='persisted_workspace'
        assert all(n['status_source']=='persisted' for p in body['items'] for n in p['portfolio_nodes'])


def test_portfolio_applies_visibility_and_does_not_load_task_trees(tmp_path,monkeypatch):
    from . import storage as store,index_reads
    from . import workspace_environment
    with scaled_client(tmp_path, 8, upgraded=True, INDEX_TABLES_ENABLED='true', WORKSPACE_SHELL_ENABLED='true') as (app,client):
        with app.state.sessions.begin() as db:
            row=db.scalars(select(WorkspaceRow)).first();state=store.load(db,BusinessRow,row)
            for i,p in enumerate(state['projects']):p['case_visibility']='new_case' if i%2 else 'excluded_history'
            state['version']=row.version+1;row.version=state['version'];row.data=store.save(db,BusinessRow,row.id,state)
        monkeypatch.setattr(workspace_environment,'normalize_environment',lambda state,wid,cfg:state.update(environment='production') or state)
        original=store.load_partial
        def bounded(*args,**kwargs):
            assert not kwargs.get('project_ids'),'portfolio must not load a case tree per row'
            return original(*args,**kwargs)
        monkeypatch.setattr(store,'load_partial',bounded)
        response=client.get('/api/projects?view=portfolio')
        assert response.status_code==200,response.text
        assert response.json()['total']==4
        monkeypatch.setattr(index_reads,'ready',lambda *args:False)
        assert client.get('/api/projects?view=portfolio').status_code==503


def test_portfolio_recognizes_imported_tasks_without_managed_policy(tmp_path):
    from .sop_import.models import CaseState, LocalTask
    from .sop_import.domain import Applicability, Lifecycle
    with scaled_client(tmp_path, 2, upgraded=True, INDEX_TABLES_ENABLED='true', WORKSPACE_SHELL_ENABLED='true') as (app,client):
        with app.state.sessions.begin() as db:
            row=db.scalars(select(WorkspaceRow)).first();pid=storage.load(db,BusinessRow,row)['projects'][0]['id']
            db.add(CaseState(workspace_id=row.id,project_id=pid));db.flush()
            db.add(LocalTask(workspace_id=row.id,id='imported-task',project_id=pid,template_family_id='family',
                source_row_key='row-1',instance_scope='case',imported_version_id='v1',snapshot={},title='Imported task',
                instructions='',participants=[],applicability=Applicability.APPLICABLE,state=Lifecycle.PENDING,local={}))
        first=next(p for p in client.get('/api/projects?view=portfolio').json()['items'] if p['id']==pid)
        assert first['sop_summary']==dict(policy=None,imported_tasks=True)


@pytest.fixture
def portfolio_case(tmp_path, home):
    def prepare(state):
        for key in ('source_confirmations', 'contract_items', 'source_work_items'):
            state[key] = []
        for i, p in enumerate(state['projects']):
            p.update(code=f'C11526{4+i}', source_kind='lark', case_visibility='source_reference',
                     source_records=project()['source_records'], daily_reports=[])
            if i:
                p['source_records'][0] = dict(p['source_records'][0],
                    url=p['source_records'][0]['url'].replace('recCONF1', 'recCONF2'))
            for n in p['nodes']:
                n.update(status='not_started', tasks=[])
    with scaled_client(tmp_path, 2, upgraded=True, mutate=prepare,
                       INDEX_TABLES_ENABLED='true', WORKSPACE_SHELL_ENABLED='true') as (app, client):
        def read(*, enabled=True):
            with app.state.sessions() as db:
                row = db.scalars(select(WorkspaceRow)).first()
                state = storage.load_partial(db, BusinessRow, row)
                state['environment'] = 'production'
                return portfolio(db, BusinessRow, row, state, '2026-10-23', assignments=home.service,
                                 data={'wid': 'lark-company' if enabled else row.id}, user={'id': 'ou_member'})
        def change(fn):
            with app.state.sessions.begin() as db:
                row = db.scalars(select(WorkspaceRow)).first()
                state = storage.load(db, BusinessRow, row)
                fn(state)
                row.data = storage.save(db, BusinessRow, row.id, state)
        def add(label, *, code='C115264', relation='recCONF1', **fields):
            return home.fake.add(NODES, {'指派鍵': code + '|' + label, '確認單編號': code, '節點': label,
                                        '工程確認單': [relation], '狀態': '未開始', **fields})
        yield SimpleNamespace(read=read, change=change, add=add, home=home,
                              persisted=read(enabled=False))


def test_portfolio_overlays_all_cases_in_one_cached_bulk_read(portfolio_case):
    h = portfolio_case
    for code, relation in (('C115264', 'recCONF1'), ('C115265', 'recCONF2')):
        for label in ('業務', 'PM', '確認單', '外業', '控制'):
            approved = label != '控制'
            h.add(label, code=code, relation=relation, **({'核准人': [{'id': 'ou_vp'}],
                '核准時間': int(T0 * 1000), '狀態': '已完成'} if approved else {}))
    result = h.read()
    assert result['basis'] == 'persisted_workspace+lark_derived'
    for p in result['items']:
        assert [n['status'] for n in p['portfolio_nodes']] == ['已完成'] * 4 + ['待處理'] + ['未開始'] * 4
        assert {n['status_source'] for n in p['portfolio_nodes']} == {'lark_derived'}
    assert h.read() == result
    # Home and portfolio use the same scope, projection, cache and TTL.
    h.home.service.assignment_sources(h.home.service.scope({'wid': 'lark-company'}, {'id': 'ou_member'}), include_roster=True)
    for table in (NODES, TASKS):
        assert h.home.fake.requests.count(('GET', f'/open-apis/bitable/v1/apps/{h.home.service.config.base}/tables/{table}/records')) == 1
    assert h.home.fake.writes() == []


@pytest.mark.parametrize('table', [NODES, TASKS])
def test_portfolio_falls_back_when_either_source_is_unreadable(portfolio_case, table):
    h = portfolio_case
    h.add('業務')
    h.home.fake.fault('GET', '/' + table + '/records', lambda _: httpx.Response(403, json={'code': 91403}), times=20)
    assert h.read() == h.read(enabled=False)
    assert h.home.fake.writes() == []


@pytest.mark.parametrize('ambiguity', ['same_relation', 'wrong_code', 'multiple_relations', 'duplicate_key', 'no_rows'])
def test_portfolio_falls_back_for_unmatched_or_ambiguous_cases(portfolio_case, ambiguity):
    h = portfolio_case
    if ambiguity != 'no_rows':
        rid = h.add('業務', **({'code': 'C999999'} if ambiguity == 'wrong_code' else {}))
    if ambiguity == 'same_relation':
        h.change(lambda s: s['projects'][1].update(source_records=s['projects'][0]['source_records']))
    elif ambiguity == 'multiple_relations':
        h.home.fake.tables[NODES][rid]['工程確認單'] = ['recCONF1', 'recCONF2']
    elif ambiguity == 'duplicate_key':
        h.add('業務')
    assert h.read() == h.read(enabled=False)
    assert h.home.fake.writes() == []


def test_portfolio_disabled_assignments_do_not_read_lark(portfolio_case):
    from dataclasses import replace
    h = portfolio_case
    h.home.service.config = replace(h.home.service.config, enabled=False)
    assert h.read() == h.persisted
    assert h.home.fake.requests == []


def test_portfolio_uses_evidence_skips_and_task_derived_statuses(portfolio_case):
    h = portfolio_case
    for label in ('業務', 'PM', '確認單', '外業', '控制'):
        rid = h.add(label)
        if label == '控制':
            h.home.fake.add(TASKS, {'標題': '校核', '節點指派': [rid], '狀態': '已完成'})
    def evidence(state):
        p = state['projects'][0]
        state['contract_items'] = [{'id': 'line1', 'project_id': p['id']}]
        p['nodes'][3]['status'] = 'approved_skipped'
    h.change(evidence)
    h.home.service.nodes.skipped_nodes = lambda _s, _p, n: n.get('status') == 'approved_skipped'
    first = h.read()['items'][0]
    assert [n['status'] for n in first['portfolio_nodes']] == ['已完成'] * 3 + ['略過', '待審核'] + ['未開始'] * 4
    assert h.home.fake.writes() == []


def test_portfolio_preserves_legacy_completion_chain_gaps(portfolio_case):
    from .node_assignment.domain import NodeKey
    h = portfolio_case
    h.add('外業', 核准人=[{'id': 'ou_vp'}], 核准時間=int(T0 * 1000), 狀態='已完成')
    h.home.service.nodes.legacy_completions = lambda *_: {NodeKey.FIELD: {'id': 'legacy-mark'}}
    first = h.read()['items'][0]
    assert [n['status'] for n in first['portfolio_nodes']] == ['已完成', '待處理', '未開始', '已完成'] + ['未開始'] * 5


def test_portfolio_loads_linked_daily_evidence_without_task_trees(portfolio_case, monkeypatch):
    from .report_links import LinkBasis
    h = portfolio_case
    original = storage.load_partial
    def bounded(*args, **kwargs):
        assert not kwargs.get('project_ids'), 'portfolio must not load case task trees'
        return original(*args, **kwargs)
    monkeypatch.setattr(storage, 'load_partial', bounded)
    for label in ('業務', 'PM', '確認單'):
        h.add(label, 核准人=[{'id': 'ou_vp'}], 核准時間=int(T0 * 1000), 狀態='已完成')
    h.add('外業')
    h.change(lambda s: s['projects'][0].update(daily_reports=[{
        'id': 'linked-daily', 'date': '2026-10-23', 'department': '外業組', 'points': 1,
        'case_mapping_status': 'matched', 'match_basis': LinkBasis.CODE.value}]))
    first = h.read()['items'][0]
    assert [n['status'] for n in first['portfolio_nodes']] == ['已完成'] * 3 + ['進行中'] + ['未開始'] * 5
    assert h.home.fake.writes() == []


def test_portfolio_falls_back_on_unparseable_source_records(portfolio_case, monkeypatch):
    from .node_assignment.cache import Cached
    from .node_assignment.lark_table import Table
    h = portfolio_case
    def read_table(_scope, table, _spec):
        return Cached([{'record_id': 'recBroken', 'fields': None}] if table is Table.NODES else [], False, T0)
    monkeypatch.setattr(h.home.service, 'read_table', read_table)
    assert h.read() == h.persisted
