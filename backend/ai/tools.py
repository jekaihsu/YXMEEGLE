"""Read tools reuse HTTP authorization and whitelist their model-visible fields."""
from dataclasses import dataclass
import re
import math
from typing import Callable
from urllib.parse import quote
import json

import httpx
from .ledger import today


class ReadDenied(Exception):
    def __init__(self, message):
        self.message = message


class Reader:
    def __init__(self, client, assignments_enabled=False, portfolio_enabled=False):
        self.client = client
        self.assignments_enabled = assignments_enabled
        self.portfolio_enabled = portfolio_enabled

    async def get(self, path, **params):
        response = await self.client.get(path, params=params)
        if response.status_code in (401, 403, 404):
            message = '你沒有權限查看出勤資料' if path == '/api/people/attendance' else '找不到或沒有權限查看這個案件'
            raise ReadDenied(message)
        response.raise_for_status()
        return response.json()


def pick(value, *keys):
    return {k: value[k] for k in keys if k in value}


def valid_case_id(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,200}', value) is not None and value not in ('.', '..')


def case_path(args):
    return '/api/projects/' + quote(args['case_id'], safe='')


CASE_STATUS = {'pending': '尚未開始', 'in_progress': '進行中', 'pending_review': '待審核',
               'paused': '暫停', 'completed': '已完成', 'source_conflict': '待核對'}
NODE_ORDER = ('sales', 'pm', 'confirmation', 'field', 'control', 'mapping', 'report', 'pricing', 'settlement')
NODE_STATES = {'not_started': '未開始', 'pending': '待處理', 'in_progress': '進行中',
               'pending_review': '待審核', 'awaiting_review': '待審核', 'completed': '已完成',
               'skipped': '略過', 'approved_skipped': '略過', 'paused': '暫停',
               **{s: s for s in ('未開始', '待處理', '進行中', '待審核', '已完成', '略過')}}


def calendar_day(value):
    from datetime import datetime, timedelta, timezone
    if value is None or value == '':
        return None
    try:
        if isinstance(value, (int, float)) or re.fullmatch(r'\d{13}', value.strip()):
            stamp = datetime.fromtimestamp(float(value) / 1000, timezone.utc)
        else:
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?\s*(?:[Zz]|[+-]\d{2}:?\d{2})?', value.strip()):
                return None
            stamp = datetime.fromisoformat(value.strip().upper().replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone(timedelta(hours=8)))
        return stamp.astimezone(timezone(timedelta(hours=8))).date().isoformat()
    except (ValueError, TypeError, OverflowError):
        return None


def project_state(project, day):
    source = project.get('portfolio_nodes', project.get('nodes', []))
    by_key = {n['key']: n for n in reversed(source)}
    states = [NODE_STATES.get(by_key.get(key, {}).get('status'), '狀態待確認') for key in NODE_ORDER]
    finished = {'已完成', '略過'}
    current = next((s for s in states if s not in finished), None)
    if all(s in finished for s in states):
        state = '已完成'
    elif any(s not in finished | {'未開始', '待處理', '進行中', '待審核', '暫停'} for s in states):
        state = '待核對'
    elif all(s in {'未開始', '待處理'} for s in states):
        state = '尚未開始'
    else:
        state = current if current in {'待審核', '暫停'} else '進行中'
    tasks = [t for n in project.get('nodes', []) for t in n.get('tasks', [])
             if t['status'] not in {'completed', 'superseded', 'approved_skipped'}]
    due = calendar_day(project.get('due_date'))
    closed = (project.get('execution_status') or project.get('status')) == 'completed'
    overdue = not closed and (float(project.get('overdue_tasks') or 0) > 0 or
        bool(due and due < calendar_day(day)) or any(t.get('due_date') and t['due_date'][:10] < day[:10] for t in tasks))
    return dict(state=state, overdue=bool(overdue))


