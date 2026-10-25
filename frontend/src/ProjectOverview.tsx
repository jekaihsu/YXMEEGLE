import type {ReactNode} from 'react';
import type {useSopTasks} from './useSopTasks';
import {CaseSopStart} from './CaseSopStart';
import {withLocalChecklist} from './nodeWorkbenchModel';
import {CalendarDays, Clock3, FileText, Flag} from 'lucide-react';
import {FlowDiagram} from './FlowDiagram';
import {buildFlowModel} from './flowModel';
import {needsAttention,selectNextAction,type OverviewTarget} from './projectOverviewModel';
import {overviewDocuments,overviewKpis,overviewMissingSummary,overviewTasks,overviewTodos} from './overviewDashboardModel';
import {workItemRows} from './workItemsModel';
import {executionAllowed,executionReason} from './ProjectExecution';
import {useProjectProgress} from './useProjectProgress';
import type {useNodeAssignments} from './useNodeAssignments';
import {Button} from './design';
import {Avatar} from './AppShell';
import {eventMessage,isProjectLead,nameOf,stamp,type Ctx} from './appCommon';
import type {Project} from './types';
import './ProjectFlow.css';
import './ProjectOverview.css';

const text=(value:unknown,fallback:string)=>typeof value==='string' && value.trim() ? value : fallback;
const shortDate=(value:unknown)=>typeof value==='string' && /^\d{4}-\d{2}-\d{2}/.test(value) ? value.slice(0,10) : '未設定';
export function ProjectOverview({c,p,assignments,selectedKey,sopTasks,workbench}:{c:Ctx;p:Project;assignments:ReturnType<typeof useNodeAssignments>;selectedKey:string;sopTasks:ReturnType<typeof useSopTasks>;workbench:ReactNode}){
 const read=useProjectProgress(p.id),list='data' in assignments.state ? assignments.state.data : undefined;
 const data=read.state.kind==='ready' && read.state.data.project_id===p.id ? read.state.data : undefined;
 const flow=buildFlowModel({project:assignments.state.kind==='disabled' ? p : {...p,nodes:[]},assignments:list,progress:data,today:c.w.as_of,users:c.w.users});
 const model={...flow,nodes:withLocalChecklist(flow.nodes,'data' in sopTasks.state?sopTasks.state.data:undefined,sopTasks.assignees)};
 const unavailable=assignments.state.kind==='loading' || assignments.state.kind==='error';
 const approval=c.s.features?.change_extension ? c.w.approvals.filter(a=>a.project_id===p.id && a.status==='pending' && p.nodes.some(n=>n.id===a.node_id && n.status==='paused')).sort((a,b)=>a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id))[0] : undefined;
 const action=selectNextAction({nodes:model.nodes,list,user:c.s.user,today:c.w.as_of,execution:{allowed:executionAllowed(p,c.w),reason:executionReason(p)},localLead:isProjectLead(c.s,p),assignmentsUnavailable:unavailable,blockingApproval:approval ? {id:approval.id,title:approval.title,node:approval.node_id,owner:p.supervisor_id ? nameOf(c.w,p.supervisor_id) : '案件主管'} : undefined});
 const field=data?.production.field,sourceStale=!!list?.stale || /stale|error|unavailable|failed/i.test(data?.sources.source_status || '') || c.w.freshness?.datasets.sources.status==='stale';
 const stale=sourceStale || !!data?.sources.reports_stale;
 const issues=needsAttention(model.nodes,field),kpis=overviewKpis({field,nodes:model.nodes,issues,available:!unavailable,stale,assignmentsStale:!!list?.stale});
 const todos=overviewTodos(action,issues,model.nodes),tasks=overviewTasks(model.nodes,!unavailable && !list?.stale);
 const rows=field ? workItemRows(field,stale || data?.sources.reports_status!=='ok').slice(0,5) : [];
 const events=c.w.events.filter(e=>e.project_id===p.id).slice().sort((a,b)=>b.created_at.localeCompare(a.created_at)).slice(0,4);
 const documents=Array.isArray(p.files) ? overviewDocuments(p.files,c.w.file_categories) : null;
 const destination=(target:OverviewTarget)=>({...target,...(target.tab==='flow'?{tab:'overview'}:{})});
 const go=(target:OverviewTarget)=>c.go({view:'project',project:p.id,...destination(target)});
 const href=(target:OverviewTarget)=>`#${new URLSearchParams({view:'project',project:p.id,...destination(target)})}`;
 const current=list?.summary.current_node || model.nodes.find(n=>n.state==='進行中' || n.state==='待審核')?.key || model.nodes[0].key;
 const fieldNode=model.nodes.find(node=>node.key==='field'),localField=p.nodes.find(node=>node.key==='field');
 const pm=c.w.users.find(user=>user.id===p.pm_id),supervisor=c.w.users.find(user=>user.id===localField?.supervisor_id);
 const sync=data?.sources.source_synced_at || c.w.source_status.last_sync;
 const status=text(p.source_status,'來源狀態待核對');
 return <div className="project-overview">
  <div className="po-main">
   {!workbench && <CaseSopStart projectId={p.id} sop={sopTasks}/>}
   <FlowDiagram compact nodes={model.nodes} overall={model.overall} selected={c.route.node?selectedKey:current} loading={assignments.state.kind==='loading'} onSelect={node=>go({tab:'overview',node})}/>
   {workbench}
    <section className="po-card po-todos" aria-labelledby="po-todo-title"><header className="po-card-heading"><h2 id="po-todo-title">待辦事項</h2><Button variant="plain" onClick={()=>go({tab:'flow',section:'all-tasks'})}>查看全部任務{tasks.complete ? ` (${tasks.rows.length})` : ''} →</Button></header>
     <ul>{todos.slice(0,3).map(row=><li key={row.id} className={row.primary ? 'po-todo-primary' : undefined}><span className="po-todo-circle" aria-hidden="true"/><div className="po-todo-content"><a href={href(row.target)} onClick={event=>{event.preventDefault();go(row.target)}}>{row.title}</a>{row.primary && <p title={row.reason}>{action.kind==='blocking' && action.title.includes('節點的負責人') ? '執行與交接窗口需要核對。' : row.reason}</p>}<div className="po-todo-meta"><span className="po-person"><Avatar small user={c.w.users.find(user=>user.id===row.ownerId || user.name===row.owner)}/>{row.owner}</span><time>{row.deadline ? shortDate(row.deadline).slice(5).replace('-','/') : '未排定'}</time></div></div>{row.primary && <Button variant="primary" onClick={()=>go(row.target)}>{action.button}</Button>}</li>)}</ul>
    </section>
   {assignments.state.kind==='error' && <p className="po-source-state" role="alert">節點暫不可用<Button onClick={()=>void assignments.reload()}>重試</Button></p>}
   {sourceStale && !list?.stale && <p className="po-source-state">工程來源為上次成功資料，待更新核對。</p>}
   {list?.stale && <p className="po-source-state">節點來源為上次成功資料，待更新核對。</p>}
   {!!kpis.length && <section className="po-kpis po-card" aria-label="案件重點指標">{kpis.map(cell=><a key={cell.id} className={`po-kpi${cell.compact ? ' po-kpi-text' : ''}${cell.id==='latest_report' ? ' po-kpi-date' : ''}${cell.alert ? ' po-kpi-alert' : ''}`} href={href(cell.target)} onClick={event=>{event.preventDefault();go(cell.target)}}><span>{cell.label}</span><strong>{cell.value}</strong><small>{cell.detail}</small></a>)}</section>}
   <p className="po-source-state">{overviewMissingSummary(kpis)}</p>
   <section className={rows.length ? "po-card po-items" : "po-items po-items-empty"} aria-label="工項進度">
    {rows.length>0 && <header className="po-card-heading"><h2 id="po-items-title">工項進度</h2><Button variant="plain" onClick={()=>go({tab:'items',node:'field'})}>查看全部工項 →</Button></header>}
    {rows.length ? <table className="po-items-table"><thead><tr>{['工項編號','工項名稱','計畫量','實際完成','進度','最近日報','狀態'].map(label=><th key={label} scope="col">{label}</th>)}</tr></thead><tbody>{rows.map(row=><tr key={row.id} data-item-id={row.id}><td data-label="工項編號">{row.code}</td><td data-label="工項名稱"><a href={href({tab:'items',node:'field',section:`item:${row.id}`})} onClick={event=>{event.preventDefault();go({tab:'items',node:'field',section:`item:${row.id}`})}}>{row.name}</a></td><td data-label="計畫量">{row.planned==='尚未提供' ? '未知' : row.planned}</td><td data-label="實際完成">{row.actualDisplay}</td><td data-label="進度">{row.progressDisplay}</td><td data-label="最近日報">{row.source.linked_reports?.map(r=>r.date || '').filter(Boolean).sort().at(-1) || '未知'}</td><td data-label="狀態"><span className="po-pill">{row.basis==='ambiguous' || row.basis==='unlinked' ? '待核對' : row.source.status==='done' ? '來源已完成' : row.source.status==='partial' ? '來源部分完成' : '未知'}</span></td></tr>)}</tbody></table> : <p className="po-empty">{read.state.kind==='loading' ? '工項資料載入中' : read.state.kind==='error' ? '工程證據暫不可用' : '尚未連結外業工項'} · <a href={href({tab:'items',node:'field'})} onClick={event=>{event.preventDefault();go({tab:'items',node:'field'})}}>查看工項 →</a></p>}
    {read.state.kind==='error' && <p className="po-source-state">{read.state.message}<Button variant="plain" onClick={read.retry}>重試工程證據</Button></p>}
    {field?.items_truncated && <p className="po-source-state">來源清單未完整，僅預覽已載入的前 {rows.length} 筆工項。</p>}
    {data?.sources.reports_status==='restricted' && <p className="po-source-state">週報來源權限不足，日報與工項狀態分開核對。</p>}
    {data?.sources.reports_stale && <p className="po-source-state">回報為上次成功資料，待更新。</p>}
   </section>
    <section className="po-card po-activity" aria-labelledby="po-activity-title"><header className="po-card-heading"><h2 id="po-activity-title">近期活動</h2><Button variant="plain" onClick={()=>go({tab:'data',section:'activity'})}>查看全部 →</Button></header>{events.length ? <ol>{events.map(event=><li key={event.id}><time dateTime={event.created_at}>{shortDate(event.created_at).slice(5).replace('-','/')}</time><a href={href({tab:'data',section:'activity'})} onClick={e=>{e.preventDefault();go({tab:'data',section:'activity'})}}>{eventMessage(event)}</a>{event.actor_id && <span>{nameOf(c.w,event.actor_id)}</span>}</li>)}</ol> : <p className="po-empty">尚無可顯示的案件活動</p>}</section>
   {!!documents?.length && <section className="po-card po-documents" aria-labelledby="po-documents-title"><h2 id="po-documents-title">相關文件</h2><div>{documents.map(group=><a key={group.id} href={href({tab:'files'})} onClick={event=>{event.preventDefault();go({tab:'files'})}}><FileText size={18}/>{group.label} {group.count}</a>)}</div><Button variant="plain" onClick={()=>go({tab:'files'})}>查看全部 →</Button></section>}
  </div>
  <aside className="po-sidebar" aria-label="案件摘要資料">
   <section className="po-card"><h2>案件資訊</h2><dl><div><dt>案件狀態</dt><dd><span className={`po-pill${status.includes('待核對') ? ' po-pill-amber' : ''}`}>{status}</span></dd></div>{text(p.project_type,'') && <div><dt>案件類型</dt><dd>{p.project_type}</dd></div>}{['demo','lark','local'].includes(p.source_kind) && <div><dt>來源</dt><dd>{p.source_kind==='demo' ? '獨立示範資料' : p.source_kind==='lark' ? '飛書' : '工作台'}</dd></div>}{p.created_at && <div><dt>建立時間</dt><dd>{shortDate(p.created_at)}</dd></div>}{sync && <div><dt>最後同步</dt><dd><time dateTime={sync} title={stamp(sync)}>{stamp(sync).replaceAll('/','-').slice(0,16)}</time></dd></div>}</dl></section>
   {(p.planned_start_date || p.planned_end_date || p.original_due_date) && <section className="po-card po-dates"><h2>關鍵日期</h2><dl>{p.planned_start_date && <div><dt><Flag size={17}/>預計開工</dt><dd>{shortDate(p.planned_start_date)}</dd></div>}{p.planned_end_date && <div><dt><CalendarDays size={17}/>預計完工</dt><dd>{shortDate(p.planned_end_date)}</dd></div>}{p.original_due_date && <div><dt><Clock3 size={17}/>合約期限</dt><dd>{shortDate(p.original_due_date)}</dd></div>}</dl></section>}
   <section className="po-card po-team"><h2>負責人與團隊</h2><dl><div><dt>PM</dt><dd className="po-person"><Avatar small user={pm}/>{p.pm_id ? nameOf(c.w,p.pm_id) : p.sop_only?'未提供':'未指派'}</dd></div><div><dt>組別主管</dt><dd className="po-person"><Avatar small user={supervisor}/>{supervisor?.name || '未指派'}</dd></div>{!!fieldNode?.departments.length && <div><dt>外業組別</dt><dd>{fieldNode.departments.join('、')}</dd></div>}{fieldNode?.assignment?.assigned_by?.name && <div><dt>指派主管</dt><dd>{fieldNode.assignment.assigned_by.name}</dd></div>}</dl></section>
  </aside>
 </div>;
}
