import type {ReactNode} from 'react';
import type {useSopTasks} from './useSopTasks';
import {withLocalChecklist,localCase} from './nodeWorkbenchModel';
import {CalendarDays, Clock3, Flag} from 'lucide-react';
import {buildFlowModel,flowTaskTarget} from './flowModel';
import {type OverviewTarget} from './projectOverviewModel';
import {executionAllowed,executionReason} from './ProjectExecution';
import {useProjectProgress} from './useProjectProgress';
import type {useNodeAssignments} from './useNodeAssignments';
import {useFlowDetails} from './useFlowDetails';
import {Avatar} from './AppShell';
import {CaseSummary} from './CaseSummary';
import {assignRequests} from './assignRequests';
import {resolveStages,stageNextStep,sharedBlockerReasons,taskView,type NextStep} from './stageModel';
import {isProjectLead,nameOf,type Ctx} from './appCommon';
import type {Project} from './types';
import './ProjectFlow.css';
import './ProjectOverview.css';

const shortDate=(value:unknown)=>typeof value==='string' && /^\d{4}-\d{2}-\d{2}/.test(value) ? value.slice(0,10) : '未設定';
export function ProjectOverview({c,p,assignments,selectedKey,sopTasks,workbench}:{c:Ctx;p:Project;assignments:ReturnType<typeof useNodeAssignments>;selectedKey:string;sopTasks:ReturnType<typeof useSopTasks>;workbench:()=>ReactNode}){
 const read=useProjectProgress(p.id),list='data' in assignments.state ? assignments.state.data : undefined;
 const details=useFlowDetails(p.id,list,selectedKey,true,assignments.revision);
 const merged=list?{...list,node_details:{...list.node_details,...Object.fromEntries(Object.entries(details.details).map(([key,d])=>[key,{tasks:d.tasks,assignable_people:d.assignable_people}]))}}:undefined;
 const data=read.state.kind==='ready' && read.state.data.project_id===p.id ? read.state.data : undefined;
 const flow=buildFlowModel({project:assignments.state.kind==='disabled' ? p : {...p,nodes:[]},assignments:merged,progress:data,today:c.w.as_of,users:c.w.users});
 const model={...flow,nodes:withLocalChecklist(flow.nodes,'data' in sopTasks.state?sopTasks.state.data:undefined,sopTasks.assignees)};
 const unavailable=assignments.state.kind==='loading' || assignments.state.kind==='error';
 const destination=(target:OverviewTarget)=>({...target,...(target.tab==='flow'?{tab:'overview'}:{})});
 const go=(target:OverviewTarget)=>c.go({view:'project',project:p.id,...destination(target)});
 const stage=resolveStages({nodes:model.nodes,list,requested:c.route.node?selectedKey:undefined});
 const execution={allowed:executionAllowed(p,c.w),reason:executionReason(p)};
 const fresh=!!list&&list.writes_enabled&&!list.stale&&assignments.state.kind==='ready' || !list&&!unavailable;
 const step=stageNextStep({caseStatus:p.status,ctx:stage,list,today:c.w.as_of,fresh,block:p.status==='paused'?{kind:'paused',reason:`案件暫停中，等待${p.pm_id?nameOf(c.w,p.pm_id):'PM'}處理。`}:execution.allowed?undefined:{kind:p.execution_system==='meegle'?'meegle':!p.execution_system||p.execution_system==='pending'?'ownership':'execution',reason:execution.reason}});
 const current=stage.nodes.find(n=>n.key===stage.currentIds[0]);
 const shared=current?sharedBlockerReasons(current.taskRows.map(row=>taskView(row,current,c.w.as_of))):[];
 const emptyBlocked=stage.currentSelected&&!localCase(p)&&current&&!current.taskRows.length&&!execution.allowed&&isProjectLead(c.s,p);
 const summaryStep=emptyBlocked&&'reasons' in step?{...step,reasons:step.reasons.filter(reason=>reason!==execution.reason)}:stage.currentSelected&&step.kind==='view'&&shared.includes(step.reason)?{...step,reason:''}:step;
 const executors=[...new Map(model.nodes.filter(n=>stage.currentIds.includes(n.key)||!!n.legacy?.started_at||!!n.assignment?.started_at||['進行中','待審核','已完成'].includes(n.state)||n.taskRows.some(t=>['in_progress','completed','進行中','已完成'].includes(t.status))).flatMap(n=>n.taskRows).filter(t=>t.ownerId&&t.ownerId!==p.pm_id&&t.ownerId!==p.nodes.find(n=>n.key==='field')?.supervisor_id).map(t=>[t.ownerId,t.owner])).values()];
 const openStep=(next:NextStep)=>{if(next.kind==='action'&&(!next.taskId||next.needs==='approve')){c.go({view:'project',project:p.id,tab:'flow',node:next.nodeKey});return}const sop=(next.kind==='action'||next.kind==='view')&&model.nodes.flatMap(n=>n.taskRows).find(r=>r.id===next.taskId&&r.source==='SOP 任務');if(sop){go({...flowTaskTarget(sop),tab:'overview'});return}if(next.kind==='action'&&next.needs==='assign'&&next.taskId){assignRequests.request(next.nodeKey,next.taskId);go({tab:'overview',node:next.nodeKey});return}if(next.kind==='action'||next.kind==='view')go({tab:'overview',node:next.nodeKey,task:next.taskId})};
 const localField=p.nodes.find(node=>node.key==='field');
 const pm=c.w.users.find(user=>user.id===p.pm_id),supervisor=c.w.users.find(user=>user.id===localField?.supervisor_id);
 return <div className="project-overview">
  <div className="po-main">
   <CaseSummary onRetry={()=>void assignments.reload()} ctx={stage} step={summaryStep} loading={assignments.state.kind==='loading'} error={assignments.state.kind==='error'?assignments.state.message:''} onStep={openStep} onCurrent={()=>go({tab:'overview',node:stage.currentIds[0]})}/>
   {workbench()}
  </div>
  <aside className="po-sidebar" aria-label="案件摘要資料">
   {(new Set([p.planned_start_date,p.planned_end_date,p.original_due_date].filter(Boolean).map(v=>String(v).slice(0,10))).size>=2) && <section className="po-card po-dates"><h2>關鍵日期</h2><dl>{p.planned_start_date && <div><dt><Flag size={17}/>預計開工</dt><dd>{shortDate(p.planned_start_date)}</dd></div>}{p.planned_end_date && <div><dt><CalendarDays size={17}/>預計完工</dt><dd>{shortDate(p.planned_end_date)}</dd></div>}{p.original_due_date && <div><dt><Clock3 size={17}/>合約期限</dt><dd>{shortDate(p.original_due_date)}</dd></div>}</dl></section>}
   <section className="po-card po-team"><h2>負責人與團隊</h2><dl><div><dt>PM</dt><dd className="po-person"><Avatar small user={pm}/>{p.pm_id ? nameOf(c.w,p.pm_id) : '未指派'}</dd></div><div><dt>組別主管</dt><dd className="po-person"><Avatar small user={supervisor}/>{supervisor?.name || '未指派'}</dd></div>{executors.length>0&&<div><dt>執行人</dt><dd className="po-executors">{executors.map(name=><span key={name}>{name}</span>)}</dd></div>}</dl></section>

  </aside>
 </div>;
}
