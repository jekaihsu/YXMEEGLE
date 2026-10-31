"""Read tools reuse HTTP authorization and whitelist their model-visible fields."""
from dataclasses import dataclass
import asyncio
from typing import Callable
from urllib.parse import quote
import json

import httpx
from .ledger import today


class ReadDenied(Exception):
    def __init__(self, message):
        self.message = message


class Reader:
    def __init__(self, client):
        self.client = client

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
    page = await reader.get('/api/projects', q=args['query'], limit=20)
    details = await asyncio.gather(*(reader.get(case_path({'case_id': p['id']})) for p in page['items']))
    return dict(total=page['total'], items=[detail['project'] for detail in details])


async def progress(reader, args):
    return await reader.get(case_path(args) + '/progress')


async def owners(reader, args):
    detail = await reader.get(case_path(args))
    try:
        assignments = await reader.get(case_path(args) + '/node-assignments')
    except ReadDenied:
        assignments = {'unavailable': True}
    return {'detail': detail, 'assignments': assignments}


async def attendance(reader, args):
    day = today()
    return {'day': day, 'view': await reader.get('/api/people/attendance', week=day)}


def project_search(value):
    return {'total': value['total'], 'cases': [pick(p, 'id', 'code', 'name', 'client', 'status', 'pm_id')
                                              for p in value['items']]}


PRODUCTION = ('field', 'control', 'mapping', 'report')
GAPS = {'no_confirmation', 'confirmation_status_conflict', 'fill_items_unknown', 'plan_unavailable',
        'plan_truncated', 'items_unlinked', 'items_ambiguous', 'no_daily_linked', 'v3_ambiguous',
        'v3_none', 'v3_no_activity', 'reports_cold', 'reports_unavailable', 'reports_disabled', 'reports_stale'}


def project_progress(value):
    return dict(project_id=value['project_id'], as_of=value.get('as_of'),
                stages=[pick(s, 'key', 'label', 'state') for s in value['stages']
                        if s.get('key') in ('sales', 'pm', 'confirmation', *PRODUCTION)],
                nodes={k: pick(value['production'][k].get('progress') or {},
                               'items_done', 'items_total', 'percent', 'unknown_items')
                       for k in PRODUCTION if k in value['production']},
                gaps=[pick(g, 'id', 'message_zh') for g in value['gaps'] if g['id'] in GAPS])


def project_owners(value):
    detail, assignments = value['detail'], value['assignments']
    project = detail['project']
    pm_id = project.get('pm_id')
    people = {p['id']: p.get('name') for p in detail.get('users', [])}
    return dict(project_id=project['id'], pm={'id': pm_id, 'name': people.get(pm_id)},
                as_of=assignments.get('fetched_at') or detail.get('as_of'),
                nodes=[dict(key=n['key'], label=n['label'], owners=[pick(p, 'id', 'open_id', 'name')
                        for p in n['owners']]) for n in assignments.get('nodes', [])],
                incomplete=assignments.get('unavailable', False) or assignments.get('stale', False))


def project_attendance(value):
    day, view = value['day'], value['view']
    days = view.get('days', [])
    column = days.index(day) if day in days else None
    groups = {'late': [], 'missing_punch': [], 'leave': [], 'trip': [], 'out': [], 'no_record': []}
    labels = {'遲到': 'late', '缺卡': 'missing_punch', '請假': 'leave', '出差': 'trip', '外出': 'out'}
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
                arrived_count=arrived, **groups, no_record_label='尚無打卡紀錄（no record yet），不可判定缺席')


def schema(properties):
    return dict(type='object', properties={k: {'type': 'string', 'minLength': 1, 'maxLength': 240}
                                           for k in properties}, required=list(properties), additionalProperties=False)


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
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://ai.internal',
                                     headers={'cookie': cookie}, timeout=15) as client:
            data = spec.projector(await spec.handler(Reader(client), args))
        result = json.dumps(data, ensure_ascii=False)
        if len(result) > 6000:
            partial = result[:5500]
            result = json.dumps({'truncated': True, 'partial_data': partial}, ensure_ascii=False)
            while len(result) > 6000:
                partial = partial[:len(partial) - (len(result) - 6000)]
                result = json.dumps({'truncated': True, 'partial_data': partial}, ensure_ascii=False)
        return result, False
    except ReadDenied as exc:
        return json.dumps({'error': exc.message}, ensure_ascii=False), True
    except Exception:
        return json.dumps({'error': '資料暫時無法讀取，請稍後重試'}, ensure_ascii=False), True
