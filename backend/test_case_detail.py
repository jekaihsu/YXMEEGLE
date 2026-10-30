import json
from copy import deepcopy
from .case_detail import SECTIONS, build_case_detail, parent_context
from .case_navigation import case_navigation
from .test_p2_int_routes import http  # noqa: F401


def task(tid, ident, category='外業'):
    return dict(id=tid, title=f'task {tid}', status='pending', category=category,
                source_identity=dict(base_token='b', table_id='rep', record_id=ident))


def fixture(env='production'):
    nodes = [dict(id='n1', name='Node One', status='in_progress', owner_id='u2',
                  tasks=[task('t1', 'r1'), task('t2', 'r2'), task('t3', 'r3')]),
             dict(id='n2', name='Node Two', status='pending', owner_id='u2', tasks=[task('t4', 'r4')])]
    return dict(
        environment=env, as_of='2026-10-14', source_status=dict(status='ok', last_sync='2026-10-14T01:00:00'),
        users=[dict(id='u1', name='Pm Synthetic'), dict(id='u2', name='Owner Synthetic')],
        projects=[dict(id='p', name='Case Alpha', code='C100', pm_id='u1', source_url='https://x/case', nodes=nodes,
                       execution_system='workbench', case_visibility='new_case',
                       files=[dict(id='f1', name='deliver.pdf', node_id='n1', task_id='t1', url='https://x/f1')]),
                  dict(id='q', name='Case Other', code='C100', pm_id='u1', nodes=[])],
        source_confirmations=[
            dict(id='b/conf/c1', code='C100-A', source_kind='confirmation', project_id='p', source_url='https://x/c1', revision=2,
                 history=[dict(revision=1, replaced_at='2026-10-01', snapshot={'fields': {'secret': 1}})]),
            dict(id='b/conf/c2', code='C100-B', source_kind='confirmation', project_id='p')],
        contract_items=[
            dict(id='b/con/k1', project_id='p', confirmation_ids=['b/conf/c1'], title='Line one', item_number='1',
                 amount_reported=987654, reporting_ids=['b/rep/r1', 'b/rep/ghost']),
            dict(id='b/con/k2', project_id='p', confirmation_ids=['b/conf/c1'], title='Line two', item_number='2',
                 reporting_ids=['b/rep/r2'])],
        source_work_items=[dict(id='b/rep/r1', project_id='p', contract_ids=['b/con/k1'], category='外業', source_url='https://x/r1'),
                           dict(id='b/rep/r2', project_id='p', contract_ids=['b/con/k2'], category='內業'),
                           dict(id='b/rep/r3', project_id='p', contract_ids=[], category='外業')],
        source_work_items_status={'p': dict(partial=False, truncated=False)},
        approvals=[dict(id='a1', project_id='p', status='pending', dates=[dict(task_id='t1', due_date='2026-12-31')])],
        events=[dict(id='e1', project_id='p', action='note', created_at='2026-10-02')])


def walk(detail):
    return detail['header']['details']['edges']


def test_scoped_case_detail_matches_full_capture_without_loading_other_trees(http, monkeypatch):
    from .test_p2_int_routes import build_state
    from . import storage
    app, client, seat, signin = http
    state, pid, _ = build_state()
    seat(state)
    signin()
    real = storage.load_partial
    captures = []

    def scoped(db, model, row, **kwargs):
        result = real(db, model, row, **kwargs)
        if kwargs.get('project_ids') is not None:
            captures.append([p['id'] for p in result['projects']])
        return result

    monkeypatch.setattr(storage, 'load_partial', scoped)
    response = client.get(f'/api/case-detail/{pid}')
    assert response.status_code == 200 and captures == [[pid]]

    def full(db, model, row, **kwargs):
        return storage.load(db, model, row) if kwargs.get('project_ids') is not None else real(db, model, row, **kwargs)

    monkeypatch.setattr(storage, 'load_partial', full)
    legacy = client.get(f'/api/case-detail/{pid}')
    assert legacy.status_code == 200
    assert response.json() == legacy.json()


