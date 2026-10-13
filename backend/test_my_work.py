"""My Work read model: all-history unfinished assigned work, explicit parents only, C-STATE read states."""
import json
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from . import my_work
from .my_work import build_my_work_input
from .operations import review_hash

READY = {'loaded': True, 'admitted': True}
ROOT = Path(__file__).resolve().parent.parent


def task(ident, owner='viewer', status='in_progress', **extra):
    return {'id': ident, 'title': f'Task {ident}', 'owner_id': owner, 'status': status, 'required': True,
            'start_date': '2020-01-01', 'due_date': '2020-02-01', 'original_due_date': '2020-02-01',
            'input_task_ids': [], 'comments': [], 'revision': 1, 'assignment_history': [], **extra}


def project(pid, name, tasks, **extra):
    node = {'id': f'{pid}-n', 'key': 'field', 'name': f'Node of {pid}', 'status': 'in_progress', 'owner_id': 'viewer',
            'reviewers': [], 'review_mode': 'all', 'requirements': [], 'tasks': tasks, 'review_cycles': []}
    return {'id': pid, 'code': f'C-{pid}', 'name': name, 'execution_system': 'workbench', 'nodes': [node],
            'evidence': [], 'files': [], 'finance_versions': [], 'payment_batches': [], 'case_visibility': 'new_case', **extra}


def workspace(*projects, environment='test'):
    users = [{'id': i, 'name': f'Person {i}', 'active': True} for i in ('viewer', 'other')]
    return {'environment': environment, 'as_of': '2026-10-14', 'users': users, 'projects': list(projects), 'delegations': [],
            'approved_leave_delegations': [], 'handover_requests': [], 'approvals': [], 'contract_items': [], 'jobs': []}


def run(ws, read=READY, viewer='viewer'):
    return build_my_work_input(ws, next(u for u in ws['users'] if u['id'] == viewer), read)


def ids(out):
    return [r['id'] for r in out['rows']]


# ---- scope -----------------------------------------------------------------
def test_old_unfinished_task_is_visible_regardless_of_any_period():
    old = task('old', due_date='2019-01-01', start_date='2019-01-01')
    out = run(workspace(project('p1', 'Case One', [old, task('new', due_date='2026-10-15')])))
    assert ids(out) == ['new', 'old']
    assert out['readState'] == 'ready'
    assert 'weeklyActivity' not in out and 'period' not in json.dumps(out)


def test_ended_tasks_are_excluded_and_unknown_status_is_not_ended():
    ws = workspace(project('p1', 'Case One', [task(s, status=s) for s in ('completed', 'superseded', 'cancelled', 'skipped')]
                           + [task('open'), task('weird', status='mystery'), task('nostatus', status=None)]))
    out = run(ws)
    assert ids(out) == ['nostatus', 'open', 'weird']
    by = {r['id']: r for r in out['rows']}
    assert by['open']['ended'] is False
    assert 'ended' not in by['weird'] and 'ended' not in by['nostatus']  # unknown stays unknown
    assert by['weird']['workflow_state'] == 'mystery' and 'workflow_state' not in by['nostatus']


def test_evidence_and_output_existence_never_ends_a_task():
    p = project('p1', 'Case One', [task('t', output='done')])
    p['evidence'] = [{'id': 'e1', 'node_id': 'p1-n', 'key': 'report', 'task_id': 't', 'name': 'Report'}]
    out = run(workspace(p))
    assert ids(out) == ['t'] and out['rows'][0]['ended'] is False
    assert 'evidence' not in out['rows'][0]


def test_restricted_task_of_another_person_is_absent_and_not_counted():
    secret = task('secret-id', owner='other', title='Secret title')
    out = run(workspace(project('p1', 'Case One', [task('mine'), secret])))
    blob = json.dumps(out, ensure_ascii=False)
    assert ids(out) == ['mine']
    assert 'secret' not in blob.lower() and 'Secret title' not in blob
    assert out['readState'] == 'ready'  # no count or partial hint that another task exists


