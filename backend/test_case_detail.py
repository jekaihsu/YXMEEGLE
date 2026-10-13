import json
from copy import deepcopy
from .case_detail import SECTIONS, build_case_detail, parent_context
from .case_navigation import case_navigation


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
