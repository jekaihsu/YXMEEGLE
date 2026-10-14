import pytest

from .node_assignment.domain import (
    Actor, Denied, IllegalTransition, NodeAction, NodeFacts, NodeKey, NodeStatus, Person,
    TaskFacts, TaskStatus, check_node_action, check_task_status, derive_chain, later_nodes_started,
    node_permissions, progress, summarize, task_counts, task_permissions)

T = TaskStatus
S = NodeStatus
K = NodeKey


def chain(**facts):
    return derive_chain({K(key): value for key, value in facts.items()})


def approved():
    return NodeFacts(approved=True)


def test_empty_case_starts_at_sales_and_everything_else_waits():
    statuses = chain()
    assert [statuses[k] for k in K] == [S.TODO] + [S.NOT_STARTED] * 8
    assert summarize(statuses).__dict__ == {'done': 0, 'total': 9, 'current_node': K.SALES}


def test_task_driven_statuses_follow_the_chain():
    statuses = chain(sales=approved(), pm=NodeFacts(tasks=(T.DONE, T.IN_PROGRESS)),
                     confirmation=NodeFacts(tasks=(T.DONE,)))
    assert statuses[K.SALES] is S.DONE
    assert statuses[K.PM] is S.IN_PROGRESS
    # Work on a node whose predecessor is unfinished does not start it.
    assert statuses[K.CONFIRMATION] is S.NOT_STARTED


def test_all_live_tasks_done_is_review_and_cancelled_tasks_do_not_count():
    statuses = chain(sales=NodeFacts(tasks=(T.DONE, T.CANCELLED, T.DONE)))
    assert statuses[K.SALES] is S.IN_REVIEW
    assert task_counts((T.DONE, T.CANCELLED, T.DONE, T.TODO)).__dict__ == {'done': 2, 'total': 3}


def test_only_cancelled_tasks_is_not_review():
    assert chain(sales=NodeFacts(tasks=(T.CANCELLED,)))[K.SALES] is S.TODO
    assert chain(sales=NodeFacts(tasks=(T.TODO, T.TODO)))[K.SALES] is S.TODO
    assert chain(sales=NodeFacts(tasks=(T.TODO, T.DONE)))[K.SALES] is S.IN_PROGRESS


def test_manual_completion_with_zero_tasks_unlocks_the_next_node():
    statuses = chain(sales=approved())
    assert statuses[K.SALES] is S.DONE and statuses[K.PM] is S.TODO
    assert progress(statuses[K.SALES], task_counts(())) == 1.0
    assert summarize(statuses).__dict__ == {'done': 1, 'total': 9, 'current_node': K.PM}


def test_skip_passes_the_chain_and_leaves_both_sides_of_the_summary():
    statuses = chain(sales=approved(), pm=NodeFacts(skipped=True), confirmation=NodeFacts(tasks=(T.IN_PROGRESS,)))
    assert statuses[K.PM] is S.SKIPPED and statuses[K.CONFIRMATION] is S.IN_PROGRESS
    assert summarize(statuses).__dict__ == {'done': 1, 'total': 8, 'current_node': K.CONFIRMATION}


def test_skip_wins_over_stored_approval_and_tasks():
    assert chain(sales=NodeFacts(skipped=True, approved=True, tasks=(T.TODO,)))[K.SALES] is S.SKIPPED


def test_rejection_holds_in_progress_even_when_every_task_is_done():
    assert chain(sales=NodeFacts(rejected=True, tasks=(T.DONE,)))[K.SALES] is S.IN_PROGRESS


def test_reopening_a_finished_node_reports_started_later_nodes_without_touching_them():
    before = chain(sales=approved(), pm=approved(), confirmation=NodeFacts(tasks=(T.IN_PROGRESS,)))
    assert later_nodes_started(before, K.PM) is True
    after = chain(sales=approved(), pm=NodeFacts(rejected=True), confirmation=NodeFacts(tasks=(T.IN_PROGRESS,)))
    assert after[K.PM] is S.IN_PROGRESS and after[K.CONFIRMATION] is S.NOT_STARTED
    untouched = chain(sales=approved(), pm=approved())
    assert later_nodes_started(untouched, K.PM) is False


def test_all_done_case_has_no_current_node():
    statuses = chain(**{k.value: approved() for k in K})
    assert summarize(statuses).__dict__ == {'done': 9, 'total': 9, 'current_node': None}


def test_progress_is_fraction_of_live_tasks():
    assert progress(S.IN_PROGRESS, task_counts((T.DONE, T.TODO, T.TODO, T.CANCELLED))) == 0.3333
    assert progress(S.TODO, task_counts(())) == 0.0


def person(ident, departments, rank='組員', employed=True):
    return Person(ident, ident, frozenset(departments), rank, employed)


def actor(p, override=False):
    return Actor(p, p.open_id if p else 'ou_x', override)


