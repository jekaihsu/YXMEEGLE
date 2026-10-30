"""Read-only projection of existing project state into OperationalCase / NodeRecord headers.

Behind `FEATURE_LARK_AUTHORITATIVE_OPS` (default OFF). Existing project, node and task IDs are copied verbatim;
entity IDs are derived deterministically from them so a restart or re-import never mints duplicates. The workspace
project data is only read, never modified.
"""
from .flags import OpsFlags


def case_entity_id(project_id):
    return f'case:{project_id}'


def node_entity_id(project_id, node_id):
    return f'node:{project_id}:{node_id}'


def project_headers(workspace):
    """Pure read: [(case, [node...])] with preserved project/node/task IDs."""
    out = []
    for project in workspace.get('projects', []):
        nodes = [{'entity_id': node_entity_id(project['id'], node['id']), 'node_id': node['id'],
                  'task_ids': [t['id'] for t in node.get('tasks', [])]} for node in project.get('nodes', [])]
        out.append(({'entity_id': case_entity_id(project['id']), 'project_id': project['id']}, nodes))
    return out


def sync_headers(domain, workspace, flags):
    """Register headers for existing projects. No-op (returns None) unless the flag is explicitly enabled."""
    if not isinstance(flags, OpsFlags) or flags.lark_authoritative_ops is not True:
        return None
    created = 0
    for case, nodes in project_headers(workspace):
        created += bool(domain.register_case(case['entity_id'], case['project_id']))
        for node in nodes:
            created += bool(domain.register_node(node['entity_id'], node['node_id'], case['entity_id'], node['task_ids']))
    return created
