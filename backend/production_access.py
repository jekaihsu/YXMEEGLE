"""Company admission is independent of simulated workspace permissions."""
from copy import deepcopy
from datetime import datetime,timezone
import json

from .workflow import require
from .business_policy import refresh_business_authority

TEST_AUTH_FIELDS = ('role', 'capabilities', 'active', 'department', 'default_workspace',
                    'authz_version', 'manager_revoked', 'capability_config_applied')


def admitted(person, app_id):
    if not app_id or not person or not person.get('active', True):
        return False
    if person.get('identity_app_id') not in (None, '', app_id):
        return False
    if person.get('bootstrap_admin') and person.get('role')=='manager':
        return not person.get('manager_revoked')
    source = person.get('directory_source') or {}
    return (person.get('directory_status') == 'employed'
            and not person.get('directory_missing', False)
            and source.get('app_id') == app_id
            and bool(source.get('record_id')))


def require_admission(person, app_id):
    require(admitted(person, app_id), '尚未核實在職名冊或帳號已停用，請聯絡公司管理員核對', 403)


DIRECTORY_MAX_AGE_SECONDS=900


def roster_age_seconds(person, now):
    """Return roster verification age, or None for missing/invalid timestamps."""
    try:
        stamp=datetime.fromisoformat(person.get('directory_last_seen_at','').replace('Z','+00:00'))
        if stamp.tzinfo is None:return None
        age=(now-stamp).total_seconds()
        return age if age>=0 else None
    except (ValueError,TypeError,AttributeError):
        return None


def company_admin_grant(person,cfg,*,tenant=None,now=None):
    """Exact owner-authorized account, independently verified by real OAuth.

    Never infer a grant from a role, name, roster gap or client-provided flag.
    Re-read configuration on each access decision so removal is effective.
    """
    if not cfg or not person or person.get('active') is not True or person.get('manager_revoked') or person.get('role')!='manager':return None
    app_id=cfg.get('LARK_APP_ID');company=tenant or cfg.get('LARK_WORKER_ORGANIZATION')
    if not app_id or company!=cfg.get('LARK_WORKER_ORGANIZATION') or company not in {v.strip() for v in cfg.get('LARK_ALLOWED_TENANTS','').split(',')}:return None
    proof=person.get('oauth_identity') or {}
    if not (person.get('identity_app_id')==app_id and proof.get('source')=='oauth_user_info'
            and proof.get('app_id')==app_id and proof.get('tenant')==company and proof.get('open_id')==person.get('id')
            and proof.get('verified_at')):return None
    try:
        grants=json.loads(cfg.get('LARK_COMPANY_ADMIN_GRANTS_JSON','[]'))
        if not isinstance(grants,list):return None
        matches=[g for g in grants if isinstance(g,dict) and g.get('open_id')==person['id'] and g.get('app_id')==app_id and g.get('tenant')==company]
        if len(matches)!=1:return None
        grant=matches[0];clock=now or datetime.now(timezone.utc)
        stamp=datetime.fromisoformat(grant['authorized_at'].replace('Z','+00:00'))
        if stamp.tzinfo is None or stamp>clock:return None
        if grant.get('expires_at'):
            expiry=datetime.fromisoformat(grant['expires_at'].replace('Z','+00:00'))
            if expiry.tzinfo is None or expiry<=clock:return None
        if grant.get('enabled') is not True or grant.get('role')!='manager' or not all(isinstance(grant.get(k),str) and grant[k].strip() for k in ('grant_id','reason','authorized_by','decision_ref')):return None
        return deepcopy(grant)
    except (ValueError,TypeError,KeyError,AttributeError):return None