async def search(reader, args):
    if reader.portfolio_enabled:
        value = await reader.get('/api/projects', view='portfolio')
        items = value['items']
    else:
        value = await reader.get('/api/workspace')
        items = value['projects']
    owner = None
    if args['owner'] == 'me':
        owner = (await reader.get('/api/session'))['user']['id']
    q = args['query'].strip().casefold()
    items = [{**p, **project_state(p, today())} for p in items]
    items = [p for p in items if
        (not q or q in ' '.join(str(p.get(k, '')) for k in ('code', 'name', 'client')).casefold()) and
        (not owner or p.get('pm_id') == owner) and (not args['overdue'] or p['overdue'])]
    counts = {key: sum(p['state'] == label for p in items) for key, label in CASE_STATUS.items()}
    counts['other'] = len(items) - sum(counts.values())
    total = len(items)
    status = CASE_STATUS.get(args['status'], args['status'])
    items = [p for p in items if status == 'all' or p['state'] == status]
    items.sort(key=lambda p: (p.get('due_date') or '9999', p['id']))
    offset = args['offset']
    return dict(total=total, matched_total=len(items), offset=offset,
                next_offset=offset+8 if offset+8 < len(items) else None,
                items=items[offset:offset+8], status_counts=counts)



async def progress(reader, args):
    value = await reader.get(case_path(args) + '/progress')
    detail = await reader.get('/api/case-detail/' + args['case_id'])
    assignment_data = (await owners(reader, args, detail=detail))['assignments']
    from .work_summary import summarize, add_sop
    value['workflow_summary'] = summarize(detail, assignment_data if reader.assignments_enabled else None)
    await add_sop(reader, args['case_id'], value['workflow_summary'])
    return value


async def owners(reader, args, *, detail=None):
    if detail is None:
        detail = await reader.get('/api/case-detail/' + args['case_id'])
    assignments = {'unavailable': True}
    if reader.assignments_enabled:
        try:
            assignments = await reader.get(case_path(args) + '/node-assignments')
        except (ReadDenied, httpx.HTTPStatusError, httpx.TimeoutException):
            pass
    return {'detail': detail, 'assignments': assignments}


async def attendance(reader, args):
    from datetime import date
    day = args['date'] or today()
    try:
        if args['range'] not in ('today', 'week') or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day):
            raise ValueError()
        target, current = date.fromisoformat(day), date.fromisoformat(today())
        if abs((target.toordinal() - target.weekday()) - (current.toordinal() - current.weekday())) > 182:
            raise ValueError()
    except (ValueError, TypeError):
        raise ReadDenied('date 請使用有效 YYYY-MM-DD 或空字串（台北日期，限目前週前後26週）') from None
    return {'range': args['range'], 'day': day, 'view': await reader.get('/api/people/attendance', week=day)}


def search_notice(data):
    count = len(data.get('cases', []))
    total = data.get('matched_total', data.get('total', count))
    if total > count:
        return dict(truncated=True, note=f'符合 {total} 筆，本頁列出 {count} 筆，起點 {data.get("offset", 0)}')
    return {}


def project_search(value):
    data = {**pick(value, 'as_of', 'matched_total', 'offset', 'next_offset'), 'total': value['total'], 'cases': [pick(p, 'id', 'code', 'name', 'status', 'state', 'overdue', 'pm_id', 'due_date')
                                              for p in value['items']]}
    data['status_counts'] = value.get('status_counts', {})
    for p in data['cases']:
        p['status_label'] = p['state']
    return {**data, **search_notice(data)}


STAGE_STATES = {'done': '完成（依 basis 判斷是否為規則推導）', 'verified': '已確認', 'active': '有進行訊號', 'waiting': '等待前置條件', 'unknown': '無法確認', 'none': '無資料'}


PRODUCTION = ('field', 'control', 'mapping', 'report')
GAPS = {'no_confirmation', 'confirmation_status_conflict', 'fill_items_unknown', 'plan_unavailable',
        'plan_truncated', 'items_unlinked', 'items_ambiguous', 'no_daily_linked', 'v3_ambiguous',
        'v3_none', 'v3_no_activity', 'reports_cold', 'reports_unavailable', 'reports_disabled', 'reports_stale'}


