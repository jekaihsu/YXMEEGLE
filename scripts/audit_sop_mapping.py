"""Read-only comparison of saved source keys and declared local mappings."""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
inventory = json.loads((ROOT / 'docs/MEEGLE_TEMPLATE_334662_INVENTORY_20260928.json').read_text(encoding='utf-8'))
tree = ast.parse((ROOT / 'backend/policy.py').read_text(encoding='utf-8'))
mapping = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'SOURCE_NODES' for t in n.targets))
targets = {}
for local, sources in mapping.items():
    for source in sources:
        targets.setdefault(source, []).append(local)
nodes = inventory['nodes']
report = {
    'audit_scope': 'declared source references only; not execution equivalence',
    'template_id': inventory['template_id'], 'version': inventory['version'],
    'source_sha256': inventory['sha256'],
    'second_template': {'id': '566082', 'status': 'body_not_available; CLI no local token 2026-09-29'},
    'source_nodes': len(nodes),
    'referenced_nodes': sum(n['key'] in targets for n in nodes),
    'unreferenced_nodes': [
        {'key': n['key'], 'name': n['name'], 'disposition': 'intentionally_disabled_by_user' if n['key'] in ('state_52', 'state_58') else 'requires_explicit_mapping_or_exclusion'}
        for n in nodes if n['key'] not in targets and n['key'] != 'started'
    ],
    'many_to_many_references': {key: value for key, value in targets.items() if len(value) > 1},
    'condition_execution_verified': False,
    'attachment_and_input_schema_complete': False,
    'migration_preserves_history_verified': False,
}
print(json.dumps(report, ensure_ascii=False, indent=2))
