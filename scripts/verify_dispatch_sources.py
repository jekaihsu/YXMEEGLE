#!/usr/bin/env python3
"""Check dispatch field dependencies against recorded or explicitly requested CLI metadata.

Offline: python scripts/verify_dispatch_sources.py --snapshot fields.json
The JSON maps table IDs to field-list CLI responses or arrays of field objects.
Live: python scripts/verify_dispatch_sources.py --live [--cli lark-cli] [--profile NAME]
Only field metadata is queried. No records or remote writes are requested.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.dispatch_board.config import DispatchBoardConfig, TABLES


def fields_in(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        if payload.get('has_more') is True:
            raise ValueError('field-list snapshot is paginated; provide all fields as an array')
        for key in ('items', 'fields', 'data', 'result'):
            if key in payload:
                return fields_in(payload[key])
    raise ValueError('field-list output must contain a field array')


def verify(snapshot):
    if not isinstance(snapshot, dict):
        raise ValueError('snapshot must map table IDs to field-list outputs')
    results = []
    for key, table in TABLES.items():
        fields = fields_in(snapshot[table.table_id]) if table.table_id in snapshot else []
        if any(not isinstance(field, dict) or not isinstance(field.get('field_name'), str) for field in fields):
            raise ValueError('invalid field metadata')
        actual = {field['field_name']: field for field in fields}
        for name, expected in table.fields.items():
            field = actual.get(name)
            kind = field.get('type') if field else None
            state = 'missing' if field is None else 'verified' if type(kind) is int and kind in expected else 'drift'
            results.append({'table': key, 'table_id': table.table_id, 'field': name, 'status': state,
                            'expected_types': list(expected), 'actual_type': kind,
                            'field_id': field.get('field_id') if field else None})
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--snapshot', type=Path)
    source.add_argument('--live', action='store_true')
    parser.add_argument('--cli', default='lark-cli')
    parser.add_argument('--profile')
    args = parser.parse_args(argv)
    try:
        if args.snapshot:
            snapshot = json.loads(args.snapshot.read_text(encoding='utf-8'))
        else:
            base = DispatchBoardConfig.from_env(os.environ).base
            snapshot = {}
            for table in TABLES.values():
                command = [args.cli]
                if args.profile:
                    command += ['--profile', args.profile]
                command += ['base', '+field-list', '--base-token', base, '--table-id', table.table_id, '--as', 'bot', '--json']
                result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=60)
                snapshot[table.table_id] = json.loads(result.stdout)
        results = verify(snapshot)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f'Cannot verify dispatch sources ({type(exc).__name__}).', file=sys.stderr)
        return 2
    for result in results:
        print(json.dumps(result, ensure_ascii=False))
    return 0 if all(result['status'] == 'verified' for result in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
