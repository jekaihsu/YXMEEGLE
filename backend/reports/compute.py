"""Pure normalization and report calculations. Dates are Taipei calendar dates."""
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
import math
import statistics
from zoneinfo import ZoneInfo
from .models import CaseDetail, ProgressResponse, ProgressRow
from .registry import BASE_TOKEN, BY_KIND, FLAGS, TABLES

TZ = ZoneInfo('Asia/Taipei')
class UnknownStatus(ValueError):
    pass


class CaseNotFound(ValueError):
    pass


STATUS = {'已通過': 'passed', '已退回': 'returned', '待檢核': 'pending'}

def cell(value):
    if value is None: return ''
    if isinstance(value, list): return ','.join(str(v) for v in (cell(x) for x in value) if v != '')
    if isinstance(value, dict):
        for key in ('text', 'text_arr', 'name', 'value', 'record_ids'):
            if value.get(key) is not None: return cell(value[key])
        return ''
    return value.strip() if isinstance(value, str) else value


def links(value):
    if isinstance(value, list): return [x for v in value for x in links(v)]
    if isinstance(value, dict): return value.get('record_ids') or []
    return []


def number(value):
    value = cell(value)
    if isinstance(value, bool) or value == '': return None
    try:
        n = float(str(value).replace(',', ''))
        return n if math.isfinite(n) else None
    except (ValueError, TypeError): return None


def day(value):
    value = cell(value)
    if value == '' or isinstance(value, bool): return None
    try:
        n = float(value)
        result = (datetime.fromtimestamp(n / 1000, timezone.utc).astimezone(TZ).date()
                  if abs(n) > 10000000 else date(1899, 12, 30) + timedelta(days=n))
        return result.isoformat()
    except (ValueError, TypeError, OverflowError, OSError):
        try: return _iso_day(value)
        except ValueError: return None


def _iso_day(value):
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=TZ)).astimezone(TZ).date().isoformat()


def monday(value):
    d = date.fromisoformat(value)
    return (d - timedelta(days=d.weekday())).isoformat()


def ratio(a, b): return a / b if b else None


def gap(ident, message, severity='warn'): return dict(id=ident, severity=severity, message=message)


def normalize_group(value):
    name=str(cell(value)).strip()
    if name in ('', '未分組', '未分', '__blank__'): return '未分組'
    while name.endswith('組'): name=name[:-1].strip()
    return '未分組' if name in ('', '未分') else name


def contract(f):
    actual=number(f.get('實際合約金額')); expected=number(f.get('預期合約金額'))
    return expected if actual is None or actual==0 and expected is not None and expected>0 else actual


def normalize(raw, base=BASE_TOKEN):
    tables = {k: [dict(id=r['record_id'], f=r['fields'], created_time=r.get('created_time')) for r in v['records']] for k, v in raw.items()}
    cost = {r['id']: r['f'] for r in tables.get('field_cost', [])}
    reviews = {'field': [], 'office': []}
    for dept in reviews:
        for r in tables.get(dept, []):
            f = r['f']; linked = next((cost[i] for i in links(f.get('所屬成本單')) if i in cost), {})
            group = cell(linked.get('組別')) if dept == 'field' else cell(f.get('營業額組別-明細'))
            group = group or '未分組'
            dt = day(f.get('出工日期') or f.get('工作日期-薪資')) if dept == 'field' else day(f.get('工作日期-營業額明細'))
            flags = [flag for flag in FLAGS if cell(f.get(flag))]
            if cell(f.get('是否有檢核程序')) == '否': flags.append('違反檢核程序')
            reviews[dept].append(dict(id=r['id'], no=str(cell(f.get('工作單號'))), date=dt or '', group=normalize_group(group),group_label=str(group),
                person=str(cell(f.get('營業額人員-明細') or f.get('姓名') or f.get('此單出工人'))),
                case_code=str(cell(f.get('案件編號') or f.get('所屬案件'))),
                item=str(cell(f.get('工項') or f.get('內業工項'))), points=number(f.get('最終營業額點數')),
                status=STATUS.get(cell(f.get('檢核狀態')), 'unset'), control_checked=f.get('控制組檢核') if type(f.get('控制組檢核')) is bool else None,
                note=str(cell(f.get('備註'))), flags=flags, link=record_link(base, dept, r['id'])))
    indices = {dept: defaultdict(list) for dept in reviews}
    for dept, rows in reviews.items():
        for row in rows: indices[dept][monday(row['date']) if row['date'] else ''].append(row)
    gaps = []
    office = reviews['office']; filled = sum(r['status'] != 'unset' for r in office)
    if filled < len(office): gaps.append(gap('office-review-coverage', f'內業工作單檢核狀態僅 {filled}/{len(office)} 有值；空白不可視為通過'))
    for dept, rows in reviews.items():
        missing = sum(not r['date'] for r in rows)
        if missing: gaps.append(gap(dept + '-date', f'{"外業" if dept == "field" else "內業"}工作單 {missing}/{len(rows)} 缺少可解析工作日期，週報不納入'))
        unknown = sum(r['group'] == '未分組' for r in rows)
        if unknown: gaps.append(gap(dept + '-group', f'{"外業" if dept == "field" else "內業"}工作單 {unknown}/{len(rows)} 組別無法還原'))
    for kind, value in raw.items():
        if value.get('status') != 'ok': gaps.append(gap('source-' + kind, f'{value["name"]} 來源尚未讀取'))
    costs = tables.get('office_cost', [])
    for key in ('PM檢核', '內業組長檢核'):
        n = sum(cell(r['f'].get(key)) != '' for r in costs)
        if n < len(costs): gaps.append(gap(key, f'內業成本單 {"專案經理檢核" if key == "PM檢核" else "內業組長檢核"} 僅 {n}/{len(costs)} 有值'))
    plan_indices=defaultdict(list); negative=0
    for r in tables.get('plan',[]):
        f=r['f']; dt=day(f.get('開始日期')); end=day(f.get('結束日期')) or dt
        dept={'外業':'field','內業':'office'}.get(cell(f.get('業別')))
        if not dt or not dept or cell(f.get('條類型'))=='休假': continue
        if end<dt: negative+=1;end=dt
        group=normalize_group(f.get('組別'))
        current=date.fromisoformat(dt); last=date.fromisoformat(end)
        while current<=last:
            plan_indices[(dept,monday(current.isoformat()))].append(dict(r,date=current.isoformat(),group=group))
            current+=timedelta(days=1)
    if negative: gaps.append(gap('plan-negative-span',f'{negative} 筆預排結束早於開始，按開始當日計算'))
    cases={str(cell(r['f'].get('案件編號'))):r for r in tables.get('case',[])}
    plan_basis='points' if any(number(r['f'].get('預估營業額點數')) is not None for r in tables.get('plan',[])) else 'days'
    cost_dates={ident:day(f.get('工作日期')) for ident,f in cost.items()}
    return dict(cost_dates=cost_dates,plan_basis=plan_basis,plan_indices=plan_indices,cases=cases,tables=tables, reviews=reviews, indices=indices, gaps=gaps, raw=raw, base=base)


