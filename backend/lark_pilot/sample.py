"""One preflight plus one bounded sample, with no pagination or persisted cache."""
from datetime import datetime, timezone
import re

from ..live_read.client import LiveLarkClient, ReadBlocked, ReadFailure
from ..live_read.rate_limit import BudgetExceeded
from .shadow import ids, identities, link, project

BASE = 'H7W6b0PFWaVF1BsgqXJj3pQ9pXb'
CASES, WORK, PEOPLE = 'tblmSQrcCs9vPQZx', 'tbl5zPLS0ExWNEty', 'tblfaCO2xPUNptQH'
FIELDS = {CASES: ('fldgZDflpb', 'flddfFq9zI'),
          WORK: ('fldjfxJIMb', 'fldlqnGoTh', 'fldvSpUqa9', 'fldJs4RTUm', 'fldnCPisZ5'),
          PEOPLE: ('fldCTLvsWG',)}
# Lark search takes field NAMES in field_names and keys response fields by NAME. Names come from the
# verified live schema capture (vcc117-mapping .runtime/lark-schema-capture/<table_id>.json, table.fields).
NAMES = {'fldgZDflpb': '工程確認單編號', 'flddfFq9zI': '外業工作單', 'fldjfxJIMb': '工作單號',
         'fldlqnGoTh': '組長人員-津貼來源V2', 'fldvSpUqa9': '組員人員-津貼來源V2',
         'fldJs4RTUm': '組長帳號-津貼自動化', 'fldnCPisZ5': '組員帳號-津貼自動化', 'fldCTLvsWG': 'Lark帳號'}
CAPS = {'cases': 3, 'work_orders': 10, 'people': 10}
ROOT = f'/bitable/v1/apps/{BASE}/tables'
SEARCH = ROOT + '/{table}/records/search'
TEMPLATE = '/bitable/v1/apps/{base}/tables/{table}/records/search'


def empty_result():
    return {'status': 'unconfigured', 'source': 'unmapped', 'fetched_at': None, 'ttl_seconds': 60,
            'last_error': None, 'sampling_rule': 'first page; sort stable record IDs; follow links; no pagination',
            'records': {name: [] for name in CAPS}, 'table_states': {name: 'not_read' for name in CAPS},
            'counts': {name: None for name in CAPS},
            'table_fetched_at': {name: None for name in CAPS},
            'receipt': {'identity_category': 'missing', 'config_present': False, 'outcome': 'unconfigured',
                        'endpoint': None, 'operation': None, 'permission_needed': None, 'requests': []}}


