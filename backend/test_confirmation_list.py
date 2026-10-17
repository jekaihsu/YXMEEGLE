from copy import deepcopy
import pytest
from . import confirmation_list as cl
from .confirmation_list import build_confirmation_list, confirmation_population


def entity(rid, code, name='案件', pid=None, version=None, pm_text='', **extra):
    row = dict(id=f'b/t/{rid}', source_identity=dict(base_token='b', table_id='t', record_id=rid),
               source_kind='confirmation', code=code, project_id=pid, source_missing=False,
               fields={'工程名稱': name, '案件負責人': pm_text, '合約總額': 987654}, **extra)
    if version is not None:
        row['source_version'] = version
    return row


def project(pid, pm='u1', system='workbench', nodes=None):
    return dict(id=pid, name='P' + pid, pm_id=pm, execution_system=system, case_visibility='new_case',
                nodes=nodes if nodes is not None else [dict(id='n1', status='completed'), dict(id='n2', status='pending')])


def state(**over):
    base = dict(environment='test', source_status={'status': 'ready'},
                users=[dict(id='u1', name='Ann'), dict(id='u2', name='Bob')],
                projects=[project('p1'), project('p2', pm='u2', system='meegle')],
                source_confirmations=[
                    entity('r1', 'C100', '甲', 'p1', version=3),
                    entity('r2', 'C100', '乙', 'p2', version=4),      # duplicate case number, other case
                    entity('r3', 'C100', '甲', 'p1', version=4),      # second version of case p1
                    entity('r4', 'C200', '丙', None, version=10),
                    entity('r5', 'C300', '丁', 'p-hidden', version=2),
                    entity('r6', 'C400', '戊', None)])
    base.update(over)
    return base


def keys_of(population):
    return [r['row_key'] for r in population]


def walk(st, **kw):
    keys, cursor = [], None
    while True:
        page = build_confirmation_list(st, cursor=cursor, limit=kw.pop('limit', 2) if cursor is None else 2, **kw)
        assert page['status'] == 200
        keys += [r['row_key'] for r in page['rows']]
        cursor = page['next_cursor']
        if not cursor:
            return keys


def test_duplicate_case_numbers_stay_separate_rows():
    page = build_confirmation_list(state(), limit=100)
    assert [r['case_number'] for r in page['rows']].count('C100') == 3
    assert len({r['row_key'] for r in page['rows']}) == 6


def test_versions_of_one_case_are_separate_rows_and_group_counts_case_once():
    page = build_confirmation_list(state(), limit=100)
    p1 = [r for r in page['rows'] if r['case_link']['project_id'] == 'p1']
    assert len(p1) == 2
    assert {r['confirmation_version']['value'] for r in p1} == {'3', '4'}
    assert {'project_id': 'p1', 'rows': 2} in page['grouping']['by_case']
    assert page['grouping']['linked_cases'] == 2           # p1, p2: not 3
    assert page['grouping']['unresolved_rows'] == 3


def test_same_record_version_delivered_twice_is_deduped_but_other_version_is_not():
    st = state()
    st['source_confirmations'] += [entity('r1', 'C100', version=3), entity('r1', 'C100', version=5)]
    page = build_confirmation_list(st, limit=100)
    assert page['totals']['authorized_source'] == 7
    assert page['diagnostics']['duplicate_versions_collapsed'] == 1


def test_mutation_version_dedupe_guard(monkeypatch):
    st = state()
    st['source_confirmations'] += [entity('r1', 'C100', version=5)]
    assert build_confirmation_list(st, limit=100)['totals']['authorized_source'] == 7
    monkeypatch.setattr(cl, '_dedupe_key', lambda ref: ref.source_key)   # mutation: drop version
    assert build_confirmation_list(st, limit=100)['totals']['authorized_source'] != 7