def record_link(base, kind, ident):
    if not ident: return None
    return f'https://www.larksuite.com/base/{base}?table={BY_KIND[kind].table_id}&record={ident}'


def kpi(rows):
    counts = Counter(r['status'] for r in rows); total = len(rows)
    return dict(total=total, **{s: counts[s] for s in ('passed','returned','pending','unset')},
                error_rate=ratio(counts['returned'], counts['passed'] + counts['returned']),
                pending_rate=ratio(counts['pending'], total), coverage=ratio(counts['passed'] + counts['returned'], total))


def review_rows(data, dept, week=None, group='', person='', **_):
    source = 'office' if dept == 'control' else dept
    rows = data['indices'][source].get(week, []) if week else data['reviews'][source]
    group=normalize_group(group) if group else ''
    return [r for r in rows if (dept != 'control' or r['group'] == '控制') and (not group or group == r['group']) and (not person or person == '__blank__' and not r['person'] or person in r['person'].split(','))]


def review(data, dept='field', week=None, weeks=12, group='', person='', **_):
    rows = review_rows(data, dept, week, group, person)
    prev = (date.fromisoformat(week) - timedelta(days=7)).isoformat()
    groups, people, items = defaultdict(list), defaultdict(list), defaultdict(list)
    for r in rows:
        groups[r['group']].append(r); items[r['item']].append(r)
        for p in r['person'].split(','):
            people[(p, r['group'])].append(r)
    by_group = [dict(group=g, **kpi(v)) for g,v in groups.items()]
    by_group.sort(key=lambda r: (r['error_rate'] is None, -(r['error_rate'] or 0), r['group']))
    trend = []
    for i in reversed(range(weeks)):
        w = (date.fromisoformat(week) - timedelta(days=7*i)).isoformat(); k = kpi(review_rows(data, dept,w,group,person))
        trend.append(dict(week=w, **{key:k[key] for key in ('total','passed','returned','error_rate')}))
    flags = Counter(f for r in rows for f in r['flags'])
    controls = review_rows(data, 'field',week,group,person)
    return dict(options=review_options(data,dept),dept=dept, week=week, kpi=kpi(rows), kpi_prev=kpi(review_rows(data,dept,prev,group,person)), trend=trend,
        by_group=by_group, by_person=[dict(person=p or '未填',person_key=p or '__blank__',group=g,**kpi(v)) for (p,g),v in sorted(people.items())],
        by_item=sorted([dict(item=item,total=len(v),returned=kpi(v)['returned'],passed=kpi(v)['passed'],error_rate=kpi(v)['error_rate']) for item,v in items.items()], key=lambda r:(-r['total'],r['item']))[:15],
        flags=[dict(flag=f,count=n,share=n/len(rows)) for f,n in sorted(flags.items())],
        control=dict(checked=sum(r['control_checked'] is True for r in controls),unchecked=sum(r['control_checked'] is False for r in controls), violated=sum('違反檢核程序' in r['flags'] for r in controls)))


