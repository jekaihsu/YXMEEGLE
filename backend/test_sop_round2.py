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