def test_unverified_case_link_stays_unresolved_even_when_name_matches():
    st = state()
    rows = {r['row_key']: r for r in build_confirmation_list(st, limit=100)['rows']}
    r4, r5 = rows['b/t/r4@i10'], rows['b/t/r5@i2']
    st['projects'].append(dict(id='p9', name='丙', code='C200', pm_id='u1', execution_system='workbench'))
    again = {r['row_key']: r for r in build_confirmation_list(st, limit=100)['rows']}
    for r in (r4, r5, again['b/t/r4@i10']):
        assert r['case_link']['state'] == 'unresolved' and r['case_link']['project_id'] is None
        assert r['case_link']['verification'] == 'receipt_missing'
        assert r['workflow_summary']['state'] == 'unknown' and r['admission']['state'] == 'unknown'
    assert r5['case_link']['reason'] == 'project_not_visible'


def test_mutation_name_join_guard(monkeypatch):
    st = state()
    st['projects'].append(dict(id='p9', name='丙', code='C200', pm_id='u1', execution_system='workbench'))

    def joined(entity_, projects):
        for pid, proj in projects.items():
            if proj.get('code') == entity_.get('code'):
                return pid, None
        return None, 'assignment_absent'
    monkeypatch.setattr(cl, '_case_link', joined)
    row = next(r for r in build_confirmation_list(st, limit=100)['rows'] if r['row_key'] == 'b/t/r4@i10')
    assert row['case_link']['state'] == 'linked'      # the guard is what keeps this unresolved


def test_walking_cursor_pages_reconciles_to_population_for_every_combination():
    st = state()
    combos = [dict(), dict(q='c100'), dict(filters={'source_version': ['4']}),
              dict(filters={'pm': ['u1']}, sort={'column': 'confirmation_version', 'direction': 'desc'}),
              dict(filters={'admission_state': 'workbench'}, q='甲', sort={'column': 'case_number', 'direction': 'asc'}),
              dict(sort={'column': 'pm', 'direction': 'desc'}), dict(filters={'pm': ['nobody']})]
    for kw in combos:
        keys = walk(st, **dict(kw))
        assert keys == keys_of(confirmation_population(st, kw.get('filters'), q=kw.get('q', ''), sort=kw.get('sort')))
        assert len(keys) == len(set(keys))
    raw = {r['row_key'] for r in build_confirmation_list(st, limit=100)['rows']}
    assert set(walk(st)) == raw


def test_numeric_sort_and_clear_and_unknown_last():
    st = state()
    asc = [r['confirmation_version']['value'] for r in build_confirmation_list(
        st, limit=100, sort={'column': 'confirmation_version', 'direction': 'asc'})['rows']]
    assert asc == ['2', '3', '4', '4', '10', None]
    desc = [r['confirmation_version']['value'] for r in build_confirmation_list(
        st, limit=100, sort={'column': 'confirmation_version', 'direction': 'desc'})['rows']]
    assert desc == ['10', '4', '4', '3', '2', None]
    cleared = build_confirmation_list(st, limit=100, sort={'column': 'case_number', 'direction': 'clear'})
    assert cleared['sort']['applied'] is None
    assert [r['row_key'] for r in cleared['rows']][:2] == ['b/t/r1@i3', 'b/t/r2@i4']


def test_default_order_is_source_order_and_not_time_based():
    page = build_confirmation_list(state(), limit=100)
    assert page['sort']['source_modified'] == 'unavailable'
    assert all(r['source_modified']['state'] == 'unknown' for r in page['rows'])
    assert build_confirmation_list(state(), limit=100, sort={'column': 'source_modified'})['status'] == 422


def test_equal_sort_keys_page_stably_by_row_key():
    st = state()
    sort = {'column': 'case_number', 'direction': 'desc'}
    assert walk(st, sort=sort, limit=1) == keys_of(confirmation_population(st, sort=sort))


def test_cursor_from_another_filter_set_is_rejected():
    st = state()
    cursor = build_confirmation_list(st, limit=1, filters={'pm': ['u1']})['next_cursor']
    assert cursor
    result = build_confirmation_list(st, limit=1, filters={'pm': ['u2']}, cursor=cursor)
    assert (result['status'], result['error']) == (422, 'cursor_filter_mismatch')
    result = build_confirmation_list(st, limit=1, filters={'pm': ['u1']}, cursor=cursor, sort={'column': 'pm'})
    assert result['error'] == 'cursor_filter_mismatch'
    assert build_confirmation_list(st, limit=1, filters={'pm': ['u1']}, cursor=cursor)['status'] == 200
    assert build_confirmation_list(st, cursor='%%%')['error'] == 'cursor_invalid'


