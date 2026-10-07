import hashlib
import json
import os
from pathlib import Path
import secrets
import re
from copy import deepcopy
from contextlib import asynccontextmanager, contextmanager
from time import perf_counter
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit
import httpx
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from itsdangerous import URLSafeTimedSerializer, BadSignature
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, String, Integer, JSON, select, update, cast, or_, and_, func
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine import make_url
from .seed import seed, USERS
from .workflow import apply_action, require, find, event, now, uid, is_pm, is_owner
from .sources import API, configuration, import_sources
from .policy import upgrade, CAPABILITIES, MANAGER_CAPABILITIES
from .operations import apply_operation, project_summary, capable, review_hash, invalidate
from . import storage
from .learning import apply_learning
from .approval_capabilities import approval_connection
from .workspace_projection import public_copy, strip_migration_archive, filter_private_workspace, public_person
from .production_access import require_admission, require_access, test_profile,company_admin_grant,set_company_admin_authority
from . import audit
from .input_validation import json_object
from .file_categories import categories, validate_category, save_category

from .models import Base, WorkspaceRow, Receipt, AuthRow, CacheRow, AuditRow, BusinessRow, PersonRow

class Action(BaseModel):
    action:str; version:int; request_id:str=Field(min_length=1,max_length=120)
    project_id:str|None=None; node_id:str|None=None; task_id:str|None=None; payload:dict=Field(default_factory=dict)
    project_versions:dict[str,int]=Field(default_factory=dict)


def _copy_local_pilot_attachments(upload_dir,source_wid,target_wid,project,id_map):
    """Copy verified local bytes into the test namespace; never mutate source files."""
    source_root=Path(upload_dir).resolve()/hashlib.sha256(source_wid.encode()).hexdigest()
    target_root=Path(upload_dir).resolve()/hashlib.sha256(target_wid.encode()).hexdigest()
    created=[]; copied={}
    try:
        for item in project.get('files',[]):
            if item.get('storage')!='local': continue
            ident=item.get('id')
            source_ident=next((old for old,new in id_map.items() if new==ident),ident)
            require(isinstance(ident,str) and ident and Path(ident).name==ident and ident not in ('.','..'),'附件識別碼錯誤',409)
            source=(source_root/source_ident).resolve(); destination=target_root/ident
            require(source.is_relative_to(source_root) and source.is_file(),'正式附件檔案不存在',409)
            payload=source.read_bytes(); digest=hashlib.sha256(payload).hexdigest()
            require(isinstance(item.get('size'),int) and len(payload)==item['size'],'正式附件大小不符',409)
            require(isinstance(item.get('sha256'),str) and digest==item['sha256'],'正式附件校驗失敗',409)
            if ident in copied:
                require(copied[ident]==(len(payload),digest),'附件索引衝突',409)
                continue
            target_root.mkdir(parents=True,exist_ok=True)
            with destination.open('xb') as handle: handle.write(payload)
            created.append(destination); copied[ident]=(len(payload),digest)
        return created
    except Exception:
        for path in created: path.unlink(missing_ok=True)
        raise

def _reidentify_pilot_project(project,occupied_ids=()):
    """Give an isolated project copy new entity IDs while preserving internal links."""
    from .workflow import uid
    copied=deepcopy(project)
    id_map={};used=set(occupied_ids)
    def collect(value):
        if isinstance(value,dict):
            ident=value.get('id')
            if isinstance(ident,str) and ident:
                if ident in used: id_map.setdefault(ident,'pilot-'+uid())
                used.add(ident)
            for child in value.values(): collect(child)
        elif isinstance(value,list):
            for child in value: collect(child)
    collect(copied)
    file_urls={f'/api/files/{item["id"]}/download':f'/api/files/{id_map[item["id"]]}/download'
               for item in copied.get('files',[]) if item.get('id') in id_map}
    source_id=copied['id']
    def rewrite(value):
        if isinstance(value,dict):
            for key,child in list(value.items()):
                if key=='id' and isinstance(child,str): value[key]=id_map.get(child,child)
                elif key=='url' and isinstance(child,str): value[key]=file_urls.get(child,child)
                elif isinstance(child,str): value[key]=id_map.get(child,child)
                else: rewrite(child)
        elif isinstance(value,list):
            for index,child in enumerate(value):
                if isinstance(child,str): value[index]=id_map.get(child,child)
                else: rewrite(child)
    rewrite(copied)
    copied['pilot_source_id']=source_id
    return copied,id_map

