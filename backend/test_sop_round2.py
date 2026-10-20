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
