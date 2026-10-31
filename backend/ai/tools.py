"""Read tools reuse HTTP authorization and whitelist their model-visible fields."""
from dataclasses import dataclass
import re
from typing import Callable
from urllib.parse import quote
import json

import httpx
from .ledger import today


class ReadDenied(Exception):
    def __init__(self, message):
        self.message = message


class Reader:
    def __init__(self, client, assignments_enabled=False):
        self.client = client
        self.assignments_enabled = assignments_enabled

    async def get(self, path, **params):
        response = await self.client.get(path, params=params)
        if response.status_code in (401, 403, 404):
            message = '你沒有權限查看出勤資料' if path == '/api/people/attendance' else '找不到或沒有權限查看這個案件'
            raise ReadDenied(message)
        response.raise_for_status()
        return response.json()


def pick(value, *keys):
    return {k: value[k] for k in keys if k in value}


def case_path(args):
    return '/api/projects/' + quote(args['case_id'], safe='')


async def search(reader, args):
    return await reader.get('/api/projects', q=args['query'], limit=8)


async def progress(reader, args):
    return await reader.get(case_path(args) + '/progress')


async def owners(reader, args):
    detail = await reader.get('/api/case-detail/' + args['case_id'])
    assignments = {'unavailable': True}
    if reader.assignments_enabled:
        try:
            assignments = await reader.get(case_path(args) + '/node-assignments')
        except ReadDenied:
            pass
    return {'detail': detail, 'assignments': assignments}


async def attendance(reader, args):
    day = today()
    return {'day': day, 'view': await reader.get('/api/people/attendance', week=day)}


def project_search(value):
    return {**pick(value, 'as_of'), 'total': value['total'], 'cases': [pick(p, 'id', 'code', 'name', 'status', 'pm_id', 'due_date')
                                              for p in value['items']]}


PRODUCTION = ('field', 'control', 'mapping', 'report')
GAPS = {'no_confirmation', 'confirmation_status_conflict', 'fill_items_unknown', 'plan_unavailable',
        'plan_truncated', 'items_unlinked', 'items_ambiguous', 'no_daily_linked', 'v3_ambiguous',
        'v3_none', 'v3_no_activity', 'reports_cold', 'reports_unavailable', 'reports_disabled', 'reports_stale'}


def project_progress(value):
    return dict(project_id=value['project_id'], as_of=value.get('as_of'),
                stages=[pick(s, 'key', 'label', 'state', 'basis') for s in value['stages']
                        if s.get('key') in ('sales', 'pm', 'confirmation', *PRODUCTION)],
                nodes={k: pick(value['production'][k].get('progress') or {},
                               'items_done', 'items_total', 'percent', 'unknown_items', 'basis')
                       for k in PRODUCTION if k in value['production']},
                gaps=[pick(g, 'id', 'message_zh') for g in value['gaps'] if g['id'] in GAPS])


def project_owners(value):
    detail, assignments = value['detail'], value['assignments']
    pm = detail['header']['pm']
    unavailable = assignments.get('unavailable', False)
    return dict(project_id=detail['header']['details']['case_identity'],
                pm=dict(id=pm.get('id'), name=pm['name'] or 'name_unavailable'),
                as_of=assignments.get('fetched_at') or detail.get('as_of'),
                node_assignment_status='node assignment data unavailable' if unavailable else 'available',
                nodes=None if unavailable else [dict(key=n['key'], label=n['label'],
                    owners=[pick(p, 'id', 'open_id', 'name') for p in n['owners']])
                    for n in assignments.get('nodes', [])],
                incomplete=unavailable or assignments.get('stale', False))


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


@dataclass(frozen=True)
class ToolSpec:
    schema: dict
    label: str
    handler: Callable
    projector: Callable


TOOLS = {
    'search_cases': ToolSpec(schema(['query']), '搜尋案件', search, project_search),
    'case_progress': ToolSpec(schema(['case_id']), '查詢案件進度', progress, project_progress),
    'case_owners': ToolSpec(schema(['case_id']), '查詢案件負責人', owners, project_owners),
    'attendance_today': ToolSpec(schema([]), '查詢今天出勤', attendance, project_attendance),
}


async def execute(app, cookie, name, args):
    spec = TOOLS.get(name)
    if spec is None or not isinstance(args, dict) or set(args) != set(spec.schema['required']):
        return json.dumps({'error': '工具參數錯誤'}, ensure_ascii=False), True
    if any(not isinstance(v, str) or not 1 <= len(v) <= 240 for v in args.values()):
        return json.dumps({'error': '工具參數錯誤'}, ensure_ascii=False), True
    if 'case_id' in args and (not re.fullmatch(r'[A-Za-z0-9_.:-]{1,200}', args['case_id']) or args['case_id'] in ('.', '..')):
        return json.dumps({'error': '工具參數錯誤'}, ensure_ascii=False), True
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://ai.internal',
                                     headers={'cookie': cookie}, timeout=15) as client:
            data = spec.projector(await spec.handler(Reader(client, str(app.state.cfg.get('NODE_ASSIGNMENT_ENABLED', 'false')).lower() == 'true'), args))
        result = json.dumps(data, ensure_ascii=False)
        while len(result) > 6000:
            data['truncated'] = True
            lists = [v for v in data.values() if isinstance(v, list) and v]
            if not lists:
                return json.dumps({'error': '資料過長', 'truncated': True}, ensure_ascii=False), True
            max(lists, key=lambda v: len(json.dumps(v, ensure_ascii=False))).pop()
            result = json.dumps(data, ensure_ascii=False)
        return result, False
    except ReadDenied as exc:
        return json.dumps({'error': exc.message}, ensure_ascii=False), True
    except Exception:
        return json.dumps({'error': '資料暫時無法讀取，請稍後重試'}, ensure_ascii=False), True
