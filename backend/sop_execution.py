"""Versioned source-node -> execution-unit mapping and topology gates (334662 v137).

Everything here fails closed. A task reference is provenance, never a mapping;
unknown conditions, unmapped nodes and missing decisions block with a named
diagnostic. Nothing in this module completes, skips or approves work, and
`source_execution_verified` stays False: only live-source evidence may enable it.
The company baseline and the meaning of template 566082 are deliberately not
decided here.
"""
from copy import deepcopy
from functools import lru_cache

from .sop_contracts import VERSION, DEFAULTS, DISABLED_NODES, _catalog, applicability, disabled_task
from .sop_runtime import _source_graph
from .sop_topology import FieldSpec, compile_condition

MAPPING_VERSION = 'sop-exec-mapping-20261006.1'
TEMPLATE_ID, SOURCE_VERSION = 334662, 137
SETTING = 'sop_topology_gate'            # ws['settings'][SETTING] == 'enforce' turns gates on
FAN_OUT_SOURCE = 'state_4'
UNRESOLVED_DECISIONS = ('company_baseline_unset', 'template_566082_meaning_unset')
# Option ids whose business meaning has not been decided stay unknown.
UNRESOLVED_OPTIONS = {('field_30fd9d', 'gb2pt_6tb'): 'pure_subcontract_meaning_undecided'}
LEAF_KINDS = {
    'state_2': 'admin_support', 'state_32': 'quote_end', 'state_50': 'client_contact',
    'state_52': 'evaluation_disabled', 'state_58': 'evaluation_disabled',
    'state_65': 'rollback_label_not_edge', 'state_70': 'case_end_candidate', 'state_83': 'first_issue_support',
}


def enforced(ws):
    return (ws or {}).get('settings', {}).get(SETTING) == 'enforce'


@lru_cache(maxsize=1)
def _template():
    template = next(t for t in _catalog()['templates'] if t['id'] == TEMPLATE_ID)
    assert template['version'] == SOURCE_VERSION
    return template


@lru_cache(maxsize=1)
def _schema():
    schema = {}
    for node in _template()['nodes']:
        for key, meta in node.get('resolved_field_metadata', {}).items():
            if meta.get('field_type') == 'radio':
                schema[key] = FieldSpec('radio', frozenset(o['option_id'] for o in meta.get('option', [])))
            elif meta.get('field_type') == 'bool':
                schema[key] = FieldSpec('boolean')
    return schema


@lru_cache(maxsize=1)
def _conditions():
    return {n['state_key']: compile_condition(n['reform_visibility'], _schema()) for n in _template()['nodes']}


@lru_cache(maxsize=1)
def execution_mapping():
    """source node -> execution units, built only from approved contracts."""
    from .policy import TASK_KEYS, SOURCE_NODES
    graph = _source_graph()
    result = {key: {'mapping_version': MAPPING_VERSION, 'template_id': TEMPLATE_ID, 'version': SOURCE_VERSION,
                    'node_key': key, 'units': []} for key in graph.nodes}
    def add(local, task_key, sources):
        for source in sources:
            if source not in result:
                raise ValueError(f'mapping names unknown source node {source}')
            result[source]['units'].append((local, task_key))
    for local, keys in TASK_KEYS.items():
        for task_key in keys:
            add(local, task_key, SOURCE_NODES.get(task_key, []))
    for local, definitions in DEFAULTS.items():
        for key, _title, sources, *_ in definitions:
            add(local, f'approved:{local}:{key}', sources)
    for key, entry in result.items():
        entry['units'] = tuple(sorted(set(entry['units'])))
        entry['status'] = 'disabled' if key in graph.disabled else 'mapped' if entry['units'] else 'unmapped'
    return result


def project_units(project):
    """(local node key, sop_task_key) -> live tasks. Refs-only tasks never count."""
    units = {}
    for node in project.get('nodes', []):
        for task in node.get('tasks', []):
            if task.get('status') == 'superseded' or not task.get('sop_task_key'):
                continue
            units.setdefault((node.get('key'), task['sop_task_key']), []).append((node, task))
    return units