def create_app(overrides=None):
    cfg=dict(os.environ); cfg.update(overrides or {})
    production=cfg.get('APP_ENV','development')=='production'
    demo=str(cfg.get('DEMO_MODE','false' if production else 'true')).lower()=='true'
    db_url=cfg.get('DATABASE_URL','sqlite:///./backend/workspace.db')
    secret=cfg.get('SESSION_SECRET')
    if production:
        if not db_url.startswith(('postgresql://','postgresql+psycopg://','postgres://')): raise RuntimeError('Production requires PostgreSQL DATABASE_URL')
        if not secret or len(secret)<32: raise RuntimeError('Production SESSION_SECRET must have at least 32 characters')
        if demo and cfg.get('ALLOW_CLOUD_DEMO','false').lower()!='true': raise RuntimeError('Cloud demo requires explicit ALLOW_CLOUD_DEMO=true')
    secret=secret or 'local-development-only-change-before-deploy'
    if db_url.startswith('postgres://'): db_url='postgresql+psycopg://'+db_url[len('postgres://'):]
    elif db_url.startswith('postgresql://'): db_url='postgresql+psycopg://'+db_url[len('postgresql://'):]
    if db_url.startswith('sqlite'):
        database_path=make_url(db_url).database
        if database_path and database_path!=':memory:': Path(database_path).resolve().parent.mkdir(parents=True,exist_ok=True)
    engine=create_engine(db_url,connect_args={'check_same_thread':False,'timeout':20} if db_url.startswith('sqlite') else {},pool_pre_ping=True)
    Base.metadata.create_all(engine); sessions=sessionmaker(engine,expire_on_commit=False,info={'index_tables':str(cfg.get('INDEX_TABLES_ENABLED','false')).lower()=='true'})
    # Migration is reversible: preserve the original JSON before normalizing.
    with sessions.begin() as db:
        for row in db.scalars(select(WorkspaceRow)):
            if row.data.get('storage_schema')!=2:
                state=upgrade(deepcopy(row.data))
                state.setdefault('migration_archive',deepcopy(row.data))
                row.data=storage.save(db,BusinessRow,row.id,state)
            elif 'migration_archive' in row.data:
                state=upgrade(storage.load(db,BusinessRow,row))
                row.data=storage.save(db,BusinessRow,row.id,state)
    signer=URLSafeTimedSerializer(secret,salt='meegle-session-v1')
    upload_dir=Path(cfg.get('UPLOAD_DIR','./backend/uploads')).resolve(); upload_dir.mkdir(parents=True,exist_ok=True)
    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            app.state.live_read.close()

    app=FastAPI(title='詠翔專案工作台',docs_url=None if production else '/api/docs',lifespan=lifespan); app.state.engine=engine; app.state.sessions=sessions; app.state.signer=signer
    app.state.cfg=cfg; app.state.upload_dir=upload_dir
    @app.exception_handler(HTTPException)
    async def safe_auth_error(request,exc):
        from fastapi.responses import JSONResponse
        if request.url.path=='/api/auth/lark/callback' and 'text/html' in request.headers.get('accept',''):
            detail=str(exc.detail)
            code=('provider_unavailable' if exc.status_code>=500 else
                  'tenant_denied' if '租戶' in detail else
                  'unverified_directory' if '名冊' in detail else
                  'inactive' if '停權' in detail else
                  'app_configuration' if '應用權限' in detail or 'OAuth 應用' in detail else
                  'authorization_denied' if '使用者拒絕授權' in detail else 'expired')
            response=RedirectResponse('/?auth_error='+code,status_code=303)
            response.delete_cookie('lark_oauth_state'); return response
        return JSONResponse({'detail':exc.detail},status_code=exc.status_code,headers=exc.headers)
    app.add_middleware(GZipMiddleware,minimum_size=1000,compresslevel=5)
    from .request_limits import JsonRequestLimit
    app.add_middleware(JsonRequestLimit)
    oauth_configured=all(cfg.get(k) for k in ('LARK_APP_ID','LARK_APP_SECRET','LARK_REDIRECT_URI','LARK_ALLOWED_TENANTS'))
    oauth_scopes=' '.join(dict.fromkeys(x for x in re.split(r'[\s,]+',cfg.get('LARK_OAUTH_SCOPES','bitable:app:readonly').strip()) if x))
    if not oauth_scopes: oauth_scopes='bitable:app:readonly'
    try: role_map=json.loads(cfg.get('LARK_ROLE_MAP_JSON','{}'))
    except (ValueError,TypeError): raise RuntimeError('LARK_ROLE_MAP_JSON must be a JSON object of open_id to role')
    if not isinstance(role_map,dict) or any(not isinstance(k,str) or v not in ('member','pm','manager') for k,v in role_map.items()):
        raise RuntimeError('LARK_ROLE_MAP_JSON roles must be member, pm, or manager')
    allowed_tenants={value.strip() for value in cfg.get('LARK_ALLOWED_TENANTS','').split(',') if value.strip()}
    admission_required=production or oauth_configured
    capability_approvers={value.strip() for value in cfg.get('LARK_CAPABILITY_APPROVER_IDS','').split(',') if value.strip()}

    def initial_capabilities(ident,role):
        return (MANAGER_CAPABILITIES[:] if role=='manager' else [])+(['approve_capability'] if ident in capability_approvers else [])

    shell_enabled=str(cfg.get('WORKSPACE_SHELL_ENABLED','false')).lower()=='true'
    TIMED_ROUTES={('GET','/api/workspace'),('GET','/api/session'),('GET','/api/projects'),('POST','/api/actions')}
    @contextmanager
    def phase(request,name):
        started=perf_counter()
        try: yield
        finally:
            phases=request.scope.setdefault('phases',{}); phases[name]=phases.get(name,0)+perf_counter()-started

    @app.middleware('http')
    async def origin_guard(request,call_next):
        started=perf_counter()
        if request.method in ('POST','PUT','PATCH','DELETE'):
            origin=request.headers.get('origin'); expected=cfg.get('PUBLIC_ORIGIN')
            actual=f"{request.url.scheme}://{request.url.netloc}"
            # Proxy deployments should set PUBLIC_ORIGIN, not blindly trust forwarded host.
            if (origin and origin not in {expected,actual}) or request.headers.get('sec-fetch-site')=='cross-site':
                from fastapi.responses import JSONResponse
                return JSONResponse({'detail':'跨站請求已拒絕'},status_code=403)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='same-origin'
        if request.url.path.startswith('/api'): response.headers['Cache-Control']='no-store'
        if (request.method,request.url.path) in TIMED_ROUTES:
            # Durations only. 'serialize' is the unmeasured remainder (response encoding and framework time).
            phases=dict(request.scope.get('phases',{})); total=perf_counter()-started
            phases['serialize']=max(total-sum(phases.values()),0)
            response.headers['Server-Timing']=', '.join([f'{k};dur={v*1000:.1f}' for k,v in phases.items()]+[f'total;dur={total*1000:.1f}'])
        return response

    def read_cookie(request):
        cookie=request.cookies.get('meegle_session')
        if not cookie: return None
        try: data=signer.loads(cookie,max_age=8*3600)
        except BadSignature: return None
        if data.get('mode')=='demo' and not demo: return None
        return data
    def set_cookie(response,data):
        response.set_cookie('meegle_session',signer.dumps(data),httponly=True,secure=production,samesite='lax',max_age=8*3600,path='/')
    def ensure_workspace(wid,empty=False):
        with sessions.begin() as db:
            if not db.get(WorkspaceRow,wid):
                data=seed(empty)
                if empty: data['as_of']=now()[:10]
                data['environment']='test' if wid.startswith('test-') else ('production' if wid.startswith('lark-') else 'demo')
                upgrade(data)
                row=WorkspaceRow(id=wid,version=1,data=data); db.add(row); db.flush()
                row.data=storage.save(db,BusinessRow,wid,data)

    def load(db,row,*,collections=None,project_ids=None):
        if project_ids is not None: state=storage.load_partial(db,BusinessRow,row,collections=[c for c in storage.COLLECTIONS if c!='projects'],project_ids=project_ids,project_children=storage.PROJECT_CHILDREN)
        else: state=storage.load(db,BusinessRow,row) if collections is None else storage.load_partial(db,BusinessRow,row,collections=collections)
        state=upgrade(state)
        from .workspace_environment import normalize_environment
        from .case_cutover import initialize_execution_system
        normalize_environment(state,row.id,cfg)
        initialize_execution_system(state)
        if row.id.startswith(('lark-','test-lark-')):
            org=row.id.removeprefix('test-')
            profiles={r.person_id:deepcopy(r.data) for r in db.scalars(select(PersonRow).where(PersonRow.organization_id==org))}
            if row.id.startswith('test-'):
                overlays={r.person_id:r.data for r in db.scalars(select(PersonRow).where(PersonRow.organization_id==row.id))}
                profiles={ident:test_profile(person,overlays.get(ident)) for ident,person in profiles.items()}
                profiles.update({ident:deepcopy(person) for ident,person in overlays.items() if ident not in profiles})
            known={u['id'] for u in state['users']}
            state['users']=[profiles.get(u['id'],u) for u in state['users']]+[p for ident,p in profiles.items() if ident not in known]
        state['native_approval_authority']={'app_id':cfg.get('LARK_APP_ID'),'tenant':cfg.get('LARK_WORKER_ORGANIZATION')}
        set_company_admin_authority(state,cfg)
        return state

    def organization(data):
        return data.get('organization') or data['wid'].removeprefix('test-')

    def reconcile_company_admin(db,org,person):
        grant=company_admin_grant(person,cfg,tenant=org.removeprefix('lark-'))
        previous=person.get('company_admin_authorization')
        if previous==grant:return False
        if grant:person['company_admin_authorization']=grant
        else:person.pop('company_admin_authorization',None)
        db.add(audit.record(AuditRow,org,person['id'],'company_admin_authorization' if grant else 'company_admin_authorization_revoked',
            details={'authorization':grant,'previous_grant_id':(previous or {}).get('grant_id'),
                     'source':'server_allowlist_and_verified_oauth','salary_base_modified':False}))
        return True

    def person_identity(db,data,user):
        if data.get('mode')!='lark': return user
        org=organization(data); row=db.get(PersonRow,(org,user['id']))
        if row:
            result=deepcopy(row.data)
            if reconcile_company_admin(db,org,result):
                row.data=deepcopy(result);db.commit()
            require(not result.get('identity_app_id') or result['identity_app_id']==cfg.get('LARK_APP_ID'),
                    '人員身分屬於另一 Lark 應用，請重新核對',403)
            # Bootstrap only explicitly configured people, once. A later manual
            # revocation must not be silently undone by each request.
            if user['id'] in capability_approvers and not result.get('capability_config_applied'):
                result['capabilities']=list(dict.fromkeys(result.get('capabilities',[])+['approve_capability']))
                result.update(capability_config_applied=True,capability_config_applied_at=now(),authz_version=result.get('authz_version',0)+1)
                row.data=result; db.commit()
            if admission_required: require_admission(result,cfg.get('LARK_APP_ID'))
            if data['wid'].startswith('test-'):
                overlay=db.get(PersonRow,(data['wid'],user['id']))
                result=test_profile(result,overlay.data if overlay else None)
            from .business_policy import refresh_business_authority
            refresh_business_authority(result,cfg)
            return result
        # Existing installations migrate the explicitly configured role once.
        result=deepcopy(user); result['role']=role_map.get(user['id'],user.get('role','member'))
        if admission_required:
            if role_map.get(user['id'])=='manager': result['bootstrap_admin']=True
            require_admission(result,cfg.get('LARK_APP_ID'))
        result['capabilities']=initial_capabilities(user['id'],result['role'])
        result.setdefault('default_workspace','test' if result['role']=='manager' else 'production')
        result.setdefault('active',True)
        db.add(PersonRow(organization_id=org,person_id=user['id'],data=result)); db.commit()
        return result
    def identity(request):
        with phase(request,'identity'): return _identity(request)
    def _identity(request):
        data=read_cookie(request); require(data is not None,'請先登入',401)
        with sessions() as db:
            if data.get('mode')=='lark':
                auth=db.get(AuthRow,data.get('sid')); require(auth is not None and auth.data.get('expires',0)>datetime.now(timezone.utc).timestamp(),'登入已過期，請重新登入',401)
                require(auth.data['wid']==data['wid'],'工作區驗證失敗',401)
            row=db.get(WorkspaceRow,data['wid']); require(row is not None,'工作區不存在',401)
            if data.get('mode')=='lark':
                profile=db.get(PersonRow,(organization(data),data['uid']))
                user=deepcopy(profile.data) if profile else find(load(db,row)['users'],data['uid'],'登入人員')
            else: user=find(load(db,row,collections=('users',))['users'],data['uid'],'登入人員')
            if (data.get('mode')=='lark' and not data['wid'].startswith('test-')
                    and request.url.path != '/api/live/status'):
                from .live_read.admission import ensure_roster_for_admission
                # End the DB read transaction before a blocking roster refresh.
                db.rollback()
                ensure_roster_for_admission(app.state.live_read,organization(data),user)
                db.expire_all()
                profile=db.get(PersonRow,(organization(data),data['uid']))
                if profile: user=deepcopy(profile.data)
            user=person_identity(db,data,user)
            require(user.get('active',True),'帳號已停權',403)
            if data.get('mode')=='lark' and admission_required:
                from .production_access import require_access
                recovery_routes={('GET','/api/session'),('POST','/api/logout'),
                    ('POST','/api/people/sync'),('GET','/api/admin/runtime-health')}
                access=require_access(user,cfg.get('LARK_APP_ID'),cfg=cfg,tenant=organization(data).removeprefix('lark-'),allow_recovery=(request.method,request.url.path) in recovery_routes)
                data={**data,'access_mode':access}
        return data,user
    def public_ws(data,wid,user,mode=None,owned=False):
        """owned=True: caller passes a fresh load nobody else uses; it is projected in place (no deepcopy)."""
        file_categories=categories(data); verification=data.get('native_definition_verification')
        result=strip_migration_archive(data) if owned else public_copy(data)
        from .source_case_policy import filter_visible_cases
        filter_visible_cases(result)
        result['workspace_id']=wid
        result['file_categories']=file_categories
        if not result['projects'] or any(p.get('source_kind')=='lark' for p in result['projects']): result['as_of']=now()[:10]
        upgrade(result)
        result['environment']=result.get('environment','demo' if any(p.get('source_kind')=='demo' for p in result['projects']) else 'production')
        result['policy_summary']=[project_summary(result,p) for p in result['projects']]
        # Workspace namespaces are assigned by the server. Match /api/actions:
        # signed demo sessions and test namespaces may simulate, never submit.
        result['approval_connection']=approval_connection(cfg,simulation_available=(mode=='demo' if mode is not None else wid.startswith('demo-')) or wid.startswith('test-'),definition_verification=verification)
        result.pop('native_definition_verification',None)
        from .case_cutover import project_execution_view
        for project in result['projects']:
            project.update(project_execution_view(result,project))
        return filter_private_workspace(result,user)
    def persist_mutation(wid,expected,callback,receipt_key=None,fingerprint=None,actor_id=None,action_name='mutation',project_versions=None):
        require(bool(actor_id),'缺少操作人員身分',403)
        with sessions.begin() as db:
            row=db.execute(select(WorkspaceRow).where(WorkspaceRow.id==wid).with_for_update()).scalar_one()
            if receipt_key:
                receipt=db.get(Receipt,receipt_key)
                if receipt:
                    require(receipt.fingerprint==fingerprint,'request_id 已用於不同操作',409)
                    state=load(db,row)
                    return public_ws(state,wid,find(state['users'],actor_id,'登入人員'))
            state=load(db,row)
            if project_versions:
                require(all(find(state['projects'],pid).get('concurrency_version',0)==version for pid,version in project_versions.items()),'此案件已被更新，請核對最新內容後重試',409)
            else: require(row.version==expected,'資料已被其他操作更新，請重新整理後重試',409)
            expected=row.version
            if actor_id: require(find(state['users'],actor_id).get('active',True),'帳號已停權',403)
            if admission_required and wid.startswith(('lark-','test-lark-')):
                person=db.get(PersonRow,(wid.removeprefix('test-'),actor_id))
                from .production_access import require_access
                require_access(person.data if person else None,cfg.get('LARK_APP_ID'),cfg=cfg,tenant=wid.removeprefix('test-').removeprefix('lark-'))
            if wid.startswith('lark-'): state['as_of']=now()[:10]
            before=audit.entities(state)
            callback(state); state['version']=row.version+1
            if wid.startswith(('lark-','test-lark-')):
                org=wid
                for person in state['users']:
                    profile=db.get(PersonRow,(org,person['id']))
                    if profile:
                        if profile.data!=person: profile.data=deepcopy(person)
                    else: db.add(PersonRow(organization_id=org,person_id=person['id'],data=deepcopy(person)))
            root=storage.save(db,BusinessRow,wid,state)
            updated=db.execute(update(WorkspaceRow).where(WorkspaceRow.id==wid,WorkspaceRow.version==expected).values(version=expected+1,data=root))
            require(updated.rowcount==1,'資料版本衝突，請重新整理',409)
            if receipt_key: db.add(Receipt(id=receipt_key,fingerprint=fingerprint,result={'version':state['version']}))
            db.add(audit.record(AuditRow,wid,actor_id,action_name,request_id=receipt_key,
                               details={'version':state['version'],'changes':audit.changes(before,state),
                                        'business_authority':{k:v for k,v in find(state['users'],actor_id).get('_business_authority',{}).items()
                                                              if k in ('grant_id','decision_ref','scopes')}}))
            return public_ws(state,wid,find(state['users'],actor_id,'登入人員'))

    @app.get('/api/health')
    def health():
        with engine.connect() as connection: connection.execute(select(1))
        return {'status':'ok','mode':'demo' if demo else 'lark','database':'postgresql' if engine.dialect.name=='postgresql' else 'sqlite'}

    def features():
        return {'features':{'workspace_shell':True}} if shell_enabled else {}

    @app.get('/api/session')
    def get_session(request:Request):
        from fastapi.responses import JSONResponse
        data=read_cookie(request)
        if not data and demo:
            data={'mode':'demo','uid':'u-pm','wid':'demo-'+uid()}; ensure_workspace(data['wid'])
            response=JSONResponse({'user':USERS[0],'users':USERS,'mode':'demo','auth_configured':oauth_configured,**features()}); set_cookie(response,data); return response
        if not data: return {'user':None,'users':[],'mode':'lark','auth_configured':oauth_configured}
        try: data,user=identity(request)
        except HTTPException: return {'user':None,'users':[],'mode':'lark','auth_configured':oauth_configured}
        if data.get('access_mode')=='recovery':
            return {'user':public_person(user,include_authority=True),'users':[],'mode':data['mode'],'workspace_id':data['wid'],
                    'environment':'test' if data['wid'].startswith('test-') else 'production','auth_configured':oauth_configured,'access_mode':'recovery'}
        with phase(request,'load'),sessions() as db: users=load(db,db.get(WorkspaceRow,data['wid']),collections=('users',))['users']
        return {'user':public_person(user,include_authority=True),'users':[public_person(person) for person in users],'mode':data['mode'],'workspace_id':data['wid'],'environment':'test' if data['wid'].startswith('test-') else data['mode'],'auth_configured':oauth_configured,'access_mode':data.get('access_mode','normal'),**features()}

    @app.post('/api/demo/session')
    async def demo_session(request:Request):
        from fastapi.responses import JSONResponse
        require(demo,'未啟用示範角色切換',403); data,user=identity(request); require(data['mode']=='demo','正式身分不可切換為示範角色',403)
        body=await json_object(request)
        with sessions() as db: users=load(db,db.get(WorkspaceRow,data['wid']))['users']
        user=find(users,body.get('user_id'),'角色'); require(user.get('active',True),'帳號已停權'); data['uid']=user['id']
        response=JSONResponse({'user':user,'users':users,'mode':'demo','auth_configured':oauth_configured}); set_cookie(response,data); return response

    @app.post('/api/logout')
    def logout(request:Request):
        from fastapi.responses import JSONResponse
        data=read_cookie(request)
        if data and data.get('sid'):
            with sessions.begin() as db:
                row=db.get(AuthRow,data['sid'])
                if row: db.delete(row)
        response=JSONResponse({'ok':True}); response.delete_cookie('meegle_session'); return response

    def shell_response(request,data,user,coordinator):
        """Slim index-backed workspace; None means the index cannot vouch for it, so the caller serves the full workspace."""
        from fastapi.responses import JSONResponse, Response
        from . import shell, index_reads
        wid=data['wid']
        with sessions() as db:
            row=db.get(WorkspaceRow,wid)
            with phase(request,'load'):
                if not index_reads.ready(db,BusinessRow,row): return None
                state=load(db,row,collections=('users','delegations','approved_leave_delegations'))
            today=now()[:10]; facts=shell.prepare(state,user,today)
            tag=shell.etag(wid,user,row.version,today,state['users'])
            if tag in [v.strip() for v in request.headers.get('if-none-match','').split(',')]: return Response(status_code=304,headers={'ETag':tag})
            with phase(request,'project'):
                result=shell.build(db,BusinessRow,row,state,user,facts,today,approval_connection(cfg,simulation_available=(data['mode']=='demo') or wid.startswith('test-'),definition_verification=state.get('native_definition_verification')))
        result['freshness']=coordinator.status(wid)
        as_of=result['freshness']['datasets']['sources']['as_of']
        return JSONResponse(result,headers={'ETag':tag,**({'X-Data-As-Of':as_of} if as_of else {})})

    @app.get('/api/workspace')
    def workspace(request:Request,scope:str=''):
        data,user=identity(request)
        coordinator=app.state.live_read
        coordinator.ensure(data['wid'],'sources')
        coordinator.ensure(data['wid'],'attendance')
        if scope=='shell' and shell_enabled:
            shell_result=shell_response(request,data,user,coordinator)
            if shell_result is not None: return shell_result
        with sessions() as db:
            with phase(request,'load'): state=load(db,db.get(WorkspaceRow,data['wid']))
            with phase(request,'project'): result=public_ws(state,data['wid'],user,data['mode'],owned=True)
        result['freshness']=coordinator.status(data['wid'])
        as_of=result['freshness']['datasets']['sources']['as_of']
        from fastapi.responses import JSONResponse
        return JSONResponse(result,headers={'X-Data-As-Of':as_of} if as_of else {})

    @app.get('/api/company-dashboard')
    def company_dashboard(request:Request,offset:int=0,limit:int=100,q:str='',group:str='',source_status:str='',attention:str='',lifecycle:str=''):
        data,user=identity(request)
        require(offset>=0 and 1<=limit<=250 and attention in ('','overdue','review'),'駕駛艙查詢參數錯誤',422)
        require(len(q)<=240 and len(group)<=120 and len(source_status)<=120 and len(lifecycle)<=120,'查詢文字過長',422)
        with sessions() as db: safe=public_ws(load(db,db.get(WorkspaceRow,data['wid'])),data['wid'],user,data['mode'],owned=True)
        from .company_dashboard import overview
        return overview(safe,offset=offset,limit=limit,q=q,group=group,source_status=source_status,attention=attention,lifecycle=lifecycle)

    @app.get('/api/projects')
    def projects(request:Request,q:str='',status:str='',owner:str='',offset:int=0,limit:int=30,view:str='',tab:str='formal',sort:str='due',dir:str='asc'):
        data,user=identity(request); require(0<=offset and 1<=limit<=100,'分頁參數錯誤',422)
        from . import index_reads
        if view:
            from . import shell
            require(view=='overview' and shell_enabled,'不支援的清單檢視',422)
            require(tab in shell.TABS and sort in shell.SORTS and dir in ('asc','desc') and len(q)<=240,'清單查詢參數錯誤',422)
            with phase(request,'load'),sessions() as db:
                row=db.get(WorkspaceRow,data['wid'])
                require(index_reads.ready(db,BusinessRow,row),'案件索引尚未就緒，請稍後重試',503)
                return shell.overview_page(db,BusinessRow,row,load(db,row,collections=()),now()[:10],q=q,status=status,owner=owner,tab=tab,sort=sort,desc=dir=='desc',offset=offset,limit=limit)
        with phase(request,'load'),sessions() as db:
            row=db.get(WorkspaceRow,data['wid'])
            if index_reads.ready(db,BusinessRow,row) and index_reads.casefold_safe(q):
                return index_reads.project_page(db,BusinessRow,data['wid'],load(db,row,collections=()).get('environment'),q=q,status=status,owner=owner,offset=offset,limit=limit)
            state=load(db,row,collections=('projects',))
        from .source_case_policy import visible_project
        with phase(request,'project'): items=[p for p in state['projects'] if visible_project(state,p) and (not q or q.casefold() in ' '.join(str(p.get(k,'')) for k in ('code','name','client')).casefold()) and (not status or p['status']==status) and (not owner or p['pm_id']==owner)]
        items.sort(key=lambda p:(p.get('due_date') or '9999',p['id']))
        return {'total':len(items),'offset':offset,'limit':limit,'items':[dict(id=p['id'],code=p['code'],name=p['name'],status=p['status'],source_status=p.get('source_status'),pm_id=p['pm_id'],due_date=p.get('due_date')) for p in items[offset:offset+limit]]}

    # Already in the shell, or large and unrelated to one case (the full-workspace screens read them on demand).
    DETAIL_SKIP=('_partial','projects','users','calendar','source_status','file_categories','approval_connection','freshness','environment','workspace_id','as_of','version','work_schedules','daily_unmatched')

    @app.get('/api/projects/{project_id}')
    def project_detail(request:Request,project_id:str):
        """One project tree and the records of that case, projected exactly like /api/workspace (same visibility and privacy filters).

        Lists keep this case's rows plus global rows without a project_id (templates, catalogues); the rest of the workspace is not sent.
        """
        data,user=identity(request); require(shell_enabled,'尚未啟用單一案件讀取',404)
        with sessions() as db:
            with phase(request,'load'): state=load(db,db.get(WorkspaceRow,data['wid']),project_ids=[project_id])
            with phase(request,'project'): result=public_ws(state,data['wid'],user,data['mode'],owned=True)
        require(len(result['projects'])==1,'找不到這個案件',404)
        mine=lambda item:not isinstance(item,dict) or item.get('project_id',project_id)==project_id
        records={k:[i for i in v if mine(i)] if isinstance(v,list) else v for k,v in result.items() if k not in DETAIL_SKIP}
        return dict(records,scope='project',version=result['version'],as_of=result['as_of'],project=result['projects'][0])

    @app.get('/api/daily-reports')
    def daily_reports(request:Request,project_id:str='',department:str='',actor_id:str='',date_from:str='',date_to:str='',status:str='all',q:str='',offset:int=0,limit:int=50):
        from .source_projection import daily_index
        data,user=identity(request)
        require(offset>=0 and 1<=limit<=100,'分頁參數錯誤',422)
        require(status in ('all','matched','unmatched','source_missing'),'日報狀態錯誤',422)
        with sessions() as db: state=load(db,db.get(WorkspaceRow,data['wid']))
        from .source_case_policy import filter_visible_cases
        filter_visible_cases(state);filter_private_workspace(state,user)
        return daily_index(state,project_id=project_id,department=department,actor_id=actor_id,date_from=date_from,date_to=date_to,status=status,q=q,offset=offset,limit=limit)

    AUDIT_BATCH=100

    def audit_page(db,wid,offset,limit,project_id,accept,prefilter=()):
        """Keyset-scan action_audit newest-first in bounded batches.

        Visibility is decided per row by ``accept`` (never after an unsafe LIMIT): every
        batch is fully filtered before the next keyset page is read, and the scan stops
        once the requested page plus one lookahead row is known. Memory is bounded
        by the page and batch sizes; reads stop after offset+limit+1 accepted
        rows or exhaustion (sparse visibility can still
        require scanning the history). ``total`` is exact when history is
        exhausted, otherwise a lower bound (``has_more`` is true).
        """
        base=select(AuditRow).where(AuditRow.workspace_id==wid,*prefilter)
        if project_id:  # conservative superset; exact check stays in ``accept``
            # SQLite JSON can escape Unicode; PostgreSQL JSON casts can retain it.
            encodings={json.dumps(project_id,ensure_ascii=ascii_only) for ascii_only in (True,False)}
            patterns=[value.replace('\\','\\\\').replace('%','\\%').replace('_','\\_') for value in encodings]
            base=base.where(or_(*[cast(AuditRow.data,String).like('%'+pattern+'%',escape='\\') for pattern in patterns]))
        need=offset+limit+1; items=[]; accepted=0; last=None; exhausted=False
        while accepted<need:
            query=base
            if last: query=query.where(or_(AuditRow.created_at<last[0],and_(AuditRow.created_at==last[0],AuditRow.id<last[1])))
            rows=list(db.scalars(query.order_by(AuditRow.created_at.desc(),AuditRow.id.desc()).limit(AUDIT_BATCH)))
            for row in rows:
                item=accept(row)
                if item is not None:
                    accepted+=1
                    if offset<accepted<=need: items.append(item)
            if len(rows)<AUDIT_BATCH: exhausted=True; break
            last=(rows[-1].created_at,rows[-1].id)
        has_more=accepted>offset+limit
        total=accepted if exhausted else need
        return {'items':items[:limit],'total':total,'offset':offset,'limit':limit,'has_more':has_more}

    @app.get('/api/audit')
    def action_audit(request:Request,project_id:str='',offset:int=0,limit:int=50):
        data,user=identity(request); require(offset>=0 and 1<=limit<=100,'分頁參數錯誤',422)
        with sessions() as db:
            state=load(db,db.get(WorkspaceRow,data['wid']),collections=('projects',))
            from .source_case_policy import visible_project
            visible={p['id'] for p in state.get('projects',[]) if visible_project(state,p)}
            manager=user.get('role')=='manager'
            def accept(row):
                details=deepcopy(row.data)
                refs={details['project_id']} if details.get('project_id') else set()
                for change in details.get('changes',[]):
                    if change.get('project_id'):refs.add(change['project_id'])
                    elif change.get('kind')=='project':refs.add(change.get('id'))
                if refs-visible:return None
                if not manager:
                    if row.action.startswith(('admin_','company_admin_','person','delegation','people_')) and row.actor_id!=user['id']: return None
                    details['changes']=[c for c in details.get('changes',[]) if c['kind'] not in ('users','delegations') or c['id']==user['id']]
                if project_id and details.get('project_id')!=project_id and not any(c.get('project_id')==project_id or (c['kind']=='project' and c['id']==project_id) for c in details.get('changes',[])): return None
                return dict(id=row.id,actor_id=row.actor_id,action=row.action,created_at=row.created_at,**details)
            prefilter=()
            if not manager:  # same rule as ``accept``, pushed into SQL to skip rows early
                prefilter=(or_(AuditRow.actor_id==user['id'],
                    and_(*[func.substr(AuditRow.action,1,len(x))!=x for x in ('admin_','company_admin_','person','delegation','people_')])),)
            return audit_page(db,data['wid'],offset,limit,project_id,accept,prefilter)

    @app.get('/api/admin/index-health')
    def index_health(request:Request):
        return index_health_run(request,False)

    @app.post('/api/admin/index-health/repair')
    def index_health_repair(request:Request):
        return index_health_run(request,True)

    def index_health_run(request,fix):
        from . import index_tables
        data,user=identity(request)
        require(user.get('active',True) and user.get('role')=='manager','索引健康檢查僅限公司管理員',403)
        wid=data['wid']
        with sessions.begin() as db:
            row=db.get(WorkspaceRow,wid)
            require(not fix or db.info.get('index_tables'),'索引表未啟用，無法修復',409)
            if fix:  # serialize with writers while the index is rewritten
                require(db.execute(update(WorkspaceRow).where(WorkspaceRow.id==wid,WorkspaceRow.version==row.version).values(version=row.version)).rowcount==1,'資料版本衝突，請重新操作',409)
            state=upgrade(storage.load(db,BusinessRow,row)); state['version']=row.version
            report=index_tables.reconcile(db,BusinessRow,wid,state)
            report['enabled']=bool(db.info.get('index_tables')); report['repaired']=False
            if fix and not report['healthy']:
                index_tables.repair(db,BusinessRow,wid,state,report)
                db.add(audit.record(AuditRow,wid,user['id'],'admin_index_repair',details={'projects':report['dirty_projects'][:50],'project_count':len(report['dirty_projects']),
                       'counter_drift':len(report['counters']['drift']),'tasks':{k:len(report['tasks'][k]) for k in ('missing','extra','stale')}}))
                report['repaired']=True
        return report

    @app.get('/api/admin/audit/history')
    def historical_action_audit(request:Request,project_id:str='',offset:int=0,limit:int=50):
        data,user=identity(request)
        require(user.get('active',True) and user.get('role')=='manager','歷史稽核診斷僅限公司管理員',403)
        require(offset>=0 and 1<=limit<=100,'分頁參數錯誤',422)
        # This deliberate administrative endpoint exposes metadata, not archived
        # source snapshots, employee fields, comments or approval evidence.
        def accept(row):
            details=row.data or {}; refs={details['project_id']} if details.get('project_id') else set()
            for change in details.get('changes',[]):
                if change.get('project_id'):refs.add(change['project_id'])
                elif change.get('kind')=='project':refs.add(change.get('id'))
            if project_id and project_id not in refs:return None
            return {'id':row.id,'actor_id':row.actor_id,'action':row.action,'created_at':row.created_at,
                'result':details.get('result'),'request_id':details.get('request_id'),
                'project_ids':sorted(r for r in refs if r),'change_count':len(details.get('changes',[]))}
        with sessions() as db: return audit_page(db,data['wid'],offset,limit,project_id,accept)

    @app.post('/api/actions')
    def actions(body:Action,request:Request):
        data,user=identity(request); raw=body.model_dump()
        from .input_validation import validate_action
        try:validate_action(raw)
        except HTTPException as exc:
            with sessions.begin() as db:
                db.add(audit.record(AuditRow,data['wid'],user['id'],body.action,result='denied',request_id=body.request_id,
                                   details={'status':exc.status_code,'reason':'validation'}))
            raise
        fingerprint=hashlib.sha256(json.dumps({k:v for k,v in raw.items() if k not in ('version','request_id','project_versions')},sort_keys=True).encode()).hexdigest()
        versions=None
        if body.project_versions:
            scoped=body.action.startswith(('task_','comment','input_','evidence_','review_','delivery_','file_','participants_')) and body.action!='file_category_save'
            scoped=scoped or body.action in {'node_complete','project_roles','sop_apply',
                'approval_create','approval_submit','approval_confirm','approval_lark','approval_execute','approval_withdraw'}
            wanted={body.project_id} if body.project_id else set()
            if body.action=='task_batch_complete': wanted={i.get('project_id') for i in body.payload.get('items',[]) if isinstance(i,dict)}
            if scoped and wanted and None not in wanted:
                require(set(body.project_versions)==wanted,'案件版本範圍不符',422); versions=body.project_versions
        def mutate(ws):
            # Re-check the actor inside the mutation after waiting for the lock.
            current=find(ws['users'],user['id']); require(current.get('active',True),'帳號已停權')
            if versions and body.action in {'approval_submit','approval_confirm','approval_lark','approval_execute','approval_withdraw','sop_apply'}:
                collection,key=('sop_requests','id') if body.action=='sop_apply' else ('approvals','approval_id')
                target=find(ws[collection],body.payload.get(key),'案件申請')
                require(target.get('project_id')==body.project_id,'申請與案件版本範圍不符',422)
            if body.action=='file_category_save':
                save_category(ws,current,body.payload); return
            from .case_cutover import assign_execution,require_execution
            if body.action=='case_execution_assign':
                assign_execution(ws,current,body.project_id,body.payload.get('execution_system'),body.payload.get('reason'))
                return
            affected_ids={i.get('project_id') for i in body.payload.get('items',[]) if isinstance(i,dict)} if body.action=='task_batch_complete' else ({body.project_id} if body.project_id else None)
            affected=[p for p in ws['projects'] if affected_ids is None or p['id'] in affected_ids]
            if affected_ids:
                for project in affected:require_execution(ws,project)
            hashes={n['id']:review_hash(p,n) for p in affected for n in p['nodes']}
            if not apply_learning(ws,current,raw,data['mode']=='demo' or data['wid'].startswith('test-')) and not apply_operation(ws,current,raw,data['mode']=='demo' or data['wid'].startswith('test-'),cfg):
                apply_action(ws,current,raw,data['mode']=='demo' or data['wid'].startswith('test-'))
                for p in affected:
                    for n in p['nodes']:
                        if hashes.get(n['id'])!=review_hash(p,n): invalidate(n,'工作內容變更')
                    from .operations import refresh_project_state
                    refresh_project_state(p,ws)
                if body.action=='task_start':
                    p=find(ws['projects'],body.project_id); p['execution_status']='in_progress'
            if body.action=='task_update':
                for p in ws['projects']:
                    for n in p['nodes']:
                        for t in n['tasks']:
                            if t['id']==body.task_id: t['manual_updated']=True
        try:
            with phase(request,'mutate'): return persist_mutation(data['wid'],body.version,mutate,f"{data['wid']}:{user['id']}:{body.request_id}",fingerprint,actor_id=user['id'],action_name=body.action,project_versions=versions)
        except HTTPException as exc:
            with sessions.begin() as db:
                db.add(audit.record(AuditRow,data['wid'],user['id'],body.action,result='denied',request_id=body.request_id,
                                   details={'status':exc.status_code,'project_id':body.project_id,'node_id':body.node_id,'task_id':body.task_id}))
            raise

    @app.post('/api/files')
    async def upload(request:Request,file:UploadFile=File(...),project_id:str=Form(...),node_id:str=Form(''),direction:str=Form(...),version:int=Form(...),category_id:str=Form('other'),file_key:str=Form(''),project_version:int|None=Form(None)):
        data,user=identity(request); require(direction in ('input','output','evidence'),'文件用途錯誤',400)
        from .case_cutover import require_execution
        def authorize_upload(ws,actor):
            p=find(ws['projects'],project_id,'案件'); n=find(p['nodes'],node_id,'節點') if node_id else None
            require_execution(ws,p)
            require(is_pm(actor,p) or (n and (n['owner_id']==actor['id'] or any(is_owner(actor,t,ws) for t in n['tasks']))))
            validate_category(ws,category_id)
            return p,n
        # Check before writing any uploaded bytes, then repeat under the mutation lock.
        with sessions() as db:authorize_upload(load(db,db.get(WorkspaceRow,data['wid'])),user)
        from .upload_policy import attachment_name
        safe_name=attachment_name(file.filename)
        ident=uid(); folder=upload_dir/hashlib.sha256(data['wid'].encode()).hexdigest(); folder.mkdir(exist_ok=True); target=folder/ident
        size=0;content_digest=hashlib.sha256()
        try:
            with target.open('xb') as handle:
                while chunk:=await file.read(1024*1024):
                    size+=len(chunk); require(size<=20*1024*1024,'附件不得超過 20 MB（Lark 保存上限）',413); handle.write(chunk);content_digest.update(chunk)
            def mutate(ws):
                # The uploader's role/capabilities may have changed while the
                # request body was being read. Authorize and attribute the
                # durable mutation using the profile reloaded under the lock.
                actor=find(ws['users'],data['uid'],'登入人員')
                require(actor.get('active',True),'帳號已停權',403)
                if data.get('mode')=='lark' and admission_required:
                    require_access(actor,cfg.get('LARK_APP_ID'),cfg=cfg,
                                   tenant=data['wid'].removeprefix('test-').removeprefix('lark-'))
                p,n=authorize_upload(ws,actor)
                related=[x for x in p['files'] if x.get('file_key',x['id'])==file_key] if file_key else []
                if file_key:
                    require(bool(related),'原文件不存在，不能新增版本',404)
                    require(all(x.get('node_id')==(node_id or None) and x.get('category_id','other')==category_id and x['direction']==direction for x in related),'新版本須維持原文件節點、分類及用途',409)
                key=file_key or ident
                number=1+max((int(x.get('version',1)) for x in related),default=0)
                p['files'].append(dict(id=ident,file_key=key,category_id=category_id,name=safe_name,node_id=node_id or None,direction=direction,version=str(number),uploaded_by=actor['id'],created_at=now(),size=size,sha256=content_digest.hexdigest(),url=f'/api/files/{ident}/download',storage='local'))
                from .operations import queue
                queue(ws,'file',actor,{'project_id':project_id,'file_id':ident},'file:'+ident)
                p['files'][-1].update(remote_status='queued',auto_store_requested=True)
                event(ws,actor,'file_upload',project_id,node_id,message=f'上傳 {safe_name}')
            return persist_mutation(data['wid'],version,mutate,actor_id=user['id'],action_name='file_upload',project_versions={project_id:project_version} if project_version is not None else None)
        except Exception:
            target.unlink(missing_ok=True); raise
        finally: await file.close()

    @app.get('/api/files/{file_id}/download')
    def download(file_id:str,request:Request):
        data,user=identity(request)
        with sessions() as db: ws=load(db,db.get(WorkspaceRow,data['wid']))
        from .source_case_policy import visible_project
        match=next((f for p in ws['projects'] if visible_project(ws,p) for f in p['files'] if f['id']==file_id and f['storage']=='local' and not f.get('withdrawn')),None); require(match is not None,'附件不存在或無權存取',404)
        path=upload_dir/hashlib.sha256(data['wid'].encode()).hexdigest()/file_id
        require(path.resolve().is_relative_to(upload_dir) and path.is_file(),'附件檔案不存在',404)
        return FileResponse(path,filename=match['name'],media_type='application/octet-stream',headers={'Content-Disposition':"attachment; filename*=UTF-8''"+__import__('urllib.parse',fromlist=['quote']).quote(match['name'])})

    def public_source_response(state,snapshot,user):
        # Shared by GET and POST sync: the raw snapshot stays in the internal cache.
        from .workspace_projection import public_source_cache
        from .source_case_policy import visible_source_snapshot
        return public_source_cache(visible_source_snapshot(state,snapshot),user)

    @app.get('/api/sources')
    def sources(request:Request):
        data,user=identity(request)
        app.state.live_read.ensure(data['wid'],'sources')
        freshness=app.state.live_read.status(data['wid'])
        if data['mode']!='lark' or data['wid'].startswith('test-'):
            result={'configured':False,'last_sync':None,'status':'requires_login','message':'測試區使用隔離試行案；請切換正式工作區讀取 V4','tables':[],'records':[]}
        else:
            with sessions() as db:
                cache=db.get(CacheRow,data['wid']);state=load(db,db.get(WorkspaceRow,data['wid']))
            result=public_source_response(state,cache.data,user) if cache else {'configured':bool(configuration(cfg)),'last_sync':None,'status':'never','message':'尚未同步來源','tables':[],'records':[]}
        return {**result,'as_of':freshness['datasets']['sources']['as_of'],'freshness':freshness}

    @app.post('/api/sources/cutover-baseline')
    async def source_case_baseline(request:Request):
        data,user=identity(request)
        require(data['mode']=='lark' and not data['wid'].startswith('test-'),'切換基準僅限正式公司工作區',403)
        require(user.get('role')=='manager','需公司管理員',403)
        raise HTTPException(410,'V4 與報價總表全部來源案件皆納入工作台，已不需建立新舊案切換基準；本操作未變更資料')

    @app.post('/api/sources/sync')
    def sync(request:Request):
        data,user=identity(request); require(data['mode']=='lark','請使用公司 Lark 登入後同步正式來源',403); require(user['role'] in ('pm','manager') or capable(user,'manage_sources'),'需要來源同步權限',403)
        require(not data['wid'].startswith('test-'),'測試工作區不可直接同步正式 V4；請使用隔離試行複本',403)
        if live_enabled(data['wid']):
            authorize_live(data['wid'],'sources',user)
            response=manual_live(data['wid'],'sources',user)
            if response: return response
            with sessions() as db:
                cache=db.get(CacheRow,data['wid']); state=load(db,db.get(WorkspaceRow,data['wid']))
            freshness=app.state.live_read.status(data['wid'])
            return {**public_source_response(state,cache.data,user),'as_of':freshness['datasets']['sources']['as_of'],'freshness':freshness}
        with sessions() as db: auth=db.get(AuthRow,data['sid']); token=auth.data['access_token']
        snapshot=app.state.source_sync.sync(data['wid'],user['id'],token)
        with sessions() as db: state=load(db,db.get(WorkspaceRow,data['wid']))
        freshness=app.state.live_read.status(data['wid'])
        return {**public_source_response(state,snapshot,user),'as_of':freshness['datasets']['sources']['as_of'],'freshness':freshness}

    @app.post('/api/approvals/{approval_id}/refresh')
    async def refresh_approval(approval_id:str,request:Request):
        data,user=identity(request); require(data['mode']=='lark','原生審批查詢需公司 Lark 登入',403)
        body=await json_object(request)
        require(type(body.get('version')) is int and body['version']>=1,'請提供有效的工作區版本',422)
        instance_code=str(body.get('instance_code','')); require(bool(re.fullmatch(r'[A-Za-z0-9_-]{6,128}',instance_code)),'請提供有效 Lark 審批實例 ID',400)
        with sessions() as db:
            ws=load(db,db.get(WorkspaceRow,data['wid'])); approval=find(ws['approvals'],approval_id,'申請'); p=find(ws['projects'],approval['project_id'],'案件'); require(is_pm(user,p))
            token=db.get(AuthRow,data['sid']).data['access_token']
        try:
            with httpx.Client(timeout=25) as client:
                response=client.get(API+'/approval/v4/instances/detail',headers={'Authorization':'Bearer '+token},params={'instance_code':instance_code,'locale':'zh-TW','user_id_type':'open_id'})
                require(response.status_code==200,'Lark 審批讀取失敗',502); result=response.json(); require(result.get('code',0)==0,'目前身份無法讀取該 Lark 審批實例',403)
        except httpx.HTTPError: raise HTTPException(502,'Lark 審批服務暫時無法連線')
        remote=result.get('data',{}); expected=cfg.get('LARK_CHANGE_APPROVAL_CODE' if approval['type']=='change' else 'LARK_EXTENSION_APPROVAL_CODE')
        if expected: require((remote.get('definition_code') or remote.get('approval_code'))==expected,'此審批實例不屬於設定的審批定義',409)
        def mutate(state):
            target=find(state['approvals'],approval_id,'申請')
            # Do not turn an arbitrary reference into authorization to change project scope.
            target.update(lark_instance_code=instance_code,lark_external_status=remote.get('status','UNKNOWN'),lark_checked_at=now(),lark_binding_verified=False)
            target['history'].append({'action':'lark_refresh','actor_id':user['id'],'created_at':now(),'message':'唯讀取得原生審批狀態；尚未驗證此實例與案件範圍一致，不自動核准'})
            event(state,user,'approval_refresh',target['project_id'],message='查詢既有 Lark 審批狀態')
        return persist_mutation(data['wid'],body['version'],mutate,actor_id=user['id'])

    @app.post('/api/learning/sync')
    async def learning_sync(request:Request):
        from .features import require_learning
        require_learning()
        from .learning_sources import read_capabilities
        from .lark_adapter import LarkAdapter, RemoteFailure
        data,user=identity(request); require(data['mode']=='lark' and not data['wid'].startswith('test-'),'能力地圖唯讀同步需公司正式工作區',403)
        require(capable(user,'manage_training') or capable(user,'manage_sources'),'需要訓練或來源管理權限',403)
        body=await json_object(request)
        require(type(body.get('version')) is int and body['version']>=1,'請提供有效的工作區版本',422)
        with sessions() as db: token=db.get(AuthRow,data['sid']).data['access_token']
        adapter=LarkAdapter(token)
        try: catalog,bindings=read_capabilities(adapter)
        except RemoteFailure as exc: raise HTTPException(502,str(exc))
        finally: adapter.client.close()
        def mutate(state):
            state['capability_catalog']=catalog; state['capability_bindings']=bindings
            state['capability_source_status']={'status':'ready','last_sync':now(),'skills':len(catalog),'people_bindings':len(bindings),'message':'已讀取技能及能力關聯；未讀薪資金額'}
            event(state,user,'capability_source_sync',message='唯讀更新能力地圖來源')
        return persist_mutation(data['wid'],body['version'],mutate,actor_id=user['id'])

    @app.post('/api/people/sync')
    def sync_people(request:Request):
        data,user=identity(request)
        require(data['mode']=='lark','公司名冊同步需使用公司 Lark 身分',403)
        target=organization(data) if data.get('access_mode')=='recovery' else data['wid']
        if data.get('access_mode')=='recovery':ensure_workspace(target,True)
        if live_enabled(target):
            authorize_live(target,'roster',user)
            response=manual_live(target,'roster',user)
            if response: return response
            with sessions() as db: state=load(db,db.get(WorkspaceRow,target))
            return {**state['people_directory_status'],'freshness':app.state.live_read.status(target)}
        return {**app.state.people_directory.sync(target,user['id']),'freshness':app.state.live_read.status(target)}

    @app.post('/api/delegations/verify-approval')
    async def verify_delegation(request:Request):
        from .learning_sources import parse_leave
        from .lark_adapter import LarkAdapter, RemoteFailure
        data,user=identity(request); require(data['mode']=='lark' and not data['wid'].startswith('test-'),'請假來源核實需正式公司身分',403)
        require(capable(user,'manage_handover'),'需要交接管理權限',403)
        body=await json_object(request)
        require(type(body.get('version')) is int and body['version']>=1,'請提供有效的工作區版本',422)
        code=str(body.get('instance_code',''))
        require(bool(re.fullmatch(r'[A-Za-z0-9_-]{6,128}',code)),'審批實例編號格式錯誤',422)
        with sessions() as db: token=db.get(AuthRow,data['sid']).data['access_token']
        adapter=LarkAdapter(token)
        try:
            remote=adapter.request('GET','/approval/v4/instances/detail',params={'instance_code':code,'user_id_type':'open_id','locale':'zh-TW'})
            result=parse_leave(remote,code)
        except RemoteFailure as exc: raise HTTPException(502,str(exc))
        finally: adapter.client.close()
        def mutate(state):
            known={u['id'] for u in state['users']}
            require(result['principal_id'] in known and result['delegate_id'] in known,'請先核實兩人的公司身分',409)
            state['approved_leave_delegations']=[a for a in state['approved_leave_delegations'] if a['id']!=code]+[result]
            event(state,user,'delegation_source_verified',message='核實請假代理來源，未額外授予財務權限')
        return persist_mutation(data['wid'],body['version'],mutate,actor_id=user['id'])

    @app.get('/api/auth/lark/login')
    def lark_login(next:str='/'):
        require(oauth_configured,'尚未設定 Lark 登入應用、回呼網址或租戶白名單',503)
        require(next.startswith('/') and not next.startswith('//') and '\\' not in next and not any(ord(c)<32 for c in next),'返回路徑不合法',422)
        state=secrets.token_urlsafe(32)
        with sessions.begin() as db: db.add(AuthRow(id='oauth-'+state,data={'expires':datetime.now(timezone.utc).timestamp()+600,'next':next}))
        response=RedirectResponse('https://accounts.larksuite.com/open-apis/authen/v1/authorize?'+urlencode({'app_id':cfg['LARK_APP_ID'],'redirect_uri':cfg['LARK_REDIRECT_URI'],'state':state,'response_type':'code','scope':oauth_scopes}))
        response.set_cookie('lark_oauth_state',signer.dumps(state),httponly=True,secure=production,samesite='lax',max_age=600); return response

    @app.get('/api/auth/lark/callback')
    def lark_callback(request:Request,code:str='',state:str='',error:str='',error_description:str=''):
        require(oauth_configured,'Lark 登入未設定',503)
        try: cookie=signer.loads(request.cookies.get('lark_oauth_state',''),max_age=600)
        except BadSignature: raise HTTPException(400,'OAuth state 驗證失敗')
        require(bool(state) and secrets.compare_digest(cookie,state),'OAuth state 驗證失敗',400)
        with sessions.begin() as db:
            nonce=db.execute(select(AuthRow).where(AuthRow.id=='oauth-'+state).with_for_update()).scalar_one_or_none()
            require(nonce is not None and nonce.data['expires']>datetime.now(timezone.utc).timestamp(),'OAuth state 已失效或已使用',400)
            return_to=nonce.data.get('next','/'); db.delete(nonce)
        # Authorization servers return OAuth errors on the callback instead of
        # an authorization code when consent is denied or a scope is invalid.
        # Never forward provider-supplied descriptions into our URL or UI.
        if error:
            provider_errors={
                'access_denied':'authorization_denied',
                'invalid_scope':'app_configuration',
                'unauthorized_client':'app_configuration',
                'invalid_client':'app_configuration',
                'temporarily_unavailable':'provider_unavailable',
                'server_error':'provider_unavailable',
            }
            safe_code=provider_errors.get(error,'authorization_failed')
            response=RedirectResponse('/?auth_error='+safe_code,status_code=303)
            response.delete_cookie('lark_oauth_state'); return response
        try:
            with httpx.Client(timeout=25) as client:
                response=client.post(API+'/authen/v2/oauth/token',json={'grant_type':'authorization_code','client_id':cfg['LARK_APP_ID'],'client_secret':cfg['LARK_APP_SECRET'],'code':code,'redirect_uri':cfg['LARK_REDIRECT_URI']})
                if response.status_code>=400:
                    try: provider_error=response.json().get('error')
                    except (ValueError,TypeError,AttributeError): provider_error=None
                    detail=('使用者拒絕授權' if provider_error=='access_denied' else
                            'OAuth 應用權限設定需管理員檢查' if provider_error in ('invalid_scope','unauthorized_client','invalid_client') else
                            'Lark 登入服務暫時無法連線')
                    raise HTTPException(400 if provider_error in ('access_denied','invalid_scope','unauthorized_client','invalid_client') else 502,detail)
                token=response.json()
                granted_scope=token.get('scope')
                if isinstance(granted_scope,str) and granted_scope.strip():
                    missing_scopes=set(oauth_scopes.split())-set(granted_scope.split())
                    if missing_scopes: raise HTTPException(403,'OAuth 應用權限未授予：請管理員檢查 Lark 應用權限與發布版本')
                require(bool(token.get('access_token')),'Lark 授權碼交換失敗',401)
                response=client.get(API+'/authen/v1/user_info',headers={'Authorization':'Bearer '+token['access_token']}); response.raise_for_status(); info=response.json().get('data',{})
        except httpx.HTTPError: raise HTTPException(502,'Lark 登入服務暫時無法連線')
        tenant=info.get('tenant_key'); require(tenant in allowed_tenants,'此 Lark 租戶不在允許名單',403)
        oid=info.get('open_id'); require(bool(oid),'Lark 未返回有效使用者身分',401)
        role=role_map.get(oid,'member')
        org='lark-'+tenant; user={'id':oid,'identity_app_id':cfg['LARK_APP_ID'],'name':info.get('name') or oid,'role':role,'department':'公司成員','avatar':(info.get('name') or '?')[:1],'active':True,'capabilities':initial_capabilities(oid,role),'default_workspace':'production'}
        from .live_read.admission import ensure_roster_for_admission
        with sessions() as db:
            existing=db.get(PersonRow,(org,oid))
            admission_person=deepcopy(existing.data) if existing else user
        # The reloaded access policy preserves grants and bootstrap recovery on failure.
        ensure_roster_for_admission(app.state.live_read,org,admission_person,callback=True)
        with sessions.begin() as db:
            profile=db.execute(select(PersonRow).where(PersonRow.organization_id==org,PersonRow.person_id==oid).with_for_update()).scalar_one_or_none()
            if profile:
                user=deepcopy(profile.data); require(user.get('active',True),'帳號已停權',403)
                require(not user.get('identity_app_id') or user['identity_app_id']==cfg['LARK_APP_ID'],'此人員身分屬於另一 Lark 應用，請先核對',403)
                user['identity_app_id']=cfg['LARK_APP_ID']
                user['oauth_identity']={'source':'oauth_user_info','app_id':cfg['LARK_APP_ID'],'tenant':tenant,'open_id':oid,'verified_at':now()}
                if role=='manager' and user.get('role')=='manager': user['bootstrap_admin']=True
                elif role=='manager' and not user.get('authz_version'):
                    user.update(role='manager',bootstrap_admin=True,capabilities=initial_capabilities(oid,'manager'))
                require_access(user,cfg['LARK_APP_ID'],allow_recovery=True,cfg=cfg,tenant=tenant)
                reconcile_company_admin(db,org,user)
                if isinstance(info.get('user_id'),str) and info['user_id']:
                    user['attendance_identity']={'employee_type':'employee_id','employee_id':info['user_id'],'open_id':oid,'app_id':cfg['LARK_APP_ID'],'tenant':tenant,'verified_at':now(),'source':'oauth_user_info'}
                profile.data=deepcopy(user)
            else:
                user['oauth_identity']={'source':'oauth_user_info','app_id':cfg['LARK_APP_ID'],'tenant':tenant,'open_id':oid,'verified_at':now()}
                if role=='manager': user['bootstrap_admin']=True
                require_access(user,cfg['LARK_APP_ID'],allow_recovery=True,cfg=cfg,tenant=tenant)
                reconcile_company_admin(db,org,user)
                if isinstance(info.get('user_id'),str) and info['user_id']:
                    user['attendance_identity']={'employee_type':'employee_id','employee_id':info['user_id'],'open_id':oid,'app_id':cfg['LARK_APP_ID'],'tenant':tenant,'verified_at':now(),'source':'oauth_user_info'}
                db.add(PersonRow(organization_id=org,person_id=oid,data=user))
        # Company OAuth always enters the real company workspace. Historical
        # manager preferences must not silently turn a fresh login into a test.
        # Explicit authorized workspace switching remains available separately.
        wid=org
        ensure_workspace(wid,True); ensure_workspace(org,True); sid=uid()
        with sessions.begin() as db:
            db.add(AuthRow(id=sid,data={'wid':wid,'organization':org,'uid':oid,'access_token':token['access_token'],'granted_scope':token.get('scope',''),'requested_scope':oauth_scopes,'expires':datetime.now(timezone.utc).timestamp()+min(int(token.get('expires_in',7200)),8*3600)}))
            db.add(audit.record(AuditRow,wid,oid,'login',details={'environment':'test' if wid.startswith('test-') else 'production'}))
        response=RedirectResponse(return_to); set_cookie(response,{'mode':'lark','uid':oid,'wid':wid,'organization':org,'sid':sid}); response.delete_cookie('lark_oauth_state'); return response

    @app.post('/api/workspace/switch')
    async def switch_workspace(request:Request):
        from fastapi.responses import JSONResponse
        data,user=identity(request); require(data['mode']=='lark','需公司登入',403)
        body=await json_object(request); target=body.get('environment'); require(isinstance(target,str) and target in ('test','production'),'工作區錯誤',422)
        wid=('test-' if target=='test' else '')+organization(data); ensure_workspace(wid,True)
        with sessions.begin() as db:
            auth=db.execute(select(AuthRow).where(AuthRow.id==data['sid']).with_for_update()).scalar_one()
            require(auth.data.get('wid')==data['wid'],'工作區已在另一視窗切換，請重新載入',409)
            auth.data={**auth.data,'wid':wid}
            db.add(audit.record(AuditRow,wid,user['id'],'workspace_switch',details={'from':data['wid'],'to':wid}))
        data['wid']=wid; response=JSONResponse({'ok':True,'environment':target}); set_cookie(response,data); return response

    @app.post('/api/pilot/copy')
    async def copy_pilot(request:Request):
        data,user=identity(request); require(data['mode']=='lark' and user['role']=='manager','需公司管理員',403)
        body=await json_object(request); require(isinstance(body.get('project_id'),str),'請提供案件編號',422); org=organization(data); wid='test-'+org; ensure_workspace(wid,True)
        copied_files=[]
        try:
            with sessions.begin() as db:
                source=db.get(WorkspaceRow,org); require(source is not None,'正式工作區尚未建立',409); source_state=load(db,source)
                p=find(source_state['projects'],body.get('project_id'),'V4案件'); target=db.execute(select(WorkspaceRow).where(WorkspaceRow.id==wid).with_for_update()).scalar_one(); state=load(db,target); expected=target.version
                require(not any(x.get('pilot_source_id')==p['id'] for x in state['projects']),'此試行案已複製',409)
                occupied_ids=set()
                def collect_ids(value):
                    if isinstance(value,dict):
                        if isinstance(value.get('id'),str): occupied_ids.add(value['id'])
                        for child in value.values(): collect_ids(child)
                    elif isinstance(value,list):
                        for child in value: collect_ids(child)
                collect_ids(state['projects'])
                copy,id_map=_reidentify_pilot_project(p,occupied_ids); copy['pilot']=True
                # Preserve stable IDs in the isolated namespace, not production identities/recipients.
                copy['pm_id']=user['id']; copy['admin_id']=''; copy['supervisor_id']=''; copy['issuer_ids']=[user['id']]; copy['confirmation_issues']=[]
                for node in copy['nodes']:
                    node['owner_id']=user['id']; node['supervisor_id']=''; node['reviewers']=[]; node['collaborator_ids']=[]; node['review_cycles']=[]
                    for task in node['tasks']: task['owner_id']=user['id']; task.pop('proxy',None)
                copied_files=_copy_local_pilot_attachments(upload_dir,org,wid,copy,id_map)
                state['projects'].append(copy); state['environment']='test'; state['version']=expected+1
                root=storage.save(db,BusinessRow,wid,state)
                updated=db.execute(update(WorkspaceRow).where(WorkspaceRow.id==wid,WorkspaceRow.version==expected).values(version=expected+1,data=root))
                require(updated.rowcount==1,'工作區已變更，請重新操作',409)
                db.add(audit.record(AuditRow,wid,user['id'],'pilot_copy',details={'project_id':copy['id'],'source_workspace':org}))
        except Exception:
            for path in copied_files: path.unlink(missing_ok=True)
            raise
        return {'ok':True,'workspace':'test','project_id':copy['id']}

    from .integration_routes import register
    register(app,identity,load,persist_mutation,sessions,WorkspaceRow,BusinessRow,PersonRow,cfg,upload_dir)
    from .native_routes import register as register_native
    register_native(app,identity,load,persist_mutation,sessions,WorkspaceRow,cfg)
    from .native_poller import NativeApprovalPoller
    app.state.native_poller=NativeApprovalPoller(sessions,WorkspaceRow,BusinessRow,PersonRow,cfg)
    from .source_sync import SourceSyncService
    app.state.source_sync=SourceSyncService(sessions,WorkspaceRow,BusinessRow,PersonRow,AuthRow,CacheRow,cfg)
    from .people_directory import PeopleDirectoryService
    app.state.people_directory=PeopleDirectoryService(sessions,WorkspaceRow,BusinessRow,PersonRow,cfg)
    from .attendance_service import AttendanceScheduleService
    app.state.attendance_schedule=AttendanceScheduleService(sessions,WorkspaceRow,BusinessRow,PersonRow,cfg)
    from .live_read.coordinator import RefreshCoordinator
    from .live_read.datasets import build_refreshers
    from .live_read.routes import register as register_live, refresh as live_refresh
    app.state.live_read=RefreshCoordinator(sessions,CacheRow,build_refreshers(
        app.state.source_sync,app.state.people_directory,app.state.attendance_schedule),cfg)

    def live_enabled(wid):
        return app.state.live_read.status(wid)['enabled']

    def authorize_live(wid,dataset,user):
        if dataset=='sources':
            app.state.source_sync._authorize(wid,user['id'])
        else:
            service=app.state.people_directory if dataset=='roster' else app.state.attendance_schedule
            with sessions() as db:
                row=db.get(WorkspaceRow,wid)
                require(row is not None,'工作區不存在',404)
                service._actor(service._state(db,row),user['id'])

    def manual_live(wid,dataset,user):
        response=live_refresh(app.state.live_read,wid,[dataset],wait=True,force=True)
        if response.status_code!=200: return response
        action={'sources':'source_sync','roster':'people_directory_sync','attendance':'attendance_schedule_sync'}[dataset]
        with sessions.begin() as db:
            db.add(audit.record(AuditRow,wid,user['id'],action,details={'live_read':True}))
        return None

    def audit_live_refresh(wid,user,datasets):
        with sessions.begin() as db:
            db.add(audit.record(AuditRow,wid,user['id'],'live_refresh',
                                details={'live_read':True,'force':True,'datasets':datasets}))

    register_live(app,identity,app.state.live_read,authorize=authorize_live,audit=audit_live_refresh)
    from .runtime_health import register as register_runtime_health
    register_runtime_health(app,identity,sessions,CacheRow,cfg,workspace_model=WorkspaceRow,coordinator=app.state.live_read)

    @app.post('/api/attendance/sync')
    async def sync_attendance(request:Request):
        data,user=identity(request)
        body=await json_object(request)
        if live_enabled(data['wid']):
            from datetime import timedelta
            from zoneinfo import ZoneInfo
            start=datetime.now(ZoneInfo('Asia/Taipei')).date()
            require(body.get('date_from') in (None,'',start.isoformat())
                    and body.get('date_to') in (None,'',(start+timedelta(days=13)).isoformat()),
                    '即時讀取使用今天起14天班表，請使用預設日期區間',422)
            authorize_live(data['wid'],'attendance',user)
            response=manual_live(data['wid'],'attendance',user)
            if response: return response
            with sessions() as db: state=load(db,db.get(WorkspaceRow,data['wid']))
            return {**state['attendance_schedule_status'],'freshness':app.state.live_read.status(data['wid'])}
        return {**app.state.attendance_schedule.sync(data['wid'],user['id'],body.get('date_from'),body.get('date_to')),'freshness':app.state.live_read.status(data['wid'])}

    frontend=Path(cfg.get('FRONTEND_DIST',str(Path(__file__).resolve().parents[1]/'frontend'/'dist')))
    if frontend.is_dir():
        if (frontend/'assets').is_dir(): app.mount('/assets',StaticFiles(directory=frontend/'assets'),name='assets')
        @app.get('/{path:path}')
        def frontend_page(path:str):
            if path.startswith('api/'): raise HTTPException(404,'API 不存在')
            candidate=(frontend/path).resolve()
            if candidate.is_relative_to(frontend.resolve()) and candidate.is_file(): return FileResponse(candidate)
            return FileResponse(frontend/'index.html')
    return app

app=create_app()
