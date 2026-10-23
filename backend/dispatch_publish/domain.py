"""Pure dispatch publish model: proposal, feasibility, approval seats, the 任務 payload and the PM work queue.

No I/O. Requests are parsed into Proposal at the route boundary; V4 rows arrive as raw Bitable records.
"""
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum

from ..dispatch_board.domain import TZ, Feasibility, Interval, _interval as schedule_interval, resource_state
from ..node_assignment.domain import EXECUTIVE_RANKS, MANAGER_RANK, NODE_DEPARTMENTS, NODE_LABELS
from ..node_assignment.lark_table import Kind, canon
from ..sources import link_ids, text
from .config import Seat


class TaskKind(StrEnum):
    OBLIGATION = 'obligation'
    EXECUTION = 'execution'


class Phase(StrEnum):
    INTAKE = 'intake'
    FORMAL = 'formal'


class PlanningStatus(StrEnum):
    UNASSIGNED = 'unassigned'
    DRAFT = 'draft'
    PENDING_APPROVAL = 'pending_approval'
    PUBLISHING = 'publishing'
    CONFIRMED = 'confirmed'
    CONFLICT = 'conflict'
    CANCELLED = 'cancelled'


class CommandResult(StrEnum):
    PENDING = 'pending'
    COMMITTED = 'committed'
    FAILED = 'failed'
    OUTCOME_UNKNOWN = 'outcome_unknown'
    RECONCILIATION_REQUIRED = 'reconciliation_required'
    # Part of the shared vocabulary; this slice refuses before persisting, so it never stores one.
    REJECTED = 'rejected'


class Decision(StrEnum):
    ACCEPTED = 'accepted'
    RETURNED = 'returned'


class ResourceKind(StrEnum):
    PERSON = 'person'
    INSTRUMENT = 'instrument'
    VEHICLE = 'vehicle'


KIND_LABEL = {TaskKind.OBLIGATION: '義務', TaskKind.EXECUTION: '執行'}
PHASE_LABEL = {Phase.INTAKE: '接案前', Phase.FORMAL: '正式'}
PLANNING_LABEL = {PlanningStatus.UNASSIGNED: '未分配', PlanningStatus.DRAFT: '草稿',
                  PlanningStatus.PENDING_APPROVAL: '待核定', PlanningStatus.PUBLISHING: '發布中',
                  PlanningStatus.CONFIRMED: '已確認', PlanningStatus.CONFLICT: '衝突', PlanningStatus.CANCELLED: '已取消'}
PLANNING_OF_LABEL = {label: status for status, label in PLANNING_LABEL.items()}
BOOKING_LABELS = frozenset({'已確認', '發布中'})
IN_FLIGHT = frozenset({CommandResult.PENDING, CommandResult.OUTCOME_UNKNOWN, CommandResult.RECONCILIATION_REQUIRED})
COMMAND_PLANNING = {CommandResult.PENDING: PlanningStatus.PUBLISHING,
                    CommandResult.OUTCOME_UNKNOWN: PlanningStatus.PUBLISHING,
                    CommandResult.RECONCILIATION_REQUIRED: PlanningStatus.CONFLICT,
                    CommandResult.COMMITTED: PlanningStatus.CONFIRMED}
COMMAND_LABEL = {CommandResult.PENDING: '處理中', CommandResult.OUTCOME_UNKNOWN: '結果未知',
                 CommandResult.RECONCILIATION_REQUIRED: '需對帳', CommandResult.COMMITTED: '已確認',
                 CommandResult.FAILED: '失敗', CommandResult.REJECTED: '已拒絕'}

REF = re.compile(r'rec[A-Za-z0-9]{1,40}')
DRAFT_ID = re.compile(r'[A-Za-z0-9_-]{8,64}')
# Lark accepts only a UUIDv4 as client_token (else 1254037); the command id is sent unchanged.
COMMAND_ID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}')
MAX_SPAN = timedelta(days=14)

STATUS = {'invalid': 422, 'blocked': 422, 'approval_not_configured': 422, 'forbidden': 403,
          'writes_disabled': 403, 'not_found': 404, 'disabled': 404, 'preview_expired': 409,
          'preview_stale': 409, 'reservation_conflict': 409, 'duplicate_command': 409, 'idempotency_conflict': 409,
          'busy': 409, 'stale_revision': 409, 'seat_conflict': 409, 'version_conflict': 409, 'nothing_to_reconcile': 409,
          'decision_holder_changed': 409, 'payload_too_large': 413, 'lark_unconfigured': 503,
          'sources_unavailable': 503, 'recheck_unavailable': 503}


class Refusal(Exception):
    def __init__(self, code, message, **extra):
        super().__init__(message)
        self.code, self.message, self.extra = code, message, extra

    @property
    def status(self):
        return STATUS[self.code]

    def body(self):
        return {'detail': self.message, 'code': self.code, **self.extra}


# Proposal


