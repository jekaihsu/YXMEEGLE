"""What a case's 報價總表 rows say, merged across every row that carries one of its 報價編號.

Pure and read-only. The register holds duplicated 報價編號 rows whose evidence is split between them, so the
facts are a union over the group and never one row. Rows deleted at the source are never evidence.
"""
import re
from dataclasses import dataclass, replace
from datetime import date

from ..sources import QUOTE_POINT_FIELDS, day, link_ids, normalized_case, number, source_id, text

LABELS = '0ABCDEFGHIJ'
# 狀態 (1) letters ordered by how far a case got; I (cancelled) only wins when every row says I.
LIVE_ORDER = '0ABCDEFGHJ'
WON_LABELS = frozenset('ABCDEFGH')
WON_STATUS = frozenset({'成案', '舊案'})
ENGINEERING_NO = re.compile(r'([CABKX])(\d+)')
DATE_FIELDS = {'inquiry_date': '詢價日期', 'first_contact_date': '第一次聯繫日期', 'quoted_date': '報價日期',
               'pm_handoff_date': '提供給PM日期', 'quote_deadline': '報價期限', 'returned_date': '回傳單日期',
               'confirmation_meeting_date': '確認單回傳開會日期', 'admin_return_date': '提供行政回傳確認單時間',
               'post_win_contact_date': '成案後聯繫日期', 'contract_end_date': '合約結束日期',
               'billable_date': 'PM告知可請款日期', 'received_date': '入帳日期'}
TEXT_FIELDS = {'project_name': '工程名稱', 'client': '行號單位', 'contact': '連絡人', 'meegle_daily': 'MEEGLE日報填報情形'}


@dataclass(frozen=True)
class QuoteFacts:
    quote_nos: tuple[str, ...] = ()
    source_rows: int = 0
    project_name: str = ''
    client: str = ''
    contact: str = ''
    inquiry_date: str = ''
    first_contact_date: str = ''
    quoted_date: str = ''
    pm_handoff_date: str = ''
    quote_deadline: str = ''
    deadline_passed: bool = False
    returned_date: str = ''
    engineering_no: str = ''
    numbered: bool = False
    numbers_consistent: bool = True
    quote_status: str = ''
    stage_label: str = ''
    confirmation_link: bool = False
    confirmation_meeting_date: str = ''
    admin_return_date: str = ''
    v4_confirmation: bool = False
    post_win_contact_date: str = ''
    contract_end_date: str = ''
    price_positive: bool = False
    field_points: bool = False
    office_points: bool = False
    admin_points: bool = False
    field_team: str = ''
    field_deadline: str = ''
    meegle_daily: str = ''
    billable_date: str = ''
    received: bool = False
    received_date: str = ''

    @property
    def won(self):
        return bool(self.returned_date or self.numbered and self.quote_status in WON_STATUS
                    or self.stage_label in WON_LABELS)

    @property
    def quoted(self):
        return bool(self.quoted_date or self.pm_handoff_date)

    @property
    def confirmation_evidence(self):
        # A 此案確認單 link alone is usually a costing sheet made at quote time; it counts only once the quote returned.
        return bool(self.confirmation_meeting_date or self.admin_return_date
                    or self.confirmation_link and self.returned_date)

    def plain(self, keys):
        return {key: getattr(self, key) for key in keys}


def has_confirmation_link(value):
    return bool(link_ids(value)) or isinstance(value, list) and any(
        isinstance(item, dict) and isinstance(item.get('id'), str) and item['id'].startswith('rec') for item in value)


def engineering_no(code):
    found = ENGINEERING_NO.match(code.upper())
    return bool(found) and int(found.group(2)) != 0


def truthy(value):
    return value is True or text(value).strip().lower() == 'true'


def present_number(value):
    amount = number(value)
    return amount is not None and amount != 0


