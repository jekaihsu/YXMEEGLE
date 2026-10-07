"""Company schedule refresh with atomic persistence and manual override priority."""
from copy import deepcopy
from datetime import date,datetime,timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import select
from fastapi import HTTPException
from .people_directory import PeopleDirectoryService
from .attendance_schedule import AttendanceScheduleReader
from .production_access import admitted
from .workflow import require,now,uid,event
from .attendance_identity import AttendanceIdentityResolver,reusable_identity,roster_identity_verified


class AttendanceScheduleService(PeopleDirectoryService):
    def resolve_identities(self,wid,actor_id):
        policy=self._policy(wid)
        def eligible(state):
            return [u for u in state['users'] if admitted(u,policy[0])]
        def signature(people):
            return {u['id']:(u.get('identity_app_id'),u.get('active'),u.get('directory_status'),
                u.get('directory_missing'),deepcopy(u.get('directory_source'))) for u in people}
        with self.sessions() as db:
            row=db.get(self.W,wid);require(row is not None,'工作區不存在',404)
            state=self._state(db,row);self._actor(state,actor_id)
            require(state.get('environment')=='production','班表識別限公司正式工作區',403)
            people=eligible(state);expected=signature(people)
            verified=[u for u in people if roster_identity_verified(u,policy[0])
                      and isinstance(u.get('id'),str) and u['id'].startswith('ou_')]
            pending=[{'user_id':u['id'],'reason':'employee_identity_unverified'}
                     for u in people if u not in verified]
            missing=[u for u in verified if not reusable_identity(u,*policy)]
        def check():
            require(self._policy(wid)==policy,'班表識別設定已變更',409)
            with self.sessions() as db:
                row=db.get(self.W,wid);require(row is not None,'工作區不存在',404)
                fresh=self._state(db,row);self._actor(fresh,actor_id)
                require(fresh.get('environment')=='production' and signature(eligible(fresh))==expected,
                        '班表識別核對期間名冊已變更',409)
        result={'mappings':{},'issues':pending}
        if missing:
            adapter=self.adapter_factory(deepcopy(self.cfg))
            try:
                fetched=AttendanceIdentityResolver(adapter,*policy,check).fetch(missing)
                result={'mappings':fetched['mappings'],'issues':pending+fetched['issues']}
            finally:adapter.client.close()
        with self.sessions.begin() as db:
            row=db.scalar(select(self.W).where(self.W.id==wid).with_for_update())
            require(row is not None,'工作區不存在',404)
            current=self._state(db,row);actor=self._actor(current,actor_id)
            require(self._policy(wid)==policy and current.get('environment')=='production'
                    and signature(eligible(current))==expected,'班表識別套用前名冊已變更',409)
            for person in current['users']:
                if person['id'] not in {u['id'] for u in missing}:continue
                if person['id'] in result['mappings']:
                    person['attendance_identity']=result['mappings'][person['id']]
                else:
                    # A completed authoritative lookup that no longer returns
                    # an identity must not keep using the previous cached ID.
                    person.pop('attendance_identity',None)
                profile=db.get(self.P,(wid,person['id']))
                if profile:profile.data=deepcopy(person)
                else:db.add(self.P(organization_id=wid,person_id=person['id'],data=deepcopy(person)))
            current['attendance_identity_status']={'resolved':len(result['mappings']),
                'issues':result['issues'],'checked_at':now(),'status':'pending' if result['issues'] else 'ready'}
            event(current,actor,'attendance_identity_sync',message='唯讀核實原生帳號與員工識別，未按姓名配對')
            self._save(db,row,current)
        return deepcopy(current['attendance_identity_status'])

    def _state(self,db,row):
        state=super()._state(db,row)
        # Legacy formal workspaces predate the environment field. Infer only
        # from the server namespace and fully validated configured company;
        # explicit isolation labels are never upgraded. Normal _save owns the
        # transaction that eventually persists this metadata with sync results.
        if state.get('environment') is None and self.cfg.get('LARK_WORKER_ORGANIZATION') and row.id=='lark-'+self.cfg['LARK_WORKER_ORGANIZATION']:
            self._policy(row.id)
            state['environment']='production'
        return state

    def _actor(self,state,actor_id):
        if actor_id is None:
            from .production_access import readonly_sync_actor
            return readonly_sync_actor(state,self.cfg,'attendance_schedule_connection')
        actor=next((u for u in state['users'] if u['id']==actor_id),None)
        require(actor and admitted(actor,self.cfg.get('LARK_APP_ID')) and
            (actor.get('role')=='manager' or 'calendar_edit' in actor.get('capabilities',[])),
            '需要已核實的班表維護權限',403)
        return actor

    def sync(self,wid,actor_id,date_from=None,date_to=None):
        policy=self._policy(wid)
        try:
            start=date.fromisoformat(date_from) if date_from else datetime.now(ZoneInfo('Asia/Taipei')).date()
            end=date.fromisoformat(date_to) if date_to else start+timedelta(days=13)
        except (ValueError,TypeError):raise HTTPException(422,'請提供有效班表日期')
        require(0<=(end-start).days<30,'班表查詢需為30天內的日期區間',422)
        if str(self.cfg.get('LARK_ATTENDANCE_IDENTITY_RESOLUTION','')).lower()=='contact':
            self.resolve_identities(wid,actor_id)
        with self.sessions() as db:
            row=db.get(self.W,wid);require(row is not None,'工作區不存在',404)
            state=self._state(db,row);self._actor(state,actor_id)
            require(state.get('environment')=='production','班表同步限公司正式工作區',403)
            people=[deepcopy(u) for u in state['users'] if admitted(u,policy[0])]
            generation=state.get('attendance_schedule_status',{}).get('sync_revision',0)
        identity=lambda users:{u['id']:(u.get('attendance_identity'),roster_identity_verified(u,policy[0])) for u in users if admitted(u,policy[0])}
        expected_identity=identity(people)
        # Admission authority lets an administrator operate the reader; it does
        # not establish that administrator's own employment/schedule identity.
        for person in people:
            if not roster_identity_verified(person,policy[0]):person.pop('attendance_identity',None)
        adapter=None
        try:
            def check():
                require(self._policy(wid)==policy,'班表同步設定已變更',409)
                with self.sessions() as db:
                    row=db.get(self.W,wid);require(row is not None,'工作區不存在',404)
                    current=self._state(db,row);self._actor(current,actor_id)
                    require(current.get('environment')=='production' and identity(current['users'])==expected_identity,
                        '人員身分或工作區已變更，請重新同步班表',409)
            adapter=self.adapter_factory(deepcopy(self.cfg))
            result=AttendanceScheduleReader(adapter,*policy,check).fetch(people,start.isoformat(),end.isoformat())
            check()
            with self.sessions.begin() as db:
                row=db.scalar(select(self.W).where(self.W.id==wid).with_for_update())
                current=self._state(db,row);actor=self._actor(current,actor_id)
                require(self._policy(wid)==policy and current.get('environment')=='production' and identity(current['users'])==expected_identity,
                    '班表套用前人員或設定已變更',409)
                require(current.get('attendance_schedule_status',{}).get('sync_revision',0)==generation,
                    '已有較新的班表同步，保留最新資料',409)
                imported,overrides=merge_schedules(current,result,people,start,end)
                current['attendance_schedule_status']={'status':result['status'],'last_success_at':result['fetched_at'],
                    'last_attempt_at':now(),'sync_revision':generation+1,'app_id':policy[0],
                    'date_from':start.isoformat(),'date_to':end.isoformat(),'issues':result['issues'],
                    'ready_count':imported,'manual_override_count':overrides,
                    'message':'已讀取正常班表；未核對的班次保留待確認，人工設定優先'}
                from .production_access import readonly_sync_connection
                prior=current.get('attendance_schedule_connection',{})
                current['attendance_schedule_connection']=readonly_sync_connection(self.cfg,actor_id or prior.get('authorized_by') or prior.get('actor_id'),dataset='attendance')
                event(current,actor,'attendance_schedule_sync',message='唯讀更新正常班表，保留人工設定與歷史')
                self._save(db,row,current)
                return deepcopy(current['attendance_schedule_status'])
        except Exception as exc:
            with self.sessions.begin() as db:
                row=db.scalar(select(self.W).where(self.W.id==wid).with_for_update())
                if row:
                    current=self._state(db,row);status=current.setdefault('attendance_schedule_status',{})
                    if status.get('sync_revision',0)==generation:
                        status.update(status='error',last_attempt_at=now(),message='正常班表讀取失敗，保留上次成功資料')
                        self._save(db,row,current)
            if isinstance(exc,HTTPException):raise
            raise HTTPException(502,'正常班表讀取失敗，保留上次成功資料') from exc
        finally:
            if adapter:adapter.client.close()

    def run_due(self,wid):
        from .live_read.config import LiveReadConfig
        config=LiveReadConfig.from_env(self.cfg)
        if config.enabled: return None
        if wid!='lark-'+self.cfg.get('LARK_WORKER_ORGANIZATION',''):return None
        with self.sessions.begin() as db:
            row=db.scalar(select(self.W).where(self.W.id==wid).with_for_update())
            if not row:return None
            state=self._state(db,row);connection=state.get('attendance_schedule_connection',{})
            if not connection.get('enabled') or state.get('environment')!='production':return None
            status=state.setdefault('attendance_schedule_status',{});previous=status.get('last_attempt_at')
            if previous:
                try:
                    if (datetime.fromisoformat(now())-datetime.fromisoformat(previous)).total_seconds()<config.attendance_ttl_seconds:return None
                except (ValueError,TypeError):pass
            status['last_attempt_at']=now();self._save(db,row,state)
        return self.sync(wid,None)


