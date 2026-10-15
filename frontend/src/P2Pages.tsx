import {cachedPanel, readPanel} from './companyDashboardCache';
// P2-INT-F pages: #view=overview | confirmations | confirmation | contract | workitem (VCC-128..132).
// Read-only. Transport only: every state text comes from the view models or dataState labels. All navigation and
// return context is built by drilldownContext.ts (drill / back / backTo / linkOut) through p2Routes.ts.
// Not changed: the legacy #project, #projects, #work and #sources views stay reachable from the left navigation.
import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {ApiError, getSessionEpoch, parseRoute} from './api';
import {ManagerOverview} from './ManagerOverview';
import {ConfirmationList} from './ConfirmationList';
import {CaseDetail} from './CaseDetail';
import {ContractDetail} from './ContractDetail';
import {WorkItemDetail} from './WorkItemDetail';
import {buildManagerOverviewView} from './managerOverviewView.ts';
import {buildConfirmationListView} from './confirmationListView.ts';
import {buildCaseDetailView} from './caseDetailView.ts';
import {buildContractDetailView} from './contractDetailView.ts';
import {buildWorkItemDetailView} from './workItemDetailView.ts';
import type {WorkItemTab} from './workItemDetailView.ts';
import {Skeleton} from './design';
import {DATA_STATE_LABELS} from './dataState.ts';
import {backTo, breadcrumbs, drill, linkOut} from './drilldownContext.ts';
import type {P2Context, P2Route, SortSpec} from './drilldownContext.ts';
import {boundHistory, caseNavigate, caseSelection, confirmationKeyOfRow, detailNavigate, kpiDrill, p2Back, p2Failure,
 p2Gate, p2Request, p2RouteOfContext, recordPage, sameFilters} from './p2Routes.ts';
import type {HistoryStore, P2Failure} from './p2Routes.ts';
import type {Ctx} from './appCommon';
import type {Route} from './types';

type Fetched = {status: 'loading'} | {status: 'ok'; body: unknown; updateFailed?: boolean} | {status: 'error'; httpStatus?: number};
const ROUTE_LABEL: Record<P2Route, string> = {overview: '管理總覽', confirmations: '工程確認單', confirmation: '案件與確認單詳情', contract: '合約明細', workitem: '工作項'};

// One GET per (url, retry, session, user). A previous user's body is never shown while the refetch is in flight.
function useP2Read(url: string | null, retry: number, version: unknown, userId: unknown): Fetched {
 const key = `${url}|${retry}|${String(version)}|${getSessionEpoch()}|${String(userId)}`;
 const [state, setState] = useState<{key: string; fetched: Fetched}>(() => {const body=url?cachedPanel(url,String(userId)):undefined;return {key,fetched:body===undefined?{status:'loading'}:{status:'ok',body}}});
 useEffect(() => {
  if (!url) return;
  const epoch = getSessionEpoch();
  const controller = new AbortController();
  readPanel(url, controller.signal,String(userId),{timeoutMs:60000,reloadVersion:JSON.stringify([version,retry])})
   .then(body => {if (!controller.signal.aborted && epoch === getSessionEpoch()) setState({key, fetched: {status: 'ok', body}})})
   .catch(error => {
    if (controller.signal.aborted || epoch !== getSessionEpoch()) return;
    const retained=cachedPanel(url,String(userId));
    if(retained!==undefined&&!(error instanceof ApiError&&(error.status===401||error.status===403)))setState({key,fetched:{status:'ok',body:retained,updateFailed:true}});
    else setState({key, fetched: {status: 'error', httpStatus: error instanceof ApiError ? error.status : undefined}});
   });
  return () => controller.abort();
 }, [key, url]);
 const cached=url?cachedPanel(url,String(userId)):undefined;
 return state.key === key ? state.fetched : cached===undefined?{status:'loading'}:{status:'ok',body:cached};
}

