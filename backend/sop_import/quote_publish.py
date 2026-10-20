"""PREPARED, NOT ENABLED: publishing a local planning quote as one 報價總表 row.

Nothing calls this module; no route, job or command reaches it. It records the reviewed mapping so the later step
starts from it. It runs only when QUOTE_PUBLISH_ENABLED is true, the actor is an active manager holding
publish_local_quote, the case is a local planning case with an official 報價編號 that the register does not
already hold, and the caller injects a client. It never builds a Lark client.
"""
from datetime import datetime, timedelta, timezone
from typing import Protocol

from .domain import require

TAIPEI = timezone(timedelta(hours=8))
# Local case key, 報價總表 field, Lark field type.
FIELD_MAP = (
    ('official_quote_no', '報價編號', 'text'),
    ('name', '工程名稱', 'text'),
    ('client', '行號單位', 'text'),
    ('description', '備註', 'text'),
    ('pm_id', '案件負責人', 'user'),
    ('created_at', '詢價日期', 'datetime'),
)
# Lifecycle evidence the stage and suggestions read, links that write both tables, and fields Lark computes.
NEVER_WRITE = frozenset({'工程編號', '編號', '狀態', '狀態 (1)', '案件狀態', '提供給PM日期', '回傳單日期', '報價日期',
                         '確認單回傳開會日期', '提供行政回傳確認單時間', '契約價格(未稅)', '契約價格(含稅)', '此案確認單',
                         '此報價之合約明細', '案件已入帳', '入帳日期', '建立時間', '填寫人'})


class QuoteTable(Protocol):
    def find(self, table: tuple[str, str], quote_no: str) -> list[str]: ...

    def create(self, table: tuple[str, str], fields: dict, idempotency_key: str) -> str: ...


def table(cfg):
    token = cfg.get('LARK_QUOTE_BASE_TOKEN')
    require(isinstance(token, str) and bool(token.strip()), 'quote_publish_unready', 503)
    return (token.strip(), 'tblENZvYAya93Twa')


def wire(kind, value):
    if kind == 'user':
        return [{'id': value}]
    if kind == 'datetime':
        day = datetime.fromisoformat(value).astimezone(TAIPEI).date()
        return int(datetime(day.year, day.month, day.day, tzinfo=TAIPEI).timestamp() * 1000)
    return value


def fields_for(project):
    return {name: wire(kind, project[key]) for key, name, kind in FIELD_MAP if project.get(key)}


def publish(project, *, actor, cfg, client: QuoteTable | None):
    require(str(cfg.get('QUOTE_PUBLISH_ENABLED', 'false')).lower() == 'true', 'quote_publish_disabled', 503)
    require(actor.get('active', True) and actor.get('role') == 'manager'
            and 'publish_local_quote' in actor.get('capabilities', []), 'quote_publish_forbidden', 403)
    require(project.get('planning_origin') == 'local' and bool(project.get('official_quote_no')) and client is not None,
            'quote_publish_unready', 409)
    target = table(cfg)
    require(not client.find(target, project['official_quote_no']), 'quote_number_taken', 409)
    fields = fields_for(project)
    return {'record_id': client.create(target, fields, f"local-quote:{project['id']}"), 'fields': fields}
