from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select, func

from .models import BusinessRow
from .node_assignment.cache import StaleCache
from .sop_import.domain import Failure
from .sop_import.models import CasePolicy, LocalTask
from .test_sop_import import h, URL, post, overview  # noqa: F401
from .test_sop_node_authority import roster


def cold_roster(h, *, failing=False):
    h.service.roster_required = True
    calls = []

    def provider(fresh=False):
        if not fresh:
            return None
        calls.append(True)
        if failing:
            raise Failure('roster_unavailable', 503)
        return roster()

    h.service.roster_provider = provider
    return calls


def test_single_node_manager_page_actions_and_node_scope(h):
    h.service.roster_provider = lambda fresh=False: roster()
    h.who[0] = 'member'
    body = overview(h)
    assert all(body['allowed_actions'][key] for key in ('import', 'manage', 'decide_suggestions'))
    assert body['allowed_actions']['start_all_nodes'] is False
    assert body['managed_node_keys'] == ['pm', 'confirmation']
    post(h, URL + '/sop-tasks', {'title': 'PM', 'node_keys': ['pm']})
    post(h, URL + '/sop-tasks', {'title': 'control', 'node_keys': ['control']}, 403)
    h.who[0] = 'pm'
    assert overview(h)['allowed_actions']['start_all_nodes'] is True
    assert len(overview(h)['managed_node_keys']) == 9


def test_cold_write_node_manager_without_reader_grant(h):
    h.who[0] = 'member'
    h.users['member']['capabilities'] = []
    calls = cold_roster(h)
    post(h, URL + '/sop-tasks', {'title': 'PM', 'node_keys': ['pm']})
    assert calls == [True]


def test_roster_outage_reads_fall_back_and_negative_cache_expires(h):
    h.who[0] = 'other'
    h.users['other']['capabilities'] = ['sop_task_read']
    calls = cold_roster(h, failing=True)
    for _ in range(5):
        body = overview(h)
        assert body['allowed_actions']['manage'] is False
    assert calls == [True]
    post(h, URL + '/sop-tasks', {'title': 'PM', 'node_keys': ['pm']}, 503)
    assert calls == [True]
    h.service.clock = lambda: 1031
    overview(h)
    assert calls == [True, True]


def test_cold_write_failure_is_503_before_assigned_only_denial(h):
    h.who[0] = 'member'
    h.users['member']['capabilities'] = []
    calls = cold_roster(h, failing=True)
    body = post(h, URL + '/sop-tasks', {'title': 'PM', 'node_keys': ['pm']}, 503)
    assert body['code'] == 'roster_unavailable'
    assert calls == [True]


def test_participant_read_recovers_authority_but_executor_transition_needs_no_refresh(h):
    task = post(h, URL + '/sop-tasks', {'title': 'mine', 'node_keys': ['pm'],
                'participants': {'executor': 'member'}})['task']
    h.who[0] = 'member'
    h.users['member']['capabilities'] = []
    calls = cold_roster(h, failing=True)
    assert overview(h)['tasks'][0]['id'] == task['id']
    assert calls == [True], 'cold read checks whether the participant is also a node manager'
    post(h, URL + f"/sop-tasks/{task['id']}/transition", {'action': 'start', 'expected_revision': task['revision']})
    assert calls == [True], 'executor can still work during a roster outage without another refresh'


@pytest.mark.parametrize('actor', ['pm', 'expired'])
def test_global_or_unauthenticated_never_refresh(h, actor):
    calls = cold_roster(h, failing=True)
    h.who[0] = actor
    assert h.client.get(URL + '/sop-tasks').status_code == (200 if actor == 'pm' else 401)
    assert calls == []


def test_stale_roster_peek_serves_reads_within_stale_max():
    now = [0]
    cache = StaleCache(60, 900, lambda: now[0])
    cache.put('roster', roster())
    now[0] = 61
    assert cache.peek('roster') is None
    assert cache.peek('roster', allow_stale=True).value.person('member').rank == '經理'
    now[0] = 901
    assert cache.peek('roster', allow_stale=True) is None


