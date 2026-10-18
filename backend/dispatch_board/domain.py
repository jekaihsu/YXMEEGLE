"""Pure V4 schedule projection. Unknown checks never become availability evidence."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import StrEnum
from typing import Literal, TypedDict

from ..sources import link_ids, text
from .config import TABLES

TZ = timezone(timedelta(hours=8))


class Feasibility(StrEnum):
    FEASIBLE = 'feasible'
    CONFLICT = 'conflict'
    UNAVAILABLE = 'unavailable'
    UNKNOWN = 'unknown'


class PlanningStatus(StrEnum):
    UNASSIGNED = 'unassigned'
    CONFIRMED = 'confirmed'


class RawRow(TypedDict):
    record_id: str
    fields: dict


class Crew(TypedDict):
    person_ref: str
    name: str | None
    active: bool | None
    feasibility: Feasibility
    reasons: list[str]


class Resource(TypedDict):
    kind: Literal['instrument', 'vehicle']
    ref: str
    label: str | None
    feasibility: Feasibility
    reasons: list[str]


class Slot(TypedDict):
    slot_id: str
    record_id: str
    kind: Literal['work', 'leave', 'standby', 'support', 'unknown']
    planning_status: PlanningStatus
    provenance: Literal['v4_row']
    interval: dict
    group: str | None
    discipline: str | None
    case: dict | None
    work_content: str | None
    crew: list[Crew]
    resources: list[Resource]
    gaps: list[str]
    issues: list[str]


@dataclass(frozen=True)
class Window:
    start: date
    end: date
    group: str | None = None

    def __post_init__(self):
        if self.start > self.end or (self.end - self.start).days >= 62:
            raise ValueError('window must contain between 1 and 62 days')

    def days(self):
        return [(self.start + timedelta(days=i)).isoformat()
                for i in range((self.end - self.start).days + 1)]


@dataclass(frozen=True)
class Interval:
    start: datetime
    end: datetime
    precision: Literal['date', 'datetime']

    def public(self):
        def render(value):
            return value.date().isoformat() if self.precision == 'date' else value.isoformat(timespec='seconds')
        return {'start': render(self.start), 'end': render(self.end), 'precision': self.precision}

    def on(self, day):
        parsed = date.fromisoformat(day)
        if self.precision == 'date':
            return self.start.date() <= parsed <= self.end.date()
        low = datetime.combine(parsed, time.min, TZ)
        return self.start < low + timedelta(days=1) and self.end > low


@dataclass(frozen=True)
class BoardInput:
    schedule: list[RawRow]
    people: list[RawRow] | None
    instruments: list[RawRow] | None
    vehicles: list[RawRow] | None
    cases: list[RawRow] | None
    fetched_at: str


def _date(raw):
    try:
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            return datetime.fromtimestamp(raw / 1000, TZ)
        if isinstance(raw, str):
            parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
            return parsed.replace(tzinfo=TZ) if parsed.tzinfo is None else parsed.astimezone(TZ)
    except (ValueError, OverflowError, OSError):
        pass
    return None


def _interval(fields):
    start = _date(fields.get('開始日期'))
    if start is None:
        return None
    raw_end = fields.get('結束日期')
    end = _date(raw_end) if raw_end is not None else start
    if end is None or end < start:
        return None
    # Midnight values carry no evidence of a time of day in this V4 source.
    precision = 'date' if start.time() == time.min and end.time() == time.min else 'datetime'
    return Interval(start, end, precision)


def _label(fields, name):
    return text(fields.get(name)).strip() or None


def _refs(raw):
    return list(dict.fromkeys(link_ids(raw)))


def _index(rows):
    return {row['record_id']: row['fields'] for row in rows or []}


def _same_day(left, right, days):
    return any(left.on(day) and right.on(day) for day in days)


def build_board(data: BoardInput, window: Window) -> dict:
    joins = {key: 'ok' if getattr(data, key) is not None else 'unavailable'
             for key in ('people', 'instruments', 'vehicles', 'cases')}
    indices = {key: _index(getattr(data, key)) for key in joins}
    days = window.days()
    slots: list[Slot] = []
    intervals = {}
    invalid_dates = 0
    latest = None

    def resolve(key, ref):
        fields = indices[key].get(ref)
        if (fields is None or any(name not in fields for name in TABLES[key].fields)) and joins[key] == 'ok':
            joins[key] = 'partial'
        return fields or {}

    for row in sorted(data.schedule, key=lambda r: r['record_id']):
        fields = row['fields']
        interval = _interval(fields)
        if interval is None:
            invalid_dates += 1
            continue
        end_day = interval.end.date()
        latest = max(latest, end_day) if latest else end_day
        if not any(interval.on(day) for day in days):
            continue
        group = _label(fields, '組別')
        if window.group and group != window.group:
            continue
        kind = {'出工': 'work', '休假': 'leave', '待命': 'standby', '支援': 'support'}.get(text(fields.get('條類型')), 'unknown')
        people, instruments, vehicles, cases = (_refs(fields.get(name)) for name in ('人員', '儀器', '車輛', '案件'))
        gaps = []
        if kind == 'work':
            if not people:
                gaps.append('no_crew')
            if not cases and _label(fields, '業別') in ('外業', '內業'):
                gaps.append('no_case')
            if _label(fields, '業別') == '外業' and not instruments:
                gaps.append('no_instrument_for_field_work')
        crew = []
        for ref in people:
            person = resolve('people', ref)
            active = person.get('在職') if type(person.get('在職')) is bool else None
            crew.append(Crew(person_ref=ref, name=_label(person, '姓名'), active=active,
                             feasibility=Feasibility.UNAVAILABLE if active is False else Feasibility.UNKNOWN,
                             reasons=(['inactive'] if active is False else []) + ['no_leave_source', 'no_capability_source']))
        resources = []
        for resource_kind, key, refs, label in (('instrument', 'instruments', instruments, '儀器名稱'),
                                                ('vehicle', 'vehicles', vehicles, '車牌')):
            for ref in refs:
                resource = resolve(key, ref)
                reasons = []
                if resource.get('啟用') is False:
                    reasons.append('inactive')
                status = _label(resource, '狀態') if resource_kind == 'instrument' else None
                if status and status != '正常':
                    reasons.append('repair' if status == '送修-損壞' else 'abnormal_status')
                known = resource.get('啟用') is True and (resource_kind == 'vehicle' or status == '正常')
                feasibility = Feasibility.UNAVAILABLE if reasons else Feasibility.FEASIBLE if known else Feasibility.UNKNOWN
                resources.append(Resource(kind=resource_kind, ref=ref, label=_label(resource, label),
                                          feasibility=feasibility, reasons=reasons or ([] if known else ['resource_status_unknown'])))
        case = None
        if cases:
            case_fields = resolve('cases', cases[0]) if len(cases) == 1 else {}
            # Explicit foreign-table links cannot be reinterpreted as V4 confirmation identities.
            raw_case = fields.get('案件')
            entries = raw_case if isinstance(raw_case, list) else [raw_case]
            if len(cases) != 1 or any(isinstance(v, dict) and v.get('table_id') not in (None, TABLES['cases'].table_id) for v in entries):
                case_fields = {}
                if joins['cases'] == 'ok':
                    joins['cases'] = 'partial'
            case = {'ref': cases[0], 'code': _label(case_fields, '工程確認單編號'), 'name': _label(case_fields, '工程名稱')}
        ident = f"v4:{TABLES['schedule'].table_id}:{row['record_id']}"
        slots.append(Slot(slot_id=ident, record_id=row['record_id'], kind=kind,
                          planning_status=PlanningStatus.UNASSIGNED if 'no_crew' in gaps else PlanningStatus.CONFIRMED,
                          provenance='v4_row', interval=interval.public(), group=group,
                          discipline=_label(fields, '業別'), case=case, work_content=_label(fields, '工作內容'),
                          crew=crew, resources=resources, gaps=gaps, issues=[]))
        intervals[ident] = interval

    bookings = {}
    for slot in slots:
        for member in slot['crew']:
            bookings.setdefault(('person', member['person_ref']), []).append((slot, member))
        for resource in slot['resources']:
            bookings.setdefault((resource['kind'], resource['ref']), []).append((slot, resource))
    for booked in bookings.values():
        for i, (left, left_member) in enumerate(booked):
            for right, right_member in booked[i + 1:]:
                a, b = intervals[left['slot_id']], intervals[right['slot_id']]
                if not _same_day(a, b, days):
                    continue
                timed = a.precision == b.precision == 'datetime' and a.start < a.end and b.start < b.end
                if timed and not (a.start < b.end and b.start < a.end):
                    continue
                state = Feasibility.CONFLICT if timed else Feasibility.UNKNOWN
                reason = 'timed_overlap' if timed else 'same_day_other_slot'
                for slot, member, other in ((left, left_member, right), (right, right_member, left)):
                    if member['feasibility'] != Feasibility.UNAVAILABLE:
                        if state == Feasibility.CONFLICT or member['feasibility'] != Feasibility.CONFLICT:
                            member['feasibility'] = state
                    if reason not in member['reasons']:
                        member['reasons'].append(reason)
                    if other['slot_id'] not in slot['issues']:
                        slot['issues'].append(other['slot_id'])

    capacity = []
    refs = sorted(set(indices['people']) | {ref for kind, ref in bookings if kind == 'person'})
    for ref in refs:
        booked = bookings.get(('person', ref), [])
        if window.group and not booked:
            continue
        person = indices['people'].get(ref, {})
        per_day = {}
        for day in days:
            count = sum(intervals[slot['slot_id']].on(day) for slot, _ in booked)
            per_day[day] = {'booked_slots': count, 'state': 'overbooked_unknown' if count > 1 else 'booked' if count else 'unknown'}
        capacity.append({'person_ref': ref, 'name': _label(person, '姓名'), 'days': per_day})
    source_gaps = [
        {'code': 'no_capability_source', 'message': 'No qualification or capability source is registered.', 'count': len(slots)},
        {'code': 'no_leave_source', 'message': 'No complete leave availability source is registered.', 'count': len(slots)},
    ]
    if invalid_dates:
        source_gaps.append({'code': 'invalid_schedule_interval', 'message': 'Schedule rows without a usable interval are excluded.', 'count': invalid_dates})
    unresolved_cases = sum(1 for slot in slots if slot['case'] and slot['case']['code'] is None and slot['case']['name'] is None)
    if unresolved_cases:
        source_gaps.append({'code': 'unresolved_case_links', 'message': 'Case links do not resolve to a V4 confirmation row.', 'count': unresolved_cases})
    if latest and window.start > latest:
        source_gaps.append({'code': f'no_bookings_after_{latest.isoformat()}',
                            'message': f'No bookings after {latest.isoformat()}.', 'count': 0})
    if latest is None:
        source_gaps.append({'code': 'no_latest_booking_date', 'message': 'Latest booking date is unknown.', 'count': 0})
    queue = [slot['slot_id'] for slot in slots if slot['planning_status'] == PlanningStatus.UNASSIGNED]
    def count_issue(reason):
        return sum(any(reason in member['reasons'] for member in slot['crew'] + slot['resources']) for slot in slots)
    partial = invalid_dates or any(value != 'ok' for value in joins.values())
    return {
        'schema_version': 1, 'window': {'from': window.start.isoformat(), 'to': window.end.isoformat(), 'tz': 'Asia/Taipei'},
        'source': {'dataset_key': 'operational_schedule', 'registry_key': 'v4', 'table_id': TABLES['schedule'].table_id,
                   'fetched_at': data.fetched_at, 'latest_booking_date': latest.isoformat() if latest else None,
                   'quality': {'states': ['partial' if partial else 'complete'], 'reason': 'incomplete_source_or_joins' if partial else None},
                   'joins': joins},
        'kpi': {'slots': len(slots), 'unassigned': len(queue), 'unknown_overlap': count_issue('same_day_other_slot'), 'conflict': count_issue('timed_overlap')},
        'unassigned_queue': queue, 'slots': slots, 'capacity': {'people': capacity}, 'gaps': source_gaps,
    }
