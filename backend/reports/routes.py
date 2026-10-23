"""Authenticated adapters for the shared PM reports contract."""
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
import os
import re
import unicodedata
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from .compute import TZ, monday, UnknownStatus, CaseNotFound
from .home import compose
from .reader import LarkReader
from .snapshot import SnapshotStore, ensure_visible_logs

SORTS={
    'review/rows':('date','group','person','case','points','status'),
    'sales':('code','name','client','pm','status','contract','progress_revenue','progress_cost','progress_billing','billable_unbilled','receivable'),
    'assets':('name','category','status','owner','uses','km','last_used','idle_days','daily_rent'),
    'progress':('case_code','case_name','planned','actual','planned_days','actual_days','matched_days','unplanned_days','achievement','diff','expected_total','done_total','remaining','status','name'),
}


PAGE_KEYS={'sort','order','offset','limit'}
ALLOWED={
    'review':{'dept','week','weeks','group','person'},
    'review/rows':PAGE_KEYS|{'dept','week','weeks','group','person','status','flag','q'},
    'progress':PAGE_KEYS|{'dept','week','group','scope','status','q'},
    'progress/case':{'key','dept','week'},
    'sales':PAGE_KEYS|{'status','pm'},
    'assets':PAGE_KEYS|{'kind','from','to','status','category','owner','idle_days','q'},
    'sources':set(),
    'home':set(),
}


def parameters(endpoint, query):
    p=dict(query)
    if 'q' in p: p['q']=unicodedata.normalize('NFKC',p['q']).strip()
    unknown=set(p)-ALLOWED[endpoint]
    if unknown: raise HTTPException(422,'不支援的查詢欄位：'+', '.join(sorted(unknown)))
    p={k:v.strip() if isinstance(v,str) and k!='key' else v for k,v in p.items()}
    p={k:v for k,v in p.items() if v!=''}
    if p.get('group'):
        from .compute import normalize_group
        p['group']=normalize_group(p['group'])
    def integer(key, default, minimum, maximum):
        try: n=int(p.get(key,default))
        except (ValueError,TypeError): raise HTTPException(422,f'{key} 必須為整數') from None
        if not minimum<=n<=maximum: raise HTTPException(422,f'{key} 超出範圍')
        p[key]=n
    def choice(key, default, choices):
        p.setdefault(key,default)
        if p[key] not in choices: raise HTTPException(422,f'{key} 不支援的值')
    def calendar(key, default):
        p.setdefault(key,default)
        from datetime import date
        try:
            parsed=date.fromisoformat(p[key])
            if parsed.isoformat()!=p[key]: raise ValueError()
        except (ValueError,TypeError): raise HTTPException(422,f'{key} 日期格式錯誤') from None
    today=datetime.now(TZ).date()
    if endpoint.startswith('review') or endpoint.startswith('progress'):
        choice('dept','field',('field','office','control') if endpoint.startswith('review') else ('field','office'))
        calendar('week',(today-timedelta(days=today.weekday()+7)).isoformat())
        if monday(p['week'])!=p['week']: raise HTTPException(422,'week 必須為週一')
        if today.year-30>int(p['week'][:4]) or int(p['week'][:4])>today.year+10: raise HTTPException(422,'week 超出範圍')
    if endpoint=='progress/case' and not re.fullmatch(r'rec[A-Za-z0-9]{1,64}',p.get('key','')): raise HTTPException(404,'case_not_found')
    if endpoint=='progress' and len(p.get('q',''))>50: raise HTTPException(422,'q 最多 50 字')
    if endpoint=='progress': choice('scope','week',('week','open'))
    if endpoint.startswith('review'): integer('weeks',12,1,104)
    if endpoint=='review/rows': choice('status','',('','passed','returned','pending','unset'))
    if endpoint=='assets':
        choice('kind','vehicle',('vehicle','instrument'))
        calendar('from',(today-timedelta(days=29)).isoformat());calendar('to',today.isoformat())
        if p['from']>p['to']: raise HTTPException(422,'from 不可晚於 to')
        if 'idle_days' in p: integer('idle_days',0,0,36500)
    if endpoint in SORTS:
        choice('sort',SORTS[endpoint][0],SORTS[endpoint]);choice('order','asc',('asc','desc'))
        integer('offset',0,0,10000000);integer('limit',50,1,200)
    for value in p.values():
        if isinstance(value,str) and len(value)>240: raise HTTPException(422,'查詢文字過長')
    return p


