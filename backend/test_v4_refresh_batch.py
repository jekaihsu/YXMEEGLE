"""Batched daily replacement preserves local history and last-record-wins mapping."""
from copy import deepcopy

import pytest

from .seed import seed
from .sources import import_sources, source_id
from . import v4_sources


def row(kind, rid, code):
    field = '工程確認單編號' if kind == 'confirmation' else '工程編號'
    return dict(base_token='v4', table_id=kind, record_id=rid, kind=kind,
                fields={field: code, '日期': '2026-10-01', '組別': '控制'})


def test_refetched_daily_moves_once_and_preserves_unfetched_history():
    state = seed(True)
    cases = [row('confirmation', 'recA', 'C115001'), row('confirmation', 'recB', 'C115002')]
    first, other = row('daily', 'recD1', 'C115001'), row('daily', 'recD2', 'C115001')
    import_sources(state, cases + [first, other])
    old, new = [next(p for p in state['projects'] if p['code'] == code) for code in ('C115001', 'C115002')]
    local = dict(deepcopy(old['daily_reports'][0]), id='local-history')
    old['daily_reports'].append(local)
    first['fields']['工程編號'] = 'C115002'
    other['fields']['工程編號'] = 'missing'
    import_sources(state, cases + [first, other])
    assert old['daily_reports'] == [local]
    assert [d['id'] for d in new['daily_reports']] == [source_id(first)]
    assert [d['id'] for d in state['daily_unmatched']] == [source_id(other)]
    import_sources(state, cases + [first, other])
    assert old['daily_reports'] == [local]
    assert [d['id'] for d in new['daily_reports']] == [source_id(first)]
    assert [d['id'] for d in state['daily_unmatched']] == [source_id(other)]


@pytest.mark.parametrize('last_code', ['C115002', 'missing', ''])
def test_duplicate_daily_input_keeps_only_the_last_mapping(last_code):
    state = seed(True)
    cases = [row('confirmation', 'recA', 'C115001'), row('confirmation', 'recB', 'C115002')]
    first = row('daily', 'recD', 'C115001')
    last = row('daily', 'recD', last_code)
    import_sources(state, cases + [first, last])
    entries = [(p['code'], d) for p in state['projects'] for d in p['daily_reports']]
    entries += [(None, d) for d in state['daily_unmatched']]
    assert len(entries) == 1
    code, entry = entries[0]
    assert code == ('C115002' if last_code == 'C115002' else None)
    assert entry['source_fields'] == last['fields']


def test_candidate_index_preserves_full_resolver_decisions(monkeypatch):
    state = seed(True)
    cases = [row('confirmation', 'recA', 'C115001'), row('confirmation', 'recB', 'C115002')]
    import_sources(state, cases)
    a, b = [next(p for p in state['projects'] if p['code'] == code) for code in ('C115001', 'C115002')]
    a['report_link_aliases'] = [{'code': 'Q115001', 'status': 'reviewed'},
                               {'code': 'Q115002', 'status': 'pending'}]
    b['report_link_aliases'] = [{'code': 'Q115001', 'status': 'reviewed'}]
    resolver = v4_sources.resolve_daily
    decisions = []

    def compare(record, projects, **kwargs):
        actual = resolver(record, projects, **kwargs)
        assert actual == resolver(record, state['projects'], **kwargs)
        if record.get('kind') == 'daily':
            decisions.append(actual)
        return actual

    monkeypatch.setattr(v4_sources, 'resolve_daily', compare)
    dailies = [row('daily', f'recD{i}', code) for i, code in enumerate(
        ('C115001', '\u200b C115002 ', 'Q115001', 'Q115002', '', 'C115001-2'))]
    conflicting = row('daily', 'recConflict', 'C115002')
    conflicting['fields']['所屬案件'] = [{'table_id': 'confirmation', 'record_ids': ['recA']}]
    unresolved = row('daily', 'recUnknown', 'C115001')
    unresolved['fields']['所屬案件'] = [{'table_id': 'confirmation', 'record_ids': ['recMissing']}]
    provisional = row('daily', 'recProvisional', '')
    provisional['fields']['可能的確認單工編(若暫無確認單才需填寫)'] = 'C115001'
    import_sources(state, cases + dailies + [conflicting, unresolved, provisional])
    assert len(decisions) == 9
    assert [d.reason for d in decisions] == [None, None, 'ambiguous_reference', 'unresolved_reference',
                                            'missing_reference', 'unresolved_reference',
                                            'ambiguous_reference', 'unresolved_reference', None]
