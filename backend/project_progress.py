"""Per-case engineering progress read model: GET /api/projects/{project_id}/progress.

Pure and read-only. The input is the workspace state the caller already narrowed with the case-detail gates
(production_access -> visible_project -> filter_visible_cases -> case_redaction); this module never widens it and
never returns raw ``source_fields``, person names or per-person amounts. Absent data is ``None``/``unknown``, never 0.
The SOP-node status (業務/PM/... 節點指派) is NOT joined here; the frontend joins it next to these stages.

Stage rules (everything else is ``unknown`` with basis ``none``):
  sales         done/rule    正式案件工編為 C 加數字，或已有確認單與至少一筆合約明細（刪除的確認單與明細不算）
  pm            done/rule    已有確認單且至少一筆合約明細
  confirmation  done/rule    同上；有確認單但無明細為 active，無確認單為 waiting
  field..report active/source 只有日報真的連結到此案件且有回報量；done 一律不推論；無確認單為 waiting/rule
  billing       active/source 來源累計已請款 > 0；done/source 案件已入帳；無金額權限一律 unknown
  settlement    done/source  來源標示案件已入帳 (checkbox 未勾無法與未填區分，維持 unknown)；無金額權限一律 unknown
"""
import math
from decimal import Decimal, InvalidOperation
from typing import Literal, TypedDict

from .case_evidence import is_c_code, live_confirmation_fields, live_contract_lines, proves_sales_by_code
from .contract_links import CATEGORY_FIELDS, plan_summary
from .sources import day, text

SCHEMA_VERSION = 1
STAGES = (('sales', '業務'), ('pm', 'PM'), ('confirmation', '確認單'), ('field', '外業'), ('control', '控制'),
          ('mapping', '圖資'), ('report', '報告'), ('billing', '計價'), ('settlement', '結算'))
PRODUCTION = {'field': ('外業', '外業組'), 'control': ('控制', '控制組'), 'mapping': ('圖資', '圖資組'), 'report': ('報告', '報告組')}
PLANNING_FIELDS = frozenset(['工編號碼'] + [f for pair in CATEGORY_FIELDS.values() for f in pair])
MAX_ITEMS = 50
MAX_WEEKS = 6
NO_DAILY = '尚無日報連結到此案件'
BASIS_LABEL = {'native': 'native', 'derived': 'derived', 'ambiguous': 'ambiguous', 'unlinked': 'unlinked', 'native_unresolved': 'unlinked'}

StageState = Literal['done', 'active', 'waiting', 'unknown']
StageBasis = Literal['rule', 'source', 'none']
Tone = Literal['ok', 'warn', 'muted']


class Evidence(TypedDict):
    label: str
    value: str
    tone: Tone


class Stage(TypedDict):
    key: str
    label: str
    state: StageState
    basis: StageBasis
    evidence: list[Evidence]


class Confirmation(TypedDict):
    present: bool
    line_count: int
    fill_item_count: int | None
    source_status: str | None


class QuoteRef(TypedDict):
    number: str | None
    engineering_code: str | None
    status: str | None


class V3Case(TypedDict):
    case_key: str
    case_code: str
    status: str
    match: Literal['code', 'quote_number']


class Identity(TypedDict):
    code: str | None
    is_c_prefix: bool
    confirmation: Confirmation
    quotes: list[QuoteRef]
    v3_cases: list[V3Case]
    v3_ambiguous: bool


class PlanBasisCounts(TypedDict):
    native: int
    derived: int
    ambiguous: int
    unlinked: int


class Planned(TypedDict):
    lines: int
    items: int
    qty: str
    basis: PlanBasisCounts
    needs_review: int


class PlannedItem(TypedDict):
    item_id: str
    code: str | None
    name: str | None
    planned_qty: str | None
    link_basis: Literal['native', 'derived', 'ambiguous', 'unlinked']


class Actual(TypedDict):
    known: bool
    value: str | None
    unit_note: str | None
    reason: str | None
    source: Literal['v4_daily', 'v3_reports'] | None