def test_hidden_case_tasks_vanish_entirely_in_production():
    hidden = project('hid', 'Hidden Case', [task('hid-t')], case_visibility='excluded_history')
    shown = project('p1', 'Case One', [task('mine')])
    out = run(workspace(hidden, shown, environment='production'))
    blob = json.dumps(out)
    assert ids(out) == ['mine'] and 'hid-t' not in blob and 'Hidden Case' not in blob and 'forbidden' not in blob


# ---- parent / titles / due ---------------------------------------------------
def test_native_task_parent_is_verified_and_only_case_title_is_emitted():
    row = run(workspace(project('p1', 'Case One', [task('t')])))['rows'][0]
    assert row['parent'] == {'verified': True, 'case_title': 'Case One'}
    assert row['case_title'] == 'Case One' and 'work_item_title' not in row  # row title only from a verified parent


def test_unverified_parent_is_false_with_unknown_titles_even_when_names_match():
    imported = task('imp', title='Case One', source_identity={'base_token': 'b', 'table_id': 't', 'record_id': 'r'})
    ws = workspace(project('p1', 'Case One', [imported], code='Case One'))
    ws['contract_items'] = [{'id': 'c', 'task_refs': [{'project_id': 'p1', 'node_id': 'p1-n', 'task_id': 'imp-OTHER'},
                                                      {'project_id': 'other', 'node_id': 'p1-n', 'task_id': 'imp'}]}]
    row = run(ws)['rows'][0]
    assert row['parent'] == {'verified': False}
    assert 'case_title' not in row and 'entry_points' not in row  # unverified: no row level title either
    ws['contract_items'][0]['task_refs'].append({'project_id': 'p1', 'node_id': 'p1-n', 'task_id': 'imp'})
    assert run(ws)['rows'][0]['parent'] == {'verified': True, 'case_title': 'Case One'}
    assert run(ws)['rows'][0]['case_title'] == 'Case One'


def test_estimated_pending_requested_dates_never_become_effective():
    t = task('t', estimated_due_date='2026-12-01', pending_due_date='2026-11-01', requested_due_date='2026-10-30')
    row = run(workspace(project('p1', 'Case One', [t])))['rows'][0]
    assert row['effective_due'] == {'verified_formal': False}
    assert not any(d in json.dumps(row) for d in ('2026-12-01', '2026-11-01', '2026-10-30', '2020-02-01'))


def test_formal_due_requires_a_proven_field_and_never_an_estimated_one(monkeypatch):
    t = task('t', estimated_due_date='2026-12-01', formal_due='2026-11-11')
    ws = workspace(project('p1', 'Case One', [t]))
    monkeypatch.setattr(my_work, 'FORMAL_DUE_FIELDS', ('formal_due',))
    assert run(ws)['rows'][0]['effective_due'] == {'value': '2026-11-11', 'verified_formal': True}
    del t['formal_due']
    assert run(ws)['rows'][0]['effective_due'] == {'verified_formal': False}


# ---- read states -------------------------------------------------------------
def test_unassigned_empty_forbidden_not_loaded_failed_stale_are_distinct():
    unassigned = run(workspace(project('p1', 'Case One', [task('x', owner='other')])))
    empty = run(workspace(project('p1', 'Case One', [task('done', status='completed')])))
    assert unassigned == {'rows': [], 'readState': 'ready', 'assignment': 'unassigned', 'canSeeAwaitingConfirmation': False}
    assert empty['assignment'] == 'assigned' and empty['rows'] == [] and empty['readState'] == 'ready'
    ws = workspace(project('p1', 'Case One', [task('t')]))
    states = {
        'not_loaded': run(ws, None)['readState'], 'not_loaded2': run(ws, {'loaded': False, 'admitted': True})['readState'],
        'forbidden': run(ws, {'loaded': True, 'admitted': False})['readState'],
        'unknown_access': run(ws, {'loaded': True})['readState'],
        'failed': run(ws, {**READY, 'failed': True})['readState'],
        'unlocated': run(ws, {**READY, 'unlocated': True})['readState'],
    }
    assert states['not_loaded'] == states['not_loaded2'] == {'states': ['loading'], 'count': None}
    assert states['forbidden'] == {'states': ['forbidden']}
    assert states['unknown_access'] == {'states': ['unknown'], 'count': None}
    assert states['failed'] == {'states': ['read_failed'], 'count': None}
    assert states['unlocated'] == {'states': ['unlocated'], 'count': None}
    for read in (None, {'loaded': True, 'admitted': False}, {**READY, 'failed': True}):
        out = run(ws, read)
        assert out['rows'] == [] and out['assignment'] == 'unknown' and out['canSeeAwaitingConfirmation'] is False