def test_mutation_cursor_set_guard(monkeypatch):
    st = state()
    cursor = build_confirmation_list(st, limit=1, filters={'source_version': ['3', '4']})['next_cursor']
    other = dict(limit=1, filters={'source_version': ['3']}, cursor=cursor)      # r1 is in both sets
    assert build_confirmation_list(st, **other)['error'] == 'cursor_filter_mismatch'
    monkeypatch.setattr(cl, '_cursor_matches', lambda expected, actual: True)     # mutation: accept any set
    assert build_confirmation_list(st, **other)['status'] == 200


def test_limit_bounds():
    for bad in (0, 101, -1, True, '5', None):
        assert build_confirmation_list(state(), limit=bad)['status'] == 422
    assert build_confirmation_list(state(), limit=1)['totals']['loaded'] == 1
    assert build_confirmation_list(state(), limit=100)['status'] == 200


def test_deadline_filter_is_unavailable_and_hides_nothing():
    st = state()
    full = keys_of(confirmation_population(st))
    page = build_confirmation_list(st, limit=100, filters={'deadline_from': '2026-01-01', 'deadline_to': '2026-01-02'})
    assert [r['row_key'] for r in page['rows']] == full
    status = page['filter_status']['deadline']
    assert status['status'] == 'unavailable' and status['reason'] and status['hides_rows'] is False
    assert keys_of(confirmation_population(st, {'deadline_from': '2026-01-01'})) == full
    assert build_confirmation_list(st, filters={'deadline_from': 'soon'})['status'] == 422


def test_unknown_due_is_never_zero_or_matched():
    for row in build_confirmation_list(state(), limit=100)['rows']:
        assert row['effective_due'] == {'state': 'unknown', 'value': None, 'reason': cl.DEADLINE_REASON}


def test_unknown_values_never_match_concrete_filters_and_are_counted():
    st = state()
    page = build_confirmation_list(st, limit=100, filters={'pm': ['u1'], 'admission_state': ['workbench']})
    assert {r['case_link']['project_id'] for r in page['rows']} == {'p1'}
    assert page['excluded_unknown']['pm'] == 3 and page['excluded_unknown']['admission_state'] == 3
    assert page['excluded_unknown']['distinct_rows'] == 3
    assert page['totals'] == {'matching': 2, 'loaded': 2, 'authorized_source': 6}
    versions = build_confirmation_list(st, limit=100, filters={'source_version': ['4']})
    assert versions['excluded_unknown']['source_version'] == 1       # r6 has no version


def test_totals_are_separate():
    page = build_confirmation_list(state(), limit=2, q='C100')
    assert page['totals'] == {'matching': 3, 'loaded': 2, 'authorized_source': 6}
    assert page['next_cursor']


def test_forbidden_absent_confirmation_contributes_nothing():
    full = state()
    narrowed = deepcopy(full)
    narrowed['source_confirmations'] = [e for e in narrowed['source_confirmations'] if e['id'] != 'b/t/r2']
    page = build_confirmation_list(narrowed, limit=100)
    blob = repr(page)
    assert 'r2' not in blob and page['totals']['authorized_source'] == 5
    assert page['grouping']['linked_cases'] == 1
    assert 'p2' not in blob
    gone = build_confirmation_list(dict(full, source_status={'status': 'forbidden'}), limit=100)
    assert gone == {'status': 403, 'page_state': {'states': ['forbidden']}}