@dataclass(frozen=True)
class Proposal:
    task_id: str | None
    project_ref: str
    case_ref: str | None
    title: str
    content: str
    kind: TaskKind
    phase: Phase | None
    package_id: str | None
    parent_task_ref: str | None
    department: str | None
    primary_owner: str
    crew: tuple[str, ...]
    start: datetime
    end: datetime
    est_person_hours: float | None
    instruments: tuple[str, ...]
    vehicles: tuple[str, ...]
    deadline: date | None
    verifications: tuple[tuple[str, str], ...]

    @property
    def hours(self):
        return round((self.end - self.start).total_seconds() / 3600, 2)

    @property
    def booked_person_hours(self):
        return round(self.hours * len(self.crew), 2)

    def items(self):
        return ([(ResourceKind.PERSON, ref) for ref in self.crew]
                + [(ResourceKind.INSTRUMENT, ref) for ref in self.instruments]
                + [(ResourceKind.VEHICLE, ref) for ref in self.vehicles])

    def public(self):
        return {'task_id': self.task_id, 'project_ref': self.project_ref, 'case_ref': self.case_ref,
                'title': self.title, 'content': self.content, 'kind': self.kind.value,
                'phase': self.phase.value if self.phase else None, 'package_id': self.package_id,
                'parent_task_ref': self.parent_task_ref, 'department': self.department,
                'primary_owner': self.primary_owner, 'crew': list(self.crew),
                'start': self.start.isoformat(timespec='minutes'), 'end': self.end.isoformat(timespec='minutes'),
                'est_person_hours': self.est_person_hours, 'instruments': list(self.instruments),
                'vehicles': list(self.vehicles), 'deadline': self.deadline.isoformat() if self.deadline else None,
                'verifications': dict(self.verifications)}


PROPOSAL_KEYS = frozenset(Proposal.__dataclass_fields__)


def item_key(kind, ref):
    return f'{kind.value}:{ref}'


def _invalid(field, message):
    return Refusal('invalid', message, field=field)


def _text_field(raw, key, limit=200):
    value = raw.get(key)
    if value is None or value == '':
        return None
    if not isinstance(value, str) or len(value.strip()) > limit or any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise _invalid(key, f'{key} 須為 {limit} 字以內的文字')
    return value.strip() or None


def _text(limit):
    return lambda raw, key: _text_field(raw, key, limit)


def _ref_field(raw, key):
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not REF.fullmatch(value):
        raise _invalid(key, f'{key} 須為 Lark 紀錄識別碼')
    return value


def _refs_field(raw, key, limit=30):
    value = raw.get(key)
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > limit or not all(isinstance(v, str) and REF.fullmatch(v) for v in value):
        raise _invalid(key, f'{key} 須為最多 {limit} 筆 Lark 紀錄識別碼')
    return tuple(dict.fromkeys(value))


def _moment(raw, key):
    value = raw.get(key)
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) and len(value) <= 40 else None
    except ValueError:
        parsed = None
    if parsed is None or parsed.tzinfo is None or parsed.second or parsed.microsecond:
        raise _invalid(key, f'{key} 須為含時區、精確到分鐘的 ISO 8601 時間')
    return parsed.astimezone(TZ)


def _enum(kind):
    def parse(raw, key):
        value = raw.get(key)
        if value is None:
            return None
        try:
            return kind(value)
        except ValueError:
            raise _invalid(key, f'{key} 須為 {"、".join(k.value for k in kind)}') from None
    return parse


def _hours(raw, key):
    hours = raw.get(key)
    if hours is not None and (type(hours) not in (int, float) or not 0 <= hours <= 10000):
        raise _invalid(key, '預估人時須為 0 至 10000 的數字')
    return None if hours is None else round(float(hours), 1)


def _deadline(raw, key):
    value = raw.get(key)
    if value is None:
        return None
    try:
        parsed = date.fromisoformat(value) if isinstance(value, str) and len(value) == 10 else None
    except ValueError:
        parsed = None
    if parsed is None:
        raise _invalid(key, '截止日須為 YYYY-MM-DD')
    return parsed


def _verifications(raw, key):
    found = raw.get(key) or {}
    if not isinstance(found, dict) or len(found) > 60 or not all(
            isinstance(reason, str) and 0 < len(reason.strip()) <= 500 for reason in found.values()):
        raise _invalid(key, '人工核實須對應本提案的人員或資源，且每項附 500 字以內理由')
    return tuple(sorted((k, v.strip()) for k, v in found.items()))


# Field -> (parser, required). A draft runs the same parsers but may leave required fields empty.
FIELDS = {
    'task_id': (_ref_field, False), 'project_ref': (_text(120), True), 'case_ref': (_ref_field, False),
    'title': (_text(200), True), 'content': (_text(5000), False), 'kind': (_enum(TaskKind), True),
    'phase': (_enum(Phase), False), 'package_id': (_text(120), False), 'parent_task_ref': (_ref_field, False),
    'department': (_text(60), False), 'primary_owner': (_ref_field, True), 'crew': (_refs_field, False),
    'start': (_moment, True), 'end': (_moment, True), 'est_person_hours': (_hours, False),
    'instruments': (_refs_field, False), 'vehicles': (_refs_field, False), 'deadline': (_deadline, False),
    'verifications': (_verifications, False),
}
REQUIRED_MESSAGE = {'primary_owner': '請指定主要負責人'}


def _fields(raw, *, draft):
    if not isinstance(raw, dict):
        raise _invalid('proposal', '提案內容須為 JSON 物件')
    unknown = sorted(set(raw) - PROPOSAL_KEYS)
    if unknown:
        raise _invalid(unknown[0], f'不支援的欄位：{unknown[0]}')
    values = {}
    for key, (parse, required) in FIELDS.items():
        values[key] = parse(raw, key)
        if required and not draft and values[key] is None:
            raise _invalid(key, REQUIRED_MESSAGE.get(key, f'{key} 為必填'))
    return values


def check_draft(raw):
    """Refuse a draft whose present fields have the wrong type; missing fields are fine."""
    _fields(raw, draft=True)