def test_round_trip_parent_child_agree_for_every_visible_node():
    state = fixture()
    edges = walk(build_case_detail(state, 'p', confirmation_key='b/conf/c1'))
    assert edges
    for e in edges:
        ctx = parent_context(state, e['child_key'])
        assert any(p['parent_key'] == e['parent_key'] and p['edge_type'] == e['edge_type'] for p in ctx['parents'])
    keys = {e['child_key'] for e in edges}
    for key in keys:
        ctx = parent_context(state, key)
        for p in ctx['parents']:
            assert any(e['parent_key'] == p['parent_key'] and e['child_key'] == key for e in edges)


def test_forbidden_child_leaves_no_id_label_or_count():
    state = fixture()
    full = build_case_detail(state, 'p', confirmation_key='b/conf/c1')
    state['source_work_items'] = [i for i in state['source_work_items'] if i['id'] != 'b/rep/r2']
    for node in state['projects'][0]['nodes']:
        node['tasks'] = [t for t in node['tasks'] if t['id'] != 't2']
    after = build_case_detail(state, 'p', confirmation_key='b/conf/c1')
    dump = json.dumps(after, ensure_ascii=False)
    assert 'r2' not in dump and 't2' not in dump and 'task t2' not in dump and '內業' not in dump
    assert after['header']['details']['relationship_counts']['work_items'] == full['header']['details']['relationship_counts']['work_items'] - 1
    assert (full['header']['details']['relationship_counts']['work_items'], after['header']['details']['relationship_counts']['work_items']) == (3, 2)
    assert 'ghost' not in json.dumps(full)  # contract-listed ids absent from state never surface
    assert [r['unresolved'] for r in after['sections']['work_items']['rows'] if 'unresolved' in r][0]['reason']
    assert any(u['parent_key'] == 'contract:b/con/k2' for u in after['sections']['work_items']['details']['unresolved_edges'])


def test_missing_parent_is_unresolved_never_guessed():
    state = fixture()
    detail = build_case_detail(state, 'p', confirmation_key='b/conf/c1')
    orphan = next(r for r in detail['sections']['work_items']['rows'] if r['key'] == 'work_item:b/rep/r3')
    assert orphan['unresolved']['reason'] == 'no_authorized_parent_edge' and orphan['parents'] == []
    ctx = parent_context(state, 'work_item:b/rep/r3')
    assert ctx['parents'] == [] and ctx['states'] == ['unknown'] and ctx['unresolved']
    # same category as another line's item and same case number elsewhere: still no association
    assert 'contract:b/con/k1' not in json.dumps(ctx)


def test_multiple_versions_are_one_case():
    state = fixture()
    d = build_case_detail(state, 'p', confirmation_key='b/conf/c2')
    h = d['header']
    assert h['selected_confirmation']['key'] == 'confirmation:b/conf/c2'
    assert [v['key'] for v in h['other_versions']] == ['confirmation:b/conf/c1']
    assert h['details']['case_identity'] == 'p' and {r['kind'] for r in d['sections']['versions']['rows']} == {'confirmation'}
    assert len(d['sections']['versions']['rows']) == 2
    # duplicate case number on another project stays separate
    assert build_case_detail(state, 'q')['header']['details']['case_identity'] == 'q'
    assert build_case_detail(state, 'p')['header']['selected_confirmation']['reason'] == 'selection_required'
    assert build_case_detail(state, 'p', confirmation_key='nope')['header']['selected_confirmation']['reason'] == 'not_in_authorized_view'


def test_one_failed_section_does_not_erase_others():
    state = fixture()
    state['events'] = [None]  # breaks only the history builder
    d = build_case_detail(state, 'p', confirmation_key='b/conf/c1')
    assert d['sections']['history']['states'] == ['read_failed']
    assert all(d['sections'][n]['states'] != ['read_failed'] for n in SECTIONS if n != 'history')
    assert d['sections']['work_items']['rows']
    forced = build_case_detail(fixture(), 'p', confirmation_key='b/conf/c1',
                               section_status={'contract_lines': {'state': 'read_failed', 'reason': 'x'}})
    assert forced['sections']['contract_lines']['rows'] == []
    assert forced['sections']['work_items']['rows']


