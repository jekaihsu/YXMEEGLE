"""Pure, fail-closed SOP source compiler and readiness core.

This module does not publish templates, mutate projects, complete nodes, or grant
skip authority. Visibility expressions are evidence only. Callers must resolve
approved applicability separately before asking for readiness.
"""
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True, order=True)
class SourceKey:
    template: int
    version: int
    node: str
    task: str | None = None


def index_contracts(catalog):
    """Keep equal display names separate; reject duplicate source identities."""
    result = {}
    for template in catalog['templates']:
        if type(template['id']) is not int or type(template['version']) is not int:
            raise ValueError('invalid template identity')
        for node in template['nodes']:
            if not isinstance(node['state_key'], str) or not node['state_key']:
                raise ValueError('invalid node identity')
            key = SourceKey(template['id'], template['version'], node['state_key'])
            if key in result:
                raise ValueError('duplicate node source identity')
            result[key] = node
            for task in node.get('tasks', []):
                if not isinstance(task['task_key'], str) or not task['task_key']:
                    raise ValueError('invalid task identity')
                task_key = SourceKey(key.template, key.version, key.node, task['task_key'])
                if task_key in result:
                    raise ValueError('duplicate task source identity')
                result[task_key] = task
    return result


@dataclass(frozen=True)
class FieldSpec:
    kind: str
    options: frozenset[str] = frozenset()

    def accepts(self, value):
        if self.kind == 'radio':
            return isinstance(value, str) and value in self.options
        if self.kind == 'boolean':
            return type(value) is bool
        if self.kind == 'text':
            return isinstance(value, str)
        if self.kind == 'number':
            import math
            return type(value) in (int, float) and math.isfinite(value)
        return False


@dataclass(frozen=True)
class Evaluation:
    value: bool | None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class Condition:
    operation: str
    field: str = ''
    expected: object = None
    spec: FieldSpec | None = None
    children: tuple = ()
    reason: str = ''

    def evaluate(self, values: Mapping):
        if self.operation == 'unknown':
            return Evaluation(None, (self.reason,))
        if self.operation == 'literal':
            return Evaluation(self.expected)
        if self.operation in ('AND', 'OR'):
            results = [child.evaluate(values) for child in self.children]
            # Deliberately fail closed even when another operand is decisive:
            # unmapped company rules must remain visible for reconciliation.
            unknown = [reason for result in results for reason in result.reasons]
            if any(result.value is None for result in results):
                return Evaluation(None, tuple(unknown))
            return Evaluation((all if self.operation == 'AND' else any)(r.value for r in results))
        if self.field not in values:
            return Evaluation(None, (f'missing_field:{self.field}',))
        actual = values[self.field]
        if not self.spec.accepts(actual):
            return Evaluation(None, (f'invalid_or_unknown_value:{self.field}',))
        equal = actual == self.expected
        return Evaluation(equal if self.operation == 'Eq' else not equal)


def _kind(value):
    # The source encodes booleans as `bool`; runtime facts are typed `boolean`.
    return 'boolean' if value == 'bool' else value


def _operand(spec, raw):
    # Source booleans are stored as the strings "1"/"0"; nothing else is coerced.
    if spec.kind == 'boolean' and isinstance(raw, str) and raw in ('0', '1'):
        return raw == '1'
    return raw


