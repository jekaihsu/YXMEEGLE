"""Read known native definitions with the deployed application; no instance access."""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.lark_adapter import application_adapter
from backend.sources import API


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--saved-config', required=True)
    parser.add_argument('--output', default='.runtime/approval-definition-probe-20260927.json')
    args = parser.parse_args()
    raw = json.loads(Path(args.saved_config).read_text(encoding='utf-8-sig'))
    cfg = raw.get('variables', {}).get('data', raw).copy()
    tenants = [v.strip() for v in cfg.get('LARK_ALLOWED_TENANTS', '').split(',') if v.strip()]
    if len(tenants) != 1:
        raise SystemExit('Expected one explicitly configured company')
    cfg.update(LARK_WORKER_IDENTITY='application', LARK_WORKER_ORGANIZATION=tenants[0])
    known = {'leave': 'E9C400FC-10AD-4581-ACF7-B37B5D16CBD5'}
    for kind, key in [('change', 'LARK_CHANGE_APPROVAL_CODE'),
                      ('extension', 'LARK_EXTENSION_APPROVAL_CODE'),
                      ('node_skip', 'LARK_NODE_SKIP_APPROVAL_CODE')]:
        if cfg.get(key): known[kind] = cfg[key]
    adapter = application_adapter(cfg)
    results = []
    try:
        for kind, code in known.items():
            if not re.fullmatch(r'[A-Za-z0-9_-]{6,128}', code):
                results.append({'kind': kind, 'error': 'invalid_configured_code'})
                continue
            response = adapter.client.get(API + '/approval/v4/approvals/' + code,
                headers={'Authorization': 'Bearer ' + adapter.token},
                params={'locale': 'zh-CN', 'user_id_type': 'open_id', 'with_admin_id': 'false'})
            body = response.json()
            item = {'kind': kind, 'http_status': response.status_code, 'code': body.get('code'),
                    'definition_code': code}
            if body.get('code') == 0:
                data = body.get('data') or {}
                form = json.loads(data.get('form') or '[]')
                item.update(name=data.get('approval_name'),
                            form_control_count=len(form), node_count=len(data.get('node_list') or []))
            else:
                item['required_scope_candidates'] = sorted(set(re.findall(
                    r'approval:[a-z_:]+', str(body.get('msg') or '') + json.dumps(body.get('error') or {}))))
            results.append(item)
    finally:
        adapter.client.close()
    report = {'identity': 'application', 'remote_writes': False, 'instance_access': False,
              'configured_types': sorted(known), 'results': results}
    target = Path(args.output)
    if target.resolve() == Path(args.saved_config).resolve():
        raise SystemExit('Output must not overwrite configuration')
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'remote_writes': False, 'results': [
        {k: v for k, v in item.items() if k not in ('definition_code', 'name')} for item in results]},
        ensure_ascii=False))


if __name__ == '__main__':
    main()
