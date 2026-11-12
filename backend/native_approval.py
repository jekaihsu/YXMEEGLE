"""Native approval boundary; no route enables submission merely by importing this.

The caller owns durable attempt checkpoints, current actor/scope authorization,
and business apply gates. This module never votes or changes project state.
"""
from copy import deepcopy
import hashlib
import json
import re
from urllib.parse import quote
from uuid import uuid4

from .lark_adapter import RemoteFailure,NativeRequestRejected


class InvalidApprovalProof(RemoteFailure):
    """A checked payload mismatch, distinct from unavailable remote evidence."""


def creation_not_performed(binding):
    if not isinstance(binding,dict):return False
    rejection=binding.get('creation_rejection');payload=binding.get('payload')
    if not isinstance(rejection,dict) or not isinstance(payload,dict):return False
    code=rejection.get('api_code');uuid=rejection.get('uuid')
    return (binding.get('creation_outcome')=='not_created' and
            binding.get('not_created_proof')=='documented_api_rejection' and
            type(rejection.get('http_status')) is int and rejection['http_status']==400 and
            type(code) is int and code in (1390001,1390015,1390013) and
            isinstance(uuid,str) and bool(uuid) and uuid==payload.get('uuid'))


def remote_binding_resolved(item):
    binding=item.get('native_binding') or {}
    if not binding.get('attempted'):return True
    immutable={k:binding.get(k) for k in ('identity','kind','definition_hash','mapping','approvers','payload')}
    if digest(immutable)!=binding.get('binding_hash'):return False
    if creation_not_performed(binding):return True
    proof=item.get('remote_resolution') or {}
    if (proof.get('binding_hash')==binding['binding_hash'] and proof.get('verified_at')
            and proof.get('instance_code')==binding.get('instance_code')
            and str(proof.get('status','')).lower()==binding.get('status')
            and proof.get('status') in ('APPROVED','REJECTED','CANCELED','DELETED')):return True
    receipt=binding.get('receipt') or {}
    return bool(not binding.get('verification_failed_at') and receipt.get('binding_verified') is True
                and receipt.get('verified_at') and receipt.get('instance_code')==binding.get('instance_code')
                and receipt.get('external_status') in ('APPROVED','REJECTED','CANCELED','DELETED'))


def abandoned_not_created(item):
    """Withdrawn request whose binding is intact and provably never created remotely."""
    binding=item.get('native_binding') or {}
    if item.get('status')!='withdrawn' or item.get('frozen') or not binding.get('attempted'):return False
    immutable={k:binding.get(k) for k in ('identity','kind','definition_hash','mapping','approvers','payload')}
    return digest(immutable)==binding.get('binding_hash') and creation_not_performed(binding)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def require(value, message):
    if not value:
        raise InvalidApprovalProof(message, 'blocked')


def form_items(raw):
    try:
        items = json.loads(raw) if isinstance(raw, str) else deepcopy(raw)
    except (TypeError, ValueError) as exc:
        raise RemoteFailure('審批表單格式無法核對', 'blocked') from exc
    require(isinstance(items, list) and bool(items), '審批表單缺少內容')
    require(all(isinstance(x, dict) and isinstance(x.get('id'), str) and x['id']
                for x in items), '審批表單欄位識別不完整')
    require(len({x['id'] for x in items}) == len(items), '審批表單欄位識別重複')
    return {x['id']: x for x in items}


