"""Case and Confirmation Detail read model (VCC-130); pure, unwired, read-only.

The input is a workspace state the caller has already narrowed (identity ->
production_access.require_access -> source_case_policy.filter_visible_cases /
visible_source_snapshot -> existing allowlists -> case_redaction.apply).  This
module never re-widens it: anything absent from the state yields no id, label,
count or "N hidden" hint, including relationship counts and ratios.  A link
whose target is not in the state is reported only as an unresolved edge with a
generic reason, because "forbidden" and "missing" cannot be told apart here.

Edges are native only (confirmation/contract/work-item/task identities that
exist in the state); nothing is joined by name, case number or id suffix.  Both
`build_case_detail` (parent -> child) and `parent_context` (child -> parent)
derive from the single edge list of `_tree`, so they agree by construction.
Edge verification is always ``receipt_missing`` (plan D3: VCC-117 absent).

Gaps left explicit: effective approved deadline is unknown (VCC-123); contract
amounts are withheld (G-AMT); no task -> evidence link exists in the state
unless a file carries a native ``task_id``.
"""
from .case_cutover import admission_fields, execution_allowed
from .data_state import data_state
from .source_entities import entity_id

RECEIPT_MISSING = 'receipt_missing'
SECTIONS = ('overview', 'versions', 'contract_lines', 'work_items', 'workflow_nodes',
            'reports_documents', 'history')
NOT_VISIBLE = 'not_in_authorized_view'
NO_PARENT = 'no_authorized_parent_edge'
NO_TARGET = 'no_authorized_edge_target'
CONTAINMENT = ('case_node', 'node_task')
CARDINALITY_ONE = {'confirmation_contract', 'contract_work_item', 'work_item_task', 'case_confirmation'}


def _text(value):
    if isinstance(value, str):
        return value or None
    if isinstance(value, dict):
        return _text(value.get('text') or value.get('name'))
    if isinstance(value, list):
        parts = [p for p in map(_text, value) if p]
        return '、'.join(parts) or None
    return None


def _ident(task):
    origin = task.get('source_identity') or {}
    if all(isinstance(origin.get(k), str) and origin[k] for k in ('base_token', 'table_id', 'record_id')):
        return entity_id(origin)
    return None


def _task_key(pid, node, task):
    return f"task:{pid}/{node['id']}/{task['id']}"


