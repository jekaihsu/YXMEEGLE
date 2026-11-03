import {api,ApiError} from './api';
import {CaseStatus} from './CaseStatus';
import {PickerPopover} from './design/PickerPopover';
import {Select as FormSelect} from './design/Select';
import {useSourceRefresh} from './useSourceRefresh';
import {useEffect, useMemo, useRef, useState, type ReactNode} from 'react';
import {readLibraryMemory,writeLibraryMemory} from './libraryMemory';
import {ArrowDown, ArrowRight, CircleCheck, Clock3, Copy, FileText, LayoutGrid, List, MoreVertical, Pin, Plus, Search, Settings2, Star, UserRound, X} from 'lucide-react';
import {usePageOwner,usePageResource} from './viewData';
import {tableCalendarDay} from './companyDashboardCache';
import {taipeiDate, taipeiTime} from './taipeiTime';
import {AdmissionCell, ExecutionAdmissionQueue} from './ExecutionAdmission';
import {Ctx} from './appCommon';
import {Skeleton,DataState,Sheet} from './design';
import {createPortal} from 'react-dom';
import {QuoteCreateSheet} from './QuoteCreateSheet';
import {caseRow, caseBadge, revealedCount, caseAttention, filterRows, groupRows, portfolioCounts, pinStorageKey, readPins, writePins, verification, DEFAULT_FILTERS, type CaseFilters, type CaseRow, type PortfolioPage} from './projectsListModel';
import './ProjectsList.css';