// Per-owner memory so Back restores what was open on a page (cursor history, drawer selection, tab); module-level on purpose.
let memoryOwner = '';
const cursorStore: HistoryStore = new Map();
const uiMemory = new Map<string, Record<string, unknown>>();
function ownMemory(owner: string) {
 if (owner === memoryOwner) return;
 memoryOwner = owner; cursorStore.clear(); uiMemory.clear();
}
function useDetailUi<T extends Record<string, unknown>>(slot: string, initial: T): [T, (patch: Partial<T>) => void] {
 const [ui, setUi] = useState<T>(() => ({...initial, ...(uiMemory.get(slot) as Partial<T> | undefined)}));
 useEffect(() => {setUi({...initial, ...(uiMemory.get(slot) as Partial<T> | undefined)})}, [slot]); // eslint-disable-line react-hooks/exhaustive-deps
 const patch = useCallback((next: Partial<T>) => setUi(prev => {const merged = {...prev, ...next}; uiMemory.set(slot, merged); return merged}), [slot]);
 return [ui, patch];
}

function Notice({state, message, httpStatus, onRetry, children}: {state: string; message: string; httpStatus?: number | null; onRetry?: () => void; children?: React.ReactNode}) {
 return <section className={`p2-banner state-${state}`} role={state === 'loading' ? 'status' : 'alert'} aria-live="polite">
  <div className="p2-banner-header"><span className="p2-banner-title">{DATA_STATE_LABELS[state as keyof typeof DATA_STATE_LABELS] ?? state}</span></div>
  <p>{message}{httpStatus ? <small>（HTTP {httpStatus}）</small> : null}</p>
  {children}
  {onRetry && <button type="button" className="button compact" onClick={onRetry}>重新讀取</button>}
 </section>;
}
function FailureNotice({failure, onRetry}: {failure: P2Failure; onRetry: () => void}) {
 return <Notice state={failure.state} message={failure.message} httpStatus={failure.httpStatus} onRetry={failure.retry ? onRetry : undefined}/>;
}