def test_page_states_are_distinct():
    ok = build_confirmation_list(state(), limit=100)
    assert ok['page_state'] is None
    nomatch = build_confirmation_list(state(), q='zzz')
    assert nomatch['page_state'] == {'states': ['filtered_empty'], 'count': 0} and nomatch['totals']['matching'] == 0
    empty = build_confirmation_list(state(source_confirmations=[]))
    assert empty['page_state'] == {'states': ['complete_empty'], 'count': 0}
    notloaded = build_confirmation_list({'environment': 'test', 'source_status': {'status': 'ready'}})
    assert notloaded['page_state']['states'] == ['unlocated'] and notloaded['totals']['matching'] is None
    loading = build_confirmation_list(state(source_status={'status': 'loading'}))
    assert loading['page_state']['states'] == ['loading'] and loading['rows'] == []
    failed = build_confirmation_list(state(source_status={'status': 'error'}), limit=100)
    assert failed['page_state'] == {'states': ['read_failed'], 'count': None}
    assert failed['totals_basis'] == 'undetermined'
    assert {r['source_status'] for r in failed['rows']} == {'stale'}
    assert {r['retention'] for r in failed['rows']} == {'snapshot'}
    stale = build_confirmation_list(state(source_status={'status': 'stale'}), limit=100)
    assert stale['totals_basis'] == 'retained_snapshot'
    assert stale['page_state']['states'] == ['stale'] and stale['page_state']['count'] is None
    partial_empty = build_confirmation_list(state(source_status={'status': 'partial'}, source_confirmations=[]))
    assert partial_empty['page_state']['states'] == ['partial']        # not claimed as zero
    assert build_confirmation_list(state(source_status={})) ['page_state']['states'] == ['unknown']
    assert confirmation_population({'source_status': {'status': 'forbidden'}}) is None


def test_missing_source_row_is_labelled_snapshot():
    st = state()
    st['source_confirmations'][0]['source_missing'] = True
    row = build_confirmation_list(st, limit=100)['rows'][0]
    assert (row['source_status'], row['retention']) == ('missing', 'snapshot')


def test_row_fields_admission_workflow_and_withheld_amounts():
    page = build_confirmation_list(state(), limit=100)
    row = page['rows'][0]
    assert row['admission']['state'] == 'workbench' and row['pm'] == {'id': 'u1', 'name': 'Ann', 'state': 'known'}
    assert row['workflow_summary'] == {'state': 'known', 'total': 2, 'completed': 1,
                                       'by_status': {'completed': 1, 'pending': 1}}
    assert page['rows'][1]['admission']['state'] == 'meegle'
    assert row['detail'] == {'source_context': {'base_token': 'b', 'table_id': 't'}, 'record_id': 'r1', 'non_default': True}
    assert 'record_id' not in page['columns']['default'] and 'record_id' in page['columns']['non_default']
    assert page['amounts']['state'] == 'withheld'
    assert '987654' not in repr(page)


def test_read_model_does_not_mutate_input_or_leak_private_keys():
    st = state()
    before = deepcopy(st)
    page = build_confirmation_list(st, limit=100)
    assert st == before
    assert not any(k.startswith('_') for r in page['rows'] for k in r)


def test_unsupported_filter_and_bad_malformed_identity():
    assert build_confirmation_list(state(), filters={'secret': 'x'})['error'] == 'filter_unsupported'
    st = state()
    st['source_confirmations'].append(dict(id='x', source_identity=dict(base_token='b', table_id='t', record_id='a/b'),
                                           source_kind='confirmation', fields={}))
    page = build_confirmation_list(st, limit=100)
    assert page['totals']['authorized_source'] == 6 and page['diagnostics']['unkeyed_rows'] == 1


# ---- P2-129B-FIX1 -------------------------------------------------------

def test_population_returns_literal_project_ids_and_distinct_case_denominator():
    pop = confirmation_population(state())
    assert pop == [
        {'row_key': 'b/t/r1@i3', 'project_id': 'p1'}, {'row_key': 'b/t/r2@i4', 'project_id': 'p2'},
        {'row_key': 'b/t/r3@i4', 'project_id': 'p1'}, {'row_key': 'b/t/r4@i10', 'project_id': None},
        {'row_key': 'b/t/r5@i2', 'project_id': None},      # p-hidden is not visible: unresolved, id not echoed
        {'row_key': 'b/t/r6@u', 'project_id': None}]
    assert len({r['project_id'] for r in pop if r['project_id']}) == 2          # distinct cases, not 3 rows for p1/p2
    assert confirmation_population(state(), {'pm': ['u1']}) == [
        {'row_key': 'b/t/r1@i3', 'project_id': 'p1'}, {'row_key': 'b/t/r3@i4', 'project_id': 'p1'}]
    assert 'p-hidden' not in repr(pop)


