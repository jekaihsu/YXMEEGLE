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


CASE_STATUS = {'pending': '尚未開始', 'in_progress': '進行中', 'completed': '已完成',
    'paused': '暫停中', 'engineering_complete': '工程完成、財務待結', 'source_conflict': '來源待核對',
    'internal': '內部案', 'active': '進行中', 'ongoing': '進行中'}


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
    q = (args['query'] or '').casefold()
    items = [p for p in items if
        (not q or q in ' '.join(str(p.get(k, '')) for k in ('code', 'name', 'client')).casefold()) and
        (not args['status'] or p['status'] == args['status']) and
        (not owner or p.get('pm_id') == owner) and
        (args['overdue'] is not True or bool(p.get('due_date') and p['due_date'][:10] < today()
            and p['status'] not in ('completed', 'engineering_complete')))]
    counts = {key: sum(p['status'] == key for p in items) for key in CASE_STATUS}
    items.sort(key=lambda p: (p.get('due_date') or '9999', p['id']))
    return dict(total=len(items), items=items[:8], status_counts=counts)



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
    day = today()
    return {'day': day, 'view': await reader.get('/api/people/attendance', week=day)}


def search_notice(data):
    count = len(data.get('cases', []))
    if data.get('total', count) > count:
        return dict(truncated=True, note=f'共 {data["total"]} 筆，僅列出 {count} 筆')
    return {}


def project_search(value):
    data = {**pick(value, 'as_of'), 'total': value['total'], 'cases': [pick(p, 'id', 'code', 'name', 'status', 'pm_id', 'due_date')
                                              for p in value['items']]}
    data['status_counts'] = value.get('status_counts', {})
    for p in data['cases']:
        p['status_label'] = CASE_STATUS.get(p.get('status'), '狀態待確認')
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


def project_attendance(value):
    day, view = value['day'], value['view']
    days = view.get('days', [])
    column = days.index(day) if day in days else None
    groups = {'late': [], 'missing_punch': [], 'leave': [], 'trip': [], 'out': [], 'no_record': [], 'early_leave': [], 'exempt': [], 'supplemented': []}
    labels = {'遲到': 'late', '缺卡': 'missing_punch', '請假': 'leave', '出差': 'trip', '外出': 'out', '早退': 'early_leave', '免打卡': 'exempt', '補卡／修正': 'supplemented'}
    arrived = 0
    approvals = {'leave': set(), 'trip': set(), 'out': set()}
    for kind, records in (('leave', view.get('leaves', [])), ('trip', view.get('trips', []))):
        for record in records:
            if record['start'] <= day <= record['end']:
                key = record.get('kind', kind)
                approvals[key].add(record['person_id'])
    for person in view.get('people', []):
        if person.get('in_service') is not True:
            continue
        evidence = person.get('attendance', [])
        label = evidence[column] if column is not None and column < len(evidence) else None
        entry = pick(person, 'id', 'name')
        tokens = set((label or '').split('、'))
        for text, key in labels.items():
            if text in tokens or person['id'] in approvals.get(key, set()):
                groups[key].append(entry)
        arrived += int('到班' in tokens)
        if label is None:
            groups['no_record'].append(entry)
    return dict(date=day, as_of=view.get('as_of'),
                incomplete=bool(view.get('incomplete') or view.get('status') != 'ok' or column is None or
                                groups['no_record'] or view.get('refreshing')),
                labelled_arrival_count=arrived, **groups, no_record_label='尚無打卡紀錄（no record yet），不代表實際出勤判定')


def schema(properties):
    descriptions = dict(query='Nonempty search query, at most 240 characters.',
                        case_id='1-200 ASCII letters, digits, underscore, dot, colon or hyphen; never . or ..')
    return dict(type='object', properties={k: dict(type='string', description=descriptions[k]) for k in properties},
                required=list(properties), additionalProperties=False)


SEARCH_SCHEMA = dict(type='object', properties={
    'query': dict(type=['string', 'null'], description='Optional keyword in case code, name or client, at most 240 characters. Use null for list questions.'),
    'status': dict(type=['string', 'null'], enum=[None, *CASE_STATUS], description='Case status filter. ' + '；'.join(f'{k}={v}' for k, v in CASE_STATUS.items())),
    'owner': dict(type=['string', 'null'], enum=[None, 'me'], description='me means the current user is PM, not task owner.'),
    'overdue': dict(type=['boolean', 'null'], description='true filters overdue workspace due dates, excluding completed and engineering_complete. Unknown deadlines cannot establish lateness.')},
    required=['query', 'status', 'owner', 'overdue'], additionalProperties=False)


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
    'attendance_today': ToolSpec(schema([]), '查詢今天出勤', attendance, project_attendance),
}


async def execute(app, cookie, name, args):
    spec = TOOLS.get(name)
    if spec is None or not isinstance(args, dict) or set(args) != set(spec.schema['required']):
        return json.dumps({'error': '工具參數錯誤'}, ensure_ascii=False), True
    if name == 'search_cases':
        for key, value in args.items():
            prop = spec.schema['properties'][key]
            if value is None:
                continue
            if ('enum' in prop and value not in prop['enum']) or (key == 'overdue' and type(value) is not bool) or (key != 'overdue' and (not isinstance(value, str) or len(value) > 240)):
                return json.dumps({'error': '工具參數錯誤：status 請使用 ' + '、'.join(CASE_STATUS) + '；owner 僅支援 me'}, ensure_ascii=False), True
    elif any(not isinstance(v, str) or not 1 <= len(v) <= 240 for v in args.values()):
        return json.dumps({'error': '工具參數錯誤'}, ensure_ascii=False), True
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


ATTENDANCE_LABELS = {'late': '遲到', 'missing_punch': '缺卡', 'leave': '請假', 'trip': '出差',
    'out': '外出', 'no_record': '尚無打卡紀錄', 'early_leave': '早退', 'exempt': '免打卡', 'supplemented': '補卡／修正'}


def display_attendance(data):
    points = [dict(label='到班', value=data.get('labelled_arrival_count', 0))]
    rows = []
    for key, label in ATTENDANCE_LABELS.items():
        people = data.get(key, [])
        points.append(dict(label=label, value=len(people)))
        rows.extend(dict(name=p.get('name') or p.get('id'), state=label) for p in people)
    note = '尚無打卡紀錄不代表實際出勤判定；同事可有多個標籤'
    if data.get('incomplete'):
        note += '；資料不完整'
    return [display_chart('今天出勤標籤', points, data, unit='人',
                headline=dict(label='標籤為到班', value=str(data.get('labelled_arrival_count', 0))), note=note),
            display_table('今天非到班標籤', [('name', '同事'), ('state', '狀態')], rows, data, note=note)]


DISPLAY_PROJECTORS = {'search_cases': display_search, 'case_owners': display_owners,
                      'case_progress': display_progress, 'attendance_today': display_attendance}


def displays(name, result):
    return DISPLAY_PROJECTORS[name](json.loads(result))