def effective_facts(project):
    """Latest supervisor-confirmed value per source field; append-only history."""
    facts = {}
    for record in project.get('sop_condition_facts', []):
        if (record.get('template_id'), record.get('source_version')) == (TEMPLATE_ID, SOURCE_VERSION):
            facts[record['field']] = record
    return {field: r['value'] for field, r in facts.items() if r.get('value') is not None}


def _facts_for_eval(project, diagnostics):
    facts = effective_facts(project)
    for field, value in list(facts.items()):
        reason = UNRESOLVED_OPTIONS.get((field, value))
        if reason:
            del facts[field]
            diagnostics.setdefault('*', set()).add(f'{reason}:{field}')
    return facts


def source_state(ws, project, mapping=None):
    """Readiness over the real DAG plus per-node diagnostics. Pure; mutates nothing."""
    graph, mapping = _source_graph(), mapping or execution_mapping()
    units, diag = project_units(project), {}
    facts = _facts_for_eval(project, diag)
    applies, completed = {}, set()

    for key in graph.nodes:
        why = diag.setdefault(key, set())
        decision = _conditions()[key].evaluate(facts)
        why.update(decision.reasons)
        value = decision.value
        entry = mapping[key]
        tasks = [pair for unit in entry['units'] for pair in units.get(unit, [])]
        if key in graph.disabled:
            applies[key] = False
            continue
        if value is True and entry['status'] != 'mapped':
            value = None
            why.add(f'unmapped_source_node:{key}')
        if value is True:
            unit_values = [applicability(project, {'applicability': t.get('sop_applicability') or 'always'})
                           for _, t in tasks if not disabled_task(t)]
            if unit_values and all(v is False for v in unit_values):
                value = False
            elif any(v is None for v in unit_values):
                value = None
                why.add(f'unit_applicability_unknown:{key}')
        applies[key] = value
        if value is not True:
            continue
        live = [t for _, t in tasks if applicability(project, {'applicability': t.get('sop_applicability') or 'always'})
                is not False and not disabled_task(t)]
        missing = [u for u in entry['units'] if u not in units]
        if missing:
            why.add(f'unit_task_missing:{key}')
        elif live and all(t.get('status') == 'completed' for t in live):
            if _financial(entry) and not _native_receipt(ws, project, entry):
                why.add(f'native_finance_receipt_required:{key}')
            else:
                completed.add(key)
    return graph.readiness(applies, completed), diag, applies


def _financial(entry):
    from .policy import FINANCIAL
    return any(local in FINANCIAL for local, _ in entry['units'])


def _native_receipt(ws, project, entry):
    """Source auto/single-user flags never stand in for the PM+admin native receipt."""
    from .policy import FINANCIAL
    from .operations import financial_confirmation
    keys = {local for local, _ in entry['units'] if local in FINANCIAL}
    nodes = [n for n in project.get('nodes', []) if n.get('key') in keys]
    return ws is not None and len(nodes) == len(keys) and all(
        financial_confirmation(ws, project, n, require_fresh=False) for n in nodes)


def gate_reasons(ws, project, node, task, mapping=None):
    """Task start/complete reasons from the source DAG. Empty unless enforced."""
    if not enforced(ws) or not task.get('sop_task_key'):
        return []
    mapping = mapping or execution_mapping()
    unit = (node.get('key'), task['sop_task_key'])
    own = {k for k, e in mapping.items() if unit in e['units']}
    if not own:
        return [f'來源節點映射未核定：{unit[0]}/{unit[1]}']
    readiness, diag, applies = source_state(ws, project, mapping)
    active = [k for k in own if applies[k] is not False]
    if not active:
        return [f'來源節點已停用或核定不適用：{",".join(sorted(own))}']
    reasons = []
    for key in sorted(active):
        result = readiness[key]
        blockers = {b for b in (*result.waiting_for, *result.unknown) if b not in own or b == key and b in result.unknown}
        if blockers:
            detail = sorted({d for b in blockers | {key} for d in diag.get(b, ())} | diag.get('*', set()))
            reasons.append(f'來源拓樸尚未就緒 {key}：等待 {",".join(sorted(blockers))}'
                           + (f'（{";".join(detail)}）' if detail else ''))
    return reasons