def compile_condition(source, schema: Mapping[str, FieldSpec]):
    """Compile the source's structured tree, never its BQL/formula strings.

    Schema must come from verified field metadata; option IDs are not inferred
    from expressions or translated labels. Only Eq/Ne scalar predicates are
    supported; unsupported syntax remains an explicit unknown.
    """
    def unknown(reason):
        return Condition('unknown', reason=reason)

    def group(raw):
        if not isinstance(raw, dict):
            return unknown('invalid_condition_group')
        if set(raw) - {'conjunction', 'conditions', 'groups'}:
            return unknown('unsupported_condition_group')
        operation = raw.get('conjunction')
        leaves, groups = raw.get('conditions', []), raw.get('groups', [])
        if operation not in ('AND', 'OR') or not isinstance(leaves, list) or not isinstance(groups, list):
            return unknown('unsupported_conjunction')
        children = []
        for leaf in leaves:
            if not isinstance(leaf, dict):
                children.append(unknown('invalid_predicate'))
                continue
            field = leaf.get('field')
            spec = schema.get(field) if isinstance(field, str) else None
            field_item = leaf.get('fieldItem') or {}
            if not spec:
                children.append(unknown(f'unmapped_field:{field}'))
            elif leaf.get('formula_expression') or leaf.get('expression'):
                children.append(unknown(f'unsupported_expression:{field}'))
            elif (not isinstance(field_item, dict) or
                  any(field_item.get(key, field) != field for key in ('key', 'source_key')) or
                  _kind(field_item.get('type', spec.kind)) != spec.kind):
                children.append(unknown(f'field_schema_conflict:{field}'))
            elif leaf.get('storage_key', field) != field or _kind(leaf.get('field_type', spec.kind)) != spec.kind:
                children.append(unknown(f'field_schema_conflict:{field}'))
            elif leaf.get('operator') not in ('Eq', 'Ne'):
                children.append(unknown(f'unsupported_operator:{field}'))
            elif leaf.get('value_list') is not None or not spec.accepts(_operand(spec, leaf.get('originalValue'))):
                children.append(unknown(f'invalid_or_unknown_operand:{field}'))
            else:
                children.append(Condition(leaf['operator'], field, _operand(spec, leaf['originalValue']), spec))
        children.extend(group(child) for child in groups)
        if not children:
            return unknown('empty_condition_group')
        return Condition(operation, children=tuple(children))

    if not isinstance(source, dict):
        return unknown('missing_condition')
    if source.get('formula_expression') or source.get('expression'):
        return unknown('unsupported_expression')
    mode = source.get('usage_mode')
    if mode == 'conditional':
        return group(source.get('condition_group'))
    if mode in ('none', 'custom') and type(source.get('value')) is bool:
        raw = source.get('condition_group') or {}
        if not isinstance(raw, dict) or raw.get('conditions') or raw.get('groups'):
            return unknown('unexpected_literal_conditions')
        return Condition('literal', expected=source['value'])
    return unknown('unsupported_usage_mode')


@dataclass(frozen=True)
class Readiness:
    status: str
    waiting_for: tuple[str, ...] = ()
    unknown: tuple[str, ...] = ()


class Topology:
    def __init__(self, fixture):
        self.template = fixture['template_id']
        self.version = fixture['version']
        nodes = fixture['nodes']
        self.nodes = {node['key']: node for node in nodes}
        if len(self.nodes) != len(nodes):
            raise ValueError('duplicate topology node')
        if any(node.get('start_mode') != 'pre_node_all_done' for node in nodes):
            raise ValueError('unsupported start mode')
        self.predecessors = {key: set() for key in self.nodes}
        self.successors = {key: set() for key in self.nodes}
        for edge in fixture['edges']:
            start, end = edge['start'], edge['end']
            if start not in self.nodes or end not in self.nodes:
                raise ValueError('unknown edge endpoint')
            self.predecessors[end].add(start)
            self.successors[start].add(end)
        pending = {key: len(pred) for key, pred in self.predecessors.items()}
        queue = [key for key, degree in pending.items() if not degree]
        visited = []
        while queue:
            key = queue.pop()
            visited.append(key)
            for child in self.successors[key]:
                pending[child] -= 1
                if not pending[child]:
                    queue.append(child)
        if len(visited) != len(nodes):
            raise ValueError('cyclic source graph requires explicit revision semantics')
        self.order = tuple(visited)
        self.disabled = frozenset(key for key, node in self.nodes.items()
                                  if node.get('disabled') or
                                  (self.template == 334662 and key in ('state_52', 'state_58')))

    def readiness(self, applicability: Mapping[str, bool | None], completed):
        """Project approved applicability and actual completions onto real edges.

        An excluded node contributes its upstream dependencies, not a fabricated
        completion. Missing/invalid applicability always blocks. Visibility and
        pass_mode never authorize exclusion, completion, or financial approval.
        """
        completed = frozenset(completed)
        if (set(applicability) | completed) - self.nodes.keys():
            raise ValueError('state does not belong to this topology')
        results, dependencies = {}, {}
        for key in self.order:
            waiting, unknown = set(), set()
            for predecessor in self.predecessors[key]:
                pred_waiting, pred_unknown = dependencies[predecessor]
                waiting.update(pred_waiting)
                unknown.update(pred_unknown)
            applies = applicability.get(key)
            if key in self.disabled or applies is False:
                results[key] = Readiness('disabled' if key in self.disabled else 'not_applicable')
                dependencies[key] = waiting, unknown
            elif type(applies) is not bool:
                unknown.add(key)
                results[key] = Readiness('blocked', tuple(sorted(waiting)), tuple(sorted(unknown)))
                dependencies[key] = waiting, unknown
            elif key in completed:
                # Historical completion does not erase unresolved upstream facts.
                results[key] = Readiness('completed', tuple(sorted(waiting)), tuple(sorted(unknown)))
                dependencies[key] = waiting, unknown
            else:
                results[key] = Readiness('blocked' if waiting or unknown else 'ready',
                                         tuple(sorted(waiting)), tuple(sorted(unknown)))
                dependencies[key] = waiting | {key}, unknown
        return results
