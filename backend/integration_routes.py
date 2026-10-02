"""Transport for connector verification, worker runs and file exports."""
import csv
import hashlib
import io
import json
from uuid import UUID
from copy import deepcopy
from fastapi import Request, HTTPException
from fastapi.responses import Response
from .workflow import require, find, uid, now, event
from .operations import capable, queue, operator
from .lark_adapter import application_adapter, RemoteFailure
from .jobs import Worker, PermissionCheckedClient
from .remote_policy import connection_policy, require_same_policy


async def input_request_body(request):
    try:
        body=await request.json()
    except (ValueError,TypeError,UnicodeDecodeError,RecursionError):
        raise HTTPException(422,'Input 請求必須是有效 JSON 物件')
    require(isinstance(body,dict),'Input 請求必須是 JSON 物件',422)
    require(type(body.get('version')) is int and body['version']>=1,'請提供有效的工作區版本',422)
    if 'project_version' in body:
        require(type(body['project_version']) is int and body['project_version']>=0,
                '請提供有效的案件版本',422)
    try:
        require(len(json.dumps(body,ensure_ascii=False,allow_nan=False).encode('utf-8'))<=65536,
                'Input 請求超過 64 KB',413)
    except (TypeError,ValueError,RecursionError):
        raise HTTPException(422,'Input 請求必須是有效且有限的 JSON 資料')
    return body

