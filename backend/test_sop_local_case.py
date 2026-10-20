"""Local planning quote creation through the real app over a synthetic production workspace; never Lark."""
import re
from copy import deepcopy

import httpx
import pytest
from sqlalchemy import func, select

from . import storage
from .app import BusinessRow, WorkspaceRow
from .case_cutover import execution_allowed
from .sop_import.models import CaseState, Family, LocalCaseRun, LocalTask, Preview
from .sop_import.quote_facts import ENGINEERING_NO
from .sop_import.local_case import OFFICIAL_NUMBER
from .test_sop_quotes import WID, harness, quote_row

CREATOR = ['create_local_case', 'sop_task_import', 'sop_task_read']
CAPS = {'u-field': CREATOR, 'u-pm': ['sop_task_read'], 'u-control': ['sop_task_read', 'sop_task_import'],
        'u-manager': ['sop_task_read'], 'u-report': ['create_local_case']}


@pytest.fixture
def local(tmp_path, monkeypatch):
    def no_outbound(*args, **kwargs):
        raise AssertionError('outbound network is forbidden')
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', no_outbound)
    app, client, signin, ids = harness(tmp_path, CAPS, LOCAL_CASE_CREATION_ENABLED='true',
                                       INDEX_TABLES_ENABLED='true', WORKSPACE_SHELL_ENABLED='true')
    signin('u-field')
    yield app, client, signin, ids
    app.state.engine.dispose()


def call(client, method, path, body=None, status=200):
    response = client.request(method, path, json=body)
    assert response.status_code == status, response.text
    return response.json()


def create(client, form, rid='r1', status=200):
    draft = call(client, 'POST', '/api/quotes/preview', form)
    return draft, call(client, 'POST', '/api/quotes', {'draft_id': draft['draft_id'], 'request_id': rid}, status)


def persisted(app):
    with app.state.sessions() as db:
        state = storage.load(db, BusinessRow, db.get(WorkspaceRow, WID))
        version = db.get(WorkspaceRow, WID).version
        counts = [db.scalar(select(func.count()).select_from(model)) for model in (LocalCaseRun, CaseState, LocalTask)]
    return [p for p in state['projects'] if p.get('planning_origin') == 'local'], version, counts


FORM = {'name': '新竹科學園區地形測量', 'pm_id': 'u-pm', 'client': '竹科管理局', 'description': '初步詢價'}


def test_create_with_default_sop_is_one_atomic_case_with_nine_empty_nodes(local):
    app, client, signin, ids = local
    draft, receipt = create(client, FORM)
    pid = draft['case']['project_id']
    assert draft['import']['selection']['node_keys'] == ['sales', 'pm', 'confirmation', 'field', 'control', 'mapping',
                                                         'report', 'pricing', 'settlement']
    assert (draft['import']['counts']['new_tasks'], draft['import']['start_node'], draft['import']['stage']) == (38, 'sales', 'inquiry')
    assert draft['case']['nodes'][0] == {'node_key': 'sales', 'node_id': f'{pid}-sales'}
    reference = receipt['local_reference']
    assert reference == 'LOCAL-' + pid[:8].upper()
    assert not OFFICIAL_NUMBER.fullmatch(reference) and not ENGINEERING_NO.match(reference)
    assert {k: receipt[k] for k in ('project_id', 'official_quote_no', 'name', 'client', 'pm_id', 'planning_origin',
                                    'case_type', 'replayed')} == {
        'project_id': pid, 'official_quote_no': None, 'name': '新竹科學園區地形測量', 'client': '竹科管理局', 'pm_id': 'u-pm',
        'planning_origin': 'local', 'case_type': 'intake', 'replayed': False}
    assert len(receipt['import']['created_task_ids']) == 38
    [case], _, counts = persisted(app)
    assert (case['id'], case['created_by'], case['case_visibility'], case['execution_system']) == (
        pid, 'u-field', 'local_planning', 'pending')
    assert [(n['key'], n['id'], n['tasks']) for n in case['nodes']][:2] == [('sales', f'{pid}-sales', []), ('pm', f'{pid}-pm', [])]
    assert len(case['nodes']) == 9 and all(n['tasks'] == [] for n in case['nodes'])
    assert counts == [1, 1, 38]
    listing = call(client, 'GET', f'/api/projects/{pid}/sop-tasks')
    assert (len(listing['tasks']), listing['start_node'], listing['stage']) == (38, 'sales', 'inquiry')
    with app.state.sessions() as db:
        assert db.get(Preview, (WID, draft['draft_id'])) is None
    assert execution_allowed({'environment': 'test'}, case) is False


