import {useEffect, useRef, useState, type ReactNode} from 'react';
import {ArrowDown, ArrowRight, Check, CircleCheck, Clock3, Copy, FileText, LayoutGrid, List, MoreVertical, Pin, PlayCircle, Plus, Search, Settings2, Star, UserRound, X} from 'lucide-react';
import {useViewData} from './viewData';
import {readPortfolio, cachedPortfolio, tableCalendarDay} from './companyDashboardCache';
import {STATUS} from './workflowLabels';
import {taipeiDate} from './taipeiTime';
import {AdmissionCell, ExecutionAdmissionQueue} from './ExecutionAdmission';
import {Ctx, Empty} from './appCommon';
import {Skeleton} from './design';
import {QuoteCreateSheet} from './QuoteCreateSheet';
import {caseRow, caseAttention, filterRows, groupRows, portfolioCounts, pinStorageKey, readPins, writePins, verification, DEFAULT_FILTERS, type CaseFilters, type CaseRow, type PortfolioPage} from './projectsListModel';
import './ProjectsList.css';

const GROUP_ICONS:Record<string,typeof Pin>={pinned:Pin,mine:UserRound,sop:Settings2,notStarted:Clock3,done:CircleCheck,other:FileText};
const PROJECT_URL='/api/projects?view=portfolio';
const readLimit=()=>{try{const value=Number(window.localStorage.getItem('yx.projects.groupSize'));return [3,5,10,25,50,100].includes(value)?value:3}catch{return 3}};
function Select({label,value,onChange,children}:{label:string;value:string;onChange:(value:string)=>void;children:ReactNode}) {
 return <label className="pl-select"><span className="sr-only">{label}</span><select aria-label={label} value={value} onChange={e=>onChange(e.target.value)}>{children}</select></label>;
}
function Person({name}:{name:string}) {return <span className="pl-person"><span className="pl-avatar" aria-hidden="true"><UserRound size={12}/></span><span>{name}</span></span>}
function Stepper({row}:{row:CaseRow}) {
 return <ol className="pl-stepper" aria-label="九階段案件流程">{row.nodes.map(n=>{
  const done=['已完成','略過'].includes(n.state),current=row.current?.key===n.key&&row.state!=='尚未開始';
  return <li key={n.key} data-state={done?'done':current?'current':n.state==='狀態待確認'?'unknown':'upcoming'} aria-label={`${n.label}，${n.state==='狀態待確認'?'未知':n.state}`} aria-current={current?'step':undefined}><span className="pl-step-dot" aria-hidden="true">{done?<Check size={9}/>:current?<span/>:null}</span><span>{n.label}</span></li>;
 })}</ol>;
}
function CaseCard({row,c,pinned,onPin,today}:{row:CaseRow;c:Ctx;pinned:boolean;onPin:()=>void;today:string}) {
 const [menu,setMenu]=useState(false),[details,setDetails]=useState(false),[message,setMessage]=useState('');
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
   <button className="pl-pin" aria-label={`${pinned?'取消釘選':'釘選'} ${p.code}`} aria-pressed={pinned} onClick={onPin}><Star size={15} fill={pinned?'currentColor':'none'}/></button>
   <div className="pl-identity"><span className="pl-code">#{p.code}{!!p.duplicate_count&&<small className="pl-dup" title="Lark 來源有相同編號的重複紀錄，已合併顯示"> · Lark 重複 {p.duplicate_count+1} 筆</small>}</span><span className="pl-client">{p.client||'客戶未提供'}</span></div>
   <a className="pl-title case-link" href={href}><FileText size={12} aria-hidden="true"/><strong>{p.name}</strong></a>
   <div className="pl-field pl-pm"><small>負責 PM</small><Person name={person(p.pm_id)}/></div>
   <div className="pl-field pl-owner"><small>目前節點負責人</small><Person name={row.current?.owners.map(o=>o.name).join('、')||'未指派'}/></div>
   <div className="pl-field pl-current"><small>目前節點</small><span>{row.current?.label||(row.state==='已完成'?'流程完成':'待核對')}</span></div>
   <span className="pl-status" data-state={row.state}>{row.state}</span>
   <div className="pl-flow" tabIndex={0} role="region" aria-label="九階段流程，可左右捲動"><Stepper row={row}/></div>
   <div className="pl-more"><button ref={trigger} aria-label={`${p.code} 更多操作`} aria-haspopup="menu" aria-expanded={menu} onClick={()=>setMenu(!menu)}><MoreVertical size={17}/></button>
    {menu&&<div ref={menuRef} className="pl-menu" role="menu" aria-label={`${p.code} 操作`} onKeyDown={e=>{
     if(e.key==='Escape'){setMenu(false);trigger.current?.focus()}
     if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();const items=Array.from(e.currentTarget.querySelectorAll<HTMLElement>('[role="menuitem"]'));const index=items.indexOf(document.activeElement instanceof HTMLElement?document.activeElement:items[0]);items[e.key==='Home'?0:e.key==='End'?items.length-1:(index+(e.key==='ArrowDown'?1:items.length-1))%items.length]?.focus()}
     if(e.key==='Tab')setMenu(false);
    }}><a role="menuitem" href={href}>開啟案件 <ArrowRight size={14}/></a><button role="menuitem" onClick={()=>{onPin();setMenu(false);trigger.current?.focus()}}>{pinned?'取消釘選':'釘選案件'}<Star size={14}/></button><button role="menuitem" onClick={()=>void copy()}>複製連結<Copy size={14}/></button><button role="menuitem" onClick={()=>{setDetails(!details);setMenu(false);trigger.current?.focus()}}>{details?'收合':'查看'}案件詳情<FileText size={14}/></button></div>}
   </div>
  </div>
  {details&&<div className="pl-details"><div><strong>資料來源</strong><span>來源 {p.source_status||'未填'}</span><span className="verification-cell" aria-label={verification(p)}>{verification(p)}</span><span>{p.case_type==='intake'?'待確認接案':'正式案件'}{p.parent_code?` · 母案 ${p.parent_code}`:''}</span><span>工作台狀態 {STATUS[p.execution_status||p.status]||p.execution_status||p.status||'未知'}</span>{p.source_lifecycle?.reasons?.length?<span>來源狀態待核對 · {p.source_lifecycle.reasons.join('、')}</span>:null}</div><div><strong>執行歸屬</strong><AdmissionCell p={p} role={c.s.user?.role}/></div><div><strong>期限與關注</strong><span className={`deadline${attention.soon?' is-upcoming':''}${deadlineLate?' is-overdue':''}`}>{taipeiDate(p.due_date,'未排期限')}</span><span>{[attention.late?'逾期':'',attention.blocked?'受阻':'',attention.soon?'即將到期':''].filter(Boolean).join(' · ')||'目前無已知期限警示'}</span></div><div><strong>SOP 納管</strong><span>{p.sop_summary?.policy==='managed'?'已納管':p.sop_summary?.policy==='legacy'?'歷史案件':p.sop_summary?.policy==='needs_review'?'政策待核對':'尚無納管紀錄'}{p.sop_summary?.imported_tasks?' · 已匯入 SOP 任務':''}</span><span>節點依工作區持久化摘要，最新指派請至案件核對。</span></div></div>}
  {message&&<p className="pl-row-message" role="status">{message}</p>}
 </article>;
}
export function Projects({c}:{c:Ctx}) {
 const [filters,setFilters]=useState<CaseFilters>({...DEFAULT_FILTERS,kind:c.route.tab==='intake'?'intake':''});
 const [view,setView]=useState('list'),[expanded,setExpanded]=useState<string[]>([]),[limit,setLimit]=useState(readLimit),[creating,setCreating]=useState(false),[notice,setNotice]=useState('');
 const shell=c.w.scope==='shell',scope=JSON.stringify([c.s.user?.id,c.s.user?.role,c.s.workspace_id,c.w.workspace_id]);
 const read=useViewData<PortfolioPage|undefined>(shell?`projects-portfolio:${scope}`:'projects-local',async signal=>shell?readPortfolio(PROJECT_URL,signal,scope,{reloadVersion:c.reloadVersion}):undefined,[c.reloadVersion]);
 const cached=shell?cachedPortfolio(PROJECT_URL,scope):undefined;
 const data=read.data||cached;
 const projects=shell?(data?.items||[]):c.w.projects;
 const asOf=data?.as_of||c.w.as_of;
 const pinKey=pinStorageKey(c.w.workspace_id||c.s.workspace_id||'default',c.s.user?.id||'anonymous');
 const [pinState,setPinState]=useState(()=>({key:pinKey,ids:readPins(window.localStorage,pinKey)}));
 const pins=pinState.key===pinKey?pinState.ids:readPins(window.localStorage,pinKey);
 useEffect(()=>{setPinState({key:pinKey,ids:readPins(window.localStorage,pinKey)})},[pinKey]);
 useEffect(()=>{const sync=(e:StorageEvent)=>{if(e.key===pinKey)setPinState({key:pinKey,ids:readPins(window.localStorage,pinKey)})};window.addEventListener('storage',sync);return()=>window.removeEventListener('storage',sync)},[pinKey]);
 const togglePin=(id:string)=>{const next=pins.includes(id)?pins.filter(p=>p!==id):[...pins,id];setPinState({key:pinKey,ids:next});if(!writePins(window.localStorage,pinKey,next))setNotice('瀏覽器無法儲存釘選，本次瀏覽仍可使用。')};
 const update=(key:keyof CaseFilters,value:string|number|boolean)=>{setFilters(f=>({...f,[key]:value}));setExpanded([])};
 const rows=filterRows(projects.map(p=>caseRow(p,c.w.users,c.s.user?.id||'',asOf)),filters,asOf);
 const groups=groupRows(rows,new Set(pins)),counts=portfolioCounts(rows),ready=!shell||!!data;
 const clients=[...new Set(projects.map(p=>p.client).filter(Boolean))].sort();
 const pmIds=[...new Set(projects.map(p=>p.pm_id).filter(Boolean))];
 const canCreate=c.s.features?.local_case_creation===true&&c.s.user?.capabilities?.includes('create_local_case')===true;
 const hasFilters=Object.entries(filters).some(([k,v])=>v!==Object.entries(DEFAULT_FILTERS).find(([key])=>key===k)?.[1]);
 const kpis=[{label:'全部案件',value:counts.all,icon:FileText},{label:'進行中',value:counts.active,icon:PlayCircle},{label:'SOP 進行中',value:counts.sop,icon:Settings2},{label:'已完成',value:counts.done,icon:CircleCheck}];
 return <div className="pl-page">
  <header className="pl-header"><div><h1>案件總覽</h1></div><div className="pl-header-actions"><label className="pl-search"><Search size={16}/><input aria-label="搜尋案件" placeholder="搜尋案件、客戶或案號…" maxLength={240} value={filters.q} onChange={e=>update('q',e.target.value)}/>{filters.q&&<button aria-label="清除搜尋" onClick={()=>update('q','')}><X size={15}/></button>}</label><div className="pl-view" role="group" aria-label="案件顯示方式"><button aria-label="清單檢視" aria-pressed={view==='list'} onClick={()=>setView('list')}><List size={17}/></button><button aria-label="卡片檢視" aria-pressed={view==='grid'} onClick={()=>setView('grid')}><LayoutGrid size={17}/></button></div>{canCreate&&<button className="pl-create" onClick={()=>setCreating(true)}><Plus size={17}/>新增案件</button>}</div></header>
  <section className="pl-kpis" aria-label="案件統計">{kpis.filter(k=>ready && k.value!==null).map(k=><div className="pl-kpi" key={k.label}><span className="pl-kpi-icon"><k.icon size={21}/></span><div><span>{k.label}</span><strong>{k.value}</strong></div></div>)}</section>
  <div className="pl-filters" role="group" aria-label="案件篩選">
   <Select label="客戶" value={filters.client} onChange={v=>update('client',v)}><option value="">客戶</option>{clients.map(client=><option key={client}>{client}</option>)}</Select>
   <Select label="篩選專案經理" value={filters.owner} onChange={v=>update('owner',v)}><option value="">負責 PM</option>{pmIds.map(id=><option key={id} value={id}>{c.w.users.find(u=>u.id===id)?.name||'姓名待核對'}</option>)}</Select>
   <Select label="節點" value={filters.node} onChange={v=>update('node',v)}><option value="">節點</option>{['業務','PM','確認單','外業','控制','圖資','報告','計價','結算'].map((label,i)=><option key={label} value={['sales','pm','confirmation','field','control','mapping','report','pricing','settlement'][i]}>{label}</option>)}<option value="unknown">待核對</option></Select>
   <Select label="狀態" value={filters.state} onChange={v=>update('state',v)}><option value="">狀態</option>{['進行中','待審核','尚未開始','已完成','暫停','待核對'].map(state=><option key={state}>{state}</option>)}</Select>
   <details className="pl-extra"><summary>更多篩選與排序</summary><div><Select label="案件分類" value={filters.kind} onChange={v=>update('kind',v)}><option value="">全部紀錄</option><option value="formal">正式案件</option><option value="intake">待確認接案</option></Select><label className="pl-check"><input type="checkbox" checked={filters.attention} onChange={e=>update('attention',e.target.checked)}/>需要關注</label><Select label="案件排序" value={filters.sort} onChange={v=>{setFilters(f=>({...f,sort:v,direction:v==='created'?-1:1}));setExpanded([])}}><option value="due">依工作台期限</option><option value="created">最近加入</option><option value="name">依案件名稱</option></Select><button aria-label="切換排序方向" onClick={()=>update('direction',-filters.direction)}><ArrowDown size={16} style={{transform:filters.direction===1?'':'rotate(180deg)'}}/></button><Select label="每組顯示筆數" value={String(limit)} onChange={v=>{setLimit(Number(v));try{window.localStorage.setItem('yx.projects.groupSize',v)}catch{setNotice('本次瀏覽已調整顯示筆數。')}}}>{[3,5,10,25,50,100].map(n=><option key={n} value={n}>每組 {n} 筆</option>)}</Select></div></details>
   {hasFilters&&<button className="pl-clear" onClick={()=>{setFilters({...DEFAULT_FILTERS});setExpanded([])}}>清除全部<X size={13}/></button>}
  </div>
  {notice&&<p role="status">{notice}</p>}
  {shell&&read.error&&<div className="pl-state" role="alert"><h2>案件讀取失敗</h2><p>{read.error}</p><button onClick={read.reload}>重新載入案件</button>{data&&<p>下方保留上次成功讀取的資料。</p>}</div>}
  {shell&&read.loading&&!data?<div className="pl-state" role="status" aria-busy="true"><p>正在載入案件…</p><Skeleton lines={5}/></div>:ready?<div className={`pl-groups ${view==='grid'?'pl-grid':''}`}>{groups.filter(g=>g.rows.length>0).map(group=>{const Icon=GROUP_ICONS[group.key];const open=expanded.includes(group.key);return <section className="pl-group" key={group.key} aria-label={group.label}><header><h2><Icon size={19}/>{group.label}<span>{group.rows.length}</span></h2>{group.rows.length>limit&&<button className="pl-expand" aria-expanded={open} onClick={()=>setExpanded(open?expanded.filter(key=>key!==group.key):[...expanded,group.key])}>{open?'收合':'顯示更多'}<ArrowRight size={15}/></button>}</header><div className="pl-group-rows">{(open?group.rows:group.rows.slice(0,limit)).map(row=><CaseCard key={row.project.id} row={row} c={c} today={asOf} pinned={pins.includes(row.project.id)} onPin={()=>togglePin(row.project.id)}/>)}</div></section>})}</div>:null}
  {ready&&!rows.length&&<Empty title="沒有符合條件的案件" detail="試試其他關鍵字或清除篩選條件。"/>}
  <footer className="pl-footer">{ready?`符合條件 ${rows.length} 筆 · 統計依目前篩選，釘選不重複計算${data?.hidden_duplicates?` · 已合併 Lark 重複編號 ${data.hidden_duplicates} 筆`:''}`:'案件統計載入中'}{taipeiDate(asOf,'')&&` · 資料日期 ${taipeiDate(asOf,'')}`}{ready&&kpis.some(k=>k.value===null)?' · 部分統計待核實':''}{shell&&read.loading&&data?' · 更新中':''}</footer>
  <details className="pl-admission"><summary>執行歸屬核定與案件生命週期</summary><p>工程確認單成案，報價資料先保留為待確認接案。來源商務狀態與工作台節點狀態分開顯示，詳見各案件的更多操作。</p><ExecutionAdmissionQueue w={c.w} s={c.s} run={(action,payload,scope)=>c.run(action,payload,scope)} busy={c.busy}/></details>
  {creating&&<QuoteCreateSheet users={c.w.users} canImport={c.s.features?.sop_task_writes===true&&(c.s.user?.role==='manager'||c.s.user?.capabilities?.includes('sop_task_import')===true)} onClose={()=>setCreating(false)} onCreated={read.reload} onOpen={ref=>{setCreating(false);c.go({view:'quotes',project:ref,tab:'flow'})}}/>}
 </div>;
}
