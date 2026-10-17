"""Typed commands parsed from request bodies, and pure planning into Lark field changes."""
import re
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import date

from .domain import (
    NODE_DEPARTMENTS, OPEN, STARTED, Actor, AssignmentMethod, Denied, IllegalTransition, NodeAction,
    NodeFacts, NodeKey, NodeStatus, TaskFacts, TaskStatus, check_node_action, check_task_status, derive_chain,
    eligible_assignee, later_nodes_started, progress, task_counts, task_permissions)
from .errors import Failure
from .lark_table import CaseSnapshot, NodeRow, TaskRow, date_millis
from .roster import Roster

OPEN_ID = re.compile(r'ou_[A-Za-z0-9]{1,64}')
PREVIEW_HASH = re.compile(r'[0-9a-f]{64}')
REVISION = re.compile(r'[0-9a-f]{16}')
UNSET = object()
LIMITS = {'request_id': 120, 'title': 200, 'detail': 2000, 'reason': 500}


def _text(body, key, *, required=True, blank=False):
    value = body.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise Failure('invalid', f'{key} 必須是文字')
    if len(value) > LIMITS[key]:
        raise Failure('invalid', f'{key} 不得超過 {LIMITS[key]} 字')
    if any(unicodedata.category(c) in ('Cc', 'Cf') and c not in '\n\t' for c in value):
        raise Failure('invalid', f'{key} 含不允許的控制字元')
    if not blank and not value.strip():
        raise Failure('invalid', f'{key} 不可空白')
    return value.strip() if key != 'detail' else value


def _open_id(value, key):
    if not isinstance(value, str) or not OPEN_ID.fullmatch(value):
        raise Failure('invalid', f'{key} 必須是 Lark open_id')
    return value


def _revision(body, key='expected_revision'):
    value = body.get(key)
    if value is not None and (not isinstance(value, str) or not REVISION.fullmatch(value)):
        raise Failure('invalid', f'{key} 格式錯誤，請重新整理後再操作')
    return value


def _deadline(value):
    if value is None:
        return None
    try:
        parsed = date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        parsed = None
    if parsed is None or parsed.isoformat() != value or not date(2000, 1, 1) <= parsed <= date(2100, 12, 31):
        raise Failure('invalid', '截止日需為 YYYY-MM-DD 的有效日期')
    return value


def _keys(body, allowed):
    unknown = set(body) - set(allowed) - {'request_id'}
    if unknown:
        raise Failure('invalid', '不支援的欄位：' + '、'.join(sorted(map(str, unknown))))


def request_id(body):
    return _text(body, 'request_id')


@dataclass(frozen=True)
class NodeCommand:
    action: NodeAction
    expected_revision: str | None
    owners: tuple[str, ...] = ()
    reason: str | None = None


def parse_node_command(action: NodeAction, body) -> NodeCommand:
    if action is NodeAction.ASSIGN:
        _keys(body, ('expected_revision', 'owner_open_ids'))
        owners = body.get('owner_open_ids')
        if not isinstance(owners, list) or not 1 <= len(owners) <= 20:
            raise Failure('invalid', '請指定 1 至 20 位負責人')
        owners = tuple(dict.fromkeys(_open_id(v, 'owner_open_ids') for v in owners))
        return NodeCommand(action, _revision(body), owners=owners)
    if action is NodeAction.REJECT:
        _keys(body, ('expected_revision', 'reason'))
        return NodeCommand(action, _revision(body), reason=_text(body, 'reason'))
    _keys(body, ('expected_revision',))
    return NodeCommand(action, _revision(body))


@dataclass(frozen=True)
class CreateTask:
    title: str
    detail: str
    assignee: str | None
    deadline: str | None
    department: str | None


def parse_create_task(body) -> CreateTask:
    _keys(body, ('title', 'detail', 'assignee_open_id', 'deadline', 'department'))
    assignee = body.get('assignee_open_id')
    department = body.get('department')
    if department is not None and not isinstance(department, str):
        raise Failure('invalid', 'department 必須是文字')
    return CreateTask(_text(body, 'title'), _text(body, 'detail', required=False, blank=True) or '',
                      None if assignee is None else _open_id(assignee, 'assignee_open_id'),
                      _deadline(body.get('deadline')), department)


@dataclass(frozen=True)
class StartSopCommand:
    preview_hash: str


def parse_start_sop(body) -> StartSopCommand:
    _keys(body, ('preview_hash',))
    value = body.get('preview_hash')
    if not isinstance(value, str) or not PREVIEW_HASH.fullmatch(value):
        raise Failure('invalid', 'preview_hash 格式錯誤，請重新取得預覽')
    return StartSopCommand(value)


@dataclass(frozen=True)
class PatchTask:
    expected_revision: str
    status: object = UNSET
    assignee: object = UNSET
    deadline: object = UNSET
    detail: object = UNSET