def verify_definition(definition, mapping):
    """Validate actual GET shape against explicit, operator-reviewed mapping.

    mapping fields: logical-name -> {id,name,type}; nodes: [{id,seats:[...]}].
    IDs always come from actual definition GET, never inferred from labels.
    """
    require(definition.get('status') == 'ACTIVE', '審批單尚未啟用')
    require(mapping.get('approval_code') and mapping.get('kind') in
            ('financial', 'change', 'extension', 'node_skip'), '審批單對應尚未設定')
    fields = mapping.get('fields', {})
    require(isinstance(fields, dict) and {'binding', 'content'} <= fields.keys(),
            '審批單缺少案件版本與內容對應')
    actual = form_items(definition.get('form'))
    require(len({f.get('id') for f in fields.values()}) == len(fields), '欄位對應重複')
    require(set(actual) == {f.get('id') for f in fields.values()}, '審批單欄位已變更')
    for f in fields.values():
        a = actual[f['id']]
        require(f.get('type') in ('input', 'textarea') and
                (a.get('type'), a.get('name')) == (f['type'], f.get('name')),
                '審批單欄位型別或名稱已變更')
    nodes = definition.get('node_list', [])
    require(isinstance(nodes, list) and all(isinstance(n, dict) and n.get('node_id')
                                           for n in nodes), '審批流程不完整')
    require(len({n['node_id'] for n in nodes}) == len(nodes), '審批節點識別重複')
    # UI-created definitions expose hashed Submit/End IDs without START/END
    # custom IDs. Bind those exact reviewed IDs; never discard arbitrary
    # need_approver=false nodes (which can be fixed-person approvals).
    boundaries=mapping.get('boundary_nodes',{})
    if boundaries:
        require(isinstance(boundaries,dict) and set(boundaries)=={'start','end'},'審批起終節點對應不完整')
        require(len({b.get('id') for b in boundaries.values()})==2,'審批起終節點識別重複')
        for role,name in (('start','Submit'),('end','End')):
            boundary=boundaries[role]
            actual_boundary=next((n for n in nodes if n['node_id']==boundary.get('id')),None)
            require(actual_boundary is not None and boundary.get('name')==name and
                    actual_boundary.get('name')==name and actual_boundary.get('need_approver') is False and
                    actual_boundary.get('node_type')=='AND' and not actual_boundary.get('custom_node_id') and
                    actual_boundary.get('empty_assignee_list')==[] and
                    actual_boundary.get('require_signature') is False,
                    '審批起終節點已變更，須重新核對管理後台')
    boundary_ids={b['id'] for b in boundaries.values()}
    actual_nodes = {n['node_id']: n for n in nodes
                    if n['node_id'] not in boundary_ids}
    expected_nodes = mapping.get('nodes', [])
    require(bool(expected_nodes) and len({n['id'] for n in expected_nodes}) == len(expected_nodes)
            and set(actual_nodes) == {n['id'] for n in expected_nodes}, '審批流程已變更')
    seats = []
    for n in expected_nodes:
        a = actual_nodes[n['id']]
        require(a.get('node_type') == 'AND' and a.get('need_approver') is True,
                '審批流程須由指定人員共同核准')
        require(n.get('seats') and (len(n['seats']) == 1 or a.get('approver_chosen_multi') is True),
                '審批流程不支援所需核准人數')
        seats.extend(n['seats'])
    require(len(set(seats)) == len(seats), '核准席次重複')
    if mapping['kind'] == 'node_skip':
        require(set(seats) == {'pm', 'supervisor'}, '跳過須 PM 與該組主管共同核准')
    if mapping['kind'] == 'financial':
        require(set(seats) == {'pm','admin'}, '財務交付確認須 PM 與行政共同核准')
    if mapping['kind'] == 'change':
        require(set(seats)=={'pm','supervisor'},
                '設計變更的 Lark 內審須 PM 與該組主管共同核准；業主確認另以佐證登錄')
    return digest(definition)


