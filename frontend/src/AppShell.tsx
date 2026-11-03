import {getSessionEpoch,onSessionEpochChange} from './api';
import {recentCasesKey,readRecentCases,openRecentCase,saveRecentCases,clearRecentCases} from './design/recentCases';
import {createRoutePrefetch} from './routeLoader';
import {RouteSkeleton} from './RouteSkeleton';
import { BookOpen, MessageSquare, CalendarDays, ChevronRight, Menu, TriangleAlert, X } from 'lucide-react';
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { ClipboardList, FileBarChart, Clock3, FolderOpen, Gauge, GitBranch, LayoutDashboard, ListTodo, PanelLeftClose, Settings2 } from 'lucide-react';
import {Avatar} from './Avatar';
import { useDialogFocus } from './useDialogFocus';
import type { Freshness, Route, Session, Workspace } from './types';

export const ROLE:Record<string,string>={pm:'專案經理',manager:'系統管理員',member:'組員'};
export const ROUTE_LABELS:Record<Route['view'],string>={assistant:'AI 助理','stage-fixture':'合成驗證環境',howto:'使用說明',dashboard:'今日工作台',reports:'PM 週報',projects:'案件總覽',quotes:'報價總表',overview:'管理總覽',people:'人員與資源出勤',approvals:'變更與展延',routines:'追蹤與檢討',admin:'管理設定',work:'我的工作',sources:'資料來源',dispatch:'派工調度',project:'案件詳情',confirmations:'案件與確認單',confirmation:'案件與確認單詳情',contract:'合約明細詳情',workitem:'工作項詳情','pm-glance':'今日工作台'};
const NAV=[{view:'assistant',label:ROUTE_LABELS.assistant,icon:MessageSquare},{view:'howto',label:ROUTE_LABELS.howto,icon:BookOpen},{view:'dashboard',label:ROUTE_LABELS['dashboard'],icon:LayoutDashboard},{view:'work',label:ROUTE_LABELS.work,icon:ListTodo},{view:'reports',label:ROUTE_LABELS['reports'],icon:FileBarChart},{view:'projects',label:ROUTE_LABELS['projects'],icon:FolderOpen},{view:'quotes',label:ROUTE_LABELS['quotes'],icon:ClipboardList},{view:'overview',label:ROUTE_LABELS['overview'],icon:Gauge},{view:'people',label:ROUTE_LABELS['people'],icon:CalendarDays},{view:'approvals',label:ROUTE_LABELS['approvals'],icon:GitBranch},{view:'routines',label:ROUTE_LABELS['routines'],icon:Clock3},{view:'admin',label:ROUTE_LABELS['admin'],icon:Settings2}] as const;
const NAV_GROUPS=[{label:'工作',views:['assistant','howto','dashboard','work']},{label:'專案',views:['projects','quotes','people']},{label:'管理',views:['reports','overview','approvals','routines','admin']}] as const;
export {Avatar} from './Avatar';

type CallbackError={title:string;description:string;next:string};
export type AppShellProps={s:Session;w?:Workspace;route:Route;error:string;setError:(m:string)=>void;callbackError?:CallbackError;mobile:boolean;setMobile:(open:boolean)=>void;sessionOpen:boolean;setSessionOpen:(open:boolean)=>void;overdue:number;activeNav:string;asOfLabel:string;busy:boolean;mutationBusy:boolean;dirtyDraft:boolean;ready:boolean;go:(r:Route)=>void;refresh:()=>Promise<void>;guardedRefresh:()=>Promise<boolean>;reread:()=>void;onFreshness:(next:Freshness,snapshot?:Freshness)=>void;children:ReactNode;overlays?:ReactNode};

