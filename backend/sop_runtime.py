"""Read-only source-topology coverage for the running workbench.

A reference on a local task records provenance, not authority to finish the
referenced source node. Keep local progress separate from source readiness until
the versioned execution mapping has actually been implemented and approved.
"""
from functools import lru_cache

from .sop_contracts import _catalog, applicability, disabled_task
from .sop_topology import Topology


@lru_cache(maxsize=1)
def _source_graph():
    template = next(t for t in _catalog()['templates'] if t['id'] == 334662)
    graph = Topology({
        'template_id': template['id'], 'version': template['version'],
        'nodes': [dict(key=n['state_key'], start_mode=n['start_mode'],
                       disabled=n['disabled']) for n in template['nodes']],
        'edges': template['connections'],
    })
    return graph


def topology_projection(project, *, details=False):
    """Expose missing wiring without changing tasks, votes, or applicability.

    No project-supplied readiness/completed flags are accepted as source facts.
    Only exact template/version/node references count toward coverage. Even full
    provenance coverage is not a verified source execution mapping.
    """
    graph = _source_graph()
    mapped = {key: {} for key in graph.nodes}
    invalid = 0
    for node in project.get('nodes', []):
        for task in node.get('tasks', []):
            if task.get('status') == 'superseded':
                continue
            refs = task.get('source_contract_refs') or []
            if not isinstance(refs, list):
                invalid += 1
                continue
            for ref in refs:
                if not isinstance(ref, dict):
                    invalid += 1
                    continue
                if ref.get('template_id') != graph.template:
                    # Other known source templates remain separate identities.
                    continue
                key = ref.get('node_key')
                if (type(ref.get('version')) is not int or ref['version'] != graph.version
                        or not isinstance(key, str) or key not in mapped):
                    invalid += 1
                    continue
                # Dedupe repeated references, not two distinct local tasks.
                identity = (node.get('id'), task.get('id'))
                mapped[key][identity] = task

    # Missing execution contracts stay unknown. Disabled source nodes have the
    # explicit company decision and can be identified without task completion.
    readiness = graph.readiness({}, ())
    enabled = set(graph.nodes) - graph.disabled
    linked = {key for key in enabled if mapped[key]}
    pending = set()
    for key in linked:
        for task in mapped[key].values():
            if disabled_task(task):
                continue
            if applicability(project, {'applicability': task.get('sop_applicability') or 'always'}) is None:
                pending.add(key)

    result = {
        'template_id': graph.template, 'version': graph.version,
        'status': 'execution_mapping_pending',
        'source_node_count': len(graph.nodes),
        'source_edge_count': sum(len(edges) for edges in graph.successors.values()),
        'disabled_node_count': len(graph.disabled),
        'referenced_node_count': len(linked),
        'unreferenced_node_count': len(enabled - linked),
        'conditional_pending_node_count': len(pending),
        'invalid_reference_count': invalid,
        'source_execution_verified': False,
        'local_completion_is_source_completion': False,
    }
    if details:
        result['nodes'] = [{
            'key': key,
            'status': readiness[key].status,
            'predecessors': sorted(graph.predecessors[key]),
            'local_task_count': len(mapped[key]),
            'local_completed_task_count': sum(t.get('status') == 'completed' for t in mapped[key].values()),
            'mapping_status': ('disabled' if key in graph.disabled else
                               'referenced_only' if mapped[key] else 'unmapped'),
            'applicability_pending': key in pending,
        } for key in sorted(graph.nodes)]
    return result