def test_partial_and_stale_flags_are_independent_and_partial_never_claims_unassigned():
    ws = workspace(project('p1', 'Case One', [task('t')]))
    assert run(ws, {**READY, 'stale': True})['readState'] == {'states': ['stale'], 'count': 1}
    ws['_partial'] = {'collections': []}
    assert run(ws)['readState'] == {'states': ['partial'], 'count': None}
    assert run(ws, {**READY, 'stale': True})['readState'] == {'states': ['partial', 'stale'], 'count': None}
    empty = workspace(project('p1', 'Case One', [task('x', owner='other')]))
    empty['_partial'] = {}
    assert run(empty)['assignment'] == 'unknown'
    broken = workspace(project('p1', 'Case One', [task('t'), {'title': 'no id', 'owner_id': 'viewer'}]))  # could be the viewer's own work
    out = run(broken)
    assert ids(out) == ['t'] and out['readState'] == {'states': ['partial'], 'count': None}


def test_inactive_or_missing_viewer_is_unknown_not_unassigned():
    ws = workspace(project('p1', 'Case One', [task('t')]))
    ws['users'][0]['active'] = False
    assert run(ws)['assignment'] == 'unknown' and run(ws)['rows'] == []
    assert build_my_work_input(ws, {'id': 'ghost'}, READY)['readState'] == {'states': ['unknown'], 'count': None}


# ---- awaiting confirmation and entry points -------------------------------------
def with_review(ws):
    p, = ws['projects']
    node = p['nodes'][0]
    node['review_cycles'] = [{'id': 'cy', 'status': 'pending', 'mode': 'all', 'content_hash': review_hash(p, node),
                              'seats': {'owner': 'viewer'}, 'votes': []}]
    return ws


def test_awaiting_flag_false_without_existing_authorization():
    out = run(workspace(project('p1', 'Case One', [task('t')])))
    assert out['canSeeAwaitingConfirmation'] is False
    assert not [r for r in out['rows'] if r.get('queue')]


def test_awaiting_flag_follows_existing_review_authorization_and_is_not_approved():
    ws = with_review(workspace(project('p1', 'Case One', [task('t')])))
    out = run(ws)
    assert out['canSeeAwaitingConfirmation'] is True
    awaiting = [r for r in out['rows'] if r.get('queue') == 'awaiting_my_confirmation']
    assert len(awaiting) == 1 and awaiting[0]['ended'] is False
    assert awaiting[0]['entry_points'][0]['kind'] == 'confirmation'
    # someone else is the seat: the viewer is not authorized, so the flag falls back to false
    ws['projects'][0]['nodes'][0]['review_cycles'][0]['seats'] = {'owner': 'other'}
    assert run(ws)['canSeeAwaitingConfirmation'] is False


def test_no_complete_or_approve_entry_points_and_routes_are_existing_same_origin():
    out = run(with_review(workspace(project('p1', 'Case One', [task('t')]))))
    kinds = {e['kind'] for r in out['rows'] for e in r.get('entry_points', [])}
    assert kinds <= {'task', 'case', 'delivery', 'confirmation'}
    for r in out['rows']:
        for e in r.get('entry_points', []):
            assert e['route'].startswith('/#view=project&project=p1') and '//' not in e['route']
            assert not any(w in json.dumps(e).lower() for w in ('complete', 'approve', 'api/'))
            assert e['exists'] is True and isinstance(e['authorized'], bool)


