"""Read-only, projected table readers."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from typing import Protocol

from ..live_read.client import LiveLarkClient, ReadFailure
from .registry import TABLES, BASE_TOKEN, Table

class Reader(Protocol):
    def read(self) -> dict: ...

class FixtureReader:
    def __init__(self, directory):
        self.directory = Path(directory)

    def read(self):
        result = {}
        for table in TABLES:
            path = self.directory / (table.name + '.json')
            if not path.exists():
                result[table.kind] = {'name': table.name, 'records': [], 'status': 'never'}
                continue
            result[table.kind] = project(json.loads(path.read_text()), table)
        return result


def project(data, table):
    return {'name': table.name, 'status': 'ok', 'records': [
        {'record_id': r['record_id'], 'fields': {k: v for k, v in r['fields'].items() if k in table.fields}}
        for r in data['records']]}

class LarkReader:
    def __init__(self, cfg, *, transport=None, tables=TABLES):
        self.cfg = dict(cfg)
        self.cfg.setdefault('LARK_WORKER_IDENTITY', 'application')
        self.cfg.setdefault('LARK_WORKER_ORGANIZATION', 'reports')
        self.transport, self.tables = transport, tables
        self.base = cfg.get('LARK_REPORT_BASE_TOKEN', BASE_TOKEN)

    def read_table(self, table):
        records, seen, ids = [], set(), set()
        params = {'page_size': 500, 'field_names': json.dumps(table.fields, ensure_ascii=False)}
        with LiveLarkClient(self.cfg, transport=self.transport) as client:
            for _ in range(100):
                response = client.request('GET', f'/bitable/v1/apps/{self.base}/tables/{table.table_id}/records', params=params)
                data = response.json().get('data')
                if isinstance(data, dict) and data.get('items') is None and data.get('has_more') is False and data.get('total') == 0:
                    data = {**data, 'items': []}
                if not isinstance(data, dict) or not isinstance(data.get('items'), list) or type(data.get('has_more')) is not bool:
                    raise ReadFailure('Incomplete reports table')
                for row in data['items']:
                    if not row.get('record_id') or row['record_id'] in ids or not isinstance(row.get('fields'), dict):
                        raise ReadFailure('Invalid or repeated reports record')
                    ids.add(row['record_id'])
                    records.append(row)
                if not data['has_more']:
                    return project({'records': records}, table)
                token = data.get('page_token')
                if not token or token in seen:
                    raise ReadFailure('Invalid reports pagination')
                seen.add(token)
                params['page_token'] = token
        raise ReadFailure('Reports table page budget exhausted')

    def read(self):
        with ThreadPoolExecutor(max_workers=3) as pool:
            return dict(zip((t.kind for t in self.tables), pool.map(self.read_table, self.tables)))
