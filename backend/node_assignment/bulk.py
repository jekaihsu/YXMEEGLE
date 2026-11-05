"""Read-only chain projection shared by home panels and the case portfolio."""
from collections import Counter, defaultdict

from ..sources import link_ids, normalized_case, text
from .domain import NODE_LABELS, NodeKey, derive_chain
from .evidence import applicable, evidence_of
from .lark_table import CaseSnapshot, assignment_key, parse_node, parse_task
from .operations import facts_of
from .service import Context, confirmation_record


class AssignmentChains:
    def __init__(self, service, state, data, user, raw_nodes, raw_tasks):
        self.nodes = {r['record_id']: parse_node(r) for r in raw_nodes}
        self.tasks = {r['record_id']: parse_task(r) for r in raw_tasks}
        self.node_fields = {r['record_id']: r['fields'] for r in raw_nodes}
        self.task_fields = {r['record_id']: r['fields'] for r in raw_tasks}
        self.projects = defaultdict(list)
        for project in state.get('projects', []):
            if project.get('source_kind') in ('demo', 'mock', 'simulation'):
                continue
            rid = confirmation_record(project, service.config)
            if rid:
                self.projects[rid].append(project)
        labels = {value: key for key, value in NODE_LABELS.items()}
        groups = defaultdict(lambda: defaultdict(list))
        self.node_keys, self.node_groups = {}, {}
        self.duplicate_keys = Counter(row.assignment_key for row in self.nodes.values())
        for rid, row in self.nodes.items():
            fields = self.node_fields[rid]
            code = normalized_case(fields.get('確認單編號'))
            key = labels.get(text(fields.get('節點')).strip())
            if code and key and row.assignment_key == assignment_key(code, key):
                self.node_keys[rid] = (code, key)
                group = (code, tuple(sorted(link_ids(fields.get('工程確認單')))))
                self.node_groups[rid] = group
                groups[group][key].append(row)
        linked = defaultdict(list)
        for task in self.tasks.values():
            if len(task.node_ids) == 1:
                linked[task.node_ids[0]].append(task)
        self.linked = {rid: tuple(linked[rid]) for rid in self.nodes}
        self.chains, self.portfolio_statuses = {}, {}
        reports = service.reports() if service.reports else None
        legacy_records = service.legacy_completion_records(data['wid']) if groups else None
        for group, rows in groups.items():
            code, relations = group
            project = self.project_for(code, relations)
            skipped = frozenset(NodeKey(n['key']) for n in project.get('nodes', [])
                                if n.get('key') in NODE_LABELS and service.skipped_nodes(state, project, n)) if project else frozenset()
            snap = CaseSnapshot(code, {k: tuple(v) for k, v in rows.items()}, self.linked)
            evidence = applicable(evidence_of(project, state, reports), skipped) if project else {}
            legacy = {}
            if project:
                ctx = Context(data['wid'], user, state, project, lambda: user)
                legacy = service.legacy_completions(ctx, snap, records=legacy_records.get(project['id'], [])) if legacy_records is not None else service.legacy_completions(ctx, snap)
            chain = derive_chain(facts_of(snap, skipped, evidence, legacy))
            self.chains[group] = chain
            if project and all(self.duplicate_keys[row.assignment_key] == 1 for entries in rows.values() for row in entries):
                self.portfolio_statuses[project['id']] = chain

    def project_for(self, code, relations):
        candidates = self.projects.get(relations[0], []) if len(relations) == 1 else []
        return candidates[0] if len(candidates) == 1 and normalized_case(candidates[0].get('code')) == code else None