def access_mode(person,app_id,*,now=None,cfg=None,tenant=None):
    """Business admission expires; active bootstrap admins may only repair it."""
    if not admitted(person,app_id):return 'denied'
    if cfg and cfg.get('LARK_APP_ID')==app_id and company_admin_grant(person,cfg,tenant=tenant,now=now):return 'normal'
    clock=now or datetime.now(timezone.utc)
    source=person.get('directory_source') or {}
    verified=(person.get('directory_status')=='employed' and not person.get('directory_missing')
              and source.get('app_id')==app_id and bool(source.get('record_id')))
    fresh=False
    try:
        stamp=datetime.fromisoformat(person.get('directory_last_seen_at','').replace('Z','+00:00'))
        age=(clock-stamp).total_seconds() if stamp.tzinfo else -999
        fresh=0<=age<=DIRECTORY_MAX_AGE_SECONDS
    except (ValueError,TypeError,AttributeError):pass
    if verified and fresh:return 'normal'
    if person.get('bootstrap_admin') and person.get('role')=='manager':return 'recovery'
    return 'denied'


def require_access(person,app_id,*,allow_recovery=False,now=None,cfg=None,tenant=None):
    mode=access_mode(person,app_id,now=now,cfg=cfg,tenant=tenant)
    require(mode=='normal' or allow_recovery and mode=='recovery',
            '公司名冊已逾15分鐘未核實，請由維運管理員恢復同步' if admitted(person,app_id)
            else '尚未核實在職名冊或帳號已停用',403)
    return mode


def set_company_admin_authority(state,cfg):
    from .business_policy import refresh_business_authority
    for person in state.get('users',[]):
        refresh_business_authority(person,cfg)
    authority=state.setdefault('native_approval_authority',{})
    authority['company_admin_ids']=[p['id'] for p in state.get('users',[]) if company_admin_grant(p,cfg)]


def business_admitted(person,app_id,authority):
    """Offline business-role checks use freshly server-derived admin authority."""
    if not admitted(person,app_id):return False
    source=person.get('directory_source') or {}
    if person.get('directory_status')=='employed' and not person.get('directory_missing') and source.get('app_id')==app_id and source.get('record_id'):return True
    proof=person.get('oauth_identity') or {}
    return (not person.get('manager_revoked') and person.get('role')=='manager'
        and authority.get('app_id')==app_id and person.get('id') in authority.get('company_admin_ids',[])
        and proof.get('app_id')==app_id and proof.get('tenant')==authority.get('tenant')
        and proof.get('open_id')==person.get('id') and proof.get('source')=='oauth_user_info')


def readonly_sync_actor(state,cfg,connection_name):
    """Server-only actor for previously enabled company read-only connections."""
    require(connection_name in ('people_directory_connection','source_connection','attendance_schedule_connection'),
            '背景唯讀連線種類未核定',403)
    connection=state.get(connection_name) or {}
    app_id=cfg.get('LARK_APP_ID');tenant=cfg.get('LARK_WORKER_ORGANIZATION')
    require(connection.get('enabled') is True and app_id and tenant and cfg.get('LARK_WORKER_IDENTITY')=='application'
            and tenant in {x.strip() for x in cfg.get('LARK_ALLOWED_TENANTS','').split(',')},
            '公司背景唯讀連線尚未授權',403)
    require(connection.get('app_id',app_id)==app_id and connection.get('tenant',tenant)==tenant,
            '公司背景唯讀授權需重新核對',403)
    require(state.get('environment') not in ('test','demo'),'隔離工作區不能使用正式背景讀取',403)
    return {'id':'system:company-readonly','name':'公司唯讀同步','role':'system','active':True,'capabilities':[]}


def readonly_sync_connection(cfg,actor_id):
    return {'enabled':True,'authorization':'company_application_readonly','app_id':cfg.get('LARK_APP_ID'),
            'tenant':cfg.get('LARK_WORKER_ORGANIZATION'),'authorized_by':actor_id,
            'interval_seconds':300}


def test_profile(formal, overlay):
    """Names and source employment remain live; test grants never leave test."""
    result = deepcopy(formal)
    if overlay:
        for key in TEST_AUTH_FIELDS:
            if key in overlay:
                result[key] = deepcopy(overlay[key])
    if not formal.get('active', True):
        result['active'] = False
    if formal.get('manager_revoked'):
        result['manager_revoked']=True
    return result
