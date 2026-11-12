"""Source recomputation evidence remains an operational server-side record."""
from copy import deepcopy
import pytest
from .seed import seed
from .workspace_projection import filter_private_workspace, public_copy

@pytest.mark.parametrize('actor_id', ['u-manager', 'u-control'])
def test_recomputation_explanations_do_not_escape_workspace_projection(actor_id):
    state = seed()
    state['contract_items'] = [{'id': 'synthetic-contract', 'history': [{
        'revision': 1, 'change_explanation': [{'field': 'fields.private',
        'before': 'PRIVATE_BEFORE', 'after': 'PRIVATE_AFTER'}],
        'snapshot': {'amount_reported': 10}}]}]
    original = deepcopy(state)
    result = filter_private_workspace(public_copy(state), {'id': actor_id})
    history = result['contract_items'][0]['history'][0]
    assert 'change_explanation' not in history
    assert history['snapshot']['amount_reported'] == 10
    assert state == original


def test_execution_blockers_are_separate_from_activation_and_do_not_change_authority():
    state = seed()
    task = state['projects'][0]['nodes'][0]['tasks'][0]
    task['status'] = 'in_progress'
    original = deepcopy(state)
    result = filter_private_workspace(public_copy(state), {'id': task['owner_id']})
    projected = result['projects'][0]['nodes'][0]['tasks'][0]
    assert projected['can_execute'] is True
    assert '任務不在待啟用狀態' in projected['activation_blockers']
    assert '任務不在待啟用狀態' not in projected['execution_blockers']
    assert state == original


def test_assignment_visibility_does_not_follow_manager_override_or_readiness():
    state = seed()
    task = state['projects'][0]['nodes'][0]['tasks'][0]
    task['status'] = 'paused'
    owner = task['owner_id']
    own = filter_private_workspace(public_copy(state), {'id': owner})
    assert own['projects'][0]['nodes'][0]['tasks'][0]['assigned_to_viewer'] is True
    assert own['projects'][0]['nodes'][0]['tasks'][0]['execution_blockers']
    manager = next(person for person in state['users'] if person['role'] == 'manager')
    assert manager['id'] != owner
    public = filter_private_workspace(public_copy(state), {'id': manager['id']})
    assert public['projects'][0]['nodes'][0]['tasks'][0]['assigned_to_viewer'] is False


@pytest.mark.parametrize('qualified,expected', [(True, True), (False, False)])
def test_proxy_assignment_requires_verified_delegation_even_while_paused(qualified, expected):
    from .workflow import now
    state = seed()
    project = state['projects'][0]
    task = project['nodes'][0]['tasks'][0]
    task['status'] = 'paused'
    delegate = next(person['id'] for person in state['users']
                    if person['id'] != task['owner_id'] and person.get('active', True))
    state['delegations'] = [dict(id='verified-proxy', project_id=project['id'],
        principal_id=task['owner_id'], delegate_id=delegate, seat='owner', scope='tasks',
        task_ids=[task['id']], status='active', start_date=now()[:10], end_date=now()[:10],
        qualified=qualified, qualification_evidence='synthetic-evidence', source='supervisor')]
    public = filter_private_workspace(public_copy(state), {'id': delegate})
    projected = public['projects'][0]['nodes'][0]['tasks'][0]
    assert projected['assigned_to_viewer'] is expected
    assert projected['execution_blockers']