class PilotReader:
    def __init__(self, cfg, *, transport=None, **client_options):
        self.cfg = cfg
        self.source = 'mock' if transport is not None else 'lark_live'
        self.client = LiveLarkClient(cfg, transport=transport,
            allowed_posts=(re.escape(ROOT) + r'/[^/]+/records/search',), **client_options)
        self.requests = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.client.close()

    def get_json(self, path):
        if path != ROOT:
            raise ReadBlocked('Pilot path outside read allowlist')
        self.requests.append({'method': 'GET', 'endpoint': '/bitable/v1/apps/{base}/tables'})
        return self.client.request('GET', path, params={'page_size': 1}).json()['data']

    def search_records(self, table, count, record_ids=None):
        if table not in FIELDS or not 1 <= count <= (3 if table == CASES else 10):
            raise ReadBlocked('Pilot search outside bounded sample')
        body = {'field_names': [NAMES[f] for f in FIELDS[table]], 'page_size': count}
        if record_ids is not None:
            # Stable Base record IDs only; never expand a person name into a query.
            body['filter'] = {'conjunction': 'or', 'conditions': [
                {'field_name': 'record_id', 'operator': 'is', 'value': [key]} for key in record_ids[:count]]}
        self.requests.append({'method': 'POST', 'endpoint': TEMPLATE})
        data = self.client.request('POST', SEARCH.format(table=table), json=body).json()['data']
        by_name = {NAMES[f]: f for f in FIELDS[table]}
        for item in data.get('items', []):
            fields = item.get('fields', {}) if isinstance(item, dict) else {}
            if isinstance(fields, dict):
                if set(fields) - set(by_name):
                    raise ReadFailure('field_name_mismatch')
                item['fields'] = {by_name[k]: v for k, v in fields.items()}
        return data

    def read(self):
        result = empty_result()
        receipt = result['receipt']
        present = all(bool(self.cfg.get(k)) for k in ('LARK_APP_ID', 'LARK_APP_SECRET', 'LARK_WORKER_ORGANIZATION'))
        receipt['config_present'] = present
        receipt['identity_category'] = ('not_application' if self.cfg.get('LARK_WORKER_IDENTITY') != 'application'
                                        else 'application' if present else 'missing')
        if not present or receipt['identity_category'] != 'application':
            return result
        result['source'] = self.source
        receipt['endpoint'] = '/bitable/v1/apps/{base}/tables'
        receipt['operation'] = 'preflight_tables'
        active = None
        try:
            self.get_json(ROOT)
            receipt.update(endpoint=TEMPLATE, operation='preflight_case')
            self.search_records(CASES, 1)
            receipt['outcome'] = 'ok'
            result['status'] = 'fresh'
            for name, table in [('cases', CASES), ('work_orders', WORK), ('people', PEOPLE)]:
                active = name
                keys = None
                if name != 'cases':
                    previous = result['records']['cases' if name == 'work_orders' else 'work_orders']
                    links = ('flddfFq9zI',) if name == 'work_orders' else ('fldlqnGoTh', 'fldvSpUqa9')
                    keys = sorted({key for row in previous for f in links
                                   for key in ids(row['fields'][f].get('value'))})
                    if not keys:
                        continue
                count = CAPS[name] if keys is None else min(CAPS[name], len(keys))
                receipt.update(endpoint=TEMPLATE, operation='sample_' + name)
                data = self.search_records(table, count, keys)
                items = data.get('items', [])
                if not isinstance(items, list) or any(not isinstance(x, dict) or not isinstance(x.get('record_id'), str)
                    or not isinstance(x.get('fields', {}), dict) for x in items):
                    raise ReadFailure('Invalid sample')
                candidates = {x['record_id']: x for x in items if keys is None or x['record_id'] in keys[:count]}
                chosen = [candidates[key] for key in sorted(candidates)[:count]]
                stamp = datetime.now(timezone.utc).isoformat()
                result['fetched_at'] = result['fetched_at'] or stamp
                result['table_fetched_at'][name] = stamp
                result['records'][name] = [project(x, table, FIELDS[table], self.source, stamp) for x in chosen]
                result['table_states'][name] = 'present'
                result['counts'][name] = {'requested': count, 'returned': len(chosen),
                    'omitted': max(len(items), len(keys or [])) - len(chosen), 'has_more': bool(data.get('has_more'))}
        except (ReadBlocked, ReadFailure, BudgetExceeded, KeyError, TypeError, ValueError) as exc:
            denied = isinstance(exc, ReadBlocked)
            receipt['outcome'] = 'denied' if denied else 'partial'
            receipt['permission_needed'] = 'bitable:app:readonly and application Base/table read grant' if denied else None
            result['status'] = 'partial' if any(result['records'].values()) else 'blocked' if denied else 'error'
            result['code'] = 'lark_permission_denied' if denied else 'lark_read_failed'
            result['last_error'] = 'Lark 拒絕此應用讀取' if denied else 'Lark 資料暫時無法讀取'
            if active:
                result['table_states'][active] = 'forbidden' if denied else 'partial'
            for rows in result['records'].values():
                for row in rows:
                    row['freshness'] = 'partial'
        if result['status'] == 'fresh' and any(
            result['table_states'][name] != 'present' or
            result['counts'][name]['has_more'] or result['counts'][name]['omitted'] > 0
            for name in CAPS
        ):
            result['status'] = 'partial'
            receipt['outcome'] = 'partial'
            for rows in result['records'].values():
                for row in rows:
                    row['freshness'] = 'partial'
        for name, f, target in [('cases', 'flddfFq9zI', 'work_orders'),
                               ('work_orders', 'fldlqnGoTh', 'people'), ('work_orders', 'fldvSpUqa9', 'people')]:
            for row in result['records'][name]:
                row['links'][f] = link(row['fields'][f].get('value'),
                    [r['record_id'] for r in result['records'][target]], result['table_states'][target])
        for row in result['records']['people']:
            row['identity'] = identities(row['fields']['fldCTLvsWG'].get('value'))
        receipt['requests'] = self.requests
        receipt['affected_fields'] = {name: list(FIELDS[table]) for name, table in
                                     [('cases', CASES), ('work_orders', WORK), ('people', PEOPLE)]}
        return result