def test_population_is_none_not_a_list_when_source_unavailable():
    for status in ('forbidden', 'loading', 'unlocated', 'unknown', 'error'):
        assert confirmation_population(state(source_status={'status': status})) is None, status
    assert confirmation_population({'environment': 'test', 'source_status': {'status': 'ready'}}) is None
    assert confirmation_population(state(source_status={'status': 'ready'}, source_confirmations=[])) == []


def test_typed_version_collision_int_3_vs_str_3_walks_all_pages():
    st = state(source_confirmations=[entity('r1', 'C1', version=3), entity('r1', 'C1', version='3')])
    page = build_confirmation_list(st, limit=1)
    assert page['totals']['matching'] == 2 and page['rows'][0]['row_key'] == 'b/t/r1@i3'
    second = build_confirmation_list(st, limit=1, cursor=page['next_cursor'])
    assert [r['row_key'] for r in second['rows']] == ['b/t/r1@s3']
    assert walk(st, limit=1) == ['b/t/r1@i3', 'b/t/r1@s3']
    assert keys_of(confirmation_population(st)) == ['b/t/r1@i3', 'b/t/r1@s3']


def test_delimiter_collision_record_with_at_sign_vs_version_walks_all_pages():
    st = state(source_confirmations=[entity('r1@3', 'C1'), entity('r1', 'C1', version=3),
                                     entity('r1', 'C1', version='x@y')])
    assert walk(st, limit=1) == ['b/t/r1@3@u', 'b/t/r1@i3', 'b/t/r1@sx%40y']
    assert keys_of(confirmation_population(st)) == ['b/t/r1@3@u', 'b/t/r1@i3', 'b/t/r1@sx%40y']
    row = build_confirmation_list(st, limit=1)['rows'][0]
    assert row['detail']['record_id'] == 'r1@3'                     # stored source id unchanged


def test_unknown_read_never_exposes_proven_zero_or_population():
    for st in (state(source_status={}, source_confirmations=[]), state(source_status={'status': 'error'}, source_confirmations=[])):
        page = build_confirmation_list(st)
        assert page['totals']['matching'] is None and page['totals']['authorized_source'] is None
        assert page['totals']['loaded'] == 0 and page['totals_basis'] == 'undetermined'
        assert confirmation_population(st) is None
    with_rows = build_confirmation_list(state(source_status={}), limit=100)
    assert with_rows['totals']['matching'] is None and with_rows['totals']['loaded'] == 6
    assert {r['source_status'] for r in with_rows['rows']} == {'unknown'}


def test_proven_empty_current_read_is_the_only_proven_zero():
    page = build_confirmation_list(state(source_confirmations=[]))
    assert page['totals'] == {'matching': 0, 'loaded': 0, 'authorized_source': 0}
    assert page['totals_basis'] == 'current' and page['page_state'] == {'states': ['complete_empty'], 'count': 0}
    for status in ('partial', 'stale'):
        p = build_confirmation_list(state(source_status={'status': status}, source_confirmations=[]))
        assert p['totals']['matching'] is None and p['totals']['authorized_source'] is None, status


def test_retained_snapshot_carries_explicit_provenance():
    ts = '2026-10-01T00:00:00+00:00'
    failed = state(source_status={'status': 'error', 'last_success_at': ts})
    page = build_confirmation_list(failed, limit=100)
    assert page['totals'] == {'matching': 6, 'loaded': 6, 'authorized_source': 6}
    assert page['totals_basis'] == 'retained_snapshot'
    assert page['snapshot'] == {'state': 'proven', 'last_success_at': ts}
    assert len(confirmation_population(failed)) == 6
    unproven = build_confirmation_list(state(source_status={'status': 'error'}), limit=100)
    assert unproven['snapshot'] == {'state': 'unproven', 'last_success_at': None}
    assert unproven['totals']['matching'] is None and confirmation_population(state(source_status={'status': 'error'})) is None
    assert build_confirmation_list(state(), limit=100)['snapshot'] is None
    assert page['as_of'] is None                       # as_of is never substituted with business time