const GROUP_ICONS:Record<string,typeof Pin>={pinned:Pin,mine:UserRound,sop:Settings2,notStarted:Clock3,done:CircleCheck,other:FileText};
const PROJECT_URL='/api/projects?view=portfolio&page=1';
const readLimit=()=>{try{const value=Number(window.localStorage.getItem('yx.projects.groupSize'));return [3,5,10,25,50,100].includes(value)?value:3}catch{return 3}};
function Select({label,value,onChange,children}:{label:string;value:string;onChange:(value:string)=>void;children:ReactNode}) {
 return <label className="pl-select"><span className="sr-only">{label}</span><FormSelect aria-label={label} value={value} onChange={e=>onChange(e.target.value)}>{children}</FormSelect></label>;
}
function Person({name}:{name:string}) {return <span className="pl-person"><span className="pl-avatar" aria-hidden="true"><UserRound size={12}/></span><span>{name}</span></span>}
function CaseCard({row,c,pinned,onPin,today}:{row:CaseRow;c:Ctx;pinned:boolean;onPin:()=>void;today:string}) {
 const [menu,setMenu]=useState(false),[details,setDetails]=useState(false),[message,setMessage]=useState('');
 const menuAnchor=useRef<HTMLDivElement>(null);
 const menuRef=useRef<HTMLDivElement>(null),trigger=useRef<HTMLButtonElement>(null);
 const p=row.project,href=`#view=project&project=${encodeURIComponent(p.id)}`,attention=caseAttention(p,today);
 const due=tableCalendarDay(p.due_date),day=tableCalendarDay(today),deadlineLate=!!due&&!!day&&due<day&&row.state!=='已完成';
 useEffect(()=>{if(!menu)return;menuRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
  const close=(event:PointerEvent)=>{if(event.target instanceof window.Node&&!menuRef.current?.contains(event.target)&&!trigger.current?.contains(event.target))setMenu(false)};
  document.addEventListener('pointerdown',close);return()=>document.removeEventListener('pointerdown',close);
 },[menu]);
 const person=(id:string)=>c.w.users.find(u=>u.id===id)?.name||(id?'姓名待核對':'未指派');
 const copy=async()=>{try{await navigator.clipboard.writeText(new URL(href,location.href).href);setMessage('已複製案件連結')}catch{setMessage('無法複製，請開啟案件後複製網址')}setMenu(false);trigger.current?.focus()};
 return <article className="pl-case" data-project={p.id}>
  <div className="pl-row" onClick={e=>{if(e.target instanceof window.Element&&!e.target.closest('a,button,summary,select,input,[role="menu"]'))c.go({view:'project',project:p.id})}}>
   <button className="pl-pin" aria-label={`釘選案件 ${p.code}`} aria-pressed={pinned} onClick={onPin}><Star size={15} fill={pinned?'currentColor':'none'}/></button>
   <div className="pl-identity"><span className="pl-code">{p.code}</span><a className="pl-title case-link" href={href}><strong>{p.name}</strong></a><span className="pl-client">{p.client||'客戶未提供'}</span>{verification(p)!=='已驗證'&&<small className="pl-source">來源：{verification(p).replace(/^來源/,'')}</small>}{!!p.duplicate_count&&<small className="pl-source">來源：合併重複 {p.duplicate_count+1} 筆</small>}{p.source_removed_at&&<small className="pl-source">來源：Lark 已移除</small>}</div>
   <div className="pl-meta"><div className="pl-field pl-pm"><Person name={person(p.pm_id)}/></div>
   <div className="pl-field pl-current"><span>{row.current?.label||(row.state==='已完成'?'流程完成':'待核對')}</span></div>
   <div className="pl-states"><span className="pl-status" data-state={caseBadge(row,today)}>{caseBadge(row,today)}</span></div></div>
   <div className="pl-more" ref={menuAnchor}><button ref={trigger} aria-label={`${p.code} 更多操作`} aria-haspopup="menu" aria-expanded={menu} onClick={()=>setMenu(!menu)}><MoreVertical size={17}/></button>
    {menu&&<PickerPopover anchor={menuAnchor} onClose={()=>setMenu(false)}><div ref={menuRef} className="pl-menu" role="menu" aria-label={`${p.code} 操作`} onKeyDown={e=>{
     if(e.key==='Escape'){setMenu(false);trigger.current?.focus()}
     if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();const items=Array.from(e.currentTarget.querySelectorAll<HTMLElement>('[role="menuitem"]'));const index=items.indexOf(document.activeElement instanceof HTMLElement?document.activeElement:items[0]);items[e.key==='Home'?0:e.key==='End'?items.length-1:(index+(e.key==='ArrowDown'?1:items.length-1))%items.length]?.focus()}
     if(e.key==='Tab')setMenu(false);
    }}><a role="menuitem" href={href}>開啟案件 <ArrowRight size={14}/></a><button role="menuitem" onClick={()=>{onPin();setMenu(false);trigger.current?.focus()}}>{pinned?'取消釘選':'釘選案件'}<Star size={14}/></button><button role="menuitem" onClick={()=>void copy()}>複製連結<Copy size={14}/></button><button role="menuitem" onClick={()=>{setDetails(!details);setMenu(false);trigger.current?.focus()}}>{details?'收合':'查看'}案件詳情<FileText size={14}/></button></div></PickerPopover>}
   </div>
  </div>
  {details&&<div className="pl-details"><div><strong>資料來源</strong><span>來源 {p.source_status||'未填'}</span><span className="verification-cell" aria-label={verification(p)}>{verification(p)}</span><span>{p.case_type==='intake'?'待確認接案':'正式案件'}{p.parent_code?` · 母案 ${p.parent_code}`:''}</span><span>工作台狀態 <CaseStatus project={p}/></span></div><div><strong>執行歸屬</strong><AdmissionCell p={p} role={c.s.user?.role}/></div><div><strong>期限與關注</strong><span className={`deadline${attention.soon?' is-upcoming':''}${deadlineLate?' is-overdue':''}`}>{taipeiDate(p.due_date,'未排期限')}</span><span>{[attention.late?'逾期':'',attention.blocked?'受阻':'',attention.soon?'即將到期':''].filter(Boolean).join(' · ')||'目前無已知期限警示'}</span></div><div><strong>SOP 納管</strong><span>{p.sop_summary?.policy==='managed'?'已納管':p.sop_summary?.policy==='legacy'?'歷史案件':p.sop_summary?.policy==='needs_review'?'政策待核對':'尚無納管紀錄'}{p.sop_summary?.imported_tasks?' · 已匯入 SOP 任務':''}</span><span>節點依工作區持久化摘要，最新指派請至案件核對。</span></div></div>}
  {message&&<p className="pl-row-message" role="status">{message}</p>}
 </article>;
}
export function Projects({c}:{c:Ctx}) {
 const [headerOpen,setHeaderOpen]=useState(false);
 const [filterOpen,setFilterOpen]=useState(false),[lifecycle,setLifecycle]=useState('all');
 const refreshSources=useSourceRefresh(c.s.workspace_id);
 const libraryScope=JSON.stringify([c.s.user?.id,c.s.workspace_id]);
 const remembered=useRef(readLibraryMemory(libraryScope)).current;
 const [filters,setFilters]=useState<CaseFilters>({...DEFAULT_FILTERS,...remembered?.filters,...(c.route.tab==='intake'?{kind:'intake'}:{})});
 const [view,setView]=useState(remembered?.view||'list'),[expanded,setExpanded]=useState<string[]>(remembered?.expanded||[]),[limit,setLimit]=useState(readLimit),[creating,setCreating]=useState(false),[notice,setNotice]=useState(''),[syncing,setSyncing]=useState(false),[syncStatus,setSyncStatus]=useState('');
 const reveal=useMemo(()=>Object.fromEntries(expanded.map(entry=>{const [key,steps]=entry.split(':');return [key,Number(steps)||1]})),[expanded]);
 const shell=c.w.scope==='shell',scope=JSON.stringify([c.s.user?.id,c.s.user?.role,c.s.user?.authz_version,c.s.user?.capabilities,c.s.access_mode,c.s.workspace_id,c.w.workspace_id]);
 const owner=usePageOwner({workspace:c.s.workspace_id||c.w.workspace_id||'',identityFingerprint:scope,openId:'projects'});
 const [refreshId,setRefreshId]=useState(0),[refreshCause,setRefreshCause]=useState<'explicit_refresh'|'own_write_committed'>('explicit_refresh');
 const resource={endpoint:PROJECT_URL};
 const result=usePageResource<PortfolioPage|undefined>(owner,resource,refreshId||c.reloadVersion?{reason:refreshCause,id:`${c.reloadVersion??0}:${refreshId}`}:{reason:'initial_open'},async(signal,current,intent)=>{
  const data=shell?await api<PortfolioPage>(PROJECT_URL,{signal,etag:true,cacheScope:scope,cache:'reload',headers:{'X-YX-Fetch-Intent':intent.reason}},current):undefined;
  return {data,snapshotId:data?.snapshot??null,fetchedAt:data?.as_of??null,verifiedAt:null,changedAt:null,completeness:data?.next_page?'partial':'complete',localRevision:null,empty:data?.total===0,stale:false};
 });
 const firstDenied=result.kind==='Denied';
 const value='value' in result?result.value:!firstDenied&&'previous' in result?result.previous:undefined;
 const data=value?.data;
 const read={data,loading:result.kind==='Loading',error:'error' in result?String(result.error instanceof Error?result.error.message:result.error):'',reload:()=>{setRefreshCause('explicit_refresh');setRefreshId(v=>v+1)},afterWrite:()=>{setRefreshCause('own_write_committed');setRefreshId(v=>v+1)}};
 const [remaining,setRemaining]=useState<{first:PortfolioPage;items:PortfolioPage['items'];complete:boolean;error:string;denied?:boolean}>();
 useEffect(()=>{
  if(!shell||!data?.next_page)return;
  const first=data,controller=new AbortController();
  setRemaining({first,items:[],complete:false,error:''});
  void (async()=>{
   let page=first.next_page;const items:PortfolioPage['items']=[];
   while(page&&!controller.signal.aborted){
    const next=await api<PortfolioPage>(`/api/projects?view=portfolio&page=${page}&snapshot=${encodeURIComponent(first.snapshot||'')}`,{signal:controller.signal,etag:true,cacheScope:scope,cache:'reload',headers:{'X-YX-Fetch-Intent':refreshId?refreshCause:'initial_open'}});
    if(next.snapshot!==first.snapshot)throw new Error('案件清單已更新，請重新讀取。');
    items.push(...next.items);page=next.next_page;
    if(!controller.signal.aborted)setRemaining({first,items:[...items],complete:!page,error:''});
   }
   if(!controller.signal.aborted)setRemaining({first,items,complete:true,error:''});
  })().catch(error=>{if(!controller.signal.aborted)setRemaining(previous=>({first,items:previous?.first===first?previous.items:[],complete:false,denied:error instanceof ApiError&&(error.status===401||error.status===403),error:error instanceof Error?error.message:'案件清單讀取失敗'}))});
  return()=>controller.abort();
 },[shell,data,scope]);
 const tail=remaining?.first===data?remaining:undefined;
 const denied=firstDenied||tail?.denied===true;
 const complete=!shell||!data?.next_page||tail?.complete===true;
 const projects=useMemo(()=>denied?undefined:shell?data?[...data.items,...(tail?.items||[])]:undefined:c.w.projects,[denied,shell,data,tail,c.w.projects]);
 const asOf=data?.as_of||c.w.as_of;
 const filtersRef=useRef(filters),viewRef=useRef(view),expandedRef=useRef(expanded);filtersRef.current=filters;viewRef.current=view;expandedRef.current=expanded;
 const pinKey=pinStorageKey(c.w.workspace_id||c.s.workspace_id||'default',c.s.user?.id||'anonymous');
 const [pinState,setPinState]=useState(()=>({key:pinKey,ids:readPins(window.localStorage,pinKey)}));
 const pins=pinState.key===pinKey?pinState.ids:readPins(window.localStorage,pinKey);
 useEffect(()=>{setPinState({key:pinKey,ids:readPins(window.localStorage,pinKey)})},[pinKey]);
 useEffect(()=>{const sync=(e:StorageEvent)=>{if(e.key===pinKey)setPinState({key:pinKey,ids:readPins(window.localStorage,pinKey)})};window.addEventListener('storage',sync);return()=>window.removeEventListener('storage',sync)},[pinKey]);
 const togglePin=(id:string)=>{const next=pins.includes(id)?pins.filter(p=>p!==id):[...pins,id];setPinState({key:pinKey,ids:next});if(!writePins(window.localStorage,pinKey,next))setNotice('瀏覽器無法儲存釘選，本次瀏覽仍可使用。')};
 const scrollY=useRef(remembered?.scrollY||0),restored=useRef(false);
 useEffect(()=>{const track=()=>{if(new URLSearchParams(location.hash.replace(/^#\/?/,'')).get('view')==='projects')scrollY.current=window.scrollY};window.addEventListener('scroll',track,{passive:true});return()=>window.removeEventListener('scroll',track)},[]);
 useEffect(()=>{writeLibraryMemory({scope:libraryScope,filters,view,expanded,scrollY:scrollY.current})},[libraryScope,filters,view,expanded]);
 useEffect(()=>()=>{writeLibraryMemory({scope:libraryScope,filters:filtersRef.current,view:viewRef.current,expanded:expandedRef.current,scrollY:scrollY.current})},[libraryScope]);
 const update=(key:keyof CaseFilters,value:string|number|boolean)=>{setFilters(f=>({...f,[key]:value}));setExpanded([])};
 const modeled=useMemo(()=>(projects??[]).map(p=>caseRow(p,c.w.users,c.s.user?.id||'',asOf)),[projects,c.w.users,c.s.user?.id,asOf]);
 const rows=useMemo(()=>filterRows(modeled,filters,asOf),[modeled,filters,asOf]);
 const degraded=shell&&data?.node_status_degraded===true;
 const groups=groupRows(rows,new Set(pins)),counts=portfolioCounts(rows),ready=!denied&&(!shell||!!data);
 const clients=useMemo(()=>[...new Set((projects??[]).map(p=>p.client).filter(Boolean))].sort(),[projects]);
 const pmIds=useMemo(()=>[...new Set((projects??[]).map(p=>p.pm_id).filter(Boolean))],[projects]);
 const canCreate=c.s.features?.local_case_creation===true&&c.s.user?.capabilities?.includes('create_local_case')===true;
 const canSync=c.s.mode==='lark'&&(c.s.access_mode||'normal')==='normal'&&c.s.user?.active!==false&&!String(c.s.workspace_id||c.w.workspace_id||'').startsWith('test-')&&(['pm','manager'].includes(c.s.user?.role||'')||c.s.user?.capabilities?.includes('manage_sources')===true);
 const sync=async()=>{if(syncing)return;setSyncing(true);setSyncStatus('');try{await refreshSources('sources',{url:'/api/sources/sync',body:'{}'});await c.refresh();read.afterWrite();setSyncStatus('Lark 同步完成，案件清單已更新。')}catch(error){setSyncStatus(error instanceof Error&&error.message.includes('結果尚未確認')?error.message:`Lark 同步失敗：${error instanceof Error?error.message:String(error)}`)}finally{setSyncing(false)}};
 useEffect(()=>{if(!ready||restored.current)return;restored.current=true;const top=scrollY.current;if(top>0)requestAnimationFrame(()=>window.scrollTo({top,left:0,behavior:'instant'}))},[ready]);
 const hasFilters=Object.entries(filters).some(([k,v])=>v!==Object.entries(DEFAULT_FILTERS).find(([key])=>key===k)?.[1]);
 return <div className="pl-page">
  <header className="pl-header"><div><h1>案件總覽</h1><p className="pl-scope">{ready?(data?.total??modeled.length):'未知'} 件 · 資料時間 {taipeiTime(asOf,'來源未提供')}</p></div><div className="pl-header-actions"><label className="pl-search"><Search size={16}/><input aria-label="搜尋案件" placeholder="搜尋案件、客戶或案號…" maxLength={240} value={filters.q} onChange={e=>update('q',e.target.value)}/>{filters.q&&<button aria-label="清除搜尋" onClick={()=>update('q','')}><X size={15}/></button>}</label><div className="pl-header-secondary" data-open={headerOpen} onKeyDown={e=>{if(e.key==='Escape'){setHeaderOpen(false);e.currentTarget.querySelector<HTMLButtonElement>('.pl-actions-trigger')?.focus()}}}><button className="pl-actions-trigger" aria-expanded={headerOpen} aria-controls="pl-secondary-actions" onClick={()=>setHeaderOpen(v=>!v)}>操作</button><div id="pl-secondary-actions" className="pl-secondary-content"><a className="button" href="#view=confirmations">工程確認單</a><div className="pl-view" role="group" aria-label="案件顯示方式"><button aria-label="清單檢視" aria-pressed={view==='list'} onClick={()=>setView('list')}><List size={17}/></button><button aria-label="卡片檢視" aria-pressed={view==='grid'} onClick={()=>setView('grid')}><LayoutGrid size={17}/></button></div><button className="pl-sync" disabled={read.loading} onClick={read.reload}>重新讀取</button>{canSync&&<button className="pl-sync" aria-label="重新同步 Lark" disabled={syncing} onClick={()=>void sync()}>{syncing?'同步中…':'重新同步 Lark'}</button>}</div></div>{canCreate&&<button className="pl-create" onClick={()=>setCreating(true)}><Plus size={17}/>新增案件</button>}</div></header>
  <p className="pl-sync-status sr-only" role="status" aria-live="polite">{syncStatus}</p>
  {!denied&&!complete&&<DataState kind={tail?.error?'Error':'Partial'} title={tail?.error?'部分案件無法載入':'案件尚未完整載入'} body={`已載入 ${projects?.length??0} / ${data?.total??'未知'} 件；搜尋僅涵蓋已載入快照，來源表筆數：${data?.total??'未知（讀取中）'}。${tail?.error||''}`} actions={tail?.error?<button onClick={read.reload}>重新讀取</button>:undefined}/>}
  <section className="pl-kpis" aria-label="生命週期篩選">{[{key:'all',label:'全部',count:rows.length},...groups.map(g=>({key:g.key,label:g.key==='sop'?'SOP 納管':g.label,count:g.rows.length}))].map(k=><button key={k.key} aria-pressed={lifecycle===k.key} onClick={()=>setLifecycle(k.key)}>{k.label} <strong>{!ready?'未知':!complete?`${k.count} 已載入`:k.count}</strong></button>)}</section>
  <p className="pl-count-detail">非互斥統計：進行中 {ready&&complete?counts.active??'未知':'未知'} · SOP 納管未完成 {ready&&complete?counts.sop??'未知':'未知'}（可重疊，依目前篩選）</p>
  <button className="pl-filter-trigger" onClick={e=>{e.currentTarget.focus();setFilterOpen(true)}}>篩選{hasFilters?`（${Object.entries(filters).filter(([k,v])=>v!==DEFAULT_FILTERS[k as keyof CaseFilters]).length}）`:'（0）'}</button>
  {filterOpen&&createPortal(<Sheet title="案件篩選與排序" onClose={()=>setFilterOpen(false)}><div className="pl-filters" role="group" aria-label="案件篩選">
   <Select label="客戶" value={filters.client} onChange={v=>update('client',v)}><option value="">客戶</option>{clients.map(client=><option key={client}>{client}</option>)}</Select>
   <Select label="篩選專案經理" value={filters.owner} onChange={v=>update('owner',v)}><option value="">負責 PM</option>{pmIds.map(id=><option key={id} value={id}>{c.w.users.find(u=>u.id===id)?.name||'姓名待核對'}</option>)}</Select>
   <Select label="節點" value={filters.node} onChange={v=>update('node',v)}><option value="">節點</option>{['業務','PM','確認單','外業','控制','圖資','報告','計價','結算'].map((label,i)=><option key={label} value={['sales','pm','confirmation','field','control','mapping','report','pricing','settlement'][i]}>{label}</option>)}<option value="unknown">待核對</option></Select>
   <Select label="狀態" value={filters.state} onChange={v=>update('state',v)}><option value="">狀態</option>{['進行中','待審核','尚未開始','已完成','暫停','待核對'].map(state=><option key={state}>{state}</option>)}</Select>
   <div className="pl-extra"><div><Select label="案件分類" value={filters.kind} onChange={v=>update('kind',v)}><option value="">全部紀錄</option><option value="formal">正式案件</option><option value="intake">待確認接案</option></Select><label className="pl-check"><input type="checkbox" checked={filters.attention} onChange={e=>update('attention',e.target.checked)}/>需要關注</label><Select label="案件排序" value={filters.sort} onChange={v=>{setFilters(f=>({...f,sort:v,direction:v==='created'?-1:1}));setExpanded([])}}><option value="due">依工作台期限</option><option value="created">最近加入</option><option value="name">依案件名稱</option></Select><button aria-label="切換排序方向" onClick={()=>update('direction',-filters.direction)}><ArrowDown size={16} style={{transform:filters.direction===1?'':'rotate(180deg)'}}/></button><Select label="每組顯示筆數" value={String(limit)} onChange={v=>{setLimit(Number(v));try{window.localStorage.setItem('yx.projects.groupSize',v)}catch{setNotice('本次瀏覽已調整顯示筆數。')}}}>{[3,5,10,25,50,100].map(n=><option key={n} value={n}>每組 {n} 筆</option>)}</Select></div></div>
   {hasFilters&&<button className="pl-clear" onClick={()=>{setFilters({...DEFAULT_FILTERS});setExpanded([])}}>清除全部<X size={13}/></button>}
  <button onClick={()=>setFilterOpen(false)}>套用篩選</button></div></Sheet>,document.body)}
  {notice&&<p role="status">{notice}</p>}
  {result.kind==='Stale'&&!read.error&&<DataState kind="Stale" title="保留上次讀取資料" body="正在重新讀取，下方保留上次快照；資料時間見頁首。"/>}
  {degraded&&<DataState kind="Partial" title="節點進度待核對" body="節點摘要不完整，目前分組可能不正確。" actions={<button onClick={read.reload}>重新讀取</button>}/>}
  {shell&&(read.error||tail?.denied)&&<DataState kind={denied?'Denied':data?'Stale':'Error'} title="案件讀取失敗" body={<>{read.error||tail?.error}{!denied&&data&&'；下方保留上次資料。'}</>} actions={<button onClick={read.reload}>重新讀取</button>}/>}
  {shell&&read.loading&&!data?<DataState kind="Loading" title="正在載入案件" body={<Skeleton lines={5}/>}/>:ready?<div className={`pl-groups ${view==='grid'?'pl-grid':''}`}>{groups.filter(g=>g.rows.length>0&&(lifecycle==='all'||lifecycle===g.key)).map(group=>{const Icon=GROUP_ICONS[group.key],visible=revealedCount(limit,reveal[group.key]??0,group.rows.length);return <section className="pl-group" key={group.key} aria-label={group.label}><header><h2><Icon size={19}/>{group.label}<span>{group.rows.length}{!complete?' 已載入':''}</span></h2><span>顯示 {visible} / {group.rows.length}{!complete?' 已載入':''}</span>{visible<group.rows.length&&<button className="pl-expand" onClick={()=>setExpanded(previous=>[...previous.filter(key=>key!==group.key&&!key.startsWith(`${group.key}:`)),`${group.key}:${(reveal[group.key]??0)+1}`])}>顯示更多（再 25 筆）<ArrowRight size={15}/></button>}</header><div className="pl-column-labels" aria-hidden="true"><span/><span>案件</span><span>負責 PM</span><span>目前節點</span><span>狀態</span><span/></div><div className="pl-group-rows" role="list">{group.rows.slice(0,visible).map(row=><div role="listitem" key={row.project.id}><CaseCard row={row} c={c} today={asOf} pinned={pins.includes(row.project.id)} onPin={()=>togglePin(row.project.id)}/></div>)}</div></section>})}</div>:null}
  {ready&&!rows.length&&<DataState kind={complete?'Empty':'Partial'} title={complete?'沒有符合條件的案件':'已載入的案件尚無符合項目'} body={complete?'試試其他關鍵字或清除篩選條件。':`已載入 ${projects?.length??0} / ${data?.total??'未知'} 件，尚不能判定全部搜尋結果。`}/>}
  <footer className="pl-footer">{ready?`${complete?'符合條件':'目前已載入符合條件'} ${rows.length} 筆 · 統計依目前篩選，釘選不重複計算${data?.hidden_duplicates?` · 已合併 Lark 重複編號 ${data.hidden_duplicates} 筆`:''}`:'案件統計載入中'}{taipeiDate(asOf,'')&&` · 資料日期 ${taipeiDate(asOf,'')}`}{!complete?' · 部分統計待核實':''}{shell&&read.loading&&data?' · 更新中':''}{data?.source_synced_at&&taipeiTime(data.source_synced_at,'')&&` · 上次同步 Lark：${taipeiTime(data.source_synced_at,'').slice(11,16)}`}{!!data?.hidden_removed&&` · 已隱藏 ${data.hidden_removed} 筆已從 Lark 移除的報價`}</footer>
  {!denied&&<details className="pl-admission"><summary>執行歸屬核定與案件生命週期</summary><p>工程確認單成案，報價資料先保留為待確認接案。來源商務狀態與工作台節點狀態分開顯示，詳見各案件的更多操作。</p><ExecutionAdmissionQueue w={c.w} s={c.s} run={(action,payload,scope)=>c.run(action,payload,scope)} busy={c.busy}/></details>}
  {creating&&<QuoteCreateSheet users={c.w.users} canImport={c.s.features?.sop_task_writes===true&&(c.s.user?.role==='manager'||c.s.user?.capabilities?.includes('sop_task_import')===true)} onClose={()=>setCreating(false)} onCreated={read.afterWrite} onOpen={ref=>{setCreating(false);c.go({view:'quotes',project:ref,tab:'flow'})}}/>}
 </div>;
}