export function P2Page({c}: {c: Ctx}) {
 const route = c.route;
 const parsed = useMemo(() => p2Gate(route), [route.view, route.ctx]); // eslint-disable-line react-hooks/exhaustive-deps
 const context = parsed.context;
 const userId = JSON.stringify([c.s?.user?.id,c.s?.user?.role,c.s.workspace_id,c.w.workspace_id]);
 ownMemory(`${getSessionEpoch()}|${String(userId)}`);
 const [notice, setNotice] = useState('');
 const [retry, setRetry] = useState(0);
 const open = useCallback((next: P2Context, replace = false) => {
  const target = p2RouteOfContext(next);
  if (!target) {setNotice('無法建立這個連結：條件或返回脈絡超出上限。目前頁面維持不變。'); return;}
  setNotice('');
  c.go(target as Route, replace);
 }, [c]);
 const openExisting = useCallback((hashOrRoute: string | null) => {
  if (!hashOrRoute) {setNotice('此連結不是系統已有的頁面，未開啟。'); return;}
  setNotice('');
  c.go(parseRoute(hashOrRoute) as Route);
 }, [c]);
 const goBack = context.stack.length ? () => {const r = p2Back(context); if (r.ok) open(r.value); else setNotice('無法返回上一層：返回脈絡已損毀。');} : undefined;
 const version = c.reloadVersion ?? c.w.version;
 const crumbs = breadcrumbs(context);
 const pageRequest = useMemo(() => parsed.ok ? p2Request(context) : null, [route.view, route.ctx]); // eslint-disable-line react-hooks/exhaustive-deps
 const fetched = useP2Read(pageRequest?.ok ? pageRequest.url : null, retry, version, userId);
 const failure = fetched.status === 'error' ? p2Failure(context.route, fetched) : null;
 const onRetry = () => setRetry(n => n + 1);
 const openSources = () => openExisting(linkOut('sources').ok ? 'view=sources' : null);
 const openEntryPoint = (entry: string) => {const l = linkOut('entry_point', entry); openExisting(l.ok ? l.hash : null);};
 const body = fetched.status === 'ok' ? fetched.body : undefined;
 let page: React.ReactNode;
 if (!parsed.ok) page = <InvalidContext label={ROUTE_LABEL[context.route]} onReset={() => open(context, true)}/>;
 else if (!pageRequest?.ok) page = <UnsupportedFilters unsupported={pageRequest?.ok === false ? pageRequest.unsupported : []} invalid={pageRequest?.ok === false ? pageRequest.invalid : []} unlocated={pageRequest?.ok === false && pageRequest.reason === 'unlocated'}
  onReset={() => open({...context, filters: {}, cursor: null}, true)}/>;
 else if (fetched.status === 'loading' && context.route !== 'confirmations') page = <div className="p2-card" aria-hidden="true"><Skeleton lines={6}/></div>;
 else if (failure && !(failure.state === 'forbidden' && context.route === 'confirmations')) page = <FailureNotice failure={failure} onRetry={onRetry}/>;
 else if (context.route === 'overview') page = <OverviewBody context={context} body={body} open={open} openEntryPoint={openEntryPoint} openSources={openSources} setNotice={setNotice} goBack={goBack}/>;
 else if (context.route === 'confirmations') page = <ConfirmationsBody context={context} body={failure ? {status: 403} : body} loading={fetched.status === 'loading'} open={open} setNotice={setNotice}/>;
 else if (context.route === 'confirmation') page = <CaseBody context={context} body={body} open={open} openExisting={openExisting} goBack={goBack} setNotice={setNotice}/>;
 else if (context.route === 'contract') page = <ContractBody context={context} body={body} open={open} setNotice={setNotice} goBack={goBack}/>;
 else page = <WorkItemBody context={context} body={body} open={open} openExisting={openExisting} setNotice={setNotice} goBack={goBack}/>;
 return <main className="page p2-page" aria-label={ROUTE_LABEL[context.route]}>
  {crumbs.length > 1 && <nav className="p2-breadcrumb" aria-label="返回路徑">
   {goBack && (context.route === 'overview' || context.route === 'confirmations') && <button type="button" className="p2-btn p2-btn-plain" onClick={goBack}>返回上一層</button>}
   <ol className="p2-breadcrumb-list">
    {crumbs.map((crumb, depth) => <li key={depth} className="p2-breadcrumb-item">
     {depth === crumbs.length - 1
      ? <strong aria-current="page">{ROUTE_LABEL[crumb.route]}</strong>
      : <><button type="button" className="p2-breadcrumb-link" onClick={() => {const r = backTo(context, depth); if (r.ok) open(r.value);}}>{ROUTE_LABEL[crumb.route]}</button><span className="p2-breadcrumb-separator" aria-hidden="true">/</span></>}
    </li>)}
   </ol>
  </nav>}
  {notice && <div className="error-banner" role="alert"><span>{notice}</span></div>}
  {fetched.status==='ok'&&fetched.updateFailed&&<Notice state="read_failed" message="上次資料，更新失敗。資料日期保留原快照時間。" onRetry={onRetry}/>}
  {page}
 </main>;
}

function InvalidContext({label, onReset}: {label: string; onReset: () => void}) {
 return <Notice state="unknown" message={`網址中的篩選或返回脈絡無法驗證，因此沒有讀取「${label}」的資料（不會改用較寬的條件代替）。`}>
  <button type="button" className="button compact" onClick={onReset}>清除並重新開啟（不含篩選）</button>
 </Notice>;
}

function UnsupportedFilters({unsupported, invalid, unlocated, onReset}: {unsupported: string[]; invalid: string[]; unlocated: boolean; onReset: () => void}) {
 if (unlocated) return <Notice state="unlocated" message="找不到此項目，或你沒有權限檢視。"/>;
 return <Notice state="unknown" message="這組篩選條件無法完整送到伺服器，因此沒有讀取資料（不會用較寬的條件代替）。">
  {!!unsupported.length && <p>伺服器沒有對應欄位：{unsupported.join('、')}</p>}
  {!!invalid.length && <p>內容無法使用：{invalid.join('、')}</p>}
  <button type="button" className="button compact" onClick={onReset}>清除篩選</button>
 </Notice>;
}

type Open = (next: P2Context, replace?: boolean) => void;

