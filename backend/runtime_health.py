"""Manager-only runtime observability; no integration-success inference."""
from datetime import datetime, timezone
import json
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

WORKER_HEARTBEAT_MAX_AGE=300
WORKER_SUCCESS_MAX_AGE=900
BACKUP_MAX_AGE=36*60*60
BACKUP_CHECK_MAX_AGE=900
DIRECTORY_WARNING_AGE=600


def directory_status(sessions,workspace_model,cfg,now):
    from .production_access import DIRECTORY_MAX_AGE_SECONDS
    result={'status':'missing','last_success_at':None,'success_age_seconds':None,
            'max_age_seconds':DIRECTORY_MAX_AGE_SECONDS,'warning_age_seconds':DIRECTORY_WARNING_AGE,
            'blocking':True,'recovery_hint':'請檢查名冊來源讀取權限與背景同步，重新同步公司名冊成功後再驗證同事登入。'}
    if workspace_model is None or not cfg.get('LARK_WORKER_ORGANIZATION'):return result
    try:
        with sessions() as db:
            row=db.get(workspace_model,'lark-'+cfg['LARK_WORKER_ORGANIZATION'])
            data=(row.data or {}).get('people_directory_status',{}) if row else {}
        if not isinstance(data,dict):result['status']='invalid';return result
    except Exception:
        result['status']='unavailable';return result
    if not data:return result
    success,age=timestamp(data.get('last_success_at'),now)
    # Directory admission tolerates no future proof, even within heartbeat skew.
    if success and datetime.fromisoformat(success)>now:success,age=None,None
    precise_age=(now-datetime.fromisoformat(success)).total_seconds() if success else None
    result.update(last_success_at=success,success_age_seconds=age)
    if data.get('app_id')!=cfg.get('LARK_APP_ID') or age is None:result['status']='invalid'
    elif data.get('status')=='error':result['status']='degraded'
    elif precise_age>DIRECTORY_MAX_AGE_SECONDS:result['status']='stale'
    elif data.get('status') not in ('ready','review_required'):result['status']='invalid'
    else:
        result['blocking']=False
        result['status']='warning' if age>=DIRECTORY_WARNING_AGE or data.get('status')=='review_required' else 'ok'
    return result


def timestamp(value,now):
    if not isinstance(value,str): return None,None
    try:
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        if parsed.tzinfo is None: return None,None
        parsed=parsed.astimezone(timezone.utc)
        seconds=(now-parsed).total_seconds()
        if seconds < -60: return None,None
        return parsed.isoformat(),max(0,int(seconds))
    except (ValueError,OverflowError): return None,None


def worker_status(sessions,cache_row,now):
    result={'status':'missing','last_success_at':None,'success_age_seconds':None,
            'last_heartbeat_at':None,'heartbeat_age_seconds':None,
            'heartbeat_max_age_seconds':WORKER_HEARTBEAT_MAX_AGE,
            'success_max_age_seconds':WORKER_SUCCESS_MAX_AGE}
    try:
        with sessions() as db:
            row=db.get(cache_row,'runtime:worker')
            data=dict(row.data) if row and isinstance(row.data,dict) else {}
    except Exception:
        result['status']='unavailable'; return result
    if not data: return result
    success,success_age=timestamp(data.get('last_success_at'),now)
    heartbeat,heartbeat_age=timestamp(data.get('at'),now)
    result.update(last_success_at=success,success_age_seconds=success_age,
                  last_heartbeat_at=heartbeat,heartbeat_age_seconds=heartbeat_age)
    reported=data.get('status')
    result['reported_status']=reported if reported in ('ok','running','degraded') else 'unknown'
    if heartbeat_age is None: result['status']='invalid'
    elif heartbeat_age>WORKER_HEARTBEAT_MAX_AGE: result['status']='stale'
    elif reported=='degraded': result['status']='degraded'
    elif reported not in ('ok','running'): result['status']='invalid'
    elif success_age is None: result['status']='starting' if reported=='running' else 'invalid'
    elif success_age>WORKER_SUCCESS_MAX_AGE: result['status']='stale'
    else: result['status']='ok'
    return result


def backup_status(cfg,now):
    result={'status':'not_configured','last_success_at':None,'success_age_seconds':None,
            'last_checked_at':None,'check_age_seconds':None,'max_age_seconds':BACKUP_MAX_AGE,
            'check_max_age_seconds':BACKUP_CHECK_MAX_AGE}
    destination=cfg.get('BACKUP_DIR')
    if not destination: return result
    result['status']='missing'
    try:
        path=Path(destination)/'status.json'
        if path.is_symlink(): result['status']='invalid'; return result
        with path.open('rb') as handle: raw=handle.read(65537)
        if len(raw)>65536: result['status']='invalid'; return result
        data=json.loads(raw)
        if not isinstance(data,dict): result['status']='invalid'; return result
    except FileNotFoundError: return result
    except (ValueError,UnicodeError): result['status']='invalid'; return result
    except OSError: result['status']='unavailable'; return result
    success,success_age=timestamp(data.get('last_success_at'),now)
    checked,check_age=timestamp(data.get('last_checked_at'),now)
    remote=data.get('offsite') or {}
    remote_time,remote_age=timestamp(remote.get('last_verified_at'),now)
    result['offsite']={'status':'verified' if remote.get('status')=='verified' and remote.get('encrypted') is True and remote_age is not None and remote_age<=BACKUP_MAX_AGE else 'not_verified',
                      'encrypted':remote.get('encrypted') is True,'last_verified_at':remote_time}
    result.update(last_success_at=success,success_age_seconds=success_age,
                  last_checked_at=checked,check_age_seconds=check_age)
    if data.get('status')!='ok': result['status']='degraded'
    elif success_age is None or check_age is None: result['status']='invalid'
    elif success_age>BACKUP_MAX_AGE or check_age>BACKUP_CHECK_MAX_AGE: result['status']='stale'
    elif result['offsite']['status']!='verified':result['status']='local_only'
    else: result['status']='ok'
    return result


def snapshot(sessions,cache_row,cfg,*,now=None,workspace_model=None):
    now=(now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    worker=worker_status(sessions,cache_row,now); backup=backup_status(cfg,now)
    directory=directory_status(sessions,workspace_model,cfg,now)
    return {'checked_at':now.isoformat(),
            'status':'ok' if worker['status']=='ok' and backup['status']=='ok' and directory['status']=='ok' else 'attention',
            'worker':worker,'backup':backup,'directory':directory,
            'scope':'runtime_only','external_integrations_verified':False,
            'backup_archive_verified_by_this_request':False}


def register(app,identity,sessions,CacheRow,cfg,*,workspace_model=None):
    @app.get('/api/admin/runtime-health')
    def runtime_health(request:Request):
        data,user=identity(request)
        tenant=cfg.get('LARK_WORKER_ORGANIZATION')
        from .production_access import access_mode
        recovery=(data.get('organization')=='lark-'+str(tenant)
                  and data.get('wid') in ('lark-'+str(tenant),'test-lark-'+str(tenant))
                  and access_mode(user,cfg.get('LARK_APP_ID'),cfg=cfg)=='recovery')
        if not (tenant and data.get('mode')=='lark' and (data.get('wid')=='lark-'+tenant or recovery)
                and user.get('role')=='manager' and user.get('active',True)):
            raise HTTPException(403,'僅公司正式工作區管理員可查看維護狀態')
        return JSONResponse(snapshot(sessions,CacheRow,cfg,workspace_model=workspace_model),headers={'Cache-Control':'no-store'})
