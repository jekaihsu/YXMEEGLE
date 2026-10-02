"""Response-only privacy projection; authoritative storage remains intact."""
from copy import deepcopy


def public_person(person, *, include_authority=False):
    fields = {'id','name','role','department','avatar','active','directory_status',
              'directory_missing','can_mention','default_workspace'}
    if include_authority:
        fields |= {'capabilities','authz_version'}
    result = {key: deepcopy(value) for key, value in person.items() if key in fields}
    if include_authority:
        from .business_policy import can_business_override
        result['can_business_override'] = can_business_override(person)
    return result


def public_source_cache(cache, user=None):
    """Only documented business fields leave the server, including for managers.

    Source readers keep original fields for matching/hashing. This response copy
    is not suitable as an authoritative sync input.
    """
    from .sources import FIELDS, REVIEW_FIELDS
    result = {key: deepcopy(value) for key, value in cache.items()
              if key in {'configured','last_sync','status','message','tables','records'}}
    result['tables'] = [{k: deepcopy(v) for k,v in row.items()
                         if k in {'name','kind','table_id','count','status','pages_read','page_limit','record_limit'}}
                        for row in cache.get('tables', [])]
    records = []
    for row in cache.get('records', []):
        kind = row.get('kind')
        allowed = set(FIELDS.get(kind, []))
        if kind in ('daily','cost'):
            # Dates and names are represented by the normalized daily report;
            # payroll/allowance identity formulas never enter public raw fields.
            allowed = {'日期','工作日期','出工日期','工作日期-營業額明細','營業額組別-明細',
                       '組別','內業組別','所屬組別','案件編號','工程編號','案號','所屬案件',
                       '工作內容','工項說明','本明細適用工項','備註','營業額點數','最終營業額點數'} | set(REVIEW_FIELDS)
        public = {k: deepcopy(v) for k,v in row.items() if k in ('record_id','table_id','kind','department')}
        public['fields'] = {k: _public_field_value(v) for k,v in row.get('fields', {}).items() if k in allowed}
        records.append(public)
    result['records'] = records
    return result


def _public_field_value(value):
    if isinstance(value, list):
        return [_public_field_value(item) for item in value]
    if isinstance(value, dict):
        # Lark person/formula objects can carry email or personnel metadata.
        return {key: _public_field_value(item) for key,item in value.items()
                if key in {'text','name','type','value','record_ids','link_record_ids'}}
    return deepcopy(value)


def public_copy(value):
    """Do not copy migration snapshots into responses, including nested archives."""
    if isinstance(value, dict):
        return {key: public_copy(item) for key, item in value.items() if key != 'migration_archive'}
    if isinstance(value, list):
        return [public_copy(item) for item in value]
    return deepcopy(value)


def filter_private_workspace(state, user):
    """Apply the existing leave-view policy after authoritative policy calculations.

    Use the current workspace profile, never stale role/capability claims supplied
    by a caller. Unknown or disabled actors receive no leave approval records.
    """
    actor = next((person for person in state.get('users', [])
                  if user and person.get('id') == user.get('id') and person.get('active', True)), None)
    ident = actor.get('id') if actor else None
    from .production_access import admitted
    expected_app=state.get('people_directory_status',{}).get('app_id') or (actor or {}).get('identity_app_id')
    simulated=state.get('environment') in ('demo','test')
    for person in state.get('users',[]):
        person['can_mention']=bool(person.get('active',True) and (simulated or admitted(person,expected_app)))
    may_manage = bool(actor and (actor.get('role') == 'manager'
                                or 'manage_handover' in actor.get('capabilities', [])))
    # Compute against the complete authority state, before hiding unrelated leave
    # records. The known project avoids scanning all tasks for every task.
    from .workflow import is_owner, now
    state['task_capabilities_checked_at'] = now()
    for project in state.get('projects', []):
        for node in project.get('nodes', []):
            for task in node.get('tasks', []):
                task['can_execute'] = bool(actor and is_owner(actor, task, state, project=project))
                from .workflow_rules import confirmation_hash, activation_reasons
                task['confirmation_hash'] = confirmation_hash(project, node, task)
                task['activation_blockers'] = activation_reasons(state, project, node, task)
        # Operational source provenance remains server-side for reconciliation.
        # Browser pages use normalized business fields and explicit source URLs.
        _strip_source_payloads(project)
    _strip_source_payloads(state.get('approvals', []))
    for collection in ('daily_reviews','source_quotes','source_confirmations','contract_items'):
        _strip_source_payloads(state.get(collection,[]))
    state['approved_leave_delegations'] = [item for item in state.get('approved_leave_delegations', [])
        if actor and (may_manage or ident in (item.get('principal_id'), item.get('delegate_id')))]
    if not may_manage:
        state['delegations'] = [item for item in state.get('delegations', [])
            if ident in (item.get('principal_id'), item.get('delegate_id'))]
        state['handover_requests'] = [item for item in state.get('handover_requests', [])
            if ident in (item.get('principal_id'), item.get('delegate_id'), item.get('requested_by'))]
    if not actor or actor.get('role')!='manager':
        state.pop('source_case_review',None)
    # Background snapshots and source payloads are operational, not public case
    # data. A manager gets metadata through the same projection, never secrets.
    for job in state.get('jobs', []):
        for key in ('snapshot','payload','policy','authorization','remote_response','request'):
            job.pop(key, None)
    for key in ('capability_bindings','capability_awards','training_plans','learning_mappings'):
        state.pop(key, None)
    state.pop('_mention_reservations', None)
    for person in state.get('users', []):
        safe = public_person(person, include_authority=person.get('id') == ident)
        person.clear()
        person.update(safe)
    return state


def _strip_source_payloads(value):
    if isinstance(value, dict):
        for key in ('source_fields','source_records','raw_fields','_business_authority'):
            value.pop(key, None)
        # Quote snapshots carry an unbounded copy of source fields as `fields`.
        if 'fields' in value and isinstance(value['fields'],dict):
            value['fields'] = public_source_cache({'records':[{'kind':'quote','fields':value['fields']} ]})['records'][0]['fields']
        for key in ('title','name','body','description'):
            if key in value and value[key] is not None and not isinstance(value[key],str):
                value[key] = '資料格式異常，請聯絡管理員核對'
                value['display_data_needs_review'] = True
        for item in value.values():
            _strip_source_payloads(item)
    elif isinstance(value, list):
        for item in value:
            _strip_source_payloads(item)
