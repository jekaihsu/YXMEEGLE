"""Weekly projection of existing roster and read-only Lark attendance evidence."""
from datetime import date, datetime, timedelta
from ..status import TAIPEI
from ..client import ReadFailure
from ...attendance_identity import AttendanceIdentityResolver

PERSON_FIELDS = ('id', 'name', 'group', 'in_service')


def week_window(value=None, *, now=None):
    day = date.fromisoformat(value) if value else (now or datetime.now(TAIPEI)).astimezone(TAIPEI).date()
    monday = day - timedelta(days=day.weekday())
    return [(monday + timedelta(days=i)).isoformat() for i in range(7)]


def project_people(users, app_id):
    result = []
    for user in users:
        source = user.get('directory_source') or {}
        if source.get('app_id') != app_id or user.get('directory_missing'):
            continue
        status = user.get('directory_status')
        group = user.get('department') or None
        if user.get('department_source') in ('unknown', 'work_category_unmapped'):
            group = None
        result.append(dict(id=user['id'], name=user.get('name') or None,
                           group=group,
                           in_service=True if status == 'employed' else False if status == 'left' else None))
    return sorted(result, key=lambda p: (p['group'] or '', p['name'] or '', p['id']))


def empty_view(days):
    return dict(week_start=days[0], week_end=days[-1], days=days, people=[], trips=[],
                summary=dict(people=None, in_service=None, on_leave=None, on_trip=None, trips=None),
                status='incomplete', as_of=None, missing_scopes=[], issues=[])


def require_list(data, key):
    value = data.get(key)
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ReadFailure('Attendance response is incomplete')
    return value


def evidence_day(value):
    raw = str(value or '')
    if len(raw) == 8 and raw.isdigit():
        raw = raw[:4] + '-' + raw[4:6] + '-' + raw[6:]
    try:
        return date.fromisoformat(raw[:10]).isoformat()
    except ValueError:
        return None


def day_labels(records):
    labels = set()
    known = {'Normal': '到班', 'SystemCheck': '到班', 'Late': '遲到', 'Early': '早退',
             'Lack': '缺卡', 'NoNeedCheck': '免打卡'}
    supplements = {'Leave': '請假', 'Travel': '出差', 'GoOut': '外出'}
    for record in records:
        if not isinstance(record, dict):
            continue
        for side in ('check_in', 'check_out'):
            result = record.get(side + '_result')
            supplement = record.get(side + '_result_supplement')
            if supplement in supplements:
                labels.add(supplements[supplement])
            elif supplement in ('CardReplacement', 'CardReplacementApplication', 'ManagerModification'):
                labels.add('補卡／修正')
            elif result in known:
                labels.add(known[result])
    return '、'.join(sorted(labels)) or None


