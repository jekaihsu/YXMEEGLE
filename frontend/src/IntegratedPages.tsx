import {SopWorkList} from './SopWorkInbox';
import {parseSopWork} from './SopWorkSummary';
// P1-INT pages: #work -> MyWorkTable(buildMyWorkView(...)), #sources -> SourceHealth(buildSourceHealthView(...)).
// The legacy MyWork / Sources screens stay reachable through tab=legacy. Transport only; all state text comes
// from the view models. New GETs: /api/my-work and /api/source-health.
import {lazy, Suspense, useCallback, useEffect, useMemo, useState} from 'react';
import {api, ApiError, getSessionEpoch, parseRoute} from './api';
const MyWorkTable=lazy(()=>import('./MyWorkTable'));
const AssignmentTable=lazy(()=>import('./MyWorkTable').then(module=>({default:module.AssignmentTable})));
import {buildMyWorkView} from './myWorkView.ts';
import {buildSourceHealthView} from './sourceHealthView.ts';
import {filtersFromRoute, hashOfRoute, isLegacyTab, myWorkInput, sourceHealthInput, withFilters} from './integrationRoutes.ts';
import {Segmented} from './design';
import {HOME_PANELS,useHomePanels,type HomePanel} from './useHomePanels';
import {PanelStatus} from './DailyHome';
import {Button} from './design';
import type {Ctx} from './appCommon';
export {DispatchWorkflowPage as DispatchPage} from './DispatchWorkflowPage';

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
  <LegacyTabs c={c} view="work"/><SopWorkList data={fetched.status==='ok'&&fetched.body&&typeof fetched.body==='object'&&'sop_work' in fetched.body?parseSopWork(fetched.body.sop_work):null}/>
  <Suspense fallback={<div aria-hidden="true" className="skeleton skeleton-row"/>}><MyWorkTable view={view} onSelect={id => update({selectedId: id}, false)} onModeChange={mode => update({mode, selectedId: null}, true)}
   onSearch={search => update({search}, true)} onNavigate={navigate}
   restoreFocus={restoreFocus} onFocusRestored={focusRestored}/></Suspense>
 </main>;
}

export function SourceHealthPage({c}: {c: Ctx}) {
 const fetched = useFetched('/api/source-health', c.reloadVersion ?? c.w.version, c.s?.user?.id);
 // G-DIAG is open: no diagnostic capability exists, so the page shows the page state only.
 const view = useMemo(() => buildSourceHealthView(sourceHealthInput(fetched), {diagnosticCapability: false}), [fetched]);
 return <main className="page sources-page" aria-label="資料來源">
  <LegacyTabs c={c} view="sources"/>
  <Suspense fallback={<p role="status">正在載入來源健康…</p>}><SourceHealth view={view}/></Suspense>
 </main>;
}


export function WorkPage({c}:{c:Ctx}) {return c.s?.features && ('change_extension' in c.s.features || 'node_assignment' in c.s.features) ? <AssignmentWorkPage c={c}/> : <LegacyWorkPage c={c}/>}
function AssignmentWorkPage({c}:{c:Ctx}) {
 const panel=HOME_PANELS.find(p=>p===c.route.tab) ?? 'assigned';
 const params=new URLSearchParams(c.route.ctx);
 const scope=params.get('scope')==='team' ? 'team' : 'mine';
 const read=useHomePanels(c,{panel,scope,q:params.get('q')||'',deadline:params.get('deadline')||'all',cursor:params.get('cursor')||''},true,true);
 const update=(changes:Record<string,string>,nextPanel:HomePanel=panel)=>{
  const next=new URLSearchParams(c.route.ctx);
  next.delete('cursor');
  if(nextPanel==='proxy' || nextPanel==='local')next.set('scope','mine');
  for(const [key,value] of Object.entries(changes))value ? next.set(key,value) : next.delete(key);
  c.go({view:'work',tab:nextPanel,ctx:next.toString()},true);
 };
 return <main className="page work-page" aria-label="我的工作完整表格">
  <h1>我的工作</h1><SopWorkList data={parseSopWork(read.body?.sop_work)}/>
  <div className="my-work-toolbar">
   <label>工作清單<select value={panel} onChange={e=>{const next=HOME_PANELS.find(p=>p===e.target.value);if(next)update({},next)}}>
    <option value="assigned">指派給我</option><option value="confirmation">待我確認</option><option value="delegated">我交辦的</option><option value="proxy">代理給我</option><option value="local">本地 SOP</option><option value="completed">已完成</option>
   </select></label>
   <label>期限<select value={params.get('deadline')||'all'} onChange={e=>update({deadline:e.target.value})}><option value="all">全部期限</option><option value="unscheduled">未排期限</option></select></label>
   <label>搜尋<input placeholder="搜尋任務、案件或關鍵字" type="search" value={params.get('q')||''} onChange={e=>update({q:e.target.value})}/></label>
   {(read.body?.manager_view_available || scope==='team') && <label>範圍<select value={scope} onChange={e=>update({scope:e.target.value})}><option value="mine">我的工作</option><option value="team">同組</option></select></label>}
  </div>
  <PanelStatus read={read}/>
  {read.body && <><p>節點責任 {read.body.counts.node_assignments ?? '未知'} 項 · 任務 {read.body.counts.tasks ?? '未知'} 項{read.body.counts.local_workflow ? ` · 本地 SOP ${read.body.counts.local_workflow} 項` : ''}</p>
  <Suspense fallback={<p className="my-work-loading" role="status">正在載入工作…</p>}><AssignmentTable items={read.body.items} onNavigate={c.go}/></Suspense>
   {!read.body.items.length && <p>{read.body.complete ? '目前沒有符合條件的工作' : '工作來源待核對'}</p>}
  </>}
  <div className="my-work-actions">
   {params.has('cursor') && <Button onClick={()=>update({})}>回第一頁</Button>}
   {read.body?.next_cursor && <Button onClick={()=>update({cursor:read.body?.next_cursor||''})}>下一頁</Button>}
   {read.error && <p role="status">{read.error}</p>}
  </div>
 </main>;
}