def project_progress(value):
    return dict(project_id=value['project_id'], as_of=value.get('as_of'),
                workflow_summary=value.get('workflow_summary'),
                stages=[dict(**pick(s, 'key', 'label', 'state', 'basis'), state_label=STAGE_STATES.get(s['state'], '狀態待確認')) for s in value['stages']
                        if s.get('key') in ('sales', 'pm', 'confirmation', *PRODUCTION)],
                nodes={k: pick(value['production'][k].get('progress') or {},
                               'items_done', 'items_total', 'percent', 'unknown_items', 'basis')
                       for k in PRODUCTION if k in value['production']},
                gaps=[pick(g, 'id', 'message_zh') for g in value['gaps'] if g['id'] in GAPS])


def project_owners(value):
    detail, assignments = value['detail'], value['assignments']
    pm = detail['header']['pm']
    unavailable = assignments.get('unavailable', False)
    result = dict(project_id=detail['header']['details']['case_identity'],
                pm=dict(id=pm.get('id'), name=pm['name'] or 'name_unavailable'),
                node_assignment_status='node assignment data unavailable' if unavailable else 'available',
                nodes=None if unavailable else [dict(key=n['key'], label=n['label'],
                    owners=[pick(p, 'id', 'open_id', 'name') for p in n['owners']])
                    for n in assignments.get('nodes', [])],
                incomplete=unavailable or assignments.get('stale', False))
    case_time = detail.get('sections', {}).get('overview', {}).get('source_time', {}).get('value')
    if case_time:
        result['as_of'] = case_time
    if assignments.get('fetched_at'):
        result['node_assignments_as_of'] = assignments['fetched_at']
    return result


ATTENDANCE_LABELS = {'unaccounted': '沒有打卡紀錄', 'late': '遲到', 'missing_punch': '缺卡',
    'on_leave': '請假', 'trip': '出差', 'out': '外出', 'early_leave': '早退',
    'exempt': '免打卡', 'supplemented': '補卡／修正'}


def attendance_day(view, day):
    from datetime import date
    days = view.get('days', [])
    column = days.index(day) if day in days else None
    groups = {key: [] for key in ATTENDANCE_LABELS}
    approvals = {key: set() for key in ('on_leave', 'trip', 'out')}
    for kind, records in (('on_leave', view.get('leaves', [])), ('trip', view.get('trips', []))):
        for record in records:
            if record['start'] <= day <= record['end']:
                approvals[record.get('kind', kind)].add(record['person_id'])
    arrived, seen = 0, set()
    working = date.fromisoformat(day).weekday() < 5 and day <= today()
    for person in view.get('people', []):
        if person.get('in_service') is not True or person['id'] in seen:
            continue
        seen.add(person['id'])
        evidence = person.get('attendance', [])
        label = evidence[column] if column is not None and column < len(evidence) else None
        tokens = set((label or '').split('、'))
        entry = pick(person, 'id', 'name')
        explained = [key for key in ('on_leave', 'trip', 'out', 'exempt')
                     if ATTENDANCE_LABELS[key] in tokens or person['id'] in approvals.get(key, set())]
        arrived += int('到班' in tokens)
        for key, text in ATTENDANCE_LABELS.items():
            if key != 'unaccounted' and (text in tokens or key in explained):
                groups[key].append(entry)
        if label is None and not explained and working:
            groups['unaccounted'].append(entry)
    return dict(date=day, evaluated=working, counts=dict(arrived=arrived, **{k: len(v) for k, v in groups.items()}),
                **groups)