def fetch_week(adapter, users, app_id, tenant, days, roster_complete):
    people = project_people(users, app_id)
    view = empty_view(days)
    view['people'] = [dict(p, attendance=[None] * 7) for p in people]
    issues = []
    employed = [p for p in people if p['in_service'] is True]
    subjects = [dict(id=p['id'], identity_app_id=app_id) for p in employed]
    identities = AttendanceIdentityResolver(adapter, app_id, tenant, lambda: None).fetch(subjects)
    issues.extend(identities['issues'])
    # Groups are metadata only. Without group detail/department expansion, do not
    # infer who is required to punch or publish an attendance-rate denominator.
    groups = []
    cursor = None
    seen = set()
    for _ in range(100):
        page = adapter.request('GET', '/attendance/v1/groups', params=dict(page_size=50, **({'page_token': cursor} if cursor else {})))
        groups.extend(require_list(page, 'group_list'))
        if page.get('has_more') is False:
            break
        cursor = page.get('page_token')
        if page.get('has_more') is not True or not isinstance(cursor, str) or not cursor or cursor in seen:
            raise ReadFailure('Attendance group pagination is incomplete')
        seen.add(cursor)
    else:
        raise ReadFailure('Attendance group pagination exceeded limit')
    mapping = {p['employee_id']: oid for oid, p in identities['mappings'].items()}
    tasks, approvals, invalid = [], [], set()
    ids = list(mapping)
    for offset in range(0, len(ids), 50):
        batch = ids[offset:offset+50]
        body = dict(user_ids=batch, check_date_from=int(days[0].replace('-', '')), check_date_to=int(days[-1].replace('-', '')))
        query = {'employee_type': 'employee_id'}
        data = adapter.request('POST', '/attendance/v1/user_tasks/query', params=query, json=dict(body, ignore_invalid_users=True))
        tasks.extend(require_list(data, 'user_task_results'))
        for key in ('invalid_user_ids', 'unauthorized_user_ids'):
            if not isinstance(data.get(key, []), list):
                raise ReadFailure('Attendance invalid-user response is incomplete')
            invalid.update(data.get(key, []))
        data = adapter.request('POST', '/attendance/v1/user_approvals/query', params=query, json=body)
        approvals.extend(require_list(data, 'user_approvals'))
    by_id = {p['id']: p for p in view['people']}
    for task in tasks:
        employee = task.get('user_id')
        if employee not in mapping:
            raise ReadFailure('Attendance returned an unrequested identity')
        day = evidence_day(task.get('day'))
        if day not in days or not isinstance(task.get('records'), list):
            issues.append({'reason': 'unread_task'}); continue
        if employee not in invalid:
            person = by_id[mapping[employee]]
            i = days.index(day)
            label = day_labels(task['records'])
            if label:
                person['attendance'][i] = '、'.join(sorted(set((person['attendance'][i] or '').split('、') + label.split('、')) - {''}))
    unique = {}
    leave_people, trip_people = set(), set()
    for row in approvals:
        employee = row.get('user_id')
        if employee not in mapping:
            raise ReadFailure('Attendance approval returned an unrequested identity')
        person = by_id[mapping[employee]]
        for key, kind in (('trips', 'trip'), ('outs', 'out'), ('leaves', 'leave')):
            items = row.get(key, [])
            if not isinstance(items, list):
                raise ReadFailure('Attendance approvals are incomplete')
            for item in items:
                if not isinstance(item, dict):
                    raise ReadFailure('Attendance approval is incomplete')
                start, end = evidence_day(item.get('start_time')), evidence_day(item.get('end_time'))
                if not start or not end or end < start:
                    issues.append({'reason': 'unread_approval'}); continue
                if end > start and str(item.get('end_time', '')).endswith('00:00:00'):
                    end = (date.fromisoformat(end) - timedelta(days=1)).isoformat()
                covered = [d for d in days if start <= d <= end]
                if not covered:
                    continue
                if employee in invalid:
                    continue
                if kind == 'leave':
                    leave_people.add(person['id'])
                if kind == 'trip':
                    trip_people.add(person['id'])
                # Leave durations and punch obligations are deliberately not inferred.
                if kind != 'leave':
                    ident = str(item.get('approval_id') or item.get('uniq_id') or f'{start}|{end}')
                    unique[(employee, kind, ident)] = dict(person_id=person['id'], name=person['name'], group=person['group'], kind=kind, start=start, end=end)
    issues.extend({'reason': 'invalid_attendance_identity', 'user_id': mapping[e]} for e in invalid if e in mapping)
    if not roster_complete:
        issues.append({'reason': 'roster_incomplete'})
    if any(p['group'] is None or p['in_service'] is None for p in people):
        issues.append({'reason': 'roster_fields_unverified'})
    today = datetime.now(TAIPEI).date().isoformat()
    if any(p['in_service'] is True and any(d <= today and p['attendance'][i] is None for i, d in enumerate(days)) for p in view['people']):
        issues.append({'reason': 'attendance_evidence_incomplete'})
    view.update(status='incomplete' if issues else 'ok', issues=issues, trips=sorted(unique.values(), key=lambda t: (t['start'], t['name'] or '')))
    roster_known = roster_complete and all(p['in_service'] is not None for p in people)
    approvals_known = roster_known and not identities['issues'] and not invalid and not any(i['reason'] == 'unread_approval' for i in issues)
    view['summary'] = dict(people=len(people) if roster_complete else None,
                           in_service=len(employed) if roster_known else None,
                           on_leave=len(leave_people) if approvals_known else None,
                           on_trip=len(trip_people) if approvals_known else None,
                           trips=sum(t['kind'] == 'trip' for t in unique.values()) if approvals_known else None)
    return view