def test_stale_section_is_labelled_and_fetch_time_is_not_source_time():
    d = build_case_detail(fixture(), 'p', confirmation_key='b/conf/c1', as_of='2026-10-15T00:00:00',
                          section_status={'work_items': {'state': 'stale', 'source_time': '2026-09-01'}})
    assert 'stale' in d['sections']['work_items']['states']
    assert 'stale' not in d['sections']['versions']['states']
    t = d['sections']['work_items']['source_time']
    assert t['value'] == '2026-09-01' and t['fetched_at'] == '2026-10-15T00:00:00'
    state = fixture(); state['source_status']['status'] = 'stale'
    assert all('stale' in s['states'] for s in build_case_detail(state, 'p', confirmation_key='b/conf/c1')['sections'].values())


def test_pending_date_never_becomes_effective():
    h = build_case_detail(fixture(), 'p', confirmation_key='b/conf/c1')['header']
    assert h['dates']['pending_requested'][0]['requested_due_date'] == '2026-12-31'
    assert h['dates']['effective_approved']['state'] == 'unknown'
    assert h['dates']['estimated']['state'] == 'unknown'
    assert '2026-12-31' not in json.dumps(h['dates']['effective_approved'])


def test_revocation_removes_child_everywhere():
    state = fixture()
    assert parent_context(state, 'work_item:b/rep/r1')['parents']
    state['source_work_items'] = [i for i in state['source_work_items'] if i['id'] != 'b/rep/r1']
    state['projects'][0]['nodes'][0]['tasks'] = [t for t in state['projects'][0]['nodes'][0]['tasks'] if t['id'] != 't1']
    ctx = parent_context(state, 'work_item:b/rep/r1')
    assert ctx['states'] == ['unlocated'] and ctx['parents'] == []
    d = build_case_detail(state, 'p', confirmation_key='b/conf/c1')
    dump = json.dumps(d, ensure_ascii=False)
    assert 'b/rep/r1' not in dump and 'task t1' not in dump
    assert parent_context(state, 'task:p/n1/t1')['states'] == ['unlocated']
    state['projects'] = [p for p in state['projects'] if p['id'] != 'p']
    gone = build_case_detail(state, 'p')
    assert gone['page_state'] == ['unlocated'] and gone['header'] is None and 'Case Alpha' not in json.dumps(gone)


def test_amounts_withheld_and_edges_receipt_missing():
    d = build_case_detail(fixture(), 'p', confirmation_key='b/conf/c1')
    assert '987654' not in json.dumps(d)
    assert d['header']['contract_amounts']['state'] == 'withheld'
    assert all(r['amount']['state'] == 'withheld' for r in d['sections']['contract_lines']['rows'])
    assert {e['verification'] for e in walk(d)} == {'receipt_missing'}


def test_cardinality_one_conflict_is_flagged():
    state = fixture()
    state['contract_items'][0]['confirmation_ids'] = ['b/conf/c1', 'b/conf/c2']
    d = build_case_detail(state, 'p', confirmation_key='b/conf/c1')
    row = next(r for r in d['sections']['contract_lines']['rows'] if r['key'] == 'contract:b/con/k1')
    assert row['parents'][0]['contested'] is True
    ctx = parent_context(state, 'contract:b/con/k1')
    assert ctx['states'] == ['partial'] and len(ctx['parents']) == 2


def test_header_stage_and_evidence_and_entry_point():
    d = build_case_detail(fixture(), 'p', confirmation_key='b/conf/c1')
    h = d['header']
    assert h['current_stage']['state'] == 'verified' and h['responsible_person']['name'] == 'Owner Synthetic'
    assert h['pm']['name'] == 'Pm Synthetic' and h['source_link']['url'] == 'https://x/c1'
    assert d['sections']['reports_documents']['details']['entry_point'] == dict(view='project', project='p', tab='data', section='files')
    assert parent_context(fixture(), 'evidence:f1')['parents'][0]['parent_key'] == 'task:p/n1/t1'
    state = fixture(); state['projects'][0]['nodes'][1]['status'] = 'in_progress'
    assert build_case_detail(state, 'p')['header']['current_stage']['state'] == 'unknown'