def node_closure_reasons(ws, project, node):
    """Settlement/pricing may close only with the native receipt; leaves never close a project."""
    if not enforced(ws):
        return []
    if node.get('key') in ('pricing', 'settlement'):
        from .operations import financial_confirmation
        if not financial_confirmation(ws, project, node, require_fresh=False):
            return ['此節點需 PM＋行政原生財務核准回執；來源自動／單人確認旗標不能取代']
    return []


def evaluation_disabled_violations(project):
    """Tasks tied to the disabled assessment nodes (52/58) must stay paused/not required."""
    return [t['id'] for node in project.get('nodes', []) for t in node.get('tasks', [])
            if t.get('status') != 'superseded'
            and any(r.get('template_id') == TEMPLATE_ID and r.get('node_key') in DISABLED_NODES
                    for r in t.get('source_contract_refs') or [])
            and not (t.get('status') == 'paused' and not t.get('required'))]


def leaf_semantics():
    graph = _source_graph()
    leaves = sorted(k for k, s in graph.successors.items() if not s)
    return {k: LEAF_KINDS.get(k, 'unclassified_leaf') for k in leaves}


def engineering_closure(ws, project):
    """A leaf is never engineering completion; closure rides the explicit settlement gate."""
    from .operations import missing
    node = next((n for n in project.get('nodes', []) if n.get('key') == 'settlement'), None)
    if node is None:
        return {'closed': False, 'reasons': ['missing_settlement_node']}
    reasons = ([] if node.get('status') == 'completed' else ['settlement_not_completed'])
    reasons += missing(project, node, ws) if node.get('status') != 'completed' else []
    return {'closed': not reasons and node.get('status') == 'completed', 'reasons': reasons}


# ---- (4) confirmation issue -> state_4 fan-out ----------------------------------------------

def fan_out_targets():
    return tuple(sorted(_source_graph().successors[FAN_OUT_SOURCE]))


def formal_issue(issue):
    """Only a real, non-simulated issuance with a receipt per recipient counts."""
    if issue.get('status') != 'issued' or issue.get('simulated'):
        return False
    receipts = {s.get('key'): s.get('receipt') or {} for s in issue.get('receipts', [])}
    return bool(issue.get('recipients')) and all(
        receipts.get(r, {}).get('message_id') and not receipts[r].get('simulated') for r in issue['recipients'])


def record_fan_out(project, issue):
    """Idempotent per (issue, group node, recipient). Fan-out is notification, not confirmation."""
    if not formal_issue(issue):
        return []
    added, known = [], {e['key'] for e in project.setdefault('sop_fan_out', [])}
    groups = issue.get('recipient_groups') or {}
    receipts = {s.get('key'): s.get('receipt') or {} for s in issue.get('receipts', [])}
    for recipient in issue['recipients']:
        for node in groups.get(recipient, []):
            if node not in fan_out_targets():
                continue
            key = f'{issue["id"]}:{node}:{recipient}'
            if key in known:
                continue
            entry = {'key': key, 'issue_id': issue['id'], 'version': issue['version'], 'source_node': FAN_OUT_SOURCE,
                     'group_node': node, 'recipient': recipient, 'status': 'notified',
                     'message_id': receipts[recipient]['message_id']}
            project['sop_fan_out'].append(entry)
            added.append(entry)
    return added


