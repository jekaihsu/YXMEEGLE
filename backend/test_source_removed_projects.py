"""Case removal follows verified complete Lark table snapshots only."""
from copy import deepcopy
import pytest

from .seed import seed
from .sources import import_sources

BASE = 'removed-case-base'
TABLES = {'quote': 'tbl-quote', 'confirmation': 'tbl-confirmation', 'quote_confirmation': 'tbl-quote-confirmation'}


def row(kind, rid, fields):
    return dict(base_token=BASE, table_id=TABLES[kind], record_id=rid, kind=kind, fields=fields)


def complete(kind, count, status='ready'):
    return [dict(base_token=BASE, table_id=TABLES[kind], kind=kind, status=status, count=count)]


def project(state, code):
    return next(p for p in state['projects'] if p['code'] == code)


def test_removed_intake_is_marked_once_and_reappearance_clears_it():
    quote = row('quote', 'recQuote', {'報價編號': 'Q115901', '工程名稱': '報價案'})
    state = seed(True)
    import_sources(state, [quote], complete('quote', 1))
    intake = project(state, 'Q115901')
    assert 'source_removed_at' not in intake
    import_sources(state, [], complete('quote', 0))
    first = intake['source_removed_at']
    assert first and len(state['projects']) == 1
    import_sources(state, [], complete('quote', 0))
    assert intake['source_removed_at'] == first
    import_sources(state, [quote], complete('quote', 1))
    assert 'source_removed_at' not in intake
    assert project(state, 'Q115901')['id'] == intake['id']


def test_incomplete_table_cannot_mark_a_case_removed():
    quote = row('quote', 'recQuote', {'報價編號': 'Q115902'})
    state = seed(True)
    import_sources(state, [quote], complete('quote', 1))
    intake = project(state, 'Q115902')
    for tables in (None, complete('quote', 0, 'error'), complete('quote', 1)):
        import_sources(state, [], tables)
        assert 'source_removed_at' not in intake
    import_sources(state, [], complete('quote', 0))
    assert intake['source_removed_at']
    import_sources(state, [quote])
    assert 'source_removed_at' not in intake


@pytest.mark.parametrize('kind', ['confirmation', 'quote_confirmation'])
def test_formal_case_waits_for_all_source_tables_and_preserves_local_work(kind):
    confirmation = row(kind, 'recCase', {'工程確認單編號': 'C115903', '狀態': '執行中'})
    quote = row('quote', 'recQuote', {'報價編號': 'Q115903', '工程編號': 'C115903',
                                      '此案確認單': [{'table_id': TABLES[kind], 'record_ids': ['recCase']}]})
    state = seed(True)
    both = complete('quote', 1) + complete(kind, 1)
    import_sources(state, [confirmation, quote], both)
    formal = project(state, 'C115903')
    local_task = deepcopy(formal['nodes'][0]['tasks'][0])
    local_task['id'] = 'local-task'
    formal['nodes'][0]['tasks'].append(local_task)
    formal['comments'].append({'id': 'local-comment', 'text': '保留歷史'})
    nodes = deepcopy(formal['nodes'])
    comments = deepcopy(formal['comments'])
    import_sources(state, [quote], complete('quote', 1) + complete(kind, 0))
    assert 'source_removed_at' not in formal
    import_sources(state, [], complete('quote', 0))
    assert 'source_removed_at' not in formal
    import_sources(state, [], complete('quote', 0) + complete(kind, 0))
    assert formal['source_removed_at'] and formal in state['projects']
    assert formal['nodes'] == nodes and formal['comments'] == comments
    import_sources(state, [confirmation], complete(kind, 1))
    assert 'source_removed_at' not in formal
    assert next(t for t in formal['nodes'][0]['tasks'] if t['id'] == 'local-task') == local_task
    assert formal['comments'] == comments
