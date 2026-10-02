"""Periodic GET-only observation of already attempted native approvals.

The original applicant need not remain enabled to observe an existing instance.
Observation never submits, votes, applies a business transition or changes money.
"""
from copy import deepcopy
from datetime import datetime
from urllib.parse import quote
from sqlalchemy import select,update
from . import storage
from .policy import upgrade
from .workflow import now,require,event,find
from .native_approval import verify_definition,verify_instance,digest,observe_original_instance,creation_not_performed
from .native_requests import context,actors
from .production_access import business_admitted,set_company_admin_authority
from .lark_adapter import application_adapter,RemoteFailure

COLLECTIONS=('approvals','node_skip_requests','financial_requests')


class NativeApprovalPoller:
    def __init__(self,sessions,W,B,P,cfg,adapter_factory=None):
        self.sessions,self.W,self.B,self.P,self.cfg=sessions,W,B,P,cfg
        self.adapter_factory=adapter_factory or application_adapter

    def _load(self,db,row):
        state=upgrade(storage.load(db,self.B,row))
        from .workspace_environment import normalize_environment
        normalize_environment(state,row.id,self.cfg)
        people={r.person_id:deepcopy(r.data) for r in db.scalars(select(self.P).where(self.P.organization_id==row.id))}
        state['users']=[people.pop(p['id'],p) for p in state['users']]+list(people.values())
        state['native_approval_authority']={'app_id':self.cfg.get('LARK_APP_ID'),'tenant':self.cfg.get('LARK_WORKER_ORGANIZATION')}
        set_company_admin_authority(state,self.cfg)
        return state

    def _save(self,db,row,state):
        state['version']=row.version+1
        changed=db.execute(update(self.W).where(self.W.id==row.id,self.W.version==row.version)
            .values(version=state['version'],data=storage.save(db,self.B,row.id,state)))
        require(changed.rowcount==1,'審批查回版本衝突',409)

    def _policy(self,wid,binding):
        identity=binding.get('identity',{})
        require(self.cfg.get('LARK_WORKER_IDENTITY')=='application' and self.cfg.get('LARK_APP_ID') and
            wid=='lark-'+self.cfg.get('LARK_WORKER_ORGANIZATION','') and identity.get('workspace_id')==wid and
            identity.get('tenant')==self.cfg.get('LARK_WORKER_ORGANIZATION') and identity.get('app_id')==self.cfg['LARK_APP_ID'],
            '審批查回限原核定公司應用',403)
        require(identity['tenant'] in {v.strip() for v in self.cfg.get('LARK_ALLOWED_TENANTS','').split(',') if v.strip()},'公司不在核定名單',403)
        immutable={k:binding.get(k) for k in ('identity','kind','definition_hash','mapping','approvers','payload')}
        require(binding.get('attempted') and digest(immutable)==binding.get('binding_hash'),'原送審版本無法核對',409)

    def _claim(self,wid,collection,ident):
        with self.sessions.begin() as db:
            row=db.scalar(select(self.W).where(self.W.id==wid).with_for_update())
            if not row:return None
            state=self._load(db,row)
            if state.get('environment')!='production':return None
            item=next((x for x in state.get(collection,[]) if x['id']==ident),None)
            if not item or item.get('simulated'):return None
            binding=item.get('native_binding')
            if not binding or not binding.get('attempted') or creation_not_performed(binding):return None
            previous=item.get('native_poll_status',{}).get('last_attempt_at')
            if previous:
                try:
                    if (datetime.fromisoformat(now())-datetime.fromisoformat(previous)).total_seconds()<300:return None
                except (TypeError,ValueError):pass
            item.setdefault('native_poll_status',{}).update(last_attempt_at=now())
            self._save(db,row,state)
            return deepcopy(binding)

    def _check(self,wid,collection,ident,binding):
        self._policy(wid,binding)
        with self.sessions() as db:
            row=db.get(self.W,wid);require(row is not None,'工作區不存在',404)
            state=self._load(db,row);require(state.get('environment')=='production','正式工作區已變更',403)
            item=find(state.get(collection,[]),ident,'原審批')
            require(item.get('native_binding',{}).get('binding_hash')==binding['binding_hash'],'原審批版本已被替換',409)

    def _commit(self,wid,collection,ident,binding,receipt,observation,error=None,definite=False):
        with self.sessions.begin() as db:
            row=db.scalar(select(self.W).where(self.W.id==wid).with_for_update())
            if not row:return
            state=self._load(db,row);item=next((i for i in state.get(collection,[]) if i['id']==ident),None)
            if not item or item.get('native_binding',{}).get('binding_hash')!=binding['binding_hash']:return
            status=item.setdefault('native_poll_status',{});current_binding=item['native_binding']
            if observation:item['native_observation']=observation
            if error:
                status.update(status='error',message=error)
                current_binding.update(verification_failed_at=now(),verification_error=error)
                if definite:
                    item['native_receipt']=dict(item.get('native_receipt') or {},approved=False,binding_verified=False)
                    if item.get('status')!='executed':item['status']='invalidated'
            else:
                self._policy(wid,binding)
                p=find(state['projects'],item['project_id']);n=next((n for n in p['nodes'] if n['id']==item.get('node_id')),None)
                applicable=False;scope_valid=False
                try:
                    scope_valid=context(state,p,n,item,self.cfg['LARK_APP_ID'],self.cfg['LARK_WORKER_ORGANIZATION'])==binding['identity']
                    scope_valid=scope_valid and actors(state,p,n,item,binding['mapping'],self.cfg['LARK_APP_ID'])==binding['approvers'] and not receipt.get('observation_only')
                    applicant=next((u for u in state['users'] if u['id']==binding['payload']['open_id']),None)
                    applicable=scope_valid and business_admitted(applicant,self.cfg['LARK_APP_ID'],state.get('native_approval_authority',{}))
                except Exception as exc:
                    from fastapi import HTTPException
                    if not isinstance(exc,HTTPException):raise
                status.update(status='ready',last_success_at=now(),message='已查回原審批；目前範圍可採用' if applicable else '已查回原審批；目前身分或範圍已變更，不可套用')
                result=dict(receipt,approved=bool(receipt['approved'] and scope_valid),applicable=bool(applicable),
                    verified_at=now(),binding_hash=binding['binding_hash'],scope_hash=binding['identity']['scope_hash'])
                item['native_receipt']=result
                current_binding.update(receipt=deepcopy(result),instance_code=receipt['instance_code'],status=receipt['external_status'].lower())
                current_binding.pop('verification_failed_at',None);current_binding.pop('verification_error',None)
                item['lark_status']=receipt['external_status'].lower()
                terminal=receipt['external_status'] in ('CANCELED','DELETED','REJECTED','APPROVED')
                item['remote_resolution_required']=bool(not scope_valid and not terminal)
                if not terminal:item.pop('remote_resolution',None)
                if terminal and not scope_valid:
                    item['remote_resolution']={'status':receipt['external_status'],'verified_at':now(),
                                               'instance_code':receipt['instance_code'],'binding_hash':binding['binding_hash']}
                if item.get('status')!='executed':
                    if receipt['external_status'] in ('CANCELED','DELETED'):item['status']='withdrawn'
                    elif receipt['external_status']=='REJECTED':item['status']='rejected'
                    elif not scope_valid:item['status']='invalidated'
                    elif item.get('status') not in ('withdrawn','rejected','invalidated'):
                        from .native_requests import native_business_status
                        item['status']=native_business_status(state,p,n,item,receipt['approved'])
            p=next((p for p in state['projects'] if p['id']==item.get('project_id')),None)
            if p:
                from .operations import refresh_project_state
                refresh_project_state(p,state)
            event(state,{'id':'system:native-poller'},'native_approval_poll',item.get('project_id'),item.get('node_id'),message=status['message'])
            self._save(db,row,state)

    def run_due(self,wid):
        if wid!='lark-'+self.cfg.get('LARK_WORKER_ORGANIZATION','') or self.cfg.get('LARK_WORKER_IDENTITY')!='application':return []
        with self.sessions() as db:
            row=db.get(self.W,wid)
            if not row:return []
            state=self._load(db,row)
            candidates=[(c,i['id']) for c in COLLECTIONS for i in state.get(c,[])
                        if i.get('native_binding',{}).get('attempted') and not i.get('simulated')]
        results=[]
        for collection,ident in candidates:
            if len(results)>=10:break
            binding=self._claim(wid,collection,ident)
            if not binding:continue
            adapter=None;observation=None
            try:
                self._check(wid,collection,ident,binding)
                adapter=self.adapter_factory(deepcopy(self.cfg))
                def get(path):
                    self._check(wid,collection,ident,binding)
                    return adapter.request('GET',path,params={'user_id_type':'open_id'})
                instance=get('/approval/v4/instances/'+quote(binding['payload']['uuid'],safe=''))
                # Do not show another instance's status under this request.
                require(instance.get('approval_code')==binding['payload']['approval_code'] and
                    instance.get('uuid','').lower()==binding['payload']['uuid'].lower() and
                    instance.get('open_id')==binding['payload']['open_id'],'原審批身分不符',409)
                observation={'external_status':instance.get('status'),'observed_at':now(),'simulated':False}
                original_receipt=observe_original_instance(binding,instance)
                from .native_approval import InvalidApprovalProof
                try:
                    definition=get('/approval/v4/approvals/'+quote(binding['payload']['approval_code'],safe=''))
                    if verify_definition(definition,binding['mapping'])!=binding['definition_hash']:raise InvalidApprovalProof('原審批定義已改版','blocked')
                    receipt=verify_instance(binding,instance)
                except RemoteFailure:
                    # The original UUID/form identity has been checked. A
                    # changed/unavailable definition or invalid vote proof must
                    # not hide its lifecycle, and must never authorize business.
                    receipt=original_receipt
                self._commit(wid,collection,ident,binding,receipt,observation)
                results.append({'id':ident,'status':'observed'})
            except Exception as exc:
                from fastapi import HTTPException
                message=exc.detail if isinstance(exc,HTTPException) else str(exc) if isinstance(exc,RemoteFailure) else '原審批查回暫時失敗'
                from .native_approval import InvalidApprovalProof
                definite=isinstance(exc,HTTPException) or isinstance(exc,InvalidApprovalProof)
                self._commit(wid,collection,ident,binding,None,observation,error=message,definite=definite)
                results.append({'id':ident,'status':'error'})
            finally:
                if adapter:adapter.client.close()
        return results