def project_attendance(value):
    day, view = value['day'], value['view']
    period = value['range']
    dates = view.get('days', []) if period == 'week' else [day]
    daily = [attendance_day(view, d) for d in dates]
    result = dict(range=period, date=day, as_of=view.get('as_of'),
        incomplete=bool(view.get('incomplete') or view.get('status') != 'ok' or view.get('refreshing') or
                        not dates or any(d not in view.get('days', []) for d in dates)),
        truncated=False,
        basis='no punch obligation or holiday calendar in the source; weekends excluded, public holidays not excluded',
        unaccounted_meaning='今天為截至 as_of 尚無打卡紀錄，不代表實際出勤判定；過去日期為沒有打卡紀錄；未來日期不推算',
        arrived_meaning='arrived 只計到班標籤，不代表實際在場人數')
    if period == 'today':
        result.update(daily[0])
    else:
        people = {}
        for item in daily:
            for key in ATTENDANCE_LABELS:
                for person in item[key]:
                    row = people.setdefault(person['id'], dict(**person, days={}))
                    row['days'].setdefault(key, []).append(item['date'])
        ranked = sorted(people.values(), key=lambda p: (-len(p['days'].get('unaccounted', [])),
            -len(p['days'].get('late', [])), -len(p['days'].get('missing_punch', [])), p['id']))
        ranking = [dict(**pick(p, 'id', 'name'), unaccounted_days=len(p['days']['unaccounted']))
                   for p in ranked if p['days'].get('unaccounted')]
        result.update(week_start=dates[0] if dates else None, week_end=dates[-1] if dates else None,
            days=[pick(item, 'date', 'evaluated', 'counts') for item in daily],
            summary={k: dict(person_days=sum(item['counts'][k] for item in daily),
                            people=len({p['id'] for item in daily for p in item[k]})) for k in ATTENDANCE_LABELS},
            top_unaccounted=ranking[:10], people=ranked[:50], labelled_arrival_count=sum(item['counts']['arrived'] for item in daily))
        result['truncated'] = len(ranked) > 50 or len(ranking) > 10
    # Preserve counts before trimming lists so partial names never change the headline.
    while len(json.dumps(result, ensure_ascii=False)) > 6000:
        result['truncated'] = True
        if period == 'week':
            candidates = [result[k] for k in ('people', 'top_unaccounted') if result[k]]
        else:
            candidates = [result[k] for k in reversed(ATTENDANCE_LABELS) if result[k]]
        if not candidates:
            break
        candidates[0].pop()
    return result


ATTENDANCE_SCHEMA = dict(type='object', properties={
    'range': dict(type='string', enum=['today', 'week'], description='today 查詢單日；week 查詢包含 date 的週一至週日。'),
    'date': dict(type='string', description='YYYY-MM-DD 台北日期；空字串代表今天。上週請填上週日期。')},
    required=['range', 'date'], additionalProperties=False)


def schema(properties):
    descriptions = dict(case_id='1-200 ASCII letters, digits, underscore, dot, colon or hyphen; never . or ..')
    return dict(type='object', properties={k: dict(type='string', description=descriptions[k]) for k in properties},
                required=list(properties), additionalProperties=False)


SEARCH_SCHEMA = dict(type='object', properties={
    'query': dict(type='string', description='案號、案名或客戶關鍵字，最多 240 字；空字串不篩關鍵字。'),
    'status': dict(type='string', enum=['all', *CASE_STATUS, *CASE_STATUS.values()], description='all 不篩狀態；依案件總覽流程節點判定。'),
    'owner': dict(type='string', enum=['anyone', 'me'], description='anyone 不篩 PM；me 表示目前使用者是 PM。'),
    'overdue': dict(type='boolean', description='false 不篩逾期；true 使用案件總覽的期限、逾期任務數與任務期限判定。'),
    'offset': dict(type='integer', description='從第幾筆開始，非負整數，0 為第一頁，每頁 8 筆。')},
    required=['query', 'status', 'owner', 'overdue', 'offset'], additionalProperties=False)


def argument_error(key, value, prop):
    expected = {'string': str, 'boolean': bool, 'integer': int}[prop['type']]
    if type(value) is not expected:
        return f"{key} 必須是 {prop['type']}"
    if 'enum' in prop and value not in prop['enum']:
        return f"{key} 請使用 " + '、'.join(str(v) for v in prop['enum'])
    if expected is str and len(value) > 240:
        return f'{key} 最多 240 字'
    if expected is int and value < 0:
        return f'{key} 必須是非負整數'
    return None


@dataclass(frozen=True)
class ToolSpec:
    schema: dict
    label: str
    handler: Callable
    projector: Callable