export function AppShell({s,w,route,error,setError,callbackError,mobile,setMobile,sessionOpen,setSessionOpen,overdue,activeNav,ready,go,refresh,children,overlays}:AppShellProps){
 const [compact,setCompact]=useState(false);
 const [keyboardFocus,setKeyboardFocus]=useState(false);
 useEffect(()=>{
  // Programmatic route/modal focus follows the last input method, not the browser's initial focus heuristic.
  const keyboard=(event:KeyboardEvent)=>{if(!event.metaKey&&!event.ctrlKey&&!event.altKey&&!['Shift','Control','Alt','Meta'].includes(event.key))setKeyboardFocus(true)};
  const pointer=()=>setKeyboardFocus(false);
  document.addEventListener('keydown',keyboard,true);document.addEventListener('pointerdown',pointer,true);
  return()=>{document.removeEventListener('keydown',keyboard,true);document.removeEventListener('pointerdown',pointer,true)};
 },[]);
 const [epoch,setEpoch]=useState(getSessionEpoch);
 const scope=recentCasesKey(s.user?.id||'',s.workspace_id||w?.workspace_id||'',epoch);
 const storage=()=>{try{return window.sessionStorage}catch{return null}};
 const [recent,setRecent]=useState<{scope:string;ids:string[]}>(()=>({scope,ids:readRecentCases(storage(),scope)}));
 const previousScope=useRef(scope);
 useEffect(()=>onSessionEpochChange(()=>{clearRecentCases(storage(),previousScope.current);setEpoch(getSessionEpoch())}),[]);
 useEffect(()=>{
  if(previousScope.current!==scope)clearRecentCases(storage(),previousScope.current);
  previousScope.current=scope;
  setRecent({scope,ids:readRecentCases(storage(),scope)});
 },[scope]);
 useEffect(()=>{
  if(!ready||route.view!=='project'||!route.project||!s.user||!w?.projects.some(p=>p.id===route.project))return;
  setRecent(previous=>{const ids=openRecentCase(previous.scope===scope?previous.ids:[],route.project!);saveRecentCases(storage(),scope,ids);return {scope,ids}});
 },[scope,ready,route.view,route.project,w?.projects]);
 const recentProjects=(recent.scope===scope?recent.ids:[]).flatMap(id=>{const p=w?.projects.find(p=>p.id===id);return p?[p]:[]});
 const mainShell=useRef<HTMLDivElement>(null),bottomNav=useRef<HTMLElement>(null),compactBrand=useRef<HTMLDivElement>(null),skipLink=useRef<HTMLAnchorElement>(null);
 useLayoutEffect(()=>{const nodes=[mainShell.current,bottomNav.current,compactBrand.current,skipLink.current];for(const node of nodes)if(node)node.inert=mobile||sessionOpen;return()=>{for(const node of nodes)if(node)node.inert=false}},[mobile,sessionOpen]);
 useEffect(()=>{
  document.title=`${ROUTE_LABELS[route.view]}｜詠翔工作台`;
  const main=mainShell.current?.querySelector('main');if(!main||!ready)return;
  const focus=()=>{const h=main.querySelector<HTMLElement>('h1');if(!h||main.querySelector('.route-skeleton'))return false;h.tabIndex=-1;requestAnimationFrame(()=>{if(!mainShell.current?.inert)h.focus({preventScroll:true})});return true};
  if(focus())return;const observer=new window.MutationObserver(()=>{if(focus())observer.disconnect()});observer.observe(main,{childList:true,subtree:true});return()=>observer.disconnect();
 },[route.view,route.project,route.tab,ready]);
 const [prefetch]=useState(createRoutePrefetch);
 useEffect(()=>prefetch.cancel,[prefetch]);
 const intent=(target:Route)=>({onMouseEnter:()=>prefetch.schedule(target),onMouseLeave:prefetch.cancel,onFocus:()=>prefetch.schedule(target),onBlur:prefetch.cancel});
 const openSidebarRef=useRef<HTMLButtonElement>(null);
 const collapseSidebarRef=useRef<HTMLButtonElement>(null);
 const toggleSidebar=(next:boolean)=>{setCompact(next);requestAnimationFrame(()=>{(next?openSidebarRef:collapseSidebarRef).current?.focus()})};
 // Reset the document scroll for each page, case, or page tab before it paints.
 // Task dialogs and in-page focus links keep their own scrolling behavior.
 useLayoutEffect(()=>{
  const previous=history.scrollRestoration;
  history.scrollRestoration='manual';
  return()=>{history.scrollRestoration=previous};
 },[]);
 const pageSection=route.view==='project' && route.tab==='items' ? undefined : route.section;
 useLayoutEffect(()=>{
  window.scrollTo({top:0,left:0,behavior:'instant'});
 },[route.view,route.project,route.tab,pageSection,ready]);
 const navigationRef=useDialogFocus(()=>setMobile(false),mobile);
 useLayoutEffect(()=>{if(navigationRef.current)navigationRef.current.inert=sessionOpen},[sessionOpen]);

 const visibleNav=NAV.filter(n=>(n.view!=='approvals'||s.features?.change_extension===true)&&(n.view!=='routines'||s.features?.routines===true)&&(n.view!=='reports'||s.user?.role==='pm'||s.user?.role==='manager'||s.user?.role==='工務助理'||s.user?.department==='工務助理'||['郭倢瑛','朱雅琪','林瑩瑄'].includes(s.user?.name||'')||s.user?.capabilities?.includes('manage_sources')));
 const tabs=['dashboard','projects'].map(view=>NAV.find(n=>n.view===view)!);
 return <div data-keyboard-focus={keyboardFocus} className={`app-shell ${compact?'sidebar-compact':''}`}>
  <a ref={skipLink} className="skip-link" href="#main-content" onClick={event=>{event.preventDefault();const target=mainShell.current?.querySelector<HTMLElement>('h1')||document.getElementById('main-content');if(target){target.tabIndex=-1;target.focus()}}}>跳至主要內容</a>
  <div ref={compactBrand} className="compact-brand glass--bar"><a href="#view=dashboard" aria-label="詠翔工作台首頁"><span className="brand-mark"><i/><i/><i/><i/></span><strong>詠翔工作台</strong></a><button ref={openSidebarRef} className="sidebar-toggle" aria-label="展開側邊導覽" aria-expanded={!compact} aria-controls="workspace-navigation" onClick={()=>toggleSidebar(false)}><Menu size={20}/></button></div>
  {mobile&&<div className="sidebar-scrim" onClick={()=>setMobile(false)}/>}
  <aside ref={navigationRef} id="workspace-navigation" role={mobile?'dialog':undefined} aria-modal={mobile?true:undefined} aria-label="工作區導覽" tabIndex={-1} className={`sidebar glass--bar ${mobile?'open':''}`}><button className="icon-button sidebar-close" aria-label="關閉導覽" onClick={()=>setMobile(false)}><X size={20}/></button><button ref={collapseSidebarRef} className="sidebar-toggle sidebar-collapse" aria-label="收合側邊導覽" aria-expanded={!compact} aria-controls="workspace-navigation" onClick={()=>toggleSidebar(true)}><PanelLeftClose size={18}/></button><div className="sidebar-scroll"><a className="brand" href="#view=dashboard" aria-label="詠翔工作台首頁"><span className="brand-mark"><i/><i/><i/><i/></span><span>詠翔工作台<span className="brand-en">YONG XIANG</span></span></a><div className="workspace-caption">測量工程 · 專案協作</div><nav className="workspace-nav-groups" aria-label="主要導覽">{NAV_GROUPS.map(group=><div className="workspace-nav-group" key={group.label}><div className="nav-label">{group.label}</div>{visibleNav.filter(item=>group.views.some(view=>view===item.view)).map(item=><button key={item.view} aria-current={activeNav===item.view?'page':undefined} className={`nav-item ${activeNav===item.view?'active':''}`} {...intent({view:item.view})} onClick={()=>{go({view:item.view});setMobile(false)}}><item.icon size={18}/><span>{item.label}</span></button>)}</div>)}{mobile&&<button className={'nav-item'+(activeNav==='confirmations'?' active':'')} aria-current={activeNav==='confirmations'?'page':undefined} onClick={()=>{go({view:'confirmations'});setMobile(false)}}><ClipboardList size={18}/><span>工程確認單</span></button>}</nav><div className="sidebar-projects"><div className="nav-label">最近案件</div>{!recentProjects.length&&<p className="recent-empty">尚無最近開啟的案件</p>}{recentProjects.map(p=><button key={p.id} title={`${p.code} ${p.name}`} className={`recent-project ${route.project===p.id?'selected':''}`} {...intent({view:'project',project:p.id})} onClick={()=>{go({view:'project',project:p.id});setMobile(false)}}><span className="project-dot"/><span>{p.code}<small>{p.name}</small></span></button>)}</div></div></aside>
  <div ref={mainShell} className="main-shell"><header className="topbar glass--bar"><div className="breadcrumbs"><button className="icon-button mobile-menu" onClick={()=>setMobile(!mobile)} aria-label="開啟導覽" aria-expanded={mobile} aria-controls="workspace-navigation"><Menu size={20}/></button><span>工作空間</span><ChevronRight size={13}/><strong>{ROUTE_LABELS[route.view]}</strong></div><div className="topbar-right">{s.environment&&s.environment!=='production'&&<span className="demo-tag">{s.environment==='test'?'測試':'示範'}</span>}<button className="user-button" aria-label="目前登入身份" aria-expanded={sessionOpen} onClick={()=>setSessionOpen(!sessionOpen)}><Avatar user={s.user||undefined}/><span>{s.user?.name}</span></button></div></header>
  {callbackError&&<div className="error-banner auth-callback-banner" role="alert"><TriangleAlert size={18}/><span><strong>{callbackError.title}</strong><br/>{callbackError.description} {callbackError.next}</span><a className="text-button" href="/api/auth/lark/login">重新登入</a></div>}
  {error&&<div className="error-banner workspace-error" role="alert"><TriangleAlert size={18}/><span>{error}</span><button className="text-button" onClick={()=>{setError('');void refresh()}}>重新載入</button><button className="icon-button" onClick={()=>setError('')} aria-label="關閉錯誤訊息"><X size={16}/></button></div>}
  <main id="main-content" tabIndex={-1} key={route.view} className={`workspace ${route.view==='project'?'project-workspace':''}`}>
   {!ready?error?<div className="loading-page"><h2>暫時無法連接工作區</h2><p>請確認服務已啟動，或使用下方登入。</p><button className="button" onClick={()=>void refresh()}>重新連接</button>{s?.auth_configured&&<a className="button primary" href="/api/auth/lark/login">使用 Lark 登入</a>}</div>:<RouteSkeleton route={route} title={ROUTE_LABELS[route.view]}/>:children}
  </main>
  </div>
  <nav ref={bottomNav} className="mobile-tabs glass--bar" aria-label="快速導覽">{tabs.map(item=><button key={item.view} aria-current={activeNav===item.view?'page':undefined} {...intent({view:item.view})} onClick={()=>{go({view:item.view});setMobile(false)}}><item.icon size={20}/><span>{item.label}</span></button>)}<button aria-label="更多導覽" aria-expanded={mobile} aria-controls="workspace-navigation" onClick={()=>setMobile(true)}><Menu size={20}/><span>更多</span></button></nav>
  {overlays}
 </div>
}