class WorkOrders(TypedDict):
    count: int | None
    latest_date: str | None


class StageProduction(TypedDict):
    planned: Planned | None
    items: list[PlannedItem]
    items_total: int
    items_truncated: bool
    actual: Actual
    work_orders: WorkOrders


class ReportRow(TypedDict):
    case_key: str
    case_code: str
    dept: Literal['field', 'office']
    week: str
    basis: str
    planned: float
    actual: float
    planned_days: int
    actual_days: int
    matched_days: int
    achievement: float | None
    expected_total: float | None
    done_total: float | None
    remaining: float | None
    status: str


class Production(TypedDict):
    field: StageProduction
    control: StageProduction
    mapping: StageProduction
    report: StageProduction
    report_rows: list[ReportRow]
    report_rows_truncated: bool


class QuoteFinance(TypedDict):
    number: str | None
    invoiced_total: str | None
    billable_unrequested: str | None
    billable_total: str | None
    received_total: str | None
    received_date: str | None
    case_received: bool | None


class Finance(TypedDict):
    restricted: bool
    quotes: list[QuoteFinance]
    case_received: bool | None
    received_date: str | None


class Gap(TypedDict):
    id: str
    severity: Literal['info', 'warn']
    message_zh: str


class Sources(TypedDict):
    source_synced_at: str | None
    source_status: str | None
    reports_status: Literal['ok', 'cold', 'unavailable', 'restricted', 'disabled']
    reports_fetched_at: str | None
    reports_stale: bool | None


class ProjectProgress(TypedDict):
    schema_version: int
    project_id: str
    as_of: str | None
    sources: Sources
    identity: Identity
    stages: list[Stage]
    production: Production
    finance: Finance
    gaps: list[Gap]


class ReportsView:
    """Non-blocking look at the reports snapshot. A cached (even stale) snapshot is used as is; a cold store is only
    warmed in the background (single-flight, read-only) and reported as ``cold``. Never waits on Lark."""

    def __init__(self, store=None, status='ok', *, warm=True):
        self.store, self.status, self.data, self.fetched_at, self.stale = store, status, None, None, None
        if status != 'ok':
            return
        if store is None:
            self.status = 'disabled'
            return
        snapshot = store.peek()
        if snapshot is None:
            self.status = 'unavailable' if store.meta().get('refresh_error') else 'cold'
            if not warm:
                return
            try:
                store.start()
            except Exception:
                self.status = 'unavailable'
            return
        self.data, self.fetched_at, self.stale = snapshot['data'], snapshot['fetched_at'], store.meta(snapshot)['stale']

    def case(self, code):
        from .reports.compute import cell
        record = (self.data or {}).get('cases', {}).get(code) if code else None
        if record is None:
            return None
        return {'case_key': record['id'], 'case_code': code, 'status': str(cell(record['f'].get('狀態'))) or '未填'}

    def field_total(self, code):
        """The register's cumulative 外業 revenue points of one exact case, only when positive."""
        from .reports.compute import number
        record = (self.data or {}).get('cases', {}).get(code) if code else None
        total = number(record['f'].get('累計外業營業額點數')) if record else None
        return total if total and total > 0 else None

    def rows(self, code):
        """(rows, truncated): activity rows of one exact case code, newest weeks first, field and office."""
        from fastapi import HTTPException
        from .reports.compute import case_codes, monday
        data, rows, truncated = self.data, [], False
        weeks = {'field': set(), 'office': set()}
        for (dept, week), records in data['plan_indices'].items():
            if any(code in case_codes(r['f'].get('案件')) for r in records):
                weeks[dept].add(week)
        for dept, reviews in data['reviews'].items():
            weeks[dept].update(monday(r['date']) for r in reviews if r['date'] and code in case_codes(r['case_code']))
        key = data['cases'][code]['id']
        for dept, found in weeks.items():
            ordered = sorted(found, reverse=True)
            truncated = truncated or len(ordered) > MAX_WEEKS
            for week in ordered[:MAX_WEEKS]:
                try:
                    result = self.store.result('progress', {'dept': dept, 'week': week, 'scope': 'open', 'q': code, 'limit': 200})
                except HTTPException:
                    continue
                for item in result['items']:
                    if item['case_code'] == code and (item['planned_days'] or item['actual_days']):
                        rows.append({'case_key': key, 'case_code': code, 'dept': dept, 'week': week, 'basis': result['basis'],
                                     **{k: item[k] for k in ('planned', 'actual', 'planned_days', 'actual_days', 'matched_days',
                                                             'achievement', 'expected_total', 'done_total', 'remaining', 'status')}})
        rows.sort(key=lambda r: (r['week'], r['dept']), reverse=True)
        return rows, truncated