TOOLS = {
    'search_cases': ToolSpec(SEARCH_SCHEMA, '搜尋案件', search, project_search),
    'case_progress': ToolSpec(schema(['case_id']), '查詢案件進度', progress, project_progress),
    'case_owners': ToolSpec(schema(['case_id']), '查詢案件負責人', owners, project_owners),
    'attendance_today': ToolSpec(ATTENDANCE_SCHEMA, '查詢單日或每週出勤', attendance, project_attendance),
}


async def execute(app, cookie, name, args):
    spec = TOOLS.get(name)
    if spec is None or not isinstance(args, dict) or set(args) != set(spec.schema['required']):
        return json.dumps({'error': '工具參數錯誤'}, ensure_ascii=False), True
    for key, prop in spec.schema['properties'].items():
        error = argument_error(key, args[key], prop)
        if error:
            return json.dumps({'error': '工具參數錯誤：' + error}, ensure_ascii=False), True
    if 'case_id' in args and not valid_case_id(args['case_id']):
        return json.dumps({'error': '工具參數錯誤'}, ensure_ascii=False), True
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://ai.internal',
                                     headers={'cookie': cookie}, timeout=15) as client:
            data = spec.projector(await spec.handler(Reader(client, str(app.state.cfg.get('NODE_ASSIGNMENT_ENABLED', 'false')).lower() == 'true',
                str(app.state.cfg.get('WORKSPACE_SHELL_ENABLED', 'false')).lower() == 'true'), args))
        result = json.dumps(data, ensure_ascii=False)
        while len(result) > 6000:
            data['truncated'] = True
            lists = [v for v in data.values() if isinstance(v, list) and v]
            summary = data.get('workflow_summary')
            if summary and summary.get('rows'):
                lists.append(summary['rows'])
            if not lists:
                return json.dumps({'error': '資料過長', 'truncated': True}, ensure_ascii=False), True
            longest = max(lists, key=lambda v: len(json.dumps(v, ensure_ascii=False)))
            longest.pop()
            if summary and longest is summary.get('rows'):
                summary['truncated'] = True
            if name == 'search_cases':
                data.update(search_notice(data))
            result = json.dumps(data, ensure_ascii=False)
        return result, False
    except ReadDenied as exc:
        return json.dumps({'error': exc.message}, ensure_ascii=False), True
    except Exception:
        return json.dumps({'error': '資料暫時無法讀取，請稍後重試'}, ensure_ascii=False), True


def display_table(title, columns, rows, data, **extra):
    keys = [key for key, _ in columns[:8]]
    def cell(value):
        if isinstance(value, str):
            return value[:240]
        if value is None or type(value) is int or (type(value) is float and math.isfinite(value)):
            return value
        return None
    return dict(kind='table', title=title, columns=[dict(key=k, label=v) for k, v in columns[:8]],
                rows=[{k: cell(row.get(k)) for k in keys} for row in rows[:50]],
                truncated=bool(data.get('truncated') or len(rows) > 50 or len(columns) > 8),
                **({'caption': '截至 ' + str(data['as_of'])[:240]} if data.get('as_of') else {}), **extra)


def display_chart(title, points, data, **extra):
    safe_points = [dict(label=str(p['label'])[:240], value=p['value']) for p in points
                   if type(p['value']) in (int, float) and math.isfinite(p['value'])]
    return dict(kind='chart', title=title, variant='bars', points=safe_points[:12],
                truncated=bool(data.get('truncated') or len(points) > 12 or len(safe_points) != len(points)),
                **({'caption': '截至 ' + str(data['as_of'])[:240]} if data.get('as_of') else {}), **extra)


def display_search(data):
    data = {**data, **search_notice(data)}
    extra = {'note': data['note']} if data.get('note') else {}
    return [display_table('案件搜尋結果', [('code', '案號'), ('name', '案名'), ('status_label', '案件狀態'),
        ('pm_id', 'PM'), ('due_date', '交期')], data.get('cases', []), data, **extra)]