def page(rows, params, default, aliases=None):
    key = (aliases or {}).get(params.get('sort',default), params.get('sort',default))
    rows = sorted(rows, key=lambda r: str(r.get('id', r.get('code', r.get('case_code','')))))
    known = [r for r in rows if r.get(key) not in (None, '')]; missing = [r for r in rows if r.get(key) in (None, '')]
    known.sort(key=lambda r:({'passed':0,'returned':1,'pending':2,'unset':3}.get(r[key],r[key]) if key=='status' else r.get(key,'')), reverse=params.get('order','asc')=='desc')
    rows = known + missing
    offset, limit = params.get('offset',0), params.get('limit',50)
    return dict(items=rows[offset:offset+limit],total=len(rows),offset=offset,limit=limit)


def rows_report(data, **p):
    rows = review_rows(data, **p)
    rows = [r for r in rows if (not p.get('status') or r['status']==p['status']) and (not p.get('flag') or p['flag'] in r['flags']) and (not p.get('q') or p['q'].casefold() in ' '.join(str(v) for v in (r['no'],r['case_code'],r['person'],r['item'],r['note'])).casefold())]
    return page(rows,p,'date',{'case':'case_code'})


def sales(data, **p):
    rows=[]; status=defaultdict(list); pm=defaultdict(list)
    for r in data['tables'].get('case',[]):
        f=r['f']; s=str(cell(f.get('狀態'))) or '未填'; manager=str(cell(f.get('PM'))) or '未填'
        if p.get('status') and s!=p['status'] or p.get('pm') and manager!=p['pm']: continue
        row=dict(id=r['id'],code=str(cell(f.get('案件編號'))),name=str(cell(f.get('案件名稱'))),client=str(cell(f.get('業主'))),pm=manager,status=s,
            contract=contract(f),progress_revenue=number(f.get('營業額進度')),progress_cost=number(f.get('成本進度')),progress_billing=number(f.get('計價進度')),
            billable_unbilled=number(f.get('可請款未請')),receivable=number(f.get('應收未收')),link=record_link(data['base'],'case',r['id']))
        rows.append(row);status[s].append(row);pm[manager].append(row)
    def total(key): return nullable_sum(r.get(key) for r in rows)
    cases=[r['f'] for r in data['tables'].get('case',[]) if (not p.get('status') or (cell(r['f'].get('狀態')) or '未填')==p['status']) and (not p.get('pm') or (cell(r['f'].get('PM')) or '未填')==p['pm'])]
    return dict(options={key:sorted({str(cell(r['f'].get(field))) or '未填' for r in data['tables'].get('case',[])}) for key,field in [('status','狀態'),('pm','PM')]},kpi=dict(cases=len(rows),contract_total=total('contract'),billed_total=nullable_sum(number(f.get('累計已請款')) for f in cases),received_total=nullable_sum(number(f.get('累計已入帳')) for f in cases),unbilled_billable=total('billable_unbilled'),receivable=total('receivable')),
        by_status=[dict(status=s,count=len(v),contract_total=nullable_sum(r['contract'] for r in v)) for s,v in sorted(status.items())],
        by_pm=[dict(pm=s,count=len(v),contract_total=nullable_sum(r['contract'] for r in v),progress=weighted_progress(v)) for s,v in sorted(pm.items())],**page(rows,p,'code'))