def test_work_items_agree_with_existing_case_navigation_in_test_env():
    state = fixture('test')
    nav = case_navigation(deepcopy(state), 'p')['confirmations']
    nav_c = {c['id']: c['id'] for c in nav[0]['contracts']}
    d = build_case_detail(state, 'p', confirmation_key='b/conf/c1')
    assert {r['key'].split(':', 1)[1] for r in d['sections']['contract_lines']['rows']} == set(nav_c)


# ---- P2-130B-FIX1 -------------------------------------------------------------------------

def _wi(d):
    return d['sections']['work_items']


def test_f1_child_revoked_alone_is_not_recreated_from_surviving_task():
    state = fixture()
    full = build_case_detail(state, 'p', confirmation_key='b/conf/c1')
    state['source_work_items'] = [i for i in state['source_work_items'] if i['id'] != 'b/rep/r2']  # task t2 stays
    d = build_case_detail(state, 'p', confirmation_key='b/conf/c1')
    dump = json.dumps({k: d[k] for k in ('header', 'sections')}, ensure_ascii=False)
    assert 'b/rep/r2' not in dump and '內業' not in dump
    assert 'b/rep/r2' not in d['header']['details']['complete_ids']['work_items']
    counts = (full['header']['details']['relationship_counts']['work_items'],
              d['header']['details']['relationship_counts']['work_items'])
    assert counts == (3, 2)
    assert parent_context(state, 'work_item:b/rep/r2')['states'] == ['unlocated']
    gap = [u for u in _wi(d)['details']['unresolved_edges'] if u['parent_key'] == 'contract:b/con/k2']
    assert gap and gap[0]['child_key'] is None and 'r2' not in json.dumps(gap)
    assert 'partial' in _wi(d)['states']


def _legacy(task_ref_task='t2', reporting=('b/rep/r1',)):
    s = fixture('test')
    s['source_work_items'] = []
    s['source_work_items_status'] = {}
    s['contract_items'][0].update(task_refs=[{'project_id': 'p', 'node_id': 'n1', 'task_id': task_ref_task}],
                                  reporting_ids=list(reporting))
    s['contract_items'][1]['reporting_ids'] = []
    return s


def test_f2_legacy_task_ref_mismatch_stays_unresolved_like_case_navigation():
    s = _legacy()  # ref -> t2 (r2) but reporting_ids lists r1
    nav = case_navigation(deepcopy(s), 'p')['confirmations'][0]['contracts'][0]
    d = build_case_detail(s, 'p', confirmation_key='b/conf/c1')
    assert nav['work_items'] == [] and nav['unresolved']
    assert [e for e in walk(d) if e['parent_key'] == 'contract:b/con/k1'] == []
    assert any(u['parent_key'] == 'contract:b/con/k1' for u in _wi(d)['details']['unresolved_edges'])
    assert 'b/rep/r1' not in json.dumps(d['header']['details']['complete_ids'])


def test_f2_legacy_matching_ref_agrees_with_navigation_on_work_item_ids_and_unresolved():
    for s in (_legacy('t1'), _legacy('t2'), _legacy('t1', ('b/rep/r1', 'b/rep/ghost'))):
        nav = case_navigation(deepcopy(s), 'p')['confirmations'][0]['contracts']
        d = build_case_detail(s, 'p', confirmation_key='b/conf/c1')
        for c in nav:
            ids = {w['id'] for w in c['work_items']}
            mine = {e['child_key'].split(':', 1)[1] for e in walk(d)
                    if e['parent_key'] == f"contract:{c['id']}" and e['edge_type'] == 'contract_work_item'}
            assert mine == ids
            row = next(r for r in d['sections']['contract_lines']['rows'] if r['key'] == f"contract:{c['id']}")
            assert (row['work_item_links'] == 'unresolved') == c['unresolved']