def test_partial_import_retained_rows_are_snapshot_not_current():
    page = build_confirmation_list(state(source_status={'status': 'partial'}), limit=100)
    assert {r['source_status'] for r in page['rows']} == {'stale'}
    assert {r['retention'] for r in page['rows']} == {'snapshot'}
    assert page['totals_basis'] == 'partial_snapshot' and page['page_state']['states'] == ['partial']
    ok = build_confirmation_list(state(), limit=100)
    assert {r['source_status'] for r in ok['rows']} == {'located'} and {r['retention'] for r in ok['rows']} == {'current'}
    assert all(r['source_modified']['value'] is None for r in page['rows'])


def test_filtered_zero_on_partial_or_stale_keeps_source_uncertainty():
    for status in ('partial', 'stale'):
        page = build_confirmation_list(state(source_status={'status': status}), q='no-match')
        assert page['page_state'] == {'states': [status], 'count': None}, status
        assert page['totals']['matching'] is None and page['totals']['loaded'] == 0   # F2: unproven zero
        assert page['totals_basis'] != 'current'
    both = build_confirmation_list(state(source_status={'status': 'error', 'last_success_at': '2026-10-01T00:00:00+00:00'}), q='no-match')
    assert both['page_state']['states'] == ['read_failed']
    ok = build_confirmation_list(state(), q='no-match')
    assert ok['page_state'] == {'states': ['filtered_empty'], 'count': 0} and ok['totals_basis'] == 'current'


def test_unknown_read_retained_rows_are_snapshot_never_current():
    for source in ({}, {'status': 'unknown'}, {'status': 'unknown', 'last_success_at': '2026-10-01T00:00:00Z'}):
        page = build_confirmation_list(state(source_status=source), limit=100)
        assert len(page['rows']) == 6, source
        assert {(r['source_status'], r['retention']) for r in page['rows']} == {('unknown', 'snapshot')}, source
        assert page['totals']['matching'] is None and page['totals_basis'] == 'undetermined', source
    healthy = build_confirmation_list(state(), limit=100)
    assert {(r['source_status'], r['retention']) for r in healthy['rows']} == {('located', 'current')}


def test_mutation_unknown_retention_guard():
    import inspect
    good = "'retention': 'current' if status == 'located' else 'snapshot',"
    bad = "'retention': 'snapshot' if status in ('missing', 'stale') else 'current',"
    src = inspect.getsource(cl)
    assert good in src
    mutant = {'__name__': 'backend.confirmation_list_mutant', '__package__': 'backend'}
    exec(compile(src.replace(good, bad), 'mutant', 'exec'), mutant)
    rows = mutant['build_confirmation_list'](state(source_status={}), limit=100)['rows']
    assert {r['retention'] for r in rows} == {'current'}     # the guarded behaviour test would fail on this


def test_partial_with_independent_stale_flag_keeps_both_states_and_noncurrent_zero_is_undetermined():
    both = build_confirmation_list(state(source_status={'status': 'partial', 'stale': True}), limit=100)
    assert both['page_state']['states'] == ['partial', 'stale'] and both['totals_basis'] == 'partial_snapshot'
    plain = build_confirmation_list(state(source_status={'status': 'partial'}), limit=100)
    assert plain['page_state']['states'] == ['partial']      # the flag is what adds stale
    assert build_confirmation_list(state(source_status={'status': 'ready', 'stale': True}))['page_state'] is None
    for status in ({'status': 'stale'}, {'status': 'partial'}, {'status': 'partial', 'stale': True}):
        zero = build_confirmation_list(state(source_status=status), filters={'admission_state': ['nonexistent']})
        assert zero['totals']['matching'] is None and zero['rows'] == [], status
        nonzero = build_confirmation_list(state(source_status=status), limit=100)
        assert nonzero['totals']['matching'] == len(nonzero['rows']) > 0, status
    current = build_confirmation_list(state(), filters={'admission_state': ['nonexistent']})
    assert current['totals']['matching'] == 0 and current['page_state']['states'] == ['filtered_empty']