def assets(data, **p):
    kind=p.get('kind','vehicle'); start=p['from']; end=p['to']; end_day=date.fromisoformat(end)
    use=defaultdict(list); kms=defaultdict(list); excluded=0; linked_costs={'vehicle':set(),'instrument':set()}
    for asset_kind,columns in [('vehicle',('第一台車紀錄','第二台車紀錄','第三台車紀錄')),('instrument',('使用此儀器的成本單',))]:
        for asset in data['tables'].get(asset_kind,[]):
            for column in columns: linked_costs[asset_kind].update(links(asset['f'].get(column)))
    costs={r['id']:r['f'] for r in data['tables'].get('field_cost',[])}
    for asset in data['tables'].get(kind,[]):
        columns=('使用此儀器的成本單',) if kind=='instrument' else ('第一台車紀錄','第二台車紀錄','第三台車紀錄')
        for slot,column in enumerate(columns,1):
            for cost_id in set(links(asset['f'].get(column))):
                f=costs.get(cost_id,{})
                dt=data['cost_dates'].get(cost_id)
                if not dt or dt>end: continue
                ident=asset['id']; use[ident].append(dt)
                if dt>=start and kind=='vehicle':
                    first=number(f.get('出發里程'+str(slot))); last=number(f.get('結束里程'+str(slot)))
                    if first is not None and last is not None and last>=first: kms[ident].append(last-first)
                    else: excluded+=1
    rows=[]; active_ids=set(); options=defaultdict(set)
    for r in data['tables'].get(kind,[]):
        f=r['f']; ident=r['id']; days=use[ident]; selected=[dt for dt in days if start<=dt<=end]
        active=f.get('啟用') is True
        if active: active_ids.add(ident)
        status=str(cell(f.get('狀態'))) or ('啟用' if active else '停用') if kind=='vehicle' else str(cell(f.get('狀態')))
        owner=vehicle_owner(str(cell(f.get('備註')))) if kind=='vehicle' else ''
        last=max(days) if days else None
        row=dict(id=ident,name=str(cell(f.get('車牌') if kind=='vehicle' else f.get('儀器名稱'))),category=str(cell(f.get('類別'))) or ('車輛' if kind=='vehicle' else ''),status=status,owner=owner,
            uses=len(selected),km=sum(v for v in kms[ident] if v is not None) if kind=='vehicle' and any(v is not None for v in kms[ident]) else None,
            last_used=last,idle_days=(end_day-date.fromisoformat(last)).days if last else None,daily_rent=number(f.get('日租金')) if kind=='instrument' else None,note=str(cell(f.get('備註'))),link=record_link(data['base'],kind,ident))
        for key in ('status','category','owner'): options[key].add(row[key] or '__blank__')
        if any(p.get(k) and ('' if p[k]=='__blank__' else p[k])!=row[k] for k in ('status','category','owner')): continue
        if p.get('idle_days') is not None and (row['idle_days'] is not None and row['idle_days']<p['idle_days']): continue
        if p.get('q') and p['q'].casefold() not in (row['name']+' '+row['note']).casefold(): continue
        rows.append(row)
    cats=defaultdict(list)
    for r in rows: cats[r['category']].append(r)
    repair=lambda r: '送修' in r['status'] or '損壞' in r['status'] or '出險' in r['status']
    window={ident for ident,dt in data['cost_dates'].items() if start<=(dt or '')<=end}
    coverage={k:ratio(len(ids & window),len(window)) for k,ids in linked_costs.items()}
    gaps=[gap('asset-'+k+'-coverage',f'{len(ids & window)} / {len(window)} 張成本單有'+('車輛' if k=='vehicle' else '儀器')+'紀錄') for k,ids in linked_costs.items()]
    if excluded: gaps.append(gap('mileage-excluded',f'{excluded} 組里程因缺值或倒退排除，僅計部分里程'))
    return dict(gaps=gaps,options={k:sorted(v) for k,v in options.items()},kind=kind,**{'from':start,'to':end},kpi=dict(mileage_excluded=excluded,coverage=coverage[kind],total=len(rows),active=sum(r['id'] in active_ids for r in rows),in_use=sum(r['uses']>0 for r in rows),idle=sum(r['uses']==0 for r in rows),repair=sum(repair(r) for r in rows),km=sum(r['km'] or 0 for r in rows) if any(r['km'] is not None for r in rows) else None,daily_rent_total=sum(r['daily_rent'] or 0 for r in rows) if any(r['daily_rent'] is not None for r in rows) else None),
        by_category=[dict(category=c,total=len(v),in_use=sum(r['uses']>0 for r in v),repair=sum(repair(r) for r in v)) for c,v in sorted(cats.items())],
        usage_trend=[dict(week=w,uses=n) for w,n in sorted(Counter(monday(dt) for r in rows for dt in use[r['id']] if start<=dt<=end).items())],**page(rows,p,'name'))


def nullable_sum(values):
    values=[v for v in values if v is not None]
    return sum(values) if values else None


def vehicle_owner(note):
    if any(v in note for v in ('待確認','请确认','？')): return '待確認'
    if any(v in note for v in ('租','上准','格上','朝阳','朝陽')): return '租賃'
    return '自有' if '自有' in note else ''


def case_codes(value):
    return {v.strip() for v in str(cell(value)).split(',') if v.strip() and v.strip()!='C000000'}


def review_options(data,dept):
    rows=review_rows(data,dept)
    return dict(group=sorted({r['group'] for r in rows}),person=sorted({p or '__blank__' for r in rows for p in r['person'].split(',')}),flag=sorted({f for r in rows for f in r['flags']}))


def weighted_progress(rows):
    weighted=[r for r in rows if r['contract'] is not None and r['contract']>0 and r['progress_revenue'] is not None]
    return ratio(sum(r['contract']*r['progress_revenue'] for r in weighted),sum(r['contract'] for r in weighted))


def filter_progress(rows: list[ProgressRow], status: str='', q: str='') -> list[ProgressRow]:
    search=q.casefold()
    return [r for r in rows if (not status or r['status']==status) and
            (not search or search in (r['case_code']+' '+r['case_name']).casefold())]