def register(app, identity, cfg=None, *, reader=None, authorize=None, live_enabled=None, allow=None, links=None):
    cfg=os.environ if cfg is None else cfg
    store=SnapshotStore(reader or LarkReader(cfg),cfg)
    ensure_visible_logs()
    app.state.reports=store
    if (str(cfg.get('REPORTS_ENABLED','true')).lower()=='true'
            and isinstance(store.reader,LarkReader) and cfg.get('LARK_APP_ID') and cfg.get('LARK_APP_SECRET')):
        lifespan=app.router.lifespan_context
        @asynccontextmanager
        async def reports_lifespan(app):
            store.start()
            async with lifespan(app) as state:
                yield state
        app.router.lifespan_context=reports_lifespan
    def gate(request):
        data,user=identity(request)
        if str(cfg.get('REPORTS_ENABLED','true')).lower()!='true': raise HTTPException(404,'報表未啟用')
        if data.get('mode')!='lark' or str(data.get('wid','')).startswith(('test-','demo-')):
            raise HTTPException(403,'報表僅限公司正式工作區')
        if allow is not None and not allow(data,user): raise HTTPException(403,'需要 PM 或主管權限查看週報')
        return data,user
    def handler(endpoint):
        def read(request: Request):
            try:
                data,user=gate(request)
                try:
                    params=parameters(endpoint,request.query_params)
                    if endpoint=='home':
                        snapshot=store.get()
                        result=compose(lambda name,p:store.result(name,p,snapshot=snapshot),store.meta(snapshot),parameters('review',{})['week'])
                    else: result=store.result(endpoint,params)
                except UnknownStatus as exc: raise HTTPException(422,str(exc)) from None
                except CaseNotFound: raise HTTPException(404,'case_not_found') from None
                if endpoint=='progress' and links is not None:
                    from .compute import attach_local_bridges
                    result=attach_local_bridges(result,links(data,user))
                if endpoint=='progress':
                    result['meta']['can_refresh']=False
                    if authorize is not None and live_enabled is not None and live_enabled(data['wid']):
                        try:
                            authorize(data['wid'],'sources',user)
                            result['meta']['can_refresh']=True
                        except HTTPException:
                            pass
                return JSONResponse(result,headers={'Cache-Control':'no-store'})
            except HTTPException as exc:
                return JSONResponse(exc.detail if isinstance(exc.detail,dict) else {'detail':str(exc.detail)},status_code=exc.status_code,headers={'Cache-Control':'no-store',**(exc.headers or {})})
        read.__name__='reports_'+endpoint.replace('/','_')
        return read
    for endpoint in ('review','review/rows','sales','assets','progress','progress/case','sources','home'):
        app.add_api_route('/api/reports/'+endpoint,handler(endpoint),methods=['GET'])
    @app.post('/api/reports/refresh')
    def refresh(request: Request):
        try:
            data,user=gate(request)
            if authorize is None or live_enabled is None or not live_enabled(data['wid']): raise HTTPException(403,'需要資料同步權限與即時讀取設定')
            authorize(data['wid'],'sources',user)
            future=store.start(manual=True)
            if future.done():
                try: future.result()
                except Exception: raise HTTPException(503,'報表來源暫時無法讀取') from None
            return JSONResponse({'meta':store.meta()},status_code=202 if not future.done() else 200,headers={'Cache-Control':'no-store'})
        except HTTPException as exc:
            return JSONResponse(exc.detail if isinstance(exc.detail,dict) else {'detail':str(exc.detail)},status_code=exc.status_code,headers={'Cache-Control':'no-store',**(exc.headers or {})})
    return store
