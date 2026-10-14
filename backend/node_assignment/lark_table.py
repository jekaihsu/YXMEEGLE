"""Lark Bitable boundary for 節點指派, 任務 and the V4 roster.

The client can only address the configured tables. Writes additionally pass the
code-level formal write allowlist, run once (never retried on an uncertain
outcome) and re-check the caller's authority right before each request.
"""
import hashlib
import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum, StrEnum

import httpx

from ..avatar import avatar_url
from ..lark_adapter import RemoteFailure
from ..live_read.config import LiveReadConfig
from ..live_read.rate_limit import RETRY_CODES, BudgetExceeded, RetryPolicy, process_bucket
from ..live_read.token_cache import TokenError, process_token_cache
from ..remote_policy import require_formal_write
from ..sources import API, link_ids, text
from .config import NodeAssignmentConfig
from .domain import CHAIN, NODE_LABELS, NodeKey, TaskStatus
from .errors import Failure

logger = logging.getLogger(__name__)
TAIPEI = timezone(timedelta(hours=8))
INVALID_TOKEN = frozenset({99991663, 99991677})
PERMISSION_CODES = frozenset({99991672, 1254302, 91403})
SCOPE = re.compile(r'[a-z][a-z0-9_.]*(?::[a-z][a-z0-9_.]*)+')
MAX_TASKS = 500


class Table(Enum):
    NODES = 'node_table'
    TASKS = 'task_table'
    PEOPLE = 'people_table'


class Kind(StrEnum):
    TEXT = 'text'
    NUMBER = 'number'
    SELECT = 'select'
    MULTI = 'multi_select'
    DATE = 'date'
    CHECKBOX = 'checkbox'
    USERS = 'users'
    LINK = 'link'
    CREATED = 'created_time'


LARK_TYPES = {Kind.TEXT: {1}, Kind.NUMBER: {2}, Kind.SELECT: {3}, Kind.MULTI: {4}, Kind.DATE: {5},
              Kind.CHECKBOX: {7}, Kind.USERS: {11}, Kind.LINK: {18, 21}, Kind.CREATED: {1001}}

NODE_FIELDS = {
    'assignment_key': ('指派鍵', Kind.TEXT), 'code': ('確認單編號', Kind.TEXT), 'node': ('節點', Kind.SELECT),
    'owners': ('負責人', Kind.USERS), 'method': ('指派方式', Kind.SELECT), 'assigned_by': ('指派人', Kind.USERS),
    'status': ('狀態', Kind.SELECT), 'progress': ('進度', Kind.NUMBER), 'started_at': ('開始時間', Kind.DATE),
    'finished_at': ('完成時間', Kind.DATE), 'approver': ('核准人', Kind.USERS), 'approved_at': ('核准時間', Kind.DATE),
    'reject_reason': ('退回原因', Kind.TEXT), 'confirmation': ('工程確認單', Kind.LINK), 'tasks': ('任務', Kind.LINK),
}
TASK_FIELDS = {
    'title': ('標題', Kind.TEXT), 'node': ('節點指派', Kind.LINK), 'detail': ('內容', Kind.TEXT),
    'assignee': ('負責人', Kind.USERS), 'assigned_by': ('指派人', Kind.USERS), 'department': ('部門', Kind.SELECT),
    'deadline': ('截止日', Kind.DATE), 'status': ('狀態', Kind.SELECT), 'done_at': ('完成時間', Kind.DATE),
    'created_at': ('建立時間', Kind.CREATED),
}
PEOPLE_FIELDS = {
    'name': ('姓名', Kind.TEXT), 'departments': ('所屬組別', Kind.MULTI), 'rank': ('職級', Kind.SELECT),
    'employed': ('在職', Kind.CHECKBOX), 'account': ('Lark帳號', Kind.USERS),
}
SCHEMAS = {Table.NODES: NODE_FIELDS, Table.TASKS: TASK_FIELDS, Table.PEOPLE: PEOPLE_FIELDS}