def register(app,identity,load,persist,sessions,W,B,P,cfg,uploads):
    worker=Worker(sessions,W,B,P,cfg,uploads); app.state.worker=worker

    @app.post('/api/projects/{project_id}/nodes/{node_id}/inputs')
    async def register_input(project_id:str,node_id:str,request:Request):
        from .case_cutover import require_execution
        from .input_registration import make_plan,validate_plan,fingerprint,canonical,registration_fields
        data,user=identity(request);body=await input_request_body(request)
        require(isinstance(body.get('request_id'),str),'request_id 必須是固定 UUID 文字',422)
        try:request_id=str(UUID(body['request_id']))
        except ValueError:raise HTTPException(422,'請提供固定的登錄 request_id，重試沿用同一識別')
        key=body.get('key');label=body.get('label');value=body.get('value')
        require(isinstance(key,str) and 0<len(key.strip())<=120 and isinstance(label,str) and 0<len(label.strip())<=200,'請提供有效登錄項目與名稱',422)
        try:require(len(canonical(value).encode())<=50000,'Input 內容超過 50KB，請使用文件交付',422)
        except (ValueError,TypeError):raise HTTPException(422,'Input 內容必須是有效 JSON')
        requested=fingerprint({'project_id':project_id,'node_id':node_id,'key':key,'label':label,'value':value,'actor_id':user['id']})
        def mutate(s):
            p=find(s['projects'],project_id);n=find(p['nodes'],node_id);require_execution(s,p)
            current_actor=find(s['users'],user['id'])
            require(operator(current_actor,p,n),'沒有此節點提交權限',403)
            prior=next((i for i in s.get('input_revisions',[]) if i.get('request_id')==request_id),None)
            if prior:
                require(prior.get('request_hash')==requested,'同一 request_id 的內容不同，請核對既有登錄',409)
                return
            try:
                policy=connection_policy(data['wid'],s,cfg,'input')
                require(not policy['simulated'],'此入口只供已核定專用登錄連線',409)
                fields=registration_fields(cfg,policy)
                destination={'base_token':policy['base_token'],'table_id':policy.get('table_id'),'fields':fields}
                ident=uid();mapping_id=uid()
                revision=dict(id=ident,project_id=project_id,node_id=node_id,mapping_id=mapping_id,
                    key=key.strip(),label=label.strip(),value=deepcopy(value),base_value=None,
                    actor_id=user['id'],created_at=now(),status='queued',request_id=request_id,request_hash=requested)
                revision['registration_plan']=make_plan(data['wid'],p,n,revision,destination)
                validate_plan(revision['registration_plan'],policy)
            except (RemoteFailure,ValueError,TypeError) as exc:raise HTTPException(409,str(exc))
            s.setdefault('input_mappings',[]).append(dict(id=mapping_id,project_id=project_id,node_id=node_id,
                key=revision['key'],label=revision['label'],mode='append_registration',enabled=True,
                verified=False,verification_basis='pending_worker_schema_check',**destination))
            s.setdefault('input_revisions',[]).append(revision)
            queue(s,'input',current_actor,{'input_id':ident,'mapping_id':mapping_id,'project_id':project_id},'input:'+ident)
            event(s,current_actor,'input_registration_queued',project_id,node_id,message='Input 已排入專用登錄；完成讀回前不表示送達')
        return persist(data['wid'],body['version'],mutate,actor_id=user['id'],
                       project_versions={project_id:body['project_version']} if 'project_version' in body else None)

    @app.post('/api/input-revisions/{revision_id}/reconcile')
    async def reconcile_input(revision_id:str,request:Request):
        from .case_cutover import require_execution
        from .input_registration import RegistrationAdapter,registration_fields
        data,user=identity(request);body=await input_request_body(request)
        with sessions() as db:state=load(db,db.get(W,data['wid']))
        revision=deepcopy(find(state['input_revisions'],revision_id))
        from .source_case_policy import visible_project
        require(visible_project(state,find(state['projects'],revision['project_id'])),'Input 紀錄不存在',404)
        plan=deepcopy(revision.get('registration_plan'));require(plan,'舊式 Input 不支援此登錄核實入口',409)
        def allowed(s,actor):
            current=find(s['input_revisions'],revision_id);p=find(s['projects'],current['project_id']);n=find(p['nodes'],current['node_id'])
            require(current['project_id']==revision['project_id'],'Input 所屬案件已變更',409)
            require_execution(s,p);require(operator(actor,p,n),'Input 核實權限已撤銷',403)
            require(current.get('registration_plan')==plan and current.get('status')=='outcome_unknown' and not current.get('superseded'),'只有未改版的未知結果可以查回',409)
            try:fields=registration_fields(cfg,connection_policy(data['wid'],s,cfg,'input'))
            except RemoteFailure as exc:raise HTTPException(409,str(exc))
            require(plan.get('destination',{}).get('fields')==fields,'Input 登錄欄位核定設定已變更',409)
            jobs=[j for j in s['jobs'] if j.get('key')=='input:'+revision_id]
            require(len(jobs)==1 and jobs[0]['status']=='outcome_unknown','背景工作狀態不允許查回',409)
        allowed(state,user);adapter=None
        try:
            policy=connection_policy(data['wid'],state,cfg,'input')
            def check():
                fresh_data,actor=identity(request);require(fresh_data['wid']==data['wid'],'工作區已變更',403)
                with sessions() as db:fresh=load(db,db.get(W,data['wid']))
                allowed(fresh,actor);require_same_policy(policy,connection_policy(data['wid'],fresh,cfg,'input'))
            adapter=application_adapter(cfg);check();adapter.client=PermissionCheckedClient(adapter.client,check)
            receipt=RegistrationAdapter(adapter).reconcile(plan,policy)
            check()
        except RemoteFailure as exc:raise HTTPException(409 if exc.status in ('outcome_unknown','conflict','blocked') else 503,str(exc))
        finally:
            if adapter:adapter.client.close()
        def mutate(s):
            _,actor=identity(request);allowed(s,actor)
            try:require_same_policy(policy,connection_policy(data['wid'],s,cfg,'input'))
            except RemoteFailure as exc:raise HTTPException(409,str(exc))
            current=find(s['input_revisions'],revision_id)
            current.update(status='succeeded',receipt=receipt,finished_at=now())
            job=next(j for j in s['jobs'] if j.get('key')=='input:'+revision_id)
            job.update(status='succeeded',receipt=receipt,finished_at=now(),error=None,reconciled_by=actor['id'])
            event(s,actor,'input_registration_reconciled',current['project_id'],current['node_id'],message='只讀核實專用登錄內容相符')
        return persist(data['wid'],body['version'],mutate,actor_id=user['id'],
                       project_versions={revision['project_id']:body['project_version']} if 'project_version' in body else None)

    @app.post('/api/admin/worker/run')
    def run_worker(request:Request):
        data,user=identity(request); require(user['role']=='manager','需管理員權限')
        ident=worker.run_one(data['wid']); return {'job_id':ident}

    @app.post('/api/input-mappings/{mapping_id}/verify')
    async def verify(mapping_id:str,request:Request):
        data,user=identity(request); require(capable(user,'manage_sources'))
        body=await input_request_body(request)
        with sessions() as db: state=load(db,db.get(W,data['wid'])); mapping=deepcopy(find(state['input_mappings'],mapping_id))
        from .source_case_policy import visible_project
        require(visible_project(state,find(state['projects'],mapping.get('project_id'))),'Input 映射不存在',404)
        adapter=None
        try:
            policy=connection_policy(data['wid'],state,cfg,'input',for_verification=True)
            require(not policy['simulated'],'模擬工作區不能查證遠端欄位；請先核定隔離實測設定',409)
            require(mapping['base_token']==policy['base_token'] and mapping['enabled'],'來源不在核定目的或映射已停用',403)
            require(not policy.get('table_id') or mapping['table_id']==policy['table_id'],'Input 只允許核定專用登錄表',403)
            adapter=application_adapter(cfg)
            # Token acquisition may take time; verify the actor and destination again.
            def check():
                fresh_data,fresh_user=identity(request); require(fresh_data['wid']==data['wid'] and capable(fresh_user,'manage_sources'),'來源查證權限已改變',403)
                with sessions() as db: fresh=load(db,db.get(W,data['wid']))
                require_same_policy(policy,connection_policy(data['wid'],fresh,cfg,'input',for_verification=True))
                require(find(fresh['input_mappings'],mapping_id)==mapping,'映射已變更',409)
            check(); adapter.client=PermissionCheckedClient(adapter.client,check)
            field,value=adapter.verify_mapping(mapping)
        except RemoteFailure as exc:
            raise HTTPException(503,str(exc))
        finally:
            if adapter: adapter.client.close()
        def mutate(s):
            try: require_same_policy(policy,connection_policy(data['wid'],s,cfg,'input',for_verification=True))
            except RemoteFailure as exc: raise HTTPException(409,str(exc))
            m=find(s['input_mappings'],mapping_id); require(m==mapping,'映射已變更',409); m.update(verified=True,verified_at=now(),remote_value=value,schema=field,verified_mode=policy['mode'])
        return persist(data['wid'],body['version'],mutate,actor_id=user['id'])

    @app.post('/api/files/{file_id}/store-lark')
    async def store_file(file_id:str,request:Request):
        data,user=identity(request); body=await request.json()
        def mutate(s):
            p=next((p for p in s['projects'] if any(f['id']==file_id for f in p['files'])),None); require(p is not None,'文件不存在',404)
            from .case_cutover import require_execution
            require_execution(s,p)
            f=find(p['files'],file_id); n=next((n for n in p['nodes'] if n['id']==f.get('node_id')),None)
            require(operator(user,p,n)); require(f['storage']=='local' and not f.get('withdrawn'),'文件不可送出',409)
            require(not f.get('remote_status') and not any(j.get('key')=='file:'+file_id for j in s.get('jobs',[])),
                    '此文件已有送存紀錄，請至背景工作核對結果；失敗重試須使用原工作，不能重新排隊',409)
            queue(s,'file',user,{'project_id':p['id'],'file_id':file_id},'file:'+file_id); f['remote_status']='queued'
        return persist(data['wid'],body['version'],mutate,actor_id=user['id'])

    @app.post('/api/learning/mappings/verify')
    async def verify_learning_mapping(request:Request):
        from .features import require_learning
        require_learning()
        data,user=identity(request); require(capable(user,'manage_sources'),'需要來源管理權限',403)
        body=await request.json(); candidate=body.get('mapping') or {}
        mapping={'id':str(candidate.get('id') or uid()),'purpose':'training','base_token':str(candidate.get('base_token','')),'table_id':str(candidate.get('table_id','')),'fields':candidate.get('fields') or {}}
        require(not data['wid'].startswith(('test-','demo-')),'正式訓練映射只能在正式工作區核實',409)
        adapter=None
        try:
            initial_policy={key:cfg.get(key) for key in ('LARK_APP_ID','LARK_WORKER_ORGANIZATION','LARK_WORKER_IDENTITY')}
            def check():
                fresh_data,fresh_user=identity(request)
                require(fresh_data['wid']==data['wid'] and capable(fresh_user,'manage_sources'),
                        '來源查證權限已改變',403)
                require(initial_policy=={key:cfg.get(key) for key in initial_policy},'來源應用設定已改變',409)
            adapter=application_adapter(cfg)
            check(); adapter.client=PermissionCheckedClient(adapter.client,check)
            adapter.verify_training_mapping(mapping)
            check()
        except RemoteFailure as exc:
            raise HTTPException(503,str(exc))
        finally:
            if adapter: adapter.client.close()
        def mutate(s):
            require(capable(find(s['users'],user['id']),'manage_sources'),'來源查證權限已改變',403)
            require(initial_policy=={key:cfg.get(key) for key in initial_policy},'來源應用設定已改變',409)
            mapping.update(verified=True,verified_at=now()); s['learning_mappings']=[m for m in s['learning_mappings'] if m['purpose']!='training']+[mapping]
        return persist(data['wid'],body['version'],mutate,actor_id=user['id'])

    @app.get('/api/projects/{project_id}/file-index.csv')
    def file_index(project_id:str,request:Request):
        data,user=identity(request)
        with sessions() as db:
            state=load(db,db.get(W,data['wid']));p=find(state['projects'],project_id)
        from .source_case_policy import visible_project
        require(visible_project(state,p),'案件不存在或不在工作台範圍',404)
        stream=io.StringIO(); writer=csv.writer(stream); writer.writerow(['案件','名稱','用途','版本','儲存狀態','連結','撤下'])
        def safe(v):
            text=str(v or ''); return "'"+text if text.startswith(('=','+','-','@','\t','\r')) else text
        for f in p['files']: writer.writerow([safe(x) for x in (p['code'],f['name'],f['direction'],f['version'],f.get('remote_status','local'),f.get('remote_url') or f.get('url',''),f.get('withdrawn',False))])
        for f in p.get('source_attachments',[]):
            writer.writerow([safe(x) for x in (p['code'],f['name'],'來源附件索引',f.get('source_field',''),
                '來源已移除（歷史保留）' if f['status']=='source_missing' else '僅索引，尚未下載核實',f['source_url'],f['status']=='source_missing')])
        return Response('\ufeff'+stream.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="case-files.csv"'})
