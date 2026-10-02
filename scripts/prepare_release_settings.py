"""Prepare a COMPLETE replacement environment from a saved current response.

No network calls; credentials never printed. Applying the request is a separate
deployment step, after backup and source acceptance.
"""
import json
from pathlib import Path
try:
    from .release_env_guard import validate_environment
    from .deploy_prepare import validate_source_tables
except ImportError:
    from release_env_guard import validate_environment
    from deploy_prepare import validate_source_tables

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.runtime'


def main():
    result = json.loads((RUNTIME / 'release-current-env-response.json').read_text(encoding='utf-8'))
    if result.get('errors'):
        raise SystemExit('Current environment query failed')
    entries=result['data']['service']['variables']
    current = {entry['key']: entry['value'] for entry in entries}
    if len(current)!=len(entries): raise SystemExit('Duplicate environment keys; stopped')
    try: validate_environment(current)
    except ValueError as exc: raise SystemExit(str(exc)) from None
    tenants = [value.strip() for value in current.get('LARK_ALLOWED_TENANTS', '').split(',') if value.strip()]
    if len(tenants) != 1 or current.get('LARK_APP_ID') != 'cli_aa3cab98b2789e17':
        raise SystemExit('Expected dedicated app and one configured company')
    tables = validate_source_tables(ROOT / 'deployment/source-tables.json')
    delta = {
        'LARK_SOURCE_TABLES_JSON': json.dumps(tables, ensure_ascii=False, separators=(',', ':')),
        'LARK_WORKER_IDENTITY': 'application',
        'LARK_WORKER_ORGANIZATION': tenants[0],
    }
    request = {
        'query': 'mutation($s:ObjectID!,$e:ObjectID!,$data:Map!){updateEnvironmentVariable(serviceID:$s,environmentID:$e,data:$data)}',
        'variables': {'s': '6ab61834a4c05a5bcb57ad69', 'e': '6ab6168036d2a6cac409f0c6', 'data': {**current,**delta}},
    }
    (RUNTIME / 'release-settings-request.json').write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'prepared': True, 'changed_keys': sorted(delta), 'complete_key_count':len(request['variables']['data']), 'source_tables': len(tables), 'applied': False}))


if __name__ == '__main__':
    main()
