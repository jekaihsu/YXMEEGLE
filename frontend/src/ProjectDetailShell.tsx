import {ChevronLeft,Link2,MoreHorizontal,Users} from 'lucide-react';
import {PROJECT_TABS} from './projectRoutes';
import {ProjectExecutionNotice} from './ProjectExecution';
import {date,nameOf,type Ctx} from './appCommon';
import {Button} from './design';
import type {Project} from './types';
import './ProjectDetailShell.css';
export function ProjectDetailShell({c,p,tab,onPeople,onPrefetch,onCancelPrefetch}:{c:Ctx;p:Project;tab:string;onPeople:()=>void;onPrefetch:()=>void;onCancelPrefetch:()=>void}){
 const share=async()=>{try{await navigator.clipboard.writeText(location.href);c.notify('已複製此頁直達連結')}catch{c.notify('請複製瀏覽器網址列中的直達連結')}};
 return <div className="project-detail-shell"><header className="pds-header"><div className="pds-heading"><div className="pds-breadcrumb"><Button variant="plain" onClick={()=>c.go({view:'projects'})}><ChevronLeft size={15}/>案件總覽</Button><p className="pds-code">{p.code} <span>v{p.revision}</span></p></div><h1>{p.name}</h1><p className="pds-meta">{p.client || '業主尚未提供'} · PM {p.pm_id ? nameOf(c.w,p.pm_id) : '尚未指派'} · 期限 {p.due_date ? date(p.due_date) : '未排定'}</p></div><div className="pds-tools"><span className="pds-status">來源 · {p.source_status || (p.source_kind==='demo' ? '示範案件' : '待核對')}</span><span className="pds-status">{p.execution_system_label || (p.execution_system==='workbench' ? '本工作台執行' : p.execution_system==='meegle' ? 'Meegle 執行' : c.w.environment==='demo' ? '示範執行' : '歸屬待核定')}</span><button className="icon-button" aria-label="複製直達連結" onClick={()=>void share()}><Link2 size={17}/></button><details className="pds-more"><summary aria-label="更多案件操作"><MoreHorizontal size={20}/></summary><div><Button variant="plain" onClick={onPeople}><Users size={15}/>參與人員</Button><Button variant="plain" onClick={()=>c.go({view:'project',project:p.id,tab:'data',section:'basic'})}>基本資料與執行歸屬</Button></div></details></div></header>
 <nav className="pds-tabs" aria-label="案件頁面">{PROJECT_TABS.map(t=><button key={t.key} aria-current={tab===t.key ? 'page' : undefined} onMouseEnter={()=>{if(t.key==='flow')onPrefetch()}} onFocus={()=>{if(t.key==='flow')onPrefetch()}} onMouseLeave={onCancelPrefetch} onBlur={onCancelPrefetch} onClick={()=>c.go({view:'project',project:p.id,tab:t.key})}>{t.label}</button>)}</nav>
 </div>;
}
export function ProjectExecutionDetails({c,p}:{c:Ctx;p:Project}){return <details className="pds-execution"><summary>案件執行歸屬與核定</summary><ProjectExecutionNotice p={p} w={c.w} s={c.s} run={c.run} busy={c.busy}/></details>}