function OverviewBody({context, body, open, openEntryPoint, openSources, setNotice, goBack}: {context: P2Context; body: unknown; open: Open; openEntryPoint: (r: string) => void; openSources: () => void; setNotice: (m: string) => void; goBack?: () => void}) {
 const view = useMemo(() => buildManagerOverviewView({body, filters: overviewFilters(context), sort: context.sort, period: context.period, selectedId: context.selected}), [body, context]);
 const caseOpen = view.snapshot.cases.some(row => row.id === view.selectedId);
 const [pm, setPm] = useState(context.filters.pm ?? '');
 const [status, setStatus] = useState(context.filters.execution_state ?? '');
 useEffect(() => {setPm(context.filters.pm ?? ''); setStatus(context.filters.execution_state ?? '')}, [context.filters]);
 const apply = (event: React.FormEvent) => {
  event.preventDefault();
  const filters: Record<string, string> = {};
  if (pm.trim()) filters.pm = pm.trim();
  if (status.trim()) filters.execution_state = status.trim();
  open({...context, filters, selected: null}, true);
 };
 const filters = <form className="p2-toolbar" onSubmit={apply} aria-label="案件篩選">
   <div className="p2-toolbar-left">
    <div className="p2-filter-field"><label className="p2-filter-label" htmlFor="p2-ov-pm">案件負責人</label><input id="p2-ov-pm" className="p2-filter-input" value={pm} maxLength={120} onChange={e => setPm(e.target.value)}/></div>
    <div className="p2-filter-field"><label className="p2-filter-label" htmlFor="p2-ov-status">執行狀態</label><input id="p2-ov-status" className="p2-filter-input" value={status} maxLength={120} onChange={e => setStatus(e.target.value)}/></div>
   </div>
   <div className="p2-toolbar-right">
    <button type="submit" className="p2-btn-reset-filters">套用</button>
    <button type="button" className="p2-btn-reset-filters" onClick={() => open({...context, filters: {}, selected: null}, true)}>清除篩選</button>
   </div>
  </form>;
 return <>
  <ManagerOverview view={view} filters={filters}
   onSelect={id => open({...context, selected: id}, true)}
   onSort={sort => open({...context, sort}, true)}
   onBack={goBack}
   onDrilldown={drilldown => {
    const card = view.snapshot.cards.find(item => item.drilldown === drilldown);
    const result = card ? kpiDrill(context, drilldown, card.id) : null;
    if (result?.ok) open(result.value); else setNotice('這張卡片的篩選條件無法完整帶入確認單清單，因此沒有開啟。');
   }}
   onNavigate={openEntryPoint} onSourceHealthLink={openSources}/>
  {caseOpen && view.selectedId && <p><button type="button" className="p2-btn p2-btn-plain" onClick={() => {
   const result = drill(context, 'confirmation', {selected: caseSelection(view.selectedId!)});
   if (result.ok) open(result.value); else setNotice('無法開啟案件詳情。');
  }}>開啟案件與確認單詳情</button></p>}
 </>;
}
const overviewFilters = (context: P2Context) => ({
 ...(context.filters.pm ? {pm_id: context.filters.pm} : {}), ...(context.filters.execution_state ? {execution_status: context.filters.execution_state} : {}),
});

