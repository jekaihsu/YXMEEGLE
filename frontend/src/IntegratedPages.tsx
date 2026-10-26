// P1-INT pages: #work -> MyWorkTable(buildMyWorkView(...)), #sources -> SourceHealth(buildSourceHealthView(...)).
// The legacy MyWork / Sources screens stay reachable through tab=legacy. Transport only; all state text comes
// from the view models. New GETs: /api/my-work and /api/source-health.
import {lazy, Suspense, useCallback, useEffect, useMemo, useState} from 'react';
import {api, liveRefresh, ApiError, getSessionEpoch, parseRoute} from './api';
const MyWorkTable=lazy(()=>import('./MyWorkTable'));
const AssignmentTable=lazy(()=>import('./MyWorkTable').then(module=>({default:module.AssignmentTable})));
import {buildLabel} from './buildIdentity';
import {buildMyWorkView} from './myWorkView.ts';
import {buildSourceHealthView} from './sourceHealthView.ts';
import {filtersFromRoute, hashOfRoute, isLegacyTab, myWorkInput, sourceHealthInput, withFilters} from './integrationRoutes.ts';
import {Segmented} from './design';
import {HOME_PANELS,useHomePanels,type HomePanel} from './useHomePanels';
import {Button} from './design';
import './ProjectCalm.css';
import type {Ctx} from './appCommon';

const SourceHealth = lazy(() => import('./SourceHealth').then(module => ({default: module.SourceHealth})));

export type Fetched = {status: 'loading'} | {status: 'ok'; body: unknown} | {status: 'error'; httpStatus?: number};

// The body is keyed by url, version, session epoch and user: any change reads as loading, so a previous user's
// rows are never shown while the refetch is in flight.
export function useFetched(url: string, version: unknown, userId: unknown): Fetched {
 const key = `${url}|${String(version)}|${getSessionEpoch()}|${String(userId)}`;
 const [state, setState] = useState<{key: string; fetched: Fetched}>({key, fetched: {status: 'loading'}});
 useEffect(() => {
  const epoch = getSessionEpoch();
  const controller = new AbortController();
  api<unknown>(url, {method: 'GET', signal: controller.signal, cache: 'no-store'})
   .then(body => {if (epoch === getSessionEpoch()) setState({key, fetched: {status: 'ok', body}})})
   .catch(error => {
    if (controller.signal.aborted || epoch !== getSessionEpoch()) return;
    setState({key, fetched: {status: 'error', httpStatus: error instanceof ApiError ? error.status : undefined}});
   });
  return () => controller.abort();
 }, [key, url]);
 return state.key === key ? state.fetched : {status: 'loading'};
}

export function LegacyTabs({c, view}: {c: Ctx; view: 'work' | 'sources'}) {
 const legacy = isLegacyTab(c.route, view);
 const labels = view === 'work' ? ['我的工作', '舊版工作清單'] : ['來源健康', '舊版來源與同步'];
 return <Segmented label={view === 'work' ? '我的工作檢視' : '資料來源檢視'} options={[['new', labels[0]], ['legacy', labels[1]]]}
  value={legacy ? 'legacy' : 'new'} onChange={v => c.go(v === 'legacy' ? {view, tab: 'legacy'} : {view})}/>;
}

// Set when a My Work row navigates away; the remounted page restores focus only when browser Back lands on that exact hash.
let pendingReturnHash: string | null = null;

function LegacyWorkPage({c}: {c: Ctx}) {
 const fetched = useFetched('/api/my-work', c.reloadVersion ?? c.w.version, c.s?.user?.id);
 const filters = useMemo(() => filtersFromRoute(c.route), [c.route]);
 const view = useMemo(() => buildMyWorkView(myWorkInput(fetched, filters)), [fetched, filters]);
 // Selection pushes a history entry (Back closes the drawer); typing replaces it.
 const update = useCallback((next: Partial<typeof filters>, replace: boolean) => c.go(withFilters(c.route, {...filters, ...next}), replace), [c, filters]);
 const navigate = useCallback((route: string) => {
  const hash = hashOfRoute(route);
  if (!hash) return;
  pendingReturnHash = location.hash;
  c.go(parseRoute(hash) as Ctx['route']);
 }, [c]);
 // Peek on every render (StrictMode safe); cleared once focus has been restored.
 const restoreFocus = pendingReturnHash !== null && pendingReturnHash === location.hash;
 const focusRestored = useCallback(() => {pendingReturnHash = null}, []);
 return <main className="page work-page" aria-label="我的工作">
  <LegacyTabs c={c} view="work"/>
  <Suspense fallback={<div aria-hidden="true" className="skeleton skeleton-row"/>}><MyWorkTable view={view} onSelect={id => update({selectedId: id}, false)} onModeChange={mode => update({mode, selectedId: null}, true)}
   onSearch={search => update({search}, true)} onNavigate={navigate}
   restoreFocus={restoreFocus} onFocusRestored={focusRestored}/></Suspense>
 </main>;
}

