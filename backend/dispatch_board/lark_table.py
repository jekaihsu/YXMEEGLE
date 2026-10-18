"""Allowlisted, read-only V4 tables through the existing live HTTP boundary."""
import json

from ..live_read.client import LiveLarkClient, ReadFailure
from .config import DispatchBoardConfig, TABLES


class DispatchReader:
    def __init__(self, cfg, *, transport=None, client_options=None):
        self.cfg = dict(cfg)
        self.base = DispatchBoardConfig.from_env(cfg).base
        self.transport = transport
        self.client_options = client_options or {}

    def read_table(self, key):
        table = TABLES[key]
        params = {'page_size': 500, 'field_names': json.dumps(list(table.fields), ensure_ascii=False)}
        records, ids, cursors = [], set(), set()
        with LiveLarkClient(self.cfg, transport=self.transport, **self.client_options) as client:
            for _ in range(100):
                response = client.request('GET', f'/bitable/v1/apps/{self.base}/tables/{table.table_id}/records', params=params)
                data = response.json().get('data')
                if not isinstance(data, dict) or type(data.get('has_more')) is not bool:
                    raise ReadFailure('Incomplete dispatch pagination')
                page = data.get('items')
                if page is None and not records and data.get('has_more') is False and data.get('total') == 0:
                    page = []
                if not isinstance(page, list):
                    raise ReadFailure('Incomplete dispatch records')
                for row in page:
                    if not isinstance(row, dict) or not isinstance(row.get('record_id'), str) or not row['record_id'] or not isinstance(row.get('fields'), dict):
                        raise ReadFailure('Invalid dispatch record')
                    if row['record_id'] in ids:
                        raise ReadFailure('Repeated dispatch record')
                    ids.add(row['record_id'])
                    records.append({'record_id': row['record_id'], 'fields': {
                        name: value for name, value in row['fields'].items() if name in table.fields}})
                if not data['has_more']:
                    return records
                cursor = data.get('page_token')
                if not isinstance(cursor, str) or not cursor or cursor in cursors:
                    raise ReadFailure('Invalid dispatch cursor')
                cursors.add(cursor)
                params['page_token'] = cursor
        raise ReadFailure('Dispatch page budget exhausted')