const COMMIT_DELAY_MS = 400;
function ConfirmationsBody({context, body, loading, open, setNotice}: {context: P2Context; body: unknown; loading: boolean; open: Open; setNotice: (m: string) => void}) {
 // F1: the controls stay mounted through reads. Edits live in `draft`; the hash/query is committed after a pause (or on blur/Enter-free change of a select)
 // and the table shows loading, never the previous rows, while draft and committed query differ.
 const [draft, setDraft] = useState<Record<string, string>>(context.filters);
 const lastCommitted = useRef<Record<string, string>>(context.filters);
 const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
 const latest = useRef({context, open});
 latest.current = {context, open};
 useEffect(() => {
  if (!sameFilters(context.filters, lastCommitted.current)) {setDraft(context.filters); lastCommitted.current = context.filters;} // external change: Back, reset, link
 }, [context.filters]);
 useEffect(() => () => {if (timer.current) clearTimeout(timer.current)}, []);
 const commit = (filters: Record<string, string>) => {
  if (timer.current) clearTimeout(timer.current);
  timer.current = setTimeout(() => {
   timer.current = null;
   const {context: current, open: go} = latest.current;
   if (sameFilters(filters, current.filters)) return;
   lastCommitted.current = filters;
   go({...current, cursor: null, selected: null, filters}, true);
  }, COMMIT_DELAY_MS);
 };
 const edit = (filters: Record<string, string>) => {const next = withoutEmpty(filters); setDraft(next); commit(next);};
 const pending = !sameFilters(draft, context.filters);
 const showBody = pending || loading ? {status: 200, page_state: {states: ['loading'], count: null},
  rows: [], next_cursor: null, totals: {matching: null, loaded: 0, authorized_source: null}} : body;
 const view = useMemo(() => buildConfirmationListView(showBody, {filters: draft, sort: context.sort, cursor: context.cursor, columns: context.columns??['case_number','project_name','confirmation_version','pm','admission_state','source_status'], selected: context.selected,
  cursorHistory: boundHistory(cursorStore, context.filters, context.sort, context.cursor)}), [showBody, draft, context]);
 // Any change to the query (sort) restarts at page one and drops the selection.
 const requery = (next: Partial<P2Context>) => open({...context, cursor: null, selected: null, ...next}, true);
 const rows = body && typeof body === 'object' && Array.isArray((body as {rows?: unknown}).rows) ? (body as {rows: {row_key?: unknown; case_link?: {project_id?: unknown}}[]}).rows : [];
 const proximity=useRef<HTMLDivElement>(null);
 useEffect(()=>{
  const cursor=view.pagination.next.cursor;
  const connection='connection' in navigator?navigator.connection:null;
  if(!cursor||pending||loading||typeof IntersectionObserver==='undefined'||connection&&typeof connection==='object'&&('saveData' in connection&&connection.saveData||'effectiveType' in connection&&['slow-2g','2g'].includes(String(connection.effectiveType))))return;
  const request=p2Request({...context,cursor});
  if(!request.ok||!proximity.current)return;
  const controller=new AbortController();
  const observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){observer.disconnect();void readPanel(request.url,controller.signal,memoryOwner.split('|').slice(1).join('|'),{timeoutMs:60000}).catch(()=>{})}},{rootMargin:'600px'});
  observer.observe(proximity.current);
  return()=>{observer.disconnect();controller.abort()};
 },[view.pagination.next.cursor,pending,loading,context]);
 return <><ConfirmationList view={view}
  onSelect={key => open({...context, selected: key}, true)}
  onSort={(sort: SortSpec) => requery({sort})}
  onSearch={search => edit({...draft, search})}
  onFilterChange={filters => edit(filters)}
  onResetFilters={() => {if (timer.current) clearTimeout(timer.current); setDraft({}); lastCommitted.current = {}; requery({filters: {}})}}
  onColumnToggle={column => {
   const shown = view.columns.filter(col => col.visible).map(col => col.key);
   const columns = shown.includes(column) ? shown.filter(key => key !== column) : view.columns.filter(col => col.visible || col.key === column).map(col => col.key);
   open({...context, columns}, true);
  }}
  onPage={cursor => {recordPage(cursorStore, context.filters, context.sort, context.cursor, cursor); open({...context, cursor, selected: null}, true);}}
  onNavigate={rowKey => {
   const row = rows.find(item => item.row_key === rowKey);
   const projectId = row?.case_link?.project_id;
   const confirmation = confirmationKeyOfRow(rowKey);
   if (typeof projectId !== 'string' || !projectId) {setNotice('這筆確認單尚未對應到案件（對應未驗證），無法開啟案件詳情。'); return;}
   const result = drill({...context, selected: rowKey}, 'confirmation', {selected: caseSelection(projectId, confirmation)});
   if (result.ok) open(result.value); else setNotice('無法開啟案件詳情。');
  }}/><div ref={proximity} aria-hidden="true"/></>;
}
const withoutEmpty = (filters: Readonly<Record<string, string>>): Record<string, string> =>
 Object.fromEntries(Object.entries(filters).filter(([, value]) => typeof value === 'string' && value.trim() !== ''));