def _dec(value):
    raw = text(value).replace(',', '').strip()
    try:
        number = Decimal(raw) if raw else None
    except InvalidOperation:
        return None
    return number if number is not None and number.is_finite() else None


def parse_decimal(value):
    return _dec(value)


def _fmt(number):
    return None if number is None else format(number.normalize(), 'f')


def _truthy(value):
    return value is True or (isinstance(value, str) and value.strip().lower() in ('true', '是', 'yes'))


def _ev(label, value, tone='muted'):
    return {'label': label, 'value': value, 'tone': tone}


def _stage(key, label, state, basis, *evidence):
    return {'key': key, 'label': label, 'state': state, 'basis': basis, 'evidence': list(evidence)}


def _v3_matches(code, quotes, reports):
    found = {}
    for candidate, how in [(code, 'code')] + [(q['number'], 'quote_number') for q in quotes]:
        case = reports.case(candidate)
        if case and case['case_key'] not in found:
            found[case['case_key']] = {**case, 'match': how}
    return found


def v3_field_total(project, reports):
    """The register's cumulative 外業 points, only when exactly one v3 case matches the code or a quote number."""
    quotes = [{'number': text(q.get('quote_code')) or None} for q in project.get('quotes', [])]
    found = _v3_matches(text(project.get('code')) or None, quotes, reports)
    return reports.field_total(next(iter(found.values()))['case_code']) if len(found) == 1 else None


def _identity(state, project, reports):
    pid, code = project['id'], text(project.get('code')) or None
    rows = live_confirmation_fields(state, project)
    statuses = {text(f.get('狀態')) for f in rows if text(f.get('狀態'))}
    lines = live_contract_lines(state, project)
    imported = pid in (state.get('source_work_items_status') or {})
    fills = [i for i in state.get('source_work_items', []) if i.get('project_id') == pid and not i.get('source_missing')]
    quotes = [{'number': text(q.get('quote_code')) or None, 'engineering_code': text(q.get('engineering_code')) or None,
               'status': text((q.get('fields') or {}).get('狀態')) or text((q.get('fields') or {}).get('案件狀態')) or None}
              for q in project.get('quotes', [])]
    found = _v3_matches(code, quotes, reports)
    return {'code': code, 'is_c_prefix': is_c_code(code),
            'confirmation': {'present': bool(rows), 'line_count': len(lines),
                             'fill_item_count': len(fills) if imported else None,
                             'source_status': next(iter(statuses)) if len(statuses) == 1 else None},
            'quotes': quotes, 'v3_cases': list(found.values()), 'v3_ambiguous': len(found) > 1}, rows, statuses


def _daily(project, key):
    group = PRODUCTION[key][1]
    return [d for d in project.get('daily_reports', []) if d.get('department') == group and not d.get('source_missing')]