def test_managed_case_with_all_nodes_blocked_is_not_started(h):
    with h.sessions.begin() as db:
        db.add(CasePolicy(workspace_id='w', project_id='p1', policy='managed', revision=1,
                          decided_by='pm', decided_at=100, reason='selected', facts={}, node_keys=['pm']))
        node = db.get(BusinessRow, ('w', 'nodes', 'real-p1-1'))
        node.data = {**node.data, 'status': 'in_progress'}
    assert h.client.post(URL + '/sop/ensure').json() == {'state': 'not_ready', 'reason': 'no_startable_nodes'}
    with h.sessions() as db:
        assert db.scalar(select(func.count()).select_from(LocalTask)) == 0


def test_cold_node_manager_transition_without_grants(h):
    task = post(h, URL + '/sop-tasks', {'title': 'PM', 'node_keys': ['pm']})['task']
    h.who[0] = 'member'
    h.users['member']['capabilities'] = []
    calls = cold_roster(h)
    post(h, URL + f"/sop-tasks/{task['id']}/transition", {'action': 'start', 'expected_revision': task['revision']})
    assert calls == [True]


def test_cold_participant_manager_can_create_in_their_node(h):
    post(h, URL + '/sop-tasks', {'title': 'mine', 'node_keys': ['pm'], 'participants': {'executor': 'member'}})
    h.who[0] = 'member'
    h.users['member']['capabilities'] = []
    calls = cold_roster(h)
    post(h, URL + '/sop-tasks', {'title': 'PM', 'node_keys': ['pm']})
    assert calls == [True]


def test_roster_outage_concurrent_reads_share_failure(h):
    h.who[0] = 'other'
    h.users['other']['capabilities'] = ['sop_task_read']
    calls = cold_roster(h, failing=True)
    with ThreadPoolExecutor(max_workers=5) as pool:
        codes = list(pool.map(lambda _: h.client.get(URL + '/sop-tasks').status_code, range(5)))
    assert codes == [200] * 5
    assert calls == [True]


def test_forced_participant_view_never_refresh(h):
    post(h, URL + '/sop-tasks', {'title': 'mine', 'node_keys': ['pm'], 'participants': {'executor': 'member'}})
    h.who[0] = 'member'
    calls = cold_roster(h, failing=True)
    with h.sessions.begin() as db:
        project = db.get(BusinessRow, ('w', 'projects', 'p1'))
        project.data = {**project.data, 'sop_assigned_only': True}
    assert overview(h)['tasks'][0]['title'] == 'mine'
    assert calls == []


def test_managed_node_selection_excludes_unenrolled_nodes(h):
    with h.sessions.begin() as db:
        db.add(CasePolicy(workspace_id='w', project_id='p1', policy='managed', revision=1,
                          decided_by='pm', decided_at=100, reason='selected', facts={}, node_keys=['pm']))
    h.who[0] = 'member'
    h.service.roster_provider = lambda fresh=False: roster()
    assert overview(h)['managed_node_keys'] == ['pm']
    post(h, URL + '/sop-import/preview', {'template_version_id': h.vid, 'node_keys': ['pm']})


@pytest.mark.parametrize('own_task,action', [(False, 'start'), (True, 'archive')])
def test_cold_participant_manager_retains_manager_transitions(h, own_task, action):
    mine = post(h, URL + '/sop-tasks', {'title': 'mine', 'node_keys': ['pm'],
                'participants': {'executor': 'member'}})['task']
    target = mine if own_task else post(h, URL + '/sop-tasks', {'title': 'other PM', 'node_keys': ['pm']})['task']
    h.who[0] = 'member'
    h.users['member']['capabilities'] = []
    calls = cold_roster(h)
    post(h, URL + f"/sop-tasks/{target['id']}/transition", {'action': action, 'expected_revision': target['revision'], 'reason': '核對'})
    assert calls == [True]