def _tree(state, pid):
    """Visible nodes and forward edges of one case, or None when the case is absent."""
    project = next((p for p in state.get('projects', []) if p.get('id') == pid), None)
    if project is None:
        return None
    nodes = {f'case:{pid}': {'kind': 'case', 'label': _text(project.get('name'))}}
    edges, tasks_by_ident, task_keys, task_category = [], {}, {}, {}

    def edge(kind, parent, child, contested=False):
        edges.append({'edge_type': kind, 'parent_key': parent, 'child_key': child,
                      'cardinality': 'one' if kind in CARDINALITY_ONE else
                                     'containment' if kind in CONTAINMENT else 'many',
                      'contested': bool(contested), 'verification': RECEIPT_MISSING})

    task_objs = {}
    for node in project.get('nodes', []):
        nkey = f"node:{pid}/{node['id']}"
        nodes[nkey] = {'kind': 'node', 'label': _text(node.get('name'))}
        edge('case_node', f'case:{pid}', nkey)
        for task in node.get('tasks', []):
            key = _task_key(pid, node, task)
            task_keys[(node['id'], task['id'])] = key
            task_objs[(node['id'], task['id'])] = task
            edge('node_task', nkey, key)
            nodes[key] = {'kind': 'task', 'label': _text(task.get('title')), 'node_id': node['id']}
            if _ident(task):
                task_category[_ident(task)] = task.get('category')
                tasks_by_ident.setdefault(_ident(task), []).append(key)
    confirmations = [c for c in state.get('source_confirmations', [])
                     if c.get('project_id') == pid and c.get('source_kind') == 'confirmation']
    contracts = [c for c in state.get('contract_items', []) if c.get('project_id') == pid]
    items = {i['id']: i for i in state.get('source_work_items', []) if i.get('project_id') == pid}
    for c in confirmations:
        nodes[f"confirmation:{c['id']}"] = {'kind': 'confirmation', 'label': _text(c.get('code'))}
        edge('case_confirmation', f'case:{pid}', f"confirmation:{c['id']}")
    shown_conf = {c['id'] for c in confirmations}
    status = (state.get('source_work_items_status') or {}).get(pid)
    imported = state.get('source_work_items_enabled', True) and status is not None
    incomplete = set((status or {}).get('incomplete_contract_ids') or [])
    ct_unresolved = {}
    for ct in contracts:
        ckey = f"contract:{ct['id']}"
        nodes[ckey] = {'kind': 'contract', 'label': _text(ct.get('title')), 'item_number': _text(ct.get('item_number'))}
        multi = len(ct.get('confirmation_ids', [])) > 1 or bool(ct.get('unresolved_confirmation_ids'))
        for cid in ct.get('confirmation_ids', []):
            if cid in shown_conf:
                edge('confirmation_contract', f'confirmation:{cid}', ckey, multi)
        linked = {}  # work-item id -> (label, source_url, contested)
        if imported:
            # authority is per project (import status), never per surviving child: only
            # authorized imported rows may create work-item objects, edges or counts
            for iid, it in items.items():
                if ct['id'] in it.get('contract_ids', []):
                    linked[iid] = (_text(it.get('category')), it.get('source_url'), len(it['contract_ids']) > 1)
            missing = bool(status.get('partial') or status.get('truncated') or ct['id'] in incomplete
                           or any(items[i].get('source_missing') for i in linked)
                           or (not linked and bool(ct.get('reporting_ids') or ct.get('task_refs'))))
        else:
            # legacy rule of case_navigation: task_ref -> task source identity -> reporting_ids
            missing = False
            for ref in ct.get('task_refs', []):
                if ref.get('project_id') != pid:
                    continue
                task = task_objs.get((ref.get('node_id'), ref.get('task_id')))
                ident = _ident(task) if task else None
                if not ident or ident not in ct.get('reporting_ids', []):
                    missing = True
                    continue
                linked[ident] = (_text(task.get('category')) or 'unknown', task.get('source_url'), False)
            missing = missing or bool(set(ct.get('reporting_ids', [])) - linked.keys())
        ct_unresolved[ckey] = bool(missing or ct.get('source_missing') or ct.get('unresolved_confirmation_ids'))
        for iid in sorted(linked):
            label, url, contested = linked[iid]
            nodes.setdefault(f'work_item:{iid}', {'kind': 'work_item', 'label': label, 'source_url': url})
            edge('contract_work_item', ckey, f'work_item:{iid}', contested)
    for iid, it in (items.items() if imported else ()):  # visible item without a visible contract: kept, parent unresolved
        nodes.setdefault(f'work_item:{iid}', {'kind': 'work_item', 'label': _text(it.get('category')),
                                              'source_url': it.get('source_url')})
    for key in [k for k in nodes if k.startswith('work_item:')]:
        iid = key[len('work_item:'):]
        matches = tasks_by_ident.get(iid, [])
        for tkey in matches:
            edge('work_item_task', key, tkey, len(matches) > 1)
    for f in project.get('files', []):
        tkey = task_keys.get((f.get('node_id'), f.get('task_id')))
        if tkey:
            fkey = f"evidence:{f['id']}"
            nodes[fkey] = {'kind': 'evidence', 'label': _text(f.get('name')), 'url': f.get('url')}
            edge('task_evidence', tkey, fkey)
    seen, unique = set(), []
    for e in edges:
        ident = (e['edge_type'], e['parent_key'], e['child_key'])
        if ident not in seen:
            seen.add(ident)
            unique.append(e)
    return {'project': project, 'nodes': nodes, 'edges': unique, 'confirmations': confirmations,
            'contracts': contracts, 'items': items, 'ct_unresolved': ct_unresolved}


def _children(tree, parent_key):
    return [e for e in tree['edges'] if e['parent_key'] == parent_key]


def _parents(tree, child_key):
    return [e for e in tree['edges'] if e['child_key'] == child_key]


