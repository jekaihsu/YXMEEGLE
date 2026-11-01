"""Authorized read catalog and compact, explicitly allowlisted projections."""
from dataclasses import dataclass
from functools import partial
from typing import Callable, Literal
import hashlib
import json
import math
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, create_model

from . import tools as t


class Params(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Column(BaseModel):
    name: str
    label: str
    type: Literal['text', 'number', 'date', 'status'] = 'text'


@dataclass(frozen=True)
class Dataset:
    id: str
    title: str
    description: str
    params: type[Params]
    read: Callable
    projector: Callable
    columns: tuple[Column, ...]
    example: dict


def parameters(name, definitions):
    return create_model(name, __base__=Params, **definitions)


def text_param(default=''):
    return str, Field(default=default, max_length=240)

Case = parameters('CaseParams', {'case_id': (str, Field(pattern=r'^[A-Za-z0-9_:-][A-Za-z0-9_.:-]{0,199}$'))})
Search = parameters('SearchParams', dict(query=text_param(), status=(Literal['all', *t.CASE_STATUS, *t.CASE_STATUS.values()], 'all'),
    owner=(Literal['anyone', 'me'], 'anyone'), overdue=(bool, False)))
Attendance = parameters('AttendanceParams', dict(range=(Literal['today', 'week'], 'today'), date=text_param()))


def columns(*specs):
    return tuple(Column(name=s[0], label=s[1], type=s[2] if len(s) > 2 else 'text') for s in specs)


async def route(path, reader, args):
    args = dict(args)
    node_in_path = '{node_key}' in path
    path = path.format(**args)
    args.pop('case_id', None)
    if node_in_path:
        args.pop('node_key', None)
    return await reader.get(path, **{k: v for k, v in args.items() if v != ''})


def rows_at(key, fields, value):
    return [{k: row.get(k) for k in fields} for row in value.get(key, [])]


def scalar(value):
    if isinstance(value, dict):
        return scalar(value.get('value'))
    if isinstance(value, str):
        return value[:240]
    if value is None or type(value) in (bool, int) or type(value) is float and math.isfinite(value):
        return value
    return None


def contract_rows(value):
    main = value.get('main', {})
    return [{k: scalar(main.get(k)) for k in ('line_number', 'name')}]


def node_rows(value):
    return [dict(id=r.get('id'),title=r.get('title'),status=r.get('status'),
        assignee_name=(r.get('assignee') or {}).get('name'),due_date=r.get('deadline')) for r in value.get('tasks',[])]


def dispatch_rows(value):
    return [dict(id=r.get('slot_id'), start=(r.get('interval') or {}).get('start'),
        group=r.get('group'), case_name=(r.get('case') or {}).get('name'),
        work_content=r.get('work_content'), status=r.get('planning_status')) for r in value.get('slots', [])]


def legacy_rows(name, value):
    if name == 'search_cases':
        return value['cases']
    if name == 'case_progress':
        return (value.get('workflow_summary') or {}).get('rows') or value['stages']
    if name == 'case_owners':
        return t.display_owners(value)[0]['rows']
    if value.get('range') == 'week':
        return [dict(date=r['date'], **r['counts']) for r in value.get('days', [])]
    return [dict(label='到班', value=value.get('counts', {}).get('arrived', 0)),
        *[dict(label=label, value=value.get('counts', {}).get(k, 0)) for k, label in t.ATTENDANCE_LABELS.items()]]


REGISTRY: dict[str, Dataset] = {}


def add(ident, title, description, params, read, projector, cols, example=None):
    REGISTRY[ident] = Dataset(ident, title, description, params, read, projector, cols, example or {})


for ident, title, description, params, read, projector, cols in [
    ('search_cases', '案件總覽', '按案號、案名、PM、狀態或逾期查案件', Search, t.search, t.project_search,
     columns(('code','案號'),('name','案名'),('state','狀態','status'),('overdue','逾期','status'),('pm_id','PM'),('due_date','交期','date'))),
    ('case_progress', '案件進度', '查案件完成、剩餘工作與證據缺口', Case, t.progress, t.project_progress,
     columns(('label','節點'),('status','狀態','status'),('tasks_done','完成任務','number'),('tasks_total','全部任務','number'))),
    ('case_owners', '案件負責人', '查 PM 與各節點負責人', Case, t.owners, t.project_owners,
     columns(('role','節點'),('owner','負責人'))),
    ('attendance_today', '出勤', '查單日或指定週出勤標籤與沒有打卡紀錄排名', Attendance, t.attendance, t.project_attendance,
     columns(('label','標籤'),('value','人數','number'))),
]:
    add(ident, title, description, params, read, projector, cols, {'case_id':'p1'} if params is Case else {})


REPORTS = [
    ('review', '審核週報', '查審核人員、日期與狀態', 'review/rows',
     {'dept':(Literal['field','office','control'],'field'),'week':text_param(),'person':text_param(),'status':(Literal['','passed','returned','pending','unset'],'')},
     columns(('date','日期','date'),('person','人員'),('case_code','案號'),('status','狀態','status'))),
    ('sales', '業務案件', '查業務案件與 PM 狀態；不含金額，無月營收資料', 'sales', {'pm':text_param(),'status':text_param()},
     columns(('code','案號'),('name','案名'),('client','業主'),('pm','PM'),('status','狀態','status'))),
    ('progress', '進度週報', '查各案件計畫、實際與完成數量', 'progress', {'dept':(Literal['field','office'],'field'),'week':text_param(),'q':text_param()},
     columns(('case_code','案號'),('case_name','案名'),('expected_total','預計數','number'),('done_total','完成數','number'),('remaining','剩餘數','number'),('status','狀態','status'))),
    ('assets', '資產使用', '查車輛或儀器使用與閒置天數；不含租金', 'assets', {'kind':(Literal['vehicle','instrument'],'vehicle'),'from':text_param(),'to':text_param(),'owner':text_param(),'q':text_param()},
     columns(('name','名稱'),('category','類別'),('status','狀態','status'),('owner','負責人'),('uses','使用次數','number'),('idle_days','閒置天數','number'))),
    ('contacts', '聯繫週報', '查人員、案件聯繫日期與跟進狀態', 'contacts', {'from':text_param(),'to':text_param(),'person':text_param(),'q':text_param()},
     columns(('contact_date','聯繫日','date'),('case_code','案號'),('case_name','案名'),('person','人員'),('next_date','跟進日','date'),('result_status','狀態','status'))),
]
for ident, title, description, endpoint, defs, cols in REPORTS:
    add('report_'+ident, title, description, parameters(ident+'Params', defs), partial(route, '/api/reports/'+endpoint),
        partial(rows_at, 'items', [c.name for c in cols]), cols)

for ident, title, description, path, defs, key, cols in [
    ('daily_reports','日報紀錄','查人員、案件、日期的日報', '/api/daily-reports',
     dict(project_id=text_param(),actor_id=text_param(),date_from=text_param(),date_to=text_param(),q=text_param()), 'items',
     columns(('id','ID'),('date','日期','date'),('person','人員'),('project_code','案號'),('department','部門'),('description','工作'))),
    ('sop_tasks','SOP 任務','查案件或節點 SOP 任務狀態與逾期', '/api/projects/{case_id}/sop-tasks',
     {'case_id':(str, Field(pattern=r'^[A-Za-z0-9_:-][A-Za-z0-9_.:-]{0,199}$')), 'node_key':text_param()}, 'tasks',
     columns(('id','ID'),('title','任務'),('state','狀態','status'),('overdue','逾期','status'),('applicability','適用','status'))),
    ('node_detail','節點指派明細','查案件指定節點的任務與負責人', '/api/projects/{case_id}/node-assignments/nodes/{node_key}',
     {'case_id':(str, Field(pattern=r'^[A-Za-z0-9_:-][A-Za-z0-9_.:-]{0,199}$')), 'node_key':(Literal[*t.NODE_ORDER], ...)}, 'tasks',
     columns(('id','ID'),('title','任務'),('status','狀態','status'),('assignee_name','負責人'),('due_date','期限','date'))),
]:
    add(ident,title,description,parameters(ident+'Params',defs),partial(route,path),node_rows if ident=='node_detail' else partial(rows_at,key,[c.name for c in cols]),cols,
        {'case_id':'p1','node_key':'field'} if ident=='node_detail' else {'case_id':'p1'} if ident=='sop_tasks' else {})
add('contract_detail','合約項目','依合約項目 key 查名稱與項次；無到期日資料', parameters('ContractParams',{'key':(str,Field(min_length=1,max_length=240))}),
    partial(route,'/api/contract-detail'),contract_rows,columns(('line_number','項次'),('name','名稱')),{'key':'contract-key'})
add('dispatch_board','派工看板','查日期區間、組別的派工與未指派狀態',parameters('DispatchParams',{'from':text_param(),'to':text_param(),'group':text_param()}),
    partial(route,'/api/v2/dispatch/board'),dispatch_rows,columns(('id','ID'),('start','開始','date'),('group','組別'),('case_name','案名'),('work_content','工作'),('status','狀態','status')))


def index():
    return [dict(id=d.id,title=d.title,description=d.description,params=list(d.params.model_fields)) for d in REGISTRY.values()]


def describe(ident):
    d = REGISTRY[ident]
    return dict(id=d.id,title=d.title,description=d.description,params=d.params.model_json_schema(),
        columns=[c.model_dump() for c in d.columns],example=dict(id=d.id,params=d.example,limit=20,offset=0))


async def query(reader, ident, params, limit, offset):
    d = REGISTRY[ident]
    args = d.params.model_validate(params).model_dump()
    for k, v in args.items():
        if v and (k in ('date','week','from','to','date_from','date_to')):
            if date.fromisoformat(v).isoformat() != v:
                raise ValueError('invalid date')
    if ident == 'search_cases':
        args['offset'] = offset
    elif ident.startswith('report_') or ident == 'daily_reports':
        args.update(limit=limit,offset=offset)
    raw = await d.read(reader,args)
    projected = d.projector(raw)
    legacy = ident in ('search_cases','case_progress','case_owners','attendance_today')
    rows = legacy_rows(ident,projected) if legacy else projected
    total = raw.get('total',raw.get('matched_total',len(rows)))
    paged = ident == 'search_cases' or ident.startswith('report_') or ident == 'daily_reports'
    selected = rows[:limit] if paged else rows[offset:offset+limit]
    cols = d.columns
    if ident == 'attendance_today' and args['range'] == 'week':
        cols = columns(('date','日期','date'), *[(k,v,'number') for k,v in t.ATTENDANCE_LABELS.items()])
    result = dict(dataset_id=ident,columns=[c.model_dump() for c in cols],
        rows=[{c.name:scalar(r.get(c.name)) for c in cols} for r in selected],total=total,
        next_offset=offset+len(selected) if selected and offset+len(selected)<total else None,
        as_of=(projected.get('as_of') if legacy else None) or raw.get('as_of') or raw.get('last_sync') or raw.get('meta',{}).get('fetched_at') or raw.get('source',{}).get('fetched_at'),
        truncated=bool(raw.get('truncated') or offset+len(selected)<total),
        limitations=['金額與財務欄位不提供', '無來源時間時 as_of 為 null'])
    result['totals'] = {'rows':total}
    if legacy:
        while len(json.dumps(projected,ensure_ascii=False)) > 6000:
            lists = []
            def collect(value):
                if isinstance(value, dict):
                    for child in value.values():
                        collect(child)
                elif isinstance(value, list) and value:
                    lists.append(value)
            collect(projected)
            if not lists:
                projected = {'unavailable':'資料過長，無法完整列出','truncated':True}
                break
            max(lists,key=lambda v:len(json.dumps(v,ensure_ascii=False))).pop()
            projected['truncated'] = True
        result['truncated'] |= bool(projected.get('truncated'))
    meta = raw.get('meta', {})
    if meta.get('stale'):
        result['limitations'].append('來源快照已過期')
    for gap in meta.get('gaps', [])[:8]:
        if isinstance(gap, dict):
            result['limitations'].append(str(gap.get('message_zh') or gap.get('code') or '來源資料缺口')[:160])
    if legacy:
        result['summary'] = projected
    else:
        result['limitations'].append('僅列已授權來源提供的欄位；空值不是沒有')
        if raw.get('meta') or raw.get('gaps') or raw.get('page_state') or raw.get('source'):
            result['limitations'].append('來源可能不完整，無法據空結果推論沒有資料')
    while len(json.dumps(result,ensure_ascii=False)) > 14000 and result['rows']:
        result['rows'].pop()
        result['truncated'] = True
        result['next_offset'] = offset+len(result['rows'])
    result['result_id'] = 'r'+hashlib.sha256(json.dumps([ident,params,limit,offset,result],sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:20]
    return result
