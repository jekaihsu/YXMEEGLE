from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from .models import BusinessRow
from .sop_import.models import TaskEvent
from .test_sop_import import apply, h, intake, overview, post  # noqa: F401  (fixtures)

C_ROW = {'詢價日期': '2026-08-19', '行號單位': '永達能源工程股份有限公司', '第一次聯繫日期': '2026-08-19',
         '報價日期': '2026-08-10', '提供給PM日期': '2026-08-10', '報價期限': '2026-08-24', '回傳單日期': '2026-09-17',
         '契約價格(未稅)': 24000, '工程編號': 'C115264', '狀態': '成案'}
QUOTE_ROW = {'詢價日期': '2026-10-01', '行號單位': '鼎創工程股份有限公司', '報價日期': '2026-10-05',
             '提供給PM日期': '2026-10-05', '報價期限': '2026-11-05'}


@pytest.fixture
def case(intake):
    h, url, project = intake
    h.service.clock = lambda: datetime(2026, 10, 20, 12, tzinfo=ZoneInfo('Asia/Taipei')).timestamp()
    apply(h, url=url)
    return h, url, project


def set_quote(h, project, **fields):
    with h.sessions.begin() as db:
        row = db.get(BusinessRow, ('w', 'projects', project['id']))
        data = deepcopy(row.data)
        for quote in data['quotes'] + data['source_records']:
            quote['fields'].update(fields)
        row.data = data


def key(n):
    return f'meegle-v137:A:{n}'


def suggested(h, url):
    return {t['origin']['source_row_key']: (t['suggestion']['suggested_state'], t['suggestion']['tier'])
            for t in overview(h, url)['tasks'] if t['suggestion']}


def task(h, url, n):
    return next(t for t in overview(h, url)['tasks'] if t['origin']['source_row_key'] == key(n))


def decide(h, url, n, status=200, **body):
    found = task(h, url, n)
    body = {'action': 'accept_suggestion', 'facts_hash': found['suggestion']['facts_hash'],
            'expected_revision': found['revision'], **body}
    return post(h, f"{url}/sop-tasks/{found['id']}/suggestion", body, status)


def events(h, kind):
    with h.sessions() as db:
        return list(db.scalars(select(TaskEvent).where(TaskEvent.kind == kind)))


def test_c_prefix_case_suggests_quote_tasks_done(case):
    h, url, project = case
    set_quote(h, project, **C_ROW)
    assert overview(h, url)['stage'] == 'numbered'
    assert suggested(h, url) == {
        key(1): ('done', 'indicator'), key(2): ('done', 'proof'), key(3): ('done', 'indicator'),
        key(8): ('done', 'indicator'), key(9): ('done', 'indicator'), key(12): ('done', 'proof'),
        key(15): ('done', 'indicator'), key(16): ('done', 'indicator')}
    assert task(h, url, 16)['suggestion']['facts'] == {'engineering_no': 'C115264', 'numbered': True, 'numbers_consistent': True}
    assert task(h, url, 15)['suggestion']['facts'] == {'returned_date': '2026-09-17', 'price_positive': True}
    assert task(h, url, 12)['allowed_actions'] == ['start', 'block', 'archive', 'set_applicability', 'edit',
                                                   'accept_suggestion', 'dismiss_suggestion']
    assert task(h, url, 17)['allowed_actions'] == ['start', 'block', 'archive', 'set_applicability', 'edit']


def test_quote_stage_case_suggests_nothing_that_needs_a_won_quote(case):
    h, url, project = case
    assert suggested(h, url) == {key(2): ('done', 'proof')}
    set_quote(h, project, **QUOTE_ROW)
    assert overview(h, url)['stage'] == 'quoted'
    assert suggested(h, url) == {key(1): ('done', 'indicator'), key(2): ('done', 'proof'),
                                 key(8): ('done', 'indicator'), key(9): ('in_progress', 'indicator')}


