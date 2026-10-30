"""VCC-119: a changed Lark quote deadline (報價期限) must reach the existing sales tasks without duplicating them."""
import pytest
from .seed import seed
from .sources import import_sources

QUOTE = dict(base_token='q', table_id='quote', record_id='recQ1', kind='quote')


def quotes(deadline):
    return [dict(QUOTE, fields={'報價編號': 'Q115259', '工程名稱': 'Synthetic', '報價期限': deadline})]


def sales_tasks(state):
    p = next(p for p in state['projects'] if p.get('case_type') == 'intake')
    node = next(n for n in p['nodes'] if n['key'] == 'sales')
    return p, node, node['tasks']


@pytest.mark.xfail(strict=True, reason='open finding: no importer maps 報價期限 (backend/sources.py:16 only lists it as a required field) onto sales task/node due_date; '
                   'v4_sources.new_task/nodes create tasks with due_date=None (backend/sources.py:201, backend/v4_sources.py:37) and re-import never touches them')
def test_changed_quote_deadline_updates_existing_sales_tasks_without_duplicates():
    state = seed(True); state['projects'] = []
    import_sources(state, quotes('2026-09-10'))
    p, node, tasks = sales_tasks(state)
    ids = [t['id'] for t in tasks]
    assert tasks and {t['due_date'] for t in tasks} == {'2026-09-10'}  # premise from staging: sales tasks carry the quote deadline
    import_sources(state, quotes('2026-09-20'))
    p2, node2, tasks2 = sales_tasks(state)
    assert p2['id'] == p['id'] and [t['id'] for t in tasks2] == ids  # same case, no duplicated tasks
    assert {t['due_date'] for t in tasks2} == {'2026-09-20'} and node2['due_date'] == '2026-09-20'