def actual_of(project, key, v3_field_total):
    rows = _daily(project, key)
    if rows:
        points = [Decimal(str(d['points'])) for d in rows
                  if isinstance(d.get('points'), (int, float)) and not isinstance(d['points'], bool) and math.isfinite(d['points'])]
        if points:
            return {'known': True, 'value': _fmt(sum(points)), 'source': 'v4_daily',
                    'unit_note': '營業額點數（日報回報，未經驗收；非合約數量）', 'reason': None}
        return {'known': False, 'value': None, 'unit_note': None, 'source': None, 'reason': '已有日報連結，但完成數量尚未投影'}
    if key == 'field' and v3_field_total:
        return {'known': True, 'value': _fmt(Decimal(str(v3_field_total))), 'source': 'v3_reports',
                'unit_note': '營業額點數（v3 週報登記冊案件累計外業，未經驗收）', 'reason': None}
    reason = NO_DAILY if not project.get('daily_reports') else '此案件的日報沒有歸屬到' + PRODUCTION[key][0]
    return {'known': False, 'value': None, 'unit_note': None, 'source': None, 'reason': reason}


def planned_of(summary, key):
    """The category's planned totals from the derived contract plan, or None while the plan is unavailable."""
    if summary is None:
        return None
    c = summary['categories'][PRODUCTION[key][0]]
    return {'lines': c['lines'], 'items': c['items'], 'qty': c['planned_qty'], 'needs_review': c['needs_review'],
            'basis': {'native': c['items_native'], 'derived': c['items_derived'], 'ambiguous': c['items_ambiguous'],
                      'unlinked': c['items_unlinked'] + c['items_native_unresolved']}}


def work_orders_of(project, key):
    orders = _daily(project, key)
    dates = sorted(d['date'] for d in orders if d.get('date'))
    return {'count': len(orders) or None, 'latest_date': dates[-1] if dates else None}


def _planned_items(state, project, summary, key):
    if summary is None:
        return None, [], 0, False
    category = PRODUCTION[key][0]
    lines = {c['id']: c for c in state.get('contract_items', []) if c.get('project_id') == project['id']}
    mine = [i for i in summary.get('items', []) if i.get('category') == category]
    items = []
    for item in mine[:MAX_ITEMS]:
        fields = (lines.get(item.get('line_id')) or {}).get('fields') or {}
        items.append({'item_id': item['id'], 'code': text(fields.get('工編號碼')) or None,
                      'name': text(fields.get(CATEGORY_FIELDS[category][1])) or None,
                      'planned_qty': _fmt(_dec(fields.get(CATEGORY_FIELDS[category][0]))),
                      'link_basis': BASIS_LABEL[item['basis']]})
    return planned_of(summary, key), items, len(mine), len(mine) > MAX_ITEMS


def _finance(project, amounts, rows):
    quotes, received, dates = [], [], []
    for q in project.get('quotes', []):
        f = q.get('fields') or {}
        total = {k: _dec(f.get(k)) for k in ('累計已請款', '可請款未請', '案件可請款總額', '累計已入帳')}
        flag = f.get('案件已入帳')
        quotes.append({'number': text(q.get('quote_code')) or None,
                       'case_received': True if amounts and _truthy(flag) else None,
                       'received_date': (day(f.get('入帳日期')) or None) if amounts else None,
                       **{name: _fmt(total[field]) if amounts else None for name, field in
                          (('invoiced_total', '累計已請款'), ('billable_unrequested', '可請款未請'),
                           ('billable_total', '案件可請款總額'), ('received_total', '累計已入帳'))}})
    received = amounts and (any(_truthy(f.get('案件已入帳')) for f in rows) or any(q['case_received'] for q in quotes))
    dates = sorted({d for d in [day(f.get('入帳日期')) for f in rows] + [q['received_date'] for q in quotes] if d}) if amounts else []
    return {'restricted': not amounts, 'quotes': quotes, 'case_received': True if received else None,
            'received_date': dates[-1] if dates else None}


def _invoiced_any(project):
    return any((_dec((q.get('fields') or {}).get('累計已請款')) or 0) > 0 for q in project.get('quotes', []))