MEMBER = person('ou_member', {'外業'})
DEPTH_MEMBER = person('ou_depth', {'水深B'})
FIELD_MANAGER = person('ou_fm', {'水深A'}, '經理')
LEADER = person('ou_leader', {'外業'}, '組長')
OTHER_MANAGER = person('ou_om', {'行政'}, '經理')
VP = person('ou_vp', set(), '副總')
BOSS = person('ou_boss', {'業務'}, '老闆')
DEPARTED_MANAGER = person('ou_gone', {'外業'}, '經理', employed=False)


def allowed(p, key=K.FIELD, status=S.TODO, owners=frozenset(), override=False):
    return {a.value for a, ok in node_permissions(actor(p, override), key, status, owners).items() if ok}


@pytest.mark.parametrize('who,expected', [
    (MEMBER, {'claim', 'create_task'}),
    (DEPTH_MEMBER, {'claim', 'create_task'}),
    (LEADER, {'claim', 'create_task'}),
    (FIELD_MANAGER, {'claim', 'create_task', 'assign', 'complete'}),
    (OTHER_MANAGER, set()),
    (VP, {'create_task', 'assign', 'complete'}),
    (BOSS, {'create_task', 'assign', 'complete'}),
    (DEPARTED_MANAGER, set()),
    (None, set()),
])
def test_permission_matrix_on_an_open_field_node(who, expected):
    assert allowed(who) == expected


def test_admin_override_manages_any_node_but_cannot_claim_without_membership():
    assert allowed(None, K.PRICING, override=True) == {'create_task', 'assign', 'complete'}


def test_approve_and_reject_follow_the_review_state():
    assert allowed(FIELD_MANAGER, status=S.IN_REVIEW) == {'claim', 'create_task', 'assign', 'complete', 'approve', 'reject'}
    assert allowed(FIELD_MANAGER, status=S.DONE) == {'reject'}
    assert allowed(FIELD_MANAGER, status=S.SKIPPED) == set()
    assert allowed(FIELD_MANAGER, status=S.NOT_STARTED) == {'claim', 'create_task', 'assign'}


def test_claim_requires_an_unowned_node():
    assert allowed(MEMBER, owners=frozenset({'ou_fm'})) == {'create_task'}
    with pytest.raises(IllegalTransition, match='已有負責人'):
        check_node_action(actor(MEMBER), K.FIELD, NodeAction.CLAIM, S.TODO, frozenset({'ou_fm'}))


def test_denial_and_illegal_transition_are_distinct():
    with pytest.raises(Denied, match='經理或副總、老闆可以核准'):
        check_node_action(actor(MEMBER), K.FIELD, NodeAction.APPROVE, S.IN_REVIEW, frozenset())
    with pytest.raises(IllegalTransition, match='節點目前為「進行中」，不能核准'):
        check_node_action(actor(FIELD_MANAGER), K.FIELD, NodeAction.APPROVE, S.IN_PROGRESS, frozenset())


def test_task_permissions_for_assignee_manager_and_bystander():
    task = TaskFacts(T.TODO, 'ou_member', 'ou_fm')
    mine = task_permissions(actor(MEMBER), K.FIELD, S.IN_PROGRESS, task)
    assert mine.__dict__ == {'edit_status': True, 'cancel': False, 'assign': False, 'claim': False, 'edit_details': False}
    boss = task_permissions(actor(FIELD_MANAGER), K.FIELD, S.IN_PROGRESS, task)
    assert boss.__dict__ == {'edit_status': True, 'cancel': True, 'assign': True, 'claim': False, 'edit_details': True}
    other = task_permissions(actor(DEPTH_MEMBER), K.FIELD, S.IN_PROGRESS, TaskFacts(T.TODO, None, 'ou_fm'))
    assert other.__dict__ == {'edit_status': False, 'cancel': False, 'assign': False, 'claim': True, 'edit_details': False}
    own = task_permissions(actor(MEMBER), K.FIELD, S.IN_PROGRESS, TaskFacts(T.TODO, 'ou_member', 'ou_member'))
    assert own.cancel is True and own.edit_details is True


def test_tasks_are_frozen_once_the_node_is_finished():
    frozen = task_permissions(actor(FIELD_MANAGER), K.FIELD, S.DONE, TaskFacts(T.TODO, None, None))
    assert set(frozen.__dict__.values()) == {False}


def test_task_state_machine():
    manager = task_permissions(actor(FIELD_MANAGER), K.FIELD, S.IN_PROGRESS, TaskFacts(T.DONE, 'ou_member', 'ou_fm'))
    check_task_status(T.DONE, T.IN_PROGRESS, manager)
    with pytest.raises(IllegalTransition, match='不能由「已完成」改為「取消」'):
        check_task_status(T.DONE, T.CANCELLED, manager)
    assignee = task_permissions(actor(MEMBER), K.FIELD, S.IN_PROGRESS, TaskFacts(T.TODO, 'ou_member', 'ou_fm'))
    check_task_status(T.TODO, T.DONE, assignee)
    with pytest.raises(Denied, match='取消或恢復'):
        check_task_status(T.TODO, T.CANCELLED, assignee)