export function SourceHealthPage({c}: {c: Ctx}) {
 const health=useFetched('/api/health',0,c.s?.user?.id);
 const [attempt,setAttempt]=useState(0),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const fetched = useFetched('/api/source-health', `${c.reloadVersion ?? c.w.version}:${attempt}`, c.s?.user?.id);
 const view = useMemo(() => buildSourceHealthView(sourceHealthInput(fetched), {diagnosticCapability: true}), [fetched]);
 const retry=async(handle:unknown)=>{
  if(busy || !handle || typeof handle!=='object' || !('dataset' in handle) || handle.dataset!=='sources')return;
  const epoch=getSessionEpoch();setBusy(true);setError('');
  try{await liveRefresh(['sources'],true,undefined,true)}
  catch{if(epoch===getSessionEpoch())setError('更新失敗，請重試')}
  finally{if(epoch===getSessionEpoch()){setBusy(false);setAttempt(n=>n+1)}}
 };
 return <main className="page sources-page" aria-label="資料來源">
  <LegacyTabs c={c} view="sources"/>
  {error&&<p role="alert">{error}</p>}
  <Suspense fallback={<p role="status">正在載入來源健康…</p>}><SourceHealth view={view} onRetry={retry} busy={busy}/></Suspense>
  {c.s.user?.role==='manager'&&<small className="source-build-id" aria-label="部署版本">{buildLabel(health.status==='ok'?health.body:null)}</small>}
 </main>;
}


export function WorkPage({c}:{c:Ctx}) {return c.s?.features && ('change_extension' in c.s.features || 'node_assignment' in c.s.features) ? <AssignmentWorkPage c={c}/> : <LegacyWorkPage c={c}/>}
function AssignmentWorkPage({c}:{c:Ctx}) {
 const panel=HOME_PANELS.find(p=>p===c.route.tab) ?? 'assigned';
 const params=new URLSearchParams(c.route.ctx);
 const scope=params.get('scope')==='team' ? 'team' : 'mine';
 const read=useHomePanels(c,{panel,scope,q:params.get('q')||'',deadline:params.get('deadline')||'all',cursor:params.get('cursor')||'',kinds:params.get('kinds')||undefined},true,true);
 const update=(changes:Record<string,string>,nextPanel:HomePanel=panel)=>{
  const next=new URLSearchParams(c.route.ctx);
  next.delete('cursor');
  if(nextPanel==='proxy' || nextPanel==='local')next.set('scope','mine');
  for(const [key,value] of Object.entries(changes))value ? next.set(key,value) : next.delete(key);
  c.go({view:'work',tab:nextPanel,ctx:next.toString()},true);
 };
 return <main className="page work-page project-detail-calm" aria-label="我的工作完整表格">
  <header className="section-heading"><h1>我的工作</h1><Button disabled={read.pending} onClick={()=>void c.refresh()}>重新讀取</Button></header>
  <div className="my-work-toolbar">
   <label>工作清單<select value={panel} onChange={e=>{const next=HOME_PANELS.find(p=>p===e.target.value);if(next)update({},next)}}>
    <option value="assigned">指派給我</option><option value="confirmation">待我確認</option><option value="delegated">我交辦的</option><option value="proxy">代理給我</option><option value="local">本地 SOP</option><option value="completed">已完成</option>
   </select></label>
   <label>工作類型<select value={params.get('kinds')||''} onChange={e=>update({kinds:e.target.value})}><option value="">全部類型</option><option value="sop_task">SOP 任務</option><option value="node_assignment">節點責任</option><option value="task">Lark 任務</option></select></label>
   <label>期限<select value={params.get('deadline')||'all'} onChange={e=>update({deadline:e.target.value})}><option value="all">全部期限</option><option value="unscheduled">未排期限</option></select></label>
   <label>搜尋<input placeholder="搜尋任務、案件或關鍵字" type="search" value={params.get('q')||''} onChange={e=>update({q:e.target.value})}/></label>
   {(read.body?.manager_view_available || scope==='team') && <label>範圍<select value={scope} onChange={e=>update({scope:e.target.value})}><option value="mine">我的工作</option><option value="team">同組</option></select></label>}
  </div>
  {read.pending&&<p className="my-work-loading" role="status">正在讀取工作…</p>}
  {read.body && <>{read.body.items.length ? <>
   <p className="my-work-banner-as-of">已讀取 {read.body.items.length} 項工作{read.body.as_of?` · 更新於 ${new Intl.DateTimeFormat('zh-TW',{timeZone:'Asia/Taipei',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(read.body.as_of))}`:''}{!read.body.complete?' · 部分來源待讀取':''}{read.body.freshness.status==='stale'?' · 上次資料':''}</p>
   <Suspense fallback={<p className="my-work-loading" role="status">正在載入工作…</p>}><AssignmentTable items={read.body.items} onNavigate={c.go}/></Suspense>
  </> : !read.pending&&<p role="status">{read.body.complete ? '目前沒有符合條件的工作。' : '工作來源尚未完整，請重新讀取。'}</p>}</>}
  {!read.body&&!read.pending&&!read.error&&<p role="status">工作暫時無法讀取，請重新讀取。</p>}
  <div className="my-work-actions">
   {params.has('cursor') && <Button onClick={()=>update({})}>回第一頁</Button>}
   {read.body?.next_cursor && <Button onClick={()=>update({cursor:read.body?.next_cursor||''})}>下一頁</Button>}
   {read.error && <p role="status">{read.error}</p>}
  </div>
 </main>;
}
