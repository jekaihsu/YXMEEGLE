"""Exercise read projections independently of the model tool dispatch contract."""
import json
import httpx
from .ai.tools import (TOOLS, CASE_STATUS, ToolSpec,
    valid_case_id, Reader, ReadDenied, search_notice, execute as production_execute)

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



LEGACY_SCHEMAS = {'search_cases': SEARCH_SCHEMA, 'case_progress': schema(['case_id']),
                  'case_owners': schema(['case_id']), 'attendance_today': ATTENDANCE_SCHEMA}


def projection_spec(name):
    from .ai.datasets import REGISTRY
    if name not in LEGACY_SCHEMAS:
        return None
    dataset = REGISTRY[name]
    return ToolSpec(LEGACY_SCHEMAS[name], dataset.title, dataset.read, dataset.projector)



async def execute(app, cookie, name, args):
    if name in TOOLS and name != 'show_display':
        return await production_execute(app, cookie, name, args)
    spec = projection_spec(name)
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
                following = data['offset'] + len(data['cases'])
                data['next_offset'] = following if following < data['matched_total'] else None
                data.update(search_notice(data))
            result = json.dumps(data, ensure_ascii=False)
        return result, False
    except ReadDenied as exc:
        return json.dumps({'error': exc.message}, ensure_ascii=False), True
    except Exception:
        return json.dumps({'error': '資料暫時無法讀取，請稍後重試'}, ensure_ascii=False), True