def progress_case(data, key: str, dept: str='field', week: str | None=None) -> CaseDetail:
    record=next((r for r in data['tables'].get('case',[]) if r['id']==key),None)
    if record is None: raise CaseNotFound('case_not_found')
    f=record['f']; code=str(cell(f.get('案件編號')))
    people={r['id']:str(cell(r['f'].get('姓名'))) or '未填' for r in data['tables'].get('people',[])}
    def plan_people(value):
        ids=links(value)
        return ','.join(people.get(key,'未填') for key in ids) if ids else str(cell(value)) or '未填'
    plans=[dict(date=r['date'],group=r['group'],people=plan_people(r['f'].get('人員')),
                items=' · '.join(str(cell(r['f'].get(key))) for key in ('預排工作項目','工作內容') if cell(r['f'].get(key))),points=number(r['f'].get('預估營業額點數')))
           for r in data['plan_indices'].get((dept,week),[]) if code in case_codes(r['f'].get('案件'))]
    work=[dict(date=r['date'],group=r['group'],person=r['person'],item=r['item'],points=r['points'],
               checks=dict(status=r['status'],control_checked=r['control_checked']),flags=r['flags'],note=r['note'])
          for r in review_rows(data,dept,week) if code in case_codes(r['case_code'])]
    plans.sort(key=lambda r:(r['date'],r['group']))
    work.sort(key=lambda r:(r['date'],r['group'],r['person']))
    planned={r['date'] for r in plans}; actual={r['date'] for r in work}
    return dict(case=dict(code=code,name=str(cell(f.get('案件名稱'))),client=str(cell(f.get('業主'))),
        pm=str(cell(f.get('PM'))),status=str(cell(f.get('狀態'))) or '未填',
        contract=dict(expected=number(f.get('預期合約金額')),actual=number(f.get('實際合約金額'))),
        billing=dict(billed=number(f.get('累計已請款')),receivable=number(f.get('應收未收')),progress=number(f.get('計價進度'))),
        revenue_progress=number(f.get('營業額進度')),cost_progress=number(f.get('成本進度')),
        expected_points=number(f.get('預期營業額點數')),
        cumulative_points_by_dept=dict(field=number(f.get('累計外業營業額點數')),office=number(f.get('累計內業營業額點數')))),
        week=dict(dept=dept,week=week,basis=data['plan_basis'],plan_rows=plans[:200],work_rows=work[:200],
                  matched=len(planned & actual),unplanned=len(actual-planned),truncated=len(plans)>200 or len(work)>200),
        link=record_link(data['base'],'case',key))


def progress_groups(data,dept,week,selected,included,group_plan,group_actual,basis,filtered):
    group_points=defaultdict(lambda:[0,0])
    actual_points=defaultdict(float)
    for r in data['plan_indices'].get((dept,week),[]):
        if selected and selected!=r['group']: continue
        group_points[r['group']][0]+=sum(number(r['f'].get('預估營業額點數')) or 0 for code in case_codes(r['f'].get('案件')) if code in included)
    for r in review_rows(data,dept,week,selected or ''):
        codes=case_codes(r['case_code'])
        share=(r['points'] or 0)/len(codes) if codes else 0
        actual_points[r['group']]+=(share*len(codes & included) if filtered else r['points'] or 0)
        group_points[r['group']][1]+=sum(share if filtered else r['points'] or 0 for code in codes & included if (code,r['date']) in group_plan.get(r['group'],set()))
    by_group=[]
    for g in sorted(set(group_plan)|set(group_actual)):
        plg=len(group_plan[g]) if basis=='days' else group_points[g][0]
        acg=len(group_actual[g]) if basis=='days' else actual_points[g]
        numerator=len(group_plan[g]&group_actual[g]) if basis=='days' else group_points[g][1]
        by_group.append(dict(group=g,group_label=g,matched_points=group_points[g][1],planned_days=len(group_plan[g]),matched_days=len(group_plan[g]&group_actual[g]),planned=plg,actual=acg,unplanned_days=len(group_actual[g]-group_plan[g]),achievement=ratio(numerator,plg)))
    return by_group


