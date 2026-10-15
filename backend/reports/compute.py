"""Pure normalization and report calculations. Dates are Taipei calendar dates."""
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
import math
from zoneinfo import ZoneInfo
from .registry import BASE_TOKEN, BY_KIND, FLAGS, TABLES

TZ = ZoneInfo('Asia/Taipei')
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


def normalize(raw, base=BASE_TOKEN):
    tables = {k: [dict(id=r['record_id'], f=r['fields']) for r in v['records']] for k, v in raw.items()}
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
            reviews[dept].append(dict(id=r['id'], no=str(cell(f.get('工作單號'))), date=dt or '', group=str(group),
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
    plan_indices=defaultdict(list)
    for r in tables.get('plan',[]):
        dt=day(r['f'].get('開始日期')); dept={'外業':'field','內業':'office'}.get(cell(r['f'].get('業別')))
        if dt and dept and cell(r['f'].get('條類型'))=='出工': plan_indices[(dept,monday(dt))].append(r)
    cases={str(cell(r['f'].get('案件編號'))):r for r in tables.get('case',[])}
    plan_basis='points' if any(number(r['f'].get('預估營業額點數')) is not None for r in tables.get('plan',[])) else 'days'
    return dict(plan_basis=plan_basis,plan_indices=plan_indices,cases=cases,tables=tables, reviews=reviews, indices=indices, gaps=gaps, raw=raw, base=base)


def record_link(base, kind, ident):
    return f'https://www.larksuite.com/base/{base}?table={BY_KIND[kind].table_id}&record={ident}'


def kpi(rows):
    counts = Counter(r['status'] for r in rows); total = len(rows)
    return dict(total=total, **{s: counts[s] for s in ('passed','returned','pending','unset')},
                error_rate=ratio(counts['returned'], counts['passed'] + counts['returned']),
                pending_rate=ratio(counts['pending'], total), coverage=ratio(counts['passed'] + counts['returned'], total))


def review_rows(data, dept, week=None, group='', person='', **_):
    source = 'office' if dept == 'control' else dept
    rows = data['indices'][source].get(week, []) if week else data['reviews'][source]
    return [r for r in rows if (dept != 'control' or r['group'] == '控制') and (not group or group == r['group']) and (not person or person in r['person'].split(','))]


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
    return dict(dept=dept, week=week, kpi=kpi(rows), kpi_prev=kpi(review_rows(data,dept,prev,group,person)), trend=trend,
        by_group=by_group, by_person=[dict(person=p,group=g,**kpi(v)) for (p,g),v in sorted(people.items())],
        by_item=sorted([dict(item=item,total=len(v),returned=kpi(v)['returned'],passed=kpi(v)['passed'],error_rate=kpi(v)['error_rate']) for item,v in items.items()], key=lambda r:(-r['total'],r['item']))[:15],
        flags=[dict(flag=f,count=n,share=n/len(rows)) for f,n in sorted(flags.items())],
        control=dict(checked=sum(r['control_checked'] is True for r in controls),unchecked=sum(r['control_checked'] is False for r in controls), violated=sum('違反檢核程序' in r['flags'] for r in controls)))


def page(rows, params, default, aliases=None):
    key = (aliases or {}).get(params.get('sort',default), params.get('sort',default))
    rows = sorted(rows, key=lambda r: str(r.get('id', r.get('code', r.get('case_code','')))))
    known = [r for r in rows if r.get(key) is not None]; missing = [r for r in rows if r.get(key) is None]
    known.sort(key=lambda r:r.get(key,''), reverse=params.get('order','asc')=='desc')
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
        row=dict(code=str(cell(f.get('案件編號'))),name=str(cell(f.get('案件名稱'))),client=str(cell(f.get('業主'))),pm=manager,status=s,
            contract=number(f.get('實際合約金額')) if number(f.get('實際合約金額')) is not None else number(f.get('預期合約金額')),progress_revenue=number(f.get('營業額進度')),progress_cost=number(f.get('成本進度')),progress_billing=number(f.get('計價進度')),
            billable_unbilled=number(f.get('可請款未請')),receivable=number(f.get('應收未收')),link=record_link(data['base'],'case',r['id']))
        rows.append(row);status[s].append(row);pm[manager].append(row)
    def total(key): return nullable_sum(r.get(key) for r in rows)
    cases=[r['f'] for r in data['tables'].get('case',[]) if (not p.get('status') or (cell(r['f'].get('狀態')) or '未填')==p['status']) and (not p.get('pm') or (cell(r['f'].get('PM')) or '未填')==p['pm'])]
    return dict(kpi=dict(cases=len(rows),contract_total=total('contract'),billed_total=nullable_sum(number(f.get('累計已請款')) for f in cases),received_total=nullable_sum(number(f.get('累計已入帳')) for f in cases),unbilled_billable=total('billable_unbilled'),receivable=total('receivable')),
        by_status=[dict(status=s,count=len(v),contract_total=sum(r['contract'] or 0 for r in v)) for s,v in sorted(status.items())],
        by_pm=[dict(pm=s,count=len(v),contract_total=sum(r['contract'] or 0 for r in v),progress=ratio(sum(r['progress_revenue'] or 0 for r in v if r['progress_revenue'] is not None),sum(r['progress_revenue'] is not None for r in v))) for s,v in sorted(pm.items())],**page(rows,p,'code'))


def assets(data, **p):
    kind=p.get('kind','vehicle'); start=p['from']; end=p['to']; end_day=date.fromisoformat(end)
    use=defaultdict(list); kms=defaultdict(list); trend=Counter()
    costs={r['id']:r['f'] for r in data['tables'].get('field_cost',[])}
    for asset in data['tables'].get(kind,[]):
        columns=('使用此儀器的成本單',) if kind=='instrument' else ('第一台車紀錄','第二台車紀錄','第三台車紀錄')
        for slot,column in enumerate(columns,1):
            for cost_id in set(links(asset['f'].get(column))):
                f=costs.get(cost_id,{})
                dt=day(f.get('工作日期'))
                if not dt or dt>end: continue
                ident=asset['id']; use[ident].append(dt)
                if dt>=start and kind=='vehicle':
                    first=number(f.get('出發里程'+str(slot))); last=number(f.get('結束里程'+str(slot)))
                    if first is not None and last is not None and last>=first: kms[ident].append(last-first)
    rows=[]; active_ids=set()
    for r in data['tables'].get(kind,[]):
        f=r['f']; ident=r['id']; days=use[ident]; selected=[dt for dt in days if start<=dt<=end]
        active=f.get('啟用') is True
        if active: active_ids.add(ident)
        status=str(cell(f.get('狀態'))) or ('啟用' if active else '停用') if kind=='vehicle' else str(cell(f.get('狀態'))) or '未填'
        owner=vehicle_owner(str(cell(f.get('備註')))) if kind=='vehicle' else ''
        last=max(days) if days else None
        row=dict(id=ident,name=str(cell(f.get('車牌') if kind=='vehicle' else f.get('儀器名稱'))),category=str(cell(f.get('類別'))) or ('車輛' if kind=='vehicle' else '未填'),status=status,owner=owner,
            uses=len(selected),km=sum(v for v in kms[ident] if v is not None) if kind=='vehicle' and any(v is not None for v in kms[ident]) else None,
            last_used=last,idle_days=(end_day-date.fromisoformat(last)).days if last else None,daily_rent=number(f.get('日租金')) if kind=='instrument' else None,note=str(cell(f.get('備註'))),link=record_link(data['base'],kind,ident))
        if any(p.get(k) and p[k]!=row[k] for k in ('status','category','owner')): continue
        if p.get('idle_days') is not None and (row['idle_days'] is None or row['idle_days']<p['idle_days']): continue
        if p.get('q') and p['q'].casefold() not in (row['name']+' '+row['note']).casefold(): continue
        rows.append(row)
    cats=defaultdict(list)
    for r in rows: cats[r['category']].append(r)
    repair=lambda r: '送修' in r['status'] or '損壞' in r['status'] or '出險' in r['status']
    return dict(kind=kind,**{'from':start,'to':end},kpi=dict(total=len(rows),active=sum(r['id'] in active_ids for r in rows),in_use=sum(r['uses']>0 for r in rows),idle=sum(r['uses']==0 for r in rows),repair=sum(repair(r) for r in rows),km=sum(r['km'] or 0 for r in rows) if any(r['km'] is not None for r in rows) else None,daily_rent_total=sum(r['daily_rent'] or 0 for r in rows) if any(r['daily_rent'] is not None for r in rows) else None),
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


def progress(data, **p):
    dept=p.get('dept','field'); week=p['week']; plans=defaultdict(float); actual=defaultdict(float)
    planned_days=Counter(); dates=defaultdict(set); groups=defaultdict(lambda:[0,0])
    basis=data['plan_basis']
    for r in data['plan_indices'].get((dept,week),[]):
        f=r['f']; group=str(cell(f.get('組別')))
        if p.get('group') and p['group']!=group: continue
        for code in case_codes(f.get('案件')):
            planned_days[code]+=1; plans[code]+=number(f.get('預估營業額點數')) or 0
            groups[group][0]+=1 if basis=='days' else number(f.get('預估營業額點數')) or 0
    group_dates=defaultdict(set)
    for r in review_rows(data,dept,week,p.get('group','')):
        for code in case_codes(r['case_code']):
            actual[code]+=r['points'] or 0; dates[code].add(r['date'])
            group_dates[r['group']].add((code,r['date']))
            if basis=='points': groups[r['group']][1]+=r['points'] or 0
    if basis=='days':
        for group,days in group_dates.items(): groups[group][1]=len(days)
    cases=data['cases']; codes=set(planned_days)|set(dates)
    if p.get('scope')=='open': codes.update(c for c,r in cases.items() if '執行中' in str(cell(r['f'].get('狀態'))))
    rows=[]
    for code in sorted(codes):
        r=cases.get(code,{'id':'','f':{}});f=r['f']; expected=number(f.get('預期營業額點數'));done=number(f.get('累計外業營業額點數' if dept=='field' else '累計內業營業額點數'))
        pd=planned_days[code]; ad=len(dates[code]); pl=plans[code]; ac=actual[code]
        rows.append(dict(case_code=code,case_name=str(cell(f.get('案件名稱'))),planned=pl,actual=ac,planned_days=pd,actual_days=ad,achievement=ratio(ad,pd) if basis=='days' else ratio(ac,pl),diff=ac-pl,expected_total=expected,done_total=done,remaining=expected-done if expected is not None and done is not None else None,status=str(cell(f.get('狀態'))) or '未填',link=record_link(data['base'],'case',r['id'])))
    pd=sum(planned_days.values()); ad=sum(len(v) for v in dates.values()); pl=sum(plans.values()); ac=sum(actual.values())
    return dict(dept=dept,week=week,basis=basis,kpi=dict(planned_points=pl if basis=='points' else None,actual_points=ac,planned_days=pd,actual_days=ad,achievement=ratio(ad,pd) if basis=='days' else ratio(ac,pl),open_cases=sum('執行中' in r['status'] for r in rows),remaining_points=nullable_sum(r['remaining'] for r in rows if '執行中' in r['status'])),by_group=[dict(group=g,planned=v[0],actual=v[1],achievement=ratio(v[1],v[0])) for g,v in sorted(groups.items())],**page(rows,p,'case_code'))


def sources(data, fetched_at):
    return dict(base=dict(name='詠翔日報系統 v3',token=data['base'],url=f'https://www.larksuite.com/base/{data["base"]}'),tables=[dict(name=t.name,table_id=t.table_id,kind=t.kind,rows=len(data['tables'].get(t.kind,[])),used_fields=list(t.fields),status=data['raw'].get(t.kind,{}).get('status','never'),fetched_at=fetched_at if data['raw'].get(t.kind,{}).get('status')=='ok' else None,used_by=list(t.used_by)) for t in TABLES])


def report_gaps(data, endpoint, dept='field'):
    department='field' if dept=='control' else dept
    relevant={
        'review': {department+'-date',department+'-group'} | ({'office-review-coverage','PM檢核','內業組長檢核'} if department=='office' else set()),
        'review/rows': {department+'-date',department+'-group'} | ({'office-review-coverage','PM檢核','內業組長檢核'} if department=='office' else set()),
        'progress': {department+'-date',department+'-group'},
    }
    source_kinds={'review': {department,department+'_cost'}, 'review/rows': {department,department+'_cost'}, 'sales': {'case'}, 'assets': {'vehicle','instrument','field_cost','plan'}, 'progress': {'case','plan','contract',department}}
    allowed=relevant.get(endpoint,set()) | {'source-'+k for k in source_kinds.get(endpoint,set())}
    gaps=[g for g in data['gaps'] if endpoint=='sources' or g['id'] in allowed]
    if endpoint=='sales':
        for key in ('實際合約金額','案件可請款總額','累計已請款','累計已入帳','可請款未請','應收未收'):
            rows=data['tables'].get('case',[])
            n=sum(number(r['f'].get(key)) is not None for r in rows)
            if n<len(rows): gaps.append(gap('sales-'+key,f'案件 {key} 僅 {n}/{len(rows)} 有值；全空時顯示來源無資料；部分有值時僅加總有值資料，非完整總額'))
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
    if endpoint=='progress': gaps += [gap('progress-basis','預排點數全空時依出工預排列數與實際不同工作日期計算天數達成率；未指定案件不納入。剩餘點數為案件預期減部門累計，缺值顯示來源無資料。','info')]
    if endpoint=='progress':
        n=sum(number(r['f'].get('預估營業額點數')) is not None for r in data['tables'].get('plan',[]))
        gaps.append(gap('planned-coverage',f'工作預排預估營業額點數僅 {n}/{len(data["tables"].get("plan",[]))} 有值'))
    return gaps
