import asyncio
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from starlette.requests import Request

from . import storage
from .models import BusinessRow, PersonRow, WorkspaceRow
from .sop_import.case_stage import stage
from .sop_import.domain import Lifecycle
from .sop_import.models import LocalTask, Preview, TaskEvent
from .sop_import.quote_facts import collect
from .sop_import.routes import MAX_BODY
from .sop_import.service import can_manage
from .test_sop_import import apply, h, intake, overview, post, preview
from .test_sop_local_case import FORM, call, local
from .test_sop_quotes import WID, quote_row
from .test_sop_suggestions import QUOTE_ROW, case, set_quote, task


@pytest.mark.parametrize('origin', ['source', 'local'])
def test_assigned_intake_requires_pm_or_delegate(origin):
    user = {'id': 'creator', 'role': 'pm', 'capabilities': ['sop_task_import']}
    project = {'case_type': 'intake', 'planning_origin': origin, 'created_by': 'creator', 'pm_id': 'assigned'}
    ctx = SimpleNamespace(user=user, project=project)
    assert not can_manage(ctx)
    project['pm_id'] = None
    assert can_manage(ctx)
    project['pm_id'] = 'creator'
    assert can_manage(ctx)



@pytest.mark.parametrize('number,status,code', [('１１５２３６', 409, 'quote_number_taken'),
                                               ('١١٥٢٣٦', 422, 'quote_number_invalid'),
                                               ('115951A', 409, 'quote_number_taken')])
def test_normalized_official_number_uniqueness(local, number, status, code):
    app, client, _, ids = local
    with app.state.sessions.begin() as db:
        ws = db.get(WorkspaceRow, WID)
        state = storage.load(db, BusinessRow, ws)
        state['source_quotes'].append(quote_row('lower', '115951a', ids['formal']))
        ws.data = storage.save(db, BusinessRow, WID, state)
    assert call(client, 'POST', '/api/quotes/preview',
                {**FORM, 'import_tasks': False, 'official_quote_no': number}, status)['code'] == code



def test_dismissed_facts_cannot_be_accepted(case):
    h, url, project = case
    set_quote(h, project, **QUOTE_ROW)
    found = task(h, url, 1)
    body = {'facts_hash': found['suggestion']['facts_hash']}
    path = f"{url}/sop-tasks/{found['id']}/suggestion"
    post(h, path, {**body, 'action': 'dismiss_suggestion'})
    result = post(h, path, {**body, 'action': 'accept_suggestion', 'expected_revision': found['revision'],
                           'confirm': True, 'reason': 'checked'}, 409)
    assert result['code'] == 'suggestion_dismissed'
    assert task(h, url, 1)['state'] == 'pending'


def test_bulk_indicator_requires_explicit_ids(case):
    h, url, project = case
    set_quote(h, project, **QUOTE_ROW)
    tasks = [t for t in overview(h, url)['tasks'] if t['suggestion'] and t['suggestion']['tier'] == 'indicator']
    items = [{'task_id': t['id'], 'facts_hash': t['suggestion']['facts_hash'], 'expected_revision': t['revision']} for t in tasks]
    body = {'tasks': items, 'confirm': True, 'reason': 'checked'}
    path = url + '/sop-tasks/suggestions/accept'
    assert post(h, path, body, 422)['code'] == 'suggestion_confirmation_required'
    assert post(h, path, {**body, 'confirmed_task_ids': [tasks[0]['id']]}, 422)['code'] == 'suggestion_confirmation_required'
    result = post(h, path, {**body, 'confirmed_task_ids': [t['id'] for t in tasks]})
    assert len(result['results']) == len(tasks)



def test_preview_writes_expire_and_bound_actor_rows(h):
    h.service.preview_limit = 2
    first = preview(h)['preview_id']
    h.service.clock = lambda: 2000
    second = preview(h)['preview_id']
    with h.sessions() as db:
        assert db.get(Preview, ('w', first)) is None
    preview(h)
    preview(h)
    with h.sessions() as db:
        assert len(list(db.scalars(select(Preview)))) == 2



@pytest.mark.parametrize('declared', [True, False])
def test_oversized_body_stops_before_consuming_stream(h, declared):
    consumed = []
    async def receive():
        consumed.append(1)
        return {'type': 'http.request', 'body': b'x' * (MAX_BODY + 1), 'more_body': len(consumed) == 1}
    request = Request({'type': 'http', 'headers': [(b'content-length', b'1000000')] if declared else []}, receive)
    endpoint = next(r.endpoint for r in h.client.app.routes if r.path.endswith('/sop-import/preview'))
    response = asyncio.run(endpoint(request, 'p1'))
    assert response.status_code == 422
    assert len(consumed) == (0 if declared else 1)



@pytest.mark.parametrize('capability', ['create_local_case', 'sop_task_import'])
def test_local_create_rechecks_identity_under_lock(local, capability):
    app, client, _, _ = local
    draft = call(client, 'POST', '/api/quotes/preview', FORM)
    service = app.state.sop_import
    original = service.lock_workspace_row
    def revoke(db, wid):
        with app.state.sessions.begin() as other:
            person = other.get(PersonRow, (WID, 'u-field'))
            person.data = {**person.data, 'capabilities': [c for c in person.data['capabilities'] if c != capability]}
        return original(db, wid)
    service.lock_workspace_row = revoke
    result = call(client, 'POST', '/api/quotes', {'draft_id': draft['draft_id'], 'request_id': 'revoke'}, 403)
    assert result['code'] == ('local_case_forbidden' if capability == 'create_local_case' else 'sop_import_forbidden')



def test_blank_status_row_prevents_merged_cancellation():
    facts = collect([{'狀態 (1)': 'I'}, {'狀態 (1)': '', '報價日期': '2026-10-01'}], today=date(2026, 10, 20))
    assert facts.stage_label != 'I'
    assert stage(facts) == 'quoted'



def test_completed_shared_link_preview_includes_completion_history(h):
    apply(h, preview(h, node_keys=['control']))
    with h.sessions.begin() as db:
        target = db.scalar(select(LocalTask).where(LocalTask.source_row_key == 'meegle-v137:A:36'))
        target.state = Lifecycle.DONE
        target.local = {**target.local, 'evidence_basis': {'rule_id': 'reviewed', 'facts_hash': 'a' * 64},
                        'evidence_refs': ['evidence-123']}
        db.add(TaskEvent(workspace_id='w', id='completion', project_id='p1', task_id=target.id,
                         actor_id='pm', at=900, kind='suggestion_accepted', revision=2,
                         changes={'to_state': 'done', 'facts_hash': 'a' * 64}))
    plan = preview(h, node_keys=['mapping'])
    row = next(o for o in plan['outcomes'] if o['source_row_key'] == 'meegle-v137:A:36')
    assert row['outcome'] == 'link_addition'
    assert row['completion'] == {'state': 'done', 'actor_id': 'pm', 'actor_name': '林育寬', 'at': 900,
                                 'evidence_basis': {'rule_id': 'reviewed', 'facts_hash': 'a' * 64},
                                 'evidence_refs': ['evidence-123']}
