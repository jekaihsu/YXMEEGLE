#!/usr/bin/env python3
"""Opt-in app-token shape recorder; output contains types/lengths, never values.

Usage: python scripts/record_lark_fixtures.py --compare
Attendance additionally needs LARK_FIXTURE_EMPLOYEE_ID (verified employee_id).
Use --input .runtime/lark-fixtures.json --compare for an offline shape diff.
Real shapes remain unverified until this command is run on staging.
"""
import argparse
import difflib
import json
import os
from pathlib import Path
import sys
from datetime import date

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.live_read.client import LiveLarkClient
from backend.sources import configuration

SAFE_FIELDS = ('工程名稱', '所屬成本單')
QUERY_PATH = '/attendance/v1/user_daily_shifts/query'
# No HR Base or salary columns are requested, even for schema discovery.
OTHER_BASELINES = {
    'tables': {'code': 0, 'data': {'items': [{'table_id': 'tblSynthetic', 'name': 'Synthetic', 'revision': 1}], 'has_more': False}},
    'shifts_query': {'code': 0, 'data': {'user_daily_shifts': [{'user_id': 'employee-synthetic', 'month': 202610, 'day_no': 7, 'shift_id': 'shift-synthetic', 'group_id': 'group-synthetic'}]}},
    'shift_get': {'code': 0, 'data': {'shift_id': 'shift-synthetic', 'is_flexible': False, 'punch_time_rule': [{'on_time': '09:00', 'off_time': '18:00'}]}},
}


def runtime_path(path):
    """Resolve symlinks too: an apparent .runtime path must not escape it."""
    runtime = ROOT / '.runtime'
    resolved = Path(path).resolve()
    if runtime.is_symlink() or not resolved.is_relative_to(runtime) or resolved == runtime:
        raise ValueError('Fixture paths must be inside repository .runtime/')
    return resolved


def sanitise(value):
    if isinstance(value, dict):
        return {key: sanitise(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitise(item) for item in value]
    result = {'type': type(value).__name__}
    if isinstance(value, str):
        result['length'] = len(value)
    return result


def shape(value):
    """Ignore scalar lengths, ordering and counts; keep keys and type variants."""
    if isinstance(value, dict):
        if set(value) <= {'type', 'length'} and 'type' in value:
            return value['type']
        return {key: shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        variants = {json.dumps(shape(item), sort_keys=True) for item in value}
        return [json.loads(item) for item in sorted(variants)]
    return type(value).__name__


def baselines():
    result = {name: [sanitise(body)] for name, body in OTHER_BASELINES.items()}
    for api in ('list', 'search'):
        fixture = json.loads((ROOT / f'backend/fixtures/lark/sources_{api}.json').read_text())
        result[api] = [sanitise(page) for page in fixture['pages']]
        result['fields'] = [sanitise(fixture['fields'])]
    return result


def compare(recorded):
    expected = baselines()
    before = json.dumps({key: shape(value) for key, value in expected.items()}, indent=2, sort_keys=True).splitlines()
    after = json.dumps({key: shape(value) for key, value in recorded.items()}, indent=2, sort_keys=True).splitlines()
    return '\n'.join(difflib.unified_diff(before, after, fromfile='synthetic baseline', tofile='recorded shapes', lineterm=''))


def record(cfg, client):
    tables = configuration(cfg)
    # Restrict this recorder to approved business Bases, not configurable HR aliases.
    from backend.sources import KNOWN_TABLES
    tables = [t for t in tables if t['base_token'] in KNOWN_TABLES]
    if not tables:
        raise ValueError('An approved business source table is required')
    employee = cfg.get('LARK_FIXTURE_EMPLOYEE_ID')
    if not employee:
        raise ValueError('LARK_FIXTURE_EMPLOYEE_ID is required for attendance shapes')
    table = tables[0]
    root = f"/bitable/v1/apps/{table['base_token']}/tables"
    path = root + '/' + table['table_id']
    result, available = {}, set()

    def request(method, endpoint, **kwargs):
        return client.request(method, endpoint, **kwargs).json()

    def pages(name, method, endpoint, params, body=None):
        collected, seen = [], set()
        for _ in range(50):
            raw = request(method, endpoint, params=params, **({'json': body} if body is not None else {}))
            data = raw['data']
            if not isinstance(data.get('has_more'), bool) or not isinstance(data.get('items'), list):
                raise ValueError('Incomplete pagination')
            if name == 'fields':
                data['items'] = [item for item in data['items'] if item.get('field_name') in SAFE_FIELDS]
                available.update(item['field_name'] for item in data['items'])
            elif name in ('list', 'search'):
                for item in data['items']:
                    item['fields'] = {key: value for key, value in item.get('fields', {}).items() if key in SAFE_FIELDS}
            collected.append(sanitise(raw))
            if not data['has_more']:
                result[name] = collected
                return
            cursor = data.get('page_token')
            if not isinstance(cursor, str) or not cursor or cursor in seen:
                raise ValueError('Invalid pagination cursor')
            seen.add(cursor)
            params = dict(params, page_token=cursor)
        raise ValueError('Pagination limit reached')

    pages('tables', 'GET', root, {'page_size': 100})
    pages('fields', 'GET', path + '/fields', {'page_size': 100})
    projected = [name for name in SAFE_FIELDS if name in available]
    if not projected:
        raise ValueError('Source table has no approved fixture fields')
    pages('list', 'GET', path + '/records', {'page_size': 200, 'automatic_fields': 'true', 'field_names': json.dumps(projected), 'user_id_type': 'open_id'})
    pages('search', 'POST', path + '/records/search', {'page_size': 500, 'user_id_type': 'open_id'}, {'automatic_fields': True, 'field_names': projected})
    today = int(date.today().strftime('%Y%m%d'))
    raw = request('POST', QUERY_PATH, params={'employee_type': 'employee_id'}, json={'user_ids': [employee], 'check_date_from': today, 'check_date_to': today})
    result['shifts_query'] = [sanitise(raw)]
    rows = raw['data']['user_daily_shifts']
    shift = next((row.get('shift_id') for row in rows if row.get('shift_id')), None)
    if not shift:
        raise ValueError('No scheduled shift returned; cannot verify shift get')
    from urllib.parse import quote
    result['shift_get'] = [sanitise(request('GET', '/attendance/v1/shifts/' + quote(shift, safe='')))]
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default=str(ROOT / '.runtime/lark-fixtures.json'))
    parser.add_argument('--input', help='Offline sanitised recording inside .runtime')
    parser.add_argument('--compare', action='store_true')
    args = parser.parse_args(argv)
    try:
        output = runtime_path(args.output)  # Validate before any network request.
        if args.input:
            recorded = json.loads(runtime_path(args.input).read_text())
        else:
            cfg = dict(os.environ)
            cfg['LARK_WORKER_IDENTITY'] = 'application'
            with LiveLarkClient(cfg, allowed_posts=(r'/bitable/v1/apps/[^/]+/tables/[^/]+/records/search', QUERY_PATH)) as client:
                recorded = record(cfg, client)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(recorded, ensure_ascii=False, indent=2) + '\n')
        if args.compare:
            diff = compare(recorded)
            print(diff or 'No shape differences (synthetic baseline; staging verification required).')
            return int(bool(diff))
        print('Sanitised recording saved inside .runtime/')
        return 0
    except Exception:
        # SDK/server exceptions may contain credentials or response values.
        print('Recording failed; check configuration, allowed output path and read access.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
