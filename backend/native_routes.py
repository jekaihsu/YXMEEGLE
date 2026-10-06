"""Real native approval transport. Ordinary local SOP reviews are unaffected."""
from copy import deepcopy
from fastapi import Request,HTTPException
from .workflow import require,find,now,uid,event,is_pm
from .native_approval import NativeApprovalService,creation_not_performed
from .native_requests import actors,context,native_business_status
from .lark_adapter import RemoteFailure


def register(app,identity,load,persist,sessions,W,cfg):
    service=NativeApprovalService(cfg)
    app.state.native_approval_service=service

    def get_state(wid):
        with sessions() as db:
            row=db.get(W,wid);require(row is not None,'工作區不存在',404)
            return load(db,row)

    def formal(request):
        data,user=identity(request)
        require(data.get('mode')=='lark' and data['wid']=='lark-'+cfg.get('LARK_WORKER_ORGANIZATION',''),
                '正式 Lark 審批僅限公司正式工作區',403)
        return data,user

    @app.post('/api/native-approvals/definitions/verify')
    async def verify_definitions(request:Request):
        """Read definitions only; independent of any case, instance or submit flag."""
        import json
        from urllib.parse import quote
        from .native_approval import verify_definition, digest
        from .approval_capabilities import DEFINITION_KINDS
        from .production_access import require_access

        data,user=formal(request);body=await request.json()
        require(isinstance(body,dict) and set(body)=={'version'} and type(body.get('version')) is int,
                '請提供目前工作區版本',422)
        policy_keys=('LARK_APP_ID','LARK_WORKER_ORGANIZATION','LARK_WORKER_IDENTITY',
                     'LARK_ALLOWED_TENANTS','LARK_NATIVE_APPROVAL_MAPPINGS_JSON')
        policy={key:deepcopy(cfg.get(key)) for key in policy_keys}

        def authorize(state=None):
            fresh_data,fresh_user=formal(request)
            require(fresh_data['wid']==data['wid'] and fresh_user['id']==user['id'],
                    '定義查核操作者已變更',403)
            require({key:cfg.get(key) for key in policy_keys}==policy,'審批連線或對應已變更，請重新查核',409)
            require(cfg.get('LARK_APP_ID') and cfg.get('LARK_WORKER_IDENTITY')=='application'
                    and cfg.get('LARK_WORKER_ORGANIZATION') in
                    {x.strip() for x in cfg.get('LARK_ALLOWED_TENANTS','').split(',') if x.strip()},
                    '公司審批唯讀連線尚未設定',403)
            current=state if state is not None else get_state(data['wid'])
            require(current.get('environment')=='production','定義查核限公司正式工作區',403)
            actor=find(current['users'],user['id'],'操作者')
            require(actor.get('role')=='manager' and not actor.get('manager_revoked'),
                    '需公司管理員核對審批定義',403)
            require_access(actor,cfg.get('LARK_APP_ID'),cfg=cfg,tenant=cfg.get('LARK_WORKER_ORGANIZATION'))
            return actor

        state=get_state(data['wid']);authorize(state)
        require(state['version']==body['version'],'資料已更新，請重新整理',409)
        try:mappings=json.loads(cfg.get('LARK_NATIVE_APPROVAL_MAPPINGS_JSON','{}'))
        except (ValueError,TypeError):mappings={}
        if not isinstance(mappings,dict):mappings={}
        evidence={'schema_version':1,'app_id':cfg['LARK_APP_ID'],
                  'tenant':cfg['LARK_WORKER_ORGANIZATION'],'workspace_id':data['wid'],
                  'mapping_set_hash':digest(mappings),'checked_by':user['id'],'by_type':{}}
        adapter=None
        try:
            for kind in DEFINITION_KINDS:
                authorize()
                proof={'status':'unverified','checked_at':now()}
                try:
                    mapping=service.mapping(kind)
                    require(isinstance(mapping.get('approval_code'),str) and mapping['approval_code'],
                            '缺少審批定義識別',422)
                    proof['mapping_hash']=digest(mapping)
                    if adapter is None:adapter=service.adapter_factory(deepcopy(cfg))
                    authorize()
                    definition=adapter.request('GET','/approval/v4/approvals/'+quote(mapping['approval_code'],safe=''),
                                               params={'user_id_type':'open_id'})
                    authorize()
                    definition_hash=verify_definition(definition,mapping)
                    proof.update(status='verified',definition_hash=definition_hash,verified_at=now())
                except (RemoteFailure,KeyError,TypeError,ValueError,AttributeError):
                    # No remote body or token is included in public health data.
                    # A failed new check replaces old success instead of reviving it.
                    authorize()
                    proof.update(status='unverified',reason='definition_read_or_mapping_verification_failed')
                evidence['by_type'][kind]=proof
            evidence['checked_at']=now()
            def save(current):
                actor=authorize(current)
                current['native_definition_verification']=deepcopy(evidence)
                event(current,actor,'native_definitions_verify',message='唯讀核對審批定義與映射；未建立或送出審批')
            return persist(data['wid'],body['version'],save,actor_id=user['id'],action_name='native_definitions_verify')
        finally:
            if adapter is not None:adapter.client.close()

    def locate(state,kind,request_id):
        collection={'node_skip':'node_skip_requests','financial':'financial_requests',
                    'change':'approvals','extension':'approvals'}.get(kind)
        require(collection,'此類工作依原 SOP 確認',422)
        item=find(state.get(collection,[]),request_id,'審批申請')
        require(kind in ('node_skip','financial') or item.get('type')==kind,'申請類別不符',409)
        p=find(state['projects'],item['project_id'],'案件')
        n=find(p['nodes'],item['node_id'],'節點') if item.get('node_id') else None
        return p,n,item

    def permitted(user,p,item):
        require(user.get('active',True) and (user['id']==item.get('created_by') or is_pm(user,p)),
                '只有申請人或案件 PM／主管可送出及查回',403)
        require(not item.get('simulated'),'模擬申請不能送入公司正式審批',409)
        require(item.get('status') not in ('withdrawn','rejected','invalidated','executed'),
                '此申請已結束或失效，請建立新版本',409)
        require(not p.get('archived_at') and not p.get('migrated_to'),'案件已封存',409)
        require(item.get('project_revision',p['revision'])==p['revision'],'案件已改版，請建立新的申請',409)

    def check_financial_evidence(p,item):
        if item.get('type')!='financial': return
        require(item.get('source_finance')==p.get('source_finance',{}),'來源財務資料已更新，請重新建立確認申請',409)
        for ident in item.get('evidence_ids',[]):
            evidence=next((e for e in p.get('evidence',[]) if e['id']==ident),None)
            if evidence:
                require(not evidence.get('withdrawn') and evidence.get('status')=='accepted',
                        '財務交付證明尚未確認或已撤下',409)
                ident=evidence.get('file_id')
                if not ident: continue
            document=find(p.get('files',[]),ident,'交付文件')
            require(not document.get('withdrawn'),'交付文件已撤下',409)
            require(document.get('storage')!='local' or document.get('remote_status')=='verified',
                    '交付文件尚未核實存入公司 Lark',409)

    @app.post('/api/change-approvals/{request_id}/confirm-line')
    async def confirm_change_line(request_id:str,request:Request):
        from .native_requests import change_evidence,scope_hash,receipt_valid
        from .native_approval import digest
        from .production_access import business_admitted
        data,user=formal(request);body=await request.json()
        def confirm(state):
            p,n,item=locate(state,'change',request_id)
            from .case_cutover import require_execution
            require_execution(state,p)
            require(item['status'] in ('pending','approved') and item.get('native_binding',{}).get('attempted'),
                    '請先送出正式變更，再登錄本版本確認',409)
            require(item.get('project_revision')==p['revision'] and not p.get('archived_at') and not p.get('migrated_to'),
                    '變更範圍已失效',409)
            actor=find(state['users'],user['id'],'操作者');app_id=cfg.get('LARK_APP_ID')
            require(business_admitted(actor,app_id,state.get('native_approval_authority',{})),'確認人尚未核實在職身分',403)
            supervisor=(n or {}).get('supervisor_id') or p.get('supervisor_id')
            party=body.get('party');require(party in ('supervisor','client'),'確認線別錯誤',422)
            require(actor['id']==supervisor if party=='supervisor' else actor['id'] in (p.get('pm_id'),supervisor),
                    '主管須本人確認；業主佐證由案件 PM 或指定主管登錄',403)
            reason=str(body.get('reason') or '').strip();require(reason,'請填寫確認說明',422)
            current_scope=scope_hash(state,p,n,item)
            require(item['native_binding']['identity']['scope_hash']==current_scope,'送審範圍已改變，請重新申請',409)
            proof={'scope_hash':current_scope,'recorded_by':actor['id'],'recorded_at':now(),'reason':reason}
            if party=='client':
                evidence_ids=body.get('evidence_ids')
                snapshot=change_evidence(p,evidence_ids)
                proof.update(evidence_ids=list(dict.fromkeys(evidence_ids)),evidence_hash=digest(snapshot),
                             basis='external_client_evidence')
            else:proof['basis']='supervisor_personal_confirmation'
            state['native_approval_authority']={'app_id':app_id,'tenant':cfg.get('LARK_WORKER_ORGANIZATION')}
            item.setdefault('change_confirmations',{})[party]=proof
            item['owner_confirmed']=bool(item['change_confirmations'].get('supervisor'))
            item['client_confirmed']=bool(item['change_confirmations'].get('client'))
            item['status']=native_business_status(state,p,n,item,receipt_valid(state,p,n,item))
            item.setdefault('history',[]).append({'action':'change_confirm_'+party,'actor_id':actor['id'],
                'created_at':now(),'message':reason,'scope_hash':current_scope,'simulated':False})
            event(state,actor,'change_confirm_'+party,p['id'],n['id'] if n else None,
                  message='主管本人確認變更' if party=='supervisor' else '登錄業主確認佐證（非代業主審批）')
        return persist(data['wid'],body.get('version'),confirm,actor_id=user['id'],action_name='change_confirm_line')

    @app.post('/api/native-approvals/financial/request')
    async def financial_request(request:Request):
        data,user=formal(request); body=await request.json()
        require(not any(k in body for k in ('amount','contract_amount','paid','received','balance')),
                '此處僅送交財務證明，不能更改帳務金額',422)
        def create(state):
            p=find(state['projects'],body.get('project_id'),'案件')
            from .case_cutover import require_execution
            require_execution(state,p)
            n=find(p['nodes'],body.get('node_id'),'節點')
            from .policy import FINANCIAL
            require(n['key'] in FINANCIAL,'重大財務確認請選擇計價或結案節點',422)
            actor=find(state['users'],user['id'],'操作者')
            require(is_pm(actor,p) or actor['id'] in (p.get('admin_id'),n.get('owner_id')),'沒有提交財務交付證明的權限',403)
            reason=str(body.get('reason') or '').strip();kind=body.get('confirmation_kind')
            require(reason and kind in ('contract','payment','settlement'),'請填寫原因及證明類型',422)
            payables=body.get('payables_declaration','unknown')
            require(payables in ('unknown','no_payables','all_settled'),'下包支出確認方式不合法',422)
            evidence_ids=body.get('evidence_ids')
            require(isinstance(evidence_ids,list) and evidence_ids and all(isinstance(x,str) for x in evidence_ids),
                    '請選擇本案交付證明',422)
            known={e['id'] for e in p.get('evidence',[])+p.get('files',[])
                   if e.get('node_id') in (None,n['id'])}
            require(set(evidence_ids)<=known,'交付證明不存在或不屬於此節點',409)
            item={'id':uid(),'type':'financial','project_id':p['id'],'node_id':n['id'],
                  'confirmation_kind':kind,'evidence_ids':list(dict.fromkeys(evidence_ids)),
                  'payables_declaration':payables,
                  'reason':reason,'status':'draft','version':1,'project_revision':p['revision'],
                  'source_finance':deepcopy(p.get('source_finance',{})),
                  'created_by':actor['id'],'created_at':now(),'simulated':False,'history':[]}
            state.setdefault('financial_requests',[]).append(item)
            event(state,actor,'financial_confirmation_draft',p['id'],n['id'],message='建立財務交付證明草稿；未更改帳務')
        return persist(data['wid'],body.get('version'),create,actor_id=user['id'],action_name='financial_confirmation_draft')

    @app.post('/api/native-approvals/{kind}/{request_id}/{operation}')
    async def operate(kind:str,request_id:str,operation:str,request:Request):
        require(operation in ('prepare','submit','poll','cancel','abandon'),'未知審批操作',422)
        data,user=formal(request);body=await request.json();state=get_state(data['wid'])
        pv=body.get('project_version')
        require(type(pv) is int,'缺少案件版本',422)
        pid=locate(state,kind,request_id)[0]['id']
        require(find(state['projects'],pid).get('concurrency_version',0)==pv,'此案件已被更新，請核對最新內容後重試',409)
        if operation=='abandon':
            _,_,item=locate(state,kind,request_id)
            original=deepcopy(item.get('native_binding') or {})
            require(original.get('payload',{}).get('open_id')==user['id'],'只能由原申請人結束確定未建立的申請',403)
            require(creation_not_performed(original),'尚未證實 Lark 拒絕建立；請查回原審批',409)
            def abandon(s):
                _,_,target=locate(s,kind,request_id)
                require(target.get('native_binding')==original and creation_not_performed(original),'原申請已變更',409)
                require(target.get('status') not in ('executed','applied'),'已套用不可結束',409)
                target.update(status='withdrawn',lark_status='not_created',remote_resolution_required=False)
                target.setdefault('history',[]).append({'action':'native_abandon_uncreated','actor_id':user['id'],
                    'created_at':now(),'message':'依 Lark 明確拒建回執結束本地申請；未向 Lark 撤回','simulated':False})
                event(s,user,'native_abandon_uncreated',target['project_id'],target.get('node_id'),message='依明確拒建回執結束申請')
            return persist(data['wid'],None,abandon,actor_id=user['id'],action_name='native_abandon_uncreated',project_versions={pid:pv})
        if operation=='cancel':
            p,n,item=locate(state,kind,request_id)
            binding=deepcopy(item.get('native_binding') or {})
            require(binding.get('attempted') and binding.get('payload',{}).get('open_id')==user['id'],
                    '只能由原申請人撤回已送出的 Lark 審批',403)
            require(item.get('status') not in ('executed','applied'),'已套用結果不能直接撤回',409)
            original_identity=deepcopy(binding['identity']);expected=deepcopy(binding);response=[None]
            def authorize_cancel():
                fresh_data,fresh_user=formal(request)
                require(fresh_data['wid']==data['wid'] and fresh_user['id']==binding['payload']['open_id'],'撤回人身分已變更',403)
                _,_,current=locate(get_state(data['wid']),kind,request_id)
                require(current.get('native_binding',{}).get('binding_hash')==binding['binding_hash'] and current.get('status') not in ('executed','applied'),'原申請已變更或已套用',409)
                return deepcopy(original_identity)
            def save_cancel(value):
                nonlocal expected
                latest=get_state(data['wid'])
                def save(s):
                    _,_,target=locate(s,kind,request_id)
                    require(target.get('native_binding')==expected,'審批已被更新，請重新讀取',409)
                    require(target.get('status') not in ('executed','applied'),'已套用結果不可撤回',409)
                    target['native_binding']=deepcopy(value)
                    target['cancel_requested']=bool(value.get('cancel_attempted'))
                    receipt=value.get('receipt') or {}
                    if receipt.get('external_status') in ('CANCELED','DELETED'):
                        target['remote_resolution_required']=False
                        target.update(status='withdrawn',lark_status='canceled',native_receipt=dict(deepcopy(receipt),binding_hash=value['binding_hash'],scope_hash=original_identity['scope_hash']))
                    event(s,user,'native_cancel',target['project_id'],target.get('node_id'),message='已核實 Lark 撤回' if target.get('status')=='withdrawn' else '撤回結果待 Lark 查回')
                response[0]=persist(data['wid'],None,save,actor_id=user['id'],action_name='native_cancel',project_versions={pid:find(latest['projects'],pid).get('concurrency_version',0)})
                expected=deepcopy(value)
            try:service.cancel(binding,original_identity,save_cancel,authorize_cancel)
            except RemoteFailure as exc:raise HTTPException(503,str(exc)) from exc
            return response[0]
        p,n,item=locate(state,kind,request_id)
        if operation=='poll' and item.get('native_binding',{}).get('attempted'):
            original=deepcopy(item['native_binding']);observe=False
            try:
                permitted(user,p,item)
                observe=context(state,p,n,item,cfg.get('LARK_APP_ID'),cfg.get('LARK_WORKER_ORGANIZATION'))!=original['identity']
                observe=observe or service.mapping(kind)!=original['mapping'] or actors(state,p,n,item,original['mapping'],cfg.get('LARK_APP_ID'))!=original['approvers']
            except (HTTPException,RemoteFailure):observe=True
            if observe:
                expected=deepcopy(original);response=[None]
                def authorize_original():
                    fd,fu=formal(request)
                    require(fd['wid']==data['wid'] and fu['id']==user['id'],'登入身分已變更',403)
                    fp,_,current=locate(get_state(data['wid']),kind,request_id)
                    require(not current.get('simulated') and (fu['id']==original['payload']['open_id'] or is_pm(fu,fp)),
                            '只有原申請人或案件 PM 可查回原審批',403)
                    require(current.get('native_binding',{}).get('binding_hash')==original['binding_hash'],'原審批版本已變更',409)
                    return deepcopy(original['identity'])
                def save_original(value):
                    nonlocal expected
                    latest=get_state(data['wid'])
                    def save(s):
                        _,_,target=locate(s,kind,request_id)
                        require(target.get('native_binding')==expected,'原審批查回版本衝突',409)
                        target['native_binding']=deepcopy(value)
                        receipt=value.get('receipt') or {}
                        if receipt.get('binding_verified') and not value.get('verification_failed_at'):
                            terminal=receipt.get('external_status') in ('APPROVED','REJECTED','CANCELED','DELETED')
                            target['native_receipt']=dict(deepcopy(receipt),approved=False,applicable=False,
                                binding_hash=original['binding_hash'],scope_hash=original['identity']['scope_hash'])
                            target['lark_status']=receipt['external_status'].lower()
                            target['remote_resolution_required']=not terminal
                            if terminal:target['remote_resolution']={'status':receipt['external_status'],'instance_code':receipt['instance_code'],
                                'verified_at':receipt['verified_at'],'binding_hash':original['binding_hash']}
                            else:target.pop('remote_resolution',None)
                            if target.get('status') not in ('executed','applied'):
                                target['status']={'REJECTED':'rejected','CANCELED':'withdrawn','DELETED':'withdrawn'}.get(receipt['external_status'],'invalidated')
                        event(s,user,'native_original_observed',target['project_id'],target.get('node_id'),
                              message='查回已失效範圍的原審批；結果不套用目前案件')
                    response[0]=persist(data['wid'],None,save,actor_id=user['id'],action_name='native_original_observed',project_versions={pid:find(latest['projects'],pid).get('concurrency_version',0)})
                    expected=deepcopy(value)
                try:service.observe(original,original['identity'],save_original,authorize_original)
                except RemoteFailure as exc:raise HTTPException(503,str(exc)) from exc
                return response[0]
        permitted(user,p,item)
        scope_version=item.get('approval_scope_version',1 if item.get('native_binding') else 3)
        from .case_cutover import require_execution
        if operation in ('prepare','submit'):require_execution(state,p)
        tenant=cfg.get('LARK_WORKER_ORGANIZATION'); app_id=cfg.get('LARK_APP_ID')
        ctx=context(state,p,n,item,app_id,tenant)
        try: mapping=service.mapping(kind)
        except RemoteFailure as exc: raise HTTPException(503,str(exc)) from exc
        check_financial_evidence(p,item)
        approvers=actors(state,p,n,item,mapping,app_id)
        expected_binding=deepcopy(item.get('native_binding'));result=[None]

        def authorize():
            fresh_data,fresh_user=formal(request)
            require(fresh_data['wid']==data['wid'] and fresh_user['id']==user['id'],'登入身分已變更',403)
            fresh=get_state(data['wid']);fp,fn,fi=locate(fresh,kind,request_id)
            permitted(fresh_user,fp,fi)
            if operation in ('prepare','submit'):require_execution(fresh,fp)
            check_financial_evidence(fp,fi)
            require(actors(fresh,fp,fn,fi,mapping,app_id)==approvers,'核准人已變更，請重新建立申請',409)
            return context(fresh,fp,fn,fi,app_id,tenant)

        def checkpoint(binding):
            nonlocal expected_binding
            fresh=get_state(data['wid'])
            def save(state):
                fp,fn,fi=locate(state,kind,request_id);actor=find(state['users'],user['id'])
                permitted(actor,fp,fi)
                require(context(state,fp,fn,fi,app_id,tenant)==ctx,'送審範圍已變更',409)
                require(fi.get('native_binding')==expected_binding,'另一次送審已處理本申請，請重新讀取',409)
                fi['approval_scope_version']=scope_version
                state['native_approval_authority']={'app_id':app_id,'tenant':tenant}
                if binding.get('attempted') and not (expected_binding or {}).get('attempted'):
                    require_execution(state,fp)
                    from .workflow import freeze_change
                    freeze_change(state,fp,fi,actor)
                    fi['lark_status']='outcome_unknown'
                fi['native_binding']=deepcopy(binding)
                if creation_not_performed(binding):
                    fi['lark_status']='not_created'
                    fi['remote_resolution_required']=False
                receipt=binding.get('receipt')
                if receipt:
                    fi['native_receipt']=dict(deepcopy(receipt),binding_hash=binding['binding_hash'],scope_hash=ctx['scope_hash'])
                    fi['lark_status']=receipt['external_status'].lower()
                    fi['status']=native_business_status(state,fp,fn,fi,True) if receipt['approved'] else {'PENDING':'pending','REJECTED':'rejected','CANCELED':'withdrawn','DELETED':'withdrawn','UNVERIFIED':'invalidated'}.get(receipt['external_status'],'pending')
                fi.setdefault('history',[]).append({'action':'native_'+operation,'created_at':now(),
                    'actor_id':user['id'],'message':'Lark 結果已查回' if receipt else '已保存送審版本，尚未取得遠端結果','simulated':False})
                event(state,actor,'native_'+operation,fp['id'],fn['id'] if fn else None,
                      message='查回正式審批' if receipt else '保存正式審批送出版本')
            result[0]=persist(data['wid'],None,save,actor_id=user['id'],action_name='native_'+operation,project_versions={pid:find(fresh['projects'],pid).get('concurrency_version',0)})
            expected_binding=deepcopy(binding)
        try:
            if operation=='prepare':
                require(item['status']=='draft' and not (expected_binding or {}).get('attempted'),'只能準備尚未送出的草稿',409)
                content={k:deepcopy(item.get(k)) for k in ('reason','impact','confirmation_kind','payables_declaration','evidence_ids','task_ids','dates','source_finance') if k in item}
                content['project']={'id':p['id'],'code':p['code'],'name':p['name'],'revision':p['revision']}
                content['tasks']=[{k:deepcopy(t.get(k)) for k in ('id','title','owner_id','start_date','due_date','input_task_ids','output')}
                                  for node in p['nodes'] for t in node['tasks']
                                  if t['id'] in item.get('task_ids',[]) or kind=='node_skip' and node['id']==item['node_id']]
                binding=service.prepare(kind=kind,context=ctx,applicant=user['id'],approvers=approvers,content=content,authorize=authorize)
                checkpoint(binding)
            else:
                require(expected_binding is not None,'請先核對本次送審內容',409)
                require(expected_binding['payload']['open_id']==user['id'] or operation=='poll','需由原送審人提交',403)
                getattr(service,operation)(deepcopy(expected_binding),ctx,checkpoint,authorize)
        except RemoteFailure as exc: raise HTTPException(503,str(exc)) from exc
        return result[0]