def progress(data, **p) -> ProgressResponse:
    dept=p.get('dept','field'); week=p['week']; selected=normalize_group(p['group']) if p.get('group') else None
    plans=defaultdict(float); actual=defaultdict(float); matched_points=defaultdict(float)
    planned=defaultdict(set); dates=defaultdict(set); group_plan=defaultdict(set); group_actual=defaultdict(set)
    basis=data['plan_basis']
    for r in data['plan_indices'].get((dept,week),[]):
        f=r['f']; group=r['group']
        if selected and selected!=group: continue
        for code in case_codes(f.get('案件')):
            planned[code].add(r['date']); group_plan[group].add((code,r['date']))
            plans[code]+=number(f.get('預估營業額點數')) or 0
    for r in review_rows(data,dept,week,p.get('group','')):
        for code in case_codes(r['case_code']):
            actual[code]+=r['points'] or 0; dates[code].add(r['date'])
            group_actual[r['group']].add((code,r['date']))
            if r['date'] in planned[code]: matched_points[code]+=r['points'] or 0
    cases=data['cases']; codes=set(planned)|set(dates)
    if p.get('scope')=='open' and not selected: codes.update(c for c,r in cases.items() if '執行中' in str(cell(r['f'].get('狀態'))))
    rows=[]
    for code in sorted(codes):
        r=cases.get(code,{'id':'','f':{}});f=r['f']; expected=number(f.get('預期營業額點數'));done=number(f.get('累計外業營業額點數' if dept=='field' else '累計內業營業額點數'))
        pd=len(planned[code]); ad=len(dates[code]); matched=len(dates[code]&planned[code]); pl=plans[code]; ac=actual[code]
        rows.append(dict(case_key=r['id'] or None,case_code=code,case_name=str(cell(f.get('案件名稱'))) or '案件資料未建立',planned=pl,actual=ac,matched_points=matched_points[code],planned_days=pd,actual_days=ad,matched_days=matched,unplanned_days=ad-matched,achievement=ratio(matched,pd) if basis=='days' else ratio(matched_points[code],pl),diff=ad-pd if basis=='days' else ac-pl,expected_total=expected,done_total=done,remaining=expected-done if expected is not None and done is not None else None,status=str(cell(f.get('狀態'))) or '未填',link=record_link(data['base'],'case',r['id'])))
    counts=Counter(r['status'] for r in filter_progress(rows,q=p.get('q','')))
    observed={str(cell(r['f'].get('狀態'))) or '未填' for r in cases.values()} | {'未填'}
    if p.get('status') and p['status'] not in observed:
        raise UnknownStatus('status 不支援的值')
    rows=filter_progress(rows,p.get('status',''),p.get('q',''))
    included={r['case_code'] for r in rows}
    group_plan=defaultdict(set,{g:{x for x in v if x[0] in included} for g,v in group_plan.items()})
    group_actual=defaultdict(set,{g:{x for x in v if x[0] in included} for g,v in group_actual.items()})
    pd=sum(r['planned_days'] for r in rows); ad=sum(r['actual_days'] for r in rows); matched=sum(r['matched_days'] for r in rows); pl=sum(r['planned'] for r in rows); ac=sum(r['actual'] for r in rows)
    negative=sum(r['remaining'] is not None and r['remaining']<0 for r in rows)
    gaps=[gap('negative-remaining',f'{negative} 件剩餘點數為負，保留明細但不納入 KPI')] if negative else []
    by_group=progress_groups(data,dept,week,selected,included,group_plan,group_actual,basis,bool(p.get('status') or p.get('q')))
    options=sorted({r['group'] for r in data['plan_indices'].get((dept,week),[])}|{r['group'] for r in review_rows(data,dept,week)})
    return dict(gaps=gaps,options=dict(group=['__blank__' if g=='未分組' else g for g in options],status=[dict(status=s,count=n) for s,n in sorted(counts.items())]),dept=dept,week=week,basis=basis,kpi=dict(matched_points=sum(r['matched_points'] for r in rows),planned_points=pl if basis=='points' else None,actual_points=ac,planned_days=pd,actual_days=ad,matched_days=matched,unplanned_days=ad-matched,achievement=ratio(matched,pd) if basis=='days' else ratio(sum(r['matched_points'] for r in rows),pl),open_cases=sum('執行中' in r['status'] for r in rows),remaining_points=nullable_sum(r['remaining'] for r in rows if '執行中' in r['status'] and r['remaining'] is not None and r['remaining']>=0)),by_group=by_group,**page(rows,p,'case_code',{'name':'case_name'}))


def sources(data, fetched_at):
    return dict(base=dict(name='詠翔日報系統 v3',token=data['base'],url=f'https://www.larksuite.com/base/{data["base"]}'),tables=[dict(name=t.name,table_id=t.table_id,kind=t.kind,rows=len(data['tables'].get(t.kind,[])),used_fields=list(t.fields),status=data['raw'].get(t.kind,{}).get('status','never'),fetched_at=fetched_at if data['raw'].get(t.kind,{}).get('status')=='ok' else None,used_by=list(t.used_by)) for t in TABLES])