def canon(kind, raw):
    """One comparable form for both read values and wire values."""
    if kind in (Kind.TEXT, Kind.SELECT):
        return text(raw).strip()
    if kind is Kind.NUMBER:
        try:
            return None if raw is None else round(float(raw), 4)
        except (TypeError, ValueError):
            return None
    if kind in (Kind.DATE, Kind.CREATED):
        # Lark keeps the timestamp; minute precision tolerates display rounding.
        return raw // 60000 if type(raw) is int else None
    if kind is Kind.USERS:
        return tuple(sorted(user.open_id for user in users(raw)))
    if kind is Kind.LINK:
        return tuple(sorted(link_ids(raw)))
    if kind is Kind.MULTI:
        return tuple(sorted({text(v).strip() for v in raw or [] if text(v).strip()}))
    if kind is Kind.CHECKBOX:
        return raw is True
    raise ValueError(kind)


@dataclass(frozen=True)
class UserRef:
    open_id: str
    name: str
    avatar_url: str | None = None

    def public(self):
        result = {'open_id': self.open_id, 'name': self.name}
        if self.avatar_url:
            result['avatar_url'] = self.avatar_url
        return result


def users(raw):
    items = raw if isinstance(raw, list) else [raw] if isinstance(raw, dict) else []
    found = []
    for item in items:
        if isinstance(item, dict):
            ident = item.get('id') or item.get('open_id')
            if isinstance(ident, str) and re.fullmatch(r'ou_[A-Za-z0-9]+', ident):
                found.append(UserRef(ident, str(item.get('name') or '').strip(), avatar_url(item.get('avatar_url'))))
    return tuple(found)