def parent_context(state, child_key):
    """Child -> parent over the same edges as the forward tree; absent means unlocated."""
    for project in state.get('projects', []):
        tree = _tree(state, project.get('id'))
        if tree is None or child_key not in tree['nodes']:
            continue
        node = tree['nodes'][child_key]
        parents = [{'edge_type': e['edge_type'], 'parent_key': e['parent_key'],
                    'parent_label': tree['nodes'][e['parent_key']]['label'],
                    'cardinality': e['cardinality'], 'contested': e['contested'],
                    'verification': e['verification']} for e in _parents(tree, child_key)]
        unresolved = []
        if node['kind'] in ('case', 'node'):
            states = []
        elif not [p for p in parents if p['edge_type'] not in CONTAINMENT]:
            states = ['unknown']
            unresolved.append({'child_key': child_key, 'reason': NO_PARENT, 'verification': RECEIPT_MISSING})
        else:
            one = [p for p in parents if p['cardinality'] == 'one']
            contested = any(p['contested'] for p in parents) or len(one) > 1
            states = ['partial'] if contested else []
            for p in parents:
                p['contested'] = p['contested'] or len(one) > 1
        return {'child_key': child_key, 'kind': node['kind'], 'label': node['label'],
                'case_id': project['id'], 'states': states, 'parents': parents, 'unresolved': unresolved}
    return {'child_key': child_key, 'states': data_state('unlocated')['states'], 'reason': NOT_VISIBLE,
            'parents': [], 'unresolved': []}


def _person(state, pid):
    user = next((u for u in state.get('users', []) if u.get('id') == pid), None) if pid else None
    name = _text((user or {}).get('name'))
    return {'name': name} if name else {'name': None, 'states': ['unknown'], 'reason': 'person_not_in_authorized_view'}


def _section(states, rows, *, source_time, reason=None, details=None, stale=False):
    states = [s for s in states]
    freshness = None
    if stale:
        freshness = 'stale'
        if set(states) <= {'partial'}:  # only partial+stale may combine (C-STATE)
            states.append('stale')
    if states:
        states = data_state(*states)['states']  # validates the combination
    return {'states': states, 'freshness': freshness, 'reason': reason, 'source_time': source_time,
            'rows': rows, 'details': details or {}}


def _row(tree, key, **extra):
    node = tree['nodes'][key]
    parents = _parents(tree, key)
    row = {'key': key, 'kind': node['kind'], 'label': node['label'], **extra,
           'parents': [{'edge_type': e['edge_type'], 'parent_key': e['parent_key'],
                        'contested': e['contested'], 'verification': e['verification']} for e in parents]}
    if node['kind'] not in ('case', 'node') and not [e for e in parents if e['edge_type'] not in CONTAINMENT]:
        row['unresolved'] = {'reason': NO_PARENT, 'verification': RECEIPT_MISSING}
    return row


def _unresolved(kind, parent_key, reason=NO_TARGET):
    return {'edge_type': kind, 'parent_key': parent_key, 'child_key': None, 'reason': reason,
            'verification': RECEIPT_MISSING}