def group_confirmations(project, issue):
    """Each group is confirmed by its own recipients; none completes another."""
    acked = {a['user_id'] for a in issue.get('acknowledgments', [])}
    groups = {}
    for recipient, nodes in (issue.get('recipient_groups') or {}).items():
        for node in nodes:
            groups.setdefault(node, set()).add(recipient)
    state = {node: ('confirmed' if members <= acked else 'pending') for node, members in groups.items()}
    for node in fan_out_targets():
        state.setdefault(node, 'no_recipient_mapped')
    return state


# ---- (5) approval-scoped rounds -------------------------------------------------------------

ROUND_KINDS = ('change', 'extension')


def open_round(ws, project, approval, actor, *, receipt_ok=None, mapping=None):
    """Open a new round for the tasks an approved native approval names; idempotent."""
    from .workflow import require, now, uid, impacted
    from .native_requests import kind_of, receipt_valid
    from .operations import invalidate
    rounds = project.setdefault('sop_rounds', [])
    existing = next((r for r in rounds if r['approval_id'] == approval['id']), None)
    if existing:
        return existing
    require(kind_of(approval) in ROUND_KINDS and approval.get('project_id') == project['id'],
            '只有本案已核定的變更／展延審批可開新輪次', 409)
    node = next((n for n in project['nodes'] if n['id'] == approval.get('node_id')), None)
    ok = (receipt_ok or (lambda: receipt_valid(ws, project, node, approval, require_fresh=False)))()
    require(approval.get('status') in ('approved', 'applied') and ok, '需有效的原生核准回執才能開新輪次', 409)
    targets = impacted(project, approval)
    require(bool(targets), '核准範圍沒有對應任務', 409)
    number = len(rounds) + 1
    previous, touched = {}, {}
    for n, t in targets:
        previous[t['id']] = {'status': t['status'], 'owner_id': t.get('owner_id'), 'output': t.get('output'),
                             'completed_at': t.get('completed_at'), 'node_id': n['id'], 'node_status': n['status']}
        t.setdefault('round_history', []).append({'round': number, 'before': deepcopy(previous[t['id']])})
        if t['status'] == 'completed':
            t.update(status='rework', completed_at=None)
        t['sop_round'] = number
        touched[n['id']] = n
    for n in touched.values():
        invalidate(n, f'核准新輪次 {number}')   # marks cycles invalidated; votes stay in the list
    mapping = mapping or execution_mapping()
    units = {(n['key'], t.get('sop_task_key')) for n, t in targets}
    record = {'id': uid(), 'round': number, 'approval_id': approval['id'], 'kind': kind_of(approval),
              'task_ids': sorted(previous), 'node_ids': sorted(touched),
              'source_nodes': sorted(k for k, e in mapping.items() if units & set(e['units'])),
              'previous': previous, 'opened_by': actor['id'], 'opened_at': now()}
    rounds.append(record)
    return record


# ---- (2) runtime condition decisions --------------------------------------------------------

def condition_fields():
    """Source fields a supervisor may supply: only those that gate node visibility."""
    return {k: v for k, v in _schema().items() if any(k in repr(n['reform_visibility']) for n in _template()['nodes'])}


def apply_round(ws, user, body):
    from .workflow import require, find, event
    from .case_cutover import require_execution
    p = find(ws['projects'], body.get('project_id'), '案件')
    require_execution(ws, p)
    approval = find(ws['approvals'], (body.get('payload') or {}).get('approval_id'), '申請')
    require(user['id'] in (p.get('pm_id'), p.get('supervisor_id')), '需案件 PM 或指定主管', 403)
    record = open_round(ws, p, approval, user)
    event(ws, user, body['action'], p['id'], message=f'核准後新輪次 {record["round"]}；僅失效受影響範圍，前輪紀錄保留')
    return True