def prepare_binding(*, mapping, definition, context, applicant, approvers, content,
                    field_values=None):
    definition_hash = verify_definition(definition, mapping)
    required = ('app_id', 'tenant', 'workspace_id', 'project_id', 'request_id', 'version', 'scope_hash')
    require(all(context.get(k) is not None and str(context[k]) for k in required), '案件版本識別不完整')
    require(context['workspace_id'] == 'lark-' + context['tenant'], '審批限正確公司正式工作區')
    require(re.fullmatch(r'ou_[A-Za-z0-9]+', applicant or ''), '申請人帳號尚未核實')
    seats = [s for n in mapping['nodes'] for s in n['seats']]
    require(set(approvers) == set(seats) and all(re.fullmatch(r'ou_[A-Za-z0-9]+', x or '')
                                              for x in approvers.values()), '核准人帳號尚未核實')
    require(len(set(approvers.values())) == len(approvers), '共同核准須由不同人員執行')
    identity = {k: deepcopy(context[k]) for k in required}
    binding_value = json.dumps(dict(identity, kind=mapping['kind']), ensure_ascii=False,
                               sort_keys=True, separators=(',', ':'))
    values = dict(field_values or {}, binding=binding_value,
                  content=json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
    require(set(values) == set(mapping['fields']) and all(isinstance(v, str) and v for v in values.values()),
            '審批內容尚未填妥')
    form = [{'id': f['id'], 'type': f['type'], 'value': values[key]}
            for key, f in mapping['fields'].items()]
    payload = {'approval_code': mapping['approval_code'], 'open_id': applicant,
               'form': json.dumps(form, ensure_ascii=False, separators=(',', ':')),
               'uuid': str(uuid4()), 'allow_resubmit': False, 'allow_submit_again': False,
               'node_approver_open_id_list': [{'key': n['id'], 'value': [approvers[s] for s in n['seats']]}
                                              for n in mapping['nodes']]}
    immutable = {'identity': identity, 'kind': mapping['kind'], 'definition_hash': definition_hash,
                 'mapping': deepcopy(mapping), 'approvers': deepcopy(approvers), 'payload': payload}
    return dict(immutable, binding_hash=digest(immutable), attempted=False, status='prepared')


def check_binding(binding, context, definition):
    immutable = {k: binding[k] for k in ('identity', 'kind', 'definition_hash', 'mapping', 'approvers', 'payload')}
    require(digest(immutable) == binding.get('binding_hash'), '審批綁定內容已改變')
    require(binding['identity'] == {k: context.get(k) for k in binding['identity']}, '案件或責任範圍已改版，請重新送審')
    require(verify_definition(definition, binding['mapping']) == binding['definition_hash'],
            '審批單已改版，請重新核對')


def verify_instance(binding, instance):
    """Remote proof only. Caller must still check current scope and apply policy."""
    payload = binding['payload']
    require(instance.get('approval_code') == payload['approval_code'] and
            str(instance.get('uuid', '')).lower() == payload['uuid'].lower() and
            instance.get('open_id') == payload['open_id'] and instance.get('instance_code'),
            'Lark 審批與本次申請不符')
    if binding.get('instance_code'):
        require(instance['instance_code'] == binding['instance_code'], 'Lark 審批識別已改變')
    expected, actual = form_items(payload['form']), form_items(instance.get('form'))
    require(set(expected) == set(actual) and all(
        (actual[k].get('type'), actual[k].get('value')) == (v['type'], v['value'])
        for k, v in expected.items()), 'Lark 審批內容與送審版本不符')
    state = instance.get('status')
    require(state in ('PENDING', 'APPROVED', 'REJECTED', 'CANCELED', 'DELETED'), '審批結果尚無法核實')
    receipt = {'instance_code': instance['instance_code'], 'external_status': state,
               'binding_verified': True, 'approved': False, 'simulated': False}
    if state != 'APPROVED' or instance.get('reverted') is True:
        return receipt
    tasks, timeline = instance.get('task_list'), instance.get('timeline')
    require(isinstance(tasks, list) and isinstance(timeline, list), '缺少實際核准紀錄')
    forbidden = {'AUTO_PASS', 'AUTO_REJECT', 'REMOVE_REPEAT', 'TRANSFER', 'ADD_APPROVER_BEFORE',
                 'ADD_APPROVER', 'ADD_APPROVER_AFTER', 'DELETE_APPROVER', 'ROLLBACK_SELECTED', 'ROLLBACK',
                 'CANCEL', 'DELETE'}
    require(not any(t.get('type') in forbidden for t in timeline), '審批流程曾變更，須重新核對')
    expected_votes = {(n['id'], binding['approvers'][s]) for n in binding['mapping']['nodes'] for s in n['seats']}
    require(len(tasks) == len(expected_votes), '核准人數與原定流程不符')
    seen = set()
    task_ids = set()
    for task in tasks:
        pair = (task.get('node_id'), task.get('open_id'))
        require(pair in expected_votes and pair not in seen and task.get('id') and
                task['id'] not in task_ids and task.get('type') == 'AND' and
                task.get('status') == 'APPROVED', '未取得每位指定人員的實際核准')
        require(any(t.get('type') == 'PASS' and t.get('task_id') == task['id'] and
                    t.get('open_id') == task['open_id'] for t in timeline), '缺少本人核准動態')
        seen.add(pair)
        task_ids.add(task['id'])
    require(seen == expected_votes, '尚缺共同核准')
    return dict(receipt, approved=True, approval_task_ids=sorted(task_ids))


def observe_original_instance(binding,instance):
    """Identity/form-bound terminal observation without accepting vote proof."""
    state=instance.get('status')
    require(state in ('PENDING','APPROVED','REJECTED','CANCELED','DELETED'),'原審批狀態無法核實')
    receipt=verify_instance(binding,dict(instance,status='PENDING'))
    return dict(receipt,external_status=state,approved=False,applicable=False,observation_only=True)


class NativeApprovalAdapter:
    """Injected LarkAdapter + server authorization callback on every HTTP boundary."""
    def __init__(self, adapter, authorize):
        self.adapter, self.authorize = adapter, authorize

    def _request(self, method, path, **kwargs):
        self.authorize()
        return self.adapter.request(method, path, **kwargs)

    def definition(self, code):
        return self._request('GET', '/approval/v4/approvals/' + quote(code, safe=''),
                             params={'user_id_type': 'open_id'})

    def poll(self, binding, context):
        check_binding(binding, context, self.definition(binding['payload']['approval_code']))
        instance = self._request('GET', '/approval/v4/instances/' + quote(binding['payload']['uuid'], safe=''),
                                 params={'user_id_type': 'open_id'})
        return verify_instance(binding, instance)

    def observe_original(self,binding):
        immutable={k:binding.get(k) for k in ('identity','kind','definition_hash','mapping','approvers','payload')}
        require(digest(immutable)==binding.get('binding_hash'),'原送審識別已變更')
        instance=self._request('GET','/approval/v4/instances/'+quote(binding['payload']['uuid'],safe=''),params={'user_id_type':'open_id'})
        # Original-instance observation is not approval proof for a new scope.
        return observe_original_instance(binding,instance)

    def submit(self, binding, context, checkpoint):
        """checkpoint(next_binding) MUST commit before returning; failures abort I/O.

        Persist attempted even if transport outcome is unknown. Recovery never POSTs
        an already attempted version; it only queries the immutable UUID.
        """
        check_binding(binding, context, self.definition(binding['payload']['approval_code']))
        if binding.get('attempted') and not creation_not_performed(binding):
            return self.poll(binding, context)
        attempt = dict(deepcopy(binding), attempted=True, status='outcome_unknown')
        attempt.pop('creation_rejection',None);attempt.pop('not_created_proof',None)
        attempt['creation_outcome']='unknown'
        checkpoint(attempt)
        # Keep this in-process object safe as well as the caller's durable checkpoint.
        binding.update(attempt)
        try:
            data = self._request('POST', '/approval/v4/instances', json=deepcopy(binding['payload']))
            require(data.get('instance_code'), 'Lark 未回傳審批識別，結果待核對')
        except NativeRequestRejected as exc:
            if exc.operation!='create':raise
            from .workflow import now
            rejected=dict(deepcopy(binding),status='not_created',creation_outcome='not_created',
                not_created_proof='documented_api_rejection',creation_rejection={
                    'http_status':exc.http_status,'api_code':exc.api_code,'uuid':binding['payload']['uuid'],'verified_at':now()})
            rejected.setdefault('rejection_history',[]).append(dict(rejected['creation_rejection'],operation='create'))
            checkpoint(rejected);binding.update(rejected)
            raise
        except RemoteFailure:
            # Includes duplicate UUID and uncertain transport results. Never blind retry.
            return self.poll(binding, context)
        receipt = self.poll(binding, context)
        require(receipt['instance_code'] == data['instance_code'], '送審回執與查回結果不符')
        return receipt

    def cancel(self,binding,context,checkpoint):
        immutable={k:binding[k] for k in ('identity','kind','definition_hash','mapping','approvers','payload')}
        require(digest(immutable)==binding['binding_hash'] and binding['identity']==context,'原申請綁定不符，不能撤回')
        def read_original():
            return verify_instance(binding,self._request('GET','/approval/v4/instances/'+quote(binding['payload']['uuid'],safe=''),params={'user_id_type':'open_id'}))
        receipt=read_original()
        if binding.get('cancel_attempted') or receipt['external_status'] in ('CANCELED','DELETED','APPROVED','REJECTED'):
            return receipt
        if receipt['external_status']!='PENDING':
            raise RemoteFailure('此 Lark 審批已非審批中，不能撤回','blocked')
        attempt=dict(deepcopy(binding),cancel_attempted=True,status='cancel_outcome_unknown')
        attempt.pop('cancel_rejection',None)
        checkpoint(attempt);binding.update(attempt)
        try:
            self._request('POST','/approval/v4/instances/cancel',params={'user_id_type':'open_id'},
                json={'approval_code':binding['payload']['approval_code'],
                      'instance_code':receipt['instance_code'],'user_id':binding['payload']['open_id']})
        except NativeRequestRejected as exc:
            if exc.operation!='cancel':raise
            from .workflow import now
            rejected=dict(deepcopy(binding),cancel_attempted=False,status='cancel_rejected',
                cancel_rejection={'http_status':exc.http_status,'api_code':exc.api_code,'verified_at':now()})
            rejected.setdefault('rejection_history',[]).append(dict(rejected['cancel_rejection'],operation='cancel',uuid=binding['payload']['uuid']))
            checkpoint(rejected);binding.update(rejected)
            raise
        except RemoteFailure:
            return read_original()
        return read_original()


class NativeApprovalService:
    """Company API/worker service; durable storage remains owned by the caller.

    authorize() MUST read fresh server state and return the current context dict.
    checkpoint(binding) MUST atomically commit the request version and job state.
    A receipt is evidence, never permission to skip business delivery/finance gates.
    """
    def __init__(self,cfg,adapter_factory=None):
        from .lark_adapter import application_adapter
        self.cfg=cfg
        self.adapter_factory=adapter_factory or application_adapter

    def mapping(self,kind):
        require(kind in ('financial','change','extension','node_skip'),'此類工作依原 SOP 處理，不建立重大審批')
        try: mappings=json.loads(self.cfg.get('LARK_NATIVE_APPROVAL_MAPPINGS_JSON','{}'))
        except (TypeError,ValueError) as exc: raise RemoteFailure('專用審批設定尚未完成','blocked') from exc
        mapping=mappings.get(kind) if isinstance(mappings,dict) else None
        require(isinstance(mapping,dict) and mapping.get('kind')==kind,'尚未核對本類專用審批單')
        return deepcopy(mapping)

    def _check(self,context,authorize):
        require(self.cfg.get('LARK_WORKER_IDENTITY')=='application','公司審批連線尚未設定')
        require(context.get('app_id')==self.cfg.get('LARK_APP_ID') and
                context.get('tenant')==self.cfg.get('LARK_WORKER_ORGANIZATION') and
                context.get('workspace_id')=='lark-'+self.cfg.get('LARK_WORKER_ORGANIZATION',''),
                '審批僅限已核定公司正式工作區')
        require(context['tenant'] in {x.strip() for x in self.cfg.get('LARK_ALLOWED_TENANTS','').split(',') if x.strip()},'公司不在核定名單')
        live=authorize()
        require(isinstance(live,dict) and all(live.get(k)==v for k,v in context.items()),
                '案件、責任人或權限已變更，請重新核對')

    def prepare(self,*,kind,context,applicant,approvers,content,authorize,field_values=None):
        self._check(context,authorize)
        adapter=self.adapter_factory(deepcopy(self.cfg))
        try:
            native=NativeApprovalAdapter(adapter,lambda:self._check(context,authorize))
            mapping=self.mapping(kind)
            definition=native.definition(mapping['approval_code'])
            self._check(context,authorize)
            return prepare_binding(mapping=mapping,definition=definition,context=context,
                                   applicant=applicant,approvers=approvers,content=content,field_values=field_values)
        finally: adapter.client.close()

    def _run(self,binding,context,checkpoint,authorize,submit):
        from .workflow import now
        self._check(context,authorize)
        if submit not in ('cancel','observe'):require(self.mapping(binding['kind'])==binding['mapping'],'審批設定已變更，請重新核對')
        adapter=self.adapter_factory(deepcopy(self.cfg))
        def save(value):
            self._check(context,authorize)
            checkpoint(deepcopy(value))
        try:
            native=NativeApprovalAdapter(adapter,lambda:self._check(context,authorize))
            try:
                receipt=native.observe_original(binding) if submit=='observe' else native.cancel(binding,context,save) if submit=='cancel' else native.submit(binding,context,save) if submit else native.poll(binding,context)
            except RemoteFailure as exc:
                failed=dict(deepcopy(binding),verification_failed_at=now(),verification_error=str(exc))
                if isinstance(exc,InvalidApprovalProof):
                    failed.update(status='verification_failed',receipt={'approved':False,'binding_verified':False,
                        'simulated':False,'external_status':'UNVERIFIED','instance_code':binding.get('instance_code'),
                        'verified_at':None})
                save(failed)
                binding.update(failed)
                raise
            self._check(context,authorize)
            updated=dict(deepcopy(binding),instance_code=receipt['instance_code'],
                         status=receipt['external_status'].lower(),receipt=dict(receipt,verified_at=now()))
            updated.pop('verification_failed_at',None);updated.pop('verification_error',None)
            save(updated)
            binding.update(updated)
            return deepcopy(updated['receipt'])
        finally: adapter.client.close()

    def submit(self,binding,context,checkpoint,authorize):
        if not binding.get('attempted') or creation_not_performed(binding):
            if str(self.cfg.get('LARK_NATIVE_APPROVAL_SUBMIT_ENABLED','false')).lower()!='true':
                raise RemoteFailure('正式審批送出尚未啟用；既有申請仍可查回','blocked')
            if str(self.cfg.get('DEMO_MODE','false')).lower()=='true':
                raise RemoteFailure('展示服務不可新送正式審批，請使用正式服務','blocked')
        return self._run(binding,context,checkpoint,authorize,True)

    def poll(self,binding,context,checkpoint,authorize):
        return self._run(binding,context,checkpoint,authorize,False)

    def cancel(self,binding,context,checkpoint,authorize):
        require(binding.get('attempted'),'尚未送出的草稿不需要遠端撤回')
        return self._run(binding,context,checkpoint,authorize,'cancel')

    def observe(self,binding,context,checkpoint,authorize):
        require(binding.get('attempted'),'沒有已送出的原申請')
        return self._run(binding,context,checkpoint,authorize,'observe')
