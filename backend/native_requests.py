"""Server-derived scope and receipt checks shared by API and business gates."""
from copy import deepcopy
from datetime import datetime
from .native_approval import digest
from .workflow import require,find,now


def kind_of(item):
    return item.get('type') or ('node_skip' if 'content_hash' in item else 'financial')


def actors(ws,p,n,item,mapping,app_id=None):
    kind=kind_of(item)
    available={'pm':p.get('pm_id'),'admin':p.get('admin_id'),
               'owner':(n or {}).get('owner_id'),
               'supervisor':(n or {}).get('supervisor_id') or p.get('supervisor_id')}
    seats=[s for node in mapping.get('nodes',[]) for s in node.get('seats',[])]
    required={'node_skip':{'pm','supervisor'},'financial':{'pm','admin'},'change':{'pm','supervisor'}}.get(kind,set())
    require(required<=set(seats),'審批席次尚未符合已核定規則',409)
    require(kind not in ('node_skip','financial','change') or (set(seats)==required and len(seats)==len(required)),'審批席次與核定規則不同',409)
    result={seat:available.get(seat) for seat in seats}
    require(result and all(result.values()) and len(set(result.values()))==len(result),'需指定各席不同的實際核准人',409)
    for ident in result.values():
        person=find(ws['users'],ident,'核准人')
        require(person.get('active',True),'核准人已停用，請重新指派',409)
        if ws.get('environment')=='production':
            from .production_access import business_admitted
            expected=app_id or ws.get('native_approval_authority',{}).get('app_id') or ws.get('people_directory_status',{}).get('app_id')
            require(bool(expected) and business_admitted(person,expected,ws.get('native_approval_authority',{})),'核准人尚未核實同一公司應用的在職身分',409)
    return result


def scope_hash(ws,p,n,item):
    kind=kind_of(item)
    if kind=='node_skip':
        from .node_skip import fingerprint,current
        require(current(ws,p,n,item),'跳過範圍已改版，請重新申請',409)
        return item['content_hash']
    evidence_ids=set(item.get('evidence_ids',[]))
    file_ids=evidence_ids|{e.get('file_id') for e in p.get('evidence',[]) if e['id'] in evidence_ids and e.get('file_id')}
    tasks=[{k:deepcopy(v) for k,v in t.items() if k not in ('comments','status','can_execute','capabilities','confirmation_hash','activation_blockers')}
           for node in p['nodes'] for t in node['tasks']
           if t['id'] in item.get('task_ids',[]) or kind=='financial' and node['id']==(n or {}).get('id')]
    # Preserve the exact legacy algorithm for already-bound requests. New
    # requests bind semantic task scope; refresh timestamps and unrelated
    # source costs must not silently cancel an approval in progress.
    scope_version=item.get('approval_scope_version',1 if item.get('native_binding') else 3)
    if scope_version>=2:
        from .approval_scope import task_scope
        tasks=[task_scope(t) for node in p['nodes'] for t in node['tasks']
               if t['id'] in item.get('task_ids',[]) or kind=='financial' and node['id']==(n or {}).get('id')]
    scope={'kind':kind,'project_revision':p['revision'],'node_id':(n or {}).get('id'),
        'node_key':(n or {}).get('key'),'source_scope_hash':p.get('source_scope_hash') if scope_version==1 else None,
        'requirements':(n or {}).get('requirements',[]) if kind=='financial' else None,
        'source_records':p.get('source_records',[]) if scope_version==1 else None,'pm':p.get('pm_id'),'admin':p.get('admin_id'),
        'owner':(n or {}).get('owner_id'),'supervisor':(n or {}).get('supervisor_id') or p.get('supervisor_id'),
        'client':p.get('client_approver_id'),'tasks':tasks,
        'request':{k:item.get(k) for k in ('id','reason','task_ids','dates','evidence_ids','confirmation_kind','payables_declaration','project_revision')},
        'evidence':[e for e in p.get('evidence',[]) if e['id'] in evidence_ids],
        'files':[f for f in p.get('files',[]) if f['id'] in file_ids],
        'source_finance':p.get('source_finance') if kind=='financial' else None}
    if scope_version>=2:
        scope['existence']={label:{key:bool(record.get(key)) for key in
            ('source_missing','archived_at','migrated_to')} for label,record in
            (('project',p),('node',n or {}))}
    if scope_version>=3:
        from .approval_scope import file_scope
        scope['files']=[file_scope(f) for f in scope['files']]
    return digest(scope)


def context(ws,p,n,item,app_id,tenant):
    return {'app_id':app_id,'tenant':tenant,'workspace_id':'lark-'+tenant,
            'project_id':p['id'],'request_id':item['id'],
            'version':item.get('version',item.get('project_revision',1)),
            'scope_hash':scope_hash(ws,p,n,item)}