def test_duplicated_quote_rows_merge_their_evidence(case):
    h, url, project = case
    h.extra['source_quotes'] = [{'id': 'base/quotes/recTwin', 'source_missing': False, 'code': '115588',
                                 'source_identity': {'base_token': 'base', 'table_id': 'quotes', 'record_id': 'recTwin'},
                                 'fields': {'報價編號': '115588', '回傳單日期': 1789574400000, '工程編號': 'C115243'}}]
    assert overview(h, url)['stage'] == 'numbered'
    assert suggested(h, url) == {key(2): ('done', 'indicator'), key(9): ('done', 'indicator'), key(12): ('done', 'proof'),
                                 key(15): ('in_progress', 'indicator'), key(16): ('done', 'indicator')}
    assert task(h, url, 2)['suggestion']['facts'] == {'quote_nos': ['115588'], 'duplicated': True}


def test_reading_suggestions_changes_nothing(case):
    h, url, project = case
    set_quote(h, project, **C_ROW)
    before = len(events(h, 'imported'))
    overview(h, url)
    overview(h, url)
    assert {t['state'] for t in overview(h, url)['tasks']} == {'pending'}
    assert [len(events(h, kind)) for kind in ('imported', 'suggestion_accepted', 'suggestion_dismissed')] == [before, 0, 0]


def test_proof_tier_completes_an_imported_task_and_records_the_rule(case):
    h, url, project = case
    set_quote(h, project, **C_ROW)
    target = task(h, url, 12)
    rejected = post(h, f"{url}/sop-tasks/{target['id']}/transition", {'expected_revision': 1, 'action': 'complete'}, 422)
    assert rejected['code'] == 'completion_evidence_missing'
    result = decide(h, url, 12)
    assert {k: result[k] for k in ('state', 'revision', 'replayed', 'checklist_revision')} == {
        'state': 'done', 'revision': 2, 'replayed': False, 'checklist_revision': 2}
    [event] = events(h, 'suggestion_accepted')
    assert (event.actor_id, event.changes['rule_id'], event.changes['rule_revision'], event.changes['facts_hash'],
            event.changes['transition'], event.changes['from_state']) == (
        'pm', 'quote-evidence:A:12', 1, target['suggestion']['facts_hash'], 'complete', 'pending')
    assert task(h, url, 12)['local']['evidence_basis']['tier'] == 'proof'
    assert task(h, url, 12)['suggestion'] is None


def test_indicator_tier_needs_explicit_confirmation_and_reason(case):
    h, url, project = case
    set_quote(h, project, **C_ROW)
    assert decide(h, url, 3, 422)['code'] == 'suggestion_confirmation_required'
    assert decide(h, url, 3, 422, confirm=True)['code'] == 'suggestion_confirmation_required'
    assert decide(h, url, 3, confirm=True, reason='回傳本已上傳')['state'] == 'done'
    set_quote(h, project, **{'回傳單日期': None, '報價期限': '2026-11-05'})
    assert decide(h, url, 9, confirm=True, reason='追蹤中')['state'] == 'in_progress'


def test_stale_facts_hash_and_revision_are_rejected(case):
    h, url, project = case
    set_quote(h, project, **C_ROW)
    target = task(h, url, 12)
    body = {'action': 'accept_suggestion', 'facts_hash': target['suggestion']['facts_hash'], 'expected_revision': 1}
    set_quote(h, project, 回傳單日期=None)
    stale = post(h, f"{url}/sop-tasks/{target['id']}/suggestion", body, 409)
    assert stale == {'code': 'suggestion_stale', 'detail': 'suggestion_stale', 'task_id': target['id']}
    assert decide(h, url, 12, 409, expected_revision=7)['code'] == 'task_revision_conflict'
    assert task(h, url, 12)['state'] == 'pending'