def test_f3_incomplete_contract_ids_and_source_missing_warn_even_with_survivors():
    for variant in ('incomplete', 'missing'):
        s = fixture()
        s['source_work_items'] = s['source_work_items'][:2]  # drop orphan r3; k1/r1 and k2/r2 linked
        if variant == 'incomplete':
            s['source_work_items_status']['p']['incomplete_contract_ids'] = ['b/con/k1']
        else:
            s['source_work_items'][0]['source_missing'] = True
        d = build_case_detail(s, 'p', confirmation_key='b/conf/c1')
        assert _wi(d)['states'] == ['partial'], variant
        assert [u['parent_key'] for u in _wi(d)['details']['unresolved_edges']] == ['contract:b/con/k1']
        rows = {r['key']: r for r in d['sections']['contract_lines']['rows']}
        assert rows['contract:b/con/k1']['work_item_links'] == 'unresolved'
        assert rows['contract:b/con/k2']['work_item_links'] == 'located'
        assert 'work_item:b/rep/r1' in [r['key'] for r in _wi(d)['rows']]


def test_f3_clean_state_has_no_warning():
    s = fixture()
    s['source_work_items'] = s['source_work_items'][:2]
    d = build_case_detail(s, 'p', confirmation_key='b/conf/c1')
    assert _wi(d)['states'] == [] and _wi(d)['details']['unresolved_edges'] == []


def test_f4_stale_unknown_keeps_unknown_reason_and_entry_point():
    s = fixture()
    s['source_status']['status'] = 'stale'
    s['projects'][0]['files'] = []
    d = build_case_detail(s, 'p', confirmation_key='b/conf/c1')
    sec = d['sections']['reports_documents']
    assert sec['states'] == ['unknown'] and sec['freshness'] == 'stale' and sec['reason'] == 'no_native_task_evidence_link'
    assert sec['details']['entry_point']['tab'] == 'data'
    for name, section in d['sections'].items():
        assert 'read_failed' not in section['states'], name
        assert section['freshness'] == 'stale'
        assert not ({'unknown', 'stale'} <= set(section['states']))
    s['projects'][0]['nodes'] = []
    s['events'] = []
    s['source_confirmations'] = []
    d = build_case_detail(s, 'p')
    assert d['sections']['versions']['states'] == ['unknown'] and d['sections']['versions']['freshness'] == 'stale'
    assert d['sections']['history']['states'] == ['unknown'] and d['sections']['workflow_nodes']['states'] == ['unknown']


def test_f4_partial_stale_still_combine_and_fresh_has_no_freshness():
    d = build_case_detail(fixture(), 'p', confirmation_key='b/conf/c1',
                          section_status={'work_items': {'state': 'stale'}})
    assert d['sections']['work_items']['states'] == ['partial', 'stale']
    assert d['sections']['versions']['freshness'] is None


def test_f5_visible_workflow_node_rows_resolve_in_reverse_navigation():
    state = fixture()
    d = build_case_detail(state, 'p', confirmation_key='b/conf/c1')
    keys = [r['key'] for r in d['sections']['workflow_nodes']['rows']]
    assert 'node:p/n1' in keys
    ctx = parent_context(state, 'node:p/n1')
    assert ctx['states'] == [] and ctx['kind'] == 'node' and ctx['label'] == 'Node One'
    assert ctx['parents'][0]['parent_key'] == 'case:p'
    for row in d['sections']['workflow_nodes']['rows']:
        assert parent_context(state, row['key'])['states'] != ['unlocated'], row['key']
        for t in row['tasks']:
            assert parent_context(state, t['key'])['states'] != ['unlocated']
            assert any(p['parent_key'] == row['key'] for p in t['parents'])
    # a task with no work item still shows its missing work-item parent
    t3 = next(t for r in d['sections']['workflow_nodes']['rows'] for t in r['tasks'] if t['key'].endswith('/t3'))
    assert t3.get('unresolved') is None  # r3 is linked to task t3 by identity
    t4 = next(t for r in d['sections']['workflow_nodes']['rows'] for t in r['tasks'] if t['key'].endswith('/t4'))
    assert t4['unresolved']['reason'] == 'no_authorized_parent_edge'