def _stages(identity, production, finance, project, amounts):
    conf, code = identity['confirmation'], identity['code']
    has_lines = conf['present'] and conf['line_count'] > 0
    sales = (_stage('sales', '業務', 'done', 'rule', _ev('判斷', '工編以 C 開頭', 'ok'), _ev('工編', code or '—'))
             if proves_sales_by_code(project) else _stage('sales', '業務', 'done', 'rule', _ev('判斷', '已有確認單與合約明細', 'ok'))
             if has_lines else _stage('sales', '業務', 'unknown', 'none', _ev('工編', code or '—')))
    status = _ev('來源狀態', conf['source_status'] or '未填', 'muted')
    if has_lines:
        pm = _stage('pm', 'PM', 'done', 'rule', _ev('確認單明細', f"{conf['line_count']} 筆", 'ok'))
        confirmation = _stage('confirmation', '確認單', 'done', 'rule', _ev('確認單明細', f"{conf['line_count']} 筆", 'ok'), status)
    elif conf['present']:
        pm = _stage('pm', 'PM', 'active', 'rule', _ev('確認單', '尚無合約明細', 'warn'))
        confirmation = _stage('confirmation', '確認單', 'active', 'rule', _ev('確認單', '尚無合約明細', 'warn'), status)
    else:
        pm = _stage('pm', 'PM', 'waiting', 'rule', _ev('確認單', '尚未成立', 'warn'))
        confirmation = _stage('confirmation', '確認單', 'waiting', 'rule', _ev('確認單', '尚未成立', 'warn'))
    stages = [sales, pm, confirmation]
    for key, (label, _) in PRODUCTION.items():
        part = production[key]
        evidence = []
        if part['planned']:
            evidence.append(_ev('合約規劃', f"{part['planned']['lines']} 筆明細 / {part['planned']['qty']}", 'muted'))
        if part['actual']['known']:
            stages.append(_stage(key, label, 'active', 'source', *evidence, _ev('回報', f"{part['actual']['value']}（{part['actual']['unit_note']}）", 'ok')))
        elif not conf['present']:
            stages.append(_stage(key, label, 'waiting', 'rule', _ev('確認單', '尚未成立', 'warn')))
        else:
            stages.append(_stage(key, label, 'unknown', 'none', *evidence, _ev('完成量', part['actual']['reason'] or '未知', 'warn')))
    received = finance['case_received']
    if not amounts:
        gate = _ev('來源', '金額欄位僅限 PM／主管查看', 'muted')
        stages.append(_stage('billing', '計價', 'unknown', 'none', gate))
        stages.append(_stage('settlement', '結算', 'unknown', 'none', gate))
    elif received:
        when = _ev('入帳日期', finance['received_date'] or '未填', 'ok')
        stages.append(_stage('billing', '計價', 'done', 'source', _ev('來源', '案件已入帳', 'ok')))
        stages.append(_stage('settlement', '結算', 'done', 'source', _ev('來源', '案件已入帳', 'ok'), when))
    else:
        if _invoiced_any(project):
            stages.append(_stage('billing', '計價', 'active', 'source', _ev('來源', '已有累計已請款紀錄', 'ok')))
        else:
            stages.append(_stage('billing', '計價', 'unknown', 'none', _ev('來源', '無計價資料（空白不等於 0）', 'muted')))
        stages.append(_stage('settlement', '結算', 'unknown', 'none', _ev('來源', '來源未標示已入帳', 'muted')))
    return stages


