"""VCC-132 pure, unwired detail over an already authorized workspace.

Caller must narrow through identity/require_access, source_case_policy, existing
field allowlists and case_redaction before calling. No raw snapshot is read.
Absent objects are absent: dangling IDs never become rows or hidden counts.
Native navigation is usable but all mapping receipts remain receipt_missing.
"""
from copy import deepcopy

from .data_state import data_state
from .source_identity import SourceRef, is_source_key
from .sources import source_id


def _pick(row, keys):
    return {key: deepcopy(row[key]) for key in keys if key in row}


def _section(rows, *, reason=None, failed=False):
    # A visible subset does not prove a complete authorized population.
    return {'read_state': data_state('read_failed' if failed else 'partial' if rows else 'unlocated'),
            'rows': rows, **({'reason': reason} if reason else {})}


def _unknown(reason):
    return {'state': 'unknown', 'value': None, 'reason': reason}


def _origin(task):
    try:
        return SourceRef.from_entity(task.get('source_identity') or {}).source_key
    except (ValueError, TypeError, AttributeError):
        return None


def _parents(state, item):
    rows = []
    # Both directions are existing native projections, never display joins.
    for contract in state.get('contract_items', []):
        if not (contract['id'] in item.get('contract_ids', [])
                or item['id'] in contract.get('reporting_ids', [])):
            continue
        parent = _pick(contract, ('id', 'title', 'item_number', 'source_missing'))
        parent['verification'] = 'receipt_missing'
        parent['confirmations'] = [dict(_pick(c, ('id', 'code', 'source_missing')),
                                        verification='receipt_missing')
                                   for c in state.get('source_confirmations', [])
                                   if c['id'] in contract.get('confirmation_ids', [])]
        if not parent['confirmations'] and (not contract.get('confirmation_ids')
                                            or contract.get('unresolved_confirmation_ids')):
            parent['unresolved'] = {'reason': 'native_confirmation_edge_unresolved'}
        rows.append(parent)
    reason = None
    if not rows and not item.get('contract_ids'):
        reason = 'native_parent_edge_absent'
    # A dangling target could have been forbidden: never report its identity,
    # count or a missing-target hint. Explicit missing flags on visible rows
    # are the only evidence of a missing source.
    if item.get('source_missing'):
        reason = 'visible_work_item_source_missing'
    section = _section(rows, reason=reason)
    if reason:
        section['unresolved'] = [{'reason': reason}]
    return section


def _nodes(state, item):
    rows = []
    for project in state.get('projects', []):
        if project['id'] != item.get('project_id'):
            continue
        for node in project.get('nodes', []):
            for task in node.get('tasks', []):
                if _origin(task) != item['id']:
                    continue
                # sop_execution.open_round retains IDs and appends round_history.
                # This compound identity distinguishes read instances; it is not
                # a newly issued workflow ID or a verified source-node mapping.
                identity = {'project_id': project['id'], 'node_id': node['id'],
                            'task_id': task['id'], 'sop_round': task.get('sop_round')}
                row = {'instance_identity': identity,
                       'node': _pick(node, ('id', 'key', 'name', 'status', 'completed_at')),
                       'task': _pick(task, ('id', 'title', 'status', 'completed_at', 'input', 'output',
                                           'required', 'sop_task_key', 'sop_definition_version')),
                       'verification': 'receipt_missing', 'history': []}
                for history in task.get('round_history', []):
                    before = history.get('before') or {}
                    row['history'].append({'instance_identity': {
                        'project_id': project['id'], 'node_id': node['id'], 'task_id': task['id'],
                        'before_opened_round': history['round']}, 'opened_round': history['round'],
                                           'before': _pick(before, ('status', 'output', 'completed_at', 'node_status'))})
                owner = next((u for u in state.get('users', []) if u.get('id') == task.get('owner_id')), None)
                if owner:
                    row['responsible_person'] = _pick(owner, ('id', 'name'))
                # Unknown remote results keep the original job identity. Read
                # only already-visible jobs with an explicit matching task link.
                row['operations'] = [_pick(job, ('id', 'status')) for job in state.get('jobs', [])
                                     if job.get('status') == 'outcome_unknown'
                                     and (job.get('payload') or {}).get('project_id') == project['id']
                                     and (job.get('payload') or {}).get('node_id') == node['id']
                                     and (job.get('payload') or {}).get('task_id') == task['id']]
                rows.append(row)
    return _section(rows)