def report_gaps(data, endpoint, dept='field'):
    if endpoint=='progress/case': endpoint='progress'
    department='field' if dept=='control' else dept
    relevant={
        'review': {department+'-date',department+'-group'} | ({'office-review-coverage','PM檢核','內業組長檢核'} if department=='office' else set()),
        'review/rows': {department+'-date',department+'-group'} | ({'office-review-coverage','PM檢核','內業組長檢核'} if department=='office' else set()),
        'progress': {department+'-date',department+'-group','plan-negative-span'},
    }
    source_kinds={'contacts': {'crm_contact','v3_contact','case','people'}, 'review': {department,department+'_cost'}, 'review/rows': {department,department+'_cost'}, 'sales': {'case'}, 'assets': {'vehicle','instrument','field_cost','plan'}, 'progress': {'case','plan','contract','people',department}}
    allowed=relevant.get(endpoint,set()) | {'source-'+k for k in source_kinds.get(endpoint,set())}
    gaps=[g for g in data['gaps'] if endpoint=='sources' or g['id'] in allowed]
    if endpoint=='sales':
        records=data['tables'].get('case',[])
        zero=sum(number(r['f'].get('實際合約金額'))==0 and (number(r['f'].get('預期合約金額')) or 0)>0 for r in records)
        if zero: gaps.append(gap('sales-zero-contract',f'{zero} 件實際合約金額為 0，改用預期金額'))
        values=[(str(cell(r['f'].get('案件編號'))),contract(r['f'])) for r in records]
        positive=[v for _,v in values if v is not None and v>0]
        if positive:
            total=sum(positive); median=statistics.median(positive)
            outliers=[code for code,v in values if v is not None and (v>total*.5 or v>100*median)]
            if outliers: gaps.append(gap('sales-contract-outliers',f'{len(outliers)} 件合約超過總額 50% 或中位數 100 倍：'+ '、'.join(outliers)))
        for key in ('實際合約金額','案件可請款總額','累計已請款','累計已入帳','可請款未請','應收未收'):
            rows=data['tables'].get('case',[])
            n=sum(number(r['f'].get(key)) is not None for r in rows)
            if n<len(rows): gaps.append(gap('sales-'+key,f'案件 {key} 僅 {n}/{len(rows)} 有值；全空時顯示來源無資料；部分有值時僅加總有值資料，非完整總額'))
        missing_code=sum(not cell(r['f'].get('案件編號')) for r in data['tables'].get('case',[]))
        if missing_code: gaps.append(gap('sales-code',f'{missing_code} 件案件未填編號'))
        blank=sum(not cell(r['f'].get('狀態')) for r in data['tables'].get('case',[]))
        gaps += [gap('sales-status',f'案件狀態 {blank} 筆未填'),gap('sales-intake','業務接案量／成交量與請款詳情來源尚未建立')]
    if endpoint=='assets':
        for key in ('類別','狀態'):
            records=data['tables'].get('instrument',[])
            n=sum(not cell(r['f'].get(key)) for r in records)
            if n: gaps.append(gap('instrument-'+key,f'儀器費率 {key} {n}/{len(records)} 未填'))
        plans=data['tables'].get('plan',[])
        vehicle=sum(bool(links(r['f'].get('車輛'))) for r in plans)
        instrument=sum(bool(links(r['f'].get('儀器'))) for r in plans)
        gaps.append(gap('asset-planned-coverage',f'工作預排全期車輛 {vehicle} 列、儀器 {instrument} 列；預排不計入實際使用次數','info'))
        gaps += [gap('asset-inspections','TAF、自校驗、月租檢查來源尚未建立'),gap('asset-planned','工作預排僅供安排參考，使用次數以實際出工紀錄計算','info')]
    if endpoint=='progress': gaps += [gap('progress-basis','預排點數全空時依台北日期展開預排，以已預排案件日期的實際出工天數計算達成率；未預排出工另列；未指定案件不納入。剩餘點數為案件預期減部門累計，缺值顯示來源無資料。','info')]
    if endpoint=='progress':
        plan_groups={r['group'] for (d,_),rows in data['plan_indices'].items() if d==department for r in rows}
        actual_groups={r['group'] for r in data['reviews'][department]}
        unmatched=sorted(plan_groups^actual_groups)
        if unmatched: gaps.append(gap('progress-unmatched-groups','組別正規化後無對應：'+'、'.join(unmatched)))
        n=sum(number(r['f'].get('預估營業額點數')) is not None for r in data['tables'].get('plan',[]))
        gaps.append(gap('planned-coverage',f'工作預排預估營業額點數僅 {n}/{len(data["tables"].get("plan",[]))} 有值'))
    return gaps


def attach_local_bridges(result, bridges):
    result = dict(result)
    result['items'] = [{**row, 'local_cases': [dict(project_id=pid, status=b['status']) for pid, b in bridges.items()
                      if row.get('case_code') and b['status'] in ('auto_exact','reviewed') and row['case_code'] in b['codes']]}
                      for row in result.get('items', [])]
    return result


