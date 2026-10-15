"""Pure node-assignment model: the node chain, derived status and who may act.

No I/O. Lark rows are parsed into these types at the boundary (lark_table.py).
"""
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum


class NodeKey(StrEnum):
    SALES = 'sales'
    PM = 'pm'
    CONFIRMATION = 'confirmation'
    FIELD = 'field'
    CONTROL = 'control'
    MAPPING = 'mapping'
    REPORT = 'report'
    PRICING = 'pricing'
    SETTLEMENT = 'settlement'


CHAIN = tuple(NodeKey)

NODE_LABELS = {
    NodeKey.SALES: '業務', NodeKey.PM: 'PM', NodeKey.CONFIRMATION: '確認單',
    NodeKey.FIELD: '外業', NodeKey.CONTROL: '控制', NodeKey.MAPPING: '圖資',
    NodeKey.REPORT: '報告', NodeKey.PRICING: '計價', NodeKey.SETTLEMENT: '結算',
}

NODE_DEPARTMENTS = {
    NodeKey.SALES: ('業務',),
    NodeKey.PM: ('PM',),
    NodeKey.CONFIRMATION: ('PM',),
    NodeKey.FIELD: ('外業', '水深A', '水深B', '水深C', '水深D', '地形A', '地形C', '地形E', '點工B'),
    NodeKey.CONTROL: ('控制',),
    NodeKey.MAPPING: ('圖報A', '圖報B'),
    NodeKey.REPORT: ('圖報A', '圖報B'),
    NodeKey.PRICING: ('行政',),
    NodeKey.SETTLEMENT: ('行政',),
}

EXECUTIVE_RANKS = frozenset({'副總', '老闆'})
MANAGER_RANK = '經理'


class NodeStatus(StrEnum):
    NOT_STARTED = '未開始'
    TODO = '待處理'
    IN_PROGRESS = '進行中'
    IN_REVIEW = '待審核'
    DONE = '已完成'
    SKIPPED = '略過'


FINISHED = frozenset({NodeStatus.DONE, NodeStatus.SKIPPED})
OPEN = frozenset(NodeStatus) - FINISHED


class TaskStatus(StrEnum):
    TODO = '待處理'
    IN_PROGRESS = '進行中'
    DONE = '已完成'
    CANCELLED = '取消'


TASK_TRANSITIONS = {
    TaskStatus.TODO: frozenset({TaskStatus.IN_PROGRESS, TaskStatus.DONE, TaskStatus.CANCELLED}),
    TaskStatus.IN_PROGRESS: frozenset({TaskStatus.TODO, TaskStatus.DONE, TaskStatus.CANCELLED}),
    TaskStatus.DONE: frozenset({TaskStatus.IN_PROGRESS}),
    TaskStatus.CANCELLED: frozenset({TaskStatus.TODO}),
}


class AssignmentMethod(StrEnum):
    CLAIMED = '自行認領'
    ASSIGNED = '主管指派'


class NodeAction(StrEnum):
    CLAIM = 'claim'
    ASSIGN = 'assign'
    COMPLETE = 'complete'
    APPROVE = 'approve'
    REJECT = 'reject'
    CREATE_TASK = 'create_task'


# The node state machine: which derived statuses each action may start from.
ACTION_FROM = {
    NodeAction.CLAIM: OPEN,
    NodeAction.ASSIGN: OPEN,
    NodeAction.COMPLETE: frozenset({NodeStatus.TODO, NodeStatus.IN_PROGRESS, NodeStatus.IN_REVIEW}),
    NodeAction.APPROVE: frozenset({NodeStatus.IN_REVIEW}),
    NodeAction.REJECT: frozenset({NodeStatus.IN_REVIEW, NodeStatus.DONE}),
    NodeAction.CREATE_TASK: OPEN,
}
MANAGER_ACTIONS = frozenset({NodeAction.ASSIGN, NodeAction.COMPLETE, NodeAction.APPROVE, NodeAction.REJECT})

ACTION_LABELS = {
    NodeAction.CLAIM: '認領', NodeAction.ASSIGN: '指派', NodeAction.COMPLETE: '標記完成',
    NodeAction.APPROVE: '核准', NodeAction.REJECT: '退回', NodeAction.CREATE_TASK: '新增任務',
}


class Denied(Exception):
    """The actor lacks the role for this action (HTTP 403)."""


class IllegalTransition(Exception):
    """The action is not valid from the current state (HTTP 409)."""


@dataclass(frozen=True)
class NodeFacts:
    approved: bool = False
    skipped: bool = False
    rejected: bool = False
    tasks: tuple[TaskStatus, ...] = ()


@dataclass(frozen=True)
class TaskCounts:
    done: int
    total: int


def task_counts(tasks: Iterable[TaskStatus]) -> TaskCounts:
    live = [t for t in tasks if t is not TaskStatus.CANCELLED]
    return TaskCounts(sum(t is TaskStatus.DONE for t in live), len(live))


def derive_status(facts: NodeFacts, previous_done: bool) -> NodeStatus:
    if facts.skipped:
        return NodeStatus.SKIPPED
    if facts.approved:
        return NodeStatus.DONE
    if not previous_done:
        return NodeStatus.NOT_STARTED
    if facts.rejected:
        return NodeStatus.IN_PROGRESS
    counts = task_counts(facts.tasks)
    if counts.total and counts.done == counts.total:
        return NodeStatus.IN_REVIEW
    if any(t in (TaskStatus.IN_PROGRESS, TaskStatus.DONE) for t in facts.tasks):
        return NodeStatus.IN_PROGRESS
    return NodeStatus.TODO


