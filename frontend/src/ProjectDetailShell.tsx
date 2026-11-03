import {caseProgressStatus,caseStatusLabel,sourceStatusPending} from './stageModel';
import {useDetailRefresh} from './detailRefresh';
import {time} from './DataFreshness';
import type {FlowNode} from './flowModel';
import {ProjectChatLauncher} from './assistant/ProjectChatLauncher';
import {DetailsMenu} from './design/DetailsMenu';
import {useEffect,useRef} from 'react';
import {ChevronLeft,Link2,MoreHorizontal} from 'lucide-react';
import {PROJECT_TABS} from './projectRoutes';
import {ProjectExecutionNotice} from './ProjectExecution';
import {date,nameOf,type Ctx} from './appCommon';
import {Button} from './design';
import {STATUS_LEVEL_NOTE} from './stageModel';
import type {Project} from './types';
import './ProjectDetailShell.css';
export function ProjectDetailShell({c,p,tab,onPrefetch,onCancelPrefetch,current,snapshotTime,snapshotNote}:{c:Ctx;p:Project;tab:string;onPrefetch:()=>void;onCancelPrefetch:()=>void;current?:FlowNode;snapshotTime?:string|null;snapshotNote?:string}){
 const refresh=useDetailRefresh(async()=>{},false);
 const tabs=useRef<HTMLElement>(null);
 useEffect(()=>{const nav=tabs.current,active=nav?.querySelector<HTMLButtonElement>('[aria-current=page]');if(nav&&active)nav.scrollLeft=Math.max(0,active.offsetLeft-(nav.clientWidth-active.offsetWidth)/2)},[tab]);
 const share=async()=>{try{await navigator.clipboard.writeText(location.href);c.notify('已複製此頁直達連結')}catch{c.notify('請複製瀏覽器網址列中的直達連結')}};
 return <div className="project-detail-shell">{!['overview','flow'].includes(tab)&&<ProjectChatLauncher projectId={p.id} projectCode={p.code} projectName={p.name}/>}<header className="pds-header"><div className="pds-heading"><Button variant="plain" className="pds-back" onClick={()=>c.go({view:'projects'})}><ChevronLeft size={15}/>案件總覽</Button><div className="pds-breadcrumb"><p className="pds-code">{p.code}</p>{(p.case_type==='formal'||p.case_type==='intake'||p.source_kind==='demo')&&<span className="pds-case-type">{p.case_type==='formal' ? '正式案件' : p.case_type==='intake' ? '接洽案件' : p.source_kind==='demo' ? '示範案件' : ''}</span>}</div><h1>{p.name}</h1><p className="pds-meta">{p.client || '業主尚未提供'} · PM：{p.pm_id ? nameOf(c.w,p.pm_id) : '尚未指派'}<span> · 期限 {p.due_date ? date(p.due_date) : '未排定'}</span></p><div className="pds-status-line" title={STATUS_LEVEL_NOTE}><span className="pds-status-chip">{caseProgressStatus(p)==='paused'?caseStatusLabel(p):current?`${current.label} · ${current.state}`:caseStatusLabel(p)}</span>{(p.source_status||sourceStatusPending(p))&&<span className="pds-source-status">來源：{p.source_status||'狀態待確認'}{sourceStatusPending(p)?' · 狀態待核對':''}</span>}</div><div className="pds-data-time"><span>資料時間 {(snapshotTime===undefined?c.w.as_of:snapshotTime)?time((snapshotTime===undefined?c.w.as_of:snapshotTime)!):'來源未提供'}{snapshotNote}</span><Button variant="plain" onClick={()=>void (refresh?refresh(false):c.refresh())}>重新讀取</Button></div></div><div className="pds-tools"><DetailsMenu className="pds-more" label={<MoreHorizontal size={20}/>} ariaLabel="更多案件操作"><div><Button variant="plain" onClick={()=>void share()}><Link2 size={15}/>複製直達連結</Button></div></DetailsMenu></div></header>
 <div className="pds-tabs-wrap"><nav ref={tabs} onKeyDown={event=>{const buttons=[...event.currentTarget.querySelectorAll<HTMLButtonElement>('button')],index=buttons.indexOf(document.activeElement as HTMLButtonElement);const next=event.key==='Home'?0:event.key==='End'?buttons.length-1:event.key==='ArrowRight'?(index+1)%buttons.length:event.key==='ArrowLeft'?(index+buttons.length-1)%buttons.length:-1;if(next>=0){event.preventDefault();buttons[next]?.focus()}}} className="pds-tabs" aria-label="案件頁面">{PROJECT_TABS.map(t=><button key={t.key} aria-current={tab===t.key ? 'page' : undefined} onMouseEnter={()=>{if(t.key==='flow')onPrefetch()}} onFocus={()=>{if(t.key==='flow')onPrefetch()}} onMouseLeave={onCancelPrefetch} onBlur={onCancelPrefetch} onClick={()=>c.go({view:'project',project:p.id,tab:t.key})}>{t.label}</button>)}</nav></div>
 </div>;
}
export function ProjectExecutionDetails({c,p}:{c:Ctx;p:Project}){return <details className="pds-execution"><summary>案件執行歸屬與核定</summary><ProjectExecutionNotice p={p} w={c.w} s={c.s} run={c.run} busy={c.busy}/></details>}
