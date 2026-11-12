"""Daily reconciliation keeps exact-link semantics when candidates are indexed."""
from copy import deepcopy

from . import v4_sources
from .seed import seed
from .sources import import_sources, source_id
from scripts.benchmark_source_sync import source_records


def test_indexed_daily_candidates_match_the_full_resolver(monkeypatch):
    state = seed(True)
    confirmations = source_records(5, 0)
    import_sources(state, confirmations)
    projects = state['projects']
    projects[0]['report_link_aliases'] = [{'code': ' SHARED\u200b ', 'status': 'reviewed'},
                                        {'code': 'SHARED', 'status': 'reviewed'},
                                        {'code': 'PENDING', 'status': 'pending'}]
    projects[1]['report_link_aliases'] = [{'code': 'SHARED', 'status': 'reviewed'}]
    projects[2]['report_link_aliases'] = [{'code': 'UNIQUE', 'status': 'reviewed'}]
    codes = ['SHARED', 'UNIQUE', 'PENDING', ' C115000 ', 'C11500', '', 'MISSING']
    records = [dict(base_token='v4', table_id='daily', record_id=f'recD{i}', kind='daily',
                    fields={'工程編號': code, '日期': '2026-10-01', '組別': '控制'}) for i, code in enumerate(codes)]
    for i, code in enumerate(['C115001', 'UNKNOWN', 'C115000'], len(records)):
        records.append(dict(base_token='v4', table_id='daily', record_id=f'recD{i}', kind='daily',
            fields={'工程編號': code, '所屬案件': [{'table_id': 'confirmation', 'record_ids': ['rec0']}],
                    '日期': '2026-10-01', '組別': '控制'}))
    original = v4_sources.resolve_daily
    checked = []
    def compare(row, selected, **kwargs):
        result = original(row, selected, **kwargs)
        assert result == original(row, state['projects'], **kwargs)
        checked.append(len(selected))
        return result
    monkeypatch.setattr(v4_sources, 'resolve_daily', compare)
    stats = import_sources(state, confirmations + records)
    assert checked and max(checked) <= 2 < len(projects)
    assert stats['daily_imported'] == 4
    assert stats['daily_unmatched'] == 6
    assert next(d for d in state['daily_unmatched'] if d['source_case_code'] == 'SHARED')['case_mapping_status'] == 'ambiguous_reference'


def test_batch_daily_replacement_preserves_unfetched_rows_and_last_duplicate():
    state = seed(True)
    records = source_records(3, 2)
    import_sources(state, records)
    original = {p['code']: deepcopy(p['daily_reports']) for p in state['projects']}
    daily = deepcopy(next(r for r in records if r['kind'] == 'daily'))
    ident = source_id(daily)
    daily['fields']['工程編號'] = 'C115001'
    last = deepcopy(daily)
    last['fields']['工程編號'] = 'C115002'
    last['fields']['工作內容'] = 'last source row'
    # Repeating a source ID is normally rejected by the fetcher. A direct
    # importer call still preserves its established last-row-wins behavior.
    import_sources(state, [daily, last])
    rows = [(p, d) for p in state['projects'] for d in p['daily_reports']]
    assert len(rows) == 6
    replaced = [(p, d) for p, d in rows if d['id'] == ident]
    assert len(replaced) == 1
    assert replaced[0][0]['code'] == 'C115002'
    assert replaced[0][1]['description'] == 'last source row'
    untouched = {d['id']: d for entries in original.values() for d in entries if d['id'] != ident}
    assert {d['id']: d for _, d in rows if d['id'] != ident} == untouched