def test_retry_replays_the_same_case_and_receipt(local):
    app, client, signin, ids = local
    draft, receipt = create(client, FORM)
    again = call(client, 'POST', '/api/quotes', {'draft_id': draft['draft_id'], 'request_id': 'r1'})
    assert again == {**receipt, 'replayed': True}
    assert call(client, 'GET', '/api/quotes/requests/r1') == receipt
    other = call(client, 'POST', '/api/quotes/preview', FORM)
    assert call(client, 'POST', '/api/quotes', {'draft_id': other['draft_id'], 'request_id': 'r1'}, 409)['code'] == 'idempotency_mismatch'
    assert call(client, 'POST', '/api/quotes', {'draft_id': draft['draft_id'], 'request_id': 'r2'}, 404)['code'] == 'preview_not_found'
    cases, _, counts = persisted(app)
    assert ([c['id'] for c in cases], counts) == ([receipt['project_id']], [1, 1, 38])


def test_create_without_tasks(local):
    app, client, signin, ids = local
    draft, receipt = create(client, {**FORM, 'import_tasks': False})
    assert (draft['import'], receipt['import']) == (None, None)
    assert call(client, 'GET', f"/api/projects/{receipt['project_id']}/sop-tasks")['tasks'] == []
    assert persisted(app)[2] == [1, 0, 0]


def test_any_failure_rolls_back_case_tasks_and_receipt(local):
    app, client, signin, ids = local
    before = persisted(app)
    draft = call(client, 'POST', '/api/quotes/preview', FORM)
    with app.state.sessions.begin() as db:
        for family in db.scalars(select(Family)):
            family.lifecycle = 'retired'
    failed = call(client, 'POST', '/api/quotes', {'draft_id': draft['draft_id'], 'request_id': 'r1'}, 409)
    assert failed['code'] == 'template_unavailable'
    assert persisted(app) == before
    numbered = call(client, 'POST', '/api/quotes/preview', {**FORM, 'import_tasks': False, 'official_quote_no': '115950'})
    with app.state.sessions.begin() as db:
        workspace = db.get(WorkspaceRow, WID)
        state = storage.load(db, BusinessRow, workspace)
        state['source_quotes'].append(quote_row('recRace', '115950', ids['formal']))
        workspace.data = storage.save(db, BusinessRow, WID, state)
    raced = persisted(app)
    assert call(client, 'POST', '/api/quotes', {'draft_id': numbered['draft_id'], 'request_id': 'r2'}, 409)['code'] == 'quote_number_taken'
    assert persisted(app) == raced


def test_official_number_is_a_checked_display_field(local):
    app, client, signin, ids = local
    for value, code in (('C115950', 'quote_number_invalid'), ('11595', 'quote_number_invalid'), ('115236', 'quote_number_taken'),
                        ('115600', 'quote_number_taken')):
        status = 409 if code == 'quote_number_taken' else 422
        assert call(client, 'POST', '/api/quotes/preview', {**FORM, 'official_quote_no': value}, status)['code'] == code
    draft, receipt = create(client, {**FORM, 'official_quote_no': '115950-01A', 'import_tasks': False})
    assert (receipt['official_quote_no'], receipt['local_reference'].startswith('LOCAL-')) == ('115950-01A', True)
    entry = call(client, 'GET', '/api/quotes?q=115950')['items']
    assert [(e['origin'], e['quote_no'], e['local_reference'], e['stage'], e['project_id']) for e in entry] == [
        ('local', '115950-01A', receipt['local_reference'], 'inquiry', receipt['project_id'])]
    assert call(client, 'POST', '/api/quotes/preview', {**FORM, 'official_quote_no': '115950-01A'}, 409)['code'] == 'quote_number_taken'


def test_form_needs_a_name_and_an_explicit_pm_choice(local):
    app, client, signin, ids = local
    assert call(client, 'POST', '/api/quotes/preview', {'name': 'x'}, 422)['code'] == 'invalid_request'
    assert call(client, 'POST', '/api/quotes/preview', {**FORM, 'name': ' '}, 422)['code'] == 'invalid_request'
    assert call(client, 'POST', '/api/quotes/preview', {**FORM, 'pm_id': 'u-control'}, 422)['code'] == 'pm_unresolved'
    draft, receipt = create(client, {**FORM, 'pm_id': None, 'import_tasks': False})
    assert receipt['pm_id'] == ''