def parse_patch_task(body) -> PatchTask:
    _keys(body, ('expected_revision', 'status', 'assignee_open_id', 'deadline', 'detail'))
    revision = _revision(body)
    if revision is None:
        raise Failure('invalid', '請提供任務目前的 expected_revision')
    changes = {}
    if 'status' in body:
        try:
            changes['status'] = TaskStatus(body['status'])
        except ValueError:
            raise Failure('invalid', '任務狀態只能是 待處理、進行中、已完成 或 取消') from None
    if 'assignee_open_id' in body:
        value = body['assignee_open_id']
        changes['assignee'] = None if value is None else _open_id(value, 'assignee_open_id')
    if 'deadline' in body:
        changes['deadline'] = _deadline(body['deadline'])
    if 'detail' in body:
        changes['detail'] = _text(body, 'detail', blank=True)
    if not changes:
        raise Failure('invalid', '請至少提供一個要更新的欄位')
    return PatchTask(revision, **changes)


@dataclass(frozen=True)
class Situation:
    key: NodeKey
    code: str
    actor: Actor
    roster: Roster
    snapshot: CaseSnapshot
    skipped: frozenset
    now_ms: int
    confirmation_record: str | None = None


@dataclass(frozen=True)
class Plan:
    """A single verified write. `changes` uses semantic keys of NODE_FIELDS or TASK_FIELDS."""
    kind: str
    record_id: str | None
    base_revision: str | None
    changes: dict
    client_token: str | None = None
    warnings: tuple[str, ...] = ()
    before: dict = field(default_factory=dict)
    pre_create_task_ids: tuple[str, ...] | None = None

    def to_json(self):
        return {'kind': self.kind, 'record_id': self.record_id, 'base_revision': self.base_revision,
                'changes': self.changes, 'client_token': self.client_token, 'warnings': list(self.warnings),
                'before': self.before, 'pre_create_task_ids': self.pre_create_task_ids}

    @classmethod
    def from_json(cls, data):
        return cls(data['kind'], data['record_id'], data['base_revision'], data['changes'], data.get('client_token'),
                   tuple(data.get('warnings', ())), data.get('before', {}),
                   tuple(data['pre_create_task_ids']) if data.get('pre_create_task_ids') is not None else None)


def facts_of(snapshot: CaseSnapshot, skipped, overrides=None) -> dict[NodeKey, NodeFacts]:
    facts = {}
    for key in NodeKey:
        rows = snapshot.rows.get(key, ())
        row = rows[0] if len(rows) == 1 else None
        facts[key] = NodeFacts(approved=bool(row and row.approved), skipped=key in skipped,
                               rejected=bool(row and row.rejected),
                               tasks=tuple(t.status for t in snapshot.node_tasks(key)))
    facts.update(overrides or {})
    return facts


def mirror(row: NodeRow | None, status: NodeStatus, counts, now_ms) -> dict:
    """Lark 狀態/進度/開始時間 that match the derived status; never writes 略過."""
    if status is NodeStatus.SKIPPED:
        return {}
    wanted = {'status': status.value, 'progress': progress(status, counts)}
    if status in STARTED and (row is None or row.started_at is None):
        wanted['started_at'] = now_ms
    return wanted


def _row_before(row: NodeRow | None, keys):
    if row is None:
        return {}
    values = {'owners': [u.open_id for u in row.owners], 'method': row.method, 'status': row.status,
              'assigned_by': row.assigned_by and row.assigned_by.open_id,
              'approver': row.approver and row.approver.open_id, 'approved_at': row.approved_at,
              'reject_reason': row.reject_reason, 'finished_at': row.finished_at, 'started_at': row.started_at}
    return {k: values[k] for k in keys if k in values}


def _check_revision(current, expected):
    if current != expected:
        raise Failure('revision_conflict', '此節點或任務已被其他人更新，請重新整理後再操作', current_revision=current)


def plan_node(s: Situation, command: NodeCommand, expected_revision) -> Plan:
    row = s.snapshot.row(s.key)
    facts = facts_of(s.snapshot, s.skipped)
    statuses = derive_chain(facts)
    status = statuses[s.key]
    owners = frozenset(u.open_id for u in row.owners) if row else frozenset()
    illegal = None
    try:
        check_node_action(s.actor, s.key, command.action, status, owners)
    except IllegalTransition as exc:
        illegal = exc
    _check_revision(row.revision if row else None, expected_revision)
    if illegal:
        raise illegal
    me = [s.actor.open_id]
    current = facts[s.key]
    warnings = ()
    if command.action is NodeAction.CLAIM:
        changes = {'owners': me, 'method': AssignmentMethod.CLAIMED.value, 'assigned_by': me}
    elif command.action is NodeAction.ASSIGN:
        for ident in command.owners:
            if not eligible_assignee(s.roster.person(ident), s.key):
                raise Failure('invalid', '負責人必須是本節點所屬組別的在職同仁')
        changes = {'owners': list(command.owners), 'method': AssignmentMethod.ASSIGNED.value, 'assigned_by': me}
    elif command.action in (NodeAction.COMPLETE, NodeAction.APPROVE):
        current = replace(current, approved=True, rejected=False)
        changes = {'approver': me, 'approved_at': s.now_ms, 'finished_at': s.now_ms, 'reject_reason': None}
    else:
        if status is NodeStatus.DONE and later_nodes_started(statuses, s.key):
            warnings = ('later_nodes_started',)
        current = replace(current, approved=False, rejected=True)
        changes = {'reject_reason': command.reason, 'approver': None, 'approved_at': None, 'finished_at': None}
    after = derive_chain({**facts, s.key: current})[s.key]
    changes.update(mirror(row, after, task_counts(current.tasks), s.now_ms))
    return Plan('node', row.record_id if row else None, row.revision if row else None, changes,
                warnings=warnings, before=_row_before(row, changes))


