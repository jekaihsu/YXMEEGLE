"""Issue #6: only a verified canonical lifecycle may permit execution; everything else is 待核對."""
import pytest
from fastapi import HTTPException
from .test_workflow_automation import setup, body
from .source_lifecycle import declared, needs_review, summarize
from .workflow_rules import activate_scheduled, activation_reasons, execution_reasons
from .operations import refresh_project_state
from .node_skip import apply_skip, current
from .jobs import schedule

CLOCK = '2026-09-28T09:00:00+08:00'
BAD = {
    'blank': {'canonical': None, 'state': 'needs_verification', 'reasons': ['blank']},
    'unknown': {'canonical': None, 'state': 'needs_verification', 'reasons': ['unknown_option']},
    'conflict': {'canonical': None, 'state': 'needs_verification', 'reasons': ['conflict']},
    'forged_mapped_with_reasons': {'canonical': '執行中', 'state': 'mapped', 'reasons': ['conflict']},
    'mapped_without_canonical': {'canonical': None, 'state': 'mapped', 'reasons': []},
    'undocumented_canonical': {'canonical': '已簽約', 'state': 'mapped', 'reasons': []},
    'missing': None,
}
OK = {'canonical': '執行中', 'state': 'mapped', 'reasons': []}


def entry(raw, source='confirmation'):
    return {'base_token': 'b', 'table_id': 't', 'record_id': 'r' + raw,
            'fields': {'狀態': raw, '案件狀態': raw}}


def lark(p, lifecycle):
    p['source_kind'] = 'lark'
    if lifecycle is None:
        p.pop('source_lifecycle', None)
    else:
        p['source_lifecycle'] = lifecycle


def test_blank_source_beside_mapped_source_is_review_not_mapped():
    lc = summarize([entry('執行中')], [{'base_token': 'b', 'table_id': 'q', 'record_id': 'rq',
                                       'fields': {'狀態': '成案', '案件狀態': ''}}])
    assert lc['canonical'] is None and lc['state'] == 'needs_verification' and 'blank' in lc['reasons']
    assert declared({'source_lifecycle': lc}) is None and needs_review({'source_lifecycle': lc})


def test_no_sources_at_all_is_review():
    lc = summarize([], [])
    assert lc['canonical'] is None and lc['reasons'] == ['blank']


@pytest.mark.parametrize('kind', BAD)
def test_unverified_lifecycle_has_no_declared_value_and_needs_review(kind):
    p = {'source_kind': 'lark'}
    if BAD[kind] is not None: p['source_lifecycle'] = BAD[kind]
    assert declared(p) is None and needs_review(p)


def test_verified_lifecycle_and_ungoverned_cases_are_not_flagged():
    assert declared({'source_lifecycle': OK}) == '執行中' and not needs_review({'source_lifecycle': OK})
    assert not needs_review({'source_kind': 'demo'})  # no source lifecycle concept


@pytest.mark.parametrize('kind', BAD)
def test_task_readiness_and_scheduled_activation_fail_closed(setup, kind):
    ws, p, n, user = setup; t = n['tasks'][0]; lark(p, BAD[kind])
    assert any('來源案件狀態待核對' in r for r in activation_reasons(ws, p, n, t, CLOCK))
    assert execution_reasons(ws, p, n, t)
    assert t['id'] not in activate_scheduled(ws, CLOCK) and t['status'] == 'pending'


def test_verified_lifecycle_still_activates(setup):
    ws, p, n, user = setup; lark(p, OK)
    assert n['tasks'][0]['id'] in activate_scheduled(ws, CLOCK)


@pytest.mark.parametrize('kind', BAD)
def test_routine_scheduling_creates_and_notifies_nothing(setup, kind):
    ws, p, n, user = setup; ws['recurring'] = []; ws['jobs'] = []; lark(p, BAD[kind])
    schedule(ws, CLOCK)
    assert not [r for r in ws['recurring'] if r['project_id'] == p['id']] and not ws['jobs']


@pytest.mark.parametrize('kind', BAD)
def test_existing_routines_including_financial_stay_silent(setup, kind):
    ws, p, n, user = setup; ws['jobs'] = []
    ws['recurring'] = [dict(id='r1', project_id=p['id'], kind='receivable', title='x', owner_id='u-manager',
                            supervisor_id='u-manager', status='active', start_date='2026-09-01',
                            due_date='2026-09-01', history=[])]
    lark(p, BAD[kind]); schedule(ws, CLOCK)
    assert not ws['jobs']


def test_verified_lifecycle_creates_routines(setup):
    ws, p, n, user = setup; ws['recurring'] = []; lark(p, OK); schedule(ws, CLOCK)
    assert any(r['project_id'] == p['id'] for r in ws['recurring'])


@pytest.mark.parametrize('kind', BAD)
def test_node_skip_request_and_apply_fail_closed(setup, kind):
    ws, p, n, user = setup; n['key'] = 'control'; lark(p, BAD[kind])
    assert not current(ws, p, n, {'content_hash': 'x', 'skip_scope_version': 1})
    manager = next(u for u in ws['users'] if u['role'] == 'manager')
    with pytest.raises(HTTPException) as e:
        apply_skip(ws, manager, {'action': 'node_skip_create', 'project_id': p['id'], 'node_id': n['id'],
                                 'payload': {'reason': 'r' * 20, 'impact': 'i' * 20}}, True)
    assert e.value.status_code == 409


@pytest.mark.parametrize('kind', BAD)
def test_project_refresh_pauses_unverified_case_without_losing_history(setup, kind):
    ws, p, n, user = setup; lark(p, BAD[kind]); p['execution_status'] = 'pending'
    nodes = [(x['id'], x['status']) for x in p['nodes']]
    refresh_project_state(p, ws)
    assert p['execution_status'] == 'paused' and p['status'] == 'paused'
    assert nodes == [(x['id'], x['status']) for x in p['nodes']]