def apply_condition(ws, user, body):
    """PM proposes a typed field fact; the project's supervisor (a different person) confirms."""
    from .workflow import require, find, now, uid, event
    from .case_cutover import require_execution
    from .workflow_rules import assignable
    p = find(ws['projects'], body.get('project_id'), '案件')
    require_execution(ws, p)
    require(assignable(ws, user), '操作人員須為已核實在職人員', 403)
    data = body.get('payload') or {}
    if body['action'] == 'sop_condition_propose':
        require(user['id'] == p.get('pm_id'), '需案件 PM 提出條件事實', 403)
        field, value, evidence = data.get('field'), data.get('value'), data.get('evidence')
        spec = condition_fields().get(field)
        require(spec is not None and spec.accepts(value), '條件欄位或值不在來源契約內', 422)
        require((field, value) not in UNRESOLVED_OPTIONS, '此選項的業務意義尚未核定，不能作為決定輸入', 422)
        require(isinstance(evidence, str) and 0 < len(evidence.strip()) <= 2000, '需填寫佐證說明（最多 2000 字）', 422)
        supervisor = p.get('supervisor_id')
        require(supervisor and supervisor != user['id'] and any(u['id'] == supervisor and assignable(ws, u) for u in ws['users']),
                '尚未指派有效且不同於 PM 的主管', 409)
        require(field not in effective_facts(p), '已有核定的條件事實；變更須另走核定變更流程', 409)
        require(not any(r['field'] == field and r['status'] == 'pending' for r in p.get('sop_condition_proposals', [])),
                '已有待確認提案', 409)
        p.setdefault('sop_condition_proposals', []).append(dict(
            id=uid(), field=field, value=value, evidence=evidence.strip(), proposed_by=user['id'], proposed_at=now(),
            supervisor_id=supervisor, status='pending', template_id=TEMPLATE_ID, source_version=SOURCE_VERSION,
            mapping_version=MAPPING_VERSION))
    else:
        record = next((r for r in p.get('sop_condition_proposals', []) if r['id'] == data.get('proposal_id')), None)
        require(record and record['status'] == 'pending', '提案已變更或已處理', 409)
        require(user['id'] == record['supervisor_id'] == p.get('supervisor_id') and user['id'] != record['proposed_by'],
                '需不同於提案人的指定主管確認', 403)
        require(data.get('result') in ('approved', 'returned'), '確認結果錯誤', 422)
        if data['result'] == 'returned':
            record.update(status='returned', returned_by=user['id'], returned_at=now())
        else:
            record.update(status='approved', approved_by=user['id'], approved_at=now())
            p.setdefault('sop_condition_facts', []).append(dict(
                id=uid(), field=record['field'], value=record['value'], proposal_id=record['id'],
                decided_by=user['id'], proposed_by=record['proposed_by'], evidence=record['evidence'],
                decided_at=now(), template_id=TEMPLATE_ID, source_version=SOURCE_VERSION,
                mapping_version=MAPPING_VERSION))
    event(ws, user, body['action'], p['id'], message='PM 提出／主管確認來源條件事實；未完成或跳過任何工作')
    return True


def summary(project, ws=None, *, details=False):
    """Small, secret-free projection for the cockpit; no verification claim."""
    mapping = execution_mapping()
    status = [e['status'] for e in mapping.values()]
    result = {'mapping_version': MAPPING_VERSION, 'mapped_node_count': status.count('mapped'),
              'unmapped_node_count': status.count('unmapped'), 'gate_enforced': enforced(ws),
              'unresolved_decisions': list(UNRESOLVED_DECISIONS), 'source_execution_verified': False}
    if details:
        readiness, diag, _ = source_state(ws, project)
        result['nodes'] = {k: {'status': readiness[k].status, 'blocked_by': sorted({*readiness[k].waiting_for, *readiness[k].unknown}),
                               'diagnostics': sorted(diag.get(k, ())), 'mapping': mapping[k]['status']} for k in sorted(readiness)}
        result['leaves'] = leaf_semantics()
        result['fan_out_targets'] = list(fan_out_targets())
    return result
