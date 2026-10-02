"""Application-scoped exact contact ID projection; no name matching or writes."""
from datetime import datetime,timezone
from .workflow import require,now


def roster_identity_verified(person,app_id):
    source=person.get('directory_source') or {}
    return bool(app_id and person.get('active',True) and person.get('identity_app_id')==app_id
        and person.get('directory_status')=='employed' and not person.get('directory_missing')
        and source.get('app_id')==app_id and source.get('record_id'))


def schedule_subject_verified(ws,user_id,*,clock=None):
    """Historical schedules cannot establish a current formal employee identity."""
    if ws.get('environment') in ('demo','test'):return True
    app_id=(ws.get('native_approval_authority') or {}).get('app_id') or (ws.get('people_directory_status') or {}).get('app_id') or (ws.get('attendance_schedule_status') or {}).get('app_id')
    if ws.get('environment')!='production' and not app_id:return True
    person=next((u for u in ws.get('users',[]) if u.get('id')==user_id),None)
    if not person or not roster_identity_verified(person,app_id):return False
    from .production_access import access_mode
    return access_mode(person,app_id,now=clock)=='normal'


def valid_identity(person,app_id,tenant):
    m=person.get('attendance_identity') or {}
    return bool(app_id and tenant and m.get('source') in ('oauth_user_info','contact_user_batch')
        and m.get('verified_at') and m.get('app_id')==app_id and m.get('tenant')==tenant
        and m.get('open_id')==person['id'] and m.get('employee_type')=='employee_id'
        and isinstance(m.get('employee_id'),str) and m['employee_id'].strip()
        and not m['employee_id'].startswith('ou_'))


def reusable_identity(person,app_id,tenant):
    if not valid_identity(person,app_id,tenant):return False
    try:
        stamp=datetime.fromisoformat(person['attendance_identity']['verified_at'].replace('Z','+00:00'))
        return stamp.tzinfo is not None and 0<=(datetime.now(timezone.utc)-stamp).total_seconds()<86400
    except (TypeError,ValueError):return False


class AttendanceIdentityResolver:
    def __init__(self,adapter,app_id,tenant,authorize):
        self.adapter,self.app_id,self.tenant,self.authorize=adapter,app_id,tenant,authorize

    def fetch(self,people):
        require(bool(self.app_id and self.tenant),'班表身分應用或公司未設定',503)
        requested={p['id'] for p in people}
        require(len(requested)==len(people),'班表人員識別重複',409)
        require(all(p.get('identity_app_id')==self.app_id and isinstance(p['id'],str) and p['id'].startswith('ou_') for p in people),
                '班表身分需同一應用已核實帳號',403)
        mappings={};issues=[];seen_employee={}
        for offset in range(0,len(people),50):
            batch=[p['id'] for p in people[offset:offset+50]]
            self.authorize()
            data=self.adapter.request('GET','/contact/v3/users/batch',params={'user_id_type':'open_id','user_ids':batch})
            self.authorize()
            items=data.get('items');require(isinstance(items,list),'通訊錄識別回應不完整',502)
            seen=set()
            for item in items:
                oid=item.get('open_id')
                require(oid in batch and oid not in seen,'通訊錄回應識別不符或重複',502);seen.add(oid)
                employee=item.get('user_id')
                if not isinstance(employee,str) or not employee.strip() or employee.startswith('ou_'):
                    issues.append({'user_id':oid,'reason':'employee_id_unavailable'});continue
                require(employee not in seen_employee,'員工識別不能對應多個帳號',502)
                seen_employee[employee]=oid
                mappings[oid]={'open_id':oid,'employee_id':employee,'employee_type':'employee_id',
                    'app_id':self.app_id,'tenant':self.tenant,'verified_at':now(),'source':'contact_user_batch'}
            issues.extend({'user_id':oid,'reason':'contact_identity_not_returned'} for oid in batch if oid not in seen)
        return {'mappings':mappings,'issues':issues}