def parse_proposal(raw) -> Proposal:
    values = _fields(raw, draft=False)
    owner, start, end = values['primary_owner'], values['start'], values['end']
    if not start < end or end - start > MAX_SPAN:
        raise _invalid('end', '結束須晚於開始，且一段排程最多 14 天')
    proposal = Proposal(**{**values, 'content': values['content'] or '',
                           'crew': (owner,) + tuple(ref for ref in values['crew'] if ref != owner)})
    allowed = {item_key(kind, ref) for kind, ref in proposal.items()}
    if not {key for key, _ in proposal.verifications} <= allowed:
        raise _invalid('verifications', '人工核實須對應本提案的人員或資源，且每項附 500 字以內理由')
    return proposal


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def proposal_hash(proposal: Proposal) -> str:
    return digest(proposal.public())


def millis(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def from_millis(value):
    return datetime.fromtimestamp(value / 1000, TZ) if type(value) is int else None


# Sources and occupancy


@dataclass(frozen=True)
class Sources:
    """Raw V4 rows per manifest key; None marks a source that could not be read."""
    schedule: list | None
    tasks: list | None
    people: list | None
    accounts: list | None
    instruments: list | None
    vehicles: list | None
    cases: list | None
    nodes: list | None = None
    fetched_at: str | None = None

    def index(self, key):
        return {row['record_id']: row['fields'] for row in getattr(self, key) or []}


@dataclass(frozen=True)
class Directory:
    """人員名單 record ids and Lark open_ids, in both directions; ambiguous accounts map to nobody."""
    names: dict
    active: dict
    open_ids: dict
    refs: dict
    ranks: dict = field(default_factory=dict)
    groups: dict = field(default_factory=dict)

    @classmethod
    def of(cls, sources: Sources):
        people = sources.index('people')
        open_ids, owners = {}, {}
        for ref, fields in sources.index('accounts').items():
            accounts = [a.get('id') for a in fields.get('Lark帳號') or [] if isinstance(a, dict) and isinstance(a.get('id'), str)]
            if len(accounts) == 1:
                open_ids[ref] = accounts[0]
                owners.setdefault(accounts[0], []).append(ref)
        refs = {ident: found[0] for ident, found in owners.items() if len(found) == 1}
        open_ids = {ref: ident for ref, ident in open_ids.items() if refs.get(ident) == ref}
        names = {ref: text(f.get('姓名')).strip() or None for ref, f in people.items()}
        active = {ref: (f.get('在職') is True) for ref, f in people.items()} if sources.people is not None else {}
        accounts = sources.index('accounts')
        ranks = {ref: text(f.get('職級')).strip() or None for ref, f in accounts.items()}
        groups = {ref: frozenset(text(g).strip() for g in _values(f.get('所屬組別')) if text(g).strip())
                  for ref, f in accounts.items()}
        return cls(names, active, open_ids, refs, ranks, groups)

    def person(self, open_id, name=None):
        ref = self.refs.get(open_id)
        return {'person_ref': ref, 'open_id': open_id, 'name': (self.names.get(ref) if ref else None) or name or None}


def _values(raw):
    return raw if isinstance(raw, list) else [raw] if raw else []


def task_users(fields, name):
    return [(u.get('id'), text(u.get('name')).strip() or None) for u in fields.get(name) or []
            if isinstance(u, dict) and isinstance(u.get('id'), str)]


def task_interval(fields):
    start, end = from_millis(fields.get('預定開始')), from_millis(fields.get('預定結束'))
    return Interval(start, end, 'datetime') if start and end and start < end else None


@dataclass(frozen=True)
class Booking:
    source: str
    ident: str
    task_id: str | None
    title: str | None
    interval: Interval
    holders: frozenset


def bookings(sources: Sources, reservations, directory: Directory, exclude_task=None):
    found = []
    for row in sources.schedule or []:
        fields, interval = row['fields'], schedule_interval(row['fields'])
        if interval is None:
            continue
        holders = {(kind, ref) for kind, name in ((ResourceKind.PERSON, '人員'), (ResourceKind.INSTRUMENT, '儀器'),
                                                  (ResourceKind.VEHICLE, '車輛')) for ref in link_ids(fields.get(name))}
        found.append(Booking('schedule', row['record_id'], None, text(fields.get('工作內容')).strip() or None,
                             interval, frozenset(holders)))
    for row in sources.tasks or []:
        fields, interval = row['fields'], task_interval(row['fields'])
        if row['record_id'] == exclude_task or interval is None or text(fields.get('排程狀態')).strip() not in BOOKING_LABELS:
            continue
        people = [directory.refs.get(ident, ident) for ident, _ in task_users(fields, '負責人') + task_users(fields, '組員')]
        holders = {(ResourceKind.PERSON, ref) for ref in people}
        holders |= {(ResourceKind.INSTRUMENT, ref) for ref in link_ids(fields.get('使用儀器'))}
        holders |= {(ResourceKind.VEHICLE, ref) for ref in link_ids(fields.get('使用車輛'))}
        found.append(Booking('v4_task', row['record_id'], row['record_id'], text(fields.get('標題')).strip() or None,
                             interval, frozenset(holders)))
    for held in reservations:
        if held['task_id'] is not None and held['task_id'] == exclude_task:
            continue
        found.append(Booking('reservation', held['command_id'], held['task_id'], None,
                             Interval(from_millis(held['start_ms']), from_millis(held['end_ms']), 'datetime'),
                             frozenset({(ResourceKind(held['resource_kind']), held['ref'])})))
    return found


def overlap(booking: Booking, start: datetime, end: datetime):
    """conflict for two timed intervals that intersect, unknown for a date-only row on a shared day, else None."""
    span = booking.interval
    if span.precision == 'datetime':
        return Feasibility.CONFLICT if span.start < end and start < span.end else None
    last = (end - timedelta(microseconds=1)).date()
    return Feasibility.UNKNOWN if span.start.date() <= last and start.date() <= span.end.date() else None


NODE_OF_LABEL = {label: key for key, label in NODE_LABELS.items()}


def known_departments(sources: Sources, directory: Directory):
    """The /options choices: 任務 部門 values and roster 所屬組別."""
    return ({text(f.get('部門')).strip() for f in sources.index('tasks').values()}
            | set().union(*directory.groups.values())) - {''}


def owning_groups(proposal: Proposal, sources: Sources):
    """The 所屬組別 that own the node the target task, or else its parent obligation, is assigned to."""
    tasks, nodes = sources.index('tasks'), sources.index('nodes')
    for rid in (proposal.task_id, proposal.parent_task_ref):
        node = next(iter(link_ids((tasks.get(rid) or {}).get('節點指派'))), None) if rid else None
        key = NODE_OF_LABEL.get(text(nodes.get(node, {}).get('節點')).strip()) if node else None
        if key is not None:
            return frozenset(NODE_DEPARTMENTS[key])
    return None


def department_problem(proposal: Proposal, sources: Sources, directory: Directory):
    """The department chooses the 組長 and 經理 who approve, so it must be a real group and the node's own."""
    if proposal.department is None:
        return None
    if proposal.department not in known_departments(sources, directory):
        return 'unknown_department'
    owners = owning_groups(proposal, sources)
    if owners is not None and proposal.department not in owners:
        return 'department_not_node_group'
    return None


def assess(proposal: Proposal, sources: Sources, reservations, *, allow_unknown: bool) -> dict:
    """Per-person and per-resource feasibility, conflicts and commit blockers for one proposal."""
    directory = Directory.of(sources)
    verified = dict(proposal.verifications)
    booked = bookings(sources, reservations, directory, exclude_task=proposal.task_id)
    blockers, warnings, conflicts = [], ['no_capability_source', 'no_leave_source'], []
    for key in ('schedule', 'tasks'):
        if getattr(sources, key) is None:
            blockers.append(f'source_unavailable:{key}')
    instruments, vehicles = sources.index('instruments'), sources.index('vehicles')

    def judge(kind, ref, feasibility, reasons):
        seen = set()
        for booking in booked:
            if (kind, ref) not in booking.holders:
                continue
            state = overlap(booking, proposal.start, proposal.end)
            # A published task and its held reservation are one booking; the V4 row is listed first.
            if state is None or (booking.task_id is not None and booking.task_id in seen):
                continue
            seen.add(booking.task_id)
            conflicts.append({'kind': kind.value, 'ref': ref, 'feasibility': state.value,
                              'other': {'source': booking.source, 'id': booking.ident, 'task_id': booking.task_id,
                                        'title': booking.title},
                              'interval': booking.interval.public()})
            reason = 'timed_overlap' if state is Feasibility.CONFLICT else 'same_day_other_slot'
            if reason not in reasons:
                reasons.append(reason)
            if state is Feasibility.CONFLICT and feasibility is not Feasibility.UNAVAILABLE:
                feasibility = Feasibility.CONFLICT
            elif state is Feasibility.UNKNOWN and feasibility is Feasibility.FEASIBLE:
                feasibility = Feasibility.UNKNOWN
        key = item_key(kind, ref)
        if feasibility in (Feasibility.CONFLICT, Feasibility.UNAVAILABLE):
            blockers.append(f'{feasibility.value}:{key}')
        elif feasibility is Feasibility.UNKNOWN and key not in verified:
            if allow_unknown:
                warnings.append(f'unverified_unknown:{key}')
            else:
                blockers.append(f'unknown:{key}')
        return {'feasibility': feasibility.value, 'reasons': reasons, 'verification': verified.get(key)}

    crew = []
    for ref in proposal.crew:
        active = directory.active.get(ref)
        reasons = (['inactive'] if active is False else []) + (['person_unresolved'] if active is None else [])
        reasons += ['no_leave_source', 'no_capability_source']
        verdict = judge(ResourceKind.PERSON, ref, Feasibility.UNAVAILABLE if active is False else Feasibility.UNKNOWN, reasons)
        if ref not in directory.open_ids:
            blockers.append(f'person_without_lark_account:{ref}')
        crew.append({'person_ref': ref, 'name': directory.names.get(ref), 'active': active,
                     'has_lark_account': ref in directory.open_ids, **verdict})
    resources = []
    for kind, refs, index, label in ((ResourceKind.INSTRUMENT, proposal.instruments, instruments, '儀器名稱'),
                                     (ResourceKind.VEHICLE, proposal.vehicles, vehicles, '車牌')):
        for ref in refs:
            fields = index.get(ref)
            resolved = {'啟用': False, **fields} if fields is not None else {}
            feasibility, reasons = resource_state(kind.value, resolved)
            resources.append({'kind': kind.value, 'ref': ref, 'label': text(resolved.get(label)).strip() or None,
                              **judge(kind, ref, feasibility, list(reasons))})
    case = None
    if proposal.case_ref:
        fields = sources.index('cases').get(proposal.case_ref)
        case = {'ref': proposal.case_ref, 'resolved': fields is not None,
                'code': text((fields or {}).get('工程確認單編號')).strip() or None,
                'name': text((fields or {}).get('工程名稱')).strip() or None}
        if fields is None:
            blockers.append('case_unresolved')
    if problem := department_problem(proposal, sources, directory):
        blockers.append(problem)
    base_revision, row = 0, None
    if proposal.task_id:
        row = sources.index('tasks').get(proposal.task_id) if sources.tasks is not None else None
        if row is None:
            blockers.append('task_not_found')
        else:
            base_revision = int(row.get('排程版本') or 0)
            parent = link_ids(row.get('父義務'))
            if parent and parent != [proposal.parent_task_ref]:
                blockers.append('obligation_changed')
    blockers = list(dict.fromkeys(blockers))
    result = {'crew': crew, 'resources': resources, 'case': case, 'conflicts': conflicts, 'warnings': warnings,
              'blockers': blockers, 'hours': proposal.hours, 'booked_person_hours': proposal.booked_person_hours,
              'base_revision': base_revision}
    # Anything the approvers saw that a commit would act on: the target row as it stands and who each
    # person_ref resolves to in Lark. A change to either after the preview forces a new preview.
    result['digest'] = digest({'blockers': blockers, 'base_revision': base_revision,
                               'conflicts': sorted((c['kind'], c['ref'], c['other']['source'], c['other']['id'])
                                                   for c in conflicts),
                               'row': snapshot(row) if row is not None else None,
                               'accounts': [(ref, directory.open_ids.get(ref)) for ref in proposal.crew]})
    return result


# Approval seats


LEADER_RANK = '組長'
ANY_DEPARTMENT = object()
# The proposer may not confirm or review their own preview; pm_final may be their own role.
PROPOSER_EXCLUDED = frozenset({Seat.GROUP_LEADER, Seat.MANAGER_REVIEW})


@dataclass(frozen=True)
class Seats:
    """Who may decide each seat, where that list came from, and session names the roster cannot supply."""
    holders: dict
    origin: dict
    names: dict

    def mine(self, open_id):
        return frozenset(seat for seat, found in self.holders.items() if open_id in found)

    def excluding(self, proposers):
        return Seats({seat: found - proposers if seat in PROPOSER_EXCLUDED else found
                      for seat, found in self.holders.items()}, self.origin, self.names)

    def people(self, seat, directory: Directory):
        return [{'person_ref': p['person_ref'], 'name': p['name']}
                for p in (directory.person(ident, self.names.get(ident)) for ident in sorted(self.holders.get(seat, ())))]


def resolve_seats(required, directory: Directory, department, session_users, overrides) -> Seats:
    """DISPATCH_SEAT_* when set; else 組長 of the proposal's 所屬組別, its 經理 or any 副總/老闆, and session PMs."""
    def roster(match):
        return frozenset(directory.open_ids[ref] for ref, rank in directory.ranks.items()
                         if directory.active.get(ref) and ref in directory.open_ids
                         and match(rank, directory.groups.get(ref, frozenset())))

    def ours(groups):
        return bool(groups) if department is ANY_DEPARTMENT else department in groups

    rules = {
        Seat.GROUP_LEADER: lambda: roster(lambda rank, groups: rank == LEADER_RANK and ours(groups)),
        Seat.MANAGER_REVIEW: lambda: roster(lambda rank, groups: rank in EXECUTIVE_RANKS or (
            rank == MANAGER_RANK and ours(groups))),
        Seat.PM_FINAL: lambda: frozenset(u['id'] for u in session_users
                                         if u.get('role') == 'pm' and u.get('active', True) and isinstance(u.get('id'), str)),
    }
    holders, origin = {}, {}
    for seat in required:
        if overrides.get(seat):
            holders[seat], origin[seat] = frozenset(overrides[seat]), 'env'
        else:
            holders[seat], origin[seat] = rules[seat](), 'session' if seat is Seat.PM_FINAL else 'roster'
    names = {u['id']: text(u.get('name')).strip() or None for u in session_users if isinstance(u.get('id'), str)}
    return Seats(holders, origin, names)


def standing(decisions, seats: Seats):
    """Decisions that still count: an acceptance only while its actor holds the seat, a return always."""
    return [d for d in decisions if d['decision'] == Decision.RETURNED
            or d['actor_id'] in seats.holders.get(Seat(d['seat']), ())]


def seat_board(required, seats: Seats, decisions, directory: Directory):
    """Seat status for one hash, in approval order, plus the blockers that keep it from publishing."""
    valid = standing(decisions, seats)
    by_seat = {d['seat']: d for d in valid}
    board, blockers = [], []
    for seat in required:
        found = by_seat.get(seat.value)
        people = seats.people(seat, directory)
        board.append({'seat': seat.value, 'holders': [p['person_ref'] for p in people if p['person_ref']],
                      'names': [p['name'] for p in people if p['name']], 'people': people,
                      'configured': bool(people), 'source': seats.origin.get(seat),
                      'decision': found['decision'] if found else None, 'actor': found['actor_id'] if found else None,
                      'reason': found['reason'] if found else None, 'at': found['at'] if found else None})
    unconfigured = [seat.value for seat in required if not seats.holders.get(seat)]
    if unconfigured:
        blockers += ['approval_not_configured'] + [f'approval_not_configured:{seat}' for seat in unconfigured]
    if any(d['decision'] == Decision.RETURNED for d in valid):
        blockers.append('approval_returned')
    lapsed = {d['seat'] for d in decisions} - set(by_seat)
    blockers += [f'decision_holder_changed:{seat.value}' for seat in required if seat.value in lapsed]
    blockers += [f"approval_missing:{s['seat']}" for s in board if s['decision'] != Decision.ACCEPTED]
    return board, blockers


def next_seat(required, decisions):
    decided = {d['seat'] for d in decisions}
    return next((seat for seat in required if seat.value not in decided), None)


def decision_refusal(seat: Seat, actor, required, seats: Seats, decisions, proposers):
    """Why this actor may not decide this seat now, or None."""
    if seat not in required:
        return 'seat_not_required'
    if seat in PROPOSER_EXCLUDED and actor in proposers:
        return 'own_preview'
    if actor not in seats.holders.get(seat, ()):
        return 'not_seat_holder'
    decisions = standing(decisions, seats)
    if any(d['decision'] == Decision.RETURNED for d in decisions):
        return 'hash_returned'
    if any(d['seat'] == seat.value for d in decisions):
        return 'seat_already_decided'
    if any(d['actor_id'] == actor for d in decisions):
        return 'actor_holds_another_seat'
    if next_seat(required, decisions) is not seat:
        return 'earlier_seat_pending'
    return None


# 任務 payload

TASK_SPEC = {
    '標題': Kind.TEXT, '內容': Kind.TEXT, '負責人': Kind.USERS, '指派人': Kind.USERS, '截止日': Kind.DATE,
    '部門': Kind.SELECT, '狀態': Kind.SELECT, '專案編號': Kind.TEXT, '工程確認單': Kind.LINK, '任務階段': Kind.SELECT,
    '任務種類': Kind.SELECT, '工作包編號': Kind.TEXT, '父義務': Kind.LINK, '預定開始': Kind.DATE, '預定結束': Kind.DATE,
    '預估人時': Kind.NUMBER, '組員': Kind.USERS, '使用儀器': Kind.LINK, '使用車輛': Kind.LINK, '排程狀態': Kind.SELECT,
    '排程版本': Kind.NUMBER, '命令編號': Kind.TEXT, '讀回時間': Kind.DATE,
}
WRITABLE = frozenset(TASK_SPEC)


def task_fields(proposal: Proposal, directory: Directory, *, actor_open_id, command_id, revision, now_ms, create):
    """The complete 任務 field set one command writes; None clears a cell on update."""
    users = lambda refs: [{'id': directory.open_ids[ref]} for ref in refs]
    fields = {
        '標題': proposal.title, '內容': proposal.content or None, '負責人': users([proposal.primary_owner]),
        '指派人': [{'id': actor_open_id}], '截止日': millis(datetime.combine(proposal.deadline, datetime.min.time(), TZ))
        if proposal.deadline else None, '部門': proposal.department, '專案編號': proposal.project_ref,
        '工程確認單': [proposal.case_ref] if proposal.case_ref else None,
        '任務階段': PHASE_LABEL[proposal.phase] if proposal.phase else None, '任務種類': KIND_LABEL[proposal.kind],
        '工作包編號': proposal.package_id, '父義務': [proposal.parent_task_ref] if proposal.parent_task_ref else None,
        '預定開始': millis(proposal.start), '預定結束': millis(proposal.end),
        '預估人時': proposal.est_person_hours if proposal.est_person_hours is not None else proposal.booked_person_hours,
        '組員': users(proposal.crew[1:]) or None, '使用儀器': list(proposal.instruments) or None,
        '使用車輛': list(proposal.vehicles) or None, '排程狀態': PLANNING_LABEL[PlanningStatus.CONFIRMED],
        '排程版本': revision, '命令編號': command_id, '讀回時間': now_ms,
    }
    if create:
        fields['狀態'] = '待處理'
        fields = {name: value for name, value in fields.items() if value is not None}
    assert set(fields) <= WRITABLE
    return fields


def _canon(kind, raw):
    # node_assignment's canon rounds dates to the minute; dispatch writes and compares epoch milliseconds.
    if kind is Kind.DATE:
        return raw if type(raw) is int else None
    found = canon(kind, raw)
    return list(found) if isinstance(found, tuple) else found


def mismatches(written, fields):
    return sorted(name for name, value in written.items() if _canon(TASK_SPEC[name], fields.get(name)) != _canon(TASK_SPEC[name], value))


def snapshot(fields):
    """Every field a command may write, in comparable form: the row as a command found it."""
    return {name: _canon(kind, fields.get(name)) for name, kind in TASK_SPEC.items()}


def changed(before, fields):
    now = snapshot(fields)
    return sorted(name for name in TASK_SPEC if before.get(name) != now[name])


# PM work queue


def _iso(value):
    found = from_millis(value)
    return found.isoformat(timespec='minutes') if found else None


def _labels(refs, index, label):
    return [{'ref': ref, 'label': text(index.get(ref, {}).get(label)).strip() or None} for ref in refs]


def task_row(record, sources: Sources, directory: Directory):
    """One V4 任務 row in the work-queue shape, before workbench overlays."""
    fields, rid = record['fields'], record['record_id']
    cases, nodes = sources.index('cases'), sources.index('nodes')
    case_ref = next(iter(link_ids(fields.get('工程確認單'))), None)
    case = None
    if case_ref:
        found = cases.get(case_ref)
        case = {'ref': case_ref, 'code': text((found or {}).get('工程確認單編號')).strip() or None,
                'name': text((found or {}).get('工程名稱')).strip() or None, 'resolved': found is not None}
    node_ref = next(iter(link_ids(fields.get('節點指派'))), None)
    owner = next(iter(task_users(fields, '負責人')), None)
    crew_users = list(dict.fromkeys(task_users(fields, '負責人') + task_users(fields, '組員')))
    span = task_interval(fields)
    status_label = text(fields.get('排程狀態')).strip()
    kind = {v: k for k, v in KIND_LABEL.items()}.get(text(fields.get('任務種類')).strip())
    phase = {v: k for k, v in PHASE_LABEL.items()}.get(text(fields.get('任務階段')).strip())
    revision = fields.get('排程版本')
    hours = fields.get('預估人時')
    return {
        'task_id': rid, 'title': text(fields.get('標題')).strip(), 'content': text(fields.get('內容')),
        'case': case, 'project_id': text(fields.get('專案編號')).strip() or None,
        'package_id': text(fields.get('工作包編號')).strip() or None,
        'parent_task_ref': next(iter(link_ids(fields.get('父義務'))), None),
        'kind': kind.value if kind else None, 'phase': phase.value if phase else None,
        'node': {'record_id': node_ref, 'label': text(nodes.get(node_ref, {}).get('節點')).strip() or None} if node_ref else None,
        'department': text(fields.get('部門')).strip() or None,
        'status': text(fields.get('狀態')).strip() or None,
        'planning_status': (PLANNING_OF_LABEL.get(status_label) or PlanningStatus.UNASSIGNED).value,
        'acceptance_status': text(fields.get('成果接受狀態')).strip() or None,
        'acceptance_summary': text(fields.get('接受摘要')).strip() or None,
        'owner': directory.person(*owner) if owner else None,
        'crew': [directory.person(*user) for user in crew_users],
        'assigned_by': next((directory.person(*u) for u in task_users(fields, '指派人')), None),
        'interval': span.public() if span else None,
        'instruments': _labels(link_ids(fields.get('使用儀器')), sources.index('instruments'), '儀器名稱'),
        'vehicles': _labels(link_ids(fields.get('使用車輛')), sources.index('vehicles'), '車牌'),
        'deadline': (from_millis(fields.get('截止日')).date().isoformat() if type(fields.get('截止日')) is int else None),
        'est_person_hours': hours if type(hours) in (int, float) else None,
        'revision': int(revision) if type(revision) in (int, float) else None,
        'versions': {'scope': fields.get('範圍版本'), 'rule': text(fields.get('規則版本')).strip() or None,
                     'evidence': text(fields.get('證據版本')).strip() or None},
        'command_ref': text(fields.get('命令編號')).strip() or None, 'readback_at': _iso(fields.get('讀回時間')),
        'source': 'v4_task',
    }


def proposal_row(proposal: dict, directory: Directory, source):
    """A not-yet-published proposal (draft, preview or create command) in the work-queue shape."""
    people = lambda refs: [{'person_ref': ref, 'open_id': directory.open_ids.get(ref), 'name': directory.names.get(ref)}
                           for ref in refs if isinstance(ref, str)]
    crew = people([proposal.get('primary_owner')] + list(proposal.get('crew') or []))
    crew = list({p['person_ref']: p for p in crew}.values())
    start, end = proposal.get('start'), proposal.get('end')
    return {
        'task_id': proposal.get('task_id'), 'title': proposal.get('title') or '', 'content': proposal.get('content') or '',
        'case': {'ref': proposal['case_ref'], 'code': None, 'name': None, 'resolved': False} if proposal.get('case_ref') else None,
        'project_id': proposal.get('project_ref'), 'package_id': proposal.get('package_id'),
        'parent_task_ref': proposal.get('parent_task_ref'), 'kind': proposal.get('kind'), 'phase': proposal.get('phase'),
        'node': None, 'department': proposal.get('department'), 'status': None,
        'planning_status': PlanningStatus.DRAFT.value, 'acceptance_status': None, 'acceptance_summary': None,
        'owner': crew[0] if proposal.get('primary_owner') and crew else None, 'crew': crew, 'assigned_by': None,
        'interval': {'start': start, 'end': end, 'precision': 'datetime'} if start and end else None,
        'instruments': [{'ref': r, 'label': None} for r in proposal.get('instruments') or []],
        'vehicles': [{'ref': r, 'label': None} for r in proposal.get('vehicles') or []],
        'deadline': proposal.get('deadline'), 'est_person_hours': proposal.get('est_person_hours'), 'revision': None,
        'versions': {'scope': None, 'rule': None, 'evidence': None}, 'command_ref': None, 'readback_at': None,
        'source': source,
    }


@dataclass(frozen=True)
class Viewer:
    open_id: str
    can_dispatch: bool
    is_manager: bool


@dataclass(frozen=True)
class Overlay:
    """Workbench facts keyed for the join: latest command per task, open approvals, drafts."""
    commands: list
    approvals: list
    drafts: list


def _overlay_row(row, viewer: Viewer, *, command=None, approval=None, draft=None, required=(), seats_for=None,
                 allow_unknown=False, reconcilable=frozenset()):
    needs, planning = [], PlanningStatus(row['planning_status'])
    if draft is not None:
        row['draft_id'] = draft['id']
        planning = PlanningStatus.DRAFT
    if approval is not None:
        row['preview_id'] = approval['preview_id']
        decisions = approval['decisions']
        returned = any(d['decision'] == Decision.RETURNED for d in decisions)
        planning = PlanningStatus.DRAFT if returned else PlanningStatus.PENDING_APPROVAL
        seat = next_seat(required, decisions)
        # Approving a hash that still has feasibility blockers is wasted: fixing them changes the hash.
        if (not returned and seat and not approval['blockers'] and decision_refusal(
                seat, viewer.open_id, required, seats_for(approval['proposal']), decisions,
                {approval['actor_id']}) is None):
            needs.append(f'approve_seat:{seat.value}')
        if approval['actor_id'] == viewer.open_id:
            if returned:
                needs.append('review_returned')
            if not allow_unknown:
                needs += [f"verify_unknown:{code.split(':', 1)[1]}" for code in approval['blockers'] if code.startswith('unknown:')]
    if command is not None:
        state = CommandResult(command['state'])
        row['command'] = {'command_id': command['command_id'], 'state': state.value, 'label': COMMAND_LABEL[state]}
        if state in IN_FLIGHT:
            planning = COMMAND_PLANNING[state]
            if viewer.is_manager and command['command_id'] in reconcilable:
                needs.append('reconcile_command')
    row['planning_status'] = planning.value
    in_flight = command is not None and CommandResult(command['state']) in IN_FLIGHT
    if (planning is PlanningStatus.UNASSIGNED and row['source'] == 'v4_task' and viewer.can_dispatch
            and viewer.open_id in {p['open_id'] for p in [row['owner'], row['assigned_by']] if p}):
        needs.append('confirm_assignment')
    actions = []
    if viewer.can_dispatch and not in_flight:
        if planning in (PlanningStatus.UNASSIGNED, PlanningStatus.DRAFT) and row['source'] != 'workbench_preview':
            actions.append('assign')
        if planning is PlanningStatus.CONFIRMED:
            actions.append('reassign')
        if row['source'] in ('v4_task', 'workbench_draft'):
            actions.append('edit_detail')
    if any(n.startswith('approve_seat:') for n in needs):
        actions += ['approve', 'return']
    if 'reconcile_command' in needs:
        actions.append('reconcile')
    if draft is not None and draft['actor_id'] == viewer.open_id:
        actions.append('cancel_draft')
    row.setdefault('command', None)
    row.setdefault('preview_id', None)
    row.setdefault('draft_id', None)
    row['needs_me'] = needs
    row['allowed_actions'] = actions
    return row


def build_work(sources: Sources, overlay: Overlay, viewer: Viewer, *, required, seats_for, allow_unknown,
               reconcilable, window=None, group=None, scope='all'):
    """seats_for(proposal dict) -> Seats for that proposal's department."""
    directory = Directory.of(sources)
    order = lambda c: (c['created_at'], c['revision'], c['updated_at'])
    latest_command, by_id = {}, {}
    for command in sorted(overlay.commands, key=order):
        latest_command[command['task_id'] or ('preview', command['preview_hash'])] = command
        by_id[command['command_id']] = command
    approvals, drafts, gaps = {}, {}, []
    for approval in sorted(overlay.approvals, key=lambda a: a['created_at']):
        approvals[approval['task_id'] or ('draft', approval['draft_id'] or approval['preview_hash'])] = approval
    for draft in overlay.drafts:
        try:
            check_draft(draft['proposal'])
        except Refusal as exc:
            gaps.append({'code': 'invalid_draft', 'draft_id': draft['id'], 'field': exc.extra.get('field')})
            continue
        drafts[draft['task_id'] or ('draft', draft['id'])] = draft
    options = dict(required=required, seats_for=seats_for, allow_unknown=allow_unknown, reconcilable=reconcilable)
    rows = []
    for record in sources.tasks or []:
        rid = record['record_id']
        found = [latest_command.pop(rid, None)]
        # A create whose response was lost has no local task id; the row it landed carries its 命令編號.
        landed = by_id.get(text(record['fields'].get('命令編號')).strip())
        if landed is not None and landed['task_id'] is None:
            key = ('preview', landed['preview_hash'])
            if latest_command.get(key) is landed:
                found.append(latest_command.pop(key))
            approvals = {k: a for k, a in approvals.items() if a['preview_hash'] != landed['preview_hash']}
        command = max((c for c in found if c is not None), key=order, default=None)
        approval = approvals.pop(rid, None)
        if approval is not None and command is not None and command['preview_hash'] == approval['preview_hash']:
            approval = None
        rows.append(_overlay_row(task_row(record, sources, directory), viewer, command=command, approval=approval,
                                 draft=drafts.pop(rid, None), **options))
    # Work that has no V4 row yet: create commands still in flight, open approvals, then drafts.
    for key, command in latest_command.items():
        if command['task_id'] is None and CommandResult(command['state']) in IN_FLIGHT:
            rows.append(_overlay_row(proposal_row(command['proposal'], directory, 'workbench_command'), viewer,
                                     command=command, **options))
            approvals = {k: a for k, a in approvals.items() if a['preview_hash'] != command['preview_hash']}
    for key, approval in approvals.items():
        if approval['task_id'] is None:
            draft = drafts.pop(('draft', approval['draft_id']), None) if approval['draft_id'] else None
            rows.append(_overlay_row(proposal_row(approval['proposal'], directory, 'workbench_preview'), viewer,
                                     approval=approval, draft=draft, **options))
    for key, draft in drafts.items():
        if draft['task_id'] is None:
            rows.append(_overlay_row(proposal_row(draft['proposal'], directory, 'workbench_draft'), viewer,
                                     draft=draft, **options))
    rows = [row for row in rows if _visible(row, viewer, window, group, scope)]
    rows.sort(key=lambda r: (not r['needs_me'], (r['interval'] or {}).get('start') or '9999', r['title'], r['task_id'] or ''))
    status_counts, planning_counts = {}, {}
    for row in rows:
        status_counts[row['status'] or 'unknown'] = status_counts.get(row['status'] or 'unknown', 0) + 1
        planning_counts[row['planning_status']] = planning_counts.get(row['planning_status'], 0) + 1
    return {'progress': {'total': len(rows), 'status': status_counts, 'planning_status': planning_counts,
                         'needs_me': sum(1 for r in rows if r['needs_me'])},
            'needs_me': [row for row in rows if row['needs_me']], 'rows': rows, 'gaps': gaps}


def _visible(row, viewer: Viewer, window, group, scope):
    if window is not None and row['interval']:
        start = row['interval']['start'][:10]
        end = row['interval']['end'][:10]
        if end < window[0].isoformat() or start > window[1].isoformat():
            return False
    if group is not None and row['department'] != group:
        return False
    if scope == 'mine':
        people = {p['open_id'] for p in row['crew'] + [row['owner']] if p}
        return bool(row['needs_me']) or viewer.open_id in people
    return True