def merge_schedules(ws,result,people,start,end):
    rows={(r['user_id'],r['day']):r for r in result['rows']};ready=overrides=0
    for offset in range((end-start).days+1):
        day=(start+timedelta(days=offset)).isoformat()
        for person in people:
            key=(person['id'],day)
            matches=[s for s in ws['work_schedules'] if (s['user_id'],s['day'])==key]
            require(len(matches)<=1,'同日班表有多筆資料，請先核對',409)
            prior=matches[0] if matches else None
            if prior and prior.get('basis')!='attendance_schedule':overrides+=1;continue
            source=rows.get(key,{'user_id':person['id'],'day':day,'status':'pending_schedule','reason':'employee_identity_unverified'})
            item={**deepcopy(source),'id':prior['id'] if prior else uid(),'basis':'attendance_schedule',
                  'end_time':source.get('normal_off_time'),'active':source['status']=='ready'}
            comparable=lambda r:{k:v for k,v in r.items() if k not in ('history','version','updated_at','source_verified_at')}
            history=deepcopy(prior.get('history',[])) if prior else []
            changed=prior is not None and comparable(prior)!=comparable(item)
            if changed:history.append({k:deepcopy(v) for k,v in prior.items() if k!='history'})
            item.update(version=(prior or {}).get('version',1)+(1 if changed else 0),history=history,
                        updated_at=now(),source_verified_at=result['fetched_at'])
            if prior:prior.clear();prior.update(item)
            else:ws['work_schedules'].append(item)
            ready+=int(item['active'])
    return ready,overrides