def _evidence(state, item, nodes):
    rows = []
    node_ids = {r['node']['id'] for r in nodes['rows']}
    for project in state.get('projects', []):
        if project['id'] != item.get('project_id'):
            continue
        for file in project.get('files', []):
            if file.get('node_id') in node_ids:
                rows.append(dict(_pick(file, ('id', 'name', 'created_at', 'direction', 'version')),
                                 kind='attachment', relation_scope='node', evidence_only=True))
    base, table, record = item['id'].split('/')
    native_id = source_id({'base_token': base, 'table_id': table, 'record_id': record})
    for attachment in state.get('source_attachment_index', []):
        if (attachment.get('source_record_id') == native_id
                and attachment.get('base_token') == base and attachment.get('table_id') == table):
            rows.append(dict(_pick(attachment, ('id', 'name', 'status')),
                             kind='attachment', relation_scope='work_item', evidence_only=True))
    return _section(rows, reason='evidence_is_not_workflow_completion')


def build_work_item_detail(state, work_item_key, *, as_of=None):
    """Return whitelisted sections, isolating read failures without any writes.

    Missing selection returns only an unknown state (no key, count, label).
    Quantities, dates and source update time lack proven fields in the minimal
    source_work_items projection; they stay unknown even if callers add values.
    ``as_of`` is read context only, never source freshness or a calculation date.
    """
    item = next((row for row in state.get('source_work_items', [])
                 if row.get('id') == work_item_key), None)
    if item is None or not is_source_key(work_item_key):
        return {'read_state': data_state('unknown')}
    base, table, record = work_item_key.split('/')
    result = {'read_state': data_state('partial'), 'as_of': as_of,
              'header': {'id': item['id'], 'name': _unknown('work_item_name_unlocated'),
                         'category': deepcopy(item.get('category')),
                         'source_identity': {'base_token': base, 'table_id': table, 'record_id': record},
                         'execution_state': _unknown('no_work_item_execution_state')},
              'work_content': {'read_state': data_state('unknown'),
                               'quantity': _unknown('quantity_field_unlocated'),
                               'unit': _unknown('unit_field_unlocated'),
                               'amounts': {'state': 'withheld', 'reason': 'G-AMT approval absent'}},
              'plan_actual': {'read_state': data_state('unlocated'), 'available': False,
                              'reason': 'Calculation contract not approved; same item, unit and period required'},
              'work_orders': {'read_state': data_state('unlocated'), 'rows': [],
                              'verification': 'receipt_missing',
                              'reason': 'G-RCODE: R01/R02/R09/R10 work-order models unverified',
                              'source_health_link': {'view': 'sources'}},
              'side': {'read_state': data_state('unknown'),
                       'effective_due': _unknown('VCC-123 formal deadline provenance unresolved'),
                       'pending_due': _unknown('requested_date_field_unlocated'),
                       'estimated_due': _unknown('estimated_date_field_unlocated'),
                       'source_updated_at': _unknown('source_updated_time_unlocated')}}
    # Case association proves no work-item daily-report edge or population.
    # Navigation only: no rows or count, including in the state envelope.
    result['case_daily_reports'] = {
        'read_state': {'states': ['unlocated']},
        'reason': 'work-item daily-report edge unverified'}
    if any(project.get('id') == item.get('project_id') for project in state.get('projects', [])):
        # Existing project daily tab: frontend/src/ProjectDetail.tsx:60,81;
        # DailyRecords queries GET /api/daily-reports (backend/app.py:520-521).
        result['case_daily_reports']['link'] = {
            'view': 'project', 'project_id': item['project_id'], 'tab': 'daily'}
    for name, build in (('parents', lambda: _parents(state, item)),
                        ('nodes', lambda: _nodes(state, item))):
        try:
            result[name] = build()
        except (KeyError, TypeError, ValueError, AttributeError):
            result[name] = _section([], failed=True, reason='section_read_failed')
    try:
        result['deliverables'] = _evidence(state, item, result['nodes'])
    except (KeyError, TypeError, ValueError, AttributeError):
        result['deliverables'] = _section([], failed=True, reason='section_read_failed')
    tasks = [r['task'] for r in result['nodes']['rows']]
    if tasks:
        result['header']['name'] = {'state': 'existing', 'values': [t.get('title') for t in tasks]}
        result['header']['execution_state'] = {'state': 'existing', 'tasks': [
            _pick(t, ('id', 'status', 'completed_at')) for t in tasks]}
    result['side']['responsible_people'] = [r['responsible_person'] for r in result['nodes']['rows']
                                          if 'responsible_person' in r]
    result['side']['missing_edge_warnings'] = [section['reason'] for section in (result['parents'],)
                                             if section.get('reason')]
    return result