def display_owners(data):
    pm = data.get('pm', {})
    rows = [dict(role='PM', owner=pm.get('name') if pm.get('name') != 'name_unavailable' else pm.get('id'))]
    for node in data.get('nodes') or []:
        for person in node['owners']:
            rows.append(dict(role=node['label'], owner=person.get('name') or person.get('id') or person.get('open_id')))
    extra = {'note': '節點指派資料無法取得'} if data.get('nodes') is None else {}
    return [display_table('案件負責人', [('role', '職務或節點'), ('owner', '負責人')], rows, data, **extra)]


def display_progress(data):
    points = []
    bases = set()
    unknown = 0
    for stage in data.get('stages', []):
        node = data.get('nodes', {}).get(stage['key'], {})
        percent = 100 if stage['state'] == 'done' else node.get('percent')
        if percent is None:
            unknown += 1
            continue
        points.append(dict(label=stage['label'][:240], value=float(percent)))
        bases.add(stage['basis'])
    basis = '、'.join(text for key, text in [('rule', '規則推算'), ('source', '來源證據')] if key in bases)
    headline = dict(label=f'整體（已知階段平均；{basis or "無資料基礎"}；另有 {unknown} 個階段進度未知）',
                    value=f'{sum(p["value"] for p in points) / len(points):.1f}' if points else '未知')
    note = '；'.join(g['message_zh'] for g in data.get('gaps', []) if g.get('message_zh'))
    charts = [display_chart('案件階段完成百分比', points, data, unit='%', headline=headline,
                          **({'note': note} if note else {}))]
    summary = data.get('workflow_summary')
    if summary:
        charts.append(display_table('全部流程節點', [('label', '節點'), ('status', '狀態'), ('tasks_done', '完成任務'), ('tasks_total', '全部任務'), ('sop_tasks_done', 'SOP 完成'), ('sop_tasks_total', 'SOP 全部'), ('basis', '依據')], summary.get('rows', []), data, note=summary.get('unavailable', '')))
    return charts


def display_attendance(data):
    note = data.get('unaccounted_meaning', '')
    if data.get('incomplete'):
        note += '；資料不完整'
    if data.get('range') == 'week':
        days = [item['date'] for item in data.get('days', [])]
        codes = dict(unaccounted='無紀錄', late='遲', missing_punch='卡', on_leave='假', trip='出',
                     out='外', exempt='免', early_leave='早', supplemented='補')
        rows = [dict(name=p.get('name') or p['id'], **{day: '／'.join(codes[k]
            for k, dates in p['days'].items() if day in dates) or None for day in days}) for p in data.get('people', [])]
        caption = f"{data.get('week_start')} 至 {data.get('week_end')}"
        if data.get('as_of'):
            caption += '；截至 ' + str(data['as_of'])
        result = [display_table('每週出勤', [('name', '同事')] + [(d, d[5:]) for d in days], rows, data, note=note),
                  display_chart('每日沒有打卡紀錄', [dict(label=item['date'], value=item['counts']['unaccounted'])
                      for item in data.get('days', [])], data, unit='人', note=note)]
        for display in result:
            display['caption'] = caption
        return result
    counts = data.get('counts', {})
    points = [dict(label='到班', value=counts.get('arrived', 0))]
    people = {}
    for key, label in ATTENDANCE_LABELS.items():
        points.append(dict(label=label, value=counts.get(key, 0)))
        for person in data.get(key, []):
            row = people.setdefault(person['id'], dict(name=person.get('name') or person['id'], state=[]))
            row['state'].append(label)
    rows = [dict(name=p['name'], state='、'.join(p['state'])) for p in people.values()]
    return [display_chart('單日出勤標籤', points, data, unit='人', note=note),
            display_table('單日非到班標籤', [('name', '同事'), ('state', '狀態')], rows, data, note=note)]


DISPLAY_PROJECTORS = {'search_cases': display_search, 'case_owners': display_owners,
                      'case_progress': display_progress, 'attendance_today': display_attendance}


def displays(name, result):
    return DISPLAY_PROJECTORS[name](json.loads(result))
