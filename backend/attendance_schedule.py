"""Read-only schedule queries; never derive normal hours from actual punches."""
from datetime import date,datetime,timedelta
from zoneinfo import ZoneInfo
from urllib.parse import quote
import re
from .workflow import require,now
from .attendance_identity import valid_identity


def clock_minutes(value):
    match=re.fullmatch(r'(\d{1,2}):([0-5]\d)',str(value or ''))
    if not match:return None
    hours=int(match[1])
    return hours*60+int(match[2]) if hours<48 else None


def normal_end(day,shift,timezone='Asia/Taipei'):
    if shift.get('is_flexible') is not False:return {'status':'pending_schedule','reason':'flexible_or_unknown_shift'}
    rules=shift.get('punch_time_rule')
    if not isinstance(rules,list) or not rules:return {'status':'pending_schedule','reason':'missing_shift_hours'}
    endings=[]
    for rule in rules:
        start=clock_minutes(rule.get('on_time'));end=clock_minutes(rule.get('off_time'))
        if start is None or end is None or end<=start:return {'status':'pending_schedule','reason':'ambiguous_shift_hours'}
        endings.append(end)
    end=max(endings)
    cutoff=datetime.combine(date.fromisoformat(day),datetime.min.time(),ZoneInfo(timezone))+timedelta(minutes=end)
    return {'status':'ready','normal_off_at':cutoff.isoformat(),'normal_off_time':cutoff.strftime('%H:%M'),
            'off_day_offset':end//1440,'timezone':timezone,'basis':'attendance_schedule'}


class AttendanceScheduleReader:
    """Injected tenant adapter and authorization; POST is the documented query only.

    Identity metadata is server-owned verified OAuth user_info mapping; neither
    names nor open_id strings are sent as attendance employee IDs.
    """
    def __init__(self,adapter,app_id,tenant,authorize,timezone='Asia/Taipei'):
        self.adapter,self.app_id,self.tenant,self.authorize,self.timezone=adapter,app_id,tenant,authorize,timezone

    def _request(self,method,path,**kwargs):
        require((method=='POST' and path=='/attendance/v1/user_daily_shifts/query') or
                (method=='GET' and path.startswith('/attendance/v1/shifts/')),'班表讀取不允許寫入',403)
        self.authorize()
        return self.adapter.request(method,path,**kwargs)

    def fetch(self,people,date_from,date_to):
        start,end=date.fromisoformat(date_from),date.fromisoformat(date_to)
        require(0<=(end-start).days<30,'班表查詢需為30天內的日期區間',422)
        identities={};issues=[]
        for person in people:
            m=person.get('attendance_identity') or {}
            valid=valid_identity(person,self.app_id,self.tenant)
            if not valid:issues.append({'user_id':person['id'],'reason':'employee_identity_unverified'});continue
            if m['employee_id'] in identities:raise ValueError('Attendance identity is not unique')
            identities[m['employee_id']]=person['id']
        if not identities:return {'status':'pending_schedule','rows':[],'issues':issues,'fetched_at':now()}
        rows=[];employee_ids=list(identities)
        for offset in range(0,len(employee_ids),50):
            batch=employee_ids[offset:offset+50]
            data=self._request('POST','/attendance/v1/user_daily_shifts/query',params={'employee_type':'employee_id'},
                json={'user_ids':batch,'check_date_from':int(start.strftime('%Y%m%d')),'check_date_to':int(end.strftime('%Y%m%d'))})
            received=data.get('user_daily_shifts');require(isinstance(received,list),'班表回應不完整，保留既有資料',502)
            require(all(isinstance(row,dict) and row.get('user_id') in batch for row in received),'考勤回應含未要求的人員，整批停用',502)
            rows.extend(received)
        grouped={}
        for row in rows:
            require(row.get('user_id') in identities,'班表回應含未要求的人員，停止套用',502)
            try:day=datetime.strptime(str(row['month'])+str(row['day_no']).zfill(2),'%Y%m%d').date()
            except (KeyError,ValueError,TypeError):require(False,'班表日期無法核對',502)
            require(start<=day<=end,'班表日期超出查詢範圍',502)
            grouped.setdefault((identities[row['user_id']],day.isoformat()),[]).append(row)
        shifts={};result=[]
        for offset in range((end-start).days+1):
            day=(start+timedelta(days=offset)).isoformat()
            for ident in identities.values():
                matching=grouped.get((ident,day),[])
                projected={'user_id':ident,'day':day,'basis':'attendance_schedule'}
                if len(matching)!=1 or not matching[0].get('shift_id'):
                    projected.update(status='pending_schedule',reason='missing_or_ambiguous_schedule')
                else:
                    row=matching[0];shift_id=row['shift_id']
                    if shift_id not in shifts:
                        shifts[shift_id]=self._request('GET','/attendance/v1/shifts/'+quote(shift_id,safe=''))
                        require(shifts[shift_id].get('shift_id')==shift_id,'班次回應識別不符',502)
                    projected.update(normal_end(day,shifts[shift_id],self.timezone),source_shift_id=shift_id,source_group_id=row.get('group_id'))
                result.append(projected)
        return {'status':'ready' if not issues and all(r['status']=='ready' for r in result) else 'pending_schedule',
                'rows':result,'issues':issues,'fetched_at':now()}
