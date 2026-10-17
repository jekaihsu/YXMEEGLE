"""Read-only inventory of SOP contract state in a local backup snapshot.

Usage: python3 scripts/sop_inventory.py SNAPSHOT.zip

Lists projects, nodes, tasks, contract versions and pending items as
deterministic JSON on stdout. It opens the snapshot read-only, never connects
to a database or service, and never applies or rewrites anything. Whether the
counts match production is a separate, human-run acceptance step.
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from backend.sop_contracts import VERSION  # noqa: E402
from sop_snapshot_reader import SnapshotError, read_snapshot  # noqa: E402

PENDING_STATES = ('pending', 'submitted', 'waiting')


def _text(value):
    return value if isinstance(value, str) else None


def _dicts(value):
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def subcontract_decision(project, contract_version=VERSION):
    rules = project.get('sop_applicability')
    decision = rules.get('subcontract') if isinstance(rules, dict) else None
    if not isinstance(decision, dict):
        return 'missing'
    valid = (decision.get('contract_version') == contract_version and decision.get('decided_by')
             and decision.get('reason') and type(decision.get('applies')) is bool)
    return ('applies' if decision['applies'] else 'not_applicable') if valid else 'invalid'


def inventory_project(project, contract_version):
    nodes, versions, pending_nodes = [], Counter(), []
    for node in _dicts(project.get('nodes')):
        tasks = _dicts(node.get('tasks'))
        stale = [t for t in tasks if t.get('status') != 'completed' and t.get('sop_contract_version') != contract_version]
        undecided = node.get('sop_applicability_pending')
        undecided = undecided if isinstance(undecided, list) else []
        if undecided:
            pending_nodes.append(_text(node.get('key')))
        for task in tasks:
            versions[str(task.get('sop_contract_version'))] += 1
        nodes.append({
            'id': _text(node.get('id')), 'key': _text(node.get('key')), 'status': _text(node.get('status')),
            'has_requirements': isinstance(node.get('requirements'), list) and bool(node['requirements']),
            'tasks': len(tasks), 'completed_tasks': sum(t.get('status') == 'completed' for t in tasks),
            'open_tasks_needing_contract_review': sorted(str(t.get('id')) for t in stale),
            'pending_applicability': len(undecided),
        })
    return {
        'id': _text(project.get('id')), 'execution_system': project.get('execution_system') or 'pending',
        'sop_version': _text(project.get('sop_version')),
        'subcontract_decision': subcontract_decision(project, contract_version),
        'nodes': sorted(nodes, key=lambda n: (str(n['key']), str(n['id']))),
        'task_contract_versions': dict(sorted(versions.items())),
        'nodes_with_pending_applicability': sorted(k for k in pending_nodes if k),
    }


def inventory_workspace(workspace, contract_version):
    projects = [inventory_project(p, contract_version) for p in _dicts(workspace.get('projects'))]
    requests = [r for r in _dicts(workspace.get('sop_requests')) if r.get('status') in PENDING_STATES]
    approvals = [a for a in _dicts(workspace.get('approvals')) if a.get('status') in PENDING_STATES]
    return {
        'projects': sorted(projects, key=lambda p: str(p['id'])),
        'pending_sop_requests': sorted(str(r.get('id')) for r in requests),
        'pending_approvals': sorted(str(a.get('id')) for a in approvals),
    }


def build_inventory(path, contract_version=VERSION):
    digest, workspaces = read_snapshot(path)
    result = {
        'mode': 'read_only_inventory', 'snapshot_sha256': digest, 'current_contract_version': contract_version,
        'workspaces': {wid: inventory_workspace(ws, contract_version) for wid, ws in sorted(workspaces.items())},
        'not_verified': ['production counts', 'execution ownership decisions', 'daily-report reference rules'],
    }
    return result


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print('usage: sop_inventory.py SNAPSHOT.zip', file=sys.stderr)
        return 2
    try:
        report = build_inventory(argv[0])
    except SnapshotError as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