def change_evidence(p,evidence_ids):
    """Approved case evidence, including immutable verified local file versions."""
    require(isinstance(evidence_ids,list) and bool(evidence_ids) and
            all(isinstance(i,str) for i in evidence_ids),'請選擇已確認的業主佐證',422)
    result=[]
    for ident in dict.fromkeys(evidence_ids):
        evidence=find(p.get('evidence',[]),ident,'變更確認佐證')
        require(evidence.get('status')=='accepted' and not evidence.get('withdrawn'),
                '變更確認佐證尚未確認或已撤下',409)
        require(evidence.get('file_id') or str(evidence.get('value') or '').strip(),'業主佐證缺少內容或文件',409)
        entry={'evidence':deepcopy(evidence)}
        if evidence.get('file_id'):
            document=find(p.get('files',[]),evidence['file_id'],'佐證文件')
            require(not document.get('withdrawn') and (document.get('storage')!='local' or
                    document.get('remote_status')=='verified'),'佐證文件尚未核實存入 Lark 或已撤下',409)
            entry['file']=deepcopy(document)
        result.append(entry)
    return result


def change_lines_valid(ws,p,n,item):
    """External evidence and supervisor confirmation are separate from native votes."""
    if kind_of(item)!='change':return True
    from .production_access import business_admitted
    app_id=ws.get('native_approval_authority',{}).get('app_id')
    supervisor=(n or {}).get('supervisor_id') or p.get('supervisor_id')
    current_scope=scope_hash(ws,p,n,item)
    lines=item.get('change_confirmations') or {}
    for party in ('supervisor','client'):
        proof=lines.get(party) or {}
        if proof.get('scope_hash')!=current_scope or not proof.get('reason') or not proof.get('recorded_at'):return False
        person=next((u for u in ws['users'] if u['id']==proof.get('recorded_by')),None)
        if not business_admitted(person,app_id,ws.get('native_approval_authority',{})):return False
        if party=='supervisor' and proof.get('recorded_by')!=supervisor:return False
        if party=='client':
            if proof.get('recorded_by') not in (p.get('pm_id'),supervisor):return False
            try:
                if digest(change_evidence(p,proof.get('evidence_ids')))!=proof.get('evidence_hash'):return False
            except Exception as exc:
                from fastapi import HTTPException
                if isinstance(exc,HTTPException):return False
                raise
    return True


def native_business_status(ws,p,n,item,approved):
    if not approved:return 'pending'
    if kind_of(item)=='change' and not change_lines_valid(ws,p,n,item):return 'pending'
    return 'applied' if item.get('status')=='applied' else 'approved'


def receipt_valid(ws,p,n,item,require_fresh=True):
    try:
        binding=item.get('native_binding') or {}; receipt=item.get('native_receipt') or {}
        identity=binding['identity']
        authority=ws.get('native_approval_authority') or {}
        if authority.get('app_id')!=identity['app_id'] or authority.get('tenant')!=identity['tenant']: return False
        directory_app=ws.get('people_directory_status',{}).get('app_id')
        if directory_app and directory_app!=identity['app_id']: return False
        immutable={k:binding[k] for k in ('identity','kind','definition_hash','mapping','approvers','payload')}
        if digest(immutable)!=binding.get('binding_hash'): return False
        if item.get('simulated') or ws.get('environment')!='production': return False
        if item.get('status') in ('withdrawn','rejected','invalidated'): return False
        if context(ws,p,n,item,identity['app_id'],identity['tenant'])!=identity: return False
        if actors(ws,p,n,item,binding['mapping'])!=binding['approvers']: return False
        if not (receipt.get('approved') is True and receipt.get('binding_verified') is True
                and receipt.get('simulated') is False and receipt.get('binding_hash')==binding['binding_hash']
                and receipt.get('scope_hash')==identity['scope_hash']
                and receipt.get('instance_code')==binding.get('instance_code')): return False
        if require_fresh:
            if binding.get('verification_failed_at'): return False
            from .production_access import business_admitted
            applicant=next((u for u in ws['users'] if u['id']==binding['payload']['open_id']),None)
            if not business_admitted(applicant,identity['app_id'],authority): return False
            age=(datetime.fromisoformat(now())-datetime.fromisoformat(receipt['verified_at'])).total_seconds()
            if age<0 or age>300:return False
        return True
    except (KeyError,TypeError,ValueError): return False
    except Exception as exc:
        from fastapi import HTTPException
        if isinstance(exc,HTTPException): return False
        raise