function CaseBody({context, body, open, openExisting, goBack, setNotice}: {context: P2Context; body: unknown; open: Open; openExisting: (h: string | null) => void; goBack?: () => void; setNotice: (m: string) => void}) {
 const slot = `case|${context.selected}|${context.stack.length}`;
 const [ui, patch] = useDetailUi<{selected: string | null; sort: SortSpec}>(slot, {selected: null, sort: null});
 const view = useMemo(() => buildCaseDetailView(body, {selected: ui.selected, sort: ui.sort}), [body, ui]);
 return <CaseDetail view={view} currentSort={ui.sort} onBack={goBack}
  onSelect={key => patch({selected: key})}
  onSort={sort => patch({sort: typeof sort === 'string' ? {key: sort, dir: 'asc'} : sort})}
  onNavigate={target => {
   if (typeof target === 'string') {openExisting(linkOut('entry_point', target).ok ? (linkOut('entry_point', target) as {hash: string}).hash : null); return;}
   if (target.view === 'sources') {openExisting('view=sources'); return;}
   if (target.view === 'project' && typeof target.project === 'string') {
    const hash = new URLSearchParams({view: 'project', project: target.project, ...(typeof target.tab === 'string' ? {tab: target.tab} : {}), ...(typeof target.section === 'string' ? {section: target.section} : {})}).toString();
    const l = linkOut('entry_point', `/#${hash}`);
    openExisting(l.ok ? l.hash : null); return;
   }
   const next = caseNavigate(context, target);
   if (next?.result.ok) open(next.result.value, next.mode === 'replace'); else setNotice('這個項目無法開啟（沒有可用的來源鍵或不在允許的導覽路徑）。');
  }}/>;
}

function ContractBody({context, body, open, setNotice, goBack}: {context: P2Context; body: unknown; open: Open; setNotice: (m: string) => void; goBack?: () => void}) {
 const slot = `contract|${context.selected}|${context.stack.length}`;
 const [ui, patch] = useDetailUi<{selected: string | null; sort: SortSpec}>(slot, {selected: null, sort: null});
 const view = useMemo(() => buildContractDetailView(body, {selected: ui.selected, sort: ui.sort}), [body, ui]);
 return <ContractDetail view={view} onBack={goBack}
  onSelect={key => patch({selected: key})}
  onSort={column => patch({sort: ui.sort?.key === column && ui.sort.dir === 'asc' ? {key: column, dir: 'desc'} : {key: column, dir: 'asc'}})}
  onNavigate={target => {
   const next = detailNavigate(context, target);
   if (next?.ok) open(next.value); else setNotice('這個項目無法開啟：缺少所屬案件或來源鍵，不會自行推測。');
  }}/>;
}

function WorkItemBody({context, body, open, openExisting, setNotice, goBack}: {context: P2Context; body: unknown; open: Open; openExisting: (h: string | null) => void; setNotice: (m: string) => void; goBack?: () => void}) {
 const slot = `workitem|${context.selected}|${context.stack.length}`;
 const [ui, patch] = useDetailUi<{tab: WorkItemTab; selectedKey: string | null; sortDir: 'asc' | 'desc'; historyExpanded: boolean}>(slot, {tab: 'work_content', selectedKey: null, sortDir: 'desc', historyExpanded: false});
 const view = useMemo(() => buildWorkItemDetailView({body, ui}), [body, ui]);
 return <WorkItemDetail view={view} onBack={goBack}
  onSelect={selectedKey => patch({selectedKey})} onTabChange={tab => patch({tab})} onSort={sortDir => patch({sortDir})} onHistoryExpand={historyExpanded => patch({historyExpanded})}
  onNavigate={target => {
   if (target.view === 'sources') {openExisting('view=sources'); return;}
   if (target.view === 'project') {
    const l = linkOut('entry_point', `/#${new URLSearchParams({view: 'project', project: target.projectId, tab: target.tab}).toString()}`);
    openExisting(l.ok ? l.hash : null); return;
   }
   const next = detailNavigate(context, {route: target.view, key: target.key});
   if (next?.ok) open(next.value); else setNotice('這個項目無法開啟：缺少所屬案件或來源鍵，不會自行推測。');
  }}/>;
}
