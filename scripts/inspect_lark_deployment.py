"""Read only the existing company's Lark integration settings; never print secrets.

Run locally for an authorized deployment. Credentials are saved only to ignored
.runtime/lark-existing.json and must never be committed or included in a build.
"""
import argparse
import json
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--service-id', required=True)
    parser.add_argument('--environment-id')
    args = parser.parse_args()
    command = ['zeabur.cmd', 'variable', 'list', '--id', args.service_id, '--json', '-i=false']
    if args.environment_id:
        command += ['--env-id', args.environment_id]
    result = subprocess.run(command, capture_output=True, encoding='utf-8', errors='replace', timeout=60)
    if result.returncode:
        print(json.dumps({'ok': False, 'error': 'Zeabur variable read failed; output withheld to protect credentials'}))
        raise SystemExit(1)
    try:
        raw = json.loads(result.stdout)
    except ValueError:
        print(json.dumps({'ok': False, 'error': 'No structured variable response; an environment ID may be required'}))
        raise SystemExit(1)
    wanted = {'LARK_APP_ID','LARK_APP_SECRET','LARK_ALLOWED_TENANT_KEY','LARK_ALLOWED_TENANTS',
              'LARK_REDIRECT_URI','LARK_ROLE_ALLOWLIST','LARK_ROLE_MAP_JSON','LARK_ACCESS_MODE'}
    found = {}

    def visit(value):
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            key = value.get('Key') or value.get('key') or value.get('Name') or value.get('name')
            val = value.get('Value', value.get('value'))
            if key in wanted and isinstance(val, str):
                found[key] = val
            for key, val in value.items():
                if key in wanted and isinstance(val, str):
                    found[key] = val
                elif isinstance(val, (dict, list)):
                    visit(val)
    visit(raw)
    if not found:
        print(json.dumps({'ok': False, 'error': 'No matching Lark keys', 'response_type': type(raw).__name__}))
        raise SystemExit(1)
    target = Path(__file__).resolve().parents[1] / '.runtime' / 'lark-existing.json'
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(found), encoding='utf-8')
    print(json.dumps({'ok': True, 'keys': sorted(found), 'stored': '.runtime/lark-existing.json',
                      'credentials_printed': False}))


if __name__ == '__main__':
    main()