def build_case_detail(state, project_id, *, confirmation_key=None, as_of=None, section_status=None):
    """Detail read model for one case; `section_status` lets the caller mark sections stale/failed."""
    tree = _tree(state, project_id)
    if tree is None:
        return {'project_id': project_id, 'page_state': data_state('unlocated')['states'],
                'reason': NOT_VISIBLE, 'explanation': 'Case is not available in this view.',
                'sections': {}, 'header': None}
    project = tree['project']
    overrides = section_status or {}
    last_sync = (state.get('source_status') or {}).get('last_sync')
    source_stale = (state.get('source_status') or {}).get('status') == 'stale' or (state.get('source_status') or {}).get('stale') is True

    versions = [c for c in tree['confirmations']]
    selected = next((c for c in versions if c['id'] == confirmation_key), None)
    selection_reason = None
    if confirmation_key is None:
        if len(versions) == 1:
            selected = versions[0]
        else:
            selection_reason = 'selection_required'
    elif selected is None:
        selection_reason = NOT_VISIBLE
    skey = f"confirmation:{selected['id']}" if selected else None

    visible = lambda kind: [k for k, v in tree['nodes'].items() if v['kind'] == kind]
    contract_keys = [e['child_key'] for e in _children(tree, skey)] if skey else []
    item_keys = sorted({e['child_key'] for ck in contract_keys for e in _children(tree, ck)})
    orphan_items = [k for k in visible('work_item') if not _parents(tree, k)]
    task_keys = sorted({e['child_key'] for ik in item_keys + orphan_items for e in _children(tree, ik)})

    def build(name):
        override = overrides.get(name) or {}
        src_time = {'value': override.get('source_time', last_sync), 'basis': 'source_sync_completed',
                    'fetched_at': as_of}
        if override.get('state') in ('read_failed', 'loading', 'forbidden'):
            return _section([override['state']], [], source_time=src_time, reason=override.get('reason') or override['state'])
        stale = override.get('state') == 'stale' or source_stale
        out = _BUILDERS[name](src_time, stale)
        return out

    def versions_section(src, stale):
        rows = []
        for c in versions:
            key = f"confirmation:{c['id']}"
            rows.append(_row(tree, key, selected=c is selected, code=_text(c.get('code')),
                             source_url=c.get('source_url'), revision=c.get('revision')))
        return _section([] if rows else ['unknown'], rows, source_time=src, stale=stale,
                        reason=None if rows else 'no_authorized_confirmation_version',
                        details={'case_identity': project_id,
                                 'note': 'versions are separate entries of one case; never separate cases'})

    def contract_lines(src, stale):
        if not skey:
            return _section(['unknown'], [], source_time=src, reason=selection_reason, stale=stale)
        rows = []
        for ck in contract_keys:
            row = _row(tree, ck, item_number=tree['nodes'][ck]['item_number'],
                       amount={'state': 'withheld', 'reason': 'G-AMT'},
                       work_item_links='unresolved' if tree['ct_unresolved'].get(ck) else 'located')
            rows.append(row)
        unresolved = [] if rows else [_unresolved('confirmation_contract', skey)]
        return _section(['partial'] if rows else ['unknown'], rows, source_time=src, stale=stale,
                        reason=None if rows else NO_TARGET,
                        details={'unresolved_edges': unresolved})

    def work_items(src, stale):
        if not skey:
            return _section(['unknown'], [], source_time=src, reason=selection_reason, stale=stale)
        keys = sorted(set(item_keys) | set(orphan_items))
        rows = [_row(tree, k, source_url=tree['nodes'][k].get('source_url')) for k in keys]
        status = (state.get('source_work_items_status') or {}).get(project_id)
        partial = status is None or status.get('partial') or status.get('truncated')
        unresolved = [_unresolved('contract_work_item', ck) for ck in contract_keys
                      if not _children(tree, ck) or tree['ct_unresolved'].get(ck)]
        states = ['partial'] if rows and (partial or unresolved or orphan_items) else [] if rows else ['unknown']
        return _section(states, rows, source_time=src, stale=stale,
                        reason=None if rows else NO_TARGET, details={'unresolved_edges': unresolved})

    def workflow_nodes(src, stale):
        rows = []
        for node in project.get('nodes', []):
            tasks = [_row(tree, _task_key(project_id, node, t), status=t.get('status'), task_id=t['id'])
                     for t in node.get('tasks', []) if _task_key(project_id, node, t) in tree['nodes']]
            rows.append(_row(tree, f"node:{project_id}/{node['id']}", node_id=node['id'],
                             status=node.get('status'), tasks=tasks))
        return _section([] if rows else ['unknown'], rows, source_time=src, stale=stale,
                        reason=None if rows else 'no_authorized_nodes',
                        details={'read_only': True, 'note': 'identity and state only; no completion action'})

    def reports(src, stale):
        entry = {'view': 'project', 'project': project_id, 'tab': 'data', 'section': 'files'}
        rows = [_row(tree, k) for k in visible('evidence')]
        return _section(['unknown'] if not rows else ['partial'], rows, source_time=src, stale=stale,
                        reason='no_native_task_evidence_link' if not rows else 'task_evidence_links_incomplete',
                        details={'entry_point': entry,
                                 'unresolved_edges': [_unresolved('task_evidence', k, 'edge_not_located')
                                                      for k in task_keys if not _children(tree, k)]})

    def history(src, stale):
        rows = [{'confirmation_key': f"confirmation:{c['id']}", 'revision': h.get('revision'),
                 'replaced_at': h.get('replaced_at')} for c in versions for h in c.get('history', [])]
        rows += [{'event_id': e.get('id'), 'action': e.get('action'), 'created_at': e.get('created_at')}
                 for e in state.get('events', []) if e.get('project_id') == project_id]
        return _section([] if rows else ['unknown'], rows, source_time=src, stale=stale,
                        reason=None if rows else 'no_authorized_history')

    def overview(src, stale):
        return _section(['partial'], [], source_time=src, stale=stale,
                        reason='header_carries_summary', details={'case_identity': project_id})

    _BUILDERS = {'overview': overview, 'versions': versions_section, 'contract_lines': contract_lines,
                 'work_items': work_items, 'workflow_nodes': workflow_nodes,
                 'reports_documents': reports, 'history': history}
    sections = {}
    for name in SECTIONS:
        try:
            sections[name] = build(name)
        except Exception:  # one failed section must not erase the others; no error text leaks
            sections[name] = _section(['read_failed'], [], source_time={'value': last_sync, 'basis': 'source_sync_completed',
                                      'fetched_at': as_of}, reason='section_build_failed')

    live = [n for n in project.get('nodes', []) if n.get('status') != 'superseded']
    current = [n for n in live if n.get('status') == 'in_progress']
    stage = ({'state': 'verified', 'node_id': current[0]['id'], 'label': _text(current[0].get('name'))}
             if len(current) == 1 else {'state': 'unknown', 'reason': 'no_single_in_progress_node'})
    responsible = _person(state, current[0].get('owner_id')) if len(current) == 1 else \
        {'name': None, 'states': ['unknown'], 'reason': 'current_stage_unverified'}
    all_tasks = [t for n in live for t in n.get('tasks', [])]
    known = all_tasks and all('execution_blockers' in t or 'activation_blockers' in t for t in all_tasks)
    blockers = sorted({b for t in all_tasks for b in (t.get('execution_blockers') or []) + (t.get('activation_blockers') or [])
                       if isinstance(b, str)})[:20]
    pending = []
    for a in state.get('approvals', []):
        if a.get('project_id') == project_id and a.get('status') == 'pending':
            for d in a.get('dates') or []:
                pending.append({'approval_id': a.get('id'), 'requested_due_date': d.get('due_date'),
                                'task_key': next((k for k, v in tree['nodes'].items()
                                                  if v['kind'] == 'task' and k.endswith('/' + str(d.get('task_id')))), None),
                                'status': 'pending'})
    admission = admission_fields(project, execution_allowed(state, project))
    link = (selected or {}).get('source_url') or project.get('source_url')
    header = {
        'project_name': _text(project.get('name')), 'case_number': _text(project.get('code')),
        'selected_confirmation': ({'key': skey, 'code': _text(selected.get('code'))} if selected
                                  else {'key': None, 'reason': selection_reason}),
        'other_versions': [{'key': f"confirmation:{c['id']}", 'code': _text(c.get('code'))}
                           for c in versions if c is not selected],
        'admission': {**admission, 'explanation': admission.get('execution_readonly_reason') or 'admitted'},
        'pm': _person(state, project.get('pm_id')), 'responsible_person': responsible,
        'current_stage': stage,
        'dates': {
            'effective_approved': {'state': 'unknown', 'reason': 'VCC-123 deadline provenance unresolved'},
            'pending_requested': pending, 'estimated': {'state': 'unknown', 'reason': 'no verified source field'}},
        'blockers': {'items': blockers, 'states': [] if known else ['unknown']},
        'source_link': {'url': link, 'basis': 'authorized_source_reference'} if isinstance(link, str) and link
                       else {'url': None, 'states': ['unlocated']},
        'contract_amounts': {'state': 'withheld', 'reason': 'G-AMT'},
        'details': {
            'case_identity': project_id, 'confirmation_identity': (selected or {}).get('id'),
            'relationship_counts': {'basis': 'authorized_view_only; not a population total',
                                    'confirmations': len(versions), 'contracts': len(contract_keys),
                                    'work_items': len(set(item_keys) | set(orphan_items)), 'tasks': len(task_keys)},
            'complete_ids': {'contracts': [k.split(':', 1)[1] for k in contract_keys],
                             'work_items': [k.split(':', 1)[1] for k in item_keys + orphan_items]},
            'edges': tree['edges'],
            'edge_verification': RECEIPT_MISSING},
    }
    return {'project_id': project_id, 'page_state': [], 'header': header, 'sections': sections}