def row_facts(f):
    codes = [normalized_case(f.get(k)) for k in ('工程編號', '編號')]
    label = text(f.get('狀態 (1)')).strip()[:1].upper()
    team = text(f.get('外業負責組別')).strip()
    deadline = text(f.get('外業期限')).strip()
    return {**{key: day(f.get(name)) for key, name in DATE_FIELDS.items()},
            **{key: text(f.get(name)).strip() for key, name in TEXT_FIELDS.items()},
            'quote_no': normalized_case(f.get('報價編號')),
            'codes': [c for c in codes if c],
            'numbers_consistent': not codes[1] or codes[1] == codes[0],
            'quote_status': text(f.get('狀態')).strip(),
            'stage_label': label if label and label in LABELS else '',
            'confirmation_link': has_confirmation_link(f.get('此案確認單')),
            'price_positive': any((number(f.get(k)) or 0) > 0 for k in ('契約價格(未稅)', '契約價格(含稅)')),
            'field_points': present_number(f.get(QUOTE_POINT_FIELDS[0])),
            'office_points': any(present_number(f.get(k)) for k in QUOTE_POINT_FIELDS[1:4]),
            'admin_points': present_number(f.get(QUOTE_POINT_FIELDS[4])),
            'field_team': '' if team == '無' else team,
            'field_deadline': '' if deadline == '-' else deadline,
            'received': truthy(f.get('案件已入帳'))}


def merged_label(labels):
    live = [x for x in labels if x and x != 'I']
    if live:
        return max(live, key=LIVE_ORDER.index)
    return 'I' if 'I' in labels else ''


def collect(rows, *, today: date, v4_confirmation=False) -> QuoteFacts:
    """Union of the given 報價總表 field dicts, in a stable order."""
    found = [row_facts(f) for f in rows]
    first = lambda key: next((r[key] for r in found if r[key]), '')
    codes = [c for r in found for c in r['codes']]
    numbered = next((c for c in codes if engineering_no(c)), '')
    statuses = {r['quote_status'] for r in found}
    facts = QuoteFacts(
        quote_nos=tuple(sorted({r['quote_no'] for r in found if r['quote_no']})), source_rows=len(found),
        **{key: max((r[key] for r in found), default='') for key in DATE_FIELDS},
        **{key: first(key) for key in TEXT_FIELDS},
        engineering_no=numbered or (codes[0] if codes else ''), numbered=bool(numbered),
        numbers_consistent=all(r['numbers_consistent'] for r in found),
        quote_status=next((s for s in ('成案', '舊案') if s in statuses), ''),
        stage_label=merged_label([r['stage_label'] for r in found]),
        **{key: any(r[key] for r in found) for key in ('confirmation_link', 'price_positive', 'field_points',
                                                         'office_points', 'admin_points', 'received')},
        field_team=first('field_team'), field_deadline=first('field_deadline'),
        v4_confirmation=v4_confirmation)
    return replace(facts, deadline_passed=bool(facts.quote_deadline) and facts.quote_deadline < today.isoformat())


def live(row):
    return isinstance(row, dict) and not row.get('source_missing')


def case_rows(project, state):
    """Field dicts of the case's quote rows plus every other source row carrying one of its 報價編號."""
    rows = {}
    for row in list(project.get('quotes') or []) + [r for r in project.get('source_records') or []
                                                     if isinstance(r, dict) and r.get('kind') == 'quote']:
        if live(row) and row.get('id') not in rows:
            rows[row.get('id')] = row.get('fields') or {}
    numbers = {normalized_case(f.get('報價編號')) for f in rows.values()} - {''}
    for entity in (state or {}).get('source_quotes') or []:
        identity = entity.get('source_identity') or {}
        if not live(entity) or normalized_case((entity.get('fields') or {}).get('報價編號')) not in numbers:
            continue
        key = source_id(identity) if all(identity.get(k) for k in ('base_token', 'table_id', 'record_id')) else entity.get('id')
        rows.setdefault(key, entity.get('fields') or {})
    return [rows[key] for key in sorted(rows, key=str)]


def case_facts(project, state, today: date) -> QuoteFacts:
    records = [r for r in project.get('source_records') or [] if live(r)]
    facts = collect(case_rows(project, state), today=today,
                    v4_confirmation=any(r.get('kind') == 'confirmation' for r in records))
    if any(r.get('kind') == 'quote_confirmation' for r in records):
        facts = replace(facts, confirmation_link=True)
    return facts

