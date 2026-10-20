from types import SimpleNamespace

import pytest

from .sop_import.service import can_manage


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

from .sop_import import local_case
from .sop_import.domain import Failure
from .test_sop_local_case import local, call, FORM
from .test_sop_quotes import WID, quote_row
from .models import WorkspaceRow, BusinessRow
from . import storage


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

from .test_sop_import import h, intake, post, overview
from .test_sop_suggestions import case, set_quote, task, QUOTE_ROW


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

from sqlalchemy import select
from .sop_import.models import Preview
from .test_sop_import import preview


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