def derive_chain(facts: Mapping[NodeKey, NodeFacts]) -> dict[NodeKey, NodeStatus]:
    statuses = {}
    previous_done = True
    for key in CHAIN:
        statuses[key] = derive_status(facts.get(key, NodeFacts()), previous_done)
        previous_done = statuses[key] in FINISHED
    return statuses


def progress(status: NodeStatus, counts: TaskCounts) -> float:
    if status is NodeStatus.DONE:
        return 1.0
    return round(counts.done / counts.total, 4) if counts.total else 0.0


@dataclass(frozen=True)
class Summary:
    done: int
    total: int
    current_node: NodeKey | None


def summarize(statuses: Mapping[NodeKey, NodeStatus]) -> Summary:
    counted = [key for key in CHAIN if statuses[key] is not NodeStatus.SKIPPED]
    current = next((key for key in CHAIN if statuses[key] not in FINISHED), None)
    return Summary(sum(statuses[key] is NodeStatus.DONE for key in counted), len(counted), current)


STARTED = frozenset({NodeStatus.IN_PROGRESS, NodeStatus.IN_REVIEW, NodeStatus.DONE})


def later_nodes_started(statuses: Mapping[NodeKey, NodeStatus], key: NodeKey) -> bool:
    # The node after a finished one is always 待處理, so only real work counts.
    return any(statuses[k] in STARTED for k in CHAIN[CHAIN.index(key) + 1:])


@dataclass(frozen=True)
class Person:
    """One V4 roster row; departments are the 所屬組別 values."""
    open_id: str
    name: str
    departments: frozenset[str]
    rank: str | None
    employed: bool
    avatar_url: str | None = None

    def member_of(self, key: NodeKey) -> bool:
        return self.employed and not self.departments.isdisjoint(NODE_DEPARTMENTS[key])


@dataclass(frozen=True)
class Actor:
    person: Person | None
    open_id: str
    # The app's existing company-admin business grant (can_business_override).
    override: bool = False

    def member_of(self, key: NodeKey) -> bool:
        return self.person is not None and self.person.member_of(key)

    def manages(self, key: NodeKey) -> bool:
        if self.override:
            return True
        person = self.person
        return person is not None and person.employed and (
            person.rank in EXECUTIVE_RANKS or (person.rank == MANAGER_RANK and person.member_of(key)))


def check_node_action(actor: Actor, key: NodeKey, action: NodeAction, status: NodeStatus,
                      owners: frozenset[str]) -> None:
    label = ACTION_LABELS[action]
    if action in MANAGER_ACTIONS:
        if not actor.manages(key):
            raise Denied(f'只有本節點所屬組別的經理或副總、老闆可以{label}')
    elif not (actor.member_of(key) or (action is NodeAction.CREATE_TASK and actor.manages(key))):
        raise Denied(f'只有本節點所屬組別的在職同仁可以{label}')
    if status not in ACTION_FROM[action]:
        raise IllegalTransition(f'節點目前為「{status}」，不能{label}')
    if action is NodeAction.CLAIM and owners:
        raise IllegalTransition('此節點已有負責人；請由主管改派')


def node_permissions(actor: Actor, key: NodeKey, status: NodeStatus,
                     owners: frozenset[str]) -> dict[NodeAction, bool]:
    result = {}
    for action in NodeAction:
        try:
            check_node_action(actor, key, action, status, owners)
            result[action] = True
        except (Denied, IllegalTransition):
            result[action] = False
    return result


def eligible_assignee(person: Person | None, key: NodeKey) -> bool:
    return person is not None and person.member_of(key)


@dataclass(frozen=True)
class TaskFacts:
    status: TaskStatus
    assignee: str | None
    assigned_by: str | None


@dataclass(frozen=True)
class TaskPermissions:
    edit_status: bool
    cancel: bool
    assign: bool
    claim: bool
    edit_details: bool


def task_permissions(actor: Actor, key: NodeKey, node_status: NodeStatus, task: TaskFacts) -> TaskPermissions:
    if node_status in FINISHED or (not actor.override and (actor.person is None or not actor.person.employed)):
        return TaskPermissions(False, False, False, False, False)
    manager = actor.manages(key)
    mine = task.assignee == actor.open_id
    self_owned = mine and task.assigned_by == actor.open_id
    return TaskPermissions(
        edit_status=manager or mine,
        cancel=manager or self_owned,
        assign=manager,
        claim=task.assignee is None and actor.member_of(key),
        edit_details=manager or self_owned)


def check_task_status(current: TaskStatus, target: TaskStatus, allowed: TaskPermissions) -> None:
    if not allowed.edit_status:
        raise Denied('只有任務負責人或本節點主管可以更新任務狀態')
    if TaskStatus.CANCELLED in (current, target) and not allowed.cancel:
        raise Denied('只有主管或自行建立任務的負責人可以取消或恢復任務')
    if target not in TASK_TRANSITIONS[current]:
        raise IllegalTransition(f'任務狀態不能由「{current}」改為「{target}」')