def millis(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def date_millis(iso: str) -> int:
    return millis(datetime.combine(date.fromisoformat(iso), datetime.min.time(), TAIPEI))


def iso_date(ms):
    return datetime.fromtimestamp(ms / 1000, TAIPEI).date().isoformat() if type(ms) is int else None


def iso_time(ms):
    return datetime.fromtimestamp(ms / 1000, TAIPEI).isoformat(timespec='seconds') if type(ms) is int else None


def _fingerprint(values):
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


@dataclass(frozen=True)
class NodeRow:
    record_id: str
    assignment_key: str
    owners: tuple[UserRef, ...]
    method: str
    assigned_by: UserRef | None
    status: str
    started_at: int | None
    finished_at: int | None
    approver: UserRef | None
    approved_at: int | None
    reject_reason: str
    task_ids: tuple[str, ...]
    revision: str

    @property
    def approved(self):
        return self.status == '已完成' and self.approver is not None and self.approved_at is not None

    @property
    def rejected(self):
        return bool(self.reject_reason) and not self.approved


@dataclass(frozen=True)
class TaskRow:
    record_id: str
    title: str
    detail: str
    assignee: UserRef | None
    assigned_by: UserRef | None
    department: str
    deadline: str | None
    status: TaskStatus
    done_at: int | None
    created_at: int | None
    node_ids: tuple[str, ...]
    revision: str


def _record(record):
    rid, values = record.get('record_id'), record.get('fields')
    if not isinstance(rid, str) or not rid or not isinstance(values, dict):
        raise Failure('lark_error', 'Lark 紀錄缺少識別碼或欄位；不顯示部分資料')
    return rid, values


def _business(spec, values, skip=()):
    return {key: canon(kind, values.get(name)) for key, (name, kind) in spec.items() if key not in skip}


def parse_node(record) -> NodeRow:
    rid, values = _record(record)
    get = lambda key: values.get(NODE_FIELDS[key][0])
    first = lambda key: next(iter(users(get(key))), None)
    stamp = lambda key: get(key) if type(get(key)) is int else None
    # The reverse task link changes whenever a task is added; it is not node content.
    revision = _fingerprint(_business(NODE_FIELDS, values, skip=('tasks',)))
    return NodeRow(rid, text(get('assignment_key')).strip(), users(get('owners')), text(get('method')).strip(),
                   first('assigned_by'), text(get('status')).strip(), stamp('started_at'), stamp('finished_at'),
                   first('approver'), stamp('approved_at'), text(get('reject_reason')).strip(),
                   tuple(link_ids(get('tasks'))), revision)


def parse_task(record) -> TaskRow:
    rid, values = _record(record)
    get = lambda key: values.get(TASK_FIELDS[key][0])
    try:
        status = TaskStatus(text(get('status')).strip())
    except ValueError:
        status = TaskStatus.TODO
    stamp = lambda key: get(key) if type(get(key)) is int else None
    return TaskRow(rid, text(get('title')).strip(), text(get('detail')), next(iter(users(get('assignee'))), None),
                   next(iter(users(get('assigned_by'))), None), text(get('department')).strip(),
                   iso_date(stamp('deadline')), status, stamp('done_at'), stamp('created_at'),
                   tuple(link_ids(get('node'))), _fingerprint(_business(TASK_FIELDS, values, skip=('created_at',))))


def wire(spec, changes):
    """Semantic changes to Lark field values; None clears a cell."""
    out = {}
    for key, value in changes.items():
        name, kind = spec[key]
        if value is None:
            out[name] = None
        elif kind is Kind.USERS:
            out[name] = [{'id': ident} for ident in value]
        elif kind is Kind.LINK:
            out[name] = list(value)
        else:
            out[name] = value
    return out


def mismatches(spec, written, record):
    """Field names whose read-back value differs from what was written."""
    _, values = _record(record)
    lookup = {name: kind for name, kind in spec.values()}
    return sorted(name for name, value in written.items() if canon(lookup[name], values.get(name)) != canon(lookup[name], value))


def assignment_key(code, key: NodeKey):
    return f'{code}|{NODE_LABELS[key]}'


class BitableClient:
    def __init__(self, cfg, config: NodeAssignmentConfig, transport=None, *, before_write: Callable[[], None] | None = None,
                 token_cache=None, bucket=None, clock=time.monotonic, sleep=time.sleep, budget_seconds=25):
        self.cfg, self.config = cfg, config
        self.http = httpx.Client(transport=transport, follow_redirects=False)
        self.before_write = before_write or (lambda: None)
        self.token_cache = token_cache or process_token_cache
        self.bucket = bucket or process_bucket(LiveReadConfig.from_env(cfg).max_rps)
        self.clock, self.sleep = clock, sleep
        self.deadline = clock() + budget_seconds
        self.deny = transport is None and cfg.get('LARK_LIVE_READ_TRANSPORT') == 'deny'
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.http.close()

    def _root(self, table: Table):
        return f'/bitable/v1/apps/{self.config.base}/tables/{getattr(self.config, table.value)}'

    def fields(self, table: Table):
        return self._pages('GET', self._root(table) + '/fields', params={})

    def search(self, table: Table, conditions, conjunction='or'):
        body = {'filter': {'conjunction': conjunction, 'conditions': conditions}, 'automatic_fields': False}
        return self._pages('POST', self._root(table) + '/records/search', params={'user_id_type': 'open_id'}, json=body)

    def list_records(self, table: Table, field_names):
        return self._pages('GET', self._root(table) + '/records', params={
            'user_id_type': 'open_id', 'field_names': json.dumps(field_names, ensure_ascii=False)})

    def get(self, table: Table, record_id):
        record = self._call('GET', f'{self._root(table)}/records/{record_id}', params={'user_id_type': 'open_id'}).get('record')
        if not isinstance(record, dict) or record.get('record_id') != record_id:
            raise Failure('lark_error', 'Lark 讀回的紀錄識別不符')
        return record

    def batch_get(self, table: Table, record_ids):
        found = []
        for start in range(0, len(record_ids), 100):
            chunk = record_ids[start:start + 100]
            try:
                data = self._call('POST', self._root(table) + '/records/batch_get',
                                  json={'record_ids': chunk, 'user_id_type': 'open_id'})
            except Failure as exc:
                if exc.extra.get('upstream_status') != 404:
                    raise
                found.extend(self.get(table, rid) for rid in chunk)
                continue
            records = data.get('records')
            if data.get('forbidden_record_ids'):
                raise Failure('lark_permission', 'Lark 應用無權讀取部分任務紀錄', missing_scopes=['bitable:app:readonly'])
            if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
                raise Failure('lark_error', 'Lark 任務批次讀取回應不完整；不顯示部分資料')
            found.extend(records)
        return found

    def create(self, table: Table, fields, client_token):
        self._writable(table)
        data = self._call('POST', self._root(table) + '/records', write=True,
                          params={'user_id_type': 'open_id', 'client_token': client_token}, json={'fields': fields})
        rid = (data.get('record') or {}).get('record_id')
        if not isinstance(rid, str) or not rid:
            raise Failure('outcome_unknown', 'Lark 建立紀錄缺少回執；請以同一 request_id 重送以核對結果')
        return rid

    def update(self, table: Table, record_id, fields):
        self._writable(table)
        self._call('PUT', f'{self._root(table)}/records/{record_id}', write=True,
                   params={'user_id_type': 'open_id'}, json={'fields': fields})

    def _writable(self, table):
        try:
            require_formal_write(self.config.base, getattr(self.config, table.value))
        except RemoteFailure as exc:
            raise Failure('writes_disabled', str(exc)) from None

    def _pages(self, method, path, *, params, json=None, limit=50):
        items, seen_cursors, seen_ids, cursor = [], set(), set(), None
        for _ in range(limit):
            query = dict(params, page_size=500 if path.endswith('/records') or path.endswith('/search') else 100)
            if cursor:
                query['page_token'] = cursor
            data = self._call(method, path, params=query, json=json)
            page, has_more = data.get('items'), data.get('has_more')
            # Lark omits items for an empty result; accept only that exact first-page shape.
            if page is None and cursor is None and has_more is False and data.get('total') == 0 and not data.get('page_token'):
                page = []
            if type(has_more) is not bool or not isinstance(page, list) or any(not isinstance(i, dict) for i in page):
                raise Failure('lark_error', 'Lark 分頁回應不完整；不顯示部分資料')
            ids = [i.get('record_id') or i.get('field_id') for i in page]
            if len(set(ids)) != len(ids) or seen_ids.intersection(ids):
                raise Failure('lark_error', 'Lark 分頁包含重複紀錄；不顯示部分資料')
            seen_ids.update(ids)
            items.extend(page)
            if not has_more:
                return items
            cursor = data.get('page_token')
            if not isinstance(cursor, str) or not cursor or cursor in seen_cursors:
                raise Failure('lark_error', 'Lark 分頁游標缺漏或重複；不顯示部分資料')
            seen_cursors.add(cursor)
        raise Failure('lark_error', 'Lark 分頁超過上限；不顯示部分資料')

    def _token(self):
        def mint(credentials):
            response = self.http.post(API + '/auth/v3/tenant_access_token/internal', json=credentials, timeout=15)
            return response.json()
        try:
            return self.token_cache.get(self.cfg, mint, deadline=self.deadline)
        except (TokenError, BudgetExceeded, httpx.HTTPError, ValueError):
            raise Failure('lark_unavailable', 'Lark 應用授權暫時無法取得') from None

    def _call(self, method, path, *, write=False, params=None, json=None):
        if self.deny:
            raise Failure('lark_unavailable', 'Lark 連線已停用')
        if self.cfg.get('LARK_WORKER_IDENTITY') != 'application':
            raise Failure('lark_unconfigured', '節點指派需使用公司應用身分連線')
        renewed, attempt = False, 0
        while True:
            attempt += 1
            token = self._token()
            try:
                self.bucket.acquire(self.deadline)
            except BudgetExceeded:
                raise Failure('lark_unavailable', 'Lark 請求額度暫時用盡，請稍後再試') from None
            if write:
                self.before_write()
            self.calls += 1
            try:
                response = self.http.request(method, API + path, params=params, json=json, timeout=15,
                                             headers={'Authorization': 'Bearer ' + token})
            except httpx.HTTPError:
                if write:
                    raise Failure('outcome_unknown', 'Lark 寫入結果未知；請以同一 request_id 重送以核對結果') from None
                if self._backoff(None, attempt):
                    continue
                raise Failure('lark_unavailable', 'Lark 暫時無法連線') from None
            try:
                body = response.json()
            except ValueError:
                body = None
            code = body.get('code') if isinstance(body, dict) and type(body.get('code')) is int else None
            if code in INVALID_TOKEN and not renewed:
                self.token_cache.invalidate(self.cfg, token=token)
                renewed = True
                continue
            if code in PERMISSION_CODES or (response.status_code in (401, 403) and code not in INVALID_TOKEN):
                raise self._permission(body, code, method, path, write)
            if response.status_code == 429 or code in RETRY_CODES:
                if not write and self._backoff(response, attempt):
                    continue
                raise Failure('lark_unavailable', 'Lark 限流，請稍後再試', lark_code=code)
            if response.status_code >= 500 or body is None:
                if write:
                    raise Failure('outcome_unknown', 'Lark 寫入結果未知；請以同一 request_id 重送以核對結果')
                if self._backoff(response, attempt):
                    continue
                raise Failure('lark_unavailable', 'Lark 服務暫時不可用', upstream_status=response.status_code)
            if response.status_code >= 400 or code != 0:
                raise Failure('lark_error', f'Lark 拒絕請求（{code}）', lark_code=code, upstream_status=response.status_code)
            data = body.get('data')
            if not isinstance(data, dict):
                raise Failure('outcome_unknown' if write else 'lark_error', 'Lark 回應缺少內容')
            return data

    def _backoff(self, response, attempt):
        if attempt >= RetryPolicy.max_attempts:
            return False
        delay = RetryPolicy.after(response, attempt) if response is not None else 2 ** (attempt - 1)
        if self.clock() + delay >= self.deadline:
            return False
        self.sleep(delay)
        return True

    def _permission(self, body, code, method, path, write):
        body = body if isinstance(body, dict) else {}
        error = body.get('error') if isinstance(body.get('error'), dict) else {}
        found = [v.get('subject', '') for v in error.get('permission_violations') or [] if isinstance(v, dict)]
        found += SCOPE.findall(str(body.get('msg', '')))
        scopes = sorted({s for s in found if isinstance(s, str) and SCOPE.fullmatch(s)}) or (
            ['bitable:app'] if write else ['bitable:app:readonly'])
        logger.warning('node_assignment lark permission denied code=%s method=%s path=%s missing=%s',
                       code, method, path, ','.join(scopes))
        return Failure('lark_permission', 'Lark 應用缺少多維表格權限或未獲此 Base 授權，請管理員於 Lark 後台補齊',
                       lark_code=code, missing_scopes=scopes)


@dataclass(frozen=True)
class CaseSnapshot:
    code: str
    rows: dict[NodeKey, tuple[NodeRow, ...]]
    tasks: dict[str, tuple[TaskRow, ...]]
    warnings: tuple[str, ...] = ()

    def row(self, key: NodeKey) -> NodeRow | None:
        rows = self.rows.get(key, ())
        if len(rows) > 1:
            raise Failure('duplicate_assignment_key', f'「{assignment_key(self.code, key)}」在 Lark 有重複列，請管理員先合併',
                          record_ids=[r.record_id for r in rows])
        return rows[0] if rows else None

    def node_tasks(self, key: NodeKey) -> tuple[TaskRow, ...]:
        rows = self.rows.get(key, ())
        return self.tasks.get(rows[0].record_id, ()) if len(rows) == 1 else ()


def read_case(client: BitableClient, code: str) -> CaseSnapshot:
    keys = {assignment_key(code, key): key for key in CHAIN}
    found = client.search(Table.NODES, [{'field_name': NODE_FIELDS['assignment_key'][0], 'operator': 'is', 'value': [k]}
                                        for k in keys])
    rows = {}
    for record in found:
        row = parse_node(record)
        if row.assignment_key not in keys:
            raise Failure('lark_error', 'Lark 搜尋結果不符篩選條件；不顯示部分資料')
        rows.setdefault(keys[row.assignment_key], []).append(row)
    singles = [group[0] for group in rows.values() if len(group) == 1]
    wanted = list(dict.fromkeys(tid for row in singles for tid in row.task_ids))
    if len(wanted) > MAX_TASKS:
        raise Failure('lark_error', f'本案任務超過 {MAX_TASKS} 筆，無法完整顯示')
    tasks = {t.record_id: t for t in map(parse_task, client.batch_get(Table.TASKS, wanted))} if wanted else {}
    warnings = []
    by_node = {}
    for row in singles:
        linked = tuple(tasks[t] for t in row.task_ids if t in tasks and row.record_id in tasks[t].node_ids)
        if len(linked) != len(row.task_ids):
            warnings.append('task_link_mismatch')
        by_node[row.record_id] = linked
    return CaseSnapshot(code, {k: tuple(v) for k, v in rows.items()}, by_node, tuple(dict.fromkeys(warnings)))


def check_schema(client: BitableClient, table: Table):
    present = {}
    for field in client.fields(table):
        present.setdefault(field.get('field_name'), []).append(field.get('type'))
    broken = [name for name, kind in SCHEMAS[table].values()
              if len(present.get(name, [])) != 1 or present[name][0] not in LARK_TYPES[kind]]
    if broken:
        raise Failure('lark_error', 'Lark 欄位已改名、重複或型別不符：' + '、'.join(broken), fields=broken)