def test_only_case_task_managers_decide(case):
    h, url, project = case
    set_quote(h, project, **C_ROW)
    target = task(h, url, 12)
    body = {'action': 'accept_suggestion', 'facts_hash': target['suggestion']['facts_hash'], 'expected_revision': 1}
    for who in ('member',):
        h.who[0] = who
        assert post(h, f"{url}/sop-tasks/{target['id']}/suggestion", body, 403)['code'] == 'sop_import_forbidden'
        item = {'task_id': target['id'], 'facts_hash': body['facts_hash'], 'expected_revision': 1}
        assert post(h, f'{url}/sop-tasks/suggestions/accept', {'tasks': [item]}, 403)['code'] == 'sop_import_forbidden'
    h.who[0] = 'pm'
    h.cfg['SOP_TASK_WRITES_ENABLED'] = 'false'
    assert post(h, f"{url}/sop-tasks/{target['id']}/suggestion", body, 503)['code'] == 'import_unavailable'
    assert task(h, url, 12)['state'] == 'pending'


def test_accept_replays_idempotently_even_with_writes_off(case):
    h, url, project = case
    set_quote(h, project, **C_ROW)
    target = task(h, url, 12)
    body = {'action': 'accept_suggestion', 'facts_hash': target['suggestion']['facts_hash'], 'expected_revision': 1}
    first = post(h, f"{url}/sop-tasks/{target['id']}/suggestion", body)
    h.cfg['SOP_TASK_WRITES_ENABLED'] = 'false'
    again = post(h, f"{url}/sop-tasks/{target['id']}/suggestion", body)
    assert (again['replayed'], again['revision'], again['state'], again['checklist_revision']) == (True, 2, 'done', first['checklist_revision'])
    bulk = post(h, f'{url}/sop-tasks/suggestions/accept',
                {'tasks': [{'task_id': target['id'], 'facts_hash': body['facts_hash'], 'expected_revision': 1}]})
    assert [r['replayed'] for r in bulk['results']] == [True]
    assert len(events(h, 'suggestion_accepted')) == 1


def test_dismissed_suggestion_stays_hidden_until_its_facts_change(case):
    h, url, project = case
    set_quote(h, project, **C_ROW)
    found = task(h, url, 1)
    body = {'action': 'dismiss_suggestion', 'facts_hash': found['suggestion']['facts_hash'], 'reason': '待補附件'}
    assert post(h, f"{url}/sop-tasks/{found['id']}/suggestion", body)['dismissed'] is True
    assert task(h, url, 1)['suggestion'] is None
    assert post(h, f"{url}/sop-tasks/{found['id']}/suggestion", body)['replayed'] is True
    assert len(events(h, 'suggestion_dismissed')) == 1
    assert task(h, url, 1)['state'] == 'pending'
    set_quote(h, project, 行號單位='鼎創工程股份有限公司')
    assert task(h, url, 1)['suggestion']['facts']['client'] == '鼎創工程股份有限公司'


def test_bulk_accept_is_all_or_nothing(case):
    h, url, project = case
    set_quote(h, project, **C_ROW)
    proof = [task(h, url, n) for n in (2, 12)]
    items = [{'task_id': t['id'], 'facts_hash': t['suggestion']['facts_hash'], 'expected_revision': t['revision']} for t in proof]
    bad = dict(items[1], facts_hash='0' * 64)
    failed = post(h, f'{url}/sop-tasks/suggestions/accept', {'tasks': [items[0], bad]}, 409)
    assert (failed['code'], failed['task_id']) == ('suggestion_stale', proof[1]['id'])
    assert [task(h, url, n)['state'] for n in (2, 12)] == ['pending', 'pending']
    assert events(h, 'suggestion_accepted') == []
    indicator = task(h, url, 3)
    with_indicator = items + [{'task_id': indicator['id'], 'facts_hash': indicator['suggestion']['facts_hash'],
                               'expected_revision': 1}]
    assert post(h, f'{url}/sop-tasks/suggestions/accept', {'tasks': with_indicator}, 422)['task_id'] == indicator['id']
    done = post(h, f'{url}/sop-tasks/suggestions/accept', {'tasks': with_indicator, 'confirm': True, 'confirmed_task_ids': [indicator['id']], 'reason': '三處一致'})
    assert [(r['state'], r['suggestion']['tier']) for r in done['results']] == [('done', 'proof'), ('done', 'proof'), ('done', 'indicator')]
    assert done['checklist_revision'] == 2
