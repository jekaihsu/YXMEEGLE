"""Bounded, strict JSON validation before workflow mutations."""
import ipaddress
import json
import math
import unicodedata
from urllib.parse import urlsplit
from fastapi import HTTPException

MAX_ACTION_BYTES = 256 * 1024
TEXT_LIMIT = 10000
TEXT_FIELDS = {'title', 'name', 'body', 'description', 'reason', 'output', 'note',
               'qualification_note', 'source_url', 'reference_url', 'url',
               'department', 'role', 'direction', 'result', 'seat', 'scope',
               'classification', 'start_date', 'due_date', 'day', 'end_time',
               'date', 'unit', 'currency', 'tax_basis', 'phase', 'kind', 'type'}
SHORT_FIELDS = {'title', 'name', 'department', 'role', 'direction', 'result',
                'seat', 'classification', 'start_date', 'due_date', 'day', 'end_time'}
ID_LISTS = {'mentions', 'reviewers', 'issuer_ids', 'task_ids', 'evidence_ids',
            'delivery_batch_ids', 'work_item_ids', 'collaborator_ids', 'capabilities'}
OBJECT_LISTS = {'nodes', 'dates', 'items'}
BOOL_FIELDS = {'active', 'required', 'qualified', 'not_applicable', 'finished',
               'new_batch', 'all_payables_declared', 'connector_managed'}


def invalid(message='欄位型別或內容格式錯誤', code=422):
    raise HTTPException(code, message)


async def json_object(request, code=422):
    """Parse a request body that must be a JSON object; reject malformed, array, null and scalar bodies."""
    try:
        body = await request.json()
    except (ValueError, UnicodeDecodeError):
        invalid('請求內容必須是有效的 JSON', code)
    if not isinstance(body, dict):
        invalid('請求內容必須是 JSON 物件', code)
    return body


def text(value, field, limit=TEXT_LIMIT, nullable=False):
    if value is None and nullable:
        return value
    if not isinstance(value, str):
        invalid(f'{field} 必須是文字')
    if len(value) > limit:
        invalid(f'{field} 不得超過 {limit} 字')
    if any(unicodedata.category(c) == 'Cc' and c not in '\n\r\t' for c in value):
        invalid(f'{field} 含不允許的控制字元')
    return value


def safe_reference_url(value, *, optional=False):
    text(value, '連結', 2048)
    if optional and not value:
        return value
    if any(c.isspace() or unicodedata.category(c) in ('Cc', 'Cf') for c in value) or '\\' in value:
        invalid('連結包含不允許的字元')
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or '').lower().rstrip('.')
        if parsed.scheme != 'https' or not host or parsed.username is not None or parsed.password is not None:
            invalid('連結需為公開 HTTPS 網址，不可含帳號')
        if parsed.port not in (None, 443):
            invalid('連結僅支援 HTTPS 標準連接埠')
        if '.' not in host or host in ('localhost', 'localhost.localdomain') or host.endswith(('.localhost', '.local', '.internal', '.lan')):
            invalid('不接受內網連結')
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            invalid('不接受內網位址')
        # Reject alternate numeric IP spellings such as 2130706433 or 0177.0.0.1.
        if address is None and (all(c.isdigit() or c == '.' for c in host) or host.startswith('0x')):
            invalid('不接受不明確的 IP 位址')
    except (ValueError, TypeError):
        invalid('連結格式錯誤')
    return value


def _bounded(value, depth=0):
    if depth > 12:
        invalid('資料層級過深')
    if isinstance(value, dict):
        if len(value) > 200:
            invalid('欄位數量超過上限')
        for key, item in value.items():
            text(key, '欄位名稱', 160)
            _bounded(item, depth + 1)
    elif isinstance(value, list):
        if len(value) > 500:
            invalid('清單超過 500 項')
        for item in value:
            _bounded(item, depth + 1)
    elif isinstance(value, str):
        text(value, '文字', TEXT_LIMIT)
    elif isinstance(value, float) and not math.isfinite(value):
        invalid('數字必須為有限值')
    elif value is not None and type(value) not in (int, float, bool):
        invalid()


def _payload_fields(payload):
    for key, value in payload.items():
        if key.startswith('_') or key in ('oauth_identity', 'company_admin_authorization', 'business_authority'):
            invalid('不可由操作內容設定登入或授權資料')
        if key == 'template_id' and type(value) is int:
            if value <= 0:
                invalid('來源範本編號必須為正整數')
        elif key in TEXT_FIELDS or key.endswith('_id'):
            text(value, key, 240 if key in SHORT_FIELDS or key.endswith('_id') else TEXT_LIMIT,
                 nullable=key.endswith('_id') or key in ('start_date', 'due_date'))
        if key in BOOL_FIELDS and type(value) is not bool:
            invalid(f'{key} 必須是布林值')
        if key in ID_LISTS:
            if not isinstance(value, list) or len(value) > (50 if key == 'mentions' else 200):
                invalid(f'{key} 必須是符合數量上限的清單')
            for item in value:
                text(item, key, 240)
        if key in OBJECT_LISTS:
            if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
                invalid(f'{key} 必須是物件清單')
        if key in ('url', 'source_url', 'reference_url'):
            safe_reference_url(value, optional=True)
        if isinstance(value, dict):
            _payload_fields(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _payload_fields(item)


def validate_action(body):
    if not isinstance(body, dict) or not isinstance(body.get('action'), str):
        invalid('操作格式錯誤')
    _bounded(body)
    if len(json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8')) > MAX_ACTION_BYTES:
        invalid('操作資料超過 256 KB', 413)
    payload = body.get('payload', {})
    if not isinstance(payload, dict):
        invalid('payload 必須是物件')
    _payload_fields(payload)
    if body['action'] in ('task_add', 'task_update') and 'title' in payload and not payload['title'].strip():
        invalid('任務名稱不可空白')
    return body