def _department(s: Situation, requested, assignee):
    allowed = NODE_DEPARTMENTS[s.key]
    if requested is not None:
        if requested not in allowed:
            raise Failure('invalid', '部門必須是本節點所屬組別：' + '、'.join(allowed))
        return requested
    person = s.roster.person(assignee) if assignee else None
    choice = next((d for d in allowed if person and d in person.departments), None)
    if choice is None and len(allowed) == 1:
        choice = allowed[0]
    if choice is None:
        raise Failure('invalid', '請選擇任務所屬部門')
    return choice


def plan_create_task(s: Situation, command: CreateTask, client_token) -> Plan:
    row = s.snapshot.row(s.key)
    status = derive_chain(facts_of(s.snapshot, s.skipped))[s.key]
    check_node_action(s.actor, s.key, NodeAction.CREATE_TASK, status,
                      frozenset(u.open_id for u in row.owners) if row else frozenset())
    assignee = command.assignee
    if not s.actor.manages(s.key):
        if assignee not in (None, s.actor.open_id):
            raise Denied('只有本節點主管可以把任務指派給其他同仁')
        assignee = s.actor.open_id
    if assignee is not None and not eligible_assignee(s.roster.person(assignee), s.key):
        raise Failure('invalid', '負責人必須是本節點所屬組別的在職同仁')
    changes = {'title': command.title, 'detail': command.detail or None,
               'assignee': [assignee] if assignee else None, 'assigned_by': [s.actor.open_id],
               'department': _department(s, command.department, assignee),
               'deadline': date_millis(command.deadline) if command.deadline else None,
               'status': TaskStatus.TODO.value}
    return Plan('task_create', None, None, changes, client_token=client_token)


def find_task(s: Situation, task_id) -> TaskRow:
    s.snapshot.row(s.key)
    task = next((t for t in s.snapshot.node_tasks(s.key) if t.record_id == task_id), None)
    if task is None:
        raise Failure('not_found', '此節點沒有這個任務，請重新整理')
    return task


def plan_patch_task(s: Situation, task: TaskRow, command: PatchTask) -> Plan:
    status = derive_chain(facts_of(s.snapshot, s.skipped))[s.key]
    if (s.actor.person is None or not s.actor.person.employed) and not s.actor.override:
        raise Denied('你不在人員名單或尚未在職，無法更新任務')
    _check_revision(task.revision, command.expected_revision)
    if status not in OPEN:
        raise IllegalTransition(f'節點目前為「{status}」，任務已鎖定；如需修改請先退回節點')
    allowed = task_permissions(s.actor, s.key, status, TaskFacts(
        task.status, task.assignee and task.assignee.open_id, task.assigned_by and task.assigned_by.open_id))
    changes, before = {}, {}
    if command.status is not UNSET and command.status is not task.status:
        check_task_status(task.status, command.status, allowed)
        changes['status'] = command.status.value
        changes['done_at'] = s.now_ms if command.status is TaskStatus.DONE else None
        before.update(status=task.status.value, done_at=task.done_at)
    if command.assignee is not UNSET and command.assignee != (task.assignee and task.assignee.open_id):
        claiming = command.assignee == s.actor.open_id and allowed.claim
        if not (allowed.assign or claiming):
            raise Denied('只有本節點主管可以指派任務；同仁只能認領尚未指派的任務')
        if command.assignee is not None and not eligible_assignee(s.roster.person(command.assignee), s.key):
            raise Failure('invalid', '負責人必須是本節點所屬組別的在職同仁')
        changes['assignee'] = [command.assignee] if command.assignee else None
        changes['assigned_by'] = [s.actor.open_id]
        before.update(assignee=task.assignee and task.assignee.open_id,
                      assigned_by=task.assigned_by and task.assigned_by.open_id)
    for key, current in (('deadline', task.deadline), ('detail', task.detail)):
        value = getattr(command, key)
        if value is UNSET or value == current:
            continue
        if not allowed.edit_details:
            raise Denied('只有本節點主管或自行建立任務的負責人可以修改截止日與內容')
        changes[key] = (date_millis(value) if value else None) if key == 'deadline' else (value or None)
        before[key] = current
    return Plan('task_update', task.record_id, task.revision, changes, before=before)