def _gaps(identity, production, summary, statuses, reports, finance, project, amounts):
    gaps = []

    def add(ident, message, severity='warn'):
        gaps.append({'id': ident, 'severity': severity, 'message_zh': message})

    conf = identity['confirmation']
    if not conf['present']:
        add('no_confirmation', '尚無確認單，工程進度無從判斷')
    if len(statuses) > 1:
        add('confirmation_status_conflict', '確認單來源狀態不一致，未擇一顯示')
    if conf['present'] and conf['fill_item_count'] is None:
        add('fill_items_unknown', '填報工項尚未匯入，筆數未知')
    if summary is None:
        add('plan_unavailable', '合約規劃尚未推導（來源表未完整讀取或此案無明細）')
    elif summary.get('truncated'):
        add('plan_truncated', '合約規劃項目過多，清單已截斷')
    if summary is not None:
        cats = summary['categories'].values()
        unlinked = sum(c['items_unlinked'] + c['items_native_unresolved'] for c in cats)
        ambiguous = sum(c['items_ambiguous'] for c in cats)
        if unlinked:
            add('items_unlinked', f'{unlinked} 個填報工項尚未連結到合約明細')
        if ambiguous:
            add('items_ambiguous', f'{ambiguous} 個填報工項對應到多筆合約明細，需人工確認')
    numbers = [q['number'] for q in identity['quotes'] if q['number']]
    if len(numbers) != len(set(numbers)):
        add('quotes_duplicated', '同一報價編號有多筆報價紀錄，金額不可相加')
    if not project.get('daily_reports'):
        add('no_daily_linked', NO_DAILY + '，實際完成量未知（不代表尚未施工）')
    if identity['v3_ambiguous']:
        add('v3_ambiguous', '工編與報價編號對應到多個 v3 案件，未合併；請逐一確認')
    elif not identity['v3_cases'] and reports.status == 'ok':
        add('v3_none', '週報資料中找不到對應的 v3 案件', 'info')
    elif identity['v3_cases'] and not production['report_rows']:
        add('v3_no_activity', '對應的 v3 案件尚無外業／內業預排或工作單', 'info')
    if reports.status != 'ok':
        add('reports_' + reports.status, {'cold': '週報快照尚在首次讀取，v3 資料暫缺', 'unavailable': '週報快照暫時無法讀取，v3 資料暫缺',
                                         'restricted': '週報與金額僅限 PM／主管查看', 'disabled': '週報未啟用，v3 資料暫缺'}[reports.status])
    elif reports.stale:
        add('reports_stale', '週報快照已過期，等待重新讀取', 'info')
    if not amounts:
        add('finance_restricted', '金額欄位僅限 PM／主管查看')
    elif not any(any(v for k, v in q.items() if k.endswith('_total') or k == 'billable_unrequested') for q in finance['quotes']):
        add('finance_empty', '來源尚無請款資料（空白不等於 0）', 'info')
    return gaps


def build_project_progress(state, project_id, *, reports=None, amounts=False, as_of=None) -> ProjectProgress | None:
    project = next((p for p in state.get('projects', []) if p.get('id') == project_id), None)
    if project is None:
        return None
    reports = reports or ReportsView(status='restricted')
    identity, conf_rows, statuses = _identity(state, project, reports)
    summary = plan_summary(state, project_id)
    v3_rows, rows_truncated = [], False
    for case in identity['v3_cases']:  # every candidate is listed with its own case_key; rows are never merged
        found, cut = reports.rows(case['case_code'])
        v3_rows += found
        rows_truncated = rows_truncated or cut
    field_total = v3_field_total(project, reports)
    production = {}
    for key in PRODUCTION:
        planned, items, total, truncated = _planned_items(state, project, summary, key)
        production[key] = {'planned': planned, 'items': items, 'items_total': total, 'items_truncated': truncated,
                           'actual': actual_of(project, key, field_total), 'work_orders': work_orders_of(project, key)}
    production.update(report_rows=v3_rows, report_rows_truncated=rows_truncated)
    finance = _finance(project, amounts, conf_rows)
    status = state.get('source_status') or {}
    return {'schema_version': SCHEMA_VERSION, 'project_id': project_id, 'as_of': as_of or state.get('as_of'),
            'sources': {'source_synced_at': status.get('last_sync'), 'source_status': status.get('status'),
                        'reports_status': reports.status, 'reports_fetched_at': reports.fetched_at, 'reports_stale': reports.stale},
            'identity': identity, 'stages': _stages(identity, production, finance, project, amounts), 'production': production,
            'finance': finance, 'gaps': _gaps(identity, production, summary, statuses, reports, finance, project, amounts)}