def test_capability_flag_and_import_grant_gate_creation(local):
    app, client, signin, ids = local
    signin('u-pm')
    assert call(client, 'POST', '/api/quotes/preview', FORM, 403)['code'] == 'local_case_forbidden'
    signin('u-report')
    assert call(client, 'POST', '/api/quotes/preview', FORM, 403)['code'] == 'sop_import_forbidden'
    assert call(client, 'POST', '/api/quotes/preview', {**FORM, 'import_tasks': False})['import'] is None
    app.state.sop_import.local_cases_enabled = lambda: False
    assert call(client, 'POST', '/api/quotes/preview', FORM, 503)['code'] == 'local_case_unavailable'
    assert call(client, 'GET', '/api/quotes')['total'] == 2


def test_only_creator_pm_and_managers_see_it_and_official_totals_ignore_it(local):
    app, client, signin, ids = local
    signin('u-manager')
    totals = call(client, 'GET', '/api/company-dashboard')['totals']
    projects = call(client, 'GET', '/api/projects')['total']
    overview = call(client, 'GET', '/api/projects?view=overview&tab=all')
    signin('u-field')
    draft, receipt = create(client, FORM)
    pid = receipt['project_id']
    for who, visible in (('u-field', True), ('u-pm', True), ('u-manager', True), ('u-control', False)):
        signin(who)
        shown = [e['project_id'] for e in call(client, 'GET', '/api/quotes')['items'] if e['origin'] == 'local']
        assert shown == ([pid] if visible else []), who
        assert client.get(f'/api/projects/{pid}/sop-tasks').status_code == (200 if visible else 404), who
        assert client.get(f"/api/quotes/{receipt['local_reference']}").status_code == (200 if visible else 404), who
    signin('u-control')
    assert call(client, 'GET', '/api/quotes/requests/r1', status=404)['code'] == 'run_not_found'
    signin('u-manager')
    assert call(client, 'GET', '/api/company-dashboard')['totals'] == totals
    assert call(client, 'GET', '/api/projects')['total'] == projects
    after = call(client, 'GET', '/api/projects?view=overview&tab=all')
    assert (after['total'], [p['id'] for p in after['items']]) == (overview['total'], [p['id'] for p in overview['items']])
    workspace = client.get('/api/workspace')
    assert workspace.status_code == 200 and pid not in workspace.text
    assert client.get(f'/api/projects/{pid}').status_code == 404
    assert re.search('LOCAL-', client.get('/api/manager-overview').text) is None


def test_source_refresh_never_adopts_a_local_case():
    from .policy import upgrade
    from .seed import seed
    from .sop_import import local_case
    from .v4_sources import import_v4
    state = upgrade(seed(True))
    form = {'name': 'x', 'client': '', 'description': '', 'pm_id': '', 'official_quote_no': '115950'}
    project = local_case.project('a' * 32, form, 'u-field', local_case.published_template(state), '2026-10-20')
    state['projects'].append(project)
    before = deepcopy(project)
    import_v4(state, [{'kind': 'quote', 'base_token': 'b', 'table_id': 't', 'record_id': 'recLater',
                       'fields': {'報價編號': '115950', '工程編號': 'LOCAL-AAAAAAAA', '工程名稱': 'typed later', '此案確認單': []}}])
    local, intake = state['projects']
    assert {k: local[k] for k in before if k != 'nodes'} == {k: v for k, v in before.items() if k != 'nodes'}
    assert [(n['id'], n['tasks']) for n in local['nodes']] == [(n['id'], []) for n in before['nodes']]
    assert 'source_identity' not in local
    assert (intake['case_type'], intake['code'], intake['id'] != project['id']) == ('intake', '115950', True)

@pytest.mark.parametrize('enabled', ['true', 'false'])
def test_session_exposes_local_planning_write_flags(tmp_path, enabled):
    app, client, _, _ = harness(tmp_path, LOCAL_CASE_CREATION_ENABLED=enabled, SOP_TASK_WRITES_ENABLED=enabled)
    try:
        flags = call(client, 'GET', '/api/session')['features']
        assert flags['local_case_creation'] is (enabled == 'true')
        assert flags['sop_task_writes'] is (enabled == 'true')
    finally:
        app.state.engine.dispose()
