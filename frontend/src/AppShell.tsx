import {canReadDispatch} from './dispatchAccess';
import { CalendarDays, ChevronRight, Loader2, Menu, TriangleAlert, X } from 'lucide-react';
import { useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { ClipboardList, FileBarChart, Clock3, FolderOpen, Gauge, GitBranch, LayoutDashboard, ListTodo, PanelLeftClose, Settings2 } from 'lucide-react';
import {Avatar} from './Avatar';
import { useDialogFocus } from './useDialogFocus';
import type { Freshness, Route, Session, Workspace } from './types';

export const ROLE:Record<string,string>={pm:'專案經理',manager:'系統管理員',member:'組員'};
const NAV=[{view:'dashboard',label:'今日工作台',icon:LayoutDashboard},{view:'reports',label:'PM 週報',icon:FileBarChart},{view:'projects',label:'案件總覽',icon:FolderOpen},{view:'quotes',label:'報價總表',icon:ClipboardList},{view:'overview',label:'管理總覽',icon:Gauge},{view:'people',label:'人員與資源出勤',icon:CalendarDays},{view:'approvals',label:'變更與展延',icon:GitBranch},{view:'routines',label:'追蹤與檢討',icon:Clock3},{view:'admin',label:'管理設定',icon:Settings2}] as const;
const NAV_GROUPS=[{label:'工作',views:['dashboard']},{label:'專案',views:['projects','quotes','people']},{label:'管理',views:['reports','overview','approvals','routines','admin']}] as const;
const P2_DETAIL_LABEL:Record<string,string>={confirmation:'案件與確認單詳情',contract:'合約明細詳情',workitem:'工作項詳情'};
export {Avatar} from './Avatar';

type CallbackError={title:string;description:string;next:string};
export type AppShellProps={s:Session;w?:Workspace;route:Route;error:string;setError:(m:string)=>void;callbackError?:CallbackError;mobile:boolean;setMobile:(open:boolean)=>void;sessionOpen:boolean;setSessionOpen:(open:boolean)=>void;overdue:number;activeNav:string;asOfLabel:string;busy:boolean;mutationBusy:boolean;dirtyDraft:boolean;ready:boolean;go:(r:Route)=>void;refresh:()=>Promise<void>;guardedRefresh:()=>Promise<boolean>;reread:()=>void;onFreshness:(next:Freshness,snapshot?:Freshness)=>void;children:ReactNode;overlays?:ReactNode};

export function AppShell({s,w,route,error,setError,callbackError,mobile,setMobile,sessionOpen,setSessionOpen,overdue,activeNav,ready,go,refresh,children,overlays}:AppShellProps){
 const [compact,setCompact]=useState(false);
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
 const dispatchVisible=canReadDispatch(s);
 const visibleNav=NAV.filter(n=>(n.view!=='approvals'||s.features?.change_extension===true)&&(n.view!=='routines'||s.features?.routines===true)&&(n.view!=='reports'||s.user?.role==='pm'||s.user?.role==='manager'));
 const tabs=visibleNav.filter(n=>['dashboard','projects','work','approvals'].includes(n.view));
 return <div className={`app-shell ${compact?'sidebar-compact':''}`}>
  <div className="compact-brand glass--bar"><a href="#view=dashboard" aria-label="詠翔工作台首頁"><span className="brand-mark"><i/><i/><i/><i/></span><strong>詠翔工作台</strong></a><button ref={openSidebarRef} className="sidebar-toggle" aria-label="展開側邊導覽" aria-expanded={!compact} aria-controls="workspace-navigation" onClick={()=>toggleSidebar(false)}><Menu size={20}/></button></div>
  {mobile&&<div className="sidebar-scrim" onClick={()=>setMobile(false)}/>}
  <aside ref={navigationRef} id="workspace-navigation" role={mobile?'dialog':undefined} aria-modal={mobile?true:undefined} aria-label="工作區導覽" tabIndex={-1} className={`sidebar glass--bar ${mobile?'open':''}`}><button className="icon-button sidebar-close" aria-label="關閉導覽" onClick={()=>setMobile(false)}><X size={20}/></button><button ref={collapseSidebarRef} className="sidebar-toggle sidebar-collapse" aria-label="收合側邊導覽" aria-expanded={!compact} aria-controls="workspace-navigation" onClick={()=>toggleSidebar(true)}><PanelLeftClose size={18}/></button><div className="sidebar-scroll"><a className="brand" href="#view=dashboard" aria-label="詠翔工作台首頁"><span className="brand-mark"><i/><i/><i/><i/></span><span>詠翔工作台<span className="brand-en">YONG XIANG</span></span></a><div className="workspace-caption">測量工程 · 專案協作</div><nav className="workspace-nav-groups" aria-label="主要導覽">{NAV_GROUPS.map(group=><div className="workspace-nav-group" key={group.label}><div className="nav-label">{group.label}</div>{visibleNav.filter(item=>group.views.some(view=>view===item.view)).map(item=><button key={item.view} aria-current={activeNav===item.view?'page':undefined} className={`nav-item ${activeNav===item.view?'active':''}`} onClick={()=>go({view:item.view})}><item.icon size={18}/><span>{item.label}</span></button>)}</div>)}</nav><div className="sidebar-projects"><div className="nav-label">最近案件</div>{w?.projects.filter(p=>p.case_type!=='intake').slice(0,3).map(p=><button key={p.id} className={`recent-project ${route.project===p.id?'selected':''}`} onClick={()=>go({view:'project',project:p.id})}><span className="project-dot"/><span>{p.code}<small>{p.name}</small></span></button>)}</div></div></aside>
  <div className="main-shell"><header className="topbar glass--bar"><div className="breadcrumbs"><button className="icon-button mobile-menu" onClick={()=>setMobile(!mobile)} aria-label="開啟導覽" aria-expanded={mobile} aria-controls="workspace-navigation"><Menu size={20}/></button><span>工作空間</span><ChevronRight size={13}/><strong>{route.view==='project'?'案件詳情':P2_DETAIL_LABEL[route.view]||NAV.find(n=>n.view===route.view)?.label||'資料來源'}</strong></div><div className="topbar-right">{s.environment&&s.environment!=='production'&&<span className="demo-tag">{s.environment==='test'?'測試':'示範'}</span>}<button className="user-button" aria-label="目前登入身份" aria-expanded={sessionOpen} onClick={()=>setSessionOpen(!sessionOpen)}><Avatar user={s.user||undefined}/><span>{s.user?.name}</span></button></div></header>
  {callbackError&&<div className="error-banner auth-callback-banner" role="alert"><TriangleAlert size={18}/><span><strong>{callbackError.title}</strong><br/>{callbackError.description} {callbackError.next}</span><a className="text-button" href="/api/auth/lark/login">重新登入</a></div>}
  {error&&<div className="error-banner workspace-error" role="alert"><TriangleAlert size={18}/><span>{error}</span><button className="text-button" onClick={()=>{setError('');void refresh()}}>重新載入</button><button className="icon-button" onClick={()=>setError('')} aria-label="關閉錯誤訊息"><X size={16}/></button></div>}
  {!ready?<div className="loading-page"><span className="brand-mark"><i/><i/><i/><i/></span><h2>{error?'暫時無法連接工作區':'準備你的工作台'}</h2><p>{error?'請確認服務已啟動，或使用下方登入。':'正在讀取案件、排程與參與人員'}</p>{!error?<Loader2 className="spin"/>:<><button className="button" onClick={()=>void refresh()}>重新連接</button>{s?.auth_configured&&<a className="button primary" href="/api/auth/lark/login">使用 Lark 登入</a>}</>}</div>:<main key={route.view} className={`workspace ${route.view==='project'?'project-workspace':''}`}>
   {children}
  </main>}
  </div>
  <nav className="mobile-tabs glass--bar" aria-label="快速導覽">{tabs.map(item=><button key={item.view} aria-current={activeNav===item.view?'page':undefined} onClick={()=>go({view:item.view})}><item.icon size={20}/><span>{item.label}</span></button>)}<button aria-label="更多導覽" aria-expanded={mobile} aria-controls="workspace-navigation" onClick={()=>setMobile(true)}><Menu size={20}/><span>更多</span></button></nav>
  {overlays}
 </div>
}
