"""Atomic complete-snapshot application shared by manual and scheduled sync."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from sqlalchemy import select, update
from fastapi import HTTPException
from . import storage
from .sources import fetch_sources, import_sources, configuration, KNOWN_TABLES
from .workflow import now, event, require
from .policy import upgrade
from .lark_adapter import application_adapter


# Bump when import_sources or source-reference policy changes its projection.
SOURCE_PROJECTION_VERSION = 'sources-v1-20261007'
PROJECTION_FIELDS = ('projects', 'archived_projects', 'source_quotes', 'source_confirmations',
                     'contract_items', 'daily_unmatched', 'daily_reviews', 'sop_templates',
                     'users', 'settings', 'source_identity_conflicts', 'source_case_baseline',
                     'source_case_review', 'source_case_policy_revision', 'source_visible_record_ids')


def projection_fingerprint(state):
    """Conservatively detect edits to projected content and importer/policy inputs."""
    value = {key: state.get(key) for key in PROJECTION_FIELDS}
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=False,
                           separators=(',', ':'), allow_nan=False)
    return 'sha256:' + hashlib.sha256(canonical.encode('utf-8')).hexdigest()


class SourceSyncService:
    def __init__(self,sessions,W,B,P,A,C,cfg,fetcher=None,adapter_factory=None):
        self.sessions=sessions; self.W=W; self.B=B; self.P=P; self.A=A; self.C=C; self.cfg=cfg
        self.fetcher=fetcher
        self.adapter_factory=adapter_factory or (lambda config:application_adapter(config))

    def _policy(self,wid):
        require(wid=='lark-'+self.cfg.get('LARK_WORKER_ORGANIZATION',''),'來源同步限已核定公司正式工作區',403)
        require(self.cfg.get('LARK_WORKER_IDENTITY')=='application' and self.cfg.get('LARK_APP_ID'),'公司背景唯讀連線尚未設定',503)
        require(self.cfg.get('LARK_WORKER_ORGANIZATION') in {x.strip() for x in self.cfg.get('LARK_ALLOWED_TENANTS','').split(',') if x.strip()},'來源公司不在登入允許名單',403)
        require(all(KNOWN_TABLES.get(t['base_token'],{}).get(t['table_id'])==t['kind'] for t in configuration(self.cfg)),
                '公司來源僅限已核定的 V4 與報價總表',403)
        return tuple(self.cfg.get(k) for k in ('LARK_APP_ID','LARK_WORKER_ORGANIZATION','LARK_SOURCE_TABLES_JSON','LARK_V4_BASE_TOKEN','LARK_QUOTE_BASE_TOKEN'))

    def _state(self,db,row):
        return upgrade(storage.load(db,self.B,row))

    def _actor(self,db,wid,state,actor_id):
        if actor_id is None:
            from .production_access import readonly_sync_actor
            return readonly_sync_actor(state,self.cfg,'source_connection')
        profile=db.get(self.P,(wid.removeprefix('test-'),actor_id))
        actor=profile.data if profile else next((u for u in state['users'] if u['id']==actor_id),None)
        require(actor and actor.get('active',True) and (actor.get('role') in ('pm','manager') or 'manage_sources' in actor.get('capabilities',[])),'來源同步操作者已無權限',403)
        from .production_access import admitted
        require(admitted(actor,self.cfg.get('LARK_APP_ID')),'來源同步操作者尚未核實在職身分',403)
        return actor

    def _authorize(self,wid,actor_id):
        require(wid.startswith('lark-'),'隔離工作區不可直接同步正式來源',403)
        with self.sessions() as db:
            row=db.get(self.W,wid); require(row is not None,'工作區不存在',404)
            state=self._state(db,row)
            require(state.get('environment') not in ('test','demo'),'隔離工作區不可直接同步正式來源',403)
            return self._actor(db,wid,state,actor_id)

    def failure(self,wid,message,expected_generation=None):
        with self.sessions.begin() as db:
            row=db.scalar(select(self.W).where(self.W.id==wid).with_for_update())
            if not row: return
            state=self._state(db,row); status=deepcopy(state.get('source_status',{}))
            if expected_generation is not None and status.get('sync_revision',0)!=expected_generation: return
            status.update(status='error',message=message,last_attempt_at=now())
            state['source_status']=status; state['version']=row.version+1
            changed=db.execute(update(self.W).where(self.W.id==wid,self.W.version==row.version).values(version=state['version'],data=storage.save(db,self.B,wid,state)))
            require(changed.rowcount==1,'來源狀態版本衝突',409)
            cache=db.get(self.C,wid)
            if cache:
                value=deepcopy(cache.data or {}); value.update(status='error',message=message,last_attempt_at=status['last_attempt_at']); cache.data=value
            else:
                db.add(self.C(id=wid,data={'configured':True,'status':'error','last_sync':status.get('last_sync'),'last_attempt_at':status['last_attempt_at'],'message':message,'tables':[],'records':[]}))

    def fetch(self,wid,actor_id=None,*,expected_policy=None):
        self._authorize(wid,actor_id)
        policy=expected_policy if expected_policy is not None else self._policy(wid)
        def check():
            require(self._policy(wid)==policy,'來源同步設定已變更，保留原資料',409)
            self._authorize(wid,actor_id)
        check()
        adapter=self.adapter_factory(deepcopy(self.cfg))
        try:
            from .jobs import PermissionCheckedClient
            adapter.client=PermissionCheckedClient(adapter.client,check)
            check()
            return self.fetcher(adapter.token) if self.fetcher else fetch_sources(adapter.token,cfg=self.cfg,client=adapter.client)
        finally:
            adapter.client.close()

    def apply_snapshot(self,wid,snapshot,actor_id=None,*,expected_policy,expected_generation,skip_unchanged=False):
        # Both fences must be captured before fetch, never reconstructed at apply.
        require(expected_policy is not None and expected_generation is not None,
                '來源快照缺少讀取前的同步保護',409)
        policy=expected_policy
        generation=expected_generation
        require(isinstance(snapshot,dict) and isinstance(snapshot.get('records'),list) and isinstance(snapshot.get('tables'),list) and snapshot.get('last_sync') and snapshot.get('message') is not None,'來源回應不完整；保留上次成功資料',502)
        require(snapshot.get('status')=='ready' and snapshot['tables'] and all(t.get('status')=='ready' for t in snapshot['tables']),'來源分頁不完整；保留上次成功資料',409)
        configured={(t['base_token'],t['table_id']) for t in configuration(self.cfg)}
        actual=[(t.get('base_token'),t.get('table_id')) for t in snapshot['tables']]
        require(not configured or (len(set(actual))==len(actual) and set(actual)==configured),
                '來源快照未涵蓋全部核定表格；保留上次成功資料',409)
        require(all(isinstance(r,dict) and all(r.get(k) for k in ('base_token','table_id','record_id'))
                    and (not configured or (r['base_token'],r['table_id']) in configured
                         and KNOWN_TABLES.get(r['base_token'],{}).get(r['table_id'])==r.get('kind'))
                    for r in snapshot['records']),
                '來源紀錄識別或核定表格不符；保留上次成功資料',409)
        with self.sessions.begin() as db:
            row=db.scalar(select(self.W).where(self.W.id==wid).with_for_update()); require(row is not None,'工作區不存在',404)
            state=self._state(db,row)
            require(self._policy(wid)==policy,'來源同步設定已變更，保留原資料',409)
            require(state.get('environment') not in ('test','demo'),'工作區環境已變更',403)
            actor=self._actor(db,wid,state,actor_id)
            require(state.get('source_status',{}).get('sync_revision',0)==generation,'已有較新來源同步完成；保留最新資料',409)
            cache=db.get(self.C,wid)
            previous=state.get('source_status',{}).get('last_sync')
            cached_time=(cache.data or {}).get('last_sync') if cache else None
            if cached_time and (not previous or datetime.fromisoformat(cached_time)>datetime.fromisoformat(previous)):
                previous=cached_time
            require(not previous or datetime.fromisoformat(snapshot['last_sync'])>=datetime.fromisoformat(previous),'來源快照早於上次成功資料，保留最新資料',409)
            from .live_read.fingerprint import fingerprint
            digest=fingerprint(snapshot)
            status=state.get('source_status',{})
            projection_matches=(status.get('projection_fingerprint')==digest
                                and status.get('projection_version')==SOURCE_PROJECTION_VERSION
                                and status.get('projection_state_fingerprint')==projection_fingerprint(state))
            if (skip_unchanged and projection_matches and cache
                    and (cache.data or {}).get('status')=='ready'
                    and cache.data.get('source_message')==snapshot['message']
                    and fingerprint(cache.data)==digest):
                value=deepcopy(cache.data)
                value.update(last_sync=snapshot['last_sync'],as_of=snapshot['last_sync'],
                             last_attempt_at=now(),fingerprint=digest)
                cache.data=value
                # Advance the workspace read metadata without re-importing entities
                # or incrementing the source generation/event history.
                status.update(last_sync=value['last_sync'],as_of=value['as_of'],
                              last_attempt_at=value['last_attempt_at'])
                root=deepcopy(row.data)
                root.update(source_status=status,version=row.version+1)
                changed=db.execute(update(self.W).where(self.W.id==wid,self.W.version==row.version)
                                   .values(version=row.version+1,data=root))
                require(changed.rowcount==1,'來源同步版本衝突，請重試',409)
                return value
            snapshot.update(fingerprint=digest,as_of=snapshot['last_sync'],source_message=snapshot['message'])
            from .source_case_policy import apply_source_reference_policy,visible_project
            admissible=snapshot['records']
            snapshot['mapping']=import_sources(state,admissible,complete_tables=snapshot['tables'])
            apply_source_reference_policy(state,snapshot,actor)
            visible=[p for p in state['projects'] if visible_project(state,p)]
            snapshot['mapping']['projects']=sum(p.get('case_type','formal')=='formal' for p in visible)
            snapshot['mapping']['intakes']=sum(p.get('case_type')=='intake' for p in visible)
            snapshot['case_filter']={'admitted_records':len(admissible),'source_records':len(snapshot['records'])}
            mapping=snapshot['mapping']
            mapping['daily_total']=mapping['daily_imported']+mapping['daily_unmatched']
            warnings=[]
            if mapping['daily_unmatched']: warnings.append(f"日報需核對 {mapping['daily_unmatched']} 筆（未配對日報未建立案件）")
            if mapping['confirmations_missing_code']: warnings.append(f"確認單 {mapping['confirmations_missing_code']} 列未提供編號，待核對")
            if mapping['daily_missing_date']: warnings.append(f"日報 {mapping['daily_missing_date']} 筆缺日期")
            if mapping['daily_conflicting_dates']: warnings.append(f"日報 {mapping['daily_conflicting_dates']} 筆日期矛盾")
            if mapping['daily_missing_department']: warnings.append(f"日報 {mapping['daily_missing_department']} 筆缺組別")
            if mapping['identity_conflicts']: warnings.append(f"案件來源識別 {mapping['identity_conflicts']} 筆待核對")
            if mapping.get('daily_source_missing'): warnings.append(f"來源已不存在的日報 {mapping['daily_source_missing']} 筆已保留歷史並停止採用")
            snapshot['mapping_status']='review_required' if warnings else 'ready'
            snapshot['message']=f"已唯讀取得 {len(snapshot['tables'])} 張來源表；日報已配對 {mapping['daily_imported']}/{mapping['daily_total']} 筆"+('；'+'；'.join(warnings) if warnings else '')+'；未寫入 Lark'
            state['source_status']={k:snapshot[k] for k in ('status','last_sync','message')}
            state['source_status'].update(mapping=deepcopy(mapping),mapping_status=snapshot['mapping_status'])
            state['source_status'].update(sync_revision=generation+1,identity='application')
            state['source_status']['last_attempt_at']=now()
            snapshot['last_attempt_at']=state['source_status']['last_attempt_at']
            from .production_access import readonly_sync_connection
            prior_connection=state.get('source_connection') or {}
            authorized_by=actor_id or prior_connection.get('authorized_by') or prior_connection.get('actor_id')
            state['source_connection']=readonly_sync_connection(self.cfg,authorized_by)
            state['version']=row.version+1; event(state,actor,'source_sync',message=snapshot['message'])
            root=storage.save(db,self.B,wid,state)
            # storage.save assigns entity concurrency versions; stamp that final
            # representation so a subsequent unchanged read can safely skip.
            state['source_status'].update(projection_fingerprint=digest,
                projection_version=SOURCE_PROJECTION_VERSION,
                projection_state_fingerprint=projection_fingerprint(state))
            root['source_status']=deepcopy(state['source_status'])
            changed=db.execute(update(self.W).where(self.W.id==wid,self.W.version==row.version)
                               .values(version=state['version'],data=root))
            require(changed.rowcount==1,'來源同步版本衝突，請重試',409)
            cache=db.get(self.C,wid)
            if cache: cache.data=snapshot
            else: db.add(self.C(id=wid,data=snapshot))
        return snapshot

    def sync(self,wid,actor_id,token=None,*,skip_unchanged=False):
        # The compatible token argument never selects the company identity.
        generation=None
        try:
            self._authorize(wid,actor_id)
            policy=self._policy(wid)
            with self.sessions() as db:
                generation=self._state(db,db.get(self.W,wid)).get('source_status',{}).get('sync_revision',0)
            snapshot=self.fetch(wid,actor_id,expected_policy=policy)
            return self.apply_snapshot(wid,snapshot,actor_id,expected_policy=policy,
                                       expected_generation=generation,skip_unchanged=skip_unchanged)
        except Exception as exc:
            message=exc.detail if isinstance(exc,HTTPException) else '來源同步失敗；保留上次成功資料，請檢查連線或重新登入'
            self.failure(wid,message,generation)
            if isinstance(exc,HTTPException): raise
            raise HTTPException(502,message) from exc

    def run_due(self,wid):
        from .live_read.config import LiveReadConfig
        config=LiveReadConfig.from_env(self.cfg)
        if config.enabled: return None
        if not wid.startswith('lark-'): return None
        with self.sessions.begin() as db:
            row=db.scalar(select(self.W).where(self.W.id==wid).with_for_update())
            if not row: return None
            state=self._state(db,row); connection=state.get('source_connection',{})
            if not connection.get('enabled'): return None
            last=state.get('source_status',{}).get('last_attempt_at') or state.get('source_status',{}).get('last_sync')
            clock=datetime.fromisoformat(now())
            if last:
                try:
                    previous=datetime.fromisoformat(last)
                    if previous.tzinfo is None: previous=previous.replace(tzinfo=clock.tzinfo)
                    if (clock-previous).total_seconds()<config.source_ttl_seconds: return None
                except (ValueError,TypeError): pass
            # Reserve the configured interval under the workspace lock before I/O.
            state.setdefault('source_status',{})['last_attempt_at']=clock.isoformat()
            state['version']=row.version+1
            changed=db.execute(update(self.W).where(self.W.id==wid,self.W.version==row.version).values(version=state['version'],data=storage.save(db,self.B,wid,state)))
            require(changed.rowcount==1,'來源同步排程版本衝突',409)
        return self.sync(wid,None)