# ---- P2-130B-FIX2 -------------------------------------------------------------------------

def _f1_state(remove):
    s = fixture('test')
    s['contract_items'][1]['task_refs'] = [{'project_id': 'p', 'node_id': 'n1', 'task_id': 't2'}]
    before = build_case_detail(s, 'p', confirmation_key='b/conf/c1')
    s['source_work_items'] = ([] if remove == 'all' else
                              [i for i in s['source_work_items'] if i['id'] != 'b/rep/r2'])
    return s, before, build_case_detail(s, 'p', confirmation_key='b/conf/c1')


def _count(d):
    return d['header']['details']['relationship_counts']['work_items']


def _assert_no_r2(s, d):
    dump = json.dumps({k: d[k] for k in ('header', 'sections')}, ensure_ascii=False)
    assert 'b/rep/r2' not in dump and '內業' not in dump
    assert not [e for e in walk(d) if e['child_key'] == 'work_item:b/rep/r2']
    assert parent_context(s, 'work_item:b/rep/r2')['states'] == ['unlocated']
    gap = [u for u in _wi(d)['details']['unresolved_edges'] if u['parent_key'] == 'contract:b/con/k2']
    assert gap and gap[0]['child_key'] is None
    rows = {r['key']: r for r in d['sections']['contract_lines']['rows']}
    assert rows['contract:b/con/k2']['work_item_links'] == 'unresolved'


def test_fix2_last_imported_child_removed_with_surviving_task_ref_is_not_recreated():
    s, before, d = _f1_state('r2')
    assert (_count(before), _count(d)) == (3, 2)
    _assert_no_r2(s, d)


def test_fix2_whole_imported_collection_removed_with_status_intact_creates_nothing():
    s, before, d = _f1_state('all')
    assert (_count(before), _count(d)) == (3, 0)
    _assert_no_r2(s, d)
    assert 'b/rep/r1' not in json.dumps(d['header']['details']['complete_ids'])


def test_fix2_legacy_fallback_only_when_project_not_in_imported_mode():
    s, _, _ = _f1_state('all')
    s['source_work_items_status'] = {}  # genuinely not imported -> exact legacy rule applies
    d = build_case_detail(s, 'p', confirmation_key='b/conf/c1')
    assert 'work_item:b/rep/r2' in [e['child_key'] for e in walk(d)]


def test_partial_status_with_independent_stale_flag_marks_sections_partial_and_stale():
    state = fixture(); state['source_status'] = dict(status='partial', stale=True, last_sync='2026-10-14T01:00:00')
    sections = build_case_detail(state, 'p', confirmation_key='b/conf/c1')['sections']
    assert all(s['freshness'] == 'stale' for s in sections.values())
    assert any(s['states'] == ['partial', 'stale'] for s in sections.values())
    state['source_status'] = dict(status='partial', last_sync='2026-10-14T01:00:00')
    assert all(s['freshness'] is None for s in build_case_detail(state, 'p', confirmation_key='b/conf/c1')['sections'].values())


def test_work_items_details_forward_plan_without_changing_native_tree():
    from .contract_links import build_projection
    from .test_contract_links import line, item, row
    state=fixture()
    before=build_case_detail(state,'p',confirmation_key='b/conf/c1')
    projection=build_projection([line(),item(),row('confirmation','c',工程確認單編號='X')],{'b/confirmation/c':'p'}, {})
    state['derived_plan']=projection.plans
    result=build_case_detail(state,'p',confirmation_key='b/conf/c1')
    summary=result['sections']['work_items']['details'].pop('plan_summary')
    assert summary['categories']['外業']['planned_qty']=='12'
    assert summary['items']==[dict(id='b/reporting/i',category='外業',line_id='b/contract/l',basis='derived',reason='exact_match')]
    assert '_source_ids' not in summary
    before['sections']['work_items']['details'].pop('plan_summary')
    assert result==before