def test_delivery_entry_is_unauthorized_when_existing_check_does_not_allow_it():
    paused = project('p1', 'Case One', [task('t')], execution_status='paused')
    row = run(workspace(paused))['rows'][0]
    delivery = next(e for e in row['entry_points'] if e['kind'] == 'delivery')
    assert delivery['authorized'] is False


def test_unknown_operation_outcome_is_preserved_never_none():
    ws = workspace(project('p1', 'Case One', [task('t'), task('u')]))
    ws['jobs'] = [{'id': 'j', 'kind': 'delivery', 'status': 'outcome_unknown', 'payload': {'project_id': 'p1', 'task_id': 't'}}]
    by = {r['id']: r for r in run(ws)['rows']}
    assert by['t']['operation_outcome'] == 'unknown' and 'operation_outcome' not in by['u']


def test_function_is_read_only():
    ws = with_review(workspace(project('p1', 'Case One', [task('t')])))
    before = deepcopy(ws)
    run(ws)
    assert ws == before


# ---- view-model round trip -------------------------------------------------------
NODE = shutil.which('node')


@pytest.mark.skipif(NODE is None, reason='node not installed: view-model parse check not run')
def test_output_parses_through_build_my_work_view(tmp_path):
    ws = with_review(workspace(project('p1', 'Case One', [task('old', due_date='2019-01-01'), task('done', status='completed'),
                                                          task('theirs', owner='other')])))
    payload = {'ready': run(ws), 'unassigned': run(workspace(project('p1', 'C', [task('x', owner='other')]))),
               'forbidden': run(ws, {'loaded': True, 'admitted': False}), 'loading': run(ws, None)}
    src = tmp_path / 'in.json'
    src.write_text(json.dumps(payload))
    script = tmp_path / 'check.mjs'
    script.write_text(
        "import {readFileSync} from 'node:fs';\n"
        f"const {{buildMyWorkView}}=await import({json.dumps((ROOT / 'frontend/src/myWorkView.ts').as_uri())});\n"
        "const d=JSON.parse(readFileSync(process.argv[2],'utf8'));const o={};\n"
        "for(const [k,v] of Object.entries(d)) o[k]=buildMyWorkView(v);\n"
        "const w=buildMyWorkView({...d.ready,canSeeAwaitingConfirmation:true,filters:{mode:'awaiting_my_confirmation'}});\n"
        "const sr=buildMyWorkView({...d.ready,filters:{search:'Case One'}});\n"
        "console.log(JSON.stringify({views:o,awaiting:w.rows.map(r=>r.id),search:sr.rows.map(r=>r.id)}));\n")
    done = subprocess.run([NODE, '--experimental-strip-types', str(script), str(src)], capture_output=True, text=True, cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    got = json.loads(done.stdout)
    ready = got['views']['ready']
    assert [r['id'] for r in ready['rows']] == ['old'] and ready['rows'][0]['dueLabel'] == 'unknown'
    assert ready['rows'][0]['caseTitle'] == 'Case One'  # verified parent supplies the row title
    assert got['search'] == ['old']
    assert ready['drawer']['task'] is None
    assert ready['pageState'] is None and got['awaiting'] == ['review:cy:owner']
    assert got['views']['unassigned']['emptyReason'] == 'unassigned'
    assert got['views']['forbidden']['pageState'] == {'states': ['forbidden']} and got['views']['forbidden']['rows'] == []
    assert got['views']['loading']['pageState']['states'] == ['loading']


# ---- correction round 1 (Codex review task_ef2cc07991fb) ---------------------------
def test_f1_restricted_task_cannot_change_page_flags_or_assignment():
    baseline = workspace(project('p', 'Visible', []))
    with_other = deepcopy(baseline)
    with_other['projects'][0]['nodes'][0]['tasks'].append(task('restricted', owner='other', input_task_ids=None))
    assert run(with_other) == run(baseline)


@pytest.mark.parametrize('bad', [
    {'owner': 'other', 'input_task_ids': None}, {'owner': 'other', 'title': ['x'], 'revision': 'bad'},
    {'owner': 'ghost-not-a-user', 'input_task_ids': 7}, {'owner': None, 'input_task_ids': None},
    {'owner': 'other', 'id': None}, {'owner': 'other', 'id': ''}])
def test_f1_malformed_excluded_tasks_never_change_whole_output(bad):
    for mine in ([], [task('mine')]):
        baseline = workspace(project('p', 'Visible', mine))
        polluted = deepcopy(baseline)
        extra = task('restricted', **{k: v for k, v in bad.items() if k != 'id'})
        if 'id' in bad: extra['id'] = bad['id']
        polluted['projects'][0]['nodes'][0]['tasks'].append(extra)
        assert run(polluted) == run(baseline)


def test_f1_malformed_task_that_could_be_the_viewers_still_makes_the_page_partial():
    out = run(workspace(project('p', 'Visible', [task('mine'), task('broken', owner='viewer', input_task_ids=None)])))
    assert ids(out) == ['mine'] and out['readState'] == {'states': ['partial'], 'count': None}
    unassigned = run(workspace(project('p', 'Visible', [task('broken', owner='viewer', input_task_ids=None)])))
    assert unassigned['assignment'] == 'unknown'


def test_f2_hidden_case_code_is_redacted_from_all_five_holders_in_production():
    hidden = project('hidden', 'Hidden', [], code='C-RESTRICTED', case_visibility='excluded_history')
    visible = project('p', 'C-RESTRICTED', [task('mine', title='C-RESTRICTED', input='C-RESTRICTED', output='C-RESTRICTED')], code='C-VISIBLE')
    visible['events'] = [{'id': 'ev', 'task_id': 'mine', 'action': 'task_pause', 'message': 'C-RESTRICTED'}]
    ws = workspace(visible, hidden, environment='production')
    out = run(ws)
    assert 'C-RESTRICTED' not in json.dumps(out, ensure_ascii=False)
    assert ids(out) == ['mine']
    assert 'C-RESTRICTED' in json.dumps(ws['projects'][0]['name'])  # input workspace is not mutated


def test_f2_test_and_demo_environments_are_not_redacted():
    hidden = project('hidden', 'Hidden', [], code='C-RESTRICTED', case_visibility='excluded_history')
    visible = project('p', 'Visible', [task('mine', title='C-RESTRICTED')], code='C-VISIBLE')
    assert run(workspace(visible, hidden, environment='test'))['rows'][0]['title'] == 'C-RESTRICTED'


def test_f3_verified_case_title_is_row_level_and_absent_when_unverified():
    row = run(workspace(project('p', 'Visible case', [task('mine')])))['rows'][0]
    assert row['case_title'] == 'Visible case' and row['parent']['case_title'] == 'Visible case'


def test_f4_explicit_terminal_outcomes_take_precedence_over_loading():
    ws = workspace()
    cases = [({'loaded': False, 'admitted': True, 'failed': True}, 'read_failed'),
             ({'loaded': False, 'admitted': True, 'unlocated': True}, 'unlocated'),
             ({'loaded': False, 'admitted': False}, 'forbidden'),
             ({'loaded': False, 'admitted': False, 'failed': True}, 'forbidden'),
             ({'loaded': False, 'admitted': True, 'failed': True, 'unlocated': True}, 'read_failed'),
             ({'loaded': False, 'admitted': True}, 'loading'), ({'loaded': True}, 'unknown')]
    for read, state in cases:
        assert run(ws, read)['readState']['states'] == [state], read
    assert run(ws, {'loaded': False, 'admitted': True, 'failed': True})['readState'] == {'states': ['read_failed'], 'count': None}


# ---- malformed records of other people: projection boundary (R1) ------------
def _with_other(base, **extra):
    ws = deepcopy(base)
    ws['projects'][0]['nodes'][0]['tasks'].append(task(extra.pop('ident', 'other'), owner=extra.pop('owner', 'other'), **extra))
    return ws


@pytest.mark.parametrize('personal', [True, False])
@pytest.mark.parametrize('bad', [{'ident': []}, {'ident': {}}, {'ident': None}, {'ident': ''}, {'status': []}, {'status': {}},
                                 {'owner': []}, {'status': 5}])
def test_known_other_malformed_record_changes_nothing(personal, bad):
    base = workspace(project('p', 'Visible', [task('mine')] if personal else []))
    assert run(_with_other(base, **bad)) == run(base)


def test_known_other_malformed_record_in_a_second_node_and_project_changes_nothing():
    base = workspace(project('p', 'Visible', [task('mine')]), project('q', 'Other case', []))
    ws = deepcopy(base)
    ws['projects'][1]['nodes'][0]['tasks'] += [task([], owner='other'), task('x', owner='other', status=[])]
    assert run(ws) == run(base)


def test_prerequisite_on_malformed_other_record_stays_visible_and_blocked():
    base = workspace(project('p', 'Visible', [task('up', owner='other', status='completed', output='done'),
                                              task('mine', status='pending', input_task_ids=['up'])]))
    ws = deepcopy(base)
    ws['projects'][0]['nodes'][0]['tasks'][0]['status'] = []  # the upstream record is now malformed
    missing = deepcopy(base)
    del missing['projects'][0]['nodes'][0]['tasks'][0]  # same as an unresolvable prerequisite: blocked, never satisfied
    out = run(ws)
    assert out == run(missing)
    row = out['rows'][0]
    assert out['readState'] == 'ready' and out['assignment'] == 'assigned'
    assert row['id'] == 'mine' and row['workflow_state'] == 'pending' and row['ended'] is False


def test_well_formed_prerequisite_still_authoritative():
    ws = workspace(project('p', 'Visible', [task('up', owner='other', status='completed', output='done'),
                                            task('mine', status='pending', input_task_ids=['up'])]))
    ws2 = deepcopy(ws); ws2['projects'][0]['nodes'][0]['tasks'][0]['output'] = ''
    assert ids(run(ws)) == ['mine'] and ids(run(ws2)) == ['mine']


@pytest.mark.parametrize('bad', [{'ident': []}, {'status': []}])
def test_viewer_owned_malformed_record_makes_page_partial(bad):
    base = workspace(project('p', 'Visible', [task('mine')]))
    out = run(_with_other(base, owner='viewer', **bad))
    assert out['readState']['states'] == ['partial'] and out['readState']['count'] is None


# ---- redaction environment default (R2) ------------------------------------
def _secret(env='production'):
    hidden = project('hidden', 'Hidden', [], code='C-RESTRICTED', case_visibility='excluded_history')
    visible = project('p', 'C-RESTRICTED', [task('mine', title='C-RESTRICTED', input='C-RESTRICTED', output='C-RESTRICTED', status='paused')],
                      code='C-VISIBLE')
    ws = workspace(visible, hidden, environment=env)
    ws['events'] = [{'id': 'ev', 'action': 'task_pause_for_change', 'project_id': 'p', 'node_id': 'p-n', 'task_id': 'mine',
                     'message': 'C-RESTRICTED', 'created_at': '2026-10-14'}]
    return ws


def test_hidden_demo_project_does_not_disable_production_redaction_default():
    ws = _secret(None); ws.pop('environment')
    baseline = run(ws)
    assert 'C-RESTRICTED' not in json.dumps(baseline)
    ws['projects'][1]['source_kind'] = 'demo'
    assert run(ws) == baseline


def test_visible_demo_project_default_stays_unredacted_and_explicit_environments_hold():
    ws = _secret(None); ws.pop('environment'); ws['projects'][0]['source_kind'] = 'demo'
    assert 'C-RESTRICTED' in json.dumps(run(ws))
    for env, leaks in (('test', True), ('demo', True), ('production', False)):
        ws = _secret(env); ws['projects'][1]['source_kind'] = 'demo'
        assert ('C-RESTRICTED' in json.dumps(run(ws))) is leaks