def contacts(data, **p):
    """Combine CRM and legacy contact records for the weekly report."""
    import re
    import unicodedata
    tables=data['tables']
    people=tables.get('people', [])
    person_ids={r['id']:str(cell(r['f'].get('姓名'))) for r in people}
    groups={str(cell(r['f'].get('姓名'))):str(cell(r['f'].get('所屬組別') or r['f'].get('組別') or r['f'].get('部門'))) for r in people}
    fallback={'朱雅琪':'工務助理','郭倢瑛':'工務助理','林瑩瑄':'工務助理','鍾智偉':'PM','吳重樺':'PM','吳科翰':'PM'}
    def unique(value):
        return list(dict.fromkeys(x.strip() for x in re.split(r'[,，、/]',str(cell(value))) if x.strip()))
    def first(f,*keys):
        return next((f[k] for k in keys if cell(f.get(k)) != ''), '')
    def timestamp(value):
        value=cell(value)
        try:
            n=float(value)
            return n if abs(n)>10000000 else n*86400000
        except (ValueError,TypeError):
            try:
                d=datetime.fromisoformat(str(value).replace('Z','+00:00'))
                return (d if d.tzinfo else d.replace(tzinfo=TZ)).timestamp()*1000
            except (ValueError,TypeError,OverflowError): return 0
    def build(r,kind):
        f=r['f']; rawdate=first(f,'活動時間','聯繫日期','有效日期','原建立時間','建立時間') or r.get('created_time'); dt=day(rawdate) or ''
        code=', '.join(unique(first(f,'工程編號','報編（尚未成案可填）','同步報價編號','報價編號')))
        name=', '.join(unique(f.get('工程名稱')))
        person=str(cell(first(f,'執行人','聯繫人員','建立者','原建立者','建立人'))); person=person_ids.get(person,person)
        methods=[{'line':'LINE','mail':'MAIL'}.get(x.lower(),x) for x in unique(f.get('聯繫方式'))]; methods=list(dict.fromkeys(methods))
        topics=unique(f.get('聯繫主題'))
        result=str(cell(first(f,'處理結果','結果')))
        if result.upper()=='OK' or result=='已完成' or f.get('已完成') is True: result='已完成'
        nextdate=day(first(f,'下一跟進日','下次追蹤日')) or ''
        table=BY_KIND[kind]
        return dict(id=r['id'],orig_id=str(cell(f.get('原記錄ID'))),contact_date=dt,contact_date_slash=dt.replace('-','/'),sort_ts=timestamp(rawdate),case_code=code,case_name=name,person=person,group=groups.get(person) or fallback.get(person,''),client_contact=str(cell(first(f,'業主窗口','客戶(同步)','同步業主','客戶'))),method=' / '.join(methods),methods=methods,topic='、'.join(topics),topics=topics,content=str(cell(first(f,'內容摘要','聯繫內容/業主回覆','聯繫內容'))),next_date=nextdate,next_date_slash=nextdate.replace('-','/'),special_note=str(cell(first(f,'下一步','待辦事項','特別事項','摘要'))),result=result,result_status='completed' if result=='已完成' else 'pending',link=f'https://yong-xiang-survey.jp.larksuite.com/base/{table.base_token}?table={table.table_id}&record={r["id"]}')
    crm=[build(r,'crm_contact') for r in tables.get('crm_contact',[])]; legacy={r['id']:build(r,'v3_contact') for r in tables.get('v3_contact',[])}
    used=set()
    for r in crm:
        v=legacy.get(r['orig_id'])
        if v:
            used.add(v['id'])
            for key in ('contact_date','contact_date_slash','sort_ts','case_code','case_name','person','group','client_contact','method','methods','topic','topics','content','next_date','next_date_slash','special_note','result'):
                if not r[key]: r[key]=v[key]
            r['result_status']='completed' if r['result']=='已完成' else 'pending'
    rows=crm+[v for ident,v in legacy.items() if ident not in used]
    for r in rows:
        if not r['case_name']:
            case=data['cases'].get(r['case_code']) or data['cases'].get(r['case_code'].split(',')[0].strip())
            r['case_name']=str(cell(first(case['f'],'案件名稱','工程名稱'))) if case else ('115年度第二辦公室安全觀測' if r['case_code'].split(',')[0].strip()=='C115180-3' else '')
    start=p.get('week') or p.get('from') or ''; end=(date.fromisoformat(p['week'])+timedelta(days=6)).isoformat() if p.get('week') else p.get('to') or ''
    rows=[r for r in rows if r['contact_date'] and (not start or r['contact_date']>=start) and (not end or r['contact_date']<=end) and any(r[k] for k in ('case_code','case_name','person','client_contact','content','special_note','method','topic','result'))]
    raw_total=len(rows)
    options={k:sorted({v for r in rows for v in (r['topics'] if k=='topic' else r['methods'] if k=='method' else [r[k]]) if v}) for k in ('group','person','topic','method','result_status')}
    q=unicodedata.normalize('NFKC',p.get('q','')).casefold()
    rows=[r for r in rows if all(not p.get(k) or p[k]=='all' or (p[k] in r[k+'s'] if k in ('topic','method') else p[k]==r[k]) for k in ('group','person','topic','method','result_status')) and (not q or q in unicodedata.normalize('NFKC',' '.join(r[k] for k in ('case_code','case_name','client_contact','content','person','special_note'))).casefold())]
    mode=p.get('dedup_mode','latest_per_day')
    if mode=='latest_per_day':
        buckets=defaultdict(list)
        for r in rows: buckets[(r['case_code'] or r['client_contact'] or r['id'],r['contact_date'])].append(r)
        rows=[]
        for bucket in buckets.values():
            r=max(bucket,key=lambda x:(x['sort_ts'],x['id'])).copy();r['same_day_count']=len(bucket);rows.append(r)
    else:
        rows=[dict(r,same_day_count=1) for r in rows]
    sort=p.get('sort','contact_date'); order=p.get('order','desc' if sort=='contact_date' else 'asc')
    rows.sort(key=lambda r: (r.get(sort,'') or '',r['sort_ts'],r['id']),reverse=order=='desc')
    total=len(rows); kpi=dict(total=total,raw_total=raw_total,cases_count=len({r['case_code'] for r in rows if r['case_code']}),completed_count=sum(r['result_status']=='completed' for r in rows),pending_count=sum(r['result_status']=='pending' for r in rows))
    offset=int(p.get('offset',0));limit=int(p.get('limit',200))
    return dict(items=rows[offset:offset+limit],total=total,raw_total=raw_total,kpi=kpi,options=options,date_range={'from':start,'to':end},dedup_mode=mode,gaps=report_gaps(data,'contacts'),offset=offset,limit=limit)
